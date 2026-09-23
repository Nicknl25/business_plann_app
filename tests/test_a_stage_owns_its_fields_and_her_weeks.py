"""CW-075 PERRIN ROW FRAMING, killed 2026-09-18 - three defects the live run found
ABOVE the fold, each pinned on the shape that produced it.

The put-back (0d54713f) restored the concurrent fold and the bare-field stage
separation, and both held on this run: her 8 and 60 landed in the slot that means
"at once" with no alias beside them. Everything below is what the run then broke.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

import api_handlers.intake_consult as IC  # noqa: E402
from client_intake_and_finmo.intake_consultant import ASKABLE_OPS_FIELDS  # noqa: E402
from client_intake_and_finmo.intent_router import (  # noqa: E402
  _value_schema_by_consult_field as _schema,
)


def _row(**kw):
  row = {"product_name": "Custom framing", "unit_cadence": "contract"}
  row.update(kw)
  out = IC._normalize_ops_capacity_compat({"lob_models": [{"products": [row]}]})
  return out["lob_models"][0]["products"][0]


class TheOpsStageCanRecordTheQuestionsItAsks(unittest.TestCase):
  """An annual completion count belongs to FINANCIALS when it stands alone and to
  OPS when it completes a concurrent pair - turns = completions / concurrent.

  Removed from ops, its QUESTION did not go with it: the consultant still asked
  "how many do you complete in a year", found no field it could declare, and
  declared operating_periods_per_year. 930 landed in the slot that means TURNS and
  the row claimed 8 x 930 = 7,440 jobs a year against her 930. Both Perrin Row
  lines went that way. A stage that asks a question it cannot record mislabels it.
  """

  def test_the_annual_count_is_declarable_and_writable_at_ops(self):
    self.assertIn("annual_completed_units", ASKABLE_OPS_FIELDS)
    self.assertIn("annual_completed_units", _schema(consult_type="ops"))

  def test_the_actuals_stay_with_financials(self):
    ops = _schema(consult_type="ops")
    fin = _schema(consult_type="financials_year1")
    for f in ("avg_units_per_week_year1", "avg_units_per_period_year1", "utilization_rate"):
      self.assertNotIn(f, ops, "%s is the financials stage's question" % f)
      self.assertIn(f, fin)
      self.assertNotIn(f, ASKABLE_OPS_FIELDS)

  # UPDATED 2026-09-22 AND THE CHANGE IS DELIBERATE, SO IT IS WRITTEN DOWN.
  # These three used to assert that her annual count left the periods slot
  # EMPTY - correct then, because the only alternative on offer was 930 sitting
  # raw in the turns slot, which is what killed Perrin Row. It is no longer the
  # best available answer. Her annual count now completes the pair the way the
  # ceiling already did: turns = what she finishes / what she holds at once,
  # with her own figure kept beside it in annual_completed_units. So the
  # assertion moves from "nothing is stored" to "the RIGHT thing is stored and
  # her figure comes back out" - which is the stronger claim, not a weaker one.
  # What must never happen, and is still pinned, is the raw 930 landing in the
  # turns slot or a weekly figure being invented from it.

  def test_her_annual_count_completes_the_pair_instead_of_filling_the_turns_slot(self):
    """Perrin Row: 8 at once, 930 a year. The periods slot means TURNS, so it
    holds 930/8 = 116.25 - never the 930 itself."""
    r = _row(concurrent_capacity_units=8, annual_completed_units=930)
    self.assertEqual(r.get("units_per_period_capacity"), 8)
    self.assertNotEqual(r.get("operating_periods_per_year"), 930,
                        "her annual job count is sitting in the turns slot")
    self.assertAlmostEqual(r.get("operating_periods_per_year"), 930 / 8.0, 6)

  def test_her_own_figure_survives_on_the_row(self):
    """The half Ashgrove was missing. A number that exists only as someone
    else's arithmetic cannot be checked, and cannot be noticed being destroyed."""
    r = _row(concurrent_capacity_units=8, annual_completed_units=930)
    self.assertEqual(r.get("annual_completed_units"), 930)
    self.assertAlmostEqual(
      r["units_per_period_capacity"] * r["operating_periods_per_year"], 930, 6,
      "her 930 does not come back out of the row")

  def test_no_weekly_capacity_is_invented_from_the_raw_count(self):
    """8 x 930 / 52 = 143.0769 framing jobs a week, four decimals on a physical
    thing. The weekly figure now derives from the TURNS, not from her annual
    count, so it is 8 x 116.25 / 52 = 17.88 - a shop that frames about eighteen
    a week, which is what she actually said."""
    r = _row(concurrent_capacity_units=8, annual_completed_units=930)
    self.assertNotEqual(r.get("units_per_week_capacity"), 143.0769)
    self.assertAlmostEqual(r.get("units_per_week_capacity"), 8 * (930 / 8.0) / 52.0, 4)

  def test_the_second_line_shape_too(self):
    """60 on the wall, 1500 a year -> 25 turns, and 60 x 25 = her 1,500."""
    r = _row(product_name="Ready-made", concurrent_capacity_units=60,
             annual_completed_units=1500)
    self.assertEqual(r.get("units_per_period_capacity"), 60)
    self.assertAlmostEqual(r.get("operating_periods_per_year"), 25.0, 6)
    self.assertNotEqual(r.get("units_per_week_capacity"), 1730.7692)
    self.assertAlmostEqual(
      r["units_per_period_capacity"] * r["operating_periods_per_year"], 1500, 6)


