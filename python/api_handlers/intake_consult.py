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


def _is_ack_message(text: str) -> bool:
  raw = " ".join(str(text or "").strip().lower().split())
  if not raw:
    return False
  acknowledgements = {
    "ok",
    "okay",
    "k",
    "kk",
    "yes",
    "y",
    "yep",
    "yeah",
    "sure",
    "sounds good",
    "correct",
    "right",
    "got it",
    "thanks",
    "thank you",
  }
  if raw in acknowledgements:
    return True
  try:
    import re

    return bool(
      re.fullmatch(r"(ok(ay)?|y(es)?|yep|yeah|sure|correct|right|got it|thanks|thank you)[.!?]*", raw)
    )
  except Exception:
    return False


def _marketing_ready(marketing_model_json: Dict[str, Any]) -> bool:
  def _has_value(val: Any) -> bool:
    if val is None:
      return False
    if isinstance(val, str):
      return bool(val.strip())
    if isinstance(val, (int, float)):
      return True
    if isinstance(val, (list, dict)):
      return bool(val)
    return True

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
        ok = isinstance(y1, dict) and _has_value(y1.get("value"))
        if not ok:
          return False
      return True
    derived = marketing_model_json.get("derived") if isinstance(marketing_model_json, dict) else None
    if isinstance(derived, dict) and "year1_marketing_spend" in derived:
      val = derived.get("year1_marketing_spend") or {}
      if isinstance(val, dict) and _has_value(val.get("value")):
        return True
    drivers = marketing_model_json.get("drivers") if isinstance(marketing_model_json, dict) else None
    if isinstance(drivers, dict) and "monthly_marketing_budget" in drivers:
      val = drivers.get("monthly_marketing_budget") or {}
      if isinstance(val, dict) and _has_value(val.get("value")):
        return True
  except Exception:
    return False
  return False

def _milestones_ready(milestones_model_json: Dict[str, Any]) -> bool:
  try:
    if isinstance(milestones_model_json, dict) and isinstance(milestones_model_json.get("lobs"), list):
      lobs = milestones_model_json.get("lobs") or []
      if not lobs:
        return False
      non_company = [
        lob
        for lob in lobs
        if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
      ]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      for lob in requires:
        drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
        ms = drivers.get("milestones")
        if not isinstance(ms, dict):
          return False
        val = ms.get("value")
        if not isinstance(val, list) or not any(isinstance(x, dict) and str(x.get("title") or "").strip() for x in val):
          return False
      return True
    drivers = milestones_model_json.get("drivers") if isinstance(milestones_model_json, dict) else None
    if isinstance(drivers, dict) and "milestones" in drivers:
      ms = drivers.get("milestones") or {}
      if isinstance(ms, dict):
        val = ms.get("value")
        if isinstance(val, list) and any(isinstance(x, dict) and str(x.get("title") or "").strip() for x in val):
          return True
  except Exception:
    return False
  return False

def _headcount_ready(headcount_model_json: Dict[str, Any]) -> bool:
  def _has_value(val: Any) -> bool:
    if val is None:
      return False
    if isinstance(val, str):
      return bool(val.strip())
    if isinstance(val, (int, float)):
      return True
    if isinstance(val, (list, dict)):
      return bool(val)
    return True

  try:
    if isinstance(headcount_model_json, dict) and isinstance(headcount_model_json.get("lobs"), list):
      lobs = headcount_model_json.get("lobs") or []
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
        y1 = derived.get("year1_payroll")
        ok = isinstance(y1, dict) and _has_value(y1.get("value"))
        if not ok:
          return False
      return True
    derived = headcount_model_json.get("derived") if isinstance(headcount_model_json, dict) else None
    if isinstance(derived, dict) and "year1_payroll" in derived:
      val = derived.get("year1_payroll") or {}
      if isinstance(val, dict) and _has_value(val.get("value")):
        return True
  except Exception:
    return False
  return False


def _revenue_ready(revenue_model_json: Dict[str, Any]) -> bool:
  def _has_value(val: Any) -> bool:
    if val is None:
      return False
    if isinstance(val, str):
      return bool(val.strip())
    if isinstance(val, (int, float)):
      return True
    if isinstance(val, (list, dict)):
      return bool(val)
    return True

  try:
    if isinstance(revenue_model_json, dict) and isinstance(revenue_model_json.get("lobs"), list):
      lobs = revenue_model_json.get("lobs") or []
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
        y1 = derived.get("year1_revenue")
        ok = isinstance(y1, dict) and _has_value(y1.get("value"))
        if not ok:
          return False
      return True
    derived = revenue_model_json.get("derived") if isinstance(revenue_model_json, dict) else None
    if isinstance(derived, dict) and "year1_revenue" in derived:
      val = derived.get("year1_revenue") or {}
      if isinstance(val, dict) and _has_value(val.get("value")):
        return True
  except Exception:
    return False
  return False


def _model_has_required_drivers(model_json: Dict[str, Any], required_keys: Tuple[str, ...]) -> bool:
  def _has_value(val: Any) -> bool:
    if val is None:
      return False
    if isinstance(val, str):
      return bool(val.strip())
    if isinstance(val, (int, float)):
      return True
    if isinstance(val, (list, dict)):
      return bool(val)
    return True

  try:
    if isinstance(model_json, dict) and isinstance(model_json.get("lobs"), list):
      lobs = model_json.get("lobs") or []
      if not lobs:
        return False
      non_company = [
        lob
        for lob in lobs
        if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
      ]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      for lob in requires:
        drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
        for k in required_keys:
          dv = drivers.get(k)
          if not (isinstance(dv, dict) and _has_value(dv.get("value"))):
            return False
      return True
    drivers = model_json.get("drivers") if isinstance(model_json, dict) else None
    if isinstance(drivers, dict):
      for k in required_keys:
        dv = drivers.get(k)
        if not (isinstance(dv, dict) and _has_value(dv.get("value"))):
          return False
      return True
  except Exception:
    return False
  return False


def _target_market_data_ready(*, market_json: Dict[str, Any], consumer_type: str) -> bool:
  ct = str(consumer_type or "").strip().lower()
  if ct not in ("consumer", "b2b", "mixed"):
    ct = "consumer"

  def _nonempty_str(key: str) -> bool:
    return bool(str((market_json or {}).get(key) or "").strip())

  if ct in ("consumer", "mixed"):
    if not _nonempty_str("gender_age_intent"):
      return False
    if not _nonempty_str("income_intent"):
      return False
    selections = (market_json or {}).get("selections")
    if not isinstance(selections, list) or not selections:
      return False

  if ct in ("b2b", "mixed"):
    terms = (market_json or {}).get("b2b_industry_terms")
    if not isinstance(terms, list) or not any(str(t or "").strip() for t in terms):
      return False
    sizes = (market_json or {}).get("b2b_size_bands")
    if not isinstance(sizes, list) or not any(str(s or "").strip() for s in sizes):
      return False
    ages = (market_json or {}).get("b2b_age_bands")
    if not isinstance(ages, list) or not any(str(a or "").strip() for a in ages):
      return False

  return True


def _people_data_ready(*, people_json: Dict[str, Any]) -> bool:
  items = (people_json or {}).get("people")
  if not isinstance(items, list) or not items:
    return False
  return any(isinstance(p, dict) and str(p.get("full_name") or "").strip() for p in items)


