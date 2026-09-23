"""THE GUARD AT THE WRITE, not at the declaration.

Nick 2026-09-22, taking Cowork's argument: "a guard at the write boundary
catches the mislabel whatever slot it picks next, and there is always another
slot." Three days were spent closing slots one at a time - avg_units_per_week_year1,
then operating_periods_per_year, then operating_weeks_per_year - and each time the
next wrong answer simply picked a different field.

The one moment in the whole investigation when the app caught a mislabel BY
ITSELF was Ashgrove Bindery bf731ee4 turn 12: "About eleven hundred" arrived
labelled as a count of periods, something saw that a year cannot hold 1,100 of
those, and it stopped to ask. Everything here generalises that moment.

TWO GUARDS, because one is not enough and the run proved it:

  WHAT THE FIELD CAN HOLD. Arithmetic, never judgment - a year holds 12 months,
  53 weeks, and on job work one slot turns over at most once a day. Catches
  Ashgrove's 1,100 and Perrin Row's 930.

  WHAT SHE ALREADY TOLD US. 48 turns a year is entirely plausible; it was only
  wrong against her own "about eleven hundred a year". No range check would ever
  have caught the turn that killed CW-076, and this is the one that does.

Both HOLD the figure rather than dropping it, because dropping a client's number
is how her sentence becomes silence - and both ask a question whose options
contain her true answer, which Ashgrove's did not.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

import api_handlers.intake_consult as IC  # noqa: E402
from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
  implausible_write_hold_question as _ask,
  mark_implausible_writes_asked as _mark,
)


def _norm(**row):
  base = {"product_name": "Book binding & repair job", "unit_cadence": "contract"}
  base.update(row)
  return IC._normalize_ops_capacity_compat({"lob_models": [{"products": [base]}]})


def _row_of(ops):
  return ops["lob_models"][0]["products"][0]


class AValueOutsideWhatItsFieldCanHoldIsHeld(unittest.TestCase):

  def test_ashgroves_eleven_hundred_is_not_stored_as_turns(self):
    ops = _norm(units_per_period_capacity=10, operating_periods_per_year=1100)
    row = _row_of(ops)
    self.assertIsNone(row.get("operating_periods_per_year"),
                      "1,100 turns of one job in a year was stored as fact")
    self.assertTrue(row.get("_implausible_writes"), "it was dropped, not held")
    self.assertEqual(row["_implausible_writes"][0]["value"], 1100)

  def test_perrin_rows_nine_thirty_as_a_working_year_is_not_stored(self):
    ops = _norm(product_name="Custom framing", units_per_period_capacity=8,
                operating_weeks_per_year=930)
    row = _row_of(ops)
    self.assertIsNone(row.get("operating_weeks_per_year"))
    self.assertTrue(row.get("_implausible_writes"))

  def test_a_month_count_a_year_cannot_hold(self):
    """52 on a monthly row is refused and the cadence default takes over - so
    the stored figure is 12, which is right, and the 52 is still held for the
    question rather than forgotten."""
    ops = _norm(unit_cadence="monthly", units_per_period_capacity=8,
                operating_periods_per_year=52)
    row = _row_of(ops)
    self.assertEqual(row.get("operating_periods_per_year"), 12)
    self.assertTrue(row.get("_implausible_writes"))
    self.assertEqual(row["_implausible_writes"][0]["value"], 52)

  def test_a_plausible_figure_is_left_completely_alone(self):
    """The guard must be invisible on every correct run. 110 turns and a
    48-week year are both ordinary facts."""
    ops = _norm(units_per_period_capacity=10, operating_periods_per_year=110,
                operating_weeks_per_year=48)
    row = _row_of(ops)
    self.assertEqual(row.get("operating_periods_per_year"), 110)
    self.assertEqual(row.get("operating_weeks_per_year"), 48)
    self.assertNotIn("_implausible_writes", row)
    self.assertAlmostEqual(row.get("units_per_week_capacity"), 10 * 110 / 48.0, 4)

  def test_the_figure_is_never_thrown_away(self):
    """A held figure stays where the question can find it. Dropping it is how a
    client's answer becomes silence - which is the defect, not the fix."""
    row = _row_of(_norm(units_per_period_capacity=10, operating_periods_per_year=1100))
    held = row["_implausible_writes"][0]
    self.assertEqual(held["value"], 1100)
    self.assertIn("365", held["reason"])


