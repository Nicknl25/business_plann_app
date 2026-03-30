from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_RETRYABLE_STATUS = {429, 502, 503, 504}
def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _bool_env(name: str, default: bool) -> bool:
  _load_root_env()
  raw = str(os.getenv(name) or "").strip().lower()
  if not raw:
    return default
  if raw in {"1", "true", "yes", "on"}:
    return True
  if raw in {"0", "false", "no", "off"}:
    return False
  return default


def _in_test_context() -> bool:
  joined_argv = " ".join(str(arg or "") for arg in sys.argv).lower()
  return (
    "test_planning_engines.py" in joined_argv
    or "unittest" in joined_argv
    or "\\tests\\" in joined_argv
  )


def _require_openai_key() -> str:
  _load_root_env()
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def _openai_model() -> str:
  _load_root_env()
  return (
    os.getenv("CONSISTENCY_GPT_STRATEGY_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "gpt-5.1"
  ).strip() or "gpt-5.1"


def _timeout_env_int(name: str, default: int) -> int:
  _load_root_env()
  raw = (os.getenv(name) or "").strip()
  if not raw:
    return default
  try:
    return max(15, int(raw))
  except Exception:
    return default


def _openai_timeout_seconds(kind: str = "default") -> int:
  if kind == "audit":
    return _timeout_env_int("CONSISTENCY_GPT_AUDIT_TIMEOUT_SECONDS", 45)
  if kind == "validation":
    return _timeout_env_int("CONSISTENCY_GPT_VALIDATION_TIMEOUT_SECONDS", 60)
  if kind == "strategy":
    return _timeout_env_int("CONSISTENCY_GPT_STRATEGY_TIMEOUT_SECONDS", 75)
  return _timeout_env_int("OPENAI_HTTP_TIMEOUT_SECONDS", 180)


def _strategy_layer_enabled() -> bool:
  if _in_test_context():
    return _bool_env("CONSISTENCY_GPT_STRATEGY_LAYER", False)
  _load_root_env()
  if not str(os.getenv("OPENAI_API_KEY") or "").strip():
    return False
  return True


def _format_openai_error(resp: requests.Response) -> str:
  if resp.status_code in _RETRYABLE_STATUS:
    return "We're having trouble reaching our AI service right now. Please try again in a minute."
  return f"OpenAI API error {resp.status_code}: {resp.text[:500]}"


def _post_openai(
  *,
  url: str,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  timeout_seconds: Optional[int] = None,
  max_attempts: int = 3,
) -> requests.Response:
  timeout = max(15, int(timeout_seconds or _openai_timeout_seconds()))
  attempts = max(1, int(max_attempts or 1))
  last_exc: Optional[Exception] = None
  for attempt in range(attempts):
    try:
      resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
      if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
        time.sleep(0.75 * (2**attempt))
        continue
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:
      last_exc = exc
      if attempt >= attempts - 1:
        raise
      time.sleep(0.75 * (2**attempt))
    except requests.exceptions.ConnectionError as exc:
      last_exc = exc
      if attempt >= attempts - 1:
        raise
      time.sleep(0.75 * (2**attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


def _parse_json_response(data: Dict[str, Any]) -> Dict[str, Any]:
  for item in data.get("output") or []:
    if not isinstance(item, dict):
      continue
    for part in item.get("content") or []:
      if not isinstance(part, dict):
        continue
      parsed = part.get("parsed")
      if isinstance(parsed, dict):
        return parsed
      if part.get("type") != "output_text":
        continue
      raw = str(part.get("text") or "").strip()
      if not raw:
        continue
      try:
        parsed = json.loads(raw)
      except Exception:
        continue
      if isinstance(parsed, dict):
        return parsed
  return {}


def _sanitize_canonical_live_payload(value: Any) -> Any:
  if isinstance(value, dict):
    cleaned: Dict[str, Any] = {}
    for raw_key, raw_val in value.items():
      cleaned[str(raw_key or "")] = _sanitize_canonical_live_payload(raw_val)
    return cleaned
  if isinstance(value, list):
    return [_sanitize_canonical_live_payload(item) for item in value]
  return value


def _catalog_allowed_levers(strategy_catalog: List[Dict[str, Any]]) -> Dict[str, List[str]]:
  catalog: Dict[str, List[str]] = {}
  for item in strategy_catalog:
    if not isinstance(item, dict):
      continue
    strategy_id = str(item.get("strategy_id") or "").strip()
    if not strategy_id:
      continue
    catalog[strategy_id] = [
      str(lever_id or "").strip()
      for lever_id in (item.get("allowed_model_input_levers") or [])
      if str(lever_id or "").strip()
    ]
  return catalog


def _valid_finmo_line_items(fixed_facts: Dict[str, Any]) -> List[str]:
  finmo_json = (fixed_facts.get("finmo_json") or {}) if isinstance(fixed_facts.get("finmo_json"), dict) else {}
  labels: List[str] = []
  for section_key in ("pl", "balance_sheet", "cash_flow"):
    rows = finmo_json.get(section_key) if isinstance(finmo_json.get(section_key), list) else []
    for row in rows:
      if not isinstance(row, dict):
        continue
      label = str(row.get("label") or "").strip()
      if label:
        labels.append(label)
  if labels:
    return sorted({label for label in labels if label})
  return [
    "Revenue",
    "Gross Profit",
    "EBITDA",
    "Net Income",
    "Cash",
    "Total Assets",
    "Total Liabilities & Equity",
  ]


def _normalize_quarter_span(item: Dict[str, Any]) -> tuple[int, int]:
  start = item.get("quarter_start")
  end = item.get("quarter_end")
  try:
    start_int = max(1, min(20, int(start)))
  except Exception:
    start_int = 1
  try:
    end_int = max(start_int, min(20, int(end)))
  except Exception:
    end_int = start_int
  return start_int, end_int


def _coverage_gaps(spans: List[tuple[int, int]], *, horizon_start: int = 1, horizon_end: int = 20) -> List[tuple[int, int]]:
  if horizon_end < horizon_start:
    return []
  if not spans:
    return [(horizon_start, horizon_end)]
  covered = [False for _ in range(horizon_end - horizon_start + 1)]
  for start, end in spans:
    start_int = max(horizon_start, min(horizon_end, int(start)))
    end_int = max(start_int, min(horizon_end, int(end)))
    for quarter in range(start_int, end_int + 1):
      covered[quarter - horizon_start] = True
  gaps: List[tuple[int, int]] = []
  gap_start: Optional[int] = None
  for offset, is_covered in enumerate(covered):
    quarter = horizon_start + offset
    if not is_covered and gap_start is None:
      gap_start = quarter
    elif is_covered and gap_start is not None:
      gaps.append((gap_start, quarter - 1))
      gap_start = None
  if gap_start is not None:
    gaps.append((gap_start, horizon_end))
  return gaps


def _fixed_governed_period_groups() -> List[Dict[str, Any]]:
  return [
    {
      "quarter_start": 1,
      "quarter_end": 4,
      "objective": "Phase 1",
      "input_granularity": "grouped",
      "quarterly_expansion_levers": [],
      "rationale": "Application-owned fixed period group.",
    },
    {
      "quarter_start": 5,
      "quarter_end": 8,
      "objective": "Phase 2",
      "input_granularity": "grouped",
      "quarterly_expansion_levers": [],
      "rationale": "Application-owned fixed period group.",
    },
    {
      "quarter_start": 9,
      "quarter_end": 12,
      "objective": "Phase 3",
      "input_granularity": "grouped",
      "quarterly_expansion_levers": [],
      "rationale": "Application-owned fixed period group.",
    },
    {
      "quarter_start": 13,
      "quarter_end": 16,
      "objective": "Phase 4",
      "input_granularity": "grouped",
      "quarterly_expansion_levers": [],
      "rationale": "Application-owned fixed period group.",
    },
    {
      "quarter_start": 17,
      "quarter_end": 20,
      "objective": "Phase 5",
      "input_granularity": "grouped",
      "quarterly_expansion_levers": [],
      "rationale": "Application-owned fixed period group.",
    },
  ]


def _minimum_acceptable_ebitda_floor(quarter_index: int) -> Optional[float]:
  try:
    quarter_int = int(quarter_index or 0)
  except Exception:
    quarter_int = 0
  if quarter_int >= 5:
    return 0.0
  return None


def _default_controller_directives(*, severity: str) -> Dict[str, Any]:
  normalized_severity = str(severity or "").strip().lower()
  if normalized_severity == "severe":
    return {
      "minimum_meaningful_levers": 4,
      "require_multi_lever_coordination": True,
      "preserve_capacity_staffing_link": True,
      "preserve_price_demand_link": True,
      "preserve_marketing_demand_link": True,
      "prefer_delay_over_delete": True,
      "aggression_level": "high",
      "escalate_on_retry": True,
      "minimum_package_count": 2,
    }
  if normalized_severity == "moderate":
    return {
      "minimum_meaningful_levers": 2,
      "require_multi_lever_coordination": True,
      "preserve_capacity_staffing_link": True,
      "preserve_price_demand_link": True,
      "preserve_marketing_demand_link": True,
      "prefer_delay_over_delete": True,
      "aggression_level": "moderate",
      "escalate_on_retry": False,
      "minimum_package_count": 2,
    }
  return {
    "minimum_meaningful_levers": 1,
    "require_multi_lever_coordination": False,
    "preserve_capacity_staffing_link": True,
    "preserve_price_demand_link": True,
    "preserve_marketing_demand_link": True,
    "prefer_delay_over_delete": True,
    "aggression_level": "low",
    "escalate_on_retry": False,
    "minimum_package_count": 1,
  }


def _format_gap_ranges(gaps: List[tuple[int, int]]) -> List[str]:
  labels: List[str] = []
  for start, end in gaps:
    labels.append(f"Q{start}" if start == end else f"Q{start}-Q{end}")
  return labels


def _target_covers_quarter(targets: List[Dict[str, Any]], *, line_item: str, quarter_index: int) -> bool:
  wanted = str(line_item or "").strip().lower()
  for item in targets:
    if not isinstance(item, dict):
      continue
    if str(item.get("line_item") or "").strip().lower() != wanted:
      continue
    start_int, end_int = _normalize_quarter_span(item)
    if start_int <= quarter_index <= end_int:
      return True
  return False


def _target_spans_for_line_item(targets: List[Dict[str, Any]], *, line_item: str) -> List[tuple[int, int]]:
  wanted = str(line_item or "").strip().lower()
  spans: List[tuple[int, int]] = []
  for item in targets:
    if not isinstance(item, dict):
      continue
    if str(item.get("line_item") or "").strip().lower() != wanted:
      continue
    spans.append(_normalize_quarter_span(item))
  return spans


def _selection_coverage_issues(
  *,
  selection: Dict[str, Any],
  lever_plan: List[Dict[str, Any]],
  governed_period_groups: List[Dict[str, Any]],
  controlled_output_targets: List[Dict[str, Any]],
) -> List[str]:
  issues: List[str] = []
  governed_spans = [_normalize_quarter_span(item) for item in governed_period_groups if isinstance(item, dict)]
  governed_gaps = _coverage_gaps(governed_spans)
  if governed_gaps:
    issues.append(
      "governed_period_groups_missing_coverage:" + ",".join(_format_gap_ranges(governed_gaps))
    )

  spans_by_lever: Dict[str, List[tuple[int, int]]] = {}
  active_revenue_lever_present = False
  for item in lever_plan:
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    spans_by_lever.setdefault(lever_id, []).append(_normalize_quarter_span(item))
    if lever_id.startswith("revenue::"):
      active_revenue_lever_present = True
  for lever_id, spans in spans_by_lever.items():
    gaps = _coverage_gaps(spans)
    if gaps:
      issues.append(
        f"lever_adjustment_plan_missing_coverage::{lever_id}::" + ",".join(_format_gap_ranges(gaps))
      )

  ebitda_target_gaps = _coverage_gaps(_target_spans_for_line_item(controlled_output_targets, line_item="EBITDA"))
  if ebitda_target_gaps:
    issues.append(
      "controlled_output_targets_missing_ebitda_full_coverage:" + ",".join(_format_gap_ranges(ebitda_target_gaps))
    )

  if active_revenue_lever_present:
    revenue_target_gaps = _coverage_gaps(_target_spans_for_line_item(controlled_output_targets, line_item="Revenue"))
    if revenue_target_gaps:
      issues.append(
        "controlled_output_targets_missing_revenue_full_coverage:" + ",".join(_format_gap_ranges(revenue_target_gaps))
      )
  return issues


def _governed_values(values: Any) -> List[float]:
  normalized: List[float] = []
  for item in (values or []):
    try:
      normalized.append(float(item or 0.0))
    except Exception:
      normalized.append(0.0)
  if len(normalized) == 21:
    normalized = normalized[1:]
  if len(normalized) < 20:
    normalized.extend([0.0 for _ in range(20 - len(normalized))])
  return normalized[:20]


def _model_input_revenue_baseline_by_lever(model_input_json: Dict[str, Any]) -> Dict[str, List[float]]:
  sections = (model_input_json.get("sections") or {}) if isinstance(model_input_json.get("sections"), dict) else {}
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  lever_values: Dict[str, List[float]] = {}
  for row in revenue_rows:
    lob_name = str(row.get("lob") or "").strip()
    product_name = str(row.get("product") or "").strip()
    driver = str(row.get("driver") or "").strip()
    if not (lob_name and product_name and driver):
      continue
    lever_id = f"revenue::{lob_name}::{product_name}::{driver}"
    lever_values[lever_id] = _governed_values(row.get("values") or [])
  return lever_values


def _lever_plan_covering_quarter(
  lever_plan: List[Dict[str, Any]],
  *,
  lever_id: str,
  quarter_index: int,
) -> Optional[Dict[str, Any]]:
  for item in lever_plan:
    if not isinstance(item, dict):
      continue
    if str(item.get("lever_id") or "").strip() != str(lever_id or "").strip():
      continue
    start_int, end_int = _normalize_quarter_span(item)
    if start_int <= quarter_index <= end_int:
      return item
  return None


def _revenue_target_feasibility_issues(
  *,
  lever_plan: List[Dict[str, Any]],
  controlled_output_targets: List[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
) -> List[str]:
  model_input_json = (fixed_facts.get("model_input_json") or {}) if isinstance(fixed_facts.get("model_input_json"), dict) else {}
  baseline_by_lever = _model_input_revenue_baseline_by_lever(model_input_json)
  if not baseline_by_lever:
    return []

  slot_prefixes = sorted({
    "::".join(str(lever_id or "").split("::")[:3])
    for lever_id in baseline_by_lever.keys()
    if str(lever_id or "").startswith("revenue::")
  })
  if not slot_prefixes:
    return []

  issues: List[str] = []
  for raw_target in controlled_output_targets:
    if not isinstance(raw_target, dict):
      continue
    if str(raw_target.get("line_item") or "").strip().lower() != "revenue":
      continue
    target_min = raw_target.get("min_value")
    if target_min in {None, ""}:
      continue
    q_start, q_end = _normalize_quarter_span(raw_target)
    for quarter_index in range(q_start, q_end + 1):
      max_revenue = 0.0
      for slot_prefix in slot_prefixes:
        capacity_lever = f"{slot_prefix}::Capacity"
        price_lever = f"{slot_prefix}::Unit Price"
        utilization_lever = f"{slot_prefix}::Utilization"
        capacity_values = baseline_by_lever.get(capacity_lever) or [0.0 for _ in range(20)]
        price_values = baseline_by_lever.get(price_lever) or [0.0 for _ in range(20)]
        utilization_values = baseline_by_lever.get(utilization_lever) or [0.0 for _ in range(20)]
        try:
          capacity = float(capacity_values[quarter_index - 1] if quarter_index - 1 < len(capacity_values) else 0.0)
        except Exception:
          capacity = 0.0
        try:
          price = float(price_values[quarter_index - 1] if quarter_index - 1 < len(price_values) else 0.0)
        except Exception:
          price = 0.0
        try:
          utilization = float(utilization_values[quarter_index - 1] if quarter_index - 1 < len(utilization_values) else 0.0)
        except Exception:
          utilization = 0.0

        capacity_plan = _lever_plan_covering_quarter(lever_plan, lever_id=capacity_lever, quarter_index=quarter_index)
        price_plan = _lever_plan_covering_quarter(lever_plan, lever_id=price_lever, quarter_index=quarter_index)
        utilization_plan = _lever_plan_covering_quarter(lever_plan, lever_id=utilization_lever, quarter_index=quarter_index)

        if isinstance(capacity_plan, dict) and capacity_plan.get("max_value") not in {None, ""}:
          try:
            capacity = float(capacity_plan.get("max_value") or 0.0)
          except Exception:
            capacity = 0.0
        if isinstance(price_plan, dict) and price_plan.get("max_value") not in {None, ""}:
          try:
            price = float(price_plan.get("max_value") or 0.0)
          except Exception:
            price = 0.0
        if isinstance(utilization_plan, dict) and utilization_plan.get("max_value") not in {None, ""}:
          try:
            utilization = float(utilization_plan.get("max_value") or 0.0)
          except Exception:
            utilization = 0.0
        utilization = max(0.0, min(1.0, utilization))
        max_revenue += capacity * price * utilization

      try:
        target_min_float = float(target_min or 0.0)
      except Exception:
        target_min_float = 0.0
      if target_min_float > (max_revenue + 1e-9):
        issues.append(
          f"controlled_output_targets_infeasible_revenue::Q{quarter_index}::min={round(target_min_float, 6)}::max_reachable={round(max_revenue, 6)}"
        )
  return issues


def _is_ebitda_improving_revenue_lever(lever_id: str) -> bool:
  parts = str(lever_id or "").split("::")
  return len(parts) == 4 and parts[0] == "revenue" and parts[-1] in {"Capacity", "Unit Price", "Utilization"}


def _is_ebitda_improving_expense_lever(lever_id: str) -> bool:
  return str(lever_id or "") in {
    "expenses::Cost of Goods Sold",
    "expenses::Marketing",
    "expenses::Research & Development",
    "expenses::Lease",
    "expenses::Payroll",
    "expenses::General & Administrative",
  }


def _best_case_ebitda_value_for_plan(lever_id: str, plan_item: Dict[str, Any]) -> Optional[float]:
  min_value = plan_item.get("min_value")
  max_value = plan_item.get("max_value")
  if _is_ebitda_improving_revenue_lever(lever_id):
    chosen = max_value if max_value not in {None, ""} else min_value
  elif _is_ebitda_improving_expense_lever(lever_id):
    chosen = min_value if min_value not in {None, ""} else max_value
  else:
    return None
  if chosen in {None, ""}:
    return None
  try:
    return float(chosen or 0.0)
  except Exception:
    return None


def _set_model_input_lever_value(
  book: FinancialModelInputs,
  *,
  lever_id: str,
  quarter_index: int,
  value: float,
) -> None:
  parts = str(lever_id or "").split("::")
  if len(parts) == 4 and parts[0] == "revenue":
    _section, lob_name, product_name, driver = parts
    if driver == "Capacity":
      book.set_revenue_drivers(
        quarter_index=quarter_index,
        lob_name=lob_name,
        product_name=product_name,
        capacity_units=value,
      )
    elif driver == "Unit Price":
      book.set_revenue_drivers(
        quarter_index=quarter_index,
        lob_name=lob_name,
        product_name=product_name,
        unit_price=value,
      )
    elif driver == "Utilization":
      book.set_revenue_drivers(
        quarter_index=quarter_index,
        lob_name=lob_name,
        product_name=product_name,
        utilization=value,
      )
    return
  if len(parts) == 2 and parts[0] in {"expenses", "balance_sheet", "schedules"}:
    book.set_simple_driver(
      section=parts[0],
      label=parts[1],
      quarter_index=quarter_index,
      value=value,
    )


def _ebitda_target_feasibility_issues(
  *,
  lever_plan: List[Dict[str, Any]],
  controlled_output_targets: List[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
) -> List[str]:
  model_input_json = (fixed_facts.get("model_input_json") or {}) if isinstance(fixed_facts.get("model_input_json"), dict) else {}
  if not model_input_json:
    return []
  try:
    book = FinancialModelInputs.from_model_input_json(model_input_json)
    finmo_result = None
  except Exception:
    return []

  for quarter_index in range(1, 21):
    for raw_item in lever_plan:
      if not isinstance(raw_item, dict):
        continue
      lever_id = str(raw_item.get("lever_id") or "").strip()
      if not lever_id:
        continue
      start_int, end_int = _normalize_quarter_span(raw_item)
      if not (start_int <= quarter_index <= end_int):
        continue
      best_case_value = _best_case_ebitda_value_for_plan(lever_id, raw_item)
      if best_case_value is None:
        continue
      _set_model_input_lever_value(
        book,
        lever_id=lever_id,
        quarter_index=quarter_index,
        value=best_case_value,
      )

  try:
    finmo_result = calculate_finmo_model(book)
  except Exception:
    return []
  quarter_rows = {
    int(item.get("quarter_index") or 0): item
    for item in finmo_result.quarter_rows()
    if isinstance(item, dict)
  }

  issues: List[str] = []
  for raw_target in controlled_output_targets:
    if not isinstance(raw_target, dict):
      continue
    if str(raw_target.get("line_item") or "").strip().lower() != "ebitda":
      continue
    target_min = raw_target.get("min_value")
    if target_min in {None, ""}:
      continue
    try:
      target_min_float = float(target_min or 0.0)
    except Exception:
      continue
    q_start, q_end = _normalize_quarter_span(raw_target)
    for quarter_index in range(q_start, q_end + 1):
      quarter_payload = quarter_rows.get(quarter_index) or {}
      try:
        max_reachable = float(quarter_payload.get("ebitda") or 0.0)
      except Exception:
        max_reachable = 0.0
      if target_min_float <= (max_reachable + 1e-9):
        continue
      active_constraint_levers = sorted(
        {
          str(item.get("lever_id") or "").strip()
          for item in lever_plan
          if isinstance(item, dict)
          and (_normalize_quarter_span(item)[0] <= quarter_index <= _normalize_quarter_span(item)[1])
          and (
            _is_ebitda_improving_revenue_lever(str(item.get("lever_id") or "").strip())
            or _is_ebitda_improving_expense_lever(str(item.get("lever_id") or "").strip())
          )
        }
      )
      constraint_suffix = ""
      if active_constraint_levers:
        constraint_suffix = "::active_constraints=" + ",".join(active_constraint_levers)
      issues.append(
        f"controlled_output_targets_infeasible_ebitda::Q{quarter_index}::min={round(target_min_float, 6)}::max_reachable={round(max_reachable, 6)}{constraint_suffix}"
      )
  return issues


def _ebitda_viability_floor_issues(
  *,
  controlled_output_targets: List[Dict[str, Any]],
) -> List[str]:
  issues: List[str] = []
  for raw_target in controlled_output_targets:
    if not isinstance(raw_target, dict):
      continue
    if str(raw_target.get("line_item") or "").strip().lower() != "ebitda":
      continue
    target_min = raw_target.get("min_value")
    if target_min in {None, ""}:
      continue
    try:
      target_min_float = float(target_min or 0.0)
    except Exception:
      continue
    q_start, q_end = _normalize_quarter_span(raw_target)
    violated_quarters: List[int] = []
    for quarter_index in range(q_start, q_end + 1):
      viability_floor = _minimum_acceptable_ebitda_floor(quarter_index)
      if viability_floor is None:
        continue
      if target_min_float < viability_floor:
        violated_quarters.append(quarter_index)
    if violated_quarters:
      issues.append(
        "controlled_output_targets_below_minimum_viability_floor::"
        + ",".join(f"Q{quarter_index}" for quarter_index in violated_quarters)
        + f"::line_item=EBITDA::min={round(target_min_float, 6)}::required_min=0.0"
      )
  return issues


def _normalize_posture_text(value: Any) -> str:
  return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _phase_ebitda_posture(target_posture: Dict[str, Any], *, quarter_start: int) -> str:
  if quarter_start <= 4:
    return _normalize_posture_text(target_posture.get("year1_ebitda_posture"))
  if quarter_start <= 8:
    return _normalize_posture_text(target_posture.get("year2_ebitda_posture"))
  return _normalize_posture_text(target_posture.get("year3_ebitda_posture"))


def _financial_metric_envelope_by_quarter(
  *,
  lever_plan: List[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
  metric_key: str,
) -> tuple[Dict[int, float], Dict[int, float]]:
  model_input_json = (fixed_facts.get("model_input_json") or {}) if isinstance(fixed_facts.get("model_input_json"), dict) else {}
  if not model_input_json:
    return {}, {}
  try:
    baseline_book = FinancialModelInputs.from_model_input_json(model_input_json)
    best_case_book = FinancialModelInputs.from_model_input_json(model_input_json)
  except Exception:
    return {}, {}

  try:
    baseline_rows = {}
    for item in calculate_finmo_model(baseline_book).quarter_rows():
      if not isinstance(item, dict):
        continue
      try:
        baseline_rows[int(item.get("quarter_index") or 0)] = float(item.get(metric_key) or 0.0)
      except Exception:
        continue
  except Exception:
    baseline_rows = {}

  for quarter_index in range(1, 21):
    for raw_item in lever_plan:
      if not isinstance(raw_item, dict):
        continue
      lever_id = str(raw_item.get("lever_id") or "").strip()
      if not lever_id:
        continue
      start_int, end_int = _normalize_quarter_span(raw_item)
      if not (start_int <= quarter_index <= end_int):
        continue
      best_case_value = _best_case_ebitda_value_for_plan(lever_id, raw_item)
      if best_case_value is None:
        continue
      _set_model_input_lever_value(
        best_case_book,
        lever_id=lever_id,
        quarter_index=quarter_index,
        value=best_case_value,
      )

  try:
    best_rows = {}
    for item in calculate_finmo_model(best_case_book).quarter_rows():
      if not isinstance(item, dict):
        continue
      try:
        best_rows[int(item.get("quarter_index") or 0)] = float(item.get(metric_key) or 0.0)
      except Exception:
        continue
  except Exception:
    best_rows = {}
  return baseline_rows, best_rows


def _derive_app_owned_ebitda_targets(
  *,
  lever_plan: List[Dict[str, Any]],
  target_posture: Dict[str, Any],
  fixed_facts: Dict[str, Any],
) -> List[Dict[str, Any]]:
  if not isinstance(target_posture, dict) or not target_posture:
    return []
  baseline_by_quarter, best_by_quarter = _financial_metric_envelope_by_quarter(
    lever_plan=lever_plan,
    fixed_facts=fixed_facts,
    metric_key="ebitda",
  )
  if not baseline_by_quarter or not best_by_quarter:
    return []

  derived_targets: List[Dict[str, Any]] = []
  for group in _fixed_governed_period_groups():
    q_start, q_end = _normalize_quarter_span(group)
    baseline_values = [baseline_by_quarter.get(quarter_index, 0.0) for quarter_index in range(q_start, q_end + 1)]
    best_values = [best_by_quarter.get(quarter_index, 0.0) for quarter_index in range(q_start, q_end + 1)]
    baseline_avg = sum(baseline_values) / max(1, len(baseline_values))
    best_avg = sum(best_values) / max(1, len(best_values))
    posture = _phase_ebitda_posture(target_posture, quarter_start=q_start)
    viability_floor = _minimum_acceptable_ebitda_floor(q_start)

    if viability_floor is None:
      improvement = max(0.0, best_avg - baseline_avg)
      min_value = baseline_avg + (0.25 * improvement)
      max_value = baseline_avg + (0.75 * improvement)
      if max_value < min_value:
        max_value = min_value
    else:
      if best_avg <= viability_floor:
        min_value = viability_floor
        max_value = viability_floor
      elif "profit" in posture or "positive" in posture:
        min_value = max(viability_floor, best_avg * 0.25)
        max_value = max(min_value, best_avg * 0.75)
      elif "break" in posture:
        min_value = viability_floor
        max_value = max(min_value, best_avg * 0.5)
      else:
        min_value = viability_floor
        max_value = max(min_value, best_avg * 0.35)

    derived_targets.append(
      {
        "line_item": "EBITDA",
        "quarter_start": q_start,
        "quarter_end": q_end,
        "min_value": round(float(min_value), 6),
        "max_value": round(float(max_value), 6),
        "rationale": (
          "Application-derived EBITDA band from target_posture and the current reachable envelope. "
          f"Phase posture={posture or 'unspecified'}, baseline_avg={round(baseline_avg, 2)}, best_case_avg={round(best_avg, 2)}."
        ),
      }
    )
  return derived_targets


def _derive_app_owned_revenue_targets(
  *,
  lever_plan: List[Dict[str, Any]],
  target_posture: Dict[str, Any],
  fixed_facts: Dict[str, Any],
) -> List[Dict[str, Any]]:
  if not any(str(item.get("lever_id") or "").strip().startswith("revenue::") for item in lever_plan if isinstance(item, dict)):
    return []
  baseline_by_quarter, best_by_quarter = _financial_metric_envelope_by_quarter(
    lever_plan=lever_plan,
    fixed_facts=fixed_facts,
    metric_key="revenue",
  )
  if not baseline_by_quarter or not best_by_quarter:
    return []
  demand_posture = _normalize_posture_text((target_posture or {}).get("demand_posture"))
  scale_low = 0.25 if "steady" in demand_posture or "maint" in demand_posture else 0.35
  scale_high = 0.7 if "steady" in demand_posture or "maint" in demand_posture else 0.85
  derived_targets: List[Dict[str, Any]] = []
  for group in _fixed_governed_period_groups():
    q_start, q_end = _normalize_quarter_span(group)
    baseline_values = [baseline_by_quarter.get(quarter_index, 0.0) for quarter_index in range(q_start, q_end + 1)]
    best_values = [best_by_quarter.get(quarter_index, 0.0) for quarter_index in range(q_start, q_end + 1)]
    baseline_avg = sum(baseline_values) / max(1, len(baseline_values))
    best_avg = sum(best_values) / max(1, len(best_values))
    improvement = max(0.0, best_avg - baseline_avg)
    min_value = baseline_avg + (scale_low * improvement)
    max_value = baseline_avg + (scale_high * improvement)
    if max_value < min_value:
      max_value = min_value
    derived_targets.append(
      {
        "line_item": "Revenue",
        "quarter_start": q_start,
        "quarter_end": q_end,
        "min_value": round(float(min_value), 6),
        "max_value": round(float(max_value), 6),
        "rationale": (
          "Application-derived Revenue band from the current reachable envelope and demand posture. "
          f"demand_posture={demand_posture or 'unspecified'}, baseline_avg={round(baseline_avg, 2)}, best_case_avg={round(best_avg, 2)}."
        ),
      }
    )
  return derived_targets


def _package_escalation_issues(
  *,
  lever_plan: List[Dict[str, Any]],
  coverage_issues: List[str],
) -> List[str]:
  issues: List[str] = []
  has_ebitda_infeasibility = any(str(item or "").startswith("controlled_output_targets_infeasible_ebitda::") for item in (coverage_issues or []))
  has_capacity_lever = any(
    str(item.get("lever_id") or "").strip().endswith("::Capacity")
    and str(item.get("direction") or "").strip().lower() != "hold"
    for item in lever_plan
    if isinstance(item, dict)
  )
  if has_ebitda_infeasibility and not has_capacity_lever:
    issues.append("viability_requires_capacity_lever_or_broader_scale_strategy")
  return issues


def _merge_retry_context(
  prior_retry_context: Optional[Dict[str, Any]],
  *,
  coverage_issues: List[str],
  prior_selection: Dict[str, Any],
  invalid_reason: str,
  attempt_index: int,
) -> Dict[str, Any]:
  merged = dict(prior_retry_context or {}) if isinstance(prior_retry_context, dict) else {}
  merged["invalid_blueprint_reason"] = str(invalid_reason or "invalid_strategy_blueprint")
  merged["strategy_advisor_attempt_index"] = int(attempt_index or 0)
  merged["coverage_issues"] = list(coverage_issues or [])
  merged["required_fix"] = (
    "Return a complete numeric blueprint. Every active lever must have explicit coverage through Q20, "
    "and controlled_output_targets must provide explicit numeric coverage through Q20."
  )
  merged["prior_strategy_selection"] = _sanitize_canonical_live_payload(prior_selection or {})
  return merged


def _blueprint_contract_issues(selection: Dict[str, Any]) -> List[str]:
  if not isinstance(selection, dict):
    return ["strategy_selection_not_dict"]
  issues: List[str] = []
  selected_ids = [
    str(item or "").strip()
    for item in (selection.get("selected_strategy_ids") or [])
    if str(item or "").strip()
  ]
  if not selected_ids:
    issues.append("selected_strategy_ids_missing")

  allowed_model_input_levers = [
    str(item or "").strip()
    for item in (selection.get("allowed_model_input_levers") or [])
    if str(item or "").strip()
  ]
  lever_plan = [
    item for item in (selection.get("lever_adjustment_plan") or [])
    if isinstance(item, dict)
  ]
  governed_period_groups = [
    item for item in (selection.get("governed_period_groups") or [])
    if isinstance(item, dict)
  ]
  controlled_output_targets = [
    item for item in (selection.get("controlled_output_targets") or [])
    if isinstance(item, dict)
  ]
  if not allowed_model_input_levers:
    issues.append("allowed_model_input_levers_missing")
  if not lever_plan:
    issues.append("lever_adjustment_plan_missing")
  if not governed_period_groups:
    issues.append("governed_period_groups_missing")
  if not controlled_output_targets:
    issues.append("controlled_output_targets_missing")

  plan_levers = {
    str(item.get("lever_id") or "").strip()
    for item in lever_plan
    if str(item.get("direction") or "").strip().lower() != "hold"
    and str(item.get("lever_id") or "").strip()
  }
  if allowed_model_input_levers and plan_levers and not set(allowed_model_input_levers).intersection(plan_levers):
    issues.append("lever_adjustment_plan_has_no_meaningful_non_hold_allowed_overlap")

  severity = str(selection.get("severity_class") or "").strip().lower()
  minimum_strength = str(selection.get("minimum_package_strength") or "").strip().lower()
  directives = selection.get("controller_directives") if isinstance(selection.get("controller_directives"), dict) else {}
  try:
    directive_meaningful = int(float(directives.get("minimum_meaningful_levers") or 0))
  except Exception:
    directive_meaningful = 0
  try:
    directive_package_count = int(float(directives.get("minimum_package_count") or 0))
  except Exception:
    directive_package_count = 0
  effective_meaningful_levers = max(directive_meaningful, len(plan_levers))
  effective_package_count = max(directive_package_count, len(governed_period_groups))
  if severity == "severe":
    if minimum_strength != "strong":
      issues.append("severe_blueprint_requires_minimum_package_strength_strong")
    if effective_meaningful_levers < 4:
      issues.append(
        f"severe_blueprint_requires_minimum_meaningful_levers_at_least_4::current={effective_meaningful_levers}"
      )
    if effective_package_count < 2:
      issues.append(
        f"severe_blueprint_requires_minimum_package_count_at_least_2::current={effective_package_count}"
      )
    if not directives.get("escalate_on_retry"):
      issues.append("severe_blueprint_requires_escalate_on_retry_true")
    if str(directives.get("aggression_level") or "").strip().lower() != "high":
      issues.append("severe_blueprint_requires_aggression_level_high")
  return issues


def _normalize_strategy_selection_contract(
  *,
  selection: Dict[str, Any],
  strategy_catalog: List[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
) -> Dict[str, Any]:
  if not isinstance(selection, dict):
    return {}
  allowed_by_strategy = _catalog_allowed_levers(strategy_catalog)
  valid_strategy_ids = list(allowed_by_strategy.keys())
  selected_strategy_ids = [
    str(item or "").strip()
    for item in (selection.get("selected_strategy_ids") or [])
    if str(item or "").strip() in allowed_by_strategy
  ][:2]
  allowed_from_selection = sorted({
    lever_id
    for strategy_id in selected_strategy_ids
    for lever_id in allowed_by_strategy.get(strategy_id, [])
  })
  valid_levers = set(allowed_from_selection)
  normalized = dict(selection)
  normalized["selected_strategy_ids"] = selected_strategy_ids
  requested_allowed = [
    str(item or "").strip()
    for item in (selection.get("allowed_model_input_levers") or [])
    if str(item or "").strip() in valid_levers
  ]
  normalized["allowed_model_input_levers"] = requested_allowed or allowed_from_selection
  allowed_set = set(normalized["allowed_model_input_levers"])
  normalized["forbidden_model_input_levers"] = [
    str(item or "").strip()
    for item in (selection.get("forbidden_model_input_levers") or [])
    if str(item or "").strip() in valid_levers and str(item or "").strip() not in allowed_set
  ]
  severity = str(selection.get("severity_class") or "").strip().lower()
  normalized_plan: List[Dict[str, Any]] = []
  for raw_item in (selection.get("lever_adjustment_plan") or []):
    if not isinstance(raw_item, dict):
      continue
    lever_id = str(raw_item.get("lever_id") or "").strip()
    if lever_id not in allowed_set:
      continue
    start_int, end_int = _normalize_quarter_span(raw_item)
    normalized_plan.append(
      {
        **raw_item,
        "lever_id": lever_id,
        "quarter_start": start_int,
        "quarter_end": end_int,
      }
    )
  normalized["lever_adjustment_plan"] = normalized_plan
  normalized_groups = _fixed_governed_period_groups()
  normalized["governed_period_groups"] = normalized_groups
  valid_line_items = set(_valid_finmo_line_items(fixed_facts))
  raw_normalized_targets: List[Dict[str, Any]] = []
  for raw_target in (selection.get("controlled_output_targets") or []):
    if not isinstance(raw_target, dict):
      continue
    line_item = str(raw_target.get("line_item") or "").strip()
    if line_item not in valid_line_items:
      continue
    start_int, end_int = _normalize_quarter_span(raw_target)
    raw_normalized_targets.append(
      {
        **raw_target,
        "line_item": line_item,
        "quarter_start": start_int,
        "quarter_end": end_int,
      }
    )
  target_posture = selection.get("target_posture") if isinstance(selection.get("target_posture"), dict) else {}
  derived_ebitda_targets = _derive_app_owned_ebitda_targets(
    lever_plan=normalized_plan,
    target_posture=target_posture,
    fixed_facts=fixed_facts or {},
  )
  derived_revenue_targets = _derive_app_owned_revenue_targets(
    lever_plan=normalized_plan,
    target_posture=target_posture,
    fixed_facts=fixed_facts or {},
  )
  normalized_targets = [
    item for item in raw_normalized_targets
    if str(item.get("line_item") or "").strip().lower() not in {"ebitda", "revenue"}
  ]
  if derived_ebitda_targets:
    normalized_targets.extend(derived_ebitda_targets)
  else:
    normalized_targets.extend(
      item for item in raw_normalized_targets
      if str(item.get("line_item") or "").strip().lower() == "ebitda"
    )
  if derived_revenue_targets:
    normalized_targets.extend(derived_revenue_targets)
  else:
    normalized_targets.extend(
      item for item in raw_normalized_targets
      if str(item.get("line_item") or "").strip().lower() == "revenue"
    )
  normalized["controlled_output_targets"] = normalized_targets
  directives = selection.get("controller_directives") if isinstance(selection.get("controller_directives"), dict) else {}
  app_owned_directives = _default_controller_directives(severity=severity)
  normalized["controller_directives"] = {
    **app_owned_directives,
    **{
      key: directives.get(key)
      for key in ("require_multi_lever_coordination", "preserve_capacity_staffing_link", "preserve_price_demand_link", "preserve_marketing_demand_link", "prefer_delay_over_delete")
      if directives.get(key) is not None
    },
  }
  normalized["coverage_issues"] = _selection_coverage_issues(
    selection=selection,
    lever_plan=normalized_plan,
    governed_period_groups=normalized_groups,
    controlled_output_targets=normalized_targets,
  )
  normalized["coverage_issues"].extend(
    _revenue_target_feasibility_issues(
      lever_plan=normalized_plan,
      controlled_output_targets=normalized_targets,
      fixed_facts=fixed_facts or {},
    )
  )
  normalized["coverage_issues"].extend(
    _ebitda_target_feasibility_issues(
      lever_plan=normalized_plan,
      controlled_output_targets=normalized_targets,
      fixed_facts=fixed_facts or {},
    )
  )
  normalized["coverage_issues"].extend(
    _ebitda_viability_floor_issues(
      controlled_output_targets=normalized_targets,
    )
  )
  normalized["coverage_issues"].extend(
    _package_escalation_issues(
      lever_plan=normalized_plan,
      coverage_issues=normalized["coverage_issues"],
    )
  )
  normalized["coverage_issues"].extend(_blueprint_contract_issues(normalized))
  normalized["coverage_issues"] = sorted({
    str(item or "").strip()
    for item in (normalized.get("coverage_issues") or [])
    if str(item or "").strip()
  })
  normalized["active_levers"] = [
    str(item or "").strip()
    for item in (selection.get("active_levers") or [])
    if str(item or "").strip() in allowed_set
  ]
  normalized["valid_strategy_ids"] = valid_strategy_ids
  return _sanitize_canonical_live_payload(normalized)


def _quarter_plan_schema(*, fields: Dict[str, Any], required_fields: List[str]) -> Dict[str, Any]:
  return {
    "type": "array",
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        **fields,
      },
      "required": ["quarter_start", "quarter_end"] + required_fields,
    },
  }


def _hiring_release_plan_schema() -> Dict[str, Any]:
  return {
    "type": "array",
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "role_scope": {"type": "string"},
        "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "months_until_activate": {"type": ["number", "null"]},
        "staffing_posture": {"type": ["string", "null"]},
        "capacity_effect": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
      },
      "required": [
        "role_scope",
        "quarter_start",
        "quarter_end",
        "months_until_activate",
        "staffing_posture",
        "capacity_effect",
        "rationale",
      ],
    },
  }


def _milestone_activation_plan_schema() -> Dict[str, Any]:
  return {
    "type": "array",
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "description": {"type": "string"},
        "target_quarter": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "activation_condition": {"type": ["string", "null"]},
        "capacity_multiplier": {"type": ["number", "null"]},
        "growth_multiplier": {"type": ["number", "null"]},
        "rationale": {"type": "string"},
      },
      "required": [
        "description",
        "target_quarter",
        "activation_condition",
        "capacity_multiplier",
        "growth_multiplier",
        "rationale",
      ],
    },
  }


def _schema() -> Dict[str, Any]:
  return {
    "name": "consistency_strategy_selection",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "primary_cause": {
          "type": "string",
          "enum": ["payroll-driven", "pricing-driven", "utilization-driven", "mixed"],
        },
        "secondary_causes": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 4,
        },
        "reason": {"type": "string"},
        "business_model_assessment": {"type": "string"},
        "severity_class": {
          "type": "string",
          "enum": ["mild", "moderate", "severe"],
        },
        "severity_reason": {"type": "string"},
        "minimum_package_strength": {
          "type": "string",
          "enum": ["light", "moderate", "strong"],
        },
        "viability_blueprint_summary": {"type": "string"},
        "scaling_model_summary": {"type": "string"},
        "allowed_model_input_levers": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 48,
        },
        "forbidden_model_input_levers": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 24,
        },
        "lever_adjustment_plan": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lever_id": {"type": "string"},
              "direction": {"type": ["string", "null"], "enum": ["up", "down", "hold", None]},
              "intensity": {"type": ["string", "null"], "enum": ["light", "moderate", "strong", None]},
              "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "min_value": {"type": ["number", "null"]},
              "max_value": {"type": ["number", "null"]},
              "rationale": {"type": "string"},
            },
            "required": [
              "lever_id",
              "direction",
              "intensity",
              "quarter_start",
              "quarter_end",
              "min_value",
              "max_value",
              "rationale",
            ],
          },
          "maxItems": 64,
        },
        "controlled_output_targets": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "line_item": {"type": "string"},
              "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "min_value": {"type": ["number", "null"]},
              "max_value": {"type": ["number", "null"]},
              "rationale": {"type": "string"},
            },
            "required": ["line_item", "quarter_start", "quarter_end", "min_value", "max_value", "rationale"],
          },
          "maxItems": 20,
        },
        "target_posture": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "year1_ebitda_posture": {"type": ["string", "null"]},
            "year2_ebitda_posture": {"type": ["string", "null"]},
            "year3_ebitda_posture": {"type": ["string", "null"]},
            "staffing_posture": {"type": ["string", "null"]},
            "pricing_posture": {"type": ["string", "null"]},
            "demand_posture": {"type": ["string", "null"]},
            "cost_posture": {"type": ["string", "null"]},
          },
          "required": [
            "year1_ebitda_posture",
            "year2_ebitda_posture",
            "year3_ebitda_posture",
            "staffing_posture",
            "pricing_posture",
            "demand_posture",
            "cost_posture",
          ],
        },
        "capacity_release_plan": _quarter_plan_schema(
          fields={
            "capacity_posture": {"type": ["string", "null"]},
            "capacity_release_multiplier": {"type": ["number", "null"]},
            "trigger": {"type": ["string", "null"]},
            "rationale": {"type": "string"},
          },
          required_fields=["capacity_posture", "capacity_release_multiplier", "trigger", "rationale"],
        ),
        "hiring_release_plan": _hiring_release_plan_schema(),
        "demand_build_plan": _quarter_plan_schema(
          fields={
            "demand_posture": {"type": ["string", "null"]},
            "marketing_ratio_bias": {"type": ["number", "null"]},
            "growth_multiplier": {"type": ["number", "null"]},
            "rationale": {"type": "string"},
          },
          required_fields=["demand_posture", "marketing_ratio_bias", "growth_multiplier", "rationale"],
        ),
        "milestone_activation_plan": _milestone_activation_plan_schema(),
        "support_overhead_plan": _quarter_plan_schema(
          fields={
            "cost_posture": {"type": ["string", "null"]},
            "opex_ratio_bias": {"type": ["number", "null"]},
            "payroll_ratio_bias": {"type": ["number", "null"]},
            "rationale": {"type": "string"},
          },
          required_fields=["cost_posture", "opex_ratio_bias", "payroll_ratio_bias", "rationale"],
        ),
        "outer_year_margin_logic": {"type": "string"},
        "selected_strategy_ids": {
          "type": "array",
          "items": {"type": "string"},
          "minItems": 1,
          "maxItems": 2,
        },
      },
      "required": [
        "primary_cause",
        "secondary_causes",
        "reason",
        "business_model_assessment",
        "severity_class",
        "severity_reason",
        "minimum_package_strength",
        "viability_blueprint_summary",
        "scaling_model_summary",
        "allowed_model_input_levers",
        "forbidden_model_input_levers",
        "lever_adjustment_plan",
        "controlled_output_targets",
        "target_posture",
        "capacity_release_plan",
        "hiring_release_plan",
        "demand_build_plan",
        "milestone_activation_plan",
        "support_overhead_plan",
        "outer_year_margin_logic",
        "selected_strategy_ids",
      ],
    },
  }


