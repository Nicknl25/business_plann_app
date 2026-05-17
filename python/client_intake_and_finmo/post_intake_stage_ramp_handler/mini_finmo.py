"""Iter 19 Stage 5 — Stage ramp handler mini-FINMO mirror.

For the stage ramp handler the "probe" is the production stage ramp
validator itself (``_validate_stage_ramp_contract_payload``). Unlike
the exhaustion handler (which probes against mini-FINMO because full
FINMO would be too expensive) and the funding handler (which probes
against a simplified cash projection), the stage ramp validator is
already lightweight pure-Python — running it directly per turn is
the right shape.

This module exposes thin helpers that wrap the validator with the
exact signature the tool-calling session uses, so the session loop
can swap mocks in for tests without monkey-patching the production
validator.

Per docs/architecture/doctrine.md §4 Flavor 3 (mini / shadow object):
the production validator IS the canonical probe; this module is the
documentation-and-wiring layer that makes the shape explicit.
"""

from __future__ import annotations

from typing import Any, Callable, Dict


def probe_stage_ramp_contract(
  *,
  candidate: Dict[str, Any],
  expected_stage_family: str,
  business_stage: str,
  planning_mode: str,
  planning_mode_reason: str,
  r_and_d_enabled: bool,
  validator: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
  """Probe a candidate stage_ramp_contract via the production
  validator. Returns ``{validator_accepted, validator_error_text}``.

  Used by :mod:`tool_calling_session` to drive the per-turn
  acceptance check. The validator argument is injected so tests can
  pass mocks.
  """
  try:
    validator(
      payload=candidate,
      expected_stage_family=expected_stage_family,
      business_stage=business_stage,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      r_and_d_enabled=r_and_d_enabled,
    )
    return {"validator_accepted": True, "validator_error_text": None}
  except RuntimeError as exc:
    return {"validator_accepted": False, "validator_error_text": str(exc)}
