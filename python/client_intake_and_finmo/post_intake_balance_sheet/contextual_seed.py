"""Business-context balance-sheet driver seeding.

Module 5 Task 5.3 — Python proposes the balance-sheet seed grid; GPT
critiques. Python's `propose_balance_sheet_contextual_seed_payload`
builds the full payload from:
  1. Tier A intake anchors (stub-0 ar_balance, ap_balance, inventory_balance,
     prepaid_expenses, deferred_revenue when present)
  2. NAICS-cascade days/percent values (Module 1 resolver) for Q1+ trajectory
  3. Per-lever applicability gates from NAICS-2 sectors
GPT receives the proposal and may amend specific applicable / seed_value
fields based on business-specific judgment (e.g., a retail superstore with
a membership program → flip deferred_revenue.applicable=true). Python
applies the corrections via the shared critique contract.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_driver_formula_contract_rows,
)


BALANCE_SHEET_CONTEXTUAL_SEED_CONTRACT_NAME = "balance_sheet_contextual_seed"
BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY = "balance_sheet_contextual_seed"
HORIZON = 20


def _clean(value: Any) -> str:
  return str(value or "").strip()


def _lower(value: Any) -> str:
  return _clean(value).lower()


def _safe_float(value: Any) -> Optional[float]:
  try:
    if value is None or value == "":
      return None
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _clean_list(value: Any) -> List[str]:
  if not isinstance(value, list):
    return []
  return [
    _clean(item).lower()
    for item in value
    if _clean(item)
  ]


def _live_values(row: Dict[str, Any], *, horizon: int = HORIZON) -> List[Any]:
  values = list(row.get("values") or [])
  if len(values) >= horizon + 1:
    return values[1 : horizon + 1]
  return values[:horizon]


def _compose_period_values(*, stub_value: Any, live_values: List[float]) -> List[float]:
  return [float(_safe_float(stub_value) or 0.0), *[round(float(value), 6) for value in live_values[:HORIZON]]]


def _iter_model_input_rows(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []
  for section_name in ("revenue", "expenses", "balance_sheet"):
    section_rows = sections.get(section_name)
    if isinstance(section_rows, list):
      rows.extend(row for row in section_rows if isinstance(row, dict))
  return rows


def _find_row_for_lever(model_input_json: Optional[Dict[str, Any]], lever_id: str) -> Optional[Dict[str, Any]]:
  for row in _iter_model_input_rows(model_input_json):
    if _clean(row.get("lever_id")) == lever_id:
      return row
  return None


def balance_sheet_contextual_seed_candidate_rows() -> List[Dict[str, Any]]:
  """Return mapping-table rows that require contextual seeding when applicable."""
  rows: List[Dict[str, Any]] = []
  for row in post_intake_driver_formula_contract_rows():
    if not isinstance(row, dict):
      continue
    lever_id = _clean(row.get("lever_id"))
    if not lever_id.startswith("balance_sheet::"):
      continue
    if _lower(row.get("driver_bundle")) != "working_capital_bundle":
      continue
    if _lower(row.get("forecast_presence_rule_key")) != "positive_driver_when_applicable":
      continue
    rows.append(copy.deepcopy(row))
  if not rows:
    raise RuntimeError(
      "balance_sheet_contextual_seed_candidates_missing: "
      "sql.post_intak_mapping_lookup must define active balance-sheet seed candidate rows."
    )
  return rows


def _candidate_by_lever() -> Dict[str, Dict[str, Any]]:
  return {
    _clean(row.get("lever_id")): row
    for row in balance_sheet_contextual_seed_candidate_rows()
    if _clean(row.get("lever_id"))
  }


def _bounds_for_row(row: Dict[str, Any]) -> tuple[float, float]:
  minimum = _safe_float(row.get("minimum_live_value"))
  maximum = _safe_float(row.get("maximum_live_value"))
  if minimum is None:
    raise RuntimeError(f"balance_sheet_contextual_seed_min_bound_missing: {row.get('lever_id')}")
  if maximum is None:
    raise RuntimeError(f"balance_sheet_contextual_seed_max_bound_missing: {row.get('lever_id')}")
  if float(maximum) < float(minimum):
    raise RuntimeError(
      f"balance_sheet_contextual_seed_bounds_invalid: {row.get('lever_id')} min={minimum} max={maximum}"
    )
  return float(minimum), float(maximum)


def validate_balance_sheet_contextual_seed_payload(
  payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Validate GPT's contextual balance-sheet seed contract against mapping table."""
  candidate_map = _candidate_by_lever()
  source = payload if isinstance(payload, dict) else {}
  rows = [row for row in (source.get("balance_sheet_seed_grid") or []) if isinstance(row, dict)]
  if not rows:
    raise RuntimeError("balance_sheet_contextual_seed_contract_empty: balance_sheet_seed_grid is required.")
  seen: set[str] = set()
  normalized_rows: List[Dict[str, Any]] = []
  errors: List[str] = []
  for item in rows:
    lever_id = _clean(item.get("lever_id"))
    if lever_id not in candidate_map:
      errors.append(f"unsupported_lever_id={lever_id}")
      continue
    if lever_id in seen:
      errors.append(f"duplicate_lever_id={lever_id}")
      continue
    seen.add(lever_id)
    mapping_row = candidate_map[lever_id]
    applicable = bool(item.get("applicable"))
    seed_value = _safe_float(item.get("seed_value"))
    mapping_value_kind = _lower(mapping_row.get("value_kind"))
    value_kind = _lower(item.get("value_kind")) or mapping_value_kind
    minimum, maximum = _bounds_for_row(mapping_row)
    if value_kind != mapping_value_kind:
      errors.append(f"{lever_id}:value_kind_mismatch expected={mapping_value_kind} actual={value_kind}")
    if applicable:
      if seed_value is None:
        errors.append(f"{lever_id}:seed_value_missing_when_applicable")
      elif float(seed_value) < minimum or float(seed_value) > maximum:
        errors.append(f"{lever_id}:seed_value_out_of_bounds value={seed_value} min={minimum} max={maximum}")
    else:
      seed_value = 0.0
    normalized_rows.append(
      {
        "lever_id": lever_id,
        "target_driver": _clean(mapping_row.get("target_driver")),
        "value_kind": value_kind,
        "input_semantics": _lower(mapping_row.get("input_semantics")),
        "business_applicability_key": _lower(mapping_row.get("business_applicability_key")),
        "applicability_positive_tokens": _clean_list(mapping_row.get("applicability_positive_tokens")),
        "applicability_negative_tokens": _clean_list(mapping_row.get("applicability_negative_tokens")),
        "applicable": bool(applicable),
        "seed_value": round(float(seed_value or 0.0), 6),
        "minimum_live_value": minimum,
        "maximum_live_value": maximum,
        "rationale": _clean(item.get("rationale")),
        "source_of_truth": "sql.post_intak_mapping_lookup + sql.post_intake_gpt_contract_lookup",
      }
    )
  missing = sorted(set(candidate_map.keys()) - seen)
  if missing:
    errors.append(f"missing_candidate_rows={missing}")
  if errors:
    raise RuntimeError(
      "balance_sheet_contextual_seed_contract_invalid: " + "; ".join(errors[:20])
    )
  return {
    "contract_version": _clean(source.get("contract_version")) or "balance_sheet_contextual_seed_v1",
    "balance_sheet_seed_grid": normalized_rows,
    "rationale": _clean(source.get("rationale")),
    "source_of_truth": "sql.post_intake_gpt_contract_lookup",
  }


