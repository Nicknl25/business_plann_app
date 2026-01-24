from __future__ import annotations

import re
from typing import Any, Dict, Optional


_FACT_PATTERN = re.compile(r"\{\{fact:([A-Za-z0-9_.-]+)\}\}")


BUSINESS_FACT_FIELDS = {"name", "address", "start_date"}

OPS_FACT_FIELDS = {
  "consumer_type",
  "business_type",
  "unit_name",
  "unit_description",
  "unit_cadence",
  "units_per_week_capacity",
  "units_per_period_capacity",
  "unit_price",
  "shipping_method",
  "sales_modality",
  "geographic_scope",
  "geographic_coverage",
  "countries",
  "milestones",
  "capacity_driver",
  "primary_growth_lever",
  "initial_assets",
  "initial_lease",
  "initial_equity",
  "total_debt_outstanding",
  "legal_entity",
  "confidence",
  "business_description_summary",
}

MARKET_FACT_FIELDS = {
  "consumer_type",
  "gender_age_intent",
  "income_intent",
  "selections",
  "b2b_industry_terms",
  "b2b_naics_6",
  "b2b_size_bands",
  "b2b_age_bands",
  "target_market_summary",
  "confidence",
}

PEOPLE_FACT_FIELDS = {
  "people",
  "key_people_summary",
  "confidence",
}

FINANCIALS_FACT_FIELDS = {
  "financials_summary",
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
  "initial_assets",
  "initial_lease",
  "initial_equity",
  "total_debt_outstanding",
  "annual_interest_payment",
  "annual_principal_payment",
  "owner_compensation",
  "cash_on_hand",
  "confidence",
}


FACT_GROUPS = {
  "business": BUSINESS_FACT_FIELDS,
  "ops": OPS_FACT_FIELDS,
  "market": MARKET_FACT_FIELDS,
  "people": PEOPLE_FACT_FIELDS,
  "financials": FINANCIALS_FACT_FIELDS,
}


OPS_MONEY_FIELDS = {"unit_price", "initial_assets", "initial_equity", "total_debt_outstanding"}
FIN_MONEY_FIELDS = {
  "current_revenue",
  "current_cogs",
  "other_operating_expense",
  "monthly_rent_expense",
  "other_monthly_debt_payments",
  "current_payroll",
  "current_capex",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
  "initial_assets",
  "initial_equity",
  "total_debt_outstanding",
  "annual_interest_payment",
  "annual_principal_payment",
  "owner_compensation",
  "cash_on_hand",
}
COUNT_FIELDS = {"units_per_week_capacity", "units_per_period_capacity", "current_num_employees"}


def is_allowed_fact_key(key: str) -> bool:
  raw = str(key or "").strip()
  if not raw or raw.count(".") != 1:
    return False
  group, field = raw.split(".", 1)
  allowed = FACT_GROUPS.get(group)
  return bool(allowed and field in allowed)


def sanitize_fact_template(text: str) -> str:
  if not text:
    return text

  def _replace(match: re.Match[str]) -> str:
    key = match.group(1) or ""
    return match.group(0) if is_allowed_fact_key(key) else ""

  return _FACT_PATTERN.sub(_replace, str(text))


def _to_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  if isinstance(value, bool):
    return None
  if isinstance(value, (int, float)):
    return float(value)
  try:
    return float(str(value).strip().replace(",", ""))
  except Exception:
    return None


def _format_number(value: Any, *, money: bool) -> str:
  num = _to_float(value)
  if num is None:
    # Canonical intake facts should be non-null; when they aren't, default to 0 so
    # fact-bearing templates never display blanks.
    return "$0" if money else "0"
  if abs(num - round(num)) < 1e-9:
    core = f"{int(round(num)):,}"
  else:
    core = f"{num:,.2f}".rstrip("0").rstrip(".")
  return f"${core}" if money else core


def _format_lease(value: Any) -> str:
  if value is None:
    return "none"
  raw = str(value).strip()
  if not raw:
    return "none"
  parts = [p.strip() for p in raw.split(",")]
  amount = _to_float(parts[0]) if parts else None
  period = parts[1] if len(parts) > 1 else ""
  if not amount or amount <= 1e-9:
    return "none" if (period.lower() in ("none", "n/a", "na", "")) else f"$0/{period}"
  money = _format_number(amount, money=True)
  if not period or period.lower() in ("none",):
    return money
  return f"{money}/{period}"


def render_fact_template(
  text: str,
  *,
  shared_context: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> str:
  """
  Deterministically renders {{fact:<group>.<field>}} placeholders using the latest facts.

  This is used for:
  - displaying fact-bearing templates in the UI
  - providing rendered conversation context back to GPT (so it sees natural text)
  """
  if not text:
    return text

  def resolve_value(group: str, field: str) -> Any:
    if group == "business":
      return business_facts.get(field)
    if group == "ops":
      return (shared_context.get("operating_model") or {}).get(field)
    if group == "market":
      return (shared_context.get("target_market") or {}).get(field)
    if group == "people":
      return (shared_context.get("people_capability") or {}).get(field)
    if group == "financials":
      return (shared_context.get("financials") or {}).get(field)
    return None

  def format_value(group: str, field: str, value: Any) -> str:
    if field == "initial_lease":
      return _format_lease(value)

    if field in COUNT_FIELDS:
      return _format_number(value, money=False)

    if group == "ops" and field in OPS_MONEY_FIELDS:
      return _format_number(value, money=True)
    if group == "financials" and field in FIN_MONEY_FIELDS:
      return _format_number(value, money=True)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
      return _format_number(value, money=False)
    if isinstance(value, list):
      # Display lists compactly for templates.
      return ", ".join([str(v) for v in value if v is not None]).strip()
    if isinstance(value, dict):
      return ""
    return str(value).strip() if value is not None else ""

  def _replace(match: re.Match[str]) -> str:
    key = (match.group(1) or "").strip()
    if not is_allowed_fact_key(key):
      return ""
    group, field = key.split(".", 1)
    raw_value = resolve_value(group, field)
    return format_value(group, field, raw_value)

  return _FACT_PATTERN.sub(_replace, str(text))
