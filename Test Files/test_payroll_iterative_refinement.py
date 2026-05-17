"""Phase 9 P3.11 — Payroll iterative refinement tests.

Covers:
  - Pattern-based translator for Layer A.2 codes (unit tests for each
    pattern; unmatched code raises fail-fast).
  - Iterative loop: pass on round 1; pass on round N after validator
    failure; exhaustion at round 10 hard-fails with residual
    diagnostic.
  - All 7 fail-fast invariants for iteration mechanics.
  - Regression: existing payroll tests and iter 19 tests unchanged.

Mocked GPT turns. No live OpenAI. No MySQL.

Run: ``.venv\\Scripts\\python.exe "Test Files\\test_payroll_iterative_refinement.py"``
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

from client_intake_and_finmo.fail_fast.common import (  # noqa: E402
  PostIntakePreconditionFailed,
  FailFastError,
)
from client_intake_and_finmo.post_intake_headcount.payroll_validator_translator import (  # noqa: E402
  translate_payroll_validator_codes,
)
from client_intake_and_finmo.post_intake_headcount import schedule as _payroll_schedule  # noqa: E402


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


# =============================================================================
# Translator unit tests — table-driven per pattern.
# =============================================================================


def test_translator_pattern_out_of_policy_range() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_target_payroll_percent_of_revenue_out_of_policy_range:value=0.05:min=0.10:max=0.55",
  ])
  failures = out["structured_failures"]
  assert len(failures) == 1
  f = failures[0]
  assert f["field"] == "target_payroll_percent_of_revenue"
  assert f["category"] == "out_of_range"
  assert f["actual_value"] == 0.05
  assert f["required_range"] == [0.10, 0.55]


def test_translator_pattern_out_of_tier_bounds() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_wage_positioning_multiplier_out_of_tier_bounds:value=4.0:tier=floor:min=1.0:max=2.0",
  ])
  f = out["structured_failures"][0]
  assert f["field"] == "wage_positioning_multiplier"
  assert f["category"] == "out_of_range"
  assert f["actual_value"] == 4.0
  assert f["required_range"] == [1.0, 2.0]
  assert f["context"]["tier"] == "floor"


def test_translator_pattern_missing() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_wage_positioning_multiplier_missing",
    "payroll_headcount_capacity_units_per_supporting_fte_missing",
    "payroll_headcount_target_payroll_percent_of_revenue_missing",
  ])
  assert len(out["structured_failures"]) == 3
  for f in out["structured_failures"]:
    assert f["category"] == "missing"
  fields = {f["field"] for f in out["structured_failures"]}
  assert fields == {
    "wage_positioning_multiplier",
    "capacity_units_per_supporting_fte",
    "target_payroll_percent_of_revenue",
  }


def test_translator_pattern_invalid_enum() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_capacity_labor_model_invalid:bogus_value",
    "payroll_headcount_labor_intensity_class_invalid:missing",
    "payroll_headcount_wage_positioning_tier_invalid:gold",
  ])
  failures = out["structured_failures"]
  assert len(failures) == 3
  for f in failures:
    assert f["category"] == "invalid_enum"
  actual = {(f["field"], f["actual_value"]) for f in failures}
  assert actual == {
    ("capacity_labor_model", "bogus_value"),
    ("labor_intensity_class", "missing"),
    ("wage_positioning_tier", "gold"),
  }


def test_translator_pattern_per_row_field() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_non_numeric_starting_fte:rows[0]",
    "payroll_headcount_negative_hires:rows[5]",
    "payroll_headcount_currency_not_integer_annual_wage:rows[2]",
  ])
  failures = out["structured_failures"]
  assert len(failures) == 3
  for f in failures:
    assert f["category"] == "row_issue"
    assert "row_path" in f
  pairs = {(f["issue_type"], f["field"], f["row_path"]) for f in failures}
  assert pairs == {
    ("non_numeric", "starting_fte", "rows[0]"),
    ("negative", "hires", "rows[5]"),
    ("currency_not_integer", "annual_wage", "rows[2]"),
  }


def test_translator_pattern_row_generic() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_row_not_object:rows[3]",
    "payroll_headcount_invalid_quarter_index:rows[7]",
    "payroll_headcount_missing_oews_occ_title:rows[1]",
    "payroll_headcount_fte_math_mismatch:rows[9]",
  ])
  failures = out["structured_failures"]
  assert len(failures) == 4
  pairs = {(f["issue_type"], f["row_path"]) for f in failures}
  assert pairs == {
    ("row_not_object", "rows[3]"),
    ("invalid_quarter_index", "rows[7]"),
    ("missing_oews_occ_title", "rows[1]"),
    ("fte_math_mismatch", "rows[9]"),
  }


def test_translator_pattern_title_lifecycle() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_dead_support_title:Software Developers",
    "payroll_headcount_support_title_missing_after_start:Software Developers:q5",
    "payroll_headcount_support_title_stops_after_start:Data Analysts:q12",
  ])
  failures = out["structured_failures"]
  assert len(failures) == 3
  for f in failures:
    assert f["category"] == "title_lifecycle"
    assert f["field"] == "payroll_headcount_grid"
  assert failures[0]["title_label"] == "Software Developers"
  assert "quarter" not in failures[0]
  assert failures[1]["title_label"] == "Software Developers"
  assert failures[1]["quarter"] == 5
  assert failures[2]["title_label"] == "Data Analysts"
  assert failures[2]["quarter"] == 12


def test_translator_pattern_structural() -> None:
  codes = [
    "payroll_headcount_payload_not_object",
    "payroll_headcount_rows_not_array",
    "payroll_headcount_quarter_totals_not_array",
    "payroll_headcount_horizon_mismatch",
    "payroll_headcount_quarter_totals_missing_required_quarters",
    "payroll_headcount_contract_version_mismatch",
  ]
  out = translate_payroll_validator_codes(codes)
  failures = out["structured_failures"]
  assert len(failures) == len(codes)
  for f in failures:
    assert f["category"] == "structural"
    assert f["diagnostic"] == f["code"]


def test_translator_pattern_quarter_total_variants() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_quarter_total_not_object:5",
    "payroll_headcount_quarter_total_invalid_quarter:7",
    "payroll_headcount_quarter_total_missing_ending_fte:3",
    "payroll_headcount_quarter_total_negative_payroll:9",
    "payroll_headcount_quarter_total_payroll_not_integer:11",
  ])
  failures = out["structured_failures"]
  assert len(failures) == 5
  for f in failures:
    assert f["category"] == "row_issue"
    assert "quarter_totals[" in f["row_path"]


def test_translator_pattern_decision_source_and_horizon() -> None:
  out = translate_payroll_validator_codes([
    "payroll_headcount_decision_source_mismatch:expected=payroll_headcount_schedule.payroll_headcount_grid",
    "payroll_headcount_quarter_totals_must_cover_contract_horizon:20",
    "payroll_headcount_economic_basis_mismatch:expected=capacity_units_per_supporting_fte:actual=revenue_per_employee",
    "payroll_headcount_forbidden_text_field:rows[0].notes",
  ])
  failures = out["structured_failures"]
  assert len(failures) == 4
  for f in failures:
    assert f["category"] == "structural"


def test_translator_unmatched_code_raises() -> None:
  raised = False
  try:
    translate_payroll_validator_codes(["payroll_headcount_some_brand_new_failure_type_that_doesnt_exist"])
  except PostIntakePreconditionFailed as exc:
    raised = True
    assert exc.operation == "payroll_validator_translator_unmatched_code"
    assert "payroll_headcount_some_brand_new_failure_type_that_doesnt_exist" in str(
      exc.details.get("unmatched_codes")
    )
    assert "remediation" in exc.details
  assert raised


def test_translator_unmatched_does_not_fall_back_on_silent_passthrough() -> None:
  # Verify the directive's "fail-fast on unmatched" — no silent
  # conversion of unmatched codes to verbatim string failures.
  raised = False
  try:
    translate_payroll_validator_codes([
      "payroll_headcount_target_payroll_percent_of_revenue_missing",  # valid
      "some_completely_unknown_code_format",                          # invalid
    ])
  except PostIntakePreconditionFailed:
    raised = True
  assert raised


def test_translator_empty_input_returns_empty_output() -> None:
  out = translate_payroll_validator_codes([])
  assert out["structured_failures"] == []
  assert out["unmatched_codes"] == []


def test_translator_filters_empty_and_whitespace_codes() -> None:
  out = translate_payroll_validator_codes([
    "",
    "   ",
    "payroll_headcount_target_payroll_percent_of_revenue_missing",
  ])
  assert len(out["structured_failures"]) == 1


def test_translator_pattern_priority_row_generic_over_row_format() -> None:
  # `payroll_headcount_missing_oews_occ_title:rows[3]` could be
  # mis-matched by ROW_FORMAT (issue=missing, field=oews_occ_title);
  # ROW_GENERIC should win and produce issue=missing_oews_occ_title.
  out = translate_payroll_validator_codes([
    "payroll_headcount_missing_oews_occ_title:rows[3]",
  ])
  f = out["structured_failures"][0]
  assert f["issue_type"] == "missing_oews_occ_title"


# =============================================================================
# Iterative loop tests — mocked _post_openai + mocked validators.
# =============================================================================


class _FakeResponse:
  def __init__(self, *, status_code: int = 200, json_payload: Any = None, text: str = ""):
    self.status_code = status_code
    self._json = copy.deepcopy(json_payload) if json_payload is not None else {}
    self.text = text or json.dumps(self._json)

  def json(self) -> Any:
    # Return a fresh deep copy each call so the iterative loop's
    # mutation (contract["raw_openai_response"] = ...) does not
    # create circular references across rounds.
    return copy.deepcopy(self._json)


def _build_valid_payroll_schedule() -> Dict[str, Any]:
  """Synthesize a payroll_headcount_schedule dict that
  ``validate_payroll_headcount_payload`` would accept — used as the
  "success" round's parsed response."""
  return {
    "contract_version": "payroll_headcount_schedule_v1",
    "decision_source": "payroll_headcount_schedule.payroll_headcount_grid",
    "draft_id": "",
    "client_id": "",
    "policy_code": "default",
    "source_table": "intake_consult_drafts",
    "source_column": "payroll_headcount",
    "schedule_horizon_quarters": 20,
    "headcount_economic_basis": "capacity_units_per_supporting_fte",
    "capacity_labor_model": "hybrid",
    "labor_intensity_class": "medium",
    "wage_positioning_tier": "market",
    "wage_positioning_multiplier": 1.1,
    "capacity_units_per_supporting_fte": 100.0,
    "target_payroll_percent_of_revenue": 0.30,
    "rows": [],
    "quarter_totals": [
      {"quarter_index": q, "ending_fte": 5.0, "payroll": 100_000} for q in range(1, 21)
    ],
  }