class APerLineWriteObeysTheStageThatMadeIt(unittest.TestCase):
  """THE SEPARATION MUST HOLD AT THE DOOR, NOT ONLY IN THE SCHEMA.

  product_overrides is declared as a free-form object, so removing a field from
  the ops schema closed only the bare form. Per-line the key was unconstrained
  and the door own list still took it: on Harlow's real row a
  {"Bike repairs": {"avg_units_per_week_year1": 4}} still took her 25 to 4 on a
  build where that field had been "removed" from ops.
  """

  OPS = {"lob_models": [{"lob_name": "Bike shop", "products": [
    {"product_name": "Bike repairs", "unit_cadence": "contract",
     "units_per_period_capacity": 6, "avg_units_per_week_year1": 25, "unit_price": 80}]}]}
  PATCH = {"ops.product_overrides": {"Bike repairs": {"avg_units_per_week_year1": 4}}}

  def _apply(self, stage):
    return IC._apply_scoped_patch(
      self.PATCH, business_facts={}, ops_json=copy.deepcopy(self.OPS), market_json={},
      people_json={}, financials_json={}, fulfillment_json={},
      user_message="About four.", consult_stage=stage)[1]["lob_models"][0]["products"][0]

  def test_the_ops_stage_cannot_overwrite_her_weekly_volume(self):
    """Harlow's killing turn: a CONCURRENT answer aimed at the actuals field."""
    self.assertEqual(self._apply("ops").get("avg_units_per_week_year1"), 25,
                     "her 25 a week was overwritten by an answer to a different question")

  def test_the_stage_that_owns_the_field_still_writes_it(self):
    """The financials stage writes the actuals on the same rows through the same
    door - the gate is on the STAGE, never on the field alone."""
    self.assertEqual(self._apply("financials_year1").get("avg_units_per_week_year1"), 4)

  def test_an_unknown_stage_is_not_silently_gated(self):
    """No stage declared = the door behaves as it always did, so nothing else moves."""
    self.assertEqual(self._apply("").get("avg_units_per_week_year1"), 4)

  def test_the_ops_stage_still_writes_its_own_fields(self):
    patch = {"ops.product_overrides": {"Bike repairs": {"unit_price": 95}}}
    out = IC._apply_scoped_patch(
      patch, business_facts={}, ops_json=copy.deepcopy(self.OPS), market_json={},
      people_json={}, financials_json={}, fulfillment_json={},
      user_message="Ninety-five.", consult_stage="ops")[1]
    self.assertEqual(out["lob_models"][0]["products"][0].get("unit_price"), 95)


