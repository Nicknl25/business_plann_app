"""A named person is a person: the payroll budget scaler must not resize one.

``enforce_labor_scaling_on_payload`` makes payroll scale with revenue for a
labor-bound business: each quarter gets a factor and every title's FTE
trajectory is multiplied by it until quarterly payroll tracks
``revenue_q x target_payroll_percent_of_revenue``. It used to multiply EVERY
title - named individuals included - so an owner the client named by name came
out of the plan at 1.21 people, because that was the ratio that made payroll
hit the target percent. The realism row for payroll_percent_of_revenue already
stated the doctrine that violates: "payroll is NOT clipped to fit revenue
(Golden Rule preservation)". Resizing a person is clipping payroll to fit
revenue.

3560a08 fixed it in two halves, and this file guards both:

  HALF A - THE EXEMPTION. Rows with ``staffing_class == "key_person"`` are
  skipped by the scaling loop. They stay where intake put them: 1.0 for a
  full-timer, and the stated fraction for a real part-timer, which the
  part-time-hours adaptation sets before this runs and must not disturb.

  HALF B - THE FACTOR. With named people exempt, the supporting block is the
  only part that still scales, so the factor is solved on supporting payroll
  alone: supporting moves to ``target - named`` and the factor is that over
  what supporting authors today. Solved on FULL payroll instead, the exemption
  still holds every name at its stated FTE but the supporting block lands in
  the wrong place and the plan misses its own target.

Half A shipped with no test at all. Reverted completely - the ``continue``
dropped and the factor solved on full payroll again - all 57 payroll tests and
all 27 scaler-adjacent tests still passed. Nothing was red. This file is that
missing red.

MEASURED on the 1,097 stored payrolls, driving the scaler from both trees with
the orchestrator's own synthetic anchor: the pre-fix code moves a named
person's FTE on 501 drafts in the round-1 up-only shape and on 501 in the
Phase B allow_scale_down shape (part-timers on a further 230 and 395); the
fixed code moves one on ZERO. The worst inflation is Sunny Glaze Donuts
4a47ec91, where Jordan Lee - one owner, stated at 1.0 - comes out at 11.22 of
himself. No named full-timer is driven BELOW 1.0 by today's code: the Q1
starting-FTE floor holds them, so the observable defect is inflation for a
full-timer and flattening for a part-timer (a stated 0.42 pushed back to her
Q1 0.41 by the Phase B trim).

The payloads are real and stored, captured verbatim from
``intake_consult_drafts`` (the capture query and timestamp ride inside the
fixture). The anchor is not invented either - it is rebuilt here by the
orchestrator's own formula, ``payroll_budget[q] = revenue[q] x
target_payroll_percent_of_revenue`` over finmo_json's quarter_rows
(orchestrator.py:2987-2996), and both call shapes are exercised: the round-1
up-only call and the Phase B ``allow_scale_down=True`` call
(orchestrator.py:3659), which is the shape that shrinks a person.

  Sunny Glaze Donuts (537e824e) - the OVER-BUDGET case. Jordan Lee, owner and
  manager, stated at 1.0 in all 20 quarters; Maria Gonzalez, lead baker
  (part-time), stated at 0.41 / 0.42 / 0.44 / 0.45 / 0.46 across the horizon.
  Named payroll alone already exceeds the target, so there is nothing for the
  supporting block to absorb - it sits at its floor and the plan carries an
  honest overage rather than fractionally deleting someone.

  Anderson & Blake Legal Associates (09d10c39) - the ABSORBING case. Two named
  full-timers and a real supporting block of paralegals that takes the whole
  adjustment: 2.0 FTE authored, 22.99 after, landing supporting payroll on
  target-minus-named at the first scaled quarter.
"""
from __future__ import annotations

