"""revise_operating_model — apply the cascade's operating_model levers.

Fork A B1: the executive's pricing / utilization / capacity / productivity
choices (cascade tiers V3/V4/V5, G2/G3/G4, C1/C2/C3/C5) were no-ops because
the operating_model section had no revise_* tool — the SessionDriver logged
the proposal and advanced without mutating the plan. This tool makes those
levers ACTUALLY APPLY.

operating_model levers map to the model_input ``sections.revenue`` rows by
driver (the same write path the deterministic solver uses,
``orchestrator._apply_restoration_to_model_input`` lines 804-828):

    unit_price             -> revenue rows with driver == "Unit Price"
    utilization_rate       -> revenue rows with driver == "Utilization"
    units_per_week_capacity-> revenue rows with driver == "Capacity"

``per_employee_productivity`` is NOT a revenue-row driver: it is
``capacity_units_per_supporting_fte`` in the payroll contract and feeds
payroll-supported Capacity derivation. It is carried on the returned payload
so the session can re-derive capacity from it (see session_factory
propagation); it does not write a revenue row directly.

The tool returns the standard authoring-tool envelope. The caller
(SessionDriver._commit_proposal -> apply_to_plan_state_fn) propagates the
committed levers into the live model_input.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional


# operating_model field -> model_input revenue-row driver.
_FIELD_TO_REVENUE_DRIVER: Dict[str, str] = {
  "unit_price": "Unit Price",
  "utilization_rate": "Utilization",
  "units_per_week_capacity": "Capacity",
}

_PRODUCTIVITY_FIELD = "per_employee_productivity"
_HORIZON = 20


def apply_operating_model_levers_to_model_input(
  model_input_json: Dict[str, Any],
  levers: Dict[str, Any],
) -> Dict[str, Any]:
  """Write operating_model levers into ``sections.revenue`` rows by driver.

  Mutates a deep copy and returns it. Mirrors the index-1..horizon write of
  ``orchestrator._apply_restoration_to_model_input`` (index 0 is the stub).
  Unknown fields and non-positive values are skipped. ``per_employee_productivity``
  is intentionally NOT written here (it is a payroll-capacity input, not a
  revenue row)."""
  mi = copy.deepcopy(model_input_json) if isinstance(model_input_json, dict) else {}
  sections = mi.get("sections")
  revenue_rows = sections.get("revenue") if isinstance(sections, dict) else None
  if not isinstance(revenue_rows, list):
    return mi
  for field, raw_value in (levers or {}).items():
    driver = _FIELD_TO_REVENUE_DRIVER.get(str(field))
    if driver is None:
      continue
    try:
      value = float(raw_value)
    except (TypeError, ValueError):
      continue
    if value <= 0:
      continue
    for row in revenue_rows:
      if not isinstance(row, dict):
        continue
      if str(row.get("driver") or "").strip() != driver:
        continue
      values = row.get("values")
      if not isinstance(values, list) or not values:
        continue
      for idx in range(1, min(_HORIZON + 1, len(values))):
        values[idx] = value
  return mi


def _levers_from_inputs(
  patch: Optional[Dict[str, Any]], proposal: Optional[Any],
) -> Dict[str, Any]:
  """Extract {field: value} operating_model levers from the patch or proposal."""
  levers: Dict[str, Any] = {}
  if isinstance(patch, dict):
    for k, v in patch.items():
      levers[str(k)] = v
  if not levers and proposal is not None:
    field = getattr(proposal, "field", None)
    value = getattr(proposal, "proposed_value", None)
    if field is not None and value is not None:
      levers[str(field)] = value
  return levers


def revise_operating_model(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  current: Optional[Dict[str, Any]] = None,
  patch: Optional[Dict[str, Any]] = None,
  proposal: Optional[Any] = None,
  operating_context: Optional[Dict[str, Any]] = None,
  **_ignore: Any,
) -> Dict[str, Any]:
  """Apply operating_model levers (pricing / utilization / capacity /
  productivity). Returns the authoring envelope; on acceptance the caller
  propagates ``payload`` into the live model_input."""
  levers = _levers_from_inputs(patch, proposal)
  # Keep only recognized operating_model levers.
  recognized = {
    k: v for k, v in levers.items()
    if k in _FIELD_TO_REVENUE_DRIVER or k == _PRODUCTIVITY_FIELD
  }
  if not recognized:
    return {
      "accepted": False,
      "section": "operating_model",
      "payload": None,
      "violations": [{
        "code": "operating_model_no_recognized_lever",
        "message": (
          "expected one of unit_price / utilization_rate / "
          "units_per_week_capacity / per_employee_productivity"
        ),
      }],
      "decision_source": "amalgamated_gpt_supplied",
    }
  # Validate values are positive numbers (in-band enforcement is the
  # cascade proposer's job; this is a structural sanity check).
  clean: Dict[str, float] = {}
  for k, v in recognized.items():
    try:
      fv = float(v)
    except (TypeError, ValueError):
      continue
    if fv > 0:
      clean[k] = fv
  if not clean:
    return {
      "accepted": False,
      "section": "operating_model",
      "payload": None,
      "violations": [{
        "code": "operating_model_nonpositive_value",
        "message": f"operating_model lever value(s) must be positive: {recognized!r}",
      }],
      "decision_source": "amalgamated_gpt_supplied",
    }

  # Commit the revenue-driver levers into the operating_context's live
  # model_input template (the canonical committed model_input), mirroring how
  # set_drivers commits anchors. The session also propagates into its
  # in-cascade live_model_input via apply_operating_model_levers_to_model_input.
  if isinstance(operating_context, dict) and isinstance(operating_context.get("model_input_template"), dict):
    operating_context["model_input_template"] = apply_operating_model_levers_to_model_input(
      operating_context["model_input_template"], clean,
    )

  return {
    "accepted": True,
    "section": "operating_model",
    "payload": clean,
    "violations": [],
    "decision_source": "amalgamated_gpt_supplied",
  }


__all__ = [
  "revise_operating_model",
  "apply_operating_model_levers_to_model_input",
]
