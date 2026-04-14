import copy
import json
import math
import os
import re
import time
import calendar
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify

logger = logging.getLogger(__name__)
import requests
from intake_consult_draft import append_messages, get_draft
try:
  from shared_context import build_shared_context  # type: ignore
except Exception:
  try:
    from api_handlers.shared_context import build_shared_context  # type: ignore
  except Exception:
    build_shared_context = None  # type: ignore
try:
  from fact_templates import sanitize_fact_template  # type: ignore
except Exception:
  try:
    from client_intake_and_finmo.fact_templates import sanitize_fact_template  # type: ignore
  except Exception:
    def sanitize_fact_template(value: str) -> str:
      return str(value or "")
try:
  from realism_memo import generate_realism_memo_payload_safe  # type: ignore
except Exception:
  try:
    from client_intake_and_finmo.realism_memo import generate_realism_memo_payload_safe  # type: ignore
  except Exception:
    def generate_realism_memo_payload_safe(
      *,
      ops_json: Dict[str, Any],
      financials_json: Dict[str, Any],
      solved_model_input_json: Optional[Dict[str, Any]] = None,
      solved_finmo_json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
      del solved_model_input_json, solved_finmo_json
      return {
        "status": "failed",
        "issues": [],
      }

OPS_CONFIRM_QUESTION = "Does this look right before we move on to Target Market?"
OPS_MILESTONE_QUESTION = (
  "Looking ahead, what is one concrete goal you want to hit in about the next 12 months "
  "(for example: a target number of weekly units/orders, a customer count, or a rough monthly revenue level)?"
)
MARKET_CONFIRM_QUESTION = "Does this look right before we move on to Human Resources?"
PEOPLE_CONFIRM_QUESTION = "Does this look right before we move on to Financials?"
COMPETITIVE_ADVANTAGE_PREFIX = "Proposed competitive advantage:"
COMPETITIVE_ADVANTAGE_QUESTION = "Does this accurately reflect what truly sets the business apart?"
_RETRYABLE_STATUS = {429, 502, 503, 504}
_CASH_STRATEGY_REVIEW_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "client_intake_and_finmo" / "prompts" / "cash_strategy_review"
_CASH_STRATEGY_REVIEW_PROMPT_PATH = _CASH_STRATEGY_REVIEW_PROMPTS_DIR / "reviewer.md"
_REALISM_RESOLUTION_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "client_intake_and_finmo" / "prompts" / "realism_resolution"
_REALISM_RESOLUTION_PROMPT_PATH = _REALISM_RESOLUTION_PROMPTS_DIR / "reviewer.md"
_REALISM_MAX_ITERATIONS = 3


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


def _parse_pending_bool(raw: Any) -> bool:
  # Treat any non-null-ish, truthy value as pending.
  if raw is None:
    return False
  if raw is False:
    return False
  if raw == 0:
    return False
  if isinstance(raw, str):
    val = raw.strip().lower()
    if not val or val in ("0", "false", "null", "none", "[]", "{}"):
      return False
    return True
  if isinstance(raw, (list, dict)):
    return bool(raw)
  return bool(raw)


def _is_missing_number_value(value: Any) -> bool:
  if value is None:
    return True
  if isinstance(value, bool):
    return True
  try:
    return float(value) <= 0
  except Exception:
    return True


def _normalize_ops_capacity_compat(ops_obj: Any) -> Any:
  """
  Capacity compatibility: keep ops capacity coherent without re-asking the user.

  Rules (minimal, non-destructive):
  - If unit_cadence is weekly and week capacity is set, fill missing period capacity from it.
  - If unit_cadence is monthly/contract and period capacity is set, fill missing week capacity from it.
  - If unit_cadence is weekly/monthly and operating_periods_per_year is missing, fill it with 52/12.
  - Never overwrite an existing non-missing capacity number.
  - For multi-product ops (lob_models with >1 product), only normalize per-product fields;
    keep top-level unit fields null by design.
  """
  if not isinstance(ops_obj, dict):
    return ops_obj

  def _normalize_unit_dict(d: Dict[str, Any]) -> None:
    cadence = str(d.get("unit_cadence") or "").strip().lower()
    week = d.get("units_per_week_capacity")
    period = d.get("units_per_period_capacity")
    periods_per_year = d.get("operating_periods_per_year")

    if cadence == "weekly":
      if _is_missing_number_value(period) and not _is_missing_number_value(week):
        d["units_per_period_capacity"] = week
      if _is_missing_number_value(periods_per_year):
        d["operating_periods_per_year"] = 52
      return

    if cadence in ("monthly", "contract"):
      if _is_missing_number_value(week) and not _is_missing_number_value(period):
        d["units_per_week_capacity"] = period
      elif _is_missing_number_value(period) and not _is_missing_number_value(week):
        d["units_per_period_capacity"] = week
      if cadence == "monthly" and _is_missing_number_value(periods_per_year):
        d["operating_periods_per_year"] = 12
      return

    # Unknown cadence: best-effort fill the missing side only.
    if _is_missing_number_value(week) and not _is_missing_number_value(period):
      d["units_per_week_capacity"] = period
    elif _is_missing_number_value(period) and not _is_missing_number_value(week):
      d["units_per_period_capacity"] = week

  lob_models = ops_obj.get("lob_models")
  product_count = 0
  if isinstance(lob_models, list):
    for lob in lob_models:
      if not isinstance(lob, dict):
        continue
      prods = lob.get("products")
      if not isinstance(prods, list):
        continue
      for p in prods:
        if isinstance(p, dict):
          product_count += 1
          _normalize_unit_dict(p)

  # Only normalize top-level unit fields if this is not a multi-product model.
  if product_count <= 1:
    _normalize_unit_dict(ops_obj)

  return ops_obj


def _count_ops_products(ops_obj: Any) -> int:
  if not isinstance(ops_obj, dict):
    return 0
  total = 0
  lob_models = ops_obj.get("lob_models")
  if not isinstance(lob_models, list):
    return 0
  for lob in lob_models:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    total += sum(1 for product in products if isinstance(product, dict))
  return total


def _extract_single_compact_number(text: Any) -> Optional[float]:
  blob = str(text or "").strip()
  if not blob:
    return None
  tokens = re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*[kKmM]?", blob)
  values: List[float] = []
  for tok in tokens:
    cleaned = str(tok or "").strip().replace("$", "").replace(",", "")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$", cleaned)
    if not match:
      continue
    try:
      value = float(match.group(1))
    except Exception:
      continue
    suffix = str(match.group(2) or "").strip().lower()
    if suffix == "k":
      value *= 1000.0
    elif suffix == "m":
      value *= 1000000.0
    values.append(value)
  if len(values) != 1:
    return None
  value = float(values[0])
  return value if value > 0 else None


def _extract_single_compact_number_allow_zero(text: Any) -> Optional[float]:
  blob = str(text or "").strip()
  if not blob:
    return None
  tokens = re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*[kKmM]?", blob)
  values: List[float] = []
  for tok in tokens:
    cleaned = str(tok or "").strip().replace("$", "").replace(",", "")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$", cleaned)
    if not match:
      continue
    try:
      value = float(match.group(1))
    except Exception:
      continue
    suffix = str(match.group(2) or "").strip().lower()
    if suffix == "k":
      value *= 1000.0
    elif suffix == "m":
      value *= 1000000.0
    values.append(value)
  if not values:
    return None
  unique_values: List[float] = []
  for value in values:
    if not any(abs(value - existing) < 1e-9 for existing in unique_values):
      unique_values.append(value)
  if len(unique_values) != 1:
    return None
  value = float(unique_values[0])
  return value if value >= 0 else None


def _extract_compact_numbers(text: Any) -> List[float]:
  blob = str(text or "").strip()
  if not blob:
    return []
  tokens = re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*[kKmM]?", blob)
  values: List[float] = []
  for tok in tokens:
    cleaned = str(tok or "").strip().replace("$", "").replace(",", "")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$", cleaned)
    if not match:
      continue
    try:
      value = float(match.group(1))
    except Exception:
      continue
    suffix = str(match.group(2) or "").strip().lower()
    if suffix == "k":
      value *= 1000.0
    elif suffix == "m":
      value *= 1000000.0
    values.append(value)
  return values


def _looks_like_capacity_prompt(text: Any) -> bool:
  prompt = str(text or "").strip().lower()
  if not prompt:
    return False
  if "how many" not in prompt and "capacity" not in prompt:
    return False
  if "can you handle" in prompt and ("fully booked" in prompt or "busy month" in prompt or "busy week" in prompt):
    return True
  if "to make planning realistic" in prompt and ("fully busy" in prompt or "fully booked" in prompt):
    return True
  if "operationally stretched" in prompt or "over-crowded" in prompt:
    return True
  return False


def _capacity_field_for_cadence(cadence: Any) -> Tuple[str, str]:
  cadence_norm = str(cadence or "").strip().lower()
  if cadence_norm == "weekly":
    return "units_per_week_capacity", "week"
  if cadence_norm in {"monthly", "contract"}:
    return "units_per_period_capacity", "month"
  return "units_per_period_capacity", "period"


def _find_missing_capacity_target(
  snapshot_obj: Any,
  *,
  fallback_ops: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  if not isinstance(snapshot_obj, dict):
    return None
  fallback = fallback_ops if isinstance(fallback_ops, dict) else {}
  lob_models = snapshot_obj.get("lob_models")
  if isinstance(lob_models, list):
    for lob_index, lob in enumerate(lob_models):
      if not isinstance(lob, dict):
        continue
      products = lob.get("products")
      if not isinstance(products, list):
        continue
      for product_index, product in enumerate(products):
        if not isinstance(product, dict):
          continue
        if not _is_missing_number_value(product.get("units_per_period_capacity")) or not _is_missing_number_value(
          product.get("units_per_week_capacity")
        ):
          continue
        cadence = (
          product.get("unit_cadence")
          or snapshot_obj.get("unit_cadence")
          or fallback.get("unit_cadence")
        )
        field, period_label = _capacity_field_for_cadence(cadence)
        label = str(
          product.get("product_name")
          or product.get("unit_name")
          or snapshot_obj.get("unit_name")
          or fallback.get("unit_name")
          or "this offering"
        ).strip()
        return {
          "kind": "product",
          "lob_index": lob_index,
          "product_index": product_index,
          "field": field,
          "period_label": period_label,
          "label": label,
        }
  if _is_missing_number_value(snapshot_obj.get("units_per_period_capacity")) and _is_missing_number_value(
    snapshot_obj.get("units_per_week_capacity")
  ):
    cadence = snapshot_obj.get("unit_cadence") or fallback.get("unit_cadence")
    field, period_label = _capacity_field_for_cadence(cadence)
    label = str(snapshot_obj.get("unit_name") or fallback.get("unit_name") or "units").strip() or "units"
    return {
      "kind": "top_level",
      "field": field,
      "period_label": period_label,
      "label": label,
    }
  return None


def _build_capacity_target_question(target: Dict[str, Any]) -> str:
  period_label = str(target.get("period_label") or "period").strip() or "period"
  label = str(target.get("label") or "units").strip() or "units"
  if str(target.get("kind") or "").strip() == "product":
    return (
      f"To make planning realistic for {label}, in a fully busy {period_label}, "
      f"about how many {label} can you handle?"
    ).strip()
  return (
    f"To make planning realistic, in a fully busy {period_label}, "
    f"about how many {label} can you handle?"
  ).strip()


def _apply_capacity_target_value(snapshot_obj: Any, target: Dict[str, Any], value: float) -> Dict[str, Any]:
  next_snapshot = json.loads(json.dumps(snapshot_obj if isinstance(snapshot_obj, dict) else {}))
  field = str(target.get("field") or "").strip()
  if not field:
    return _normalize_ops_capacity_compat(next_snapshot)
  if str(target.get("kind") or "").strip() == "product":
    try:
      lob_index = int(target.get("lob_index"))
      product_index = int(target.get("product_index"))
      next_snapshot["lob_models"][lob_index]["products"][product_index][field] = float(value)
    except Exception:
      return _normalize_ops_capacity_compat(next_snapshot)
  else:
    next_snapshot[field] = float(value)
  return _normalize_ops_capacity_compat(next_snapshot)


def _apply_capacity_snapshot_to_ops_json(
  ops_json: Dict[str, Any],
  snapshot_obj: Dict[str, Any],
  target: Dict[str, Any],
) -> Dict[str, Any]:
  patch_obj: Dict[str, Any] = {}
  if isinstance(snapshot_obj.get("lob_models"), list):
    patch_obj["lob_models"] = snapshot_obj.get("lob_models")
  field = str(target.get("field") or "").strip()
  if field and field in snapshot_obj:
    patch_obj[field] = snapshot_obj.get(field)
  return _apply_model_ops_patch(dict(ops_json or {}), patch_obj)


def _infer_capacity_field_from_prompt(*, last_assistant: str, ops_json: Dict[str, Any]) -> Optional[str]:
  prompt = str(last_assistant or "").strip().lower()
  cadence = str((ops_json or {}).get("unit_cadence") or "").strip().lower()
  if "fully booked week" in prompt:
    return "units_per_week_capacity"
  if "fully booked month" in prompt or "fully booked period" in prompt:
    return "units_per_period_capacity"
  if cadence == "weekly":
    return "units_per_week_capacity"
  if cadence in {"monthly", "contract"}:
    return "units_per_period_capacity"
  return None


def _capacity_confirm_prompt_patch(
  *,
  last_assistant: str,
  user_message: str,
  ops_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  prompt = str(last_assistant or "").strip().lower()
  if "just to confirm your capacity:" not in prompt or "fully booked" not in prompt:
    return None
  if _count_ops_products(ops_json) > 1:
    return None
  value = _extract_single_compact_number(user_message)
  if value is None:
    return None
  field = _infer_capacity_field_from_prompt(last_assistant=last_assistant, ops_json=ops_json or {})
  if not field:
    return None
  return {field: float(value)}


def _apply_model_ops_patch(ops_json: Any, patch_obj: Any) -> Any:
  """
  Merge model-produced incremental Ops facts into the working Ops JSON.

  This mirrors the existing edit_patch persistence style, but stays scoped to Ops
  and ignores nulls so partial snapshots do not wipe prior answers.
  """
  if not isinstance(ops_json, dict) or not isinstance(patch_obj, dict):
    return ops_json

  allowed_keys = {
    "consumer_type",
    "business_type",
    "unit_name",
    "unit_description",
    "unit_cadence",
    "units_per_week_capacity",
    "units_per_period_capacity",
    "operating_periods_per_year",
    "utilization_rate",
    "unit_price",
    "shipping_method",
    "sales_modality",
    "geographic_scope",
    "geographic_coverage",
    "countries",
    "capacity_driver",
    "primary_growth_lever",
    "legal_entity",
    "lob_models",
  }
  for k, v in patch_obj.items():
    key = str(k or "").strip()
    if key not in allowed_keys or v is None:
      continue
    ops_json[key] = v

  # Keep single-product top-level convenience fields aligned with the product row.
  lob_models = ops_json.get("lob_models")
  if isinstance(lob_models, list) and len(lob_models) == 1:
    products = lob_models[0].get("products") if isinstance(lob_models[0], dict) else None
    if isinstance(products, list) and len(products) == 1 and isinstance(products[0], dict):
      product = products[0]

      def _maybe_copy_text(field: str) -> None:
        if not str(ops_json.get(field) or "").strip() and product.get(field) is not None:
          ops_json[field] = product.get(field)

      def _maybe_copy_number(field: str) -> None:
        if _is_missing_number_value(ops_json.get(field)) and product.get(field) is not None:
          ops_json[field] = product.get(field)

      _maybe_copy_text("unit_name")
      _maybe_copy_text("unit_description")
      _maybe_copy_text("unit_cadence")
      _maybe_copy_number("unit_price")
      _maybe_copy_number("units_per_week_capacity")
      _maybe_copy_number("units_per_period_capacity")
      _maybe_copy_number("operating_periods_per_year")
      _maybe_copy_number("utilization_rate")

  return _normalize_ops_capacity_compat(ops_json)


def _first_contract_product_missing_periods(obj: Any) -> Optional[Dict[str, Any]]:
  if not isinstance(obj, dict):
    return None
  lob_models = obj.get("lob_models")
  if isinstance(lob_models, list):
    for lob in lob_models:
      if not isinstance(lob, dict):
        continue
      products = lob.get("products")
      if not isinstance(products, list):
        continue
      for product in products:
        if not isinstance(product, dict):
          continue
        if str(product.get("unit_cadence") or "").strip().lower() != "contract":
          continue
        if _is_missing_number_value(product.get("operating_periods_per_year")):
          return product
    return None
  if str(obj.get("unit_cadence") or "").strip().lower() != "contract":
    return None
  if _is_missing_number_value(obj.get("operating_periods_per_year")):
    return obj
  return None


def _last_assistant_message(messages: List[Dict[str, str]]) -> str:
  for msg in reversed(messages or []):
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    text = str(msg.get("content") or "").strip()
    if text:
      return text
  return ""


def _sync_pending_revenue_adjustment_state(
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  revenue_adjudication: Any,
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  try:
    from financials_year1 import build_revenue_driver_signature as _build_signature  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_year1 import (  # type: ignore
      build_revenue_driver_signature as _build_signature,
    )
  current_signature = str(_build_signature(financials_year1_json or {}) or "").strip()
  locked_signature = str(next_financials.get("_revenue_adjustment_locked_signature") or "").strip()

  if locked_signature and current_signature and locked_signature == current_signature:
    next_financials.pop("_pending_revenue_adjustment_signature", None)
    next_financials.pop("_pending_revenue_adjustment_options", None)
    return next_financials

  if not isinstance(revenue_adjudication, dict):
    next_financials.pop("_pending_revenue_adjustment_signature", None)
    next_financials.pop("_pending_revenue_adjustment_options", None)
    return next_financials

  requires_adjustment = bool(revenue_adjudication.get("requires_adjustment"))
  options = revenue_adjudication.get("options")
  options = [option for option in (options or []) if isinstance(option, dict)]
  if requires_adjustment and current_signature and options:
    next_financials["_pending_revenue_adjustment_signature"] = current_signature
    next_financials["_pending_revenue_adjustment_options"] = options
  else:
    next_financials.pop("_pending_revenue_adjustment_signature", None)
    next_financials.pop("_pending_revenue_adjustment_options", None)
  return next_financials


def _build_cogs_baseline_signature(
  financials_year1_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> str:
  try:
    from financials_year1 import build_revenue_driver_signature as _build_signature  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_year1 import (  # type: ignore
      build_revenue_driver_signature as _build_signature,
    )
  revenue_signature = str(_build_signature(financials_year1_json or {}) or "").strip()
  naics = str((ops_json or {}).get("business_naics_6") or "").strip()
  return f"{naics}::{revenue_signature}" if revenue_signature or naics else ""


def _build_cogs_estimate_context(
  *,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  people_ctx = dict((shared_context or {}).get("people_capability") or {})
  market_ctx = dict((shared_context or {}).get("target_market") or {})
  return {
    "business_type": str((ops_json or {}).get("business_type") or "").strip(),
    "business_naics_6": str((ops_json or {}).get("business_naics_6") or "").strip(),
    "unit_name": str((ops_json or {}).get("unit_name") or "").strip(),
    "unit_description": str((ops_json or {}).get("unit_description") or "").strip(),
    "unit_cadence": str((ops_json or {}).get("unit_cadence") or "").strip(),
    "unit_price": (ops_json or {}).get("unit_price"),
    "units_per_period_capacity": (ops_json or {}).get("units_per_period_capacity"),
    "units_per_week_capacity": (ops_json or {}).get("units_per_week_capacity"),
    "operating_periods_per_year": (ops_json or {}).get("operating_periods_per_year"),
    "utilization_rate": (ops_json or {}).get("utilization_rate"),
    "shipping_method": str((ops_json or {}).get("shipping_method") or "").strip(),
    "sales_modality": str((ops_json or {}).get("sales_modality") or "").strip(),
    "geographic_scope": str((ops_json or {}).get("geographic_scope") or "").strip(),
    "capacity_driver": str((ops_json or {}).get("capacity_driver") or "").strip(),
    "competitive_advantage": str((ops_json or {}).get("competitive_advantage") or "").strip(),
    "market_summary": str((market_ctx or {}).get("target_market_summary") or "").strip(),
    "key_people_summary": str((people_ctx or {}).get("key_people_summary") or "").strip(),
    "people": people_ctx.get("people") or [],
    "inferred_roles": people_ctx.get("inferred_roles") or [],
    "financials_year1_json": financials_year1_json or {},
  }


def _resolve_cogs_baseline_or_raise(
  *,
  conn,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  estimate_cogs_percent_from_context,
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  baseline = _compute_cogs_baseline(
    conn=conn,
    ops_json=ops_json,
    shared_context=shared_context,
    estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
    financials_year1_json=financials_year1_json,
  )
  if isinstance(baseline, dict):
    return baseline
  raise RuntimeError(
    "Unable to resolve a Year-1 COGS baseline from exact industry data or GPT estimation."
  )


def _compute_cogs_baseline(
  *,
  conn,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  estimate_cogs_percent_from_context,
  financials_year1_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  revenue_year1 = float((financials_year1_json or {}).get("company_revenue_total_year1") or 0.0)
  naics_6 = str((ops_json or {}).get("business_naics_6") or "").strip()
  if revenue_year1 <= 0 or not naics_6:
    return None

  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT fiscalDateEnding, quarter, industry_cogs_percent
      FROM industry_growth_table
      WHERE naics_code = %s
        AND industry_cogs_percent IS NOT NULL
      ORDER BY fiscalDateEnding DESC, quarter DESC
      LIMIT 8
      """,
      (naics_6,),
    )
    rows = cur.fetchall() or []
  finally:
    cur.close()

  percents: List[float] = []
  years_used: List[str] = []
  seen_years = set()
  for row in rows:
    year = str(row.get("fiscalDateEnding") or "")[:4].strip()
    if year and year not in seen_years and len(seen_years) >= 2:
      continue
    value = row.get("industry_cogs_percent")
    if value is None:
      continue
    try:
      percents.append(float(value))
    except Exception:
      continue
    year = str(row.get("fiscalDateEnding") or "")[:4].strip()
    if year and year not in seen_years:
      seen_years.add(year)
      years_used.append(year)

  if percents:
    baseline_cogs_percent = float(sum(percents) / len(percents))
    baseline_cogs = float(revenue_year1 * baseline_cogs_percent)
    return {
      "baseline_cogs_percent": baseline_cogs_percent,
      "baseline_cogs": baseline_cogs,
      "cogs_adjustment": 0.0,
      "cogs_total_year1": baseline_cogs,
      "cogs_basis_naics": naics_6,
      "cogs_basis_years_used": years_used[:2],
      "revenue_year1": revenue_year1,
    }

  estimated = estimate_cogs_percent_from_context(
    cogs_estimate_context=_build_cogs_estimate_context(
      ops_json=ops_json,
      shared_context=shared_context,
      financials_year1_json=financials_year1_json,
    ),
  )
  if not estimated:
    return None
  baseline_cogs_percent = float(estimated.get("estimated_cogs_percent") or 0.0)
  baseline_cogs = float(revenue_year1 * baseline_cogs_percent)
  return {
    "baseline_cogs_percent": baseline_cogs_percent,
    "baseline_cogs": baseline_cogs,
    "cogs_adjustment": 0.0,
    "cogs_total_year1": baseline_cogs,
    "cogs_basis_naics": naics_6,
    "cogs_basis_years_used": [],
    "revenue_year1": revenue_year1,
    "cogs_basis_rationale": str(estimated.get("brief_rationale") or "").strip(),
  }


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    return float(value)
  except Exception:
    return None


def _extract_first_number_from_text(value: Any) -> Optional[float]:
  text = str(value or "").replace(",", "").strip()
  if not text:
    return None
  match = re.search(r"-?\d+(?:\.\d+)?", text)
  if not match:
    return None
  try:
    return float(match.group(0))
  except Exception:
    return None


def _normalize_ratio_like(value: Any) -> Optional[float]:
  numeric = _safe_float(value)
  if numeric is None:
    return None
  if numeric > 1.0:
    return float(numeric) / 100.0
  return float(numeric)


def _safe_int(value: Any) -> Optional[int]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    return int(float(value))
  except Exception:
    return None


def _format_currency(value: Any) -> str:
  amount = _safe_float(value)
  if amount is None:
    return "$0"
  return f"${amount:,.0f}"


def _format_percent(value: Any) -> str:
  ratio = _safe_float(value)
  if ratio is None:
    return "0%"
  return f"{ratio * 100:.0f}%"


def _summarize_income_intent(market_json: Dict[str, Any]) -> str:
  market = market_json if isinstance(market_json, dict) else {}
  values = market.get("income_intent")
  if not isinstance(values, list):
    return ""
  parts: List[str] = []
  for item in values:
    if not isinstance(item, dict):
      continue
    income_min = _safe_float(item.get("income_min"))
    income_max = _safe_float(item.get("income_max"))
    if income_min is None and income_max is None:
      continue
    if income_min is not None and income_max is not None:
      parts.append(f"{_format_currency(income_min)}-{_format_currency(income_max)}")
    elif income_min is not None:
      parts.append(f"{_format_currency(income_min)}+")
    else:
      parts.append(f"up to {_format_currency(income_max)}")
  return ", ".join(parts[:3])


def _summarize_gender_age_intent(market_json: Dict[str, Any]) -> str:
  market = market_json if isinstance(market_json, dict) else {}
  values = market.get("gender_age_intent")
  if not isinstance(values, list):
    return ""
  parts: List[str] = []
  for item in values:
    if not isinstance(item, dict):
      continue
    gender = str(item.get("gender") or "").strip()
    age_min = _safe_int(item.get("age_min"))
    age_max = _safe_int(item.get("age_max"))
    age_part = ""
    if age_min is not None and age_max is not None:
      age_part = f"{age_min}-{age_max}"
    elif age_min is not None:
      age_part = f"{age_min}+"
    elif age_max is not None:
      age_part = f"up to {age_max}"
    piece = ", ".join(part for part in [gender, age_part] if part)
    if piece:
      parts.append(piece)
  return "; ".join(parts[:3])


def _summarize_market_selections(market_json: Dict[str, Any]) -> List[str]:
  market = market_json if isinstance(market_json, dict) else {}
  selections = market.get("selections")
  if not isinstance(selections, list):
    return []
  labels: List[str] = []
  seen = set()
  for item in selections:
    if isinstance(item, dict):
      label = str(
        item.get("segment_name")
        or item.get("label")
        or item.get("selection_name")
        or item.get("name")
        or ""
      ).strip()
    else:
      label = str(item or "").strip()
    if not label or label in seen:
      continue
    seen.add(label)
    labels.append(label)
  return labels[:8]


def _milestone_cadence_hint(text: Any) -> str:
  lowered = str(text or "").strip().lower()
  if not lowered:
    return ""
  if "per week" in lowered or "weekly" in lowered or "a week" in lowered:
    return "weekly"
  if "per month" in lowered or "monthly" in lowered or "a month" in lowered:
    return "monthly"
  if "per year" in lowered or "annual" in lowered or "annually" in lowered or "yearly" in lowered:
    return "annual"
  return ""


def _period_capacity_for_cadence(product: Dict[str, Any], cadence: str) -> Optional[float]:
  cadence_norm = str(cadence or "").strip().lower()
  if cadence_norm == "weekly":
    return _safe_float(product.get("units_per_week_capacity"))
  if cadence_norm == "monthly":
    units = _safe_float(product.get("units_per_period_capacity"))
    return units
  if cadence_norm == "annual":
    units = _safe_float(product.get("units_per_period_capacity"))
    periods = _safe_float(product.get("operating_periods_per_year"))
    if units is not None and periods is not None:
      return units * periods
    annual_units = _safe_float(product.get("annual_units_year1"))
    return annual_units
  return None


def _replace_compact_number_in_text(text: Any, *, target_value: float, replacement_value: float) -> str:
  raw = str(text or "")
  if not raw:
    return raw

  def _normalize_number(value: float) -> str:
    rounded = round(float(value), 6)
    if abs(rounded - round(rounded)) < 1e-6:
      return str(int(round(rounded)))
    return f"{rounded:g}"

  pattern = re.compile(r"\b\d[\d,]*(?:\.\d+)?[kKmM]?\b")
  replaced = False

  def _repl(match: re.Match[str]) -> str:
    nonlocal replaced
    token = str(match.group(0) or "").strip()
    if not token:
      return token
    numeric = _extract_single_compact_number(token)
    if numeric is None:
      return token
    if replaced:
      return token
    if abs(float(numeric) - float(target_value)) > 1e-6:
      return token
    replaced = True
    return _normalize_number(replacement_value)

  updated = pattern.sub(_repl, raw, count=0)
  if replaced:
    return updated
  return pattern.sub(_normalize_number(replacement_value), raw, count=1)


def _refresh_shared_forecast_context(
  shared_context: Optional[Dict[str, Any]],
  bundle: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  del bundle
  return dict(shared_context or {})


def _build_planning_run_payload(
  *,
  stage: str,
  status: str,
  controller_resolution_state: Optional[Dict[str, Any]] = None,
  resolution_summary: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
  planning_mode_reason: Optional[str] = None,
  prompt_file: Optional[str] = None,
  gpt_narrative: Optional[str] = None,
  gpt_grid_metadata: Optional[Dict[str, Any]] = None,
  grid_application_summary: Optional[Dict[str, Any]] = None,
  realism_memo_before_resolution: Optional[Dict[str, Any]] = None,
  realism_resolution_decision: Optional[Dict[str, Any]] = None,
  realism_resolution_plan: Optional[Dict[str, Any]] = None,
  realism_resolution_result: Optional[Dict[str, Any]] = None,
  realism_resolution_verification: Optional[Dict[str, Any]] = None,
  realism_resolution_iterations: Optional[List[Dict[str, Any]]] = None,
  realism_resolution_stop_reason: Optional[str] = None,
  realism_resolution_iteration_count: Optional[int] = None,
  first_pass_handoff: Optional[Dict[str, Any]] = None,
  cash_strategy_review_context: Optional[Dict[str, Any]] = None,
  cash_strategy_review_decision: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_plan: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
  cash_strategy_effect_summary: Optional[Dict[str, Any]] = None,
  diagnostics_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  payload: Dict[str, Any] = {
    "contract_version": "planning_run_v1",
    "stage": str(stage or "").strip() or "pending",
    "status": str(status or "").strip() or "pending",
    "controller_resolution_state": copy.deepcopy(controller_resolution_state or {}),
    "planning_mode": str(planning_mode or "").strip() or None,
    "planning_mode_reason": str(planning_mode_reason or "").strip() or None,
    "prompt_file": str(prompt_file or "").strip() or None,
    "gpt_narrative": str(gpt_narrative or "").strip() or None,
    "gpt_grid_metadata": copy.deepcopy(gpt_grid_metadata or {}),
    "grid_application_summary": copy.deepcopy(grid_application_summary or {}),
    "realism_memo_before_resolution": copy.deepcopy(realism_memo_before_resolution or {}),
    "realism_resolution_decision": copy.deepcopy(realism_resolution_decision or {}),
    "realism_resolution_plan": copy.deepcopy(realism_resolution_plan or {}),
    "realism_resolution_result": copy.deepcopy(realism_resolution_result or {}),
    "realism_resolution_verification": copy.deepcopy(realism_resolution_verification or {}),
    "realism_resolution_iterations": copy.deepcopy(realism_resolution_iterations or []),
    "realism_resolution_stop_reason": str(realism_resolution_stop_reason or "").strip() or None,
    "realism_resolution_iteration_count": int(realism_resolution_iteration_count or 0) or None,
    "first_pass_handoff": copy.deepcopy(first_pass_handoff or {}),
    "cash_strategy_review_context": copy.deepcopy(cash_strategy_review_context or {}),
    "cash_strategy_review_decision": copy.deepcopy(cash_strategy_review_decision or {}),
    "cash_strategy_second_pass_plan": copy.deepcopy(cash_strategy_second_pass_plan or {}),
    "cash_strategy_second_pass_result": copy.deepcopy(cash_strategy_second_pass_result or {}),
    "cash_strategy_effect_summary": copy.deepcopy(cash_strategy_effect_summary or {}),
    "diagnostics_snapshot": copy.deepcopy(diagnostics_snapshot or {}),
  }
  return payload


def _first_pass_finmo_summary(finmo_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  quarter_rows = [row for row in (finmo_obj.get("quarter_rows") or []) if isinstance(row, dict)]
  live_rows = [row for row in quarter_rows if int(float(row.get("quarter_index") or 0)) >= 1]
  if not live_rows:
    return {}

  def _row_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
      "quarter_index": int(float(row.get("quarter_index") or 0)),
      "year": row.get("year"),
      "quarter": row.get("quarter"),
      "date": row.get("date"),
      "revenue": _safe_float(row.get("revenue")),
      "ebitda": _safe_float(row.get("ebitda")),
      "net_income": _safe_float(row.get("net_income")),
      "ending_cash": _safe_float(row.get("ending_cash")),
      "total_assets": _safe_float(row.get("total_assets")),
      "total_liabilities_and_equity": _safe_float(row.get("total_liabilities_and_equity")),
    }

  cash_values = [_safe_float(row.get("ending_cash")) or 0.0 for row in live_rows]
  return {
    "quarter_count": len(live_rows),
    "first_quarter": _row_metrics(live_rows[0]),
    "last_quarter": _row_metrics(live_rows[-1]),
    "cash_peak": max(cash_values) if cash_values else 0.0,
    "cash_trough": min(cash_values) if cash_values else 0.0,
  }


def _build_first_pass_handoff_payload(
  *,
  draft_id: str,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  grid_application_summary: Optional[Dict[str, Any]],
  applied_model_input_json: Optional[Dict[str, Any]],
  applied_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  business = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  model_input = applied_model_input_json if isinstance(applied_model_input_json, dict) else {}
  finmo = applied_finmo_json if isinstance(applied_finmo_json, dict) else {}
  periods = [item for item in (model_input.get("periods") or []) if isinstance(item, dict)]
  return {
    "contract_version": "first_pass_handoff_v1",
    "status": "ready",
    "handoff_role": "baseline_for_cash_strategy_review",
    "draft_id": str(draft_id or "").strip(),
    "planning_mode": str(planning_mode or "").strip(),
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "prompt_file": str(prompt_file or "").strip(),
    "business_snapshot": {
      "business_name": str(business.get("name") or business.get("business_name") or "").strip(),
      "business_type": str(ops.get("business_type") or "").strip(),
      "business_stage": str(ops.get("business_stage") or "").strip(),
      "cash_strategy": str(financials.get("cash_strategy") or "").strip(),
      "forecast_quarter_count": len(periods),
    },
    "artifacts": {
      "applied_model_input_persisted": bool(model_input),
      "applied_finmo_persisted": bool(finmo),
      "draft_fields": ["model_input_json", "finmo_json"],
    },
    "grid_application_summary": copy.deepcopy(grid_application_summary or {}),
    "finmo_summary": _first_pass_finmo_summary(finmo),
    "ready_for_cash_strategy_review": True,
  }


def _finmo_labeled_series(
  finmo_payload: Optional[Dict[str, Any]],
  *,
  section_key: str,
  label: str,
) -> List[float]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  rows = [row for row in (finmo_obj.get(section_key) or []) if isinstance(row, dict)]
  for row in rows:
    if str(row.get("label") or "").strip() != str(label or "").strip():
      continue
    return [float(_safe_float(item) or 0.0) for item in (row.get("values") or [])]
  return []


def _cash_review_quarter_metrics(finmo_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  quarter_rows = [row for row in (finmo_obj.get("quarter_rows") or []) if isinstance(row, dict)]
  live_rows = [row for row in quarter_rows if int(float(row.get("quarter_index") or 0)) >= 1]
  metrics: List[Dict[str, Any]] = []
  for row in live_rows:
    metrics.append(
      {
        "quarter_index": int(float(row.get("quarter_index") or 0)),
        "year": row.get("year"),
        "quarter": row.get("quarter"),
        "date": row.get("date"),
        "revenue": _safe_float(row.get("revenue")),
        "ebitda": _safe_float(row.get("ebitda")),
        "net_income": _safe_float(row.get("net_income")),
        "ending_cash": _safe_float(row.get("ending_cash")),
        "total_assets": _safe_float(row.get("total_assets")),
        "total_liabilities_and_equity": _safe_float(row.get("total_liabilities_and_equity")),
      }
    )
  return metrics


def _realism_metric_series(
  finmo_payload: Optional[Dict[str, Any]],
  *,
  metric: str,
) -> List[float]:
  metric_norm = str(metric or "").strip().lower().replace(" ", "_")
  metric_key_map = {
    "revenue": "revenue",
    "ebitda": "ebitda",
    "cash": "ending_cash",
    "net_income": "net_income",
  }
  key = metric_key_map.get(metric_norm, metric_norm)
  series: List[float] = []
  for row in _cash_review_quarter_metrics(finmo_payload):
    series.append(float(_safe_float(row.get(key)) or 0.0))
  return series


def _lever_catalog_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
  out: Dict[str, Dict[str, Any]] = {}
  for item in _build_writable_lever_review_catalog(model_input_json):
    lever_id = str(item.get("lever_id") or "").strip()
    if lever_id:
      out[lever_id] = dict(item)
  return out


def _relative_move_limit(
  *,
  baseline_value: float,
  max_relative_change: float,
  value_kind: str,
  input_semantics: str,
) -> float:
  baseline_abs = abs(float(baseline_value or 0.0))
  max_rel = max(0.0, min(1.0, float(max_relative_change or 0.0)))
  value_kind_norm = str(value_kind or "").strip().lower()
  semantics_norm = str(input_semantics or "").strip().lower()
  if value_kind_norm == "ratio":
    anchor = max(baseline_abs, 0.05)
    return min(0.5, anchor * max_rel)
  if value_kind_norm == "day_count":
    anchor = max(baseline_abs, 5.0)
    return max(1.0, anchor * max_rel)
  if "percent_of_revenue" in semantics_norm or "percent_of_long_term_debt" in semantics_norm:
    anchor = max(baseline_abs, 0.05)
    return min(0.5, anchor * max_rel)
  anchor = max(baseline_abs, 1.0)
  return anchor * max_rel


def _translate_realism_lever_adjustment(
  *,
  adjustment: Dict[str, Any],
  baseline_map: Dict[str, List[float]],
  lever_catalog_map: Dict[str, Dict[str, Any]],
  quarter_count: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
  lever_id = str(adjustment.get("lever_id") or "").strip()
  if not lever_id:
    return None, "missing lever_id"
  baseline_values = baseline_map.get(lever_id)
  if not baseline_values:
    return None, f"unknown lever_id {lever_id}"
  quarter_index = int(_safe_float(adjustment.get("quarter_index")) or 0)
  if quarter_index < 1 or quarter_index > max(1, int(quarter_count or 0)):
    return None, f"{lever_id} has invalid quarter_index {quarter_index or 'missing'}"
  direction = str(adjustment.get("direction") or "").strip().lower()
  if direction not in {"increase", "decrease", "either", "hold"}:
    return None, f"{lever_id} has unsupported direction {direction or 'missing'}"
  max_relative_change = _safe_float(adjustment.get("max_relative_change"))
  if max_relative_change is None:
    return None, f"{lever_id} missing max_relative_change"
  max_relative_change = max(0.0, min(1.0, float(max_relative_change)))
  meta = lever_catalog_map.get(lever_id) or {}
  baseline_window = _baseline_window_summary(baseline_values, start_q=quarter_index, end_q=quarter_index)
  baseline_value = float(_safe_float(baseline_window.get("value_end")) or 0.0)
  move_limit = _relative_move_limit(
    baseline_value=baseline_value,
    max_relative_change=max_relative_change,
    value_kind=str(meta.get("value_kind") or "").strip(),
    input_semantics=str(meta.get("input_semantics") or "").strip(),
  )
  if direction == "hold":
    min_value = baseline_value - move_limit
    max_value = baseline_value + move_limit
  elif direction == "increase":
    min_value = baseline_value
    max_value = baseline_value + move_limit
  elif direction == "decrease":
    min_value = baseline_value - move_limit
    max_value = baseline_value
  else:
    min_value = baseline_value - move_limit
    max_value = baseline_value + move_limit

  translated = {
    "lever_id": lever_id,
    "section": str(adjustment.get("section") or meta.get("section") or "").strip(),
    "direction": direction,
    "control_mode": "band",
    "quarter_index": quarter_index,
    "baseline_window": baseline_window,
    "business_reason": str(adjustment.get("business_reason") or "").strip(),
    "linked_action_effect": str(adjustment.get("linked_action_effect") or "").strip(),
    "max_relative_change": max_relative_change,
    "exact_value": None,
    "min_value": float(min(min_value, max_value)),
    "max_value": float(max(min_value, max_value)),
  }
  return translated, None


def _translate_realism_output_target(
  *,
  target: Dict[str, Any],
  finmo_json: Optional[Dict[str, Any]],
  quarter_count: int,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
  metric = str(target.get("metric") or "").strip()
  if not metric:
    return [], "missing target metric"
  quarter_index = int(_safe_float(target.get("quarter_index")) or 0)
  if quarter_index < 1 or quarter_index > max(1, int(quarter_count or 0)):
    return [], f"{metric} has invalid quarter_index {quarter_index or 'missing'}"
  direction = str(target.get("direction") or "").strip().lower()
  if direction not in {"increase", "decrease", "hold"}:
    return [], f"{metric} has unsupported direction {direction or 'missing'}"
  min_relative_change = _safe_float(target.get("min_relative_change"))
  max_relative_change = _safe_float(target.get("max_relative_change"))
  if min_relative_change is None or max_relative_change is None:
    return [], f"{metric} missing min_relative_change or max_relative_change"
  low_rel = max(0.0, min(1.0, float(min(min_relative_change, max_relative_change))))
  high_rel = max(0.0, min(1.0, float(max(min_relative_change, max_relative_change))))
  baseline_series = _realism_metric_series(finmo_json, metric=metric)
  if not baseline_series:
    return [], f"{metric} has no baseline series"

  base_value = float(_safe_float(baseline_series[quarter_index - 1]) or 0.0)
  scale = max(abs(base_value), 1.0)
  if direction == "increase":
    min_value = base_value + (low_rel * scale)
    max_value = base_value + (high_rel * scale)
  elif direction == "decrease":
    min_value = base_value - (high_rel * scale)
    max_value = base_value - (low_rel * scale)
  else:
    min_value = base_value - (high_rel * scale)
    max_value = base_value + (high_rel * scale)
  return (
    [
      {
        "metric": metric,
        "quarter_index": quarter_index,
        "direction": direction,
        "baseline_value": base_value,
        "min_value": float(min(min_value, max_value)),
        "max_value": float(max(min_value, max_value)),
        "business_reason": str(target.get("business_reason") or "").strip(),
      }
    ],
    None,
  )


def _extract_controller_lever_catalog(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  direct = [
    item
    for item in (model_input.get("controller_write_levers") or [])
    if isinstance(item, dict)
    and bool(item.get("controller_write", True))
    and str(item.get("lever_id") or "").strip()
  ]
  if direct:
    return direct
  lever_catalog = model_input.get("lever_catalog") if isinstance(model_input.get("lever_catalog"), dict) else {}
  return [
    item
    for item in lever_catalog.values()
    if isinstance(item, dict)
    and bool(item.get("controller_write", True))
    and str(item.get("lever_id") or "").strip()
  ]


def _lever_usage_guidance(lever_id: str) -> Dict[str, Any]:
  lever = str(lever_id or "").strip()
  if lever == "schedules::Plus: Additions (repayments), net":
    return {
      "label_path_override": "Plus: Additions (repayments), net (Debt Draws / Debt Repayments)",
      "accounting_role": "debt_financing",
      "preferred_uses": [
        "new borrowing",
        "debt paydown",
        "debt restructuring",
      ],
      "forbidden_uses": [
        "owner distributions",
        "partner draws",
        "equity contributions",
        "capital lease additions",
      ],
    }
  if lever == "schedules::Capital Expenditures":
    return {
      "label_path_override": "Capital Expenditures (Cash PPE Spend)",
      "accounting_role": "investing_cash_outflow",
      "preferred_uses": [
        "equipment purchases",
        "buildout spend",
        "fit-out or furniture spend",
      ],
      "forbidden_uses": [
        "noncash lease additions",
        "owner distributions",
        "debt activity",
      ],
    }
  if lever == "schedules::Less: Principal Repayments":
    return {
      "label_path_override": "Less: Principal Repayments (Capital Lease Principal)",
      "accounting_role": "capital_lease_principal_repayment",
      "preferred_uses": [
        "capital lease principal repayment",
      ],
      "forbidden_uses": [
        "term debt repayment",
        "owner distributions",
        "capex spend",
      ],
    }
  if lever == "schedules::Plus: Net Additions":
    return {
      "label_path_override": "Plus: Net Additions (Capital Lease Additions Only)",
      "accounting_role": "capital_lease_addition",
      "preferred_uses": [
        "new capital lease asset additions",
        "equipment acquired through leasing",
      ],
      "forbidden_uses": [
        "owner distributions",
        "partner draws",
        "equity contributions",
        "generic financing",
        "term debt activity",
      ],
    }
  if lever == "balance_sheet::Owner's Capital":
    return {
      "label_path_override": "Owner's Capital (Owner / Partner Capital Contributions In Only)",
      "accounting_role": "owner_equity_contribution",
      "preferred_uses": [
        "owner contribution",
        "partner capital contribution",
      ],
      "forbidden_uses": [
        "owner distribution",
        "partner draw",
        "debt draw",
        "lease activity",
        "capex spend",
      ],
    }
  if lever == "balance_sheet::Distributions":
    return {
      "label_path_override": "Distributions (Owner / Partner Payouts Out)",
      "accounting_role": "owner_distribution",
      "preferred_uses": [
        "owner distribution",
        "partner draw",
        "shareholder payout",
      ],
      "forbidden_uses": [
        "owner contribution",
        "debt draw",
        "lease activity",
        "capex spend",
      ],
    }
  if lever == "balance_sheet::Other Equity":
    return {
      "label_path_override": "Other Equity (Non-owner Equity In or Out)",
      "accounting_role": "other_equity",
      "preferred_uses": [
        "other equity contribution",
        "other equity distribution",
      ],
      "forbidden_uses": [
        "debt activity",
        "lease activity",
        "capex spend",
      ],
    }
  return {}


def _build_writable_lever_review_catalog(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  review_catalog: List[Dict[str, Any]] = []
  for item in _extract_controller_lever_catalog(model_input_json):
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    guidance = _lever_usage_guidance(lever_id)
    review_catalog.append(
      {
        "lever_id": lever_id,
        "section": str(item.get("section") or "").strip(),
        "label_path": str(guidance.get("label_path_override") or item.get("label_path") or "").strip(),
        "driver": str(item.get("driver") or item.get("label") or "").strip(),
        "lob": str(item.get("lob") or "").strip(),
        "product": str(item.get("product") or "").strip(),
        "value_kind": str(item.get("value_kind") or "").strip(),
        "input_semantics": str(item.get("input_semantics") or "").strip(),
        "accounting_role": str(guidance.get("accounting_role") or "").strip(),
        "preferred_uses": [str(v).strip() for v in (guidance.get("preferred_uses") or []) if str(v).strip()],
        "forbidden_uses": [str(v).strip() for v in (guidance.get("forbidden_uses") or []) if str(v).strip()],
      }
    )
  return review_catalog


def _model_input_with_controller_catalog(
  *,
  model_input_json: Optional[Dict[str, Any]],
  catalog_source_model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  current = copy.deepcopy(model_input_json or {}) if isinstance(model_input_json, dict) else {}
  source = catalog_source_model_input_json if isinstance(catalog_source_model_input_json, dict) else {}
  if not current:
    current = {}
  if isinstance(source.get("canonical_lever_vocabulary"), str) and not str(current.get("canonical_lever_vocabulary") or "").strip():
    current["canonical_lever_vocabulary"] = str(source.get("canonical_lever_vocabulary") or "").strip()
  if isinstance(source.get("lever_catalog"), dict) and not isinstance(current.get("lever_catalog"), dict):
    current["lever_catalog"] = copy.deepcopy(source.get("lever_catalog") or {})
  if not _extract_controller_lever_catalog(current):
    source_catalog = _extract_controller_lever_catalog(source)
    if source_catalog:
      current["controller_write_levers"] = copy.deepcopy(source_catalog)
  return current


def _build_cash_strategy_review_context_payload(
  *,
  draft_id: str,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  solved_model_input_json: Optional[Dict[str, Any]],
  solved_finmo_json: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  business = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  model_input = solved_model_input_json if isinstance(solved_model_input_json, dict) else {}
  finmo = solved_finmo_json if isinstance(solved_finmo_json, dict) else {}
  lever_catalog = _extract_controller_lever_catalog(model_input)
  lever_ids = [str(item.get("lever_id") or "").strip() for item in lever_catalog if str(item.get("lever_id") or "").strip()]
  section_counts: Dict[str, int] = {}
  for item in lever_catalog:
    section_name = str(item.get("section") or "").strip() or "unknown"
    section_counts[section_name] = int(section_counts.get(section_name) or 0) + 1
  quarter_metrics = _cash_review_quarter_metrics(finmo)
  ending_cash_series = [float(_safe_float(item.get("ending_cash")) or 0.0) for item in quarter_metrics]
  revenue_series = [float(_safe_float(item.get("revenue")) or 0.0) for item in quarter_metrics]
  ebitda_series = [float(_safe_float(item.get("ebitda")) or 0.0) for item in quarter_metrics]
  net_income_series = [float(_safe_float(item.get("net_income")) or 0.0) for item in quarter_metrics]
  ebitda_margin_series = [
    (float(ebitda) / float(revenue)) if abs(float(revenue)) > 1e-9 else 0.0
    for revenue, ebitda in zip(revenue_series, ebitda_series)
  ]
  net_income_margin_series = [
    (float(net_income) / float(revenue)) if abs(float(revenue)) > 1e-9 else 0.0
    for revenue, net_income in zip(revenue_series, net_income_series)
  ]
  controller_issue_summaries = _controller_state_issue_summaries(controller_resolution_state)
  remaining_issues = controller_issue_summaries.get("remaining_issues") or []
  resolved_issues = controller_issue_summaries.get("resolved_issues") or []
  trailing_4_ebitda_margins = ebitda_margin_series[-4:] if len(ebitda_margin_series) >= 4 else list(ebitda_margin_series)
  final_cash = ending_cash_series[-1] if ending_cash_series else 0.0
  peak_cash = max(ending_cash_series) if ending_cash_series else 0.0
  late_negative_net_income_quarters = [
    int(item.get("quarter_index") or 0)
    for item in quarter_metrics[-6:]
    if float(_safe_float(item.get("net_income")) or 0.0) < 0.0
  ]
  trigger_candidates: List[Dict[str, Any]] = []
  remaining_issue_codes = [
    str(item.get("issue_code") or "").strip().lower()
    for item in remaining_issues
    if str(item.get("issue_code") or "").strip()
  ]
  if "profitability_cash_shape_unrealistic" in remaining_issue_codes:
    trigger_candidates.append(
      {
        "trigger_type": "stress",
        "trigger_code": "profitability_cash_shape_unrealistic",
        "reason": "Remaining realism issue indicates the solved business still ends in an unrealistic profitability/cash shape.",
      }
    )
  if "financing_solvency_mismatch" in remaining_issue_codes or late_negative_net_income_quarters:
    trigger_candidates.append(
      {
        "trigger_type": "stress",
        "trigger_code": "solvency_or_income_pressure",
        "reason": "Late-horizon solvency or net-income pressure suggests management would realistically respond.",
        "late_negative_net_income_quarters": late_negative_net_income_quarters,
      }
    )
  if peak_cash > max(500000.0, final_cash * 0.9) and final_cash > 500000.0:
    trigger_candidates.append(
      {
        "trigger_type": "surplus",
        "trigger_code": "excess_idle_cash",
        "reason": "The solved business holds a visibly large cash balance that may justify strategy-shaped deployment or retention decisions.",
        "peak_cash": peak_cash,
        "final_cash": final_cash,
      }
    )
  if _has_confirmed_milestone(ops):
    trigger_candidates.append(
      {
        "trigger_type": "milestone",
        "trigger_code": "binding_future_intent_present",
        "reason": "Confirmed milestone intent exists and may require structural management action if the solved business under-manifests it.",
      }
    )
  return {
    "contract_version": "cash_strategy_review_context_v1",
    "status": "ready",
    "review_required": True,
    "review_role": "mandatory_post_solve_cash_strategy_review",
    "draft_id": str(draft_id or "").strip(),
    "planning_mode": str(planning_mode or "").strip(),
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "prompt_file": str(prompt_file or "").strip(),
    "selected_cash_strategy": str(financials.get("cash_strategy") or "").strip(),
    "ops_milestones": _build_realism_milestone_context(
      ops_json=ops,
      solved_model_input_json=model_input,
    ),
    "business_snapshot": {
      "business_name": str(business.get("name") or business.get("business_name") or "").strip(),
      "business_type": str(ops.get("business_type") or "").strip(),
      "business_stage": str(ops.get("business_stage") or "").strip(),
      "capacity_driver": str(ops.get("capacity_driver") or "").strip(),
      "unit_name": str(ops.get("unit_name") or "").strip(),
      "sales_modality": str(ops.get("sales_modality") or "").strip(),
      "geographic_scope": str(ops.get("geographic_scope") or "").strip(),
    },
    "source_artifacts": {
      "model_input_json_field": "model_input_json",
      "finmo_json_field": "finmo_json",
      "solved_model_input_persisted": bool(model_input),
      "solved_finmo_persisted": bool(finmo),
    },
    "writable_lever_catalog": {
      "lever_count": len(lever_ids),
      "section_counts": section_counts,
      "lever_ids": lever_ids,
    },
    "quarter_metrics": quarter_metrics,
    "strategy_relevant_series": {
      "revenue": revenue_series,
      "ebitda": ebitda_series,
      "net_income": net_income_series,
      "ebitda_margin": ebitda_margin_series,
      "net_income_margin": net_income_margin_series,
      "ending_cash": ending_cash_series,
      "marketing": _finmo_labeled_series(finmo, section_key="pl", label="Marketing"),
      "payroll": _finmo_labeled_series(finmo, section_key="pl", label="Payroll"),
      "lease_rent": _finmo_labeled_series(finmo, section_key="pl", label="Lease/Rent"),
      "capital_expenditures": _finmo_labeled_series(finmo, section_key="cash_flow", label="Capital Expenditures"),
      "principal_repayments": _finmo_labeled_series(finmo, section_key="cash_flow", label="Dept Receive(Repay)"),
      "long_term_debt": _finmo_labeled_series(finmo, section_key="balance_sheet", label="Long Term Debt"),
      "total_liabilities": _finmo_labeled_series(finmo, section_key="balance_sheet", label="Total Liabilities"),
    },
    "cash_profile_summary": {
      "quarter_count": len(quarter_metrics),
      "cash_peak": max(ending_cash_series) if ending_cash_series else 0.0,
      "cash_trough": min(ending_cash_series) if ending_cash_series else 0.0,
      "ending_cash_final": ending_cash_series[-1] if ending_cash_series else 0.0,
    },
    "decision_trigger_candidates": trigger_candidates,
    "late_horizon_summary": {
      "late_negative_net_income_quarters": late_negative_net_income_quarters,
      "trailing_4_ebitda_margins": trailing_4_ebitda_margins,
    },
  }


def _load_cash_strategy_review_prompt() -> str:
  try:
    return _CASH_STRATEGY_REVIEW_PROMPT_PATH.read_text(encoding="utf-8").strip()
  except Exception:
    return (
      "You are the post-solve cash strategy reviewer for a real business plan.\n"
      "You are reviewing an already solved, coherent business model.\n"
      "Your job is to decide whether the solved business visibly reflects the selected cash strategy and, if not, prescribe realistic coordinated management actions using only the provided writable lever ids.\n"
      "Be bold within reason: make the selected strategy visible when the solved economics support it, but do not force reckless or fake moves.\n"
      "Think like actual management of a living business, not like a spreadsheet optimizer.\n"
      "Any recommendation must preserve believable operating continuity of the current business.\n"
      "You may re-time, phase, slow, or scale real business actions, but do not hollow out the business below a believable steady-state operating condition.\n"
      "Do not use writable rows as implicit plugs or balancing placeholders.\n"
      "Do not silently force cash, solvency, profitability, or optics with row tweaks that lack a believable operating story.\n"
      "Capital allocation must read like a real management decision, not hidden model repair.\n"
      "Levers do not operate in silos. When a real-world action requires coordinated changes across multiple rows, return a linked lever package rather than isolated row tweaks.\n"
      "Do not invent lever ids. Do not rebuild the whole business from scratch."
    )


def _load_realism_resolution_prompt() -> str:
  try:
    return _REALISM_RESOLUTION_PROMPT_PATH.read_text(encoding="utf-8").strip()
  except Exception:
    return (
      "You are the mandatory realism resolution planner. "
      "Use only provided writable lever ids and return structured JSON only."
    ).strip()


_ISSUE_CODE_REGISTRY: Dict[str, Dict[str, Any]] = {
  "operating_model_contradiction": {
    "title": "operating_model_contradiction",
    "reopen_prefixes": ["revenue::"],
    "reopen_contains": ["::capacity", "::utilization"],
  },
  "capacity_revenue_mismatch": {
    "title": "capacity_revenue_mismatch",
    "reopen_prefixes": ["revenue::"],
    "reopen_contains": ["::capacity", "::utilization", "::unit price"],
  },
  "pricing_positioning_mismatch": {
    "title": "pricing_positioning_mismatch",
    "reopen_prefixes": ["revenue::"],
    "reopen_contains": ["::unit price"],
  },
  "staffing_payroll_mismatch": {
    "title": "staffing_payroll_mismatch",
    "reopen_prefixes": ["expenses::payroll", "revenue::"],
    "reopen_contains": ["::capacity", "::utilization"],
  },
  "cost_structure_mismatch": {
    "title": "cost_structure_mismatch",
    "reopen_prefixes": [
      "expenses::cost of goods sold",
      "expenses::general and administrative",
      "expenses::marketing",
      "expenses::payroll",
    ],
    "reopen_contains": [],
  },
  "working_capital_payment_model_mismatch": {
    "title": "working_capital_payment_model_mismatch",
    "reopen_prefixes": [
      "balance_sheet::accounts receivable days",
      "balance_sheet::inventory days",
      "balance_sheet::accounts payable days",
      "balance_sheet::prepaid expenses",
      "balance_sheet::deferred revenue",
    ],
    "reopen_contains": [],
  },
  "financing_solvency_mismatch": {
    "title": "financing_solvency_mismatch",
    "reopen_prefixes": [
      "schedules::capital expenditures",
      "schedules::plus: additions (repayments), net",
      "balance_sheet::owner's capital",
      "balance_sheet::other equity",
      "expenses::marketing",
      "expenses::payroll",
      "expenses::cost of goods sold",
      "expenses::general and administrative",
      "revenue::",
    ],
    "reopen_contains": ["::capacity", "::utilization", "::unit price"],
  },
  "profitability_cash_shape_unrealistic": {
    "title": "profitability_cash_shape_unrealistic",
    "reopen_prefixes": [
      "schedules::capital expenditures",
      "schedules::plus: additions (repayments), net",
      "balance_sheet::owner's capital",
      "balance_sheet::other equity",
      "expenses::marketing",
      "expenses::payroll",
      "expenses::cost of goods sold",
      "expenses::general and administrative",
      "revenue::",
    ],
    "reopen_contains": ["::capacity", "::utilization", "::unit price"],
  },
  "capex_footprint_mismatch": {
    "title": "The capital expenditure pattern is heavy and ongoing despite the business not achieving profitability or positive operating cash flow.",
    "reopen_prefixes": [
      "schedules::capital expenditures",
      "schedules::plus: additions (repayments), net",
      "balance_sheet::owner's capital",
      "balance_sheet::other equity",
    ],
    "reopen_contains": [],
  },
}


def _issue_registry_entry(issue_code: Any) -> Dict[str, Any]:
  return _ISSUE_CODE_REGISTRY.get(str(issue_code or "").strip().lower(), {})


def _canonical_issue_title(issue_code: Any, fallback: Any) -> str:
  entry = _issue_registry_entry(issue_code)
  title = str(entry.get("title") or "").strip()
  if title:
    return title
  return str(fallback or "").strip()


def _touched_lever_ids_from_result(result_payload: Optional[Dict[str, Any]]) -> List[str]:
  result = result_payload if isinstance(result_payload, dict) else {}
  ids: List[str] = []
  for item in (result.get("applied_updates") or []):
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if lever_id and lever_id not in ids:
      ids.append(lever_id)
  return ids


def _normalized_issue_records(items: Any) -> List[Dict[str, str]]:
  out: List[Dict[str, str]] = []
  for item in (items or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    issue = str(item.get("issue") or "").strip()
    detail = str(item.get("detail") or "").strip()
    if not issue_code or not issue or not detail:
      continue
    record: Dict[str, str] = {"issue": issue, "detail": detail}
    record["issue_code"] = issue_code
    out.append(record)
  return out


def _memo_issue_records(payload: Optional[Dict[str, Any]], *fields: str) -> List[Dict[str, str]]:
  memo = payload if isinstance(payload, dict) else {}
  for field in fields:
    items = _normalized_issue_records(memo.get(field))
    if items:
      return items
  return []


def _issue_ledger_key(item: Dict[str, Any]) -> str:
  issue_code = str(item.get("issue_code") or "").strip().lower()
  return f"code::{issue_code}" if issue_code else ""


def _core_issue_record(item: Dict[str, Any]) -> Dict[str, str]:
  issue_code = str(item.get("issue_code") or "").strip().lower()
  record: Dict[str, str] = {
    "issue": _canonical_issue_title(issue_code, item.get("issue")),
    "detail": str(item.get("detail") or "").strip(),
  }
  if issue_code:
    record["issue_code"] = issue_code
  return record


def _merge_issue_identity_fields(
  existing: Dict[str, Any],
  incoming: Dict[str, Any],
) -> Dict[str, Any]:
  merged = copy.deepcopy(existing if isinstance(existing, dict) else {})
  incoming_core = _core_issue_record(incoming if isinstance(incoming, dict) else {})
  incoming_code = str(incoming_core.get("issue_code") or "").strip().lower()
  if incoming_code and not str(merged.get("issue_code") or "").strip():
    merged["issue_code"] = incoming_code
  canonical_title = _canonical_issue_title(incoming_code, incoming_core.get("issue"))
  if canonical_title:
    merged["issue"] = canonical_title
  if incoming_core.get("detail") and not str(merged.get("detail") or "").strip():
    merged["detail"] = incoming_core["detail"]
  return merged


def _normalize_realism_verifier_status(value: Any) -> str:
  status = str(value or "").strip().lower()
  if status in {"resolved", "partially_resolved", "not_resolved"}:
    return status
  return "not_resolved"


def _normalize_realism_materiality(value: Any) -> str:
  materiality = str(value or "").strip().lower()
  if materiality in {"immaterial", "material"}:
    return materiality
  return "material"


def _normalize_realism_remaining_quarters(value: Any) -> List[int]:
  return [
    int(_safe_float(q) or 0)
    for q in (value or [])
    if int(_safe_float(q) or 0) >= 1
  ]


def _normalize_realism_lever_ids(value: Any) -> List[str]:
  return [
    str(lever_id or "").strip()
    for lever_id in (value or [])
    if str(lever_id or "").strip()
  ]


_REALISM_ITERATION_LOW_SEVERITY_MAX = 15
_REALISM_ITERATION_SMALL_QUARTER_COUNT_MAX = 2


def _safe_int_in_range(value: Any, *, default: int, minimum: int, maximum: int) -> int:
  parsed = _safe_float(value)
  if parsed is None:
    return default
  bounded = int(round(parsed))
  return max(minimum, min(maximum, bounded))


def _controller_resolution_from_verification_issue(
  issue_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  result = issue_result if isinstance(issue_result, dict) else {}
  verifier_status = _normalize_realism_verifier_status(result.get("status"))
  remaining_issue_materiality = _normalize_realism_materiality(
    result.get("remaining_issue_materiality")
    if result.get("remaining_issue_materiality") is not None
    else result.get("residual_materiality")
  )
  remaining_issue_severity_score = _safe_int_in_range(
    result.get("remaining_issue_severity_score")
    if result.get("remaining_issue_severity_score") is not None
    else result.get("residual_severity_score"),
    default=100 if verifier_status == "not_resolved" else 50,
    minimum=0,
    maximum=100,
  )
  remaining_problem_quarters = _normalize_realism_remaining_quarters(
    result.get("remaining_problem_quarters")
  )
  next_required_lever_ids = _normalize_realism_lever_ids(
    result.get("next_required_lever_ids")
  )

  return {
    "verifier_status": verifier_status,
    "remaining_issue_materiality": remaining_issue_materiality,
    "remaining_issue_severity_score": remaining_issue_severity_score,
    "remaining_problem_quarters": remaining_problem_quarters,
    "next_required_lever_ids": next_required_lever_ids,
  }


def _iteration_decision_from_issue_record(
  item: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  record = item if isinstance(item, dict) else {}
  verifier_status = _normalize_realism_verifier_status(record.get("verifier_status"))
  severity = _safe_int_in_range(
    record.get("remaining_issue_severity_score"),
    default=100 if verifier_status == "not_resolved" else 50,
    minimum=0,
    maximum=100,
  )
  quarters = _normalize_realism_remaining_quarters(record.get("remaining_problem_quarters"))
  next_levers = _normalize_realism_lever_ids(record.get("next_required_lever_ids"))

  if verifier_status == "resolved":
    return {
      "iteration_decision": "no_further_iteration_needed",
      "iteration_needed": False,
      "iteration_reason": "Verifier marked the issue resolved.",
    }

  if (
    verifier_status == "partially_resolved"
    and severity <= _REALISM_ITERATION_LOW_SEVERITY_MAX
    and len(quarters) <= _REALISM_ITERATION_SMALL_QUARTER_COUNT_MAX
    and not next_levers
  ):
    return {
      "iteration_decision": "no_further_iteration_needed",
      "iteration_needed": False,
      "iteration_reason": (
        "Verifier marked the issue partially resolved, and the remaining gap is low-severity, "
        "localized, and has no prescribed next levers."
      ),
    }

  return {
    "iteration_decision": "continue_iteration",
    "iteration_needed": True,
    "iteration_reason": (
      "Verifier indicates the issue remains unresolved or still materially open enough to justify another pass."
    ),
  }


def _clone_issue_status_records(issue_status_records: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
  return [
    _normalize_issue_record_to_controller_truth(item)
    for item in (issue_status_records or [])
    if isinstance(item, dict)
  ]


def _controller_issue_effective_status(item: Optional[Dict[str, Any]]) -> str:
  record = item if isinstance(item, dict) else {}
  verifier_status = _normalize_realism_verifier_status(record.get("verifier_status"))
  if verifier_status == "resolved":
    return "resolved"
  return "open"


def _controller_issue_is_blocking(item: Optional[Dict[str, Any]]) -> bool:
  record = item if isinstance(item, dict) else {}
  return _controller_issue_effective_status(record) != "resolved"


def _issue_needs_iteration(item: Optional[Dict[str, Any]]) -> bool:
  record = item if isinstance(item, dict) else {}
  if isinstance(record.get("iteration_needed"), bool):
    return bool(record.get("iteration_needed"))
  return bool(_iteration_decision_from_issue_record(record).get("iteration_needed"))


def _normalize_issue_record_to_controller_truth(
  item: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  record = copy.deepcopy(item if isinstance(item, dict) else {})
  record["verifier_status"] = _normalize_realism_verifier_status(record.get("verifier_status"))
  iteration_decision = _iteration_decision_from_issue_record(record)
  record["status_source"] = "verifier_status"
  record["iteration_decision"] = str(iteration_decision.get("iteration_decision") or "").strip()
  record["iteration_needed"] = bool(iteration_decision.get("iteration_needed"))
  record["iteration_reason"] = str(iteration_decision.get("iteration_reason") or "").strip()
  record.pop("controller_status", None)
  record.pop("controller_blocking", None)
  record.pop("controller_resolution", None)
  record.pop("controller_close_reason", None)
  record.pop("status", None)
  record.pop("resolved_iteration", None)
  return record


def _build_issue_status_records_from_issue_list(
  *,
  current_issues: Optional[List[Dict[str, Any]]],
  iteration: int,
) -> List[Dict[str, Any]]:
  records_by_key: Dict[str, Dict[str, Any]] = {}
  order: List[str] = []
  for item in (current_issues or []):
    if not isinstance(item, dict):
      continue
    key = _issue_ledger_key(item)
    if not key or key in records_by_key:
      continue
    record = {
      "verifier_status": "not_resolved",
      "first_detected_iteration": int(iteration),
      "last_seen_iteration": int(iteration),
    }
    record = _merge_issue_identity_fields(record, item)
    if str(item.get("candidate_kind") or "").strip():
      record["candidate_kind"] = str(item.get("candidate_kind") or "").strip()
    records_by_key[key] = record
    order.append(key)

  return [
    _normalize_issue_record_to_controller_truth(records_by_key[key])
    for key in order
    if isinstance(records_by_key.get(key), dict)
  ]


def _issue_keys_from_status_records(
  issue_status_records: Optional[List[Dict[str, Any]]],
  *,
  status_filter: Optional[str] = None,
) -> List[str]:
  keys: List[str] = []
  for item in (issue_status_records or []):
    if not isinstance(item, dict):
      continue
    normalized = _normalize_issue_record_to_controller_truth(item)
    if status_filter:
      wanted = str(status_filter).strip().lower()
      if wanted == "open" and not _controller_issue_is_blocking(normalized):
        continue
      if wanted == "resolved" and _controller_issue_is_blocking(normalized):
        continue
      if wanted not in {"open", "resolved"} and _controller_issue_effective_status(normalized) != wanted:
        continue
    key = _issue_ledger_key(normalized)
    if key:
      keys.append(key)
  return keys


def _issue_keys_requiring_iteration(
  issue_status_records: Optional[List[Dict[str, Any]]],
) -> List[str]:
  keys: List[str] = []
  for item in (issue_status_records or []):
    if not isinstance(item, dict):
      continue
    normalized = _normalize_issue_record_to_controller_truth(item)
    if not _issue_needs_iteration(normalized):
      continue
    key = _issue_ledger_key(normalized)
    if key:
      keys.append(key)
  return keys
  
  
def _filter_issue_status_records(
  issue_status_records: Optional[List[Dict[str, Any]]],
  issue_keys: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
  normalized_records = [
    _normalize_issue_record_to_controller_truth(item)
    for item in (issue_status_records or [])
    if isinstance(item, dict)
  ]
  if not issue_keys:
    return normalized_records
  allowed = {str(item).strip() for item in issue_keys if str(item).strip()}
  return [
    copy.deepcopy(item)
    for item in normalized_records
    if _issue_ledger_key(item) in allowed
  ]


def _build_realism_planner_issue_state(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  issue_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
  filtered_records = _filter_issue_status_records(issue_status_records, issue_keys)
  planner_issue_records: List[Dict[str, Any]] = []
  for item in filtered_records:
    issue_code = str(item.get("issue_code") or "").strip()
    if not issue_code:
      continue
    planner_issue_records.append(
      {
        "issue_code": issue_code,
        "remaining_problem_quarters": _normalize_realism_remaining_quarters(
          item.get("remaining_problem_quarters")
        ),
        "remaining_issue_severity_score": _safe_int_in_range(
          item.get("remaining_issue_severity_score"),
          default=0,
          minimum=0,
          maximum=100,
        ),
        "next_required_lever_ids": _normalize_realism_lever_ids(
          item.get("next_required_lever_ids")
        ),
      }
    )
  return {
    "contract_version": "realism_planner_issue_state_v1",
    "issue_count": len(planner_issue_records),
    "issue_status_records": planner_issue_records,
  }


def _active_issue_codes_from_planner_issue_state(
  planner_issue_state: Optional[Dict[str, Any]],
) -> List[str]:
  codes: List[str] = []
  seen: Set[str] = set()
  for item in ((planner_issue_state or {}).get("issue_status_records") or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if not issue_code or issue_code in seen:
      continue
    seen.add(issue_code)
    codes.append(issue_code)
  return codes


def _build_controller_resolution_state_from_issue_ledger(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  iteration: int,
  verification_payload: Optional[Dict[str, Any]] = None,
  issue_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
  filtered_records = _filter_issue_status_records(issue_status_records, issue_keys)
  full_records = _clone_issue_status_records(_filter_issue_status_records(issue_status_records, None))
  detected_records = filtered_records if issue_keys else full_records
  detected_issues = [_core_issue_record(item) for item in detected_records]
  resolved_issues = [
    _core_issue_record(item)
    for item in filtered_records
    if not _controller_issue_is_blocking(item)
  ]
  remaining_issues = [
    _core_issue_record(item)
    for item in filtered_records
    if _controller_issue_is_blocking(item)
  ]
  tolerated_issues: List[Dict[str, Any]] = []
  iteration_pending_issues = [
    _core_issue_record(item)
    for item in filtered_records
    if _issue_needs_iteration(item)
  ]
  verification = (
    verification_payload.get("verification")
    if isinstance(verification_payload, dict) and isinstance(verification_payload.get("verification"), dict)
    else {}
  )
  status = "all_cleared" if not remaining_issues else "issues_remaining"
  return {
    "contract_version": "controller_resolution_state_v3",
    "owner": "controller",
    "source_of_truth": "issue_status_records.verifier_status",
    "status": status,
    "display_status": "all cleared" if not remaining_issues else "issues remaining",
    "all_cleared": not remaining_issues,
    "hard_cleared": not remaining_issues,
    "detected_issue_count": len(detected_issues),
    "remaining_issue_count": len(remaining_issues),
    "resolved_issue_count": len(resolved_issues),
    "tolerated_issue_count": len(tolerated_issues),
    "iteration_pending_issue_count": len(iteration_pending_issues),
    "detected_issues": detected_issues,
    "remaining_issues": remaining_issues,
    "resolved_issues": resolved_issues,
    "tolerated_issues": tolerated_issues,
    "iteration_pending_issues": iteration_pending_issues,
    "issue_status_records": _clone_issue_status_records(filtered_records),
    "last_review_iteration": int(iteration),
    "verification_summary": {
      "overall_assessment": str(verification.get("overall_assessment") or "").strip(),
      "executive_summary": str(verification.get("executive_summary") or "").strip(),
    },
  }


def _controller_state_issue_status_records(
  controller_resolution_state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  return _clone_issue_status_records(controller_state.get("issue_status_records"))


def _controller_state_issue_summaries(
  controller_resolution_state: Optional[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
  records = _controller_state_issue_status_records(controller_resolution_state)
  return {
    "detected_issues": [_core_issue_record(item) for item in records],
    "remaining_issues": [_core_issue_record(item) for item in records if _controller_issue_is_blocking(item)],
    "resolved_issues": [_core_issue_record(item) for item in records if not _controller_issue_is_blocking(item)],
  }


def _build_persisted_realism_memo_payload(
  *,
  controller_resolution_state: Optional[Dict[str, Any]],
  working_memo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  memo = working_memo if isinstance(working_memo, dict) else {}
  verification_summary = (
    memo.get("verification_summary")
    if isinstance(memo.get("verification_summary"), dict)
    else controller_state.get("verification_summary")
  )
  return {
    "contract_version": "realism_memo_storage_v3",
    "owner": "controller",
    "storage_mode": "non_canonical",
    "state_source": "planning_run_json.controller_resolution_state",
    "last_review_iteration": int(
      _safe_float(controller_state.get("last_review_iteration") or memo.get("last_review_iteration")) or 0
    ),
    "verification_summary": copy.deepcopy(verification_summary or {}),
  }


def _compact_issue_codes(items: Any) -> List[str]:
  codes: List[str] = []
  for item in (items or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if issue_code and issue_code not in codes:
      codes.append(issue_code)
  return codes


def _compact_realism_memo_for_trace(memo: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  memo_obj = memo if isinstance(memo, dict) else {}
  remaining_issues = [
    item for item in ((memo_obj.get("remaining_issues") or memo_obj.get("issues") or []))
    if isinstance(item, dict)
  ]
  resolved_issues = [item for item in (memo_obj.get("resolved_issues") or []) if isinstance(item, dict)]
  detected_issues = [
    item for item in ((memo_obj.get("detected_issues") or memo_obj.get("issues") or []))
    if isinstance(item, dict)
  ]
  return {
    "status": str(memo_obj.get("status") or "").strip(),
    "remaining_issue_count": len(remaining_issues),
    "resolved_issue_count": len(resolved_issues),
    "detected_issue_count": len(detected_issues) if detected_issues else len(remaining_issues),
    "remaining_issue_codes": _compact_issue_codes(remaining_issues),
    "resolved_issue_codes": _compact_issue_codes(resolved_issues),
    "detected_issue_codes": _compact_issue_codes(detected_issues if detected_issues else remaining_issues),
    "last_review_iteration": int(_safe_float(memo_obj.get("last_review_iteration")) or 0),
  }


def _compact_resolution_summary_for_trace(summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  summary_obj = summary if isinstance(summary, dict) else {}
  remaining = [item for item in (summary_obj.get("remaining_violations") or []) if isinstance(item, dict)]
  resolved = [item for item in (summary_obj.get("resolved_violations") or []) if isinstance(item, dict)]
  baseline = [item for item in (summary_obj.get("baseline_violations") or []) if isinstance(item, dict)]
  tolerated = [item for item in (summary_obj.get("tolerated_violations") or []) if isinstance(item, dict)]
  return {
    "status": str(summary_obj.get("status") or "").strip(),
    "all_cleared": bool(summary_obj.get("all_cleared")),
    "hard_cleared": bool(summary_obj.get("hard_cleared")),
    "remaining_issue_count": len(remaining),
    "resolved_issue_count": len(resolved),
    "tolerated_issue_count": len(tolerated),
    "baseline_issue_count": len(baseline),
    "remaining_issue_codes": _compact_issue_codes(remaining),
    "resolved_issue_codes": _compact_issue_codes(resolved),
    "tolerated_issue_codes": _compact_issue_codes(tolerated),
    "baseline_issue_codes": _compact_issue_codes(baseline),
  }


def _sanitize_realism_iteration_trace(
  iterations: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  sanitized: List[Dict[str, Any]] = []
  for item in (iterations or []):
    if not isinstance(item, dict):
      continue
    entry = copy.deepcopy(item)
    if isinstance(entry.get("memo_before"), dict):
      entry["memo_before"] = _compact_realism_memo_for_trace(entry.get("memo_before"))
    if isinstance(entry.get("memo_after"), dict):
      entry["memo_after"] = _compact_realism_memo_for_trace(entry.get("memo_after"))
    fresh_issue_candidates = []
    for candidate in (entry.get("fresh_issue_candidates") or []):
      if not isinstance(candidate, dict):
        continue
      candidate_payload = {
        "issue_code": str(candidate.get("issue_code") or "").strip().lower(),
        "issue": str(candidate.get("issue") or "").strip(),
        "candidate_kind": str(candidate.get("candidate_kind") or "").strip(),
      }
      if candidate_payload["issue_code"] or candidate_payload["issue"] or candidate_payload["candidate_kind"]:
        fresh_issue_candidates.append(candidate_payload)
    if "fresh_issue_candidates" in entry:
      entry["fresh_issue_candidates"] = fresh_issue_candidates
    sanitized.append(entry)
  return sanitized


def _build_resolution_summary_from_issue_ledger(
  *,
  before_memo: Optional[Dict[str, Any]],
  issue_status_records: Optional[List[Dict[str, Any]]],
  verification_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del before_memo
  controller_state = _build_controller_resolution_state_from_issue_ledger(
    issue_status_records=copy.deepcopy(issue_status_records),
    iteration=0,
    verification_payload=copy.deepcopy(verification_payload),
  )
  return {
    "status": str(controller_state.get("status") or "").strip(),
    "display_status": str(controller_state.get("display_status") or "").strip(),
    "baseline_violations": copy.deepcopy(controller_state.get("detected_issues") or []),
    "resolved_violations": copy.deepcopy(controller_state.get("resolved_issues") or []),
    "tolerated_violations": copy.deepcopy(controller_state.get("tolerated_issues") or []),
    "remaining_violations": copy.deepcopy(controller_state.get("remaining_issues") or []),
    "remaining_blocking_violations": copy.deepcopy(controller_state.get("remaining_issues") or []),
    "all_cleared": bool(controller_state.get("all_cleared")),
    "hard_cleared": bool(controller_state.get("hard_cleared")),
    "verification_executive_summary": str(
      ((controller_state.get("verification_summary") or {}) if isinstance(controller_state.get("verification_summary"), dict) else {}).get("executive_summary") or ""
    ).strip(),
  }


def _build_realism_memo_from_issue_ledger(
  *,
  before_memo: Optional[Dict[str, Any]],
  issue_status_records: Optional[List[Dict[str, Any]]],
  resolution_summary: Optional[Dict[str, Any]],
  iteration: int,
  verification_payload: Optional[Dict[str, Any]] = None,
  issue_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
  del before_memo
  controller_state = _build_controller_resolution_state_from_issue_ledger(
    issue_status_records=copy.deepcopy(issue_status_records),
    iteration=iteration,
    verification_payload=copy.deepcopy(verification_payload),
    issue_keys=copy.deepcopy(issue_keys),
  )
  remaining_issues = copy.deepcopy(controller_state.get("remaining_issues") or [])
  return {
    "owner": "controller",
    "status": "resolved" if not remaining_issues else "ready",
    "issues": copy.deepcopy(remaining_issues),
    "detected_issues": copy.deepcopy(controller_state.get("detected_issues") or []),
    "resolved_issues": copy.deepcopy(controller_state.get("resolved_issues") or []),
    "remaining_issues": copy.deepcopy(remaining_issues),
    "last_review_iteration": int(controller_state.get("last_review_iteration") or iteration),
    "verification_summary": copy.deepcopy(controller_state.get("verification_summary") or {}),
  }


def _apply_realism_verification_to_issue_status_records(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  verification_payload: Optional[Dict[str, Any]],
  iteration: int,
  allowed_issue_keys: Optional[List[str]] = None,
  allow_new_records: bool = True,
) -> List[Dict[str, Any]]:
  base_records = {
    _issue_ledger_key(item): _normalize_issue_record_to_controller_truth(item)
    for item in (issue_status_records or [])
    if isinstance(item, dict) and _issue_ledger_key(item)
  }
  verification = (
    verification_payload.get("verification")
    if isinstance(verification_payload, dict) and isinstance(verification_payload.get("verification"), dict)
    else {}
  )
  if not verification:
    return []

  allowed = {str(item).strip() for item in (allowed_issue_keys or []) if str(item).strip()}
  issue_results = [item for item in (verification.get("issue_results") or []) if isinstance(item, dict)]
  records_by_key: Dict[str, Dict[str, Any]] = {}
  order: List[str] = []
  for item in issue_results:
    code = str(item.get("issue_code") or "").strip().lower()
    issue = str(item.get("issue") or code).strip()
    key = _issue_ledger_key({"issue_code": code})
    if not key:
      continue
    if allowed and key not in allowed:
      continue
    existing = copy.deepcopy(base_records.get(key) or {})
    if not existing and not allow_new_records:
      continue
    verification_reason = str(item.get("verification_reason") or "").strip()
    verifier_resolution = _controller_resolution_from_verification_issue(item)
    if not existing:
      existing = {
        "issue": issue or code,
        "detail": "",
        "first_detected_iteration": int(iteration),
      }
    if key not in records_by_key:
      order.append(key)
    if code:
      existing["issue_code"] = code
    if issue:
      existing["issue"] = issue
    if str(item.get("detail") or "").strip():
      existing["detail"] = str(item.get("detail") or "").strip()
    if int(_safe_float(existing.get("first_detected_iteration")) or 0) <= 0:
      existing["first_detected_iteration"] = int(iteration)
    existing["last_seen_iteration"] = int(iteration)
    existing["verifier_status"] = str(verifier_resolution.get("verifier_status") or "").strip()
    existing["remaining_issue_materiality"] = str(
      verifier_resolution.get("remaining_issue_materiality") or ""
    ).strip()
    existing["remaining_issue_severity_score"] = int(
      verifier_resolution.get("remaining_issue_severity_score") or 0
    )
    existing["verification_reason"] = verification_reason
    existing["remaining_problem_quarters"] = copy.deepcopy(
      verifier_resolution.get("remaining_problem_quarters") or []
    )
    existing["next_required_lever_ids"] = copy.deepcopy(
      verifier_resolution.get("next_required_lever_ids") or []
    )
    existing["observed_improvement_summary"] = str(item.get("observed_improvement_summary") or "").strip()
    records_by_key[key] = existing

  out: List[Dict[str, Any]] = []
  for key in order:
    record = records_by_key.get(key)
    if isinstance(record, dict):
      out.append(_normalize_issue_record_to_controller_truth(record))
  return out


def _extract_open_verification_feedback(
  verification_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  verification = (
    verification_payload.get("verification")
    if isinstance(verification_payload, dict) and isinstance(verification_payload.get("verification"), dict)
    else {}
  )
  if not verification:
    return {}
  issue_results = [item for item in (verification.get("issue_results") or []) if isinstance(item, dict)]
  open_issue_results = [
    {
      "issue_code": str(item.get("issue_code") or "").strip(),
      "status": str(verifier_resolution.get("verifier_status") or "").strip(),
      "remaining_issue_materiality": str(
        verifier_resolution.get("remaining_issue_materiality") or ""
      ).strip(),
      "remaining_issue_severity_score": int(
        verifier_resolution.get("remaining_issue_severity_score") or 0
      ),
      "verification_reason": str(item.get("verification_reason") or "").strip(),
      "remaining_problem_quarters": copy.deepcopy(
        verifier_resolution.get("remaining_problem_quarters") or []
      ),
      "next_required_lever_ids": copy.deepcopy(
        verifier_resolution.get("next_required_lever_ids") or []
      ),
      "observed_improvement_summary": str(item.get("observed_improvement_summary") or "").strip(),
    }
    for item in issue_results
    for verifier_resolution in [_controller_resolution_from_verification_issue(item)]
    if str(verifier_resolution.get("verifier_status") or "").strip().lower() != "resolved"
  ]
  if not open_issue_results:
    return {}
  return {
    "overall_assessment": str(verification.get("overall_assessment") or "").strip(),
    "executive_summary": str(verification.get("executive_summary") or "").strip(),
    "open_issue_results": open_issue_results,
  }


def _persist_realism_loop_state(
  *,
  conn,
  draft_id: str,
  stage: str,
  status: str,
  controller_resolution_state: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  grid_application_summary: Optional[Dict[str, Any]],
  realism_memo_before_resolution: Optional[Dict[str, Any]],
  realism_resolution_decision: Optional[Dict[str, Any]],
  realism_resolution_plan: Optional[Dict[str, Any]],
  realism_resolution_result: Optional[Dict[str, Any]],
  realism_resolution_verification: Optional[Dict[str, Any]],
  realism_resolution_iterations: Optional[List[Dict[str, Any]]],
  resolution_summary: Optional[Dict[str, Any]],
  realism_memo_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  persisted_realism_memo = _build_persisted_realism_memo_payload(
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    working_memo=copy.deepcopy(realism_memo_json),
  )
  payload = _build_planning_run_payload(
    stage=stage,
    status=status,
    controller_resolution_state=copy.deepcopy(controller_resolution_state or {}),
    resolution_summary=copy.deepcopy(resolution_summary or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution or {}),
    realism_resolution_decision=copy.deepcopy(realism_resolution_decision or {}),
    realism_resolution_plan=copy.deepcopy(realism_resolution_plan or {}),
    realism_resolution_result=copy.deepcopy(realism_resolution_result or {}),
    realism_resolution_verification=copy.deepcopy(realism_resolution_verification or {}),
    realism_resolution_iterations=_sanitize_realism_iteration_trace(copy.deepcopy(realism_resolution_iterations or [])),
  )
  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    realism_memo_json=copy.deepcopy(persisted_realism_memo),
    planning_run_json=copy.deepcopy(payload),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
  )
  return payload


def _parse_responses_json_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
  try:
    parsed = json.loads(_parse_responses_text(data))
  except Exception:
    return None
  return parsed if isinstance(parsed, dict) else None


def _cash_strategy_review_schema(allowed_lever_ids: List[str]) -> Dict[str, Any]:
  return {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "recommendation_mode": {"type": "string", "enum": ["maintain", "adjust"]},
      "decision_trigger_type": {
        "type": "string",
        "enum": ["none", "stress", "surplus", "milestone", "mixed"],
      },
      "decision_trigger_summary": {"type": "string"},
      "alignment_assessment": {
        "type": "string",
        "enum": ["aligned", "underexpressed", "overexpressed", "misaligned"],
      },
      "executive_summary": {"type": "string"},
      "capital_posture_summary": {"type": "string"},
      "hold_cash_justification": {"type": "string"},
      "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
      "recommended_actions": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "action_id": {"type": "string"},
            "business_move": {"type": "string"},
            "why_now": {"type": "string"},
            "expected_visual_effect": {"type": "string"},
            "coordination_notes": {"type": "string"},
            "timing_start_q": {"type": "integer", "minimum": 1, "maximum": 20},
            "timing_end_q": {"type": "integer", "minimum": 1, "maximum": 20},
            "priority": {"type": "integer", "minimum": 1, "maximum": 10},
            "boldness": {"type": "string", "enum": ["light", "moderate", "strong"]},
            "lever_adjustments": {
              "type": "array",
              "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                  "lever_id": {"type": "string", "enum": allowed_lever_ids or [""]},
                  "section": {"type": "string"},
                  "direction": {"type": "string", "enum": ["increase", "decrease", "hold", "retime"]},
                  "value_mode": {"type": "string", "enum": ["exact", "band"]},
                  "exact_value": {"type": ["number", "null"]},
                  "min_value": {"type": ["number", "null"]},
                  "max_value": {"type": ["number", "null"]},
                  "timing_start_q": {"type": "integer", "minimum": 1, "maximum": 20},
                  "timing_end_q": {"type": "integer", "minimum": 1, "maximum": 20},
                  "business_reason": {"type": "string"},
                  "linked_action_effect": {"type": "string"},
                },
                "required": [
                  "lever_id",
                  "section",
                  "direction",
                  "value_mode",
                  "exact_value",
                  "min_value",
                  "max_value",
                  "timing_start_q",
                  "timing_end_q",
                  "business_reason",
                  "linked_action_effect",
                ],
              },
            },
          },
          "required": [
            "action_id",
            "business_move",
            "why_now",
            "expected_visual_effect",
            "coordination_notes",
            "timing_start_q",
            "timing_end_q",
            "priority",
            "boldness",
            "lever_adjustments",
          ],
        },
      },
    },
    "required": [
      "recommendation_mode",
      "decision_trigger_type",
      "decision_trigger_summary",
      "alignment_assessment",
      "executive_summary",
      "capital_posture_summary",
      "hold_cash_justification",
      "confidence",
      "recommended_actions",
    ],
  }


def _cash_strategy_review_failure_payload(
  *,
  selected_cash_strategy: str,
  prompt_file: str,
  status: str,
  detail: str = "",
) -> Dict[str, Any]:
  return {
    "contract_version": "cash_strategy_review_decision_v1",
    "status": status,
    "prompt_file": prompt_file,
    "selected_cash_strategy": str(selected_cash_strategy or "").strip(),
    "review_status": "not_completed",
    "detail": str(detail or "").strip(),
    "decision": {},
  }


def _realism_resolution_schema(allowed_lever_ids: List[str]) -> Dict[str, Any]:
  return {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "recommendation_mode": {"type": "string", "enum": ["maintain", "adjust"]},
      "resolution_assessment": {
        "type": "string",
        "enum": ["already_realistic", "issues_addressable", "partially_addressable"],
      },
      "executive_summary": {"type": "string"},
      "issue_resolution_summary": {"type": "string"},
      "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
      "issue_packets": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "issue_code": {"type": "string"},
            "issue_summary": {"type": "string"},
            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            "root_cause": {"type": "string"},
            "affected_quarters": {
              "type": "array",
              "minItems": 1,
              "items": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "evidence_points": {
              "type": "array",
              "minItems": 1,
              "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                  "quarter_index": {"type": "integer", "minimum": 1, "maximum": 20},
                  "metric_name": {"type": "string"},
                  "observed_value": {"type": "number"},
                  "problem_statement": {"type": "string"},
                },
                "required": ["quarter_index", "metric_name", "observed_value", "problem_statement"],
              },
            },
            "candidate_lever_ids": {
              "type": "array",
              "minItems": 1,
              "items": {"type": "string", "enum": allowed_lever_ids or [""]},
            },
            "required_fix_shape": {"type": "string"},
            "success_criteria": {
              "type": "array",
              "minItems": 1,
              "items": {"type": "string"},
            },
            "disallowed_fix_patterns": {
              "type": "array",
              "items": {"type": "string"},
            },
          },
          "required": [
            "issue_code",
            "issue_summary",
            "severity",
            "root_cause",
            "affected_quarters",
            "evidence_points",
            "candidate_lever_ids",
            "required_fix_shape",
            "success_criteria",
            "disallowed_fix_patterns",
          ],
        },
      },
      "recommended_actions": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "action_id": {"type": "string"},
            "issue_codes": {
              "type": "array",
              "minItems": 1,
              "items": {"type": "string"},
            },
            "business_move": {"type": "string"},
            "why_now": {"type": "string"},
            "expected_visual_effect": {"type": "string"},
            "coordination_notes": {"type": "string"},
            "target_quarters": {
              "type": "array",
              "minItems": 1,
              "items": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "priority": {"type": "integer", "minimum": 1, "maximum": 10},
            "boldness": {"type": "string", "enum": ["light", "moderate", "strong"]},
            "lever_adjustments": {
              "type": "array",
              "minItems": 1,
              "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                  "lever_id": {"type": "string", "enum": allowed_lever_ids or [""]},
                  "section": {"type": "string"},
                  "exact_value": {"type": "number"},
                  "quarter_index": {"type": "integer", "minimum": 1, "maximum": 20},
                  "business_reason": {"type": "string"},
                  "linked_action_effect": {"type": "string"},
                },
                "required": [
                  "lever_id",
                  "section",
                  "exact_value",
                  "quarter_index",
                  "business_reason",
                  "linked_action_effect",
                ],
              },
            },
          },
          "required": [
            "action_id",
            "issue_codes",
            "business_move",
            "why_now",
            "expected_visual_effect",
            "coordination_notes",
            "target_quarters",
            "priority",
            "boldness",
            "lever_adjustments",
          ],
        },
      },
    },
    "required": [
      "recommendation_mode",
      "resolution_assessment",
      "executive_summary",
      "issue_resolution_summary",
      "confidence",
      "issue_packets",
      "recommended_actions",
    ],
  }


def _realism_verification_schema(allowed_lever_ids: List[str]) -> Dict[str, Any]:
  return {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "overall_assessment": {
        "type": "string",
        "enum": ["all_resolved", "partially_resolved", "not_resolved"],
      },
      "executive_summary": {"type": "string"},
      "issue_results": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "issue_code": {"type": "string"},
            "status": {"type": "string", "enum": ["resolved", "partially_resolved", "not_resolved"]},
            "remaining_issue_materiality": {"type": "string", "enum": ["immaterial", "material"]},
            "remaining_issue_severity_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "verification_reason": {"type": "string"},
            "remaining_problem_quarters": {
              "type": "array",
              "items": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "next_required_lever_ids": {
              "type": "array",
              "items": {"type": "string", "enum": allowed_lever_ids or [""]},
            },
            "observed_improvement_summary": {"type": "string"},
          },
          "required": [
            "issue_code",
            "status",
            "remaining_issue_materiality",
            "remaining_issue_severity_score",
            "verification_reason",
            "remaining_problem_quarters",
            "next_required_lever_ids",
            "observed_improvement_summary",
          ],
        },
      },
    },
    "required": ["overall_assessment", "executive_summary", "issue_results"],
  }


def _realism_resolution_failure_payload(
  *,
  prompt_file: str,
  status: str,
  detail: str = "",
) -> Dict[str, Any]:
  return {
    "contract_version": "realism_resolution_decision_v1",
    "status": status,
    "prompt_file": prompt_file,
    "review_status": "not_completed",
    "detail": str(detail or "").strip(),
    "decision": {},
  }


def _active_issue_codes_from_memo(realism_memo_before_resolution: Optional[Dict[str, Any]]) -> List[str]:
  active_issues = _memo_issue_records(realism_memo_before_resolution, "remaining_issues", "issues")
  codes: List[str] = []
  seen = set()
  for item in active_issues:
    if not isinstance(item, dict):
      continue
    code = str(item.get("issue_code") or "").strip().lower()
    if not code or code in seen:
      continue
    seen.add(code)
    codes.append(code)
  return codes


def _build_issue_packets_from_issue_ledger(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  prior_decision_payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  prior_decision = prior_decision_payload if isinstance(prior_decision_payload, dict) else {}
  prior_packets = (
    prior_decision.get("decision", {}).get("issue_packets")
    if isinstance(prior_decision.get("decision"), dict)
    else []
  )
  prior_packet_map: Dict[str, Dict[str, Any]] = {}
  for item in prior_packets or []:
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if issue_code:
      prior_packet_map[issue_code] = copy.deepcopy(item)

  packets: List[Dict[str, Any]] = []
  seen: set[str] = set()
  for record in _clone_issue_status_records(issue_status_records):
    issue_code = str(record.get("issue_code") or "").strip().lower()
    if not issue_code or issue_code in seen:
      continue
    seen.add(issue_code)
    packet = copy.deepcopy(prior_packet_map.get(issue_code) or {})
    if not packet:
      packet = {
        "issue_code": issue_code,
        "issue": str(record.get("issue") or _canonical_issue_title(issue_code, "") or issue_code).strip(),
        "detail": str(record.get("detail") or "").strip(),
        "success_criteria": "",
        "why_it_matters": "",
      }
    if not str(packet.get("issue") or "").strip():
      packet["issue"] = str(record.get("issue") or _canonical_issue_title(issue_code, "") or issue_code).strip()
    if not str(packet.get("detail") or "").strip():
      packet["detail"] = str(record.get("detail") or "").strip()
    packets.append(packet)
  return packets


def _realism_resolution_decision_contract_error(
  *,
  parsed: Optional[Dict[str, Any]],
  active_issue_codes: Optional[List[str]],
) -> Optional[str]:
  decision = parsed if isinstance(parsed, dict) else {}
  codes = [str(code or "").strip().lower() for code in (active_issue_codes or []) if str(code or "").strip()]
  if not codes:
    return None
  recommendation_mode = str(decision.get("recommendation_mode") or "").strip().lower()
  issue_packets = [item for item in (decision.get("issue_packets") or []) if isinstance(item, dict)]
  recommended_actions = [item for item in (decision.get("recommended_actions") or []) if isinstance(item, dict)]
  packet_codes = {
    str(item.get("issue_code") or "").strip().lower()
    for item in issue_packets
    if str(item.get("issue_code") or "").strip()
  }
  missing_codes = [code for code in codes if code not in packet_codes]
  if recommendation_mode != "adjust":
    return (
      "Active realism issues were provided, so recommendation_mode must be 'adjust', "
      f"not {recommendation_mode or 'missing'}."
    )
  if not issue_packets:
    return "Active realism issues were provided, but issue_packets was empty."
  if missing_codes:
    return f"Issue packets were missing active issue codes: {', '.join(missing_codes)}."
  if not recommended_actions:
    return "Active realism issues were provided, but recommended_actions was empty."
  return None


def _realism_verification_failure_payload(
  *,
  prompt_file: str,
  status: str,
  detail: str = "",
) -> Dict[str, Any]:
  return {
    "contract_version": "realism_resolution_verification_v1",
    "status": status,
    "prompt_file": prompt_file,
    "verification_status": "not_completed",
    "detail": str(detail or "").strip(),
    "verification": {},
  }


def _run_realism_resolution_openai(
  *,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  planner_issue_state: Dict[str, Any],
  solved_model_input_json: Dict[str, Any],
  solved_finmo_json: Dict[str, Any],
  current_iteration: int = 1,
) -> Dict[str, Any]:
  prompt_file = "client_intake_and_finmo/prompts/realism_resolution/reviewer.md"
  planner_issue_state = (
    copy.deepcopy(planner_issue_state)
    if isinstance(planner_issue_state, dict)
    else {}
  )
  active_issue_codes = _active_issue_codes_from_planner_issue_state(planner_issue_state)
  if not active_issue_codes:
    return _realism_resolution_failure_payload(
      prompt_file=prompt_file,
      status="skipped_no_realism_issues",
      detail="No realism issues were active before the resolution pass.",
    )
  api_key = _openai_key()
  if not api_key:
    return _realism_resolution_failure_payload(
      prompt_file=prompt_file,
      status="skipped_missing_openai_key",
      detail="OPENAI_API_KEY is not configured.",
    )

  lever_catalog = _build_writable_lever_review_catalog(solved_model_input_json)
  allowed_lever_ids = [str(item.get("lever_id") or "").strip() for item in lever_catalog if str(item.get("lever_id") or "").strip()]
  if not allowed_lever_ids:
    return _realism_resolution_failure_payload(
      prompt_file=prompt_file,
      status="failed_missing_levers",
      detail="No writable lever ids were available for realism resolution.",
    )

  system_prompt = _load_realism_resolution_prompt()
  user_context = {
    "draft_id": str(draft_id or "").strip(),
    "current_iteration": int(current_iteration or 1),
    "business_name": str((business_facts or {}).get("name") or (business_facts or {}).get("business_name") or "").strip(),
    "ops_json": ops_json,
    "ops_milestones": _build_realism_milestone_context(
      ops_json=ops_json,
      solved_model_input_json=solved_model_input_json,
    ),
    "financials_json": financials_json,
    "planner_issue_state": planner_issue_state,
    "writable_lever_catalog": lever_catalog,
    "writable_lever_current_values": _solved_lever_value_map(solved_model_input_json),
    "solved_model_input_json": solved_model_input_json,
    "solved_finmo_quarter_rows": [
      row for row in ((solved_finmo_json or {}).get("quarter_rows") or []) if isinstance(row, dict)
    ],
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_context, ensure_ascii=False)}]},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "realism_resolution_decision",
        "schema": _realism_resolution_schema(allowed_lever_ids),
        "strict": True,
      }
    },
  }
  try:
    resp = _post_openai(
      url="https://api.openai.com/v1/responses",
      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
      payload=payload,
    )
  except Exception as exc:
    return _realism_resolution_failure_payload(
      prompt_file=prompt_file,
      status="failed_openai_request",
      detail=str(exc),
    )
  if resp.status_code >= 400:
    return _realism_resolution_failure_payload(
      prompt_file=prompt_file,
      status="failed_openai_status",
      detail=resp.text[:1200],
    )
  parsed = _parse_responses_json_dict(resp.json())
  if not isinstance(parsed, dict):
    return _realism_resolution_failure_payload(
      prompt_file=prompt_file,
      status="failed_parse",
      detail="Unable to parse realism resolution JSON.",
    )
  contract_error = _realism_resolution_decision_contract_error(
    parsed=parsed,
    active_issue_codes=active_issue_codes,
  )
  if contract_error:
    retry_payload = copy.deepcopy(payload)
    retry_payload["input"] = list(retry_payload.get("input") or []) + [
      {
        "role": "user",
        "content": [
          {
            "type": "input_text",
            "text": json.dumps(
              {
                "repair_contract_violation": contract_error,
                "required_active_issue_codes": active_issue_codes,
                "instruction": (
                  "You must return recommendation_mode='adjust', one issue_packet for each active issue code, "
                  "and at least one recommended_action because active realism issues are still open in this pass."
                ),
              },
              ensure_ascii=False,
            ),
          }
        ],
      }
    ]
    try:
      retry_resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload=retry_payload,
      )
    except Exception as exc:
      return _realism_resolution_failure_payload(
        prompt_file=prompt_file,
        status="failed_contract_retry_request",
        detail=f"{contract_error} Retry error: {exc}",
      )
    if retry_resp.status_code >= 400:
      return _realism_resolution_failure_payload(
        prompt_file=prompt_file,
        status="failed_contract_retry_status",
        detail=f"{contract_error} Retry status body: {retry_resp.text[:1200]}",
      )
    parsed_retry = _parse_responses_json_dict(retry_resp.json())
    if not isinstance(parsed_retry, dict):
      return _realism_resolution_failure_payload(
        prompt_file=prompt_file,
        status="failed_contract_retry_parse",
        detail=f"{contract_error} Retry parse failed.",
      )
    retry_contract_error = _realism_resolution_decision_contract_error(
      parsed=parsed_retry,
      active_issue_codes=active_issue_codes,
    )
    if retry_contract_error:
      return _realism_resolution_failure_payload(
        prompt_file=prompt_file,
        status="failed_invalid_repair_contract",
        detail=retry_contract_error,
      )
    parsed = parsed_retry
  return {
    "contract_version": "realism_resolution_decision_v1",
    "status": "completed",
    "prompt_file": prompt_file,
    "review_status": "completed",
    "detail": "",
    "decision": parsed,
  }


def _run_realism_verification_openai(
  *,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  realism_memo_before_resolution: Dict[str, Any],
  realism_resolution_decision: Dict[str, Any],
  realism_resolution_plan: Dict[str, Any],
  realism_resolution_result: Dict[str, Any],
  updated_model_input_json: Dict[str, Any],
  updated_finmo_json: Dict[str, Any],
) -> Dict[str, Any]:
  prompt_file = "client_intake_and_finmo/prompts/realism_resolution/verifier.md"
  api_key = _openai_key()
  if not api_key:
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="skipped_missing_openai_key",
      detail="OPENAI_API_KEY is not configured.",
    )

  decision_payload = (
    realism_resolution_decision.get("decision")
    if isinstance(realism_resolution_decision.get("decision"), dict)
    else {}
  )
  issue_packets = [item for item in (decision_payload.get("issue_packets") or []) if isinstance(item, dict)]
  if not issue_packets:
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="failed_missing_issue_packets",
      detail="No issue packets were available for realism verification.",
    )

  lever_catalog = _build_writable_lever_review_catalog(updated_model_input_json)
  allowed_lever_ids = [str(item.get("lever_id") or "").strip() for item in lever_catalog if str(item.get("lever_id") or "").strip()]
  if not allowed_lever_ids:
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="failed_missing_levers",
      detail="No writable lever ids were available for realism verification.",
    )

  try:
    verify_prompt = (_REALISM_RESOLUTION_PROMPTS_DIR / "verifier.md").read_text(encoding="utf-8").strip()
  except Exception as exc:
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="failed_load_prompt",
      detail=str(exc),
    )

  user_context = {
    "draft_id": str(draft_id or "").strip(),
    "business_name": str((business_facts or {}).get("name") or (business_facts or {}).get("business_name") or "").strip(),
    "ops_milestones": _build_realism_milestone_context(
      ops_json=ops_json,
      solved_model_input_json=updated_model_input_json,
    ),
    "realism_memo_before_resolution": realism_memo_before_resolution,
    "issue_packets": issue_packets,
    "realism_resolution_plan": realism_resolution_plan,
    "applied_updates": [
      item for item in ((realism_resolution_result or {}).get("applied_updates") or []) if isinstance(item, dict)
    ],
    "updated_model_input_json": updated_model_input_json,
    "updated_finmo_quarter_rows": [
      row for row in ((updated_finmo_json or {}).get("quarter_rows") or []) if isinstance(row, dict)
    ],
    "writable_lever_catalog": lever_catalog,
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": [{"type": "input_text", "text": verify_prompt}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_context, ensure_ascii=False)}]},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "realism_resolution_verification",
        "schema": _realism_verification_schema(allowed_lever_ids),
        "strict": True,
      }
    },
  }
  try:
    resp = _post_openai(
      url="https://api.openai.com/v1/responses",
      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
      payload=payload,
    )
  except Exception as exc:
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="failed_openai_request",
      detail=str(exc),
    )
  if resp.status_code >= 400:
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="failed_openai_status",
      detail=resp.text[:1200],
    )
  parsed = _parse_responses_json_dict(resp.json())
  if not isinstance(parsed, dict):
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="failed_parse",
      detail="Unable to parse realism verification JSON.",
    )
  return {
    "contract_version": "realism_resolution_verification_v1",
    "status": "completed",
    "prompt_file": prompt_file,
    "verification_status": "completed",
    "detail": "",
    "verification": parsed,
  }


def _run_cash_strategy_review_openai(
  *,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  first_pass_handoff: Dict[str, Any],
  cash_strategy_review_context: Dict[str, Any],
  solved_model_input_json: Dict[str, Any],
  solved_finmo_json: Dict[str, Any],
) -> Dict[str, Any]:
  prompt_file = "client_intake_and_finmo/prompts/cash_strategy_review/reviewer.md"
  selected_cash_strategy = str((financials_json or {}).get("cash_strategy") or "").strip()
  if not selected_cash_strategy:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy="",
      prompt_file=prompt_file,
      status="skipped_no_cash_strategy",
      detail="No cash strategy was selected for this draft.",
    )
  api_key = _openai_key()
  if not api_key:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="skipped_missing_openai_key",
      detail="OPENAI_API_KEY is not configured.",
    )

  allowed_lever_ids = [
    str(item or "").strip()
    for item in ((cash_strategy_review_context or {}).get("writable_lever_catalog", {}) or {}).get("lever_ids", [])
    if str(item or "").strip()
  ]
  if not allowed_lever_ids:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_missing_levers",
      detail="No writable lever ids were available for cash strategy review.",
    )

  system_prompt = _load_cash_strategy_review_prompt()
  user_context = {
    "draft_id": str(draft_id or "").strip(),
    "business_name": str((business_facts or {}).get("name") or (business_facts or {}).get("business_name") or "").strip(),
    "selected_cash_strategy": selected_cash_strategy,
    "first_pass_handoff": first_pass_handoff,
    "cash_strategy_review_context": cash_strategy_review_context,
    "solved_model_input_json": solved_model_input_json,
    "solved_finmo_quarter_rows": [
      row for row in ((solved_finmo_json or {}).get("quarter_rows") or []) if isinstance(row, dict)
    ],
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_context, ensure_ascii=False)}]},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "cash_strategy_review_decision",
        "schema": _cash_strategy_review_schema(allowed_lever_ids),
        "strict": True,
      }
    },
  }
  try:
    resp = _post_openai(
      url="https://api.openai.com/v1/responses",
      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
      payload=payload,
    )
  except Exception as exc:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_openai_request",
      detail=str(exc),
    )
  if resp.status_code >= 400:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_openai_status",
      detail=resp.text[:1200],
    )
  parsed = _parse_responses_json_dict(resp.json())
  if not isinstance(parsed, dict):
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_parse",
      detail="Unable to parse cash strategy review JSON.",
    )
  return {
    "contract_version": "cash_strategy_review_decision_v1",
    "status": "completed",
    "prompt_file": prompt_file,
    "selected_cash_strategy": selected_cash_strategy,
    "review_status": "completed",
    "detail": "",
    "decision": parsed,
  }


def _quarter_count_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> int:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  periods = [item for item in (model_input.get("periods") or []) if isinstance(item, dict)]
  return max(1, len(periods)) if periods else 20


def _normalized_quarter_window(start_q: Any, end_q: Any, *, quarter_count: int) -> Tuple[int, int]:
  start = int(_safe_float(start_q) or 1)
  end = int(_safe_float(end_q) or start)
  start = max(1, min(int(quarter_count or 1), start))
  end = max(start, min(int(quarter_count or 1), end))
  return start, end


def _solved_lever_value_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, List[float]]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  lever_map: Dict[str, List[float]] = {}

  for row in [item for item in (sections.get("revenue") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    if lever_id:
      lever_map[lever_id] = [float(_safe_float(value) or 0.0) for value in (row.get("values") or [])]
  for section_name in ("expenses", "balance_sheet"):
    for row in [item for item in (sections.get(section_name) or []) if isinstance(item, dict)]:
      lever_id = str(row.get("lever_id") or "").strip()
      if lever_id:
        lever_map[lever_id] = [float(_safe_float(value) or 0.0) for value in (row.get("values") or [])]
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    if lever_id:
      lever_map[lever_id] = [float(_safe_float(value) or 0.0) for value in (row.get("values") or [])]
  return lever_map


def _window_values(values: List[float], *, start_q: int, end_q: int) -> List[float]:
  if not values:
    return []
  start_idx = max(0, int(start_q) - 1)
  end_idx = max(start_idx, int(end_q) - 1)
  return [float(_safe_float(item) or 0.0) for item in values[start_idx:end_idx + 1]]


def _baseline_window_summary(values: List[float], *, start_q: int, end_q: int) -> Dict[str, Any]:
  window = _window_values(values, start_q=start_q, end_q=end_q)
  if not window:
    return {
      "quarter_start": start_q,
      "quarter_end": end_q,
      "value_start": 0.0,
      "value_end": 0.0,
      "value_min": 0.0,
      "value_max": 0.0,
    }
  return {
    "quarter_start": start_q,
    "quarter_end": end_q,
    "value_start": window[0],
    "value_end": window[-1],
    "value_min": min(window),
    "value_max": max(window),
  }


def _translate_cash_strategy_adjustment(
  *,
  adjustment: Dict[str, Any],
  baseline_map: Dict[str, List[float]],
  quarter_count: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
  lever_id = str(adjustment.get("lever_id") or "").strip()
  if not lever_id:
    return None, "missing lever_id"
  baseline_values = baseline_map.get(lever_id)
  if not baseline_values:
    return None, f"unknown lever_id {lever_id}"

  start_q, end_q = _normalized_quarter_window(
    adjustment.get("timing_start_q"),
    adjustment.get("timing_end_q"),
    quarter_count=quarter_count,
  )
  value_mode = str(adjustment.get("value_mode") or "").strip().lower()
  direction = str(adjustment.get("direction") or "").strip().lower()
  translated: Dict[str, Any] = {
    "lever_id": lever_id,
    "section": str(adjustment.get("section") or "").strip(),
    "direction": direction,
    "control_mode": value_mode,
    "timing_start_q": start_q,
    "timing_end_q": end_q,
    "baseline_window": _baseline_window_summary(baseline_values, start_q=start_q, end_q=end_q),
    "business_reason": str(adjustment.get("business_reason") or "").strip(),
    "linked_action_effect": str(adjustment.get("linked_action_effect") or "").strip(),
  }

  if value_mode == "exact":
    exact_value = _safe_float(adjustment.get("exact_value"))
    if exact_value is None:
      return None, f"{lever_id} exact mode missing exact_value"
    translated["exact_value"] = float(exact_value)
    translated["min_value"] = None
    translated["max_value"] = None
    return translated, None

  if value_mode == "band":
    min_value = _safe_float(adjustment.get("min_value"))
    max_value = _safe_float(adjustment.get("max_value"))
    if min_value is None or max_value is None:
      return None, f"{lever_id} band mode missing min_value or max_value"
    low = float(min(min_value, max_value))
    high = float(max(min_value, max_value))
    translated["exact_value"] = None
    translated["min_value"] = low
    translated["max_value"] = high
    return translated, None

  return None, f"{lever_id} has unsupported value_mode {value_mode}"


def _build_cash_strategy_second_pass_plan(
  *,
  review_decision_payload: Optional[Dict[str, Any]],
  solved_model_input_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  review_payload = review_decision_payload if isinstance(review_decision_payload, dict) else {}
  selected_cash_strategy = str((financials_json or {}).get("cash_strategy") or review_payload.get("selected_cash_strategy") or "").strip()
  review_status = str(review_payload.get("status") or "").strip()
  prompt_file = str(review_payload.get("prompt_file") or "").strip()
  if review_status != "completed":
    return {
      "contract_version": "cash_strategy_second_pass_plan_v1",
      "status": "skipped_review_not_completed",
      "selected_cash_strategy": selected_cash_strategy,
      "prompt_file": prompt_file,
      "review_status": review_status,
      "default_unspecified_lever_policy": {},
      "translated_action_packages": [],
      "translation_warnings": [],
      "next_step": "wait_for_completed_cash_strategy_review",
    }

  decision = review_payload.get("decision") if isinstance(review_payload.get("decision"), dict) else {}
  recommendation_mode = str(decision.get("recommendation_mode") or "").strip().lower()
  alignment_assessment = str(decision.get("alignment_assessment") or "").strip()
  quarter_count = _quarter_count_from_model_input(solved_model_input_json)
  baseline_map = _solved_lever_value_map(solved_model_input_json)
  warnings: List[str] = []
  translated_packages: List[Dict[str, Any]] = []
  touched_lever_ids: List[str] = []

  for action in [item for item in (decision.get("recommended_actions") or []) if isinstance(item, dict)]:
    translated_controls: List[Dict[str, Any]] = []
    for adjustment in [item for item in (action.get("lever_adjustments") or []) if isinstance(item, dict)]:
      translated, warning = _translate_cash_strategy_adjustment(
        adjustment=adjustment,
        baseline_map=baseline_map,
        quarter_count=quarter_count,
      )
      if warning:
        warnings.append(f"{str(action.get('action_id') or '').strip() or 'action'}: {warning}")
        continue
      if translated:
        translated_controls.append(translated)
        lever_id = str(translated.get("lever_id") or "").strip()
        if lever_id and lever_id not in touched_lever_ids:
          touched_lever_ids.append(lever_id)
    translated_packages.append(
      {
        "action_id": str(action.get("action_id") or "").strip(),
        "business_move": str(action.get("business_move") or "").strip(),
        "why_now": str(action.get("why_now") or "").strip(),
        "expected_visual_effect": str(action.get("expected_visual_effect") or "").strip(),
        "coordination_notes": str(action.get("coordination_notes") or "").strip(),
        "timing_start_q": int(_safe_float(action.get("timing_start_q")) or 1),
        "timing_end_q": int(_safe_float(action.get("timing_end_q")) or max(1, int(_safe_float(action.get("timing_start_q")) or 1))),
        "priority": int(_safe_float(action.get("priority")) or 1),
        "boldness": str(action.get("boldness") or "").strip(),
        "translated_controls": translated_controls,
      }
    )

  status = "ready"
  next_step = "ready_for_second_pass_solver"
  if recommendation_mode == "maintain":
    status = "ready_maintain_first_pass"
    next_step = "no_second_pass_adjustment_required"
  elif recommendation_mode == "adjust" and not touched_lever_ids:
    status = "ready_no_valid_translated_controls"
    next_step = "review_translation_warnings_before_second_pass_solver"

  return {
    "contract_version": "cash_strategy_second_pass_plan_v1",
    "status": status,
    "selected_cash_strategy": selected_cash_strategy,
    "prompt_file": prompt_file,
    "review_status": review_status,
    "recommendation_mode": recommendation_mode,
    "decision_trigger_type": str(decision.get("decision_trigger_type") or "").strip(),
    "decision_trigger_summary": str(decision.get("decision_trigger_summary") or "").strip(),
    "alignment_assessment": alignment_assessment,
    "executive_summary": str(decision.get("executive_summary") or "").strip(),
    "capital_posture_summary": str(decision.get("capital_posture_summary") or "").strip(),
    "hold_cash_justification": str(decision.get("hold_cash_justification") or "").strip(),
    "confidence": str(decision.get("confidence") or "").strip(),
    "baseline_source": "first_pass_solved_model",
    "default_unspecified_lever_policy": {
      "mode": "lock_to_first_pass_solved_values",
      "scope": "all_unspecified_writable_levers",
      "rationale": "Second pass should only move levers explicitly prescribed by the cash strategy review.",
    },
    "translated_action_packages": translated_packages,
    "translated_control_count": sum(len(item.get("translated_controls") or []) for item in translated_packages),
    "touched_lever_ids": touched_lever_ids,
    "translation_warnings": warnings,
    "next_step": next_step,
  }


def _build_realism_resolution_plan(
  *,
  review_decision_payload: Optional[Dict[str, Any]],
  solved_model_input_json: Optional[Dict[str, Any]],
  solved_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  del solved_finmo_json
  review_payload = review_decision_payload if isinstance(review_decision_payload, dict) else {}
  review_status = str(review_payload.get("status") or "").strip()
  prompt_file = str(review_payload.get("prompt_file") or "").strip()
  if review_status != "completed":
    return {
      "contract_version": "realism_resolution_plan_v1",
      "status": "skipped_review_not_completed",
      "prompt_file": prompt_file,
      "review_status": review_status,
      "default_unspecified_lever_policy": {},
      "translated_action_packages": [],
      "translation_warnings": [],
      "next_step": "wait_for_completed_realism_resolution_review",
    }

  decision = review_payload.get("decision") if isinstance(review_payload.get("decision"), dict) else {}
  recommendation_mode = str(decision.get("recommendation_mode") or "").strip().lower()
  resolution_assessment = str(decision.get("resolution_assessment") or "").strip()
  issue_packets = [item for item in (decision.get("issue_packets") or []) if isinstance(item, dict)]
  issue_packet_map = {
    str(item.get("issue_code") or "").strip().lower(): copy.deepcopy(item)
    for item in issue_packets
    if str(item.get("issue_code") or "").strip()
  }
  quarter_count = _quarter_count_from_model_input(solved_model_input_json)
  baseline_map = _solved_lever_value_map(solved_model_input_json)
  warnings: List[str] = []
  translated_packages: List[Dict[str, Any]] = []
  touched_lever_ids: List[str] = []

  for action in [item for item in (decision.get("recommended_actions") or []) if isinstance(item, dict)]:
    translated_updates: List[Dict[str, Any]] = []
    action_quarters: List[int] = []
    action_issue_codes = [
      str(item or "").strip().lower()
      for item in (action.get("issue_codes") or [])
      if str(item or "").strip()
    ]
    for adjustment in [item for item in (action.get("lever_adjustments") or []) if isinstance(item, dict)]:
      lever_id = str(adjustment.get("lever_id") or "").strip()
      if not lever_id:
        warnings.append(f"{str(action.get('action_id') or '').strip() or 'action'}: missing lever_id")
        continue
      baseline_values = baseline_map.get(lever_id)
      if not baseline_values:
        warnings.append(f"{str(action.get('action_id') or '').strip() or 'action'}: unknown lever_id {lever_id}")
        continue
      quarter_index = int(_safe_float(adjustment.get("quarter_index")) or 0)
      if quarter_index < 1 or quarter_index > quarter_count:
        warnings.append(f"{str(action.get('action_id') or '').strip() or 'action'}: invalid quarter_index for {lever_id}")
        continue
      exact_value = _safe_float(adjustment.get("exact_value"))
      if exact_value is None:
        warnings.append(f"{str(action.get('action_id') or '').strip() or 'action'}: missing exact_value for {lever_id}")
        continue
      baseline_value = float(_safe_float(baseline_values[quarter_index - 1]) or 0.0)
      translated_updates.append(
        {
          "lever_id": lever_id,
          "quarter_index": quarter_index,
          "exact_value": float(exact_value),
          "baseline_value": baseline_value,
          "issue_codes": action_issue_codes,
          "business_reason": str(adjustment.get("business_reason") or "").strip(),
          "linked_action_effect": str(adjustment.get("linked_action_effect") or "").strip(),
        }
      )
      if lever_id not in touched_lever_ids:
        touched_lever_ids.append(lever_id)
      action_quarters.append(quarter_index)
    action_quarters = sorted({quarter for quarter in action_quarters if quarter > 0})
    translated_packages.append(
      {
        "action_id": str(action.get("action_id") or "").strip(),
        "issue_codes": action_issue_codes,
        "business_move": str(action.get("business_move") or "").strip(),
        "why_now": str(action.get("why_now") or "").strip(),
        "expected_visual_effect": str(action.get("expected_visual_effect") or "").strip(),
        "coordination_notes": str(action.get("coordination_notes") or "").strip(),
        "target_quarters": sorted({int(_safe_float(q) or 0) for q in (action.get("target_quarters") or []) if int(_safe_float(q) or 0) >= 1}),
        "quarter_indices": action_quarters,
        "timing_start_q": action_quarters[0] if action_quarters else 1,
        "timing_end_q": action_quarters[-1] if action_quarters else 1,
        "priority": int(_safe_float(action.get("priority")) or 1),
        "boldness": str(action.get("boldness") or "").strip(),
        "issue_packets": [copy.deepcopy(issue_packet_map.get(code) or {"issue_code": code}) for code in action_issue_codes],
        "translated_updates": translated_updates,
      }
    )

  status = "ready"
  next_step = "ready_for_realism_resolution_application"
  if recommendation_mode == "maintain":
    status = "ready_maintain_first_pass"
    next_step = "no_realism_resolution_adjustment_required"
  elif recommendation_mode == "adjust" and not touched_lever_ids:
    status = "ready_no_valid_translated_updates"
    next_step = "review_translation_warnings_before_realism_resolution_application"

  return {
    "contract_version": "realism_resolution_plan_v1",
    "status": status,
    "prompt_file": prompt_file,
    "review_status": review_status,
    "recommendation_mode": recommendation_mode,
    "resolution_assessment": resolution_assessment,
    "executive_summary": str(decision.get("executive_summary") or "").strip(),
    "issue_resolution_summary": str(decision.get("issue_resolution_summary") or "").strip(),
    "confidence": str(decision.get("confidence") or "").strip(),
    "issue_packets": issue_packets,
    "baseline_source": "first_pass_solved_model",
    "default_unspecified_lever_policy": {
      "mode": "lock_to_first_pass_solved_values",
      "scope": "all_unspecified_writable_levers",
      "rationale": "Realism resolution should only rewrite the quarter-specific levers explicitly prescribed by the realism resolution review.",
    },
    "translated_action_packages": translated_packages,
    "translated_update_count": sum(len(item.get("translated_updates") or []) for item in translated_packages),
    "touched_lever_ids": touched_lever_ids,
    "translation_warnings": warnings,
    "next_step": next_step,
  }


def _clamp_value(value: float, *, minimum: Optional[float], maximum: Optional[float]) -> float:
  next_value = float(value)
  if minimum is not None:
    next_value = max(next_value, float(minimum))
  if maximum is not None:
    next_value = min(next_value, float(maximum))
  return float(next_value)


def _preferred_exact_from_band_control(control: Dict[str, Any], *, boldness: str) -> Optional[float]:
  minimum = _safe_float(control.get("min_value"))
  maximum = _safe_float(control.get("max_value"))
  if minimum is None and maximum is None:
    return None
  baseline_window = control.get("baseline_window") if isinstance(control.get("baseline_window"), dict) else {}
  baseline_value = _safe_float(baseline_window.get("value_end"))
  if baseline_value is None:
    baseline_value = _safe_float(baseline_window.get("value_start"))
  if baseline_value is None:
    baseline_value = 0.0
  direction = str(control.get("direction") or "").strip().lower()
  boldness_norm = str(boldness or "").strip().lower()

  if direction == "increase":
    if maximum is None:
      return minimum
    edge = float(maximum)
    if boldness_norm == "light":
      return float((baseline_value + edge) / 2.0)
    if boldness_norm == "moderate":
      return float(baseline_value + 0.75 * (edge - baseline_value))
    return edge

  if direction == "decrease":
    if minimum is None:
      return maximum
    edge = float(minimum)
    if boldness_norm == "light":
      return float((baseline_value + edge) / 2.0)
    if boldness_norm == "moderate":
      return float(baseline_value + 0.75 * (edge - baseline_value))
    return edge

  if direction == "hold":
    return _clamp_value(float(baseline_value), minimum=minimum, maximum=maximum)

  if direction == "retime":
    return _clamp_value(float(baseline_value), minimum=minimum, maximum=maximum)

  candidate = baseline_value
  if minimum is not None and maximum is not None:
    candidate = (float(minimum) + float(maximum)) / 2.0
  elif minimum is not None:
    candidate = float(minimum)
  elif maximum is not None:
    candidate = float(maximum)
  return float(candidate)


def _apply_followup_exact_updates(
  *,
  review_plan: Optional[Dict[str, Any]],
  current_model_input_json: Optional[Dict[str, Any]],
  contract_version: str,
) -> Dict[str, Any]:
  plan = review_plan if isinstance(review_plan, dict) else {}
  plan_status = str(plan.get("status") or "").strip()
  if plan_status == "ready_maintain_first_pass":
    return {
      "contract_version": contract_version,
      "status": "skipped_maintain_first_pass",
      "final_model_source": "current_model",
      "applied_update_count": 0,
      "applied_updates": [],
      "warnings": [],
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": {},
    }
  if plan_status != "ready":
    return {
      "contract_version": contract_version,
      "status": "skipped_not_ready",
      "final_model_source": "current_model",
      "applied_update_count": 0,
      "applied_updates": [],
      "warnings": [str(item).strip() for item in (plan.get("translation_warnings") or []) if str(item).strip()],
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": {},
    }

  try:
    from client_intake_and_finmo.quarter_grid import apply_exact_lever_updates_to_model_input  # type: ignore
  except Exception:
    from quarter_grid import apply_exact_lever_updates_to_model_input  # type: ignore
  try:
    from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore
  except Exception:
    from finmo_bridge import build_python_finmo_json  # type: ignore

  warnings = [str(item).strip() for item in (plan.get("translation_warnings") or []) if str(item).strip()]
  baseline_map = _solved_lever_value_map(current_model_input_json if isinstance(current_model_input_json, dict) else {})
  applied_updates: List[Dict[str, Any]] = []
  for action in [item for item in (plan.get("translated_action_packages") or []) if isinstance(item, dict)]:
    translated_updates = [item for item in (action.get("translated_updates") or []) if isinstance(item, dict)]
    translated_controls = [item for item in (action.get("translated_controls") or []) if isinstance(item, dict)]

    for update in translated_updates:
      lever_id = str(update.get("lever_id") or "").strip()
      quarter_index = int(_safe_float(update.get("quarter_index")) or 0)
      exact_value = _safe_float(update.get("exact_value"))
      if not lever_id or quarter_index < 1 or exact_value is None:
        warnings.append(f"{str(action.get('action_id') or '').strip() or 'action'}: invalid exact update")
        continue
      applied_updates.append(
        {
          "action_id": str(action.get("action_id") or "").strip(),
          "issue_codes": [
            str(item or "").strip().lower()
            for item in (update.get("issue_codes") or action.get("issue_codes") or [])
            if str(item or "").strip()
          ],
          "lever_id": lever_id,
          "quarter_index": quarter_index,
          "exact_value": float(exact_value),
          "baseline_value": _safe_float(update.get("baseline_value")),
          "business_reason": str(update.get("business_reason") or "").strip(),
          "linked_action_effect": str(update.get("linked_action_effect") or "").strip(),
          "boldness": str(action.get("boldness") or "").strip(),
        }
      )

    for control in translated_controls:
      lever_id = str(control.get("lever_id") or "").strip()
      start_q = int(_safe_float(control.get("timing_start_q")) or 0)
      end_q = int(_safe_float(control.get("timing_end_q")) or start_q)
      if not lever_id or start_q < 1 or end_q < start_q:
        warnings.append(f"{str(action.get('action_id') or '').strip() or 'action'}: invalid control timing")
        continue
      baseline_values = baseline_map.get(lever_id) or []
      for quarter_index in range(start_q, end_q + 1):
        quarter_baseline = float(_safe_float(baseline_values[quarter_index - 1]) or 0.0) if quarter_index - 1 < len(baseline_values) else 0.0
        control_mode = str(control.get("control_mode") or "").strip().lower()
        if control_mode == "exact":
          exact_value = _safe_float(control.get("exact_value"))
        else:
          exact_value = _preferred_exact_from_band_control(
            {
              **control,
              "baseline_window": {
                "value_start": quarter_baseline,
                "value_end": quarter_baseline,
              },
            },
            boldness=str(action.get("boldness") or "").strip(),
          )
        if exact_value is None:
          warnings.append(f"{str(action.get('action_id') or '').strip() or 'action'}: could not materialize control for {lever_id} Q{quarter_index}")
          continue
        applied_updates.append(
          {
            "action_id": str(action.get("action_id") or "").strip(),
            "issue_codes": [
              str(item or "").strip().lower()
              for item in (action.get("issue_codes") or [])
              if str(item or "").strip()
            ],
            "lever_id": lever_id,
            "quarter_index": quarter_index,
            "exact_value": float(exact_value),
            "baseline_value": quarter_baseline,
            "business_reason": str(control.get("business_reason") or action.get("why_now") or "").strip(),
            "linked_action_effect": str(control.get("linked_action_effect") or action.get("expected_visual_effect") or "").strip(),
            "boldness": str(action.get("boldness") or "").strip(),
          }
        )

  if not applied_updates:
    return {
      "contract_version": contract_version,
      "status": "skipped_no_updates",
      "final_model_source": "current_model",
      "applied_update_count": 0,
      "applied_updates": [],
      "warnings": warnings,
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": {},
    }

  updated_model_input_json = apply_exact_lever_updates_to_model_input(
    model_input_json=current_model_input_json if isinstance(current_model_input_json, dict) else {},
    exact_updates=applied_updates,
  )
  updated_finmo_json = build_python_finmo_json(model_input_json=updated_model_input_json)
  return {
    "contract_version": contract_version,
    "status": "completed",
    "final_model_source": "review_applied",
    "applied_update_count": len(applied_updates),
    "applied_control_count": len(applied_updates),
    "applied_updates": applied_updates,
    "warnings": warnings,
    "updated_model_input_json": updated_model_input_json,
    "updated_finmo_json": updated_finmo_json,
  }


def _run_realism_resolution_loop(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  grid_application_summary: Optional[Dict[str, Any]],
  catalog_source_model_input_json: Dict[str, Any],
  applied_model_input_json: Dict[str, Any],
  applied_finmo_json: Dict[str, Any],
) -> Dict[str, Any]:
  del target_market_json, people_json, financials_year1_json, fulfillment_json, marketing_model_json
  current_model_input = _model_input_with_controller_catalog(
    model_input_json=copy.deepcopy(applied_model_input_json),
    catalog_source_model_input_json=copy.deepcopy(catalog_source_model_input_json),
  )
  current_finmo = copy.deepcopy(applied_finmo_json if isinstance(applied_finmo_json, dict) else {})
  initial_scan_memo = generate_realism_memo_payload_safe(
    ops_json=ops_json,
    financials_json=financials_json,
    solved_model_input_json=copy.deepcopy(current_model_input),
    solved_finmo_json=copy.deepcopy(current_finmo),
  )
  issue_ledger = _build_issue_status_records_from_issue_list(
    current_issues=_memo_issue_records(copy.deepcopy(initial_scan_memo), "remaining_issues", "issues"),
    iteration=0,
  )
  trace: List[Dict[str, Any]] = []
  initial_resolution_summary = _build_resolution_summary_from_issue_ledger(
    before_memo=copy.deepcopy(initial_scan_memo),
    issue_status_records=copy.deepcopy(issue_ledger),
  )
  persisted_initial_memo = _build_realism_memo_from_issue_ledger(
    before_memo=copy.deepcopy(initial_scan_memo),
    issue_status_records=copy.deepcopy(issue_ledger),
    resolution_summary=copy.deepcopy(initial_resolution_summary),
    iteration=0,
  )
  _persist_realism_loop_state(
    conn=conn,
    draft_id=str(draft_id).strip(),
    stage="realism_resolution_running",
    status="running",
    controller_resolution_state=_build_controller_resolution_state_from_issue_ledger(
      issue_status_records=copy.deepcopy(issue_ledger),
      iteration=0,
    ),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=copy.deepcopy(persisted_initial_memo),
    realism_resolution_decision={},
    realism_resolution_plan={},
    realism_resolution_result={},
    realism_resolution_verification={},
    realism_resolution_iterations=[],
    resolution_summary=copy.deepcopy(initial_resolution_summary),
    realism_memo_json=copy.deepcopy(persisted_initial_memo),
    model_input_json=copy.deepcopy(current_model_input),
    finmo_json=copy.deepcopy(current_finmo),
  )
  final_memo = copy.deepcopy(persisted_initial_memo)
  final_resolution_summary = copy.deepcopy(initial_resolution_summary)
  last_decision: Dict[str, Any] = {}
  last_plan: Dict[str, Any] = {}
  last_result: Dict[str, Any] = {}
  last_verification: Dict[str, Any] = {}
  stop_reason = "not_started"
  active_issue_keys = _issue_keys_from_status_records(issue_ledger, status_filter="open")
  for iteration in range(1, _REALISM_MAX_ITERATIONS + 1):
    active_memo = _build_realism_memo_from_issue_ledger(
      before_memo=copy.deepcopy(persisted_initial_memo),
      issue_status_records=copy.deepcopy(issue_ledger),
      resolution_summary=copy.deepcopy(final_resolution_summary),
      iteration=iteration - 1,
      verification_payload=copy.deepcopy(last_verification),
      issue_keys=copy.deepcopy(active_issue_keys),
    )
    active_issues = _memo_issue_records(active_memo, "remaining_issues", "issues")
    planner_issue_state = _build_realism_planner_issue_state(
      issue_status_records=copy.deepcopy(issue_ledger),
      issue_keys=copy.deepcopy(active_issue_keys),
    )
    iteration_record: Dict[str, Any] = {
      "iteration": iteration,
      "phase": "main",
      "memo_before": copy.deepcopy(active_memo),
      "active_issue_codes": [str(item.get("issue_code") or "").strip().lower() for item in active_issues if isinstance(item, dict)],
      "planner_issue_state": copy.deepcopy(planner_issue_state),
      "prior_verification_feedback": copy.deepcopy(_extract_open_verification_feedback(last_verification)),
    }

    if str(active_memo.get("status") or "").strip().lower() not in {"ready", "resolved"}:
      iteration_record["status"] = "stopped_memo_not_ready"
      trace.append(iteration_record)
      stop_reason = str(active_memo.get("status") or "").strip() or "memo_not_ready"
      final_memo = copy.deepcopy(active_memo)
      break

    if not active_issues or not active_issue_keys:
      iteration_record["status"] = "stopped_no_remaining_issues"
      trace.append(iteration_record)
      stop_reason = "main_loop_no_remaining_active_issues"
      final_memo = copy.deepcopy(active_memo)
      break

    decision = _run_realism_resolution_openai(
      draft_id=str(draft_id or "").strip(),
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      planner_issue_state=copy.deepcopy(planner_issue_state),
      solved_model_input_json=copy.deepcopy(current_model_input),
      solved_finmo_json=copy.deepcopy(current_finmo),
      current_iteration=iteration,
    )
    if isinstance(decision, dict):
      decision["iteration"] = iteration
      decision["repair_owner"] = "realism_ai_direct_write"
      decision["issue_count"] = len(active_issues)
    plan = _build_realism_resolution_plan(
      review_decision_payload=copy.deepcopy(decision),
      solved_model_input_json=copy.deepcopy(current_model_input),
      solved_finmo_json=copy.deepcopy(current_finmo),
    )
    result = _apply_followup_exact_updates(
      review_plan=copy.deepcopy(plan),
      current_model_input_json=copy.deepcopy(current_model_input),
      contract_version="realism_resolution_result_v3",
    )
    iteration_record["decision"] = copy.deepcopy(decision)
    iteration_record["plan"] = copy.deepcopy(plan)
    iteration_record["result"] = copy.deepcopy(result)
    trace.append(iteration_record)
    last_decision = copy.deepcopy(decision)
    last_plan = copy.deepcopy(plan)
    last_result = copy.deepcopy(result)

    if str(result.get("status") or "").strip() not in {"completed", "skipped_maintain_first_pass"}:
      iteration_record["status"] = "stopped_write_failed"
      stop_reason = str(result.get("status") or "").strip() or "realism_write_failed"
      break

    next_model_input = (
      _model_input_with_controller_catalog(
        model_input_json=copy.deepcopy(result.get("updated_model_input_json") or {}),
        catalog_source_model_input_json=copy.deepcopy(catalog_source_model_input_json),
      )
      if isinstance(result.get("updated_model_input_json"), dict)
      else copy.deepcopy(current_model_input)
    )
    next_finmo = (
      copy.deepcopy(result.get("updated_finmo_json") or {})
      if isinstance(result.get("updated_finmo_json"), dict) and result.get("updated_finmo_json")
      else copy.deepcopy(current_finmo)
    )

    verification_after = _run_realism_verification_openai(
      draft_id=str(draft_id or "").strip(),
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      realism_memo_before_resolution=copy.deepcopy(active_memo),
      realism_resolution_decision=copy.deepcopy(decision),
      realism_resolution_plan=copy.deepcopy(plan),
      realism_resolution_result=copy.deepcopy(result),
      updated_model_input_json=copy.deepcopy(next_model_input),
      updated_finmo_json=copy.deepcopy(next_finmo),
    )
    last_verification = copy.deepcopy(verification_after)
    issue_ledger = _apply_realism_verification_to_issue_status_records(
      issue_status_records=copy.deepcopy(issue_ledger),
      verification_payload=copy.deepcopy(verification_after),
      iteration=iteration,
      allowed_issue_keys=copy.deepcopy(active_issue_keys),
      allow_new_records=False,
    )
    resolution_summary_after = _build_resolution_summary_from_issue_ledger(
      before_memo=copy.deepcopy(persisted_initial_memo),
      issue_status_records=copy.deepcopy(issue_ledger),
      verification_payload=copy.deepcopy(verification_after),
    )
    resolved_memo_after = _build_realism_memo_from_issue_ledger(
      before_memo=copy.deepcopy(persisted_initial_memo),
      issue_status_records=copy.deepcopy(issue_ledger),
      resolution_summary=copy.deepcopy(resolution_summary_after),
      iteration=iteration,
      verification_payload=copy.deepcopy(verification_after),
    )
    active_issue_keys = list(set(_issue_keys_requiring_iteration(issue_ledger)))
    iteration_record["memo_after"] = copy.deepcopy(resolved_memo_after)
    iteration_record["verification_after"] = copy.deepcopy(verification_after)
    iteration_record["status"] = "completed_iteration"
    current_model_input = copy.deepcopy(next_model_input)
    current_finmo = copy.deepcopy(next_finmo)
    final_memo = copy.deepcopy(resolved_memo_after)
    final_resolution_summary = copy.deepcopy(resolution_summary_after)
    _persist_realism_loop_state(
      conn=conn,
      draft_id=str(draft_id).strip(),
      stage="realism_resolution_running",
      status="running",
      controller_resolution_state=_build_controller_resolution_state_from_issue_ledger(
        issue_status_records=copy.deepcopy(issue_ledger),
        iteration=iteration,
        verification_payload=copy.deepcopy(verification_after),
      ),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      realism_memo_before_resolution=copy.deepcopy(persisted_initial_memo),
      realism_resolution_decision=copy.deepcopy(decision),
      realism_resolution_plan=copy.deepcopy(plan),
      realism_resolution_result=copy.deepcopy(result),
      realism_resolution_verification=copy.deepcopy(verification_after),
      realism_resolution_iterations=copy.deepcopy(trace),
      resolution_summary=copy.deepcopy(resolution_summary_after),
      realism_memo_json=copy.deepcopy(resolved_memo_after),
      model_input_json=copy.deepcopy(current_model_input),
      finmo_json=copy.deepcopy(current_finmo),
    )

    if not active_issue_keys:
      stop_reason = "main_loop_no_remaining_iteration_needed"
      break

    if iteration >= _REALISM_MAX_ITERATIONS:
      stop_reason = "main_loop_max_iterations_reached_with_iteration_pending"
      break

    stop_reason = "main_loop_iteration_pending_after_iteration"

  fresh_scan_iteration = len(trace) + 1
  fresh_scan_memo = generate_realism_memo_payload_safe(
    ops_json=ops_json,
    financials_json=financials_json,
    solved_model_input_json=copy.deepcopy(current_model_input),
    solved_finmo_json=copy.deepcopy(current_finmo),
  )
  fresh_issue_set = _build_issue_status_records_from_issue_list(
    current_issues=_memo_issue_records(copy.deepcopy(fresh_scan_memo), "remaining_issues", "issues"),
    iteration=fresh_scan_iteration,
  )
  fresh_issue_candidates: List[Dict[str, Any]] = []
  if fresh_issue_set:
    fresh_issue_candidates = [_core_issue_record(item) for item in fresh_issue_set]
    cleanup_issue_keys = _issue_keys_requiring_iteration(fresh_issue_set)
    issue_ledger = copy.deepcopy(fresh_issue_set)
    cleanup_memo_before = _build_realism_memo_from_issue_ledger(
      before_memo=copy.deepcopy(persisted_initial_memo),
      issue_status_records=copy.deepcopy(issue_ledger),
      resolution_summary=copy.deepcopy(final_resolution_summary),
      iteration=fresh_scan_iteration,
      issue_keys=copy.deepcopy(cleanup_issue_keys),
    )
    cleanup_planner_issue_state = _build_realism_planner_issue_state(
      issue_status_records=copy.deepcopy(issue_ledger),
      issue_keys=copy.deepcopy(cleanup_issue_keys),
    )
    cleanup_record: Dict[str, Any] = {
      "iteration": fresh_scan_iteration,
      "phase": "cleanup",
      "memo_before": copy.deepcopy(cleanup_memo_before),
      "active_issue_codes": [str(item.get("issue_code") or "").strip().lower() for item in fresh_issue_set if isinstance(item, dict)],
      "planner_issue_state": copy.deepcopy(cleanup_planner_issue_state),
      "fresh_scan_memo": copy.deepcopy(fresh_scan_memo),
      "fresh_issue_candidates": copy.deepcopy(fresh_issue_candidates),
      "prior_verification_feedback": {},
    }
    decision = _run_realism_resolution_openai(
      draft_id=str(draft_id or "").strip(),
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      planner_issue_state=copy.deepcopy(cleanup_planner_issue_state),
      solved_model_input_json=copy.deepcopy(current_model_input),
      solved_finmo_json=copy.deepcopy(current_finmo),
      current_iteration=fresh_scan_iteration,
    )
    if isinstance(decision, dict):
      decision["iteration"] = fresh_scan_iteration
      decision["repair_owner"] = "realism_ai_direct_write"
      decision["issue_count"] = len(cleanup_issue_keys)
      decision["resolution_phase"] = "cleanup"
    plan = _build_realism_resolution_plan(
      review_decision_payload=copy.deepcopy(decision),
      solved_model_input_json=copy.deepcopy(current_model_input),
      solved_finmo_json=copy.deepcopy(current_finmo),
    )
    result = _apply_followup_exact_updates(
      review_plan=copy.deepcopy(plan),
      current_model_input_json=copy.deepcopy(current_model_input),
      contract_version="realism_resolution_result_v3",
    )
    cleanup_record["decision"] = copy.deepcopy(decision)
    cleanup_record["plan"] = copy.deepcopy(plan)
    cleanup_record["result"] = copy.deepcopy(result)
    trace.append(cleanup_record)
    last_decision = copy.deepcopy(decision)
    last_plan = copy.deepcopy(plan)
    last_result = copy.deepcopy(result)

    if str(result.get("status") or "").strip() in {"completed", "skipped_maintain_first_pass"}:
      next_model_input = (
        _model_input_with_controller_catalog(
          model_input_json=copy.deepcopy(result.get("updated_model_input_json") or {}),
          catalog_source_model_input_json=copy.deepcopy(catalog_source_model_input_json),
        )
        if isinstance(result.get("updated_model_input_json"), dict)
        else copy.deepcopy(current_model_input)
      )
      next_finmo = (
        copy.deepcopy(result.get("updated_finmo_json") or {})
        if isinstance(result.get("updated_finmo_json"), dict) and result.get("updated_finmo_json")
        else copy.deepcopy(current_finmo)
      )
      verification_after = _run_realism_verification_openai(
        draft_id=str(draft_id or "").strip(),
        business_facts=copy.deepcopy(business_facts or {}),
        ops_json=copy.deepcopy(ops_json or {}),
        realism_memo_before_resolution=copy.deepcopy(cleanup_memo_before),
        realism_resolution_decision=copy.deepcopy(decision),
        realism_resolution_plan=copy.deepcopy(plan),
        realism_resolution_result=copy.deepcopy(result),
        updated_model_input_json=copy.deepcopy(next_model_input),
        updated_finmo_json=copy.deepcopy(next_finmo),
      )
      last_verification = copy.deepcopy(verification_after)
      issue_ledger = _apply_realism_verification_to_issue_status_records(
        issue_status_records=copy.deepcopy(issue_ledger),
        verification_payload=copy.deepcopy(verification_after),
        iteration=fresh_scan_iteration,
        allowed_issue_keys=copy.deepcopy(cleanup_issue_keys),
        allow_new_records=False,
      )
      current_model_input = copy.deepcopy(next_model_input)
      current_finmo = copy.deepcopy(next_finmo)
      final_resolution_summary = _build_resolution_summary_from_issue_ledger(
        before_memo=copy.deepcopy(persisted_initial_memo),
        issue_status_records=copy.deepcopy(issue_ledger),
        verification_payload=copy.deepcopy(verification_after),
      )
      final_memo = _build_realism_memo_from_issue_ledger(
        before_memo=copy.deepcopy(persisted_initial_memo),
        issue_status_records=copy.deepcopy(issue_ledger),
        resolution_summary=copy.deepcopy(final_resolution_summary),
        iteration=fresh_scan_iteration,
        verification_payload=copy.deepcopy(verification_after),
      )
      cleanup_record["verification_after"] = copy.deepcopy(verification_after)
      cleanup_record["memo_after"] = copy.deepcopy(final_memo)
      cleanup_record["status"] = "completed_iteration"
      remaining_issue_keys_after_cleanup = _issue_keys_requiring_iteration(issue_ledger)
      if remaining_issue_keys_after_cleanup:
        final_followup_iteration = len(trace) + 1
        final_followup_memo_before = _build_realism_memo_from_issue_ledger(
          before_memo=copy.deepcopy(persisted_initial_memo),
          issue_status_records=copy.deepcopy(issue_ledger),
          resolution_summary=copy.deepcopy(final_resolution_summary),
          iteration=final_followup_iteration,
          issue_keys=copy.deepcopy(remaining_issue_keys_after_cleanup),
        )
        final_followup_planner_issue_state = _build_realism_planner_issue_state(
          issue_status_records=copy.deepcopy(issue_ledger),
          issue_keys=copy.deepcopy(remaining_issue_keys_after_cleanup),
        )
        final_followup_record: Dict[str, Any] = {
          "iteration": final_followup_iteration,
          "phase": "final_followup",
          "memo_before": copy.deepcopy(final_followup_memo_before),
          "active_issue_codes": copy.deepcopy(remaining_issue_keys_after_cleanup),
          "planner_issue_state": copy.deepcopy(final_followup_planner_issue_state),
          "prior_verification_feedback": {},
        }
        decision = _run_realism_resolution_openai(
          draft_id=str(draft_id or "").strip(),
          business_facts=copy.deepcopy(business_facts or {}),
          ops_json=copy.deepcopy(ops_json or {}),
          financials_json=copy.deepcopy(financials_json or {}),
          planner_issue_state=copy.deepcopy(final_followup_planner_issue_state),
          solved_model_input_json=copy.deepcopy(current_model_input),
          solved_finmo_json=copy.deepcopy(current_finmo),
          current_iteration=final_followup_iteration,
        )
        if isinstance(decision, dict):
          decision["iteration"] = final_followup_iteration
          decision["repair_owner"] = "realism_ai_direct_write"
          decision["issue_count"] = len(remaining_issue_keys_after_cleanup)
          decision["resolution_phase"] = "final_followup"
        plan = _build_realism_resolution_plan(
          review_decision_payload=copy.deepcopy(decision),
          solved_model_input_json=copy.deepcopy(current_model_input),
          solved_finmo_json=copy.deepcopy(current_finmo),
        )
        result = _apply_followup_exact_updates(
          review_plan=copy.deepcopy(plan),
          current_model_input_json=copy.deepcopy(current_model_input),
          contract_version="realism_resolution_result_v3",
        )
        final_followup_record["decision"] = copy.deepcopy(decision)
        final_followup_record["plan"] = copy.deepcopy(plan)
        final_followup_record["result"] = copy.deepcopy(result)
        trace.append(final_followup_record)
        last_decision = copy.deepcopy(decision)
        last_plan = copy.deepcopy(plan)
        last_result = copy.deepcopy(result)

        if str(result.get("status") or "").strip() in {"completed", "skipped_maintain_first_pass"}:
          next_model_input = (
            _model_input_with_controller_catalog(
              model_input_json=copy.deepcopy(result.get("updated_model_input_json") or {}),
              catalog_source_model_input_json=copy.deepcopy(catalog_source_model_input_json),
            )
            if isinstance(result.get("updated_model_input_json"), dict)
            else copy.deepcopy(current_model_input)
          )
          next_finmo = (
            copy.deepcopy(result.get("updated_finmo_json") or {})
            if isinstance(result.get("updated_finmo_json"), dict) and result.get("updated_finmo_json")
            else copy.deepcopy(current_finmo)
          )
          verification_after = _run_realism_verification_openai(
            draft_id=str(draft_id or "").strip(),
            business_facts=copy.deepcopy(business_facts or {}),
            ops_json=copy.deepcopy(ops_json or {}),
            realism_memo_before_resolution=copy.deepcopy(final_followup_memo_before),
            realism_resolution_decision=copy.deepcopy(decision),
            realism_resolution_plan=copy.deepcopy(plan),
            realism_resolution_result=copy.deepcopy(result),
            updated_model_input_json=copy.deepcopy(next_model_input),
            updated_finmo_json=copy.deepcopy(next_finmo),
          )
          last_verification = copy.deepcopy(verification_after)
          issue_ledger = _apply_realism_verification_to_issue_status_records(
            issue_status_records=copy.deepcopy(issue_ledger),
            verification_payload=copy.deepcopy(verification_after),
            iteration=final_followup_iteration,
            allowed_issue_keys=copy.deepcopy(remaining_issue_keys_after_cleanup),
            allow_new_records=False,
          )
          current_model_input = copy.deepcopy(next_model_input)
          current_finmo = copy.deepcopy(next_finmo)
          final_resolution_summary = _build_resolution_summary_from_issue_ledger(
            before_memo=copy.deepcopy(persisted_initial_memo),
            issue_status_records=copy.deepcopy(issue_ledger),
            verification_payload=copy.deepcopy(verification_after),
          )
          final_memo = _build_realism_memo_from_issue_ledger(
            before_memo=copy.deepcopy(persisted_initial_memo),
            issue_status_records=copy.deepcopy(issue_ledger),
            resolution_summary=copy.deepcopy(final_resolution_summary),
            iteration=final_followup_iteration,
            verification_payload=copy.deepcopy(verification_after),
          )
          final_followup_record["verification_after"] = copy.deepcopy(verification_after)
          final_followup_record["memo_after"] = copy.deepcopy(final_memo)
          final_followup_record["status"] = "completed_iteration"
          stop_reason = "final_followup_pass_completed"
        else:
          final_followup_record["status"] = "stopped_write_failed"
          stop_reason = str(result.get("status") or "").strip() or "final_followup_write_failed"
          final_resolution_summary = _build_resolution_summary_from_issue_ledger(
            before_memo=copy.deepcopy(persisted_initial_memo),
            issue_status_records=copy.deepcopy(issue_ledger),
            verification_payload=copy.deepcopy(last_verification),
          )
          final_memo = _build_realism_memo_from_issue_ledger(
            before_memo=copy.deepcopy(persisted_initial_memo),
            issue_status_records=copy.deepcopy(issue_ledger),
            resolution_summary=copy.deepcopy(final_resolution_summary),
            iteration=final_followup_iteration,
            verification_payload=copy.deepcopy(last_verification),
          )
      else:
        stop_reason = "cleanup_pass_completed"
    else:
      cleanup_record["status"] = "stopped_write_failed"
      stop_reason = str(result.get("status") or "").strip() or "cleanup_write_failed"
      final_resolution_summary = _build_resolution_summary_from_issue_ledger(
        before_memo=copy.deepcopy(persisted_initial_memo),
        issue_status_records=copy.deepcopy(issue_ledger),
        verification_payload=copy.deepcopy(last_verification),
      )
      final_memo = _build_realism_memo_from_issue_ledger(
        before_memo=copy.deepcopy(persisted_initial_memo),
        issue_status_records=copy.deepcopy(issue_ledger),
        resolution_summary=copy.deepcopy(final_resolution_summary),
        iteration=fresh_scan_iteration,
        verification_payload=copy.deepcopy(last_verification),
      )
    _persist_realism_loop_state(
      conn=conn,
      draft_id=str(draft_id).strip(),
      stage="realism_resolution_running",
      status="running",
      controller_resolution_state=_build_controller_resolution_state_from_issue_ledger(
        issue_status_records=copy.deepcopy(issue_ledger),
        iteration=len(trace),
        verification_payload=copy.deepcopy(last_verification),
      ),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      realism_memo_before_resolution=copy.deepcopy(persisted_initial_memo),
      realism_resolution_decision=copy.deepcopy(last_decision),
      realism_resolution_plan=copy.deepcopy(last_plan),
      realism_resolution_result=copy.deepcopy(last_result),
      realism_resolution_verification=copy.deepcopy(last_verification),
      realism_resolution_iterations=copy.deepcopy(trace),
      resolution_summary=copy.deepcopy(final_resolution_summary),
      realism_memo_json=copy.deepcopy(final_memo),
      model_input_json=copy.deepcopy(current_model_input),
      finmo_json=copy.deepcopy(current_finmo),
    )
  else:
    final_resolution_summary = _build_resolution_summary_from_issue_ledger(
      before_memo=copy.deepcopy(persisted_initial_memo),
      issue_status_records=copy.deepcopy(issue_ledger),
      verification_payload=copy.deepcopy(last_verification),
    )
    final_memo = _build_realism_memo_from_issue_ledger(
      before_memo=copy.deepcopy(persisted_initial_memo),
      issue_status_records=copy.deepcopy(issue_ledger),
      resolution_summary=copy.deepcopy(final_resolution_summary),
      iteration=len(trace),
      verification_payload=copy.deepcopy(last_verification),
    )

  resolution_summary = copy.deepcopy(final_resolution_summary)
  realism_memo_json = copy.deepcopy(final_memo)
  controller_resolution_state = _build_controller_resolution_state_from_issue_ledger(
    issue_status_records=copy.deepcopy(issue_ledger),
    iteration=len(trace),
    verification_payload=copy.deepcopy(last_verification),
  )
  return {
    "initial_memo": copy.deepcopy(persisted_initial_memo),
    "final_memo": copy.deepcopy(final_memo),
    "issue_ledger": copy.deepcopy(issue_ledger),
    "realism_memo_json": copy.deepcopy(realism_memo_json),
    "final_model_input_json": copy.deepcopy(current_model_input),
    "final_finmo_json": copy.deepcopy(current_finmo),
    "iterations": trace,
    "iteration_count": len(trace),
    "stop_reason": stop_reason,
    "last_decision": copy.deepcopy(last_decision),
    "last_plan": copy.deepcopy(last_plan),
    "last_result": copy.deepcopy(last_result),
    "last_verification": copy.deepcopy(last_verification),
    "fresh_scan_memo": copy.deepcopy(fresh_scan_memo),
    "fresh_issue_candidates": [
      {
        **_core_issue_record(item),
        "candidate_kind": str(item.get("candidate_kind") or "").strip(),
      }
      for item in fresh_issue_candidates
    ],
  }


def _sum_series(values: Any) -> float:
  if not isinstance(values, list):
    return 0.0
  return float(sum(float(_safe_float(item) or 0.0) for item in values))


def _series_changed_count(before: Any, after: Any, *, tolerance: float = 1.0) -> int:
  before_list = before if isinstance(before, list) else []
  after_list = after if isinstance(after, list) else []
  changed = 0
  for before_value, after_value in zip(before_list, after_list):
    if abs(float(_safe_float(before_value) or 0.0) - float(_safe_float(after_value) or 0.0)) > float(tolerance):
      changed += 1
  return changed


def _build_cash_strategy_effect_summary(
  *,
  financials_json: Optional[Dict[str, Any]],
  review_decision_payload: Optional[Dict[str, Any]],
  second_pass_result: Optional[Dict[str, Any]],
  first_pass_finmo_json: Optional[Dict[str, Any]],
  final_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  review_payload = review_decision_payload if isinstance(review_decision_payload, dict) else {}
  decision = review_payload.get("decision") if isinstance(review_payload.get("decision"), dict) else {}
  result = second_pass_result if isinstance(second_pass_result, dict) else {}
  first_finmo = first_pass_finmo_json if isinstance(first_pass_finmo_json, dict) else {}
  final_finmo = final_finmo_json if isinstance(final_finmo_json, dict) else {}

  first_metrics = _cash_review_quarter_metrics(first_finmo)
  final_metrics = _cash_review_quarter_metrics(final_finmo)

  first_cash_series = [float(_safe_float(item.get("ending_cash")) or 0.0) for item in first_metrics]
  final_cash_series = [float(_safe_float(item.get("ending_cash")) or 0.0) for item in final_metrics]

  first_marketing = _finmo_labeled_series(first_finmo, section_key="pl", label="Marketing")
  final_marketing = _finmo_labeled_series(final_finmo, section_key="pl", label="Marketing")
  first_payroll = _finmo_labeled_series(first_finmo, section_key="pl", label="Payroll")
  final_payroll = _finmo_labeled_series(final_finmo, section_key="pl", label="Payroll")
  first_capex = _finmo_labeled_series(first_finmo, section_key="cash_flow", label="Capital Expenditures")
  final_capex = _finmo_labeled_series(final_finmo, section_key="cash_flow", label="Capital Expenditures")
  first_principal = _finmo_labeled_series(first_finmo, section_key="cash_flow", label="Dept Receive(Repay)")
  final_principal = _finmo_labeled_series(final_finmo, section_key="cash_flow", label="Dept Receive(Repay)")

  first_final_cash = first_cash_series[-1] if first_cash_series else 0.0
  final_final_cash = final_cash_series[-1] if final_cash_series else 0.0
  first_peak_cash = max(first_cash_series) if first_cash_series else 0.0
  final_peak_cash = max(final_cash_series) if final_cash_series else 0.0

  changed_quarters = _series_changed_count(first_cash_series, final_cash_series, tolerance=1.0)
  material_change_detected = any([
    abs(final_final_cash - first_final_cash) > 1.0,
    abs(final_peak_cash - first_peak_cash) > 1.0,
    _series_changed_count(first_marketing, final_marketing, tolerance=1.0) > 0,
    _series_changed_count(first_payroll, final_payroll, tolerance=1.0) > 0,
    _series_changed_count(first_capex, final_capex, tolerance=1.0) > 0,
    _series_changed_count(first_principal, final_principal, tolerance=1.0) > 0,
  ])

  recommendation_mode = str(decision.get("recommendation_mode") or "").strip()
  final_model_source = str(result.get("final_model_source") or "").strip() or "first_pass"
  result_status = str(result.get("status") or "").strip()

  summary_line = (
    f"Cash review selected `{final_model_source}` with status `{result_status}`. "
    f"Final ending cash changed by {_format_currency(final_final_cash - first_final_cash)} "
    f"and peak cash changed by {_format_currency(final_peak_cash - first_peak_cash)}."
  )
  if recommendation_mode == "adjust" and not material_change_detected:
    summary_line += " Review requested adjustment, but no material post-solve change was achieved."
  elif recommendation_mode == "maintain":
    summary_line += " Review determined the first-pass model already expressed the chosen cash strategy adequately."

  return {
    "contract_version": "cash_strategy_effect_summary_v1",
    "selected_cash_strategy": str(financials.get("cash_strategy") or "").strip(),
    "review_status": str(review_payload.get("status") or "").strip(),
    "recommendation_mode": recommendation_mode,
    "decision_trigger_type": str(decision.get("decision_trigger_type") or "").strip(),
    "decision_trigger_summary": str(decision.get("decision_trigger_summary") or "").strip(),
    "recommended_action_count": len([item for item in (decision.get("recommended_actions") or []) if isinstance(item, dict)]),
    "second_pass_status": result_status,
    "final_model_source": final_model_source,
    "applied_control_count": int(_safe_float(result.get("applied_control_count")) or 0),
    "material_change_detected": bool(material_change_detected),
    "changed_cash_quarter_count": changed_quarters,
    "cash_metrics": {
      "first_pass_final_cash": first_final_cash,
      "final_pass_final_cash": final_final_cash,
      "delta_final_cash": float(final_final_cash - first_final_cash),
      "first_pass_peak_cash": first_peak_cash,
      "final_pass_peak_cash": final_peak_cash,
      "delta_peak_cash": float(final_peak_cash - first_peak_cash),
    },
    "deployment_deltas": {
      "marketing_total_delta": float(_sum_series(final_marketing) - _sum_series(first_marketing)),
      "payroll_total_delta": float(_sum_series(final_payroll) - _sum_series(first_payroll)),
      "capital_expenditures_total_delta": float(_sum_series(final_capex) - _sum_series(first_capex)),
      "principal_repayment_total_delta": float(_sum_series(final_principal) - _sum_series(first_principal)),
    },
    "summary_line": summary_line,
  }


def _build_intake_complete_planning_run_payload() -> Dict[str, Any]:
  return _build_planning_run_payload(
    stage="intake_complete",
    status="pending",
    gpt_narrative="Intake complete. Ready for backend planning.",
  )


def _build_financials_completion_turn(*, acknowledgement: str = "") -> Dict[str, Any]:
  message = "Thanks. I have everything I need for financials, and the intake is complete."
  if str(acknowledgement or "").strip():
    message = f"{str(acknowledgement).strip()}\n\n{message}".strip()
  return {
    "assistant_message": message,
    "finalize_ready": False,
    "transition_to_done": True,
  }


def _persist_and_reload_financials_progress(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    active_focus="financials",
    business_facts=business_facts,
  )
  persisted = get_draft(conn, draft_id=str(draft_id).strip())
  return (
    _parse_json_dict(persisted.get("financials_json")),
    _parse_json_dict(persisted.get("financials_year1_json")),
    _parse_json_dict(persisted.get("marketing_model_json")),
  )


def _advance_persisted_financials_stage(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  shared_context: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
  acknowledgement: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  persisted_financials, persisted_year1, persisted_marketing = _persist_and_reload_financials_progress(
    conn=conn,
    draft_id=draft_id,
    business_facts=business_facts,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json or {},
  )
  next_stage = _next_financials_stage(persisted_financials)
  if next_stage:
    next_context = dict(intake_context or {})
    next_context["financials_json"] = persisted_financials
    next_shared = dict(shared_context or {})
    next_shared["financials"] = persisted_financials
    if isinstance(persisted_marketing, dict) and persisted_marketing:
      next_shared["marketing"] = persisted_marketing
    next_context["shared_context"] = next_shared
    next_context["financials_active_stage"] = next_stage
    next_turn = {
      "assistant_message": _build_financials_stage_message(
        stage_name=next_stage,
        intake_context=next_context,
        shared_context=next_shared,
        financials_json=persisted_financials,
        financials_year1_json=persisted_year1,
        business_facts=business_facts,
        conn=conn,
      ),
      "finalize_ready": False,
    }
    if str(acknowledgement or "").strip():
      next_text = str(next_turn.get("assistant_message") or "").strip()
      next_turn["assistant_message"] = (
        f"{str(acknowledgement).strip()}\n\n{next_text}".strip()
        if next_text
        else str(acknowledgement).strip()
      )
    next_financials = _sync_pending_revenue_adjustment_state(
      persisted_financials,
      persisted_year1,
      next_turn.get("revenue_adjudication") if isinstance(next_turn, dict) else None,
    )
    return next_turn, next_financials, persisted_marketing

  completion_turn = _build_financials_completion_turn(acknowledgement=acknowledgement)
  next_financials = _sync_pending_revenue_adjustment_state(
    persisted_financials,
    persisted_year1,
    completion_turn.get("revenue_adjudication") if isinstance(completion_turn, dict) else None,
  )
  return completion_turn, next_financials, persisted_marketing


def _build_financials_revenue_intro_message(
  *,
  intake_context: Dict[str, Any],
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> str:
  revenue_math_line = str((intake_context or {}).get("revenue_math_line") or "").strip()
  operating_model = dict((shared_context or {}).get("operating_model") or {})
  price = _format_currency(operating_model.get("unit_price"))
  utilization = _format_percent(operating_model.get("utilization_rate"))
  weekly_capacity = _safe_float(operating_model.get("units_per_week_capacity"))
  periods = _safe_float(operating_model.get("operating_periods_per_year"))
  annual_revenue = _format_currency((financials_year1_json or {}).get("company_revenue_total_year1"))
  capacity_text = f"{weekly_capacity:g} sessions per week" if weekly_capacity is not None else "the modeled weekly capacity"
  periods_text = f"{periods:g} operating periods" if periods is not None else "the modeled operating periods"
  lead = "Year 1 revenue:"
  if revenue_math_line:
    lead = f"{lead}\n\n{revenue_math_line}"
  summary = (
    f"This planning baseline assumes you run at about {utilization} utilization of {capacity_text}, "
    f"at an average price of {price}, across {periods_text}, which produces about {annual_revenue} in Year-1 revenue."
  )
  return (
    f"{lead}\n\n"
    f"{summary} "
    "We will use this as the baseline for the rest of financial planning."
  ).strip()


def _financials_baseline_estimators() -> Tuple[Any, Any]:
  try:
    from financials_consultant import (  # type: ignore
      estimate_cogs_percent_from_context as _estimate_cogs_percent_from_context,
      estimate_marketing_baseline_from_context as _estimate_marketing_baseline_from_context,
    )
  except Exception:
    from client_intake_and_finmo.financials_consultant import (  # type: ignore
      estimate_cogs_percent_from_context as _estimate_cogs_percent_from_context,
      estimate_marketing_baseline_from_context as _estimate_marketing_baseline_from_context,
    )
  return _estimate_cogs_percent_from_context, _estimate_marketing_baseline_from_context


def _build_financials_stage_message(
  *,
  stage_name: str,
  intake_context: Dict[str, Any],
  shared_context: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  conn,
) -> str:
  stage = str(stage_name or "").strip()
  estimate_cogs_percent_from_context, estimate_marketing_baseline_from_context = _financials_baseline_estimators()
  if stage == "revenue_intro":
    return _build_financials_revenue_intro_message(
      intake_context=intake_context,
      shared_context=shared_context,
      financials_year1_json=financials_year1_json,
    )
  if stage == "cogs":
    baseline = _resolve_cogs_baseline_or_raise(
      conn=conn,
      ops_json=dict((shared_context or {}).get("operating_model") or {}),
      shared_context=shared_context,
      estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
      financials_year1_json=financials_year1_json,
    )
    return _build_cogs_baseline_message(baseline)
  if stage == "current_payroll":
    return _build_payroll_baseline_message(_compute_payroll_baseline(shared_context=shared_context))
  if stage == "marketing":
    marketing_model = _resolve_marketing_model_or_raise(
      conn=conn,
      ops_json=dict((shared_context or {}).get("operating_model") or {}),
      market_json=dict((shared_context or {}).get("target_market") or {}),
      people_json=dict((shared_context or {}).get("people_capability") or {}),
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      existing_marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
    )
    return _build_marketing_baseline_message(marketing_model)
  if stage == "monthly_rent_expense":
    return _build_monthly_rent_message(shared_context=shared_context)
  if stage == "future_rent_expected":
    return _build_future_rent_message(
      shared_context=shared_context,
      monthly_rent_expense=(financials_json or {}).get("monthly_rent_expense"),
    )
  if stage == "owner_compensation":
    return (
      "As of last month, how much did you pay yourself from the business in wages, draws, or other owner compensation? "
      "A dollar amount is fine."
    )
  if stage == "other_operating_expense":
    return (
      "As of last month, about how much did you spend on other regular business bills besides payroll, marketing, and rent, "
      "like utilities, software, insurance, accounting, phone, internet, and general overhead?"
    )
  if stage == "current_num_employees":
    return (
      "As of last month, how many people were on payroll for the business, not counting outside contractors? "
      "A whole number is fine."
    )
  if stage == "current_capex":
    return (
      "As of last month, did you make any larger one-time purchases for the business, like equipment, devices, furniture, build-out, or vehicles? "
      "If yes, what was the rough total?"
    )
  if stage == "initial_assets":
    return (
      "As of last month, what is your best rough estimate of the total value of the main equipment, devices, furniture, and fixtures already in the business?"
    )
  if stage == "initial_lease":
    return _build_initial_lease_message()
  if stage == "initial_equity":
    return (
      "As of last month, what is your best rough estimate of the total money or value put into the business so far by you or any investors?"
    )
  if stage == "total_debt_outstanding":
    return (
      "As of last month, what was the total amount the business still owed on loans, lines of credit, or business credit cards?"
    )
  if stage == "other_monthly_debt_payments":
    return (
      "As of last month, besides regular rent and credit card minimums already baked into other expenses, what other loan or debt payments did the business make each month?"
    )
  if stage == "annual_interest_payment":
    return (
      "Of your debt payments, what is your best estimate of the annual interest cost, meaning the finance charge rather than principal paydown?"
    )
  if stage == "annual_principal_payment":
    return (
      "What is your best estimate of the annual principal you expect to repay on the business debt, separate from interest?"
    )
  if stage == "cash_on_hand":
    return "As of last month, about how much cash did the business have on hand in its bank accounts and any cash on site?"
  if stage == "ar_balance":
    return (
      "As of last month, about how much money did customers still owe you for completed work, like unpaid invoices or payment plans?"
    )
  if stage == "ap_balance":
    return (
      "As of last month, about how much did the business still owe in regular operating bills, like unpaid supplier invoices, utilities, or business credit card balances related to operations?"
    )
  if stage == "inventory_balance":
    return (
      "As of last month, about how much inventory did you have on hand, like products or supplies kept in stock to use or sell?"
    )
  if stage == "cash_strategy":
    return _build_cash_strategy_message()
  return "What number should I record for this financial item?"


def _financials_stage_default_patch(
  *,
  stage_name: str,
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  conn,
) -> Optional[Dict[str, Any]]:
  stage = str(stage_name or "").strip()
  estimate_cogs_percent_from_context, estimate_marketing_baseline_from_context = _financials_baseline_estimators()
  if stage == "revenue_intro":
    baseline_revenue = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    if baseline_revenue is None:
      return None
    return {
      "current_revenue": float(baseline_revenue),
    }
  if stage == "cogs":
    baseline = _resolve_cogs_baseline_or_raise(
      conn=conn,
      ops_json=dict((shared_context or {}).get("operating_model") or {}),
      shared_context=shared_context,
      estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
      financials_year1_json=financials_year1_json,
    )
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1")) or 0.0
    total = float(baseline.get("baseline_cogs") or 0.0)
    return {
      "current_cogs": total,
      "cogs_total_year1": total,
      "cogs_percent_of_revenue": (total / revenue_year1) if revenue_year1 > 0 else float(baseline.get("baseline_cogs_percent") or 0.0),
      "baseline_cogs": total,
      "baseline_cogs_percent": float(baseline.get("baseline_cogs_percent") or 0.0),
      "cogs_adjustment": 0.0,
      "cogs_basis_naics": baseline.get("cogs_basis_naics"),
      "cogs_basis_years_used": baseline.get("cogs_basis_years_used") or [],
      "cogs_basis_rationale": str(baseline.get("cogs_basis_rationale") or "").strip(),
    }
  if stage == "current_payroll":
    baseline = _compute_payroll_baseline(shared_context=shared_context)
    total = float(baseline.get("baseline_payroll_year1") or 0.0)
    return {
      "current_payroll": total,
      "payroll_total_year1": total,
      "baseline_payroll_year1": total,
      "payroll_adjustment": 0.0,
      "payroll_basis_people_roles": baseline.get("payroll_basis_people_roles") or [],
    }
  if stage == "marketing":
    marketing_model = _resolve_marketing_model_or_raise(
      conn=conn,
      ops_json=dict((shared_context or {}).get("operating_model") or {}),
      market_json=dict((shared_context or {}).get("target_market") or {}),
      people_json=dict((shared_context or {}).get("people_capability") or {}),
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      existing_marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
    )
    total = float(marketing_model.get("baseline_marketing") or 0.0)
    percent = float(marketing_model.get("baseline_marketing_percent") or 0.0)
    return {
      "marketing_total_year1": total,
      "marketing_percent_of_revenue": percent,
      "baseline_marketing": total,
      "baseline_marketing_percent": percent,
      "marketing_adjustment": 0.0,
    }
  return None


def _build_financials_stage_acknowledgement(
  *,
  stage_name: str,
  financials_json: Dict[str, Any],
) -> str:
  stage = str(stage_name or "").strip()
  if stage == "cogs":
    total = _format_currency((financials_json or {}).get("cogs_total_year1"))
    percent = _format_percent((financials_json or {}).get("cogs_percent_of_revenue"))
    return f"Got it. I’ll use Year-1 direct costs of {total} ({percent} of revenue)."
  if stage == "current_payroll":
    return f"Got it. I’ll use Year-1 payroll of {_format_currency((financials_json or {}).get('payroll_total_year1'))}."
  if stage == "marketing":
    total = _format_currency((financials_json or {}).get("marketing_total_year1"))
    percent = _format_percent((financials_json or {}).get("marketing_percent_of_revenue"))
    return f"Got it. I’ll use a Year-1 marketing budget of {total} ({percent} of revenue)."
  if stage == "revenue_intro":
    return "Understood. We’ll use the current Year-1 revenue model as the baseline and move into the rest of financials."
  if stage == "cash_strategy":
    return _build_cash_strategy_acknowledgement((financials_json or {}).get("cash_strategy"))
  if stage == "current_num_employees":
    return f"Got it. I’ll use {int(round(float((financials_json or {}).get('current_num_employees') or 0)))} for current employee count."
  scalar_field = stage if stage in _GENERIC_FINANCIALS_FIELD_LABELS else ""
  if scalar_field:
    value = (financials_json or {}).get(stage)
    if stage == "future_rent_expected":
      return "Got it. I’ll treat future dedicated space as part of the model." if bool(value) else "Got it. I’ll treat future dedicated space as not expected for now."
    return _build_financials_scalar_stage_acknowledgement(stage, float(value or 0.0))
  return "Got it."


def _build_financials_live_turn(
  *,
  conn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  shared_context: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  guardrail_triggered: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  del guardrail_triggered
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  next_stage = _next_financials_stage(next_financials)
  if not next_stage:
    return _build_financials_completion_turn(), next_financials

  next_context = dict(intake_context or {})
  next_context["financials_json"] = next_financials
  next_shared = dict(shared_context or {})
  next_shared["financials"] = next_financials
  next_shared["financials_controller"] = _build_financials_controller_context(next_stage)
  next_context["shared_context"] = next_shared
  if next_stage:
    next_context["financials_active_stage"] = next_stage
  else:
    next_context.pop("financials_active_stage", None)

  turn = {
    "assistant_message": _build_financials_stage_message(
      stage_name=next_stage,
      intake_context=next_context,
      shared_context=next_shared,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      business_facts=dict((shared_context or {}).get("business_facts") or {}),
      conn=conn,
    ),
    "finalize_ready": False,
  }
  return turn, next_financials


def _build_cogs_baseline_message(cogs_baseline: Dict[str, Any]) -> str:
  return (
    f"A reasonable Year-1 COGS baseline is about "
    f"{_format_percent(cogs_baseline.get('baseline_cogs_percent'))} of revenue, which puts your projected Year-1 direct costs around "
    f"{_format_currency(cogs_baseline.get('baseline_cogs'))}.\n\n"
    "Does that broadly match how your business works, or should we adjust it because your direct costs are materially different?"
  )


def _build_payroll_baseline_signature(shared_context: Dict[str, Any]) -> str:
  people_context = dict((shared_context or {}).get("people_capability") or {})
  people_rows: List[Dict[str, Any]] = []
  for person in people_context.get("people") or []:
    if not isinstance(person, dict):
      continue
    people_rows.append(
      {
        "source": "person",
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "annual_wage": person.get("annual_wage"),
      }
    )
  role_rows: List[Dict[str, Any]] = []
  for role in people_context.get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    role_rows.append(
      {
        "source": "inferred_role",
        "role_title": str(role.get("role_title") or "").strip(),
        "annual_wage": role.get("annual_wage"),
        "months_until_hire": role.get("months_until_hire"),
      }
    )
  try:
    return json.dumps({"people": people_rows, "roles": role_rows}, sort_keys=True, ensure_ascii=False)
  except Exception:
    return ""


def _compute_payroll_baseline(
  *,
  shared_context: Dict[str, Any],
) -> Dict[str, Any]:
  people_context = dict((shared_context or {}).get("people_capability") or {})
  operating_model = dict((shared_context or {}).get("operating_model") or {})
  basis_roles: List[Dict[str, Any]] = []
  baseline_total = 0.0

  for person in people_context.get("people") or []:
    if not isinstance(person, dict):
      continue
    try:
      annual_wage = float(person.get("annual_wage") or 0.0)
    except Exception:
      annual_wage = 0.0
    annual_wage = max(0.0, annual_wage)
    baseline_total += annual_wage
    basis_roles.append(
      {
        "source": "person",
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "months_counted_year1": 12,
        "year1_payroll_amount": annual_wage,
      }
    )

  for role in people_context.get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    try:
      annual_wage = float(role.get("annual_wage") or 0.0)
    except Exception:
      annual_wage = 0.0
    annual_wage = max(0.0, annual_wage)
    raw_months = role.get("months_until_hire")
    try:
      months_until_hire = int(float(raw_months))
    except Exception:
      months_until_hire = 0
    months_until_hire = max(0, min(12, months_until_hire))
    months_counted = max(0, 12 - months_until_hire)
    year1_amount = float(annual_wage * (months_counted / 12.0))
    baseline_total += year1_amount
    basis_roles.append(
      {
        "source": "inferred_role",
        "role_title": str(role.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "months_until_hire": months_until_hire,
        "months_counted_year1": months_counted,
        "year1_payroll_amount": year1_amount,
      }
    )

  return {
    "baseline_payroll_year1": float(baseline_total),
    "payroll_adjustment": 0.0,
    "payroll_total_year1": float(baseline_total),
    "payroll_basis_people_roles": basis_roles,
    "business_stage": str(operating_model.get("business_stage") or "").strip().lower(),
  }


def _build_payroll_baseline_message(payroll_baseline: Dict[str, Any]) -> str:
  roles = payroll_baseline.get("payroll_basis_people_roles") or []
  role_count = len(roles)
  role_phrase = "role" if role_count == 1 else "roles"
  existing_count = 0
  inferred_count = 0
  for role in roles:
    if not isinstance(role, dict):
      continue
    source = str(role.get("source") or "").strip().lower()
    if source == "person":
      existing_count += 1
    elif source == "inferred_role":
      inferred_count += 1
  stage = str(payroll_baseline.get("business_stage") or "").strip().lower()
  clarification = (
    "This payroll estimate reflects the staffing plan already captured, including current team members and any additional roles discussed earlier where applicable."
  )
  if stage == "pre-revenue":
    clarification = (
      "This payroll estimate reflects the team needed to launch and operate in Year 1, including any planned hires from the staffing plan."
    )
  elif stage == "early-stage":
    clarification = (
      "This payroll estimate reflects the current staffing plan plus near-term additions as the business ramps and workload increases."
    )
  elif stage == "operating":
    clarification = (
      "This payroll estimate reflects the existing team plus any incremental additions from the staffing plan; it is not replacing the team already in place."
    )
  composition = ""
  if existing_count and inferred_count:
    composition = (
      f" That includes {existing_count} current team {'role' if existing_count == 1 else 'roles'} "
      f"and {inferred_count} additional planned {'role' if inferred_count == 1 else 'roles'}."
    )
  elif existing_count:
    composition = f" That includes {existing_count} current team {'role' if existing_count == 1 else 'roles'}."
  elif inferred_count:
    composition = (
      f" That includes {inferred_count} planned {'role' if inferred_count == 1 else 'roles'} from the staffing plan."
    )
  return (
    f"Based on the people plan already defined, a reasonable Year-1 payroll baseline is about "
    f"{_format_currency(payroll_baseline.get('baseline_payroll_year1'))} across {role_count} {role_phrase} in the plan.\n\n"
    f"{clarification}{composition}\n\n"
    "Does that broadly match your Year-1 payroll expectation, or should we adjust it because your actual payroll setup is materially different?"
  )


def _extract_zip_codes(text: Any) -> List[str]:
  import re

  raw = str(text or "").strip()
  if not raw:
    return []
  seen = set()
  out: List[str] = []
  for match in re.findall(r"\b(\d{5})(?:-\d{4})?\b", raw):
    code = str(match).strip()
    if code and code not in seen:
      seen.add(code)
      out.append(code)
  return out


def _is_us_country(value: Any) -> bool:
  raw = " ".join(str(value or "").strip().lower().split())
  if not raw:
    return True
  return raw in {"us", "u.s.", "usa", "u.s.a.", "united states", "united states of america"}


def _marketing_dependency_signature(
  *,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> str:
  signature_payload = {
    "business": {
      "address_zip": str((business_facts or {}).get("address_zip") or "").strip(),
      "address_state": str((business_facts or {}).get("address_state") or "").strip(),
      "address_country": str((business_facts or {}).get("address_country") or "").strip(),
    },
    "ops": {
      "consumer_type": str((ops_json or {}).get("consumer_type") or "").strip(),
      "business_type": str((ops_json or {}).get("business_type") or "").strip(),
      "business_naics_6": str((ops_json or {}).get("business_naics_6") or "").strip(),
      "unit_name": str((ops_json or {}).get("unit_name") or "").strip(),
      "unit_description": str((ops_json or {}).get("unit_description") or "").strip(),
      "unit_cadence": str((ops_json or {}).get("unit_cadence") or "").strip(),
      "unit_price": (ops_json or {}).get("unit_price"),
      "units_per_week_capacity": (ops_json or {}).get("units_per_week_capacity"),
      "units_per_period_capacity": (ops_json or {}).get("units_per_period_capacity"),
      "operating_periods_per_year": (ops_json or {}).get("operating_periods_per_year"),
      "utilization_rate": (ops_json or {}).get("utilization_rate"),
      "shipping_method": str((ops_json or {}).get("shipping_method") or "").strip(),
      "sales_modality": str((ops_json or {}).get("sales_modality") or "").strip(),
      "geographic_scope": str((ops_json or {}).get("geographic_scope") or "").strip(),
      "geographic_coverage": str((ops_json or {}).get("geographic_coverage") or "").strip(),
      "countries": (ops_json or {}).get("countries") or [],
      "competitive_advantage": str((ops_json or {}).get("competitive_advantage") or "").strip(),
      "capacity_driver": str((ops_json or {}).get("capacity_driver") or "").strip(),
      "primary_growth_lever": str((ops_json or {}).get("primary_growth_lever") or "").strip(),
    },
    "market": {
      "consumer_type": str((market_json or {}).get("consumer_type") or "").strip(),
      "selections": (market_json or {}).get("selections") or [],
      "b2b_naics_6": (market_json or {}).get("b2b_naics_6") or [],
      "b2b_size_bands": (market_json or {}).get("b2b_size_bands") or [],
      "b2b_age_bands": (market_json or {}).get("b2b_age_bands") or [],
      "marketing_plan_summary": str((market_json or {}).get("marketing_plan_summary") or "").strip(),
      "target_market_summary": str((market_json or {}).get("target_market_summary") or "").strip(),
    },
    "year1": {
      "company_revenue_total_year1": (financials_year1_json or {}).get("company_revenue_total_year1"),
      "lobs": (financials_year1_json or {}).get("lobs") or [],
    },
  }
  return json.dumps(signature_payload, sort_keys=True, ensure_ascii=False)


def _marketing_explicit_zips(
  *,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> List[str]:
  coverage = str((ops_json or {}).get("geographic_coverage") or "").strip()
  zips = _extract_zip_codes(coverage)
  address_zip = str((business_facts or {}).get("address_zip") or "").strip()
  if address_zip and address_zip not in zips:
    zips.append(address_zip)
  return zips


def _fetch_crosswalk_rows_for_zips(conn, zips: List[str]) -> List[Dict[str, Any]]:
  if not zips:
    return []
  placeholders = ",".join(["%s"] * len(zips))
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT zcta, state_fips, county_fips, geoid, zpop_pct, zhu_pct
      FROM zip_county_crosswalk
      WHERE zcta IN ({placeholders})
      """,
      tuple(zips),
    )
    return cur.fetchall() or []
  finally:
    cur.close()


def _fetch_crosswalk_rows_for_counties(conn, county_geoids: List[str]) -> List[Dict[str, Any]]:
  if not county_geoids:
    return []
  placeholders = ",".join(["%s"] * len(county_geoids))
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT zcta, state_fips, county_fips, geoid, zpop_pct, zhu_pct
      FROM zip_county_crosswalk
      WHERE geoid IN ({placeholders})
      """,
      tuple(county_geoids),
    )
    return cur.fetchall() or []
  finally:
    cur.close()


def _acs_zip_column_sets(conn) -> Tuple[set[str], set[str]]:
  cache = getattr(_acs_zip_column_sets, "_cache", None)
  if isinstance(cache, tuple) and len(cache) == 2:
    return cache  # type: ignore[return-value]
  cur = conn.cursor()
  try:
    cur.execute("SHOW COLUMNS FROM acs_zip_2022_part1")
    part1 = {str(row[0]) for row in (cur.fetchall() or [])}
    cur.execute("SHOW COLUMNS FROM acs_zip_2022_part2")
    part2 = {str(row[0]) for row in (cur.fetchall() or [])}
  finally:
    cur.close()
  result = (part1, part2)
  setattr(_acs_zip_column_sets, "_cache", result)
  return result


def _weighted_acs_total_for_code(
  *,
  conn,
  table_name: str,
  acs_code: str,
  zips: List[str],
  county_geoids: List[str],
  state_fips: List[str],
  weight_field: Optional[str],
) -> float:
  code = str(acs_code or "").strip()
  if not code:
    return 0.0
  cur = conn.cursor()
  try:
    if county_geoids:
      placeholders = ",".join(["%s"] * len(county_geoids))
      if weight_field:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0) * COALESCE(x.`{weight_field}`, 0) / 100.0), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE x.geoid IN ({placeholders})
          """,
          tuple(county_geoids),
        )
      else:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0)), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE x.geoid IN ({placeholders})
          """,
          tuple(county_geoids),
        )
    elif state_fips:
      placeholders = ",".join(["%s"] * len(state_fips))
      if weight_field:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0) * COALESCE(x.`{weight_field}`, 0) / 100.0), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE x.state_fips IN ({placeholders})
          """,
          tuple(state_fips),
        )
      else:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0)), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE x.state_fips IN ({placeholders})
          """,
          tuple(state_fips),
        )
    elif zips:
      placeholders = ",".join(["%s"] * len(zips))
      if weight_field:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0) * COALESCE(x.`{weight_field}`, 0) / 100.0), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE a.zcta IN ({placeholders})
          """,
          tuple(zips),
        )
      else:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0)), 0)
          FROM {table_name} a
          WHERE a.zcta IN ({placeholders})
          """,
          tuple(zips),
        )
    else:
      cur.execute(
        f"""
        SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0)), 0)
        FROM {table_name} a
        """
      )
    row = cur.fetchone()
  finally:
    cur.close()
  try:
    return float((row or [0])[0] or 0.0)
  except Exception:
    return 0.0


def _marketing_segment_weight_field(segment: str) -> Optional[str]:
  seg = str(segment or "").strip()
  if seg in {"Income", "Household Structure", "Housing Economics"}:
    return "zhu_pct"
  if seg:
    return "zpop_pct"
  return None


def _all_cbp_state_fips(conn) -> List[str]:
  cur = conn.cursor()
  try:
    cur.execute("SELECT DISTINCT state_fips FROM cbp_2022_raw ORDER BY state_fips ASC")
    return [str(row[0]).strip() for row in (cur.fetchall() or []) if str(row[0]).strip()]
  finally:
    cur.close()


def _state_fips_from_text(conn, text: str) -> List[str]:
  clean_text = str(text or "").strip().lower()
  if not clean_text:
    return []
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute("SELECT DISTINCT state_fips, state_name FROM cbp_2022_raw")
    rows = cur.fetchall() or []
  finally:
    cur.close()
  resolved: List[str] = []
  seen = set()
  for row in rows:
    state_name = str((row or {}).get("state_name") or "").strip().lower()
    state_fips = str((row or {}).get("state_fips") or "").strip()
    if not state_name or not state_fips:
      continue
    pattern = re.compile(rf"(?<![a-z]){re.escape(state_name)}(?![a-z])")
    if pattern.search(clean_text) and state_fips not in seen:
      seen.add(state_fips)
      resolved.append(state_fips)
  return sorted(resolved)


def _marketing_normalized_geography(
  *,
  conn,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> Dict[str, Any]:
  scope = str((ops_json or {}).get("geographic_scope") or "").strip().lower() or "local"
  coverage = str((ops_json or {}).get("geographic_coverage") or "").strip()
  address_zip = str((business_facts or {}).get("address_zip") or "").strip()
  address_state = str((business_facts or {}).get("address_state") or "").strip()

  explicit_zips = _extract_zip_codes(coverage)
  anchor_zip = address_zip if len(address_zip) == 5 and address_zip.isdigit() else ""
  crosswalk_seed_zips: List[str] = list(explicit_zips)
  if anchor_zip and anchor_zip not in crosswalk_seed_zips:
    crosswalk_seed_zips.append(anchor_zip)
  crosswalk_rows = _fetch_crosswalk_rows_for_zips(conn, crosswalk_seed_zips) if crosswalk_seed_zips else []

  county_geoids = sorted(
    {
      str(row.get("geoid") or "").strip()
      for row in crosswalk_rows
      if isinstance(row, dict) and str(row.get("geoid") or "").strip()
    }
  )
  state_fips = sorted(
    {
      str(row.get("state_fips") or "").strip()
      for row in crosswalk_rows
      if isinstance(row, dict) and str(row.get("state_fips") or "").strip()
    }
  )

  if scope == "national":
    state_fips = _all_cbp_state_fips(conn)
    county_geoids = []
  else:
    text_states = _state_fips_from_text(conn, coverage)
    if scope == "regional":
      for state in text_states:
        if state not in state_fips:
          state_fips.append(state)
      state_fips = sorted(set(state_fips))
    if scope == "local":
      # Local market sizing should anchor to county even if the client only confirmed
      # a city/metro phrase. Address ZIP gives us the county aggregation basis.
      if not county_geoids and anchor_zip:
        anchor_rows = _fetch_crosswalk_rows_for_zips(conn, [anchor_zip])
        county_geoids = sorted(
          {
            str(row.get("geoid") or "").strip()
            for row in anchor_rows
            if isinstance(row, dict) and str(row.get("geoid") or "").strip()
          }
        )
        for row in anchor_rows:
          state = str(row.get("state_fips") or "").strip()
          if state and state not in state_fips:
            state_fips.append(state)
        state_fips = sorted(set(state_fips))

  if not state_fips and address_state:
    cur = conn.cursor()
    try:
      cur.execute(
        """
        SELECT DISTINCT state_fips
        FROM cbp_2022_raw
        WHERE LOWER(state_name) = LOWER(%s)
        ORDER BY state_fips ASC
        """,
        (address_state,),
      )
      state_fips = [str(row[0]).strip() for row in (cur.fetchall() or []) if str(row[0]).strip()]
    finally:
      cur.close()

  return {
    "scope": scope,
    "coverage_summary": coverage,
    "anchor_zip": anchor_zip,
    "explicit_zip_basis": explicit_zips,
    "county_geoids": county_geoids,
    "state_fips": state_fips,
  }


def _build_b2c_marketing_basis(
  *,
  conn,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  normalized_geography: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  selections = market_json.get("selections")
  if not isinstance(selections, list) or not selections:
    return None

  geo = dict(normalized_geography or {})
  zips = list(geo.get("explicit_zip_basis") or [])
  county_geoids = list(geo.get("county_geoids") or [])
  state_fips = list(geo.get("state_fips") or [])
  part1_cols, part2_cols = _acs_zip_column_sets(conn)
  segment_basis: List[Dict[str, Any]] = []

  for selection in selections:
    if not isinstance(selection, dict):
      continue
    segment = str(selection.get("segment") or "").strip()
    codes = selection.get("acs_codes")
    if not segment or not isinstance(codes, list):
      continue
    clean_codes: List[str] = []
    seen_codes = set()
    for code in codes:
      acs_code = str(code or "").strip()
      if not acs_code or acs_code in seen_codes:
        continue
      if acs_code not in part1_cols and acs_code not in part2_cols:
        continue
      seen_codes.add(acs_code)
      clean_codes.append(acs_code)
    if not clean_codes:
      continue
    weight_field = _marketing_segment_weight_field(segment)
    total = 0.0
    for acs_code in clean_codes:
      table_name = "acs_zip_2022_part1" if acs_code in part1_cols else "acs_zip_2022_part2"
      total += _weighted_acs_total_for_code(
        conn=conn,
        table_name=table_name,
        acs_code=acs_code,
        zips=zips,
        county_geoids=county_geoids,
        state_fips=state_fips,
        weight_field=weight_field if (zips or county_geoids or state_fips) else None,
      )
    segment_basis.append(
      {
        "segment": segment,
        "acs_codes": clean_codes,
        "basis_count": float(max(0.0, total)),
        "weight_basis": "housing" if weight_field == "zhu_pct" else "population",
      }
    )

  if not segment_basis:
    return None

  return {
    "basis_type": "b2c",
    "scope": str((geo.get("scope") or (ops_json or {}).get("geographic_scope") or "").strip().lower() or "local"),
    "anchor_zip": str(geo.get("anchor_zip") or "").strip(),
    "zip_basis": zips,
    "county_geoids": county_geoids,
    "state_fips": state_fips,
    "coverage_summary": str(geo.get("coverage_summary") or "").strip(),
    "segment_basis_counts": segment_basis,
  }


def _state_fips_from_basis(
  *,
  conn,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> List[str]:
  normalized = _marketing_normalized_geography(conn=conn, ops_json=ops_json, business_facts=business_facts)
  return list(normalized.get("state_fips") or [])


_BDS_SIZE_BUCKET_MAP = {
  "1-4": "a) 1 to 4",
  "5-9": "b) 5 to 9",
  "10-19": "c) 10 to 19",
  "20-99": "d) 20 to 99",
  "100-499": "e) 100 to 499",
  "500-999": "f) 500 to 999",
  "1000-2499": "g) 1000 to 2499",
  "2500-4999": "h) 2500 to 4999",
  "5000-9999": "i) 5000 to 9999",
  "10000+": "j) 10000+",
}

_BDS_AGE_BUCKET_MAP = {
  "0": "a) 0",
  "1": "b) 1",
  "2": "c) 2",
  "3": "d) 3",
  "4": "e) 4",
  "5": "f) 5",
  "6-10": "g) 6 to 10",
  "11-15": "h) 11 to 15",
  "16-20": "i) 16 to 20",
  "21-25": "j) 21 to 25",
  "26+": "k) 26+",
}


def _cbp_exact_hits_for_codes(
  *,
  conn,
  naics_codes: List[str],
  state_fips: List[str],
) -> List[Dict[str, Any]]:
  if not naics_codes or not state_fips:
    return []
  code_placeholders = ",".join(["%s"] * len(naics_codes))
  state_placeholders = ",".join(["%s"] * len(state_fips))
  params: List[Any] = [*naics_codes, *state_fips]
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT naics, SUM(estab) AS estab_total, SUM(emp) AS emp_total
      FROM cbp_2022_raw
      WHERE naics IN ({code_placeholders})
        AND state_fips IN ({state_placeholders})
      GROUP BY naics
      """,
      tuple(params),
    )
    return cur.fetchall() or []
  finally:
    cur.close()


def _cbp_parent_hit(
  *,
  conn,
  prefix: str,
  state_fips: List[str],
) -> Optional[Dict[str, Any]]:
  if not prefix or not state_fips:
    return None
  state_placeholders = ",".join(["%s"] * len(state_fips))
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT naics, SUM(estab) AS estab_total, SUM(emp) AS emp_total
      FROM cbp_2022_raw
      WHERE naics = %s
        AND state_fips IN ({state_placeholders})
      GROUP BY naics
      """,
      tuple([prefix, *state_fips]),
    )
    row = cur.fetchone()
  finally:
    cur.close()
  return row if isinstance(row, dict) else None


def _latest_bds_year(conn, *, table_name: str) -> Optional[int]:
  cur = conn.cursor()
  try:
    cur.execute(f"SELECT MAX(year) FROM {table_name}")
    row = cur.fetchone()
  finally:
    cur.close()
  try:
    return int((row or [None])[0])
  except Exception:
    return None


def _aggregate_bds_signal(
  *,
  conn,
  table_name: str,
  bucket_column: str,
  selected_bucket_labels: List[str],
  naics4_prefixes: List[int],
  exclude_bucket: Optional[str] = None,
) -> Dict[str, Any]:
  if not naics4_prefixes:
    return {
      "latest_year": None,
      "selected_buckets": [],
      "selected_firms": 0.0,
      "total_firms": 0.0,
      "selected_share": 0.0,
    }
  latest_year = _latest_bds_year(conn, table_name=table_name)
  if latest_year is None:
    return {
      "latest_year": None,
      "selected_buckets": [],
      "selected_firms": 0.0,
      "total_firms": 0.0,
      "selected_share": 0.0,
    }
  placeholders = ",".join(["%s"] * len(naics4_prefixes))
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT `{bucket_column}` AS bucket_label, SUM(firms) AS firms_total
      FROM {table_name}
      WHERE year = %s
        AND vcnaics4 IN ({placeholders})
      GROUP BY `{bucket_column}`
      """,
      tuple([latest_year, *naics4_prefixes]),
    )
    rows = cur.fetchall() or []
  finally:
    cur.close()
  total = 0.0
  selected = 0.0
  cleaned_selected = {str(label).strip() for label in selected_bucket_labels if str(label).strip()}
  for row in rows:
    label = str(row.get("bucket_label") or "").strip()
    try:
      firms_total = float(row.get("firms_total") or 0.0)
    except Exception:
      firms_total = 0.0
    if exclude_bucket and label == exclude_bucket:
      continue
    total += firms_total
    if label in cleaned_selected:
      selected += firms_total
  share = (selected / total) if total > 0 else 0.0
  return {
    "latest_year": latest_year,
    "selected_buckets": sorted(cleaned_selected),
    "selected_firms": float(max(0.0, selected)),
    "total_firms": float(max(0.0, total)),
    "selected_share": float(max(0.0, share)),
  }


def _build_b2b_marketing_basis(
  *,
  conn,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  normalized_geography: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  selected_codes = []
  seen_codes = set()
  for value in market_json.get("b2b_naics_6") or []:
    code = str(value or "").strip()
    if len(code) == 6 and code.isdigit() and code not in seen_codes:
      seen_codes.add(code)
      selected_codes.append(code)
  if not selected_codes:
    return None

  state_fips = list((normalized_geography or {}).get("state_fips") or [])
  if not state_fips:
    return None

  cbp_match_level = 6
  cbp_source_codes: List[str] = []
  cbp_establishments_total = 0.0
  cbp_employee_total = 0.0

  exact_hits = _cbp_exact_hits_for_codes(conn=conn, naics_codes=selected_codes, state_fips=state_fips)
  if exact_hits:
    cbp_source_codes = [str(row.get("naics") or "").strip() for row in exact_hits if str(row.get("naics") or "").strip()]
    for row in exact_hits:
      try:
        cbp_establishments_total += float(row.get("estab_total") or 0.0)
      except Exception:
        pass
      try:
        cbp_employee_total += float(row.get("emp_total") or 0.0)
      except Exception:
        pass
  else:
    for level in (5, 4, 3, 2):
      prefixes = {code[:level] for code in selected_codes if len(code) >= level}
      if len(prefixes) != 1:
        continue
      prefix = next(iter(prefixes))
      parent_hit = _cbp_parent_hit(conn=conn, prefix=prefix, state_fips=state_fips)
      if not parent_hit:
        continue
      cbp_match_level = level
      cbp_source_codes = [prefix]
      try:
        cbp_establishments_total = float(parent_hit.get("estab_total") or 0.0)
      except Exception:
        cbp_establishments_total = 0.0
      try:
        cbp_employee_total = float(parent_hit.get("emp_total") or 0.0)
      except Exception:
        cbp_employee_total = 0.0
      break

  naics4_prefixes = sorted({int(code[:4]) for code in selected_codes})
  selected_size_labels = [_BDS_SIZE_BUCKET_MAP.get(str(band).strip()) for band in (market_json.get("b2b_size_bands") or [])]
  selected_size_labels = [label for label in selected_size_labels if label]
  selected_age_labels = [_BDS_AGE_BUCKET_MAP.get(str(band).strip()) for band in (market_json.get("b2b_age_bands") or [])]
  selected_age_labels = [label for label in selected_age_labels if label]

  size_signal = _aggregate_bds_signal(
    conn=conn,
    table_name="bds_firm_size",
    bucket_column="firm_size_bucket",
    selected_bucket_labels=selected_size_labels,
    naics4_prefixes=naics4_prefixes,
  )
  age_signal = _aggregate_bds_signal(
    conn=conn,
    table_name="bds_firm_age",
    bucket_column="firm_age_bucket",
    selected_bucket_labels=selected_age_labels,
    naics4_prefixes=naics4_prefixes,
    exclude_bucket="l) Left Censored",
  )

  return {
    "basis_type": "b2b",
    "scope": str(((normalized_geography or {}).get("scope") or (ops_json or {}).get("geographic_scope") or "").strip().lower() or "local"),
    "anchor_zip": str((normalized_geography or {}).get("anchor_zip") or "").strip(),
    "county_geoids": (normalized_geography or {}).get("county_geoids") or [],
    "state_fips": state_fips,
    "coverage_summary": str((normalized_geography or {}).get("coverage_summary") or "").strip(),
    "cbp_basis": {
      "match_level": cbp_match_level,
      "source_codes": cbp_source_codes,
      "establishments_total": float(max(0.0, cbp_establishments_total)),
      "employees_total": float(max(0.0, cbp_employee_total)),
    },
    "size_signal": size_signal,
    "age_signal": age_signal,
    "selected_naics_6": selected_codes,
    "selected_naics_4": [str(value) for value in naics4_prefixes],
  }


def _required_units_year1(financials_year1_json: Dict[str, Any]) -> float:
  total_units = 0.0
  lobs = (financials_year1_json or {}).get("lobs")
  if not isinstance(lobs, list):
    return 0.0
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      try:
        avg_units = float(product.get("avg_units_per_period_year1") or product.get("avg_units_per_week_year1") or 0.0)
      except Exception:
        avg_units = 0.0
      try:
        periods = float(product.get("operating_periods_per_year") or product.get("operating_weeks_per_year") or 0.0)
      except Exception:
        periods = 0.0
      total_units += max(0.0, avg_units) * max(0.0, periods)
  return float(max(0.0, total_units))


def _build_marketing_estimate_context(
  *,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  marketing_basis = dict(marketing_model_json or {})
  b2b_basis = dict(marketing_basis.get("b2b_basis_counts") or {})
  cbp_basis = dict(b2b_basis.get("cbp_basis") or {})
  market_basis_type = str(marketing_basis.get("market_basis_type") or "").strip().lower()
  normalized_geography = marketing_basis.get("geography_basis") or {}
  scope = str((normalized_geography or {}).get("scope") or "").strip().lower()
  return {
    "business": {
      "name": business_facts.get("name"),
      "address_zip": business_facts.get("address_zip"),
      "address_state": business_facts.get("address_state"),
      "address_country": business_facts.get("address_country"),
    },
    "ops": {
      "consumer_type": ops_json.get("consumer_type"),
      "business_type": ops_json.get("business_type"),
      "business_naics_6": ops_json.get("business_naics_6"),
      "unit_name": ops_json.get("unit_name"),
      "unit_description": ops_json.get("unit_description"),
      "unit_cadence": ops_json.get("unit_cadence"),
      "unit_price": ops_json.get("unit_price"),
      "units_per_week_capacity": ops_json.get("units_per_week_capacity"),
      "units_per_period_capacity": ops_json.get("units_per_period_capacity"),
      "operating_periods_per_year": ops_json.get("operating_periods_per_year"),
      "utilization_rate": ops_json.get("utilization_rate"),
      "shipping_method": ops_json.get("shipping_method"),
      "sales_modality": ops_json.get("sales_modality"),
      "geographic_scope": ops_json.get("geographic_scope"),
      "geographic_coverage": ops_json.get("geographic_coverage"),
      "capacity_driver": ops_json.get("capacity_driver"),
      "primary_growth_lever": ops_json.get("primary_growth_lever"),
      "competitive_advantage": ops_json.get("competitive_advantage"),
    },
    "market": {
      "consumer_type": market_json.get("consumer_type"),
      "target_market_summary": market_json.get("target_market_summary"),
      "marketing_plan_summary": market_json.get("marketing_plan_summary"),
      "b2b_industry_terms": market_json.get("b2b_industry_terms") or [],
      "b2b_naics_6": market_json.get("b2b_naics_6") or [],
      "b2b_size_bands": market_json.get("b2b_size_bands") or [],
      "b2b_age_bands": market_json.get("b2b_age_bands") or [],
      "selections": market_json.get("selections") or [],
    },
    "people": {
      "key_people_summary": people_json.get("key_people_summary"),
      "people": people_json.get("people") or [],
      "inferred_roles": people_json.get("inferred_roles") or [],
    },
    "financials_year1_json": financials_year1_json or {},
    "normalized_geography": normalized_geography,
    "market_measurement_guidance": {
      "combined_reachable_market_reporting_only": True,
      "combined_reachable_market_note": (
        "reachable_market is a high-level planning/reporting field only. "
        "Do not treat it as a literal additive TAM count when B2C and B2B are both present."
      ),
      "b2c_measurement_unit": "people/customers",
      "b2b_measurement_unit": "firms",
      "mixed_case_note": (
        "In mixed models, keep B2C people reach and B2B firm reach conceptually separate. "
        "Do not use neat or symmetrical splits unless the observed data truly supports them."
      ) if market_basis_type == "mixed" else "",
      "scope_note": (
        "Regional and national B2B reach must stay grounded in the observed state-level CBP firm universe."
        if scope in {"regional", "national"} else
        "Local B2B reach must still stay grounded in the observed state-level CBP firm universe while respecting the tighter local footprint."
      ),
      "b2b_observed_establishments_total": cbp_basis.get("establishments_total"),
      "b2b_observed_employees_total": cbp_basis.get("employees_total"),
      "b2b_cbp_match_level": cbp_basis.get("match_level"),
    },
    "marketing_model_basis": {
      "version": marketing_basis.get("version"),
      "market_basis_type": marketing_basis.get("market_basis_type"),
      "geography_basis": normalized_geography,
      "b2c_basis_counts": marketing_basis.get("b2c_basis_counts") or [],
      "b2b_basis_counts": b2b_basis,
      "required_revenue_year1": marketing_basis.get("required_revenue_year1"),
      "required_units_year1": marketing_basis.get("required_units_year1"),
      "reachable_market": marketing_basis.get("reachable_market"),
      "reachable_market_b2c": marketing_basis.get("reachable_market_b2c"),
      "reachable_market_b2b": marketing_basis.get("reachable_market_b2b"),
    },
  }


def _marketing_intensity_from_percent(percent: float) -> str:
  value = float(max(0.0, percent))
  if value >= 0.12:
    return "very_high"
  if value >= 0.08:
    return "high"
  if value >= 0.04:
    return "medium"
  return "low"


def _fallback_marketing_estimate(
  *,
  base_model: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  fallback_reason: str,
) -> Optional[Dict[str, Any]]:
  revenue_year1 = float(base_model.get("required_revenue_year1") or 0.0)
  if revenue_year1 <= 0:
    return None

  market_basis_type = str(base_model.get("market_basis_type") or "").strip().lower() or "consumer"
  stage = str((ops_json or {}).get("business_stage") or "").strip().lower()
  scope = str(((base_model.get("geography_basis") or {}).get("scope") or (ops_json or {}).get("geographic_scope") or "")).strip().lower()
  sales_modality = str((ops_json or {}).get("sales_modality") or "").strip().lower()
  shipping_method = str((ops_json or {}).get("shipping_method") or "").strip().lower()
  capacity_driver = str((ops_json or {}).get("capacity_driver") or "").strip().lower()
  unit_cadence = str((ops_json or {}).get("unit_cadence") or "").strip().lower()
  unit_price = _safe_float((ops_json or {}).get("unit_price")) or 0.0
  required_units_year1 = float(base_model.get("required_units_year1") or 0.0)

  baseline_percent = 0.0

  if stage == "operating":
    baseline_percent += 0.035
  elif stage == "pre-revenue":
    baseline_percent += 0.06
  else:
    baseline_percent += 0.045

  if market_basis_type == "consumer":
    baseline_percent += 0.025
  elif market_basis_type == "mixed":
    baseline_percent += 0.02
  else:
    baseline_percent += 0.012

  if "online" in sales_modality or "ecommerce" in sales_modality:
    baseline_percent += 0.018
  elif "hybrid" in sales_modality:
    baseline_percent += 0.01
  elif "in-person" in shipping_method or "shop" in shipping_method or "facility" in shipping_method:
    baseline_percent += 0.004

  if scope == "regional":
    baseline_percent += 0.008
  elif scope == "national":
    baseline_percent += 0.015
  elif scope == "local":
    baseline_percent += 0.002

  if unit_price >= 1000:
    baseline_percent -= 0.012
  elif unit_price >= 500:
    baseline_percent -= 0.006
  elif unit_price <= 75:
    baseline_percent += 0.015
  elif unit_price <= 200:
    baseline_percent += 0.008

  if capacity_driver == "labor":
    baseline_percent -= 0.004

  marketing_plan_text = " ".join(
    [
      str((market_json or {}).get("marketing_plan_summary") or ""),
      str((market_json or {}).get("target_market_summary") or ""),
      str((ops_json or {}).get("primary_growth_lever") or ""),
      str((ops_json or {}).get("competitive_advantage") or ""),
    ]
  ).lower()
  channel_terms = (
    "google",
    "search",
    "maps",
    "instagram",
    "facebook",
    "linkedin",
    "referral",
    "partnership",
    "delivery",
    "ads",
    "seo",
  )
  baseline_percent += min(0.015, 0.003 * sum(1 for term in channel_terms if term in marketing_plan_text))
  baseline_percent = float(min(0.18, max(0.025, baseline_percent)))

  if unit_cadence == "weekly":
    repeat_units_per_entity = 10.0 if market_basis_type == "b2b" else 6.0
  elif unit_cadence == "monthly":
    repeat_units_per_entity = 6.0 if market_basis_type == "b2b" else 2.5
  elif unit_cadence == "annual":
    repeat_units_per_entity = 1.2
  else:
    repeat_units_per_entity = 3.0 if market_basis_type == "b2b" else 2.0

  expected_entities_year1 = max(1.0, required_units_year1 / max(1.0, repeat_units_per_entity)) if required_units_year1 > 0 else 1.0

  positive_b2c_counts = [
    float(item.get("basis_count") or 0.0)
    for item in (base_model.get("b2c_basis_counts") or [])
    if isinstance(item, dict) and float(item.get("basis_count") or 0.0) > 0
  ]
  b2c_anchor = max(positive_b2c_counts) if positive_b2c_counts else 0.0
  b2c_ratio = 0.001 if scope == "national" else 0.003 if scope == "regional" else 0.008
  reachable_market_b2c = 0.0
  if market_basis_type in {"consumer", "mixed"}:
    if b2c_anchor > 0:
      reachable_market_b2c = max(expected_entities_year1 * 4.0, b2c_anchor * b2c_ratio)
    else:
      reachable_market_b2c = expected_entities_year1 * 6.0

  cbp_basis = dict((base_model.get("b2b_basis_counts") or {}).get("cbp_basis") or {})
  observed_establishments = float(cbp_basis.get("establishments_total") or 0.0)
  b2b_ratio = 0.02 if scope == "national" else 0.01 if scope == "regional" else 0.004
  reachable_market_b2b = 0.0
  if market_basis_type in {"b2b", "mixed"}:
    if observed_establishments > 0:
      reachable_market_b2b = max(expected_entities_year1 * 1.5, observed_establishments * b2b_ratio)
      reachable_market_b2b = min(observed_establishments, reachable_market_b2b)
    else:
      reachable_market_b2b = expected_entities_year1 * 3.0

  if market_basis_type == "consumer":
    combined_reachable_market = max(reachable_market_b2c, expected_entities_year1 * 4.0)
  elif market_basis_type == "b2b":
    combined_reachable_market = max(reachable_market_b2b, expected_entities_year1 * 2.0)
  else:
    combined_reachable_market = max(reachable_market_b2c, reachable_market_b2b, expected_entities_year1 * 5.0)

  capture_rate_year1 = 0.0
  if combined_reachable_market > 0:
    capture_rate_year1 = min(1.0, max(0.0, expected_entities_year1 / combined_reachable_market))

  business_label = str((ops_json or {}).get("business_type") or business_facts.get("business_name") or "this business").strip() or "this business"
  rationale = (
    f"Deterministic fallback used because the GPT marketing estimator did not return an accepted result "
    f"({fallback_reason}). The baseline was anchored to the saved operating context for {business_label}, "
    f"including market type={market_basis_type}, scope={scope or 'unspecified'}, sales modality={sales_modality or shipping_method or 'unspecified'}, "
    f"unit price={_format_currency(unit_price)}, and Year-1 revenue={_format_currency(revenue_year1)}. "
    f"The result is a conservative planning baseline intended to keep intake moving without treating broad observed market ceilings as directly reachable demand."
  )

  return {
    "reachable_market": float(max(1.0, combined_reachable_market)),
    "reachable_market_b2c": float(max(0.0, reachable_market_b2c)),
    "reachable_market_b2b": float(max(0.0, reachable_market_b2b)),
    "capture_rate_year1": float(capture_rate_year1),
    "expected_customers_or_clients_year1": float(max(1.0, expected_entities_year1)),
    "expected_units_year1": float(max(0.0, required_units_year1)),
    "marketing_intensity": _marketing_intensity_from_percent(baseline_percent),
    "baseline_marketing_percent": float(baseline_percent),
    "brief_rationale": rationale,
    "estimation_method": "deterministic_fallback",
    "estimation_status": "fallback_used",
    "estimation_warning": f"GPT marketing baseline unavailable; fallback used ({fallback_reason}).",
  }


def _compute_marketing_model_json(
  *,
  conn,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  existing_marketing_model_json: Dict[str, Any],
  estimate_marketing_baseline_from_context,
) -> Dict[str, Any]:
  signature = _marketing_dependency_signature(
    ops_json=ops_json,
    market_json=market_json,
    financials_year1_json=financials_year1_json,
    business_facts=business_facts,
  )
  base_model: Dict[str, Any] = {
    "version": 3,
    "signature": signature,
    "market_basis_type": str((market_json or {}).get("consumer_type") or (ops_json or {}).get("consumer_type") or "").strip().lower() or "consumer",
    "geography_basis": {},
    "b2c_basis_counts": [],
    "b2b_basis_counts": {},
    "required_revenue_year1": float((financials_year1_json or {}).get("company_revenue_total_year1") or 0.0),
    "required_units_year1": _required_units_year1(financials_year1_json or {}),
    "reachable_market_b2c": None,
    "reachable_market_b2b": None,
    "missing_dependencies": [],
    "ready": False,
    "estimation_method": "",
    "estimation_status": "",
    "estimation_warning": "",
  }
  normalized_geography = _marketing_normalized_geography(
    conn=conn,
    ops_json=ops_json,
    business_facts=business_facts,
  )
  base_model["geography_basis"] = normalized_geography

  if not _is_us_country((business_facts or {}).get("address_country")):
    base_model["missing_dependencies"] = ["us_only_quantified_market"]
    return base_model

  market_basis_type = str(base_model.get("market_basis_type") or "").strip().lower()
  b2c_basis = None
  b2b_basis = None
  if market_basis_type in {"consumer", "mixed"}:
    b2c_basis = _build_b2c_marketing_basis(
      conn=conn,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      normalized_geography=normalized_geography,
    )
    if isinstance(b2c_basis, dict):
      base_model["b2c_basis_counts"] = b2c_basis.get("segment_basis_counts") or []
      base_model["geography_basis"]["zip_basis"] = b2c_basis.get("zip_basis") or []
      base_model["geography_basis"]["county_geoids"] = b2c_basis.get("county_geoids") or []
      base_model["geography_basis"]["state_fips"] = b2c_basis.get("state_fips") or base_model["geography_basis"].get("state_fips") or []
      base_model["geography_basis"]["scope"] = b2c_basis.get("scope")
  if market_basis_type in {"b2b", "mixed"}:
    b2b_basis = _build_b2b_marketing_basis(
      conn=conn,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      normalized_geography=normalized_geography,
    )
    if isinstance(b2b_basis, dict):
      base_model["b2b_basis_counts"] = {
        "cbp_basis": b2b_basis.get("cbp_basis") or {},
        "size_signal": b2b_basis.get("size_signal") or {},
        "age_signal": b2b_basis.get("age_signal") or {},
        "state_fips": b2b_basis.get("state_fips") or [],
        "selected_naics_6": b2b_basis.get("selected_naics_6") or [],
        "selected_naics_4": b2b_basis.get("selected_naics_4") or [],
      }
      base_model["geography_basis"]["state_fips"] = b2b_basis.get("state_fips") or []
      base_model["geography_basis"]["scope"] = b2b_basis.get("scope")

  has_b2c = bool(base_model.get("b2c_basis_counts"))
  has_b2b = bool((base_model.get("b2b_basis_counts") or {}).get("cbp_basis") or (base_model.get("b2b_basis_counts") or {}).get("size_signal") or (base_model.get("b2b_basis_counts") or {}).get("age_signal"))
  if market_basis_type == "consumer" and not has_b2c:
    base_model["missing_dependencies"] = ["b2c_market_basis"]
    fallback = _fallback_marketing_estimate(
      base_model=base_model,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      fallback_reason="missing_b2c_market_basis",
    )
    if isinstance(fallback, dict):
      baseline_percent = float(fallback.get("baseline_marketing_percent") or 0.0)
      base_model.update(
        {
          **fallback,
          "baseline_marketing_percent": baseline_percent,
          "baseline_marketing": float(base_model["required_revenue_year1"] * baseline_percent),
          "marketing_basis_summary": str(fallback.get("brief_rationale") or "").strip(),
          "ready": True,
        }
      )
    return base_model
  if market_basis_type == "b2b" and not has_b2b:
    base_model["missing_dependencies"] = ["b2b_market_basis"]
    fallback = _fallback_marketing_estimate(
      base_model=base_model,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      fallback_reason="missing_b2b_market_basis",
    )
    if isinstance(fallback, dict):
      baseline_percent = float(fallback.get("baseline_marketing_percent") or 0.0)
      base_model.update(
        {
          **fallback,
          "baseline_marketing_percent": baseline_percent,
          "baseline_marketing": float(base_model["required_revenue_year1"] * baseline_percent),
          "marketing_basis_summary": str(fallback.get("brief_rationale") or "").strip(),
          "ready": True,
        }
      )
    return base_model
  if market_basis_type == "mixed" and not (has_b2c or has_b2b):
    base_model["missing_dependencies"] = ["market_basis"]
    fallback = _fallback_marketing_estimate(
      base_model=base_model,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      fallback_reason="missing_market_basis",
    )
    if isinstance(fallback, dict):
      baseline_percent = float(fallback.get("baseline_marketing_percent") or 0.0)
      base_model.update(
        {
          **fallback,
          "baseline_marketing_percent": baseline_percent,
          "baseline_marketing": float(base_model["required_revenue_year1"] * baseline_percent),
          "marketing_basis_summary": str(fallback.get("brief_rationale") or "").strip(),
          "ready": True,
        }
      )
    return base_model
  if base_model["required_revenue_year1"] <= 0:
    base_model["missing_dependencies"] = ["required_revenue_year1"]
    return base_model

  existing_model = dict(existing_marketing_model_json or {})
  if (
    int(existing_model.get("version") or 0) == int(base_model.get("version") or 0)
    and str(existing_model.get("signature") or "").strip() == signature
    and existing_model.get("ready") is True
    and existing_model.get("baseline_marketing_percent") is not None
  ):
    for key in (
      "reachable_market",
      "reachable_market_b2c",
      "reachable_market_b2b",
      "capture_rate_year1",
      "expected_customers_or_clients_year1",
      "expected_units_year1",
      "marketing_intensity",
      "baseline_marketing_percent",
      "baseline_marketing",
      "marketing_basis_summary",
      "demand_supports_required_units",
      "estimation_method",
      "estimation_status",
      "estimation_warning",
    ):
      if key in existing_model:
        base_model[key] = existing_model.get(key)
    base_model["ready"] = True
    return base_model

  estimated = estimate_marketing_baseline_from_context(
    marketing_estimate_context=_build_marketing_estimate_context(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      marketing_model_json=base_model,
    )
  )
  if not isinstance(estimated, dict):
    estimated = _fallback_marketing_estimate(
      base_model=base_model,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      fallback_reason="estimator_returned_no_accepted_result",
    )
  if not isinstance(estimated, dict):
    return base_model

  baseline_percent = float(estimated.get("baseline_marketing_percent") or 0.0)
  baseline_amount = float(base_model["required_revenue_year1"] * baseline_percent)
  expected_units_year1 = float(estimated.get("expected_units_year1") or 0.0)
  reachable_market = float(estimated.get("reachable_market") or 0.0)
  reachable_market_b2c = _safe_float(estimated.get("reachable_market_b2c"))
  reachable_market_b2b = _safe_float(estimated.get("reachable_market_b2b"))
  if market_basis_type == "consumer":
    reachable_market_b2c = reachable_market
    reachable_market_b2b = 0.0
  elif market_basis_type == "b2b":
    reachable_market_b2c = 0.0
    reachable_market_b2b = reachable_market
  else:
    if reachable_market_b2c is None:
      reachable_market_b2c = 0.0
    if reachable_market_b2b is None:
      reachable_market_b2b = 0.0
  base_model.update(
    {
      "reachable_market": reachable_market,
      "reachable_market_b2c": max(0.0, reachable_market_b2c),
      "reachable_market_b2b": max(0.0, reachable_market_b2b),
      "capture_rate_year1": float(estimated.get("capture_rate_year1") or 0.0),
      "expected_customers_or_clients_year1": float(estimated.get("expected_customers_or_clients_year1") or 0.0),
      "expected_units_year1": expected_units_year1,
      "marketing_intensity": str(estimated.get("marketing_intensity") or "").strip() or "medium",
      "baseline_marketing_percent": baseline_percent,
      "baseline_marketing": baseline_amount,
      "marketing_basis_summary": str(estimated.get("brief_rationale") or "").strip(),
      "demand_supports_required_units": expected_units_year1 >= float(base_model.get("required_units_year1") or 0.0),
      "estimation_method": str(estimated.get("estimation_method") or "gpt_estimate").strip() or "gpt_estimate",
      "estimation_status": str(estimated.get("estimation_status") or "gpt_estimate_ready").strip() or "gpt_estimate_ready",
      "estimation_warning": str(estimated.get("estimation_warning") or "").strip(),
      "ready": True,
    }
  )
  return base_model


def _resolve_marketing_model_or_raise(
  *,
  conn,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  existing_marketing_model_json: Dict[str, Any],
  estimate_marketing_baseline_from_context,
) -> Dict[str, Any]:
  marketing_model = _compute_marketing_model_json(
    conn=conn,
    ops_json=ops_json,
    market_json=market_json,
    people_json=people_json,
    financials_year1_json=financials_year1_json,
    business_facts=business_facts,
    existing_marketing_model_json=existing_marketing_model_json,
    estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
  )
  if isinstance(marketing_model, dict) and marketing_model.get("ready") is True:
    return marketing_model
  raise RuntimeError("Unable to resolve a Year-1 marketing baseline from the current market and operating context.")


def _build_marketing_baseline_message(marketing_baseline: Dict[str, Any]) -> str:
  return (
    f"A reasonable Year-1 marketing baseline is about "
    f"{_format_percent(marketing_baseline.get('baseline_marketing_percent'))} of revenue, which puts your projected Year-1 marketing spend around "
    f"{_format_currency(marketing_baseline.get('baseline_marketing'))}.\n\n"
    "Does that broadly match what it will take to attract and convert customers in Year 1, or should we adjust it because your marketing spend will be materially different?"
  )


def _normalize_marketing_reply_to_fields(
  *,
  reply: Dict[str, Any],
  baseline: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  baseline_amount = float(baseline.get("baseline_marketing") or 0.0)
  revenue_year1 = float(baseline.get("required_revenue_year1") or 0.0)
  baseline_percent = float(baseline.get("baseline_marketing_percent") or 0.0)
  intent_type = str(reply.get("intent_type") or "").strip()

  if intent_type == "accept_baseline":
    total = baseline_amount
  elif intent_type == "set_total":
    try:
      total = float(reply.get("marketing_total_year1"))
    except Exception:
      return None
  elif intent_type == "set_percent":
    try:
      percent = float(reply.get("marketing_percent_of_revenue"))
    except Exception:
      return None
    total = float(revenue_year1 * percent)
  elif intent_type == "set_adjustment":
    try:
      adjustment = float(reply.get("marketing_adjustment"))
    except Exception:
      return None
    total = baseline_amount + adjustment
  else:
    return None

  total = max(0.0, float(total))
  adjustment = float(total - baseline_amount)
  percent_total = float(total / revenue_year1) if revenue_year1 > 0 else baseline_percent
  return {
    "baseline_marketing_percent": baseline_percent,
    "baseline_marketing": baseline_amount,
    "marketing_adjustment": adjustment,
    "marketing_total_year1": total,
    "marketing_percent_of_revenue": percent_total,
  }


def _sync_marketing_field_family(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  revenue = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
  baseline_percent = _safe_float(next_financials.get("baseline_marketing_percent"))
  baseline_amount = _safe_float(next_financials.get("baseline_marketing"))
  if baseline_percent is None:
    baseline_percent = _safe_float((marketing_model_json or {}).get("baseline_marketing_percent"))
  if baseline_amount is None:
    baseline_amount = _safe_float((marketing_model_json or {}).get("baseline_marketing"))
  if baseline_percent is None and baseline_amount is not None and revenue and revenue > 0:
    baseline_percent = baseline_amount / revenue
  if baseline_amount is None and baseline_percent is not None and revenue is not None:
    baseline_amount = revenue * baseline_percent

  total = _safe_float(next_financials.get("marketing_total_year1"))
  percent_total = _safe_float(next_financials.get("marketing_percent_of_revenue"))
  if total is None and percent_total is not None and revenue is not None:
    total = revenue * percent_total
  if percent_total is None and total is not None and revenue and revenue > 0:
    percent_total = total / revenue

  if total is None:
    return next_financials

  next_financials["marketing_total_year1"] = total
  if percent_total is not None:
    next_financials["marketing_percent_of_revenue"] = percent_total
  if baseline_percent is not None:
    next_financials["baseline_marketing_percent"] = baseline_percent
  if baseline_amount is not None:
    next_financials["baseline_marketing"] = baseline_amount
  if baseline_amount is not None:
    next_financials["marketing_adjustment"] = total - baseline_amount
  return next_financials

def _build_initial_lease_message() -> str:
  return (
    "Now let's capture any leased or rented equipment or space beyond your main rent. "
    "What monthly amount should we use for any leased equipment, vehicles, servers, or additional space you do not own? "
    "If there is none, use 0."
  )


def _financials_business_stage(shared_context: Dict[str, Any]) -> str:
  operating_model = (shared_context or {}).get("operating_model") or {}
  if not isinstance(operating_model, dict):
    return ""
  return str(operating_model.get("business_stage") or "").strip().lower()


def _build_monthly_rent_message(*, shared_context: Dict[str, Any]) -> str:
  stage = _financials_business_stage(shared_context)
  if stage == "operating":
    return (
      "What do you pay each month for the space you use to run the business, like an office, storefront, clinic, kitchen, warehouse, or similar dedicated space?"
    )
  return (
    "What do you pay each month for any dedicated business space, like an office, storefront, clinic, kitchen, warehouse, or similar facility? "
    "If you are not paying for separate space yet but already know what it will cost when you open, use that amount."
  )


def _build_future_rent_message(
  *,
  shared_context: Dict[str, Any],
  monthly_rent_expense: Any,
) -> str:
  try:
    current_rent = float(monthly_rent_expense)
  except Exception:
    current_rent = 0.0
  stage = _financials_business_stage(shared_context)
  if current_rent > 0:
    if stage == "operating":
      return "Looking ahead, do you expect paid dedicated business space to stay part of how this business operates?"
    return "Looking ahead, do you expect paid dedicated business space to stay part of this business once it is up and running?"
  if stage == "operating":
    return "Looking ahead, do you expect this business to need paid dedicated space later, or do you expect it to stay remote or space-light?"
  return "Looking ahead, do you expect this business to need paid dedicated space later, or do you expect it to stay without separate business space?"










def _financials_field_resolved(financials_json: Dict[str, Any], field: str) -> bool:
  if not isinstance(financials_json, dict):
    return False
  if field not in financials_json:
    return False
  if str(field or "").strip() == "cash_strategy":
    return _cash_strategy_option(financials_json.get(field)) is not None
  return financials_json.get(field) is not None


def _ensure_financials_stage_defaults(financials_json: Dict[str, Any]) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  try:
    debt = float(next_financials.get("total_debt_outstanding"))
  except Exception:
    debt = None
  if debt is not None and debt <= 0:
    next_financials.setdefault("other_monthly_debt_payments", 0)
    next_financials.setdefault("annual_interest_payment", 0)
    next_financials.setdefault("annual_principal_payment", 0)
  return next_financials


_FINANCIALS_STAGE_ORDER: Tuple[str, ...] = (
  "revenue_intro",
  "cogs",
  "current_payroll",
  "marketing",
  "monthly_rent_expense",
  "future_rent_expected",
  "owner_compensation",
  "other_operating_expense",
  "current_num_employees",
  "current_capex",
  "initial_assets",
  "initial_lease",
  "initial_equity",
  "total_debt_outstanding",
  "other_monthly_debt_payments",
  "annual_interest_payment",
  "annual_principal_payment",
  "cash_on_hand",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
  "cash_strategy",
)


_FINANCIALS_STAGE_SPECS: Dict[str, Dict[str, Any]] = {
  "revenue_intro": {
    "patch_targets": ("current_revenue",),
    "completion_fields": ("_financials_revenue_intro_done",),
    "confirmable_baseline": True,
    "clarifier": "What Year-1 revenue number should I use as the starting financial baseline instead?",
  },
  "cogs": {
    "patch_targets": ("current_cogs", "cogs_total_year1", "cogs_percent_of_revenue"),
    "completion_fields": ("current_cogs",),
    "confirmable_baseline": True,
    "clarifier": "What Year-1 direct-cost amount or percent should I use instead?",
  },
  "current_payroll": {
    "patch_targets": ("current_payroll", "payroll_total_year1"),
    "completion_fields": ("current_payroll",),
    "confirmable_baseline": True,
    "clarifier": "What Year-1 payroll should I use instead?",
  },
  "marketing": {
    "patch_targets": ("marketing_total_year1", "marketing_percent_of_revenue"),
    "completion_fields": ("marketing_total_year1",),
    "confirmable_baseline": True,
    "clarifier": "What Year-1 marketing budget or percent should I use instead?",
  },
  "monthly_rent_expense": {
    "patch_targets": ("monthly_rent_expense",),
    "completion_fields": ("monthly_rent_expense",),
    "confirmable_baseline": False,
    "clarifier": "What monthly rent amount should I record?",
  },
  "future_rent_expected": {
    "patch_targets": ("future_rent_expected",),
    "completion_fields": ("future_rent_expected",),
    "confirmable_baseline": False,
    "clarifier": "Should I record future dedicated business space as expected, yes or no?",
  },
  "owner_compensation": {
    "patch_targets": ("owner_compensation",),
    "completion_fields": ("owner_compensation",),
    "confirmable_baseline": False,
    "clarifier": "What annual owner compensation should I record?",
  },
  "other_operating_expense": {
    "patch_targets": ("other_operating_expense",),
    "completion_fields": ("other_operating_expense",),
    "confirmable_baseline": False,
    "clarifier": "What monthly other operating expense should I record?",
  },
  "current_num_employees": {
    "patch_targets": ("current_num_employees",),
    "completion_fields": ("current_num_employees",),
    "confirmable_baseline": False,
    "clarifier": "What whole-number employee count should I record?",
  },
  "current_capex": {
    "patch_targets": ("current_capex",),
    "completion_fields": ("current_capex",),
    "confirmable_baseline": False,
    "clarifier": "What current capital spending amount should I record?",
  },
  "initial_assets": {
    "patch_targets": ("initial_assets",),
    "completion_fields": ("initial_assets",),
    "confirmable_baseline": False,
    "clarifier": "What initial asset value should I record?",
  },
  "initial_lease": {
    "patch_targets": ("initial_lease",),
    "completion_fields": ("initial_lease",),
    "confirmable_baseline": False,
    "clarifier": "What monthly lease amount should I record for leased equipment or space beyond main rent?",
  },
  "initial_equity": {
    "patch_targets": ("initial_equity",),
    "completion_fields": ("initial_equity",),
    "confirmable_baseline": False,
    "clarifier": "What initial equity amount should I record?",
  },
  "total_debt_outstanding": {
    "patch_targets": ("total_debt_outstanding",),
    "completion_fields": ("total_debt_outstanding",),
    "confirmable_baseline": False,
    "clarifier": "What total debt outstanding amount should I record?",
  },
  "other_monthly_debt_payments": {
    "patch_targets": ("other_monthly_debt_payments",),
    "completion_fields": ("other_monthly_debt_payments",),
    "confirmable_baseline": False,
    "clarifier": "What other monthly debt-payment amount should I record?",
  },
  "annual_interest_payment": {
    "patch_targets": ("annual_interest_payment",),
    "completion_fields": ("annual_interest_payment",),
    "confirmable_baseline": False,
    "clarifier": "What annual interest amount should I record?",
  },
  "annual_principal_payment": {
    "patch_targets": ("annual_principal_payment",),
    "completion_fields": ("annual_principal_payment",),
    "confirmable_baseline": False,
    "clarifier": "What annual principal repayment amount should I record?",
  },
  "cash_on_hand": {
    "patch_targets": ("cash_on_hand",),
    "completion_fields": ("cash_on_hand",),
    "confirmable_baseline": False,
    "clarifier": "What cash-on-hand amount should I record?",
  },
  "ar_balance": {
    "patch_targets": ("ar_balance",),
    "completion_fields": ("ar_balance",),
    "confirmable_baseline": False,
    "clarifier": "What accounts receivable balance should I record?",
  },
  "ap_balance": {
    "patch_targets": ("ap_balance",),
    "completion_fields": ("ap_balance",),
    "confirmable_baseline": False,
    "clarifier": "What accounts payable balance should I record?",
  },
  "inventory_balance": {
    "patch_targets": ("inventory_balance",),
    "completion_fields": ("inventory_balance",),
    "confirmable_baseline": False,
    "clarifier": "What inventory balance should I record?",
  },
  "cash_strategy": {
    "patch_targets": ("cash_strategy",),
    "completion_fields": ("cash_strategy",),
    "confirmable_baseline": False,
    "clarifier": "Which cash approach should I record: Reinvest, Preserve cash, Shareholder return, or Balanced?",
  },
}

_CASH_STRATEGY_OPTIONS: Tuple[Dict[str, str], ...] = (
  {
    "value": "reinvest",
    "label": "Reinvest",
    "description": "Use extra cash to fund growth, capacity, or expansion when the economics support it.",
  },
  {
    "value": "preserve_cash",
    "label": "Preserve cash",
    "description": "Keep a thicker cash cushion and stay more conservative about putting excess cash back to work.",
  },
  {
    "value": "shareholder_return",
    "label": "Shareholder return",
    "description": "Treat excess cash as something that can be taken out of the business rather than just left to build up.",
  },
  {
    "value": "balanced",
    "label": "Balanced",
    "description": "Keep a healthy cushion while still reinvesting selectively when it makes sense.",
  },
)

_CASH_STRATEGY_INITIAL_PROMPT_MARKER = "One last financial planning question before I wrap this section up:"
_CASH_STRATEGY_CLARIFY_PROMPT_MARKER = "Just to make sure I record this correctly,"
_CASH_STRATEGY_FORCED_CHOICE_PROMPT_MARKER = "To lock this in cleanly, please pick the one option below that fits best right now:"


def _cash_strategy_option(value: Any) -> Optional[Dict[str, str]]:
  normalized = str(value or "").strip().lower()
  if not normalized:
    return None
  for option in _CASH_STRATEGY_OPTIONS:
    if normalized == option["value"]:
      return dict(option)
  return None


def _cash_strategy_decision_mode(last_assistant: str) -> str:
  assistant_text = str(last_assistant or "").strip().lower()
  if not assistant_text:
    return "initial"
  if _CASH_STRATEGY_FORCED_CHOICE_PROMPT_MARKER.lower() in assistant_text:
    return "forced_choice"
  if _CASH_STRATEGY_CLARIFY_PROMPT_MARKER.lower() in assistant_text:
    return "clarify"
  return "initial"


def _format_cash_strategy_options(*, numbered: bool = False) -> str:
  option_lines = []
  for idx, option in enumerate(_CASH_STRATEGY_OPTIONS, start=1):
    prefix = f"{idx}. " if numbered else "- "
    option_lines.append(f"{prefix}{option['label']}: {option['description']}")
  return "\n".join(option_lines)


def _build_cash_strategy_clarify_message() -> str:
  return (
    f"{_CASH_STRATEGY_CLARIFY_PROMPT_MARKER} which direction is closer to what you want for extra cash?\n\n"
    + _format_cash_strategy_options()
    + "\n\nA short answer is fine."
  )


def _build_cash_strategy_forced_choice_message() -> str:
  return (
    f"{_CASH_STRATEGY_FORCED_CHOICE_PROMPT_MARKER}\n\n"
    + _format_cash_strategy_options(numbered=True)
    + "\n\nReply with one option name or number."
  )


def _infer_cash_strategy_last_resort(
  *,
  conversation_messages: List[Dict[str, str]],
  last_assistant: str,
  user_message: str,
) -> Optional[str]:
  key = _openai_key()
  if not key:
    return None
  system = (
    "You are selecting the best-fit cash strategy for a financial intake flow.\n"
    "Choose exactly one of these persisted values: reinvest, preserve_cash, shareholder_return, balanced.\n"
    "Use the recent conversation as the source of truth.\n"
    "The user was already asked to choose explicitly but may still have answered indirectly.\n"
    "Pick the option that best matches the user's intent.\n"
    "Return only the persisted value."
  )
  recent = list(conversation_messages or [])[-12:]
  transcript_lines: List[str] = []
  for message in recent:
    role = str((message or {}).get("role") or "").strip().lower()
    content = str((message or {}).get("content") or "").strip()
    if role and content:
      transcript_lines.append(f"{role}: {content}")
  if str(last_assistant or "").strip():
    transcript_lines.append(f"latest_assistant: {str(last_assistant).strip()}")
  if str(user_message or "").strip():
    transcript_lines.append(f"latest_user: {str(user_message).strip()}")
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload={
      "model": _openai_model(),
      "input": [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(transcript_lines)},
      ],
    },
  )
  if resp.status_code >= 400:
    return None
  option = _cash_strategy_option(_parse_responses_text(resp.json()))
  return str(option.get("value")) if option else None


def _financials_stage_spec(stage_name: Optional[str]) -> Dict[str, Any]:
  return dict(_FINANCIALS_STAGE_SPECS.get(str(stage_name or "").strip(), {}))


def _financials_stage_complete(stage_name: str, financials_json: Dict[str, Any]) -> bool:
  spec = _financials_stage_spec(stage_name)
  completion_fields = tuple(spec.get("completion_fields") or ())
  if not completion_fields:
    return False
  data = _ensure_financials_stage_defaults(financials_json)
  return all(_financials_field_resolved(data, field_name) for field_name in completion_fields)


def _build_financials_controller_context(stage_name: Optional[str], *, last_assistant: str = "") -> Dict[str, Any]:
  stage = str(stage_name or "").strip()
  spec = _financials_stage_spec(stage)
  current_stage = {
    "name": stage or None,
    "patch_targets": list(spec.get("patch_targets") or []),
    "completion_fields": list(spec.get("completion_fields") or []),
    "confirmable_baseline": bool(spec.get("confirmable_baseline")),
    "clarifier": str(spec.get("clarifier") or "").strip(),
  }
  if stage == "cash_strategy":
    current_stage["allowed_values"] = [option["value"] for option in _CASH_STRATEGY_OPTIONS]
    current_stage["options"] = [dict(option) for option in _CASH_STRATEGY_OPTIONS]
    current_stage["decision_mode"] = _cash_strategy_decision_mode(last_assistant)
  return {"current_stage": current_stage}


def _financials_stage_confirm_question(stage_name: Optional[str]) -> Optional[str]:
  spec = _financials_stage_spec(stage_name)
  if not bool(spec.get("confirmable_baseline")):
    return None
  stage = str(stage_name or "").strip()
  if stage == "revenue_intro":
    return "Should I use this Year-1 revenue baseline for financial planning?"
  if stage == "cogs":
    return "Should I use this Year-1 direct-cost baseline?"
  if stage == "current_payroll":
    return "Should I use this Year-1 payroll baseline?"
  if stage == "marketing":
    return "Should I use this Year-1 marketing baseline?"
  return None


def _build_financials_stage_clarifier(stage_name: Optional[str]) -> str:
  spec = _financials_stage_spec(stage_name)
  clarifier = str(spec.get("clarifier") or "").strip()
  if clarifier:
    return clarifier
  return "What should I record for this financial item?"


def _next_financials_stage(financials_json: Dict[str, Any]) -> Optional[str]:
  data = _ensure_financials_stage_defaults(financials_json)
  for stage_name in _FINANCIALS_STAGE_ORDER:
    if not _financials_stage_complete(stage_name, data):
      return stage_name
  return None


_GENERIC_FINANCIALS_SCALAR_FIELDS = {
  "owner_compensation",
  "other_operating_expense",
  "current_num_employees",
  "current_capex",
  "initial_assets",
  "initial_lease",
  "initial_equity",
  "total_debt_outstanding",
  "other_monthly_debt_payments",
  "annual_interest_payment",
  "annual_principal_payment",
  "cash_on_hand",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
}

_GENERIC_FINANCIALS_FIELD_LABELS = {
  "owner_compensation": "owner compensation",
  "other_operating_expense": "other operating expense",
  "current_num_employees": "current employee count",
  "current_capex": "current capital spending",
  "initial_assets": "initial assets already in the business",
  "initial_lease": "monthly lease commitment beyond main rent",
  "initial_equity": "money invested so far",
  "total_debt_outstanding": "total debt outstanding",
  "other_monthly_debt_payments": "other monthly debt payments",
  "annual_interest_payment": "annual interest payment",
  "annual_principal_payment": "annual principal payment",
  "cash_on_hand": "cash on hand",
  "ar_balance": "accounts receivable",
  "ap_balance": "accounts payable",
  "inventory_balance": "inventory balance",
}


def _build_cash_strategy_message_legacy_unused() -> str:
  option_lines = []
  for option in _CASH_STRATEGY_OPTIONS:
    option_lines.append(f"- {option['label']}: {option['description']}")
  return (
    "One last financial planning question before I wrap this section up: when this business starts building extra cash, "
    "what would you want to do with it?\n\n"
    + "\n".join(option_lines)
    + "\n\nYou can answer in plain language and I’ll map it to the closest approach."
  )


def _build_cash_strategy_message() -> str:
  return (
    f"{_CASH_STRATEGY_INITIAL_PROMPT_MARKER} when this business starts building extra cash, "
    "what would you want to do with it?\n\n"
    + _format_cash_strategy_options()
    + "\n\nYou can answer in plain language and I'll map it to the closest approach."
  )


def _build_cash_strategy_acknowledgement(value: Any) -> str:
  option = _cash_strategy_option(value)
  if not option:
    return "Got it."
  return f"Got it. I’ll treat {option['label'].lower()} as the preferred cash posture."


def _is_generic_financials_scalar_stage(stage_name: Optional[str]) -> bool:
  return str(stage_name or "").strip() in _GENERIC_FINANCIALS_SCALAR_FIELDS


def _build_financials_scalar_stage_acknowledgement(stage_name: str, value: float) -> str:
  label = _GENERIC_FINANCIALS_FIELD_LABELS.get(stage_name, stage_name.replace("_", " "))
  if stage_name == "current_num_employees":
    return f"Got it - I'll use {int(round(value))} for {label}."
  return f"Got it - I'll use {_format_currency(value)} for {label}."


def _build_financials_scalar_stage_clarifier(stage_name: str) -> str:
  label = _GENERIC_FINANCIALS_FIELD_LABELS.get(stage_name, stage_name.replace("_", " "))
  if stage_name == "current_num_employees":
    return f"What number should I record for {label}? A whole number is fine."
  return f"What amount should I record for {label}? A rough number is fine, and 0 is okay if that is correct."


def _financials_stage_fallback_patch(
  *,
  stage_name: Optional[str],
  user_message: str,
  financials_year1_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  stage = str(stage_name or "").strip()
  user_text = str(user_message or "").strip()
  user_lower = user_text.lower()
  if stage != "marketing":
    return None
  numeric = _extract_first_number_from_text(user_text)
  if numeric is None:
    return None
  if "per month" in user_lower or "monthly" in user_lower:
    total = float(numeric) * 12.0
  else:
    total = float(numeric)
  revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1")) or 0.0
  patch: Dict[str, Any] = {"marketing_total_year1": total}
  if revenue_year1 > 0:
    patch["marketing_percent_of_revenue"] = float(total / revenue_year1)
  return patch


def _normalize_financials_router_patch(
  *,
  patch: Dict[str, Any],
  active_stage: Optional[str],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  last_assistant: str,
  user_message: str = "",
) -> Optional[Dict[str, Any]]:
  if not isinstance(patch, dict) or not patch:
    return None
  stage_name = str(active_stage or "").strip()
  allowed_fields = set(_financials_stage_spec(stage_name).get("patch_targets") or ())
  if not allowed_fields:
    return None
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  touched: set[str] = set()
  assistant_lower = str(last_assistant or "").strip().lower()
  user_lower = str(user_message or "").strip().lower()
  for raw_key, raw_value in patch.items():
    field_name = str(raw_key or "").strip()
    if field_name.startswith("financials."):
      field_name = field_name.split(".", 1)[1].strip()
    if field_name not in allowed_fields:
      continue
    if raw_value is None:
      continue
    if field_name == "current_num_employees":
      numeric = _safe_float(raw_value)
      if numeric is None:
        continue
      next_financials[field_name] = int(round(numeric))
      touched.add(field_name)
      continue
    if field_name == "owner_compensation":
      numeric = _safe_float(raw_value)
      if numeric is None:
        continue
      asks_monthly = "owner compensation" in assistant_lower and ("per month" in assistant_lower or "last month" in assistant_lower)
      mentions_annual = any(token in user_lower for token in ("annual", "annually", "per year", "yearly", "/year", "a year"))
      if asks_monthly and not mentions_annual and numeric <= 50000.0:
        numeric *= 12.0
      next_financials[field_name] = float(numeric)
      touched.add(field_name)
      continue
    if field_name == "future_rent_expected":
      next_financials[field_name] = bool(raw_value)
      touched.add(field_name)
      continue
    if field_name == "initial_lease":
      numeric = _safe_float(raw_value)
      if numeric is None:
        continue
      next_financials[field_name] = float(numeric)
      touched.add(field_name)
      continue
    if field_name == "cash_strategy":
      option = _cash_strategy_option(raw_value)
      if option is None:
        continue
      next_financials[field_name] = option["value"]
      touched.add(field_name)
      continue
    if field_name in {"cogs_percent_of_revenue", "marketing_percent_of_revenue"}:
      numeric = _normalize_ratio_like(raw_value)
      if numeric is None:
        continue
      next_financials[field_name] = float(numeric)
      touched.add(field_name)
      continue
    numeric = _safe_float(raw_value)
    if numeric is None:
      continue
    if stage_name == "marketing" and field_name == "marketing_total_year1":
      if ("per month" in user_lower or "monthly" in user_lower) and numeric <= 20000.0:
        numeric *= 12.0
    next_financials[field_name] = float(numeric)
    touched.add(field_name)
  if not touched:
    return None
  if stage_name == "revenue_intro" and "current_revenue" in touched:
    next_financials["_financials_revenue_intro_done"] = True
  if "cogs_percent_of_revenue" in touched:
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1")) or 0.0
    percent = float(next_financials.get("cogs_percent_of_revenue") or 0.0)
    next_financials["current_cogs"] = percent * revenue_year1 if revenue_year1 > 0 else 0.0
    next_financials["cogs_total_year1"] = float(next_financials.get("current_cogs") or 0.0)
  if "current_cogs" in touched:
    next_financials["cogs_total_year1"] = float(next_financials.get("current_cogs") or 0.0)
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    if revenue_year1 and revenue_year1 > 0:
      next_financials["cogs_percent_of_revenue"] = float(next_financials["current_cogs"]) / revenue_year1
  if "cogs_total_year1" in touched:
    next_financials["current_cogs"] = float(next_financials.get("cogs_total_year1") or 0.0)
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    if revenue_year1 and revenue_year1 > 0:
      next_financials["cogs_percent_of_revenue"] = float(next_financials["current_cogs"]) / revenue_year1
  if "current_payroll" in touched:
    next_financials["payroll_total_year1"] = float(next_financials.get("current_payroll") or 0.0)
  if "payroll_total_year1" in touched:
    next_financials["current_payroll"] = float(next_financials.get("payroll_total_year1") or 0.0)
  if "marketing_total_year1" in touched or "marketing_percent_of_revenue" in touched:
    next_financials = _sync_marketing_field_family(
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      marketing_model_json={},
    )
  return _ensure_financials_stage_defaults(next_financials)


def _rescale_financials_year1_to_current_revenue(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  next_year1 = dict(financials_year1_json or {})
  target_total = _safe_float((financials_json or {}).get("current_revenue"))
  current_total = _safe_float(next_year1.get("company_revenue_total_year1"))
  if target_total is None or target_total <= 0 or current_total is None or current_total <= 0:
    return next_year1
  if abs(target_total - current_total) <= max(0.01, abs(target_total) * 1e-9):
    return next_year1

  factor = float(target_total / current_total)
  if factor <= 0:
    return next_year1

  lobs = next_year1.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return next_year1

  product_overrides: Dict[str, Dict[str, float]] = {}
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip() or "Line of business"
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip() or "Product"
      cadence = str(product.get("unit_cadence") or "").strip().lower()
      scaled_fields: Dict[str, float] = {}

      for field_name in (
        "units_per_period_capacity",
        "avg_units_per_period_year1",
      ):
        value = _safe_float(product.get(field_name))
        if value is not None:
          scaled_fields[field_name] = float(value * factor)

      if cadence == "weekly":
        for field_name in ("units_per_week_capacity", "avg_units_per_week_year1"):
          value = _safe_float(product.get(field_name))
          if value is not None:
            scaled_fields[field_name] = float(value * factor)
      elif cadence == "monthly":
        for field_name in ("units_per_month_capacity", "avg_units_per_month_year1"):
          value = _safe_float(product.get(field_name))
          if value is not None:
            scaled_fields[field_name] = float(value * factor)
      else:
        for field_name in ("concurrent_capacity_units", "avg_active_units_year1"):
          value = _safe_float(product.get(field_name))
          if value is not None:
            scaled_fields[field_name] = float(value * factor)

      if scaled_fields:
        product_overrides[f"{lob_name}::{product_name}"] = scaled_fields

  if not product_overrides:
    return next_year1

  try:
    try:
      from financials_year1 import apply_revenue_driver_patch  # type: ignore
    except Exception:
      from client_intake_and_finmo.financials_year1 import apply_revenue_driver_patch  # type: ignore
    return apply_revenue_driver_patch(next_year1, {"product_overrides": product_overrides})
  except Exception:
    return next_year1


def _sync_financials_consult_persistence_state(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  next_year1 = _rescale_financials_year1_to_current_revenue(
    financials_json=next_financials,
    financials_year1_json=financials_year1_json,
  )

  revenue_year1 = _safe_float(next_year1.get("company_revenue_total_year1")) or 0.0
  if revenue_year1 > 0:
    next_financials["current_revenue"] = float(revenue_year1)

  cogs_percent = _safe_float(next_financials.get("cogs_percent_of_revenue"))
  cogs_total = _safe_float(next_financials.get("cogs_total_year1"))
  current_cogs = _safe_float(next_financials.get("current_cogs"))
  if cogs_percent is not None and revenue_year1 > 0:
    cogs_percent = max(0.0, min(float(cogs_percent), 1.0))
    synced_total = float(cogs_percent * revenue_year1)
    next_financials["cogs_percent_of_revenue"] = cogs_percent
    next_financials["current_cogs"] = synced_total
    next_financials["cogs_total_year1"] = synced_total
  elif cogs_total is not None:
    synced_total = max(0.0, float(cogs_total))
    next_financials["current_cogs"] = synced_total
    next_financials["cogs_total_year1"] = synced_total
    if revenue_year1 > 0:
      next_financials["cogs_percent_of_revenue"] = float(synced_total / revenue_year1)
  elif current_cogs is not None:
    synced_total = max(0.0, float(current_cogs))
    next_financials["current_cogs"] = synced_total
    next_financials["cogs_total_year1"] = synced_total
    if revenue_year1 > 0:
      next_financials["cogs_percent_of_revenue"] = float(synced_total / revenue_year1)

  current_payroll = _safe_float(next_financials.get("current_payroll"))
  payroll_total = _safe_float(next_financials.get("payroll_total_year1"))
  if payroll_total is not None:
    synced_total = max(0.0, float(payroll_total))
    next_financials["current_payroll"] = synced_total
    next_financials["payroll_total_year1"] = synced_total
  elif current_payroll is not None:
    synced_total = max(0.0, float(current_payroll))
    next_financials["current_payroll"] = synced_total
    next_financials["payroll_total_year1"] = synced_total

  next_financials = _sync_marketing_field_family(
    financials_json=next_financials,
    financials_year1_json=next_year1,
    marketing_model_json=marketing_model_json or {},
  )
  return _ensure_financials_stage_defaults(next_financials), next_year1


def _extract_ops_proposal_patch(
  *,
  last_assistant: str,
  route_intent,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  recent_messages: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
  text = str(last_assistant or "").strip()
  if not text:
    return None
  try:
    proposal_intent = route_intent(
      consult_type="ops",
      user_message=text,
      baseline_json=ops_json,
      shared_context=shared_context,
      recent_messages=recent_messages,
      active_focus="ops",
    )
  except Exception:
    return None
  if str(proposal_intent.get("action") or "").strip() != "edit_patch":
    return None
  patch = proposal_intent.get("patch")
  if not isinstance(patch, dict) or not patch:
    return None
  return patch


def _fallback_ops_followup_question(ops_json: Dict[str, Any]) -> str:
  ops = ops_json if isinstance(ops_json, dict) else {}

  def _missing_text(field: str) -> bool:
    return not str(ops.get(field) or "").strip()

  if _missing_text("capacity_driver"):
    return (
      "What most limits how much you can grow right now: your available labor/time, "
      "your systems/processes, or having enough customer demand?"
    )
  if _missing_text("primary_growth_lever"):
    return (
      "What do you see as the main lever you'll push first to grow this business: "
      "winning more demand, improving systems/processes, or adding more people/capacity?"
    )
  if _missing_text("legal_entity"):
    return "Which legal structure are you using right now: Sole proprietor, LLC, Partnership, S-corp, or C-corp?"
  return ""


def _run_financials_turn_and_sync(
  *,
  route_intent,
  conn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  business_facts: Dict[str, Any],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  active_stage = _next_financials_stage(next_financials)

  def _stage_context(
    stage_name: Optional[str],
    fin_json: Dict[str, Any],
    extra_shared: Optional[Dict[str, Any]] = None,
    prior_assistant: str = "",
  ) -> Dict[str, Any]:
    ctx = dict(intake_context or {})
    ctx["financials_json"] = fin_json
    next_shared = dict(extra_shared if isinstance(extra_shared, dict) else (shared_context or {}))
    next_shared["financials"] = fin_json
    next_shared["financials_controller"] = _build_financials_controller_context(
      stage_name,
      last_assistant=prior_assistant,
    )
    ctx["shared_context"] = next_shared
    if stage_name:
      ctx["financials_active_stage"] = stage_name
    else:
      ctx.pop("financials_active_stage", None)
    return ctx

  if not active_stage:
    return _build_financials_completion_turn(), next_financials

  stage_context = _stage_context(active_stage, next_financials, prior_assistant=last_assistant)
  stage_shared_context = dict(stage_context.get("shared_context") or {})
  confirm_question = _financials_stage_confirm_question(active_stage)
  if not str(user_message or "").strip():
    return {
      "assistant_message": _build_financials_stage_message(
        stage_name=active_stage,
        intake_context=stage_context,
        shared_context=stage_shared_context,
        financials_json=next_financials,
        financials_year1_json=financials_year1_json,
        business_facts=business_facts,
        conn=conn,
      ),
      "finalize_ready": False,
    }, next_financials

  routed = route_intent(
    consult_type="financials",
    user_message=str(user_message).strip(),
    baseline_json=next_financials,
    shared_context=stage_shared_context,
    recent_messages=conversation_messages[-30:] if conversation_messages else [],
    confirm_question_override=confirm_question,
    active_focus="financials",
  )
  action = str(routed.get("action") or "").strip()
  assistant_message = sanitize_fact_template(str(routed.get("assistant_message") or "").strip())
  patch = routed.get("patch") if isinstance(routed.get("patch"), dict) else None
  cash_strategy_mode = _cash_strategy_decision_mode(last_assistant) if active_stage == "cash_strategy" else ""

  if action == "confirm_proceed":
    default_patch = _financials_stage_default_patch(
      stage_name=active_stage,
      shared_context=stage_shared_context,
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      conn=conn,
    )
    if isinstance(default_patch, dict) and default_patch:
      patch = {f"financials.{k}": v for k, v in default_patch.items()}
      action = "edit_patch"

  if action == "edit_patch" and patch:
    normalized_patch = _normalize_financials_router_patch(
      patch=patch,
      active_stage=active_stage,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      last_assistant=last_assistant,
      user_message=user_message,
    )
    if isinstance(normalized_patch, dict) and normalized_patch:
      acknowledgement = assistant_message or _build_financials_stage_acknowledgement(
        stage_name=active_stage,
        financials_json=normalized_patch,
      )
      next_context = _stage_context(active_stage, normalized_patch)
      next_turn, updated_financials, _ = _advance_persisted_financials_stage(
        conn=conn,
        draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
        business_facts=business_facts,
        intake_context=next_context,
        conversation_messages=conversation_messages,
        shared_context=stage_shared_context,
        financials_json=normalized_patch,
        financials_year1_json=financials_year1_json,
        marketing_model_json=dict((stage_shared_context or {}).get("marketing") or {}),
        acknowledgement=acknowledgement,
      )
      return next_turn, updated_financials

  if active_stage == "cash_strategy":
    if cash_strategy_mode == "forced_choice":
      inferred_value = _infer_cash_strategy_last_resort(
        conversation_messages=conversation_messages,
        last_assistant=last_assistant,
        user_message=user_message,
      )
      if inferred_value:
        normalized_patch = _normalize_financials_router_patch(
          patch={"financials.cash_strategy": inferred_value},
          active_stage=active_stage,
          financials_json=next_financials,
          financials_year1_json=financials_year1_json,
          last_assistant=last_assistant,
          user_message=user_message,
        )
        if isinstance(normalized_patch, dict) and normalized_patch:
          acknowledgement = assistant_message or _build_financials_stage_acknowledgement(
            stage_name=active_stage,
            financials_json=normalized_patch,
          )
          next_context = _stage_context(active_stage, normalized_patch)
          next_turn, updated_financials, _ = _advance_persisted_financials_stage(
            conn=conn,
            draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
            business_facts=business_facts,
            intake_context=next_context,
            conversation_messages=conversation_messages,
            shared_context=stage_shared_context,
            financials_json=normalized_patch,
            financials_year1_json=financials_year1_json,
            marketing_model_json=dict((stage_shared_context or {}).get("marketing") or {}),
            acknowledgement=acknowledgement,
          )
          return next_turn, updated_financials
    if action != "answer_readonly":
      if cash_strategy_mode == "initial":
        return {"assistant_message": _build_cash_strategy_clarify_message(), "finalize_ready": False}, next_financials
      if cash_strategy_mode == "clarify":
        return {"assistant_message": _build_cash_strategy_forced_choice_message(), "finalize_ready": False}, next_financials

  fallback_patch = _financials_stage_fallback_patch(
    stage_name=active_stage,
    user_message=user_message,
    financials_year1_json=financials_year1_json,
  )
  if isinstance(fallback_patch, dict) and fallback_patch:
    normalized_patch = _normalize_financials_router_patch(
      patch=fallback_patch,
      active_stage=active_stage,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      last_assistant=last_assistant,
      user_message=user_message,
    )
    if isinstance(normalized_patch, dict) and normalized_patch:
      acknowledgement = assistant_message or _build_financials_stage_acknowledgement(
        stage_name=active_stage,
        financials_json=normalized_patch,
      )
      next_context = _stage_context(active_stage, normalized_patch)
      next_turn, updated_financials, _ = _advance_persisted_financials_stage(
        conn=conn,
        draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
        business_facts=business_facts,
        intake_context=next_context,
        conversation_messages=conversation_messages,
        shared_context=stage_shared_context,
        financials_json=normalized_patch,
        financials_year1_json=financials_year1_json,
        marketing_model_json=dict((stage_shared_context or {}).get("marketing") or {}),
        acknowledgement=acknowledgement,
      )
      return next_turn, updated_financials

  if action == "answer_readonly" and assistant_message:
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  if action == "confirm_clarify" and assistant_message:
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  return {
    "assistant_message": _build_financials_stage_clarifier(active_stage),
    "finalize_ready": False,
  }, next_financials


def _ops_ready_for_wrap_from_gate_obj(obj: Any) -> bool:
  if not isinstance(obj, dict):
    return False

  def _has_text(field: str) -> bool:
    return bool(str(obj.get(field) or "").strip())

  def _product_complete(product: Dict[str, Any]) -> bool:
    if not isinstance(product, dict):
      return False
    if not str(product.get("unit_name") or "").strip():
      return False
    cadence = str(product.get("unit_cadence") or "").strip().lower()
    if not cadence:
      return False
    if _is_missing_number_value(product.get("unit_price")):
      return False
    if _is_missing_number_value(product.get("units_per_period_capacity")) and _is_missing_number_value(
      product.get("units_per_week_capacity")
    ):
      return False
    if _is_missing_number_value(product.get("utilization_rate")):
      return False
    if cadence == "contract" and _is_missing_number_value(product.get("operating_periods_per_year")):
      return False
    return True

  lob_models = obj.get("lob_models")
  products: List[Dict[str, Any]] = []
  if isinstance(lob_models, list):
    for lob in lob_models:
      if not isinstance(lob, dict):
        continue
      lob_products = lob.get("products")
      if not isinstance(lob_products, list):
        continue
      for product in lob_products:
        if isinstance(product, dict):
          products.append(product)

  business_wide_fields = [
    "shipping_method",
    "sales_modality",
    "geographic_scope",
    "legal_entity",
    "capacity_driver",
    "primary_growth_lever",
  ]
  if not all(_has_text(field) for field in business_wide_fields):
    return False

  if products:
    return all(_product_complete(product) for product in products)

  if not _has_text("unit_name") or not _has_text("unit_cadence"):
    return False
  if _is_missing_number_value(obj.get("unit_price")):
    return False
  if _is_missing_number_value(obj.get("units_per_period_capacity")) and _is_missing_number_value(
    obj.get("units_per_week_capacity")
  ):
    return False
  if _is_missing_number_value(obj.get("utilization_rate")):
    return False
  if str(obj.get("unit_cadence") or "").strip().lower() == "contract" and _is_missing_number_value(
    obj.get("operating_periods_per_year")
  ):
    return False
  return True


def _is_guardrail_acknowledgement(message: str) -> bool:
  text = str(message or "").strip().lower()
  if not text:
    return False
  try:
    import re

    patterns = [
      r"\bok\b",
      r"\bokay\b",
      r"\byes\b",
      r"\bsounds good\b",
      r"\blooks good\b",
      r"\bworks for me\b",
      r"\bgo ahead\b",
      r"\bproceed\b",
      r"\bkeep (it|this) (as is|the same)\b",
      r"\bkeep as is\b",
      r"\bleave it\b",
      r"\bno changes\b",
      r"\bno change\b",
      r"\bi understand\b",
      r"\bunderstood\b",
      r"\baccept\b",
      r"\bi'?m ok\b",
      r"\bi am ok\b",
      r"\bfine\b",
      r"\ball good\b",
    ]
    return any(re.search(pat, text) for pat in patterns)
  except Exception:
    return False


def _is_restatement_acceptance(message: str) -> bool:
  """
  Semantic acceptance for restatement confirmations.
  Default to accept unless the user expresses disagreement, correction, or uncertainty.
  """
  text = str(message or "").strip().lower()
  if not text:
    return False
  try:
    import re

    reject_patterns = [
      r"\bno\b",
      r"\bnope\b",
      r"\bnot\b",
      r"\bincorrect\b",
      r"\bwrong\b",
      r"\bnot really\b",
      r"\bnot exactly\b",
      r"\bdoesn'?t\b",
      r"\bdoes not\b",
      r"\bthat'?s not\b",
      r"\bnot (quite|really)\b",
      r"\bexcept\b",
      r"\bbut\b",
      r"\bhowever\b",
      r"\binstead\b",
      r"\bactually\b",
      r"\bwe (don'?t|do not)\b",
      r"\bi (don'?t|do not)\b",
      r"\bnot sure\b",
      r"\bunsure\b",
      r"\bkind of\b",
      r"\bsort of\b",
      r"\bmaybe\b",
      r"\bdepends\b",
      r"\bpartly\b",
      r"\bpartially\b",
      r"\bnot fully\b",
      r"\bnot (completely|entirely)\b",
      r"\bquestion\b",
      r"\bconfused\b",
      r"\bchange\b",
      r"\bcorrect\b",
      r"\bclarify\b",
      r"\bupdate\b",
      r"\brevise\b",
    ]
    if any(re.search(pat, text) for pat in reject_patterns):
      return False
  except Exception:
    return False

  return True


def _classify_restatement_response(*, restatement: str, user_reply: str) -> Optional[str]:
  """
  Use GPT to classify the user's reply to a restatement as ACCEPT, REJECT, or CLARIFY.
  Returns one of those strings, or None if classification fails.
  """
  key = _openai_key()
  if not key:
    return None
  system = (
    "You are classifying a user's reply to a proposed restatement.\n"
    "Return exactly one of: ACCEPT, REJECT, CLARIFY.\n"
    "If the assistant text is not a restatement asking for confirmation, return CLARIFY.\n"
    "- ACCEPT: the user generally agrees that the restatement is accurate, even if they add extra nuance,\n"
    "  caveats, future plans, or additional details (e.g., \"yes, but...\", \"mostly yes...\", \"although...\").\n"
    "  Treat these as ACCEPT unless they clearly contradict the restatement.\n"
    "- REJECT: the user disagrees with a material part of the restatement or explicitly corrects/contradicts it.\n"
    "- CLARIFY: user is unsure, ambiguous, or asks for clarification.\n"
    "Return only the label."
  )
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": f"Restatement:\n{restatement}"},
      {"role": "user", "content": f"User reply:\n{user_reply}"},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return None
  raw = _parse_responses_text(resp.json())
  label = str(raw or "").strip().upper()
  return label if label in ("ACCEPT", "REJECT", "CLARIFY") else None


def _detect_confirm_question(last_assistant: str) -> Optional[str]:
  text = str(last_assistant or "").strip().lower()
  if not text:
    return None
  for question in (
    OPS_CONFIRM_QUESTION,
    MARKET_CONFIRM_QUESTION,
    PEOPLE_CONFIRM_QUESTION,
  ):
    if question and question.lower() in text:
      return question
  return None


def _extract_competitive_advantage_prompt(last_assistant: str) -> Optional[str]:
  text = str(last_assistant or "").strip()
  if not text:
    return None
  for line in text.splitlines():
    line_stripped = line.strip()
    if not line_stripped:
      continue
    if line_stripped.lower().startswith(COMPETITIVE_ADVANTAGE_PREFIX.lower()):
      _, _, rest = line_stripped.partition(":")
      value = rest.strip()
      return value or None
  return None


def _extract_confirmed_restatement(messages: List[Dict[str, str]]) -> Optional[str]:
  for idx in range(len(messages) - 2, -1, -1):
    assistant_msg = messages[idx]
    user_msg = messages[idx + 1]
    if str(assistant_msg.get("role") or "") != "assistant":
      continue
    if str(user_msg.get("role") or "") != "user":
      continue
    assistant_text = str(assistant_msg.get("content") or "").strip()
    user_text = str(user_msg.get("content") or "").strip()
    if not assistant_text or not user_text:
      continue
    if not _is_guardrail_acknowledgement(user_text):
      continue
    if not assistant_text.endswith("?"):
      continue
    sentence_marks = sum(1 for ch in assistant_text if ch in ".!?")
    if sentence_marks < 2:
      continue
    return assistant_text
  return None


def _finalize_flag_field(focus: str, value: bool) -> Optional[Dict[str, Any]]:
  focus_norm = str(focus or "").strip().lower()
  mapping = {
    "ops": "ops_finalize_proposed",
    "market": "market_finalize_proposed",
    "people": "people_finalize_proposed",
  }
  key = mapping.get(focus_norm)
  if not key:
    return None
  return {key: bool(value)}


def _year1_driver_map(year1_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  out: Dict[str, Dict[str, Any]] = {}
  if not isinstance(year1_json, dict):
    return out
  lobs = year1_json.get("lobs")
  if not isinstance(lobs, list):
    return out
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip().lower()
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip().lower()
      if not product_name:
        continue
      key = f"{lob_name}::{product_name}"
      out[key] = {
        "unit_cadence": str(product.get("unit_cadence") or "").strip().lower(),
        "unit_price": product.get("unit_price"),
        "units_per_period_capacity": product.get("units_per_period_capacity"),
        "operating_periods_per_year": product.get("operating_periods_per_year"),
        "utilization_rate": product.get("utilization_rate"),
      }
  return out


def _year1_drivers_conflict(existing_year1: Optional[Dict[str, Any]], base_year1: Dict[str, Any]) -> bool:
  if not isinstance(existing_year1, dict) or not existing_year1:
    return False
  existing_map = _year1_driver_map(existing_year1)
  base_map = _year1_driver_map(base_year1)
  if not existing_map or not base_map:
    return False

  def _num(value: Any) -> Optional[float]:
    try:
      return float(value)
    except Exception:
      return None

  for key, base_driver in base_map.items():
    existing_driver = existing_map.get(key)
    if not existing_driver:
      continue
    base_cadence = str(base_driver.get("unit_cadence") or "").strip().lower()
    existing_cadence = str(existing_driver.get("unit_cadence") or "").strip().lower()
    if base_cadence and existing_cadence and base_cadence != existing_cadence:
      return True
    base_price = _num(base_driver.get("unit_price"))
    existing_price = _num(existing_driver.get("unit_price"))
    if base_price is not None and existing_price is not None and abs(base_price - existing_price) > 0.01:
      return True
    base_capacity = _num(base_driver.get("units_per_period_capacity"))
    existing_capacity = _num(existing_driver.get("units_per_period_capacity"))
    if base_capacity is not None and existing_capacity is not None and abs(base_capacity - existing_capacity) > 0.01:
      return True
    base_periods = _num(base_driver.get("operating_periods_per_year"))
    existing_periods = _num(existing_driver.get("operating_periods_per_year"))
    if base_periods is not None and existing_periods is not None and abs(base_periods - existing_periods) > 0.01:
      return True
    base_util = _num(base_driver.get("utilization_rate"))
    existing_util = _num(existing_driver.get("utilization_rate"))
    if base_util is not None and existing_util is not None and abs(base_util - existing_util) > 0.0001:
      return True
  return False


def _normalize_unscoped_patch(patch: Dict[str, Any], *, focus: str) -> Dict[str, Any]:
  focus_norm = str(focus or "").strip().lower()
  if not isinstance(patch, dict) or not patch:
    return patch
  field_sets = {
    "ops": {
      "consumer_type",
      "business_type",
      "business_stage",
      "business_naics_6",
      "unit_name",
      "unit_description",
      "unit_cadence",
      "units_per_week_capacity",
      "units_per_period_capacity",
      "operating_periods_per_year",
      "utilization_rate",
      "unit_price",
      "shipping_method",
      "sales_modality",
      "geographic_scope",
      "geographic_coverage",
      "countries",
      "milestones",
      "competitive_advantage",
      "capacity_driver",
      "primary_growth_lever",
      "legal_entity",
      "lob_models",
      "confidence",
    },
    "market": {
      "consumer_type",
      "gender_age_intent",
      "income_intent",
      "selections",
      "b2b_industry_terms",
      "b2b_naics_6",
      "b2b_size_bands",
      "b2b_age_bands",
      "marketing_plan_summary",
      "confidence",
    },
    "people": {
      "people",
      "inferred_roles",
      "inferred_roles_summary",
      "business_naics_6",
      "confidence",
    },
    "financials": {
      "current_revenue",
      "current_cogs",
      "baseline_marketing_percent",
      "baseline_marketing",
      "marketing_adjustment",
      "marketing_total_year1",
      "marketing_percent_of_revenue",
      "other_operating_expense",
      "monthly_rent_expense",
      "future_rent_expected",
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
    },
    "fulfillment": {
      "time",
      "personnel",
    },
  }
  allowed = field_sets.get(focus_norm, set())
  if not allowed:
    return patch
  normalized: Dict[str, Any] = {}
  for raw_key, value in patch.items():
    key = str(raw_key or "").strip()
    if not key:
      continue
    if "." in key:
      normalized[key] = value
      continue
    if key in allowed:
      normalized[f"{focus_norm}.{key}"] = value
    else:
      normalized[key] = value
  return normalized

def _constraints_snippet_already_sent(messages: List[Dict[str, str]]) -> bool:
  for msg in messages or []:
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    content = str(msg.get("content") or "")
    if "operational constraints:" in content.lower():
      return True
  return False


def _append_constraints_snippet(
  assistant_text: str,
  snippet: str,
  messages: List[Dict[str, str]],
  *,
  force: bool = False,
) -> str:
  # Financials no longer shows the deterministic "Operational constraints" block
  # in the client-facing chat output.
  return assistant_text



def _strip_acs_codes(text: str) -> str:
  """
  Never expose raw ACS codes in the UI conversation.
  """
  try:
    import re

    return re.sub(r"\b[A-Z]\d{5}_\d{3}E\b", "[ACS code redacted]", text)
  except Exception:
    return text


def _parse_date(value: Any) -> Optional[date]:
  if value is None:
    return None
  if isinstance(value, datetime):
    return value.date()
  if isinstance(value, date):
    return value
  raw = str(value).strip()
  if not raw:
    return None
  try:
    return datetime.fromisoformat(raw).date()
  except ValueError:
    pass
  for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
    try:
      return datetime.strptime(raw, fmt).date()
    except ValueError:
      continue
  return None


def _infer_business_stage(start_date_raw: Any, current_date: Optional[date] = None) -> Optional[str]:
  start_date = _parse_date(start_date_raw)
  if start_date is None:
    return None
  today = current_date or datetime.utcnow().date()
  if start_date > today:
    return "pre-revenue"
  delta_days = (today - start_date).days
  if delta_days <= 365:
    return "early-stage"
  return "operating"


def _openai_key() -> Optional[str]:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  return key or None


def _openai_model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _openai_timeout_seconds() -> int:
  raw = (os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS") or "").strip()
  if raw:
    try:
      return max(30, int(raw))
    except Exception:
      return 180
  return 180


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _openai_timeout_seconds()
  last_exc: Optional[Exception] = None
  for attempt in range(3):
    try:
      resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
      if resp.status_code in _RETRYABLE_STATUS and attempt < 2:
        time.sleep(0.75 * (2**attempt))
        continue
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:
      last_exc = exc
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
    except requests.exceptions.ConnectionError as exc:
      last_exc = exc
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


def _parse_responses_text(data: Dict[str, Any]) -> str:
  output = data.get("output") or []
  chunks: List[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        chunks.append(str(part["text"]))
  if not chunks:
    raise RuntimeError("OpenAI response contained no output_text.")
  return "\n".join(chunks).strip()


def _months_until(target: date, reference_date: Optional[date]) -> int:
  ref = reference_date or datetime.utcnow().date()
  months = (target.year - ref.year) * 12 + (target.month - ref.month)
  if target.day > ref.day:
    months += 1
  if months < 0:
    return 0
  return months


def _timing_months_max_deterministic(timing_text: str, reference_date: Optional[date]) -> Optional[int]:
  text = str(timing_text or "").strip().lower()
  if not text:
    return None
  try:
    import re

    months_match = re.search(r"\b(\d+)\s*(months?|mos?)\b", text)
    if months_match:
      return int(months_match.group(1))
    years_match = re.search(r"\b(\d+)\s*(years?|yrs?)\b", text)
    if years_match:
      return int(years_match.group(1)) * 12

    quarter_match = re.search(r"\bq([1-4])\s*([12]\d{3})\b", text)
    if quarter_match:
      q = int(quarter_match.group(1))
      year = int(quarter_match.group(2))
      month = q * 3
      last_day = calendar.monthrange(year, month)[1]
      return _months_until(date(year, month, last_day), reference_date)
    quarter_match = re.search(r"\b([12]\d{3})\s*q([1-4])\b", text)
    if quarter_match:
      year = int(quarter_match.group(1))
      q = int(quarter_match.group(2))
      month = q * 3
      last_day = calendar.monthrange(year, month)[1]
      return _months_until(date(year, month, last_day), reference_date)

    month_map = {
      "jan": 1,
      "january": 1,
      "feb": 2,
      "february": 2,
      "mar": 3,
      "march": 3,
      "apr": 4,
      "april": 4,
      "may": 5,
      "jun": 6,
      "june": 6,
      "jul": 7,
      "july": 7,
      "aug": 8,
      "august": 8,
      "sep": 9,
      "sept": 9,
      "september": 9,
      "oct": 10,
      "october": 10,
      "nov": 11,
      "november": 11,
      "dec": 12,
      "december": 12,
    }
    month_regex = r"\b(" + "|".join(month_map.keys()) + r")\b"
    month_match = re.search(month_regex + r".*?\b([12]\d{3})\b", text)
    if month_match:
      month_name = month_match.group(1)
      year = int(month_match.group(2))
      month = month_map.get(month_name)
      if month:
        last_day = calendar.monthrange(year, month)[1]
        return _months_until(date(year, month, last_day), reference_date)

    year_end_match = re.search(r"(end of|by end of)\s*([12]\d{3})\b", text)
    if year_end_match:
      year = int(year_end_match.group(2))
      return _months_until(date(year, 12, 31), reference_date)
  except Exception:
    return None
  return None


def _timing_months_max_via_openai(timing_text: str, reference_date: Optional[date]) -> Optional[int]:
  key = _openai_key()
  if not key:
    return None
  timing = str(timing_text or "").strip()
  if timing:
    timing = timing.replace("\u2013", "-").replace("\u2014", "-")
  if not timing:
    return None
  ref_date = reference_date.isoformat() if isinstance(reference_date, date) else None
  system = (
    "You convert milestone timing text into a single integer: the MAX number of months. "
    "If the text contains a range, return the upper bound in months. "
    "If the text references quarters or years, convert to months. "
    "If you cannot determine a number of months, return null. "
    "Return ONLY valid JSON: {\"months_max\": <integer or null>}."
  )
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps({"timing": timing, "reference_date": ref_date})},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return None
  data = resp.json()
  raw = _parse_responses_text(data)
  try:
    parsed = json.loads(raw)
  except Exception:
    parsed = None
  if isinstance(parsed, dict):
    value = parsed.get("months_max")
  else:
    value = raw.strip()
  if value is None:
    return None
  if isinstance(value, (int, float)):
    return int(round(float(value)))
  try:
    return int(round(float(str(value).strip())))
  except Exception:
    return None


def _enrich_milestones_timing(ops_json: Dict[str, Any], reference_date: Optional[date]) -> None:
  milestones = ops_json.get("milestones")
  if isinstance(milestones, str):
    try:
      milestones = json.loads(milestones)
    except Exception:
      milestones = None
  if not isinstance(milestones, list):
    return
  def _coerce_positive_int(value: Any) -> Optional[int]:
    if value is None:
      return None
    if isinstance(value, bool):
      return None
    if isinstance(value, (int, float)):
      if float(value) <= 0:
        return None
      return int(round(float(value)))
    try:
      parsed = int(round(float(str(value).strip())))
    except Exception:
      return None
    return parsed if parsed > 0 else None

  for milestone in milestones:
    if not isinstance(milestone, dict):
      continue
    existing = _coerce_positive_int(milestone.get("timing_months_max"))
    if existing is not None:
      milestone["timing_months_max"] = existing
      continue
    months = _timing_months_max_deterministic(str(milestone.get("timing") or "").strip(), reference_date)
    if months is None:
      months = _timing_months_max_via_openai(str(milestone.get("timing") or "").strip(), reference_date)
    if months is None:
      continue
    milestone["timing_months_max"] = months


def _parse_milestones(raw: Any) -> List[Dict[str, Any]]:
  if raw is None:
    return []
  if isinstance(raw, str):
    try:
      parsed = json.loads(raw)
    except Exception:
      return []
    raw = parsed
  if not isinstance(raw, list):
    return []
  return [m for m in raw if isinstance(m, dict)]


def _build_realism_milestone_context(
  ops_json: Dict[str, Any],
  solved_model_input_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  milestones = _parse_milestones((ops_json or {}).get("milestones"))
  if not milestones:
    return []

  periods = [
    item
    for item in ((solved_model_input_json or {}).get("periods") or [])
    if isinstance(item, dict)
  ]
  max_quarter_index = max(
    [int(_safe_float(item.get("quarter")) or 0) for item in periods if int(_safe_float(item.get("quarter")) or 0) > 0] or [20]
  )
  milestone_context: List[Dict[str, Any]] = []

  for milestone in milestones:
    if not isinstance(milestone, dict):
      continue
    description = str(milestone.get("description") or "").strip()
    timing = str(milestone.get("timing") or "").strip()
    months_max = _safe_int(milestone.get("timing_months_max"))
    target_quarter_index: Optional[int] = None
    if months_max is not None and months_max > 0:
      target_quarter_index = max(1, min(max_quarter_index, int(math.ceil(float(months_max) / 3.0))))
    target_period = next(
      (
        item for item in periods
        if target_quarter_index is not None
        and int(_safe_float(item.get("quarter")) or 0) == target_quarter_index
      ),
      {},
    )
    milestone_context.append(
      {
        "description": description,
        "timing": timing,
        "timing_months_max": months_max,
        "target_quarter_index": target_quarter_index,
        "target_period_date": str(target_period.get("date") or "").strip(),
        "target_period_column": str(target_period.get("column_letter") or "").strip(),
        "is_binding_future_intent": bool(description and (timing or months_max is not None)),
      }
    )
  return milestone_context


def _has_confirmed_milestone(ops_json: Dict[str, Any]) -> bool:
  for milestone in _parse_milestones((ops_json or {}).get("milestones")):
    desc = str(milestone.get("description") or "").strip()
    timing = str(milestone.get("timing") or "").strip()
    if desc and timing:
      return True
  return False


def _ensure_ops_business_naics(conn, ops_json: Dict[str, Any]) -> None:
  if not isinstance(ops_json, dict):
    return
  if not ops_json.get("business_type"):
    return
  if ops_json.get("business_naics_6"):
    return
  try:
    try:
      from business_type_naics import get_naics_from_business_type  # type: ignore
    except Exception:
      from client_intake_and_finmo.business_type_naics import (  # type: ignore
        get_naics_from_business_type,
      )
    ops_json["business_naics_6"] = get_naics_from_business_type(
      conn, ops_json.get("business_type")
    )
  except Exception:
    ops_json.setdefault("business_naics_6", None)


def _extract_ops_pending_milestone(
  *,
  text: str,
  route_intent,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
  try:
    milestone_intent = route_intent(
      consult_type="ops",
      user_message=str(text or "").strip(),
      baseline_json=ops_json,
      shared_context=shared_context,
      recent_messages=[],
      active_focus="ops",
    )
  except Exception:
    return None
  if str(milestone_intent.get("action") or "").strip() != "edit_patch":
    return None
  patch = milestone_intent.get("patch")
  if not isinstance(patch, dict) or not patch:
    return None
  milestones_val = patch.get("milestones")
  if not milestones_val:
    return None
  if isinstance(milestones_val, str):
    try:
      milestones_val = json.loads(milestones_val)
    except Exception:
      return None
  if not isinstance(milestones_val, list):
    return None
  return [m for m in milestones_val if isinstance(m, dict)]


def _extract_ops_pending_milestone_via_openai(
  *,
  text: str,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> Dict[str, Any]:
  key = _openai_key()
  user_text = str(text or "").strip()
  if not key or not user_text:
    return {"captured": False, "milestone": None, "clarification_question": ""}

  schema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "captured": {"type": "boolean"},
      "milestone": {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
          "description": {"type": "string"},
          "timing": {"type": "string"},
        },
        "required": ["description", "timing"],
      },
      "clarification_question": {"type": "string"},
    },
    "required": ["captured", "milestone", "clarification_question"],
  }

  system = (
    "You are extracting a single 12-month business milestone from the user's answer.\n"
    "The user is answering the question: what is one concrete goal they want to hit in about the next 12 months?\n\n"
    "Return ONLY JSON matching the schema.\n"
    "- If the user's answer clearly states one concrete goal, set captured=true and return one milestone object.\n"
    "- milestone.description should be a concise plain-English business goal.\n"
    "- milestone.timing should preserve the user's timeframe in plain English when available (for example: "
    "\"Within the next 12 months\" or \"By Q4 2026\").\n"
    "- If the answer is unclear or does not contain a concrete goal, set captured=false and ask one short clarification question.\n"
    "- Do not ask for permission to continue.\n"
    "- Do not return more than one milestone.\n"
  )
  context = {
    "business_name": str(business_facts.get("name") or "").strip(),
    "business_type": str((ops_json or {}).get("business_type") or "").strip(),
    "unit_name": str((ops_json or {}).get("unit_name") or "").strip(),
    "unit_cadence": str((ops_json or {}).get("unit_cadence") or "").strip(),
    "user_answer": user_text,
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "ops_pending_milestone_extract",
        "schema": schema,
        "strict": True,
      }
    },
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return {"captured": False, "milestone": None, "clarification_question": ""}

  data = resp.json()
  output = data.get("output") or []
  parsed: Optional[Dict[str, Any]] = None
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        parsed = part["json"]
        break
    if parsed:
      break
  if parsed is None:
    try:
      parsed = json.loads(_parse_responses_text(data))
    except Exception:
      parsed = None
  if not isinstance(parsed, dict):
    return {"captured": False, "milestone": None, "clarification_question": ""}
  return {
    "captured": bool(parsed.get("captured", False)),
    "milestone": parsed.get("milestone") if isinstance(parsed.get("milestone"), dict) else None,
    "clarification_question": str(parsed.get("clarification_question") or "").strip(),
  }


def _detect_people_done_adding_via_openai(
  *,
  last_assistant: str,
  user_message: str,
) -> bool:
  key = _openai_key()
  assistant_text = str(last_assistant or "").strip()
  user_text = str(user_message or "").strip()
  if not key or not assistant_text or not user_text:
    return False

  schema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "done_adding_people": {"type": "boolean"},
    },
    "required": ["done_adding_people"],
  }
  system = (
    "You are classifying a People/HR intake reply.\n"
    "Decide whether the client is saying they are done adding key people and wants to move to the full review.\n"
    "Return ONLY JSON matching the schema.\n"
    "Set done_adding_people=true only when the user's reply clearly means there are no more people to add right now.\n"
    "Do not rely on exact keywords; use the assistant question and the user's reply together."
  )
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {
        "role": "user",
        "content": json.dumps(
          {
            "assistant_message": assistant_text,
            "user_message": user_text,
          },
          ensure_ascii=False,
        ),
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "people_done_adding_detect",
        "schema": schema,
        "strict": True,
      }
    },
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return False
  data = resp.json()
  output = data.get("output") or []
  parsed: Optional[Dict[str, Any]] = None
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        parsed = part["json"]
        break
    if parsed:
      break
  if parsed is None:
    try:
      parsed = json.loads(_parse_responses_text(data))
    except Exception:
      parsed = None
  if not isinstance(parsed, dict):
    return False
  return bool(parsed.get("done_adding_people"))


def _build_people_review_payload(
  *,
  conn,
  final_obj: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
  people_json = dict(final_obj or {})
  try:
    from people_roles import (  # type: ignore
      apply_oews_wages,
      apply_oews_wages_to_people,
      format_roles_summary,
    )

    roles = people_json.get("inferred_roles") if isinstance(people_json, dict) else None
    roles = roles if isinstance(roles, list) else []
    people_list = people_json.get("people") if isinstance(people_json, dict) else None
    people_list = people_list if isinstance(people_list, list) else []
    enriched_people = apply_oews_wages_to_people(
      conn,
      people=people_list,
      business_type=ops_json.get("business_type"),
      business_stage=ops_json.get("business_stage"),
      address_state=business_facts.get("address_state"),
      address=business_facts.get("address"),
      business_naics_6=ops_json.get("business_naics_6"),
    )
    enriched_roles = apply_oews_wages(
      conn,
      roles=roles,
      business_type=ops_json.get("business_type"),
      business_stage=ops_json.get("business_stage"),
      address_state=business_facts.get("address_state"),
      address=business_facts.get("address"),
      business_naics_6=ops_json.get("business_naics_6"),
    )
    people_json["business_naics_6"] = ops_json.get("business_naics_6")
    people_json["people"] = enriched_people
    people_json["inferred_roles"] = enriched_roles
    people_json["inferred_roles_summary"] = format_roles_summary(enriched_roles)
  except Exception:
    if "inferred_roles" not in people_json:
      people_json["inferred_roles"] = []
    if "inferred_roles_summary" not in people_json:
      people_json["inferred_roles_summary"] = ""
    if "business_naics_6" not in people_json:
      people_json["business_naics_6"] = None

  if isinstance(people_json, dict):
    people_json.pop("key_people_summary", None)

  try:
    try:
      from fact_templates import render_fact_template  # type: ignore
    except Exception:
      from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

    if isinstance(people_json, dict):
      business_facts_for_render = {
        "name": str(business_facts.get("name") or "").strip(),
        "address": str(business_facts.get("address") or "").strip(),
        "start_date": str(business_facts.get("start_date") or "").strip(),
      }
      shared_ctx_for_render = {
        "operating_model": ops_json,
        "target_market": market_json,
        "people_capability": people_json,
        "financials": financials_json,
      }
      ppl = people_json.get("people")
      if isinstance(ppl, list):
        for p in ppl:
          if not isinstance(p, dict):
            continue
          for fk, fv in list(p.items()):
            if isinstance(fv, str) and "{{fact:" in fv:
              p[fk] = render_fact_template(
                fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
              ).strip()
      roles = people_json.get("inferred_roles")
      if isinstance(roles, list):
        for r in roles:
          if not isinstance(r, dict):
            continue
          for fk, fv in list(r.items()):
            if isinstance(fv, str) and "{{fact:" in fv:
              r[fk] = render_fact_template(
                fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
              ).strip()
  except Exception:
    pass

  key_people_blocks: List[str] = []
  try:
    people_list = people_json.get("people") if isinstance(people_json, dict) else None
    people_list = people_list if isinstance(people_list, list) else []
    for p in people_list:
      if not isinstance(p, dict):
        continue
      para = p.get("paragraph")
      if isinstance(para, str) and para.strip():
        block = para.strip()
        wage_raw = p.get("annual_wage")
        try:
          wage_val = float(wage_raw)
        except Exception:
          wage_val = None
        if wage_val is not None and wage_val > 0:
          wage_fmt = f"${int(round(wage_val)):,.0f}"
          block = f"{block.rstrip()} Estimated annual wage: {wage_fmt}/year."
        key_people_blocks.append(block)
  except Exception:
    key_people_blocks = []

  inferred_roles_summary = str((people_json or {}).get("inferred_roles_summary") or "").strip()
  parts: List[str] = []
  has_people = bool(key_people_blocks)
  has_roles = bool(inferred_roles_summary)
  if has_people and has_roles:
    parts.append(
      "Review this draft (key people narrative + suggested year-1 roles with wages and timing) and tell me any changes."
    )
  elif has_people:
    parts.append("Review this draft (key people narrative) and tell me any changes.")
  elif has_roles:
    parts.append("Review these suggested year-1 roles (with wages and timing) and tell me any changes.")

  if has_people:
    parts.append("\n\n".join(key_people_blocks))
  if has_roles:
    parts.append(inferred_roles_summary)
  assistant_final = "\n\n".join([p for p in parts if p.strip()]).strip()
  if assistant_final:
    assistant_final = f"{assistant_final}\n\n{PEOPLE_CONFIRM_QUESTION}".strip()
  else:
    assistant_final = PEOPLE_CONFIRM_QUESTION

  return people_json, assistant_final

def _propose_ops_competitive_advantage(
  *,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  shared_context: Dict[str, Any],
  confirmed_restatement: Optional[str],
) -> str:
  key = _openai_key()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  system = (
    "You are a senior business consultant defining a company’s competitive advantage.\n\n"
    "This is NOT marketing language.\n"
    "This is an execution-based advantage grounded in how the business actually operates.\n\n"
    "Context:\n"
    "You are given the full operating model, including:\n"
    "- business type and stage\n"
    "- unit definition and pricing\n"
    "- capacity driver (labor / system / demand)\n"
    "- fulfillment and delivery model\n"
    "- geographic scope and coverage\n"
    "- target customer type (consumer / B2B / mixed)\n\n"
    "Your task:\n"
    "Propose ONE concise competitive advantage that clearly explains:\n"
    "1) What this business does meaningfully differently from typical competitors\n"
    "2) Why that difference exists operationally (process, structure, constraints, choices)\n"
    "3) Why it matters economically or experientially to the customer\n"
    "4) Why it is not trivial for competitors to replicate\n\n"
    "Hard rules:\n"
    "- Do NOT use generic phrases (e.g., “high quality,” “great service,” “customer-focused,” “fast,” “personalized”) unless you explain *how* they are structurally enabled.\n"
    "- Do NOT describe multiple advantages — pick the single most defensible one.\n"
    "- Do NOT restate the business description.\n"
    "- Tie the advantage to at least ONE concrete operational choice (e.g., menu design, staffing model, throughput discipline, geographic focus, fulfillment cadence).\n"
    "- Keep it to 2–3 sentences total.\n\n"
    "After proposing the advantage, ask ONE confirmation question:\n"
    "“Does this accurately reflect what truly sets the business apart?”\n\n"
    "If the client disagrees:\n"
    "- Ask ONE targeted clarification question.\n"
    "- Revise the advantage once and ask for confirmation again."
  )
  ops_payload = dict(ops_json or {})
  ops_payload["business_type"] = (ops_json or {}).get("business_type")
  ops_payload["business_naics_6"] = (ops_json or {}).get("business_naics_6")
  context_payload = {
    "confirmed_restatement": confirmed_restatement,
    "ops": ops_payload,
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(context_payload)},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    raise RuntimeError(_format_openai_error(resp))
  data = resp.json()
  raw = _parse_responses_text(data)
  cleaned = " ".join(str(raw or "").split()).strip().strip('"')
  if not cleaned:
    raise RuntimeError("Failed to generate competitive advantage.")
  question = COMPETITIVE_ADVANTAGE_QUESTION
  lower = cleaned.lower()
  q_lower = question.lower()
  if q_lower in lower:
    idx = lower.rfind(q_lower)
    cleaned = cleaned[:idx].strip()
  if not cleaned:
    raise RuntimeError("Failed to generate competitive advantage.")
  return cleaned


def _build_business_type_candidates(
  *,
  conn,
  messages: List[Dict[str, str]],
  restatement_text: Optional[str] = None,
) -> List[str]:
  """
  Select a single best-matching business_type token from naics_master.business_types,
  using the latest confirmed restatement as the primary signal.
  """
  try:
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

    if restatement_text is None:
      restatement_text = _extract_confirmed_restatement(messages)
    if not restatement_text or not all_business_types:
      return []

    def _pick_index(restatement: str, options: List[str]) -> Optional[int]:
      key = _openai_key()
      if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
      system = (
        "You are selecting the single best-matching business type from a fixed list.\n"
        "Return EXACTLY ONE integer index from the provided list. Do not add any text.\n"
        "If multiple are close, pick the closest operationally.\n"
        "Return only the index and nothing else."
      )
      numbered = [f"{idx}. {val}" for idx, val in enumerate(options, start=1)]
      payload = {
        "model": _openai_model(),
        "input": [
          {"role": "system", "content": system},
          {"role": "user", "content": f"Restatement:\n{restatement}"},
          {"role": "user", "content": "Business types:\n" + "\n".join(numbered)},
        ],
      }
      resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload=payload,
      )
      if resp.status_code >= 400:
        raise RuntimeError(_format_openai_error(resp))
      raw = _parse_responses_text(resp.json())
      raw_text = str(raw or "").strip().strip('"')
      try:
        idx = int(raw_text)
      except Exception:
        return None
      return idx if 1 <= idx <= len(options) else None

    def _pick_ranked_indices(
      restatement: str,
      options: List[str],
      k_expected: int,
    ) -> Optional[List[int]]:
      key = _openai_key()
      if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
      system = (
        "You are selecting the best-matching business types from a fixed list.\n"
        f"Return EXACTLY {k_expected} integer indices, ranked best-to-worst.\n"
        "Return a comma-separated list of integers and nothing else."
      )
      numbered = [f"{idx}. {val}" for idx, val in enumerate(options, start=1)]
      payload = {
        "model": _openai_model(),
        "input": [
          {"role": "system", "content": system},
          {"role": "user", "content": f"Restatement:\n{restatement}"},
          {"role": "user", "content": "Business types:\n" + "\n".join(numbered)},
        ],
      }
      resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload=payload,
      )
      if resp.status_code >= 400:
        raise RuntimeError(_format_openai_error(resp))
      raw = _parse_responses_text(resp.json())
      raw_text = str(raw or "").strip().strip('"')
      try:
        import re

        parts = [int(x) for x in re.findall(r"\d+", raw_text)]
      except Exception:
        return None
      if len(parts) != k_expected:
        return None
      if len(set(parts)) != len(parts):
        return None
      if any(p < 1 or p > len(options) for p in parts):
        return None
      return parts

    batch_size = 300
    k = 3
    winners: List[str] = []
    for i in range(0, len(all_business_types), batch_size):
      batch = all_business_types[i : i + batch_size]
      if not batch:
        continue
      k_expected = min(k, len(batch))
      picks = _pick_ranked_indices(restatement_text, batch, k_expected)
      if picks is None:
        picks = _pick_ranked_indices(restatement_text, batch, k_expected)
      if picks is None:
        logger.warning(
          "business_type_ranked_pick_failed restatement=%r batch_index=%d",
          restatement_text,
          i // batch_size,
        )
        raise RuntimeError("Failed to select ranked business_type indices.")
      for idx in picks:
        winners.append(batch[idx - 1])

    if not winners:
      raise RuntimeError("No business_type candidates selected.")

    # Deduplicate while preserving order.
    reduced: List[str] = []
    seen = set()
    for bt in winners:
      if bt in seen:
        continue
      seen.add(bt)
      reduced.append(bt)

    if len(reduced) == 1:
      logger.warning("business_type_reduced_candidates=%s", reduced)
      return [reduced[0]]

    final_idx = _pick_index(restatement_text, reduced)
    if final_idx is None:
      final_idx = _pick_index(restatement_text, reduced)
    if final_idx is None:
      logger.warning(
        "business_type_final_pick_failed restatement=%r total=%d",
        restatement_text,
        len(reduced),
      )
      raise RuntimeError("Failed to select final business_type index.")

    logger.warning("business_type_reduced_candidates=%s", reduced)
    logger.warning(
      "business_type_final_pick index=%d value=%r",
      final_idx,
      reduced[final_idx - 1],
    )
    return [reduced[final_idx - 1]]
  except RuntimeError:
    raise
  except Exception:
    return []


def _normalize_business_type_from_candidates(
  raw_value: Any, candidates: List[str]
) -> Any:
  """
  Normalize a business_type value to the closest candidate label (case-insensitive).
  Falls back to the raw value if no candidates are available.
  """
  raw = str(raw_value or "").strip()
  if not raw or not candidates:
    return raw_value
  raw_lower = raw.lower()
  for candidate in candidates:
    if str(candidate or "").strip().lower() == raw_lower:
      return candidate
  try:
    from difflib import SequenceMatcher

    best = None
    best_score = 0.0
    for candidate in candidates:
      cand = str(candidate or "").strip()
      if not cand:
        continue
      score = SequenceMatcher(None, raw_lower, cand.lower()).ratio()
      if score > best_score:
        best_score = score
        best = cand
    return best if best else raw_value
  except Exception:
    return raw_value


def _compute_focus_and_confirm_question(
  *,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  ops_confirmed: bool,
  market_confirmed: bool,
  people_confirmed: bool,
  financials_confirmed: bool,
) -> Tuple[str, Optional[str]]:
  del ops_json, market_json, people_json, financials_json
  # No realtime missing-fields gating; progression follows confirmations in order.
  if not ops_confirmed:
    return ("ops", None)
  if not market_confirmed:
    return ("market", None)
  if not people_confirmed:
    return ("people", None)
  if not financials_confirmed:
    return ("financials", None)
  return ("done", None)


def _next_focus(current: str) -> str:
  order = ["ops", "market", "people", "financials", "done"]
  cur = str(current or "").strip().lower()
  if cur not in order:
    return "ops"
  idx = order.index(cur)
  return order[min(idx + 1, len(order) - 1)]


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
  fulfillment_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  """
  Apply patch keys scoped as "<group>.<field>" into the canonical section objects.
  """
  next_business = dict(business_facts)
  next_ops = dict(ops_json)
  next_market = dict(market_json)
  next_people = dict(people_json)
  next_financials = dict(financials_json)
  next_fulfillment = dict(fulfillment_json)

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
    elif group == "fulfillment":
      next_fulfillment[field] = value

  return next_business, next_ops, next_market, next_people, next_financials, next_fulfillment


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
        "financials_year1_json": draft.get("financials_year1_json"),
        "fulfillment_json": draft.get("fulfillment_json"),
        "model_input_json": draft.get("model_input_json"),
        "finmo_json": draft.get("finmo_json"),
        "planning_run_json": draft.get("planning_run_json"),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def _run_planning_system_for_draft(
  *,
  conn,
  draft_id: str,
) -> Dict[str, Any]:
  if build_shared_context is None:
    raise RuntimeError("build_shared_context_unavailable")
  draft = get_draft(conn, draft_id=str(draft_id).strip())
  if str(draft.get("active_focus") or "").strip().lower() != "done":
    raise RuntimeError("draft_not_complete")

  try:
    from financials_consultant import estimate_marketing_baseline_from_context  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_consultant import estimate_marketing_baseline_from_context  # type: ignore
  try:
    from financials_year1 import assemble_financials_year1  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_year1 import assemble_financials_year1  # type: ignore

  ops_json = _parse_json_dict(draft.get("operating_model_json"))
  market_json = _parse_json_dict(draft.get("target_market_json"))
  people_json = _parse_json_dict(draft.get("people_json"))
  financials_json = _parse_json_dict(draft.get("financials_json"))
  financials_year1_json = _parse_json_dict(draft.get("financials_year1_json"))
  fulfillment_json = _parse_json_dict(draft.get("fulfillment_json"))
  marketing_model_json = _parse_json_dict(draft.get("marketing_model_json"))
  planning_run_json = _parse_json_dict(draft.get("planning_run_json"))

  business_facts: Dict[str, Any] = {
    "name": draft.get("business_name"),
    "business_name": draft.get("business_name"),
    "address": draft.get("business_address"),
    "start_date": draft.get("business_start_date"),
    "address_street": draft.get("address_street"),
    "address_city": draft.get("address_city"),
    "address_state": draft.get("address_state"),
    "address_zip": draft.get("address_zip"),
    "address_country": draft.get("address_country"),
  }

  def _persist_system_stage(
    *,
    stage: str,
    status: str,
    planning_mode: str = "",
    planning_mode_reason: str = "",
    prompt_file: str = "",
    gpt_narrative: str = "",
    gpt_grid_metadata: Optional[Dict[str, Any]] = None,
    grid_application_summary: Optional[Dict[str, Any]] = None,
    model_input_payload: Optional[Dict[str, Any]] = None,
    finmo_payload: Optional[Dict[str, Any]] = None,
  ) -> Dict[str, Any]:
    payload = _build_planning_run_payload(
      stage=stage,
      status=status,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
      gpt_narrative=gpt_narrative,
      gpt_grid_metadata=copy.deepcopy(gpt_grid_metadata or {}),
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    )
    append_messages(
      conn,
      draft_id=str(draft_id).strip(),
      new_messages=[],
      model_input_json=model_input_payload,
      finmo_json=finmo_payload,
      planning_run_json=payload,
      active_focus="done",
      status="completed",
      completed=True,
    )
    return payload

  shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
  shared_context = dict(shared_context or {})
  shared_context["operating_model"] = ops_json
  shared_context["target_market"] = market_json
  shared_context["people_capability"] = people_json
  shared_context["financials"] = financials_json

  base_year1 = assemble_financials_year1(shared_context, None)
  if _year1_drivers_conflict(financials_year1_json, base_year1):
    financials_year1_json = base_year1
  else:
    financials_year1_json = assemble_financials_year1(shared_context, financials_year1_json)
  if isinstance(financials_year1_json, dict) and financials_year1_json:
    shared_context["financials_year1_json"] = financials_year1_json

  try:
    marketing_model_json = _compute_marketing_model_json(
      conn=conn,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      existing_marketing_model_json=marketing_model_json,
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
    )
  except Exception:
    marketing_model_json = dict(marketing_model_json or {})
  shared_context["marketing"] = marketing_model_json

  try:
    from finmo_bridge import sync_planning_state_to_finmo  # type: ignore
  except Exception:
    from client_intake_and_finmo.finmo_bridge import sync_planning_state_to_finmo  # type: ignore
  try:
    from quarter_grid import determine_planning_mode, generate_live_quarter_grid_plan, apply_live_quarter_grid_plan  # type: ignore
  except Exception:
    from client_intake_and_finmo.quarter_grid import determine_planning_mode, generate_live_quarter_grid_plan, apply_live_quarter_grid_plan  # type: ignore

  sync_result = sync_planning_state_to_finmo(
    finmo_path="",
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    controller_input_seed=[],
    forecast_quarters=[],
    calibration_spec=None,
  )
  model_input_json = (
    sync_result.get("model_input_json")
    if isinstance(sync_result.get("model_input_json"), dict)
    else {}
  )
  finmo_json = (
    sync_result.get("finmo_json")
    if isinstance(sync_result.get("finmo_json"), dict)
    else {}
  )
  planning_run_json = _persist_system_stage(
    stage="baseline_ready",
    status="running",
    model_input_payload=model_input_json,
    finmo_payload=finmo_json,
  )

  planning_choice = determine_planning_mode(
    ops_json=dict(ops_json or {}),
    target_market_json=dict(market_json or {}),
    people_json=dict(people_json or {}),
    financials_json=dict(financials_json or {}),
    financials_year1_json=dict(financials_year1_json or {}),
    fulfillment_json=dict(fulfillment_json or {}),
    marketing_model_json=dict(marketing_model_json or {}),
    model_input_json=copy.deepcopy(model_input_json),
    finmo_json=copy.deepcopy(finmo_json),
    business_facts=copy.deepcopy(business_facts or {}),
  )
  planning_mode = str(planning_choice.get("planning_mode") or "").strip()
  planning_mode_reason = str(planning_choice.get("planning_mode_reason") or "").strip()
  planning_run_json = _persist_system_stage(
    stage="quarter_grid_running",
    status="running",
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=str(planning_choice.get("prompt_file") or "").strip(),
    model_input_payload=model_input_json,
    finmo_payload=finmo_json,
  )

  planning_result = generate_live_quarter_grid_plan(
    business_name=str(business_facts.get("name") or "").strip(),
    planning_mode=planning_mode,
    model_input_json=copy.deepcopy(model_input_json),
    finmo_json=copy.deepcopy(finmo_json),
    ops_json=ops_json,
    target_market_json=market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    realism_memo_json=_parse_json_dict(draft.get("realism_memo_json")),
    business_facts=copy.deepcopy(business_facts or {}),
  )
  validation = planning_result.get("validation") if isinstance(planning_result.get("validation"), dict) else {}
  if (
    list(validation.get("missing_rows") or [])
    or list(validation.get("extra_rows") or [])
    or list(validation.get("duplicate_rows") or [])
    or list(validation.get("malformed_rows") or [])
  ):
    raise RuntimeError("planning_grid_validation_failed")
  planning_run_json = _persist_system_stage(
    stage="quarter_grid_ready",
    status="ready_for_grid_application",
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=str(planning_result.get("prompt_file") or "").strip(),
    gpt_narrative=str(planning_result.get("gpt_narrative") or "").strip(),
    gpt_grid_metadata=copy.deepcopy(planning_result.get("metadata") or {}),
    model_input_payload=model_input_json,
    finmo_payload=finmo_json,
  )

  grid_application_result = apply_live_quarter_grid_plan(
    baseline_model_input_json=copy.deepcopy(model_input_json),
    grid_json=copy.deepcopy(planning_result.get("grid_json") or {}),
  )
  grid_application_summary = (
    grid_application_result.get("application_summary")
    if isinstance(grid_application_result.get("application_summary"), dict)
    else {}
  )
  applied_model_input_json = (
    grid_application_result.get("applied_model_input_json")
    if isinstance(grid_application_result.get("applied_model_input_json"), dict)
    else {}
  )
  applied_finmo_json = (
    grid_application_result.get("applied_finmo_json")
    if isinstance(grid_application_result.get("applied_finmo_json"), dict)
    else {}
  )
  realism_resolution_loop = _run_realism_resolution_loop(
    conn=conn,
    draft_id=str(draft_id).strip(),
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    target_market_json=copy.deepcopy(market_json or {}),
    people_json=copy.deepcopy(people_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    financials_year1_json=copy.deepcopy(financials_year1_json or {}),
    fulfillment_json=copy.deepcopy(fulfillment_json or {}),
    marketing_model_json=copy.deepcopy(marketing_model_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=str(planning_result.get("prompt_file") or "").strip(),
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    catalog_source_model_input_json=copy.deepcopy(model_input_json),
    applied_model_input_json=copy.deepcopy(applied_model_input_json),
    applied_finmo_json=copy.deepcopy(applied_finmo_json),
  )
  realism_memo_before_resolution = (
    realism_resolution_loop.get("initial_memo")
    if isinstance(realism_resolution_loop.get("initial_memo"), dict)
    else {}
  )
  realism_resolution_iterations = [
    item for item in (realism_resolution_loop.get("iterations") or []) if isinstance(item, dict)
  ]
  realism_resolution_stop_reason = str(realism_resolution_loop.get("stop_reason") or "").strip()
  realism_resolution_iteration_count = int(_safe_float(realism_resolution_loop.get("iteration_count")) or 0)
  realism_resolution_decision = (
    realism_resolution_loop.get("last_decision")
    if isinstance(realism_resolution_loop.get("last_decision"), dict)
    else {}
  )
  realism_resolution_plan = (
    realism_resolution_loop.get("last_plan")
    if isinstance(realism_resolution_loop.get("last_plan"), dict)
    else {}
  )
  realism_resolution_result = (
    realism_resolution_loop.get("last_result")
    if isinstance(realism_resolution_loop.get("last_result"), dict)
    else {}
  )
  realism_resolution_verification = (
    realism_resolution_loop.get("last_verification")
    if isinstance(realism_resolution_loop.get("last_verification"), dict)
    else {}
  )
  realism_resolved_model_input_json = (
    realism_resolution_loop.get("final_model_input_json")
    if isinstance(realism_resolution_loop.get("final_model_input_json"), dict)
    else applied_model_input_json
  )
  realism_resolved_finmo_json = (
    realism_resolution_loop.get("final_finmo_json")
    if isinstance(realism_resolution_loop.get("final_finmo_json"), dict)
    else applied_finmo_json
  )
  realism_memo_json = (
    realism_resolution_loop.get("realism_memo_json")
    if isinstance(realism_resolution_loop.get("realism_memo_json"), dict)
    else {}
  )
  realism_issue_ledger = (
    realism_resolution_loop.get("issue_ledger")
    if isinstance(realism_resolution_loop.get("issue_ledger"), list)
    else []
  )
  controller_resolution_state = _build_controller_resolution_state_from_issue_ledger(
    issue_status_records=copy.deepcopy(realism_issue_ledger),
    iteration=realism_resolution_iteration_count,
    verification_payload=copy.deepcopy(realism_resolution_verification),
  )
  resolution_summary: Dict[str, Any] = {}
  final_model_input_json = copy.deepcopy(realism_resolved_model_input_json)
  final_finmo_json = copy.deepcopy(realism_resolved_finmo_json)
  first_pass_handoff = _build_first_pass_handoff_payload(
    draft_id=str(draft_id).strip(),
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=str(planning_result.get("prompt_file") or "").strip(),
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    applied_model_input_json=copy.deepcopy(final_model_input_json),
    applied_finmo_json=copy.deepcopy(final_finmo_json),
  )
  cash_strategy_review_context = _build_cash_strategy_review_context_payload(
    draft_id=str(draft_id).strip(),
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=str(planning_result.get("prompt_file") or "").strip(),
    solved_model_input_json=copy.deepcopy(final_model_input_json),
    solved_finmo_json=copy.deepcopy(final_finmo_json),
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
  )
  cash_strategy_review_decision = _run_cash_strategy_review_openai(
    draft_id=str(draft_id).strip(),
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    first_pass_handoff=copy.deepcopy(first_pass_handoff),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
    solved_model_input_json=copy.deepcopy(final_model_input_json),
    solved_finmo_json=copy.deepcopy(final_finmo_json),
  )
  cash_strategy_second_pass_plan = _build_cash_strategy_second_pass_plan(
    review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
    solved_model_input_json=copy.deepcopy(final_model_input_json),
    financials_json=copy.deepcopy(financials_json or {}),
  )
  cash_strategy_second_pass_result = _apply_followup_exact_updates(
    review_plan=copy.deepcopy(cash_strategy_second_pass_plan),
    current_model_input_json=copy.deepcopy(final_model_input_json),
    contract_version="cash_strategy_second_pass_result_v1",
  )
  cash_strategy_recheck_verification: Dict[str, Any] = {}
  if (
    isinstance(cash_strategy_second_pass_result.get("updated_model_input_json"), dict)
    and cash_strategy_second_pass_result.get("status") == "completed"
  ):
    final_model_input_json = copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or {})
    final_finmo_json = copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or {})
    strategy_recheck_iteration = max(1, realism_resolution_iteration_count + 1)
    strategy_recheck_memo = _build_realism_memo_from_issue_ledger(
      before_memo=copy.deepcopy(realism_memo_json),
      issue_status_records=copy.deepcopy(realism_issue_ledger),
      resolution_summary=copy.deepcopy(resolution_summary),
      iteration=strategy_recheck_iteration,
      issue_keys=_issue_keys_from_status_records(copy.deepcopy(realism_issue_ledger), status_filter="open"),
    )
    strategy_recheck_ledger = _filter_issue_status_records(
      issue_status_records=copy.deepcopy(realism_issue_ledger),
      issue_keys=_issue_keys_from_status_records(copy.deepcopy(realism_issue_ledger), status_filter="open"),
    )
    strategy_recheck_issue_packets = _build_issue_packets_from_issue_ledger(
      issue_status_records=copy.deepcopy(strategy_recheck_ledger),
      prior_decision_payload=copy.deepcopy(realism_resolution_decision),
    )
    if strategy_recheck_issue_packets:
      cash_strategy_recheck_verification = _run_realism_verification_openai(
        draft_id=str(draft_id).strip(),
        business_facts=copy.deepcopy(business_facts or {}),
        ops_json=copy.deepcopy(ops_json or {}),
        realism_memo_before_resolution=copy.deepcopy(strategy_recheck_memo),
        realism_resolution_decision={
          "decision": {
            "issue_packets": copy.deepcopy(strategy_recheck_issue_packets),
          }
        },
        realism_resolution_plan={
          "status": "strategy_recheck_verification",
          "translated_action_packages": [],
        },
        realism_resolution_result={
          "applied_updates": copy.deepcopy(
            cash_strategy_second_pass_result.get("applied_updates") or []
          ),
        },
        updated_model_input_json=copy.deepcopy(final_model_input_json),
        updated_finmo_json=copy.deepcopy(final_finmo_json),
      )
      strategy_recheck_ledger = _apply_realism_verification_to_issue_status_records(
        issue_status_records=copy.deepcopy(strategy_recheck_ledger),
        verification_payload=copy.deepcopy(cash_strategy_recheck_verification),
        iteration=strategy_recheck_iteration,
        allowed_issue_keys=_issue_keys_from_status_records(copy.deepcopy(strategy_recheck_ledger)),
        allow_new_records=False,
      )
    else:
      strategy_recheck_ledger = []
    if isinstance(cash_strategy_second_pass_result, dict):
      cash_strategy_second_pass_result["strategy_recheck_verification"] = copy.deepcopy(
        cash_strategy_recheck_verification
      )
    resolution_summary = _build_resolution_summary_from_issue_ledger(
      before_memo=copy.deepcopy(strategy_recheck_memo),
      issue_status_records=copy.deepcopy(strategy_recheck_ledger),
      verification_payload=copy.deepcopy(cash_strategy_recheck_verification),
    )
    realism_memo_json = _build_realism_memo_from_issue_ledger(
      before_memo=copy.deepcopy(strategy_recheck_memo),
      issue_status_records=copy.deepcopy(strategy_recheck_ledger),
      resolution_summary=copy.deepcopy(resolution_summary),
      iteration=strategy_recheck_iteration,
      verification_payload=copy.deepcopy(cash_strategy_recheck_verification),
    )
    realism_issue_ledger = copy.deepcopy(strategy_recheck_ledger)
    controller_resolution_state = _build_controller_resolution_state_from_issue_ledger(
      issue_status_records=copy.deepcopy(realism_issue_ledger),
      iteration=strategy_recheck_iteration,
      verification_payload=copy.deepcopy(cash_strategy_recheck_verification),
    )
  cash_strategy_effect_summary = _build_cash_strategy_effect_summary(
    financials_json=copy.deepcopy(financials_json or {}),
    review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
    second_pass_result=copy.deepcopy(cash_strategy_second_pass_result),
    first_pass_finmo_json=copy.deepcopy(realism_resolved_finmo_json),
    final_finmo_json=copy.deepcopy(final_finmo_json),
  )
  persisted_realism_memo = _build_persisted_realism_memo_payload(
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    working_memo=copy.deepcopy(realism_memo_json),
  )
  diagnostics_snapshot = {
    "contract_version": "planning_diagnostics_snapshot_v1",
    "baseline_model_input_json": copy.deepcopy(model_input_json),
    "baseline_finmo_json": copy.deepcopy(finmo_json),
    "grid_applied_model_input_json": copy.deepcopy(applied_model_input_json),
    "grid_applied_finmo_json": copy.deepcopy(applied_finmo_json),
    "realism_resolved_model_input_json": copy.deepcopy(realism_resolved_model_input_json),
    "realism_resolved_finmo_json": copy.deepcopy(realism_resolved_finmo_json),
    "final_model_input_json": copy.deepcopy(final_model_input_json),
    "final_finmo_json": copy.deepcopy(final_finmo_json),
  }
  next_planning_run_json = _build_planning_run_payload(
    stage="cash_strategy_completed",
    status="completed",
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    resolution_summary=copy.deepcopy(resolution_summary),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=str(planning_result.get("prompt_file") or "").strip(),
    gpt_narrative=str(planning_result.get("gpt_narrative") or "").strip(),
    gpt_grid_metadata=copy.deepcopy(planning_result.get("metadata") or {}),
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=realism_memo_before_resolution,
    realism_resolution_decision=realism_resolution_decision,
    realism_resolution_plan=realism_resolution_plan,
    realism_resolution_result=realism_resolution_result,
    realism_resolution_verification=realism_resolution_verification,
    realism_resolution_iterations=realism_resolution_iterations,
    realism_resolution_stop_reason=realism_resolution_stop_reason,
    realism_resolution_iteration_count=realism_resolution_iteration_count,
    first_pass_handoff=copy.deepcopy(first_pass_handoff),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan),
    cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result),
    cash_strategy_effect_summary=copy.deepcopy(cash_strategy_effect_summary),
    diagnostics_snapshot=copy.deepcopy(diagnostics_snapshot),
  )

  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    operating_model_json=ops_json,
    target_market_json=market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    realism_memo_json=persisted_realism_memo,
    fulfillment_json=fulfillment_json,
    model_input_json=final_model_input_json,
    finmo_json=final_finmo_json,
    planning_run_json=next_planning_run_json,
    active_focus="done",
    business_facts=business_facts,
    status="completed",
    completed=True,
  )

  return {
    "draft_id": str(draft_id).strip(),
    "planning_run_json": next_planning_run_json,
    "realism_memo_json": persisted_realism_memo,
    "model_input_json": final_model_input_json,
    "finmo_json": final_finmo_json,
  }


def post_intake_consult_system_run_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = str(payload.get("draft_id") or "").strip()
  if not draft_id:
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    try:
      result = _run_planning_system_for_draft(conn=conn, draft_id=draft_id)
    except RuntimeError as exc:
      detail = str(exc).strip() or "system_run_failed"
      if detail == "draft_not_complete":
        return (jsonify({"error": "conflict", "detail": detail}), 409)
      app.logger.exception("System run failed for draft %s: %s", draft_id, detail)
      return (jsonify({"error": "system_run_failed", "detail": detail}), 500)
    except Exception as exc:
      app.logger.exception("System run failed for draft %s", draft_id)
      return (jsonify({"error": "system_run_failed", "detail": str(exc)}), 500)

    planning_run_json = (
      result.get("planning_run_json")
      if isinstance(result.get("planning_run_json"), dict)
      else {}
    )
    return jsonify(
      {
        "status": "ok",
        "draft_id": str(result.get("draft_id") or draft_id).strip(),
        "action": "system_run_complete",
        "assistant_message": "System run complete.",
        "planning_run_json": planning_run_json,
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def _parse_json_value(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(str(raw))
  except Exception:
    return raw

def _serialize_debug_draft_row(row: Dict[str, Any]) -> Dict[str, Any]:
  if not isinstance(row, dict):
    return {}
  json_columns = {
    "messages_json",
    "operating_model_json",
    "target_market_json",
    "people_json",
    "financials_json",
    "marketing_model_json",
    "financials_year1_json",
    "realism_memo_json",
    "model_input_json",
    "finmo_json",
    "planning_run_json",
    "pending_ops_milestone_json",
    "fulfillment_json",
  }
  serialized: Dict[str, Any] = {}
  for key, value in row.items():
    if key in json_columns:
      serialized[key] = _parse_json_value(value)
    elif isinstance(value, (datetime, date)):
      serialized[key] = value.isoformat(sep=" ")
    else:
      serialized[key] = value
  return serialized


def get_intake_consult_debug_state_handler(*, app, request, draft_id: str):
  if request.method == "OPTIONS":
    return ("", 204)

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
        "table": "intake_consult_drafts",
        "draft_id": str(draft_id).strip(),
        "controller_resolution_state": (
          _parse_json_dict(draft.get("planning_run_json")).get("controller_resolution_state")
          if isinstance(_parse_json_dict(draft.get("planning_run_json")).get("controller_resolution_state"), dict)
          else {}
        ),
        "row": _serialize_debug_draft_row(draft),
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
    from people_capability_consultant import (  # type: ignore
      extract_people_collection_progress,
      people_capability_chat_turn,
      people_capability_finalize,
    )
    from financials_year1 import (  # type: ignore
      assemble_financials_year1,
      build_revenue_driver_signature,
      build_revenue_guardrail_signals,
      build_revenue_constraints_snippet,
      build_revenue_math_line,
    )
    from api_handlers.fact_propagation import propagate_shared_facts
    from api_handlers.revenue_guardrail_state import acknowledge_signature, get_acknowledged_signature
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
    financials_year1_json = _parse_json_dict(consult.get("financials_year1_json"))
    fulfillment_json = _parse_json_dict(consult.get("fulfillment_json"))
    pending_ops_milestone = _parse_pending_bool(consult.get("pending_ops_milestone_json"))

    _ensure_ops_business_naics(conn, ops_json)
    restatement_locked_prior = bool(ops_json.get("business_type_candidates_locked"))

    ops_confirmed = bool(consult.get("ops_confirmed"))
    market_confirmed = bool(consult.get("market_confirmed"))
    people_confirmed = bool(consult.get("people_confirmed"))
    financials_confirmed = bool(consult.get("financials_confirmed"))
    ops_finalize_proposed = bool(consult.get("ops_finalize_proposed"))
    market_finalize_proposed = bool(consult.get("market_finalize_proposed"))
    people_finalize_proposed = bool(consult.get("people_finalize_proposed"))

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
    address_keys = ("address_street", "address_city", "address_state", "address_zip", "address_country")
    payload_parts: Dict[str, str] = {}
    for key in address_keys:
      if payload.get(key) is None:
        payload_parts[key] = ""
        continue
      payload_parts[key] = str(payload.get(key) or "").strip()
    has_all_parts = all(payload_parts.values())
    if payload.get("address") is not None:
      addr_raw = str(payload.get("address") or "").strip()
      if addr_raw and has_all_parts:
        business_facts["address"] = addr_raw
    start_date_raw = payload.get("business_start_date")
    if start_date_raw is None:
      start_date_raw = payload.get("businessStartDate") or payload.get("business_startDate")
    if start_date_raw is not None:
      sd_raw = str(start_date_raw or "").strip()
      if sd_raw:
        business_facts["start_date"] = sd_raw

    if has_all_parts:
      for key, val in payload_parts.items():
        if val:
          business_facts[key] = val

    current_date = datetime.utcnow().date()
    current_date_iso = current_date.isoformat()
    business_stage_hint = _infer_business_stage(business_facts.get("start_date"), current_date)

    focus, confirm_question = _compute_focus_and_confirm_question(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      ops_confirmed=ops_confirmed,
      market_confirmed=market_confirmed,
      people_confirmed=people_confirmed,
      financials_confirmed=financials_confirmed,
    )

    shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
    shared_context = dict(shared_context or {})
    shared_context["operating_model"] = ops_json
    shared_context["target_market"] = market_json
    shared_context["people_capability"] = people_json
    shared_context["financials"] = financials_json
    base_year1 = assemble_financials_year1(shared_context, None)
    if _year1_drivers_conflict(financials_year1_json, base_year1):
      financials_year1_json = base_year1
    else:
      financials_year1_json = assemble_financials_year1(shared_context, financials_year1_json)
    financials_json, financials_year1_json = _sync_financials_consult_persistence_state(
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      marketing_model_json=marketing_model_json,
    )
    shared_context["financials"] = financials_json
    if isinstance(financials_year1_json, dict) and financials_year1_json:
      shared_context["financials_year1_json"] = financials_year1_json

    def _refresh_marketing_model() -> Dict[str, Any]:
      nonlocal marketing_model_json, shared_context
      try:
        marketing_model_json = _compute_marketing_model_json(
          conn=conn,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_year1_json=financials_year1_json,
          business_facts=business_facts,
          existing_marketing_model_json=marketing_model_json,
          estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
        )
      except Exception:
        marketing_model_json = dict(marketing_model_json or {})
      shared_context["marketing"] = marketing_model_json
      return marketing_model_json

    def _persist_intake_completion(
      *,
      new_messages: List[Dict[str, str]],
      ops_value: Dict[str, Any],
      market_value: Dict[str, Any],
      people_value: Dict[str, Any],
      financials_value: Dict[str, Any],
      financials_year1_value: Dict[str, Any],
      marketing_value: Dict[str, Any],
      confirmations_value: Optional[Dict[str, bool]] = None,
      flat_fields_value: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
      planning_run_json = _build_intake_complete_planning_run_payload()
      realism_memo_json = generate_realism_memo_payload_safe(
        ops_json=ops_value,
        financials_json=financials_value,
      )
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=new_messages,
        operating_model_json=ops_value,
        target_market_json=market_value,
        people_json=people_value,
        financials_json=financials_value,
        financials_year1_json=financials_year1_value,
        marketing_model_json=marketing_value,
        realism_memo_json=realism_memo_json,
        planning_run_json=planning_run_json,
        active_focus="done",
        confirmations=confirmations_value,
        business_facts=business_facts,
        status="completed",
        completed=True,
        flat_fields=flat_fields_value,
      )
      return planning_run_json

    _refresh_marketing_model()
    revenue_math_line = build_revenue_math_line(
      financials_year1_json,
      unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
    )
    revenue_constraints_snippet = build_revenue_constraints_snippet(
      shared_context,
      financials_year1_json,
      business_start_date=str(business_facts.get("start_date") or "").strip() or None,
    )
    guardrail_signals = build_revenue_guardrail_signals(
      shared_context,
      financials_year1_json,
      business_start_date=str(business_facts.get("start_date") or "").strip() or None,
      fulfillment_context=fulfillment_json,
    )
    driver_signature = build_revenue_driver_signature(financials_year1_json)
    guardrail_acknowledged = (
      get_acknowledged_signature(str(draft_id).strip()) == driver_signature
    )
    guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged

    if starting:
      start_instruction = _start_instruction_for_focus(focus)
      turn_messages = [*messages, {"role": "user", "content": start_instruction}]
      intake_context: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "fulfillment_json": fulfillment_json,
      }
      if focus == "market":
        consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
        if consumer_type not in ("consumer", "b2b", "mixed"):
          consumer_type = "consumer"
        intake_context["consumer_type"] = consumer_type
      intake_context["financials_year1_json"] = financials_year1_json
      intake_context["revenue_math_line"] = revenue_math_line
      intake_context["revenue_constraints_snippet"] = revenue_constraints_snippet
      intake_context["revenue_driver_patch"] = None
      intake_context["revenue_guardrail_triggered"] = guardrail_triggered
      intake_context["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
      intake_context["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

      # Target Market is model-interpreted every turn and returns a structured patch,
      # allowing us to persist the Target Market JSON incrementally (no controller parsing).
      turn: Dict[str, Any] = {}
      closeout: Optional[Dict[str, Any]] = None
      if focus == "ops":
        turn = consultant_chat_turn(intake_context=intake_context, conversation_messages=turn_messages) or {}
        ops_json = _apply_model_ops_patch(ops_json, turn.get("patch") if isinstance(turn, dict) else None)
        try:
          shared_context["operating_model"] = ops_json
        except Exception:
          pass
      elif focus == "market":
        turn = target_market_chat_turn(intake_context=intake_context, conversation_messages=turn_messages) or {}
        try:
          if isinstance(market_json, dict):
            patch_obj = turn.get("patch") if isinstance(turn, dict) else None
            if isinstance(patch_obj, dict):
              allowed_keys = {
                "consumer_type",
                "gender_age_intent",
                "income_intent",
                "b2b_industry_terms",
                "b2b_size_bands",
                "b2b_age_bands",
              }
              for k, v in patch_obj.items():
                key = str(k or "").strip()
                if not key:
                  continue
                if key.startswith("market."):
                  key = key.split(".", 1)[1].strip()
                if key in allowed_keys:
                  # In strict json_schema, the model must always output every patch key.
                  # We treat null values as "no change" to avoid wiping prior answers.
                  if v is None:
                    continue
                  market_json[key] = v
        except Exception:
          pass
      elif focus == "people":
        turn = people_capability_chat_turn(intake_context=intake_context, conversation_messages=turn_messages) or {}
      elif focus == "financials":
        turn, financials_json = _build_financials_live_turn(
          conn=conn,
          intake_context=intake_context,
          conversation_messages=turn_messages,
          shared_context=shared_context,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          guardrail_triggered=False,
        )
      else:
        turn = {"assistant_message": "Continue."}

      assistant_text = str(turn.get("assistant_message") or "").strip() or "Continue."

      assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      if focus == "financials":
        assistant_text = _append_constraints_snippet(
          assistant_text,
          revenue_constraints_snippet,
          messages,
          force=True,
        )

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[{"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json if focus == "done" else None,
        target_market_json=market_json if focus in {"market", "done"} else None,
        people_json=people_json if focus == "done" else None,
        financials_json=financials_json if focus in {"financials", "done"} else None,
        financials_year1_json=financials_year1_json if focus == "done" else None,
        marketing_model_json=marketing_model_json if focus == "done" else _refresh_marketing_model(),
        active_focus=focus,
        business_facts=business_facts,
        status="completed" if focus == "done" else None,
        completed=bool(focus == "done"),
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": bool(focus == "done"),
          "action": "continue",
          "assistant_message": assistant_text,
          "planning_mode": (
            str((closeout or {}).get("planning_mode") or "").strip()
            if isinstance(closeout, dict)
            else None
          ) or None,
          "planning_mode_reason": (
            str((closeout or {}).get("planning_mode_reason") or "").strip()
            if isinstance(closeout, dict)
            else None
          ) or None,
          "prompt_file": (
            str((closeout or {}).get("prompt_file") or "").strip()
            if isinstance(closeout, dict)
            else None
          ) or None,
        }
      )

    user_msg = {"role": "user", "content": message}
    recent_messages = messages[-12:] if len(messages) > 12 else list(messages)
    last_assistant = _last_assistant_message(messages)
    restatement_confirmed_this_turn = False
    persist_ops_from_restatement = False
    ops_restatement_meta_touched = False
    ops_restatement_pending = bool((ops_json or {}).get("_ops_restatement_pending"))
    ops_restatement_text = str((ops_json or {}).get("_ops_restatement_text") or "").strip()
    if (
      str(focus).strip().lower() == "ops"
      and last_assistant
    ):
      # Only run restatement confirmation inference when the controller explicitly
      # marked the prior assistant turn as the restatement confirmation prompt.
      # This avoids early persistence from classifier misfires on non-restatement turns.
      if ops_restatement_pending:
        try:
          classification = _classify_restatement_response(
            restatement=ops_restatement_text or last_assistant,
            user_reply=message,
          )
        finally:
          # Pending applies to exactly one client reply turn. Clear it regardless of
          # ACCEPT/REJECT/CLARIFY so we don't keep classifying subsequent answers.
          if isinstance(ops_json, dict):
            ops_json.pop("_ops_restatement_pending", None)
          ops_restatement_meta_touched = True
        if classification == "ACCEPT":
          restatement_confirmed_this_turn = True

    if restatement_confirmed_this_turn:
      already_locked = bool(ops_json.get("business_type_candidates_locked"))
      existing_candidates = ops_json.get("business_type_candidates")
      has_candidates = isinstance(existing_candidates, list) and bool(existing_candidates)
      if not already_locked and not has_candidates:
        try:
          bt_candidates = _build_business_type_candidates(
            conn=conn,
            messages=[*messages, user_msg],
            restatement_text=ops_restatement_text or last_assistant,
          )
        except Exception as exc:
          logger.exception("business_type_selection_failed: %s", exc)
          return (jsonify({"error": "business_type_selection_failed"}), 500)
        if not bt_candidates:
          logger.warning("business_type_selection_empty restatement=%r", last_assistant)
          return (jsonify({"error": "business_type_selection_failed"}), 500)
        ops_json["business_type_candidates"] = bt_candidates
        ops_json["business_type_candidates_locked"] = True
        ops_json["business_type"] = bt_candidates[0]
        try:
          try:
            from business_type_naics import get_naics_from_business_type  # type: ignore
          except Exception:
            from client_intake_and_finmo.business_type_naics import (  # type: ignore
              get_naics_from_business_type,
            )
          if ops_json.get("business_type"):
            ops_json["business_naics_6"] = get_naics_from_business_type(
              conn, ops_json.get("business_type")
            )
          else:
            ops_json["business_naics_6"] = None
        except Exception:
          ops_json["business_naics_6"] = None
        lines = []
        for idx, bt in enumerate(bt_candidates[:80], start=1):
          lines.append(f"{idx}. {bt}")
        if lines:
          logger.warning(
            "BUSINESS TYPE CANDIDATES (ranked):\n%s",
            "\n".join(lines),
          )
        logger.warning(
          "business_type_persisted business_type=%r business_naics_6=%r",
          ops_json.get("business_type"),
          ops_json.get("business_naics_6"),
        )
        persist_ops_from_restatement = True
    revenue_driver_patch = None
    pending_competitive_advantage = _extract_competitive_advantage_prompt(last_assistant)
    competitive_intent_override: Optional[Dict[str, Any]] = None
    if (
      pending_competitive_advantage
      and str(focus).strip().lower() == "ops"
      and not restatement_locked_prior
    ):
      pending_competitive_advantage = None

    if (
      pending_competitive_advantage
      and str(focus).strip().lower() == "ops"
      and not str((ops_json or {}).get("competitive_advantage") or "").strip()
    ):
      competitive_intent = route_intent(
        consult_type="ops",
        user_message=message,
        baseline_json=ops_json,
        shared_context=shared_context,
        recent_messages=recent_messages,
        confirm_question_override=COMPETITIVE_ADVANTAGE_QUESTION,
        active_focus="ops",
      )
      comp_action = str(competitive_intent.get("action") or "").strip()
      comp_router_msg = sanitize_fact_template(
        str(competitive_intent.get("assistant_message") or "").strip()
      )
      comp_patch = competitive_intent.get("patch") if isinstance(competitive_intent.get("patch"), dict) else None
      if comp_action == "confirm_clarify":
        assistant_text = comp_router_msg
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          marketing_model_json=_refresh_marketing_model(),
          active_focus=focus,
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": focus,
            "awaiting_confirmation": True,
            "done": False,
            "action": "confirm_clarify",
            "assistant_message": assistant_text,
          }
        )
      if comp_action == "confirm_proceed":
        # Commit the confirmed competitive advantage immediately so subsequent Ops logic
        # in this turn cannot re-trigger the proposal injection.
        confirmed_advantage = sanitize_fact_template(
          str(pending_competitive_advantage or "").strip()
        )
        ops_json["competitive_advantage"] = confirmed_advantage
        try:
          shared_context["operating_model"] = ops_json
        except Exception:
          pass
        comp_action = "edit_patch"
        comp_patch = {
          "ops.competitive_advantage": confirmed_advantage
        }
      if comp_action != "edit_patch":
        raise RuntimeError("Unexpected intent action for competitive advantage.")
      competitive_intent_override = {
        "action": comp_action,
        "router_msg": comp_router_msg,
        "patch": comp_patch,
      }

    if not starting:
      # Revenue adjudication / option-battle flow has been removed from the live
      # Financials consult. Financials now stays on the controller/router path.
      pass

    if (
      guardrail_triggered
      and not revenue_driver_patch
      and not starting
      and _is_guardrail_acknowledgement(message)
    ):
      acknowledge_signature(str(draft_id).strip(), driver_signature)
      guardrail_triggered = False

    revenue_math_line = build_revenue_math_line(
      financials_year1_json,
      unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
    )

    focus, confirm_question = _compute_focus_and_confirm_question(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      ops_confirmed=ops_confirmed,
      market_confirmed=market_confirmed,
      people_confirmed=people_confirmed,
      financials_confirmed=financials_confirmed,
    )

    baseline_json = {
      "business": business_facts,
      "ops": ops_json,
      "market": market_json,
      "people": people_json,
      "financials": financials_json,
      "financials_year1": financials_year1_json,
      "marketing": dict((shared_context or {}).get("marketing") or {}),
      "fulfillment": fulfillment_json,
    }
    current_financials_stage = (
      _next_financials_stage(financials_json)
      if str(focus).strip().lower() == "financials"
      else None
    )
    shared_context_for_router = shared_context
    try:
      router_candidates = ops_json.get("business_type_candidates")
      if isinstance(router_candidates, list) and router_candidates:
        shared_context_for_router = dict(shared_context or {})
        shared_context_for_router["business_type_candidates"] = router_candidates
    except Exception:
      shared_context_for_router = shared_context
    # Route the user's message through the GPT-only intent router first.
    confirm_override = str(confirm_question or _detect_confirm_question(last_assistant) or "").strip()
    # NOTE: Target Market replies are interpreted directly by the Target Market consultant
    # (structured patch). We intentionally do not maintain controller-owned "pending income"
    # confirmation state to avoid brittle loops.
    milestone_intent_override: Optional[Dict[str, Any]] = None
    if (
      str(focus).strip().lower() == "ops"
      and pending_ops_milestone
      and not _has_confirmed_milestone(ops_json)
    ):
      try:
        extracted_milestone = _extract_ops_pending_milestone_via_openai(
          text=message,
          ops_json=ops_json,
          business_facts=business_facts,
        )
        milestone_obj = extracted_milestone.get("milestone")
        clarification_question = sanitize_fact_template(
          str(extracted_milestone.get("clarification_question") or "").strip()
        )
        if bool(extracted_milestone.get("captured")) and isinstance(milestone_obj, dict):
          milestone_intent_override = {
            "action": "edit_patch",
            "router_msg": "Got it.",
            "patch": {"milestones": [milestone_obj]},
          }
        elif clarification_question:
          milestone_intent_override = {
            "action": "confirm_clarify",
            "router_msg": clarification_question,
            "patch": None,
          }
        else:
          milestone_intent = route_intent(
            consult_type="ops",
            user_message=message,
            baseline_json=ops_json,
            shared_context=shared_context_for_router,
            recent_messages=recent_messages,
            active_focus="ops",
          )
          m_action = str(milestone_intent.get("action") or "").strip()
          m_router_msg = sanitize_fact_template(str(milestone_intent.get("assistant_message") or "").strip())
          m_patch = (
            milestone_intent.get("patch") if isinstance(milestone_intent.get("patch"), dict) else None
          )
          # Only override routing when the router actually produced a milestones patch.
          if m_action == "edit_patch" and isinstance(m_patch, dict) and (
            "milestones" in m_patch or "ops.milestones" in m_patch
          ):
            milestone_intent_override = {
              "action": m_action,
              "router_msg": m_router_msg,
              "patch": m_patch,
            }
          elif m_action == "confirm_clarify" and m_router_msg:
            milestone_intent_override = {
              "action": m_action,
              "router_msg": m_router_msg,
              "patch": None,
            }
      except Exception:
        milestone_intent_override = None

    if (
      str(focus).strip().lower() == "people"
      and str(confirm_override or "").strip() != PEOPLE_CONFIRM_QUESTION
      and _detect_people_done_adding_via_openai(
        last_assistant=last_assistant,
        user_message=message,
      )
    ):
      intake_context_people = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "operating_model_json": ops_json,
        "target_market_json": market_json,
        "people_json": people_json,
        "financials_json": financials_json,
        "fulfillment_json": fulfillment_json,
      }
      final_obj = people_capability_finalize(
        intake_context=intake_context_people,
        conversation_messages=[*messages, user_msg],
      )
      people_json, assistant_final = _build_people_review_payload(
        conn=conn,
        final_obj=final_obj,
        ops_json=ops_json,
        market_json=market_json,
        financials_json=financials_json,
        business_facts=business_facts,
      )
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        people_json=people_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus="people",
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("people", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "people",
          "awaiting_confirmation": True,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_final,
        }
      )

    if str(focus).strip().lower() == "financials":
      intake_context_financials = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "operating_model_json": ops_json,
        "target_market_json": market_json,
        "people_json": people_json,
        "financials_json": financials_json,
        "financials_year1_json": financials_year1_json,
        "fulfillment_json": fulfillment_json,
        "revenue_math_line": revenue_math_line,
        "revenue_constraints_snippet": revenue_constraints_snippet,
        "revenue_driver_patch": revenue_driver_patch,
        "revenue_guardrail_triggered": guardrail_triggered,
        "revenue_guardrail_context_signals": guardrail_signals.get("context_signals") or [],
        "revenue_guardrail_product_signals": guardrail_signals.get("product_signals") or [],
      }
      financials_turn, financials_json = _run_financials_turn_and_sync(
        route_intent=route_intent,
        conn=conn,
        intake_context=intake_context_financials,
        conversation_messages=[*messages, user_msg],
        business_facts=business_facts,
        shared_context=shared_context,
        last_assistant=last_assistant,
        user_message=message,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
      )
      shared_context["financials"] = financials_json
      shared_context["financials_year1"] = financials_year1_json
      assistant_text = sanitize_fact_template(
        str((financials_turn or {}).get("assistant_message") or "").strip()
      )
      assistant_text = _append_constraints_snippet(
        assistant_text,
        revenue_constraints_snippet,
        messages,
        force=True,
      )

      if bool((financials_turn or {}).get("transition_to_done")):
        assistant_final = str((financials_turn or {}).get("assistant_message") or "").strip()
        _persist_intake_completion(
          new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=_refresh_marketing_model(),
          confirmations_value={"financials": True},
          flat_fields_value=_finalize_flag_field("financials", True),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "done",
            "awaiting_confirmation": False,
            "done": True,
            "action": "intake_complete",
            "assistant_message": assistant_final,
          }
        )

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        financials_json=financials_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus="financials",
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("financials", False),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "financials",
          "awaiting_confirmation": False,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    if competitive_intent_override:
      action = str(competitive_intent_override.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(competitive_intent_override.get("router_msg") or "").strip())
      patch = (
        competitive_intent_override.get("patch")
        if isinstance(competitive_intent_override.get("patch"), dict)
        else None
      )
    elif milestone_intent_override:
      action = str(milestone_intent_override.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(milestone_intent_override.get("router_msg") or "").strip())
      patch = (
        milestone_intent_override.get("patch")
        if isinstance(milestone_intent_override.get("patch"), dict)
        else None
      )
    elif str(focus).strip().lower() == "ops" and not restatement_locked_prior:
      action = "continue_chat"
      router_msg = ""
      patch = None
    elif str(focus).strip().lower() == "market" and not market_finalize_proposed:
      # Target Market is model-interpreted every turn (structured patch), not router-parsed.
      action = "continue_chat"
      router_msg = ""
      patch = None
    else:
      intent = route_intent(
        consult_type="unified",
        user_message=message,
        baseline_json=baseline_json,
        shared_context=shared_context_for_router,
        recent_messages=recent_messages,
        confirm_question_override=confirm_override,
        active_focus=focus,
      )

      action = str(intent.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(intent.get("assistant_message") or "").strip())
      patch = intent.get("patch") if isinstance(intent.get("patch"), dict) else None

    if (
      str(focus).strip().lower() == "ops"
      and action == "confirm_proceed"
      and not ops_finalize_proposed
      and not pending_ops_milestone
      and not competitive_intent_override
      and not milestone_intent_override
    ):
      inferred_ops_patch = _extract_ops_proposal_patch(
        last_assistant=last_assistant,
        route_intent=route_intent,
        ops_json=ops_json,
        shared_context=shared_context,
        recent_messages=recent_messages,
      )
      if isinstance(inferred_ops_patch, dict) and inferred_ops_patch:
        action = "edit_patch"
        patch = inferred_ops_patch

    if str(focus).strip().lower() == "financials" and action == "confirm_proceed":
      try:
        active_stage = str(current_financials_stage or "").strip()
        stage_spec = _financials_stage_spec(active_stage)
        if active_stage and bool(stage_spec.get("confirmable_baseline")):
          default_patch = _financials_stage_default_patch(
            stage_name=active_stage,
            shared_context=shared_context,
            financials_year1_json=financials_year1_json,
            business_facts=business_facts,
            conn=conn,
          )
          if isinstance(default_patch, dict) and default_patch:
            action = "edit_patch"
            patch = {f"financials.{k}": v for k, v in default_patch.items()}
      except Exception:
        pass

    if (
      str(focus).strip().lower() == "ops"
      and pending_ops_milestone
      and not _has_confirmed_milestone(ops_json)
      and not milestone_intent_override
      and action != "edit_patch"
    ):
      action = "confirm_clarify"
      router_msg = (
        "What is one concrete goal you want to hit in about the next 12 months, and by when?"
      )
      patch = None

    milestone_patch_from_user: Optional[List[Dict[str, Any]]] = None
    if action == "edit_patch" and isinstance(patch, dict):
      patch = _normalize_unscoped_patch(patch, focus=focus)
      if str(focus or "").strip().lower() == "financials":
        normalized_financials_patch = _normalize_financials_router_patch(
          patch=patch,
          active_stage=current_financials_stage,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          last_assistant=last_assistant,
          user_message=user_text,
        )
        if isinstance(normalized_financials_patch, dict) and normalized_financials_patch:
          patch = {f"financials.{k}": v for k, v in normalized_financials_patch.items()}
      candidate = patch.get("milestones")
      if candidate is None:
        candidate = patch.get("ops.milestones")
      if isinstance(candidate, str):
        try:
          candidate = json.loads(candidate)
        except Exception:
          candidate = None
      if isinstance(candidate, list):
        milestone_patch_from_user = [m for m in candidate if isinstance(m, dict)]

    if milestone_patch_from_user:
      existing_milestones = _parse_milestones((ops_json or {}).get("milestones"))
      if existing_milestones:
        milestone_patch_from_user = None

    # Only accept milestone patches when we are explicitly in the milestone-capture step.
    # This keeps Ops sequencing stable (competitive advantage second-to-last, milestone last)
    # and prevents earlier turns from accidentally persisting a milestone out of order.
    if (
      str(focus).strip().lower() == "ops"
      and pending_ops_milestone
      and not _has_confirmed_milestone(ops_json)
    ):
      if milestone_patch_from_user:
        ops_json["milestones"] = milestone_patch_from_user
        _enrich_milestones_timing(ops_json, reference_date=current_date)
        shared_context["operating_model"] = ops_json
        pending_ops_milestone = False

    # Sections can only advance after the explicit final confirmation has been proposed.
    finalize_flags = {
      "ops": ops_finalize_proposed,
      "market": market_finalize_proposed,
      "people": people_finalize_proposed,
    }
    if action == "confirm_proceed" and focus in finalize_flags and not finalize_flags.get(focus):
      action = "continue_chat"

    # If the intake is fully complete, "continue" should guide the user to submission.
    if focus == "done" and action == "continue_chat":
      assistant_text = 'Final review is complete and the facts line up well enough to proceed.\n\nClick "Submit intake" to finish.'
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        marketing_model_json=_refresh_marketing_model(),
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
      patch = _normalize_unscoped_patch(patch, focus=focus)

      # Target Market: after we generate a marketing_plan_summary, we present it for
      # confirmation. If the client counters with edits, keep them in this proposal
      # step and re-show the updated marketing_plan_summary (do not restart the
      # full Target Market consult).
      if (
        str(focus or "").strip().lower() == "market"
        and market_finalize_proposed
        and isinstance(patch, dict)
        and ("market.marketing_plan_summary" in patch)
      ):
        business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
          patch,
          business_facts=business_facts,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          fulfillment_json=fulfillment_json,
        )
        assistant_text = sanitize_fact_template(
          str((market_json or {}).get("marketing_plan_summary") or "").strip()
        )
        assistant_text = _strip_acs_codes(assistant_text)
        assistant_text = f"{assistant_text}\n\n{MARKET_CONFIRM_QUESTION}".strip()
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          target_market_json=market_json,
          marketing_model_json=_refresh_marketing_model(),
          active_focus="market",
          business_facts=business_facts,
          flat_fields=_finalize_flag_field("market", True),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "market",
            "awaiting_confirmation": True,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

      people_patch_applied = bool(
        str(focus or "").strip().lower() == "people"
        or any(str(k).strip().lower().startswith("people.") for k in patch.keys())
      )
      baseline_people_json = json.loads(json.dumps(people_json)) if people_json else {}
      business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
        patch,
        business_facts=business_facts,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        fulfillment_json=fulfillment_json,
      )
      marketing_patch_touched = any(
        str(key or "").strip() in {
          "marketing_total_year1",
          "marketing_percent_of_revenue",
          "financials.marketing_total_year1",
          "financials.marketing_percent_of_revenue",
        }
        for key in patch.keys()
      )
      if marketing_patch_touched:
        financials_json = _sync_marketing_field_family(
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          marketing_model_json=marketing_model_json,
        )
      # Keep capacity compatibility coherent (especially monthly/contract cadence).
      ops_json = _normalize_ops_capacity_compat(ops_json)
      try:
        shared_context = dict(shared_context or {})
        shared_context["operating_model"] = ops_json
        shared_context["target_market"] = market_json
        shared_context["people_capability"] = people_json
        shared_context["financials"] = financials_json

        # Persist ops.business_description_summary rendered (no {{fact:...}} placeholders),
        # even when ops is updated via edit patches after finalization.
        try:
          try:
            from fact_templates import render_fact_template  # type: ignore
          except Exception:
            from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

          if isinstance(ops_json, dict) and str(ops_json.get("business_description_summary") or "").strip():
            business_facts_for_render = {
              "name": str(business_facts.get("name") or "").strip(),
              "address": str(business_facts.get("address") or "").strip(),
              "start_date": str(business_facts.get("start_date") or "").strip(),
            }
            shared_ctx_for_render = {
              "operating_model": ops_json,
              "target_market": market_json,
              "people_capability": people_json,
              "financials": financials_json,
            }
            ops_json["business_description_summary"] = render_fact_template(
              str(ops_json.get("business_description_summary") or ""),
              shared_context=shared_ctx_for_render,
              business_facts=business_facts_for_render,
            ).strip()
            shared_context["operating_model"] = ops_json
        except Exception:
          pass

        base_year1 = assemble_financials_year1(shared_context, None)
        if _year1_drivers_conflict(financials_year1_json, base_year1):
          financials_year1_json = base_year1
        else:
          financials_year1_json = assemble_financials_year1(shared_context, financials_year1_json)
        financials_json, financials_year1_json = _sync_financials_consult_persistence_state(
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          marketing_model_json=marketing_model_json,
        )
        shared_context["financials"] = financials_json
        if isinstance(financials_year1_json, dict) and financials_year1_json:
          shared_context["financials_year1_json"] = financials_year1_json
        revenue_math_line = build_revenue_math_line(
          financials_year1_json,
          unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
        )
        revenue_constraints_snippet = build_revenue_constraints_snippet(
          shared_context,
          financials_year1_json,
          business_start_date=str(business_facts.get("start_date") or "").strip() or None,
        )
        guardrail_signals = build_revenue_guardrail_signals(
          shared_context,
          financials_year1_json,
          business_start_date=str(business_facts.get("start_date") or "").strip() or None,
          fulfillment_context=fulfillment_json,
        )
        driver_signature = build_revenue_driver_signature(financials_year1_json)
        guardrail_acknowledged = (
          get_acknowledged_signature(str(draft_id).strip()) == driver_signature
        )
        guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged
      except Exception:
        pass
      def _coerce_wage(value: Any) -> Optional[float]:
        try:
          return float(value)
        except Exception:
          return None

      def _people_key(item: Dict[str, Any]) -> str:
        name = str(item.get("full_name") or "").strip().lower()
        title = str(item.get("role_title") or "").strip().lower()
        if name or title:
          return f"{name}::{title}".strip(":")
        return ""

      def _role_key(item: Dict[str, Any]) -> str:
        return str(item.get("role_title") or "").strip().lower()

      def _build_wage_map(items: List[Dict[str, Any]], key_fn) -> Dict[str, Optional[float]]:
        mapping: Dict[str, Optional[float]] = {}
        for it in items:
          if not isinstance(it, dict):
            continue
          key = key_fn(it)
          if not key:
            continue
          mapping[key] = _coerce_wage(it.get("annual_wage"))
        return mapping

      def _mark_client_overrides(
        updated_items: List[Dict[str, Any]],
        baseline_map: Dict[str, Optional[float]],
        key_fn,
      ) -> None:
        for it in updated_items:
          if not isinstance(it, dict):
            continue
          key = key_fn(it)
          if not key:
            continue
          new_wage = _coerce_wage(it.get("annual_wage"))
          if new_wage is None:
            continue
          old_wage = baseline_map.get(key)
          if old_wage is None or abs(new_wage - old_wage) > 0.01:
            it["wage_source"] = "client_override"

      try:
        baseline_people_list = (
          baseline_people_json.get("people") if isinstance(baseline_people_json, dict) else []
        )
        baseline_roles_list = (
          baseline_people_json.get("inferred_roles") if isinstance(baseline_people_json, dict) else []
        )
        if isinstance(people_json, dict):
          updated_people_list = people_json.get("people")
          updated_roles_list = people_json.get("inferred_roles")
          if isinstance(updated_people_list, list) and isinstance(baseline_people_list, list):
            _mark_client_overrides(
              updated_people_list, _build_wage_map(baseline_people_list, _people_key), _people_key
            )
          if isinstance(updated_roles_list, list) and isinstance(baseline_roles_list, list):
            _mark_client_overrides(
              updated_roles_list, _build_wage_map(baseline_roles_list, _role_key), _role_key
            )
      except Exception:
        pass

      # People/HR confirm stage: if the client counters/edits the People review, we apply
      # the patch, acknowledge briefly, and advance to Financials WITHOUT re-showing
      # roles/people again (noise). This keeps behavior scoped to People only.
      if (
        str(focus or "").strip().lower() == "people"
        and bool(people_finalize_proposed)
        and isinstance(patch, dict)
        and any(str(k).strip().lower().startswith("people.") for k in patch.keys())
      ):
        # Refresh derived People fields after edits (keeps SQL internally consistent).
        try:
          from people_roles import format_roles_summary  # type: ignore

          if isinstance(people_json, dict):
            roles_now = people_json.get("inferred_roles")
            roles_now = roles_now if isinstance(roles_now, list) else []
            people_json["inferred_roles_summary"] = format_roles_summary(roles_now)
        except Exception:
          pass

        # Render People fact templates (no {{fact:...}} placeholders) for persisted JSON.
        try:
          try:
            from fact_templates import render_fact_template  # type: ignore
          except Exception:
            from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

          if isinstance(people_json, dict):
            business_facts_for_render = {
              "name": str(business_facts.get("name") or "").strip(),
              "address": str(business_facts.get("address") or "").strip(),
              "start_date": str(business_facts.get("start_date") or "").strip(),
            }
            shared_ctx_for_render = {
              "operating_model": ops_json,
              "target_market": market_json,
              "people_capability": people_json,
              "financials": financials_json,
            }
            ppl = people_json.get("people")
            if isinstance(ppl, list):
              for p in ppl:
                if not isinstance(p, dict):
                  continue
                for fk, fv in list(p.items()):
                  if isinstance(fv, str) and "{{fact:" in fv:
                    p[fk] = render_fact_template(
                      fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
                    ).strip()
            roles = people_json.get("inferred_roles")
            if isinstance(roles, list):
              for r in roles:
                if not isinstance(r, dict):
                  continue
                for fk, fv in list(r.items()):
                  if isinstance(fv, str) and "{{fact:" in fv:
                    r[fk] = render_fact_template(
                      fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
                    ).strip()
            shared_context["people_capability"] = people_json
        except Exception:
          pass

        next_focus = "financials"
        start_instruction = _start_instruction_for_focus(next_focus)
        turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
        intake_context_next: Dict[str, Any] = {
          "client_id": client_id,
          "draft_id": str(draft_id).strip(),
          "business_name": business_facts.get("name"),
          "business_start_date": business_facts.get("start_date"),
          "address": business_facts.get("address"),
          "current_date": current_date_iso,
          "business_stage_hint": business_stage_hint,
          "shared_context": shared_context,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "fulfillment_json": fulfillment_json,
        }
        intake_context_next["financials_year1_json"] = financials_year1_json
        intake_context_next["revenue_math_line"] = revenue_math_line
        intake_context_next["revenue_constraints_snippet"] = revenue_constraints_snippet
        intake_context_next["revenue_driver_patch"] = revenue_driver_patch
        intake_context_next["revenue_guardrail_triggered"] = guardrail_triggered
        intake_context_next["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
        intake_context_next["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

        financials_turn, financials_json = _build_financials_live_turn(
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          shared_context=shared_context,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          guardrail_triggered=guardrail_triggered,
        )
        next_assistant = str(financials_turn.get("assistant_message") or "").strip()
        assistant_text = f"Got it - updated.\n\nGreat, let's move on to Financials.\n\n{next_assistant}".strip()
        assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
        assistant_text = _append_constraints_snippet(
          assistant_text,
          revenue_constraints_snippet,
          messages,
          force=True,
        )

        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          confirmations={"people": True},
          marketing_model_json=_refresh_marketing_model(),
          active_focus=next_focus,
          business_facts=business_facts,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          flat_fields=_finalize_flag_field("people", False),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": next_focus,
            "awaiting_confirmation": False,
            "done": False,
            "action": "confirm_proceed",
            "assistant_message": assistant_text,
          }
        )
      business_type_touched = False
      if isinstance(patch, dict):
        business_type_touched = "ops.business_type" in patch
      try:
        try:
          from business_type_naics import get_naics_from_business_type  # type: ignore
        except Exception:
          from client_intake_and_finmo.business_type_naics import (  # type: ignore
            get_naics_from_business_type,
          )
        if business_type_touched:
          bt_candidates = ops_json.get("business_type_candidates")
          if not isinstance(bt_candidates, list):
            bt_candidates = []
          ops_json["business_type"] = _normalize_business_type_from_candidates(
            ops_json.get("business_type"),
            bt_candidates,
          )
        if business_type_touched:
          if ops_json.get("business_type"):
            ops_json["business_naics_6"] = get_naics_from_business_type(
              conn, ops_json.get("business_type")
            )
          else:
            ops_json["business_naics_6"] = None
          logger.warning(
            "business_type_persisted business_type=%r business_naics_6=%r",
            ops_json.get("business_type"),
            ops_json.get("business_naics_6"),
          )
        elif ops_json.get("business_type") and not ops_json.get("business_naics_6"):
          bt_candidates = ops_json.get("business_type_candidates")
          if not isinstance(bt_candidates, list):
            bt_candidates = []
          ops_json["business_type"] = _normalize_business_type_from_candidates(
            ops_json.get("business_type"),
            bt_candidates,
          )
          ops_json["business_naics_6"] = get_naics_from_business_type(
            conn, ops_json.get("business_type")
          )
      except Exception:
        if business_type_touched and "business_naics_6" not in ops_json:
          ops_json["business_naics_6"] = None
      try:
        _enrich_milestones_timing(ops_json, reference_date=current_date)
      except Exception:
        pass
      try:
        from people_roles import (  # type: ignore
          apply_oews_wages,
          apply_oews_wages_to_people,
          format_roles_summary,
        )

        people_list = people_json.get("people") if isinstance(people_json, dict) else None
        people_list = people_list if isinstance(people_list, list) else []
        if people_list:
          enriched_people = apply_oews_wages_to_people(
            conn,
            people=people_list,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          people_json["people"] = enriched_people

        roles = people_json.get("inferred_roles") if isinstance(people_json, dict) else None
        roles = roles if isinstance(roles, list) else []
        if roles:
          enriched_roles = apply_oews_wages(
            conn,
            roles=roles,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          people_json["inferred_roles"] = enriched_roles
          people_json["inferred_roles_summary"] = format_roles_summary(enriched_roles)
      except Exception:
        pass
      active_focus_out = focus
      status_out: str | None = None
      completed_out = False
      confirm_question_live = _detect_confirm_question(last_assistant)

      # People/HR: if we're on the People section-final confirmation step and the client
      # counters with edits, acknowledge the change and advance (do not re-show the full
      # People recap/wage proposal again).
      if (
        str(focus).strip().lower() == "people"
        and active_focus_out == focus
        and confirm_question_live == PEOPLE_CONFIRM_QUESTION
      ):
        next_focus = "financials"
        start_instruction = _start_instruction_for_focus(next_focus)
        turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
        intake_context_next: Dict[str, Any] = {
          "client_id": client_id,
          "draft_id": str(draft_id).strip(),
          "business_name": business_facts.get("name"),
          "business_start_date": business_facts.get("start_date"),
          "address": business_facts.get("address"),
          "current_date": current_date_iso,
          "business_stage_hint": business_stage_hint,
          "shared_context": shared_context,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "fulfillment_json": fulfillment_json,
        }
        intake_context_next["financials_year1_json"] = financials_year1_json
        intake_context_next["revenue_math_line"] = revenue_math_line
        intake_context_next["revenue_constraints_snippet"] = revenue_constraints_snippet
        intake_context_next["revenue_driver_patch"] = revenue_driver_patch
        intake_context_next["revenue_guardrail_triggered"] = guardrail_triggered
        intake_context_next["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
        intake_context_next["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

        financials_turn, financials_json = _build_financials_live_turn(
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          shared_context=shared_context,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          guardrail_triggered=guardrail_triggered,
        )
        next_assistant = str(financials_turn.get("assistant_message") or "").strip()
        next_assistant = sanitize_fact_template(str(next_assistant or "").strip())
        next_assistant = _append_constraints_snippet(
          next_assistant,
          revenue_constraints_snippet,
          messages,
          force=True,
        )
        assistant_text = f"Got it, updated.\n\nGreat, let's move on to Financials.\n\n{next_assistant}".strip()

        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          people_json=people_json,
          financials_json=financials_json,
          marketing_model_json=_refresh_marketing_model(),
          active_focus=next_focus,
          confirmations={"people": True},
          business_facts=business_facts,
          flat_fields=_finalize_flag_field("people", True),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": next_focus,
            "awaiting_confirmation": False,
            "done": False,
            "action": "confirm_proceed",
            "assistant_message": assistant_text,
          }
        )

      # If the draft was already marked complete, edits must reopen the affected
      # section so the persisted SQL state stays authoritative again.
      if str(draft_status).strip().lower() == "completed" or focus == "done":
        status_out = "in_progress"
        patch_focus = next(
          (
            str(key).split(".", 1)[0].strip().lower()
            for key in (patch or {}).keys()
            if str(key).count(".") == 1
            and str(key).split(".", 1)[0].strip().lower() in {"ops", "market", "people", "financials"}
          ),
          "",
        )
        active_focus_out = patch_focus or ("financials" if focus == "done" else focus)

      # For edit patches, the intent router is used only to interpret intent and
      # produce the deterministic patch. The domain consultant generates the next
      # conversational turn. Showing both messages causes duplicated acknowledgements
      # and repeated questions.
      #
      # Exception: if the edit re-opens a completed intake into final review, keep the
      # router acknowledgement so the user clearly sees the update before the audit.
      assistant_text = router_msg if (confirm_question_live or active_focus_out != focus) else ""
      # If we're awaiting a section-final confirmation, re-ask the confirm question
      if confirm_question_live:
        assistant_text = f"{assistant_text}\n\n{confirm_question_live}".strip()
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
          "current_date": current_date_iso,
          "business_stage_hint": business_stage_hint,
          "shared_context": shared_context_live,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "fulfillment_json": fulfillment_json,
        }
        intake_context_followup["financials_year1_json"] = financials_year1_json
        intake_context_followup["revenue_math_line"] = revenue_math_line
        intake_context_followup["revenue_constraints_snippet"] = revenue_constraints_snippet
        intake_context_followup["revenue_driver_patch"] = revenue_driver_patch
        intake_context_followup["revenue_guardrail_triggered"] = guardrail_triggered
        intake_context_followup["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
        intake_context_followup["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

        followup_focus = active_focus_out if active_focus_out != "done" else focus
        if followup_focus == "market":
          consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
          if consumer_type not in ("consumer", "b2b", "mixed"):
            consumer_type = "consumer"
          intake_context_followup["consumer_type"] = consumer_type

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
          followup_turn, financials_json = _build_financials_live_turn(
            conn=conn,
            intake_context=intake_context_followup,
            conversation_messages=[*messages, user_msg],
            shared_context=shared_context,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            guardrail_triggered=guardrail_triggered,
          )
          if bool((followup_turn or {}).get("transition_to_done")):
            assistant_final = str((followup_turn or {}).get("assistant_message") or "").strip()
            _persist_intake_completion(
              new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
              ops_value=ops_json,
              market_value=market_json,
              people_value=people_json,
              financials_value=financials_json,
              financials_year1_value=financials_year1_json,
              marketing_value=_refresh_marketing_model(),
              confirmations_value={"financials": True},
              flat_fields_value=_finalize_flag_field("financials", True),
            )
            return jsonify(
              {
                "status": "ok",
                "draft_id": str(draft_id).strip(),
                "client_id": client_id,
                "active_focus": "done",
                "awaiting_confirmation": False,
                "done": True,
                "action": "intake_complete",
                "assistant_message": assistant_final,
              }
            )
        else:
          followup_turn = {"assistant_message": ""}

        if followup_focus == "ops":
          ops_json = _apply_model_ops_patch(
            ops_json, followup_turn.get("patch") if isinstance(followup_turn, dict) else None
          )
          try:
            shared_context["operating_model"] = ops_json
          except Exception:
            pass

        followup_text = sanitize_fact_template(str(followup_turn.get("assistant_message") or "").strip())
        if focus == "market":
          followup_text = _strip_acs_codes(followup_text)
        if followup_focus == "financials":
          followup_text = _append_constraints_snippet(
            followup_text,
            revenue_constraints_snippet,
            messages,
            force=True,
          )
        if followup_focus == "ops" and not followup_text:
          followup_text = _fallback_ops_followup_question(ops_json)
        if followup_focus == "ops":
          followup_finalize_ready = bool(followup_turn.get("finalize_ready", False))
          followup_attempts_finalize = (
            followup_finalize_ready
            or (OPS_CONFIRM_QUESTION.lower() in str(followup_text or "").lower())
          )
          if followup_attempts_finalize:
            if not str((ops_json or {}).get("competitive_advantage") or "").strip():
              confirmed_restatement = _extract_confirmed_restatement(messages)
              proposed_advantage = _propose_ops_competitive_advantage(
                ops_json=ops_json,
                business_facts=business_facts,
                shared_context=shared_context,
                confirmed_restatement=confirmed_restatement,
              )
              proposed_advantage = sanitize_fact_template(str(proposed_advantage or "").strip())
              assistant_text = (
                f"{COMPETITIVE_ADVANTAGE_PREFIX} {proposed_advantage}\n\n"
                f"{COMPETITIVE_ADVANTAGE_QUESTION}"
              ).strip()
              append_messages(
                conn,
                draft_id=str(draft_id).strip(),
                new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
                operating_model_json=ops_json,
                marketing_model_json=_refresh_marketing_model(),
                active_focus="ops",
                business_facts=business_facts,
                pending_ops_milestone_json=pending_ops_milestone,
                flat_fields=_finalize_flag_field("ops", False),
              )
              return jsonify(
                {
                  "status": "ok",
                  "draft_id": str(draft_id).strip(),
                  "client_id": client_id,
                  "active_focus": "ops",
                  "awaiting_confirmation": True,
                  "done": False,
                  "action": "continue",
                  "assistant_message": assistant_text,
                }
              )

            if (
              str((ops_json or {}).get("competitive_advantage") or "").strip()
              and not _has_confirmed_milestone(ops_json)
              and not pending_ops_milestone
            ):
              assistant_text = OPS_MILESTONE_QUESTION
              pending_ops_milestone = True
              append_messages(
                conn,
                draft_id=str(draft_id).strip(),
                new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
                operating_model_json=ops_json,
                marketing_model_json=_refresh_marketing_model(),
                active_focus="ops",
                business_facts=business_facts,
                pending_ops_milestone_json=True,
                flat_fields=_finalize_flag_field("ops", False),
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

            business_type_candidates = ops_json.get("business_type_candidates")
            if not isinstance(business_type_candidates, list):
              business_type_candidates = []
            intake_context_followup["business_type_candidates"] = business_type_candidates
            final_messages = [*messages, user_msg, {"role": "assistant", "content": followup_text}]
            final_obj = consultant_finalize(
              intake_context=intake_context_followup, conversation_messages=final_messages
            )
            for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
              if isinstance(v, str):
                final_obj[k] = sanitize_fact_template(v)
            existing_advantage = str((ops_json or {}).get("competitive_advantage") or "").strip()
            if (
              existing_advantage
              and isinstance(final_obj, dict)
              and not str(final_obj.get("competitive_advantage") or "").strip()
            ):
              final_obj["competitive_advantage"] = existing_advantage
            try:
              try:
                from business_type_naics import get_naics_from_business_type  # type: ignore
              except Exception:
                from client_intake_and_finmo.business_type_naics import (  # type: ignore
                  get_naics_from_business_type,
                )
              if final_obj.get("business_type"):
                final_obj["business_naics_6"] = get_naics_from_business_type(
                  conn, final_obj.get("business_type")
                )
            except Exception:
              if "business_naics_6" not in final_obj:
                final_obj["business_naics_6"] = None
            try:
              _enrich_milestones_timing(final_obj, reference_date=current_date)
            except Exception:
              pass

            ops_json = final_obj
            try:
              shared_context = dict(shared_context or {})
              shared_context["operating_model"] = ops_json
              shared_context["target_market"] = market_json
              shared_context["people_capability"] = people_json
              shared_context["financials"] = financials_json
            except Exception:
              pass

            next_focus = "market"
            start_instruction = _start_instruction_for_focus(next_focus)
            turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
            intake_context_next: Dict[str, Any] = {
              "client_id": client_id,
              "draft_id": str(draft_id).strip(),
              "business_name": business_facts.get("name"),
              "business_start_date": business_facts.get("start_date"),
              "address": business_facts.get("address"),
              "current_date": current_date_iso,
              "business_stage_hint": business_stage_hint,
              "shared_context": shared_context,
              "operating_model_json": ops_json,
              "target_market_json": market_json,
              "people_json": people_json,
              "financials_json": financials_json,
              "fulfillment_json": fulfillment_json,
            }
            consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
            if consumer_type not in ("consumer", "b2b", "mixed"):
              consumer_type = "consumer"
            intake_context_next["consumer_type"] = consumer_type
            market_turn = target_market_chat_turn(
              intake_context=intake_context_next, conversation_messages=turn_messages
            )
            next_assistant = str((market_turn or {}).get("assistant_message") or "").strip()
            assistant_text = f"Great, let's move on to Target Market.\n\n{next_assistant}".strip()
            assistant_text = _strip_acs_codes(sanitize_fact_template(str(assistant_text or "").strip()))

            append_messages(
              conn,
              draft_id=str(draft_id).strip(),
              new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
              operating_model_json=ops_json,
              target_market_json=market_json,
              marketing_model_json=_refresh_marketing_model(),
              active_focus=next_focus,
              confirmations={"ops": True},
              business_facts=business_facts,
              flat_fields=_finalize_flag_field("ops", True),
            )
            return jsonify(
              {
                "status": "ok",
                "draft_id": str(draft_id).strip(),
                "client_id": client_id,
                "active_focus": next_focus,
                "awaiting_confirmation": False,
                "done": False,
                "action": "confirm_proceed",
                "assistant_message": assistant_text,
              }
            )
        if followup_text:
          if assistant_text:
            assistant_text = f"{assistant_text}\n\n{followup_text}".strip()
          else:
            assistant_text = followup_text
      assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json,
        target_market_json=market_json,
        people_json=people_json if people_patch_applied else None,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        fulfillment_json=fulfillment_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=active_focus_out,
        business_facts=business_facts,
        status=status_out,
        completed=completed_out,
        pending_ops_milestone_json=pending_ops_milestone
        if str(active_focus_out).strip().lower() == "ops"
        else None,
        flat_fields=_finalize_flag_field(focus, False),
      )

      action_out = "edit_patch"
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": active_focus_out,
          "awaiting_confirmation": bool(confirm_question_live),
          "done": bool(active_focus_out == "done"),
          "action": action_out,
          "assistant_message": assistant_text,
        }
      )

    if action == "confirm_proceed":
      confirmations: Dict[str, bool] = {focus: True}
      next_focus = _next_focus(focus)

      # Generate the first question for the next focus immediately.
      start_instruction = _start_instruction_for_focus(next_focus)
      turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
      intake_context_next: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "consumer_type": (ops_json or {}).get("consumer_type"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
      }
      intake_context_next["financials_year1_json"] = financials_year1_json
      intake_context_next["revenue_math_line"] = revenue_math_line
      intake_context_next["revenue_constraints_snippet"] = revenue_constraints_snippet
      intake_context_next["revenue_driver_patch"] = revenue_driver_patch
      intake_context_next["revenue_guardrail_triggered"] = guardrail_triggered
      intake_context_next["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
      intake_context_next["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

      if next_focus == "ops":
        next_assistant = consultant_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "market":
        market_turn = target_market_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )
        next_assistant = str((market_turn or {}).get("assistant_message") or "").strip()
      elif next_focus == "people":
        next_assistant = people_capability_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "financials":
        financials_turn, financials_json = _build_financials_live_turn(
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          shared_context=shared_context,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          guardrail_triggered=guardrail_triggered,
        )
        next_assistant = str(financials_turn.get("assistant_message") or "").strip()
      else:
        next_assistant = "Continue."

      transition = ""
      if next_focus == "market":
        transition = "Great, let's move on to Target Market."
      elif next_focus == "people":
        transition = "Great, let's move on to Human Resources."
      elif next_focus == "financials":
        transition = "Great, let's move on to Financials."
      elif next_focus == "done":
        transition = ""
      if transition:
        next_assistant = f"{transition}\n\n{next_assistant}".strip() if next_assistant else transition

      next_assistant = sanitize_fact_template(str(next_assistant or "").strip())
      if next_focus == "market":
        next_assistant = _strip_acs_codes(next_assistant)
      if next_focus == "financials":
        next_assistant = _append_constraints_snippet(
          next_assistant,
          revenue_constraints_snippet,
          messages,
          force=True,
        )

      if next_focus == "done":
        next_assistant = str(next_assistant or "").strip() or "Intake complete."
        _persist_intake_completion(
          new_messages=[user_msg, {"role": "assistant", "content": next_assistant}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=_refresh_marketing_model(),
          confirmations_value=confirmations,
          flat_fields_value=_finalize_flag_field(focus, False),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "done",
            "awaiting_confirmation": False,
            "done": True,
            "action": "intake_complete",
            "assistant_message": next_assistant,
          }
        )

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": next_assistant}],
        confirmations=confirmations,
        operating_model_json=ops_json if next_focus == "done" else None,
        marketing_model_json=marketing_model_json if next_focus == "done" else _refresh_marketing_model(),
        active_focus=next_focus,
        business_facts=business_facts,
        target_market_json=market_json if next_focus in {"market", "done"} else None,
        people_json=people_json if next_focus == "done" else None,
        financials_json=financials_json if next_focus in {"financials", "done"} else None,
        financials_year1_json=financials_year1_json if next_focus == "done" else None,
        flat_fields=_finalize_flag_field(focus, False),
        status="completed" if next_focus == "done" else None,
        completed=bool(next_focus == "done"),
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": next_focus,
          "awaiting_confirmation": False,
          "done": bool(next_focus == "done"),
          "action": "confirm_proceed",
          "assistant_message": next_assistant,
        }
      )

    if action == "confirm_clarify":
      assistant_text = sanitize_fact_template(router_msg)
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        target_market_json=market_json if focus == "market" else None,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=focus,
        business_facts=business_facts,
        pending_ops_milestone_json=pending_ops_milestone if focus == "ops" else None,
        flat_fields=_finalize_flag_field(focus, False),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": False,
          "action": "confirm_clarify",
          "assistant_message": assistant_text,
        }
      )

    if action == "answer_readonly":
      assistant_text = sanitize_fact_template(router_msg)
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        target_market_json=market_json if focus == "market" else None,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=focus,
        business_facts=business_facts,
        pending_ops_milestone_json=pending_ops_milestone if focus == "ops" else None,
        flat_fields=_finalize_flag_field(focus, False),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": False,
          "action": "answer_readonly",
          "assistant_message": assistant_text,
        }
      )

    # continue_chat: run the current focus consult normally.
    intake_context = {
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
      "current_date": current_date_iso,
      "business_stage_hint": business_stage_hint,
      "shared_context": shared_context,
      "operating_model_json": ops_json,
      "target_market_json": market_json,
      "people_json": people_json,
      "financials_json": financials_json,
      "fulfillment_json": fulfillment_json,
    }
    intake_context["financials_year1_json"] = financials_year1_json
    intake_context["revenue_math_line"] = revenue_math_line
    intake_context["revenue_constraints_snippet"] = revenue_constraints_snippet
    intake_context["revenue_driver_patch"] = revenue_driver_patch
    intake_context["revenue_guardrail_triggered"] = guardrail_triggered
    intake_context["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
    intake_context["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []
    if focus == "market":
      consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
      if consumer_type not in ("consumer", "b2b", "mixed"):
        consumer_type = "consumer"
      intake_context["consumer_type"] = consumer_type
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
      turn, financials_json = _build_financials_live_turn(
        conn=conn,
        intake_context=intake_context,
        conversation_messages=[*messages, user_msg],
        shared_context=shared_context,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        guardrail_triggered=guardrail_triggered,
      )
    else:
      turn = {"assistant_message": "Continue.", "finalize_ready": False}

    assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
    if focus == "market":
      assistant_text = _strip_acs_codes(assistant_text)
    if focus == "financials":
      assistant_text = _append_constraints_snippet(
        assistant_text,
        revenue_constraints_snippet,
        messages,
        force=True,
      )

    # Ops: apply model-produced structured patch immediately (no controller parsing).
    if str(focus).strip().lower() == "ops" and isinstance(turn, dict):
      ops_json = _apply_model_ops_patch(ops_json, turn.get("patch"))
      try:
        shared_context["operating_model"] = ops_json
      except Exception:
        pass

    # Target Market: apply model-produced structured patch immediately (no controller parsing).
    if str(focus).strip().lower() == "market" and isinstance(turn, dict):
      patch_obj = turn.get("patch")
      if isinstance(patch_obj, dict) and isinstance(market_json, dict):
        allowed_keys = {
          "consumer_type",
          "gender_age_intent",
          "income_intent",
          "b2b_industry_terms",
          "b2b_size_bands",
          "b2b_age_bands",
        }
        for k, v in patch_obj.items():
          key = str(k or "").strip()
          if not key:
            continue
          if key.startswith("market."):
            key = key.split(".", 1)[1].strip()
          if key in allowed_keys:
            # In strict json_schema, the model must always output every patch key.
            # We treat null values as "no change" to avoid wiping prior answers.
            if v is None:
              continue
            market_json[key] = v
        try:
          shared_context["target_market"] = market_json
        except Exception:
          pass

    # People: persist raw structured person facts incrementally during collection.
    if str(focus).strip().lower() == "people":
      try:
        people_progress_context = dict(intake_context)
        people_progress_context["existing_people_capability_json"] = people_json
        extracted_people = extract_people_collection_progress(
          intake_context=people_progress_context,
          conversation_messages=[
            *messages,
            user_msg,
            {"role": "assistant", "content": assistant_text},
          ],
        )
        extracted_people_list = (
          extracted_people.get("people") if isinstance(extracted_people, dict) else None
        )
        if isinstance(extracted_people_list, list) and extracted_people_list:
          next_people_json = dict(people_json or {})
          next_people_json["people"] = extracted_people_list
          next_people_json["business_naics_6"] = ops_json.get("business_naics_6")
          people_json = next_people_json
          try:
            shared_context["people_capability"] = people_json
          except Exception:
            pass
      except Exception:
        pass

    finalize_ready = bool(turn.get("finalize_ready", False))
    review_ready = bool(turn.get("review_ready", False))
    # Controller-owned restatement-confirmation state: only classify acceptance on the
    # client reply to the explicit restatement confirmation prompt.
    if (
      str(focus).strip().lower() == "ops"
      and bool(turn.get("is_restatement_confirmation_prompt", False))
      and not bool((ops_json or {}).get("business_type_candidates_locked"))
    ):
      if isinstance(ops_json, dict):
        ops_json["_ops_restatement_pending"] = True
        ops_json["_ops_restatement_text"] = assistant_text
      ops_restatement_meta_touched = True
    if str(focus).strip().lower() == "people" and review_ready and not finalize_ready:
      finalize_ready = True
    if str(focus).strip().lower() == "financials":
      finalize_ready = False

    if str(focus).strip().lower() == "ops" and assistant_text:
      question_count = assistant_text.count("?")
      if question_count > 1:
        first_part = assistant_text.split("?", 1)[0].strip()
        if first_part:
          assistant_text = f"{first_part}?"
        finalize_ready = False
      # If the Ops consultant produced the section-final confirm question in normal chat,
      # treat it as a finalize attempt so we can enforce milestone-first and then auto-advance.
      if OPS_CONFIRM_QUESTION.lower() in assistant_text.lower():
        finalize_ready = True

    ops_ready_for_wrap = False
    # Ops hard gate: do not allow the ops "finalize-ready" path (which triggers competitive
    # advantage/milestone injection and summary auto-skip) unless capacity has been captured.
    #
    # We avoid brittle heuristic phrase-matching by taking a structured snapshot via
    # consultant_finalize() and checking the numeric capacity fields directly.
    if str(focus).strip().lower() == "ops" and (finalize_ready or not assistant_text):
      try:
        gate_messages = [*messages, user_msg, {"role": "assistant", "content": assistant_text}]
        business_type_candidates = (ops_json or {}).get("business_type_candidates")
        if not isinstance(business_type_candidates, list):
          business_type_candidates = []
        gate_context = dict(intake_context)
        gate_context["business_type_candidates"] = business_type_candidates
        gate_obj = consultant_finalize(intake_context=gate_context, conversation_messages=gate_messages)

        def _missing_number(value: Any) -> bool:
          if value is None:
            return True
          if isinstance(value, bool):
            return True
          try:
            return float(value) <= 0
          except Exception:
            return True

        def _final_obj_missing_capacity(obj: Any) -> bool:
          if not isinstance(obj, dict):
            return True
          lob_models = obj.get("lob_models")
          products: List[Dict[str, Any]] = []
          if isinstance(lob_models, list):
            for lob in lob_models:
              if not isinstance(lob, dict):
                continue
              prods = lob.get("products")
              if not isinstance(prods, list):
                continue
              for p in prods:
                if isinstance(p, dict):
                  products.append(p)
          if products:
            for p in products:
              if _missing_number(p.get("units_per_period_capacity")) and _missing_number(
                p.get("units_per_week_capacity")
              ):
                return True
            return False
          return _missing_number(obj.get("units_per_period_capacity")) and _missing_number(
            obj.get("units_per_week_capacity")
          )

        def _final_obj_missing_utilization(obj: Any) -> bool:
          if not isinstance(obj, dict):
            return True
          lob_models = obj.get("lob_models")
          products: List[Dict[str, Any]] = []
          if isinstance(lob_models, list):
            for lob in lob_models:
              if not isinstance(lob, dict):
                continue
              prods = lob.get("products")
              if not isinstance(prods, list):
                continue
              for p in prods:
                if isinstance(p, dict):
                  products.append(p)
          if products:
            for p in products:
              if _missing_number(p.get("utilization_rate")):
                return True
            return False
          return _missing_number(obj.get("utilization_rate"))

        if _final_obj_missing_capacity(gate_obj):
          capacity_target = _find_missing_capacity_target(gate_obj, fallback_ops=ops_json)
          captured_capacity = False
          numeric_capacity_value = _extract_single_compact_number(message)
          if (
            capacity_target
            and numeric_capacity_value is not None
            and _looks_like_capacity_prompt(last_assistant)
          ):
            updated_gate_obj = _apply_capacity_target_value(
              gate_obj,
              capacity_target,
              float(numeric_capacity_value),
            )
            ops_json = _apply_capacity_snapshot_to_ops_json(
              ops_json,
              updated_gate_obj,
              capacity_target,
            )
            shared_context = dict(shared_context or {})
            shared_context["operating_model"] = ops_json
            intake_context = dict(intake_context or {})
            intake_context["shared_context"] = shared_context
            intake_context["operating_model_json"] = ops_json
            gate_context = dict(gate_context or {})
            gate_context["shared_context"] = shared_context
            gate_context["operating_model_json"] = ops_json
            try:
              business_type_candidates = (ops_json or {}).get("business_type_candidates")
              if isinstance(business_type_candidates, list):
                intake_context["business_type_candidates"] = business_type_candidates
            except Exception:
              pass
            follow_up_turn = consultant_chat_turn(
              intake_context=intake_context,
              conversation_messages=[*messages, user_msg],
            ) or {}
            assistant_text = sanitize_fact_template(
              str((follow_up_turn or {}).get("assistant_message") or "").strip()
            )
            finalize_ready = bool(follow_up_turn.get("finalize_ready"))
            captured_capacity = True
          if not captured_capacity:
            if capacity_target:
              assistant_text = _build_capacity_target_question(capacity_target)
            else:
              assistant_text = (
                "To make planning realistic, in a fully busy period, about how many units do you expect you can handle?"
              ).strip()
            finalize_ready = False
        elif _final_obj_missing_utilization(gate_obj):
          def _first_product_missing_utilization(obj: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(obj, dict):
              return None
            lob_models = obj.get("lob_models")
            if isinstance(lob_models, list):
              for lob in lob_models:
                if not isinstance(lob, dict):
                  continue
                products = lob.get("products")
                if not isinstance(products, list):
                  continue
                for product in products:
                  if isinstance(product, dict) and _missing_number(product.get("utilization_rate")):
                    return product
            return obj if _missing_number(obj.get("utilization_rate")) else None

          missing_product = _first_product_missing_utilization(gate_obj) or {}
          util_label = str(
            missing_product.get("product_name")
            or missing_product.get("unit_name")
            or (ops_json or {}).get("unit_name")
            or "this offering"
          ).strip()
          assistant_text = (
            f"For Year 1 planning, what average utilization do you want to assume for {util_label} "
            "(for example, 70% of practical capacity)?"
          ).strip()
          finalize_ready = False
        else:
          missing_period_product = _first_contract_product_missing_periods(gate_obj)
          if missing_period_product:
            period_label = str(
              missing_period_product.get("product_name")
              or missing_period_product.get("unit_name")
              or (ops_json or {}).get("unit_name")
              or "this contract offering"
            ).strip()
            assistant_text = (
              f"For {period_label}, about how many times does one active slot typically turn over in a year? "
              "(For example, if one matter usually lasts about 3 months, that would be about 4 turns per year.)"
            ).strip()
            finalize_ready = False
          else:
            # Competitive advantage should be second-to-last and milestones last.
            # For multi-product ops, readiness must come from the product rows plus
            # the business-wide top-level fields, not placeholder top-level unit fields.
            if _ops_ready_for_wrap_from_gate_obj(gate_obj):
              ops_ready_for_wrap = True
              finalize_ready = True
            else:
              finalize_ready = False
      except Exception:
        # Best-effort: if gating fails, preserve existing behavior.
        pass

    if str(focus).strip().lower() == "ops" and not assistant_text and not finalize_ready:
      assistant_text = _fallback_ops_followup_question(ops_json)

    if (
      str(focus).strip().lower() == "ops"
      and finalize_ready
      and ops_ready_for_wrap
      and not str((ops_json or {}).get("competitive_advantage") or "").strip()
    ):
      confirmed_restatement = _extract_confirmed_restatement(messages)
      proposed_advantage = _propose_ops_competitive_advantage(
        ops_json=ops_json,
        business_facts=business_facts,
        shared_context=shared_context,
        confirmed_restatement=confirmed_restatement,
      )
      proposed_advantage = sanitize_fact_template(str(proposed_advantage or "").strip())
      if proposed_advantage:
        assistant_text = (
          f"{COMPETITIVE_ADVANTAGE_PREFIX} {proposed_advantage}\n\n"
          f"{COMPETITIVE_ADVANTAGE_QUESTION}"
        )
        finalize_ready = False

    if (
      str(focus).strip().lower() == "ops"
      and finalize_ready
      and ops_ready_for_wrap
      and str((ops_json or {}).get("competitive_advantage") or "").strip()
      and not _has_confirmed_milestone(ops_json)
      and not pending_ops_milestone
    ):
      # Ask for milestone once, after competitive advantage is set; use a pending flag so
      # the next user reply is interpreted as an ops.milestones patch.
      assistant_text = OPS_MILESTONE_QUESTION
      finalize_ready = False
      pending_ops_milestone = True

    # Safety: avoid dead-end assistant replies with no next question.
    # If GPT responded with an acknowledgement only (no question) and we're not finalizing,
    # immediately ask for the next single question so the user isn't forced to type "ok".
    if (not finalize_ready) and assistant_text and ("?" not in assistant_text):
      continue_instruction = (
        "Continue. Ask exactly ONE next question for the client to answer (do not bundle)."
      )
      followup_messages = [
        *messages,
        user_msg,
        {"role": "assistant", "content": assistant_text},
        {"role": "user", "content": continue_instruction},
      ]
      try:
        if focus == "ops":
          followup_turn = consultant_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "market":
          followup_turn = target_market_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "people":
          followup_turn = people_capability_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "financials":
          followup_turn, financials_json = _build_financials_live_turn(
            conn=conn,
            intake_context=intake_context,
            conversation_messages=followup_messages,
            shared_context=shared_context,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            guardrail_triggered=guardrail_triggered,
          )
        else:
          followup_turn = {"assistant_message": ""}
        followup_text = sanitize_fact_template(str(followup_turn.get("assistant_message") or "").strip())
        if focus == "market":
          followup_text = _strip_acs_codes(followup_text)
        if focus == "financials":
          followup_text = _append_constraints_snippet(
            followup_text,
            revenue_constraints_snippet,
            messages,
            force=True,
          )
        if followup_text:
          # If the follow-up turn indicates the consult is complete, carry that
          # completion signal forward so we finalize immediately instead of
          # returning a dead-end statement that forces the user to type "ok".
          if bool(followup_turn.get("finalize_ready", False)):
            finalize_ready = True
            assistant_text = followup_text.strip()
          else:
            assistant_text = f"{assistant_text}\n\n{followup_text}".strip()
      except Exception:
        # Best-effort; if follow-up fails, keep the original reply.
        pass

    if str(focus).strip().lower() == "financials" and bool(turn.get("transition_to_done")):
      assistant_final = str(turn.get("assistant_message") or "").strip()
      _persist_intake_completion(
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        ops_value=ops_json,
        market_value=market_json,
        people_value=people_json,
        financials_value=financials_json,
        financials_year1_value=financials_year1_json,
        marketing_value=_refresh_marketing_model(),
        confirmations_value={"financials": True},
        flat_fields_value=_finalize_flag_field("financials", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "done",
          "awaiting_confirmation": False,
          "done": True,
          "action": "intake_complete",
          "assistant_message": assistant_final,
        }
      )
    if not finalize_ready:
      review_people = None
      if str(focus).strip().lower() == "people" and review_ready:
        review_people = people_capability_finalize(
          intake_context=intake_context,
          conversation_messages=[*messages, user_msg, {"role": "assistant", "content": assistant_text}],
        )
        for k, v in list(review_people.items() if isinstance(review_people, dict) else []):
          if isinstance(v, str):
            review_people[k] = sanitize_fact_template(v)
        try:
          from people_roles import (  # type: ignore
            apply_oews_wages,
            apply_oews_wages_to_people,
            format_roles_summary,
          )

          roles = review_people.get("inferred_roles") if isinstance(review_people, dict) else None
          roles = roles if isinstance(roles, list) else []
          people = review_people.get("people") if isinstance(review_people, dict) else None
          people = people if isinstance(people, list) else []
          enriched_people = apply_oews_wages_to_people(
            conn,
            people=people,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          enriched_roles = apply_oews_wages(
            conn,
            roles=roles,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          review_people["business_naics_6"] = ops_json.get("business_naics_6")
          review_people["people"] = enriched_people
          review_people["inferred_roles"] = enriched_roles
          review_people["inferred_roles_summary"] = format_roles_summary(enriched_roles)
        except Exception:
          if isinstance(review_people, dict):
            if "inferred_roles" not in review_people:
              review_people["inferred_roles"] = []
            if "inferred_roles_summary" not in review_people:
              review_people["inferred_roles_summary"] = ""
            if "business_naics_6" not in review_people:
              review_people["business_naics_6"] = None
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json if str(focus).strip().lower() == "ops" else None,
        target_market_json=market_json if str(focus).strip().lower() == "market" else None,
        financials_json=financials_json if focus == "financials" else None,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=focus,
        business_facts=business_facts,
        financials_year1_json=financials_year1_json if focus == "financials" else None,
        pending_ops_milestone_json=pending_ops_milestone if focus == "ops" else None,
        flat_fields=_finalize_flag_field(focus, False),
        people_json=review_people if review_ready else (people_json if str(focus).strip().lower() == "people" else None),
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

    # Finalize the current focus into structured JSON, then ask for confirmation.
    final_messages = [*messages, user_msg, {"role": "assistant", "content": assistant_text}]

    if focus == "ops":
      business_type_candidates = ops_json.get("business_type_candidates")
      if not isinstance(business_type_candidates, list):
        business_type_candidates = []
      intake_context["business_type_candidates"] = business_type_candidates
      final_obj = consultant_finalize(intake_context=intake_context, conversation_messages=final_messages)
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      existing_advantage = str((ops_json or {}).get("competitive_advantage") or "").strip()
      if (
        existing_advantage
        and isinstance(final_obj, dict)
        and not str(final_obj.get("competitive_advantage") or "").strip()
      ):
        final_obj["competitive_advantage"] = existing_advantage
      if isinstance(final_obj, dict):
        lob_models = final_obj.get("lob_models")
        if isinstance(lob_models, list) and len(lob_models) == 1:
          products = lob_models[0].get("products") if isinstance(lob_models[0], dict) else None
          if isinstance(products, list) and len(products) == 1 and isinstance(products[0], dict):
            product = products[0]

            def _is_missing_number(value: Any) -> bool:
              if value is None:
                return True
              if isinstance(value, bool):
                return True
              try:
                return float(value) <= 0
              except Exception:
                return True

            def _maybe_set_text(field: str) -> None:
              if not final_obj.get(field) and product.get(field) is not None:
                final_obj[field] = product.get(field)

            def _maybe_set_number(field: str) -> None:
              if _is_missing_number(final_obj.get(field)) and product.get(field) is not None:
                final_obj[field] = product.get(field)

            _maybe_set_text("unit_name")
            _maybe_set_text("unit_description")
            _maybe_set_text("unit_cadence")
            _maybe_set_number("unit_price")
            _maybe_set_number("units_per_week_capacity")
            _maybe_set_number("units_per_period_capacity")
            _maybe_set_number("operating_periods_per_year")
            _maybe_set_number("utilization_rate")
      # Capacity compatibility: fill missing week/period fields deterministically.
      final_obj = _normalize_ops_capacity_compat(final_obj)
      try:
        try:
          from business_type_naics import get_naics_from_business_type  # type: ignore
        except Exception:
          from client_intake_and_finmo.business_type_naics import (  # type: ignore
            get_naics_from_business_type,
          )

        if final_obj.get("business_type"):
          final_obj["business_naics_6"] = get_naics_from_business_type(
            conn, final_obj.get("business_type")
          )
      except Exception:
        if "business_naics_6" not in final_obj:
          final_obj["business_naics_6"] = None
      try:
        _enrich_milestones_timing(final_obj, reference_date=current_date)
      except Exception:
        pass

      # Persist a rendered business_description_summary (no {{fact:...}} placeholders).
      # Keep the change scoped to this single field only.
      try:
        try:
          from fact_templates import render_fact_template  # type: ignore
        except Exception:
          from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

        if isinstance(final_obj, dict) and str(final_obj.get("business_description_summary") or "").strip():
          business_facts_for_render = {
            "name": str(business_facts.get("name") or "").strip(),
            "address": str(business_facts.get("address") or "").strip(),
            "start_date": str(business_facts.get("start_date") or "").strip(),
          }
          shared_ctx_for_render = {
            "operating_model": final_obj,
            "target_market": market_json,
            "people_capability": people_json,
            "financials": financials_json,
          }
          final_obj["business_description_summary"] = render_fact_template(
            str(final_obj.get("business_description_summary") or ""),
            shared_context=shared_ctx_for_render,
            business_facts=business_facts_for_render,
          ).strip()
      except Exception:
        pass
      # Do not show the Ops summary for confirmation. Assume affirmative and
      # advance directly to Target Market after persisting the finalized ops_json.
      if not str((ops_json or {}).get("competitive_advantage") or "").strip():
        confirmed_restatement = _extract_confirmed_restatement(messages)
        proposed_advantage = _propose_ops_competitive_advantage(
          ops_json=ops_json,
          business_facts=business_facts,
          shared_context=shared_context,
          confirmed_restatement=confirmed_restatement,
        )
        proposed_advantage = sanitize_fact_template(str(proposed_advantage or "").strip())
        assistant_text = (
          f"{COMPETITIVE_ADVANTAGE_PREFIX} {proposed_advantage}\n\n"
          f"{COMPETITIVE_ADVANTAGE_QUESTION}"
        ).strip()
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          operating_model_json=ops_json,
          marketing_model_json=_refresh_marketing_model(),
          active_focus="ops",
          business_facts=business_facts,
          pending_ops_milestone_json=pending_ops_milestone,
          flat_fields=_finalize_flag_field("ops", False),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "ops",
            "awaiting_confirmation": True,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

      ops_json = final_obj
      try:
        shared_context = dict(shared_context or {})
        shared_context["operating_model"] = ops_json
        shared_context["target_market"] = market_json
        shared_context["people_capability"] = people_json
        shared_context["financials"] = financials_json
      except Exception:
        pass

      next_focus = "market"
      start_instruction = _start_instruction_for_focus(next_focus)
      turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
      intake_context_next: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "operating_model_json": ops_json,
        "target_market_json": market_json,
        "people_json": people_json,
        "financials_json": financials_json,
        "fulfillment_json": fulfillment_json,
      }
      consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
      if consumer_type not in ("consumer", "b2b", "mixed"):
        consumer_type = "consumer"
      intake_context_next["consumer_type"] = consumer_type
      market_turn = target_market_chat_turn(
        intake_context=intake_context_next, conversation_messages=turn_messages
      )
      next_assistant = str((market_turn or {}).get("assistant_message") or "").strip()
      assistant_final = f"Great, let's move on to Target Market.\n\n{next_assistant}".strip()
      assistant_final = _strip_acs_codes(sanitize_fact_template(str(assistant_final or "").strip()))

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        operating_model_json=ops_json,
        target_market_json=market_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=next_focus,
        confirmations={"ops": True},
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("ops", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": next_focus,
          "awaiting_confirmation": False,
          "done": False,
          "action": "confirm_proceed",
          "assistant_message": assistant_final,
        }
      )
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
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      if isinstance(final_obj, dict):
        final_obj.pop("target_market_summary", None)
        final_obj.pop("_pending_income_intent", None)
        final_obj.pop("_pending_capture_field", None)
        final_obj.pop("_pending_gender_focus", None)
        final_obj.pop("_pending_age_range", None)

      # Persist a rendered marketing_plan_summary (no {{fact:...}} placeholders).
      # Keep the change scoped to this single field only.
      try:
        try:
          from fact_templates import render_fact_template  # type: ignore
        except Exception:
          from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

        if isinstance(final_obj, dict) and str(final_obj.get("marketing_plan_summary") or "").strip():
          business_facts_for_render = {
            "name": str(business_facts.get("name") or "").strip(),
            "address": str(business_facts.get("address") or "").strip(),
            "start_date": str(business_facts.get("start_date") or "").strip(),
          }
          shared_ctx_for_render = {
            "operating_model": ops_json,
            "target_market": final_obj,
            "people_capability": people_json,
            "financials": financials_json,
          }
          final_obj["marketing_plan_summary"] = render_fact_template(
            str(final_obj.get("marketing_plan_summary") or ""),
            shared_context=shared_ctx_for_render,
            business_facts=business_facts_for_render,
          ).strip()
      except Exception:
        pass
      market_json = final_obj

      # Show the finalized marketing_plan_summary to the client for confirmation/counter
      # before advancing. This replaces the older in-chat "promotion model" proposal.
      assistant_final = sanitize_fact_template(
        str((market_json or {}).get("marketing_plan_summary") or "").strip()
      )
      assistant_final = _strip_acs_codes(assistant_final)
      assistant_final = f"{assistant_final}\n\n{MARKET_CONFIRM_QUESTION}".strip()

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        target_market_json=market_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus="market",
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("market", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "market",
          "awaiting_confirmation": True,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_final,
        }
      )
    elif focus == "people":
      final_obj = people_capability_finalize(intake_context=intake_context, conversation_messages=final_messages)
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      try:
        from people_roles import (  # type: ignore
          apply_oews_wages,
          apply_oews_wages_to_people,
          format_roles_summary,
        )

        roles = final_obj.get("inferred_roles") if isinstance(final_obj, dict) else None
        roles = roles if isinstance(roles, list) else []
        people_list = final_obj.get("people") if isinstance(final_obj, dict) else None
        people_list = people_list if isinstance(people_list, list) else []
        enriched_people = apply_oews_wages_to_people(
          conn,
          people=people_list,
          business_type=ops_json.get("business_type"),
          business_stage=ops_json.get("business_stage"),
          address_state=business_facts.get("address_state"),
          address=business_facts.get("address"),
          business_naics_6=ops_json.get("business_naics_6"),
        )
        enriched_roles = apply_oews_wages(
          conn,
          roles=roles,
          business_type=ops_json.get("business_type"),
          business_stage=ops_json.get("business_stage"),
          address_state=business_facts.get("address_state"),
          address=business_facts.get("address"),
          business_naics_6=ops_json.get("business_naics_6"),
        )
        final_obj["business_naics_6"] = ops_json.get("business_naics_6")
        final_obj["people"] = enriched_people
        final_obj["inferred_roles"] = enriched_roles
        final_obj["inferred_roles_summary"] = format_roles_summary(enriched_roles)
      except Exception:
        if "inferred_roles" not in final_obj:
          final_obj["inferred_roles"] = []
        if "inferred_roles_summary" not in final_obj:
          final_obj["inferred_roles_summary"] = ""
        if "business_naics_6" not in final_obj:
          final_obj["business_naics_6"] = None

      # People/HR: show a one-time review (key people + inferred roles) and ask for
      # confirmation. If the client counters, we acknowledge and advance without
      # re-showing this review again.
      if isinstance(final_obj, dict):
        final_obj.pop("key_people_summary", None)
      people_json = final_obj

      # Render People fact templates (no {{fact:...}} placeholders) for display + persistence.
      try:
        try:
          from fact_templates import render_fact_template  # type: ignore
        except Exception:
          from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

        if isinstance(people_json, dict):
          business_facts_for_render = {
            "name": str(business_facts.get("name") or "").strip(),
            "address": str(business_facts.get("address") or "").strip(),
            "start_date": str(business_facts.get("start_date") or "").strip(),
          }
          shared_ctx_for_render = {
            "operating_model": ops_json,
            "target_market": market_json,
            "people_capability": people_json,
            "financials": financials_json,
          }
          ppl = people_json.get("people")
          if isinstance(ppl, list):
            for p in ppl:
              if not isinstance(p, dict):
                continue
              for fk, fv in list(p.items()):
                if isinstance(fv, str) and "{{fact:" in fv:
                  p[fk] = render_fact_template(
                    fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
                  ).strip()
          roles = people_json.get("inferred_roles")
          if isinstance(roles, list):
            for r in roles:
              if not isinstance(r, dict):
                continue
              for fk, fv in list(r.items()):
                if isinstance(fv, str) and "{{fact:" in fv:
                  r[fk] = render_fact_template(
                    fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
                  ).strip()
      except Exception:
        pass

      key_people_blocks: List[str] = []
      try:
        people_list = people_json.get("people") if isinstance(people_json, dict) else None
        people_list = people_list if isinstance(people_list, list) else []
        for p in people_list:
          if not isinstance(p, dict):
            continue
          para = p.get("paragraph")
          if isinstance(para, str) and para.strip():
            block = para.strip()
            wage_raw = p.get("annual_wage")
            try:
              wage_val = float(wage_raw)
            except Exception:
              wage_val = None
            if wage_val is not None and wage_val > 0:
              wage_fmt = f"${int(round(wage_val)):,.0f}"
              # Keep wage visible to the client, but embedded in the narrative (no standalone line).
              block = f"{block.rstrip()} Estimated annual wage: {wage_fmt}/year."
            key_people_blocks.append(block)
      except Exception:
        key_people_blocks = []

      inferred_roles_summary = str((people_json or {}).get("inferred_roles_summary") or "").strip()
      parts: List[str] = []
      has_people = bool(key_people_blocks)
      has_roles = bool(inferred_roles_summary)
      if has_people and has_roles:
        parts.append(
          "Review this draft (key people narrative + suggested year-1 roles with wages and timing) and tell me any changes."
        )
      elif has_people:
        parts.append("Review this draft (key people narrative) and tell me any changes.")
      elif has_roles:
        parts.append("Review these suggested year-1 roles (with wages and timing) and tell me any changes.")

      if has_people:
        parts.append("\n\n".join(key_people_blocks))
      if has_roles:
        parts.append(inferred_roles_summary)
      assistant_final = "\n\n".join([p for p in parts if p.strip()]).strip()
      if assistant_final:
        assistant_final = f"{assistant_final}\n\n{PEOPLE_CONFIRM_QUESTION}".strip()
      else:
        assistant_final = PEOPLE_CONFIRM_QUESTION

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        people_json=people_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus="people",
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("people", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "people",
          "awaiting_confirmation": True,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_final,
        }
      )
    else:
      assistant_final = assistant_text

    assistant_final = sanitize_fact_template(str(assistant_final or "").strip())

    assistant_payload: Dict[str, Any] = {"role": "assistant", "content": assistant_final}

    append_messages(
      conn,
      draft_id=str(draft_id).strip(),
      new_messages=[user_msg, assistant_payload],
      operating_model_json=ops_json if focus == "ops" else None,
      target_market_json=market_json if focus == "market" else None,
      people_json=people_json if focus == "people" else None,
      financials_json=financials_json if focus == "financials" else None,
      financials_year1_json=financials_year1_json if focus == "financials" else None,
      marketing_model_json=_refresh_marketing_model(),
      active_focus=focus,
      business_facts=business_facts,
      flat_fields=_finalize_flag_field(focus, True),
    )

    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft_id).strip(),
        "client_id": client_id,
        "active_focus": focus,
        "awaiting_confirmation": True,
        "done": False,
        "action": "await_confirmation",
        "assistant_message": assistant_final,
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


