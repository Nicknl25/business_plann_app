"""A golden-master leg must never report green without comparing something.

Why this exists. Until 2026-08-21, a leg carrying `proof=GOLDEN_MASTER` run
WITHOUT `--prove` compared nothing at all. It built its surface, checked a
size floor and a named canary, PRINTED "GOLDEN-SHA <name> <hex>", and returned
green. The digest went to stdout and nowhere else.

Measured consequence: R49 reported `[ ok ]` on a commit that moved 61 static
text cells, and R32 carried the identical hole. These legs exist to answer one
question - "did this output change?" - and bare mode was answering it green
without looking. That made the fast gate weaker evidence than it read as, on
every text-touching commit in the stretch, not just the one that exposed it.

The failure mode this pins is SILENCE, so most of these tests assert that
something refuses to be green rather than that something passes.
"""
from __future__ import annotations

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

from replay_gate import legs as legs_mod  # noqa: E402
from replay_gate.legs import (  # noqa: E402
  BLESSED_INPUT, BLESSED_PREFIX, BLESSED_SURFACES, GOLDEN_MASTER,
  bare_golden_verdict,
)
from replay_gate.runner import all_legs  # noqa: E402


def _golden_legs():
  return [l for l in all_legs() if l.proof == GOLDEN_MASTER]


class EveryGoldenLegIsBlessedTests(unittest.TestCase):

  def test_there_are_golden_master_legs_at_all(self):
    """Guard the guard: if the label were renamed, every test below would
    pass vacuously over an empty list."""
    self.assertGreaterEqual(len(_golden_legs()), 3,
                            "expected at least R31, R32 and R49")

  def test_every_golden_leg_has_a_blessed_record(self):
    """A re-bless updates the baseline commit AND the digests. Forgetting the
    second half is the whole reason this file exists."""
    for leg in _golden_legs():
      self.assertIn(
        leg.id, BLESSED_SURFACES,
        f"{leg.id} is a golden-master leg with no BLESSED_SURFACES entry, so "
        f"bare mode cannot check it. Record its digests when re-blessing.")

  def test_every_blessed_record_names_a_surface_and_its_commit(self):
    for leg_id, record in BLESSED_SURFACES.items():
      self.assertIn("at", record,
                    f"{leg_id} does not record the commit its digests were "
                    f"taken at, which is also the leg's baseline")
      surfaces = [k for k in record if k not in ("input", "at")]
      self.assertTrue(surfaces, f"{leg_id} blesses no surface at all")
      for name in surfaces:
        self.assertGreaterEqual(
          len(record[name]), BLESSED_PREFIX,
          f"{leg_id}/{name} digest is shorter than the {BLESSED_PREFIX} "
          f"characters actually compared")

  def test_no_golden_leg_carries_its_own_baseline_literal(self):
    """The foot-gun this closes. The baseline commit and the blessed digests
    are the same fact - the commit the surface was photographed at - and
    holding it in two literals meant a re-bless could update one and not the
    other. That fired within an hour of the blessed record being introduced:
    a digest transcribed from a run predating a later fix in the same commit.

    Asserted against the SOURCE, deliberately. The obvious test - that
    leg.baseline equals the record's "at" - is now tautological, because the
    baseline is DERIVED from that record and the two cannot disagree by
    construction. A test that cannot fail is the thing this file exists to
    stop, so this one checks the property that can still regress: that the
    Leg call passes FROM_BLESSED rather than a commit of its own.
    """
    src = open(legs_mod.__file__, encoding="utf-8").read()
    for leg in _golden_legs():
      start = src.index(f'Leg("{leg.id}",')
      head = src[start:start + 400]
      self.assertIn(
        "FROM_BLESSED", head,
        f"{leg.id} passes a baseline commit of its own instead of "
        f"FROM_BLESSED, so the commit lives in two places again and a "
        f"re-bless can update one without the other")

  def test_from_blessed_without_a_record_is_loud(self):
    """The other half: resolving must fail rather than default."""
    from replay_gate.legs import FROM_BLESSED, Leg
    with self.assertRaises(KeyError) as caught:
      Leg("R_NOT_REAL", "INVARIANT", "bug", "title", "fix", FROM_BLESSED,
          lambda ctx: (True, ""))
    self.assertIn("BLESSED_SURFACES", str(caught.exception))

  def test_the_fixture_identity_is_shared_not_copied(self):
    """All three legs read the same frozen draft. Three copies of that sha is
    a fourth thing to forget."""
    self.assertGreaterEqual(len(BLESSED_INPUT), 32)
    for leg_id, record in BLESSED_SURFACES.items():
      self.assertNotIn(
        "input", record,
        f"{leg_id} carries its own copy of the fixture sha; the shared "
        f"BLESSED_INPUT is the one home")


