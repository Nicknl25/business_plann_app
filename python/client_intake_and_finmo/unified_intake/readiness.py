from __future__ import annotations

from typing import Any, Dict, List, Tuple


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


def marketing_ready(marketing_model_json: Dict[str, Any]) -> bool:
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


def milestones_ready(milestones_model_json: Dict[str, Any]) -> bool:
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


def headcount_ready(headcount_model_json: Dict[str, Any]) -> bool:
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


def revenue_ready(revenue_model_json: Dict[str, Any]) -> bool:
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


def cogs_ready(cogs_model_json: Dict[str, Any]) -> bool:
  try:
    if isinstance(cogs_model_json, dict) and isinstance(cogs_model_json.get("lobs"), list):
      lobs = cogs_model_json.get("lobs") or []
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
        y1 = derived.get("year1_cogs")
        ok = isinstance(y1, dict) and _has_value(y1.get("value"))
        if not ok:
          return False
      return True
    derived = cogs_model_json.get("derived") if isinstance(cogs_model_json, dict) else None
    if isinstance(derived, dict) and "year1_cogs" in derived:
      val = derived.get("year1_cogs") or {}
      if isinstance(val, dict) and _has_value(val.get("value")):
        return True
  except Exception:
    return False
  return False


def gna_ready(gna_model_json: Dict[str, Any]) -> bool:
  try:
    if isinstance(gna_model_json, dict) and isinstance(gna_model_json.get("lobs"), list):
      lobs = gna_model_json.get("lobs") or []
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
        y1 = derived.get("year1_gna_total")
        ok = isinstance(y1, dict) and _has_value(y1.get("value"))
        if not ok:
          return False
      return True
    derived = gna_model_json.get("derived") if isinstance(gna_model_json, dict) else None
    if isinstance(derived, dict) and "year1_gna_total" in derived:
      val = derived.get("year1_gna_total") or {}
      if isinstance(val, dict) and _has_value(val.get("value")):
        return True
  except Exception:
    return False
  return False


def model_has_required_drivers(model_json: Dict[str, Any], required_keys: Tuple[str, ...]) -> bool:
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


def target_market_data_ready(*, market_json: Dict[str, Any], consumer_type: str) -> bool:
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


def people_data_ready(*, people_json: Dict[str, Any]) -> bool:
  items = (people_json or {}).get("people")
  if not isinstance(items, list) or not items:
    return False
  return any(isinstance(p, dict) and str(p.get("full_name") or "").strip() for p in items)


def financials_data_ready(*, financials_json: Dict[str, Any]) -> bool:
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
