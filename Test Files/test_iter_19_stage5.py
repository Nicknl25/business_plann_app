"""Iter 19 Stage 5 tests — stage ramp adaptation.

Covers:
  - Python deterministic builder (build_python_stage_ramp_contract)
    produces a contract that passes the production validator for a
    healthy retail NAICS.
  - The builder is total: missing NAICS coverage falls back to
    conservative defaults rather than raising.
  - Stage ramp handler GPT tool-calling session shape:
    verified-commit / best-effort / failed-precondition branches,
    extension budget, tool definition.
  - Two-stage handler pipeline: Python first; GPT escalates only on
    validator rejection.
  - Production wiring: intake_consult passes the new wrapper as the
    estimate_stage_ramp_contract_with_gpt dependency.

Mocked GPT turns. No live OpenAI. No MySQL.

Run: ``.venv\\Scripts\\python.exe "Test Files\\test_iter_19_stage5.py"``
"""

from __future__ import annotations

import copy
import json
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_contracts.runner import (  # noqa: E402
  _validate_stage_ramp_contract_payload,
  build_python_stage_ramp_contract,
)
from client_intake_and_finmo.post_intake_stage_ramp_handler import (  # noqa: E402
  StageRampHandlerResult,
  StageRampHandlerStatus,
  engage_stage_ramp_handler_on_validator_failure,
  run_stage_ramp_handler,
)
from client_intake_and_finmo.post_intake_stage_ramp_handler import (  # noqa: E402
  handler as _sr_handler,
  mini_finmo as _sr_mini_finmo,
  prompts as _sr_prompts,
  tool_calling_session as _sr_session,
)


_RESULTS: List[Tuple[str, bool, str]] = []


def _run(name: str, fn: Callable[[], None]) -> None:
  try:
    fn()
    _RESULTS.append((name, True, ""))
    print(f"  PASS  {name}")
  except AssertionError as exc:
    _RESULTS.append((name, False, str(exc)))
    print(f"  FAIL  {name}: {exc}")
  except Exception as exc:
    _RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
    print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    traceback.print_exc()


# --------------------------------------------------------------------------
# Python builder — total + cohort-driven.
# --------------------------------------------------------------------------


def test_python_builder_returns_validator_compliant_contract_for_retail() -> None:
  contract = build_python_stage_ramp_contract(
    business_facts={"start_date": "2018-01-01"},
    ops_json={"business_naics_6": "455211", "business_stage": "operational"},
    financials_json={"initial_assets": 250_000},
    financials_year1_json={"company_revenue_total_year1": 2_000_000},
    planning_mode="growth",
    planning_mode_reason="organic expansion",
    r_and_d_applicability={"r_and_d_enabled": False},
  )
  # The contract must validate against the production validator.
  validated = _validate_stage_ramp_contract_payload(
    payload=contract,
    expected_stage_family="operational",
    business_stage="operational",
    planning_mode="growth",
    planning_mode_reason="organic expansion",
    r_and_d_enabled=False,
  )
  assert isinstance(validated, dict)
  # rd_max must be 0 throughout when R&D is disabled.
  for row in contract["quarter_ramp_grid"]:
    assert row["rd_max"] == 0.0


def test_python_builder_total_on_missing_naics_coverage() -> None:
  contract = build_python_stage_ramp_contract(
    business_facts={},
    ops_json={},  # no NAICS
    financials_json={},
    financials_year1_json={},
    planning_mode="growth",
    planning_mode_reason="",
    r_and_d_applicability={"r_and_d_enabled": True},
  )
  # Builder returns a validator-clean dict (no provenance fields);
  # provenance is added by engage_stage_ramp_handler_on_validator_
  # failure after validation. Builder output must NOT contain
  # undeclared fields per the contract table.
  assert isinstance(contract, dict)
  assert "decision_source" not in contract
  assert "stage_family" in contract
  assert "utilization_high_watermark" in contract
  assert len(contract["quarter_ramp_grid"]) == 20
  assert "rationale" in contract


