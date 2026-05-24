"""revise_capex_rd_balance_seed — partial-patch variant of the capex/R&D/
balance-seed authoring tool.

The base ``set_capex_rd_balance_seed`` tool already accepts an ``overrides``
argument (a sparse dict the tool applies on top of the deterministic-floor
payload). This revise tool composes the prior overrides with a new patch so
the cascade can carry forward earlier revisions while layering a fresh edit.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from client_intake_and_finmo.post_intake_amalgamated.tools._patch import (
  deep_merge_patch,
)


def revise_capex_rd_balance_seed(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  current_overrides: Optional[Dict[str, Any]] = None,
  patch: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  # Test seam.
  _set_capex_rd_balance_seed: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  if not isinstance(patch, dict) or not patch:
    return {
      "accepted": False,
      "section": "capex_rd_balance_seed",
      "payload": None,
      "overrides_applied": [],
      "violations": [{
        "code": "capex_rd_balance_seed_patch_required",
        "message": "patch dict missing or empty",
      }],
      "decision_source": "amalgamated_gpt_supplied",
      "patch_applied": [],
    }

  base_overrides = current_overrides if isinstance(current_overrides, dict) else {}
  merged, applied = deep_merge_patch(base_overrides, patch)

  setter = _set_capex_rd_balance_seed
  if setter is None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # type: ignore  # noqa: E501
      set_capex_rd_balance_seed,
    )
    setter = set_capex_rd_balance_seed

  envelope = setter(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    overrides=copy.deepcopy(merged),
    business_facts=business_facts,
    ops_json=ops_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
  )
  envelope = dict(envelope) if isinstance(envelope, dict) else {}
  envelope["patch_applied"] = applied
  envelope.setdefault("section", "capex_rd_balance_seed")
  return envelope


__all__ = ["revise_capex_rd_balance_seed"]
