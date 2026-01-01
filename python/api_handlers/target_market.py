import json
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify


def post_target_market_session_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:post_target_market_session (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore
    from target_market_draft import create_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import target market draft helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
    client_id = str(consult.get("client_id") or "").strip()
    if not client_id:
      raise RuntimeError("Consult draft missing client_id.")
    create_draft(conn, draft_id=str(draft_id).strip(), client_id=client_id)
    return jsonify({"status": "ok", "draft_id": str(draft_id).strip(), "client_id": client_id})
  finally:
    try:
      conn.close()
    except Exception:
      pass


def get_target_market_draft_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:get_target_market_draft (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  draft_id = request.args.get("draft_id")
  if not draft_id:
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from target_market_draft import get_draft as get_tm_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import target market draft helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    draft = get_tm_draft(conn, draft_id=str(draft_id).strip())
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
        "draft_status": draft.get("status"),
        "messages_json": draft.get("messages_json"),
        "target_market_json": draft.get("target_market_json"),
      }
    )
  except Exception as exc:
    return (
      jsonify({"error": "not_found", "detail": str(exc)}),
      404,
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def post_target_market_consult_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:post_target_market_consult (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  raw_message = payload.get("message")
  message = raw_message
  edit_finalize = bool(payload.get("edit_finalize", False))
  reopen = bool(payload.get("reopen", False))
  allow_on_completed = reopen or edit_finalize
  reopen_status = reopen and not edit_finalize
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  starting = message is None or not str(message).strip()
  if starting:
    message = "Start the target market intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions)."

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore
    from target_market_draft import (  # type: ignore
      append_messages,
      create_draft,
      get_draft as get_tm_draft,
      reopen_draft,
    )
    from target_market_consultant import (  # type: ignore
      target_market_chat_turn,
      target_market_finalize,
    )
    from intent_router import route_intent  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import target market consult helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  def _fetch_mapping_rows(conn) -> List[Dict[str, Any]]:
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        "SELECT acs_code, description, segment, min_value, max_value FROM target_market_mapping"
      )
      rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass

    def _parse_nullable_float(value: Any) -> Any:
      if value is None or value == "":
        return None
      try:
        return float(value)
      except Exception:
        return None

    mapping_rows: List[Dict[str, Any]] = []
    for r in rows:
      if not isinstance(r, dict):
        continue
      mapping_rows.append(
        {
          "acs_code": str(r.get("acs_code") or "").strip(),
          "description": str(r.get("description") or "").strip(),
          "segment": str(r.get("segment") or "").strip(),
          "min_value": _parse_nullable_float(r.get("min_value")),
          "max_value": _parse_nullable_float(r.get("max_value")),
        }
      )

    allowed_segments = {
      "Gender & Age",
      "Income",
      "Education",
      "Household Structure",
      "Housing Economics",
      "Employment",
    }

    cleaned: List[Dict[str, Any]] = []
    for r in mapping_rows:
      if not r["acs_code"] or not r["segment"]:
        continue
      if r["segment"] not in allowed_segments:
        continue
      # Ignore "Total households" rows for household structure selection.
      if r["segment"] == "Household Structure":
        desc_norm = " ".join(str(r["description"]).split()).strip().lower()
        if desc_norm == "total households":
          continue
      cleaned.append(r)
    if not cleaned:
      raise RuntimeError("target_market_mapping table is empty; load it before running the target market consult.")
    return cleaned

  def _validate_final(final_obj: Dict[str, Any], mapping_rows: List[Dict[str, Any]], consumer_type: str) -> None:
    if not str(final_obj.get("target_market_summary") or "").strip():
      raise RuntimeError("Final target market JSON missing target_market_summary.")

    conf = final_obj.get("confidence")
    try:
      conf_val = float(conf)
    except Exception as exc:
      raise RuntimeError("Final target market JSON missing valid confidence.") from exc
    if conf_val <= 0 or conf_val > 1:
      raise RuntimeError("confidence must be between 0 and 1.")

    if consumer_type in ("consumer", "mixed"):
      mapping_by_code = {str(r.get("acs_code") or ""): str(r.get("segment") or "") for r in mapping_rows}

      gender_age_intent = final_obj.get("gender_age_intent")
      if not isinstance(gender_age_intent, list) or len(gender_age_intent) == 0:
        raise RuntimeError("Final target market JSON missing gender_age_intent.")
      for item in gender_age_intent:
        if not isinstance(item, dict):
          raise RuntimeError("gender_age_intent must be an array of objects.")
        gender_focus = str(item.get("gender_focus") or "").strip().lower()
        if gender_focus not in ("female", "male", "all"):
          raise RuntimeError("gender_focus must be one of: female, male, all.")
        try:
          age_min = float(item.get("age_min"))
          age_max = float(item.get("age_max"))
        except Exception as exc:
          raise RuntimeError("gender_age_intent age_min/age_max must be numbers.") from exc
        # Age ranges can legitimately start at 0 (e.g., "all ages" or child-focused ranges).
        if age_min < 0 or age_max < 0 or age_max < age_min:
          raise RuntimeError("gender_age_intent requires age_min <= age_max and both >= 0.")

      income_intent = final_obj.get("income_intent")
      if not isinstance(income_intent, list) or len(income_intent) == 0:
        raise RuntimeError("Final target market JSON missing income_intent.")
      for item in income_intent:
        if not isinstance(item, dict):
          raise RuntimeError("income_intent must be an array of objects.")
        try:
          inc_min = float(item.get("income_min"))
          inc_max = float(item.get("income_max"))
        except Exception as exc:
          raise RuntimeError("income_intent income_min/income_max must be numbers.") from exc
        # Income ranges can legitimately start at 0 (e.g., "all incomes" or very low-income brackets).
        if inc_min < 0 or inc_max < 0 or inc_max < inc_min:
          raise RuntimeError("income_intent requires income_min <= income_max and both >= 0.")

      selections = final_obj.get("selections")
      if not isinstance(selections, list):
        raise RuntimeError("Final target market JSON missing selections list.")

      allowed_segments = {
        "Education",
        "Household Structure",
        "Employment",
        "Housing Economics",
      }
      seen_segments: set[str] = set()
      for sel in selections:
        if not isinstance(sel, dict):
          continue
        seg = str(sel.get("segment") or "").strip()
        if not seg:
          continue
        if seg not in allowed_segments:
          raise RuntimeError(
            f"Segment {seg!r} is not allowed. Allowed segments: {', '.join(sorted(allowed_segments))}"
          )
        seen_segments.add(seg)
        codes = sel.get("acs_codes")
        if not isinstance(codes, list) or len(codes) == 0:
          raise RuntimeError(f"Segment {seg} must include at least one ACS code.")
        for code in codes:
          code_str = str(code).strip()
          if code_str not in mapping_by_code:
            raise RuntimeError(f"Unknown ACS code selected: {code_str}")
          if mapping_by_code[code_str] != seg:
            raise RuntimeError(
              f"ACS code {code_str} belongs to segment {mapping_by_code[code_str]!r}, not {seg!r}"
            )

      if "Education" not in seen_segments:
        raise RuntimeError("Missing required segment selection: Education")

    if consumer_type in ("b2b", "mixed"):
      size_allowed = {
        "1-4",
        "5-9",
        "10-19",
        "20-99",
        "100-499",
        "500-999",
        "1000-2499",
        "2500-4999",
        "5000-9999",
        "10000+",
      }
      age_allowed = {"0", "1", "2", "3", "4", "5", "6-10", "11-15", "16-20", "21-25", "26+"}

      industry_terms = final_obj.get("b2b_industry_terms")
      if not isinstance(industry_terms, list) or len(industry_terms) == 0:
        raise RuntimeError("Final target market JSON missing b2b_industry_terms.")
      for term in industry_terms:
        if not str(term).strip():
          raise RuntimeError("b2b_industry_terms must not contain blanks.")

      b2b_naics_6 = final_obj.get("b2b_naics_6")
      if b2b_naics_6 is not None:
        if not isinstance(b2b_naics_6, list):
          raise RuntimeError("b2b_naics_6 must be an array of 6-digit strings or null.")
        if len(b2b_naics_6) == 0:
          raise RuntimeError("b2b_naics_6 must not be an empty array.")
        if len(b2b_naics_6) > 20:
          raise RuntimeError("b2b_naics_6 must include at most 20 NAICS codes.")
        import re

        for code in b2b_naics_6:
          s = str(code).strip()
          if not re.fullmatch(r"\d{6}", s):
            raise RuntimeError(f"Invalid NAICS code in b2b_naics_6: {s!r}")

      size_bands = final_obj.get("b2b_size_bands")
      if not isinstance(size_bands, list) or len(size_bands) == 0:
        raise RuntimeError("Final target market JSON missing b2b_size_bands.")
      for band in size_bands:
        b = str(band).strip()
        if b not in size_allowed:
          raise RuntimeError(f"Invalid b2b_size_bands value: {b!r}")

      age_bands = final_obj.get("b2b_age_bands")
      if not isinstance(age_bands, list) or len(age_bands) == 0:
        raise RuntimeError("Final target market JSON missing b2b_age_bands.")
      for band in age_bands:
        b = str(band).strip()
        if b not in age_allowed:
          raise RuntimeError(f"Invalid b2b_age_bands value: {b!r}")

  def _derive_bucket_codes(
    *,
    mapping_rows: List[Dict[str, Any]],
    segment: str,
    range_min: float,
    range_max: float,
    gender_focus: Optional[str] = None,
  ) -> List[str]:
    import re

    # Collect all eligible buckets for the segment (and gender filter if applicable).
    rows: List[Tuple[float, float, str]] = []
    min_candidates: List[float] = []
    max_candidates: List[float] = []

    for r in mapping_rows:
      if str(r.get("segment") or "").strip() != segment:
        continue
      mn = r.get("min_value")
      mx = r.get("max_value")
      if mn is None or mx is None:
        continue
      try:
        mn_f = float(mn)
        mx_f = float(mx)
      except Exception:
        continue

      desc = str(r.get("description") or "")
      if gender_focus:
        dl = desc.lower()
        # Word-boundary match avoids "female" matching "male".
        is_female = bool(re.search(r"\bfemale\b", dl))
        is_male = bool(re.search(r"\bmale\b", dl))
        if gender_focus == "female" and not is_female:
          continue
        if gender_focus == "male" and not is_male:
          continue
        if gender_focus == "all" and not (is_female or is_male):
          continue

      min_candidates.append(mn_f)
      max_candidates.append(mx_f)
      rows.append((mn_f, mx_f, str(r.get("acs_code") or "").strip()))

    if not rows:
      return []

    # Anchor the requested range to the closest bucket boundaries using min_value/max_value.
    # For example, if a user says 19–58, choose min=18 (closest <=19) and max=59 (closest >=58),
    # then include every bucket overlapping that anchored range.
    lower_min_candidates = [v for v in min_candidates if v <= range_min]
    anchor_min = max(lower_min_candidates) if lower_min_candidates else min(min_candidates)

    upper_max_candidates = [v for v in max_candidates if v >= range_max]
    anchor_max = min(upper_max_candidates) if upper_max_candidates else max(max_candidates)

    rows = [t for t in rows if not (t[1] < anchor_min or t[0] > anchor_max)]
    rows.sort(key=lambda t: (t[0], t[1], t[2]))
    codes: List[str] = []
    for _, _, code in rows:
      if code and code not in codes:
        codes.append(code)
    return codes

  try:
    conn = get_mysql_connection()
    try:
      consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
      client_id = str(consult.get("client_id") or "").strip()
      from api_handlers.shared_context import build_shared_context

      shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
      operating_model = shared_context.get("operating_model") or {}

      consumer_type = str(operating_model.get("consumer_type") or "").strip().lower()
      if consumer_type not in ("consumer", "b2b", "mixed"):
        consumer_type = "consumer"

      # Ensure the target market draft row exists.
      try:
        tm_draft = get_tm_draft(conn, draft_id=str(draft_id).strip())
      except Exception:
        create_draft(conn, draft_id=str(draft_id).strip(), client_id=client_id)
        tm_draft = get_tm_draft(conn, draft_id=str(draft_id).strip())

      tm_status = str(tm_draft.get("status") or "").strip().lower()

      user_msg = {"role": "user", "content": str(message).strip()}

      # Completed consult: route ALL user messages through the GPT intent router.
      if tm_status == "completed":
        baseline_target_market: Dict[str, Any] = {}
        try:
          raw_existing = tm_draft.get("target_market_json")
          if isinstance(raw_existing, dict):
            baseline_target_market = raw_existing
          elif raw_existing:
            parsed_existing = json.loads(str(raw_existing))
            if isinstance(parsed_existing, dict):
              baseline_target_market = parsed_existing
        except Exception:
          baseline_target_market = {}

        history_for_router: List[Dict[str, str]] = []
        try:
          raw_messages = tm_draft.get("messages_json")
          if raw_messages:
            parsed = json.loads(str(raw_messages))
            if isinstance(parsed, list):
              history_for_router = [m for m in parsed if isinstance(m, dict)]
        except Exception:
          history_for_router = []

        if starting:
          summary = str(baseline_target_market.get("target_market_summary") or "").strip()
          assistant_message = (summary or "Target market intake complete.").strip()
          assistant_message = (
            f"{assistant_message}\n\nDoes this look right before we move on to People & Capability?"
          ).strip()
          try:
            import re

            assistant_message = re.sub(
              r"\b[A-Z]\d{5}_\d{3}E\b",
              "[ACS code redacted]",
              assistant_message,
            )
          except Exception:
            pass
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "done": True,
              "action": "await_confirmation",
              "assistant_message": assistant_message,
              "target_market_json": json.dumps(baseline_target_market, ensure_ascii=False)
              if baseline_target_market
              else None,
            }
          )

        routed = route_intent(
          consult_type="target_market",
          user_message=str(message).strip(),
          baseline_json=baseline_target_market,
          shared_context=shared_context,
          recent_messages=history_for_router[-30:] if history_for_router else [],
        )
        action = str(routed.get("action") or "").strip()
        assistant_message = str(routed.get("assistant_message") or "").strip()
        patch = routed.get("patch")

        updated_target_market = baseline_target_market
        if action == "edit_patch":
          if not isinstance(patch, dict):
            patch = {}
          updated_target_market = dict(baseline_target_market)
          updated_target_market.update(patch)

        # Guardrail: never expose raw ACS codes in the UI conversation.
        try:
          import re

          assistant_message = re.sub(
            r"\b[A-Z]\d{5}_\d{3}E\b",
            "[ACS code redacted]",
            assistant_message,
          )
        except Exception:
          pass

        assistant_msg = {"role": "assistant", "content": assistant_message}
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, assistant_msg],
          status="completed",
          target_market_json=updated_target_market if action == "edit_patch" else None,
          flat_fields=updated_target_market if action == "edit_patch" else None,
          completed=bool(action == "edit_patch"),
        )

        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "done": True,
            "action": action,
            "assistant_message": assistant_message,
            "target_market_json": json.dumps(updated_target_market, ensure_ascii=False)
            if updated_target_market
            else None,
          }
        )

      history: List[Dict[str, str]] = []
      try:
        raw_messages = tm_draft.get("messages_json")
        if raw_messages:
          parsed = json.loads(str(raw_messages))
          if isinstance(parsed, list):
            history = [m for m in parsed if isinstance(m, dict)]
      except Exception:
        history = []

      context = {
        "client_id": client_id,
        "shared_context": shared_context,
        "consumer_type": consumer_type,
        "business_name": payload.get("business_name"),
        "business_type": payload.get("business_type"),
        "address": payload.get("address"),
        "address_street": payload.get("address_street"),
        "address_city": payload.get("address_city"),
        "address_state": payload.get("address_state"),
        "address_zip": payload.get("address_zip"),
        "address_country": payload.get("address_country"),
        "business_description_summary": operating_model.get("business_description_summary"),
        "unit_name": operating_model.get("unit_name"),
        "unit_description": operating_model.get("unit_description"),
        "unit_price": operating_model.get("unit_price"),
        "shipping_method": operating_model.get("shipping_method"),
        "sales_modality": operating_model.get("sales_modality"),
        "geographic_scope": operating_model.get("geographic_scope"),
        "geographic_coverage": operating_model.get("geographic_coverage"),
      }

      # user_msg is defined above (needed for completed routing).
      if edit_finalize:
        mapping_rows: List[Dict[str, Any]] = []
        if consumer_type != "b2b":
          mapping_rows = _fetch_mapping_rows(conn)

        existing_target_market: Dict[str, Any] = {}
        try:
          raw_existing = tm_draft.get("target_market_json")
          if isinstance(raw_existing, dict):
            existing_target_market = raw_existing
          elif raw_existing:
            parsed_existing = json.loads(str(raw_existing))
            if isinstance(parsed_existing, dict):
              existing_target_market = parsed_existing
        except Exception:
          existing_target_market = {}

        final_context = dict(context)
        if existing_target_market:
          final_context["edit_mode"] = True
          final_context["edit_request"] = str(message).strip()
          final_context["existing_target_market_json"] = existing_target_market

        final_obj = target_market_finalize(
          intake_context=final_context,
          # IMPORTANT: in edit mode, rely on existing_target_market_json as the baseline
          # to avoid drift from previously generated summaries.
          conversation_messages=[user_msg],
          mapping_rows=mapping_rows,
        )
        if not isinstance(final_obj, dict):
          raise RuntimeError("Finalization did not return an object.")

        def _user_requested_all_ages(conversation_messages: List[Dict[str, Any]]) -> bool:
          import re

          last_age_intent: Optional[str] = None  # "all" | "range"
          for m in conversation_messages:
            if not isinstance(m, dict):
              continue
            if str(m.get("role") or "").strip().lower() != "user":
              continue
            content = str(m.get("content") or "").strip().lower()
            if "age" not in content:
              continue
            if "all ages" in content or "all age" in content:
              last_age_intent = "all"
              continue
            if re.search(r"\b\d{1,3}\s*(?:-|â€“|to)\s*\d{1,3}\b", content):
              last_age_intent = "range"
          return last_age_intent == "all"

        if consumer_type in ("consumer", "mixed"):
          wants_all_ages = _user_requested_all_ages([*history, user_msg])
          if wants_all_ages:
            all_age_rows = [
              r
              for r in mapping_rows
              if str(r.get("segment") or "").strip() == "Gender & Age"
              and r.get("min_value") is not None
              and r.get("max_value") is not None
            ]
            if all_age_rows:
              try:
                global_min_age = min(float(r["min_value"]) for r in all_age_rows)  # type: ignore[arg-type]
                global_max_age = max(float(r["max_value"]) for r in all_age_rows)  # type: ignore[arg-type]
                gender_age_intent = final_obj.get("gender_age_intent")
                if isinstance(gender_age_intent, list) and gender_age_intent:
                  for intent in gender_age_intent:
                    if not isinstance(intent, dict):
                      continue
                    intent["age_min"] = global_min_age
                    intent["age_max"] = global_max_age
              except Exception:
                pass

        _validate_final(final_obj, mapping_rows, consumer_type)

        if consumer_type in ("consumer", "mixed"):
          derived_gender_codes: List[str] = []
          for intent in final_obj.get("gender_age_intent") or []:
            if not isinstance(intent, dict):
              continue
            gender_focus = str(intent.get("gender_focus") or "").strip().lower()
            try:
              age_min = float(intent.get("age_min"))
              age_max = float(intent.get("age_max"))
            except Exception:
              continue
            codes = _derive_bucket_codes(
              mapping_rows=mapping_rows,
              segment="Gender & Age",
              range_min=age_min,
              range_max=age_max,
              gender_focus=gender_focus,
            )
            for c in codes:
              if c not in derived_gender_codes:
                derived_gender_codes.append(c)
          if not derived_gender_codes:
            raise RuntimeError(
              "Could not derive any Gender & Age ACS codes from gender_age_intent; ensure target_market_mapping min_value/max_value are populated for this segment."
            )

          derived_income_codes: List[str] = []
          for intent in final_obj.get("income_intent") or []:
            if not isinstance(intent, dict):
              continue
            try:
              inc_min = float(intent.get("income_min"))
              inc_max = float(intent.get("income_max"))
            except Exception:
              continue
            codes = _derive_bucket_codes(
              mapping_rows=mapping_rows,
              segment="Income",
              range_min=inc_min,
              range_max=inc_max,
              gender_focus=None,
            )
            for c in codes:
              if c not in derived_income_codes:
                derived_income_codes.append(c)
          if not derived_income_codes:
            raise RuntimeError(
              "Could not derive any Income ACS codes from income_intent; ensure target_market_mapping min_value/max_value are populated for this segment."
            )

          selections_in = final_obj.get("selections")
          if not isinstance(selections_in, list):
            selections_in = []
          cleaned_selections: List[Dict[str, Any]] = []
          for sel in selections_in:
            if not isinstance(sel, dict):
              continue
            seg = str(sel.get("segment") or "").strip()
            if seg in ("Gender & Age", "Income"):
              continue
            cleaned_selections.append(sel)
          final_obj["selections"] = [
            {"segment": "Gender & Age", "acs_codes": derived_gender_codes},
            {"segment": "Income", "acs_codes": derived_income_codes},
            *cleaned_selections,
          ]

          try:
            import re

            summary_raw = str(final_obj.get("target_market_summary") or "")
            summary_clean = re.sub(r"\b[A-Z]\d{5}_\d{3}E\b", "", summary_raw)
            final_obj["target_market_summary"] = " ".join(summary_clean.split()).strip()
          except Exception:
            pass

        if consumer_type in ("b2b", "mixed"):
          import re

          def _escape_like(value: str) -> str:
            return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

          def _normalize_naics6_list(values: Any) -> List[str]:
            if not isinstance(values, list):
              return []
            out: List[str] = []
            for v in values:
              s = str(v).strip()
              if not s:
                continue
              if not re.fullmatch(r"\d{6}", s):
                continue
              if s not in out:
                out.append(s)
            return out

          def _filter_existing_with_business_types(conn, codes_in: List[str]) -> List[str]:
            if not codes_in:
              return []
            cur = conn.cursor()
            try:
              placeholders = ",".join(["%s"] * len(codes_in))
              cur.execute(
                f"SELECT naics_6 FROM naics_master WHERE naics_6 IN ({placeholders}) AND business_types IS NOT NULL AND TRIM(business_types) <> ''",
                tuple(codes_in),
              )
              rows = cur.fetchall() or []
              allowed = {str(r[0]).strip() for r in rows if r and r[0] is not None}
            finally:
              try:
                cur.close()
              except Exception:
                pass
            return [c for c in codes_in if c in allowed]

          def _augment_from_terms(conn, industry_terms: List[str], existing: List[str]) -> List[str]:
            if not industry_terms or len(existing) >= 20:
              return existing
            cur = conn.cursor()
            try:
              clauses: List[str] = []
              params: List[str] = []
              for term in industry_terms:
                t = str(term).strip().lower()
                if not t:
                  continue
                pattern = f"%{_escape_like(t)}%"
                clauses.append("LOWER(naics_title) LIKE %s ESCAPE '\\\\'")
                params.append(pattern)
              if not clauses:
                return existing
              sql = (
                "SELECT DISTINCT naics_6 "
                "FROM naics_master "
                "WHERE business_types IS NOT NULL AND TRIM(business_types) <> '' "
                f"AND ({' OR '.join(clauses)}) "
                "ORDER BY naics_6 ASC "
                "LIMIT 500"
              )
              cur.execute(sql, tuple(params))
              rows = cur.fetchall() or []
              out = list(existing)
              for (naics6,) in rows:
                code = str(naics6).strip()
                if not re.fullmatch(r"\d{6}", code):
                  continue
                if code not in out:
                  out.append(code)
                if len(out) >= 20:
                  break
              return out
            finally:
              try:
                cur.close()
              except Exception:
                pass

          industry_terms_raw = final_obj.get("b2b_industry_terms") or []
          industry_terms = [str(t).strip() for t in industry_terms_raw if str(t).strip()]
          gpt_naics6_raw = final_obj.get("b2b_naics_6")
          gpt_naics6 = _normalize_naics6_list(gpt_naics6_raw)
          naics6_codes = _filter_existing_with_business_types(conn, gpt_naics6)
          naics6_codes = _augment_from_terms(conn, industry_terms, naics6_codes)
          if not naics6_codes:
            raise RuntimeError(
              "Could not select any NAICS 6-digit codes for the selected B2B industries. "
              "Ensure naics_master contains matching 6-digit codes with non-empty business_types."
            )

          naics6_codes_sorted = sorted(naics6_codes)
          final_obj["b2b_naics_6"] = naics6_codes_sorted
          final_obj["target_market_b2b_industry"] = ",".join(naics6_codes_sorted)

          size_order = ["1-4", "5-9", "10-19", "20-99", "100-499", "500-999", "1000-2499", "2500-4999", "5000-9999", "10000+"]
          age_order = ["0", "1", "2", "3", "4", "5", "6-10", "11-15", "16-20", "21-25", "26+"]
          size_set = {str(x).strip() for x in (final_obj.get("b2b_size_bands") or [])}
          age_set = {str(x).strip() for x in (final_obj.get("b2b_age_bands") or [])}
          final_obj["target_market_b2b_size"] = ",".join([v for v in size_order if v in size_set])
          final_obj["target_market_b2b_age"] = ",".join([v for v in age_order if v in age_set])

        assistant_message = (
          str(final_obj.get("target_market_summary") or "").strip()
          or "Target market intake complete."
        )
        assistant_message = (
          f"{assistant_message}\n\nDoes this look right before we move on to People & Capability?"
        ).strip()
        try:
          import re

          assistant_message = re.sub(r"\b[A-Z]\d{5}_\d{3}E\b", "[ACS code redacted]", assistant_message)
        except Exception:
          pass

        assistant_msg = {"role": "assistant", "content": assistant_message}
        new_messages = [user_msg, assistant_msg]
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="completed",
          target_market_json=final_obj,
          flat_fields=final_obj,
          completed=True,
        )

        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "done": True,
            "action": "await_confirmation",
            "assistant_message": assistant_message,
            "target_market_json": json.dumps(final_obj, ensure_ascii=False),
          }
        )

      turn = target_market_chat_turn(
        intake_context=context,
        conversation_messages=[*history, user_msg],
      )
      assistant_text = str(turn.get("assistant_message") or "").strip()
      # Guardrail: never expose raw ACS codes in the UI conversation.
      try:
        import re

        assistant_text = re.sub(
          r"\b[A-Z]\d{5}_\d{3}E\b",
          "[ACS code redacted]",
          assistant_text,
        )
      except Exception:
        pass
      finalize_ready = bool(turn.get("finalize_ready", False))
      assistant_msg = {"role": "assistant", "content": assistant_text}
      new_messages = [user_msg, assistant_msg]

      done = False
      assistant_message = assistant_text
      target_market_json_out: Optional[str] = None

      if finalize_ready:
        mapping_rows: List[Dict[str, Any]] = []
        if consumer_type != "b2b":
          mapping_rows = _fetch_mapping_rows(conn)
        final_obj = target_market_finalize(
          intake_context=context,
          conversation_messages=[*history, *new_messages],
          mapping_rows=mapping_rows,
        )
        if not isinstance(final_obj, dict):
          raise RuntimeError("Finalization did not return an object.")

        def _user_requested_all_ages(conversation_messages: List[Dict[str, Any]]) -> bool:
          import re

          # Only treat "all ages" as the active intent if it's the last age-related
          # statement. This avoids a stale override if the user later provides a
          # numeric age range.
          last_age_intent: Optional[str] = None  # "all" | "range"

          for m in conversation_messages:
            if not isinstance(m, dict):
              continue
            if str(m.get("role") or "").strip().lower() != "user":
              continue
            content = str(m.get("content") or "").strip().lower()
            if "age" not in content:
              continue

            if "all ages" in content or "all age" in content:
              last_age_intent = "all"
              continue

            # Detect a numeric age range like "18-45", "18–45", "18 to 45", etc.
            if re.search(r"\b\d{1,3}\s*(?:-|–|to)\s*\d{1,3}\b", content):
              last_age_intent = "range"

          return last_age_intent == "all"

        if consumer_type in ("consumer", "mixed"):
          wants_all_ages = _user_requested_all_ages([*history, *new_messages])
          if wants_all_ages:
            all_age_rows = [
              r
              for r in mapping_rows
              if str(r.get("segment") or "").strip() == "Gender & Age"
              and r.get("min_value") is not None
              and r.get("max_value") is not None
            ]
            if all_age_rows:
              try:
                global_min_age = min(float(r["min_value"]) for r in all_age_rows)  # type: ignore[arg-type]
                global_max_age = max(float(r["max_value"]) for r in all_age_rows)  # type: ignore[arg-type]
                gender_age_intent = final_obj.get("gender_age_intent")
                if isinstance(gender_age_intent, list) and gender_age_intent:
                  for intent in gender_age_intent:
                    if not isinstance(intent, dict):
                      continue
                    intent["age_min"] = global_min_age
                    intent["age_max"] = global_max_age
              except Exception:
                pass

        _validate_final(final_obj, mapping_rows, consumer_type)

        if consumer_type in ("consumer", "mixed"):
          # Deterministically derive ACS codes for Gender & Age and Income from intent ranges.
          derived_gender_codes: List[str] = []
          for intent in final_obj.get("gender_age_intent") or []:
            if not isinstance(intent, dict):
              continue
            gender_focus = str(intent.get("gender_focus") or "").strip().lower()
            try:
              age_min = float(intent.get("age_min"))
              age_max = float(intent.get("age_max"))
            except Exception:
              continue
            codes = _derive_bucket_codes(
              mapping_rows=mapping_rows,
              segment="Gender & Age",
              range_min=age_min,
              range_max=age_max,
              gender_focus=gender_focus,
            )
            for c in codes:
              if c not in derived_gender_codes:
                derived_gender_codes.append(c)
          if not derived_gender_codes:
            raise RuntimeError(
              "Could not derive any Gender & Age ACS codes from gender_age_intent; ensure target_market_mapping min_value/max_value are populated for this segment."
            )

          derived_income_codes: List[str] = []
          for intent in final_obj.get("income_intent") or []:
            if not isinstance(intent, dict):
              continue
            try:
              inc_min = float(intent.get("income_min"))
              inc_max = float(intent.get("income_max"))
            except Exception:
              continue
            codes = _derive_bucket_codes(
              mapping_rows=mapping_rows,
              segment="Income",
              range_min=inc_min,
              range_max=inc_max,
              gender_focus=None,
            )
            for c in codes:
              if c not in derived_income_codes:
                derived_income_codes.append(c)
          if not derived_income_codes:
            raise RuntimeError(
              "Could not derive any Income ACS codes from income_intent; ensure target_market_mapping min_value/max_value are populated for this segment."
            )

          # Merge derived selections with model-selected segments (Education + opted-in optional segments).
          selections_in = final_obj.get("selections")
          if not isinstance(selections_in, list):
            selections_in = []
          cleaned_selections: List[Dict[str, Any]] = []
          for sel in selections_in:
            if not isinstance(sel, dict):
              continue
            seg = str(sel.get("segment") or "").strip()
            if seg in ("Gender & Age", "Income"):
              continue
            cleaned_selections.append(sel)
          final_obj["selections"] = [
            {"segment": "Gender & Age", "acs_codes": derived_gender_codes},
            {"segment": "Income", "acs_codes": derived_income_codes},
            *cleaned_selections,
          ]

          # Guardrail: never expose raw ACS codes in stored summary or UI.
          try:
            import re

            summary_raw = str(final_obj.get("target_market_summary") or "")
            summary_clean = re.sub(r"\b[A-Z]\d{5}_\d{3}E\b", "", summary_raw)
            final_obj["target_market_summary"] = " ".join(summary_clean.split()).strip()
          except Exception:
            pass

        if consumer_type in ("b2b", "mixed"):
          import re

          def _escape_like(value: str) -> str:
            return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

          def _normalize_naics6_list(values: Any) -> List[str]:
            if not isinstance(values, list):
              return []
            out: List[str] = []
            for v in values:
              s = str(v).strip()
              if not s:
                continue
              if not re.fullmatch(r"\d{6}", s):
                continue
              if s not in out:
                out.append(s)
              if len(out) >= 20:
                break
            return out

          def _filter_existing_with_business_types(conn, codes_in: List[str]) -> List[str]:
            if not codes_in:
              return []
            cur = conn.cursor()
            try:
              placeholders = ",".join(["%s"] * len(codes_in))
              cur.execute(
                f"SELECT naics_6 FROM naics_master WHERE naics_6 IN ({placeholders}) AND business_types IS NOT NULL AND TRIM(business_types) <> ''",
                tuple(codes_in),
              )
              rows = cur.fetchall() or []
              allowed = {str(r[0]).strip() for r in rows if r and str(r[0]).strip()}
            finally:
              try:
                cur.close()
              except Exception:
                pass
            return [c for c in codes_in if c in allowed]

          def _augment_from_terms(conn, industry_terms: List[str], existing: List[str]) -> List[str]:
            if not industry_terms or len(existing) >= 20:
              return existing
            cur = conn.cursor()
            try:
              clauses: List[str] = []
              params: List[str] = []
              for term in industry_terms:
                t = str(term).strip().lower()
                if not t:
                  continue
                pattern = f"%{_escape_like(t)}%"
                clauses.append("LOWER(naics_title) LIKE %s ESCAPE '\\\\'")
                params.append(pattern)
              if not clauses:
                return existing
              sql = (
                "SELECT DISTINCT naics_6 "
                "FROM naics_master "
                "WHERE business_types IS NOT NULL AND TRIM(business_types) <> '' "
                f"AND ({' OR '.join(clauses)}) "
                "ORDER BY naics_6 ASC "
                "LIMIT 500"
              )
              cur.execute(sql, tuple(params))
              rows = cur.fetchall() or []
              out = list(existing)
              for (naics6,) in rows:
                code = str(naics6).strip()
                if not re.fullmatch(r"\d{6}", code):
                  continue
                if code not in out:
                  out.append(code)
                if len(out) >= 20:
                  break
              return out
            finally:
              try:
                cur.close()
              except Exception:
                pass

          industry_terms_raw = final_obj.get("b2b_industry_terms") or []
          industry_terms = [str(t).strip() for t in industry_terms_raw if str(t).strip()]
          gpt_naics6_raw = final_obj.get("b2b_naics_6")
          gpt_naics6 = _normalize_naics6_list(gpt_naics6_raw)
          naics6_codes = _filter_existing_with_business_types(conn, gpt_naics6)
          naics6_codes = _augment_from_terms(conn, industry_terms, naics6_codes)
          if not naics6_codes:
            raise RuntimeError(
              "Could not select any NAICS 6-digit codes for the selected B2B industries. "
              "Ensure naics_master contains matching 6-digit codes with non-empty business_types."
            )

          # Store both the derived codes list and the persisted CSV columns.
          naics6_codes_sorted = sorted(naics6_codes)
          final_obj["b2b_naics_6"] = naics6_codes_sorted
          final_obj["target_market_b2b_industry"] = ",".join(naics6_codes_sorted)

          # Persist fixed-band selections as CSV strings.
          size_order = ["1-4", "5-9", "10-19", "20-99", "100-499", "500-999", "1000-2499", "2500-4999", "5000-9999", "10000+"]
          age_order = ["0", "1", "2", "3", "4", "5", "6-10", "11-15", "16-20", "21-25", "26+"]
          size_set = {str(x).strip() for x in (final_obj.get("b2b_size_bands") or [])}
          age_set = {str(x).strip() for x in (final_obj.get("b2b_age_bands") or [])}
          final_obj["target_market_b2b_size"] = ",".join([v for v in size_order if v in size_set])
          final_obj["target_market_b2b_age"] = ",".join([v for v in age_order if v in age_set])

        done = True
        assistant_message = (
          str(final_obj.get("target_market_summary") or "").strip()
          or "Target market intake complete."
        )
        assistant_message = (
          f"{assistant_message}\n\nDoes this look right before we move on to People & Capability?"
        ).strip()
        try:
          import re

          assistant_message = re.sub(
            r"\b[A-Z]\d{5}_\d{3}E\b",
            "[ACS code redacted]",
            assistant_message,
          )
        except Exception:
          pass

        assistant_msg_final = {"role": "assistant", "content": assistant_message}
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, assistant_msg_final],
          status="completed",
          target_market_json=final_obj,
          flat_fields=final_obj,
          completed=True,
        )
        target_market_json_out = json.dumps(final_obj, ensure_ascii=False)
      else:
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="in_progress",
        )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "done": done,
          "action": "await_confirmation" if done else "continue",
          "assistant_message": assistant_message,
          "target_market_json": target_market_json_out,
        }
      )
    finally:
      try:
        conn.close()
      except Exception:
        pass
  except Exception as exc:
    app.logger.exception("Failed target market consult: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)