def test_python_builder_produces_non_decreasing_utilization() -> None:
  contract = build_python_stage_ramp_contract(
    business_facts={"start_date": "2018-01-01"},
    ops_json={"business_naics_6": "455211", "business_stage": "operational"},
    financials_json={},
    financials_year1_json={},
    planning_mode="growth",
    planning_mode_reason="",
    r_and_d_applicability={"r_and_d_enabled": False},
  )
  utils = [float(row["max_util"]) for row in contract["quarter_ramp_grid"]]
  for prev, curr in zip(utils, utils[1:]):
    assert curr >= prev - 1e-9, f"utilization regressed: {prev} -> {curr}"


def test_python_builder_operational_postures_match_policy() -> None:
  contract = build_python_stage_ramp_contract(
    business_facts={"start_date": "2018-01-01"},
    ops_json={"business_naics_6": "455211", "business_stage": "operational"},
    financials_json={},
    financials_year1_json={},
    planning_mode="growth",
    planning_mode_reason="",
    r_and_d_applicability={"r_and_d_enabled": False},
  )
  postures = [row["posture"] for row in contract["quarter_ramp_grid"]]
  # Operational stage: every posture must be in the allowed set.
  allowed = {"loss_allowed", "improving_losses", "near_breakeven", "positive"}
  for p in postures:
    assert p in allowed


# --------------------------------------------------------------------------
# Mocks for GPT tool-calling.
# --------------------------------------------------------------------------