import copy
import gzip
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, os.path.join(ROOT, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

FIXTURE = os.path.join(HERE, "fixtures", "payroll_named_person_payloads.json.gz")
SUNNY = "537e824e"      # Sunny Glaze Donuts - over-budget, one full-timer + one part-timer
ANDERSON = "09d10c39"   # Anderson & Blake - supporting block absorbs the whole delta

# Maria Gonzalez, lead baker (part-time), as intake stated her.
MARIA = [0.41] * 4 + [0.42] * 4 + [0.44] * 4 + [0.45] * 4 + [0.46] * 4


def _fixture():
  with gzip.open(FIXTURE, "rt", encoding="utf-8") as fh:
    return json.load(fh)["drafts"]


def _payload(short):
  return json.loads(_fixture()[short]["payroll_headcount"])


def _anchor(short):
  """The orchestrator's own synthetic anchor, rebuilt (orchestrator.py:2987-2996)."""
  draft = _fixture()[short]
  target_pct = float(json.loads(draft["payroll_headcount"])["target_payroll_percent_of_revenue"])
  return {
    "labor_intensity_class": json.loads(draft["payroll_headcount"]).get("labor_intensity_class"),
    "per_quarter": [
      {"q": int(r["quarter_index"]), "payroll_budget": float(r.get("revenue") or 0.0) * target_pct}
      for r in draft["finmo_quarter_rows"]
      if int(r.get("quarter_index") or 0) >= 1
    ],
  }


def _target_by_q(short):
  return {int(p["q"]): float(p["payroll_budget"]) for p in _anchor(short)["per_quarter"]}


def _is_named(row):
  return str(row.get("staffing_class") or "").strip().lower() == "key_person"


def _fte_series(payload, person):
  by_q = {int(r["quarter_index"]): float(r.get("ending_fte") or 0.0)
          for r in payload["rows"] if _is_named(r) and r.get("person_name") == person}
  return [by_q[q] for q in sorted(by_q)]


def _named_people(payload):
  return sorted({r.get("person_name") for r in payload["rows"] if _is_named(r)})


def _payroll_by_q(payload, named):
  """Quarterly payroll from the named half (``named=True``) or the supporting half."""
  out = {}
  for r in payload["rows"]:
    if _is_named(r) is not named:
      continue
    q = int(r["quarter_index"])
    out[q] = out.get(q, 0.0) + float(r.get("total_quarterly_payroll") or 0.0)
  return out


def _supporting_fte_by_q(payload):
  out = {}
  for r in payload["rows"]:
    if _is_named(r):
      continue
    q = int(r["quarter_index"])
    out[q] = round(out.get(q, 0.0) + float(r.get("ending_fte") or 0.0), 2)
  return out


def _scale(short, allow_scale_down):
  """Drive the real scaler on a copy of the real stored payload."""
  from client_intake_and_finmo.post_intake_headcount.schedule import (
    enforce_labor_scaling_on_payload,
  )
  before = _payload(short)
  after = copy.deepcopy(before)
  summary = enforce_labor_scaling_on_payload(after, _anchor(short), allow_scale_down=allow_scale_down)
  return before, after, summary


# Both call shapes the orchestrator makes: round 1 is up-only, Phase B's payroll
# lever may also trim, and the trim is the shape that shrinks a person.
CALL_SHAPES = [("round1_up_only", False), ("phase_b_allow_scale_down", True)]


class TheFixtureCarriesTheClassTests(unittest.TestCase):
  """Control. If the stored payloads stop carrying named people, or the anchor
  stops moving them, the guard below is vacuous and must say so."""

  def test_the_named_people_are_stored_as_intake_stated_them(self):
    sunny = _payload(SUNNY)
    self.assertEqual(_named_people(sunny), ["Jordan Lee", "Maria Gonzalez"])
    self.assertEqual(_fte_series(sunny, "Jordan Lee"), [1.0] * 20,
                     "Jordan Lee is a full-timer stated at 1.0 - fixture no longer carries the class")
    self.assertEqual(_fte_series(sunny, "Maria Gonzalez"), MARIA,
                     "Maria Gonzalez is a stated part-timer - fixture no longer carries the class")
    anderson = _payload(ANDERSON)
    self.assertEqual(_named_people(anderson), ["Emily Anderson", "Michael Blake"])
    for who in _named_people(anderson):
      self.assertEqual(_fte_series(anderson, who), [1.0] * 20)

  def test_both_drafts_have_a_supporting_block_to_absorb_with(self):
    for short in (SUNNY, ANDERSON):
      supporting = [r for r in _payload(short)["rows"] if not _is_named(r)]
      self.assertTrue(supporting, f"{short}: no supporting rows - nothing could absorb")

  def test_the_anchor_actually_moves_both_drafts_in_both_call_shapes(self):
    for short in (SUNNY, ANDERSON):
      for label, allow_scale_down in CALL_SHAPES:
        _, _, summary = _scale(short, allow_scale_down)
        self.assertIsNotNone(summary, f"{short}/{label}: scaler declined to scale - guard is vacuous")
        self.assertTrue(summary.get("scaled"))

  def test_sunny_glaze_is_the_over_budget_case_and_anderson_is_not(self):
    """The two drafts must stay on opposite sides of the affordability line,
    or the over-budget and absorbing assertions below stop meaning anything."""
    sunny_named, sunny_target = _payroll_by_q(_payload(SUNNY), True), _target_by_q(SUNNY)
    self.assertGreater(sunny_named[1], sunny_target[1],
                       "Sunny Glaze must not be able to fund its named people out of target")
    and_named, and_target = _payroll_by_q(_payload(ANDERSON), True), _target_by_q(ANDERSON)
    self.assertLess(and_named[1], and_target[1],
                    "Anderson & Blake must have room left over for supporting to absorb into")


class ANamedPersonIsNeverResizedTests(unittest.TestCase):
  """HALF A - the exemption. Every one of these goes red the moment the
  ``key_person`` skip is dropped from the scaling loop."""

  def test_named_full_timers_land_at_exactly_one(self):
    cases = [(SUNNY, "Jordan Lee"), (ANDERSON, "Emily Anderson"), (ANDERSON, "Michael Blake")]
    for short, who in cases:
      for label, allow_scale_down in CALL_SHAPES:
        with self.subTest(draft=short, person=who, call=label):
          _, after, _ = _scale(short, allow_scale_down)
          got = _fte_series(after, who)
          self.assertEqual(got, [1.0] * 20,
                           f"{who} was stated at 1.0 and came out at {sorted(set(got))} - "
                           "the plan emits a fraction of a named person")

  def test_a_stated_part_timer_keeps_her_own_fraction(self):
    for label, allow_scale_down in CALL_SHAPES:
      with self.subTest(call=label):
        _, after, _ = _scale(SUNNY, allow_scale_down)
        self.assertEqual(_fte_series(after, "Maria Gonzalez"), MARIA,
                         "Maria Gonzalez's stated part-time fraction was overwritten by the "
                         "budget factor - the up-only shape inflates it, the Phase B trim "
                         "flattens it back to her Q1 0.41")

  def test_every_named_row_comes_through_untouched(self):
    """Not just the FTE: a named person's whole row - hires, average FTE, wage
    cost, taxes and total payroll - is a fixed cost of the roster."""
    fields = ("starting_fte", "hires", "ending_fte", "average_fte",
              "quarterly_wage_cost", "quarterly_taxes_benefits", "total_quarterly_payroll")
    for short in (SUNNY, ANDERSON):
      for label, allow_scale_down in CALL_SHAPES:
        with self.subTest(draft=short, call=label):
          before, after, _ = _scale(short, allow_scale_down)
          key = lambda r: (r.get("person_name"), r.get("position_title"), int(r["quarter_index"]))
          was = {key(r): {f: r.get(f) for f in fields} for r in before["rows"] if _is_named(r)}
          now = {key(r): {f: r.get(f) for f in fields} for r in after["rows"] if _is_named(r)}
          self.assertEqual(sorted(was), sorted(now), "a named row appeared or vanished")
          moved = [(k, was[k], now[k]) for k in was if was[k] != now[k]]
          self.assertFalse(moved, f"{len(moved)} named rows were rewritten, e.g. {moved[:2]}")

  def test_the_supporting_block_absorbs_the_whole_adjustment(self):
    """Whatever the scaler moves, it moves out of the supporting block: the
    change in total payroll equals the change in supporting payroll, exactly."""
    for short in (SUNNY, ANDERSON):
      for label, allow_scale_down in CALL_SHAPES:
        with self.subTest(draft=short, call=label):
          before, after, _ = _scale(short, allow_scale_down)
          named_before, named_after = _payroll_by_q(before, True), _payroll_by_q(after, True)
          sup_before, sup_after = _payroll_by_q(before, False), _payroll_by_q(after, False)
          for q in sorted(named_before):
            total_delta = ((named_after[q] + sup_after[q]) - (named_before[q] + sup_before[q]))
            self.assertAlmostEqual(total_delta, sup_after[q] - sup_before[q], places=2,
                                   msg=f"Q{q}: the named half moved by "
                                       f"{named_after[q] - named_before[q]:,.0f}")

  def test_the_over_budget_case_is_left_honest_rather_than_clipped(self):
    """In its early quarters Sunny Glaze cannot fund Jordan Lee and Maria out
    of revenue x target% at all. The ruled outcome is that the plan says so:
    nobody is fractionally deleted, the supporting block is not cut below what
    it authored, and the overage stands where the money genuinely is not there.
    (Later quarters grow into the budget and supporting does get to move - so
    this is asserted per quarter, on the quarters that are actually short.)"""
    target = _target_by_q(SUNNY)
    for label, allow_scale_down in CALL_SHAPES:
      with self.subTest(call=label):
        before, after, _ = _scale(SUNNY, allow_scale_down)
        named = _payroll_by_q(after, True)
        total = {q: named[q] + _payroll_by_q(after, False)[q] for q in named}
        fte_before, fte_after = _supporting_fte_by_q(before), _supporting_fte_by_q(after)
        short_quarters = [q for q in sorted(target) if named[q] > target[q]]
        self.assertTrue(short_quarters, "Sunny Glaze is no longer the over-budget case")
        for q in short_quarters:
          self.assertGreater(total[q], target[q],
                             f"Q{q}: payroll was clipped to fit revenue")
          self.assertGreaterEqual(fte_after[q], fte_before[q],
                                  f"Q{q}: the supporting block was cut to pay for the overage")


class TheFactorIsSolvedOnSupportingPayrollAloneTests(unittest.TestCase):
  """HALF B - the factor. The exemption alone is not enough: with named people
  held fixed but the factor still solved on FULL payroll, every name stays put
  and the supporting block lands in the wrong place. Anderson & Blake is the
  case with room to absorb into, so it is where this is visible."""

  def test_supporting_lands_on_target_minus_named_at_the_first_scaled_quarter(self):
    """At the first scaled quarter there is no earlier quarter to ratchet or
    carry from, so the solved factor is observable directly: supporting payroll
    must land on (target - named). Solved on full payroll it lands on
    supporting x (target / total) instead - a different number entirely."""
    target = _target_by_q(ANDERSON)
    for label, allow_scale_down in CALL_SHAPES:
      with self.subTest(call=label):
        before, after, summary = _scale(ANDERSON, allow_scale_down)
        q0 = int(summary["first_scaled_quarter"])
        named = _payroll_by_q(after, True)[q0]
        want = target[q0] - named
        self.assertGreater(want, 0.0, "Anderson & Blake must have room left to absorb into")
        got = _payroll_by_q(after, False)[q0]
        wrong = (_payroll_by_q(before, False)[q0]
                 * (target[q0] / (_payroll_by_q(before, True)[q0] + _payroll_by_q(before, False)[q0])))
        # 1% covers the scaler's own 2-dp FTE grid; the full-payroll solve
        # misses by more than 60% on this draft, so the two cannot be confused.
        self.assertLessEqual(abs(got - want), 0.01 * want,
                             f"Q{q0}: supporting landed at {got:,.0f}, target-minus-named is "
                             f"{want:,.0f}; a factor solved on FULL payroll would land it at "
                             f"about {wrong:,.0f}")

  def test_the_supporting_block_really_did_move(self):
    """If supporting never moves, the assertion above passes for the wrong
    reason. On this draft the paralegals go from 2.0 FTE to about 23."""
    for label, allow_scale_down in CALL_SHAPES:
      with self.subTest(call=label):
        before, after, summary = _scale(ANDERSON, allow_scale_down)
        q0 = int(summary["first_scaled_quarter"])
        self.assertGreater(_supporting_fte_by_q(after)[q0],
                           _supporting_fte_by_q(before)[q0] * 2.0,
                           "supporting did not absorb - nothing to measure the factor against")


if __name__ == "__main__":
  unittest.main()