def _make_iterative_environment(*, scripted_post_openai_responses, mock_validator_for_contract, mock_build_payload, mock_assert_economic):
  """Inject mocks for the iterative loop without monkey-patching globals
  permanently. Returns (call_log, env_dict)."""
  call_log: Dict[str, Any] = {"post_openai_calls": 0, "rounds": []}

  # Backup originals so they can be restored.
  originals = {
    "_post_openai": _payroll_schedule._post_openai,
    "_parse_responses_json_dict": _payroll_schedule._parse_responses_json_dict,
    "validate_payroll_headcount_contract_payload": _payroll_schedule.validate_payroll_headcount_contract_payload,
    "build_payroll_headcount_payload_from_contract": _payroll_schedule.build_payroll_headcount_payload_from_contract,
    "_assert_payroll_contract_economic_feasible_for_retry": _payroll_schedule._assert_payroll_contract_economic_feasible_for_retry,
    "_openai_key": _payroll_schedule._openai_key,
    "_assert_payroll_sequence_step": _payroll_schedule._assert_payroll_sequence_step,
    "post_intake_assert_process_object_control": _payroll_schedule.post_intake_assert_process_object_control,
    "_payroll_capacity_guardrails": _payroll_schedule._payroll_capacity_guardrails,
    "_supporting_staff_guardrails_for_gpt": _payroll_schedule._supporting_staff_guardrails_for_gpt,
    "_payroll_capacity_grid_for_gpt": _payroll_schedule._payroll_capacity_grid_for_gpt,
    "_oews_title_catalog_for_business": _payroll_schedule._oews_title_catalog_for_business,
    "_payroll_decision_options_from_policy": _payroll_schedule._payroll_decision_options_from_policy,
    "post_intake_payroll_feasibility_mapping": _payroll_schedule.post_intake_payroll_feasibility_mapping,
    "_revenue_driver_context_from_model_input": _payroll_schedule._revenue_driver_context_from_model_input,
    "_compact_stage_ramp_contract_for_payroll": _payroll_schedule._compact_stage_ramp_contract_for_payroll,
    "post_intake_gpt_context_filter_payload": _payroll_schedule.post_intake_gpt_context_filter_payload,
    "post_intake_gpt_context_request_char_budget": _payroll_schedule.post_intake_gpt_context_request_char_budget,
    "post_intake_gpt_contract_openai_schema": _payroll_schedule.post_intake_gpt_contract_openai_schema,
    "_openai_model": _payroll_schedule._openai_model,
    "_payroll_process_sequence_settings": _payroll_schedule._payroll_process_sequence_settings,
    "post_intake_build_prompt_from_contract": _payroll_schedule.post_intake_build_prompt_from_contract,
    "_people_json_with_resolved_key_person_wages": _payroll_schedule._people_json_with_resolved_key_person_wages,
    "_people_staffing_context": _payroll_schedule._people_staffing_context,
    "post_intake_headcount_policy_for": _payroll_schedule.post_intake_headcount_policy_for,
    "_payroll_capacity_guardrail_summary_for_gpt": _payroll_schedule._payroll_capacity_guardrail_summary_for_gpt,
  }

  def _mock_post_openai(*args, **kwargs):
    idx = call_log["post_openai_calls"]
    call_log["post_openai_calls"] += 1
    if idx >= len(scripted_post_openai_responses):
      return _FakeResponse(status_code=500, text="exhausted")
    return scripted_post_openai_responses[idx]

  def _mock_parse(raw):
    if isinstance(raw, dict) and "_parsed" in raw:
      return raw["_parsed"]
    return raw if isinstance(raw, dict) else {}

  # Apply mocks
  _payroll_schedule._post_openai = _mock_post_openai
  _payroll_schedule._parse_responses_json_dict = _mock_parse
  _payroll_schedule.validate_payroll_headcount_contract_payload = mock_validator_for_contract
  _payroll_schedule.build_payroll_headcount_payload_from_contract = mock_build_payload
  _payroll_schedule._assert_payroll_contract_economic_feasible_for_retry = mock_assert_economic
  _payroll_schedule._openai_key = lambda: "fake-api-key"
  _payroll_schedule._assert_payroll_sequence_step = lambda **kwargs: None
  _payroll_schedule.post_intake_assert_process_object_control = lambda **kwargs: None
  _payroll_schedule._payroll_capacity_guardrails = lambda **kwargs: {}
  _payroll_schedule._supporting_staff_guardrails_for_gpt = lambda *a, **k: {}
  _payroll_schedule._payroll_capacity_grid_for_gpt = lambda *a, **k: []
  _payroll_schedule._oews_title_catalog_for_business = lambda **kwargs: {"title_candidates": []}
  _payroll_schedule._payroll_decision_options_from_policy = lambda policy: {}
  _payroll_schedule.post_intake_payroll_feasibility_mapping = lambda: {"rows": []}
  _payroll_schedule._revenue_driver_context_from_model_input = lambda model_input_json, *, finmo_json=None: {}
  _payroll_schedule._compact_stage_ramp_contract_for_payroll = lambda x: {}
  _payroll_schedule.post_intake_gpt_context_filter_payload = lambda *, contract_name, payload, include_phase: payload
  _payroll_schedule.post_intake_gpt_context_request_char_budget = lambda *, contract_name, include_phase, default=None: None
  _payroll_schedule.post_intake_gpt_contract_openai_schema = lambda **kwargs: {"type": "object"}
  _payroll_schedule._openai_model = lambda: "gpt-4o-mini-fake"
  _payroll_schedule._payroll_process_sequence_settings = lambda step_key: {
    "timeout_seconds": 180.0, "max_attempts": 1, "step_key": step_key, "source_table": "fake",
  }
  _payroll_schedule.post_intake_build_prompt_from_contract = lambda *args, **kwargs: "fake system prompt"
  _payroll_schedule._people_json_with_resolved_key_person_wages = lambda people_json, **kwargs: people_json or {}
  _payroll_schedule._people_staffing_context = lambda *args, **kwargs: {}
  _payroll_schedule.post_intake_headcount_policy_for = lambda code: {"policy_code": "default"}
  _payroll_schedule._payroll_capacity_guardrail_summary_for_gpt = lambda *args, **kwargs: {}

  def restore():
    for name, fn in originals.items():
      setattr(_payroll_schedule, name, fn)

  return call_log, restore


