"""Phase 9 P3.33 Phase 3 step 4d — stage_ramp + payroll revise_* tools.

Companion to step 4c's tests. The shared deep_merge_patch helper is
covered there; these tests focus on stage_ramp + payroll passthrough,
the rejection short-circuits, and the patch_applied audit field.

Memo §13.1 acceptance: each revise_* is round-trip tested via a fake
setter — patch -> re-validate -> accept, plus out-of-band patch ->
reject with structured violation.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class _FakeSetter:
  def __init__(self, *, accepted: bool, section: str, violations=None, extra=None):
    self.accepted = accepted
    self.section = section
    self.violations = list(violations or [])
    self.extra = dict(extra or {})
    self.calls = []

  def __call__(self, **kwargs):
    self.calls.append(kwargs)
    envelope = {
      "accepted": self.accepted,
      "section": self.section,
      "violations": list(self.violations),
      "bands_echoed": {"echoed": True},
      "decision_source": "amalgamated_gpt_supplied",
    }
    envelope.update(self.extra)
    return envelope


# ---------------------------------------------------------------------------
# revise_stage_ramp_contract
# ---------------------------------------------------------------------------

class ReviseStageRampTest(unittest.TestCase):
  def test_patch_merged_before_setter_called(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_stage_ramp_contract import (  # noqa: E501
      revise_stage_ramp_contract,
    )
    base = {"cogs_max": [0.7, 0.68, 0.66], "marketing_max": [0.12, 0.11, 0.10]}
    patch = {"cogs_max": [0.65, 0.63, 0.61]}
    setter = _FakeSetter(accepted=True, section="stage_ramp",
                         extra={"contract": "merged"})

    env = revise_stage_ramp_contract(
      current_contract=base, patch=patch,
      _set_stage_ramp_contract=setter,
    )

    self.assertTrue(env["accepted"])
    self.assertEqual(env["section"], "stage_ramp")
    self.assertEqual(env["patch_applied"], ["cogs_max"])
    self.assertEqual(len(setter.calls), 1)
    forwarded = setter.calls[0]["contract"]
    self.assertEqual(forwarded["cogs_max"], [0.65, 0.63, 0.61])
    self.assertEqual(forwarded["marketing_max"], [0.12, 0.11, 0.10])

  def test_rejection_passthrough_with_violations_and_patch_applied(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_stage_ramp_contract import (  # noqa: E501
      revise_stage_ramp_contract,
    )
    setter = _FakeSetter(
      accepted=False, section="stage_ramp",
      violations=[{"code": "stage_ramp_grid_out_of_band",
                   "field": "cogs_max", "delta": 0.04}],
    )
    env = revise_stage_ramp_contract(
      current_contract={"cogs_max": [0.7, 0.68, 0.66]},
      patch={"cogs_max": [0.30, 0.28, 0.27]},   # too low
      _set_stage_ramp_contract=setter,
    )
    self.assertFalse(env["accepted"])
    self.assertEqual(env["violations"][0]["code"], "stage_ramp_grid_out_of_band")
    self.assertEqual(env["patch_applied"], ["cogs_max"])

  def test_no_current_contract_rejects_without_calling_setter(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_stage_ramp_contract import (  # noqa: E501
      revise_stage_ramp_contract,
    )
    setter = _FakeSetter(accepted=True, section="stage_ramp")
    env = revise_stage_ramp_contract(
      current_contract=None, patch={"cogs_max": [0.6, 0.58, 0.56]},
      _set_stage_ramp_contract=setter,
    )
    self.assertFalse(env["accepted"])
    self.assertEqual(env["violations"][0]["code"], "no_current_stage_ramp_contract")
    self.assertEqual(setter.calls, [])

  def test_empty_patch_rejects_without_calling_setter(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_stage_ramp_contract import (  # noqa: E501
      revise_stage_ramp_contract,
    )
    setter = _FakeSetter(accepted=True, section="stage_ramp")
    env = revise_stage_ramp_contract(
      current_contract={"cogs_max": [0.7]}, patch={},
      _set_stage_ramp_contract=setter,
    )
    self.assertFalse(env["accepted"])
    self.assertEqual(env["violations"][0]["code"], "stage_ramp_patch_required")
    self.assertEqual(setter.calls, [])

  def test_passthrough_kwargs_forwarded_to_setter(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_stage_ramp_contract import (  # noqa: E501
      revise_stage_ramp_contract,
    )
    setter = _FakeSetter(accepted=True, section="stage_ramp",
                         extra={"contract": "merged"})
    revise_stage_ramp_contract(
      current_contract={"cogs_max": [0.7]},
      patch={"cogs_max": [0.65]},
      planning_mode="operational",
      expected_stage_family="operational",
      _set_stage_ramp_contract=setter,
    )
    fwd = setter.calls[0]
    self.assertEqual(fwd["planning_mode"], "operational")
    self.assertEqual(fwd["expected_stage_family"], "operational")


# ---------------------------------------------------------------------------
# revise_payroll_schedule
# ---------------------------------------------------------------------------

class RevisePayrollTest(unittest.TestCase):
  def test_patch_merged_and_forwarded(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_payroll_schedule import (  # noqa: E501
      revise_payroll_schedule,
    )
    base = {
      "classes": {
        "engineering": {"fte_q1": 4, "fte_q12": 12},
        "sales":       {"fte_q1": 1, "fte_q12":  6},
      },
    }
    patch = {"classes": {"sales": {"fte_q12": 4}}}
    setter = _FakeSetter(accepted=True, section="payroll",
                         extra={"contract": "merged", "payload": {}})
    env = revise_payroll_schedule(
      current_contract=base, patch=patch,
      _set_payroll_schedule=setter,
    )
    self.assertTrue(env["accepted"])
    self.assertEqual(env["patch_applied"], ["classes.sales.fte_q12"])
    forwarded = setter.calls[0]["contract"]
    self.assertEqual(forwarded["classes"]["sales"], {"fte_q1": 1, "fte_q12": 4})
    self.assertEqual(forwarded["classes"]["engineering"], {"fte_q1": 4, "fte_q12": 12})

  def test_no_current_contract_rejects(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_payroll_schedule import (  # noqa: E501
      revise_payroll_schedule,
    )
    setter = _FakeSetter(accepted=True, section="payroll")
    env = revise_payroll_schedule(
      current_contract={}, patch={"x": 1},
      _set_payroll_schedule=setter,
    )
    self.assertFalse(env["accepted"])
    self.assertEqual(env["violations"][0]["code"], "no_current_payroll_contract")
    self.assertEqual(setter.calls, [])

  def test_empty_patch_rejects(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_payroll_schedule import (  # noqa: E501
      revise_payroll_schedule,
    )
    setter = _FakeSetter(accepted=True, section="payroll")
    env = revise_payroll_schedule(
      current_contract={"classes": {"engineering": {"fte_q1": 4}}},
      patch={},
      _set_payroll_schedule=setter,
    )
    self.assertFalse(env["accepted"])
    self.assertEqual(env["violations"][0]["code"], "payroll_patch_required")
    self.assertEqual(setter.calls, [])


class PackageReexportsTest(unittest.TestCase):
  def test_stage_ramp_and_payroll_revise_tools_re_exported(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools import (
      revise_stage_ramp_contract, revise_payroll_schedule,
    )
    self.assertTrue(callable(revise_stage_ramp_contract))
    self.assertTrue(callable(revise_payroll_schedule))


if __name__ == "__main__":
  unittest.main()
