"""Shared fixture builders for Contract 5c
(TargetMarketJsonContract sub-contract retrofit) acceptance
tests.

Module is leading-underscore-prefixed so the test runner does
NOT auto-discover it as a test module.

Per spec §6 Commit 5c-1: fixtures provide minimal-valid +
toggle-friendly defaults. Consumer-only profile is the default
(simplest path -- 4 non-nullable required fields populated, all
7 nullable-required fields default to None per F6 / production-
reality-wins). Toggles enable b2b/mixed cases with the b2b_*
arrays + 3 CSV extras.

Fixtures align with the §0 value-constraint policy: payloads
exercise STRUCTURAL shape only; values use simple defaults
(empty strings, 0.0, [] are FINE -- no value checks to
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
# GenderAgeIntentEntry -- 3 fields per target_market_consultant.py:139-151
# ---------------------------------------------------------------------------

def valid_gender_age_intent_entry_dict(
  *,
  gender_focus: str = "all",
  age_min: float = 25.0,
  age_max: float = 65.0,
) -> Dict[str, Any]:
  """GenderAgeIntentEntry-shaped dict. Defaults: all-gender, 25-65."""
  return {
    "gender_focus": gender_focus,
    "age_min": age_min,
    "age_max": age_max,
  }


# ---------------------------------------------------------------------------
# IncomeIntentEntry -- 2 fields per target_market_consultant.py:155-164
# ---------------------------------------------------------------------------

def valid_income_intent_entry_dict(
  *,
  income_min: float = 30000.0,
  income_max: float = 120000.0,
) -> Dict[str, Any]:
  """IncomeIntentEntry-shaped dict."""
  return {
    "income_min": income_min,
    "income_max": income_max,
  }


# ---------------------------------------------------------------------------
# SelectionsEntry -- 2 fields per target_market_consultant.py:167-184
# ---------------------------------------------------------------------------

def valid_selections_entry_dict(
  *,
  segment: str = "Education",
  acs_codes: Optional[List[Any]] = None,
) -> Dict[str, Any]:
  """SelectionsEntry-shaped dict."""
  if acs_codes is None:
    acs_codes = ["B15003_017E", "B15003_022E"]
  return {
    "segment": segment,
    "acs_codes": acs_codes,
  }


# ---------------------------------------------------------------------------
# Top-level TargetMarketJsonContract -- 14 typed fields
# ---------------------------------------------------------------------------

def valid_target_market_json_dict(
  *,
  consumer_type: str = "consumer",
  include_gender_age: bool = True,
  include_income: bool = True,
  include_selections: bool = True,
  include_b2b_arrays: bool = False,
  include_csv_extras: bool = False,
  include_target_market_summary: bool = False,
  **overrides: Any,
) -> Dict[str, Any]:
  """TargetMarketJsonContract-shaped dict. Default profile
  matches the PRODUCTION POST-POP shape per F1 / T3 (mirrors
  5d ``valid_people_json_dict`` post-pop default):
    - 3 non-nullable required schema fields populated
      (consumer_type, marketing_plan_summary, confidence)
    - ``target_market_summary`` OMITTED (popped at
      intake_consult.py:10863 before persistence -- mirrors
      key_people_summary pop at intake_consult.py:6241)
    - 3 consumer-side nullable arrays populated with one entry
      each; 4 b2b_* arrays + 3 CSV extras omitted

  Toggle ``include_target_market_summary`` exercises the
  contract's PSL2 acceptance of BOTH presence + absence of this
  field (mirrors 5d ``include_key_people_summary``).
  Toggles ``include_b2b_arrays`` + ``include_csv_extras`` enable
  b2b/mixed cases.

  Per F6: 7 nullable-required schema fields all type as
  Optional[X] = None. Defaults populate the 3 consumer-side
  fields with non-null values for readability; omit the 4 b2b_*
  fields entirely (defaults to None via Pydantic).

  **overrides applied last -- caller can override any field.
  """
  payload: Dict[str, Any] = {
    # --- 3 non-nullable required ---
    "consumer_type": consumer_type,
    "marketing_plan_summary": (
      "Word-of-mouth + neighborhood events + Instagram Reels."
    ),
    "confidence": 0.85,
  }
  if include_target_market_summary:
    payload["target_market_summary"] = (
      "Local consumers interested in specialty coffee and community spaces."
    )
  if include_gender_age:
    payload["gender_age_intent"] = [valid_gender_age_intent_entry_dict()]
  if include_income:
    payload["income_intent"] = [valid_income_intent_entry_dict()]
  if include_selections:
    payload["selections"] = [valid_selections_entry_dict()]
  if include_b2b_arrays:
    payload.update({
      "b2b_industry_terms": ["specialty food service", "cafes"],
      "b2b_naics_6": ["722515", "722513"],
      "b2b_size_bands": ["1-4", "5-9", "10-19"],
      "b2b_age_bands": ["3", "4", "5"],
    })
  if include_csv_extras:
    payload.update({
      "target_market_b2b_industry": "722515,722513",
      "target_market_b2b_size": "1-4,5-9,10-19",
      "target_market_b2b_age": "3,4,5",
    })
  payload.update(overrides)
  return payload


__all__ = [
  "valid_gender_age_intent_entry_dict",
  "valid_income_intent_entry_dict",
  "valid_selections_entry_dict",
  "valid_target_market_json_dict",
]
