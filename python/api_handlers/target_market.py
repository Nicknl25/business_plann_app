import json
from typing import Any, Dict, List, Optional

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
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  starting = message is None or not str(message).strip()
  if starting:
    message = "Start the target market intake. Ask your first question."

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore
    from target_market_draft import append_messages, create_draft, get_draft as get_tm_draft  # type: ignore
    from target_market_consultant import (  # type: ignore
      target_market_chat_turn,
      target_market_finalize,
    )
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

  def _validate_final(final_obj: Dict[str, Any], mapping_rows: List[Dict[str, Any]]) -> None:
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
      if age_min <= 0 or age_max <= 0 or age_max < age_min:
        raise RuntimeError("gender_age_intent requires age_min <= age_max and both > 0.")

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
      if inc_min <= 0 or inc_max <= 0 or inc_max < inc_min:
        raise RuntimeError("income_intent requires income_min <= income_max and both > 0.")

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

    if not str(final_obj.get("target_market_summary") or "").strip():
      raise RuntimeError("Final target market JSON missing target_market_summary.")

    conf = final_obj.get("confidence")
    try:
      conf_val = float(conf)
    except Exception as exc:
      raise RuntimeError("Final target market JSON missing valid confidence.") from exc
    if conf_val <= 0 or conf_val > 1:
      raise RuntimeError("confidence must be between 0 and 1.")

  def _derive_bucket_codes(
    *,
    mapping_rows: List[Dict[str, Any]],
    segment: str,
    range_min: float,
    range_max: float,
    gender_focus: Optional[str] = None,
  ) -> List[str]:
    import re

    rows = []
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
      if mx_f < range_min or mn_f > range_max:
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
      rows.append((mn_f, mx_f, str(r.get("acs_code") or "").strip()))
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
      operating_raw = consult.get("operating_model_json")
      operating_model: Dict[str, Any] = {}
      if operating_raw:
        try:
          parsed = json.loads(str(operating_raw))
          if isinstance(parsed, dict):
            operating_model = parsed
        except Exception:
          operating_model = {}

      # Ensure the target market draft row exists.
      try:
        tm_draft = get_tm_draft(conn, draft_id=str(draft_id).strip())
      except Exception:
        create_draft(conn, draft_id=str(draft_id).strip(), client_id=client_id)
        tm_draft = get_tm_draft(conn, draft_id=str(draft_id).strip())

      tm_status = str(tm_draft.get("status") or "").strip().lower()
      if tm_status == "completed":
        tm_raw = tm_draft.get("target_market_json")
        tm_summary = ""
        if tm_raw:
          try:
            tm_obj = json.loads(str(tm_raw))
            if isinstance(tm_obj, dict):
              tm_summary = str(tm_obj.get("target_market_summary") or "").strip()
          except Exception:
            tm_summary = ""
        try:
          import re

          tm_summary = re.sub(r"\b[A-Z]\d{5}_\d{3}E\b", "[ACS code redacted]", tm_summary)
        except Exception:
          pass
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "done": True,
            "assistant_message": tm_summary or "Target market intake complete.",
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
        "business_description_summary": operating_model.get("business_description_summary"),
        "unit_name": operating_model.get("unit_name"),
        "unit_description": operating_model.get("unit_description"),
        "unit_price": operating_model.get("unit_price"),
        "shipping_method": operating_model.get("shipping_method"),
        "sales_modality": operating_model.get("sales_modality"),
        "geographic_scope": operating_model.get("geographic_scope"),
      }

      user_msg = {"role": "user", "content": str(message).strip()}
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

      if finalize_ready:
        mapping_rows = _fetch_mapping_rows(conn)
        final_obj = target_market_finalize(
          intake_context=context,
          conversation_messages=[*history, *new_messages],
          mapping_rows=mapping_rows,
        )
        if not isinstance(final_obj, dict):
          raise RuntimeError("Finalization did not return an object.")
        _validate_final(final_obj, mapping_rows)

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

        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="completed",
          target_market_json=final_obj,
          completed=True,
        )
        done = True
        assistant_message = str(final_obj.get("target_market_summary") or "").strip() or "Target market intake complete."
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
          "assistant_message": assistant_message,
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

