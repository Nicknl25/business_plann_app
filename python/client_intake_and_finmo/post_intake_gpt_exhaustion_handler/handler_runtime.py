"""Phase 9 P3.5 — Handler runtime.

Phase 2 implementation: Call 1 (EBITDA anchors) + Call 2 (driver anchors).
Phase 3 will add the iteration loop and deterministic snap-in (this
module exposes a single ``execute_handler`` entry point; later phases
extend it without changing the call-site contract).

GPT calls route through ``call_gpt_with_schema_or_fallback`` so they
share the chokepoint that enforces the per-run GPT budget (Phase 9 P3.5
raised to 8) and the seed/temperature reproducibility settings.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (
  HandlerResult,
  HandlerStatus,
  TOLERANCE_BPS,
  MAX_ITERATIONS,
  HORIZON_QUARTERS,
  GPT_AUTHORED_LEVER_IDS,
  _DRIVER_KEY_TO_LEVER_ID,
  _q1_actual_state,
  _q11_line_items,
  _q11_ebitda_margin,
  _write_gpt_authored_per_quarter_values,
)
from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.prompts import (
  SYSTEM_PROMPT,
  CALL_1_RESPONSE_SCHEMA,
  CALL_2_RESPONSE_SCHEMA,
  build_call_1_user_prompt,
  build_call_2_user_prompt,
)
from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.validators import (
  validate_call_1,
  validate_call_2,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thin user-prompt -> chokepoint adapter.
#
# call_gpt_with_schema_or_fallback in _gpt_critic_io.py expects a
# system_prompt (str) and a user_context (Dict[str, Any]) which it
# JSON-encodes before sending. Our prompts already render to a long
# string. We pass the rendered string under a single key so the wire
# format remains a JSON object (matching the chokepoint's contract).
# ---------------------------------------------------------------------------


def _call_gpt_with_user_prompt(
  *,
  consultant_name: str,
  user_prompt_text: str,
  response_schema: Dict[str, Any],
  schema_name: str,
) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
    call_gpt_with_schema_or_fallback,
  )
  return call_gpt_with_schema_or_fallback(
    consultant_name=consultant_name,
    system_prompt=SYSTEM_PROMPT,
    user_context={"prompt": user_prompt_text},
    response_schema=response_schema,
    schema_name=schema_name,
  )


# ---------------------------------------------------------------------------
# execute_handler: Phase 2 wiring.
# ---------------------------------------------------------------------------


def execute_handler(
  *,
  restoration_result: Any,
  model_input: Dict[str, Any],
  operating_model: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  intake_context: Dict[str, Any],
  finmo_json: Optional[Dict[str, Any]] = None,
) -> HandlerResult:
  """Phase 2 wiring: Call 1 (EBITDA anchors) + Call 2 (driver anchors).

  Returns LANDED_GPT when the GPT-authored drivers produce Q11 EBITDA
  within TOLERANCE_BPS of the GPT Call 1 anchor on the first pass.
  Otherwise returns ITERATING with the FINMO actual recorded; Phase 3
  will replace this branch with the iteration loop and snap-in. Until
  Phase 3 lands, callers see a transparent FAILED status with the
  reason "phase_2_pending_iteration_loop" so the wiring is observable
  end-to-end without claiming success the system did not deliver.
  """
  exhaustion_diagnostic: Dict[str, Any] = {}
  try:
    if hasattr(restoration_result, "to_dict"):
      exhaustion_diagnostic = restoration_result.to_dict()
    elif isinstance(restoration_result, dict):
      exhaustion_diagnostic = dict(restoration_result)
  except Exception:
    exhaustion_diagnostic = {"note": "restoration_result_not_serializable"}

  # 1. Build Q1 actual state from the supplied finmo_json (or rebuild).
  if not isinstance(finmo_json, dict) or not finmo_json:
    try:
      finmo_json = build_finmo(copy.deepcopy(model_input or {}))
    except Exception as exc:
      return HandlerResult(
        status=HandlerStatus.FAILED,
        gpt_calls_made=0,
        provenance={
          "phase": "phase_2_pre_call_finmo_failed",
          "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        },
        reason="finmo_rebuild_failed_before_call_1",
      )
  q1_state = _q1_actual_state(finmo_json or {})

  provenance: Dict[str, Any] = {
    "phase": "phase_2_call_1_call_2",
    "exhaustion_diagnostic": {
      "status": exhaustion_diagnostic.get("status"),
      "q11_ebitda_margin": exhaustion_diagnostic.get("q11_ebitda_margin"),
      "drivers_at_bounds_summary": exhaustion_diagnostic.get("drivers_at_bounds_summary"),
      "reason": exhaustion_diagnostic.get("reason"),
    },
    "q1_state": q1_state,
    "calls": [],
  }

  gpt_calls_made = 0

  # 2. Call 1: EBITDA anchors.
  call_1_user_prompt = build_call_1_user_prompt(
    operating_model=operating_model or {},
    q1_state=q1_state,
  )
  call_1_resp = _call_gpt_with_user_prompt(
    consultant_name="post_intake_gpt_exhaustion_handler_call_1_ebitda",
    user_prompt_text=call_1_user_prompt,
    response_schema=CALL_1_RESPONSE_SCHEMA,
    schema_name="post_intake_gpt_exhaustion_handler_call_1_ebitda",
  )
  gpt_calls_made += 1
  call_1_parsed = call_1_resp.get("parsed") if isinstance(call_1_resp, dict) else None
  call_1_decision = call_1_resp.get("decision_source") if isinstance(call_1_resp, dict) else "unknown"
  call_1_ok, call_1_err = validate_call_1(call_1_parsed)
  provenance["calls"].append({
    "call": "call_1_ebitda_anchors",
    "decision_source": call_1_decision,
    "schema_valid": bool(call_1_ok),
    "schema_error": call_1_err,
    "parsed_summary": (
      {
        "ebitda_anchors": (call_1_parsed or {}).get("ebitda_anchors"),
        "reasoning_chars": len(str((call_1_parsed or {}).get("reasoning") or "")),
      }
      if call_1_ok else None
    ),
  })
  if not call_1_ok:
    return HandlerResult(
      status=HandlerStatus.FAILED,
      gpt_calls_made=gpt_calls_made,
      iterations_used=0,
      q11_ebitda_actual=_q11_ebitda_margin(finmo_json or {}),
      provenance=provenance,
      reason=f"call_1_failed: {call_1_err or call_1_decision}",
    )
  ebitda_anchors = (call_1_parsed or {}).get("ebitda_anchors") or {}
  q11_target = float(ebitda_anchors.get("q11", 0.0))
  q20_target = float(ebitda_anchors.get("q20", q11_target))

  # 3. Call 2: driver anchors. Retry once with the validation error
  # in-prompt if the first attempt fails sanity.
  call_2_parsed, call_2_calls, call_2_err, call_2_decision = _gpt_call_2_with_retry(
    operating_model=operating_model or {},
    q1_state=q1_state,
    call_1_output=call_1_parsed or {},
  )
  gpt_calls_made += call_2_calls
  provenance["calls"].append({
    "call": "call_2_driver_anchors",
    "decision_source": call_2_decision,
    "schema_valid": call_2_parsed is not None,
    "schema_error": call_2_err,
    "calls_used": call_2_calls,
  })
  if not call_2_parsed:
    # Phase 3 will fall through to deterministic snap-in here. Phase 2
    # returns FAILED transparently so the wiring is observable.
    return HandlerResult(
      status=HandlerStatus.FAILED,
      gpt_calls_made=gpt_calls_made,
      iterations_used=0,
      q11_ebitda_target=q11_target,
      q11_ebitda_actual=_q11_ebitda_margin(finmo_json or {}),
      provenance=provenance,
      reason=f"call_2_failed_phase_3_snap_in_pending: {call_2_err or call_2_decision}",
    )

  # 4. Interpolate driver anchors to 20-quarter trajectories and write.
  driver_anchors = (call_2_parsed or {}).get("driver_anchors") or {}
  write_summary = _write_gpt_authored_per_quarter_values(
    model_input=model_input or {},
    driver_anchors=driver_anchors,
    provenance_tag="gpt_call_2_drivers",
  )
  provenance["call_2_write_summary"] = write_summary

  # 5. Rebuild FINMO and check Q11 convergence.
  try:
    rebuilt_finmo = build_finmo(copy.deepcopy(model_input or {}))
  except Exception as exc:
    return HandlerResult(
      status=HandlerStatus.FAILED,
      gpt_calls_made=gpt_calls_made,
      iterations_used=0,
      q11_ebitda_target=q11_target,
      q11_ebitda_actual=None,
      provenance={**provenance, "rebuild_error": f"{type(exc).__name__}: {str(exc)[:200]}"},
      reason="finmo_rebuild_failed_after_call_2",
    )
  q11_actual = _q11_ebitda_margin(rebuilt_finmo or {})
  provenance["post_call_2_q11_ebitda_margin"] = q11_actual
  tolerance_decimal = float(TOLERANCE_BPS) / 10000.0
  if q11_actual is not None and abs(q11_target - float(q11_actual)) <= tolerance_decimal:
    return HandlerResult(
      status=HandlerStatus.LANDED_GPT,
      gpt_calls_made=gpt_calls_made,
      iterations_used=0,
      q11_ebitda_target=q11_target,
      q11_ebitda_actual=float(q11_actual),
      provenance=provenance,
      realism_flags_to_mute=_default_metrics_to_mute(exhaustion_diagnostic),
      reason="call_2_converged_within_tolerance",
    )

  # 6. Phase 2 floor: Phase 3 takes over with iteration loop + snap-in.
  # Until Phase 3 lands, surface the gap in the provenance and return
  # FAILED. Phase 3 will replace this return path with iterate_then_snap.
  try:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.iteration_runtime import (  # type: ignore
      iterate_and_snap,
    )
  except Exception:
    iterate_and_snap = None  # type: ignore
  if iterate_and_snap is None:
    gap = (
      abs(q11_target - float(q11_actual))
      if q11_actual is not None else None
    )
    return HandlerResult(
      status=HandlerStatus.FAILED,
      gpt_calls_made=gpt_calls_made,
      iterations_used=0,
      q11_ebitda_target=q11_target,
      q11_ebitda_actual=q11_actual,
      provenance=provenance,
      reason=(
        "phase_2_pending_iteration_loop: gap_after_call_2 "
        f"target={q11_target} actual={q11_actual} gap={gap}"
      ),
    )
  return iterate_and_snap(
    starting_provenance=provenance,
    starting_call_count=gpt_calls_made,
    call_1_output=call_1_parsed or {},
    most_recent_drivers=driver_anchors,
    operating_model=operating_model or {},
    q1_state=q1_state,
    model_input=model_input or {},
    build_finmo=build_finmo,
    intake_context=intake_context,
    exhaustion_diagnostic=exhaustion_diagnostic,
    q20_target=q20_target,
  )


def _gpt_call_2_with_retry(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  call_1_output: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], int, Optional[str], str]:
  """Run Call 2 once; retry once if validation fails. Returns
  (parsed_or_None, calls_used, last_error, last_decision_source).
  """
  user_prompt = build_call_2_user_prompt(
    operating_model=operating_model,
    q1_state=q1_state,
    call_1_output=call_1_output,
  )
  resp = _call_gpt_with_user_prompt(
    consultant_name="post_intake_gpt_exhaustion_handler_call_2_drivers",
    user_prompt_text=user_prompt,
    response_schema=CALL_2_RESPONSE_SCHEMA,
    schema_name="post_intake_gpt_exhaustion_handler_call_2_drivers",
  )
  parsed = resp.get("parsed") if isinstance(resp, dict) else None
  decision = resp.get("decision_source") if isinstance(resp, dict) else "unknown"
  ok, err = validate_call_2(parsed)
  if ok:
    return parsed, 1, None, decision

  # Retry with the validation error appended so GPT corrects the
  # specific failure mode.
  retry_prompt = (
    user_prompt
    + "\n\nNOTE: Your prior response failed validation: "
    + str(err or "schema_or_sanity_failure")
    + "\nReturn valid JSON matching the schema with all values in plausible ranges."
  )
  resp2 = _call_gpt_with_user_prompt(
    consultant_name="post_intake_gpt_exhaustion_handler_call_2_drivers_retry",
    user_prompt_text=retry_prompt,
    response_schema=CALL_2_RESPONSE_SCHEMA,
    schema_name="post_intake_gpt_exhaustion_handler_call_2_drivers_retry",
  )
  parsed2 = resp2.get("parsed") if isinstance(resp2, dict) else None
  decision2 = resp2.get("decision_source") if isinstance(resp2, dict) else "unknown"
  ok2, err2 = validate_call_2(parsed2)
  if ok2:
    return parsed2, 2, None, decision2
  return None, 2, err2 or err, decision2 or decision


def _default_metrics_to_mute(exhaustion_diagnostic: Dict[str, Any]) -> List[str]:
  """Phase 2 placeholder: mute ebitda_margin (the universal viability
  driver). Phase 4 replaces this with the proper "metric had a hard_fail
  AND its primary_levers include any GPT-authored driver" logic.
  """
  return ["ebitda_margin"]