class TheConversionUsesTheYearSheStated(unittest.TestCase):
  """A literal 52.0 divided every conversion, and operating_weeks_per_year was read
  only on a WEEKLY row - which returns before the conversion. She said about fifty
  weeks, the app said it would use fifty, and the arithmetic used 52 anyway."""

  def test_her_stated_weeks_are_the_divisor(self):
    r = _row(units_per_period_capacity=8, operating_periods_per_year=116.25,
             operating_weeks_per_year=50)
    self.assertAlmostEqual(r.get("units_per_week_capacity"), 18.6, 4)

  def test_it_lands_on_the_figure_she_actually_gave(self):
    """Perrin Row said eighteen finished a week. 8 x (930/8) / 50 = 18.6."""
    r = _row(units_per_period_capacity=8, operating_periods_per_year=930 / 8,
             operating_weeks_per_year=50)
    self.assertAlmostEqual(r.get("units_per_week_capacity"), 18.6, 4)

  def test_fifty_two_is_the_fallback_when_she_has_not_said(self):
    r = _row(units_per_period_capacity=8, operating_periods_per_year=116.25)
    self.assertAlmostEqual(r.get("units_per_week_capacity"), 8 * 116.25 / 52.0, 4)

  def test_a_nonsense_year_falls_back_rather_than_dividing_by_it(self):
    for weeks in (0, -3, 400):
      with self.subTest(weeks=weeks):
        r = _row(units_per_period_capacity=8, operating_periods_per_year=116.25,
                 operating_weeks_per_year=weeks)
        self.assertAlmostEqual(r.get("units_per_week_capacity"), 8 * 116.25 / 52.0, 4)

  def test_the_inverse_conversion_uses_it_too(self):
    r = _row(units_per_week_capacity=18.6, operating_periods_per_year=116.25,
             operating_weeks_per_year=50)
    self.assertAlmostEqual(r.get("units_per_period_capacity"), 18.6 * 50 / 116.25, 4)


class AYearStatedLateStillCounts(unittest.TestCase):
  """Cowork condition 3c, which nobody had ever tested. On CW-075 the order was
  exactly this: the app divided by 52 in the same reply-cycle in which it told her
  it would use fifty. A weekly figure WE derived from the fallback is ours to
  recompute when she states her year; a figure SHE stated is never touched."""

  def _two_turns(self, stated_week=None):
    row = {"product_name": "x", "unit_cadence": "contract",
           "units_per_period_capacity": 8, "operating_periods_per_year": 116.25}
    if stated_week is not None:
      row["units_per_week_capacity"] = stated_week
    ops = IC._normalize_ops_capacity_compat({"lob_models": [{"products": [row]}]})
    first = ops["lob_models"][0]["products"][0].get("units_per_week_capacity")
    ops["lob_models"][0]["products"][0]["operating_weeks_per_year"] = 50
    second = IC._normalize_ops_capacity_compat(ops)["lob_models"][0]["products"][0]
    return first, second.get("units_per_week_capacity")

  def test_a_derived_week_is_recomputed_when_she_states_her_year(self):
    first, second = self._two_turns()
    self.assertAlmostEqual(first, 8 * 116.25 / 52.0, 4, "turn one uses the fallback")
    self.assertAlmostEqual(second, 18.6, 4, "her fifty weeks did not reach the derived figure")

  def test_a_figure_she_stated_is_never_recomputed(self):
    first, second = self._two_turns(stated_week=17.0)
    self.assertEqual(first, 17.0)
    self.assertEqual(second, 17.0, "we recomputed a number the client gave us")


class ADeclarationTheStageCannotAcceptIsAlreadyRefused(unittest.TestCase):
  """Cowork condition Y - already true, and it would NOT have caught CW-075.

  _app_asked_field returns "" when the declared field is not in the stage's
  allowed list, so an unacceptable declaration cannot lead the router. But all
  three of CW-075's mislabels named fields the ops stage CAN accept
  (operating_periods_per_year, units_per_week_capacity) - they were wrong for the
  QUESTION, not unacceptable to the stage. Only checking the declaration against
  the question it labels would have caught them, and that is the free-authorship
  defect, which remains open and untouched.
  """

  ALLOWED = ["ops.units_per_period_capacity", "ops.operating_periods_per_year",
             "ops.units_per_week_capacity", "ops.unit_price"]

  def _declared(self, field):
    from client_intake_and_finmo.intent_router import _app_asked_field
    return _app_asked_field([{"role": "assistant", "content": "q", "asked_field": field}],
                            self.ALLOWED)

  def test_a_field_the_stage_cannot_accept_never_leads(self):
    for f in ("avg_units_per_week_year1", "avg_units_per_period_year1", "utilization_rate"):
      with self.subTest(field=f):
        self.assertEqual(self._declared(f), "")

  def test_the_cw075_mislabels_were_all_acceptable_fields(self):
    """Which is why condition Y would not have blocked this run."""
    for f in ("operating_periods_per_year", "units_per_week_capacity"):
      with self.subTest(field=f):
        self.assertEqual(self._declared(f), "ops." + f)


if __name__ == "__main__":
  unittest.main()
