"""Module 3 v3 — contract sweep end-to-end verification.

Confirms that the NAICS-bound stage_ramp_contract / payroll_headcount_schedule
schemas produce non-trivial industry-tightened bounds at prompt-build time,
and that removing the hardcoded `field_schema_overrides` in
`_stage_ramp_contract_schema` did not regress fields outside the NAICS-bind
list.

Run: `.venv\\Scripts\\python.exe "Test Files\\test_module3_contract_sweep.py"`
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_mapping import (  # noqa: E402
  post_intake_gpt_contract_openai_schema,
)
# Production wrappers that apply field_schema_overrides (e.g., the rev_target
# rate_schema and the q integer constraint).
from client_intake_and_finmo.post_intake_contracts.runner import (  # noqa: E402
  _stage_ramp_contract_schema,
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


def _grid_field(schema: Dict[str, Any], grid_name: str, field_name: str) -> Dict[str, Any]:
  return schema["properties"][grid_name]["items"]["properties"][field_name]


def test_stage_ramp_cogs_naics_band_for_retail() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="stage_ramp_contract", business_naics="455211"
  )
  cogs_target = _grid_field(schema, "quarter_ramp_grid", "cogs_target")
  band = cogs_target.get("_naics_band") or {}
  assert band.get("metric_key") == "cogs_percent_of_revenue", band
  # Retail COGS NAICS-typical band is ~75-83%.
  assert 0.7 < float(cogs_target["minimum"]) < 0.85, cogs_target
  assert 0.7 < float(cogs_target["maximum"]) < 0.95, cogs_target


def test_stage_ramp_cogs_naics_band_for_software() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="stage_ramp_contract", business_naics="511210"
  )
  cogs_target = _grid_field(schema, "quarter_ramp_grid", "cogs_target")
  band = cogs_target.get("_naics_band") or {}
  assert band.get("metric_key") == "cogs_percent_of_revenue", band
  # Software COGS is typically much lower than retail (SaaS / publishers
  # have very different cost structure). Both retail and software bands
  # land WITHIN the static envelope [0.05, 0.90] — the test confirms the
  # bands DIFFER between industries, which is the whole point.
  retail_schema = post_intake_gpt_contract_openai_schema(
    contract_name="stage_ramp_contract", business_naics="455211"
  )
  retail_cogs = _grid_field(retail_schema, "quarter_ramp_grid", "cogs_target")
  assert cogs_target["minimum"] != retail_cogs["minimum"], (
    f"software and retail COGS bands should differ: software={cogs_target} retail={retail_cogs}"
  )


def test_stage_ramp_marketing_max_naics_bound() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="stage_ramp_contract", business_naics="455211"
  )
  marketing = _grid_field(schema, "quarter_ramp_grid", "marketing_max")
  band = marketing.get("_naics_band") or {}
  assert band.get("metric_key") == "marketing_percent_of_revenue", band
  assert "minimum" in marketing
  assert "maximum" in marketing


def test_stage_ramp_rev_target_keeps_static_override_via_production_wrapper() -> None:
  # rev_target / rev_max / rev_spike_max are NOT NAICS-bound (yet); they
  # keep the hardcoded rate_schema override (0..2.5) applied by
  # `_stage_ramp_contract_schema` after the contract row build.
  schema = _stage_ramp_contract_schema(business_naics="455211")
  rev_target = _grid_field(schema, "quarter_ramp_grid", "rev_target")
  assert rev_target.get("minimum") == 0
  assert rev_target.get("maximum") == 2.5
  assert "_naics_band" not in rev_target, (
    f"rev_target should not carry NAICS provenance until a future module wires the qoq metric: {rev_target}"
  )


def test_stage_ramp_q_field_integer_override_via_production_wrapper() -> None:
  schema = _stage_ramp_contract_schema(business_naics="455211")
  q_field = _grid_field(schema, "quarter_ramp_grid", "q")
  assert q_field.get("type") == "integer"
  assert q_field.get("minimum") == 1
  assert q_field.get("maximum") == 20


def test_stage_ramp_naics_bind_survives_production_wrapper() -> None:
  # The most important assertion: the NAICS-bound cogs / marketing / r&d /
  # ga / lease fields produce industry-specific bounds even after the
  # production wrapper. Confirms the override-deletion in
  # _stage_ramp_contract_schema actually let the NAICS injection through.
  schema = _stage_ramp_contract_schema(business_naics="455211")
  for field_name in ("cogs_target", "cogs_max", "marketing_max", "rd_max", "ga_max", "lease_max"):
    field = _grid_field(schema, "quarter_ramp_grid", field_name)
    assert "_naics_band" in field, f"{field_name} lost NAICS injection: {field}"
    assert "minimum" in field and "maximum" in field, (field_name, field)


def test_payroll_target_payroll_pct_naics_bound() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="payroll_headcount_schedule", business_naics="455211"
  )
  field = schema["properties"]["target_payroll_percent_of_revenue"]
  band = field.get("_naics_band") or {}
  assert band.get("metric_key") == "payroll_percent_of_revenue", band
  # iter 19 Stage 2 — mapping outer envelope tightened to [0.06, 0.80]
  # (union of tier sanity bounds). NAICS narrows within.
  assert 0.06 <= float(field["minimum"])
  assert float(field["maximum"]) <= 0.80
  assert float(field["maximum"]) - float(field["minimum"]) < 0.74, (
    f"NAICS should narrow the payroll band: {field}"
  )


def test_maintenance_capex_naics_band_no_static_universal() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="maintenance_capex_percent", business_naics="455211"
  )
  field = schema["properties"]["maintenance_capex_percent"]
  band = field.get("_naics_band") or {}
  assert band.get("metric_key") == "maintenance_capex_percent_of_revenue", band
  # v3 quantile widening — target-only band widens to ±50% of target by
  # default. So min/max should be different, not equal.
  assert "minimum" in field and "maximum" in field
  assert float(field["maximum"]) > float(field["minimum"]), (
    f"target-only band should be widened by quantiles, not collapsed: {field}"
  )


def test_no_naics_falls_through_cleanly_for_stage_ramp() -> None:
  # Without NAICS, the stage_ramp_contract schema falls back to the
  # mapping table's static envelope (0.05..0.90 for cogs_target).
  schema = post_intake_gpt_contract_openai_schema(contract_name="stage_ramp_contract")
  cogs_target = _grid_field(schema, "quarter_ramp_grid", "cogs_target")
  assert "_naics_band" not in cogs_target, cogs_target
  assert float(cogs_target["minimum"]) == 0.05
  assert float(cogs_target["maximum"]) == 0.90


def main() -> int:
  print("running test_module3_contract_sweep.py")
  print("-" * 70)
  tests = [
    ("stage_ramp_cogs_naics_for_retail", test_stage_ramp_cogs_naics_band_for_retail),
    ("stage_ramp_cogs_naics_differs_software_vs_retail", test_stage_ramp_cogs_naics_band_for_software),
    ("stage_ramp_marketing_max_naics_bound", test_stage_ramp_marketing_max_naics_bound),
    ("stage_ramp_rev_target_static_via_wrapper", test_stage_ramp_rev_target_keeps_static_override_via_production_wrapper),
    ("stage_ramp_q_field_integer_via_wrapper", test_stage_ramp_q_field_integer_override_via_production_wrapper),
    ("stage_ramp_naics_bind_survives_wrapper", test_stage_ramp_naics_bind_survives_production_wrapper),
    ("payroll_target_pct_naics_bound", test_payroll_target_payroll_pct_naics_bound),
    ("maintenance_capex_quantile_widened", test_maintenance_capex_naics_band_no_static_universal),
    ("no_naics_falls_through_cleanly", test_no_naics_falls_through_cleanly_for_stage_ramp),
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