class AWriteThatContradictsWhatSheSaidIsHeld(unittest.TestCase):
  """CW-076's killing turn. No bound would have caught it."""

  def _ashgrove_before_the_weeks_question(self):
    return _norm(units_per_period_capacity=10, annual_completed_units=1100)

  def test_her_annual_figure_is_kept_and_completes_the_pair(self):
    row = _row_of(self._ashgrove_before_the_weeks_question())
    self.assertEqual(row.get("annual_completed_units"), 1100)
    self.assertAlmostEqual(row.get("operating_periods_per_year"), 110.0, 6)
    self.assertAlmostEqual(
      row["units_per_period_capacity"] * row["operating_periods_per_year"], 1100, 6)

  def test_her_forty_eight_weeks_cannot_silently_become_her_turns(self):
    ops = self._ashgrove_before_the_weeks_question()
    _row_of(ops)["operating_periods_per_year"] = 48      # the killing write
    row = _row_of(IC._normalize_ops_capacity_compat(ops))
    self.assertIsNone(row.get("operating_periods_per_year"),
                      "10 x 48 = 480 a year was stored over her stated 1,100")
    self.assertEqual(row.get("annual_completed_units"), 1100,
                     "her own figure was destroyed and nothing noticed")

  def test_the_question_quotes_her_own_number_back(self):
    ops = self._ashgrove_before_the_weeks_question()
    _row_of(ops)["operating_periods_per_year"] = 48
    q = _ask(IC._normalize_ops_capacity_compat(ops))
    self.assertTrue(q)
    self.assertIn("1,100", q)
    self.assertIn("480", q)
    self.assertIn("how many weeks a year you are open", q,
                  "the option she would actually have picked is missing")

  def test_a_correctly_homed_annual_pair_is_not_called_a_contradiction(self):
    """On a row with a stated CEILING, capacity x turns IS the ceiling and her
    actual sits below it - utilisation is exactly that gap. Comparing capacity x
    turns against her actual called every correct pair a contradiction when this
    guard was first written."""
    ops = _norm(concurrent_capacity_units=6, annual_capacity_units=34,
                annual_completed_units=26)
    row = _row_of(ops)
    self.assertNotIn("_implausible_writes", row)
    self.assertAlmostEqual(
      row["units_per_period_capacity"] * row["operating_periods_per_year"]
      * row["utilization_rate"], 26, 6)

  def test_a_small_correction_is_a_fact_not_a_question(self):
    """She is allowed to revise. Only a figure that moves her stated year by
    more than a rounding margin is worth stopping for."""
    ops = self._ashgrove_before_the_weeks_question()
    _row_of(ops)["operating_periods_per_year"] = 111    # 1,110 vs 1,100
    row = _row_of(IC._normalize_ops_capacity_compat(ops))
    self.assertEqual(row.get("operating_periods_per_year"), 111)
    self.assertNotIn("_implausible_writes", row)


class TheQuestionContainsHerTrueAnswer(unittest.TestCase):
  """ASHGROVE'S DID NOT, AND THAT IS ITS OWN DEFECT (Nick 2026-09-22).

  She was asked "is 1,100 how many working weeks or months a year you run, or
  the most you could finish in a year?" and hers was neither - she had to reply
  "Neither. That's how many I actually finish in a year", a sentence the app
  forced her to compose because its own list left out the only right answer.
  The app had even said the words in the same breath: "I haven't recorded how
  many you usually finish in a year yet."
  """

  def test_the_annual_question_offers_what_she_actually_finishes(self):
    q = _ask(_norm(units_per_period_capacity=10, operating_periods_per_year=1100))
    self.assertIn("how many you actually finish in a year", q)

  def test_there_is_always_a_way_out_of_the_list(self):
    """A readback whose options exclude the true answer turns her confusion
    into her consent."""
    q = _ask(_norm(units_per_period_capacity=10, operating_periods_per_year=1100))
    self.assertIn("something else", q)

  def test_it_says_why_it_is_asking(self):
    q = _ask(_norm(units_per_period_capacity=10, operating_periods_per_year=1100))
    self.assertIn("365", q)
    self.assertIn("1100", q.replace(",", ""))

  def test_it_names_the_line_on_a_business_with_more_than_one(self):
    q = _ask(_norm(product_name="Short-run print job",
                   units_per_period_capacity=10, operating_periods_per_year=1100))
    self.assertIn("Short-run print job", q)

  def test_it_is_let_go_after_two_asks(self):
    """The same discipline as every other hold - nothing loops. Being let go
    means we stop asking, never that we quietly store it."""
    ops = _norm(units_per_period_capacity=10, operating_periods_per_year=1100)
    self.assertTrue(_ask(ops))
    _mark(ops)
    self.assertTrue(_ask(ops))
    _mark(ops)
    self.assertIsNone(_ask(ops))
    self.assertIsNone(_row_of(ops).get("operating_periods_per_year"),
                      "letting the question go quietly stored the figure")

  def test_no_question_when_nothing_is_held(self):
    self.assertIsNone(_ask(_norm(units_per_period_capacity=10,
                                 operating_periods_per_year=110)))


if __name__ == "__main__":
  unittest.main(verbosity=2)
