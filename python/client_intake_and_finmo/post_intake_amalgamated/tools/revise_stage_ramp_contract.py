"""revise_stage_ramp_contract — partial-patch variant of
``set_stage_ramp_contract``.

The cascade's stage-ramp revision steps (spec §5.1 V2 ramp tuning, §5.2 G1
ramp reshape, §5.5 H2 coherence reconciliation) modify a small slice of the
already-committed contract grid. Rather than asking the proposer / GPT to
re-author the entire payload they hand a sparse patch to this tool, which:

  1. Deep-merges the patch onto the currently-committed contract.
  2. Defers to ``set_stage_ramp_contract`` for cohort-band + schema
     validation + robust-bound clip + commit (no logic duplication).
  3. Returns the standard authoring-tool envelope with one extra field,
     ``patch_applied``: the list of dotted paths the patch touched.

Rejection still does NOT mutate state. The cascade caller decides whether
to advance the tier (spec §8.1: any rejection from this tool is a tier-
advance trigger).
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from client_intake_and_finmo.post_intake_amalgamated.tools._patch import (
  deep_merge_patch,
)


def revise_stage_ramp_contract(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  current_contract: Optional[Dict[str, Any]] = None,
  patch: Optional[Dict[str, Any]] = None,
  # Passthrough to set_stage_ramp_contract — needed for the validator and
  # the robust-bound clip on the merged candidate.
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  planning_mode_reason: str = "",
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  r_and_d_applicability: Optional[Dict[str, Any]] = None,
  expected_stage_family: str = "",
  # Test seam — production callers pass None.
  _set_stage_ramp_contract: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """Apply a sparse patch to the currently committed stage_ramp contract
  and re-validate via ``set_stage_ramp_contract``.

  Returns the authoring envelope::

    {
      "accepted": bool,
      "section": "stage_ramp",
      "contract": <validated contract>|None,
      "violations": [...],
      "bands_echoed": {...},
      "decision_source": "amalgamated_gpt_supplied"|...,
      "patch_applied": ["<dotted-path>", ...],
    }
  """
  if not isinstance(current_contract, dict) or not current_contract:
    return {
      "accepted": False,
      "section": "stage_ramp",
      "contract": None,
      "violations": [{
        "code": "no_current_stage_ramp_contract",
        "message": (
          "revise_stage_ramp_contract requires a currently-committed contract "
          "to patch. Call set_stage_ramp_contract first."
        ),
      }],
      "bands_echoed": {},
      "decision_source": "amalgamated_session_pending",
      "patch_applied": [],
    }
  if not isinstance(patch, dict) or not patch:
    return {
      "accepted": False,
      "section": "stage_ramp",
      "contract": None,
      "violations": [{
        "code": "stage_ramp_patch_required",
        "message": "patch dict missing or empty",
      }],
      "bands_echoed": {},
      "decision_source": "amalgamated_gpt_supplied",
      "patch_applied": [],
    }

  merged, applied = deep_merge_patch(current_contract, patch)

  setter = _set_stage_ramp_contract
  if setter is None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # type: ignore  # noqa: E501
      set_stage_ramp_contract,
    )
    setter = set_stage_ramp_contract

  envelope = setter(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    contract=copy.deepcopy(merged),
    business_facts=business_facts,
    ops_json=ops_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    people_json=people_json,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    r_and_d_applicability=r_and_d_applicability,
    expected_stage_family=expected_stage_family,
  )
  envelope = dict(envelope) if isinstance(envelope, dict) else {}
  envelope["patch_applied"] = applied
  envelope.setdefault("section", "stage_ramp")
  return envelope


__all__ = ["revise_stage_ramp_contract"]
