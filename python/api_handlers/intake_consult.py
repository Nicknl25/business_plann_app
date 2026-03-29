import copy
import json
import os
import re
import time
import calendar
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify

logger = logging.getLogger(__name__)
import requests
from intake_consult_draft import append_messages, ensure_draft_finmo_workbook, get_draft

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


def _should_check_revenue_patch(last_assistant: str, user_message: str) -> bool:
  assistant = str(last_assistant or "").lower()
  if "year 1 revenue" in assistant or "year-1 revenue" in assistant:
    return True
  if "revenue math" in assistant:
    return True
  msg = str(user_message or "").lower()
  keywords = [
    "unit price",
    "price per",
    "units per week",
    "units/week",
    "units per month",
    "units/month",
    "per month",
    "monthly",
    "per contract",
    "contracts",
    "retainer",
    "weeks per year",
    "weeks/year",
    "periods per year",
    "periods/year",
    "utilization",
    "capacity",
    "product",
    "line of business",
    "lob",
  ]
  return any(k in msg for k in keywords)


def _extract_revenue_proposal_patch(
  *,
  last_assistant: str,
  route_intent,
  financials_year1_json: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  text = str(last_assistant or "").strip()
  if not text:
    return None
  try:
    proposal_intent = route_intent(
      consult_type="financials_year1",
      user_message=text,
      baseline_json=financials_year1_json,
      shared_context=shared_context,
      recent_messages=[],
      active_focus="financials",
    )
  except Exception:
    return None
  if str(proposal_intent.get("action") or "").strip() != "edit_patch":
    return None
  patch = proposal_intent.get("patch")
  if not isinstance(patch, dict) or not patch:
    return None
  return patch


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


def _get_pending_revenue_adjustment_options(
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  if not isinstance(financials_json, dict):
    return []
  try:
    from financials_year1 import build_revenue_driver_signature as _build_signature  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_year1 import (  # type: ignore
      build_revenue_driver_signature as _build_signature,
    )
  current_signature = str(_build_signature(financials_year1_json or {}) or "").strip()
  pending_signature = str(financials_json.get("_pending_revenue_adjustment_signature") or "").strip()
  locked_signature = str(financials_json.get("_revenue_adjustment_locked_signature") or "").strip()
  if not current_signature or not pending_signature or pending_signature != current_signature:
    return []
  if locked_signature and locked_signature == current_signature:
    return []
  options = financials_json.get("_pending_revenue_adjustment_options")
  return [option for option in (options or []) if isinstance(option, dict)]


def _apply_revenue_option_bundle(
  *,
  financials_year1_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  option_bundle: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_year1 = financials_year1_json
  next_financials = dict(financials_json or {})
  bundle = option_bundle if isinstance(option_bundle, dict) else {}
  year1_patch = bundle.get("financials_year1_patch")
  if isinstance(year1_patch, dict) and year1_patch:
    try:
      from financials_year1 import apply_revenue_driver_patch as _apply_patch  # type: ignore
    except Exception:
      from client_intake_and_finmo.financials_year1 import (  # type: ignore
        apply_revenue_driver_patch as _apply_patch,
      )
    next_year1 = _apply_patch(financials_year1_json, year1_patch)
  financials_patch = bundle.get("financials_patch")
  if isinstance(financials_patch, dict):
    for key, value in financials_patch.items():
      field = str(key or "").strip()
      if not field:
        continue
      next_financials[field] = value
  return next_year1, next_financials


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


def _attach_consistency_financial_context(
  intake_context: Dict[str, Any],
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  ctx = dict(intake_context or {})
  forecast_quarters = []
  if isinstance(ctx.get("forecast_quarters"), list):
    forecast_quarters = [q for q in (ctx.get("forecast_quarters") or []) if isinstance(q, dict)]
  elif isinstance(ctx.get("shared_context"), dict):
    shared_forecast = ctx.get("shared_context", {}).get("forecast_quarters")
    if isinstance(shared_forecast, list):
      forecast_quarters = [q for q in shared_forecast if isinstance(q, dict)]
  try:
    try:
      from consistency_financials import (  # type: ignore
        build_consistency_financial_summary,
        build_consistency_financial_table,
      )
    except Exception:
      from client_intake_and_finmo.consistency_financials import (  # type: ignore
        build_consistency_financial_summary,
        build_consistency_financial_table,
      )

    summary = build_consistency_financial_summary(
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
    )
    ctx["consistency_financial_summary"] = summary
    ctx["consistency_financial_table_markdown"] = build_consistency_financial_table(
      summary,
      forecast_quarters=forecast_quarters,
    )
  except Exception:
    pass
  return ctx


def _get_pending_consistency_solver_state(financials_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  state = (financials_json or {}).get("_consistency_solver_state")
  if not isinstance(state, dict):
    return None
  if str(state.get("status") or "").strip() != "awaiting_choice":
    return None
  scenarios = state.get("scenarios")
  if not isinstance(scenarios, list) or not scenarios:
    return None
  return state


def _get_blocking_consistency_solver_state(financials_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  state = (financials_json or {}).get("_consistency_solver_state")
  if not isinstance(state, dict):
    return None
  if str(state.get("status") or "").strip() != "blocking_unresolved":
    return None
  return state


def _parse_consistency_solver_reply(
  *,
  user_message: str,
  solver_state: Dict[str, Any],
) -> Dict[str, Any]:
  text = str(user_message or "").strip()
  if not text or not isinstance(solver_state, dict):
    return {}
  scenarios = solver_state.get("client_scenarios")
  if not isinstance(scenarios, list) or not scenarios:
    scenarios = solver_state.get("scenarios")
  if not isinstance(scenarios, list) or not scenarios:
    return {}

  normalized = text.lower()
  selected_index: Optional[int] = None
  keyed_match = re.search(r"\b(?:option|scenario|strategy|path)\s*(\d{1,2})\b", normalized)
  if keyed_match:
    try:
      selected_index = int(keyed_match.group(1))
    except Exception:
      selected_index = None
  elif re.fullmatch(r"\s*\d{1,2}\s*", text):
    try:
      selected_index = int(text.strip())
    except Exception:
      selected_index = None
  else:
    for idx, scenario in enumerate(scenarios, start=1):
      if not isinstance(scenario, dict):
        continue
      name = str(scenario.get("scenario_name") or "").strip().lower()
      if name and name in normalized:
        selected_index = idx
        break

  if selected_index is None or selected_index < 1 or selected_index > len(scenarios):
    if "?" in text or normalized.startswith(("what", "why", "how", "which")):
      return {"intent_type": "ask_question"}
    if any(token in normalized for token in ("none", "reject", "neither", "start over", "different option")):
      return {"intent_type": "reject_all"}
    return {}

  scenario = scenarios[selected_index - 1] if isinstance(scenarios[selected_index - 1], dict) else {}
  scenario_id = str(
    scenario.get("scenario_id")
    or scenario.get("id")
    or selected_index
  ).strip()
  override_payload: Dict[str, Any] = {
    "unit_price_absolute": None,
    "price_change_percent": None,
    "utilization_percent": None,
    "marketing_total_year1_absolute": None,
    "marketing_reduction_percent": None,
    "other_opex_absolute": None,
    "other_opex_reduction_percent": None,
    "role_title": None,
    "months_until_hire": None,
    "milestone_timing_months_max": None,
  }

  percent_patterns = {
    "price_change_percent": r"\b(?:price|pricing)[^%\n\r]{0,30}?(-?\d+(?:\.\d+)?)\s*%",
    "utilization_percent": r"\butil(?:ization)?[^%\n\r]{0,30}?(\d+(?:\.\d+)?)\s*%",
    "marketing_reduction_percent": r"\bmarketing[^%\n\r]{0,30}?(?:cut|reduce|lower|down)[^%\n\r]{0,20}?(\d+(?:\.\d+)?)\s*%",
    "other_opex_reduction_percent": r"\b(?:other\s+)?opex[^%\n\r]{0,30}?(?:cut|reduce|lower|down)[^%\n\r]{0,20}?(\d+(?:\.\d+)?)\s*%",
  }
  for key, pattern in percent_patterns.items():
    match = re.search(pattern, normalized)
    if not match:
      continue
    try:
      override_payload[key] = float(match.group(1))
    except Exception:
      override_payload[key] = None

  money_patterns = {
    "unit_price_absolute": r"\b(?:price|pricing)[^\n\r$]{0,20}?\$([\d,]+(?:\.\d+)?)",
    "marketing_total_year1_absolute": r"\bmarketing[^\n\r$]{0,20}?\$([\d,]+(?:\.\d+)?)",
    "other_opex_absolute": r"\b(?:other\s+)?opex[^\n\r$]{0,20}?\$([\d,]+(?:\.\d+)?)",
  }
  for key, pattern in money_patterns.items():
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
      continue
    try:
      override_payload[key] = float(str(match.group(1)).replace(",", ""))
    except Exception:
      override_payload[key] = None

  hire_match = re.search(
    r"\b(?:hire|hiring|delay|push|move)[^.\n\r]{0,40}?(?:to|by|in)?\s*(\d+(?:\.\d+)?)\s*(?:months?|mos?)\b",
    normalized,
  )
  if hire_match:
    try:
      override_payload["months_until_hire"] = float(hire_match.group(1))
    except Exception:
      override_payload["months_until_hire"] = None

  milestone_match = re.search(
    r"\bmilestone[^.\n\r]{0,40}?(?:within|by|in|under|max)?\s*(\d+(?:\.\d+)?)\s*(?:months?|mos?)\b",
    normalized,
  )
  if milestone_match:
    try:
      override_payload["milestone_timing_months_max"] = float(milestone_match.group(1))
    except Exception:
      override_payload["milestone_timing_months_max"] = None

  role_match = re.search(
    r"\b(?:hire|hiring|delay|push|move)\s+([a-z][a-z0-9 &/-]{1,60}?)(?:\s+(?:to|by|in)\s+\d+\s*(?:months?|mos?))?\b",
    normalized,
  )
  if role_match:
    role_title = str(role_match.group(1) or "").strip(" .,:;")
    override_payload["role_title"] = role_title or None

  has_override = any(value is not None for value in override_payload.values())
  return {
    "intent_type": "modify_option" if has_override else "select_option",
    "selected_scenario_id": scenario_id,
    **override_payload,
  }


def _clear_consistency_solver_state(financials_json: Dict[str, Any]) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  next_financials.pop("_consistency_solver_state", None)
  next_financials.pop("_consistency_close_stage", None)
  return next_financials

def _build_consistency_initial_table(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> str:
  ctx = _attach_consistency_financial_context(
    {},
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  table_markdown = str(ctx.get("consistency_financial_table_markdown") or "").strip()
  return table_markdown


def _build_consistency_runtime_context(
  *,
  client_id: str,
  draft_id: str,
  finmo_path: Optional[str],
  business_facts: Dict[str, Any],
  business_stage_hint: Optional[str],
  current_date_iso: str,
  shared_context: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  ctx: Dict[str, Any] = {
    "client_id": client_id,
    "draft_id": str(draft_id).strip(),
    "finmo_path": str(finmo_path or "").strip(),
    "business_name": business_facts.get("name"),
    "business_start_date": business_facts.get("start_date"),
    "address": business_facts.get("address"),
    "current_date": current_date_iso,
    "business_stage_hint": business_stage_hint,
    "shared_context": dict(shared_context or {}),
    "operating_model_json": ops_json,
    "target_market_json": market_json,
    "people_json": people_json,
    "financials_json": financials_json,
    "financials_year1_json": financials_year1_json,
    "fulfillment_json": fulfillment_json,
  }
  if isinstance(marketing_model_json, dict):
    ctx["marketing_model_json"] = marketing_model_json
  return ctx


def _build_constraint_bundle_for_persistence(
  *,
  conn=None,
  intake_context: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    context = intake_context if isinstance(intake_context, dict) else {}
    try:
      from solver_trace import reset_solver_trace_stage, trace_lazy  # type: ignore
    except Exception:
      from client_intake_and_finmo.solver_trace import reset_solver_trace_stage, trace_lazy  # type: ignore
    reset_solver_trace_stage()
    trace_lazy(
      "INPUTS",
      "Persisted state entering planning pipeline",
      lambda: {
        "operating_model_json": ops_json or {},
        "target_market_json": market_json or {},
        "people_json": people_json or {},
        "financials_json": financials_json or {},
        "financials_year1_json": financials_year1_json or {},
        "marketing_model_json": marketing_model_json or {},
        "fulfillment_json": context.get("fulfillment_json") if isinstance(context, dict) else {},
      },
    )
    try:
      from constraint_engine import build_constraint_engine_bundle  # type: ignore
    except Exception:
      from client_intake_and_finmo.constraint_engine import build_constraint_engine_bundle  # type: ignore
    try:
      from forecast_engine import build_forecast_engine_bundle  # type: ignore
    except Exception:
      from client_intake_and_finmo.forecast_engine import build_forecast_engine_bundle  # type: ignore
    constraint_bundle = build_constraint_engine_bundle(
      conn=conn,
      shared_context=context.get("shared_context") if isinstance(context, dict) else {},
      operating_model_json=ops_json or {},
      target_market_json=market_json or {},
      people_json=people_json or {},
      financials_json=financials_json or {},
      financials_year1_json=financials_year1_json or {},
      marketing_model_json=marketing_model_json or {},
      fulfillment_json=context.get("fulfillment_json") if isinstance(context, dict) else {},
    )
    forecast_bundle = build_forecast_engine_bundle(
      shared_context=context.get("shared_context") if isinstance(context, dict) else {},
      operating_model_json=ops_json or {},
      target_market_json=market_json or {},
      people_json=people_json or {},
      financials_json=financials_json or {},
      financials_year1_json=financials_year1_json or {},
      marketing_model_json=marketing_model_json or {},
      normalized_traits=(
        constraint_bundle.get("normalized_traits") if isinstance(constraint_bundle, dict) else None
      ),
      benchmark_payload=(
        constraint_bundle.get("benchmark_payload") if isinstance(constraint_bundle, dict) else None
      ),
      constraint_engine_state=(
        constraint_bundle.get("constraint_engine_state") if isinstance(constraint_bundle, dict) else None
      ),
    )

    merged_bundle = dict(constraint_bundle or {})
    if isinstance(forecast_bundle, dict):
      merged_bundle["forecast_engine_state"] = forecast_bundle.get("forecast_engine_state") or {}
      merged_bundle["forecast_quarters"] = forecast_bundle.get("forecast_quarters") or []
      base_versions = dict((constraint_bundle or {}).get("engine_versions") or {})
      forecast_versions = dict(forecast_bundle.get("engine_versions") or {})
      for key, value in forecast_versions.items():
        if value is None or value == "":
          base_versions.setdefault(key, value)
          continue
        base_versions[key] = value
      merged_bundle["engine_versions"] = base_versions
    trace_lazy(
      "DERIVED",
      "Constraint and forecast bundles",
      lambda: {
        "normalized_traits": merged_bundle.get("normalized_traits") or {},
        "benchmark_payload": merged_bundle.get("benchmark_payload") or {},
        "constraint_engine_state": merged_bundle.get("constraint_engine_state") or {},
        "forecast_engine_state": merged_bundle.get("forecast_engine_state") or {},
      },
    )
    return merged_bundle
  except Exception:
    return {}


def _constraint_bundle_append_kwargs(bundle: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = bundle if isinstance(bundle, dict) else {}
  return {
    "normalized_traits_json": payload.get("normalized_traits"),
    "benchmark_payload_json": payload.get("benchmark_payload"),
    "constraint_engine_state_json": payload.get("constraint_engine_state"),
    "forecast_engine_state_json": payload.get("forecast_engine_state"),
    "forecast_quarters_json": payload.get("forecast_quarters"),
    "engine_versions_json": payload.get("engine_versions"),
  }


def _constraint_bundle_response_kwargs(bundle: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = bundle if isinstance(bundle, dict) else {}
  return {
    "forecast_engine_state": payload.get("forecast_engine_state") or {},
    "forecast_quarters": payload.get("forecast_quarters") or [],
    "engine_versions": payload.get("engine_versions") or {},
  }


def _refresh_shared_forecast_context(
  shared_context: Optional[Dict[str, Any]],
  bundle: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  updated = dict(shared_context or {})
  payload = bundle if isinstance(bundle, dict) else {}
  updated["forecast_engine_state"] = payload.get("forecast_engine_state") or {}
  updated["forecast_quarters"] = payload.get("forecast_quarters") or []
  updated["engine_versions"] = payload.get("engine_versions") or {}
  return updated


def _humanize_business_descriptor(
  *,
  solver_state: Optional[Dict[str, Any]],
) -> str:
  fixed_facts = (((solver_state or {}).get("state_model") or {}).get("fixed_facts") or {}) if isinstance(((solver_state or {}).get("state_model") or {}), dict) else {}
  fixed_facts = fixed_facts if isinstance(fixed_facts, dict) else {}
  business_type = str(fixed_facts.get("business_type") or "").strip()
  if business_type:
    return business_type
  commercial_context = fixed_facts.get("commercial_context") if isinstance(fixed_facts.get("commercial_context"), dict) else {}
  archetype = str((commercial_context or {}).get("commercial_archetype") or "").strip().replace("_", " ")
  if archetype:
    return archetype
  return "business"


def _build_quarterly_projection_table(forecast_quarters: Optional[List[Dict[str, Any]]]) -> str:
  try:
    try:
      from consistency_financials import _build_quarterly_ebitda_forecast_table  # type: ignore
    except Exception:
      from client_intake_and_finmo.consistency_financials import _build_quarterly_ebitda_forecast_table  # type: ignore
  except Exception:
    return ""
  return str(_build_quarterly_ebitda_forecast_table(forecast_quarters or []) or "").strip()


def _build_consistency_forecast_view_from_finmo_safe(
  finmo_json: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
  try:
    try:
      from finmo_bridge import build_consistency_forecast_view_from_finmo  # type: ignore
    except Exception:
      from client_intake_and_finmo.finmo_bridge import build_consistency_forecast_view_from_finmo  # type: ignore
  except Exception:
    return [], []
  try:
    result = build_consistency_forecast_view_from_finmo(finmo_json if isinstance(finmo_json, dict) else {})
  except Exception:
    return [], []
  quarter_driver_path = [item for item in ((result.get("quarter_driver_path") or []) if isinstance(result, dict) else []) if isinstance(item, dict)]
  forecast_years = [item for item in ((result.get("forecast_years") or []) if isinstance(result, dict) else []) if isinstance(item, dict)]
  return quarter_driver_path, forecast_years


def _describe_modified_levers(scenario: Optional[Dict[str, Any]]) -> str:
  scenario_obj = scenario if isinstance(scenario, dict) else {}
  families = [
    str(item or "").strip()
    for item in (scenario_obj.get("lever_families") or scenario_obj.get("meaningful_families") or [])
    if str(item or "").strip()
  ]
  label_map = {
    "price": "pricing",
    "utilization": "utilization",
    "marketing": "marketing",
    "staffing": "staffing",
    "payroll": "staffing support",
    "opex": "operating expense",
    "cogs": "cost structure",
    "milestone": "timing",
  }
  labels = [label_map.get(item, item.replace("_", " ")) for item in families]
  labels = [item for item in labels if item]
  if not labels:
    return "the operating path"
  if len(labels) == 1:
    return labels[0]
  if len(labels) == 2:
    return f"{labels[0]} and {labels[1]}"
  return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _build_consistency_finalized_message(
  *,
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
  initial_table_markdown: str,
  modified_forecast_quarters: Optional[List[Dict[str, Any]]],
  finmo_json: Optional[Dict[str, Any]] = None,
) -> str:
  if isinstance(finmo_json, dict) and finmo_json:
    finmo_quarters, _ = _build_consistency_forecast_view_from_finmo_safe(finmo_json)
    if finmo_quarters:
      modified_forecast_quarters = finmo_quarters
  quarter_table = _build_quarterly_projection_table(modified_forecast_quarters)
  business_descriptor = _humanize_business_descriptor(solver_state=solver_state)
  scenario_obj = selected_scenario if isinstance(selected_scenario, dict) else {}
  client_output = scenario_obj.get("client_output") if isinstance(scenario_obj.get("client_output"), dict) else {}
  scenario_summary = str(client_output.get("summary") or "").strip()
  dominant_tradeoff = str(
    scenario_obj.get("dominant_tradeoff")
    or client_output.get("scenario_name")
    or "the most viable path"
  ).strip()
  modified_levers = _describe_modified_levers(scenario_obj)
  explanation = (
    f"The Initial Projections table shows the original Year 1 plan captured during intake. "
    f"The Modified Quarterly Projections table shows the revised quarter-by-quarter path that best aligns this {business_descriptor} with a realistic operating structure. "
    f"We adjusted {modified_levers} so the business follows the most viable path for this type of operation; {scenario_summary.lower() if scenario_summary else dominant_tradeoff.lower()}. "
    f"At this stage, moving materially away from this path would reduce realism and internal consistency. Intake is now complete. You may submit the plan."
  )
  sections = ["Initial Projections", "", initial_table_markdown.strip(), "", "Modified Quarterly Projections"]
  if quarter_table:
    sections.extend(["", quarter_table])
  sections.extend(["", explanation.strip()])
  return "\n".join([section for section in sections if section is not None]).strip()


def _build_consistency_blocked_message(
  *,
  solver_state: Optional[Dict[str, Any]],
  initial_table_markdown: str,
) -> str:
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  blocking_reason = str(solver_obj.get("blocking_reason") or "").strip()
  blocking_violations = [
    str(item or "").strip().replace("_", " ")
    for item in (solver_obj.get("blocking_violations") or [])
    if str(item or "").strip()
  ]
  reason_text = "No viable governed scenario was produced after the allowed consistency attempts."
  if blocking_reason == "no_viable_scenarios":
    reason_text = "No viable governed scenario was produced after the allowed consistency attempts."
  elif blocking_reason:
    reason_text = f"Consistency could not finish because of {blocking_reason.replace('_', ' ')}."
  details = ""
  if blocking_violations:
    details = f" Remaining blocking issues: {', '.join(blocking_violations)}."
  sections = [
    "Initial Projections",
    "",
    initial_table_markdown.strip(),
    "",
    "Consistency remains unresolved.",
    "",
    f"{reason_text}{details} Intake is staying in consistency until a governed path is produced.",
  ]
  return "\n".join([section for section in sections if section is not None]).strip()


def _build_consistency_provisional_message(
  *,
  solver_state: Optional[Dict[str, Any]],
  attempted_scenario: Optional[Dict[str, Any]],
  initial_table_markdown: str,
  modified_forecast_quarters: Optional[List[Dict[str, Any]]],
  finmo_json: Optional[Dict[str, Any]] = None,
) -> str:
  if isinstance(finmo_json, dict) and finmo_json:
    finmo_quarters, _ = _build_consistency_forecast_view_from_finmo_safe(finmo_json)
    if finmo_quarters:
      modified_forecast_quarters = finmo_quarters
  quarter_table = _build_quarterly_projection_table(modified_forecast_quarters)
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  blocking_violations = [
    str(item or "").strip().replace("_", " ")
    for item in (solver_obj.get("blocking_violations") or [])
    if str(item or "").strip()
  ]
  scenario_obj = attempted_scenario if isinstance(attempted_scenario, dict) else {}
  client_output = scenario_obj.get("client_output") if isinstance(scenario_obj.get("client_output"), dict) else {}
  scenario_summary = str(client_output.get("summary") or "").strip()
  dominant_tradeoff = str(
    scenario_obj.get("dominant_tradeoff")
    or client_output.get("scenario_name")
    or "the strongest governed path produced so far"
  ).strip()
  business_descriptor = _humanize_business_descriptor(solver_state=solver_state)
  modified_levers = _describe_modified_levers(scenario_obj)
  issue_text = f" Remaining blocking issues: {', '.join(blocking_violations)}." if blocking_violations else ""
  explanation = (
    f"The Initial Projections table shows the original Year 1 plan captured during intake. "
    f"The Modified Quarterly Projections table shows the strongest quarter-by-quarter path produced so far for this {business_descriptor}. "
    f"We adjusted {modified_levers} so the business moves toward a more realistic operating structure; {scenario_summary.lower() if scenario_summary else dominant_tradeoff.lower()}. "
    f"Consistency is still unresolved and intake is staying in consistency while GPT and controller continue refining the path.{issue_text}"
  )
  sections = ["Initial Projections", "", initial_table_markdown.strip(), "", "Modified Quarterly Projections"]
  if quarter_table:
    sections.extend(["", quarter_table])
  sections.extend(["", explanation.strip()])
  return "\n".join([section for section in sections if section is not None]).strip()


def _build_consistency_financial_summary_safe(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  try:
    try:
      from consistency_financials import build_consistency_financial_summary  # type: ignore
    except Exception:
      from client_intake_and_finmo.consistency_financials import build_consistency_financial_summary  # type: ignore
    summary = build_consistency_financial_summary(
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
    )
    return summary if isinstance(summary, dict) else {}
  except Exception:
    return {}


def _rollup_forecast_years_from_quarters(
  forecast_quarters: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  quarters = [quarter for quarter in (forecast_quarters or []) if isinstance(quarter, dict)]
  if not quarters:
    return []
  years: List[Dict[str, Any]] = []
  for year_index in range(5):
    year_quarters = quarters[year_index * 4:(year_index + 1) * 4]
    if not year_quarters:
      continue
    utilization_values = [
      _safe_float(quarter.get("utilization"))
      for quarter in year_quarters
      if _safe_float(quarter.get("utilization")) is not None
    ]
    years.append(
      {
        "year_index": year_index + 1,
        "period_label": f"Year {year_index + 1}",
        "revenue": round(sum(_safe_float(quarter.get("revenue")) or 0.0 for quarter in year_quarters), 2),
        "cogs": round(sum(_safe_float(quarter.get("cogs")) or 0.0 for quarter in year_quarters), 2),
        "payroll": round(sum(_safe_float(quarter.get("payroll")) or 0.0 for quarter in year_quarters), 2),
        "marketing": round(sum(_safe_float(quarter.get("marketing")) or 0.0 for quarter in year_quarters), 2),
        "opex": round(sum(_safe_float(quarter.get("opex")) or 0.0 for quarter in year_quarters), 2),
        "ebitda": round(sum(_safe_float(quarter.get("ebitda")) or 0.0 for quarter in year_quarters), 2),
        "net_income": round(sum(_safe_float(quarter.get("net_income")) or 0.0 for quarter in year_quarters), 2),
        "utilization": (
          round(sum(value for value in utilization_values if value is not None) / len(utilization_values), 6)
          if utilization_values
          else None
        ),
      }
    )
  return years


def _build_consistency_modified_plan_payload(
  *,
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
  constraint_bundle: Optional[Dict[str, Any]],
  initial_ops_json: Dict[str, Any],
  initial_market_json: Dict[str, Any],
  initial_people_json: Dict[str, Any],
  initial_financials_json: Dict[str, Any],
  initial_financials_year1_json: Dict[str, Any],
  initial_marketing_model_json: Dict[str, Any],
  modified_ops_json: Dict[str, Any],
  modified_market_json: Dict[str, Any],
  modified_people_json: Dict[str, Any],
  modified_financials_json: Dict[str, Any],
  modified_financials_year1_json: Dict[str, Any],
  modified_marketing_model_json: Dict[str, Any],
  modified_forecast_quarters: Optional[List[Dict[str, Any]]],
  finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  scenario_obj = selected_scenario if isinstance(selected_scenario, dict) else {}
  bundle = constraint_bundle if isinstance(constraint_bundle, dict) else {}
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  state_model = solver_obj.get("state_model") if isinstance(solver_obj.get("state_model"), dict) else {}
  fixed_facts = state_model.get("fixed_facts") if isinstance(state_model.get("fixed_facts"), dict) else {}
  forecast_engine_state = (
    scenario_obj.get("forecast_engine_state")
    if isinstance(scenario_obj.get("forecast_engine_state"), dict)
    else bundle.get("forecast_engine_state")
  )
  forecast_engine_state = forecast_engine_state if isinstance(forecast_engine_state, dict) else {}
  finmo_quarters, finmo_years = _build_consistency_forecast_view_from_finmo_safe(finmo_json)
  if finmo_quarters:
    modified_forecast_quarters = finmo_quarters
  forecast_years = finmo_years if finmo_years else (
    forecast_engine_state.get("forecast_years") if isinstance(forecast_engine_state.get("forecast_years"), list) else []
  )
  if not forecast_years:
    forecast_years = _rollup_forecast_years_from_quarters(modified_forecast_quarters)
  quarter_driver_path: List[Dict[str, Any]] = []
  quarter_rollups: List[Dict[str, Any]] = []
  child_first = False
  for quarter in modified_forecast_quarters or []:
    if not isinstance(quarter, dict):
      continue
    driver_row = copy.deepcopy(quarter)
    lobs = driver_row.get("lobs")
    child_first = child_first or (isinstance(lobs, list) and len(lobs) > 0)
    driver_row["source_level"] = "child_rollup" if isinstance(lobs, list) and lobs else "parent_only"
    quarter_driver_path.append(driver_row)
    rollup_row = {k: copy.deepcopy(v) for k, v in quarter.items() if k != "lobs"}
    rollup_row["source_level"] = driver_row["source_level"]
    quarter_rollups.append(rollup_row)

  if not child_first:
    child_first = bool(
      isinstance(modified_financials_year1_json.get("lobs"), list) and modified_financials_year1_json.get("lobs")
    )

  scenario_client_output = scenario_obj.get("client_output") if isinstance(scenario_obj.get("client_output"), dict) else {}
  modified_year1_summary = _build_consistency_financial_summary_safe(
    financials_json=modified_financials_json,
    financials_year1_json=modified_financials_year1_json,
  )
  initial_year1_summary = _build_consistency_financial_summary_safe(
    financials_json=initial_financials_json,
    financials_year1_json=initial_financials_year1_json,
  )

  return {
    "contract_version": "consistency_modified_plan_v1",
    "source": "scenario" if scenario_obj else "baseline_forecast",
    "child_first": bool(child_first),
    "business_context": {
      "business_type": str(fixed_facts.get("business_type") or modified_ops_json.get("business_type") or "").strip(),
      "business_stage": str(
        fixed_facts.get("business_stage")
        or modified_ops_json.get("business_stage")
        or (((bundle.get("normalized_traits") or {}) if isinstance(bundle.get("normalized_traits"), dict) else {}).get("business_stage"))
        or ""
      ).strip(),
      "capacity_driver": str(fixed_facts.get("capacity_driver") or modified_ops_json.get("capacity_driver") or "").strip(),
      "sales_modality": str(fixed_facts.get("sales_modality") or modified_ops_json.get("sales_modality") or "").strip(),
      "customer_type": str(fixed_facts.get("customer_type") or modified_ops_json.get("customer_type") or "").strip(),
      "unit_cadence": str(fixed_facts.get("unit_cadence") or modified_ops_json.get("unit_cadence") or "").strip(),
    },
    "scenario": {
      "scenario_id": scenario_obj.get("scenario_id"),
      "strategy_id": scenario_obj.get("strategy_id"),
      "archetype": scenario_obj.get("archetype"),
      "dominant_tradeoff": scenario_obj.get("dominant_tradeoff"),
      "demand_posture": scenario_obj.get("demand_posture"),
      "staffing_posture": scenario_obj.get("staffing_posture"),
      "cost_posture": scenario_obj.get("cost_posture"),
      "scenario_name": scenario_client_output.get("scenario_name"),
      "summary": scenario_client_output.get("summary"),
      "tradeoff": scenario_client_output.get("tradeoff"),
      "confidence": scenario_client_output.get("confidence"),
    },
    "initial_plan": {
      "operating_model": copy.deepcopy(initial_ops_json or {}),
      "target_market": copy.deepcopy(initial_market_json or {}),
      "people": copy.deepcopy(initial_people_json or {}),
      "financials": copy.deepcopy(initial_financials_json or {}),
      "financials_year1": copy.deepcopy(initial_financials_year1_json or {}),
      "marketing_model": copy.deepcopy(initial_marketing_model_json or {}),
      "year1_summary": initial_year1_summary,
    },
    "modified_plan": {
      "operating_model": copy.deepcopy(modified_ops_json or {}),
      "target_market": copy.deepcopy(modified_market_json or {}),
      "people": copy.deepcopy(modified_people_json or {}),
      "financials": copy.deepcopy(modified_financials_json or {}),
      "financials_year1": copy.deepcopy(modified_financials_year1_json or {}),
      "marketing_model": copy.deepcopy(modified_marketing_model_json or {}),
      "year1_summary": modified_year1_summary,
    },
    "year1_modified_state": copy.deepcopy((forecast_years[0] if forecast_years else modified_year1_summary) or {}),
    "quarter_driver_path": quarter_driver_path,
    "quarter_rollups": quarter_rollups,
    "forecast_years": copy.deepcopy(forecast_years or []),
    "forecast_meta": {
      "financial_authority": "finmo" if finmo_years else "forecast_engine",
      "forecast_confidence": forecast_engine_state.get("forecast_confidence"),
      "convergence_source": forecast_engine_state.get("convergence_source"),
      "convergence_strength": forecast_engine_state.get("convergence_strength"),
      "year1_warning_status": forecast_engine_state.get("year1_warning_status"),
      "blocking_violations": copy.deepcopy(forecast_engine_state.get("blocking_violations") or []),
      "forecast_orchestration": copy.deepcopy(forecast_engine_state.get("forecast_orchestration") or {}),
      "scenario_strategy": copy.deepcopy(forecast_engine_state.get("scenario_strategy") or {}),
      "finmo_accounting_check": copy.deepcopy(
        (finmo_json.get("accounting_check") if isinstance(finmo_json, dict) else {}) or {}
      ),
    },
    "timed_events": {
      "role_timing_overrides": copy.deepcopy(
        ((forecast_engine_state.get("forecast_orchestration") or {}) if isinstance(forecast_engine_state.get("forecast_orchestration"), dict) else {}).get("role_timing_overrides") or []
      ),
      "milestone_timing_overrides": copy.deepcopy(
        ((forecast_engine_state.get("forecast_orchestration") or {}) if isinstance(forecast_engine_state.get("forecast_orchestration"), dict) else {}).get("milestone_timing_overrides") or []
      ),
      "event_response": copy.deepcopy(
        ((forecast_engine_state.get("forecast_orchestration") or {}) if isinstance(forecast_engine_state.get("forecast_orchestration"), dict) else {}).get("event_response") or {}
      ),
    },
  }


def _normalized_violation_codes(values: Any) -> List[str]:
  codes: List[str] = []
  seen = set()
  for item in values or []:
    code = str(item or "").strip()
    if not code or code in seen:
      continue
    seen.add(code)
    codes.append(code)
  return codes


def _quarter_violation_codes(
  forecast_quarters: Optional[List[Dict[str, Any]]],
) -> List[str]:
  combined: List[str] = []
  for quarter in forecast_quarters or []:
    if not isinstance(quarter, dict):
      continue
    combined.extend(quarter.get("constraint_violations") or [])
  return _normalized_violation_codes(combined)


def _build_violation_resolution_summary(
  *,
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
  constraint_bundle: Optional[Dict[str, Any]],
  modified_forecast_quarters: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  scenario_obj = selected_scenario if isinstance(selected_scenario, dict) else {}
  bundle = constraint_bundle if isinstance(constraint_bundle, dict) else {}
  constraint_engine_state = bundle.get("constraint_engine_state") if isinstance(bundle.get("constraint_engine_state"), dict) else {}
  forecast_engine_state = (
    scenario_obj.get("forecast_engine_state")
    if isinstance(scenario_obj.get("forecast_engine_state"), dict)
    else bundle.get("forecast_engine_state")
  )
  forecast_engine_state = forecast_engine_state if isinstance(forecast_engine_state, dict) else {}

  baseline_violations = _normalized_violation_codes(
    (constraint_engine_state.get("violations") or [])
    or (solver_obj.get("constraint_violations") or [])
    or (solver_obj.get("blocking_violations") or [])
  )
  scenario_remaining = _normalized_violation_codes(scenario_obj.get("remaining_violations") or [])
  scenario_remaining_blocking = _normalized_violation_codes(
    scenario_obj.get("remaining_blocking_violations") or []
  )
  forecast_blocking = _normalized_violation_codes(forecast_engine_state.get("blocking_violations") or [])
  quarter_violations = _quarter_violation_codes(modified_forecast_quarters)

  final_violations = _normalized_violation_codes(
    scenario_remaining or quarter_violations or forecast_blocking
  )
  final_blocking_violations = _normalized_violation_codes(
    scenario_remaining_blocking or forecast_blocking
  )
  resolved_violations = [
    code for code in baseline_violations
    if code not in set(final_violations)
  ]
  remaining_violations = list(final_violations)

  if not baseline_violations and not remaining_violations:
    status = "no_errors"
    display = "no errors"
  elif not remaining_violations:
    status = "cleared"
    display = "cleared"
  elif not final_blocking_violations:
    status = "soft_issues_remaining"
    display = "soft issues remaining"
  else:
    status = "hard_issues_remaining"
    display = "hard issues remaining"

  return {
    "status": status,
    "display_status": display,
    "baseline_violations": baseline_violations,
    "resolved_violations": resolved_violations,
    "remaining_violations": remaining_violations,
    "remaining_blocking_violations": final_blocking_violations,
    "all_cleared": not remaining_violations,
    "hard_cleared": not final_blocking_violations,
  }


def _require_consistency_modified_plan(closeout: Any) -> Dict[str, Any]:
  payload = (
    closeout.get("consistency_modified_plan_json")
    if isinstance(closeout, dict)
    else None
  )
  if isinstance(payload, dict) and payload:
    return payload
  raise RuntimeError("consistency_modified_plan_missing")


def _valid_consistency_modified_plan_from_closeout(closeout: Any) -> Optional[Dict[str, Any]]:
  payload = (
    closeout.get("consistency_modified_plan_json")
    if isinstance(closeout, dict)
    else None
  )
  if not isinstance(payload, dict) or not payload:
    return None
  if not isinstance(payload.get("quarter_driver_path"), list) or not payload.get("quarter_driver_path"):
    return None
  if not isinstance(payload.get("forecast_years"), list) or not payload.get("forecast_years"):
    return None
  if not isinstance(payload.get("resolution_summary"), dict) or not payload.get("resolution_summary"):
    return None
  return payload


def _consistency_closeout_ready_for_completion(closeout: Any) -> bool:
  if not isinstance(closeout, dict):
    return False
  solver_state = closeout.get("solver_state") if isinstance(closeout.get("solver_state"), dict) else {}
  if str(solver_state.get("status") or "").strip() == "blocking_unresolved":
    return False
  return _valid_consistency_modified_plan_from_closeout(closeout) is not None


def _consistency_trace_scenario_summary(scenario: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(scenario, dict):
    return {}
  return {
    "scenario_id": scenario.get("scenario_id"),
    "strategy_id": scenario.get("strategy_id"),
    "strategy_name": scenario.get("strategy_name"),
    "strategy_source": scenario.get("strategy_source"),
    "label": scenario.get("label"),
    "rationale": scenario.get("rationale"),
    "archetype": scenario.get("archetype"),
    "archetype_display": scenario.get("archetype_display"),
    "dominant_tradeoff": scenario.get("dominant_tradeoff"),
    "canonical_lever_vocabulary": scenario.get("canonical_lever_vocabulary"),
    "allowed_model_input_levers": copy.deepcopy(scenario.get("allowed_model_input_levers") or []),
    "remaining_violations": copy.deepcopy(scenario.get("remaining_violations") or []),
    "remaining_blocking_violations": copy.deepcopy(scenario.get("remaining_blocking_violations") or []),
    "realism_distance": scenario.get("realism_distance"),
    "target_distance": scenario.get("target_distance"),
    "lever_summary": copy.deepcopy(scenario.get("lever_summary") or {}),
    "contract_diagnostics": copy.deepcopy(scenario.get("contract_diagnostics") or {}),
    "forecast_orchestration": copy.deepcopy(scenario.get("forecast_orchestration") or {}),
    "exact_patches": copy.deepcopy(scenario.get("exact_patches") or {}),
    "summary": copy.deepcopy(scenario.get("summary") or {}),
  }


def _consistency_trace_contract_summary(bundle: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(bundle, dict):
    return {}
  profile = bundle.get("profile") if isinstance(bundle.get("profile"), dict) else {}
  diagnostics = bundle.get("diagnostics") if isinstance(bundle.get("diagnostics"), dict) else {}
  direct_inputs = bundle.get("direct_inputs") if isinstance(bundle.get("direct_inputs"), dict) else {}
  return {
    "strategy_id": str(profile.get("strategy_id") or profile.get("profile_id") or diagnostics.get("strategy_id") or "").strip(),
    "strategy_name": str(profile.get("strategy_name") or profile.get("profile_id") or "").strip(),
    "strategy_source": str(profile.get("strategy_source") or diagnostics.get("strategy_source") or "").strip(),
    "canonical_lever_vocabulary": "model_inputs_controller_write_only",
    "allowed_model_input_levers": copy.deepcopy((((bundle.get("controller_calibration_request") or {}) if isinstance(bundle.get("controller_calibration_request"), dict) else {}).get("allowed_model_input_levers") or [])),
    "forecast_orchestration": copy.deepcopy(profile.get("forecast_orchestration") or {}),
    "contract_diagnostics": copy.deepcopy(diagnostics),
    "contract_inputs": {
      "target_payroll_min_total": direct_inputs.get("target_payroll_min_total"),
      "target_payroll_max_total": direct_inputs.get("target_payroll_max_total"),
      "structural_payroll_floor": direct_inputs.get("structural_payroll_floor"),
      "marketing_min": direct_inputs.get("marketing_min"),
      "marketing_upper": direct_inputs.get("marketing_upper"),
      "other_opex_min": direct_inputs.get("other_opex_min"),
      "other_opex_max": direct_inputs.get("other_opex_max"),
      "price_lower": direct_inputs.get("price_lower"),
      "price_upper": direct_inputs.get("price_upper"),
      "util_min": direct_inputs.get("util_min"),
      "util_max": direct_inputs.get("util_max"),
      "units_min": direct_inputs.get("units_min"),
      "units_max": direct_inputs.get("units_max"),
    },
  }


def _build_consistency_gpt_governance_payload(
  *,
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  state_model = solver_obj.get("state_model") if isinstance(solver_obj.get("state_model"), dict) else {}
  strategy_layer = state_model.get("strategy_layer") if isinstance(state_model.get("strategy_layer"), dict) else {}
  diagnosis = strategy_layer.get("diagnosis") if isinstance(strategy_layer.get("diagnosis"), dict) else {}
  strategy_selection = strategy_layer.get("strategy_selection") if isinstance(strategy_layer.get("strategy_selection"), dict) else {}
  strategies = [copy.deepcopy(item) for item in (strategy_layer.get("strategies") or []) if isinstance(item, dict)]
  return {
    "contract_version": "consistency_gpt_governance_v1",
    "required_at_runtime": True,
    "status": solver_obj.get("status"),
    "blocking_reason": solver_obj.get("blocking_reason"),
    "strategy_layer_source": strategy_layer.get("source"),
    "primary_drivers": copy.deepcopy(strategy_layer.get("primary_drivers") or []),
    "diagnosis": copy.deepcopy(diagnosis),
    "strategy_selection": copy.deepcopy(strategy_selection),
    "selected_strategies": strategies,
    "governed_attempt_count": int(solver_obj.get("governed_attempt_count") or 0),
    "retry_attempts": copy.deepcopy(solver_obj.get("strategy_retry_attempts") or []),
    "selected_scenario": _consistency_trace_scenario_summary(selected_scenario),
  }


def _build_consistency_controller_contract_payload(
  *,
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  scenarios = [
    _consistency_trace_scenario_summary(item)
    for item in (solver_obj.get("scenarios") or [])
    if isinstance(item, dict)
  ]
  attempted_contracts = [
    _consistency_trace_contract_summary(item)
    for item in (solver_obj.get("attempted_contract_bundles") or [])
    if isinstance(item, dict)
  ]
  return {
    "contract_version": "consistency_controller_contract_v1",
    "status": solver_obj.get("status"),
    "selection_mode": solver_obj.get("selection_mode"),
    "solve_mode": solver_obj.get("solve_mode"),
    "search_mode": solver_obj.get("search_mode"),
    "selected_target_label": solver_obj.get("selected_target_label"),
    "selected_target_ebitda_min": solver_obj.get("selected_target_ebitda_min"),
    "selected_target_ebitda_max": solver_obj.get("selected_target_ebitda_max"),
    "governed_attempt_count": int(solver_obj.get("governed_attempt_count") or 0),
    "retry_attempts": copy.deepcopy(solver_obj.get("strategy_retry_attempts") or []),
    "selected_scenario": _consistency_trace_scenario_summary(selected_scenario),
    "scenario_contracts": scenarios or attempted_contracts,
  }


def _build_consistency_solver_execution_payload(
  *,
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  scenarios = [
    _consistency_trace_scenario_summary(item)
    for item in (solver_obj.get("scenarios") or [])
    if isinstance(item, dict)
  ]
  attempted_scenarios = [
    _consistency_trace_scenario_summary(item)
    for item in (solver_obj.get("attempted_scenarios") or [])
    if isinstance(item, dict)
  ]
  return {
    "contract_version": "consistency_solver_execution_v1",
    "status": solver_obj.get("status"),
    "blocking_reason": solver_obj.get("blocking_reason"),
    "blocking_violations": copy.deepcopy(solver_obj.get("blocking_violations") or []),
    "selection_mode": solver_obj.get("selection_mode"),
    "solve_mode": solver_obj.get("solve_mode"),
    "search_mode": solver_obj.get("search_mode"),
    "structural_gap": solver_obj.get("structural_gap"),
    "baseline_summary": copy.deepcopy(solver_obj.get("baseline_summary") or {}),
    "baseline_loss_pct": solver_obj.get("baseline_loss_pct"),
    "governed_attempt_count": int(solver_obj.get("governed_attempt_count") or 0),
    "retry_attempts": copy.deepcopy(solver_obj.get("strategy_retry_attempts") or []),
    "scenario_count": len(scenarios),
    "attempted_scenario_count": len(attempted_scenarios),
    "selected_scenario": _consistency_trace_scenario_summary(selected_scenario),
    "scenarios": scenarios,
    "attempted_scenarios": attempted_scenarios,
  }


def _build_consistency_finmo_attempts_payload(
  *,
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  attempted = [
    item for item in (solver_obj.get("attempted_scenarios") or [])
    if isinstance(item, dict)
  ]
  selected_id = str((selected_scenario or {}).get("scenario_id") or "").strip() if isinstance(selected_scenario, dict) else ""
  attempts: List[Dict[str, Any]] = []
  for attempt_index, item in enumerate(attempted, start=1):
    scenario_id = str(item.get("scenario_id") or "").strip()
    controller_request = item.get("controller_calibration_request") if isinstance(item.get("controller_calibration_request"), dict) else {}
    gpt_validation_request = item.get("gpt_validation_request") if isinstance(item.get("gpt_validation_request"), dict) else {}
    forecast_engine_state = item.get("forecast_engine_state") if isinstance(item.get("forecast_engine_state"), dict) else {}
    attempts.append(
      {
        "attempt_number": attempt_index,
        "scenario_id": scenario_id,
        "strategy_id": str(item.get("strategy_id") or "").strip(),
        "strategy_name": str(item.get("strategy_name") or "").strip(),
        "accepted": bool(selected_id and scenario_id == selected_id),
        "remaining_violations": copy.deepcopy(item.get("remaining_violations") or []),
        "remaining_blocking_violations": copy.deepcopy(item.get("remaining_blocking_violations") or []),
        "allowed_model_input_levers": copy.deepcopy(item.get("allowed_model_input_levers") or []),
        "controller_calibration_request": copy.deepcopy(controller_request),
        "gpt_validation_request": copy.deepcopy(gpt_validation_request),
        "gpt_validation_result": copy.deepcopy(item.get("gpt_validation_result") or {}),
        "model_input_json": copy.deepcopy(item.get("model_input_json") or {}),
        "finmo_json": copy.deepcopy(item.get("finmo_json") or {}),
        "forecast_status": str(forecast_engine_state.get("status") or "").strip(),
      }
    )
  return {
    "contract_version": "consistency_finmo_attempts_v1",
    "attempt_count": len(attempts),
    "selected_scenario_id": selected_id or None,
    "attempts": attempts,
  }


def _build_consistency_fidelity_trace_payload(
  *,
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  solver_obj = solver_state if isinstance(solver_state, dict) else {}
  state_model = solver_obj.get("state_model") if isinstance(solver_obj.get("state_model"), dict) else {}
  strategy_layer = state_model.get("strategy_layer") if isinstance(state_model.get("strategy_layer"), dict) else {}
  diagnosis = strategy_layer.get("diagnosis") if isinstance(strategy_layer.get("diagnosis"), dict) else {}
  strategy_selection = strategy_layer.get("strategy_selection") if isinstance(strategy_layer.get("strategy_selection"), dict) else {}
  attempted = [item for item in (solver_obj.get("attempted_scenarios") or []) if isinstance(item, dict)]
  contracts = [item for item in (solver_obj.get("attempted_contract_bundles") or []) if isinstance(item, dict)]

  def _orchestration_counts(orchestration: Any) -> Dict[str, Any]:
    obj = orchestration if isinstance(orchestration, dict) else {}
    return {
      "present": bool(obj),
      "quarter_policy_count": len([item for item in (obj.get("quarter_policies") or []) if isinstance(item, dict)]),
      "role_override_count": len([item for item in (obj.get("role_timing_overrides") or []) if isinstance(item, dict)]),
      "milestone_override_count": len([item for item in (obj.get("milestone_timing_overrides") or []) if isinstance(item, dict)]),
    }

  attempt_summaries = []
  for item in attempted:
    target = item.get("target_path_assessment") if isinstance(item.get("target_path_assessment"), dict) else {}
    attempt_summaries.append(
      {
        "strategy_id": item.get("strategy_id"),
        "strategy_source": item.get("strategy_source"),
        "presentation_issues": copy.deepcopy(item.get("presentation_issues") or []),
        "remaining_violations": copy.deepcopy(item.get("remaining_violations") or []),
        "target_path": {
          "year1_margin": target.get("year1_margin"),
          "year2_margin": target.get("year2_margin"),
          "year3_margin": target.get("year3_margin"),
          "miss_years": copy.deepcopy(target.get("miss_years") or []),
        },
        "canonical_lever_vocabulary": item.get("canonical_lever_vocabulary"),
        "allowed_model_input_levers": copy.deepcopy(item.get("allowed_model_input_levers") or []),
        "orchestration": _orchestration_counts(item.get("forecast_orchestration")),
      }
    )

  contract_summaries = []
  for bundle in contracts:
    profile = bundle.get("profile") if isinstance(bundle.get("profile"), dict) else {}
    diagnostics = bundle.get("diagnostics") if isinstance(bundle.get("diagnostics"), dict) else {}
    audit = diagnostics.get("gpt_translation_audit") if isinstance(diagnostics.get("gpt_translation_audit"), dict) else {}
    contract_summaries.append(
      {
        "strategy_id": profile.get("strategy_id") or profile.get("profile_id"),
        "strategy_source": profile.get("strategy_source"),
        "canonical_lever_vocabulary": "model_inputs_controller_write_only",
        "allowed_model_input_levers": copy.deepcopy((((bundle.get("controller_calibration_request") or {}) if isinstance(bundle.get("controller_calibration_request"), dict) else {}).get("allowed_model_input_levers") or [])),
        "diagnostic_issues": copy.deepcopy(diagnostics.get("issues") or []),
        "audit_status": audit.get("audit_status"),
        "audit_error": audit.get("error"),
        "orchestration": _orchestration_counts(profile.get("forecast_orchestration")),
      }
    )

  selected_summary = {}
  if isinstance(selected_scenario, dict):
    selected_target = selected_scenario.get("target_path_assessment") if isinstance(selected_scenario.get("target_path_assessment"), dict) else {}
    selected_summary = {
      "strategy_id": selected_scenario.get("strategy_id"),
      "strategy_source": selected_scenario.get("strategy_source"),
      "presentation_issues": copy.deepcopy(selected_scenario.get("presentation_issues") or []),
      "remaining_violations": copy.deepcopy(selected_scenario.get("remaining_violations") or []),
      "target_path": {
        "year1_margin": selected_target.get("year1_margin"),
        "year2_margin": selected_target.get("year2_margin"),
        "year3_margin": selected_target.get("year3_margin"),
        "miss_years": copy.deepcopy(selected_target.get("miss_years") or []),
      },
      "orchestration": _orchestration_counts(selected_scenario.get("forecast_orchestration")),
    }

  return {
    "contract_version": "consistency_fidelity_trace_v1",
    "solver_status": solver_obj.get("status"),
    "blocking_reason": solver_obj.get("blocking_reason"),
    "selection_mode": solver_obj.get("selection_mode"),
    "governed_attempt_count": solver_obj.get("governed_attempt_count"),
    "gpt_intent": {
      "strategy_layer_source": strategy_layer.get("source"),
      "selected_strategy_ids": copy.deepcopy(strategy_selection.get("selected_strategy_ids") or []),
      "severity_class": diagnosis.get("severity_class"),
      "minimum_package_strength": diagnosis.get("minimum_package_strength"),
      "canonical_lever_vocabulary": "model_inputs_controller_write_only",
      "target_margin_path": copy.deepcopy(diagnosis.get("target_margin_path") or {}),
      "escalation_required": diagnosis.get("escalation_required"),
      "governed_retry_attempt": diagnosis.get("governed_retry_attempt"),
    },
    "attempted_scenarios": attempt_summaries,
    "attempted_contracts": contract_summaries,
    "selected_scenario": selected_summary,
  }


def _persist_consistency_governance_artifacts(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  solver_state: Optional[Dict[str, Any]],
  selected_scenario: Optional[Dict[str, Any]],
  active_focus: str = "consistency",
  constraint_bundle: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  gpt_governance_json = _build_consistency_gpt_governance_payload(
    solver_state=solver_state,
    selected_scenario=selected_scenario,
  )
  controller_contract_json = _build_consistency_controller_contract_payload(
    solver_state=solver_state,
    selected_scenario=selected_scenario,
  )
  solver_execution_json = _build_consistency_solver_execution_payload(
    solver_state=solver_state,
    selected_scenario=selected_scenario,
  )
  finmo_attempts_json = _build_consistency_finmo_attempts_payload(
    solver_state=solver_state,
    selected_scenario=selected_scenario,
  )
  try:
    try:
      from solver_trace import trace_lazy  # type: ignore
    except Exception:
      from client_intake_and_finmo.solver_trace import trace_lazy  # type: ignore
    trace_lazy(
      "GPT_GOVERNANCE",
      "Real-time GPT governance payload",
      lambda: gpt_governance_json,
    )
    trace_lazy(
      "CONTROLLER_CONTRACT",
      "Real-time controller contract payload",
      lambda: controller_contract_json,
    )
    trace_lazy(
      "SOLVER_EXECUTION",
      "Real-time solver execution payload",
      lambda: solver_execution_json,
    )
    trace_lazy(
      "CONSISTENCY_FIDELITY",
      "Real-time GPT/controller fidelity payload",
      lambda: _build_consistency_fidelity_trace_payload(
        solver_state=solver_state,
        selected_scenario=selected_scenario,
      ),
    )
    trace_lazy(
      "FINMO_ATTEMPTS",
      "Real-time Finmo attempt payload",
      lambda: finmo_attempts_json,
    )
  except Exception:
    pass
  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    active_focus=str(active_focus or "consistency").strip() or "consistency",
    business_facts=business_facts,
    consistency_gpt_governance_json=gpt_governance_json,
    consistency_controller_contract_json=controller_contract_json,
    consistency_solver_execution_json=solver_execution_json,
    consistency_finmo_attempts_json=finmo_attempts_json,
    **_constraint_bundle_append_kwargs(constraint_bundle or {}),
  ) if hasattr(conn, "cursor") else None
  return gpt_governance_json, controller_contract_json, solver_execution_json


def _persist_and_reload_consistency_modified_state(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  consistency_modified_plan_json: Dict[str, Any],
  consistency_gpt_governance_json: Dict[str, Any],
  consistency_controller_contract_json: Dict[str, Any],
  consistency_solver_execution_json: Dict[str, Any],
  consistency_finmo_attempts_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  constraint_bundle: Optional[Dict[str, Any]] = None,
  active_focus: str = "consistency",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
  if not isinstance(consistency_modified_plan_json, dict) or not consistency_modified_plan_json:
    raise RuntimeError("consistency_modified_plan_missing")
  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    active_focus=str(active_focus or "consistency").strip() or "consistency",
    business_facts=business_facts,
    consistency_modified_plan_json=consistency_modified_plan_json,
    consistency_gpt_governance_json=consistency_gpt_governance_json,
    consistency_controller_contract_json=consistency_controller_contract_json,
    consistency_solver_execution_json=consistency_solver_execution_json,
    consistency_finmo_attempts_json=consistency_finmo_attempts_json,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    **_constraint_bundle_append_kwargs(constraint_bundle or {}),
  ) if hasattr(conn, "cursor") else None
  persisted_draft = get_draft(conn, draft_id=str(draft_id).strip())
  persisted_modified = _parse_json_value(persisted_draft.get("consistency_modified_plan_json"))
  if not isinstance(persisted_modified, dict) or not persisted_modified:
    raise RuntimeError("consistency_modified_plan_persist_failed")
  modified_plan = persisted_modified.get("modified_plan") if isinstance(persisted_modified.get("modified_plan"), dict) else {}
  if not isinstance(modified_plan, dict) or not modified_plan:
    raise RuntimeError("consistency_modified_plan_missing_modified_plan")
  quarter_driver_path = persisted_modified.get("quarter_driver_path") if isinstance(persisted_modified.get("quarter_driver_path"), list) else []
  return (
    persisted_modified,
    copy.deepcopy(modified_plan.get("operating_model") or {}),
    copy.deepcopy(modified_plan.get("target_market") or {}),
    copy.deepcopy(modified_plan.get("people") or {}),
    copy.deepcopy(modified_plan.get("financials") or {}),
    copy.deepcopy(modified_plan.get("financials_year1") or {}),
    copy.deepcopy(modified_plan.get("marketing_model") or {}),
    [copy.deepcopy(item) for item in quarter_driver_path if isinstance(item, dict)],
  )


def _initialize_consistency_finmo_baseline(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  try:
    try:
      from finmo_bridge import sync_consistency_state_to_finmo  # type: ignore
    except Exception:
      from client_intake_and_finmo.finmo_bridge import sync_consistency_state_to_finmo  # type: ignore
  except Exception:
    return {}, {}

  try:
    finmo_path = ensure_draft_finmo_workbook(conn, draft_id=str(draft_id).strip())
  except Exception:
    finmo_path = None
  if not finmo_path:
    try:
      finmo_path = str((get_draft(conn, draft_id=str(draft_id).strip()) or {}).get("finmo_path") or "").strip()
    except Exception:
      finmo_path = ""
  if not finmo_path:
    return {}, {}

  try:
    result = sync_consistency_state_to_finmo(
      finmo_path=finmo_path,
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
  except Exception:
    return {}, {}

  model_input_json = result.get("model_input_json") if isinstance(result.get("model_input_json"), dict) else {}
  finmo_json = result.get("finmo_json") if isinstance(result.get("finmo_json"), dict) else {}
  if model_input_json or finmo_json:
    append_messages(
      conn,
      draft_id=str(draft_id).strip(),
      new_messages=[],
      active_focus="consistency",
      business_facts=business_facts,
      model_input_json=model_input_json if model_input_json else None,
      finmo_json=finmo_json if finmo_json else None,
    )
    try:
      try:
        from solver_trace import trace_lazy  # type: ignore
      except Exception:
        from client_intake_and_finmo.solver_trace import trace_lazy  # type: ignore
      trace_lazy("FINMO_BASELINE", "Consistency baseline Finmo payload", lambda: {
        "finmo_path": finmo_path,
        "model_input_json": model_input_json,
        "finmo_json": finmo_json,
      })
    except Exception:
      pass
  return model_input_json, finmo_json


def _sync_consistency_finmo_artifacts(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  controller_input_seed: Optional[List[Dict[str, Any]]],
  modified_forecast_quarters: Optional[List[Dict[str, Any]]],
  selected_scenario: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  try:
    try:
      from finmo_bridge import sync_consistency_state_to_finmo  # type: ignore
    except Exception:
      from client_intake_and_finmo.finmo_bridge import sync_consistency_state_to_finmo  # type: ignore
  except Exception:
    return {}, {}

  try:
    draft_row = get_draft(conn, draft_id=str(draft_id).strip())
  except Exception:
    return {}, {}
  finmo_path = str(draft_row.get("finmo_path") or "").strip()
  if not finmo_path:
    return {}, {}
  calibration_spec = (
    (selected_scenario.get("controller_calibration_request") if isinstance(selected_scenario.get("controller_calibration_request"), dict) else {})
    or (selected_scenario.get("finmo_calibration_spec") if isinstance(selected_scenario, dict) else {})
  ) if isinstance(selected_scenario, dict) else {}
  try:
    result = sync_consistency_state_to_finmo(
      finmo_path=finmo_path,
      business_facts=business_facts,
      ops_json=ops_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      marketing_model_json=marketing_model_json,
      controller_input_seed=controller_input_seed or [],
      forecast_quarters=modified_forecast_quarters or [],
      calibration_spec=calibration_spec,
    )
  except Exception:
    return {}, {}
  model_input_json = result.get("model_input_json") if isinstance(result.get("model_input_json"), dict) else {}
  finmo_json = result.get("finmo_json") if isinstance(result.get("finmo_json"), dict) else {}
  return model_input_json, finmo_json


def _best_attempted_consistency_candidate(solver_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  attempted = [
    item for item in ((solver_state or {}).get("attempted_scenarios") or [])
    if isinstance(item, dict)
  ]
  if not attempted:
    attempted = [
      item for item in ((solver_state or {}).get("scenarios") or [])
      if isinstance(item, dict)
    ]
  if not attempted:
    return {}
  ranked = sorted(
    attempted,
    key=lambda item: (
      int(max(0, _safe_int(item.get("remaining_blocking_count")) or 0)),
      int(max(0, _safe_int(item.get("remaining_violation_count")) or 0)),
      len(item.get("presentation_issues") or []),
      -1.0 * (_safe_float((((item.get("forecast_years") or [None])[0]) or {}).get("ebitda")) or 0.0),
    ),
  )
  best = ranked[0] if ranked else {}
  return best if isinstance(best, dict) else {}


def _run_consistency_closeout(
  *,
  conn,
  client_id: str,
  draft_id: str,
  business_facts: Dict[str, Any],
  business_stage_hint: Optional[str],
  current_date_iso: str,
  shared_context: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  try:
    persisted_draft = get_draft(conn, draft_id=str(draft_id).strip())
  except Exception:
    persisted_draft = {}
  baseline_model_input_json, baseline_finmo_json = _initialize_consistency_finmo_baseline(
    conn=conn,
    draft_id=str(draft_id).strip(),
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
  )
  if baseline_model_input_json:
    shared_context = dict(shared_context or {})
    shared_context["model_input_json"] = copy.deepcopy(baseline_model_input_json)
  if baseline_finmo_json:
    shared_context = dict(shared_context or {})
    shared_context["finmo_json"] = copy.deepcopy(baseline_finmo_json)
  if not persisted_draft:
    try:
      persisted_draft = get_draft(conn, draft_id=str(draft_id).strip())
    except Exception:
      persisted_draft = {}
  initial_ops_json = copy.deepcopy(ops_json if isinstance(ops_json, dict) else {})
  initial_market_json = copy.deepcopy(market_json if isinstance(market_json, dict) else {})
  initial_people_json = copy.deepcopy(people_json if isinstance(people_json, dict) else {})
  initial_financials_json = copy.deepcopy(financials_json if isinstance(financials_json, dict) else {})
  initial_financials_year1_json = copy.deepcopy(
    financials_year1_json if isinstance(financials_year1_json, dict) else {}
  )
  initial_marketing_model_json = copy.deepcopy(
    marketing_model_json if isinstance(marketing_model_json, dict) else {}
  )
  initial_table_markdown = _build_consistency_initial_table(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  consistency_runtime_context = _build_consistency_runtime_context(
    client_id=client_id,
    draft_id=str(draft_id).strip(),
    finmo_path=str((persisted_draft or {}).get("finmo_path") or "").strip(),
    business_facts=business_facts,
    business_stage_hint=business_stage_hint,
    current_date_iso=current_date_iso,
    shared_context=shared_context,
    ops_json=ops_json,
    market_json=market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
  )
  solver_state, constraint_bundle = _start_consistency_solver_if_needed(
    intake_context=consistency_runtime_context,
    ops_json=ops_json,
    market_json=market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
  )
  gpt_governance_json: Dict[str, Any] = {}
  controller_contract_json: Dict[str, Any] = {}
  solver_execution_json: Dict[str, Any] = {}
  finmo_attempts_json: Dict[str, Any] = {}
  if isinstance(solver_state, dict):
    gpt_governance_json, controller_contract_json, solver_execution_json = _persist_consistency_governance_artifacts(
      conn=conn,
      draft_id=str(draft_id).strip(),
      business_facts=business_facts,
      solver_state=solver_state,
      selected_scenario=None,
      active_focus="consistency",
      constraint_bundle=constraint_bundle,
    )
    finmo_attempts_json = _build_consistency_finmo_attempts_payload(
      solver_state=solver_state,
      selected_scenario=None,
    )
  selected_scenario: Optional[Dict[str, Any]] = None
  modified_forecast_quarters: List[Dict[str, Any]] = []
  updated_shared_context = dict(shared_context or {})
  updated_ops_json = dict(ops_json or {})
  updated_market_json = dict(market_json or {})
  updated_people_json = dict(people_json or {})
  updated_financials_json = _clear_consistency_solver_state(financials_json)
  updated_financials_year1_json = dict(financials_year1_json or {})
  updated_marketing_model_json = dict(marketing_model_json or {})
  consistency_modified_plan_json: Dict[str, Any] = {}
  model_input_json: Dict[str, Any] = copy.deepcopy(baseline_model_input_json if isinstance(baseline_model_input_json, dict) else {})
  finmo_json: Dict[str, Any] = copy.deepcopy(baseline_finmo_json if isinstance(baseline_finmo_json, dict) else {})

  if isinstance(solver_state, dict) and (solver_state.get("scenarios") or []):
    selected_scenario_id = str((((solver_state.get("scenarios") or [])[0]) or {}).get("scenario_id") or "1").strip() or "1"
    applied_solver = _apply_consistency_solver_choice(
      selected_scenario_id=selected_scenario_id,
      overrides={},
      ops_json=updated_ops_json,
      market_json=updated_market_json,
      people_json=updated_people_json,
      financials_json=updated_financials_json,
      financials_year1_json=updated_financials_year1_json,
      marketing_model_json=updated_marketing_model_json,
      solver_state_override=solver_state,
    )
    if applied_solver:
      updated_ops_json = dict(applied_solver.get("ops_json") or updated_ops_json)
      updated_people_json = _sync_people_state_after_consistency(
        people_json=dict(applied_solver.get("people_json") or updated_people_json)
      )
      updated_financials_json = _clear_consistency_solver_state(
        dict(applied_solver.get("financials_json") or updated_financials_json)
      )
      updated_financials_year1_json = dict(
        applied_solver.get("financials_year1_json") or updated_financials_year1_json
      )
      updated_marketing_model_json = dict(
        applied_solver.get("marketing_model_json") or updated_marketing_model_json
      )
      selected_scenario = applied_solver.get("scenario") if isinstance(applied_solver, dict) else {}

      updated_shared_context["operating_model"] = updated_ops_json
      updated_shared_context["target_market"] = updated_market_json
      updated_shared_context["people_capability"] = updated_people_json
      updated_shared_context["financials"] = updated_financials_json
      updated_shared_context["financials_year1"] = updated_financials_year1_json
      updated_shared_context["target_market"] = updated_market_json
      updated_shared_context["marketing"] = updated_marketing_model_json
      modified_forecast_quarters = [
        q for q in (
          (selected_scenario or {}).get("forecast_quarters")
          or constraint_bundle.get("forecast_quarters")
          or []
        )
        if isinstance(q, dict)
      ]
      if isinstance(solver_state, dict):
        gpt_governance_json, controller_contract_json, solver_execution_json = _persist_consistency_governance_artifacts(
          conn=conn,
          draft_id=str(draft_id).strip(),
          business_facts=business_facts,
          solver_state=solver_state,
          selected_scenario=selected_scenario,
          active_focus="consistency",
          constraint_bundle=constraint_bundle,
        )
        finmo_attempts_json = _build_consistency_finmo_attempts_payload(
          solver_state=solver_state,
          selected_scenario=selected_scenario,
        )
      model_input_json, finmo_json = _sync_consistency_finmo_artifacts(
        conn=conn,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        ops_json=updated_ops_json,
        people_json=updated_people_json,
        financials_json=updated_financials_json,
        financials_year1_json=updated_financials_year1_json,
        marketing_model_json=updated_marketing_model_json,
        controller_input_seed=[
          item for item in (((selected_scenario or {}).get("controller_input_seed") or []))
          if isinstance(item, dict)
        ],
        modified_forecast_quarters=modified_forecast_quarters,
        selected_scenario=selected_scenario if isinstance(selected_scenario, dict) else None,
      )
      finmo_quarter_driver_path, _finmo_forecast_years = _build_consistency_forecast_view_from_finmo_safe(finmo_json)
      if finmo_quarter_driver_path:
        modified_forecast_quarters = finmo_quarter_driver_path
      consistency_modified_plan_json = _build_consistency_modified_plan_payload(
        solver_state=solver_state,
        selected_scenario=selected_scenario,
        constraint_bundle=constraint_bundle,
        initial_ops_json=initial_ops_json,
        initial_market_json=initial_market_json,
        initial_people_json=initial_people_json,
        initial_financials_json=initial_financials_json,
        initial_financials_year1_json=initial_financials_year1_json,
        initial_marketing_model_json=initial_marketing_model_json,
        modified_ops_json=updated_ops_json,
        modified_market_json=updated_market_json,
        modified_people_json=updated_people_json,
        modified_financials_json=updated_financials_json,
        modified_financials_year1_json=updated_financials_year1_json,
        modified_marketing_model_json=updated_marketing_model_json,
        modified_forecast_quarters=modified_forecast_quarters,
        finmo_json=finmo_json,
      )
      consistency_modified_plan_json["resolution_summary"] = _build_violation_resolution_summary(
        solver_state=solver_state,
        selected_scenario=selected_scenario,
        constraint_bundle=constraint_bundle,
        modified_forecast_quarters=modified_forecast_quarters,
      )
      (
        consistency_modified_plan_json,
        updated_ops_json,
        updated_market_json,
        updated_people_json,
        updated_financials_json,
        updated_financials_year1_json,
        updated_marketing_model_json,
        modified_forecast_quarters,
      ) = _persist_and_reload_consistency_modified_state(
        conn=conn,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        consistency_modified_plan_json=consistency_modified_plan_json,
        consistency_gpt_governance_json=gpt_governance_json,
        consistency_controller_contract_json=controller_contract_json,
        consistency_solver_execution_json=solver_execution_json,
        consistency_finmo_attempts_json=finmo_attempts_json,
        model_input_json=model_input_json,
        finmo_json=finmo_json,
        constraint_bundle=constraint_bundle,
        active_focus="consistency",
      )
      if not isinstance(consistency_modified_plan_json.get("resolution_summary"), dict) or not consistency_modified_plan_json.get("resolution_summary"):
        consistency_modified_plan_json["resolution_summary"] = _build_violation_resolution_summary(
          solver_state=solver_state,
          selected_scenario=selected_scenario,
          constraint_bundle=constraint_bundle,
          modified_forecast_quarters=modified_forecast_quarters,
        )

  if (
    isinstance(solver_state, dict)
    and not isinstance(selected_scenario, dict)
    and str(solver_state.get("status") or "").strip() != "blocking_unresolved"
  ):
    raise RuntimeError("consistency_governed_scenario_missing")

  if (
    isinstance(solver_state, dict)
    and str(solver_state.get("status") or "").strip() == "blocking_unresolved"
    and not isinstance(selected_scenario, dict)
  ):
    attempted_candidate = _best_attempted_consistency_candidate(solver_state)
    attempted_modified_state = (
      (attempted_candidate.get("modified_state") or {})
      if isinstance(attempted_candidate.get("modified_state"), dict) else {}
    )
    attempted_forecast_quarters = [
      item for item in ((attempted_candidate.get("forecast_quarters") or []))
      if isinstance(item, dict)
    ] if isinstance(attempted_candidate, dict) else []
    if attempted_candidate:
      model_input_json, finmo_json = _sync_consistency_finmo_artifacts(
        conn=conn,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        ops_json=(attempted_modified_state.get("ops_json") if isinstance(attempted_modified_state.get("ops_json"), dict) else updated_ops_json),
        people_json=(attempted_modified_state.get("people_json") if isinstance(attempted_modified_state.get("people_json"), dict) else updated_people_json),
        financials_json=(attempted_modified_state.get("financials_json") if isinstance(attempted_modified_state.get("financials_json"), dict) else updated_financials_json),
        financials_year1_json=(attempted_modified_state.get("financials_year1_json") if isinstance(attempted_modified_state.get("financials_year1_json"), dict) else updated_financials_year1_json),
        marketing_model_json=(attempted_modified_state.get("marketing_model_json") if isinstance(attempted_modified_state.get("marketing_model_json"), dict) else updated_marketing_model_json),
        controller_input_seed=[
          item for item in ((attempted_candidate.get("controller_input_seed") or []))
          if isinstance(item, dict)
        ],
        modified_forecast_quarters=attempted_forecast_quarters,
        selected_scenario=attempted_candidate,
      )
      finmo_quarter_driver_path, _finmo_forecast_years = _build_consistency_forecast_view_from_finmo_safe(finmo_json)
      if finmo_quarter_driver_path:
        attempted_forecast_quarters = finmo_quarter_driver_path
      consistency_modified_plan_json = _build_consistency_modified_plan_payload(
        solver_state=solver_state,
        selected_scenario=attempted_candidate,
        constraint_bundle=constraint_bundle,
        initial_ops_json=initial_ops_json,
        initial_market_json=initial_market_json,
        initial_people_json=initial_people_json,
        initial_financials_json=initial_financials_json,
        initial_financials_year1_json=initial_financials_year1_json,
        initial_marketing_model_json=initial_marketing_model_json,
        modified_ops_json=(attempted_modified_state.get("ops_json") if isinstance(attempted_modified_state.get("ops_json"), dict) else updated_ops_json),
        modified_market_json=updated_market_json,
        modified_people_json=(attempted_modified_state.get("people_json") if isinstance(attempted_modified_state.get("people_json"), dict) else updated_people_json),
        modified_financials_json=(attempted_modified_state.get("financials_json") if isinstance(attempted_modified_state.get("financials_json"), dict) else updated_financials_json),
        modified_financials_year1_json=(attempted_modified_state.get("financials_year1_json") if isinstance(attempted_modified_state.get("financials_year1_json"), dict) else updated_financials_year1_json),
        modified_marketing_model_json=(attempted_modified_state.get("marketing_model_json") if isinstance(attempted_modified_state.get("marketing_model_json"), dict) else updated_marketing_model_json),
        modified_forecast_quarters=attempted_forecast_quarters,
        finmo_json=finmo_json,
      )
      consistency_modified_plan_json["resolution_summary"] = _build_violation_resolution_summary(
        solver_state=solver_state,
        selected_scenario=attempted_candidate,
        constraint_bundle=constraint_bundle,
        modified_forecast_quarters=attempted_forecast_quarters,
      )
      (
        consistency_modified_plan_json,
        updated_ops_json,
        updated_market_json,
        updated_people_json,
        updated_financials_json,
        updated_financials_year1_json,
        updated_marketing_model_json,
        attempted_forecast_quarters,
      ) = _persist_and_reload_consistency_modified_state(
        conn=conn,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        consistency_modified_plan_json=consistency_modified_plan_json,
        consistency_gpt_governance_json=gpt_governance_json,
        consistency_controller_contract_json=controller_contract_json,
        consistency_solver_execution_json=solver_execution_json,
        consistency_finmo_attempts_json=finmo_attempts_json,
        model_input_json=model_input_json,
        finmo_json=finmo_json,
        constraint_bundle=constraint_bundle,
        active_focus="consistency",
      )
    resolution_summary = _build_violation_resolution_summary(
      solver_state=solver_state,
      selected_scenario=attempted_candidate if isinstance(attempted_candidate, dict) else selected_scenario,
      constraint_bundle=constraint_bundle,
      modified_forecast_quarters=attempted_forecast_quarters or modified_forecast_quarters,
    )
    try:
      try:
        from solver_trace import trace_lazy  # type: ignore
      except Exception:
        from client_intake_and_finmo.solver_trace import trace_lazy  # type: ignore
      trace_lazy(
        "GPT_GOVERNANCE",
        "Consistency GPT governance payload",
        lambda: gpt_governance_json,
      )
      trace_lazy(
        "CONTROLLER_CONTRACT",
        "Consistency controller contract payload",
        lambda: controller_contract_json,
      )
      trace_lazy(
        "SOLVER_EXECUTION",
        "Consistency solver execution payload",
        lambda: solver_execution_json,
      )
      trace_lazy(
        "CONSISTENCY_FIDELITY",
        "Consistency GPT/controller fidelity payload",
        lambda: _build_consistency_fidelity_trace_payload(
          solver_state=solver_state,
          selected_scenario=selected_scenario,
        ),
      )
      trace_lazy(
        "CONSISTENCY",
        "Violation resolution summary",
        lambda: resolution_summary,
      )
      trace_lazy(
        "MODEL_INPUT",
        "Current Model Inputs workbook payload",
        lambda: model_input_json,
      )
      trace_lazy(
        "FINMO",
        "Current Financial Model QTR workbook payload",
        lambda: finmo_json,
      )
      trace_lazy(
        "FINMO_ATTEMPTS",
        "Consistency Finmo attempt payload",
        lambda: finmo_attempts_json,
      )
    except Exception:
      pass
    updated_shared_context["consistency_gpt_governance"] = gpt_governance_json
    updated_shared_context["consistency_controller_contract"] = controller_contract_json
    updated_shared_context["consistency_solver_execution"] = solver_execution_json
    updated_shared_context["consistency_resolution_summary"] = resolution_summary
    updated_shared_context["consistency_modified_plan"] = consistency_modified_plan_json
    updated_shared_context["model_input_json"] = model_input_json
    updated_shared_context["finmo_json"] = finmo_json
    updated_shared_context["consistency_finmo_attempts"] = finmo_attempts_json
    return {
      "assistant_text": _build_consistency_provisional_message(
        solver_state=solver_state,
        attempted_scenario=attempted_candidate,
        initial_table_markdown=initial_table_markdown,
        modified_forecast_quarters=attempted_forecast_quarters,
        finmo_json=finmo_json,
      ),
      "solver_state": solver_state,
      "selected_scenario": selected_scenario,
      "constraint_bundle": constraint_bundle,
      "shared_context": updated_shared_context,
      "ops_json": updated_ops_json,
      "market_json": updated_market_json,
      "people_json": updated_people_json,
      "financials_json": updated_financials_json,
      "financials_year1_json": updated_financials_year1_json,
      "marketing_model_json": updated_marketing_model_json,
      "consistency_modified_plan_json": consistency_modified_plan_json,
      "consistency_gpt_governance_json": gpt_governance_json,
      "consistency_controller_contract_json": controller_contract_json,
      "consistency_solver_execution_json": solver_execution_json,
      "consistency_finmo_attempts_json": finmo_attempts_json,
      "model_input_json": model_input_json,
      "finmo_json": finmo_json,
    }

  if not consistency_modified_plan_json:
    consistency_modified_plan_json = _build_consistency_modified_plan_payload(
      solver_state=solver_state,
      selected_scenario=selected_scenario,
      constraint_bundle=constraint_bundle,
      initial_ops_json=initial_ops_json,
      initial_market_json=initial_market_json,
      initial_people_json=initial_people_json,
      initial_financials_json=initial_financials_json,
      initial_financials_year1_json=initial_financials_year1_json,
      initial_marketing_model_json=initial_marketing_model_json,
      modified_ops_json=updated_ops_json,
      modified_market_json=updated_market_json,
      modified_people_json=updated_people_json,
      modified_financials_json=updated_financials_json,
      modified_financials_year1_json=updated_financials_year1_json,
      modified_marketing_model_json=updated_marketing_model_json,
      modified_forecast_quarters=modified_forecast_quarters,
      finmo_json=finmo_json,
    )
    consistency_modified_plan_json["resolution_summary"] = _build_violation_resolution_summary(
      solver_state=solver_state,
      selected_scenario=selected_scenario,
      constraint_bundle=constraint_bundle,
      modified_forecast_quarters=modified_forecast_quarters,
    )
  resolution_summary = consistency_modified_plan_json.get("resolution_summary") if isinstance(consistency_modified_plan_json.get("resolution_summary"), dict) else _build_violation_resolution_summary(
    solver_state=solver_state,
    selected_scenario=selected_scenario,
    constraint_bundle=constraint_bundle,
    modified_forecast_quarters=modified_forecast_quarters,
  )
  try:
    try:
      from solver_trace import trace_lazy  # type: ignore
    except Exception:
      from client_intake_and_finmo.solver_trace import trace_lazy  # type: ignore
    trace_lazy(
      "MODIFIED_PLAN",
      "Consistency modified plan payload",
      lambda: consistency_modified_plan_json,
    )
    trace_lazy(
      "GPT_GOVERNANCE",
      "Consistency GPT governance payload",
      lambda: gpt_governance_json,
    )
    trace_lazy(
      "CONTROLLER_CONTRACT",
      "Consistency controller contract payload",
      lambda: controller_contract_json,
    )
    trace_lazy(
      "SOLVER_EXECUTION",
      "Consistency solver execution payload",
      lambda: solver_execution_json,
    )
    trace_lazy(
      "CONSISTENCY_FIDELITY",
      "Consistency GPT/controller fidelity payload",
      lambda: _build_consistency_fidelity_trace_payload(
        solver_state=solver_state,
        selected_scenario=selected_scenario,
      ),
    )
    trace_lazy(
      "CONSISTENCY",
      "Violation resolution summary",
      lambda: resolution_summary,
    )
    trace_lazy(
      "MODEL_INPUT",
      "Current Model Inputs workbook payload",
      lambda: model_input_json,
    )
    trace_lazy(
      "FINMO",
      "Current Financial Model QTR workbook payload",
      lambda: finmo_json,
    )
    trace_lazy(
      "FINMO_ATTEMPTS",
      "Consistency Finmo attempt payload",
      lambda: finmo_attempts_json,
    )
  except Exception:
    pass
  updated_shared_context["consistency_modified_plan"] = consistency_modified_plan_json
  updated_shared_context["consistency_gpt_governance"] = gpt_governance_json
  updated_shared_context["consistency_controller_contract"] = controller_contract_json
  updated_shared_context["consistency_solver_execution"] = solver_execution_json
  updated_shared_context["model_input_json"] = model_input_json
  updated_shared_context["finmo_json"] = finmo_json
  updated_shared_context["consistency_finmo_attempts"] = finmo_attempts_json

  assistant_text = _build_consistency_finalized_message(
    solver_state=solver_state,
    selected_scenario=selected_scenario,
    initial_table_markdown=initial_table_markdown,
    modified_forecast_quarters=modified_forecast_quarters,
    finmo_json=finmo_json,
  )
  return {
    "assistant_text": assistant_text,
    "solver_state": solver_state,
    "selected_scenario": selected_scenario,
    "constraint_bundle": constraint_bundle,
    "shared_context": updated_shared_context,
    "ops_json": updated_ops_json,
    "market_json": updated_market_json,
    "people_json": updated_people_json,
    "financials_json": updated_financials_json,
    "financials_year1_json": updated_financials_year1_json,
    "marketing_model_json": updated_marketing_model_json,
    "consistency_modified_plan_json": consistency_modified_plan_json,
    "consistency_gpt_governance_json": gpt_governance_json,
    "consistency_controller_contract_json": controller_contract_json,
    "consistency_solver_execution_json": solver_execution_json,
    "consistency_finmo_attempts_json": finmo_attempts_json,
    "model_input_json": model_input_json,
    "finmo_json": finmo_json,
  }


def _financials_ready_for_consistency(
  financials_json: Dict[str, Any],
  *,
  guardrail_triggered: bool = False,
) -> bool:
  return (not guardrail_triggered) and _next_financials_stage(financials_json) is None


def _build_financials_completion_turn(*, acknowledgement: str = "") -> Dict[str, Any]:
  message = "Thanks. I have everything I need for financials, and I’m moving into the consistency pass now."
  if str(acknowledgement or "").strip():
    message = f"{str(acknowledgement).strip()}\n\n{message}".strip()
  return {
    "assistant_message": message,
    "finalize_ready": False,
    "transition_to_consistency": True,
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
  financials_chat_turn,
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
    next_turn = financials_chat_turn(
      intake_context=next_context,
      conversation_messages=conversation_messages,
    ) or {}
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


def _maybe_run_consistency_closeout(
  *,
  focus_hint: Optional[str],
  guardrail_triggered: bool,
  conn,
  client_id: str,
  draft_id: str,
  business_facts: Dict[str, Any],
  business_stage_hint: Optional[str],
  current_date_iso: str,
  shared_context: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  focus_normalized = str(focus_hint or "").strip().lower()
  if focus_normalized != "consistency":
    return None
  return _run_consistency_closeout(
    conn=conn,
    client_id=client_id,
    draft_id=draft_id,
    business_facts=business_facts,
    business_stage_hint=business_stage_hint,
    current_date_iso=current_date_iso,
    shared_context=shared_context,
    ops_json=ops_json,
    market_json=market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
  )


def _start_consistency_solver_if_needed(
  *,
  intake_context: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
  try:
    try:
      from solver_trace import trace_lazy  # type: ignore
    except Exception:
      from client_intake_and_finmo.solver_trace import trace_lazy  # type: ignore
  except Exception:
    trace_lazy = None  # type: ignore
  constraint_bundle: Dict[str, Any] = _build_constraint_bundle_for_persistence(
    intake_context=intake_context,
    ops_json=ops_json,
    market_json=market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
  )
  if isinstance(intake_context, dict):
    intake_context["shared_context"] = _refresh_shared_forecast_context(
      intake_context.get("shared_context") if isinstance(intake_context, dict) else {},
      constraint_bundle,
    )

  try:
    try:
      from consistency_solver import build_consistency_solver_state  # type: ignore
    except Exception:
      from client_intake_and_finmo.consistency_solver import build_consistency_solver_state  # type: ignore
  except Exception:
    return None, constraint_bundle

  solver_state = build_consistency_solver_state(
    ops_json=ops_json,
    target_market_json=market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=(intake_context.get("fulfillment_json") if isinstance(intake_context, dict) else {}),
    marketing_model_json=marketing_model_json,
    normalized_traits=(
      constraint_bundle.get("normalized_traits") if isinstance(constraint_bundle, dict) else None
    ),
    benchmark_payload=(
      constraint_bundle.get("benchmark_payload") if isinstance(constraint_bundle, dict) else None
    ),
    constraint_engine_state=(
      constraint_bundle.get("constraint_engine_state") if isinstance(constraint_bundle, dict) else None
    ),
    finmo_path=str((intake_context or {}).get("finmo_path") or "").strip(),
    business_facts={
      "name": (intake_context or {}).get("business_name"),
      "start_date": (intake_context or {}).get("business_start_date"),
      "address": (intake_context or {}).get("address"),
    },
    model_input_json=(
      ((intake_context.get("shared_context") or {}) if isinstance(intake_context.get("shared_context"), dict) else {}).get("model_input_json")
      if isinstance(intake_context, dict) else None
    ),
    finmo_json=(
      ((intake_context.get("shared_context") or {}) if isinstance(intake_context.get("shared_context"), dict) else {}).get("finmo_json")
      if isinstance(intake_context, dict) else None
    ),
  )
  if not isinstance(solver_state, dict):
    return None, constraint_bundle

  if trace_lazy:
    trace_lazy(
      "FINAL",
      "Solver state built",
      lambda: {
        "status": solver_state.get("status"),
        "solve_mode": solver_state.get("solve_mode"),
        "blocking_reason": solver_state.get("blocking_reason"),
        "blocking_violations": solver_state.get("blocking_violations") or [],
        "baseline_summary": solver_state.get("baseline_summary") or {},
        "baseline_realism_distance": solver_state.get("baseline_realism_distance"),
        "selected_target_label": solver_state.get("selected_target_label"),
        "selected_target_ebitda_min": solver_state.get("selected_target_ebitda_min"),
        "selected_target_ebitda_max": solver_state.get("selected_target_ebitda_max"),
        "scenario_count": len(solver_state.get("scenarios") or []),
        "client_scenario_count": len(solver_state.get("client_scenarios") or []),
      },
    )

  return solver_state, constraint_bundle


def _apply_consistency_solver_choice(
  *,
  selected_scenario_id: str,
  overrides: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  solver_state_override: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  solver_state = solver_state_override if isinstance(solver_state_override, dict) else _get_pending_consistency_solver_state(financials_json)
  if not solver_state:
    return None

  try:
    try:
      from consistency_solver import apply_consistency_solver_choice  # type: ignore
    except Exception:
      from client_intake_and_finmo.consistency_solver import apply_consistency_solver_choice  # type: ignore
  except Exception:
    return None

  base_financials = dict(financials_json or {})
  base_financials.pop("_consistency_solver_state", None)

  applied = apply_consistency_solver_choice(
    ops_json=ops_json,
    people_json=people_json,
    financials_json=base_financials,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    solver_state=solver_state,
    selected_scenario_id=selected_scenario_id,
    overrides=overrides,
  )
  if not isinstance(applied, dict):
    return None

  next_ops = dict(applied.get("ops_json") or ops_json)
  next_people = dict(applied.get("people_json") or people_json)
  next_financials = dict(applied.get("financials_json") or base_financials)
  next_year1 = dict(applied.get("financials_year1_json") or financials_year1_json)
  next_marketing_model = dict(applied.get("marketing_model_json") or marketing_model_json)

  try:
    updated_consults, propagated = propagate_shared_facts(
      source_consult_type="financials_year1",
      before_json=financials_year1_json,
      after_json=next_year1,
      consult_jsons={
        "ops": next_ops,
        "target_market": market_json,
        "people": next_people,
        "financials": next_financials,
        "financials_year1": next_year1,
      },
    )
    next_ops = updated_consults.get("ops") or next_ops
    next_people = updated_consults.get("people") or next_people
    next_financials = updated_consults.get("financials") or next_financials
    next_year1 = updated_consults.get("financials_year1") or next_year1
    if propagated:
      pass
  except Exception:
    pass

  next_financials = _sync_marketing_field_family(
    financials_json=next_financials,
    financials_year1_json=next_year1,
    marketing_model_json=next_marketing_model,
  )
  next_financials.pop("_consistency_solver_state", None)
  return {
    "ops_json": next_ops,
    "people_json": next_people,
    "financials_json": next_financials,
    "financials_year1_json": next_year1,
    "marketing_model_json": next_marketing_model,
    "scenario": applied.get("scenario") if isinstance(applied, dict) else None,
    "exact_patches": applied.get("exact_patches") if isinstance(applied, dict) else None,
  }


def _sync_people_state_after_consistency(
  *,
  people_json: Dict[str, Any],
) -> Dict[str, Any]:
  next_people = dict(people_json or {})
  try:
    from people_roles import format_roles_summary  # type: ignore
  except Exception:
    return next_people
  roles = next_people.get("inferred_roles")
  roles = roles if isinstance(roles, list) else []
  try:
    next_people["inferred_roles_summary"] = format_roles_summary(roles)
  except Exception:
    pass
  return next_people


def _sync_marketing_state_after_consistency(
  *,
  intake_context: Dict[str, Any],
  market_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  scenario_context: Optional[Dict[str, Any]] = None,
  rewrite_narrative: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  del intake_context, scenario_context, rewrite_narrative
  next_market = dict(market_json or {})
  next_marketing_model = dict(marketing_model_json or {})

  for key in (
    "marketing_total_year1",
    "marketing_percent_of_revenue",
    "baseline_marketing",
    "baseline_marketing_percent",
    "marketing_adjustment",
  ):
    if (financials_json or {}).get(key) is not None:
      next_marketing_model[key] = (financials_json or {}).get(key)

  return next_market, next_marketing_model


def _build_cogs_baseline_message(cogs_baseline: Dict[str, Any]) -> str:
  return (
    f"A reasonable Year-1 COGS baseline is about "
    f"{_format_percent(cogs_baseline.get('baseline_cogs_percent'))} of revenue, which puts your projected Year-1 direct costs around "
    f"{_format_currency(cogs_baseline.get('baseline_cogs'))}.\n\n"
    "Does that broadly match how your business works, or should we adjust it because your direct costs are materially different?"
  )


def _build_cogs_adjustment_acknowledgement(cogs_fields: Dict[str, Any]) -> str:
  total = _format_currency(cogs_fields.get("cogs_total_year1"))
  revenue = float(cogs_fields.get("revenue_year1") or 0.0)
  try:
    percent_value = (
      float(cogs_fields.get("cogs_total_year1") or 0.0) / revenue if revenue > 0 else float(cogs_fields.get("baseline_cogs_percent") or 0.0)
    )
  except Exception:
    percent_value = float(cogs_fields.get("baseline_cogs_percent") or 0.0)
  return (
    f"Got it - I'll use Year-1 direct costs of "
    f"{total} "
    f"({_format_percent(percent_value)} of revenue)."
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


def _build_payroll_adjustment_acknowledgement(payroll_fields: Dict[str, Any]) -> str:
  return (
    f"Got it - I'll use Year-1 payroll of "
    f"{_format_currency(payroll_fields.get('payroll_total_year1'))}."
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
    return base_model
  if market_basis_type == "b2b" and not has_b2b:
    base_model["missing_dependencies"] = ["b2b_market_basis"]
    return base_model
  if market_basis_type == "mixed" and not (has_b2c or has_b2b):
    base_model["missing_dependencies"] = ["market_basis"]
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


def _build_marketing_adjustment_acknowledgement(marketing_fields: Dict[str, Any]) -> str:
  return (
    f"Got it - I'll use a Year-1 marketing budget of "
    f"{_format_currency(marketing_fields.get('marketing_total_year1'))} "
    f"({_format_percent(marketing_fields.get('marketing_percent_of_revenue'))} of revenue)."
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

def _normalize_payroll_reply_to_fields(
  *,
  reply: Dict[str, Any],
  baseline: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  baseline_amount = float(baseline.get("baseline_payroll_year1") or 0.0)
  intent_type = str(reply.get("intent_type") or "").strip()

  if intent_type == "accept_baseline":
    total = baseline_amount
  elif intent_type == "set_total":
    try:
      total = float(reply.get("payroll_total_year1"))
    except Exception:
      return None
  elif intent_type == "set_adjustment":
    try:
      adjustment = float(reply.get("payroll_adjustment"))
    except Exception:
      return None
    total = baseline_amount + adjustment
  else:
    return None

  total = max(0.0, float(total))
  adjustment = float(total - baseline_amount)
  return {
    "baseline_payroll_year1": baseline_amount,
    "payroll_adjustment": adjustment,
    "payroll_total_year1": total,
    "payroll_basis_people_roles": baseline.get("payroll_basis_people_roles") or [],
    "current_payroll": total,
  }


def _normalize_cogs_reply_to_fields(
  *,
  reply: Dict[str, Any],
  baseline: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  baseline_amount = float(baseline.get("baseline_cogs") or 0.0)
  revenue_year1 = float(baseline.get("revenue_year1") or 0.0)
  baseline_percent = float(baseline.get("baseline_cogs_percent") or 0.0)
  years_used = baseline.get("cogs_basis_years_used")
  intent_type = str(reply.get("intent_type") or "").strip()

  if intent_type == "accept_baseline":
    total = baseline_amount
  elif intent_type == "set_total":
    try:
      total = float(reply.get("cogs_total_year1"))
    except Exception:
      return None
  elif intent_type == "set_percent":
    try:
      percent = float(reply.get("cogs_percent_of_revenue"))
    except Exception:
      return None
    total = float(revenue_year1 * percent)
  elif intent_type == "set_adjustment":
    try:
      adjustment = float(reply.get("cogs_adjustment"))
    except Exception:
      return None
    total = baseline_amount + adjustment
  else:
    return None

  total = max(0.0, float(total))
  adjustment = float(total - baseline_amount)
  percent_total = float(total / revenue_year1) if revenue_year1 > 0 else baseline_percent
  return {
    "baseline_cogs_percent": baseline_percent,
    "baseline_cogs": baseline_amount,
    "cogs_adjustment": adjustment,
    "cogs_total_year1": total,
    "cogs_basis_naics": baseline.get("cogs_basis_naics"),
    "cogs_basis_years_used": years_used if isinstance(years_used, list) else [],
    "cogs_basis_rationale": str(baseline.get("cogs_basis_rationale") or "").strip(),
    "current_cogs": total,
    "cogs_percent_of_revenue": percent_total,
  }


def _build_initial_lease_message() -> str:
  return (
    "Now let's capture any leased or rented equipment or space beyond your main rent. "
    "Do you pay to use any equipment, vehicles, servers, or other space you do not own, and if so, about how much and how often "
    "(for example, $5,000 per month or $20,000 per year)?"
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


def _maybe_handle_financials_monthly_rent_turn(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  interpret_monthly_rent_reply,
  interpret_future_rent_reply,
  financials_chat_turn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
  next_financials = dict(financials_json or {})
  if _financials_field_resolved(next_financials, "monthly_rent_expense"):
    return None, next_financials

  if not str(user_message or "").strip():
    return {
      "assistant_message": _build_monthly_rent_message(shared_context=shared_context),
      "finalize_ready": False,
    }, next_financials

  reply = interpret_monthly_rent_reply(
    user_message=user_message,
    last_assistant=last_assistant,
  )
  intent_type = str(reply.get("intent_type") or "").strip()
  if intent_type in ("ask_question", "unclear") or not intent_type:
    assistant_message = str(reply.get("question_or_clarification") or "").strip()
    if not assistant_message:
      assistant_message = "What monthly amount should I use for dedicated business space, if any?"
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  if intent_type == "set_none":
    amount = 0.0
  else:
    try:
      amount = float(reply.get("monthly_rent_expense"))
    except Exception:
      amount = None
    if amount is None:
      return {
        "assistant_message": "What monthly amount should I use for dedicated business space, if any?",
        "finalize_ready": False,
      }, next_financials
    amount = max(0.0, amount)

  next_financials["monthly_rent_expense"] = float(amount)
  next_shared_context = dict(shared_context or {})
  next_shared_context["financials"] = next_financials
  next_intake_context = dict(intake_context or {})
  next_intake_context["financials_json"] = next_financials
  next_intake_context["shared_context"] = next_shared_context
  next_stage = _next_financials_stage(next_financials)
  if next_stage == "future_rent_expected":
    future_turn, next_financials = _maybe_handle_financials_future_rent_turn(
      conn=conn,
      draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
      business_facts=business_facts,
      interpret_future_rent_reply=interpret_future_rent_reply,
      financials_chat_turn=financials_chat_turn,
      intake_context=next_intake_context,
      conversation_messages=conversation_messages,
      shared_context=next_shared_context,
      last_assistant="",
      user_message="",
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if future_turn is not None:
      return future_turn, next_financials
  turn, next_financials, _ = _advance_persisted_financials_stage(
    conn=conn,
    draft_id=draft_id,
    business_facts=business_facts,
    financials_chat_turn=financials_chat_turn,
    intake_context=next_intake_context,
    conversation_messages=conversation_messages,
    shared_context=next_shared_context,
    financials_json=next_financials,
    financials_year1_json=financials_year1_json,
    marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
  )
  return turn, next_financials


def _maybe_handle_financials_future_rent_turn(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  interpret_future_rent_reply,
  financials_chat_turn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
  next_financials = dict(financials_json or {})
  if _financials_field_resolved(next_financials, "future_rent_expected"):
    return None, next_financials

  if not str(user_message or "").strip():
    return {
      "assistant_message": _build_future_rent_message(
        shared_context=shared_context,
        monthly_rent_expense=next_financials.get("monthly_rent_expense"),
      ),
      "finalize_ready": False,
    }, next_financials

  reply = interpret_future_rent_reply(
    user_message=user_message,
    last_assistant=last_assistant,
  )
  intent_type = str(reply.get("intent_type") or "").strip()
  if intent_type in ("ask_question", "unclear") or not intent_type:
    assistant_message = str(reply.get("question_or_clarification") or "").strip()
    if not assistant_message:
      assistant_message = "Should I treat paid dedicated business space as something this business is likely to need later on?"
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  if intent_type == "set_true":
    next_financials["future_rent_expected"] = True
  elif intent_type == "set_false":
    next_financials["future_rent_expected"] = False
  else:
    return {
      "assistant_message": "Should I treat paid dedicated business space as something this business is likely to need later on?",
      "finalize_ready": False,
    }, next_financials

  next_shared_context = dict(shared_context or {})
  next_shared_context["financials"] = next_financials
  next_intake_context = dict(intake_context or {})
  next_intake_context["financials_json"] = next_financials
  next_intake_context["shared_context"] = next_shared_context
  turn, next_financials, _ = _advance_persisted_financials_stage(
    conn=conn,
    draft_id=draft_id,
    business_facts=business_facts,
    financials_chat_turn=financials_chat_turn,
    intake_context=next_intake_context,
    conversation_messages=conversation_messages,
    shared_context=next_shared_context,
    financials_json=next_financials,
    financials_year1_json=financials_year1_json,
    marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
  )
  return turn, next_financials


def _normalize_initial_lease_reply(reply: Dict[str, Any]) -> Optional[str]:
  intent_type = str(reply.get("intent_type") or "").strip()
  if intent_type == "set_none":
    return "0,none"
  if intent_type != "set_value":
    return None
  try:
    amount = float(reply.get("payment_amount"))
  except Exception:
    amount = 0.0
  amount = max(0.0, amount)
  period = str(reply.get("period") or "").strip().lower()
  if period == "annual":
    period = "yearly"
  if period not in {"daily", "weekly", "monthly", "quarterly", "yearly", "one-time", "unknown"}:
    period = "unknown"
  return f"{amount:g},{period}"


def _maybe_handle_financials_initial_lease_turn(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  interpret_initial_lease_reply,
  financials_chat_turn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
  next_financials = dict(financials_json or {})
  if _financials_field_resolved(next_financials, "initial_lease"):
    return None, next_financials

  if not str(user_message or "").strip():
    return {"assistant_message": _build_initial_lease_message(), "finalize_ready": False}, next_financials

  reply = interpret_initial_lease_reply(
    user_message=user_message,
    last_assistant=last_assistant,
  )
  intent_type = str(reply.get("intent_type") or "").strip()
  if intent_type in ("ask_question", "unclear") or not intent_type:
    assistant_message = str(reply.get("question_or_clarification") or "").strip()
    if not assistant_message:
      assistant_message = (
        "Should I record no additional lease commitments beyond main rent, or is there a payment amount and frequency we should use?"
      )
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  normalized = _normalize_initial_lease_reply(reply)
  if not normalized:
    return {
      "assistant_message": "Should I record no additional lease commitments beyond main rent, or is there a payment amount and frequency we should use?",
      "finalize_ready": False,
    }, next_financials

  next_financials["initial_lease"] = normalized
  next_shared_context = dict(shared_context or {})
  next_shared_context["financials"] = next_financials
  next_intake_context = dict(intake_context or {})
  next_intake_context["financials_json"] = next_financials
  next_intake_context["shared_context"] = next_shared_context
  turn, next_financials, _ = _advance_persisted_financials_stage(
    conn=conn,
    draft_id=draft_id,
    business_facts=business_facts,
    financials_chat_turn=financials_chat_turn,
    intake_context=next_intake_context,
    conversation_messages=conversation_messages,
    shared_context=next_shared_context,
    financials_json=next_financials,
    financials_year1_json=financials_year1_json,
    marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
  )
  return turn, next_financials


def _maybe_handle_financials_payroll_turn(
  *,
  interpret_payroll_reply,
  validate_payroll_setup,
  estimate_marketing_baseline_from_context,
  interpret_marketing_reply,
  validate_marketing_setup,
  interpret_monthly_rent_reply,
  interpret_future_rent_reply,
  financials_chat_turn,
  conn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  business_facts: Dict[str, Any],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
  next_financials = dict(financials_json or {})
  current_signature = _build_payroll_baseline_signature(shared_context)
  pending_signature = str(next_financials.get("_pending_payroll_signature") or "").strip()
  pending_baseline = next_financials.get("_pending_payroll_baseline")

  if pending_signature and current_signature and pending_signature != current_signature:
    next_financials.pop("_pending_payroll_signature", None)
    next_financials.pop("_pending_payroll_baseline", None)
    pending_baseline = None

  current_payroll_resolved = "current_payroll" in next_financials
  if not current_payroll_resolved and not isinstance(pending_baseline, dict):
    baseline = _compute_payroll_baseline(shared_context=shared_context)
    next_financials["_pending_payroll_signature"] = current_signature
    next_financials["_pending_payroll_baseline"] = baseline
    return {
      "assistant_message": _build_payroll_baseline_message(baseline),
      "finalize_ready": False,
    }, next_financials

  if not isinstance(pending_baseline, dict):
    return None, next_financials

  if not str(user_message or "").strip():
    return {
      "assistant_message": _build_payroll_baseline_message(pending_baseline),
      "finalize_ready": False,
    }, next_financials

  reply = interpret_payroll_reply(
    user_message=user_message,
    last_assistant=last_assistant,
    payroll_context=pending_baseline,
  )
  intent_type = str(reply.get("intent_type") or "").strip()
  if intent_type in ("ask_question", "unclear") or not intent_type:
    assistant_message = str(reply.get("question_or_clarification") or "").strip()
    if not assistant_message:
      assistant_message = (
        "What should we use for Year-1 payroll: keep the people-plan baseline, use a total annual payroll amount, or adjust the baseline up or down?"
      )
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  normalized = _normalize_payroll_reply_to_fields(reply=reply, baseline=pending_baseline)
  if not isinstance(normalized, dict):
    return {
      "assistant_message": "What should we use for Year-1 payroll: keep the baseline, use a total annual payroll amount, or adjust the baseline up or down?",
      "finalize_ready": False,
    }, next_financials

  if intent_type != "accept_baseline":
    validation_context = dict(intake_context or {})
    validation_financials = dict(next_financials)
    validation_financials.update(normalized)
    validation_shared = dict(shared_context or {})
    validation_shared["financials"] = validation_financials
    validation_context["financials_json"] = validation_financials
    validation_context["shared_context"] = validation_shared
    validation = validate_payroll_setup(
      intake_context=validation_context,
      payroll_context={**pending_baseline, **normalized},
      user_message=user_message,
    )
    if not bool(validation.get("proceed", False)):
      assistant_message = str(validation.get("assistant_message") or "").strip()
      if not assistant_message:
        assistant_message = "What should Year-1 payroll be instead?"
      return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  next_financials.update(normalized)
  next_financials.pop("_pending_payroll_signature", None)
  next_financials.pop("_pending_payroll_baseline", None)
  acknowledgement = (
    _build_payroll_adjustment_acknowledgement(next_financials)
    if intent_type != "accept_baseline"
    else ""
  )

  next_shared_context = dict(shared_context or {})
  next_shared_context["financials"] = next_financials
  next_intake_context = dict(intake_context or {})
  next_intake_context["financials_json"] = next_financials
  next_intake_context["shared_context"] = next_shared_context

  next_stage = _next_financials_stage(next_financials)
  if next_stage == "marketing":
    marketing_turn, next_financials, next_marketing_model = _maybe_handle_financials_marketing_turn(
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
      interpret_marketing_reply=interpret_marketing_reply,
      validate_marketing_setup=validate_marketing_setup,
      interpret_monthly_rent_reply=interpret_monthly_rent_reply,
      interpret_future_rent_reply=interpret_future_rent_reply,
      financials_chat_turn=financials_chat_turn,
      conn=conn,
      intake_context=next_intake_context,
      conversation_messages=conversation_messages,
      business_facts=business_facts,
      shared_context=next_shared_context,
      last_assistant="",
      user_message="",
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    next_shared_context["marketing"] = next_marketing_model
    if marketing_turn is not None:
      if acknowledgement:
        next_text = str(marketing_turn.get("assistant_message") or "").strip()
        marketing_turn["assistant_message"] = (
          f"{acknowledgement}\n\n{next_text}".strip() if next_text else acknowledgement
        )
      return marketing_turn, next_financials
  if next_stage:
    next_intake_context["financials_active_stage"] = next_stage
  else:
    next_intake_context.pop("financials_active_stage", None)

  turn = financials_chat_turn(
    intake_context=next_intake_context,
    conversation_messages=conversation_messages,
  ) or {}
  if acknowledgement:
    next_text = str(turn.get("assistant_message") or "").strip()
    turn["assistant_message"] = (
      f"{acknowledgement}\n\n{next_text}".strip() if next_text else acknowledgement
  )
  next_financials = _sync_pending_revenue_adjustment_state(
    next_financials,
    financials_year1_json,
    turn.get("revenue_adjudication") if isinstance(turn, dict) else None,
  )
  return turn, next_financials


def _maybe_handle_financials_marketing_turn(
  *,
  estimate_marketing_baseline_from_context,
  interpret_marketing_reply,
  validate_marketing_setup,
  interpret_monthly_rent_reply,
  interpret_future_rent_reply,
  financials_chat_turn,
  conn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  business_facts: Dict[str, Any],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
  next_financials = dict(financials_json or {})
  ops_json = dict((shared_context or {}).get("operating_model") or {})
  market_json = dict((shared_context or {}).get("target_market") or {})
  people_json = dict((shared_context or {}).get("people_capability") or {})
  current_marketing_model = dict((shared_context or {}).get("marketing") or {})
  marketing_model = _compute_marketing_model_json(
    conn=conn,
    ops_json=ops_json,
    market_json=market_json,
    people_json=people_json,
    financials_year1_json=financials_year1_json,
    business_facts=business_facts,
    existing_marketing_model_json=current_marketing_model,
    estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
  )
  current_signature = str(marketing_model.get("signature") or "").strip()
  pending_signature = str(next_financials.get("_pending_marketing_signature") or "").strip()
  pending_baseline = next_financials.get("_pending_marketing_baseline")

  if pending_signature and current_signature and pending_signature != current_signature:
    next_financials.pop("_pending_marketing_signature", None)
    next_financials.pop("_pending_marketing_baseline", None)
    pending_baseline = None

  current_marketing_resolved = "marketing_total_year1" in next_financials
  if not current_marketing_resolved and not isinstance(pending_baseline, dict):
    ready_model = _resolve_marketing_model_or_raise(
      conn=conn,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      existing_marketing_model_json=marketing_model,
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
    )
    marketing_model = ready_model
    next_financials["_pending_marketing_signature"] = current_signature
    next_financials["_pending_marketing_baseline"] = ready_model
    return {
      "assistant_message": _build_marketing_baseline_message(ready_model),
      "finalize_ready": False,
    }, next_financials, marketing_model

  if not isinstance(pending_baseline, dict):
    pending_baseline = _resolve_marketing_model_or_raise(
      conn=conn,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      existing_marketing_model_json=marketing_model,
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
    )
    marketing_model = pending_baseline
    next_financials["_pending_marketing_signature"] = current_signature
    next_financials["_pending_marketing_baseline"] = pending_baseline

  if not str(user_message or "").strip():
    return {
      "assistant_message": _build_marketing_baseline_message(pending_baseline),
      "finalize_ready": False,
    }, next_financials, marketing_model

  reply = interpret_marketing_reply(
    user_message=user_message,
    last_assistant=last_assistant,
    marketing_context=pending_baseline,
  )
  intent_type = str(reply.get("intent_type") or "").strip()
  if intent_type in ("ask_question", "unclear") or not intent_type:
    assistant_message = str(reply.get("question_or_clarification") or "").strip()
    if not assistant_message:
      assistant_message = (
        "What should we use for Year-1 marketing: keep the baseline, use a total annual amount, or adjust the baseline up or down?"
      )
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials, marketing_model

  normalized = _normalize_marketing_reply_to_fields(reply=reply, baseline=pending_baseline)
  if not isinstance(normalized, dict):
    return {
      "assistant_message": "What should we use for Year-1 marketing: keep the baseline, use a total annual amount, or adjust the baseline up or down?",
      "finalize_ready": False,
    }, next_financials, marketing_model

  if intent_type != "accept_baseline":
    validation_context = dict(intake_context or {})
    validation_financials = dict(next_financials)
    validation_financials.update(normalized)
    validation_shared = dict(shared_context or {})
    validation_shared["financials"] = validation_financials
    validation_shared["marketing"] = marketing_model
    validation_context["financials_json"] = validation_financials
    validation_context["shared_context"] = validation_shared
    validation = validate_marketing_setup(
      intake_context=validation_context,
      marketing_context={**pending_baseline, **normalized},
      user_message=user_message,
    )
    if not bool(validation.get("proceed", False)):
      assistant_message = str(validation.get("assistant_message") or "").strip()
      if not assistant_message:
        assistant_message = "What should the Year-1 marketing budget be instead?"
      return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials, marketing_model

  next_financials.update(normalized)
  next_financials.pop("_pending_marketing_signature", None)
  next_financials.pop("_pending_marketing_baseline", None)
  acknowledgement = (
    _build_marketing_adjustment_acknowledgement(next_financials)
    if intent_type != "accept_baseline"
    else ""
  )

  next_shared_context = dict(shared_context or {})
  next_shared_context["financials"] = next_financials
  next_shared_context["marketing"] = marketing_model
  next_intake_context = dict(intake_context or {})
  next_intake_context["financials_json"] = next_financials
  next_intake_context["shared_context"] = next_shared_context
  next_stage = _next_financials_stage(next_financials)
  if next_stage == "monthly_rent_expense":
    rent_turn, next_financials = _maybe_handle_financials_monthly_rent_turn(
      conn=conn,
      draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
      business_facts=business_facts,
      interpret_monthly_rent_reply=interpret_monthly_rent_reply,
      interpret_future_rent_reply=interpret_future_rent_reply,
      financials_chat_turn=financials_chat_turn,
      intake_context=next_intake_context,
      conversation_messages=conversation_messages,
      shared_context=next_shared_context,
      last_assistant="",
      user_message="",
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if rent_turn is not None:
      if acknowledgement:
        next_text = str(rent_turn.get("assistant_message") or "").strip()
        rent_turn["assistant_message"] = (
          f"{acknowledgement}\n\n{next_text}".strip() if next_text else acknowledgement
        )
      return rent_turn, next_financials, marketing_model
  if next_stage:
    next_intake_context["financials_active_stage"] = next_stage
  else:
    next_intake_context.pop("financials_active_stage", None)

  turn = financials_chat_turn(
    intake_context=next_intake_context,
    conversation_messages=conversation_messages,
  ) or {}
  if acknowledgement:
    next_text = str(turn.get("assistant_message") or "").strip()
    turn["assistant_message"] = (
      f"{acknowledgement}\n\n{next_text}".strip() if next_text else acknowledgement
    )
  next_financials = _sync_pending_revenue_adjustment_state(
    next_financials,
    financials_year1_json,
    turn.get("revenue_adjudication") if isinstance(turn, dict) else None,
  )
  return turn, next_financials, marketing_model


def _maybe_handle_financials_cogs_turn(
  *,
  interpret_cogs_reply,
  estimate_cogs_percent_from_context,
  interpret_payroll_reply,
  validate_payroll_setup,
  estimate_marketing_baseline_from_context,
  interpret_marketing_reply,
  validate_marketing_setup,
  interpret_monthly_rent_reply,
  interpret_future_rent_reply,
  interpret_initial_lease_reply,
  financials_chat_turn,
  conn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  business_facts: Dict[str, Any],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
  next_financials = dict(financials_json or {})
  ops_json = dict((shared_context or {}).get("operating_model") or {})
  current_signature = _build_cogs_baseline_signature(financials_year1_json, ops_json)
  pending_signature = str(next_financials.get("_pending_cogs_signature") or "").strip()
  pending_baseline = next_financials.get("_pending_cogs_baseline")

  if pending_signature and current_signature and pending_signature != current_signature:
    next_financials.pop("_pending_cogs_signature", None)
    next_financials.pop("_pending_cogs_baseline", None)
    pending_baseline = None

  current_cogs_resolved = "current_cogs" in next_financials
  if not current_cogs_resolved and not isinstance(pending_baseline, dict):
    baseline = _resolve_cogs_baseline_or_raise(
      conn=conn,
      ops_json=ops_json,
      shared_context=shared_context,
      estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
      financials_year1_json=financials_year1_json,
    )
    next_financials["_pending_cogs_signature"] = current_signature
    next_financials["_pending_cogs_baseline"] = baseline
    return {
      "assistant_message": _build_cogs_baseline_message(baseline),
      "finalize_ready": False,
    }, next_financials

  if not isinstance(pending_baseline, dict):
    pending_baseline = _resolve_cogs_baseline_or_raise(
      conn=conn,
      ops_json=ops_json,
      shared_context=shared_context,
      estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
      financials_year1_json=financials_year1_json,
    )
    next_financials["_pending_cogs_signature"] = current_signature
    next_financials["_pending_cogs_baseline"] = pending_baseline

  if not str(user_message or "").strip():
    return {
      "assistant_message": _build_cogs_baseline_message(pending_baseline),
      "finalize_ready": False,
    }, next_financials

  reply = interpret_cogs_reply(
    user_message=user_message,
    last_assistant=last_assistant,
    cogs_context=pending_baseline,
  )
  intent_type = str(reply.get("intent_type") or "").strip()
  if intent_type in ("ask_question", "unclear") or not intent_type:
    assistant_message = str(reply.get("question_or_clarification") or "").strip()
    if not assistant_message:
      assistant_message = "Should we keep that direct-cost baseline, or adjust it because your direct costs work differently?"
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  normalized = _normalize_cogs_reply_to_fields(reply=reply, baseline=pending_baseline)
  if not isinstance(normalized, dict):
    return {
      "assistant_message": "Should we keep that direct-cost baseline, or adjust it because your direct costs work differently?",
      "finalize_ready": False,
    }, next_financials

  if intent_type != "accept_baseline":
    try:
      from financials_consultant import validate_cogs_setup  # type: ignore
    except Exception:
      from client_intake_and_finmo.financials_consultant import validate_cogs_setup  # type: ignore
    validation_context = dict(intake_context or {})
    validation_financials = dict(next_financials)
    validation_financials.update(normalized)
    validation_shared = dict(shared_context or {})
    validation_shared["financials"] = validation_financials
    validation_context["financials_json"] = validation_financials
    validation_context["shared_context"] = validation_shared
    validation = validate_cogs_setup(
      intake_context=validation_context,
      cogs_context={**pending_baseline, **normalized},
      user_message=user_message,
    )
    if not bool(validation.get("proceed", False)):
      assistant_message = str(validation.get("assistant_message") or "").strip()
      if not assistant_message:
        assistant_message = "What should Year-1 direct costs be instead?"
      return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  next_financials.update(normalized)
  next_financials.pop("_pending_cogs_signature", None)
  next_financials.pop("_pending_cogs_baseline", None)
  acknowledgement = (
    _build_cogs_adjustment_acknowledgement(next_financials)
    if intent_type != "accept_baseline"
    else ""
  )

  next_shared_context = dict(shared_context or {})
  next_shared_context["financials"] = next_financials
  next_intake_context = dict(intake_context or {})
  next_intake_context["financials_json"] = next_financials
  next_intake_context["shared_context"] = next_shared_context
  next_stage = _next_financials_stage(next_financials)
  if next_stage == "current_payroll":
    payroll_turn, next_financials = _maybe_handle_financials_payroll_turn(
      interpret_payroll_reply=interpret_payroll_reply,
      validate_payroll_setup=validate_payroll_setup,
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
      interpret_marketing_reply=interpret_marketing_reply,
      validate_marketing_setup=validate_marketing_setup,
      interpret_monthly_rent_reply=interpret_monthly_rent_reply,
      interpret_future_rent_reply=interpret_future_rent_reply,
      financials_chat_turn=financials_chat_turn,
      conn=conn,
      intake_context=next_intake_context,
      conversation_messages=conversation_messages,
      business_facts=business_facts,
      shared_context=next_shared_context,
      last_assistant="",
      user_message="",
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if payroll_turn is not None:
      if acknowledgement:
        next_text = str(payroll_turn.get("assistant_message") or "").strip()
        payroll_turn["assistant_message"] = (
          f"{acknowledgement}\n\n{next_text}".strip() if next_text else acknowledgement
        )
      return payroll_turn, next_financials
  if next_stage == "initial_lease":
    lease_turn, next_financials = _maybe_handle_financials_initial_lease_turn(
      conn=conn,
      draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
      business_facts=business_facts,
      interpret_initial_lease_reply=interpret_initial_lease_reply,
      financials_chat_turn=financials_chat_turn,
      intake_context=next_intake_context,
      conversation_messages=conversation_messages,
      shared_context=next_shared_context,
      last_assistant="",
      user_message="",
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if lease_turn is not None:
      if acknowledgement:
        next_text = str(lease_turn.get("assistant_message") or "").strip()
        lease_turn["assistant_message"] = (
          f"{acknowledgement}\n\n{next_text}".strip() if next_text else acknowledgement
        )
      return lease_turn, next_financials
  if next_stage:
    next_intake_context["financials_active_stage"] = next_stage
  else:
    next_intake_context.pop("financials_active_stage", None)

  turn = financials_chat_turn(
    intake_context=next_intake_context,
    conversation_messages=conversation_messages,
  ) or {}
  if acknowledgement:
    next_text = str(turn.get("assistant_message") or "").strip()
    turn["assistant_message"] = (
      f"{acknowledgement}\n\n{next_text}".strip() if next_text else acknowledgement
    )
  next_financials = _sync_pending_revenue_adjustment_state(
    next_financials,
    financials_year1_json,
    turn.get("revenue_adjudication") if isinstance(turn, dict) else None,
  )
  next_financials["_financials_revenue_intro_done"] = True
  return turn, next_financials


def _financials_field_resolved(financials_json: Dict[str, Any], field: str) -> bool:
  if not isinstance(financials_json, dict):
    return False
  if field not in financials_json:
    return False
  value = financials_json.get(field)
  if field == "initial_lease":
    return bool(str(value or "").strip())
  return value is not None


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


def _next_financials_stage(financials_json: Dict[str, Any]) -> Optional[str]:
  data = _ensure_financials_stage_defaults(financials_json)
  ordered_stages = [
    ("revenue_intro", lambda d: bool(d.get("_financials_revenue_intro_done"))),
    ("cogs", lambda d: _financials_field_resolved(d, "current_cogs")),
    ("current_payroll", lambda d: _financials_field_resolved(d, "current_payroll")),
    ("marketing", lambda d: _financials_field_resolved(d, "marketing_total_year1")),
    ("monthly_rent_expense", lambda d: _financials_field_resolved(d, "monthly_rent_expense")),
    ("future_rent_expected", lambda d: _financials_field_resolved(d, "future_rent_expected")),
    ("owner_compensation", lambda d: _financials_field_resolved(d, "owner_compensation")),
    ("other_operating_expense", lambda d: _financials_field_resolved(d, "other_operating_expense")),
    ("current_num_employees", lambda d: _financials_field_resolved(d, "current_num_employees")),
    ("current_capex", lambda d: _financials_field_resolved(d, "current_capex")),
    ("initial_assets", lambda d: _financials_field_resolved(d, "initial_assets")),
    ("initial_lease", lambda d: _financials_field_resolved(d, "initial_lease")),
    ("initial_equity", lambda d: _financials_field_resolved(d, "initial_equity")),
    ("total_debt_outstanding", lambda d: _financials_field_resolved(d, "total_debt_outstanding")),
    ("other_monthly_debt_payments", lambda d: _financials_field_resolved(d, "other_monthly_debt_payments")),
    ("annual_interest_payment", lambda d: _financials_field_resolved(d, "annual_interest_payment")),
    ("annual_principal_payment", lambda d: _financials_field_resolved(d, "annual_principal_payment")),
    ("cash_on_hand", lambda d: _financials_field_resolved(d, "cash_on_hand")),
    ("ar_balance", lambda d: _financials_field_resolved(d, "ar_balance")),
    ("ap_balance", lambda d: _financials_field_resolved(d, "ap_balance")),
    ("inventory_balance", lambda d: _financials_field_resolved(d, "inventory_balance")),
  ]
  for stage_name, resolved_fn in ordered_stages:
    if not resolved_fn(data):
      return stage_name
  return None


def _financials_stage_is_controller_owned(stage_name: Optional[str]) -> bool:
  return bool(str(stage_name or "").strip())


_GENERIC_FINANCIALS_SCALAR_FIELDS = {
  "owner_compensation",
  "other_operating_expense",
  "current_num_employees",
  "current_capex",
  "initial_assets",
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

_GENERIC_FINANCIALS_ZERO_WORDS = (
  "0",
  "zero",
  "none",
  "nothing",
  "no",
  "nope",
  "nil",
  "n/a",
  "not applicable",
  "not owed",
  "did not owe",
  "don't owe",
  "do not owe",
  "no unpaid",
)

_GENERIC_FINANCIALS_FIELD_LABELS = {
  "owner_compensation": "owner compensation",
  "other_operating_expense": "other operating expense",
  "current_num_employees": "current employee count",
  "current_capex": "current capital spending",
  "initial_assets": "initial assets already in the business",
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


def _is_generic_financials_scalar_stage(stage_name: Optional[str]) -> bool:
  return str(stage_name or "").strip() in _GENERIC_FINANCIALS_SCALAR_FIELDS


def _extract_financials_scalar_stage_value(stage_name: str, user_message: Any) -> Optional[float]:
  text = str(user_message or "").strip()
  if not text:
    return None
  numeric_value = _extract_single_compact_number_allow_zero(text)
  if numeric_value is not None:
    return numeric_value
  normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
  normalized = re.sub(r"\s+", " ", normalized).strip()
  if not normalized:
    return None
  for token in _GENERIC_FINANCIALS_ZERO_WORDS:
    if token in normalized:
      return 0.0
  return None


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


def _maybe_handle_financials_generic_patch_turn(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  route_intent,
  financials_chat_turn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  active_stage: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  stage_name = str(active_stage or "").strip()
  if not stage_name or not str(user_message or "").strip():
    return None, next_financials
  try:
    from fact_templates import sanitize_fact_template as _sanitize_fact_template  # type: ignore
  except Exception:
    def _sanitize_fact_template(value: str) -> str:
      return str(value or "")

  if _is_generic_financials_scalar_stage(stage_name):
    stage_value = _extract_financials_scalar_stage_value(stage_name, user_message)
    if stage_value is not None:
      updated_financials = dict(next_financials)
      updated_financials[stage_name] = int(round(stage_value)) if stage_name == "current_num_employees" else float(stage_value)
      updated_financials = _ensure_financials_stage_defaults(updated_financials)
      acknowledgement = _build_financials_scalar_stage_acknowledgement(stage_name, float(updated_financials.get(stage_name) or 0.0))
      next_context = dict(intake_context or {})
      next_context["financials_json"] = updated_financials
      next_shared = dict(shared_context or {})
      next_shared["financials"] = updated_financials
      next_context["shared_context"] = next_shared
      next_turn, updated_financials, _ = _advance_persisted_financials_stage(
        conn=conn,
        draft_id=draft_id,
        business_facts=business_facts,
        financials_chat_turn=financials_chat_turn,
        intake_context=next_context,
        conversation_messages=conversation_messages,
        shared_context=next_shared,
        financials_json=updated_financials,
        financials_year1_json=financials_year1_json,
        marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
        acknowledgement=acknowledgement,
      )
      next_turn["assistant_message"] = _sanitize_fact_template(str(next_turn.get("assistant_message") or "").strip())
      return next_turn, updated_financials
    return {
      "assistant_message": _build_financials_scalar_stage_clarifier(stage_name),
      "finalize_ready": False,
    }, next_financials

  routed = route_intent(
    consult_type="financials",
    user_message=str(user_message).strip(),
    baseline_json=next_financials,
    shared_context=shared_context,
    recent_messages=conversation_messages[-30:] if conversation_messages else [],
    active_focus="financials",
  )
  action = str(routed.get("action") or "").strip()
  assistant_message = _sanitize_fact_template(str(routed.get("assistant_message") or "").strip())
  patch = routed.get("patch") if isinstance(routed.get("patch"), dict) else None

  if action == "edit_patch" and patch:
    updated_financials = dict(next_financials)
    updated_financials.update(patch)
    updated_financials = _ensure_financials_stage_defaults(updated_financials)
    next_context = dict(intake_context or {})
    next_context["financials_json"] = updated_financials
    next_shared = dict(shared_context or {})
    next_shared["financials"] = updated_financials
    next_context["shared_context"] = next_shared
    next_turn, updated_financials, _ = _advance_persisted_financials_stage(
      conn=conn,
      draft_id=draft_id,
      business_facts=business_facts,
      financials_chat_turn=financials_chat_turn,
      intake_context=next_context,
      conversation_messages=conversation_messages,
      shared_context=next_shared,
      financials_json=updated_financials,
      financials_year1_json=financials_year1_json,
      marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
      acknowledgement=assistant_message or "Got it.",
    )
    next_turn["assistant_message"] = _sanitize_fact_template(str(next_turn.get("assistant_message") or "").strip())
    return next_turn, updated_financials

  if action in {"confirm_clarify", "answer_readonly", "continue_chat"} and assistant_message:
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  return None, next_financials


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
  financials_chat_turn,
  route_intent,
  interpret_cogs_reply,
  interpret_monthly_rent_reply,
  interpret_future_rent_reply,
  estimate_cogs_percent_from_context,
  interpret_payroll_reply,
  validate_payroll_setup,
  estimate_marketing_baseline_from_context,
  interpret_marketing_reply,
  validate_marketing_setup,
  interpret_initial_lease_reply,
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

  def _stage_context(stage_name: Optional[str], fin_json: Dict[str, Any]) -> Dict[str, Any]:
    ctx = dict(intake_context or {})
    ctx["financials_json"] = fin_json
    next_shared = dict(shared_context or {})
    next_shared["financials"] = fin_json
    ctx["shared_context"] = next_shared
    if stage_name:
      ctx["financials_active_stage"] = stage_name
    else:
      ctx.pop("financials_active_stage", None)
    return ctx

  if active_stage == "cogs":
    cogs_turn, next_financials = _maybe_handle_financials_cogs_turn(
      interpret_cogs_reply=interpret_cogs_reply,
      estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
      interpret_payroll_reply=interpret_payroll_reply,
      validate_payroll_setup=validate_payroll_setup,
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
      interpret_marketing_reply=interpret_marketing_reply,
      validate_marketing_setup=validate_marketing_setup,
      interpret_monthly_rent_reply=interpret_monthly_rent_reply,
      interpret_future_rent_reply=interpret_future_rent_reply,
      interpret_initial_lease_reply=interpret_initial_lease_reply,
      financials_chat_turn=financials_chat_turn,
      conn=conn,
      intake_context=_stage_context(active_stage, next_financials),
      conversation_messages=conversation_messages,
      business_facts=business_facts,
      shared_context=shared_context,
      last_assistant=last_assistant,
      user_message=user_message,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if cogs_turn is not None:
      return cogs_turn, next_financials
  if active_stage == "current_payroll":
    payroll_turn, next_financials = _maybe_handle_financials_payroll_turn(
      interpret_payroll_reply=interpret_payroll_reply,
      validate_payroll_setup=validate_payroll_setup,
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
      interpret_marketing_reply=interpret_marketing_reply,
      validate_marketing_setup=validate_marketing_setup,
      interpret_monthly_rent_reply=interpret_monthly_rent_reply,
      interpret_future_rent_reply=interpret_future_rent_reply,
      financials_chat_turn=financials_chat_turn,
      conn=conn,
      intake_context=_stage_context(active_stage, next_financials),
      conversation_messages=conversation_messages,
      business_facts=business_facts,
      shared_context=shared_context,
      last_assistant=last_assistant,
      user_message=user_message,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if payroll_turn is not None:
      return payroll_turn, next_financials
  if active_stage == "marketing":
    marketing_turn, next_financials, marketing_model = _maybe_handle_financials_marketing_turn(
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
      interpret_marketing_reply=interpret_marketing_reply,
      validate_marketing_setup=validate_marketing_setup,
      interpret_monthly_rent_reply=interpret_monthly_rent_reply,
      interpret_future_rent_reply=interpret_future_rent_reply,
      financials_chat_turn=financials_chat_turn,
      conn=conn,
      intake_context=_stage_context(active_stage, next_financials),
      conversation_messages=conversation_messages,
      business_facts=business_facts,
      shared_context=shared_context,
      last_assistant=last_assistant,
      user_message=user_message,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    try:
      shared_context["marketing"] = marketing_model
    except Exception:
      pass
    if marketing_turn is not None:
      return marketing_turn, next_financials
  if active_stage == "monthly_rent_expense":
    rent_turn, next_financials = _maybe_handle_financials_monthly_rent_turn(
      conn=conn,
      draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
      business_facts=business_facts,
      interpret_monthly_rent_reply=interpret_monthly_rent_reply,
      interpret_future_rent_reply=interpret_future_rent_reply,
      financials_chat_turn=financials_chat_turn,
      intake_context=_stage_context(active_stage, next_financials),
      conversation_messages=conversation_messages,
      shared_context=shared_context,
      last_assistant=last_assistant,
      user_message=user_message,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if rent_turn is not None:
      return rent_turn, next_financials
  if active_stage == "future_rent_expected":
    future_rent_turn, next_financials = _maybe_handle_financials_future_rent_turn(
      conn=conn,
      draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
      business_facts=business_facts,
      interpret_future_rent_reply=interpret_future_rent_reply,
      financials_chat_turn=financials_chat_turn,
      intake_context=_stage_context(active_stage, next_financials),
      conversation_messages=conversation_messages,
      shared_context=shared_context,
      last_assistant=last_assistant,
      user_message=user_message,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if future_rent_turn is not None:
      return future_rent_turn, next_financials
  if active_stage == "initial_lease":
    lease_turn, next_financials = _maybe_handle_financials_initial_lease_turn(
      conn=conn,
      draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
      business_facts=business_facts,
      interpret_initial_lease_reply=interpret_initial_lease_reply,
      financials_chat_turn=financials_chat_turn,
      intake_context=_stage_context(active_stage, next_financials),
      conversation_messages=conversation_messages,
      shared_context=shared_context,
      last_assistant=last_assistant,
      user_message=user_message,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
    if lease_turn is not None:
      return lease_turn, next_financials
  if active_stage:
    generic_turn, next_financials = _maybe_handle_financials_generic_patch_turn(
      conn=conn,
      draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
      business_facts=business_facts,
      route_intent=route_intent,
      financials_chat_turn=financials_chat_turn,
      intake_context=_stage_context(active_stage, next_financials),
      conversation_messages=conversation_messages,
      shared_context=shared_context,
      last_assistant=last_assistant,
      user_message=user_message,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      active_stage=active_stage,
    )
    if generic_turn is not None:
      return generic_turn, next_financials

  turn = financials_chat_turn(
    intake_context=_stage_context(active_stage, next_financials),
    conversation_messages=conversation_messages,
  ) or {}
  next_financials = _sync_pending_revenue_adjustment_state(
    next_financials,
    financials_year1_json,
    turn.get("revenue_adjudication") if isinstance(turn, dict) else None,
  )

  if active_stage == "revenue_intro":
    next_financials["_financials_revenue_intro_done"] = True
    revenue_adjudication = turn.get("revenue_adjudication") if isinstance(turn, dict) else None
    needs_adjustment = bool((revenue_adjudication or {}).get("requires_adjustment")) if isinstance(revenue_adjudication, dict) else False
    if not needs_adjustment:
      next_stage = _next_financials_stage(next_financials)
      if next_stage == "cogs":
        cogs_turn, next_financials = _maybe_handle_financials_cogs_turn(
          interpret_cogs_reply=interpret_cogs_reply,
          estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
          interpret_payroll_reply=interpret_payroll_reply,
          validate_payroll_setup=validate_payroll_setup,
          estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
          interpret_marketing_reply=interpret_marketing_reply,
          validate_marketing_setup=validate_marketing_setup,
          interpret_monthly_rent_reply=interpret_monthly_rent_reply,
          interpret_future_rent_reply=interpret_future_rent_reply,
          interpret_initial_lease_reply=interpret_initial_lease_reply,
          financials_chat_turn=financials_chat_turn,
          conn=conn,
          intake_context=_stage_context(next_stage, next_financials),
          conversation_messages=conversation_messages,
          business_facts=business_facts,
          shared_context=shared_context,
          last_assistant="",
          user_message="",
          financials_json=next_financials,
          financials_year1_json=financials_year1_json,
        )
        if cogs_turn and str(cogs_turn.get("assistant_message") or "").strip():
          combined_turn = dict(turn)
          combined_turn["assistant_message"] = (
            f"{str(turn.get('assistant_message') or '').strip()}\n\n{str(cogs_turn.get('assistant_message') or '').strip()}"
          ).strip()
          combined_turn["finalize_ready"] = False
          return combined_turn, next_financials
      elif next_stage:
        stage_turn = financials_chat_turn(
          intake_context=_stage_context(next_stage, next_financials),
          conversation_messages=conversation_messages,
        ) or {}
        stage_text = str(stage_turn.get("assistant_message") or "").strip()
        if stage_text:
          combined_turn = dict(turn)
          combined_turn["assistant_message"] = (
            f"{str(turn.get('assistant_message') or '').strip()}\n\n{stage_text}"
          ).strip()
          combined_turn["finalize_ready"] = False
          return combined_turn, next_financials

  return turn, next_financials


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
      from intake_business_types import get_naics_from_business_type  # type: ignore
    except Exception:
      from client_intake_and_finmo.intake_business_types import (  # type: ignore
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
  consistency_passed: bool,
) -> Tuple[str, Optional[str]]:
  # No realtime missing-fields gating; progression follows confirmations in order.
  if not ops_confirmed:
    return ("ops", None)
  if not market_confirmed:
    return ("market", None)
  if not people_confirmed:
    return ("people", None)
  if not financials_confirmed:
    return ("financials", None)
  if not consistency_passed:
    return ("consistency", None)
  return ("done", None)


def _next_focus(current: str) -> str:
  order = ["ops", "market", "people", "financials", "consistency", "done"]
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
  if focus_norm == "consistency":
    return "Start the consistency check. Review the current intake model and ask your first clarifying question."
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
        "financials_year1_json": draft.get("financials_year1_json"),
        "fulfillment_json": draft.get("fulfillment_json"),
        "consistency_solver_state_json": _extract_consistency_solver_state(draft.get("financials_json")),
        "normalized_traits_json": draft.get("normalized_traits_json"),
        "benchmark_payload_json": draft.get("benchmark_payload_json"),
        "constraint_engine_state_json": draft.get("constraint_engine_state_json"),
        "forecast_engine_state_json": draft.get("forecast_engine_state_json"),
        "forecast_quarters_json": draft.get("forecast_quarters_json"),
        "consistency_gpt_governance_json": draft.get("consistency_gpt_governance_json"),
        "consistency_controller_contract_json": draft.get("consistency_controller_contract_json"),
        "consistency_solver_execution_json": draft.get("consistency_solver_execution_json"),
        "engine_versions_json": draft.get("engine_versions_json"),
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


def _extract_consistency_solver_state(raw_financials: Any) -> Dict[str, Any]:
  parsed = _parse_json_value(raw_financials)
  if isinstance(parsed, dict):
    state = parsed.get("_consistency_solver_state")
    return state if isinstance(state, dict) else {}
  return {}


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
    "normalized_traits_json",
    "benchmark_payload_json",
    "constraint_engine_state_json",
    "forecast_engine_state_json",
    "forecast_quarters_json",
    "model_input_json",
    "finmo_json",
    "consistency_finmo_attempts_json",
    "consistency_modified_plan_json",
    "consistency_gpt_governance_json",
    "consistency_controller_contract_json",
    "consistency_solver_execution_json",
    "engine_versions_json",
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
  serialized["consistency_solver_state_json"] = _extract_consistency_solver_state(row.get("financials_json"))
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
    try:
      from solver_trace import configure_solver_trace_run, trace_values  # type: ignore
    except Exception:
      from client_intake_and_finmo.solver_trace import configure_solver_trace_run, trace_values  # type: ignore

    from intake_consultant import consultant_chat_turn, consultant_finalize  # type: ignore
    from target_market_consultant import target_market_chat_turn, target_market_finalize  # type: ignore
    from people_capability_consultant import (  # type: ignore
      extract_people_collection_progress,
      people_capability_chat_turn,
      people_capability_finalize,
    )
    from financials_consultant import (  # type: ignore
      _adjudicate_revenue_setup,
      estimate_cogs_percent_from_context,
      estimate_marketing_baseline_from_context,
      financials_chat_turn,
      interpret_cogs_reply,
      interpret_initial_lease_reply,
      interpret_marketing_reply,
      interpret_monthly_rent_reply,
      interpret_payroll_reply,
      interpret_future_rent_reply,
      interpret_revenue_option_reply,
      validate_marketing_setup,
      validate_payroll_setup,
    )
    from financials_year1 import (  # type: ignore
      assemble_financials_year1,
      apply_revenue_driver_patch,
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

  trace_run_name = str(request.headers.get("X-Solver-Trace-Run-Name") or "").strip()
  trace_reset_raw = str(request.headers.get("X-Solver-Trace-Reset") or "").strip().lower()
  configure_solver_trace_run(
    trace_run_name,
    reset_file=trace_reset_raw in {"1", "true", "yes", "on"},
  )
  trace_values(
    "REQUEST",
    "Intake consult request received",
    draft_id=str(draft_id).strip(),
    trace_run_name=trace_run_name,
    trace_reset=trace_reset_raw in {"1", "true", "yes", "on"},
    starting=starting,
    has_message=bool(message),
  )

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
    consistency_passed = bool(consult.get("consistency_passed"))
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
      consistency_passed=consistency_passed,
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

    def _persist_consistency_completion(
      *,
      closeout: Dict[str, Any],
      new_messages: List[Dict[str, str]],
      ops_value: Dict[str, Any],
      market_value: Dict[str, Any],
      people_value: Dict[str, Any],
      financials_value: Dict[str, Any],
      financials_year1_value: Dict[str, Any],
      marketing_value: Dict[str, Any],
      persisted_constraint_bundle: Dict[str, Any],
      confirmations_value: Optional[Dict[str, bool]] = None,
      flat_fields_value: Optional[Dict[str, Any]] = None,
      include_fulfillment: bool = False,
      ) -> Dict[str, Any]:
      consistency_modified_plan_json = _require_consistency_modified_plan(closeout)
      consistency_gpt_governance_json = (
        closeout.get("consistency_gpt_governance_json")
        if isinstance(closeout.get("consistency_gpt_governance_json"), dict)
        else {}
      )
      consistency_controller_contract_json = (
        closeout.get("consistency_controller_contract_json")
        if isinstance(closeout.get("consistency_controller_contract_json"), dict)
        else {}
      )
      consistency_solver_execution_json = (
        closeout.get("consistency_solver_execution_json")
        if isinstance(closeout.get("consistency_solver_execution_json"), dict)
        else {}
      )
      model_input_json = (
        closeout.get("model_input_json")
        if isinstance(closeout.get("model_input_json"), dict)
        else {}
      )
      finmo_json = (
        closeout.get("finmo_json")
        if isinstance(closeout.get("finmo_json"), dict)
        else {}
      )
      consistency_finmo_attempts_json = (
        closeout.get("consistency_finmo_attempts_json")
        if isinstance(closeout.get("consistency_finmo_attempts_json"), dict)
        else {}
      )
      return _persist_consistency_modified_plan_completion(
        new_messages=new_messages,
        ops_value=ops_value,
        market_value=market_value,
        people_value=people_value,
        financials_value=financials_value,
        financials_year1_value=financials_year1_value,
        marketing_value=marketing_value,
        persisted_constraint_bundle=persisted_constraint_bundle,
        consistency_modified_plan_json=consistency_modified_plan_json,
        consistency_gpt_governance_json=consistency_gpt_governance_json,
        consistency_controller_contract_json=consistency_controller_contract_json,
        consistency_solver_execution_json=consistency_solver_execution_json,
        model_input_json=model_input_json,
        finmo_json=finmo_json,
        consistency_finmo_attempts_json=consistency_finmo_attempts_json,
        confirmations_value=confirmations_value,
        flat_fields_value=flat_fields_value,
        include_fulfillment=include_fulfillment,
      )

    def _persist_consistency_blocking_closeout(
      *,
      closeout: Dict[str, Any],
      new_messages: List[Dict[str, str]],
      ops_value: Dict[str, Any],
      market_value: Dict[str, Any],
      people_value: Dict[str, Any],
      financials_value: Dict[str, Any],
      financials_year1_value: Dict[str, Any],
      marketing_value: Dict[str, Any],
      persisted_constraint_bundle: Dict[str, Any],
      confirmations_value: Optional[Dict[str, bool]] = None,
      flat_fields_value: Optional[Dict[str, Any]] = None,
      include_fulfillment: bool = False,
    ) -> None:
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
        consistency_modified_plan_json=_valid_consistency_modified_plan_from_closeout(closeout),
        consistency_gpt_governance_json=(
          closeout.get("consistency_gpt_governance_json")
          if isinstance(closeout.get("consistency_gpt_governance_json"), dict)
          else {}
        ),
        consistency_controller_contract_json=(
          closeout.get("consistency_controller_contract_json")
          if isinstance(closeout.get("consistency_controller_contract_json"), dict)
          else {}
        ),
        consistency_solver_execution_json=(
          closeout.get("consistency_solver_execution_json")
          if isinstance(closeout.get("consistency_solver_execution_json"), dict)
          else {}
        ),
        model_input_json=(
          closeout.get("model_input_json")
          if isinstance(closeout.get("model_input_json"), dict)
          else {}
        ),
        finmo_json=(
          closeout.get("finmo_json")
          if isinstance(closeout.get("finmo_json"), dict)
          else {}
        ),
        consistency_finmo_attempts_json=(
          closeout.get("consistency_finmo_attempts_json")
          if isinstance(closeout.get("consistency_finmo_attempts_json"), dict)
          else {}
        ),
        fulfillment_json=fulfillment_json if include_fulfillment else None,
        active_focus="consistency",
        confirmations=confirmations_value,
        business_facts=business_facts,
        consistency_passed=False,
        status="in_progress",
        completed=False,
        flat_fields=flat_fields_value,
        **_constraint_bundle_append_kwargs(persisted_constraint_bundle),
      )

    def _persist_consistency_modified_plan_completion(
      *,
      new_messages: List[Dict[str, str]],
      ops_value: Dict[str, Any],
      market_value: Dict[str, Any],
      people_value: Dict[str, Any],
      financials_value: Dict[str, Any],
      financials_year1_value: Dict[str, Any],
      marketing_value: Dict[str, Any],
      persisted_constraint_bundle: Dict[str, Any],
      consistency_modified_plan_json: Dict[str, Any],
      consistency_gpt_governance_json: Optional[Dict[str, Any]] = None,
      consistency_controller_contract_json: Optional[Dict[str, Any]] = None,
      consistency_solver_execution_json: Optional[Dict[str, Any]] = None,
      model_input_json: Optional[Dict[str, Any]] = None,
      finmo_json: Optional[Dict[str, Any]] = None,
      consistency_finmo_attempts_json: Optional[Dict[str, Any]] = None,
      confirmations_value: Optional[Dict[str, bool]] = None,
      flat_fields_value: Optional[Dict[str, Any]] = None,
      include_fulfillment: bool = False,
    ) -> Dict[str, Any]:
      if not isinstance(consistency_modified_plan_json, dict) or not consistency_modified_plan_json:
        raise RuntimeError("consistency_modified_plan_missing")
      if not isinstance(consistency_gpt_governance_json, dict) or not consistency_gpt_governance_json:
        raise RuntimeError("consistency_gpt_governance_missing")
      if not isinstance(consistency_controller_contract_json, dict) or not consistency_controller_contract_json:
        raise RuntimeError("consistency_controller_contract_missing")
      if not isinstance(consistency_solver_execution_json, dict) or not consistency_solver_execution_json:
        raise RuntimeError("consistency_solver_execution_missing")
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=new_messages,
        operating_model_json=ops_value,
        target_market_json=market_value,
        people_json=people_value,
        financials_json=financials_value,
        financials_year1_json=financials_year1_value,
        **_constraint_bundle_append_kwargs(persisted_constraint_bundle),
        consistency_modified_plan_json=consistency_modified_plan_json,
        consistency_gpt_governance_json=consistency_gpt_governance_json,
        consistency_controller_contract_json=consistency_controller_contract_json,
        consistency_solver_execution_json=consistency_solver_execution_json,
        model_input_json=model_input_json,
        finmo_json=finmo_json,
        consistency_finmo_attempts_json=consistency_finmo_attempts_json,
        fulfillment_json=fulfillment_json if include_fulfillment else None,
        marketing_model_json=marketing_value,
        active_focus="done",
        confirmations=confirmations_value,
        business_facts=business_facts,
        consistency_passed=True,
        status="completed",
        completed=True,
        flat_fields=flat_fields_value,
      )
      persisted_draft = get_draft(conn, draft_id=str(draft_id).strip())
      persisted_modified = _parse_json_value(persisted_draft.get("consistency_modified_plan_json"))
      if not isinstance(persisted_modified, dict) or not persisted_modified:
        raise RuntimeError("consistency_modified_plan_persist_failed")
      if not isinstance(persisted_modified.get("quarter_driver_path"), list) or not persisted_modified.get("quarter_driver_path"):
        raise RuntimeError("consistency_modified_plan_missing_quarter_driver_path")
      if not isinstance(persisted_modified.get("forecast_years"), list) or not persisted_modified.get("forecast_years"):
        raise RuntimeError("consistency_modified_plan_missing_forecast_years")
      if not isinstance(persisted_modified.get("resolution_summary"), dict) or not persisted_modified.get("resolution_summary"):
        raise RuntimeError("consistency_modified_plan_missing_resolution_summary")
      if not isinstance(_parse_json_value(persisted_draft.get("consistency_gpt_governance_json")), dict) or not _parse_json_value(persisted_draft.get("consistency_gpt_governance_json")):
        raise RuntimeError("consistency_gpt_governance_persist_failed")
      if not isinstance(_parse_json_value(persisted_draft.get("consistency_controller_contract_json")), dict) or not _parse_json_value(persisted_draft.get("consistency_controller_contract_json")):
        raise RuntimeError("consistency_controller_contract_persist_failed")
      if not isinstance(_parse_json_value(persisted_draft.get("consistency_solver_execution_json")), dict) or not _parse_json_value(persisted_draft.get("consistency_solver_execution_json")):
        raise RuntimeError("consistency_solver_execution_persist_failed")
      return persisted_modified

    def _transition_financials_to_consistency_via_sql(
      *,
      ops_value: Dict[str, Any],
      market_value: Dict[str, Any],
      people_value: Dict[str, Any],
      financials_value: Dict[str, Any],
      financials_year1_value: Dict[str, Any],
      marketing_value: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[],
        operating_model_json=ops_value,
        target_market_json=market_value,
        people_json=people_value,
        financials_json=financials_value,
        financials_year1_json=financials_year1_value,
        marketing_model_json=marketing_value,
        active_focus="consistency",
        business_facts=business_facts,
      )
      persisted_draft = get_draft(conn, draft_id=str(draft_id).strip())
      persisted_row = dict((persisted_draft or {}).get("row") or {})
      persisted_ops = dict(persisted_row.get("operating_model_json") or ops_value)
      persisted_market = dict(persisted_row.get("target_market_json") or market_value)
      persisted_people = dict(persisted_row.get("people_json") or people_value)
      persisted_financials = dict(persisted_row.get("financials_json") or financials_value)
      persisted_financials_year1 = dict(
        persisted_row.get("financials_year1_json") or financials_year1_value
      )
      persisted_marketing = dict(persisted_row.get("marketing_model_json") or marketing_value)
      if not _financials_ready_for_consistency(
        persisted_financials,
        guardrail_triggered=guardrail_triggered,
      ):
        raise RuntimeError("financials_not_ready_for_consistency_from_sql")
      persisted_shared_context = dict(shared_context or {})
      persisted_shared_context["operating_model"] = persisted_ops
      persisted_shared_context["target_market"] = persisted_market
      persisted_shared_context["people_capability"] = persisted_people
      persisted_shared_context["financials"] = persisted_financials
      persisted_shared_context["financials_year1"] = persisted_financials_year1
      persisted_shared_context["marketing"] = persisted_marketing
      closeout = _maybe_run_consistency_closeout(
        focus_hint="consistency",
        guardrail_triggered=guardrail_triggered,
        conn=conn,
        client_id=client_id,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        business_stage_hint=business_stage_hint,
        current_date_iso=current_date_iso,
        shared_context=persisted_shared_context,
        ops_json=persisted_ops,
        market_json=persisted_market,
        people_json=persisted_people,
        financials_json=persisted_financials,
        financials_year1_json=persisted_financials_year1,
        fulfillment_json=fulfillment_json,
        marketing_model_json=persisted_marketing,
      )
      if not isinstance(closeout, dict):
        raise RuntimeError("consistency_closeout_not_ready")
      return (
        closeout,
        persisted_ops,
        persisted_market,
        persisted_people,
        persisted_financials,
        persisted_financials_year1,
        persisted_marketing,
        persisted_shared_context,
      )

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
        turn, financials_json = _run_financials_turn_and_sync(
          financials_chat_turn=financials_chat_turn,
          route_intent=route_intent,
          interpret_cogs_reply=interpret_cogs_reply,
          interpret_monthly_rent_reply=interpret_monthly_rent_reply,
          interpret_future_rent_reply=interpret_future_rent_reply,
          estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
          interpret_payroll_reply=interpret_payroll_reply,
          validate_payroll_setup=validate_payroll_setup,
          estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
          interpret_marketing_reply=interpret_marketing_reply,
          validate_marketing_setup=validate_marketing_setup,
          interpret_initial_lease_reply=interpret_initial_lease_reply,
          conn=conn,
          intake_context=intake_context,
          conversation_messages=turn_messages,
          business_facts=business_facts,
          shared_context=shared_context,
          last_assistant="",
          user_message="",
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
        )
      elif focus == "consistency":
        closeout = _maybe_run_consistency_closeout(
          focus_hint=focus,
          guardrail_triggered=False,
          conn=conn,
          client_id=client_id,
          draft_id=str(draft_id).strip(),
          business_facts=business_facts,
          business_stage_hint=business_stage_hint,
          current_date_iso=current_date_iso,
          shared_context=shared_context,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          fulfillment_json=fulfillment_json,
          marketing_model_json=_refresh_marketing_model(),
        )
        if not isinstance(closeout, dict):
          raise RuntimeError("consistency_closeout_not_ready")
        ops_json = dict(closeout.get("ops_json") or ops_json)
        market_json = dict(closeout.get("market_json") or market_json)
        people_json = dict(closeout.get("people_json") or people_json)
        financials_json = dict(closeout.get("financials_json") or financials_json)
        financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
        marketing_model_json = dict(closeout.get("marketing_model_json") or _refresh_marketing_model())
        shared_context = dict(closeout.get("shared_context") or shared_context)
        turn = {"assistant_message": closeout.get("assistant_text") or "Continue."}
        focus = "done" if _consistency_closeout_ready_for_completion(closeout) else "consistency"
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

      if focus == "done":
        _persist_consistency_completion(
          closeout=closeout,
          new_messages=[{"role": "assistant", "content": assistant_text}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=marketing_model_json,
          persisted_constraint_bundle=dict(closeout.get("constraint_bundle") or {}),
        )
      elif (
        isinstance(closeout, dict)
        and str((((closeout.get("solver_state") if isinstance(closeout.get("solver_state"), dict) else {}) or {}).get("status") or "")).strip() == "blocking_unresolved"
      ):
        _persist_consistency_blocking_closeout(
          closeout=closeout,
          new_messages=[{"role": "assistant", "content": assistant_text}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=marketing_model_json,
          persisted_constraint_bundle=dict(closeout.get("constraint_bundle") or {}),
        )
      else:
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
          consistency_passed=bool(focus == "done"),
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
      finmo_path_after_confirmation = ensure_draft_finmo_workbook(
        conn,
        draft_id=str(draft_id).strip(),
      )
      if not str(finmo_path_after_confirmation or "").strip():
        return (jsonify({"error": "finmo_workbook_initialization_failed"}), 500)
      consult["finmo_path"] = str(finmo_path_after_confirmation).strip()
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
            from intake_business_types import get_naics_from_business_type  # type: ignore
          except Exception:
            from client_intake_and_finmo.intake_business_types import (  # type: ignore
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
      # Revenue driver edits (financials_year1) should only be interpreted while the
      # user is in the Financials section; otherwise we can incorrectly intercept
      # unrelated edits (e.g., People/HR wage/timing changes) and crash the turn.
      should_check_revenue = (
        str(focus).strip().lower() == "financials"
        and (_should_check_revenue_patch(last_assistant, message) or guardrail_triggered)
      )
      if should_check_revenue:
        pending_revenue_options = _get_pending_revenue_adjustment_options(
          financials_json,
          financials_year1_json,
        )
        selected_revenue_option = False
        selected_option_bundle: Dict[str, Any] = {}
        if pending_revenue_options and last_assistant:
          option_reply = interpret_revenue_option_reply(
            user_message=message,
            last_assistant=last_assistant,
            pending_options=pending_revenue_options,
          )
          if str(option_reply.get("intent_type") or "").strip() == "select_option":
            selected_option_id = str(option_reply.get("selected_option_id") or "").strip()
            for option in pending_revenue_options:
              if str(option.get("option_id") or "").strip() != selected_option_id:
                continue
              selected_option_bundle = option.get("driver_changes") if isinstance(option.get("driver_changes"), dict) else {}
              selected_revenue_option = True
              break

        revenue_intent: Dict[str, Any] = {}
        action = ""
        patch = None
        selected_financials_patch: Dict[str, Any] = {}
        if selected_revenue_option:
          patch = selected_option_bundle.get("financials_year1_patch")
          patch = patch if isinstance(patch, dict) else {}
          selected_financials_patch = selected_option_bundle.get("financials_patch")
          selected_financials_patch = (
            selected_financials_patch if isinstance(selected_financials_patch, dict) else {}
          )
        else:
          revenue_intent = route_intent(
            consult_type="financials_year1",
            user_message=message,
            baseline_json=financials_year1_json,
            shared_context=shared_context,
            recent_messages=recent_messages,
            active_focus="financials",
          )
          action = str(revenue_intent.get("action") or "").strip()
          if action == "edit_patch":
            patch = revenue_intent.get("patch")
          elif action == "confirm_proceed":
            patch = _extract_revenue_proposal_patch(
              last_assistant=last_assistant,
              route_intent=route_intent,
              financials_year1_json=financials_year1_json,
              shared_context=shared_context,
            )
        if (isinstance(patch, dict) and patch) or selected_financials_patch:
          before_year1 = json.loads(json.dumps(financials_year1_json, ensure_ascii=False))
          financials_json.pop("_pending_revenue_adjustment_signature", None)
          financials_json.pop("_pending_revenue_adjustment_options", None)
          if isinstance(patch, dict) and patch:
            revenue_driver_patch = patch
            financials_year1_json = apply_revenue_driver_patch(financials_year1_json, patch)
          if selected_financials_patch:
            for field, value in selected_financials_patch.items():
              field_name = str(field or "").strip()
              if not field_name:
                continue
              financials_json[field_name] = value
          updated_consults, propagated = propagate_shared_facts(
            source_consult_type="financials_year1",
            before_json=before_year1,
            after_json=financials_year1_json,
            consult_jsons={
              "ops": ops_json,
              "target_market": market_json,
              "people": people_json,
              "financials": financials_json,
              "financials_year1": financials_year1_json,
            },
          )
          ops_json = updated_consults.get("ops") or ops_json
          market_json = updated_consults.get("target_market") or market_json
          people_json = updated_consults.get("people") or people_json
          financials_json = updated_consults.get("financials") or financials_json
          financials_year1_json = (
            updated_consults.get("financials_year1") or financials_year1_json
          )
          if propagated:
            shared_context["operating_model"] = ops_json
            shared_context["target_market"] = market_json
            shared_context["people_capability"] = people_json
            shared_context["financials"] = financials_json
            shared_context["financials_year1"] = financials_year1_json

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
          if guardrail_triggered:
            acknowledge_signature(str(draft_id).strip(), driver_signature)
            guardrail_triggered = False

          validation_context = {
            "business_name": business_facts.get("name"),
            "business_start_date": business_facts.get("start_date"),
            "shared_context": shared_context,
            "financials_json": financials_json,
            "financials_year1_json": financials_year1_json,
            "fulfillment_json": fulfillment_json,
            "revenue_guardrail_context_signals": guardrail_signals.get("context_signals") or [],
            "revenue_guardrail_product_signals": guardrail_signals.get("product_signals") or [],
          }
          validation_adjudication = _adjudicate_revenue_setup(validation_context)
          should_lock_revenue = bool(selected_revenue_option)
          if isinstance(validation_adjudication, dict) and validation_adjudication:
            should_lock_revenue = should_lock_revenue or (
              not bool(validation_adjudication.get("requires_adjustment"))
              or bool(validation_adjudication.get("good_to_proceed_without_revenue_change"))
            )
          if should_lock_revenue:
            lock_summary = ""
            if isinstance(validation_adjudication, dict):
              lock_summary = str(
                validation_adjudication.get("plain_language_summary")
                or validation_adjudication.get("proceed_rationale")
                or ""
              ).strip()
            if not lock_summary:
              lock_summary = (
                "This revised revenue setup is now the locked Year-1 baseline for the rest of the "
                "Financials consult, so we can move on to the remaining financial inputs."
              )
            financials_json["_revenue_adjustment_locked_signature"] = driver_signature
            financials_json["_revenue_adjustment_locked_summary"] = lock_summary
            financials_json.pop("_pending_revenue_adjustment_signature", None)
            financials_json.pop("_pending_revenue_adjustment_options", None)
          else:
            financials_json.pop("_revenue_adjustment_locked_signature", None)
            financials_json.pop("_revenue_adjustment_locked_summary", None)
            if selected_revenue_option:
              financials_json.pop("_pending_revenue_adjustment_signature", None)
              financials_json.pop("_pending_revenue_adjustment_options", None)

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
      consistency_passed=consistency_passed,
    )

    baseline_json = {
      "business": business_facts,
      "ops": ops_json,
      "market": market_json,
      "people": people_json,
      "financials": financials_json,
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

    pending_consistency_solver = (
      _get_pending_consistency_solver_state(financials_json)
      if str(focus).strip().lower() == "consistency"
      else None
    )
    blocking_consistency_solver = (
      _get_blocking_consistency_solver_state(financials_json)
      if str(focus).strip().lower() == "consistency"
      else None
    )
    if blocking_consistency_solver and not starting:
      initial_table_markdown = str(blocking_consistency_solver.get("baseline_table_markdown") or "").strip()
      baseline_bundle = (
        ((blocking_consistency_solver.get("state_model") or {}).get("baseline_forecast_bundle") or {})
        if isinstance((blocking_consistency_solver.get("state_model") or {}), dict)
        else {}
      )
      modified_forecast_quarters = [
        q for q in ((baseline_bundle.get("forecast_quarters") if isinstance(baseline_bundle, dict) else []) or [])
        if isinstance(q, dict)
      ]
      financials_json = dict(financials_json or {})
      financials_json.pop("_consistency_solver_state", None)
      persisted_constraint_bundle = _build_constraint_bundle_for_persistence(
        conn=conn,
        intake_context=_build_consistency_runtime_context(
          client_id=client_id,
          draft_id=str(draft_id).strip(),
          business_facts=business_facts,
          business_stage_hint=business_stage_hint,
          current_date_iso=current_date_iso,
          shared_context=shared_context,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          fulfillment_json=fulfillment_json,
          marketing_model_json=marketing_model_json,
        ),
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        marketing_model_json=marketing_model_json,
      )
      consistency_modified_plan_json = _build_consistency_modified_plan_payload(
        solver_state=blocking_consistency_solver,
        selected_scenario=None,
        constraint_bundle=persisted_constraint_bundle,
        initial_ops_json=ops_json,
        initial_market_json=market_json,
        initial_people_json=people_json,
        initial_financials_json=financials_json,
        initial_financials_year1_json=financials_year1_json,
        initial_marketing_model_json=marketing_model_json,
        modified_ops_json=ops_json,
        modified_market_json=market_json,
        modified_people_json=people_json,
        modified_financials_json=financials_json,
        modified_financials_year1_json=financials_year1_json,
        modified_marketing_model_json=marketing_model_json,
        modified_forecast_quarters=modified_forecast_quarters,
      )
      assistant_text = _build_consistency_finalized_message(
        solver_state=blocking_consistency_solver,
        selected_scenario=None,
        initial_table_markdown=initial_table_markdown,
        modified_forecast_quarters=modified_forecast_quarters,
      )
      blocking_gpt_governance_json, blocking_controller_contract_json, blocking_solver_execution_json = _persist_consistency_governance_artifacts(
        conn=conn,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        solver_state=blocking_consistency_solver,
        selected_scenario=None,
        active_focus="consistency",
        constraint_bundle=persisted_constraint_bundle,
      )
      blocking_finmo_attempts_json = _build_consistency_finmo_attempts_payload(
        solver_state=blocking_consistency_solver,
        selected_scenario=None,
      )
      _persist_consistency_modified_plan_completion(
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        ops_value=ops_json,
        market_value=market_json,
        people_value=people_json,
        financials_value=financials_json,
        financials_year1_value=financials_year1_json,
        marketing_value=_refresh_marketing_model(),
        persisted_constraint_bundle=persisted_constraint_bundle,
        consistency_modified_plan_json=consistency_modified_plan_json,
        consistency_gpt_governance_json=blocking_gpt_governance_json,
        consistency_controller_contract_json=blocking_controller_contract_json,
        consistency_solver_execution_json=blocking_solver_execution_json,
        consistency_finmo_attempts_json=blocking_finmo_attempts_json,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "done",
          "awaiting_confirmation": False,
          "done": True,
          "action": "consistency_passed",
          "assistant_message": assistant_text,
        }
      )
    if pending_consistency_solver and not starting:
      selected_scenario_id = str((((pending_consistency_solver.get("scenarios") or [])[0]) or {}).get("scenario_id") or "1").strip() or "1"
      applied_solver = _apply_consistency_solver_choice(
        selected_scenario_id=selected_scenario_id,
        overrides={},
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        marketing_model_json=marketing_model_json,
        solver_state_override=pending_consistency_solver,
      )
      if applied_solver:
        ops_json = dict(applied_solver.get("ops_json") or ops_json)
        people_json = dict(applied_solver.get("people_json") or people_json)
        financials_json = dict(applied_solver.get("financials_json") or financials_json)
        financials_year1_json = dict(applied_solver.get("financials_year1_json") or financials_year1_json)
        marketing_model_json = dict(applied_solver.get("marketing_model_json") or marketing_model_json)
        selected_scenario = applied_solver.get("scenario") if isinstance(applied_solver, dict) else {}
        initial_table_markdown = str((pending_consistency_solver.get("baseline_table_markdown") or "")).strip()
        assistant_text = _build_consistency_finalized_message(
          solver_state=pending_consistency_solver,
          selected_scenario=selected_scenario,
          initial_table_markdown=initial_table_markdown,
          modified_forecast_quarters=[q for q in ((selected_scenario or {}).get("forecast_quarters") or []) if isinstance(q, dict)],
        )
        persisted_constraint_bundle = _build_constraint_bundle_for_persistence(
          conn=conn,
          intake_context=_build_consistency_runtime_context(
            client_id=client_id,
            draft_id=str(draft_id).strip(),
            business_facts=business_facts,
            business_stage_hint=business_stage_hint,
            current_date_iso=current_date_iso,
            shared_context=shared_context,
            ops_json=ops_json,
            market_json=market_json,
            people_json=people_json,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            fulfillment_json=fulfillment_json,
            marketing_model_json=marketing_model_json,
          ),
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          marketing_model_json=marketing_model_json,
        )
        financials_json.pop("_consistency_solver_state", None)
        consistency_modified_plan_json = _build_consistency_modified_plan_payload(
          solver_state=pending_consistency_solver,
          selected_scenario=selected_scenario,
          constraint_bundle=persisted_constraint_bundle,
          initial_ops_json=ops_json,
          initial_market_json=market_json,
          initial_people_json=people_json,
          initial_financials_json=financials_json,
          initial_financials_year1_json=financials_year1_json,
          initial_marketing_model_json=marketing_model_json,
          modified_ops_json=ops_json,
          modified_market_json=market_json,
          modified_people_json=people_json,
          modified_financials_json=financials_json,
          modified_financials_year1_json=financials_year1_json,
          modified_marketing_model_json=marketing_model_json,
          modified_forecast_quarters=[q for q in ((selected_scenario or {}).get("forecast_quarters") or []) if isinstance(q, dict)],
        )
        pending_gpt_governance_json, pending_controller_contract_json, pending_solver_execution_json = _persist_consistency_governance_artifacts(
          conn=conn,
          draft_id=str(draft_id).strip(),
          business_facts=business_facts,
          solver_state=pending_consistency_solver,
          selected_scenario=selected_scenario,
          active_focus="consistency",
          constraint_bundle=persisted_constraint_bundle,
        )
        pending_finmo_attempts_json = _build_consistency_finmo_attempts_payload(
          solver_state=pending_consistency_solver,
          selected_scenario=selected_scenario,
        )
        _persist_consistency_modified_plan_completion(
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=marketing_model_json,
          persisted_constraint_bundle=persisted_constraint_bundle,
          consistency_modified_plan_json=consistency_modified_plan_json,
          consistency_gpt_governance_json=pending_gpt_governance_json,
          consistency_controller_contract_json=pending_controller_contract_json,
          consistency_solver_execution_json=pending_solver_execution_json,
          consistency_finmo_attempts_json=pending_finmo_attempts_json,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "done",
            "awaiting_confirmation": False,
            "done": True,
            "action": "consistency_passed",
            "assistant_message": assistant_text,
            **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
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
    elif (
      str(focus).strip().lower() == "financials"
      and _financials_stage_is_controller_owned(current_financials_stage)
    ):
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
      assistant_text = 'Consistency check is complete and the facts line up well enough to proceed.\n\nClick "Submit intake" to finish.'
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
        if str(focus or "").strip().lower() == "consistency":
          try:
            shared_context = dict(shared_context or {})
            shared_context["operating_model"] = ops_json
            shared_context["target_market"] = market_json
            shared_context["people_capability"] = people_json
            shared_context["financials"] = financials_json
            shared_context["financials_year1"] = financials_year1_json
          except Exception:
            pass
          market_json, marketing_model_json = _sync_marketing_state_after_consistency(
            intake_context={
              "business_name": business_facts.get("name"),
              "business_start_date": business_facts.get("start_date"),
              "shared_context": shared_context,
              "operating_model_json": ops_json,
              "target_market_json": market_json,
              "financials_json": financials_json,
              "financials_year1_json": financials_year1_json,
            },
            market_json=market_json,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            marketing_model_json=_refresh_marketing_model(),
            scenario_context={
              "lever_families": ["marketing"],
              "source": "consistency_edit_patch",
            },
            rewrite_narrative=True,
          )
          shared_context["target_market"] = market_json
          shared_context["marketing"] = marketing_model_json
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

        financials_turn, financials_json = _run_financials_turn_and_sync(
          financials_chat_turn=financials_chat_turn,
          route_intent=route_intent,
          interpret_cogs_reply=interpret_cogs_reply,
          interpret_monthly_rent_reply=interpret_monthly_rent_reply,
          interpret_future_rent_reply=interpret_future_rent_reply,
          estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
          interpret_payroll_reply=interpret_payroll_reply,
          validate_payroll_setup=validate_payroll_setup,
          estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
          interpret_marketing_reply=interpret_marketing_reply,
          validate_marketing_setup=validate_marketing_setup,
          interpret_initial_lease_reply=interpret_initial_lease_reply,
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          business_facts=business_facts,
          shared_context=shared_context,
          last_assistant="",
          user_message="",
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
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
          from intake_business_types import get_naics_from_business_type  # type: ignore
        except Exception:
          from client_intake_and_finmo.intake_business_types import (  # type: ignore
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
      consistency_passed_out = False
      completed_out = False
      confirm_question_live = _detect_confirm_question(last_assistant)

      if str(focus).strip().lower() == "consistency":
        closeout = _maybe_run_consistency_closeout(
          focus_hint=focus,
          guardrail_triggered=guardrail_triggered,
          conn=conn,
          client_id=client_id,
          draft_id=str(draft_id).strip(),
          business_facts=business_facts,
          business_stage_hint=business_stage_hint,
          current_date_iso=current_date_iso,
          shared_context=shared_context,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          fulfillment_json=fulfillment_json,
          marketing_model_json=_refresh_marketing_model(),
        )
        if not isinstance(closeout, dict):
          raise RuntimeError("consistency_closeout_not_ready")
        assistant_text = str(closeout.get("assistant_text") or "").strip()
        ops_json = dict(closeout.get("ops_json") or ops_json)
        market_json = dict(closeout.get("market_json") or market_json)
        people_json = dict(closeout.get("people_json") or people_json)
        financials_json = dict(closeout.get("financials_json") or financials_json)
        financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
        marketing_model_json = dict(closeout.get("marketing_model_json") or _refresh_marketing_model())
        shared_context = dict(closeout.get("shared_context") or shared_context)
        persisted_constraint_bundle = dict(closeout.get("constraint_bundle") or {})
        if _consistency_closeout_ready_for_completion(closeout):
          _persist_consistency_completion(
            closeout=closeout,
            new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
            ops_value=ops_json,
            market_value=market_json,
            people_value=people_json,
            financials_value=financials_json,
            financials_year1_value=financials_year1_json,
            marketing_value=_refresh_marketing_model(),
            persisted_constraint_bundle=persisted_constraint_bundle,
            include_fulfillment=True,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": "done",
              "awaiting_confirmation": False,
              "done": True,
              "action": "consistency_passed",
              "assistant_message": assistant_text,
              **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
            }
          )
        _persist_consistency_blocking_closeout(
          closeout=closeout,
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=_refresh_marketing_model(),
          persisted_constraint_bundle=persisted_constraint_bundle,
          include_fulfillment=True,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "consistency",
            "awaiting_confirmation": False,
            "done": False,
            "action": "consistency_blocked",
            "assistant_message": assistant_text,
            **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
          }
        )

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

        financials_turn, financials_json = _run_financials_turn_and_sync(
          financials_chat_turn=financials_chat_turn,
          route_intent=route_intent,
          interpret_cogs_reply=interpret_cogs_reply,
          interpret_monthly_rent_reply=interpret_monthly_rent_reply,
          interpret_future_rent_reply=interpret_future_rent_reply,
          estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
          interpret_payroll_reply=interpret_payroll_reply,
          validate_payroll_setup=validate_payroll_setup,
          estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
          interpret_marketing_reply=interpret_marketing_reply,
          validate_marketing_setup=validate_marketing_setup,
          interpret_initial_lease_reply=interpret_initial_lease_reply,
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          business_facts=business_facts,
          shared_context=shared_context,
          last_assistant="",
          user_message="",
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
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

      # If the draft was already marked complete, edits must reopen it and trigger
      # a new consistency pass.
      if str(draft_status).strip().lower() == "completed" or focus == "done":
        status_out = "in_progress"
        active_focus_out = "consistency"

      # For edit patches, the intent router is used only to interpret intent and
      # produce the deterministic patch. The domain consultant generates the next
      # conversational turn. Showing both messages causes duplicated acknowledgements
      # and repeated questions.
      #
      # Exception: if the edit re-opens a completed intake into Consistency, keep the
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
          followup_turn, financials_json = _run_financials_turn_and_sync(
            financials_chat_turn=financials_chat_turn,
            route_intent=route_intent,
            interpret_cogs_reply=interpret_cogs_reply,
            interpret_monthly_rent_reply=interpret_monthly_rent_reply,
            interpret_future_rent_reply=interpret_future_rent_reply,
            estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
            interpret_payroll_reply=interpret_payroll_reply,
            validate_payroll_setup=validate_payroll_setup,
            estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
            interpret_marketing_reply=interpret_marketing_reply,
            validate_marketing_setup=validate_marketing_setup,
            interpret_initial_lease_reply=interpret_initial_lease_reply,
            conn=conn,
            intake_context=intake_context_followup,
            conversation_messages=[*messages, user_msg],
            business_facts=business_facts,
            shared_context=shared_context,
            last_assistant="",
            user_message="",
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
          )
          if bool((followup_turn or {}).get("transition_to_consistency")):
            closeout, ops_json, market_json, people_json, financials_json, financials_year1_json, marketing_model_json, shared_context = _transition_financials_to_consistency_via_sql(
              ops_value=ops_json,
              market_value=market_json,
              people_value=people_json,
              financials_value=financials_json,
              financials_year1_value=financials_year1_json,
              marketing_value=_refresh_marketing_model(),
            )
            ops_json = dict(closeout.get("ops_json") or ops_json)
            market_json = dict(closeout.get("market_json") or market_json)
            people_json = dict(closeout.get("people_json") or people_json)
            financials_json = dict(closeout.get("financials_json") or financials_json)
            financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
            marketing_model_json = dict(closeout.get("marketing_model_json") or marketing_model_json)
            shared_context = dict(closeout.get("shared_context") or shared_context)
            followup_turn = {"assistant_message": closeout.get("assistant_text") or ""}
            consistency_passed_out = True
            completed_out = True
            active_focus_out = "done"
            status_out = "completed"
            followup_focus = "consistency"
        elif followup_focus == "consistency":
          if assistant_text:
            assistant_text = f"{assistant_text}\n\nI re-ran the final consistency pass to keep the plan realistic and internally aligned.".strip()
          closeout = _maybe_run_consistency_closeout(
            focus_hint=followup_focus,
            guardrail_triggered=guardrail_triggered,
            conn=conn,
            client_id=client_id,
            draft_id=str(draft_id).strip(),
            business_facts=business_facts,
            business_stage_hint=business_stage_hint,
            current_date_iso=current_date_iso,
            shared_context=shared_context,
            ops_json=ops_json,
            market_json=market_json,
            people_json=people_json,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            fulfillment_json=fulfillment_json,
            marketing_model_json=_refresh_marketing_model(),
          )
          if not isinstance(closeout, dict):
            raise RuntimeError("consistency_closeout_not_ready")
          ops_json = dict(closeout.get("ops_json") or ops_json)
          market_json = dict(closeout.get("market_json") or market_json)
          people_json = dict(closeout.get("people_json") or people_json)
          financials_json = dict(closeout.get("financials_json") or financials_json)
          financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
          marketing_model_json = dict(closeout.get("marketing_model_json") or _refresh_marketing_model())
          shared_context = dict(closeout.get("shared_context") or shared_context)
          followup_turn = {"assistant_message": closeout.get("assistant_text") or ""}
          consistency_passed_out = True
          completed_out = True
          active_focus_out = "done"
          status_out = "completed"
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
                from intake_business_types import get_naics_from_business_type  # type: ignore
              except Exception:
                from client_intake_and_finmo.intake_business_types import (  # type: ignore
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
        if consistency_passed_out:
          if 'Click "Submit intake"' not in assistant_text:
            assistant_text = f'{assistant_text}\n\nClick "Submit intake" to finish.'.strip()

      assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)

      consistency_response_bundle = (
        _build_constraint_bundle_for_persistence(
          conn=conn,
          intake_context=_build_consistency_runtime_context(
            client_id=client_id,
            draft_id=str(draft_id).strip(),
            business_facts=business_facts,
            business_stage_hint=business_stage_hint,
            current_date_iso=current_date_iso,
            shared_context=shared_context,
            ops_json=ops_json,
            market_json=market_json,
            people_json=people_json,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            fulfillment_json=fulfillment_json,
            marketing_model_json=_refresh_marketing_model(),
          ),
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          marketing_model_json=_refresh_marketing_model(),
        )
        if str(focus).strip().lower() == "consistency" or str(active_focus_out).strip().lower() in {"consistency", "done"}
        else {}
      )
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json,
        target_market_json=market_json,
        people_json=people_json if people_patch_applied else None,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        **_constraint_bundle_append_kwargs(consistency_response_bundle),
        fulfillment_json=fulfillment_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=active_focus_out,
        business_facts=business_facts,
        consistency_passed=consistency_passed_out,
        status=status_out,
        completed=completed_out,
        pending_ops_milestone_json=pending_ops_milestone
        if str(active_focus_out).strip().lower() == "ops"
        else None,
        flat_fields=_finalize_flag_field(focus, False),
      )

      action_out = "consistency_passed" if active_focus_out == "done" else "edit_patch"
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
          **_constraint_bundle_response_kwargs(consistency_response_bundle),
        }
      )

    if action == "confirm_proceed":
      closeout = _maybe_run_consistency_closeout(
        focus_hint=focus,
        guardrail_triggered=guardrail_triggered,
        conn=conn,
        client_id=client_id,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        business_stage_hint=business_stage_hint,
        current_date_iso=current_date_iso,
        shared_context=shared_context,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        fulfillment_json=fulfillment_json,
        marketing_model_json=_refresh_marketing_model(),
      )
      if isinstance(closeout, dict):
        assistant_text = str(closeout.get("assistant_text") or "").strip()
        ops_json = dict(closeout.get("ops_json") or ops_json)
        market_json = dict(closeout.get("market_json") or market_json)
        people_json = dict(closeout.get("people_json") or people_json)
        financials_json = dict(closeout.get("financials_json") or financials_json)
        financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
        marketing_model_json = dict(closeout.get("marketing_model_json") or _refresh_marketing_model())
        shared_context = dict(closeout.get("shared_context") or shared_context)
        persisted_constraint_bundle = dict(closeout.get("constraint_bundle") or {})
        if _consistency_closeout_ready_for_completion(closeout):
          _persist_consistency_completion(
            closeout=closeout,
            new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
            ops_value=ops_json,
            market_value=market_json,
            people_value=people_json,
            financials_value=financials_json,
            financials_year1_value=financials_year1_json,
            marketing_value=marketing_model_json,
            persisted_constraint_bundle=persisted_constraint_bundle,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": "done",
              "awaiting_confirmation": False,
              "done": True,
              "action": "consistency_passed",
              "assistant_message": assistant_text,
              **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
            }
          )
        _persist_consistency_blocking_closeout(
          closeout=closeout,
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=marketing_model_json,
          persisted_constraint_bundle=persisted_constraint_bundle,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "consistency",
            "awaiting_confirmation": False,
            "done": False,
            "action": "consistency_blocked",
            "assistant_message": assistant_text,
            **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
          }
        )
      confirmations: Dict[str, bool] = {focus: True}
      next_focus = _next_focus(focus)

      # Generate the first question for the next focus immediately.
      start_instruction = _start_instruction_for_focus(next_focus)
      turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
      next_constraint_bundle: Dict[str, Any] = {}
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
        financials_turn, financials_json = _run_financials_turn_and_sync(
          financials_chat_turn=financials_chat_turn,
          route_intent=route_intent,
          interpret_cogs_reply=interpret_cogs_reply,
          interpret_monthly_rent_reply=interpret_monthly_rent_reply,
          interpret_future_rent_reply=interpret_future_rent_reply,
          estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
          interpret_payroll_reply=interpret_payroll_reply,
          validate_payroll_setup=validate_payroll_setup,
          estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
          interpret_marketing_reply=interpret_marketing_reply,
          validate_marketing_setup=validate_marketing_setup,
          interpret_initial_lease_reply=interpret_initial_lease_reply,
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          business_facts=business_facts,
          shared_context=shared_context,
          last_assistant="",
          user_message="",
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
        )
        next_assistant = str(financials_turn.get("assistant_message") or "").strip()
      elif next_focus == "consistency":
        closeout = _maybe_run_consistency_closeout(
          focus_hint=next_focus,
          guardrail_triggered=guardrail_triggered,
          conn=conn,
          client_id=client_id,
          draft_id=str(draft_id).strip(),
          business_facts=business_facts,
          business_stage_hint=business_stage_hint,
          current_date_iso=current_date_iso,
          shared_context=shared_context,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          fulfillment_json=fulfillment_json,
          marketing_model_json=_refresh_marketing_model(),
        )
        if not isinstance(closeout, dict):
          raise RuntimeError("consistency_closeout_not_ready")
        next_assistant = str(closeout.get("assistant_text") or "").strip()
        ops_json = dict(closeout.get("ops_json") or ops_json)
        market_json = dict(closeout.get("market_json") or market_json)
        people_json = dict(closeout.get("people_json") or people_json)
        financials_json = dict(closeout.get("financials_json") or financials_json)
        financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
        marketing_model_json = dict(closeout.get("marketing_model_json") or _refresh_marketing_model())
        shared_context = dict(closeout.get("shared_context") or shared_context)
        next_constraint_bundle = dict(closeout.get("constraint_bundle") or {})
        next_focus = "done"
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
        **(_constraint_bundle_append_kwargs(next_constraint_bundle) if next_focus == "done" else {}),
        flat_fields=_finalize_flag_field(focus, False),
        consistency_passed=bool(next_focus == "done"),
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
          **(_constraint_bundle_response_kwargs(next_constraint_bundle) if next_focus == "done" else {}),
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
      turn, financials_json = _run_financials_turn_and_sync(
        financials_chat_turn=financials_chat_turn,
        route_intent=route_intent,
        interpret_cogs_reply=interpret_cogs_reply,
        interpret_monthly_rent_reply=interpret_monthly_rent_reply,
        interpret_future_rent_reply=interpret_future_rent_reply,
        estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
        interpret_payroll_reply=interpret_payroll_reply,
        validate_payroll_setup=validate_payroll_setup,
        estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
        interpret_marketing_reply=interpret_marketing_reply,
        validate_marketing_setup=validate_marketing_setup,
        interpret_initial_lease_reply=interpret_initial_lease_reply,
        conn=conn,
        intake_context=intake_context,
        conversation_messages=[*messages, user_msg],
        business_facts=business_facts,
        shared_context=shared_context,
        last_assistant=last_assistant,
        user_message=message,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
      )
    elif focus == "consistency":
      closeout = _maybe_run_consistency_closeout(
        focus_hint=focus,
        guardrail_triggered=guardrail_triggered,
        conn=conn,
        client_id=client_id,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        business_stage_hint=business_stage_hint,
        current_date_iso=current_date_iso,
        shared_context=shared_context,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        fulfillment_json=fulfillment_json,
        marketing_model_json=_refresh_marketing_model(),
      )
      if not isinstance(closeout, dict):
        raise RuntimeError("consistency_closeout_not_ready")
      ops_json = dict(closeout.get("ops_json") or ops_json)
      market_json = dict(closeout.get("market_json") or market_json)
      people_json = dict(closeout.get("people_json") or people_json)
      financials_json = dict(closeout.get("financials_json") or financials_json)
      financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
      marketing_model_json = dict(closeout.get("marketing_model_json") or _refresh_marketing_model())
      shared_context = dict(closeout.get("shared_context") or shared_context)
      turn = {
        "assistant_message": str(closeout.get("assistant_text") or "").strip(),
        "finalize_ready": True,
        "constraint_bundle": dict(closeout.get("constraint_bundle") or {}),
      }
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
          followup_turn, financials_json = _run_financials_turn_and_sync(
            financials_chat_turn=financials_chat_turn,
            route_intent=route_intent,
            interpret_cogs_reply=interpret_cogs_reply,
            interpret_monthly_rent_reply=interpret_monthly_rent_reply,
            interpret_future_rent_reply=interpret_future_rent_reply,
            estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
            interpret_payroll_reply=interpret_payroll_reply,
            validate_payroll_setup=validate_payroll_setup,
            estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
            interpret_marketing_reply=interpret_marketing_reply,
            validate_marketing_setup=validate_marketing_setup,
            interpret_initial_lease_reply=interpret_initial_lease_reply,
            conn=conn,
            intake_context=intake_context,
            conversation_messages=followup_messages,
            business_facts=business_facts,
            shared_context=shared_context,
            last_assistant="",
            user_message="",
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
          )
        elif focus == "consistency":
          closeout = _maybe_run_consistency_closeout(
            focus_hint=focus,
            guardrail_triggered=guardrail_triggered,
            conn=conn,
            client_id=client_id,
            draft_id=str(draft_id).strip(),
            business_facts=business_facts,
            business_stage_hint=business_stage_hint,
            current_date_iso=current_date_iso,
            shared_context=shared_context,
            ops_json=ops_json,
            market_json=market_json,
            people_json=people_json,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            fulfillment_json=fulfillment_json,
            marketing_model_json=_refresh_marketing_model(),
          )
          if not isinstance(closeout, dict):
            raise RuntimeError("consistency_closeout_not_ready")
          ops_json = dict(closeout.get("ops_json") or ops_json)
          market_json = dict(closeout.get("market_json") or market_json)
          people_json = dict(closeout.get("people_json") or people_json)
          financials_json = dict(closeout.get("financials_json") or financials_json)
          financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
          marketing_model_json = dict(closeout.get("marketing_model_json") or _refresh_marketing_model())
          shared_context = dict(closeout.get("shared_context") or shared_context)
          followup_turn = {
            "assistant_message": closeout.get("assistant_text") or "",
            "finalize_ready": True,
            "constraint_bundle": dict(closeout.get("constraint_bundle") or {}),
          }
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

    if focus == "consistency" and finalize_ready:
      closeout = _maybe_run_consistency_closeout(
        focus_hint=focus,
        guardrail_triggered=guardrail_triggered,
        conn=conn,
        client_id=client_id,
        draft_id=str(draft_id).strip(),
        business_facts=business_facts,
        business_stage_hint=business_stage_hint,
        current_date_iso=current_date_iso,
        shared_context=shared_context,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        fulfillment_json=fulfillment_json,
        marketing_model_json=_refresh_marketing_model(),
      )
      if not isinstance(closeout, dict):
        raise RuntimeError("consistency_closeout_not_ready")
      assistant_text = str(closeout.get("assistant_text") or "").strip()
      ops_json = dict(closeout.get("ops_json") or ops_json)
      market_json = dict(closeout.get("market_json") or market_json)
      people_json = dict(closeout.get("people_json") or people_json)
      financials_json = dict(closeout.get("financials_json") or financials_json)
      financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
      marketing_model_json = dict(closeout.get("marketing_model_json") or _refresh_marketing_model())
      shared_context = dict(closeout.get("shared_context") or shared_context)
      persisted_constraint_bundle = dict(closeout.get("constraint_bundle") or {})
      if _consistency_closeout_ready_for_completion(closeout):
        _persist_consistency_completion(
          closeout=closeout,
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=marketing_model_json,
          persisted_constraint_bundle=persisted_constraint_bundle,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "done",
            "awaiting_confirmation": False,
            "done": True,
            "action": "consistency_passed",
            "assistant_message": assistant_text,
            **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
          }
        )
      _persist_consistency_blocking_closeout(
        closeout=closeout,
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        ops_value=ops_json,
        market_value=market_json,
        people_value=people_json,
        financials_value=financials_json,
        financials_year1_value=financials_year1_json,
        marketing_value=marketing_model_json,
        persisted_constraint_bundle=persisted_constraint_bundle,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "consistency",
          "awaiting_confirmation": False,
          "done": False,
          "action": "consistency_blocked",
          "assistant_message": assistant_text,
          **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
        }
      )
    if str(focus).strip().lower() == "financials" and bool(turn.get("transition_to_consistency")):
      closeout, ops_json, market_json, people_json, financials_json, financials_year1_json, marketing_model_json, shared_context = _transition_financials_to_consistency_via_sql(
        ops_value=ops_json,
        market_value=market_json,
        people_value=people_json,
        financials_value=financials_json,
        financials_year1_value=financials_year1_json,
        marketing_value=_refresh_marketing_model(),
      )
      assistant_final = str(closeout.get("assistant_text") or "").strip()
      ops_json = dict(closeout.get("ops_json") or ops_json)
      market_json = dict(closeout.get("market_json") or market_json)
      people_json = dict(closeout.get("people_json") or people_json)
      financials_json = dict(closeout.get("financials_json") or financials_json)
      financials_year1_json = dict(closeout.get("financials_year1_json") or financials_year1_json)
      marketing_model_json = dict(closeout.get("marketing_model_json") or marketing_model_json)
      shared_context = dict(closeout.get("shared_context") or shared_context)
      persisted_constraint_bundle = dict(closeout.get("constraint_bundle") or {})
      if _consistency_closeout_ready_for_completion(closeout):
        _persist_consistency_completion(
          closeout=closeout,
          new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=marketing_model_json,
          persisted_constraint_bundle=persisted_constraint_bundle,
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
            "action": "consistency_passed",
            "assistant_message": assistant_final,
            **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
          }
        )
      _persist_consistency_blocking_closeout(
        closeout=closeout,
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        ops_value=ops_json,
        market_value=market_json,
        people_value=people_json,
        financials_value=financials_json,
        financials_year1_value=financials_year1_json,
        marketing_value=marketing_model_json,
        persisted_constraint_bundle=persisted_constraint_bundle,
        confirmations_value={"financials": True},
        flat_fields_value=_finalize_flag_field("financials", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "consistency",
          "awaiting_confirmation": False,
          "done": False,
          "action": "consistency_blocked",
          "assistant_message": assistant_final,
          **_constraint_bundle_response_kwargs(persisted_constraint_bundle),
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
          from intake_business_types import get_naics_from_business_type  # type: ignore
        except Exception:
          from client_intake_and_finmo.intake_business_types import (  # type: ignore
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
      consistency_passed=False,
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

