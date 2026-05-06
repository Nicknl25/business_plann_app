"""Module 3 v1 verification — Tasks 3.1 + 3.2 + 3.3 (subset).

Verifies that the contract lookup correctly:

1. Surfaces the new NAICS-bound columns in loaded rows.
2. Injects NAICS-derived `minimum`/`maximum` into the JSON schema at
   prompt-build time when a row has `naics_baseline_metric_key`.
3. Stamps `_naics_band` provenance on the schema field.
4. Falls through cleanly when `business_naics` is not supplied (no min/max
   on the schema, no provenance stamped).
5. Emits no static `2.0`/`15.0` bound on `maintenance_capex_percent` (the
   hardcoded universal range was deleted in this module).

Run: `.venv\\Scripts\\python.exe "Test Files\\test_module3_contract_naics_bounds.py"`
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
  post_intake_gpt_contract_field_for_path,
  post_intake_gpt_contract_openai_schema,
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
# DDL load — Task 3.1.
# --------------------------------------------------------------------------


def test_contract_row_exposes_naics_bound_columns() -> None:
  row = post_intake_gpt_contract_field_for_path(
    contract_name="maintenance_capex_percent",
    field_path="maintenance_capex_percent",
  )
  assert row is not None, "maintenance_capex_percent row missing"
  for key in (
    "naics_baseline_metric_key",
    "naics_baseline_band_kind",
    "naics_baseline_min_quantile",
    "naics_baseline_max_quantile",
    "mapping_table_outer_envelope",
  ):
    assert key in row, f"contract row missing column {key}"
  assert row.get("naics_baseline_metric_key") == "maintenance_capex_percent_of_revenue", row
  assert row.get("naics_baseline_band_kind") == "min_target_max", row


def test_maintenance_capex_no_static_universal_range() -> None:
  # Before Module 3, this row carried min_value=2.0 / max_value=15.0 — a
  # universal-business range that the spec explicitly called out as a
  # legacy hardcode. Module 3 deletes those.
  row = post_intake_gpt_contract_field_for_path(
    contract_name="maintenance_capex_percent",
    field_path="maintenance_capex_percent",
  )
  assert row is not None
  assert row.get("min_value") in (None, 0, 0.0), (
    f"static min_value should be NULL/zero, got {row.get('min_value')}"
  )
  assert row.get("max_value") in (None, 0, 0.0), (
    f"static max_value should be NULL/zero, got {row.get('max_value')}"
  )


# --------------------------------------------------------------------------
# Schema build — Task 3.2.
# --------------------------------------------------------------------------


def test_schema_without_naics_emits_no_minmax_for_maintenance_capex() -> None:
  schema = post_intake_gpt_contract_openai_schema(contract_name="maintenance_capex_percent")
  field = (schema.get("properties") or {}).get("maintenance_capex_percent") or {}
  assert "minimum" not in field, f"expected no minimum without NAICS, got {field}"
  assert "maximum" not in field, f"expected no maximum without NAICS, got {field}"
  assert "_naics_band" not in field, f"expected no provenance without NAICS, got {field}"


def test_schema_with_naics_injects_band_and_provenance() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="maintenance_capex_percent", business_naics="455211"
  )
  field = (schema.get("properties") or {}).get("maintenance_capex_percent") or {}
  assert "minimum" in field, f"expected NAICS-derived minimum, got {field}"
  assert "maximum" in field, f"expected NAICS-derived maximum, got {field}"
  assert isinstance(field.get("_naics_band"), dict), f"missing provenance: {field}"
  band = field["_naics_band"]
  assert band.get("metric_key") == "maintenance_capex_percent_of_revenue"
  assert band.get("trust_flag") in (
    "naics_6_direct",
    "naics_5_fallback",
    "naics_4_fallback",
    "naics_3_fallback",
    "naics_2_fallback",
    "generic_default",
  ), band
  # The injected min/max must equal the resolver's source values when
  # `mapping_table_outer_envelope=False` (no static fallback to intersect).
  assert band.get("effective_min") == band.get("source_min"), band
  assert band.get("effective_max") == band.get("source_max"), band


def test_schema_with_naics_for_software_naics_resolves() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="maintenance_capex_percent", business_naics="511210"
  )
  field = (schema.get("properties") or {}).get("maintenance_capex_percent") or {}
  band = field.get("_naics_band") or {}
  assert band.get("metric_key") == "maintenance_capex_percent_of_revenue"
  # Software typically has different maintenance capex than retail; we just
  # confirm the resolver landed on something rather than no_coverage.
  assert band.get("trust_flag") != "no_coverage", band


def test_schema_with_invalid_naics_falls_through_gracefully() -> None:
  schema = post_intake_gpt_contract_openai_schema(
    contract_name="maintenance_capex_percent", business_naics=""
  )
  field = (schema.get("properties") or {}).get("maintenance_capex_percent") or {}
  assert "_naics_band" not in field, f"empty NAICS should not stamp provenance: {field}"


def test_outer_envelope_intersection_when_static_present() -> None:
  # Inject an artificial contract row scenario via field_schema_overrides:
  # we want to verify the outer-envelope intersection logic. Easiest path:
  # directly call _resolve_naics_bound through the lookup. Public API is
  # via the schema build, so we synthesize a minimum case here.
  from client_intake_and_finmo.post_intake_mapping import post_intake_gpt_contract_lookup
  lookup = post_intake_gpt_contract_lookup()
  synthetic_row = {
    "contract_name": "synthetic_test",
    "min_value": 0.10,
    "max_value": 0.20,
    "naics_baseline_metric_key": "cogs_percent_of_revenue",
    "naics_baseline_band_kind": "min_target_max",
    "mapping_table_outer_envelope": True,
  }
  effective_min, effective_max, prov = lookup._resolve_naics_bound(  # type: ignore[attr-defined]
    synthetic_row, business_naics="455211"
  )
  # NAICS COGS for 455211 is roughly 75-83%. The static envelope is 10-20%.
  # Outer envelope means the static is the absolute cap — NAICS band falls
  # entirely outside [0.10, 0.20], so the intersection is empty and the
  # resolver should retain the static envelope as a safety fallback.
  assert prov is not None, "provenance should still record the attempt"
  assert prov.get("outer_envelope_applied") is True
  # When intersection is empty, effective bounds revert to static.
  assert effective_min == 0.10, effective_min
  assert effective_max == 0.20, effective_max


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_module3_contract_naics_bounds.py")
  print("-" * 70)
  tests = [
    ("contract_row_exposes_naics_bound_columns", test_contract_row_exposes_naics_bound_columns),
    ("maintenance_capex_no_static_universal_range", test_maintenance_capex_no_static_universal_range),
    ("schema_without_naics_emits_no_minmax", test_schema_without_naics_emits_no_minmax_for_maintenance_capex),
    ("schema_with_naics_injects_band_and_provenance", test_schema_with_naics_injects_band_and_provenance),
    ("schema_with_naics_for_software_naics", test_schema_with_naics_for_software_naics_resolves),
    ("schema_with_invalid_naics_falls_through", test_schema_with_invalid_naics_falls_through_gracefully),
    ("outer_envelope_intersection_with_static", test_outer_envelope_intersection_when_static_present),
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
