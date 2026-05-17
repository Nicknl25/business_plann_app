"""Iter 19 Stage 2 tests — F2/F3 schema tightening + prompt explicitness
for ``target_payroll_percent_of_revenue``.

Covers the three changes:
  - Static envelope tightened from (0.01, 0.90) to (0.06, 0.80) — the
    union of post_intake_headcount_policy_lookup tier sanity bounds.
  - Root schema augmented with allOf/if-then conditionals so that each
    ``labor_intensity_class`` tier narrows ``target_payroll_percent_of_
    revenue`` to its tier-specific [min_pct, max_pct] band.
  - System prompt updated with an anti-confusion example (0.45 vs 45 vs
    0.045) so GPT does not emit the 10×-shifted scale error.

No MySQL, no live OpenAI. Smoke-tests only assert schema and prompt
structure (the strict-mode parser behavior is OpenAI-side and not
testable here).

Run: ``.venv\\Scripts\\python.exe "Test Files\\test_iter_19_stage2.py"``
"""

from __future__ import annotations

import inspect
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_mapping import (  # noqa: E402
  _PAYROLL_INTENSITY_TIER_BOUNDS,
  _augment_root_schema_for_contract,
  post_intake_gpt_contract_openai_schema,
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


# --------------------------------------------------------------------------
# Tier bound table mirrors the policy table.
# --------------------------------------------------------------------------


def test_tier_bounds_cover_four_intensity_classes() -> None:
  assert set(_PAYROLL_INTENSITY_TIER_BOUNDS.keys()) == {"low", "medium", "high", "expert"}


def test_tier_bounds_match_policy_lookup_defaults() -> None:
  # Mirror the defaults baked into post_intake_headcount/lookup.py
  # payroll_revenue_sanity_bounds_json. If those diverge, this test
  # catches it — see doctrine.md §4 Flavor 4 (invariant check).
  assert _PAYROLL_INTENSITY_TIER_BOUNDS["low"] == (0.06, 0.45)
  assert _PAYROLL_INTENSITY_TIER_BOUNDS["medium"] == (0.10, 0.55)
  assert _PAYROLL_INTENSITY_TIER_BOUNDS["high"] == (0.16, 0.70)
  assert _PAYROLL_INTENSITY_TIER_BOUNDS["expert"] == (0.18, 0.80)


def test_tier_bounds_have_low_min_of_six_percent() -> None:
  # The 10×-shifted 0.045 from F2/F3 must fall below the LOWEST tier
  # min (low.min_pct = 0.06). If this regresses, the strict parser
  # might let 0.045 through again.
  lowest_min = min(min_pct for min_pct, _ in _PAYROLL_INTENSITY_TIER_BOUNDS.values())
  assert lowest_min == 0.06
  assert 0.045 < lowest_min


# --------------------------------------------------------------------------
# Static envelope tightening on the contract row.
# --------------------------------------------------------------------------


def test_static_envelope_tightened_below_lowest_tier_min() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="payroll_headcount_schedule",
    business_naics=None,  # force the static fallback (no NAICS narrowing)
  )
  field = schema["properties"]["target_payroll_percent_of_revenue"]
  # Pre-iter-19 envelope was (0.01, 0.90); now (0.06, 0.80) — the union
  # of tier bounds.
  assert float(field["minimum"]) == 0.06, field
  assert float(field["maximum"]) == 0.80, field


def test_static_envelope_rejects_decimal_shift_scale_error() -> None:
  # 0.045 (the F2/F3 symptom) is strictly below the envelope; a
  # strict-mode parser must reject it because the schema minimum is
  # now 0.06.
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="payroll_headcount_schedule",
    business_naics=None,
  )
  field = schema["properties"]["target_payroll_percent_of_revenue"]
  assert 0.045 < float(field["minimum"])


# --------------------------------------------------------------------------
# allOf/if-then tier conditional bounds.
# --------------------------------------------------------------------------


def test_root_schema_omits_all_of_branches_per_openai_strict_mode() -> None:
  # P3.13 fix #2 — OpenAI strict-mode JSON schema does not permit
  # `allOf`. Tier-conditional bounds are enforced post-parse by the
  # runtime validator only. The static envelope on the contract row
  # remains tight enough to reject the original Stage 2 target (the
  # 10×-shifted 0.045 scale error) at parse time.
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="payroll_headcount_schedule",
    business_naics=None,
  )
  assert "allOf" not in schema, (
    "schema must not contain allOf (rejected by OpenAI strict mode)"
  )