class BareModeRefusesGreenTests(unittest.TestCase):
  """Every path that cannot verify must be red, not green."""

  GOOD = {"single_line_input": BLESSED_INPUT,
          "workbook_text": BLESSED_SURFACES["R49"]["workbook_text"]}

  def test_matching_digests_hold(self):
    ok, verdict, _ = bare_golden_verdict("R49", dict(self.GOOD))
    self.assertTrue(ok)
    self.assertEqual(verdict, "HOLDS")

  def test_a_moved_surface_is_drift(self):
    shas = dict(self.GOOD, workbook_text="deadbeefcafe0000")
    ok, verdict, detail = bare_golden_verdict("R49", shas)
    self.assertFalse(ok)
    self.assertEqual(verdict, "DRIFT")
    self.assertIn("deadbeefcafe", detail)

  def test_drift_hands_back_the_block_to_paste(self):
    """Re-blessing must not require transcribing a digest by hand from an
    earlier run - that is the exact way it went wrong."""
    shas = dict(self.GOOD, workbook_text="deadbeefcafe0000")
    _, _, detail = bare_golden_verdict("R49", shas)
    self.assertIn('"R49": {', detail)
    self.assertIn('"at": "<this commit>"', detail)
    self.assertIn('"workbook_text": "deadbeefcafe",', detail,
                  "the pasteable block must carry the digest MEASURED this "
                  "run, not the stale blessed one")

  def test_an_unblessed_leg_refuses_green(self):
    ok, verdict, _ = bare_golden_verdict("R99", dict(self.GOOD))
    self.assertFalse(ok)
    self.assertEqual(verdict, "UNBLESSED")

  def test_a_leg_that_emitted_no_digest_refuses_green(self):
    """The original defect's exact shape: nothing was hashed, so nothing was
    checked. That must not look like a pass."""
    ok, verdict, _ = bare_golden_verdict("R49", {})
    self.assertFalse(ok)
    self.assertEqual(verdict, "UNEARNED")

  def test_a_missing_surface_refuses_green(self):
    ok, verdict, _ = bare_golden_verdict(
      "R49", {"single_line_input": self.GOOD["single_line_input"]})
    self.assertFalse(ok)
    self.assertEqual(verdict, "UNEARNED")

  def test_a_moved_fixture_is_uncomparable_not_drift(self):
    """Precision matters here. A changed fixture legitimately changes every
    surface; calling that DRIFT would train everyone to re-bless through a
    real one."""
    shas = dict(self.GOOD, single_line_input="0" * 64)
    ok, verdict, detail = bare_golden_verdict("R49", shas)
    self.assertFalse(ok)
    self.assertEqual(verdict, "UNCOMPARABLE")
    self.assertNotIn("DRIFT", detail)

  def test_comparison_is_on_the_prefix_actually_recorded(self):
    """The notes quote 12 characters; a full-length digest must still match."""
    shas = dict(self.GOOD,
                workbook_text=BLESSED_SURFACES["R49"]["workbook_text"][:BLESSED_PREFIX]
                + "ffffffffffffffff")
    ok, _, _ = bare_golden_verdict("R49", shas)
    self.assertTrue(ok, "a longer digest with the blessed prefix should match")


class TheLegsRecordRatherThanOnlyPrintTests(unittest.TestCase):
  """The digests have to reach the comparator to be compared."""

  def test_no_leg_only_prints_its_golden_sha(self):
    src = open(legs_mod.__file__, encoding="utf-8").read()
    self.assertNotIn(
      'print(f"GOLDEN-SHA', src,
      "a leg is printing its golden digest instead of recording it with "
      "ctx.golden() - printed digests are invisible to bare mode, which is "
      "exactly how R49 went green on 61 moved cells")

  def test_ctx_golden_records_and_echoes(self):
    from replay_gate.context import GateContext
    ctx = GateContext.__new__(GateContext)
    ctx.reset()
    ctx.golden("workbook_text", "abc123abc123")
    self.assertEqual(ctx.golden_shas["workbook_text"], "abc123abc123")

  def test_reset_clears_the_record_between_legs(self):
    """Otherwise one leg's digest satisfies the next leg's check."""
    from replay_gate.context import GateContext
    ctx = GateContext.__new__(GateContext)
    ctx.reset()
    ctx.golden("workbook_text", "abc123abc123")
    ctx.reset()
    self.assertEqual(ctx.golden_shas, {})


if __name__ == "__main__":
  unittest.main()