def test_iterative_loop_passes_on_round_1() -> None:
  schedule = _build_valid_payroll_schedule()

  def _validator(parsed):
    return parsed

  def _builder(contract, **kwargs):
    return schedule

  def _assert_econ(**kwargs):
    return None

  responses = [
    _FakeResponse(status_code=200, json_payload={"_parsed": schedule}),
  ]
  call_log, restore = _make_iterative_environment(
    scripted_post_openai_responses=responses,
    mock_validator_for_contract=_validator,
    mock_build_payload=_builder,
    mock_assert_economic=_assert_econ,
  )
  try:
    result = _payroll_schedule.estimate_payroll_headcount_schedule_with_gpt(
      business_facts={}, ops_json={}, people_json={},
      financials_json={}, financials_year1_json={},
      planning_mode="growth", planning_mode_reason="",
      model_input_json={}, finmo_json={},
      stage_ramp_contract={},
    )
  finally:
    restore()
  assert result == schedule
  assert call_log["post_openai_calls"] == 1


def test_iterative_loop_passes_on_round_2_after_layer_a2_failure() -> None:
  schedule = _build_valid_payroll_schedule()

  def _validator(parsed):
    return parsed

  call_state = {"build_count": 0}

  def _builder(contract, **kwargs):
    call_state["build_count"] += 1
    if call_state["build_count"] == 1:
      # First round fails Layer A.2
      from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
        post_intake_fail_fast_raise,
      )
      post_intake_fail_fast_raise(
        "payroll_headcount_schedule_validation_failed",
        "synthetic A.2 failure",
        stage="payroll_headcount_payload_build",
        details={"errors": ["payroll_headcount_target_payroll_percent_of_revenue_missing"]},
      )
    return schedule

  def _assert_econ(**kwargs):
    return None

  responses = [
    _FakeResponse(status_code=200, json_payload={"_parsed": schedule}),
    _FakeResponse(status_code=200, json_payload={"_parsed": schedule}),
  ]
  call_log, restore = _make_iterative_environment(
    scripted_post_openai_responses=responses,
    mock_validator_for_contract=_validator,
    mock_build_payload=_builder,
    mock_assert_economic=_assert_econ,
  )
  try:
    result = _payroll_schedule.estimate_payroll_headcount_schedule_with_gpt(
      business_facts={}, ops_json={}, people_json={},
      financials_json={}, financials_year1_json={},
      planning_mode="growth", planning_mode_reason="",
      model_input_json={}, finmo_json={},
      stage_ramp_contract={},
    )
  finally:
    restore()
  assert result == schedule
  assert call_log["post_openai_calls"] == 2


