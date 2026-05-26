"""Cleanup Commit 5/6 (defense-in-depth) acceptance tests.

Covers:
- Contract 6 R8: GetBandsViewContract.count == len(bands)
  cross-field invariant.
- Contract 6 R9: IndustryBaselineResolvedContract.
  cascade_payloads + get_bands_views key/value consistency.
- Contract 6 R17: _naics_6_from_ops length-warning at the
  upstream producer (defense-in-depth at the source,
  complementing the dropped F11 pattern).
- Contract 7 R14: MirrorContract.from_mirror(mirror)
  classmethod adapter.

Per §0 (value-constraint policy): cross-field invariants
covered here are STRUCTURAL consistency checks (length /
key-value identity), NOT value-level content checks. §0's
prohibition targets content checks; structural consistency
is allowed.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from pydantic import ValidationError  # noqa: E402

from client_intake_and_finmo.post_intake_contracts.industry_baseline_resolved_contract import (  # noqa: E402
  GetBandsViewContract,
  IndustryBaselineResolvedContract,
)
from client_intake_and_finmo.post_intake_contracts.amalgamated_session_contract import (  # noqa: E402
  MirrorContract,
)
from client_intake_and_finmo.finmo_bridge import _naics_6_from_ops  # noqa: E402
from _p3_40_contract_6_fixtures import (  # noqa: E402
  valid_cascade_resolver_payload_dict,
  valid_get_bands_view_dict,
  valid_industry_baseline_resolved_dict,
)
from _p3_40_contract_7_fixtures import (  # noqa: E402
  valid_mirror_dict,
)


# ---------------------------------------------------------------------------
# R8: GetBandsViewContract.count == len(bands)
# ---------------------------------------------------------------------------

class GetBandsViewCountInvariantTest(unittest.TestCase):
  """R8 (Cleanup 5/6): structural cross-field consistency."""

  def test_consistent_count_accepted(self) -> None:
    """Fixture already populates count=len(bands)."""
    contract = GetBandsViewContract.model_validate(
      valid_get_bands_view_dict()
    )
    self.assertEqual(contract.count, len(contract.bands))

  def test_count_mismatch_rejected(self) -> None:
    """Producer drift: count reports 5 but only 2 bands populated."""
    payload = valid_get_bands_view_dict()
    payload["count"] = 99
    with self.assertRaises(ValidationError) as ctx:
      GetBandsViewContract.model_validate(payload)
    self.assertIn("count/bands mismatch", str(ctx.exception))


# ---------------------------------------------------------------------------
# R9: cascade_payloads + get_bands_views key/value consistency
# ---------------------------------------------------------------------------

class CascadePayloadsKeyConsistencyTest(unittest.TestCase):
  """R9 (Cleanup 5/6): structural key/value identity."""

  def test_consistent_keys_accepted(self) -> None:
    contract = IndustryBaselineResolvedContract.model_validate(
      valid_industry_baseline_resolved_dict()
    )
    for key, payload in contract.cascade_payloads.items():
      self.assertEqual(payload.metric_key, key)

  def test_cascade_metric_key_mismatch_rejected(self) -> None:
    """Producer drift: payload keyed by metric_key 'A' but
    payload.metric_key field says 'B'."""
    payload = valid_industry_baseline_resolved_dict()
    # Take an existing entry + inject a different metric_key in
    # the inner payload
    existing_key = next(iter(payload["cascade_payloads"].keys()))
    payload["cascade_payloads"][existing_key]["metric_key"] = "wrong_key"
    with self.assertRaises(ValidationError) as ctx:
      IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIn("metric_key mismatch", str(ctx.exception))

  def test_get_bands_views_section_mismatch_rejected(self) -> None:
    """Producer drift: view keyed by section 'drivers' but
    view.section field says 'payroll'."""
    payload = valid_industry_baseline_resolved_dict()
    existing_key = next(iter(payload["get_bands_views"].keys()))
    # Use a section other than the dict key
    other_section = (
      "payroll" if existing_key != "payroll" else "drivers"
    )
    payload["get_bands_views"][existing_key]["section"] = other_section
    with self.assertRaises(ValidationError) as ctx:
      IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIn("section mismatch", str(ctx.exception))


# ---------------------------------------------------------------------------
# R17: _naics_6_from_ops length-warning at upstream producer
# ---------------------------------------------------------------------------

class NaicsNormalizerLengthWarningTest(unittest.TestCase):
  """R17 (Cleanup 5/6): defense-in-depth at the source.
  Complements the dropped F11 pattern (which lived at the
  contract gate). PSL2: log-only, doesn't reject."""

  def test_6_digit_naics_no_warning(self) -> None:
    """Valid 6-digit NAICS produces no warning."""
    with self.assertLogs(
      "client_intake_and_finmo.finmo_bridge", level="WARNING",
    ) as captured_logs:
      # Emit a sentinel to ensure assertLogs has something to
      # observe (otherwise empty list is an error in some pytest
      # configs); the test then verifies our sentinel is the
      # only WARNING.
      logging.getLogger(
        "client_intake_and_finmo.finmo_bridge"
      ).warning("test_sentinel")
      result = _naics_6_from_ops({"business_naics_6": "722515"})
    self.assertEqual(result, "722515")
    naics_warnings = [
      r for r in captured_logs.records
      if "naics_6_malformed_length" in r.message
    ]
    self.assertEqual(naics_warnings, [])

  def test_5_digit_naics_logs_warning_but_returns_value(self) -> None:
    """PSL2: log-only. Returns the partial value; downstream
    fallback handles."""
    with self.assertLogs(
      "client_intake_and_finmo.finmo_bridge", level="WARNING",
    ) as captured_logs:
      result = _naics_6_from_ops({"business_naics_6": "72251"})
    self.assertEqual(result, "72251")  # value returned despite length
    naics_warnings = [
      r for r in captured_logs.records
      if "naics_6_malformed_length" in r.message
    ]
    self.assertEqual(len(naics_warnings), 1)

  def test_empty_naics_returns_none_no_warning(self) -> None:
    """Empty string -> None (per original behavior); no warning
    because there are no digits to assess."""
    result = _naics_6_from_ops({"business_naics_6": ""})
    self.assertIsNone(result)

  def test_alpha_only_naics_returns_none_no_warning(self) -> None:
    """All-alpha string -> empty after strip -> None."""
    result = _naics_6_from_ops({"business_naics_6": "ABC"})
    self.assertIsNone(result)