def _financials_data_ready(*, financials_json: Dict[str, Any]) -> bool:
  required = [
    "current_revenue",
    "current_cogs",
    "other_operating_expense",
    "monthly_rent_expense",
    "other_monthly_debt_payments",
    "current_payroll",
    "current_num_employees",
    "current_capex",
    "ar_balance",
    "ap_balance",
    "inventory_balance",
    "total_debt_outstanding",
    "annual_interest_payment",
    "annual_principal_payment",
    "owner_compensation",
    "cash_on_hand",
  ]
  for k in required:
    if (financials_json or {}).get(k) is None:
      return False
  return True

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
  milestones_model_json: Dict[str, Any],
  revenue_model_json: Dict[str, Any],
  ops_concept_model_json: Dict[str, Any],
  fulfillment_model_json: Dict[str, Any],
  people_json: Dict[str, Any],
  headcount_model_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> str:
  def _has_nonempty(obj: Dict[str, Any], key: str) -> bool:
    try:
      return bool(str((obj or {}).get(key) or "").strip())
    except Exception:
      return False

  def _target_market_ready(*, market_obj: Dict[str, Any], consumer_type: str) -> bool:
    ct = str(consumer_type or "").strip().lower()
    if ct not in ("consumer", "b2b", "mixed"):
      ct = "consumer"

    def _nonempty_str(k: str) -> bool:
      return bool(str((market_obj or {}).get(k) or "").strip())

    if ct in ("consumer", "mixed"):
      if not _nonempty_str("gender_age_intent"):
        return False
      if not _nonempty_str("income_intent"):
        return False
      selections = market_obj.get("selections")
      if not isinstance(selections, list) or not selections:
        return False

    if ct in ("b2b", "mixed"):
      terms = market_obj.get("b2b_industry_terms")
      if not isinstance(terms, list) or not any(str(t or "").strip() for t in terms):
        return False
      sizes = market_obj.get("b2b_size_bands")
      if not isinstance(sizes, list) or not any(str(s or "").strip() for s in sizes):
        return False
      ages = market_obj.get("b2b_age_bands")
      if not isinstance(ages, list) or not any(str(a or "").strip() for a in ages):
        return False

    return True

  def _people_ready(*, people_obj: Dict[str, Any]) -> bool:
    items = people_obj.get("people")
    if not isinstance(items, list) or not items:
      return False
    return any(isinstance(p, dict) and str(p.get("full_name") or "").strip() for p in items)

  def _financials_ready(*, fin_obj: Dict[str, Any]) -> bool:
    required = [
      "current_revenue",
      "current_cogs",
      "other_operating_expense",
      "monthly_rent_expense",
      "other_monthly_debt_payments",
      "current_payroll",
      "current_num_employees",
      "current_capex",
      "ar_balance",
      "ap_balance",
      "inventory_balance",
      "total_debt_outstanding",
      "annual_interest_payment",
      "annual_principal_payment",
      "owner_compensation",
      "cash_on_hand",
    ]
    for k in required:
      if fin_obj.get(k) is None:
        return False
    return True

  def _model_has_driver(card: Dict[str, Any], *, keys: Tuple[str, ...]) -> bool:
    try:
      lobs = card.get("lobs") if isinstance(card, dict) else None
      if isinstance(lobs, list) and lobs:
        non_company = [l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"]
        requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
        for lob in requires:
          drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
          if not all(str((drivers.get(k) or {}).get("value") or "").strip() for k in keys):
            return False
        return True
      drivers = card.get("drivers") if isinstance(card, dict) else None
      if isinstance(drivers, dict):
        return all(str((drivers.get(k) or {}).get("value") or "").strip() for k in keys)
    except Exception:
      return False
    return False

  def _revenue_ready(card: Dict[str, Any]) -> bool:
    try:
      lobs = card.get("lobs") if isinstance(card, dict) else None
      if isinstance(lobs, list) and lobs:
        non_company = [l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"]
        requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
        for lob in requires:
          derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
          y1 = derived.get("year1_revenue")
          if not (isinstance(y1, dict) and str(y1.get("value") or "").strip()):
            return False
        return True
    except Exception:
      return False
    return False

  # IMPORTANT: Section JSON may be partially populated by edit patches.
  # Readiness is based on structured drivers + model cards (summaries are deprecated).
  ops_ready = (
    _has_nonempty(ops_json, "business_type")
    and _has_nonempty(ops_json, "unit_name")
    and _has_nonempty(ops_json, "units_per_week_capacity")
    and _revenue_ready(revenue_model_json)
    and _model_has_driver(fulfillment_model_json, keys=("fulfillment_model", "who_fulfills", "lead_time"))
    and _model_has_driver(ops_concept_model_json, keys=("operating_unit", "primary_constraint", "process_overview"))
    and _milestones_ready(milestones_model_json)
  )

  market_ready = _target_market_ready(
    market_obj=market_json, consumer_type=str((ops_json or {}).get("consumer_type") or "consumer")
  ) and _marketing_ready(marketing_model_json)

  people_ready = _people_ready(people_obj=people_json) and _headcount_ready(headcount_model_json)

  financials_ready = _financials_ready(fin_obj=financials_json)

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


def _propose_marketing_suggestions(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  today_iso: str,
  naics_6: Optional[str],
  consumer_type: str,
  marketing_model_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """
  Proposal-first: let GPT infer + propose marketing drivers (no hard-coded budgets).
  """
  try:
    from model_card_proposer import propose_marketing_suggestions  # type: ignore
  except Exception as exc:
    raise RuntimeError(f"Marketing proposer is unavailable: {exc}")

  lobs: List[Dict[str, str]] = []
  try:
    raw_lobs = marketing_model_json.get("lobs") if isinstance(marketing_model_json, dict) else None
    if isinstance(raw_lobs, list):
      for l in raw_lobs:
        if not isinstance(l, dict):
          continue
        lobs.append(
          {
            "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
            "lob_name": str(l.get("lob_name") or "").strip(),
          }
        )
  except Exception:
    lobs = []

  business_name = str(business_facts.get("name") or "").strip()
  business_type = str((ops_json or {}).get("business_type") or "").strip()
  start_date = str(business_facts.get("start_date") or "").strip() or None

  return propose_marketing_suggestions(
    business_name=business_name,
    business_type=business_type,
    naics_6=naics_6,
    today_iso=today_iso,
    business_start_date=start_date,
    consumer_type=consumer_type,
    ops_json=ops_json,
    target_market_json=market_json,
    shared_context=shared_context,
    lobs=lobs,
  )


def _propose_milestones_suggestions(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  today_iso: str,
  naics_6: Optional[str],
  milestones_model_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """
  Proposal-first: let GPT infer + propose milestone cards (no open-ended 'what milestones?' prompts).
  """
  try:
    from model_card_proposer import propose_milestones_suggestions  # type: ignore
  except Exception as exc:
    raise RuntimeError(f"Milestones proposer is unavailable: {exc}")

  lobs: List[Dict[str, str]] = []
  try:
    raw_lobs = milestones_model_json.get("lobs") if isinstance(milestones_model_json, dict) else None
    if isinstance(raw_lobs, list):
      for l in raw_lobs:
        if not isinstance(l, dict):
          continue
        lobs.append(
          {
            "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
            "lob_name": str(l.get("lob_name") or "").strip(),
          }
        )
  except Exception:
    lobs = []

  business_name = str(business_facts.get("name") or "").strip()
  business_type = str((ops_json or {}).get("business_type") or "").strip()
  start_date = str(business_facts.get("start_date") or "").strip() or None

  return propose_milestones_suggestions(
    business_name=business_name,
    business_type=business_type,
    naics_6=naics_6,
    today_iso=today_iso,
    business_start_date=start_date,
    ops_json=ops_json,
    shared_context=shared_context,
    lobs=lobs,
  )


def _propose_revenue_suggestions(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  today_iso: str,
  naics_6: Optional[str],
  revenue_model_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """
  Proposal-first: let GPT infer + propose revenue model drivers (capacity/utilization/weeks/price).
  """
  try:
    from model_card_proposer import propose_revenue_suggestions  # type: ignore
  except Exception as exc:
    raise RuntimeError(f"Revenue proposer is unavailable: {exc}")

  lobs: List[Dict[str, str]] = []
  try:
    raw_lobs = revenue_model_json.get("lobs") if isinstance(revenue_model_json, dict) else None
    if isinstance(raw_lobs, list):
      for l in raw_lobs:
        if not isinstance(l, dict):
          continue
        lobs.append(
          {
            "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
            "lob_name": str(l.get("lob_name") or "").strip(),
          }
        )
  except Exception:
    lobs = []

  business_name = str(business_facts.get("name") or "").strip()
  business_type = str((ops_json or {}).get("business_type") or "").strip()
  start_date = str(business_facts.get("start_date") or "").strip() or None

  return propose_revenue_suggestions(
    business_name=business_name,
    business_type=business_type,
    naics_6=naics_6,
    today_iso=today_iso,
    business_start_date=start_date,
    ops_json=ops_json,
    shared_context=shared_context,
    lobs=lobs,
  )


def _propose_ops_concept_suggestions(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  today_iso: str,
  naics_6: Optional[str],
  ops_concept_model_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """
  Proposal-first: infer + propose an operating-concept driver card per LOB (conceptual, not a narrative summary).
  """
  try:
    from model_card_proposer import propose_ops_concept_suggestions  # type: ignore
  except Exception as exc:
    raise RuntimeError(f"Ops-concept proposer is unavailable: {exc}")

  lobs: List[Dict[str, str]] = []
  try:
    raw_lobs = ops_concept_model_json.get("lobs") if isinstance(ops_concept_model_json, dict) else None
    if isinstance(raw_lobs, list):
      for l in raw_lobs:
        if not isinstance(l, dict):
          continue
        lobs.append(
          {
            "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
            "lob_name": str(l.get("lob_name") or "").strip(),
          }
        )
  except Exception:
    lobs = []

  business_name = str(business_facts.get("name") or "").strip()
  business_type = str((ops_json or {}).get("business_type") or "").strip()
  start_date = str(business_facts.get("start_date") or "").strip() or None

  return propose_ops_concept_suggestions(
    business_name=business_name,
    business_type=business_type,
    naics_6=naics_6,
    today_iso=today_iso,
    business_start_date=start_date,
    ops_json=ops_json,
    shared_context=shared_context,
    lobs=lobs,
  )


def _propose_fulfillment_suggestions(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  today_iso: str,
  naics_6: Optional[str],
  fulfillment_model_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """
  Proposal-first: infer + propose a fulfillment model driver card per LOB.
  """
  try:
    from model_card_proposer import propose_fulfillment_suggestions  # type: ignore
  except Exception as exc:
    raise RuntimeError(f"Fulfillment proposer is unavailable: {exc}")

  lobs: List[Dict[str, str]] = []
  try:
    raw_lobs = fulfillment_model_json.get("lobs") if isinstance(fulfillment_model_json, dict) else None
    if isinstance(raw_lobs, list):
      for l in raw_lobs:
        if not isinstance(l, dict):
          continue
        lobs.append(
          {
            "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
            "lob_name": str(l.get("lob_name") or "").strip(),
          }
        )
  except Exception:
    lobs = []

  business_name = str(business_facts.get("name") or "").strip()
  business_type = str((ops_json or {}).get("business_type") or "").strip()
  start_date = str(business_facts.get("start_date") or "").strip() or None

  return propose_fulfillment_suggestions(
    business_name=business_name,
    business_type=business_type,
    naics_6=naics_6,
    today_iso=today_iso,
    business_start_date=start_date,
    ops_json=ops_json,
    shared_context=shared_context,
    lobs=lobs,
  )


def _propose_headcount_suggestions(
  *,
  conn,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  today_iso: str,
  naics_6: Optional[str],
  headcount_model_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """
  Proposal-first: let GPT infer + propose headcount roles, then enrich pay rates from the wages dataset.
  """
  try:
    from model_card_proposer import propose_headcount_suggestions  # type: ignore
    from wage_lookup import enrich_headcount_roles, normalize_state_code  # type: ignore
  except Exception as exc:
    raise RuntimeError(f"Headcount proposer is unavailable: {exc}")

  lobs: List[Dict[str, str]] = []
  try:
    raw_lobs = headcount_model_json.get("lobs") if isinstance(headcount_model_json, dict) else None
    if isinstance(raw_lobs, list):
      for l in raw_lobs:
        if not isinstance(l, dict):
          continue
        lobs.append(
          {
            "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
            "lob_name": str(l.get("lob_name") or "").strip(),
          }
        )
  except Exception:
    lobs = []

  business_name = str(business_facts.get("name") or "").strip()
  business_type = str((ops_json or {}).get("business_type") or "").strip()
  start_date = str(business_facts.get("start_date") or "").strip() or None

  base = propose_headcount_suggestions(
    business_name=business_name,
    business_type=business_type,
    naics_6=naics_6,
    today_iso=today_iso,
    business_start_date=start_date,
    ops_json=ops_json,
    people_json=people_json,
    shared_context=shared_context,
    lobs=lobs,
  )

  state_code = normalize_state_code(business_facts.get("address_state"))
  enriched_out: List[Dict[str, Any]] = []
  for s in base:
    if not isinstance(s, dict):
      continue
    roles = s.get("roles")
    if not isinstance(roles, list) or not roles:
      continue
    roles_enriched, total = enrich_headcount_roles(
      conn=conn,
      roles=roles,
      state_code=state_code,
      state_name=None,
      naics_6=naics_6,
    )
    enriched_out.append(
      {
        **s,
        "roles_enriched": roles_enriched,
        "year1_payroll": float(total),
      }
    )

  return enriched_out or []


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
        "milestones_model_json": draft.get("milestones_model_json"),
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
    from fact_templates import sanitize_fact_template  # type: ignore
    from intent_router import route_intent  # type: ignore

    from intake_consultant import consultant_chat_turn, consultant_finalize  # type: ignore
    from target_market_consultant import target_market_chat_turn, target_market_finalize  # type: ignore
    from marketing_consultant import marketing_chat_turn  # type: ignore
    from milestones_consultant import milestones_chat_turn  # type: ignore
    from headcount_consultant import headcount_chat_turn  # type: ignore
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
    revenue_model_json = _parse_json_dict(consult.get("revenue_model_json"))
    ops_concept_model_json = _parse_json_dict(consult.get("ops_concept_model_json"))
    fulfillment_model_json = _parse_json_dict(consult.get("fulfillment_model_json"))
    headcount_model_json = _parse_json_dict(consult.get("headcount_model_json"))
    milestones_model_json = _parse_json_dict(consult.get("milestones_model_json"))
    model_card_proposals = _parse_json_list(consult.get("model_card_proposals_json"))

    # One-time safe backfill: older drafts may still carry legacy narrative summaries.
    # Summaries are deprecated end-to-end and should never reappear in the UI.
    try:
      legacy_changed = False
      if isinstance(ops_json, dict) and ops_json.get("business_description_summary"):
        ops_json["business_description_summary"] = None
        legacy_changed = True
      if isinstance(market_json, dict) and market_json.get("target_market_summary"):
        market_json["target_market_summary"] = None
        legacy_changed = True
      if isinstance(people_json, dict) and people_json.get("key_people_summary"):
        people_json["key_people_summary"] = None
        legacy_changed = True
      if isinstance(financials_json, dict) and financials_json.get("financials_summary"):
        financials_json["financials_summary"] = None
        legacy_changed = True
      if legacy_changed:
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[],
          operating_model_json=ops_json,
          target_market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
        )
    except Exception:
      pass

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
      milestones_model_json=milestones_model_json,
      revenue_model_json=revenue_model_json,
      ops_concept_model_json=ops_concept_model_json,
      fulfillment_model_json=fulfillment_model_json,
      people_json=people_json,
      headcount_model_json=headcount_model_json,
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
        revenue_model_json = _ensure_lob_model_card(revenue_model_json or {}, lobs)
        headcount_model_json = _ensure_lob_model_card(headcount_model_json or {}, lobs)
        fulfillment_model_json = _ensure_lob_model_card(fulfillment_model_json or {}, lobs)
        milestones_model_json = _ensure_lob_model_card(milestones_model_json or {}, lobs)
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[],
          ops_concept_model_json=ops_concept_model_json,
          marketing_model_json=marketing_model_json,
          revenue_model_json=revenue_model_json,
          headcount_model_json=headcount_model_json,
          fulfillment_model_json=fulfillment_model_json,
          milestones_model_json=milestones_model_json,
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

      # People headcount pending: show proposal-first model card prompt (no extra chat questions).
      if (
        str(focus or "").strip().lower() == "people"
        and _people_data_ready(people_json=people_json)
        and not _headcount_ready(headcount_model_json)
      ):
        suggestions: List[Dict[str, Any]] = []
        try:
          suggestions = _propose_headcount_suggestions(
            conn=conn,
            business_facts=business_facts,
            ops_json=ops_json,
            people_json=people_json,
            shared_context=shared_context,
            today_iso=date.today().isoformat(),
            naics_6=naics_6,
            headcount_model_json=headcount_model_json,
          )
        except Exception:
          suggestions = []

        existing_lobs = {
          str(p.get("lob_key") or "").strip()
          for p in model_card_proposals
          if isinstance(p, dict) and p.get("model") == "headcount"
        }
        now_ms = int(time.time() * 1000)
        for s in suggestions:
          lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
          if lob_key and lob_key in existing_lobs:
            continue
          proposal_id = f"hc_{now_ms}_{len(model_card_proposals)+1}"
          model_card_proposals = [
            *model_card_proposals,
            {
              "id": proposal_id,
              "model": "headcount",
              "title": "Headcount (Year 1 payroll)",
              "lob_key": lob_key or None,
              "lob_name": s.get("lob_name"),
              "updates": [
                {
                  "key": "roles",
                  "value": s.get("roles_enriched") if isinstance(s.get("roles_enriched"), list) else [],
                  "unit": None,
                  "time_basis": None,
                  "rationale": str(s.get("basis") or "").strip() or "Proposed Year-1 staffing plan; edit roles/counts as needed.",
                }
              ],
              "derived": [
                {
                  "key": "year1_payroll",
                  "value": s.get("year1_payroll"),
                  "unit": "USD",
                  "time_basis": "year",
                  "derivation": "sum(employee_count × hourly_rate × hours_per_week × weeks_per_year)",
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
            headcount_chat_turn(
              intake_context={**intake_context, "headcount_suggestions": suggestions},
              conversation_messages=turn_messages,
            ).get("assistant_message")
            or ""
          ).strip()
        )
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[{"role": "assistant", "content": assistant_text}],
          active_focus="people",
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "people",
            "awaiting_confirmation": False,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

      # Ops model-card gating (proposal-first, no summaries, no typed yes/no):
      # revenue -> fulfillment -> ops concept -> milestones.
      if str(focus or "").strip().lower() == "ops":
        try:
          from revenue_consultant import revenue_chat_turn  # type: ignore
          from fulfillment_consultant import fulfillment_chat_turn  # type: ignore
          from ops_concept_consultant import ops_concept_chat_turn  # type: ignore
        except Exception:
          revenue_chat_turn = None  # type: ignore
          fulfillment_chat_turn = None  # type: ignore
          ops_concept_chat_turn = None  # type: ignore

        ops_has_min_for_models = bool(str((ops_json or {}).get("business_type") or "").strip()) and bool(
          str((ops_json or {}).get("unit_name") or "").strip()
        )

        # 1) Revenue model card (editable drivers + immediate recompute).
        if ops_has_min_for_models and not _revenue_ready(revenue_model_json) and revenue_chat_turn:
          suggestions: List[Dict[str, Any]] = []
          try:
            suggestions = _propose_revenue_suggestions(
              business_facts=business_facts,
              ops_json=ops_json,
              shared_context=shared_context,
              today_iso=date.today().isoformat(),
              naics_6=naics_6,
              revenue_model_json=revenue_model_json,
            )
          except Exception:
            suggestions = []

          existing_lobs = {
            str(p.get("lob_key") or "").strip()
            for p in model_card_proposals
            if isinstance(p, dict) and p.get("model") == "revenue"
          }
          now_ms = int(time.time() * 1000)
          for s in suggestions:
            lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
            if lob_key and lob_key in existing_lobs:
              continue
            proposal_id = f"rev_{now_ms}_{len(model_card_proposals)+1}"
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": proposal_id,
                "model": "revenue",
                "title": "Revenue (Year 1 model)",
                "lob_key": lob_key or None,
                "lob_name": s.get("lob_name"),
                "updates": [
                  {
                    "key": "units_per_week_capacity",
                    "value": s.get("units_per_week_capacity"),
                    "unit": str((ops_json or {}).get("unit_name") or "").strip() or "units",
                    "time_basis": "week",
                    "rationale": str(s.get("basis") or "").strip() or "Proposed capacity anchor.",
                  },
                  {
                    "key": "avg_units_per_week_year1",
                    "value": s.get("avg_units_per_week_year1"),
                    "unit": str((ops_json or {}).get("unit_name") or "").strip() or "units",
                    "time_basis": "week",
                    "rationale": "Proposed Year-1 average volume (reflects ramp). Edit if needed.",
                  },
                  {
                    "key": "utilization_rate",
                    "value": (
                      (float(s.get("avg_units_per_week_year1")) / float(s.get("units_per_week_capacity")))
                      if (s.get("avg_units_per_week_year1") is not None and s.get("units_per_week_capacity"))
                      else None
                    ),
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Year-1 average utilization (editable).",
                  },
                  {
                    "key": "operating_weeks_per_year",
                    "value": s.get("operating_weeks_per_year"),
                    "unit": "weeks",
                    "time_basis": "year",
                    "rationale": "Proposed operating weeks (edit for seasonality/closures).",
                  },
                  {
                    "key": "unit_price",
                    "value": s.get("unit_price"),
                    "unit": "USD",
                    "time_basis": "per_unit",
                    "rationale": "Proposed average price per unit (edit if your pricing differs).",
                  },
                ],
                "derived": [],
                "created_at_ms": now_ms,
              },
            ]
            existing_lobs.add(lob_key)

          if suggestions:
            append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)

          assistant_text = sanitize_fact_template(
            str(
              revenue_chat_turn(
                intake_context={**intake_context, "revenue_suggestion": (suggestions[0] if suggestions else {})},
                conversation_messages=turn_messages,
              ).get("assistant_message")
              or ""
            ).strip()
          )
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=[{"role": "assistant", "content": assistant_text}],
            active_focus="ops",
            business_facts=business_facts,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": "ops",
              "awaiting_confirmation": False,
              "done": False,
              "action": "continue",
              "assistant_message": assistant_text,
            }
          )

        # 2) Fulfillment model card (conceptual ops reality).
        if ops_has_min_for_models and _revenue_ready(revenue_model_json) and not _model_has_required_drivers(
          fulfillment_model_json, ("fulfillment_model", "who_fulfills", "lead_time")
        ) and fulfillment_chat_turn:
          suggestions: List[Dict[str, Any]] = []
          try:
            suggestions = _propose_fulfillment_suggestions(
              business_facts=business_facts,
              ops_json=ops_json,
              shared_context=shared_context,
              today_iso=date.today().isoformat(),
              naics_6=naics_6,
              fulfillment_model_json=fulfillment_model_json,
            )
          except Exception:
            suggestions = []

          existing_lobs = {
            str(p.get("lob_key") or "").strip()
            for p in model_card_proposals
            if isinstance(p, dict) and p.get("model") == "fulfillment"
          }
          now_ms = int(time.time() * 1000)
          for s in suggestions:
            lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
            if lob_key and lob_key in existing_lobs:
              continue
            proposal_id = f"ful_{now_ms}_{len(model_card_proposals)+1}"
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": proposal_id,
                "model": "fulfillment",
                "title": "Fulfillment model",
                "lob_key": lob_key or None,
                "lob_name": s.get("lob_name"),
                "updates": [
                  {
                    "key": "fulfillment_model",
                    "value": s.get("fulfillment_model"),
                    "unit": None,
                    "time_basis": None,
                    "rationale": str(s.get("basis") or "").strip(),
                  },
                  {
                    "key": "who_fulfills",
                    "value": s.get("who_fulfills"),
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Who performs fulfillment day-to-day.",
                  },
                  {
                    "key": "lead_time",
                    "value": s.get("lead_time"),
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Typical timing/lead time assumption.",
                  },
                ],
                "derived": [],
                "created_at_ms": now_ms,
              },
            ]
            existing_lobs.add(lob_key)

          if suggestions:
            append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)

          assistant_text = sanitize_fact_template(
            str(
              fulfillment_chat_turn(
                intake_context={**intake_context, "fulfillment_suggestion": (suggestions[0] if suggestions else {})},
                conversation_messages=turn_messages,
              ).get("assistant_message")
              or ""
            ).strip()
          )
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=[{"role": "assistant", "content": assistant_text}],
            active_focus="ops",
            business_facts=business_facts,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": "ops",
              "awaiting_confirmation": False,
              "done": False,
              "action": "continue",
              "assistant_message": assistant_text,
            }
          )

        # 3) Ops concept model card.
        if ops_has_min_for_models and _revenue_ready(revenue_model_json) and not _model_has_required_drivers(
          ops_concept_model_json, ("operating_unit", "primary_constraint", "process_overview")
        ) and ops_concept_chat_turn:
          suggestions: List[Dict[str, Any]] = []
          try:
            suggestions = _propose_ops_concept_suggestions(
              business_facts=business_facts,
              ops_json=ops_json,
              shared_context=shared_context,
              today_iso=date.today().isoformat(),
              naics_6=naics_6,
              ops_concept_model_json=ops_concept_model_json,
            )
          except Exception:
            suggestions = []

          existing_lobs = {
            str(p.get("lob_key") or "").strip()
            for p in model_card_proposals
            if isinstance(p, dict) and p.get("model") == "ops_concept"
          }
          now_ms = int(time.time() * 1000)
          for s in suggestions:
            lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
            if lob_key and lob_key in existing_lobs:
              continue
            proposal_id = f"ops_{now_ms}_{len(model_card_proposals)+1}"
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": proposal_id,
                "model": "ops_concept",
                "title": "Operating concept",
                "lob_key": lob_key or None,
                "lob_name": s.get("lob_name"),
                "updates": [
                  {
                    "key": "operating_unit",
                    "value": s.get("operating_unit"),
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Scoped operating unit for this LOB.",
                  },
                  {
                    "key": "primary_constraint",
                    "value": s.get("primary_constraint"),
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Primary constraint/bottleneck assumption.",
                  },
                  {
                    "key": "process_overview",
                    "value": s.get("process_overview"),
                    "unit": None,
                    "time_basis": None,
                    "rationale": str(s.get("basis") or "").strip(),
                  },
                ],
                "derived": [],
                "created_at_ms": now_ms,
              },
            ]
            existing_lobs.add(lob_key)

          if suggestions:
            append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)

          assistant_text = sanitize_fact_template(
            str(
              ops_concept_chat_turn(
                intake_context={**intake_context, "ops_concept_suggestion": (suggestions[0] if suggestions else {})},
                conversation_messages=turn_messages,
              ).get("assistant_message")
              or ""
            ).strip()
          )
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=[{"role": "assistant", "content": assistant_text}],
            active_focus="ops",
            business_facts=business_facts,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": "ops",
              "awaiting_confirmation": False,
              "done": False,
              "action": "continue",
              "assistant_message": assistant_text,
            }
          )

        # 4) Milestones model card (non-spammable; Accept/Edit only).
        if ops_has_min_for_models and _revenue_ready(revenue_model_json) and not _milestones_ready(milestones_model_json):
          suggestions: List[Dict[str, Any]] = []
          try:
            suggestions = _propose_milestones_suggestions(
              business_facts=business_facts,
              ops_json=ops_json,
              shared_context=shared_context,
              today_iso=date.today().isoformat(),
              naics_6=naics_6,
              milestones_model_json=milestones_model_json,
            )
          except Exception:
            suggestions = []

          # LOB anti-spam: if milestones are identical across all LOBs, propose once at company_total
          # and let Accept apply to all LOBs via apply_to_all_lobs.
          apply_to_all_default = False
          try:
            non_company = [
              s
              for s in suggestions
              if isinstance(s, dict) and str(s.get("lob_key") or "").strip() not in ("", "company_total")
            ]
            if len(non_company) > 1:
              def _canon(ms: Any) -> List[tuple[str, str, str]]:
                out: List[tuple[str, str, str]] = []
                if not isinstance(ms, list):
                  return out
                for m in ms:
                  if not isinstance(m, dict):
                    continue
                  title = " ".join(str(m.get("title") or "").split()).strip()
                  desc = " ".join(str(m.get("description") or "").split()).strip()
                  period = " ".join(str(m.get("target_period") or "").split()).strip()
                  if not title and not period and not desc:
                    continue
                  out.append((title, desc, period))
                return out

              first = _canon(non_company[0].get("milestones"))
              if first and all(_canon(s.get("milestones")) == first for s in non_company[1:]):
                suggestions = [{"lob_key": "company_total", "lob_name": None, "milestones": non_company[0].get("milestones")}]
                apply_to_all_default = True
          except Exception:
            apply_to_all_default = False

          existing_lobs = {
            str(p.get("lob_key") or "").strip()
            for p in model_card_proposals
            if isinstance(p, dict) and p.get("model") == "milestones"
          }
          now_ms = int(time.time() * 1000)
          for s in suggestions:
            lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
            if lob_key and lob_key in existing_lobs:
              continue
            proposal_id = f"ms_{now_ms}_{len(model_card_proposals)+1}"
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": proposal_id,
                "model": "milestones",
                "title": "Milestones",
                "lob_key": lob_key or None,
                "lob_name": s.get("lob_name"),
                "apply_to_all_lobs": bool(apply_to_all_default and str(lob_key or "").strip() == "company_total"),
                "updates": [
                  {
                    "key": "milestones",
                    "value": s.get("milestones") if isinstance(s.get("milestones"), list) else [],
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Proposed milestones; edit to reflect your goals and timing.",
                  }
                ],
                "derived": [],
                "created_at_ms": now_ms,
              },
            ]
            existing_lobs.add(lob_key)

          append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)

          assistant_text = sanitize_fact_template(
            str(
              milestones_chat_turn(
                intake_context={**intake_context, "milestones_suggestions": suggestions},
                conversation_messages=turn_messages,
              ).get("assistant_message")
              or ""
            ).strip()
          )
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=[{"role": "assistant", "content": assistant_text}],
            active_focus="ops",
            business_facts=business_facts,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": "ops",
              "awaiting_confirmation": False,
              "done": False,
              "action": "continue",
              "assistant_message": assistant_text,
            }
          )

      turn: Dict[str, Any] = {"assistant_message": "", "turn_outcome": "ASK_NEXT"}
      if focus == "ops":
        turn = consultant_chat_turn(intake_context=intake_context, conversation_messages=turn_messages)
      elif focus == "market":
        if _target_market_data_ready(market_json=market_json, consumer_type=ops_consumer_type) and not _marketing_ready(
          marketing_model_json
        ):
          suggestions: List[Dict[str, Any]] = []
          try:
            suggestions = _propose_marketing_suggestions(
              business_facts=business_facts,
              ops_json=ops_json,
              market_json=market_json,
              shared_context=shared_context,
              today_iso=date.today().isoformat(),
              naics_6=naics_6,
              consumer_type=ops_consumer_type,
              marketing_model_json=marketing_model_json,
            )
          except Exception:
            suggestions = []

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

            # LOB anti-spam: if primary channels are identical across LOBs, propose once at company_total
            # and let Accept apply to all LOBs via apply_to_all_lobs.
            omit_channels_per_lob = False
            try:
              non_company = [
                s
                for s in suggestions
                if isinstance(s, dict) and str(s.get("lob_key") or "").strip() not in ("", "company_total")
              ]
              channels = [str(s.get("primary_channels") or "").strip() for s in non_company]
              channels_norm = [" ".join(c.split()).strip().lower() for c in channels if c]
              has_global_channels = bool(channels_norm) and len(set(channels_norm)) == 1
              has_global_channels_proposal = any(
                isinstance(p, dict)
                and p.get("model") == "marketing"
                and str(p.get("lob_key") or "").strip() == "company_total"
                and any(
                  isinstance(u, dict) and str(u.get("key") or "").strip() == "primary_channels"
                  for u in (p.get("updates") or [])
                )
                for p in model_card_proposals
              )
              if has_global_channels:
                omit_channels_per_lob = True
              if has_global_channels and not has_global_channels_proposal:
                proposal_id = f"mkc_{now_ms}_{len(model_card_proposals)+1}"
                model_card_proposals = [
                  *model_card_proposals,
                  {
                    "id": proposal_id,
                    "model": "marketing",
                    "title": "Primary acquisition channels",
                    "lob_key": "company_total",
                    "lob_name": None,
                    "apply_to_all_lobs": True,
                    "updates": [
                      {
                        "key": "primary_channels",
                        "value": str(non_company[0].get("primary_channels") or "").strip(),
                        "unit": None,
                        "time_basis": None,
                        "rationale": "Same channels across lines of business; edit if a specific LOB differs.",
                      },
                    ],
                    "derived": [],
                    "created_at_ms": now_ms,
                  },
                ]
            except Exception:
              pass

            for s in needs:
              updates = [
                {
                  "key": "monthly_marketing_budget",
                  "value": s.get("monthly_marketing_budget"),
                  "unit": "USD",
                  "time_basis": "month",
                  "rationale": s.get("basis"),
                },
              ]
              if not omit_channels_per_lob:
                updates.append(
                  {
                    "key": "primary_channels",
                    "value": s.get("primary_channels"),
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Starting assumption; edit to reflect your actual plan.",
                  }
                )
              proposal_id = f"mk_{now_ms}_{len(model_card_proposals)+1}"
              model_card_proposals = [
                *model_card_proposals,
                {
                  "id": proposal_id,
                  "model": "marketing",
                  "title": "Marketing budget (Year 1)",
                  "lob_key": s.get("lob_key"),
                  "lob_name": s.get("lob_name"),
                  "updates": updates,
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

    # If a model-card gate is pending, ignore acknowledgement-only chat inputs so we never
    # spam the conversation with repeated "Use the buttons..." assistant messages.
    if _is_ack_message(message):
      pending_gate = False
      if (
        str(focus or "").strip().lower() == "people"
        and _people_data_ready(people_json=people_json)
        and not _headcount_ready(headcount_model_json)
      ):
        pending_gate = True
      elif (
        str(focus or "").strip().lower() == "market"
        and _target_market_data_ready(market_json=market_json, consumer_type=ops_consumer_type)
        and not _marketing_ready(marketing_model_json)
      ):
        pending_gate = True
      elif str(focus or "").strip().lower() == "ops":
        ops_has_min_for_models = bool(str((ops_json or {}).get("business_type") or "").strip()) and bool(
          str((ops_json or {}).get("unit_name") or "").strip()
        )
        if ops_has_min_for_models and (
          (not _revenue_ready(revenue_model_json))
          or (
            not _model_has_required_drivers(
              fulfillment_model_json, ("fulfillment_model", "who_fulfills", "lead_time")
            )
          )
          or (
            not _model_has_required_drivers(
              ops_concept_model_json, ("operating_unit", "primary_constraint", "process_overview")
            )
          )
          or (not _milestones_ready(milestones_model_json))
        ):
          pending_gate = True

      if pending_gate:
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": focus,
            "awaiting_confirmation": False,
            "done": False,
            "action": "noop",
            "assistant_message": "",
          }
        )

    # People headcount pending: do not route through the people consultant; return an Accept/Edit prompt.
    if (
      str(focus or "").strip().lower() == "people"
      and _people_data_ready(people_json=people_json)
      and not _headcount_ready(headcount_model_json)
    ):
      suggestions: List[Dict[str, Any]] = []
      try:
        suggestions = _propose_headcount_suggestions(
          conn=conn,
          business_facts=business_facts,
          ops_json=ops_json,
          people_json=people_json,
          shared_context=shared_context,
          today_iso=date.today().isoformat(),
          naics_6=naics_6,
          headcount_model_json=headcount_model_json,
        )
      except Exception:
        suggestions = []

      existing_lobs = {
        str(p.get("lob_key") or "").strip()
        for p in model_card_proposals
        if isinstance(p, dict) and p.get("model") == "headcount"
      }
      now_ms = int(time.time() * 1000)
      for s in suggestions:
        lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
        if lob_key and lob_key in existing_lobs:
          continue
        proposal_id = f"hc_{now_ms}_{len(model_card_proposals)+1}"
        model_card_proposals = [
          *model_card_proposals,
          {
            "id": proposal_id,
            "model": "headcount",
            "title": "Headcount (Year 1 payroll)",
            "lob_key": lob_key or None,
            "lob_name": s.get("lob_name"),
            "updates": [
              {
                "key": "roles",
                "value": s.get("roles_enriched") if isinstance(s.get("roles_enriched"), list) else [],
                "unit": None,
                "time_basis": None,
                "rationale": str(s.get("basis") or "").strip() or "Proposed Year-1 staffing plan; edit roles/counts as needed.",
              }
            ],
            "derived": [
              {
                "key": "year1_payroll",
                "value": s.get("year1_payroll"),
                "unit": "USD",
                "time_basis": "year",
                "derivation": "sum(employee_count × hourly_rate × hours_per_week × weeks_per_year)",
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
          headcount_chat_turn(
            intake_context={
              "client_id": client_id,
              "draft_id": str(draft_id).strip(),
              "shared_context": shared_context,
              "headcount_suggestions": suggestions,
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
        active_focus="people",
        business_facts=business_facts,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "people",
          "awaiting_confirmation": False,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    # Ops model-card gating (proposal-first, no summaries, no typed yes/no):
    # revenue -> fulfillment -> ops concept -> milestones.
    if str(focus or "").strip().lower() == "ops":
      try:
        from revenue_consultant import revenue_chat_turn  # type: ignore
        from fulfillment_consultant import fulfillment_chat_turn  # type: ignore
        from ops_concept_consultant import ops_concept_chat_turn  # type: ignore
      except Exception:
        revenue_chat_turn = None  # type: ignore
        fulfillment_chat_turn = None  # type: ignore
        ops_concept_chat_turn = None  # type: ignore

      ops_has_min_for_models = bool(str((ops_json or {}).get("business_type") or "").strip()) and bool(
        str((ops_json or {}).get("unit_name") or "").strip()
      )

      # 1) Revenue model card.
      if ops_has_min_for_models and not _revenue_ready(revenue_model_json) and revenue_chat_turn:
        suggestions: List[Dict[str, Any]] = []
        try:
          suggestions = _propose_revenue_suggestions(
            business_facts=business_facts,
            ops_json=ops_json,
            shared_context=shared_context,
            today_iso=date.today().isoformat(),
            naics_6=naics_6,
            revenue_model_json=revenue_model_json,
          )
        except Exception:
          suggestions = []

        existing_lobs = {
          str(p.get("lob_key") or "").strip()
          for p in model_card_proposals
          if isinstance(p, dict) and p.get("model") == "revenue"
        }
        now_ms = int(time.time() * 1000)
        for s in suggestions:
          lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
          if lob_key and lob_key in existing_lobs:
            continue
          proposal_id = f"rev_{now_ms}_{len(model_card_proposals)+1}"
          model_card_proposals = [
            *model_card_proposals,
            {
              "id": proposal_id,
              "model": "revenue",
              "title": "Revenue (Year 1 model)",
              "lob_key": lob_key or None,
              "lob_name": s.get("lob_name"),
              "updates": [
                {
                  "key": "units_per_week_capacity",
                  "value": s.get("units_per_week_capacity"),
                  "unit": str((ops_json or {}).get("unit_name") or "").strip() or "units",
                  "time_basis": "week",
                  "rationale": str(s.get("basis") or "").strip() or "Proposed capacity anchor.",
                },
                {
                  "key": "avg_units_per_week_year1",
                  "value": s.get("avg_units_per_week_year1"),
                  "unit": str((ops_json or {}).get("unit_name") or "").strip() or "units",
                  "time_basis": "week",
                  "rationale": "Proposed Year-1 average volume (reflects ramp). Edit if needed.",
                },
                {
                  "key": "utilization_rate",
                  "value": (
                    (float(s.get("avg_units_per_week_year1")) / float(s.get("units_per_week_capacity")))
                    if (s.get("avg_units_per_week_year1") is not None and s.get("units_per_week_capacity"))
                    else None
                  ),
                  "unit": None,
                  "time_basis": None,
                  "rationale": "Year-1 average utilization (editable).",
                },
                {
                  "key": "operating_weeks_per_year",
                  "value": s.get("operating_weeks_per_year"),
                  "unit": "weeks",
                  "time_basis": "year",
                  "rationale": "Proposed operating weeks (edit for seasonality/closures).",
                },
                {
                  "key": "unit_price",
                  "value": s.get("unit_price"),
                  "unit": "USD",
                  "time_basis": "per_unit",
                  "rationale": "Proposed average price per unit (edit if your pricing differs).",
                },
              ],
              "derived": [],
              "created_at_ms": now_ms,
            },
          ]
          existing_lobs.add(lob_key)

        if suggestions:
          append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)

        assistant_text = sanitize_fact_template(
          str(
            revenue_chat_turn(
              intake_context={
                "client_id": client_id,
                "draft_id": str(draft_id).strip(),
                "shared_context": shared_context,
                "revenue_suggestion": (suggestions[0] if suggestions else {}),
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
          active_focus="ops",
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "ops",
            "awaiting_confirmation": False,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

      # 2) Fulfillment model card.
      if ops_has_min_for_models and _revenue_ready(revenue_model_json) and not _model_has_required_drivers(
        fulfillment_model_json, ("fulfillment_model", "who_fulfills", "lead_time")
      ) and fulfillment_chat_turn:
        suggestions: List[Dict[str, Any]] = []
        try:
          suggestions = _propose_fulfillment_suggestions(
            business_facts=business_facts,
            ops_json=ops_json,
            shared_context=shared_context,
            today_iso=date.today().isoformat(),
            naics_6=naics_6,
            fulfillment_model_json=fulfillment_model_json,
          )
        except Exception:
          suggestions = []

        existing_lobs = {
          str(p.get("lob_key") or "").strip()
          for p in model_card_proposals
          if isinstance(p, dict) and p.get("model") == "fulfillment"
        }
        now_ms = int(time.time() * 1000)
        for s in suggestions:
          lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
          if lob_key and lob_key in existing_lobs:
            continue
          proposal_id = f"ful_{now_ms}_{len(model_card_proposals)+1}"
          model_card_proposals = [
            *model_card_proposals,
            {
              "id": proposal_id,
              "model": "fulfillment",
              "title": "Fulfillment model",
              "lob_key": lob_key or None,
              "lob_name": s.get("lob_name"),
              "updates": [
                {"key": "fulfillment_model", "value": s.get("fulfillment_model"), "unit": None, "time_basis": None, "rationale": str(s.get("basis") or "").strip()},
                {"key": "who_fulfills", "value": s.get("who_fulfills"), "unit": None, "time_basis": None, "rationale": "Who performs fulfillment day-to-day."},
                {"key": "lead_time", "value": s.get("lead_time"), "unit": None, "time_basis": None, "rationale": "Typical timing/lead time assumption."},
              ],
              "derived": [],
              "created_at_ms": now_ms,
            },
          ]
          existing_lobs.add(lob_key)

        if suggestions:
          append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)

        assistant_text = sanitize_fact_template(
          str(
            fulfillment_chat_turn(
              intake_context={
                "client_id": client_id,
                "draft_id": str(draft_id).strip(),
                "shared_context": shared_context,
                "fulfillment_suggestion": (suggestions[0] if suggestions else {}),
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
          active_focus="ops",
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "ops",
            "awaiting_confirmation": False,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

      # 3) Ops concept model card.
      if ops_has_min_for_models and _revenue_ready(revenue_model_json) and not _model_has_required_drivers(
        ops_concept_model_json, ("operating_unit", "primary_constraint", "process_overview")
      ) and ops_concept_chat_turn:
        suggestions: List[Dict[str, Any]] = []
        try:
          suggestions = _propose_ops_concept_suggestions(
            business_facts=business_facts,
            ops_json=ops_json,
            shared_context=shared_context,
            today_iso=date.today().isoformat(),
            naics_6=naics_6,
            ops_concept_model_json=ops_concept_model_json,
          )
        except Exception:
          suggestions = []

        existing_lobs = {
          str(p.get("lob_key") or "").strip()
          for p in model_card_proposals
          if isinstance(p, dict) and p.get("model") == "ops_concept"
        }
        now_ms = int(time.time() * 1000)
        for s in suggestions:
          lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
          if lob_key and lob_key in existing_lobs:
            continue
          proposal_id = f"ops_{now_ms}_{len(model_card_proposals)+1}"
          model_card_proposals = [
            *model_card_proposals,
            {
              "id": proposal_id,
              "model": "ops_concept",
              "title": "Operating concept",
              "lob_key": lob_key or None,
              "lob_name": s.get("lob_name"),
              "updates": [
                {"key": "operating_unit", "value": s.get("operating_unit"), "unit": None, "time_basis": None, "rationale": "Scoped operating unit for this LOB."},
                {"key": "primary_constraint", "value": s.get("primary_constraint"), "unit": None, "time_basis": None, "rationale": "Primary constraint/bottleneck assumption."},
                {"key": "process_overview", "value": s.get("process_overview"), "unit": None, "time_basis": None, "rationale": str(s.get("basis") or "").strip()},
              ],
              "derived": [],
              "created_at_ms": now_ms,
            },
          ]
          existing_lobs.add(lob_key)

        if suggestions:
          append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)

        assistant_text = sanitize_fact_template(
          str(
            ops_concept_chat_turn(
              intake_context={
                "client_id": client_id,
                "draft_id": str(draft_id).strip(),
                "shared_context": shared_context,
                "ops_concept_suggestion": (suggestions[0] if suggestions else {}),
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
          active_focus="ops",
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "ops",
            "awaiting_confirmation": False,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

    # Ops milestones pending: do not route through the ops consultant; return an Accept/Edit prompt.
    if (
      str(focus or "").strip().lower() == "ops"
      and _revenue_ready(revenue_model_json)
      and not _milestones_ready(milestones_model_json)
    ):
      suggestions: List[Dict[str, Any]] = []
      try:
        suggestions = _propose_milestones_suggestions(
          business_facts=business_facts,
          ops_json=ops_json,
          shared_context=shared_context,
          today_iso=date.today().isoformat(),
          naics_6=naics_6,
          milestones_model_json=milestones_model_json,
        )
      except Exception:
        suggestions = []

      # LOB anti-spam: if milestones are identical across all LOBs, propose once at company_total
      # and let Accept apply to all LOBs via apply_to_all_lobs.
      apply_to_all_default = False
      try:
        non_company = [
          s
          for s in suggestions
          if isinstance(s, dict) and str(s.get("lob_key") or "").strip() not in ("", "company_total")
        ]
        if len(non_company) > 1:
          def _canon(ms: Any) -> List[tuple[str, str, str]]:
            out: List[tuple[str, str, str]] = []
            if not isinstance(ms, list):
              return out
            for m in ms:
              if not isinstance(m, dict):
                continue
              title = " ".join(str(m.get("title") or "").split()).strip()
              desc = " ".join(str(m.get("description") or "").split()).strip()
              period = " ".join(str(m.get("target_period") or "").split()).strip()
              if not title and not period and not desc:
                continue
              out.append((title, desc, period))
            return out

          first = _canon(non_company[0].get("milestones"))
          if first and all(_canon(s.get("milestones")) == first for s in non_company[1:]):
            suggestions = [{"lob_key": "company_total", "lob_name": None, "milestones": non_company[0].get("milestones")}]
            apply_to_all_default = True
      except Exception:
        apply_to_all_default = False

      existing_lobs = {
        str(p.get("lob_key") or "").strip()
        for p in model_card_proposals
        if isinstance(p, dict) and p.get("model") == "milestones"
      }
      now_ms = int(time.time() * 1000)
      for s in suggestions:
        lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
        if lob_key and lob_key in existing_lobs:
          continue
        proposal_id = f"ms_{now_ms}_{len(model_card_proposals)+1}"
        model_card_proposals = [
          *model_card_proposals,
          {
            "id": proposal_id,
            "model": "milestones",
            "title": "Milestones",
            "lob_key": lob_key or None,
            "lob_name": s.get("lob_name"),
            "apply_to_all_lobs": bool(apply_to_all_default and str(lob_key or "").strip() == "company_total"),
            "updates": [
              {
                "key": "milestones",
                "value": s.get("milestones") if isinstance(s.get("milestones"), list) else [],
                "unit": None,
                "time_basis": None,
                "rationale": "Proposed milestones; edit to reflect your goals and timing.",
              }
            ],
            "derived": [],
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
          milestones_chat_turn(
            intake_context={
              "client_id": client_id,
              "draft_id": str(draft_id).strip(),
              "shared_context": shared_context,
              "milestones_suggestions": suggestions,
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
        active_focus="ops",
        business_facts=business_facts,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "ops",
          "awaiting_confirmation": False,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    # Market extension: once Target Market is complete, keep Market focus active until Marketing is locked.
    # While Marketing is pending, we show an Accept/Edit proposal and do not route through the target market consultant.
    if (
      str(focus or "").strip().lower() == "market"
      and _target_market_data_ready(market_json=market_json, consumer_type=ops_consumer_type)
      and not _marketing_ready(marketing_model_json)
    ):
      suggestions: List[Dict[str, Any]] = []
      try:
        suggestions = _propose_marketing_suggestions(
          business_facts=business_facts,
          ops_json=ops_json,
          market_json=market_json,
          shared_context=shared_context,
          today_iso=date.today().isoformat(),
          naics_6=naics_6,
          consumer_type=ops_consumer_type,
          marketing_model_json=marketing_model_json,
        )
      except Exception:
        suggestions = []

      existing_lobs = {
        str(p.get("lob_key") or "").strip()
        for p in model_card_proposals
        if isinstance(p, dict) and p.get("model") == "marketing"
      }
      now_ms = int(time.time() * 1000)

      # LOB anti-spam: if primary channels are identical across LOBs, propose once at company_total
      # and let Accept apply to all LOBs via apply_to_all_lobs. Per-LOB budget cards omit channels.
      omit_channels_per_lob = False
      try:
        non_company = [
          s
          for s in suggestions
          if isinstance(s, dict) and str(s.get("lob_key") or "").strip() not in ("", "company_total")
        ]
        channels = [str(s.get("primary_channels") or "").strip() for s in non_company]
        channels_norm = [" ".join(c.split()).strip().lower() for c in channels if c]
        has_global_channels = bool(channels_norm) and len(set(channels_norm)) == 1
        has_global_channels_proposal = any(
          isinstance(p, dict)
          and p.get("model") == "marketing"
          and str(p.get("lob_key") or "").strip() == "company_total"
          and any(
            isinstance(u, dict) and str(u.get("key") or "").strip() == "primary_channels"
            for u in (p.get("updates") or [])
          )
          for p in model_card_proposals
        )
        if has_global_channels:
          omit_channels_per_lob = True
        if has_global_channels and not has_global_channels_proposal:
          proposal_id = f"mkc_{now_ms}_{len(model_card_proposals)+1}"
          model_card_proposals = [
            *model_card_proposals,
            {
              "id": proposal_id,
              "model": "marketing",
              "title": "Primary acquisition channels",
              "lob_key": "company_total",
              "lob_name": None,
              "apply_to_all_lobs": True,
              "updates": [
                {
                  "key": "primary_channels",
                  "value": str(non_company[0].get("primary_channels") or "").strip(),
                  "unit": None,
                  "time_basis": None,
                  "rationale": "Same channels across lines of business; edit if a specific LOB differs.",
                },
              ],
              "derived": [],
              "created_at_ms": now_ms,
            },
          ]
          existing_lobs.add("company_total")
      except Exception:
        pass

      for s in suggestions:
        lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
        if lob_key and lob_key in existing_lobs:
          continue
        updates = [
          {
            "key": "monthly_marketing_budget",
            "value": s.get("monthly_marketing_budget"),
            "unit": "USD",
            "time_basis": "month",
            "rationale": s.get("basis"),
          },
        ]
        if not omit_channels_per_lob:
          updates.append(
            {
              "key": "primary_channels",
              "value": s.get("primary_channels"),
              "unit": None,
              "time_basis": None,
              "rationale": "Starting assumption; edit to reflect your actual plan.",
            }
          )
        proposal_id = f"mk_{now_ms}_{len(model_card_proposals)+1}"
        model_card_proposals = [
          *model_card_proposals,
          {
            "id": proposal_id,
            "model": "marketing",
            "title": "Marketing budget (Year 1)",
            "lob_key": lob_key or None,
            "lob_name": s.get("lob_name"),
            "updates": updates,
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

      # Summaries are deprecated end-to-end; never echo or rewrite them after edits.
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
        # finalizer so we persist structured JSON (no summaries).
        if followup_section_complete and followup_focus in ("ops", "market", "people", "financials"):
          final_messages = [*messages, user_msg]
          intake_context_final = dict(intake_context_followup)
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
              merged = dict(ops_json or {})
              final_obj.pop("assistant_message", None)
              final_obj.pop("turn_outcome", None)
              final_obj.pop("business_description_summary", None)
              for k, v in list(final_obj.items()):
                if k not in merged or merged.get(k) in (None, ""):
                  merged[k] = v
              ops_json = merged
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
              merged = dict(market_json or {})
              final_obj.pop("assistant_message", None)
              final_obj.pop("turn_outcome", None)
              final_obj.pop("target_market_summary", None)
              for k, v in list(final_obj.items()):
                if k not in merged or merged.get(k) in (None, ""):
                  merged[k] = v
              market_json = merged
            elif followup_focus == "people":
              final_obj = people_capability_finalize(
                intake_context=intake_context_final, conversation_messages=final_messages
              )
              if not isinstance(final_obj, dict):
                final_obj = {}
              for k, v in list(final_obj.items()):
                if isinstance(v, str):
                  final_obj[k] = sanitize_fact_template(v)
              merged = dict(people_json or {})
              final_obj.pop("assistant_message", None)
              final_obj.pop("turn_outcome", None)
              final_obj.pop("key_people_summary", None)
              for k, v in list(final_obj.items()):
                if k not in merged or merged.get(k) in (None, ""):
                  merged[k] = v
              people_json = merged
            elif followup_focus == "financials":
              final_obj = financials_finalize(
                intake_context=intake_context_final, conversation_messages=final_messages
              )
              if not isinstance(final_obj, dict):
                final_obj = {}
              for k, v in list(final_obj.items()):
                if isinstance(v, str):
                  final_obj[k] = sanitize_fact_template(v)
              merged = dict(financials_json or {})
              final_obj.pop("assistant_message", None)
              final_obj.pop("turn_outcome", None)
              final_obj.pop("financials_summary", None)
              for k, v in list(final_obj.items()):
                if k not in merged or merged.get(k) in (None, ""):
                  merged[k] = v
              financials_json = merged
          except Exception:
            pass

          # After a section completes, immediately advance and ask the next question (no wait states).
          next_focus_after_final = _compute_focus(
            ops_json=ops_json,
            market_json=market_json,
            marketing_model_json=marketing_model_json,
            milestones_model_json=milestones_model_json,
            revenue_model_json=revenue_model_json,
            ops_concept_model_json=ops_concept_model_json,
            fulfillment_model_json=fulfillment_model_json,
            people_json=people_json,
            headcount_model_json=headcount_model_json,
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
                if _target_market_data_ready(
                  market_json=market_json, consumer_type=ops_consumer_type
                ) and not _marketing_ready(marketing_model_json):
                  suggestions: List[Dict[str, Any]] = []
                  try:
                    suggestions = _propose_marketing_suggestions(
                      business_facts=business_facts,
                      ops_json=ops_json,
                      market_json=market_json,
                      shared_context=shared_context,
                      today_iso=date.today().isoformat(),
                      naics_6=naics_6,
                      consumer_type=ops_consumer_type,
                      marketing_model_json=marketing_model_json,
                    )
                  except Exception:
                    suggestions = []

                  existing_lobs = {
                    str(p.get("lob_key") or "").strip()
                    for p in model_card_proposals
                    if isinstance(p, dict) and p.get("model") == "marketing"
                  }
                  now_ms = int(time.time() * 1000)

                  omit_channels_per_lob = False
                  try:
                    non_company = [
                      s
                      for s in suggestions
                      if isinstance(s, dict) and str(s.get("lob_key") or "").strip() not in ("", "company_total")
                    ]
                    channels = [str(s.get("primary_channels") or "").strip() for s in non_company]
                    channels_norm = [" ".join(c.split()).strip().lower() for c in channels if c]
                    has_global_channels = bool(channels_norm) and len(set(channels_norm)) == 1
                    has_global_channels_proposal = any(
                      isinstance(p, dict)
                      and p.get("model") == "marketing"
                      and str(p.get("lob_key") or "").strip() == "company_total"
                      and any(
                        isinstance(u, dict) and str(u.get("key") or "").strip() == "primary_channels"
                        for u in (p.get("updates") or [])
                      )
                      for p in model_card_proposals
                    )
                    if has_global_channels:
                      omit_channels_per_lob = True
                    if has_global_channels and (not has_global_channels_proposal) and non_company:
                      proposal_id = f"mkc_{now_ms}_{len(model_card_proposals)+1}"
                      model_card_proposals = [
                        *model_card_proposals,
                        {
                          "id": proposal_id,
                          "model": "marketing",
                          "title": "Primary acquisition channels",
                          "lob_key": "company_total",
                          "lob_name": None,
                          "apply_to_all_lobs": True,
                          "updates": [
                            {
                              "key": "primary_channels",
                              "value": str(non_company[0].get("primary_channels") or "").strip(),
                              "unit": None,
                              "time_basis": None,
                              "rationale": "Same channels across lines of business; edit if a specific LOB differs.",
                            },
                          ],
                          "derived": [],
                          "created_at_ms": now_ms,
                        },
                      ]
                      existing_lobs.add("company_total")
                  except Exception:
                    pass

                  for s in suggestions:
                    lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
                    if lob_key and lob_key in existing_lobs:
                      continue
                    updates = [
                      {
                        "key": "monthly_marketing_budget",
                        "value": s.get("monthly_marketing_budget"),
                        "unit": "USD",
                        "time_basis": "month",
                        "rationale": s.get("basis"),
                      },
                    ]
                    if not omit_channels_per_lob:
                      updates.append(
                        {
                          "key": "primary_channels",
                          "value": s.get("primary_channels"),
                          "unit": None,
                          "time_basis": None,
                          "rationale": "Starting assumption; edit to reflect your actual plan.",
                        }
                      )
                    proposal_id = f"mk_{now_ms}_{len(model_card_proposals)+1}"
                    model_card_proposals = [
                      *model_card_proposals,
                      {
                        "id": proposal_id,
                        "model": "marketing",
                        "title": "Marketing budget (Year 1)",
                        "lob_key": lob_key or None,
                        "lob_name": s.get("lob_name"),
                        "updates": updates,
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

                  suggestion = (suggestions[0] if suggestions else {})
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

    # Summaries are deprecated end-to-end; no summary template rewrite is performed.

    if focus == "ops":
      business_type_candidates = _build_business_type_candidates(conn=conn, messages=final_messages)
      intake_context["business_type_candidates"] = business_type_candidates
      final_obj = consultant_finalize(intake_context=intake_context, conversation_messages=final_messages)
      if not isinstance(final_obj, dict):
        final_obj = {}
      for k, v in list(final_obj.items()):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      # Summaries are deprecated: keep legacy fields null so they never render in the UI.
      final_obj["business_description_summary"] = None
      assistant_final = ""
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
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      # Summaries are deprecated: keep legacy fields null so they never render in the UI.
      final_obj["target_market_summary"] = None
      assistant_final = ""
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
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      # Summaries are deprecated: keep legacy fields null so they never render in the UI.
      final_obj["key_people_summary"] = None
      assistant_final = ""
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
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      # Summaries are deprecated: keep legacy fields null so they never render in the UI.
      final_obj["financials_summary"] = None
      assistant_final = ""
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
      milestones_model_json=milestones_model_json,
      revenue_model_json=revenue_model_json,
      ops_concept_model_json=ops_concept_model_json,
      fulfillment_model_json=fulfillment_model_json,
      people_json=people_json,
      headcount_model_json=headcount_model_json,
      financials_json=financials_json,
    )

    transition = ""
    if next_focus == "market":
      if _target_market_data_ready(
        market_json=market_json, consumer_type=str((ops_json or {}).get("consumer_type") or "consumer")
      ) and not _marketing_ready(marketing_model_json):
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
        # Ops gating: if any required Ops model card is pending, show its Accept/Edit prompt
        # instead of restarting the free-text Ops consultant.
        try:
          from revenue_consultant import revenue_chat_turn  # type: ignore
          from fulfillment_consultant import fulfillment_chat_turn  # type: ignore
          from ops_concept_consultant import ops_concept_chat_turn  # type: ignore
        except Exception:
          revenue_chat_turn = None  # type: ignore
          fulfillment_chat_turn = None  # type: ignore
          ops_concept_chat_turn = None  # type: ignore

        now_ms = int(time.time() * 1000)
        if (not _revenue_ready(revenue_model_json)) and revenue_chat_turn:
          # Ensure at least one proposal exists so the UI can Accept/Edit.
          if not any(isinstance(p, dict) and p.get("model") == "revenue" for p in model_card_proposals):
            cap = (ops_json or {}).get("units_per_week_capacity")
            price = (ops_json or {}).get("unit_price")
            y1 = (ops_json or {}).get("starting_revenue")
            avg = None
            try:
              if cap is not None and price not in (None, "", 0) and y1 not in (None, ""):
                avg = float(y1) / float(price) / 52.0
            except Exception:
              avg = None
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": f"rev_{now_ms}",
                "model": "revenue",
                "title": "Revenue (Year 1 model)",
                "lob_key": "company_total",
                "lob_name": None,
                "updates": [
                  {
                    "key": "units_per_week_capacity",
                    "value": cap,
                    "unit": str((ops_json or {}).get("unit_name") or "").strip() or "units",
                    "time_basis": "week",
                    "rationale": "Current busy-week capacity.",
                  },
                  {
                    "key": "avg_units_per_week_year1",
                    "value": avg,
                    "unit": str((ops_json or {}).get("unit_name") or "").strip() or "units",
                    "time_basis": "week",
                    "rationale": "Year-1 average volume (edit if needed).",
                  },
                  {
                    "key": "utilization_rate",
                    "value": (float(avg) / float(cap) if (avg is not None and cap not in (None, "", 0)) else None),
                    "unit": None,
                    "time_basis": None,
                    "rationale": "Year-1 average utilization (editable).",
                  },
                  {
                    "key": "operating_weeks_per_year",
                    "value": 52,
                    "unit": "weeks",
                    "time_basis": "year",
                    "rationale": "Default operating weeks; edit for seasonality/closures.",
                  },
                  {
                    "key": "unit_price",
                    "value": price,
                    "unit": "USD",
                    "time_basis": "per_unit",
                    "rationale": "Average price per unit (synced from pricing).",
                  },
                ],
                "derived": [],
                "created_at_ms": now_ms,
              },
            ]
            append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)
          next_turn = revenue_chat_turn(
            intake_context={**intake_context_next, "revenue_suggestion": {}},
            conversation_messages=turn_messages,
          )
        elif (not _model_has_required_drivers(fulfillment_model_json, ("fulfillment_model", "who_fulfills", "lead_time"))) and fulfillment_chat_turn:
          if not any(isinstance(p, dict) and p.get("model") == "fulfillment" for p in model_card_proposals):
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": f"ful_{now_ms}",
                "model": "fulfillment",
                "title": "Fulfillment model",
                "lob_key": "company_total",
                "lob_name": None,
                "updates": [
                  {"key": "fulfillment_model", "value": None, "unit": None, "time_basis": None, "rationale": "Proposed fulfillment model (edit)."},
                  {"key": "who_fulfills", "value": None, "unit": None, "time_basis": None, "rationale": "Who fulfills day-to-day (edit)."},
                  {"key": "lead_time", "value": None, "unit": None, "time_basis": None, "rationale": "Typical lead time (edit)."},
                ],
                "derived": [],
                "created_at_ms": now_ms,
              },
            ]
            append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)
          next_turn = fulfillment_chat_turn(
            intake_context={**intake_context_next, "fulfillment_suggestion": {}},
            conversation_messages=turn_messages,
          )
        elif (not _model_has_required_drivers(ops_concept_model_json, ("operating_unit", "primary_constraint", "process_overview"))) and ops_concept_chat_turn:
          if not any(isinstance(p, dict) and p.get("model") == "ops_concept" for p in model_card_proposals):
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": f"ops_{now_ms}",
                "model": "ops_concept",
                "title": "Operating concept",
                "lob_key": "company_total",
                "lob_name": None,
                "updates": [
                  {"key": "operating_unit", "value": str((ops_json or {}).get("unit_name") or "").strip() or None, "unit": None, "time_basis": None, "rationale": "Operating unit (edit)."},
                  {"key": "primary_constraint", "value": str((ops_json or {}).get("capacity_driver") or "").strip() or None, "unit": None, "time_basis": None, "rationale": "Primary constraint (edit)."},
                  {"key": "process_overview", "value": None, "unit": None, "time_basis": None, "rationale": "Process overview (edit)."},
                ],
                "derived": [],
                "created_at_ms": now_ms,
              },
            ]
            append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], model_card_proposals=model_card_proposals)
          next_turn = ops_concept_chat_turn(
            intake_context={**intake_context_next, "ops_concept_suggestion": {}},
            conversation_messages=turn_messages,
          )
        elif (not _milestones_ready(milestones_model_json)):
          next_turn = milestones_chat_turn(
            intake_context={**intake_context_next, "milestones_suggestions": []},
            conversation_messages=turn_messages,
          )
        else:
          next_turn = consultant_chat_turn(
            intake_context=intake_context_next, conversation_messages=turn_messages
          )
      elif next_focus == "market":
        if _target_market_data_ready(
          market_json=market_json, consumer_type=str((ops_json or {}).get("consumer_type") or "consumer")
        ) and not _marketing_ready(marketing_model_json):
          suggestions: List[Dict[str, Any]] = []
          try:
            suggestions = _propose_marketing_suggestions(
              business_facts=business_facts,
              ops_json=ops_json,
              market_json=market_json,
              shared_context=shared_context,
              today_iso=date.today().isoformat(),
              naics_6=naics_6,
              consumer_type=ops_consumer_type,
              marketing_model_json=marketing_model_json,
            )
          except Exception:
            suggestions = []

          existing_lobs = {
            str(p.get("lob_key") or "").strip()
            for p in model_card_proposals
            if isinstance(p, dict) and p.get("model") == "marketing"
          }
          now_ms = int(time.time() * 1000)

          omit_channels_per_lob = False
          try:
            non_company = [
              s
              for s in suggestions
              if isinstance(s, dict) and str(s.get("lob_key") or "").strip() not in ("", "company_total")
            ]
            channels = [str(s.get("primary_channels") or "").strip() for s in non_company]
            channels_norm = [" ".join(c.split()).strip().lower() for c in channels if c]
            has_global_channels = bool(channels_norm) and len(set(channels_norm)) == 1
            has_global_channels_proposal = any(
              isinstance(p, dict)
              and p.get("model") == "marketing"
              and str(p.get("lob_key") or "").strip() == "company_total"
              and any(
                isinstance(u, dict) and str(u.get("key") or "").strip() == "primary_channels"
                for u in (p.get("updates") or [])
              )
              for p in model_card_proposals
            )
            if has_global_channels:
              omit_channels_per_lob = True
            if has_global_channels and (not has_global_channels_proposal) and non_company:
              proposal_id = f"mkc_{now_ms}_{len(model_card_proposals)+1}"
              model_card_proposals = [
                *model_card_proposals,
                {
                  "id": proposal_id,
                  "model": "marketing",
                  "title": "Primary acquisition channels",
                  "lob_key": "company_total",
                  "lob_name": None,
                  "apply_to_all_lobs": True,
                  "updates": [
                    {
                      "key": "primary_channels",
                      "value": str(non_company[0].get("primary_channels") or "").strip(),
                      "unit": None,
                      "time_basis": None,
                      "rationale": "Same channels across lines of business; edit if a specific LOB differs.",
                    },
                  ],
                  "derived": [],
                  "created_at_ms": now_ms,
                },
              ]
              existing_lobs.add("company_total")
          except Exception:
            pass

          for s in suggestions:
            lob_key = str(s.get("lob_key") or "").strip() or ("company_total" if len(suggestions) == 1 else "")
            if lob_key and lob_key in existing_lobs:
              continue
            updates = [
              {
                "key": "monthly_marketing_budget",
                "value": s.get("monthly_marketing_budget"),
                "unit": "USD",
                "time_basis": "month",
                "rationale": s.get("basis"),
              },
            ]
            if not omit_channels_per_lob:
              updates.append(
                {
                  "key": "primary_channels",
                  "value": s.get("primary_channels"),
                  "unit": None,
                  "time_basis": None,
                  "rationale": "Starting assumption; edit to reflect your actual plan.",
                }
              )
            proposal_id = f"mk_{now_ms}_{len(model_card_proposals)+1}"
            model_card_proposals = [
              *model_card_proposals,
              {
                "id": proposal_id,
                "model": "marketing",
                "title": "Marketing budget (Year 1)",
                "lob_key": lob_key or None,
                "lob_name": s.get("lob_name"),
                "updates": updates,
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

          suggestion = (suggestions[0] if suggestions else {})
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