def test_tier_bound_constants_remain_for_mirror_invariant() -> None:
  # The Python constants still drive the policy-mirror drift check
  # (_assert_payroll_tier_bounds_mirror_consistent in P3.12) even
  # though they no longer add allOf to the schema.
  assert set(_PAYROLL_INTENSITY_TIER_BOUNDS.keys()) == {"low", "medium", "high", "expert"}
  assert _PAYROLL_INTENSITY_TIER_BOUNDS["low"] == (0.06, 0.45)


def test_augmentation_is_idempotent_on_non_payroll_contracts() -> None:
  # Calling the augmenter on a non-payroll contract is a no-op.
  schema_in: Dict[str, Any] = {"type": "object", "properties": {"x": {"type": "string"}}}
  schema_out = _augment_root_schema_for_contract(
    contract_name="some_other_contract", schema=schema_in
  )
  assert schema_out is schema_in
  assert "allOf" not in schema_out


def test_augmentation_no_op_when_required_fields_missing() -> None:
  schema_in: Dict[str, Any] = {
    "type": "object",
    "properties": {"target_payroll_percent_of_revenue": {"type": "number"}},
    # missing labor_intensity_class
  }
  schema_out = _augment_root_schema_for_contract(
    contract_name="payroll_headcount_schedule", schema=schema_in
  )
  assert "allOf" not in schema_out


# --------------------------------------------------------------------------
# Prompt explicitness — the anti-confusion example must be present.
# --------------------------------------------------------------------------


def test_prompt_includes_anti_confusion_example_for_target_payroll() -> None:
  # Read the prompt-builder source directly. The anti-confusion
  # example must reference all three mis-encodings (45, 0.45, 0.045)
  # so GPT cannot miss it.
  src = open(_payroll_schedule.__file__, encoding="utf-8").read()
  assert "0.45 means 45 percent of revenue" in src
  assert "Do NOT emit 45" in src
  assert "0.045" in src


def test_prompt_required_instruction_carries_bounds_and_example() -> None:
  # The prompt_required_instruction baked into the contract row must
  # also surface the band + example, so any prompt builder that
  # auto-renders it inherits the anti-confusion text.
  from client_intake_and_finmo.post_intake_mapping import (
    post_intake_gpt_contract_lookup,
  )
  lookup = post_intake_gpt_contract_lookup()
  rows = lookup.rows(contract_name="payroll_headcount_schedule")
  matching = [
    r for r in rows
    if str(r.get("field_name") or "").strip() == "target_payroll_percent_of_revenue"
  ]
  assert len(matching) == 1
  prompt = str(matching[0].get("prompt_required_instruction") or "")
  assert "0.06, 0.80" in prompt
  assert "0.045" in prompt
  assert "labor_intensity_class" in prompt


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_iter_19_stage2.py")
  print("-" * 70)
  tests = [
    ("tier_bounds_cover_four_classes", test_tier_bounds_cover_four_intensity_classes),
    ("tier_bounds_match_policy_defaults", test_tier_bounds_match_policy_lookup_defaults),
    ("tier_bounds_lowest_min_is_six_percent", test_tier_bounds_have_low_min_of_six_percent),
    ("static_envelope_tightened", test_static_envelope_tightened_below_lowest_tier_min),
    ("static_envelope_rejects_decimal_shift", test_static_envelope_rejects_decimal_shift_scale_error),
    ("root_schema_omits_all_of_per_openai_strict_mode", test_root_schema_omits_all_of_branches_per_openai_strict_mode),
    ("tier_bound_constants_kept_for_mirror_invariant", test_tier_bound_constants_remain_for_mirror_invariant),
    ("augmenter_no_op_other_contracts", test_augmentation_is_idempotent_on_non_payroll_contracts),
    ("augmenter_no_op_missing_fields", test_augmentation_no_op_when_required_fields_missing),
    ("prompt_anti_confusion_example", test_prompt_includes_anti_confusion_example_for_target_payroll),
    ("prompt_required_instruction_carries_example", test_prompt_required_instruction_carries_bounds_and_example),
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