def test_iterative_loop_exhausts_at_round_10_with_residual_diagnostic() -> None:
  def _validator(parsed):
    return parsed

  def _builder(contract, **kwargs):
    # Always fail Layer A.2
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
      post_intake_fail_fast_raise,
    )
    post_intake_fail_fast_raise(
      "payroll_headcount_schedule_validation_failed",
      "synthetic A.2 failure",
      stage="payroll_headcount_payload_build",
      details={"errors": ["payroll_headcount_target_payroll_percent_of_revenue_missing"]},
    )

  def _assert_econ(**kwargs):
    return None

  schedule = _build_valid_payroll_schedule()
  responses = [_FakeResponse(status_code=200, json_payload={"_parsed": schedule}) for _ in range(11)]
  call_log, restore = _make_iterative_environment(
    scripted_post_openai_responses=responses,
    mock_validator_for_contract=_validator,
    mock_build_payload=_builder,
    mock_assert_economic=_assert_econ,
  )
  raised = None
  try:
    try:
      _payroll_schedule.estimate_payroll_headcount_schedule_with_gpt(
        business_facts={}, ops_json={}, people_json={},
        financials_json={}, financials_year1_json={},
        planning_mode="growth", planning_mode_reason="",
        model_input_json={}, finmo_json={},
        stage_ramp_contract={},
      )
    except FailFastError as exc:
      raised = exc
  finally:
    restore()
  assert raised is not None
  assert raised.code == "payroll_iterative_refinement_exhausted"
  assert raised.details["rounds_used"] == 10
  assert raised.details["hard_cap_rounds"] == 10
  assert call_log["post_openai_calls"] == 10