def _validation_schema() -> Dict[str, Any]:
  return {
    "name": "consistency_finmo_validation",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "validation_status": {
          "type": "string",
          "enum": ["accepted", "accepted_with_notes", "rejected"],
        },
        "believable": {"type": "boolean"},
        "viable_path": {"type": "boolean"},
        "output_matches_intent": {"type": "boolean"},
        "issues": {
          "type": "array",
          "items": {"type": "string"},
        },
        "required_adjustments": {
          "type": "array",
          "items": {"type": "string"},
        },
        "notes": {"type": "string"},
      },
      "required": [
        "validation_status",
        "believable",
        "viable_path",
        "output_matches_intent",
        "issues",
        "required_adjustments",
        "notes",
      ],
    },
  }


def _strategy_system_prompts() -> List[str]:
  return [
    (
      "You are the governor for a business-plan realism and repair engine.\n"
      "\n"
      "Mission:\n"
      "Build a believable viable business over 20 quarters, not a cosmetic improvement and not a fake spreadsheet win.\n"
      "Choose the best 1 or 2 strategy ids from the provided bounded strategy catalog.\n"
      "Do not invent new strategy ids.\n"
      "\n"
      "Thinking Standard:\n"
      "Reason like a serious operator and investor reviewing a flawed plan.\n"
      "Use the full business picture: persisted intake facts, consultant outputs, baseline_summary, model_input_view, finmo_view, retry_context, and your own real-world knowledge of how this business type should actually operate.\n"
      "diagnosis contains the upstream toolset selector. Treat diagnosis.preferred_strategy_ids as the default toolset shortlist and diagnosis.toolset_selector_reason as the reason those toolsets were prioritized.\n"
      "The persisted SQL state is the client's stated plan and starting point, not the truth. Challenge unrealistic pricing, compensation, staffing, utilization, growth, margin, and timing assumptions when they are not believable.\n"
      "If the baseline is implausibly weak, stabilize it. If it is implausibly strong, normalize it. Do not simply preserve client optimism.\n"
      "Avoid long negative paths. A repaired business may still have early pressure, but multi-year flat or worsening losses are usually unacceptable unless the business facts truly force that outcome.\n"
      "If the business is structurally unprofitable, unrealistic, or failing to converge toward a believable steady state, you must prescribe a coordinated multi-lever restructuring that creates a plausible path to viability.\n"
      "In those cases, do not return incremental, cosmetic, timid, or overly conservative adjustments that leave the business failing.\n"
      "For severe cases, do not settle into a stable negative-EBITDA story while a broader preferred toolset remains available in diagnosis.preferred_strategy_ids.\n"
      "If a capacity-enabled or growth-supporting preferred strategy is available, you should use it unless the business facts make it clearly incompatible.\n"
      "A valid repair must materially change the operating structure when needed, coordinate multiple levers across revenue, staffing, utilization, and cost, and produce a believable path toward breakeven or acceptable margins within a reasonable timeframe for the business type and stage.\n"
      "\n"
      "Shared Language Contract:\n"
      "You may only prescribe controllable levers using exact Model Inputs workbook lever ids from strategy_catalog.allowed_model_input_levers.\n"
      "Use strategy_catalog.allowed_model_input_lever_details to understand what each workbook lever means, whether it is a ratio or direct input, which full quarters it may control, and whether it belongs to revenue, expenses, balance sheet, or schedules.\n"
      "Do not invent lever names, abstractions, synonyms, or old solver-family vocabulary.\n"
      "When prescribing a lever, speak in the exact workbook language shown in model_input_view. Controller is not allowed to infer synonyms later.\n"
      "forbidden_model_input_levers are workbook levers that should stay mostly untouched for this case.\n"
      "\n"
      "Revenue Reasoning:\n"
      "Read the revenue section carefully. Revenue levers are scoped by line of business and product, not just by generic driver name.\n"
      "Reason explicitly about LOB, product, capacity, unit price, and utilization together.\n"
      "Do not change revenue drivers in a way that breaks business logic. Price, utilization, capacity, demand pacing, and staffing support must still fit together.\n"
      "If child products exist, preserve child-first reasoning. Parent behavior should emerge from children rather than replacing them.\n"
      "Lever impact contract: Unit Price and Utilization change revenue only within the currently available capacity. Material revenue expansion requires an explicit Capacity lever or another true volume lever. Cost levers like COGS, Payroll, Marketing, and G&A do not themselves increase revenue.\n"
      "Do not prescribe revenue targets above what the active revenue levers can physically produce over the governed quarter.\n"
      "\n"
      "Cost and Compensation Reasoning:\n"
      "Treat payroll, founder pay, leadership compensation, planned hires, marketing, COGS, G&A, lease, interest, depreciation, and taxes as business design choices, not sacred inputs.\n"
      "If compensation is economically unrealistic, you may cut it, defer it, or phase it back in later.\n"
      "If inferred or planned roles are not supportable, delay them, reduce them, or reshape the operating model so the staffing plan becomes believable.\n"
      "If you defer staffing or compensation, the rest of the business must stay coherent: capacity, utilization, growth pacing, support overhead, and demand build must still make sense.\n"
      "\n"
      "Time Horizon and Grouping:\n"
      "You are governing Quarter 1 through Quarter 20.\n"
      "The application owns the fixed five governed phase groups across the horizon: Q1-Q4, Q5-Q8, Q9-Q12, Q13-Q16, and Q17-Q20.\n"
      "Do not spend effort inventing alternative groupings. The application will apply the fixed period structure.\n"
      "Use exact timing inside your lever_adjustment_plan and controlled_output_targets against that fixed five-block horizon.\n"
      "You must decide when changes start, when they stop, when capacity expands, when roles release, when demand builds, when milestones activate, and when support overhead steps up because scale is real.\n"
      "\n"
      "Bands and Targets:\n"
      "Use exact timing but mostly bounded ranges for controllable inputs. Do not pin exact values unless something truly must be fixed.\n"
      "Controller needs room to solve numerically inside your bands. If you pin everything exactly, Solver becomes ineffective and feasibility collapses.\n"
      "For every lever you activate in lever_adjustment_plan, you must provide explicit numeric phase coverage through Quarter 20 with no uncovered gaps. If a lever should stabilize, hold, or revert later, you must still express that later phase explicitly rather than stopping early.\n"
      "controlled_output_targets should usually be bands by quarter group or year phase, not brittle point targets.\n"
      "The application derives EBITDA and Revenue target bands from your target_posture and lever package. Do not spend effort hand-authoring EBITDA or Revenue bands.\n"
      "Use controlled_output_targets only for additional non-EBITDA, non-Revenue outputs when they are genuinely important to the business logic, such as cash constraints.\n"
      "Any controlled_output_targets you do provide must use Financial Model QTR dollar values for the specified quarter. Do not use margins, percentages, ratios, or annualized values.\n"
      "Use Financial Model QTR line items like Revenue, EBITDA, Gross Profit, Net Income, Cash, Total Assets, or Total Liabilities & Equity.\n"
      "\n"
      "Controller Handoff:\n"
      "Controller is an execution layer, not a co-strategist.\n"
      "Your output must be specific enough that controller only has to translate your workbook lever plan into Excel Solver changing-cell instructions and stay within your bands.\n"
      "Do not rely on hidden controller heuristics or global envelope overrides. You are the source of business logic, timing, and bounds.\n"
      "The application owns baseline controller directives/posture for all cases. Focus your judgment on lever selection, lever bands, output targets, and release/build logic.\n"
      "\n"
      "Required Output Content:\n"
      "Return a full viability blueprint, not just strategy ids.\n"
      "You must explain the business_model_assessment, secondary_causes, allowed_model_input_levers, forbidden_model_input_levers, lever_adjustment_plan, controlled_output_targets, target_posture, viability_blueprint_summary, scaling_model_summary, capacity_release_plan, hiring_release_plan, demand_build_plan, milestone_activation_plan, support_overhead_plan, and outer_year_margin_logic.\n"
      "Do not rely on controller to invent business logic later. Business logic must be fully expressed through lever_adjustment_plan, target_posture, any additional controlled_output_targets for non-EBITDA/non-Revenue outputs, and the release/build plans.\n"
      "A blueprint with uncovered lever periods or uncovered target periods is invalid.\n"
      "Application-owned minimum saleability floor: the application will derive EBITDA targets and will not accept a Year 2+ path below breakeven.\n"
      "\n"
      "Severity and Retry:\n"
      "Classify case severity as mild, moderate, or severe and explain why in severity_reason.\n"
      "Set minimum_package_strength to light, moderate, or strong.\n"
      "The application owns controller posture for all cases. You do not need to emit controller_directives or governed_period_groups.\n"
      "If the workbook view shows a structurally broken case, you must return a severe blueprint with a strong multi-lever repair package and materially different lever bands or target posture than a weak baseline plan.\n"
      "When severity_class is moderate or severe, you must use at least one revenue-side lever, at least one cost-side or staffing lever, include both early-phase and outer-year changes, and produce a non-flat trajectory.\n"
      "Do not return single-lever or weak adjustments in moderate or severe cases unless the business facts make that the only believable path.\n"
      "For severe cases, do not return a polite or modest plan. Return a strong but realistic multi-lever restructuring path.\n"
      "For severe cases, lever_adjustment_plan must cover at least four meaningful workbook levers, include at least one revenue-side lever and at least one cost-side lever, and include both an early-phase action and an outer-year action.\n"
      "When a business is structurally broken, you are expected to make decisive but believable moves, not small adjustments that preserve failure.\n"
      "Use retry_context carefully. On retry, do not just rename the same weak strategy. Change the lever package, bounds, timing, or target path enough to materially improve solvability.\n"
      "If retry_context.escalation_required is true, the prior attempts still produced all-negative degrading five-year paths. In that case, do not repeat the same strategy story. Materially strengthen the operating plan, growth architecture, and target posture.\n"
      "\n"
      "Believability Rules:\n"
      "Business type and business stage matter materially when deciding what is realistic.\n"
      "If a business is badly broken, do not rely on a single lever unless a single-lever repair is truly believable.\n"
      "Choose strategies that keep the business believable, preserve the original plan where possible, and avoid nonsense even when Solver could technically force the numbers.\n"
      "Return JSON only."
    ),
    (
      "You are rescuing a failed strategy-selection attempt for a business-plan realism and repair engine.\n"
      "The previous strategy choice did not produce a viable repair, or selection output was missing.\n"
      "You must still choose 1 or 2 strategy ids from the provided catalog.\n"
      "Do not return an empty selection.\n"
      "Use retry_context to avoid repeating the same failed strategy story.\n"
      "If retry_context.coverage_issues is present, you must explicitly repair those numeric gaps.\n"
      "Do not return another blueprint with uncovered lever periods, missing controlled_output_targets, or output-target coverage gaps anywhere inside Q1-Q20.\n"
      "A response that still has coverage_issues is invalid.\n"
      "Pick a different, still-believable operating approach if the previous one missed.\n"
      "Return JSON only."
    ),
    (
      "You must return a valid strategy selection now.\n"
      "Select the best 1 or 2 strategy ids from the catalog and provide conservative overrides.\n"
      "Do not leave selected_strategy_ids empty.\n"
      "The application will apply the fixed five governed period groups: Q1-Q4, Q5-Q8, Q9-Q12, Q13-Q16, and Q17-Q20.\n"
      "Every active lever must have explicit phase coverage through Q20, and controlled_output_targets must provide explicit numeric coverage for all governed quarters through Q20.\n"
      "Do not return another blueprint with coverage gaps.\n"
      "Prefer believable repair over perfect optimization.\n"
      "Return JSON only."
    ),
  ]