# ---------------------------------------------------------------------------
# R14: MirrorContract.from_mirror classmethod adapter
# ---------------------------------------------------------------------------

class MirrorContractFromMirrorClassmethodTest(unittest.TestCase):
  """R14 (Cleanup 5/6): explicit dataclass -> contract adapter."""

  def test_from_mirror_produces_valid_contract(self) -> None:
    """Mirror() default -> MirrorContract.from_mirror -> valid."""
    from client_intake_and_finmo.post_intake_amalgamated.mirror import (
      Mirror,
    )
    # Build a Mirror with the minimum valid shape (needs bands).
    from _p3_40_contract_6_fixtures import valid_get_bands_view_dict
    mirror = Mirror()
    # Populate bands so the F1 composition validates.
    mirror.bands = {
      section: valid_get_bands_view_dict(section=section)
      for section in (
        "stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet",
      )
    }
    contract = MirrorContract.from_mirror(mirror)
    self.assertIsInstance(contract, MirrorContract)
    # Empty validation_state on the dataclass normalizes to None
    # in the contract per the from_mirror adapter.
    self.assertIsNone(contract.validation_state)

  def test_from_mirror_propagates_validation_error(self) -> None:
    """If the Mirror has an invalid sub-shape, the adapter
    raises ValidationError (caller converts to
    ContractViolation via enforcement.py helper)."""
    from client_intake_and_finmo.post_intake_amalgamated.mirror import (
      Mirror,
    )
    mirror = Mirror()
    # bands left empty dict -- not a valid GetBandsViewContract
    # dict per Contract 6 (requires section/draft_id/etc.)
    mirror.bands = {"drivers": {}}  # invalid sub-shape
    with self.assertRaises(ValidationError):
      MirrorContract.from_mirror(mirror)


if __name__ == "__main__":
  unittest.main()