def test_iterative_loop_dispatches_layer_a1_to_contract_table_path() -> None:
  schedule = _build_valid_payroll_schedule()
  call_state = {"validator_count": 0}

  def _validator(parsed):
    call_state["validator_count"] += 1
    if call_state["validator_count"] == 1:
      from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
        post_intake_fail_fast_raise,
      )
      post_intake_fail_fast_raise(
        "payroll_headcount_contract_table_validation_failed",
        "synthetic A.1 prose failure",
        stage="payroll_headcount_contract_payload",
        details={"errors": ["target_payroll_percent_of_revenue must be one of [...]"]},
      )
    return parsed

  def _builder(contract, **kwargs):
    return schedule

  def _assert_econ(**kwargs):
    return None

  responses = [
    _FakeResponse(status_code=200, json_payload={"_parsed": schedule}),
    _FakeResponse(status_code=200, json_payload={"_parsed": schedule}),
  ]
  call_log, restore = _make_iterative_environment(
    scripted_post_openai_responses=responses,
    mock_validator_for_contract=_validator,
    mock_build_payload=_builder,
    mock_assert_economic=_assert_econ,
  )
  try:
    result = _payroll_schedule.estimate_payroll_headcount_schedule_with_gpt(
      business_facts={}, ops_json={}, people_json={},
      financials_json={}, financials_year1_json={},
      planning_mode="growth", planning_mode_reason="",
      model_input_json={}, finmo_json={},
      stage_ramp_contract={},
    )
  finally:
    restore()
  assert result == schedule
  assert call_log["post_openai_calls"] == 2