def advise_consistency_strategy_selection(
  *,
  baseline_summary: Dict[str, Any],
  fixed_facts: Dict[str, Any],
  viability_mode: bool,
  diagnosis: Dict[str, Any],
  strategy_catalog: List[Dict[str, Any]],
  retry_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  if not _strategy_layer_enabled():
    return {}
  try:
    api_key = _require_openai_key()
  except Exception:
    return {}

  catalog_payload = []
  for item in strategy_catalog:
    if not isinstance(item, dict):
      continue
    catalog_payload.append(
      {
        "strategy_id": str(item.get("strategy_id") or "").strip(),
        "strategy_name": str(item.get("strategy_name") or "").strip(),
        "archetype": str(item.get("archetype") or "").strip(),
        "allowed_model_input_levers": list(item.get("allowed_model_input_levers") or []),
        "allowed_model_input_lever_details": _sanitize_canonical_live_payload(item.get("allowed_model_input_lever_details") or []),
        "dominant_tradeoff": str(item.get("dominant_tradeoff") or "").strip(),
      }
    )
  if not catalog_payload:
    return {}

  schema = _schema()
  base_user_payload = {
    "baseline_summary": _sanitize_canonical_live_payload(baseline_summary or {}),
    "fixed_facts": _sanitize_canonical_live_payload(fixed_facts or {}),
    "diagnosis": _sanitize_canonical_live_payload(diagnosis or {}),
    "model_input_view": _sanitize_canonical_live_payload((fixed_facts or {}).get("model_input_json") or {}),
    "finmo_view": _sanitize_canonical_live_payload((fixed_facts or {}).get("finmo_json") or {}),
    "viability_mode": bool(viability_mode),
    "strategy_catalog": catalog_payload,
  }
  if isinstance(retry_context, dict) and retry_context:
    base_user_payload["retry_context"] = _sanitize_canonical_live_payload(retry_context)

  system_prompts = _strategy_system_prompts()

  last_error: Optional[str] = None
  last_invalid_selection: Dict[str, Any] = {}
  last_invalid_coverage_issues: List[str] = []
  last_attempt_index: int = 0
  for attempt_index, system_prompt in enumerate(system_prompts, start=1):
    last_attempt_index = attempt_index
    payload = {
      "model": _openai_model(),
      "input": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(base_user_payload, ensure_ascii=False)},
      ],
      "text": {
        "format": {
          "type": "json_schema",
          "name": schema["name"],
          "schema": schema["schema"],
          "strict": True,
        }
      },
    }
    url = "https://api.openai.com/v1/responses"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
      resp = _post_openai(
        url=url,
        headers=headers,
        payload=payload,
        timeout_seconds=_openai_timeout_seconds("strategy"),
        max_attempts=2,
      )
      if resp.status_code >= 400:
        last_error = _format_openai_error(resp)
        continue
      parsed = _parse_json_response(resp.json())
    except Exception as exc:
      last_error = str(exc)
      continue
    if not isinstance(parsed, dict):
      last_error = "non_dict_response"
      continue
    parsed = _normalize_strategy_selection_contract(
      selection=parsed,
      strategy_catalog=strategy_catalog,
      fixed_facts=fixed_facts or {},
    )
    selected_ids = parsed.get("selected_strategy_ids")
    coverage_issues = list(parsed.get("coverage_issues") or []) if isinstance(parsed.get("coverage_issues"), list) else []
    if isinstance(selected_ids, list) and any(str(item or "").strip() for item in selected_ids):
      if not coverage_issues:
        parsed["advisor_attempt_count"] = attempt_index
        return parsed
      last_invalid_selection = _sanitize_canonical_live_payload(parsed)
      last_invalid_coverage_issues = [str(item or "").strip() for item in coverage_issues if str(item or "").strip()]
      base_user_payload["retry_context"] = _merge_retry_context(
        retry_context if isinstance(base_user_payload.get("retry_context"), dict) else retry_context,
        coverage_issues=coverage_issues,
        prior_selection=parsed,
        invalid_reason="strategy_blueprint_coverage_gaps",
        attempt_index=attempt_index,
      )
      last_error = "strategy_blueprint_coverage_gaps"
      continue
    last_error = "missing_selected_strategy_ids"
  return {
    "error": "strategy_advisor_no_selection",
    "error_detail": str(last_error or "unknown"),
    "advisor_attempt_count": int(last_attempt_index or 0),
    "last_invalid_selection": last_invalid_selection,
    "coverage_issues": last_invalid_coverage_issues,
  }