def _make_mock_gpt_turn(scripted: List[Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
  state = {"i": 0}

  def _mock(**kwargs: Any) -> Dict[str, Any]:
    if state["i"] >= len(scripted):
      return {
        "tool_calls": [],
        "raw_assistant_items": [],
        "decision_source": "python_proposer_plus_gpt_critic",
        "detail": "",
      }
    resp = scripted[state["i"]]
    state["i"] += 1
    return resp

  return _mock


def _tool_call_with_contract(contract: Dict[str, Any], call_id: str = "c1") -> Dict[str, Any]:
  return {
    "tool_calls": [
      {
        "name": "probe_stage_ramp_contract",
        "call_id": call_id,
        "arguments": json.dumps(contract),
      }
    ],
    "raw_assistant_items": [
      {
        "type": "function_call",
        "name": "probe_stage_ramp_contract",
        "call_id": call_id,
        "arguments": json.dumps(contract),
      }
    ],
    "decision_source": "python_proposer_plus_gpt_critic",
    "detail": "",
  }


def _stop_response() -> Dict[str, Any]:
  return {
    "tool_calls": [],
    "raw_assistant_items": [{"role": "assistant", "content": [{"type": "output_text", "text": "stop"}]}],
    "decision_source": "python_proposer_plus_gpt_critic",
    "detail": "",
  }


def _mock_validator_factory(*, accept_first: bool = True):
  """Validator mock that accepts the first call, then rejects after.
  ``accept_first=False`` always rejects."""
  state = {"calls": 0}

  def _v(**kwargs):
    state["calls"] += 1
    if accept_first and state["calls"] == 1:
      return {}
    raise RuntimeError("synthetic_validator_rejection: cogs_max out of band")

  return _v


# --------------------------------------------------------------------------
# Tool-calling session unit tests.
# --------------------------------------------------------------------------


def test_session_verified_when_validator_accepts_first_probe() -> None:
  mock_gpt = _make_mock_gpt_turn([
    _tool_call_with_contract({"placeholder": True}, "c1"),
    _stop_response(),
  ])
  result = _sr_session.run_stage_ramp_tool_calling_session(
    python_contract={"stage_family": "operational"},
    validator_error_text="initial python rejection",
    _call_gpt_turn=mock_gpt,
    _validator=_mock_validator_factory(accept_first=True),
  )
  assert result.status == "verified"
  assert result.tool_calls_used == 1
  assert result.verified_commit_call_n == 1


def test_session_hard_cap_with_best_effort_no_acceptance() -> None:
  # 15 probes, validator always rejects → hard cap = 10 reached.
  scripted = [_tool_call_with_contract({"attempt": i}, f"c{i}") for i in range(15)]
  mock_gpt = _make_mock_gpt_turn(scripted)
  result = _sr_session.run_stage_ramp_tool_calling_session(
    python_contract={"stage_family": "operational"},
    validator_error_text="initial python rejection",
    _call_gpt_turn=mock_gpt,
    _validator=_mock_validator_factory(accept_first=False),
  )
  assert result.status == "best_effort_no_acceptance"
  assert result.tool_calls_used == _sr_session.HARD_CAP_TOOL_CALLS
  assert result.budget_extension_triggered is True


def test_session_failed_precondition_when_gpt_never_calls_tool() -> None:
  mock_gpt = _make_mock_gpt_turn([_stop_response()])
  result = _sr_session.run_stage_ramp_tool_calling_session(
    python_contract={"stage_family": "operational"},
    validator_error_text="x",
    _call_gpt_turn=mock_gpt,
    _validator=_mock_validator_factory(accept_first=False),
  )
  assert result.status == "failed_precondition"
  assert result.tool_calls_used == 0


def test_session_tool_definition_includes_full_grid_shape() -> None:
  tool_def = _sr_session._build_tool_definition()
  assert tool_def["name"] == "probe_stage_ramp_contract"
  assert tool_def["strict"] is True
  props = tool_def["parameters"]["properties"]
  assert "stage_family" in props
  assert "utilization_high_watermark" in props
  assert "quarter_ramp_grid" in props
  grid_items = props["quarter_ramp_grid"]["items"]
  for field in ("q", "rev_target", "rev_max", "max_util", "cogs_target", "ni_floor", "posture"):
    assert field in grid_items["properties"]


def test_session_counts_against_run_budget_is_false() -> None:
  assert _sr_session.COUNTS_AGAINST_RUN_BUDGET is False
  assert _sr_session.HARD_CAP_TOOL_CALLS == 10


# --------------------------------------------------------------------------
# Handler pipeline — run_stage_ramp_handler.
# --------------------------------------------------------------------------


def test_run_stage_ramp_handler_resolved_via_mocked_session() -> None:
  # The session returns a verified contract; the handler's
  # post-session canonical validator check must also accept it.
  def _mock_session(**kwargs):
    return _sr_session.StageRampToolCallSessionResult(
      status="verified",
      refined_contract={"stage_family": "operational", "ok": True},
      tool_calls_used=2,
      verified_commit_call_n=2,
    )
  def _mock_validator(**kwargs):
    return {}
  result = run_stage_ramp_handler(
    python_contract={"stage_family": "operational", "business_stage": "operational"},
    validator_error_text="initial rejection",
    _run_gpt_session=_mock_session,
    _validator=_mock_validator,
  )
  assert result.status == StageRampHandlerStatus.RESOLVED
  assert result.refined_contract is not None
  assert "refined_contract_validator_accepted" in result.diagnostic


def test_run_stage_ramp_handler_exhausted_when_session_best_effort() -> None:
  def _mock_session(**kwargs):
    return _sr_session.StageRampToolCallSessionResult(
      status="best_effort_no_acceptance",
      refined_contract=None,
      tool_calls_used=10,
      best_effort_call_n=7,
      detail="hard_cap",
    )
  def _mock_validator(**kwargs):
    return {}
  result = run_stage_ramp_handler(
    python_contract={"stage_family": "operational", "business_stage": "operational"},
    validator_error_text="initial rejection",
    _run_gpt_session=_mock_session,
    _validator=_mock_validator,
  )
  assert result.status == StageRampHandlerStatus.EXHAUSTED
  assert "best_effort_no_acceptance" in result.diagnostic


def test_run_stage_ramp_handler_exhausted_when_post_session_validator_rejects() -> None:
  # The session reports verified but the canonical validator rejects
  # the refined contract → handler returns EXHAUSTED.
  def _mock_session(**kwargs):
    return _sr_session.StageRampToolCallSessionResult(
      status="verified",
      refined_contract={"stage_family": "operational"},
      tool_calls_used=3,
      verified_commit_call_n=3,
    )
  def _mock_rejecting_validator(**kwargs):
    raise RuntimeError("canonical_validator_rejects: missing ni_floor")
  result = run_stage_ramp_handler(
    python_contract={"stage_family": "operational", "business_stage": "operational"},
    validator_error_text="initial rejection",
    _run_gpt_session=_mock_session,
    _validator=_mock_rejecting_validator,
  )
  assert result.status == StageRampHandlerStatus.EXHAUSTED
  assert "post_session_validator_failed" in result.diagnostic


# --------------------------------------------------------------------------
# engage_stage_ramp_handler_on_validator_failure — production entry point.
# --------------------------------------------------------------------------


def test_engage_returns_python_contract_when_validator_accepts() -> None:
  call_count = {"build": 0, "validator": 0}

  def _build(**kwargs):
    call_count["build"] += 1
    return {"stage_family": "operational", "business_stage": "operational"}

  def _validator(**kwargs):
    call_count["validator"] += 1
    return {}

  out = engage_stage_ramp_handler_on_validator_failure(
    build_python_contract=_build,
    validator=_validator,
    business_facts={},
    ops_json={},
    financials_json={},
    financials_year1_json={},
    planning_mode="growth",
    planning_mode_reason="",
  )
  assert out["stage_family"] == "operational"
  assert call_count["build"] == 1
  assert call_count["validator"] == 1


def test_engage_invokes_handler_when_validator_rejects_python() -> None:
  # Python rejected once → handler runs → handler returns refined.
  # The P3.12 authority-violation check rejects out-of-authority root
  # fields, so the test uses an in-authority field (rationale) as the
  # python-vs-refined marker.
  def _build(**kwargs):
    return {"stage_family": "operational", "rationale": "python_build"}

  def _rejecting_validator(**kwargs):
    # First call (on python_contract) rejects; subsequent calls accept
    # the refined contract distinguished by rationale content.
    payload = kwargs.get("payload") or {}
    if str(payload.get("rationale") or "").startswith("handler_refined"):
      return {}
    raise RuntimeError("python_contract_rejected")

  def _mock_session(**kwargs):
    return _sr_session.StageRampToolCallSessionResult(
      status="verified",
      refined_contract={
        "stage_family": "operational",
        "rationale": "handler_refined: synthetic test refinement",
      },
      tool_calls_used=2,
      verified_commit_call_n=2,
    )

  # Monkey-patch the handler's session resolver via the test seam.
  import client_intake_and_finmo.post_intake_stage_ramp_handler.handler as _h
  orig = _h.run_stage_ramp_handler
  def _patched_runner(**kwargs):
    return orig(**kwargs, _run_gpt_session=_mock_session)
  _h.run_stage_ramp_handler = _patched_runner
  try:
    out = engage_stage_ramp_handler_on_validator_failure(
      build_python_contract=_build,
      validator=_rejecting_validator,
      business_facts={},
      ops_json={"business_stage": "operational"},
      financials_json={},
      financials_year1_json={},
      planning_mode="growth",
      planning_mode_reason="",
    )
  finally:
    _h.run_stage_ramp_handler = orig
  assert str(out.get("rationale") or "").startswith("handler_refined")
  assert out.get("decision_source") == "stage_ramp_handler_refined"
  assert "python_proposal_diagnostic" in out


def test_engage_raises_when_handler_exhausted() -> None:
  def _build(**kwargs):
    return {"stage_family": "operational", "business_stage": "operational"}

  def _always_reject(**kwargs):
    raise RuntimeError("always_rejects")

  def _mock_session(**kwargs):
    return _sr_session.StageRampToolCallSessionResult(
      status="best_effort_no_acceptance",
      refined_contract=None,
      tool_calls_used=10,
    )

  import client_intake_and_finmo.post_intake_stage_ramp_handler.handler as _h
  orig = _h.run_stage_ramp_handler
  def _patched_runner(**kwargs):
    return orig(**kwargs, _run_gpt_session=_mock_session)
  _h.run_stage_ramp_handler = _patched_runner
  raised = None
  try:
    engage_stage_ramp_handler_on_validator_failure(
      build_python_contract=_build,
      validator=_always_reject,
      business_facts={},
      ops_json={},
      financials_json={},
      financials_year1_json={},
      planning_mode="growth",
      planning_mode_reason="",
    )
  except RuntimeError as exc:
    raised = exc
  finally:
    _h.run_stage_ramp_handler = orig
  assert raised is not None
  assert "stage_ramp_handler" in str(raised)


# --------------------------------------------------------------------------
# Module shape — doctrine §5 invariants.
# --------------------------------------------------------------------------


def test_module_has_required_five_files() -> None:
  module_dir = os.path.dirname(_sr_handler.__file__)
  for filename in ("__init__.py", "handler.py", "tool_calling_session.py", "prompts.py", "mini_finmo.py"):
    path = os.path.join(module_dir, filename)
    assert os.path.exists(path), f"missing: {path}"


def test_module_session_constants_match_doctrine() -> None:
  assert _sr_session.HARD_CAP_TOOL_CALLS == 10
  assert _sr_session.INITIAL_TOOL_CALL_BUDGET == 8
  assert _sr_session.EXTENSION_TOOL_CALLS == 2
  assert _sr_session.COUNTS_AGAINST_RUN_BUDGET is False


def test_authority_is_explicit_and_excludes_operating_levers() -> None:
  authority_str = " ".join(_sr_handler.STAGE_RAMP_FIELD_AUTHORITY)
  # Must include stage_ramp_contract grid fields.
  for required_field in ("rev_target", "cogs_max", "ni_floor", "posture", "utilization_high_watermark"):
    assert required_field in authority_str
  # MUST NOT include operating-side levers or payroll fields (these
  # are other handlers' authority).
  forbidden = ("expenses::Payroll", "revenue::Capacity", "Owner's Capital", "Debt Issuance")
  for f in forbidden:
    assert f not in authority_str, f"out-of-scope field in stage ramp authority: {f}"


# --------------------------------------------------------------------------
# Production wiring — intake_consult uses the new path.
# --------------------------------------------------------------------------


def test_intake_consult_wires_python_first_with_handler() -> None:
  import api_handlers.intake_consult as _intake
  src = open(_intake.__file__, encoding="utf-8").read()
  assert "_stage_ramp_contract_python_first_with_handler" in src
  # The dependency-injection key must reference the new wrapper.
  assert "estimate_stage_ramp_contract_with_gpt=_stage_ramp_contract_python_first_with_handler" in src
  # The legacy GPT-only function is still imported (kept for tests +
  # legacy callers); the call-site uses the new wrapper.
  assert "_estimate_stage_ramp_contract_with_gpt =" in src
  assert "iter 19 Stage 5" in src


# --------------------------------------------------------------------------
# mini_finmo helper.
# --------------------------------------------------------------------------


def test_mini_finmo_probe_returns_accepted_for_passing_validator() -> None:
  def _accepting(**kwargs):
    return {}
  out = _sr_mini_finmo.probe_stage_ramp_contract(
    candidate={"stage_family": "operational"},
    expected_stage_family="operational",
    business_stage="operational",
    planning_mode="growth",
    planning_mode_reason="",
    r_and_d_enabled=True,
    validator=_accepting,
  )
  assert out["validator_accepted"] is True
  assert out["validator_error_text"] is None


def test_mini_finmo_probe_returns_rejected_with_error_text() -> None:
  def _rejecting(**kwargs):
    raise RuntimeError("synthetic_rejection: cogs_max too high")
  out = _sr_mini_finmo.probe_stage_ramp_contract(
    candidate={"stage_family": "operational"},
    expected_stage_family="operational",
    business_stage="operational",
    planning_mode="growth",
    planning_mode_reason="",
    r_and_d_enabled=True,
    validator=_rejecting,
  )
  assert out["validator_accepted"] is False
  assert "synthetic_rejection" in out["validator_error_text"]


# --------------------------------------------------------------------------
# Prompts module — re-exports the canonical strings.
# --------------------------------------------------------------------------


def test_prompts_module_carries_authority_signals() -> None:
  prompt = _sr_prompts.STAGE_RAMP_HANDLER_SYSTEM_PROMPT
  for field in ("rev_target", "rev_max", "max_util", "cogs_target", "ni_floor", "posture"):
    assert field in prompt, f"system prompt missing field: {field}"


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_iter_19_stage5.py")
  print("-" * 70)
  tests = [
    ("python_builder_validator_compliant_retail", test_python_builder_returns_validator_compliant_contract_for_retail),
    ("python_builder_total_on_missing_naics", test_python_builder_total_on_missing_naics_coverage),
    ("python_builder_non_decreasing_utilization", test_python_builder_produces_non_decreasing_utilization),
    ("python_builder_operational_postures", test_python_builder_operational_postures_match_policy),
    ("session_verified_first_probe", test_session_verified_when_validator_accepts_first_probe),
    ("session_hard_cap_best_effort", test_session_hard_cap_with_best_effort_no_acceptance),
    ("session_failed_precondition", test_session_failed_precondition_when_gpt_never_calls_tool),
    ("session_tool_definition_full_grid", test_session_tool_definition_includes_full_grid_shape),
    ("session_run_budget_decoupled", test_session_counts_against_run_budget_is_false),
    ("handler_resolved_via_session", test_run_stage_ramp_handler_resolved_via_mocked_session),
    ("handler_exhausted_best_effort", test_run_stage_ramp_handler_exhausted_when_session_best_effort),
    ("handler_exhausted_post_session_validator", test_run_stage_ramp_handler_exhausted_when_post_session_validator_rejects),
    ("engage_returns_python_when_accepted", test_engage_returns_python_contract_when_validator_accepts),
    ("engage_invokes_handler_on_rejection", test_engage_invokes_handler_when_validator_rejects_python),
    ("engage_raises_when_exhausted", test_engage_raises_when_handler_exhausted),
    ("module_has_required_five_files", test_module_has_required_five_files),
    ("module_session_constants", test_module_session_constants_match_doctrine),
    ("authority_is_explicit", test_authority_is_explicit_and_excludes_operating_levers),
    ("intake_consult_wires_new_path", test_intake_consult_wires_python_first_with_handler),
    ("mini_finmo_probe_accepted", test_mini_finmo_probe_returns_accepted_for_passing_validator),
    ("mini_finmo_probe_rejected", test_mini_finmo_probe_returns_rejected_with_error_text),
    ("prompts_carry_authority_signals", test_prompts_module_carries_authority_signals),
  ]
  for name, fn in tests:
    _run(name, fn)
  print("-" * 70)
  passed = sum(1 for _, ok, _ in _RESULTS if ok)
  failed = [(n, why) for n, ok, why in _RESULTS if not ok]
  print(f"{passed}/{len(_RESULTS)} passed")
  if failed:
    print("FAILURES:")
    for name, why in failed:
      print(f"  {name}: {why}")
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