def test_iterative_loop_dispatches_layer_a3_to_economic_feasibility_path() -> None:
  schedule = _build_valid_payroll_schedule()
  econ_calls = {"count": 0}

  def _validator(parsed):
    return parsed

  def _builder(contract, **kwargs):
    return schedule

  def _assert_econ(**kwargs):
    econ_calls["count"] += 1
    if econ_calls["count"] == 1:
      from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
        post_intake_fail_fast_raise,
      )
      post_intake_fail_fast_raise(
        "payroll_revenue_economic_feasibility_failed",
        "synthetic A.3 feasibility failure",
        stage="payroll_headcount_contract_economic_feasibility",
        details={
          "violations": [
            {"quarter_index": 5, "payroll_percent_of_revenue": 0.65, "policy_min_pct": 0.10, "policy_max_pct": 0.55}
          ],
        },
      )

  responses = [
    _FakeResponse(status_code=200, json_payload={"_parsed": schedule}),
    _FakeResponse(status_code=200, json_payload={"_parsed": schedule}),
  ]
  call_log, restore = _make_iterative_environment(
    scripted_post_openai_responses=responses,
    mock_validator_for_contract=_validator,
    mock_build_payload=_builder,
    mock_assert_economic=_assert_econ,
  )
  try:
    result = _payroll_schedule.estimate_payroll_headcount_schedule_with_gpt(
      business_facts={}, ops_json={}, people_json={},
      financials_json={}, financials_year1_json={},
      planning_mode="growth", planning_mode_reason="",
      model_input_json={}, finmo_json={},
      stage_ramp_contract={},
    )
  finally:
    restore()
  assert result == schedule
  assert call_log["post_openai_calls"] == 2