def apply_balance_sheet_contextual_seed_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  payload: Optional[Dict[str, Any]],
  *,
  live_count: int = HORIZON,
) -> Dict[str, Any]:
  """Apply validated contextual seed values to balance-sheet model-input rows."""
  validated = validate_balance_sheet_contextual_seed_payload(payload)
  next_payload = copy.deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  if not isinstance(sections, dict):
    raise RuntimeError("balance_sheet_contextual_seed_model_input_sections_missing")
  applied_rows: List[Dict[str, Any]] = []
  for seed_row in validated["balance_sheet_seed_grid"]:
    lever_id = _clean(seed_row.get("lever_id"))
    model_row = _find_row_for_lever(next_payload, lever_id)
    if not isinstance(model_row, dict):
      raise RuntimeError(f"balance_sheet_contextual_seed_model_input_row_missing: {lever_id}")
    values = list(model_row.get("values") or [])
    stub_value = values[0] if values else 0.0
    existing_live = _live_values(model_row, horizon=live_count)
    seed_value = float(_safe_float(seed_row.get("seed_value")) or 0.0)
    live_values: List[float] = []
    for idx in range(max(0, live_count)):
      existing = _safe_float(existing_live[idx]) if idx < len(existing_live) else None
      if bool(seed_row.get("applicable")):
        live_values.append(round(seed_value, 6))
      else:
        live_values.append(round(float(existing or 0.0), 6))
    model_row["values"] = _compose_period_values(stub_value=stub_value, live_values=live_values)
    model_row["derived_driver"] = BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY
    model_row["balance_sheet_contextual_seed"] = copy.deepcopy(seed_row)
    applied_rows.append(
      {
        "lever_id": lever_id,
        "applicable": bool(seed_row.get("applicable")),
        "seed_value": round(seed_value, 6),
      }
    )
  next_payload.setdefault("derived_driver_policies", {})
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"][BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY] = validated
  next_payload.setdefault("derived_driver_runtime", {})
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"][BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY] = {
      "source_contract": BALANCE_SHEET_CONTEXTUAL_SEED_CONTRACT_NAME,
      "applied_rows": applied_rows,
    }
  return next_payload


