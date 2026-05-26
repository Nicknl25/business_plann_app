"""Shared fixture builders for Contract 5b
(OperatingModelJsonContract sub-contract retrofit) acceptance
tests.

Module is leading-underscore-prefixed so the test runner does
NOT auto-discover it as a test module.

Per spec §6 Commit 5b-1: fixtures provide minimal-valid +
toggle-friendly defaults. Single-LOB top-level-convenience case
is the default (single-product business -- the most common
production shape). Multi-LOB toggle exercises the nullable-
required path per F7.

Fixtures align with the §0 value-constraint policy: payloads
exercise STRUCTURAL shape only; values use simple defaults
(empty strings, 0.0, etc. are FINE -- no value checks to
satisfy).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


# ---------------------------------------------------------------------------
# ProductContract -- 9 fields per intake_consultant.py:91-115
# ---------------------------------------------------------------------------

def valid_product_dict(
  *,
  product_name: str = "Default product",
  unit_cadence: str = "weekly",
  unit_price: float = 100.0,
  operating_periods_per_year: Optional[float] = 52.0,
  utilization_rate: Optional[float] = 0.70,
) -> Dict[str, Any]:
  """ProductContract-shaped dict. 9 fields per
  intake_consultant.py:91-115. Defaults are a single-product
  weekly-cadence service business -- the most common production
  shape."""
  return {
    "product_name": product_name,
    "unit_name": "unit",
    "unit_description": "one unit of service",
    "unit_cadence": unit_cadence,
    "units_per_week_capacity": 40.0,
    "units_per_period_capacity": 40.0,
    "operating_periods_per_year": operating_periods_per_year,
    "utilization_rate": utilization_rate,
    "unit_price": unit_price,
  }


# ---------------------------------------------------------------------------
# LobModelContract -- 2 fields per intake_consultant.py:84-119
# ---------------------------------------------------------------------------

def valid_lob_model_dict(
  *,
  lob_name: str = "Default LOB",
  products: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """LobModelContract-shaped dict. 2 fields. Default 1
  product."""
  if products is None:
    products = [valid_product_dict()]
  return {
    "lob_name": lob_name,
    "products": products,
  }


# ---------------------------------------------------------------------------
# MilestoneContract -- 2 fields per intake_consultant.py:141-148
# ---------------------------------------------------------------------------

def valid_milestone_dict(
  *,
  description: str = "Open second location",
  timing: str = "2027 Q1",
) -> Dict[str, Any]:
  """MilestoneContract-shaped dict. 2 fields."""
  return {
    "description": description,
    "timing": timing,
  }


# ---------------------------------------------------------------------------
# Top-level OperatingModelJsonContract -- 27 typed fields
# ---------------------------------------------------------------------------

def valid_operating_model_json_dict(
  *,
  include_lob_models: bool = False,
  include_milestones: bool = True,
  include_production_extras: bool = True,
  **overrides: Any,
) -> Dict[str, Any]:
  """OperatingModelJsonContract-shaped dict. 27 typed fields by
  default (when all toggles on).

  Defaults: single-product top-level convenience case --
  top-level unit_* fields populated (per system prompt at
  intake_consultant.py:636-639 single-LOB-single-product
  branch); ``lob_models`` is None (toggle on for multi-LOB
  case); ``milestones`` populated with 1 entry; all 4
  production extras present.

  Per F7: 10 nullable-required schema fields all type as
  Optional[X] = None. Defaults populate them with non-null
  values for single-product case readability; tests can pass
  None explicitly via overrides.

  **overrides applied last -- caller can override any field.
  """
  payload: Dict[str, Any] = {
    # --- 13 non-nullable required schema fields ---
    "consumer_type": "consumer",
    "business_type": "Coffee shop",
    "business_description_summary": (
      "A neighborhood coffee shop with daily walk-in customers."
    ),
    "shipping_method": "in-store pickup",
    "sales_modality": "physical",
    "geographic_scope": "local",
    "geographic_coverage": "Brooklyn NY",
    "countries": ["US"],
    "milestones": (
      [valid_milestone_dict()] if include_milestones else []
    ),
    "capacity_driver": "labor",
    "primary_growth_lever": "Daily transactions per location",
    "legal_entity": "LLC",
    "confidence": 0.85,
    # --- 10 nullable-required schema fields (populated for single-product case) ---
    "business_stage": "operating",
    "lob_models": (
      [valid_lob_model_dict()] if include_lob_models else None
    ),
    "unit_name": "cup",
    "unit_description": "one prepared beverage",
    "unit_cadence": "weekly",
    "units_per_week_capacity": 500.0,
    "units_per_period_capacity": 500.0,
    "operating_periods_per_year": 52.0,
    "utilization_rate": 0.65,
    "unit_price": 5.50,
  }
  if include_production_extras:
    payload.update({
      "business_naics_6": "722515",
      "competitive_advantage": "Local roastery sourcing",
      "business_type_candidates": ["Coffee shop", "Cafe"],
      "business_type_candidates_locked": True,
    })
  payload.update(overrides)
  return payload


__all__ = [
  "valid_product_dict",
  "valid_lob_model_dict",
  "valid_milestone_dict",
  "valid_operating_model_json_dict",
]
