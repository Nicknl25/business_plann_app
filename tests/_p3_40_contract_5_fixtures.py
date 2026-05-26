"""Shared fixture builders for Contract 5 (IntakeDraftContract)
acceptance tests. Same single-source-of-truth pattern as
Contracts 1-4 fixture modules.

Module is leading-underscore-prefixed so the test runner does NOT
auto-discover it as a test module.

Re-uses Contract 5b fixture ``valid_operating_model_json_dict``
per Commit 5b-3 retrofit + Contract 5c fixture
``valid_target_market_json_dict`` per Commit 5c-3 retrofit
(operating_model_json + target_market_json now typed via their
respective sub-contracts instead of Dict[str, Any]). The
remaining 6 fields stay opaque Dict[str, Any] per spec Flag 0
(b) first cut -- Contracts 5d/5e/etc. retrofits will follow
the 5b/5c precedent.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from _p3_40_contract_5b_fixtures import (  # noqa: E402
  valid_operating_model_json_dict,
)
from _p3_40_contract_5c_fixtures import (  # noqa: E402
  valid_target_market_json_dict,
)


# ---------------------------------------------------------------------------
# Top-level IntakeDraftContract
# ---------------------------------------------------------------------------

def valid_intake_draft_dict(
  *,
  include_fulfillment_json: bool = True,
) -> Dict[str, Any]:
  """Build a valid IntakeDraftContract dict.

  Defaults populate all 8 fields. ``include_fulfillment_json``
  toggle exercises the Optional Tier-F fulfillment_json field
  per spec Flag 1 (a).

  All field values are minimal-but-non-empty arbitrary dicts.
  Sub-shape typing is deferred per F0 (b) -- the contract accepts
  Dict[str, Any], so any dict (including {}) is structurally
  valid. Using non-empty payloads here makes test assertions
  more readable (clear which field is being tested).
  """
  payload: Dict[str, Any] = {
    "operating_model_json": valid_operating_model_json_dict(),
    "target_market_json": valid_target_market_json_dict(),
    "people_json": {
      "people": [],
      "inferred_roles": [],
    },
    "financials_json": {
      "gross_margin_percent": 0.40,
    },
    "financials_year1_json": {
      "company_revenue_total_year1": 1000000.0,
      "lobs": [],
    },
    "marketing_model_json": {
      "version": 3,
    },
    "planning_context_summary_json": {
      "planning_mode": "growth",
    },
  }
  if include_fulfillment_json:
    payload["fulfillment_json"] = {
      "fulfillment_model": "test",
    }
  return payload