# ===========================================================================
# Module 5 Task 5.3 — Python proposer for the balance-sheet contextual seed.
#
# Maps each candidate lever to its NAICS metric, applicability rule, and
# trajectory formula. The proposer never invents new levers — it walks the
# `balance_sheet_contextual_seed_candidate_rows()` list and produces one row
# per candidate, in the same payload shape `validate_balance_sheet_contextual_seed_payload`
# accepts. GPT critiques the proposal; if GPT amends, Python applies the
# corrections via the shared critique contract; if GPT rejects or fails,
# the proposal stands as the safety floor.
# ===========================================================================


# Lever-to-NAICS-metric map. When the lever's resolver metric is None, the
# proposer falls back to the legacy mapping-table band midpoint.
_LEVER_TO_NAICS_METRIC: Dict[str, str] = {
  "balance_sheet::Accounts Receivable Days": "ar_days_dso",
  "balance_sheet::Accounts Payable Days": "ap_days_dpo",
  "balance_sheet::Inventory Days": "inventory_days",
  "balance_sheet::Prepaid Expenses (% of Revenue)": "prepaid_expenses_percent_of_revenue",
  "balance_sheet::Deferred Revenue (% of Revenue)": "deferred_revenue_percent_of_revenue",
}


# NAICS-2 sectors where each lever applies. None = always applies.
_LEVER_APPLICABILITY_NAICS_2: Dict[str, Optional[set]] = {
  "balance_sheet::Accounts Receivable Days": None,  # universal — every business with revenue has some AR cycle
  "balance_sheet::Accounts Payable Days": None,    # universal — every business with operating expenses has some AP cycle
  "balance_sheet::Inventory Days": {"31", "32", "33", "42", "44", "45", "72"},
  "balance_sheet::Prepaid Expenses (% of Revenue)": None,  # universal but small for most businesses
  "balance_sheet::Deferred Revenue (% of Revenue)": {"51", "52", "53", "54", "62"},
}


def _proposer_clamp_to_bounds(value: float, min_value: float, max_value: float) -> float:
  if min_value > max_value:
    min_value, max_value = max_value, min_value
  return max(min_value, min(max_value, float(value)))


