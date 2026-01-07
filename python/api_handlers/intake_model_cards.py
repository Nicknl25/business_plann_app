import json
import time
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


def _as_number(value: Any) -> Optional[float]:
  if value is None:
    return None
  if isinstance(value, (int, float)):
    return float(value)
  raw = str(value).strip().replace(",", "")
  if not raw:
    return None
  try:
    return float(raw)
  except Exception:
    return None


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


def _model_column(model: str) -> Optional[str]:
  norm = str(model or "").strip().lower()
  mapping = {
    "ops_concept": "ops_concept_model_json",
    "fulfillment": "fulfillment_model_json",
    "marketing": "marketing_model_json",
    "pricing": "pricing_model_json",
    "revenue": "revenue_model_json",
    "headcount": "headcount_model_json",
    "milestones": "milestones_model_json",
    "cogs": "cogs_model_json",
    "gna": "gna_model_json",
  }
  return mapping.get(norm)


def _focus_for_model(model: str) -> Optional[str]:
  norm = str(model or "").strip().lower()
  if norm in ("marketing", "pricing"):
    return "market"
  if norm in ("revenue",):
    return "ops"
  if norm in ("cogs", "gna"):
    return "ops"
  if norm in ("headcount",):
    return "people"
  if norm in ("ops_concept", "fulfillment", "milestones"):
    return "ops"
  return None


def _has_nonempty_text(obj: Dict[str, Any], key: str) -> bool:
  try:
    return bool(str((obj or {}).get(key) or "").strip())
  except Exception:
    return False


def _normalize_model_card(card: Dict[str, Any]) -> Dict[str, Any]:
  """
  Backwards compatible:
  - old shape: {drivers: {...}, derived: {...}}
  - new shape: {lobs: [{lob_key, lob_name?, drivers: {...}, derived: {...}, rationale?}, ...]}
  """
  out = dict(card or {})
  lobs = out.get("lobs")
  if isinstance(lobs, list) and all(isinstance(x, dict) for x in lobs):
    # Ensure each lob has required containers.
    fixed = []
    for lob in lobs:
      lob_key = str(lob.get("lob_key") or "company_total").strip() or "company_total"
      fixed.append(
        {
          **lob,
          "lob_key": lob_key,
          "lob_name": str(lob.get("lob_name") or "").strip() or None,
          "drivers": lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {},
          "derived": lob.get("derived") if isinstance(lob.get("derived"), dict) else {},
        }
      )
    out["lobs"] = fixed
    out.pop("drivers", None)
    out.pop("derived", None)
    return _ensure_company_total_lob(out)

  # Promote old fields into a single default LOB.
  drivers = out.get("drivers") if isinstance(out.get("drivers"), dict) else {}
  derived = out.get("derived") if isinstance(out.get("derived"), dict) else {}
  out["lobs"] = [
    {
      "lob_key": "company_total",
      "lob_name": None,
      "drivers": dict(drivers),
      "derived": dict(derived),
    }
  ]
  out.pop("drivers", None)
  out.pop("derived", None)
  return _ensure_company_total_lob(out)


def _ensure_company_total_lob(card: Dict[str, Any]) -> Dict[str, Any]:
  """
  Ensure the system-required, user-invisible "company_total" LOB exists as a stable home
  for shared drivers and optional aggregated derived values.
  """
  out = dict(card or {})
  lobs = out.get("lobs")
  if not isinstance(lobs, list):
    lobs = []
  has_company_total = any(
    isinstance(l, dict) and str(l.get("lob_key") or "").strip() == "company_total" for l in lobs
  )
  if not has_company_total:
    lobs = [
      {"lob_key": "company_total", "lob_name": None, "drivers": {}, "derived": {}},
      *[l for l in lobs if isinstance(l, dict)],
    ]
  out["lobs"] = lobs
  return out


