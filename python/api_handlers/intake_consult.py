import json
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify


def _parse_json_dict(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _parse_messages(raw: Any) -> List[Dict[str, str]]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return [m for m in raw if isinstance(m, dict)]
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  return [m for m in parsed if isinstance(m, dict)] if isinstance(parsed, list) else []


def _parse_json_list(raw: Any) -> List[Any]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return list(raw)
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  return list(parsed) if isinstance(parsed, list) else []


def _strip_acs_codes(text: str) -> str:
  """
  Never expose raw ACS codes in the UI conversation.
  """
  try:
    import re

    return re.sub(r"\b[A-Z]\d{5}_\d{3}E\b", "[ACS code redacted]", text)
  except Exception:
    return text


def _marketing_ready(marketing_model_json: Dict[str, Any]) -> bool:
  try:
    if isinstance(marketing_model_json, dict) and isinstance(marketing_model_json.get("lobs"), list):
      lobs = marketing_model_json.get("lobs") or []
      if not lobs:
        return False
      non_company = [
        lob
        for lob in lobs
        if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
      ]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      for lob in requires:
        derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
        y1 = derived.get("year1_marketing_spend")
        ok = isinstance(y1, dict) and bool(str(y1.get("value") or "").strip())
        if not ok:
          return False
      return True
    derived = marketing_model_json.get("derived") if isinstance(marketing_model_json, dict) else None
    if isinstance(derived, dict) and "year1_marketing_spend" in derived:
      val = derived.get("year1_marketing_spend") or {}
      if isinstance(val, dict) and str(val.get("value") or "").strip():
        return True
    drivers = marketing_model_json.get("drivers") if isinstance(marketing_model_json, dict) else None
    if isinstance(drivers, dict) and "monthly_marketing_budget" in drivers:
      val = drivers.get("monthly_marketing_budget") or {}
      if isinstance(val, dict) and str(val.get("value") or "").strip():
        return True
  except Exception:
    return False
  return False


def _slugify_lob_key(name: str) -> str:
  raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name or ""))
  raw = "_".join([p for p in raw.split("_") if p])
  if not raw:
    return "lob"
  if raw[0].isdigit():
    raw = f"lob_{raw}"
  return raw[:48]


def _extract_lobs_from_text(text: str) -> List[Dict[str, str]]:
  raw = str(text or "")
  lowered = raw.lower()
  if "line of business" not in lowered and "lines of business" not in lowered and "lob" not in lowered:
    return []

  # Heuristic: capture "(1) ... (2) ..." segments.
  import re

  parts = re.split(r"\(\s*\d+\s*\)\s*", raw)
  parts = [p.strip(" .;\n\r\t") for p in parts if p and p.strip()]
  if len(parts) <= 1:
    return []

  out: List[Dict[str, str]] = []
  for p in parts[1:6]:
    # Use the phrase up to the first period/semicolon as the name.
    name = re.split(r"[.;\n\r]", p, maxsplit=1)[0].strip()
    if not name:
      continue
    key = _slugify_lob_key(name)
    # Ensure uniqueness.
    existing = {x["lob_key"] for x in out if isinstance(x, dict) and "lob_key" in x}
    if key in existing:
      suffix = 2
      while f"{key}_{suffix}" in existing:
        suffix += 1
      key = f"{key}_{suffix}"
    out.append({"lob_key": key, "lob_name": name})
  return out


def _ensure_lob_model_card(card: Dict[str, Any], lobs: List[Dict[str, str]]) -> Dict[str, Any]:
  if not lobs:
    return card
  now_ms = int(time.time() * 1000)
  existing_lobs = card.get("lobs") if isinstance(card, dict) else None
  if isinstance(existing_lobs, list) and existing_lobs:
    has_company_total = any(
      isinstance(l, dict) and str(l.get("lob_key") or "").strip() == "company_total" for l in existing_lobs
    )
    if has_company_total:
      return card
    return {
      **card,
      "lobs": [
        {"lob_key": "company_total", "lob_name": None, "drivers": {}, "derived": {}},
        *existing_lobs,
      ],
    }

  # Always include system-required company_total first (user-invisible shared-home).
  deduped: List[Dict[str, str]] = []
  seen = set()
  for entry in [{"lob_key": "company_total", "lob_name": ""}, *list(lobs or [])]:
    key = str(entry.get("lob_key") or "").strip() or "company_total"
    if key in seen:
      continue
    seen.add(key)
    deduped.append(entry)
  return {
    "version": int((card or {}).get("version") or 1),
    "updated_at_ms": now_ms,
    "lobs": [
      {
        "lob_key": str(l.get("lob_key") or "company_total").strip() or "company_total",
        "lob_name": str(l.get("lob_name") or "").strip() or None,
        "drivers": {},
        "derived": {},
      }
      for l in deduped
    ],
  }


def _build_business_type_candidates(*, conn, messages: List[Dict[str, str]]) -> List[str]:
  """
  Build a small, relevant business_type candidate list by scoring known values against
  early user messages. This keeps finalization deterministic while avoiding a huge list.
  """
  try:
    from difflib import SequenceMatcher

    cur = conn.cursor()
    try:
      cur.execute("SELECT business_types FROM naics_master WHERE business_types IS NOT NULL")
      rows = cur.fetchall() or []
      values: List[str] = []
      for (bt,) in rows:
        if bt is None:
          continue
        for part in str(bt).split(","):
          part_str = str(part).strip()
          if part_str:
            values.append(part_str)
      all_business_types = sorted(set(values), key=lambda x: x.lower())
    finally:
      try:
        cur.close()
      except Exception:
        pass

    user_texts: List[str] = []
    for msg in messages:
      if str(msg.get("role") or "") != "user":
        continue
      content = str(msg.get("content") or "").strip()
      if not content:
        continue
      # Ignore internal-start markers if present.
      if "Start the operational intake." in content:
        continue
      user_texts.append(content)
      if len(user_texts) >= 6:
        break

    base = " ".join(user_texts).strip().lower()
    base = " ".join(base.split())
    tokens = {t for t in base.replace("/", " ").replace("-", " ").split() if len(t) >= 3}

    scored = []
    for bt in all_business_types:
      btl = bt.lower()
      token_score = sum(1 for t in tokens if t in btl) if tokens else 0
      ratio = SequenceMatcher(None, base, btl).ratio() if base else 0.0
      scored.append((token_score, ratio, bt))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [bt for _, _, bt in scored[:80]] or (all_business_types[:80] if all_business_types else [])
  except Exception:
    return []


_BUSINESS_TYPE_TO_NAICS_6_CACHE: Dict[str, str] | None = None