def _proposer_intake_implied_seed(
  *,
  lever_id: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Optional[float]:
  """Tier A: when intake stub-0 supplies the balance, return the implied
  days/percent for the trajectory anchor. None when intake didn't provide.
  """
  revenue_year_one = (
    _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    or _safe_float((financials_year1_json or {}).get("revenue_total_year1"))
    or _safe_float((financials_json or {}).get("current_revenue"))
  )
  if revenue_year_one is None or revenue_year_one <= 0.0:
    return None
  quarter_revenue = float(revenue_year_one) / 4.0
  if lever_id == "balance_sheet::Accounts Receivable Days":
    ar = _safe_float((financials_json or {}).get("ar_balance"))
    if ar is None or ar <= 0.0:
      return None
    return (float(ar) / quarter_revenue) * 90.0
  if lever_id == "balance_sheet::Accounts Payable Days":
    ap = _safe_float((financials_json or {}).get("ap_balance"))
    if ap is None or ap <= 0.0:
      return None
    # Approximate ap_expense_base = revenue × (1 - typical_gross_margin)
    # Conservative anchor: scale by quarter revenue. The Module 1 wiring
    # uses the actual operating-expense base in the live row computation.
    return (float(ap) / quarter_revenue) * 90.0
  if lever_id == "balance_sheet::Inventory Days":
    inventory = _safe_float((financials_json or {}).get("inventory_balance"))
    if inventory is None or inventory <= 0.0:
      return None
    return (float(inventory) / quarter_revenue) * 90.0
  if lever_id == "balance_sheet::Prepaid Expenses (% of Revenue)":
    prepaid = _safe_float((financials_json or {}).get("prepaid_expenses"))
    if prepaid is None or prepaid <= 0.0:
      return None
    return float(prepaid) / quarter_revenue
  if lever_id == "balance_sheet::Deferred Revenue (% of Revenue)":
    deferred = _safe_float((financials_json or {}).get("deferred_revenue"))
    if deferred is None or deferred <= 0.0:
      return None
    return float(deferred) / quarter_revenue
  return None


def _proposer_naics_seed(*, lever_id: str, business_naics_6: str) -> Optional[Dict[str, Any]]:
  """NAICS-cascade fallback: returns the resolver payload's benchmark_target
  for the lever's metric, or None when the lever is not in the metric map
  or the cascade has no coverage.
  """
  metric_key = _LEVER_TO_NAICS_METRIC.get(lever_id)
  if not metric_key or not business_naics_6:
    return None
  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
    band = post_intake_industry_baseline_for_naics(metric_key=metric_key, naics_6=business_naics_6)
  except Exception:
    return None
  if not isinstance(band, dict) or band.get("trust_flag") == "no_coverage":
    return None
  target = band.get("benchmark_target")
  if target is None:
    target = band.get("benchmark_min") or band.get("benchmark_max")
  if target is None:
    return None
  return {
    "benchmark_target": float(target),
    "metric_key": metric_key,
    "naics_code_used": band.get("naics_code_used"),
    "naics_level_used": band.get("naics_level_used"),
    "confidence_tier": band.get("confidence_tier"),
    "data_source": band.get("data_source"),
    "trust_flag": band.get("trust_flag"),
  }


def _proposer_applicability_for_lever(*, lever_id: str, business_naics_6: str) -> Dict[str, Any]:
  """Determines whether each lever applies for a given business based on
  NAICS-2 sector. Returns dict with `applicable` bool and `reason` string.
  """
  naics_2 = "".join(ch for ch in str(business_naics_6 or "") if ch.isdigit())[:2]
  applicable_set = _LEVER_APPLICABILITY_NAICS_2.get(lever_id)
  if applicable_set is None:
    return {"applicable": True, "reason": "lever_universally_applicable"}
  if not naics_2:
    # Conservative default for ambiguous-sector levers when NAICS missing.
    return {"applicable": False, "reason": f"lever_gated_by_naics2_unknown_naics"}
  if naics_2 in applicable_set:
    return {"applicable": True, "reason": f"naics2_{naics_2}_in_applicable_set"}
  return {"applicable": False, "reason": f"naics2_{naics_2}_not_in_applicable_set"}


def propose_balance_sheet_contextual_seed_payload(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Module 5 Task 5.3 — build the balance-sheet seed proposal deterministically.

  Per-lever logic:
    1. Determine `applicable` from NAICS-2 sector.
    2. When applicable=False → seed_value = 0 (legitimate zero).
    3. When applicable=True:
       a. Tier A intake anchor (stub-0 balance × 90 / revenue) takes
          priority when present.
       b. Otherwise, NAICS-cascade benchmark_target.
       c. Clamp to mapping-table min/max bounds.
    4. Carry NAICS provenance for every row that used the cascade.

  Returns the same payload shape `validate_balance_sheet_contextual_seed_payload`
  expects so downstream `apply_balance_sheet_contextual_seed_to_model_input`
  works unchanged.
  """
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}

  business_naics_6 = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit())
  candidate_rows = balance_sheet_contextual_seed_candidate_rows()

  proposed_rows: List[Dict[str, Any]] = []
  for candidate in candidate_rows:
    lever_id = _clean(candidate.get("lever_id"))
    if not lever_id:
      continue
    minimum, maximum = _bounds_for_row(candidate)
    value_kind = _lower(candidate.get("value_kind"))

    applicability = _proposer_applicability_for_lever(
      lever_id=lever_id, business_naics_6=business_naics_6
    )
    naics_provenance: Optional[Dict[str, Any]] = None
    rationale_parts: List[str] = []

    if not applicability["applicable"]:
      seed_value = 0.0
      rationale_parts.append(f"applicable=false ({applicability['reason']})")
    else:
      intake_implied = _proposer_intake_implied_seed(
        lever_id=lever_id,
        financials_json=financials,
        financials_year1_json=year1,
      )
      if intake_implied is not None and intake_implied > 0.0:
        seed_value = _proposer_clamp_to_bounds(intake_implied, minimum, maximum)
        rationale_parts.append(f"tier_a_intake_anchor (raw={intake_implied:.4f})")
      else:
        naics_band = _proposer_naics_seed(lever_id=lever_id, business_naics_6=business_naics_6)
        if naics_band is not None:
          seed_value = _proposer_clamp_to_bounds(naics_band["benchmark_target"], minimum, maximum)
          naics_provenance = {
            "metric_key": naics_band["metric_key"],
            "naics_code_used": naics_band["naics_code_used"],
            "naics_level_used": naics_band["naics_level_used"],
            "confidence_tier": naics_band["confidence_tier"],
            "data_source": naics_band["data_source"],
            "trust_flag": naics_band["trust_flag"],
          }
          rationale_parts.append(
            f"naics_cascade ({naics_band['metric_key']} target={naics_band['benchmark_target']:.4f})"
          )
        else:
          # No intake anchor, no NAICS coverage → mapping-band midpoint.
          seed_value = (float(minimum) + float(maximum)) / 2.0
          rationale_parts.append("mapping_band_midpoint_fallback")

    row: Dict[str, Any] = {
      "lever_id": lever_id,
      "applicable": bool(applicability["applicable"]),
      "seed_value": round(float(seed_value), 6),
      "value_kind": value_kind,
      "rationale": "; ".join(rationale_parts) or "deterministic_proposer",
    }
    if naics_provenance is not None:
      row["naics_provenance"] = naics_provenance
    proposed_rows.append(row)

  return {
    "contract_version": "balance_sheet_contextual_seed_proposal_v1",
    "decision_source": "python_proposer",
    "balance_sheet_seed_grid": proposed_rows,
    "rationale": (
      "Python proposer: per-lever applicability gated by NAICS-2; seed values "
      "from Tier A intake anchors when present, else NAICS resolver, else "
      "mapping-table band midpoint. GPT critique may amend specific rows."
    ),
    "source_of_truth": "python_proposer + sql.post_intake_industry_baseline_lookup",
    "naics_6": business_naics_6 or None,
  }