def test_iterative_loop_external_seed_threads_through_round_1() -> None:
  schedule = _build_valid_payroll_schedule()

  def _validator(parsed):
    return parsed

  def _builder(contract, **kwargs):
    return schedule

  def _assert_econ(**kwargs):
    return None

  responses = [_FakeResponse(status_code=200, json_payload={"_parsed": schedule})]
  call_log, restore = _make_iterative_environment(
    scripted_post_openai_responses=responses,
    mock_validator_for_contract=_validator,
    mock_build_payload=_builder,
    mock_assert_economic=_assert_econ,
  )
  try:
    result = _payroll_schedule.estimate_payroll_headcount_schedule_with_gpt(
      business_facts={}, ops_json={}, people_json={},
      financials_json={}, financials_year1_json={},
      planning_mode="growth", planning_mode_reason="",
      model_input_json={}, finmo_json={},
      stage_ramp_contract={},
      previous_contract_failure={
        "error": "convergence-detected downstream failure",
        "violations": [{"quarter_index": 7, "payroll_percent_of_revenue": 0.75}],
      },
    )
  finally:
    restore()
  assert result == schedule
  # No assertion on internal state — just that the call succeeded
  # with external seed without raising.


# =============================================================================
# Fail-fast invariants (7) on iteration mechanics.
# =============================================================================


def test_machinery_fail_fast_state_corruption_user_context() -> None:
  raised = False
  try:
    _payroll_schedule._assert_payroll_iterative_state_intact(
      round_n=3,
      user_context=None,
      payload_base={"text": "ok"},
    )
  except PostIntakePreconditionFailed as exc:
    raised = True
    assert exc.operation == "payroll_iterative_refinement_state_corruption"
  assert raised


def test_machinery_fail_fast_state_corruption_payload_base() -> None:
  raised = False
  try:
    _payroll_schedule._assert_payroll_iterative_state_intact(
      round_n=2,
      user_context={"k": 1},
      payload_base={},  # missing "text"
    )
  except PostIntakePreconditionFailed as exc:
    raised = True
    assert exc.operation == "payroll_iterative_refinement_state_corruption"
  assert raised


def test_machinery_fail_fast_state_intact_passes_healthy() -> None:
  # Healthy state must not raise.
  _payroll_schedule._assert_payroll_iterative_state_intact(
    round_n=1,
    user_context={"k": "v"},
    payload_base={"text": {"format": {}}},
  )


def test_machinery_fail_fast_budget_decoupling_violation_outside_scope() -> None:
  # If the contextvar is None (loop bypassed), the check must fail.
  # Reset the var manually to None to simulate outside-scope call.
  raised = False
  try:
    _payroll_schedule._assert_payroll_iterative_budget_decoupled(round_n=1)
  except PostIntakePreconditionFailed as exc:
    raised = True
    assert exc.operation == "payroll_iterative_refinement_budget_decoupling_violation"
  assert raised


def test_machinery_fail_fast_budget_decoupling_passes_inside_scope() -> None:
  token = _payroll_schedule._PAYROLL_ITER_GPT_CALL_COUNT.set(0)
  try:
    _payroll_schedule._assert_payroll_iterative_budget_decoupled(round_n=1)
  finally:
    _payroll_schedule._PAYROLL_ITER_GPT_CALL_COUNT.reset(token)


def test_machinery_fail_fast_translator_unmatched_code() -> None:
  raised = False
  try:
    translate_payroll_validator_codes(["payroll_headcount_brand_new_unknown_pattern"])
  except PostIntakePreconditionFailed as exc:
    raised = True
    assert exc.operation == "payroll_validator_translator_unmatched_code"
  assert raised


def test_machinery_fail_fast_feedback_packet_dispatches_class_a_via_translator() -> None:
  # Build a fake FailFastError with A.2 wrapper code; verify dispatch.
  from client_intake_and_finmo.fail_fast.common import FailFastError as _FFE  # type: ignore
  exc = _FFE(
    "payroll_headcount_payload_invalid",
    "synthetic",
    details={"errors": ["payroll_headcount_target_payroll_percent_of_revenue_missing"]},
  )
  packet = _payroll_schedule._build_payroll_iterative_feedback_packet(
    exc=exc, parsed={"x": 1}, round_n=4,
  )
  assert packet["feedback_class"] == "schedule_validation"
  assert packet["round_n"] == 4
  assert len(packet["translated_failures"]) == 1
  assert packet["translated_failures"][0]["field"] == "target_payroll_percent_of_revenue"