def _get_lob_entry(
  card: Dict[str, Any], *, lob_key: str, lob_name: Optional[str]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  normalized = _ensure_company_total_lob(_normalize_model_card(card))
  lobs = normalized.get("lobs")
  if not isinstance(lobs, list):
    lobs = []
  norm_key = str(lob_key or "company_total").strip() or "company_total"
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    if str(lob.get("lob_key") or "").strip() == norm_key:
      if lob_name and not str(lob.get("lob_name") or "").strip():
        lob["lob_name"] = str(lob_name).strip()
      return normalized, lob

  new_lob = {"lob_key": norm_key, "lob_name": str(lob_name).strip() if lob_name else None, "drivers": {}, "derived": {}}
  lobs.append(new_lob)
  normalized["lobs"] = lobs
  return normalized, new_lob


def _compute_next_focus_from_draft(*, draft: Dict[str, Any]) -> str:
  operating_model = _parse_json_dict(draft.get("operating_model_json"))
  target_market = _parse_json_dict(draft.get("target_market_json"))
  people = _parse_json_dict(draft.get("people_json"))
  financials = _parse_json_dict(draft.get("financials_json"))
  ops_concept = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("ops_concept_model_json"))))
  fulfillment = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("fulfillment_model_json"))))
  marketing = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("marketing_model_json"))))
  revenue = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("revenue_model_json"))))
  milestones = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("milestones_model_json"))))
  headcount = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("headcount_model_json"))))
  cogs = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("cogs_model_json"))))
  gna = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("gna_model_json"))))

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

  def _model_has_driver(card: Dict[str, Any], *, keys: Tuple[str, ...]) -> bool:
    try:
      lobs = card.get("lobs")
      if not isinstance(lobs, list) or not lobs:
        return False
      non_company = [
        lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
      ]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      for lob in requires:
        drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
        for k in keys:
          dv = drivers.get(k)
          if not (isinstance(dv, dict) and _has_value(dv.get("value"))):
            return False
      return True
    except Exception:
      return False

  def _milestones_ready(card: Dict[str, Any]) -> bool:
    try:
      lobs = card.get("lobs")
      if not isinstance(lobs, list) or not lobs:
        return False
      non_company = [
        lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
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
    except Exception:
      return False

  def _revenue_ready(card: Dict[str, Any]) -> bool:
    try:
      lobs = card.get("lobs")
      if not isinstance(lobs, list) or not lobs:
        return False
      non_company = [
        lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
      ]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      for lob in requires:
        dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
        y1 = dmap.get("year1_revenue")
        ok = isinstance(y1, dict) and _has_value(y1.get("value"))
        if not ok:
          return False
      return True
    except Exception:
      return False

  def _derived_ready(card: Dict[str, Any], key: str) -> bool:
    try:
      lobs = card.get("lobs")
      if not isinstance(lobs, list) or not lobs:
        return False
      non_company = [
        lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
      ]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      for lob in requires:
        dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
        derived_val = dmap.get(key)
        ok = isinstance(derived_val, dict) and _has_value(derived_val.get("value"))
        if not ok:
          return False
      return True
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

  ops_ready = (
    _has_nonempty_text(operating_model, "business_type")
    and _has_nonempty_text(operating_model, "unit_name")
    and _has_nonempty_text(operating_model, "units_per_week_capacity")
    and _revenue_ready(revenue)
    and _model_has_driver(fulfillment, keys=("fulfillment_model", "who_fulfills", "lead_time"))
    and _model_has_driver(ops_concept, keys=("operating_unit", "primary_constraint", "process_overview"))
    and _milestones_ready(milestones)
    and _derived_ready(cogs, "year1_cogs")
    and _derived_ready(gna, "year1_gna_total")
  )

  market_ready_base = _target_market_ready(
    market_obj=target_market, consumer_type=str((operating_model or {}).get("consumer_type") or "consumer")
  )
  marketing_ready = False
  try:
    lobs = marketing.get("lobs")
    if isinstance(lobs, list) and lobs:
      # If the only LOB is company_total, require it.
      non_company = [lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      marketing_ready = True
      for lob in requires:
        derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
        y1 = derived.get("year1_marketing_spend")
        ok = isinstance(y1, dict) and _has_value(y1.get("value"))
        if not ok:
          marketing_ready = False
          break
  except Exception:
    marketing_ready = False
  market_ready = market_ready_base and marketing_ready

  people_ready = False
  try:
    items = people.get("people")
    people_ready = isinstance(items, list) and any(
      isinstance(p, dict) and str(p.get("full_name") or "").strip() for p in (items or [])
    )
  except Exception:
    people_ready = False
  if people_ready:
    try:
      lobs = headcount.get("lobs")
      if not isinstance(lobs, list) or not lobs:
        people_ready = False
      else:
        non_company = [
          lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
        ]
        requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
        for lob in requires:
          dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
          y1 = dmap.get("year1_payroll")
          ok = isinstance(y1, dict) and _has_value(y1.get("value"))
          if not ok:
            people_ready = False
            break
    except Exception:
      people_ready = False

  financials_ready = True
  try:
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
      if financials.get(k) is None:
        financials_ready = False
        break
  except Exception:
    financials_ready = False

  if not ops_ready:
    return "ops"
  if not market_ready:
    return "market"
  if not people_ready:
    return "people"
  if not financials_ready:
    return "financials"
  return "done"


def _apply_updates(
  *,
  model: str,
  current_card: Dict[str, Any],
  updates: List[Dict[str, Any]],
  derived: List[Dict[str, Any]],
  now_ms: int,
  lob_key: str,
  lob_name: Optional[str],
  apply_to_all_lobs: bool,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  normalized = _ensure_company_total_lob(_normalize_model_card(current_card))
  targets: List[Tuple[str, Optional[str]]] = [(lob_key, lob_name)]
  if apply_to_all_lobs and str(lob_key or "").strip() == "company_total":
    try:
      lobs = normalized.get("lobs")
      if isinstance(lobs, list):
        for lob in lobs:
          if not isinstance(lob, dict):
            continue
          k = str(lob.get("lob_key") or "").strip()
          if not k or k == "company_total":
            continue
          targets.append((k, str(lob.get("lob_name") or "").strip() or None))
    except Exception:
      pass

  changes: List[Dict[str, Any]] = []
  for target_key, target_name in targets:
    normalized, lob = _get_lob_entry(normalized, lob_key=target_key, lob_name=target_name)
    drivers: Dict[str, Any] = dict(lob.get("drivers") or {})
    derived_map: Dict[str, Any] = dict(lob.get("derived") or {})

    for u in updates:
      key = str(u.get("key") or "").strip()
      if not key:
        continue
      if str(model or "").strip().lower() == "cogs" and key == "production":
        old = lob.get("production")
        value = u.get("value")
        next_val = value if isinstance(value, dict) and value else None
        lob["production"] = next_val
        changes.append({"model": model, "lob_key": target_key, "path": "production", "old": old, "new": next_val})
        continue
      old = drivers.get(key)
      next_val = {
        "value": u.get("value"),
        "unit": u.get("unit"),
        "time_basis": u.get("time_basis"),
        "rationale": u.get("rationale"),
        "updated_at_ms": now_ms,
      }
      drivers[key] = next_val
      changes.append(
        {"model": model, "lob_key": target_key, "path": f"drivers.{key}", "old": old, "new": next_val}
      )

    # Derived values are LOB-specific; do not fan-out derived updates across LOBs.
    if (not apply_to_all_lobs) or (target_key == lob_key):
      for d in derived:
        key = str(d.get("key") or "").strip()
        if not key:
          continue
        # Headcount: ignore client-provided year1_payroll derived; it is computed from roles.
        if str(model or "").strip().lower() == "headcount" and key == "year1_payroll":
          continue
        old = derived_map.get(key)
        next_val = {
          "value": d.get("value"),
          "unit": d.get("unit"),
          "time_basis": d.get("time_basis"),
          "derivation": d.get("derivation"),
          "updated_at_ms": now_ms,
        }
        derived_map[key] = next_val
        changes.append(
          {"model": model, "lob_key": target_key, "path": f"derived.{key}", "old": old, "new": next_val}
        )

    lob["drivers"] = drivers
    lob["derived"] = derived_map

  normalized["version"] = int(normalized.get("version") or 1)
  normalized["updated_at_ms"] = now_ms
  normalized = _recompute_company_total_derived(normalized, model=model, now_ms=now_ms)
  return normalized, changes


def _recompute_company_total_derived(card: Dict[str, Any], *, model: str, now_ms: int) -> Dict[str, Any]:
  """
  For multi-LOB cards, keep company-level derived values as simple sums of LOB-level derived values.
  No allocation logic: we only sum already-entered per-LOB derived numbers.
  """
  normalized = _ensure_company_total_lob(_normalize_model_card(card))
  lobs = normalized.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return normalized

  non_company = [l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"]
  if not non_company:
    return normalized

  # Only keys we currently use for query rollups.
  sum_keys_by_model = {
    "marketing": ["year1_marketing_spend"],
    "revenue": ["year1_revenue"],
    "headcount": ["year1_payroll"],
  }
  keys = sum_keys_by_model.get(str(model or "").strip().lower(), [])
  if not keys:
    return normalized

  # Find company_total entry
  company_total = None
  for lob in lobs:
    if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() == "company_total":
      company_total = lob
      break
  if not isinstance(company_total, dict):
    return normalized

  derived_out = company_total.get("derived") if isinstance(company_total.get("derived"), dict) else {}
  derived_out = dict(derived_out)

  for key in keys:
    total = 0.0
    found_any = False
    unit = None
    time_basis = None
    for lob in non_company:
      dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
      val = dmap.get(key)
      if not isinstance(val, dict):
        continue
      num = _as_number(val.get("value"))
      if num is None:
        continue
      total += float(num)
      found_any = True
      unit = unit or val.get("unit")
      time_basis = time_basis or val.get("time_basis")
    if not found_any:
      continue
    derived_out[key] = {
      "value": total,
      "unit": unit,
      "time_basis": time_basis,
      "derivation": "sum(per_lob)",
      "updated_at_ms": now_ms,
    }

  company_total["derived"] = derived_out
  return normalized


def _recompute_headcount_from_roles(
  *,
  conn,
  draft: Dict[str, Any],
  card: Dict[str, Any],
  now_ms: int,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  """
  Deterministically enrich headcount roles using the IN wages dataset (when available),
  falling back to GPT-proposed fallback rates when no dataset match exists, then compute year1_payroll.
  """
  changes: List[Dict[str, Any]] = []
  normalized = _ensure_company_total_lob(_normalize_model_card(card))
  lobs = normalized.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return normalized, changes

  try:
    from wage_lookup import enrich_headcount_roles, normalize_state_code  # type: ignore
  except Exception:
    return normalized, changes

  state_code = normalize_state_code(draft.get("address_state"))
  naics_6: Optional[str] = None
  try:
    ops_json = _parse_json_dict(draft.get("operating_model_json"))
    naics_6 = _resolve_naics_6(conn=conn, business_type=str((ops_json or {}).get("business_type") or ""))
  except Exception:
    naics_6 = None

  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
    roles_val = drivers.get("roles")
    if not isinstance(roles_val, dict):
      continue
    roles_list = roles_val.get("value")
    if not isinstance(roles_list, list):
      continue

    enriched, total = enrich_headcount_roles(
      conn=conn,
      roles=roles_list,
      state_code=state_code,
      state_name=None,
      naics_6=naics_6,
    )

    old_roles = roles_val.get("value")
    roles_val["value"] = enriched
    roles_val["updated_at_ms"] = now_ms
    drivers["roles"] = roles_val
    lob["drivers"] = drivers
    changes.append(
      {
        "model": "headcount",
        "lob_key": str(lob.get("lob_key") or "").strip() or "company_total",
        "path": "drivers.roles.value",
        "old": old_roles,
        "new": enriched,
      }
    )

    derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
    old_y1 = derived.get("year1_payroll")
    derived["year1_payroll"] = {
      "value": float(total),
      "unit": "USD",
      "time_basis": "year",
      "derivation": "sum(employee_count x hourly_rate x hours_per_week x weeks_per_year)",
      "updated_at_ms": now_ms,
    }
    lob["derived"] = derived
    changes.append(
      {
        "model": "headcount",
        "lob_key": str(lob.get("lob_key") or "").strip() or "company_total",
        "path": "derived.year1_payroll",
        "old": old_y1,
        "new": derived.get("year1_payroll"),
      }
    )

  normalized["updated_at_ms"] = now_ms
  normalized = _recompute_company_total_derived(normalized, model="headcount", now_ms=now_ms)
  return normalized, changes


def _recompute_revenue_from_drivers(
  *,
  draft: Dict[str, Any],
  revenue_card: Dict[str, Any],
  now_ms: int,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Optional[float]]:
  """
  Deterministically compute year1_revenue derived values from revenue drivers and keep the
  canonical Ops fields (unit_price, units_per_week_capacity, starting_revenue) in sync.

  Returns: (next_revenue_card, next_ops_json, next_pricing_card, company_total_year1_revenue)
  """
  ops_json = _parse_json_dict(draft.get("operating_model_json"))
  pricing_card = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("pricing_model_json"))))
  normalized = _ensure_company_total_lob(_normalize_model_card(revenue_card))

  lobs = normalized.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return normalized, ops_json, pricing_card, None

  def _get_driver_num(drivers: Dict[str, Any], key: str) -> Optional[float]:
    v = drivers.get(key)
    if isinstance(v, dict):
      return _as_number(v.get("value"))
    return None

  non_company = [
    lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
  ]
  targets = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]

  company_total_y1 = 0.0
  company_total_has = False
  company_total_unit_price: Optional[float] = None
  company_total_capacity: Optional[float] = None

  for lob in targets:
    if not isinstance(lob, dict):
      continue
    drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
    drivers = dict(drivers)

    capacity = _get_driver_num(drivers, "units_per_week_capacity")
    if capacity is None:
      capacity = _as_number((ops_json or {}).get("units_per_week_capacity"))
    avg_units = _get_driver_num(drivers, "avg_units_per_week_year1")
    util_driver = _get_driver_num(drivers, "utilization_rate")
    if util_driver is not None and capacity is not None:
      avg_units = float(util_driver) * float(capacity)
      # Keep the two editable drivers in sync.
      prev = drivers.get("avg_units_per_week_year1")
      if isinstance(prev, dict):
        prev = dict(prev)
      else:
        prev = {}
      prev["value"] = avg_units
      prev["unit"] = prev.get("unit") or str((ops_json or {}).get("unit_name") or "").strip() or "units"
      prev["time_basis"] = prev.get("time_basis") or "week"
      prev["updated_at_ms"] = now_ms
      drivers["avg_units_per_week_year1"] = prev
    elif avg_units is not None and capacity is not None and float(capacity) > 0:
      util_driver = float(avg_units) / float(capacity)
      prevu = drivers.get("utilization_rate")
      if isinstance(prevu, dict):
        prevu = dict(prevu)
      else:
        prevu = {}
      prevu["value"] = util_driver
      prevu["unit"] = None
      prevu["time_basis"] = None
      prevu["updated_at_ms"] = now_ms
      drivers["utilization_rate"] = prevu
    weeks = _get_driver_num(drivers, "operating_weeks_per_year")
    if weeks is None:
      weeks = 52.0

    unit_price = _get_driver_num(drivers, "unit_price")
    if unit_price is None:
      unit_price = _as_number((ops_json or {}).get("unit_price"))

    y1_revenue: Optional[float] = None
    if avg_units is not None and weeks is not None and unit_price is not None:
      y1_revenue = float(avg_units) * float(unit_price) * float(weeks)

    derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
    derived = dict(derived)
    derived["year1_revenue"] = {
      "value": y1_revenue,
      "unit": "USD",
      "time_basis": "year",
      "derivation": "avg_units_per_week_year1 x unit_price x operating_weeks_per_year",
      "updated_at_ms": now_ms,
    }
    if avg_units is not None and unit_price is not None:
      derived["weekly_revenue"] = {
        "value": float(avg_units) * float(unit_price),
        "unit": "USD",
        "time_basis": "week",
        "derivation": "avg_units_per_week_year1 x unit_price",
        "updated_at_ms": now_ms,
      }
    if capacity is not None and avg_units is not None and float(capacity) > 0:
      derived["utilization_rate"] = {
        "value": float(avg_units) / float(capacity),
        "unit": None,
        "time_basis": None,
        "derivation": "avg_units_per_week_year1 / units_per_week_capacity",
        "updated_at_ms": now_ms,
      }
    lob["drivers"] = drivers
    lob["derived"] = derived

    if y1_revenue is not None:
      company_total_y1 += float(y1_revenue)
      company_total_has = True

    # If there is only one user-visible LOB, treat its unit_price/capacity as company defaults.
    if len(targets) == 1:
      company_total_unit_price = unit_price
      company_total_capacity = capacity

  normalized = _recompute_company_total_derived(normalized, model="revenue", now_ms=now_ms)

  # Sync Ops canonical fields (single-business rollups) from company_total where available.
  if company_total_has:
    ops_json = dict(ops_json or {})
    ops_json["starting_revenue"] = float(company_total_y1)
  if company_total_unit_price is not None:
    ops_json = dict(ops_json or {})
    ops_json["unit_price"] = float(company_total_unit_price)
  if company_total_capacity is not None:
    ops_json = dict(ops_json or {})
    ops_json["units_per_week_capacity"] = float(company_total_capacity)

  # Sync Pricing card unit_price so edits in Revenue and Pricing stay consistent.
  try:
    lobs_p = pricing_card.get("lobs")
    if isinstance(lobs_p, list):
      company_p = next(
        (l for l in lobs_p if isinstance(l, dict) and str(l.get("lob_key") or "").strip() == "company_total"),
        None,
      )
      if isinstance(company_p, dict) and company_total_unit_price is not None:
        drivers_p = company_p.get("drivers") if isinstance(company_p.get("drivers"), dict) else {}
        drivers_p = dict(drivers_p)
        drivers_p["unit_price"] = {
          "value": float(company_total_unit_price),
          "unit": "USD",
          "time_basis": "per_unit",
          "rationale": "Synced from the revenue model drivers.",
          "updated_at_ms": now_ms,
        }
        company_p["drivers"] = drivers_p
        pricing_card["updated_at_ms"] = now_ms
  except Exception:
    pass

  return normalized, ops_json, pricing_card, (float(company_total_y1) if company_total_has else None)


def _recompute_marketing_from_drivers(*, marketing_card: Dict[str, Any], now_ms: int) -> Dict[str, Any]:
  """
  Deterministically compute year1_marketing_spend from monthly_marketing_budget for each LOB,
  then (for multi-LOB) keep company_total derived as a simple sum.
  """
  normalized = _ensure_company_total_lob(_normalize_model_card(marketing_card))
  lobs = normalized.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return normalized

  def _get_num(drivers: Dict[str, Any], key: str) -> Optional[float]:
    dv = drivers.get(key)
    if not isinstance(dv, dict):
      return None
    return _as_number(dv.get("value"))

  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
    drivers = dict(drivers)
    derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
    derived = dict(derived)

    monthly = _get_num(drivers, "monthly_marketing_budget")
    if monthly is None:
      existing_y1 = derived.get("year1_marketing_spend")
      y1_num = _as_number(existing_y1.get("value")) if isinstance(existing_y1, dict) else None
      if y1_num is not None:
        monthly = float(y1_num) / 12.0
        drivers["monthly_marketing_budget"] = {
          "value": max(0.0, float(monthly)),
          "unit": "USD",
          "time_basis": "month",
          "rationale": str((drivers.get("monthly_marketing_budget") or {}).get("rationale") or "").strip() or None,
          "updated_at_ms": now_ms,
        }

    y1_val = (max(0.0, float(monthly)) * 12.0) if monthly is not None else None
    derived["year1_marketing_spend"] = {
      "value": y1_val,
      "unit": "USD",
      "time_basis": "year",
      "derivation": "monthly_marketing_budget x 12",
      "updated_at_ms": now_ms,
    }

    lob["drivers"] = drivers
    lob["derived"] = derived

  normalized = _recompute_company_total_derived(normalized, model="marketing", now_ms=now_ms)
  return normalized


def post_intake_model_cards_handler(*, app, request):
  """
  Persist model-card driver updates (Accept/Edit) to the consult draft immediately.

  Request:
  {
    "draft_id": "...",
    "action": "accept" | "edit",
    "model": "marketing" | "headcount" | "pricing" | "fulfillment" | "ops_concept" | "cogs" | "gna",
    "updates": [{ "key": "...", "value": ..., "unit": "...", "time_basis": "...", "rationale": "..." }],
    "derived": [{ "key": "...", "value": ..., "unit": "...", "time_basis": "...", "derivation": "..." }],
    "proposal_id": "...?",
    "note": "...?"
  }
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = str(payload.get("draft_id") or "").strip()
  if not draft_id:
    return (jsonify({"error": "invalid_request", "detail": "draft_id is required"}), 400)

  model = str(payload.get("model") or "").strip().lower()
  column = _model_column(model)
  if not column:
    return (
      jsonify(
        {
          "error": "invalid_request",
          "detail": "model must be one of: ops_concept, fulfillment, marketing, pricing, revenue, headcount, milestones, cogs, gna",
        }
      ),
      400,
    )

  updates = payload.get("updates")
  derived = payload.get("derived")
  if updates is None:
    updates = []
  if derived is None:
    derived = []
  if not isinstance(updates, list) or not all(isinstance(u, dict) for u in updates):
    return (jsonify({"error": "invalid_request", "detail": "updates must be a list of objects"}), 400)
  if not isinstance(derived, list) or not all(isinstance(d, dict) for d in derived):
    return (jsonify({"error": "invalid_request", "detail": "derived must be a list of objects"}), 400)

  action = str(payload.get("action") or "").strip().lower()
  if action not in ("accept", "edit"):
    action = "edit"
  proposal_id = str(payload.get("proposal_id") or "").strip() or None
  note = str(payload.get("note") or "").strip() or None
  lob_key = str(payload.get("lob_key") or "company_total").strip() or "company_total"
  lob_name = str(payload.get("lob_name") or "").strip() or None
  apply_to_all_lobs = bool(payload.get("apply_to_all_lobs"))

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import append_messages, get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    draft = get_draft(conn, draft_id=draft_id)
    current_card = _parse_json_dict(draft.get(column))
    now_ms = int(time.time() * 1000)
    pricing_unit_price_updated = False
    pricing_unit_price_value: Any = None
    if model == "pricing":
      try:
        for u in (updates or []):
          if str(u.get("key") or "").strip() == "unit_price":
            pricing_unit_price_updated = True
            pricing_unit_price_value = u.get("value")
            break
      except Exception:
        pricing_unit_price_updated = False
        pricing_unit_price_value = None
    next_card, changes = _apply_updates(
      model=model,
      current_card=current_card,
      updates=updates,
      derived=derived,
      now_ms=now_ms,
      lob_key=lob_key,
      lob_name=lob_name,
      apply_to_all_lobs=apply_to_all_lobs,
    )

    # Deterministic headcount math: enrich roles (dataset/fallback) + compute year1_payroll.
    if model == "headcount":
      touched_roles = any(str(u.get("key") or "").strip() == "roles" for u in updates)
      if touched_roles:
        next_card, extra_changes = _recompute_headcount_from_roles(
          conn=conn, draft=draft, card=next_card, now_ms=now_ms
        )
        changes.extend(extra_changes)

    # Deterministic marketing math: compute year1_marketing_spend from monthly_marketing_budget.
    if model == "marketing":
      next_card = _recompute_marketing_from_drivers(marketing_card=next_card, now_ms=now_ms)

    # Deterministic COGS / G&A math (company_total rollups).
    year1_cogs_value: Optional[float] = None
    year1_gna_total_value: Optional[float] = None
    if model in ("cogs", "gna"):
      try:
        from unified_intake.model_engine import (  # type: ignore
          recompute_cogs_company_total,
          recompute_gna_company_total,
        )
      except Exception:
        recompute_cogs_company_total = None  # type: ignore
        recompute_gna_company_total = None  # type: ignore

      if model == "cogs" and recompute_cogs_company_total:
        revenue_live = _parse_json_dict(draft.get("revenue_model_json"))
        next_card, year1_cogs_value = recompute_cogs_company_total(
          next_card, revenue_card=revenue_live, now_ms=now_ms
        )
      if model == "gna" and recompute_gna_company_total:
        next_card, year1_gna_total_value = recompute_gna_company_total(next_card, now_ms=now_ms)

    # Deterministic revenue math: compute year1_revenue + keep Ops unit_price/capacity/starting_revenue synced.
    next_ops_json: Optional[Dict[str, Any]] = None
    next_pricing_card: Optional[Dict[str, Any]] = None
    year1_revenue_value: Optional[float] = None
    if model == "revenue":
      next_card, next_ops_json, next_pricing_card, year1_revenue_value = _recompute_revenue_from_drivers(
        draft=draft, revenue_card=next_card, now_ms=now_ms
      )

    # If the user edits unit_price in Pricing, also update Ops + recompute revenue derived values (if present)
    # so the visible revenue math stays coherent.
    if model == "pricing" and pricing_unit_price_updated:
      ops_json_live = _parse_json_dict(draft.get("operating_model_json"))
      if pricing_unit_price_value in (None, "", "null"):
        ops_json_live["unit_price"] = None
      else:
        ops_json_live["unit_price"] = pricing_unit_price_value
      next_ops_json = ops_json_live
      try:
        existing_revenue = _parse_json_dict(draft.get("revenue_model_json"))
        if existing_revenue:
          recomputed, ops2, pricing2, y1 = _recompute_revenue_from_drivers(
            draft={**draft, "operating_model_json": ops_json_live, "pricing_model_json": next_card},
            revenue_card=existing_revenue,
            now_ms=now_ms,
          )
          # Only persist recompute if it changed something meaningful.
          if recomputed != existing_revenue:
            next_ops_json = ops2
            next_pricing_card = pricing2
            year1_revenue_value = y1
            # Persist revenue card via kwargs mapping below.
            draft = {**draft, "revenue_model_json": recomputed}
            # Ensure the main card update still returns pricing card as next_card.
            # The revenue card write happens via kwargs below.
            kwargs_revenue_override = recomputed
          else:
            kwargs_revenue_override = None
        else:
          kwargs_revenue_override = None
      except Exception:
        kwargs_revenue_override = None
    else:
      kwargs_revenue_override = None

    try:
      current_nonce = int(draft.get("driver_revision_nonce") or 0)
    except Exception:
      current_nonce = 0
    next_nonce = current_nonce + 1

    existing_events = draft.get("driver_events_json")
    if isinstance(existing_events, list):
      events = list(existing_events)
    else:
      try:
        parsed = json.loads(str(existing_events)) if existing_events else []
      except Exception:
        parsed = []
      events = parsed if isinstance(parsed, list) else []

    events.append(
      {
        "nonce": next_nonce,
        "at_ms": now_ms,
        "action": action,
        "proposal_id": proposal_id,
        "note": note,
        "changes": changes,
      }
    )
    if len(events) > 500:
      events = events[-500:]

    proposals = _parse_json_list(draft.get("model_card_proposals_json"))
    if proposal_id:
      proposals = [
        p for p in proposals if not (isinstance(p, dict) and str(p.get("id") or "").strip() == str(proposal_id))
      ]

    # Update rollup columns opportunistically (query-friendly), without requiring a fixed driver taxonomy.
    year1_marketing_spend: Any = None
    year1_payroll: Any = None
    year1_cogs: Any = None
    year1_gna_total: Any = None
    if model == "marketing":
      # Only set company_total rollup if it exists.
      try:
        for lob in (next_card.get("lobs") or []):
          if not isinstance(lob, dict):
            continue
          if str(lob.get("lob_key") or "").strip() != "company_total":
            continue
          dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
          y1 = dmap.get("year1_marketing_spend")
          if isinstance(y1, dict):
            year1_marketing_spend = _as_number(y1.get("value"))
      except Exception:
        year1_marketing_spend = None
    if model == "headcount":
      try:
        for lob in (next_card.get("lobs") or []):
          if not isinstance(lob, dict):
            continue
          if str(lob.get("lob_key") or "").strip() != "company_total":
            continue
          dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
          y1 = dmap.get("year1_payroll")
          if isinstance(y1, dict):
            year1_payroll = _as_number(y1.get("value"))
      except Exception:
        year1_payroll = None
    if model == "cogs":
      year1_cogs = year1_cogs_value
    if model == "gna":
      year1_gna_total = year1_gna_total_value
    if model in ("ops_concept", "fulfillment", "pricing"):
      pass
    if model == "pricing":
      # Nothing automatic here yet; pricing rollups are typically used via revenue logic.
      pass

    # Persist the new card + event log; do not append a synthetic user message.
    kwargs: Dict[str, Any] = {
      "draft_id": draft_id,
      "new_messages": [],
      "driver_events": events,
      "driver_revision_nonce": next_nonce,
      "model_card_proposals": proposals,
      # Always keep text chat enabled; model cards are internal-only.
      "interaction_mode": "chat",
    }

    # Map column -> append_messages argument name.
    card_param_by_column = {
      "ops_concept_model_json": "ops_concept_model_json",
      "fulfillment_model_json": "fulfillment_model_json",
      "marketing_model_json": "marketing_model_json",
      "pricing_model_json": "pricing_model_json",
      "revenue_model_json": "revenue_model_json",
      "headcount_model_json": "headcount_model_json",
      "milestones_model_json": "milestones_model_json",
      "cogs_model_json": "cogs_model_json",
      "gna_model_json": "gna_model_json",
    }
    card_param = card_param_by_column.get(column)
    if card_param:
      kwargs[card_param] = next_card

    # Additive sync: Pricing model is sourced from Ops `unit_price`. If the user edits the pricing
    # driver, keep Ops canonical `unit_price` in lockstep so revenue math updates immediately.
    if next_ops_json is not None:
      kwargs["operating_model_json"] = next_ops_json
    if next_pricing_card is not None:
      kwargs["pricing_model_json"] = next_pricing_card
    if kwargs_revenue_override is not None:
      kwargs["revenue_model_json"] = kwargs_revenue_override

    if year1_marketing_spend is not None:
      kwargs["year1_marketing_spend"] = year1_marketing_spend
    if year1_payroll is not None:
      kwargs["year1_payroll"] = year1_payroll
    if year1_revenue_value is not None:
      kwargs["year1_revenue"] = float(year1_revenue_value)
    if year1_cogs is not None:
      kwargs["year1_cogs"] = float(year1_cogs)
    if year1_gna_total is not None:
      kwargs["year1_gna_total"] = float(year1_gna_total)

    append_messages(conn, **kwargs)

    # UX: model-card edits are internal-only state updates; they must not create new chat turns.
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft_id,
        "client_id": str(draft.get("client_id") or "").strip(),
        "model": model,
        "driver_revision_nonce": next_nonce,
        "interaction_mode": "chat",
        "model_card": next_card,
      }
    )

    # Ask the next question by delegating to the existing consult flow (no UI "wait" state).
    fresh = get_draft(conn, draft_id=draft_id)
    next_focus = _compute_next_focus_from_draft(draft=fresh)

    assistant_message: str = ""
    try:
      # Pull the freshest draft state after the write.
      messages_raw = fresh.get("messages_json")
      messages = []
      try:
        parsed_msgs = json.loads(str(messages_raw)) if messages_raw else []
        if isinstance(parsed_msgs, list):
          messages = [m for m in parsed_msgs if isinstance(m, dict)]
      except Exception:
        messages = []

      from api_handlers.shared_context import build_shared_context  # type: ignore
      from fact_templates import sanitize_fact_template  # type: ignore
      from intake_consultant import consultant_chat_turn  # type: ignore
      from target_market_consultant import target_market_chat_turn  # type: ignore
      from marketing_consultant import marketing_chat_turn  # type: ignore
      from revenue_consultant import revenue_chat_turn  # type: ignore
      from fulfillment_consultant import fulfillment_chat_turn  # type: ignore
      from ops_concept_consultant import ops_concept_chat_turn  # type: ignore
      from cogs_consultant import cogs_chat_turn  # type: ignore
      from gna_consultant import gna_chat_turn  # type: ignore
      from milestones_consultant import milestones_chat_turn  # type: ignore
      from headcount_consultant import headcount_chat_turn  # type: ignore
      from people_capability_consultant import people_capability_chat_turn  # type: ignore
      from financials_consultant import financials_chat_turn  # type: ignore

      shared_context = build_shared_context(conn, draft_id=draft_id)
      ops_json = _parse_json_dict(fresh.get("operating_model_json"))
      naics_6 = _resolve_naics_6(conn=conn, business_type=str((ops_json or {}).get("business_type") or ""))
      ops_consumer_type = str((ops_json or {}).get("consumer_type") or "").strip().lower()
      if ops_consumer_type not in ("consumer", "b2b", "mixed"):
        ops_consumer_type = "consumer"
      intake_context = {
        "client_id": str(fresh.get("client_id") or "").strip(),
        "draft_id": draft_id,
        "business_name": fresh.get("business_name"),
        "business_start_date": fresh.get("business_start_date"),
        "address": fresh.get("business_address"),
        "consumer_type": ops_consumer_type,
        "naics_6": naics_6,
        "shared_context": shared_context,
      }
      continue_instruction = "Continue. Ask exactly ONE next question for the client to answer (do not bundle)."
      start_by_focus = {
        "ops": "Start the operational intake. Ask your first question.",
        "market": "Start the target market intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions).",
        "people": "Start the People & Capability intake. Ask your first question.",
        "financials": "Start the financials intake. Ask your first question.",
      }
      # When editing model cards mid-stream, never restart a section: continue from current state.
      instruction = continue_instruction if messages else start_by_focus.get(next_focus, continue_instruction)
      conversation_messages = [*messages, {"role": "user", "content": instruction}]

      turn: Dict[str, Any] = {"assistant_message": ""}
      if next_focus == "ops":
        operating_model = _parse_json_dict(fresh.get("operating_model_json"))
        revenue_card = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("revenue_model_json"))))
        fulfillment_card = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("fulfillment_model_json"))))
        ops_concept_card = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("ops_concept_model_json"))))
        milestones_card = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("milestones_model_json"))))
        cogs_card = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("cogs_model_json"))))
        gna_card = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("gna_model_json"))))

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

        def _revenue_pending(card: Dict[str, Any]) -> bool:
          try:
            lobs = card.get("lobs")
            if not isinstance(lobs, list) or not lobs:
              return True
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            for lob in requires:
              dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
              y1 = dmap.get("year1_revenue")
              if not (isinstance(y1, dict) and _has_value(y1.get("value"))):
                return True
            return False
          except Exception:
            return True

        def _model_missing_driver(card: Dict[str, Any], keys: Tuple[str, ...]) -> bool:
          try:
            lobs = card.get("lobs")
            if not isinstance(lobs, list) or not lobs:
              return True
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            for lob in requires:
              drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
              for k in keys:
                dv = drivers.get(k)
                if not (isinstance(dv, dict) and _has_value(dv.get("value"))):
                  return True
            return False
          except Exception:
            return True

        def _milestones_pending(card: Dict[str, Any]) -> bool:
          try:
            lobs = card.get("lobs")
            if not isinstance(lobs, list) or not lobs:
              return True
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            for lob in requires:
              drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
              ms = drivers.get("milestones")
              if not isinstance(ms, dict):
                return True
              val = ms.get("value")
              if not isinstance(val, list) or not any(isinstance(x, dict) and str(x.get("title") or "").strip() for x in val):
                return True
            return False
          except Exception:
            return True

        def _derived_pending(card: Dict[str, Any], key: str) -> bool:
          try:
            lobs = card.get("lobs")
            if not isinstance(lobs, list) or not lobs:
              return True
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            for lob in requires:
              dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
              val = dmap.get(key)
              if not (isinstance(val, dict) and _has_value(val.get("value"))):
                return True
            return False
          except Exception:
            return True

        unit_name_live = str((operating_model or {}).get("unit_name") or "").strip()
        proposals_now = _parse_json_list(fresh.get("model_card_proposals_json"))

        if _revenue_pending(revenue_card):
          suggestion: Dict[str, Any] = {}
          if not any(isinstance(p, dict) and p.get("model") == "revenue" for p in proposals_now):
            try:
              from model_card_proposer import propose_revenue_suggestions  # type: ignore

              lobs_in: List[Dict[str, str]] = []
              raw_lobs = revenue_card.get("lobs")
              if isinstance(raw_lobs, list):
                for l in raw_lobs:
                  if not isinstance(l, dict):
                    continue
                  lobs_in.append(
                    {
                      "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                      "lob_name": str(l.get("lob_name") or "").strip(),
                    }
                  )
              suggested = propose_revenue_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((operating_model or {}).get("business_type") or "").strip(),
                naics_6=naics_6,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                ops_json=operating_model,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              if suggested and isinstance(suggested[0], dict):
                suggestion = suggested[0]
              now_ms = int(time.time() * 1000)
              for s in suggested:
                if not isinstance(s, dict):
                  continue
                proposal_id = f"rev_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "revenue",
                    "title": "Revenue (Year 1 model)",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
                    "updates": [
                      {
                        "key": "units_per_week_capacity",
                        "value": s.get("units_per_week_capacity"),
                        "unit": unit_name_live or "units",
                        "time_basis": "week",
                        "rationale": str(s.get("basis") or "").strip() or "Proposed capacity anchor.",
                      },
                      {
                        "key": "avg_units_per_week_year1",
                        "value": s.get("avg_units_per_week_year1"),
                        "unit": unit_name_live or "units",
                        "time_basis": "week",
                        "rationale": "Proposed Year-1 average volume (accounts for ramp).",
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
                        "rationale": "Operating weeks per year (editable).",
                      },
                      {
                        "key": "unit_price",
                        "value": s.get("unit_price"),
                        "unit": "USD",
                        "time_basis": "per_unit",
                        "rationale": "Average revenue per unit (editable).",
                      },
                    ],
                    "derived": [],
                    "created_at_ms": now_ms,
                  },
                ]
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass
          turn = revenue_chat_turn(
            intake_context={
              **intake_context,
              "revenue_card": revenue_card,
              "revenue_suggestion": suggestion,
              "unit_name": unit_name_live,
            },
            conversation_messages=conversation_messages,
          )
        elif _model_missing_driver(fulfillment_card, ("fulfillment_model", "who_fulfills", "lead_time")):
          suggestion = {}
          if not any(isinstance(p, dict) and p.get("model") == "fulfillment" for p in proposals_now):
            try:
              from model_card_proposer import propose_fulfillment_suggestions  # type: ignore

              lobs_in: List[Dict[str, str]] = []
              raw_lobs = fulfillment_card.get("lobs")
              if isinstance(raw_lobs, list):
                for l in raw_lobs:
                  if not isinstance(l, dict):
                    continue
                  lobs_in.append(
                    {
                      "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                      "lob_name": str(l.get("lob_name") or "").strip(),
                    }
                  )
              suggested = propose_fulfillment_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((operating_model or {}).get("business_type") or "").strip(),
                naics_6=naics_6,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                ops_json=operating_model,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              if suggested and isinstance(suggested[0], dict):
                suggestion = suggested[0]
              now_ms = int(time.time() * 1000)
              for s in suggested:
                if not isinstance(s, dict):
                  continue
                proposal_id = f"ful_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "fulfillment",
                    "title": "Fulfillment model",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
                    "updates": [
                      {
                        "key": "fulfillment_model",
                        "value": s.get("fulfillment_model"),
                        "unit": None,
                        "time_basis": None,
                        "rationale": str(s.get("basis") or "").strip() or "Proposed fulfillment model.",
                      },
                      {
                        "key": "who_fulfills",
                        "value": s.get("who_fulfills"),
                        "unit": None,
                        "time_basis": None,
                        "rationale": "Who fulfills and where work happens.",
                      },
                      {
                        "key": "lead_time",
                        "value": s.get("lead_time"),
                        "unit": None,
                        "time_basis": None,
                        "rationale": "Typical fulfillment lead time.",
                      },
                    ],
                    "derived": [],
                    "created_at_ms": now_ms,
                  },
                ]
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass
          turn = fulfillment_chat_turn(
            intake_context={**intake_context, "fulfillment_card": fulfillment_card, "fulfillment_suggestion": suggestion},
            conversation_messages=conversation_messages,
          )
        elif _model_missing_driver(ops_concept_card, ("operating_unit", "primary_constraint", "process_overview")):
          suggestion = {}
          if not any(isinstance(p, dict) and p.get("model") == "ops_concept" for p in proposals_now):
            try:
              from model_card_proposer import propose_ops_concept_suggestions  # type: ignore

              lobs_in: List[Dict[str, str]] = []
              raw_lobs = ops_concept_card.get("lobs")
              if isinstance(raw_lobs, list):
                for l in raw_lobs:
                  if not isinstance(l, dict):
                    continue
                  lobs_in.append(
                    {
                      "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                      "lob_name": str(l.get("lob_name") or "").strip(),
                    }
                  )
              suggested = propose_ops_concept_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((operating_model or {}).get("business_type") or "").strip(),
                naics_6=naics_6,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                ops_json=operating_model,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              if suggested and isinstance(suggested[0], dict):
                suggestion = suggested[0]
              now_ms = int(time.time() * 1000)
              for s in suggested:
                if not isinstance(s, dict):
                  continue
                proposal_id = f"opc_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "ops_concept",
                    "title": "Operating concept",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
                    "updates": [
                      {
                        "key": "operating_unit",
                        "value": s.get("operating_unit"),
                        "unit": None,
                        "time_basis": None,
                        "rationale": str(s.get("basis") or "").strip() or "Proposed operating unit.",
                      },
                      {
                        "key": "primary_constraint",
                        "value": s.get("primary_constraint"),
                        "unit": None,
                        "time_basis": None,
                        "rationale": "What most constrains throughput today.",
                      },
                      {
                        "key": "process_overview",
                        "value": s.get("process_overview"),
                        "unit": None,
                        "time_basis": None,
                        "rationale": "Plain-English operating reality (editable).",
                      },
                    ],
                    "derived": [],
                    "created_at_ms": now_ms,
                  },
                ]
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass
          turn = ops_concept_chat_turn(
            intake_context={**intake_context, "ops_concept_card": ops_concept_card, "ops_concept_suggestion": suggestion},
            conversation_messages=conversation_messages,
          )
        elif _milestones_pending(milestones_card):
          suggestions: List[Dict[str, Any]] = []
          if not any(isinstance(p, dict) and p.get("model") == "milestones" for p in proposals_now):
            try:
              from model_card_proposer import propose_milestones_suggestions  # type: ignore

              lobs_in: List[Dict[str, str]] = []
              raw_lobs = milestones_card.get("lobs")
              if isinstance(raw_lobs, list):
                for l in raw_lobs:
                  if not isinstance(l, dict):
                    continue
                  lobs_in.append(
                    {
                      "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                      "lob_name": str(l.get("lob_name") or "").strip(),
                    }
                  )
              suggestions = propose_milestones_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((operating_model or {}).get("business_type") or "").strip(),
                naics_6=naics_6,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                ops_json=operating_model,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              now_ms = int(time.time() * 1000)
              for s in suggestions:
                if not isinstance(s, dict):
                  continue
                proposal_id = f"ms_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "milestones",
                    "title": "Milestones",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
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
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass
          turn = milestones_chat_turn(
            intake_context={**intake_context, "milestones_suggestions": suggestions},
            conversation_messages=conversation_messages,
          )
        elif _derived_pending(cogs_card, "year1_cogs"):
          suggestion = {}
          if not any(isinstance(p, dict) and p.get("model") == "cogs" for p in proposals_now):
            try:
              from model_card_proposer import propose_cogs_suggestions  # type: ignore

              lobs_in: List[Dict[str, str]] = []
              raw_lobs = cogs_card.get("lobs")
              if isinstance(raw_lobs, list):
                for l in raw_lobs:
                  if not isinstance(l, dict):
                    continue
                  lobs_in.append(
                    {
                      "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                      "lob_name": str(l.get("lob_name") or "").strip(),
                    }
                  )
              suggested = propose_cogs_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((operating_model or {}).get("business_type") or "").strip(),
                naics_6=naics_6,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                ops_json=operating_model,
                fulfillment_model_json=fulfillment_card,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              if suggested and isinstance(suggested[0], dict):
                suggestion = suggested[0]
              now_ms = int(time.time() * 1000)
              for s in suggested:
                if not isinstance(s, dict):
                  continue
                updates: List[Dict[str, Any]] = []
                for key in (
                  "materials_cost_per_unit",
                  "direct_fulfillment_cost_per_unit",
                  "other_variable_cost_per_unit",
                ):
                  if s.get(key) is None:
                    continue
                  updates.append(
                    {
                      "key": key,
                      "value": s.get(key),
                      "unit": "USD",
                      "time_basis": "per_unit",
                      "rationale": str(s.get("basis") or "").strip() or "Proposed COGS driver.",
                    }
                  )
                production = s.get("production")
                if isinstance(production, dict) and production:
                  updates.append(
                    {
                      "key": "production",
                      "value": production,
                      "unit": None,
                      "time_basis": None,
                      "rationale": "Proposed production flow.",
                    }
                  )
                if not updates:
                  continue
                proposal_id = f"cogs_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "cogs",
                    "title": "COGS (Year 1)",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
                    "updates": updates,
                    "derived": [],
                    "created_at_ms": now_ms,
                  },
                ]
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass
          turn = cogs_chat_turn(
            intake_context={**intake_context, "cogs_card": cogs_card, "cogs_suggestion": suggestion},
            conversation_messages=conversation_messages,
          )
        elif _derived_pending(gna_card, "year1_gna_total"):
          suggestion = {}
          if not any(isinstance(p, dict) and p.get("model") == "gna" for p in proposals_now):
            try:
              from model_card_proposer import propose_gna_suggestions  # type: ignore

              lobs_in: List[Dict[str, str]] = []
              raw_lobs = gna_card.get("lobs")
              if isinstance(raw_lobs, list):
                for l in raw_lobs:
                  if not isinstance(l, dict):
                    continue
                  lobs_in.append(
                    {
                      "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                      "lob_name": str(l.get("lob_name") or "").strip(),
                    }
                  )
              suggested = propose_gna_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((operating_model or {}).get("business_type") or "").strip(),
                naics_6=naics_6,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                ops_json=operating_model,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              if suggested and isinstance(suggested[0], dict):
                suggestion = suggested[0]
              now_ms = int(time.time() * 1000)
              for s in suggested:
                if not isinstance(s, dict):
                  continue
                updates: List[Dict[str, Any]] = []
                for key in (
                  "monthly_rent_expense",
                  "monthly_software_expense",
                  "monthly_insurance_expense",
                  "monthly_utilities_expense",
                  "monthly_admin_expense",
                  "other_operating_expense",
                ):
                  if s.get(key) is None:
                    continue
                  updates.append(
                    {
                      "key": key,
                      "value": s.get(key),
                      "unit": "USD",
                      "time_basis": "month",
                      "rationale": str(s.get("basis") or "").strip() or "Proposed G&A baseline.",
                    }
                  )
                if not updates:
                  continue
                monthly_total = 0.0
                for u in updates:
                  try:
                    monthly_total += float(u.get("value") or 0.0)
                  except Exception:
                    pass
                derived = [
                  {
                    "key": "year1_gna_total",
                    "value": (monthly_total * 12.0) if monthly_total > 0 else None,
                    "unit": "USD",
                    "time_basis": "year",
                    "derivation": "sum(monthly drivers) x 12",
                  }
                ]
                proposal_id = f"gna_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "gna",
                    "title": "G&A (Year 1)",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
                    "updates": updates,
                    "derived": derived,
                    "created_at_ms": now_ms,
                  },
                ]
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass
          turn = gna_chat_turn(
            intake_context={**intake_context, "gna_card": gna_card, "gna_suggestion": suggestion},
            conversation_messages=conversation_messages,
          )
        else:
          turn = consultant_chat_turn(intake_context=intake_context, conversation_messages=conversation_messages)
      elif next_focus == "market":
        target_market = _parse_json_dict(fresh.get("target_market_json"))
        marketing = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("marketing_model_json"))))
        marketing_pending = True
        try:
          lobs = marketing.get("lobs")
          if isinstance(lobs, list) and lobs:
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            marketing_pending = any(
              not (
                isinstance((lob.get("derived") if isinstance(lob, dict) else None), dict)
                and isinstance(((lob.get("derived") or {}).get("year1_marketing_spend")), dict)
                and (
                  (((lob.get("derived") or {}).get("year1_marketing_spend") or {}).get("value")) is not None
                  and (
                    not isinstance(((lob.get("derived") or {}).get("year1_marketing_spend") or {}).get("value"), str)
                    or bool(
                      str(
                        ((lob.get("derived") or {}).get("year1_marketing_spend") or {}).get("value") or ""
                      ).strip()
                    )
                  )
                )
              )
              for lob in requires
            )
        except Exception:
          marketing_pending = True

        consumer_type_live = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
        if consumer_type_live not in ("consumer", "b2b", "mixed"):
          consumer_type_live = "consumer"

        target_market_ready = True
        try:
          if consumer_type_live in ("consumer", "mixed"):
            target_market_ready = target_market_ready and bool(str((target_market or {}).get("gender_age_intent") or "").strip())
            target_market_ready = target_market_ready and bool(str((target_market or {}).get("income_intent") or "").strip())
            sels = (target_market or {}).get("selections")
            target_market_ready = target_market_ready and isinstance(sels, list) and bool(sels)
          if consumer_type_live in ("b2b", "mixed"):
            terms = (target_market or {}).get("b2b_industry_terms")
            sizes = (target_market or {}).get("b2b_size_bands")
            ages = (target_market or {}).get("b2b_age_bands")
            target_market_ready = target_market_ready and isinstance(terms, list) and any(str(t or "").strip() for t in (terms or []))
            target_market_ready = target_market_ready and isinstance(sizes, list) and any(str(s or "").strip() for s in (sizes or []))
            target_market_ready = target_market_ready and isinstance(ages, list) and any(str(a or "").strip() for a in (ages or []))
        except Exception:
          target_market_ready = False

        if target_market_ready and marketing_pending:
          # Marketing is pending: generate a proposal so the UI can present Accept/Edit controls.
          proposals_now = _parse_json_list(fresh.get("model_card_proposals_json"))
          if not any(isinstance(p, dict) and p.get("model") == "marketing" for p in proposals_now):
            try:
              from model_card_proposer import propose_marketing_suggestions  # type: ignore

              lobs_in: List[Dict[str, str]] = []
              raw_lobs = marketing.get("lobs")
              if isinstance(raw_lobs, list):
                for l in raw_lobs:
                  if not isinstance(l, dict):
                    continue
                  lobs_in.append(
                    {
                      "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                      "lob_name": str(l.get("lob_name") or "").strip(),
                    }
                  )
              suggested = propose_marketing_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((ops_json or {}).get("business_type") or "").strip(),
                naics_6=naics_6,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                consumer_type=consumer_type_live,
                ops_json=ops_json,
                target_market_json=target_market,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              now_ms = int(time.time() * 1000)
              for s in suggested:
                if not isinstance(s, dict):
                  continue
                proposal_id = f"mk_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "marketing",
                    "title": "Marketing budget (Year 1)",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
                    "updates": [
                      {
                        "key": "monthly_marketing_budget",
                        "value": s.get("monthly_marketing_budget"),
                        "unit": "USD",
                        "time_basis": "month",
                        "rationale": str(s.get("basis") or "").strip() or "Proposed monthly marketing budget.",
                      },
                      {
                        "key": "primary_channels",
                        "value": s.get("primary_channels"),
                        "unit": None,
                        "time_basis": None,
                        "rationale": "Proposed primary acquisition channels.",
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
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass

          suggestion: Dict[str, Any] = {}
          try:
            for p in proposals_now:
              if isinstance(p, dict) and p.get("model") == "marketing":
                updates = p.get("updates") if isinstance(p.get("updates"), list) else []
                derived = p.get("derived") if isinstance(p.get("derived"), list) else []
                suggestion = {
                  "monthly_marketing_budget": next((u.get("value") for u in updates if u.get("key") == "monthly_marketing_budget"), None),
                  "primary_channels": next((u.get("value") for u in updates if u.get("key") == "primary_channels"), None),
                  "year1_marketing_spend": next((d.get("value") for d in derived if d.get("key") == "year1_marketing_spend"), None),
                }
                break
          except Exception:
            suggestion = {}

          turn = marketing_chat_turn(
            intake_context={**intake_context, "marketing_suggestion": suggestion},
            conversation_messages=conversation_messages,
          )
        else:
          turn = target_market_chat_turn(intake_context=intake_context, conversation_messages=conversation_messages)
      elif next_focus == "people":
        people = _parse_json_dict(fresh.get("people_json"))
        headcount = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("headcount_model_json"))))
        headcount_pending = True
        try:
          lobs = headcount.get("lobs")
          if isinstance(lobs, list) and lobs:
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            headcount_pending = any(
              not (
                isinstance((lob.get("derived") if isinstance(lob, dict) else None), dict)
                and isinstance(((lob.get("derived") or {}).get("year1_payroll")), dict)
                and (
                  (((lob.get("derived") or {}).get("year1_payroll") or {}).get("value")) is not None
                  and (
                    not isinstance(((lob.get("derived") or {}).get("year1_payroll") or {}).get("value"), str)
                    or bool(
                      str(((lob.get("derived") or {}).get("year1_payroll") or {}).get("value") or "").strip()
                    )
                  )
                )
              )
              for lob in requires
            )
        except Exception:
          headcount_pending = True

        people_ready = False
        try:
          items = (people or {}).get("people")
          people_ready = isinstance(items, list) and any(isinstance(p, dict) and str(p.get("full_name") or "").strip() for p in (items or []))
        except Exception:
          people_ready = False

        if people_ready and headcount_pending:
          # Ensure at least one headcount proposal exists; propose if missing.
          proposals_now = _parse_json_list(fresh.get("model_card_proposals_json"))
          suggestion: Dict[str, Any] = {}
          if not any(isinstance(p, dict) and p.get("model") == "headcount" for p in proposals_now):
            try:
              from model_card_proposer import propose_headcount_suggestions  # type: ignore
              from wage_lookup import enrich_headcount_roles, normalize_state_code  # type: ignore

              ops_json = _parse_json_dict(fresh.get("operating_model_json"))
              naics_6_live = _resolve_naics_6(
                conn=conn, business_type=str((ops_json or {}).get("business_type") or "")
              )
              state_code = normalize_state_code(fresh.get("address_state"))
              lobs_in = []
              try:
                raw_lobs = headcount.get("lobs")
                if isinstance(raw_lobs, list):
                  for l in raw_lobs:
                    if isinstance(l, dict):
                      lobs_in.append(
                        {
                          "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                          "lob_name": str(l.get("lob_name") or "").strip(),
                        }
                      )
              except Exception:
                lobs_in = []
              suggested = propose_headcount_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((ops_json or {}).get("business_type") or "").strip(),
                naics_6=naics_6_live,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                ops_json=ops_json,
                people_json=people,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              if suggested and isinstance(suggested[0], dict):
                suggestion = suggested[0]
              now_ms = int(time.time() * 1000)
              for s in suggested:
                if not isinstance(s, dict):
                  continue
                roles = s.get("roles")
                if not isinstance(roles, list) or not roles:
                  continue
                roles_enriched, total = enrich_headcount_roles(
                  conn=conn, roles=roles, state_code=state_code, state_name=None, naics_6=naics_6_live
                )
                proposal_id = f"hc_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "headcount",
                    "title": "Headcount (Year 1 payroll)",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
                    "updates": [
                      {
                        "key": "roles",
                        "value": roles_enriched,
                        "unit": None,
                        "time_basis": None,
                        "rationale": str(s.get("basis") or "").strip()
                        or "Proposed Year-1 staffing plan; edit roles/counts as needed.",
                      }
                    ],
                    "derived": [
                      {
                        "key": "year1_payroll",
                        "value": float(total),
                        "unit": "USD",
                        "time_basis": "year",
                        "derivation": "sum(employee_count x hourly_rate x hours_per_week x weeks_per_year)",
                      }
                    ],
                    "created_at_ms": now_ms,
                  },
                ]
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass

          # Hard fallback: ensure at least one proposal exists for button-only interaction.
          try:
            if not any(isinstance(p, dict) and p.get("model") == "headcount" for p in proposals_now):
              now_ms = int(time.time() * 1000)
              proposals_now = [
                *proposals_now,
                {
                  "id": f"hc_{now_ms}_{len(proposals_now)+1}",
                  "model": "headcount",
                  "title": "Headcount (Year 1 payroll)",
                  "lob_key": "company_total",
                  "lob_name": None,
                  "updates": [
                    {
                      "key": "roles",
                      "value": [],
                      "unit": None,
                      "time_basis": None,
                      "rationale": "Proposed Year-1 staffing plan; edit roles/counts as needed.",
                    }
                  ],
                  "derived": [
                    {
                      "key": "year1_payroll",
                      "value": fresh.get("year1_payroll"),
                      "unit": "USD",
                      "time_basis": "year",
                      "derivation": "sum(employee_count x hourly_rate x hours_per_week x weeks_per_year)",
                    }
                  ],
                  "created_at_ms": now_ms,
                },
              ]
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
          except Exception:
            pass

          turn = headcount_chat_turn(
            intake_context={**intake_context, "headcount_suggestion": suggestion},
            conversation_messages=conversation_messages,
          )
        else:
          turn = people_capability_chat_turn(intake_context=intake_context, conversation_messages=conversation_messages)
      elif next_focus == "financials":
        turn = financials_chat_turn(intake_context=intake_context, conversation_messages=conversation_messages)

      assistant_message = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())

      # If a revenue-relevant driver was just edited, always reprint the updated revenue math
      # (trust surface) before continuing, so the client sees immediate recompute.
      revenue_updated = bool(
        model == "revenue"
        or (model == "pricing" and pricing_unit_price_updated)
      )
      if revenue_updated:
        try:
          revenue_card_live = _ensure_company_total_lob(
            _normalize_model_card(_parse_json_dict(fresh.get("revenue_model_json")))
          )
          ops_live = _parse_json_dict(fresh.get("operating_model_json"))
          unit_name_live = str((ops_live or {}).get("unit_name") or "").strip()
          rev_turn = revenue_chat_turn(
            intake_context={**intake_context, "revenue_card": revenue_card_live, "unit_name": unit_name_live},
            conversation_messages=conversation_messages,
          )
          rev_text = sanitize_fact_template(str(rev_turn.get("assistant_message") or "").strip())
          if rev_text and (rev_text not in assistant_message):
            assistant_message = "\n\n".join([t for t in (rev_text, assistant_message) if str(t or "").strip()]).strip()
        except Exception:
          pass
    except Exception:
      assistant_message = ""

    state_after = get_draft(conn, draft_id=draft_id)
    interaction_mode_out = "button_only" if _parse_json_list(state_after.get("model_card_proposals_json")) else "chat"

    if assistant_message:
      append_messages(
        conn,
        draft_id=draft_id,
        new_messages=[{"role": "assistant", "content": assistant_message}],
        active_focus=next_focus,
        status="in_progress",
        interaction_mode=interaction_mode_out,
      )
    else:
      if next_focus == "done":
        assistant_message = "All sections are complete."
        append_messages(
          conn,
          draft_id=draft_id,
          new_messages=[{"role": "assistant", "content": assistant_message}],
          active_focus="done",
          status="completed",
          completed=True,
          consistency_passed=True,
          interaction_mode="chat",
        )

    return jsonify(
      {
        "status": "ok",
        "draft_id": draft_id,
        "client_id": str(draft.get("client_id") or "").strip(),
        "model": model,
        "driver_revision_nonce": next_nonce,
        "active_focus": next_focus,
        "interaction_mode": interaction_mode_out,
        "assistant_message": assistant_message,
        "model_card": next_card,
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass
