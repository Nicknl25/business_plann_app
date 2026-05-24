"""Phase 9 P3.33 Phase 3 step 4c — drivers + capex_rd_balance_seed revise
tools (+ shared deep-merge helper).

Memo §13.1 acceptance: "Each revise_* is round-trip tested: patch →
re-validate → accept; out-of-band patch → reject with structured
violation."

This commit ships the helper and the two simplest revise_* tools.
``revise_stage_ramp_contract`` and ``revise_payroll_schedule`` land in
the next commit with their own tests.

Hermetic — exercises the tools against a fake setter that records its
inputs (confirms merge happens before validation and the envelope is
passed through with the ``patch_applied`` audit field added).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


# ---------------------------------------------------------------------------
# deep_merge_patch — shared helper
# ---------------------------------------------------------------------------

class DeepMergePatchTest(unittest.TestCase):
  def test_nested_dict_merges_recursively(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools._patch import (
      deep_merge_patch,
    )
    base = {
      "drivers": {"COGS": 0.72, "Marketing": 0.10, "G&A": 0.18},
      "stage_ramp": {"cogs_max": [0.7, 0.68, 0.66]},
    }
    patch = {"drivers": {"COGS": 0.65}}
    merged, applied = deep_merge_patch(base, patch)
    self.assertEqual(merged["drivers"]["COGS"], 0.65)
    self.assertEqual(merged["drivers"]["Marketing"], 0.10)
    self.assertEqual(merged["drivers"]["G&A"], 0.18)
    self.assertEqual(merged["stage_ramp"]["cogs_max"], [0.7, 0.68, 0.66])
    self.assertEqual(applied, ["drivers.COGS"])

  def test_scalar_in_overlay_replaces_dict_in_base(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools._patch import (
      deep_merge_patch,
    )
    base = {"drivers": {"COGS": 0.72}}
    patch = {"drivers": 0.65}  # wholesale replacement
    merged, applied = deep_merge_patch(base, patch)
    self.assertEqual(merged, {"drivers": 0.65})
    self.assertEqual(applied, ["drivers"])

  def test_list_values_are_replaced_wholesale(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools._patch import (
      deep_merge_patch,
    )
    base = {"cogs_max": [0.7, 0.68, 0.66, 0.64]}
    patch = {"cogs_max": [0.6, 0.58, 0.56, 0.55]}
    merged, applied = deep_merge_patch(base, patch)
    self.assertEqual(merged["cogs_max"], [0.6, 0.58, 0.56, 0.55])
    self.assertEqual(applied, ["cogs_max"])

  def test_input_not_mutated(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools._patch import (
      deep_merge_patch,
    )
    base = {"drivers": {"COGS": 0.72, "Marketing": 0.10}}
    patch = {"drivers": {"COGS": 0.65}}
    merged, _ = deep_merge_patch(base, patch)
    # base preserved, patch preserved, keys outside the patch carried over.
    self.assertEqual(base["drivers"]["COGS"], 0.72)
    self.assertEqual(patch["drivers"]["COGS"], 0.65)
    self.assertEqual(merged["drivers"]["Marketing"], 0.10)


# ---------------------------------------------------------------------------
# Fake setter — records the merged contract the revise_* tool defers with
# ---------------------------------------------------------------------------

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
# revise_drivers
# ---------------------------------------------------------------------------

class ReviseDriversTest(unittest.TestCase):
  def test_anchor_dict_patched_per_lever(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_drivers import (
      revise_drivers,
    )
    current = {
      "expenses::Cost of Goods Sold": {"q1": 0.72, "q11": 0.66, "q20": 0.62},
      "expenses::Marketing":          {"q1": 0.12, "q11": 0.10, "q20": 0.08},
    }
    patch = {"expenses::Cost of Goods Sold": {"q1": 0.65, "q11": 0.60}}
    setter = _FakeSetter(accepted=True, section="drivers",
                         extra={"anchors": "merged", "commit_summary": {}})

    env = revise_drivers(
      current_anchors=current, patch=patch,
      operating_context={"model_input_template": {}},
      _set_drivers=setter,
    )
    self.assertTrue(env["accepted"])
    self.assertSetEqual(
      set(env["patch_applied"]),
      {"expenses::Cost of Goods Sold.q1", "expenses::Cost of Goods Sold.q11"},
    )
    forwarded = setter.calls[0]["anchors"]
    self.assertEqual(
      forwarded["expenses::Cost of Goods Sold"],
      {"q1": 0.65, "q11": 0.60, "q20": 0.62},
    )
    self.assertEqual(forwarded["expenses::Marketing"]["q1"], 0.12)

  def test_band_violation_passthrough(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_drivers import (
      revise_drivers,
    )
    setter = _FakeSetter(
      accepted=False, section="drivers",
      violations=[{"code": "driver_anchor_below_band_min",
                   "lever_id": "expenses::Cost of Goods Sold",
                   "anchor": "q1", "actual": 0.30, "band_min": 0.45,
                   "delta": 0.15, "units": "fraction"}],
      extra={"anchors": None, "commit_summary": None},
    )
    env = revise_drivers(
      current_anchors={"expenses::Cost of Goods Sold": {"q1": 0.72}},
      patch={"expenses::Cost of Goods Sold": {"q1": 0.30}},
      operating_context={"model_input_template": {}},
      _set_drivers=setter,
    )
    self.assertFalse(env["accepted"])
    self.assertEqual(env["violations"][0]["code"],
                     "driver_anchor_below_band_min")
    self.assertEqual(env["patch_applied"],
                     ["expenses::Cost of Goods Sold.q1"])


# ---------------------------------------------------------------------------
# revise_capex_rd_balance_seed
# ---------------------------------------------------------------------------

class ReviseCapexRdBalanceSeedTest(unittest.TestCase):
  def test_overrides_composed_with_patch(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_capex_rd_balance_seed import (  # noqa: E501
      revise_capex_rd_balance_seed,
    )
    current_overrides = {"maintenance_capex_percent": 0.04}
    patch = {"r_and_d_applicability": {"r_and_d_enabled": False}}
    setter = _FakeSetter(accepted=True, section="capex_rd_balance_seed",
                         extra={"payload": {}, "overrides_applied": [
                           {"section": "r_and_d_applicability",
                            "field": "r_and_d_enabled", "applied": False},
                         ]})

    env = revise_capex_rd_balance_seed(
      current_overrides=current_overrides, patch=patch,
      _set_capex_rd_balance_seed=setter,
    )
    self.assertTrue(env["accepted"])
    # base lacked an r_and_d_applicability sub-dict, so the patch added the
    # whole sub-dict as one unit — recorded at the top-level key.
    self.assertEqual(env["patch_applied"], ["r_and_d_applicability"])
    forwarded = setter.calls[0]["overrides"]
    self.assertEqual(forwarded["maintenance_capex_percent"], 0.04)
    self.assertEqual(forwarded["r_and_d_applicability"],
                     {"r_and_d_enabled": False})

  def test_empty_patch_rejects(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_capex_rd_balance_seed import (  # noqa: E501
      revise_capex_rd_balance_seed,
    )
    setter = _FakeSetter(accepted=True, section="capex_rd_balance_seed")
    env = revise_capex_rd_balance_seed(
      current_overrides={"maintenance_capex_percent": 0.04},
      patch={},
      _set_capex_rd_balance_seed=setter,
    )
    self.assertFalse(env["accepted"])
    self.assertEqual(env["violations"][0]["code"],
                     "capex_rd_balance_seed_patch_required")
    self.assertEqual(setter.calls, [])


class PackageReexportsTest(unittest.TestCase):
  def test_revise_tools_re_exported_from_tools_package(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools import (
      revise_drivers, revise_capex_rd_balance_seed,
    )
    for fn in (revise_drivers, revise_capex_rd_balance_seed):
      self.assertTrue(callable(fn))


if __name__ == "__main__":
  unittest.main()