def validate_consistency_finmo_result(
  *,
  validation_request: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  fixed_facts: Optional[Dict[str, Any]] = None,
  strategy_selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  if not _strategy_layer_enabled():
    return {}
  try:
    api_key = _require_openai_key()
  except Exception:
    return {}

  payload = {
    "validation_request": _sanitize_canonical_live_payload(validation_request or {}),
    "model_input_view": _sanitize_canonical_live_payload(model_input_json or {}),
    "finmo_view": _sanitize_canonical_live_payload(finmo_json or {}),
    "fixed_facts": _sanitize_canonical_live_payload(fixed_facts or {}),
    "strategy_selection": _sanitize_canonical_live_payload(strategy_selection or {}),
  }
  schema = _validation_schema()
  request_payload = {
    "model": _openai_model(),
    "input": [
      {
        "role": "system",
        "content": (
          "You are validating a persisted Finmo result for a business-plan realism and repair engine.\n"
          "Your job is to judge whether the latest persisted Model Inputs and Financial Model QTR outputs match the intended governed business path and are believable.\n"
          "Use the full business picture: fixed_facts, strategy_selection, validation_request, model_input_view, finmo_view, and your own real-world knowledge of how this business type should actually operate.\n"
          "Do not invent new levers or redesign the business from scratch. Validate the result that was actually produced.\n"
          "A passing result must be believable, materially aligned with the requested timing and output intent, and plausibly converge toward a viable operating state.\n"
          "Reject results that are still structurally weak, unrealistic, flatly failing, or materially inconsistent with the intended lever timing and business logic.\n"
          "Do not accept a result just because the spreadsheet improves. It must be believable and viable enough for the business type and stage.\n"
          "Return JSON only."
        ),
      },
      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema["name"],
        "schema": schema["schema"],
        "strict": True,
      }
    },
  }
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  try:
    resp = _post_openai(
      url=url,
      headers=headers,
      payload=request_payload,
      timeout_seconds=_openai_timeout_seconds("validation"),
      max_attempts=1,
    )
    if resp.status_code >= 400:
      return {"error": _format_openai_error(resp)}
    parsed = _parse_json_response(resp.json())
  except Exception as exc:
    return {"error": str(exc)}
  return parsed if isinstance(parsed, dict) else {}