def test_machinery_fail_fast_feedback_packet_dispatches_class_b_verbatim() -> None:
  from client_intake_and_finmo.fail_fast.common import FailFastError as _FFE  # type: ignore
  exc = _FFE(
    "payroll_headcount_contract_table_validation_failed",
    "synthetic A.1",
    details={"errors": ["target_payroll_percent_of_revenue must be one of [a, b]"]},
  )
  packet = _payroll_schedule._build_payroll_iterative_feedback_packet(
    exc=exc, parsed={"x": 1}, round_n=2,
  )
  assert packet["feedback_class"] == "contract_table"
  assert packet["contract_table_errors"] == [
    "target_payroll_percent_of_revenue must be one of [a, b]"
  ]


def test_machinery_fail_fast_feedback_packet_dispatches_class_c_econ_feasibility() -> None:
  from client_intake_and_finmo.fail_fast.common import FailFastError as _FFE  # type: ignore
  exc = _FFE(
    "payroll_revenue_economic_feasibility_failed",
    "synthetic A.3",
    details={"violations": [{"quarter_index": 5, "payroll_percent_of_revenue": 0.65}]},
  )
  packet = _payroll_schedule._build_payroll_iterative_feedback_packet(
    exc=exc, parsed={"x": 1}, round_n=3,
  )
  assert packet["feedback_class"] == "economic_feasibility"
  assert "compacted_violations" in packet


# =============================================================================
# Run.
# =============================================================================


def main() -> int:
  print("running test_payroll_iterative_refinement.py")
  print("-" * 70)
  tests = [
    # Translator unit tests
    ("translator_out_of_policy_range", test_translator_pattern_out_of_policy_range),
    ("translator_out_of_tier_bounds", test_translator_pattern_out_of_tier_bounds),
    ("translator_missing", test_translator_pattern_missing),
    ("translator_invalid_enum", test_translator_pattern_invalid_enum),
    ("translator_per_row_field", test_translator_pattern_per_row_field),
    ("translator_row_generic", test_translator_pattern_row_generic),
    ("translator_title_lifecycle", test_translator_pattern_title_lifecycle),
    ("translator_structural", test_translator_pattern_structural),
    ("translator_quarter_total_variants", test_translator_pattern_quarter_total_variants),
    ("translator_decision_source_and_horizon", test_translator_pattern_decision_source_and_horizon),
    ("translator_unmatched_raises", test_translator_unmatched_code_raises),
    ("translator_unmatched_no_silent_passthrough", test_translator_unmatched_does_not_fall_back_on_silent_passthrough),
    ("translator_empty_input", test_translator_empty_input_returns_empty_output),
    ("translator_filters_whitespace", test_translator_filters_empty_and_whitespace_codes),
    ("translator_pattern_priority", test_translator_pattern_priority_row_generic_over_row_format),
    # Iterative loop tests
    ("iter_loop_round_1_pass", test_iterative_loop_passes_on_round_1),
    ("iter_loop_round_2_after_a2", test_iterative_loop_passes_on_round_2_after_layer_a2_failure),
    ("iter_loop_exhaust_round_10", test_iterative_loop_exhausts_at_round_10_with_residual_diagnostic),
    ("iter_loop_dispatch_layer_a1", test_iterative_loop_dispatches_layer_a1_to_contract_table_path),
    ("iter_loop_dispatch_layer_a3", test_iterative_loop_dispatches_layer_a3_to_economic_feasibility_path),
    ("iter_loop_external_seed", test_iterative_loop_external_seed_threads_through_round_1),
    # Machinery fail-fast invariants
    ("ff_state_corruption_user_context", test_machinery_fail_fast_state_corruption_user_context),
    ("ff_state_corruption_payload_base", test_machinery_fail_fast_state_corruption_payload_base),
    ("ff_state_intact_passes_healthy", test_machinery_fail_fast_state_intact_passes_healthy),
    ("ff_budget_decoupling_violation", test_machinery_fail_fast_budget_decoupling_violation_outside_scope),
    ("ff_budget_decoupling_passes_inside_scope", test_machinery_fail_fast_budget_decoupling_passes_inside_scope),
    ("ff_translator_unmatched", test_machinery_fail_fast_translator_unmatched_code),
    ("ff_packet_class_a_translator", test_machinery_fail_fast_feedback_packet_dispatches_class_a_via_translator),
    ("ff_packet_class_b_verbatim", test_machinery_fail_fast_feedback_packet_dispatches_class_b_verbatim),
    ("ff_packet_class_c_econ", test_machinery_fail_fast_feedback_packet_dispatches_class_c_econ_feasibility),
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
