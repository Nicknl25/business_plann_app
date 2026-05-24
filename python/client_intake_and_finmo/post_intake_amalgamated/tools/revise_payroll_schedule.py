"""revise_payroll_schedule — partial-patch variant of ``set_payroll_schedule``.

Used by VIABILITY V6 (payroll restructure), CAPACITY C3 (headcount alignment),
and any coherence reconciliation that touches headcount. Deep-merges a sparse
patch onto the currently committed payroll contract and defers to
``set_payroll_schedule`` for validator + builder.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from client_intake_and_finmo.post_intake_amalgamated.tools._patch import (
  deep_merge_patch,
)


def revise_payroll_schedule(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  current_contract: Optional[Dict[str, Any]] = None,
  patch: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  policy_code: str = "default",
  # Test seam.
  _set_payroll_schedule: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  if not isinstance(current_contract, dict) or not current_contract:
    return {
      "accepted": False,
      "section": "payroll",
      "contract": None,
      "payload": None,
      "violations": [{
        "code": "no_current_payroll_contract",
        "message": (
          "revise_payroll_schedule requires a currently-committed contract "
          "to patch. Call set_payroll_schedule first."
        ),
      }],
      "bands_echoed": {},
      "decision_source": "amalgamated_session_pending",
      "patch_applied": [],
    }
  if not isinstance(patch, dict) or not patch:
    return {
      "accepted": False,
      "section": "payroll",
      "contract": None,
      "payload": None,
      "violations": [{
        "code": "payroll_patch_required",
        "message": "patch dict missing or empty",
      }],
      "bands_echoed": {},
      "decision_source": "amalgamated_gpt_supplied",
      "patch_applied": [],
    }

  merged, applied = deep_merge_patch(current_contract, patch)

  setter = _set_payroll_schedule
  if setter is None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (  # type: ignore  # noqa: E501
      set_payroll_schedule,
    )
    setter = set_payroll_schedule

  envelope = setter(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    contract=copy.deepcopy(merged),
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people_json,
    model_input_json=model_input_json,
    policy_code=policy_code,
  )
  envelope = dict(envelope) if isinstance(envelope, dict) else {}
  envelope["patch_applied"] = applied
  envelope.setdefault("section", "payroll")
  return envelope


__all__ = ["revise_payroll_schedule"]