def _ensure_business_type_to_naics_cache(*, conn) -> Dict[str, str]:
  global _BUSINESS_TYPE_TO_NAICS_6_CACHE
  if _BUSINESS_TYPE_TO_NAICS_6_CACHE is not None:
    return _BUSINESS_TYPE_TO_NAICS_6_CACHE

  mapping: Dict[str, str] = {}
  cur = conn.cursor()
  try:
    cur.execute(
      "SELECT business_types, naics_6 FROM naics_master WHERE business_types IS NOT NULL AND naics_6 IS NOT NULL"
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  for row in rows:
    try:
      business_types_raw, naics_6 = row
    except Exception:
      continue
    if not business_types_raw or not naics_6:
      continue
    naics_6_str = str(naics_6).strip()
    if not naics_6_str:
      continue
    for part in str(business_types_raw).split(","):
      token = str(part).strip()
      if token and token not in mapping:
        mapping[token] = naics_6_str

  _BUSINESS_TYPE_TO_NAICS_6_CACHE = mapping
  return mapping


def _resolve_naics_6(*, conn, business_type: str) -> Optional[str]:
  bt = str(business_type or "").strip()
  if not bt:
    return None
  try:
    mapping = _ensure_business_type_to_naics_cache(conn=conn)
  except Exception:
    return None
  return mapping.get(bt)


def _compute_focus(
  *,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> str:
  def _has_nonempty_text(obj: Dict[str, Any], key: str) -> bool:
    try:
      return bool(str((obj or {}).get(key) or "").strip())
    except Exception:
      return False

  # IMPORTANT: Section JSON may be partially populated by edit patches.
  # A section is complete once its summary template exists.
  ops_ready = _has_nonempty_text(ops_json, "business_description_summary")
  market_ready = _has_nonempty_text(market_json, "target_market_summary") and _marketing_ready(
    marketing_model_json
  )
  people_ready = _has_nonempty_text(people_json, "key_people_summary")
  financials_ready = _has_nonempty_text(financials_json, "financials_summary")

  # Strict sequencing for progress; edits are allowed anytime, but advancement follows this order.
  if not ops_ready:
    return "ops"

  if not market_ready:
    return "market"

  if not people_ready:
    return "people"

  if not financials_ready:
    return "financials"

  return "done"
def _start_instruction_for_focus(focus: str) -> str:
  focus_norm = str(focus or "").strip().lower()
  if focus_norm == "ops":
    return "Start the operational intake. Ask your first question."
  if focus_norm == "market":
    return "Start the target market intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions)."
  if focus_norm == "people":
    return "Start the People & Capability intake. Ask your first question."
  if focus_norm == "financials":
    return "Start the financials intake. Ask your first question."
  return "Continue."


def _apply_scoped_patch(
  patch: Dict[str, Any],
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  """
  Apply patch keys scoped as "<group>.<field>" into the canonical section objects.
  """
  next_business = dict(business_facts)
  next_ops = dict(ops_json)
  next_market = dict(market_json)
  next_people = dict(people_json)
  next_financials = dict(financials_json)

  for raw_key, value in (patch or {}).items():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    group, field = key.split(".", 1)
    group = group.strip().lower()
    field = field.strip()
    if not group or not field:
      continue

    if group == "business":
      next_business[field] = value
      if field == "address":
        # If the canonical address string changes via chat-driven patch, we do not
        # have reliable structured parts (street/city/state/zip/country). Clear
        # parts so the UI can prompt the client to re-select a full address from
        # suggestions before final submit.
        for part_key in (
          "address_street",
          "address_city",
          "address_state",
          "address_zip",
          "address_country",
        ):
          next_business[part_key] = None
    elif group == "ops":
      next_ops[field] = value
    elif group == "market":
      next_market[field] = value
    elif group == "people":
      next_people[field] = value
    elif group == "financials":
      next_financials[field] = value

  return next_business, next_ops, next_market, next_people, next_financials


def _suggest_marketing_budget(*, ops_json: Dict[str, Any]) -> Dict[str, Any]:
  starting_revenue = None
  try:
    starting_revenue = float((ops_json or {}).get("starting_revenue"))  # type: ignore[arg-type]
  except Exception:
    starting_revenue = None

  consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
  capacity_driver = str((ops_json or {}).get("capacity_driver") or "").strip().lower()

  # Deterministic starting point: % of Year-1 revenue if we have it, otherwise a small baseline.
  pct = 0.08
  if consumer_type == "b2b":
    pct = 0.06
  if consumer_type == "mixed":
    pct = 0.07
  if capacity_driver == "demand":
    pct = min(0.12, pct + 0.02)

  annual = 12000.0
  basis = "It's a conservative baseline while still leaving room for paid acquisition experiments."
  if starting_revenue and starting_revenue > 0:
    annual = max(0.0, round((starting_revenue * pct) / 100.0) * 100.0)
    basis = f"It's about {pct*100:.0f}% of your Year-1 revenue target (a common starting point for a demand-driven ramp)."

  monthly = round((annual / 12.0) / 50.0) * 50.0 if annual > 0 else 0.0
  annual = monthly * 12.0

  channels = "Website/SEO plus partnerships/referrals"
  return {
    "monthly_marketing_budget": monthly,
    "year1_marketing_spend": annual,
    "basis": basis,
    "primary_channels": channels,
  }


def _suggest_marketing_budget_per_lob(*, ops_json: Dict[str, Any], lobs: List[Dict[str, str]]) -> List[Dict[str, Any]]:
  base = _suggest_marketing_budget(ops_json=ops_json)
  out: List[Dict[str, Any]] = []
  for lob in list(lobs or []):
    lob_key = str(lob.get("lob_key") or "").strip() or "company_total"
    if lob_key == "company_total":
      continue
    lob_name = str(lob.get("lob_name") or "").strip() or None
    # No allocation logic: treat each LOB independently with a conservative baseline that can be edited.
    out.append(
      {
        "lob_key": lob_key,
        "lob_name": lob_name,
        "monthly_marketing_budget": base.get("monthly_marketing_budget"),
        "year1_marketing_spend": base.get("year1_marketing_spend"),
        "basis": "Starting point per line of business; edit to reflect your plan (no allocation logic is being applied).",
        "primary_channels": base.get("primary_channels"),
      }
    )
  return out


def _ensure_pricing_model_card(
  *,
  ops_json: Dict[str, Any],
  pricing_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  if pricing_model_json and isinstance(pricing_model_json, dict) and pricing_model_json.get("drivers"):
    return pricing_model_json

  unit_price = (ops_json or {}).get("unit_price")
  if unit_price in (None, ""):
    return pricing_model_json or {}
  try:
    unit_price_num = float(unit_price)
  except Exception:
    unit_price_num = unit_price

  now_ms = int(time.time() * 1000)
  return {
    "version": 1,
    "updated_at_ms": now_ms,
    "drivers": {
      "unit_price": {
        "value": unit_price_num,
        "unit": "USD",
        "time_basis": "per_unit",
        "rationale": "Captured from the operational revenue model as the standard price per unit.",
        "updated_at_ms": now_ms,
      }
    },
    "derived": {},
  }


def _fetch_target_market_mapping_rows(conn) -> List[Dict[str, Any]]:
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
    raise RuntimeError(
      "target_market_mapping table is empty; load it before running the target market consult."
    )
  return cleaned


def post_intake_consult_session_handler(*, app, request):
  """
  Create a new durable unified intake draft and return {draft_id, client_id}.
  """
  if request.method == "OPTIONS":
    return ("", 204)

  try:
    from intake_submission import generate_client_id, get_mysql_connection  # type: ignore
    from intake_consult_draft import create_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import intake consult draft helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  client_id = generate_client_id()
  conn = get_mysql_connection()
  try:
    draft = create_draft(conn, client_id=client_id)
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def get_intake_consult_draft_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  draft_id = request.args.get("draft_id")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
    except Exception as exc:
      return (jsonify({"error": "not_found", "detail": str(exc)}), 404)

    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
        "draft_status": draft.get("status"),
        "active_focus": draft.get("active_focus"),
        "ops_confirmed": bool(draft.get("ops_confirmed")),
        "market_confirmed": bool(draft.get("market_confirmed")),
        "people_confirmed": bool(draft.get("people_confirmed")),
        "financials_confirmed": bool(draft.get("financials_confirmed")),
        "consistency_passed": bool(draft.get("consistency_passed")),
        "business_name": draft.get("business_name"),
        "business_address": draft.get("business_address"),
        "address_street": draft.get("address_street"),
        "address_city": draft.get("address_city"),
        "address_state": draft.get("address_state"),
        "address_zip": draft.get("address_zip"),
        "address_country": draft.get("address_country"),
        "business_start_date": draft.get("business_start_date"),
        "messages_json": draft.get("messages_json"),
        "operating_model_json": draft.get("operating_model_json"),
        "target_market_json": draft.get("target_market_json"),
        "people_json": draft.get("people_json"),
        "financials_json": draft.get("financials_json"),
        "ops_concept_model_json": draft.get("ops_concept_model_json"),
        "fulfillment_model_json": draft.get("fulfillment_model_json"),
        "marketing_model_json": draft.get("marketing_model_json"),
        "pricing_model_json": draft.get("pricing_model_json"),
        "headcount_model_json": draft.get("headcount_model_json"),
        "model_card_proposals_json": draft.get("model_card_proposals_json"),
        "driver_events_json": draft.get("driver_events_json"),
        "driver_revision_nonce": draft.get("driver_revision_nonce"),
        "year1_revenue": draft.get("year1_revenue"),
        "year1_marketing_spend": draft.get("year1_marketing_spend"),
        "year1_payroll": draft.get("year1_payroll"),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def post_intake_consult_handler(*, app, request):
  """
  Unified intake consult controller (single chat, single draft model).
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

  raw_message = payload.get("message")
  message = str(raw_message or "").strip()
  starting = raw_message is None or not message

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import append_messages, get_draft  # type: ignore
    from api_handlers.shared_context import build_shared_context  # type: ignore
    from fact_templates import FACT_GROUPS, sanitize_fact_template  # type: ignore
    from intent_router import route_intent  # type: ignore
    from template_rewriter import rewrite_summary_as_fact_template  # type: ignore

    from intake_consultant import consultant_chat_turn, consultant_finalize  # type: ignore
    from target_market_consultant import target_market_chat_turn, target_market_finalize  # type: ignore
    from marketing_consultant import marketing_chat_turn  # type: ignore
    from people_capability_consultant import (  # type: ignore
      people_capability_chat_turn,
      people_capability_finalize,
    )
    from financials_consultant import financials_chat_turn, financials_finalize  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import unified intake helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    consult = get_draft(conn, draft_id=str(draft_id).strip())
    client_id = str(consult.get("client_id") or "").strip()
    draft_status = str(consult.get("status") or "").strip().lower()
    if draft_status == "submitted":
      return (
        jsonify({"error": "duplicate_submit", "detail": "This draft was already submitted."}),
        409,
      )

    messages = _parse_messages(consult.get("messages_json"))

    ops_json = _parse_json_dict(consult.get("operating_model_json"))
    market_json = _parse_json_dict(consult.get("target_market_json"))
    people_json = _parse_json_dict(consult.get("people_json"))
    financials_json = _parse_json_dict(consult.get("financials_json"))
    marketing_model_json = _parse_json_dict(consult.get("marketing_model_json"))
    pricing_model_json = _parse_json_dict(consult.get("pricing_model_json"))
    ops_concept_model_json = _parse_json_dict(consult.get("ops_concept_model_json"))
    model_card_proposals = _parse_json_list(consult.get("model_card_proposals_json"))

    ops_confirmed = bool(consult.get("ops_confirmed"))
    market_confirmed = bool(consult.get("market_confirmed"))
    people_confirmed = bool(consult.get("people_confirmed"))
    financials_confirmed = bool(consult.get("financials_confirmed"))
    consistency_passed = bool(consult.get("consistency_passed"))

    business_facts: Dict[str, Any] = {
      "name": consult.get("business_name"),
      "address": consult.get("business_address"),
      "start_date": consult.get("business_start_date"),
      "address_street": consult.get("address_street"),
      "address_city": consult.get("address_city"),
      "address_state": consult.get("address_state"),
      "address_zip": consult.get("address_zip"),
      "address_country": consult.get("address_country"),
    }

    # Allow explicit client-detail updates from the UI (no intent inference).
    if payload.get("business_name") is not None:
      name_raw = str(payload.get("business_name") or "").strip()
      if name_raw:
        business_facts["name"] = name_raw
    if payload.get("address") is not None:
      addr_raw = str(payload.get("address") or "").strip()
      if addr_raw:
        business_facts["address"] = addr_raw
    start_date_raw = payload.get("business_start_date")
    if start_date_raw is None:
      start_date_raw = payload.get("businessStartDate") or payload.get("business_startDate")
    if start_date_raw is not None:
      sd_raw = str(start_date_raw or "").strip()
      if sd_raw:
        business_facts["start_date"] = sd_raw

    for key in ("address_street", "address_city", "address_state", "address_zip", "address_country"):
      if payload.get(key) is None:
        continue
      val = str(payload.get(key) or "").strip()
      if val:
        business_facts[key] = val

    focus = _compute_focus(
      ops_json=ops_json,
      market_json=market_json,
      marketing_model_json=marketing_model_json,
      people_json=people_json,
      financials_json=financials_json,
    )

    shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())

    baseline_json = {
      "business": business_facts,
      "ops": ops_json,
      "market": market_json,
      "people": people_json,
      "financials": financials_json,
    }

    # Provide business_type candidates for GPT-only intent routing (internal only).
    # This enables early classification confirmation without exposing any labels to the client UI.
    if focus == "ops" and not str((ops_json or {}).get("business_type") or "").strip():
      try:
        baseline_json["business_type_candidates"] = _build_business_type_candidates(
          conn=conn, messages=messages
        )
      except Exception:
        baseline_json["business_type_candidates"] = []

    naics_6 = _resolve_naics_6(conn=conn, business_type=str((ops_json or {}).get("business_type") or ""))
    ops_consumer_type = str((ops_json or {}).get("consumer_type") or "").strip().lower()
    if ops_consumer_type not in ("consumer", "b2b", "mixed"):
      ops_consumer_type = "consumer"

    # Multi-LOB detection (heuristic): if the user explicitly describes multiple lines of business,
    # persist scoped LOB entries inside the model-card JSON columns (no additional tables).
    try:
      lobs = _extract_lobs_from_text(message) if (not starting and message) else []
      if lobs and not (isinstance(ops_concept_model_json.get("lobs"), list) and ops_concept_model_json.get("lobs")):
        ops_concept_model_json = _ensure_lob_model_card(ops_concept_model_json or {}, lobs)
        # Seed Marketing/Headcount/ Fulfillment cards with the same LOB structure (empty drivers/derived).
        marketing_model_json = _ensure_lob_model_card(marketing_model_json or {}, lobs)
        headcount_model_json = _ensure_lob_model_card(headcount_model_json or {}, lobs)
        fulfillment_model_json = _ensure_lob_model_card(fulfillment_model_json or {}, lobs)
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[],
          ops_concept_model_json=ops_concept_model_json,
          marketing_model_json=marketing_model_json,
          headcount_model_json=headcount_model_json,
          fulfillment_model_json=fulfillment_model_json,
        )
    except Exception:
      pass

    # Additive: pricing model card is sourced from Ops unit_price (no extra questions).
    try:
      next_pricing = _ensure_pricing_model_card(ops_json=ops_json, pricing_model_json=pricing_model_json)
      if next_pricing and next_pricing != pricing_model_json:
        pricing_model_json = next_pricing
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[],
          pricing_model_json=pricing_model_json,
        )
    except Exception:
      pass

    if starting:
      start_instruction = _start_instruction_for_focus(focus)
      turn_messages = [*messages, {"role": "user", "content": start_instruction}]
      intake_context: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "today_iso": date.today().isoformat(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "consumer_type": ops_consumer_type,
        "naics_6": naics_6,
        "shared_context": shared_context,
      }

      if focus == "done":
        assistant_text = 'All sections are complete.\n\nClick "Submit intake" to finish.'
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[{"role": "assistant", "content": assistant_text}],
          active_focus="done",
          business_facts=business_facts,
          consistency_passed=True,
          status="completed",
          completed=True,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "done",
            "awaiting_confirmation": False,
            "done": True,
            "action": "ready_to_submit",
            "assistant_message": assistant_text,
          }
        )

      turn: Dict[str, Any] = {"assistant_message": "", "turn_outcome": "ASK_NEXT"}
      if focus == "ops":
        turn = consultant_chat_turn(intake_context=intake_context, conversation_messages=turn_messages)
      elif focus == "market":
        if str((market_json or {}).get("target_market_summary") or "").strip() and not _marketing_ready(
          marketing_model_json
        ):
          marketing_lobs = []
          try:
            marketing_lobs = marketing_model_json.get("lobs") if isinstance(marketing_model_json, dict) else []
          except Exception:
            marketing_lobs = []

          suggestions: List[Dict[str, Any]] = []
          if isinstance(marketing_lobs, list) and marketing_lobs:
            lob_list = [
              {
                "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                "lob_name": str(l.get("lob_name") or "").strip(),
              }
              for l in marketing_lobs
              if isinstance(l, dict)
            ]
            suggestions = _suggest_marketing_budget_per_lob(ops_json=ops_json, lobs=lob_list)
            if not suggestions:
              suggestions = [_suggest_marketing_budget(ops_json=ops_json)]
          else:
            suggestions = [_suggest_marketing_budget(ops_json=ops_json)]

          # Ensure pending proposals exist for UI Accept/Edit.
          existing_ids = {
            str(p.get("id") or "").strip()
            for p in model_card_proposals
            if isinstance(p, dict) and p.get("model") == "marketing"
          }
          needs = []
          if len(suggestions) == 1 and not existing_ids:
            needs = suggestions
          elif len(suggestions) > 1:
            existing_lobs = {
              str(p.get("lob_key") or "").strip()
              for p in model_card_proposals
              if isinstance(p, dict) and p.get("model") == "marketing"
            }
            for s in suggestions:
              if str(s.get("lob_key") or "").strip() and str(s.get("lob_key") or "").strip() not in existing_lobs:
                needs.append(s)

          if needs:
            now_ms = int(time.time() * 1000)
            for s in needs:
              proposal_id = f"mk_{now_ms}_{len(model_card_proposals)+1}"
              model_card_proposals = [
                *model_card_proposals,
                {
                  "id": proposal_id,
                  "model": "marketing",
                  "title": "Marketing budget (Year 1)",
                  "lob_key": s.get("lob_key"),
                  "lob_name": s.get("lob_name"),
                  "updates": [
                    {
                      "key": "monthly_marketing_budget",
                      "value": s.get("monthly_marketing_budget"),
                      "unit": "USD",
                      "time_basis": "month",
                      "rationale": s.get("basis"),
                    },
                    {
                      "key": "primary_channels",
                      "value": s.get("primary_channels"),
                      "unit": None,
                      "time_basis": None,
                      "rationale": "Starting assumption; edit to reflect your actual plan.",
                    },
                  ],
                  "derived": [
                    {
                      "key": "year1_marketing_spend",
                      "value": s.get("year1_marketing_spend"),
                      "unit": "USD",
                      "time_basis": "year",
                      "derivation": "monthly_marketing_budget x 12",
                    }
                  ],
                  "created_at_ms": now_ms,
                },
              ]
            append_messages(
              conn,
              draft_id=str(draft_id).strip(),
              new_messages=[],
              model_card_proposals=model_card_proposals,
            )

          turn = marketing_chat_turn(
            intake_context={**intake_context, "marketing_suggestion": (suggestions[0] if suggestions else {})},
            conversation_messages=turn_messages,
          )
        else:
          turn = target_market_chat_turn(intake_context=intake_context, conversation_messages=turn_messages)
      elif focus == "people":
        turn = people_capability_chat_turn(intake_context=intake_context, conversation_messages=turn_messages)
      elif focus == "financials":
        turn = financials_chat_turn(intake_context=intake_context, conversation_messages=turn_messages)
      else:
        turn = {"assistant_message": "Continue.", "turn_outcome": "ASK_NEXT"}

      assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[{"role": "assistant", "content": assistant_text}],
        active_focus=focus,
        business_facts=business_facts,
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": False,
          "done": bool(focus == "done"),
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    user_msg = {"role": "user", "content": message}
    recent_messages = messages[-12:] if len(messages) > 12 else list(messages)

    # Market extension: once Target Market is complete, keep Market focus active until Marketing is locked.
    # While Marketing is pending, we show an Accept/Edit proposal and do not route through the target market consultant.
    if (
      str(focus or "").strip().lower() == "market"
      and str((market_json or {}).get("target_market_summary") or "").strip()
      and not _marketing_ready(marketing_model_json)
    ):
      marketing_lobs = []
      try:
        marketing_lobs = marketing_model_json.get("lobs") if isinstance(marketing_model_json, dict) else []
      except Exception:
        marketing_lobs = []

      suggestions: List[Dict[str, Any]] = []
      if isinstance(marketing_lobs, list) and marketing_lobs:
        lob_list = [
          {
            "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
            "lob_name": str(l.get("lob_name") or "").strip(),
          }
          for l in marketing_lobs
          if isinstance(l, dict)
        ]
        suggestions = _suggest_marketing_budget_per_lob(ops_json=ops_json, lobs=lob_list)
        if not suggestions:
          suggestions = [_suggest_marketing_budget(ops_json=ops_json)]
      else:
        suggestions = [_suggest_marketing_budget(ops_json=ops_json)]

      existing_lobs = {
        str(p.get("lob_key") or "").strip()
        for p in model_card_proposals
        if isinstance(p, dict) and p.get("model") == "marketing"
      }
      now_ms = int(time.time() * 1000)
      for s in suggestions:
        lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
        if lob_key and lob_key in existing_lobs:
          continue
        proposal_id = f"mk_{now_ms}_{len(model_card_proposals)+1}"
        model_card_proposals = [
          *model_card_proposals,
          {
            "id": proposal_id,
            "model": "marketing",
            "title": "Marketing budget (Year 1)",
            "lob_key": lob_key or None,
            "lob_name": s.get("lob_name"),
            "updates": [
              {
                "key": "monthly_marketing_budget",
                "value": s.get("monthly_marketing_budget"),
                "unit": "USD",
                "time_basis": "month",
                "rationale": s.get("basis"),
              },
              {
                "key": "primary_channels",
                "value": s.get("primary_channels"),
                "unit": None,
                "time_basis": None,
                "rationale": "Starting assumption; edit to reflect your actual plan.",
              },
            ],
            "derived": [
              {
                "key": "year1_marketing_spend",
                "value": s.get("year1_marketing_spend"),
                "unit": "USD",
                "time_basis": "year",
                "derivation": "monthly_marketing_budget x 12",
              }
            ],
            "created_at_ms": now_ms,
          },
        ]
        existing_lobs.add(lob_key)

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[],
        model_card_proposals=model_card_proposals,
      )

      assistant_text = sanitize_fact_template(
        str(
          marketing_chat_turn(
            intake_context={
              "client_id": client_id,
              "draft_id": str(draft_id).strip(),
              "shared_context": shared_context,
              "marketing_suggestion": (suggestions[0] if suggestions else {}),
            },
            conversation_messages=[*messages, user_msg],
          ).get("assistant_message")
          or ""
        ).strip()
      )
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        active_focus="market",
        business_facts=business_facts,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "market",
          "awaiting_confirmation": False,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    # Route the user's message through the GPT-only intent router first.
    intent = route_intent(
      consult_type="unified",
      user_message=message,
      baseline_json=baseline_json,
      shared_context=shared_context,
      recent_messages=recent_messages,
      confirm_question_override="",
      active_focus=focus,
    )

    action = str(intent.get("action") or "").strip()
    router_msg = sanitize_fact_template(str(intent.get("assistant_message") or "").strip())
    patch = intent.get("patch") if isinstance(intent.get("patch"), dict) else None

    # Safety: never treat an empty patch as an edit_patch action.
    if action == "edit_patch" and not patch:
      action = "continue_chat"

    preface = ""
    if action in ("confirm_proceed", "confirm_clarify", "answer_readonly"):
      preface = router_msg
      action = "continue_chat"

    # If the intake is fully complete, "continue" should guide the user to submission.
    if focus == "done" and action == "continue_chat":
      assistant_text = 'Consistency check is complete and the facts are now coherent.\n\nClick "Submit intake" to finish.'
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        active_focus="done",
        business_facts=business_facts,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "done",
          "awaiting_confirmation": False,
          "done": True,
          "action": "ready_to_submit",
          "assistant_message": assistant_text,
        }
      )

    if action == "edit_patch" and patch:
      prev_business_facts = dict(business_facts)
      prev_ops_json = dict(ops_json)
      prev_market_json = dict(market_json)
      prev_people_json = dict(people_json)
      prev_financials_json = dict(financials_json)

      business_facts, ops_json, market_json, people_json, financials_json = _apply_scoped_patch(
        patch,
        business_facts=business_facts,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
      )

      # Track fact revisions as immutable history (drivers are superseded, not blended).
      fact_revision_nonce_out: int | None = None
      fact_revisions_out: List[Dict[str, Any]] | None = None
      try:
        current_nonce = int(consult.get("fact_revision_nonce") or 0)
      except Exception:
        current_nonce = 0
      try:
        raw_revs = consult.get("fact_revisions_json")
        parsed_revs = json.loads(str(raw_revs)) if raw_revs else []
        if not isinstance(parsed_revs, list):
          parsed_revs = []
      except Exception:
        parsed_revs = []

      revision_entries: List[Dict[str, Any]] = []
      try:
        for raw_key in (patch or {}).keys():
          key = str(raw_key or "").strip()
          if key.count(".") != 1:
            continue
          group, field = key.split(".", 1)
          group = group.strip().lower()
          field = field.strip()
          if not group or not field:
            continue

          old_value: Any = None
          next_value: Any = None
          if group == "business":
            old_value = prev_business_facts.get(field)
            next_value = business_facts.get(field)
          elif group == "ops":
            old_value = prev_ops_json.get(field)
            next_value = ops_json.get(field)
          elif group == "market":
            old_value = prev_market_json.get(field)
            next_value = market_json.get(field)
          elif group == "people":
            old_value = prev_people_json.get(field)
            next_value = people_json.get(field)
          elif group == "financials":
            old_value = prev_financials_json.get(field)
            next_value = financials_json.get(field)
          else:
            continue

          if old_value == next_value:
            continue
          revision_entries.append(
            {
              "field": key,
              "old": old_value,
              "new": next_value,
            }
          )
      except Exception:
        revision_entries = []

      if revision_entries:
        next_nonce = current_nonce + 1
        now_ms = int(time.time() * 1000)
        for e in revision_entries:
          e["nonce"] = next_nonce
          e["at_ms"] = now_ms
        parsed_revs.extend(revision_entries)
        if len(parsed_revs) > 200:
          parsed_revs = parsed_revs[-200:]
        fact_revision_nonce_out = next_nonce
        fact_revisions_out = parsed_revs
      active_focus_out = focus
      status_out: str | None = None
      consistency_passed_out = False
      completed_out = False

      # Always echo the latest relevant summary templates after an edit so the user
      # doesn't have to scroll to see the updated current-state narrative.
      summary_by_group: Dict[str, str] = {
        "ops": str((ops_json or {}).get("business_description_summary") or "").strip(),
        "market": str((market_json or {}).get("target_market_summary") or "").strip(),
        "people": str((people_json or {}).get("key_people_summary") or "").strip(),
        "financials": str((financials_json or {}).get("financials_summary") or "").strip(),
      }
      changed_groups: List[str] = []
      try:
        for raw_key in (patch or {}).keys():
          key = str(raw_key or "").strip()
          if key.count(".") != 1:
            continue
          group, _field = key.split(".", 1)
          group = group.strip().lower()
          if group and group not in changed_groups:
            changed_groups.append(group)
      except Exception:
        changed_groups = []

      # One-time upgrade path: older drafts may contain literal summaries that do not
      # use {{fact:...}} placeholders, which prevents fact propagation after edits.
      try:
        allowed_fact_keys: List[str] = []
        for g, fields in (FACT_GROUPS or {}).items():
          for f in list(fields or []):
            allowed_fact_keys.append(f"{g}.{f}")

        def _has_unit_price(ops_obj: Dict[str, Any]) -> bool:
          try:
            val = (ops_obj or {}).get("unit_price")
          except Exception:
            return False
          if val is None:
            return False
          if isinstance(val, (int, float)):
            return float(val) > 0
          raw = str(val).strip()
          if not raw:
            return False
          try:
            return float(raw) > 0
          except Exception:
            return False

        unit_price_required = _has_unit_price(ops_json)

        required_by_group: Dict[str, List[str]] = {
          "ops": [
            "business.name",
            "ops.unit_name",
            "ops.units_per_week_capacity",
            "ops.starting_revenue",
            "ops.initial_assets",
            "ops.total_debt_outstanding",
            "ops.initial_lease",
            "ops.initial_equity",
            *(("ops.unit_price",) if unit_price_required else ()),
          ],
          "market": [
            "business.name",
            "market.gender_age_intent",
            "market.income_intent",
            *(("ops.unit_price",) if unit_price_required else ()),
          ],
          "people": ["business.name"],
          "financials": [
            "business.name",
            "financials.current_revenue",
            "financials.current_cogs",
            "financials.other_operating_expense",
            "financials.monthly_rent_expense",
            "financials.other_monthly_debt_payments",
            "financials.current_payroll",
            "financials.current_num_employees",
            "financials.current_capex",
            "financials.ar_balance",
            "financials.ap_balance",
            "financials.inventory_balance",
            "financials.total_debt_outstanding",
            "financials.annual_interest_payment",
            "financials.annual_principal_payment",
            "financials.owner_compensation",
            "financials.cash_on_hand",
          ],
        }

        def _needs_upgrade(group: str, text: str) -> bool:
          raw = str(text or "")
          if "{{fact:" not in raw:
            return True
          for k in required_by_group.get(group, []):
            if f"{{{{fact:{k}}}}}" not in raw:
              return True
          return False

        def _upgrade(group: str, text: str) -> str:
          if not text:
            return ""
          if not _needs_upgrade(group, text):
            return text
          return rewrite_summary_as_fact_template(
            text=text,
            shared_context={
              "operating_model": ops_json,
              "target_market": market_json,
              "people_capability": people_json,
              "financials": financials_json,
            },
            business_facts=business_facts,
            required_fact_keys=required_by_group.get(group, []),
            allowed_fact_keys=allowed_fact_keys,
          )

        upgrade_targets = [str(focus or "").strip().lower(), *changed_groups]
        for g in upgrade_targets:
          if g not in summary_by_group:
            continue
          current = summary_by_group.get(g) or ""
          if not current:
            continue
          try:
            upgraded = _upgrade(g, current)
          except Exception:
            upgraded = current
          if upgraded and upgraded != current:
            summary_by_group[g] = upgraded
            if g == "ops":
              ops_json["business_description_summary"] = upgraded
            elif g == "market":
              market_json["target_market_summary"] = upgraded
            elif g == "people":
              people_json["key_people_summary"] = upgraded
            elif g == "financials":
              financials_json["financials_summary"] = upgraded
      except Exception:
        pass

      # If the draft was already marked complete, edits must reopen it and trigger
      # a continued consult so the user can keep refining facts.
      if str(draft_status).strip().lower() == "completed" or focus == "done":
        status_out = "in_progress"
        active_focus_out = (changed_groups[0] if changed_groups else "ops")

      # For edit patches, the intent router is used only to interpret intent and
      # produce the deterministic patch. The domain consultant generates the next
      # conversational turn. Showing both messages causes duplicated acknowledgements
      # and repeated questions.
      #
      # Exception: if the edit re-opens a completed intake into Consistency, keep the
      # router acknowledgement so the user clearly sees the update before the audit.
      assistant_text = router_msg if active_focus_out != focus else ""

      # Always keep the intake moving after edits (no confirmation wait states).
      if False:
        pass
      else:
        # Otherwise, keep the intake moving: acknowledge the edit and then continue
        # with the next question for the current focus (no standstills).
        shared_context_live = dict(shared_context or {})
        shared_context_live["operating_model"] = ops_json
        shared_context_live["target_market"] = market_json
        shared_context_live["people_capability"] = people_json
        shared_context_live["financials"] = financials_json

        intake_context_followup = {
          "client_id": client_id,
          "draft_id": str(draft_id).strip(),
          "business_name": business_facts.get("name"),
          "business_start_date": business_facts.get("start_date"),
          "address": business_facts.get("address"),
          "address_street": payload.get("address_street"),
          "address_city": payload.get("address_city"),
          "address_state": payload.get("address_state"),
          "address_zip": payload.get("address_zip"),
          "address_country": payload.get("address_country"),
          "consumer_type": ops_consumer_type,
          "naics_6": _resolve_naics_6(
            conn=conn, business_type=str((ops_json or {}).get("business_type") or "")
          ),
          "shared_context": shared_context_live,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
        }

        followup_focus = active_focus_out if active_focus_out != "done" else focus

        if followup_focus == "ops":
          followup_turn = consultant_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "market":
          followup_turn = target_market_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "people":
          followup_turn = people_capability_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "financials":
          followup_turn = financials_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        else:
          followup_turn = {"assistant_message": ""}

        followup_outcome = str(followup_turn.get("turn_outcome") or "").strip().upper()
        followup_section_complete = followup_outcome == "SECTION_COMPLETE"

        # If the domain consultant signaled completion, deterministically run the strict
        # finalizer so the user gets the section summary immediately.
        if followup_section_complete and followup_focus in ("ops", "market", "people", "financials"):
          final_messages = [*messages, user_msg]
          intake_context_final = dict(intake_context_followup)
          assistant_final = ""
          try:
            if followup_focus == "ops":
              business_type_candidates = _build_business_type_candidates(conn=conn, messages=final_messages)
              intake_context_final["business_type_candidates"] = business_type_candidates
              final_obj = consultant_finalize(intake_context=intake_context_final, conversation_messages=final_messages)
              if not isinstance(final_obj, dict):
                final_obj = {}
              for k, v in list(final_obj.items()):
                if isinstance(v, str):
                  final_obj[k] = sanitize_fact_template(v)
              summary_text = sanitize_fact_template(str(final_obj.get("assistant_message") or "").strip()) or sanitize_fact_template(
                str(final_obj.get("business_description_summary") or "").strip()
              )
              summary_text = summary_text or "Operational intake complete."
              try:
                summary_text = _upgrade("ops", summary_text)
              except Exception:
                pass
              merged = dict(ops_json or {})
              final_obj.pop("assistant_message", None)
              final_obj.pop("turn_outcome", None)
              for k, v in list(final_obj.items()):
                if k not in merged or merged.get(k) in (None, ""):
                  merged[k] = v
              merged["business_description_summary"] = summary_text
              ops_json = merged
              assistant_final = summary_text
            elif followup_focus == "market":
              consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
              mapping_rows: List[Dict[str, Any]] = []
              if consumer_type != "b2b":
                mapping_rows = _fetch_target_market_mapping_rows(conn)
              final_obj = target_market_finalize(
                intake_context={**intake_context_final, "consumer_type": consumer_type},
                conversation_messages=final_messages,
                mapping_rows=mapping_rows,
              )
              if not isinstance(final_obj, dict):
                final_obj = {}
              for k, v in list(final_obj.items()):
                if isinstance(v, str):
                  final_obj[k] = sanitize_fact_template(v)
              summary_text = sanitize_fact_template(str(final_obj.get("assistant_message") or "").strip()) or sanitize_fact_template(
                str(final_obj.get("target_market_summary") or "").strip()
              )
              summary_text = summary_text or "Target market intake complete."
              try:
                summary_text = _upgrade("market", summary_text)
              except Exception:
                pass
              merged = dict(market_json or {})
              final_obj.pop("assistant_message", None)
              final_obj.pop("turn_outcome", None)
              for k, v in list(final_obj.items()):
                if k not in merged or merged.get(k) in (None, ""):
                  merged[k] = v
              merged["target_market_summary"] = summary_text
              market_json = merged
              assistant_final = _strip_acs_codes(summary_text)
            elif followup_focus == "people":
              final_obj = people_capability_finalize(
                intake_context=intake_context_final, conversation_messages=final_messages
              )
              if not isinstance(final_obj, dict):
                final_obj = {}
              for k, v in list(final_obj.items()):
                if isinstance(v, str):
                  final_obj[k] = sanitize_fact_template(v)
              summary_text = sanitize_fact_template(str(final_obj.get("assistant_message") or "").strip()) or sanitize_fact_template(
                str(final_obj.get("key_people_summary") or "").strip()
              )
              summary_text = summary_text or "People & capability intake complete."
              try:
                summary_text = _upgrade("people", summary_text)
              except Exception:
                pass
              merged = dict(people_json or {})
              final_obj.pop("assistant_message", None)
              final_obj.pop("turn_outcome", None)
              for k, v in list(final_obj.items()):
                if k not in merged or merged.get(k) in (None, ""):
                  merged[k] = v
              merged["key_people_summary"] = summary_text
              people_json = merged
              assistant_final = summary_text
            elif followup_focus == "financials":
              final_obj = financials_finalize(
                intake_context=intake_context_final, conversation_messages=final_messages
              )
              if not isinstance(final_obj, dict):
                final_obj = {}
              for k, v in list(final_obj.items()):
                if isinstance(v, str):
                  final_obj[k] = sanitize_fact_template(v)
              summary_text = sanitize_fact_template(str(final_obj.get("assistant_message") or "").strip()) or sanitize_fact_template(
                str(final_obj.get("financials_summary") or "").strip()
              )
              summary_text = summary_text or "Financials intake complete."
              try:
                summary_text = _upgrade("financials", summary_text)
              except Exception:
                pass
              merged = dict(financials_json or {})
              final_obj.pop("assistant_message", None)
              final_obj.pop("turn_outcome", None)
              for k, v in list(final_obj.items()):
                if k not in merged or merged.get(k) in (None, ""):
                  merged[k] = v
              merged["financials_summary"] = summary_text
              financials_json = merged
              assistant_final = summary_text
          except Exception:
            assistant_final = ""

          assistant_final = sanitize_fact_template(str(assistant_final or "").strip())
          if followup_focus == "market":
            assistant_final = _strip_acs_codes(assistant_final)
          if assistant_final:
            assistant_text = f"{assistant_text}\n\n{assistant_final}".strip() if assistant_text else assistant_final

          # After a section completes, immediately advance and ask the next question (no wait states).
          next_focus_after_final = _compute_focus(
            ops_json=ops_json,
            market_json=market_json,
            marketing_model_json=marketing_model_json,
            people_json=people_json,
            financials_json=financials_json,
          )
          transition_after_final = ""
          if next_focus_after_final == "market":
            transition_after_final = "Great - let's move on to Target Market."
          elif next_focus_after_final == "people":
            transition_after_final = "Great - let's move on to People & Capability."
          elif next_focus_after_final == "financials":
            transition_after_final = "Great - let's move on to Financials."

          if next_focus_after_final == "done":
            completed_out = True
            status_out = "completed"
            active_focus_out = "done"
            completion_msg = 'All sections are complete.\n\nClick "Submit intake" to finish.'
            assistant_text = (
              f"{assistant_text}\n\n{transition_after_final}\n\n{completion_msg}".strip()
              if transition_after_final
              else f"{assistant_text}\n\n{completion_msg}".strip()
            )
          else:
            start_instruction = _start_instruction_for_focus(next_focus_after_final)
            next_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
            next_turn: Dict[str, Any] = {"assistant_message": ""}
            try:
              if next_focus_after_final == "ops":
                next_turn = consultant_chat_turn(
                  intake_context=intake_context_followup, conversation_messages=next_messages
                )
              elif next_focus_after_final == "market":
                if str((market_json or {}).get("target_market_summary") or "").strip() and not _marketing_ready(
                  marketing_model_json
                ):
                  suggestion = _suggest_marketing_budget(ops_json=ops_json)
                  if not any(isinstance(p, dict) and p.get("model") == "marketing" for p in model_card_proposals):
                    proposal_id = f"mk_{int(time.time()*1000)}"
                    model_card_proposals = [
                      *model_card_proposals,
                      {
                        "id": proposal_id,
                        "model": "marketing",
                        "title": "Marketing budget (Year 1)",
                        "updates": [
                          {
                            "key": "monthly_marketing_budget",
                            "value": suggestion.get("monthly_marketing_budget"),
                            "unit": "USD",
                            "time_basis": "month",
                            "rationale": suggestion.get("basis"),
                          },
                          {
                            "key": "primary_channels",
                            "value": suggestion.get("primary_channels"),
                            "unit": None,
                            "time_basis": None,
                            "rationale": "Starting assumption; edit to reflect your actual plan.",
                          },
                        ],
                        "derived": [
                          {
                            "key": "year1_marketing_spend",
                            "value": suggestion.get("year1_marketing_spend"),
                            "unit": "USD",
                            "time_basis": "year",
                            "derivation": "monthly_marketing_budget x 12",
                          }
                        ],
                        "created_at_ms": int(time.time() * 1000),
                      },
                    ]
                    append_messages(
                      conn,
                      draft_id=str(draft_id).strip(),
                      new_messages=[],
                      model_card_proposals=model_card_proposals,
                    )
                  next_turn = marketing_chat_turn(
                    intake_context={**intake_context_followup, "marketing_suggestion": suggestion},
                    conversation_messages=next_messages,
                  )
                else:
                  next_turn = target_market_chat_turn(
                    intake_context=intake_context_followup, conversation_messages=next_messages
                  )
              elif next_focus_after_final == "people":
                next_turn = people_capability_chat_turn(
                  intake_context=intake_context_followup, conversation_messages=next_messages
                )
              elif next_focus_after_final == "financials":
                next_turn = financials_chat_turn(
                  intake_context=intake_context_followup, conversation_messages=next_messages
                )
            except Exception:
              next_turn = {"assistant_message": ""}

            next_text = sanitize_fact_template(str(next_turn.get("assistant_message") or "").strip())
            if next_focus_after_final == "market":
              next_text = _strip_acs_codes(next_text)

            active_focus_out = next_focus_after_final
            if transition_after_final and next_text:
              assistant_text = f"{assistant_text}\n\n{transition_after_final}\n\n{next_text}".strip()
            elif transition_after_final:
              assistant_text = f"{assistant_text}\n\n{transition_after_final}".strip()
            elif next_text:
              assistant_text = f"{assistant_text}\n\n{next_text}".strip()

        followup_text = sanitize_fact_template(str(followup_turn.get("assistant_message") or "").strip())
        if followup_focus == "market":
          followup_text = _strip_acs_codes(followup_text)
        if followup_text:
          if assistant_text:
            assistant_text = f"{assistant_text}\n\n{followup_text}".strip()
          else:
            assistant_text = followup_text

      assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
      if str(active_focus_out or "").strip().lower() == "market":
        assistant_text = _strip_acs_codes(assistant_text)

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json,
        target_market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        active_focus=active_focus_out,
        business_facts=business_facts,
        consistency_passed=consistency_passed_out,
        status=status_out,
        fact_revision_nonce=fact_revision_nonce_out,
        fact_revisions=fact_revisions_out,
        completed=completed_out,
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": active_focus_out,
          "awaiting_confirmation": False,
          "done": bool(active_focus_out == "done"),
          "action": "edit_patch" if active_focus_out != "done" else "consistency_passed",
          "assistant_message": assistant_text,
        }
      )

    # continue_chat: run the current focus consult normally.
    intake_context = {
      "client_id": client_id,
      "draft_id": str(draft_id).strip(),
      "today_iso": date.today().isoformat(),
      "business_name": business_facts.get("name"),
      "business_start_date": business_facts.get("start_date"),
      "address": business_facts.get("address"),
      "address_street": payload.get("address_street"),
      "address_city": payload.get("address_city"),
      "address_state": payload.get("address_state"),
      "address_zip": payload.get("address_zip"),
      "address_country": payload.get("address_country"),
      "consumer_type": ops_consumer_type,
      "naics_6": naics_6,
      "shared_context": shared_context,
      "operating_model_json": ops_json,
      "target_market_json": market_json,
      "people_json": people_json,
      "financials_json": financials_json,
    }

    if focus == "ops":
      turn = consultant_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "market":
      turn = target_market_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "people":
      turn = people_capability_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "financials":
      turn = financials_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    else:
      turn = {"assistant_message": "Continue.", "turn_outcome": "ASK_NEXT"}

    assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
    if focus == "market":
      assistant_text = _strip_acs_codes(assistant_text)

    turn_outcome = str(turn.get("turn_outcome") or "").strip().upper()

    if turn_outcome != "SECTION_COMPLETE":
      if preface:
        assistant_text = f"{preface}\n\n{assistant_text}".strip()
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        active_focus=focus,
        business_facts=business_facts,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": False,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    # Finalize the current focus into structured JSON, then immediately advance.
    # IMPORTANT: do NOT include the chat-turn assistant text in the finalizer context.
    # Some models may output a draft recap with incorrect literals; the strict finalizer
    # should operate only on the conversation + the user's last message to avoid drift.
    final_messages = [*messages, user_msg]

    # Ensure fact-bearing summaries are stored as templates (no stale embedded literals).
    allowed_fact_keys_for_rewrite: List[str] = []
    try:
      for g, fields in (FACT_GROUPS or {}).items():
        for f in list(fields or []):
          allowed_fact_keys_for_rewrite.append(f"{g}.{f}")
    except Exception:
      allowed_fact_keys_for_rewrite = []

    def _has_unit_price(ops_obj: Dict[str, Any]) -> bool:
      try:
        val = (ops_obj or {}).get("unit_price")
      except Exception:
        return False
      if val is None:
        return False
      if isinstance(val, (int, float)):
        return float(val) > 0
      raw = str(val).strip()
      if not raw:
        return False
      try:
        return float(raw) > 0
      except Exception:
        return False

    required_placeholders_by_group: Dict[str, List[str]] = {
      "ops": [
        "business.name",
        "ops.unit_name",
        "ops.units_per_week_capacity",
        "ops.starting_revenue",
        "ops.initial_assets",
        "ops.total_debt_outstanding",
        "ops.initial_lease",
        "ops.initial_equity",
        *(("ops.unit_price",) if _has_unit_price(ops_json) else ()),
      ],
      "market": [
        "business.name",
        "market.gender_age_intent",
        "market.income_intent",
        *(("ops.unit_price",) if _has_unit_price(ops_json) else ()),
      ],
      "people": ["business.name"],
      "financials": [
        "business.name",
        "financials.current_revenue",
        "financials.current_cogs",
        "financials.other_operating_expense",
        "financials.monthly_rent_expense",
        "financials.current_payroll",
        "financials.current_num_employees",
        "financials.owner_compensation",
        "financials.current_capex",
        "financials.cash_on_hand",
        "financials.ar_balance",
        "financials.ap_balance",
        "financials.inventory_balance",
        "financials.total_debt_outstanding",
        "financials.other_monthly_debt_payments",
        "financials.annual_interest_payment",
        "financials.annual_principal_payment",
      ],
    }

    def _upgrade_summary_if_needed(group: str, summary: str) -> str:
      raw = str(summary or "").strip()
      if not raw:
        return raw
      if "{{fact:" not in raw:
        needs = True
      else:
        needs = any(
          f"{{{{fact:{k}}}}}" not in raw for k in required_placeholders_by_group.get(group, [])
        )
      if not needs:
        return raw
      try:
        return rewrite_summary_as_fact_template(
          text=raw,
          shared_context={
            "operating_model": ops_json,
            "target_market": market_json,
            "people_capability": people_json,
            "financials": financials_json,
          },
          business_facts=business_facts,
          required_fact_keys=required_placeholders_by_group.get(group, []),
          allowed_fact_keys=allowed_fact_keys_for_rewrite,
        )
      except Exception:
        return raw

    if focus == "ops":
      business_type_candidates = _build_business_type_candidates(conn=conn, messages=final_messages)
      intake_context["business_type_candidates"] = business_type_candidates
      final_obj = consultant_finalize(intake_context=intake_context, conversation_messages=final_messages)
      if not isinstance(final_obj, dict):
        final_obj = {}
      for k, v in list(final_obj.items()):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      summary_text = sanitize_fact_template(str(final_obj.get("assistant_message") or "").strip()) or sanitize_fact_template(
        str(final_obj.get("business_description_summary") or "").strip()
      )
      summary_text = summary_text or "Operational intake complete."
      summary_text = _upgrade_summary_if_needed("ops", summary_text)
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      final_obj["business_description_summary"] = summary_text
      assistant_final = summary_text
      ops_json = final_obj
      market_json_out = None
      people_json_out = None
      financials_json_out = None
    elif focus == "market":
      consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
      mapping_rows: List[Dict[str, Any]] = []
      if consumer_type != "b2b":
        mapping_rows = _fetch_target_market_mapping_rows(conn)
      final_obj = target_market_finalize(
        intake_context={**intake_context, "consumer_type": consumer_type},
        conversation_messages=final_messages,
        mapping_rows=mapping_rows,
      )

      # Deterministic completeness guard for mixed/B2B flows:
      # In mixed and B2B mode, firmographics must be explicitly captured (not inferred).
      if consumer_type in ("b2b", "mixed"):
        b2b_terms = final_obj.get("b2b_industry_terms")
        b2b_sizes = final_obj.get("b2b_size_bands")
        b2b_ages = final_obj.get("b2b_age_bands")

        missing_question: str | None = None
        if not isinstance(b2b_terms, list) or not any(str(t or "").strip() for t in b2b_terms):
          missing_question = (
            "For your business (company) customers, what kinds of organizations are your ideal ongoing accounts? "
            "A short list is fine (e.g., dealerships, repair/body shops, property managers, fleets)."
          )
        elif not isinstance(b2b_sizes, list) or not b2b_sizes:
          missing_question = (
            "For those business customers, do you care about company size, or are you open to all sizes? "
            "If you do care, tell me the employee-size range you want (for example: 1–49, 50–499, 500+)."
          )
        elif not isinstance(b2b_ages, list) or not b2b_ages:
          missing_question = (
            "For those business customers, do you care how long they’ve been in business, or are you open to all ages? "
            "If you do care, tell me whether you prefer newer companies, established companies, or both."
          )

        if missing_question:
          assistant_text = sanitize_fact_template(str(missing_question).strip())
          assistant_text = _strip_acs_codes(assistant_text)
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
            active_focus=focus,
            business_facts=business_facts,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": focus,
              "awaiting_confirmation": False,
              "done": False,
              "action": "continue",
              "assistant_message": assistant_text,
            }
          )

      if not isinstance(final_obj, dict):
        final_obj = {}
      for k, v in list(final_obj.items()):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      summary_text = sanitize_fact_template(str(final_obj.get("assistant_message") or "").strip()) or sanitize_fact_template(
        str(final_obj.get("target_market_summary") or "").strip()
      )
      summary_text = summary_text or "Target market intake complete."
      summary_text = _upgrade_summary_if_needed("market", summary_text)
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      final_obj["target_market_summary"] = summary_text
      assistant_final = _strip_acs_codes(summary_text)
      market_json = final_obj
      market_json_out = final_obj
      people_json_out = None
      financials_json_out = None
      ops_json_out = None
    elif focus == "people":
      final_obj = people_capability_finalize(intake_context=intake_context, conversation_messages=final_messages)
      if not isinstance(final_obj, dict):
        final_obj = {}
      for k, v in list(final_obj.items()):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      summary_text = sanitize_fact_template(str(final_obj.get("assistant_message") or "").strip()) or sanitize_fact_template(
        str(final_obj.get("key_people_summary") or "").strip()
      )
      summary_text = summary_text or "People & capability intake complete."
      summary_text = _upgrade_summary_if_needed("people", summary_text)
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      final_obj["key_people_summary"] = summary_text
      assistant_final = summary_text
      people_json = final_obj
      people_json_out = final_obj
      market_json_out = None
      financials_json_out = None
      ops_json_out = None
    elif focus == "financials":
      final_obj = financials_finalize(intake_context=intake_context, conversation_messages=final_messages)
      if not isinstance(final_obj, dict):
        final_obj = {}
      for k, v in list(final_obj.items()):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      summary_text = sanitize_fact_template(str(final_obj.get("assistant_message") or "").strip()) or sanitize_fact_template(
        str(final_obj.get("financials_summary") or "").strip()
      )
      summary_text = summary_text or "Financials intake complete."
      summary_text = _upgrade_summary_if_needed("financials", summary_text)
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      final_obj["financials_summary"] = summary_text
      assistant_final = summary_text
      financials_json = final_obj
      financials_json_out = final_obj
      market_json_out = None
      people_json_out = None
      ops_json_out = None
    else:
      assistant_final = assistant_text
      ops_json_out = None
      market_json_out = None
      people_json_out = None
      financials_json_out = None

    assistant_final = sanitize_fact_template(str(assistant_final or "").strip())

    confirmations: Dict[str, bool] | None = None
    if str(focus or "").strip().lower() in ("ops", "market", "people", "financials"):
      confirmations = {str(focus or "").strip().lower(): True}

    next_focus = _compute_focus(
      ops_json=ops_json,
      market_json=market_json,
      marketing_model_json=marketing_model_json,
      people_json=people_json,
      financials_json=financials_json,
    )

    transition = ""
    if next_focus == "market":
      if str((market_json or {}).get("target_market_summary") or "").strip() and not _marketing_ready(
        marketing_model_json
      ):
        transition = "Great - let's lock in Marketing assumptions."
      else:
        transition = "Great - let's move on to Target Market."
    elif next_focus == "people":
      transition = "Great - let's move on to People & Capability."
    elif next_focus == "financials":
      transition = "Great - let's move on to Financials."

    shared_context_live = dict(shared_context or {})
    shared_context_live["operating_model"] = ops_json
    shared_context_live["target_market"] = market_json
    shared_context_live["people_capability"] = people_json
    shared_context_live["financials"] = financials_json

    naics_6_live = _resolve_naics_6(
      conn=conn, business_type=str((ops_json or {}).get("business_type") or "")
    )
    ops_consumer_type_live = str((ops_json or {}).get("consumer_type") or "").strip().lower()
    if ops_consumer_type_live not in ("consumer", "b2b", "mixed"):
      ops_consumer_type_live = "consumer"

    start_instruction = _start_instruction_for_focus(next_focus)
    turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
    intake_context_next = {
      "client_id": client_id,
      "draft_id": str(draft_id).strip(),
      "today_iso": date.today().isoformat(),
      "business_name": business_facts.get("name"),
      "business_start_date": business_facts.get("start_date"),
      "address": business_facts.get("address"),
      "address_street": payload.get("address_street"),
      "address_city": payload.get("address_city"),
      "address_state": payload.get("address_state"),
      "address_zip": payload.get("address_zip"),
      "address_country": payload.get("address_country"),
      "consumer_type": ops_consumer_type_live,
      "naics_6": naics_6_live,
      "shared_context": shared_context_live,
      "operating_model_json": ops_json,
      "target_market_json": market_json,
      "people_json": people_json,
      "financials_json": financials_json,
    }

    next_text = ""
    active_focus_out = next_focus
    status_out: str | None = None
    completed_out = False
    consistency_passed_out = False
    action_out = "continue"

    if next_focus == "done":
      active_focus_out = "done"
      status_out = "completed"
      completed_out = True
      # Legacy field (safe to keep true so older UIs treat the draft as fully complete).
      consistency_passed_out = True
      action_out = "ready_to_submit"
      next_text = 'All sections are complete.\n\nClick "Submit intake" to finish.'
    else:
      next_turn: Dict[str, Any] = {"assistant_message": ""}
      if next_focus == "ops":
        next_turn = consultant_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )
      elif next_focus == "market":
        if str((market_json or {}).get("target_market_summary") or "").strip() and not _marketing_ready(
          marketing_model_json
        ):
          suggestion = _suggest_marketing_budget(ops_json=ops_json)
          if not any(isinstance(p, dict) and p.get("model") == "marketing" for p in model_card_proposals):
            proposal_id = f"mk_{int(time.time()*1000)}"
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": proposal_id,
                "model": "marketing",
                "title": "Marketing budget (Year 1)",
                "updates": [
                  {
                    "key": "monthly_marketing_budget",
                    "value": suggestion.get("monthly_marketing_budget"),
                    "unit": "USD",
                    "time_basis": "month",
                    "rationale": suggestion.get("basis"),
                  },
                  {
                    "key": "primary_channels",
                    "value": suggestion.get("primary_channels"),
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Starting assumption; edit to reflect your actual plan.",
                  },
                ],
                "derived": [
                  {
                    "key": "year1_marketing_spend",
                    "value": suggestion.get("year1_marketing_spend"),
                    "unit": "USD",
                    "time_basis": "year",
                    "derivation": "monthly_marketing_budget x 12",
                  }
                ],
                "created_at_ms": int(time.time() * 1000),
              },
            ]
            append_messages(
              conn,
              draft_id=str(draft_id).strip(),
              new_messages=[],
              model_card_proposals=model_card_proposals,
            )
          next_turn = marketing_chat_turn(
            intake_context={**intake_context_next, "marketing_suggestion": suggestion},
            conversation_messages=turn_messages,
          )
        else:
          next_turn = target_market_chat_turn(
            intake_context=intake_context_next, conversation_messages=turn_messages
          )
      elif next_focus == "people":
        next_turn = people_capability_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )
      elif next_focus == "financials":
        next_turn = financials_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )

      next_text = sanitize_fact_template(str(next_turn.get("assistant_message") or "").strip())
      if next_focus == "market":
        next_text = _strip_acs_codes(next_text)

    assistant_out = "\n\n".join([t for t in (assistant_final, transition, next_text) if str(t or "").strip()]).strip()
    if preface:
      assistant_out = f"{preface}\n\n{assistant_out}".strip()

    append_messages(
      conn,
      draft_id=str(draft_id).strip(),
      new_messages=[user_msg, {"role": "assistant", "content": assistant_out}],
      operating_model_json=ops_json,
      target_market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      confirmations=confirmations,
      active_focus=active_focus_out,
      business_facts=business_facts,
      consistency_passed=consistency_passed_out,
      status=status_out,
      completed=completed_out,
    )

    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft_id).strip(),
        "client_id": client_id,
        "active_focus": active_focus_out,
        "awaiting_confirmation": False,
        "done": bool(active_focus_out == "done"),
        "action": action_out,
        "assistant_message": assistant_out,
      }
    )
  except Exception as exc:
    app.logger.exception("Failed intake consult: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)
  finally:
    try:
      conn.close()
    except Exception:
      pass
