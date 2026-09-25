"""Nick 2026-09-25 ruling (a): a number the reader read is never dropped
for its digits.

CW-072 Marley Lane, and again on Tollemache & Reyes 2026-09-25: the
client said "About three point eight million" and "Three million eight
hundred thousand". The intent router read both correctly and returned
current_revenue = 3,800,000. The underivable-write guards then scanned
her SENTENCE for those digits, did not find them, and silently reverted
the write - so the app asked the same question again. Only "3,800,000"
survived. Six turns lost to a client speaking normally. Harrowgate's
"four dollars twenty" was lost the same way, in the ops guard.

A guard that re-reads her words is a SECOND reader. Nick's standing rule
(2026-09-13): a client's sentence is interpreted once, by the router.

Each case below is a shape the 12-September guards MEASURABLY dropped -
this file fails on that build and passes on the restore.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from api_handlers import intake_consult as IC  # noqa: E402

ASKED = ("about how much revenue is the business bringing in a year "
         "right now?")

# ordinary spoken magnitudes whose digits do not spell the value
SPOKEN = [
    ("About three point eight million.", 3800000),
    ("Three million eight hundred thousand.", 3800000),
    ("a million and a half", 1500000),
]

OPS_SPOKEN = [
    ("unit_price", 4.2, "four dollars twenty"),
    ("unit_price", 12.75, "twelve seventy five"),
    ("unit_price", 4.2, "about four dollars and twenty cents"),
    ("units_per_week_capacity", 1200, "twelve hundred a week"),
    ("units_per_week_capacity", 250, "two fifty a week flat out"),
]


def _ops(leaf, value):
  return {"lob_models": [{"lob_name": "Exterior", "products": [
      {"product_name": "A-110", leaf: value,
       "operating_periods_per_year": 52}]}]}


class TheRouterReadItSoItIsKept(unittest.TestCase):

  def test_the_stage_guard_keeps_what_the_router_read(self):
    for msg, value in SPOKEN:
      for field in ("current_revenue", "current_cogs", "current_payroll"):
        out = IC._guard_underivable_stage_writes(
            fin_before={field: None}, fin_after={field: value},
            user_message=msg, last_assistant=ASKED)
        self.assertEqual(
            out.get(field), value,
            "%r: the router read %s=%s and the stage guard dropped it"
            % (msg, field, value))

  def test_the_financials_guard_keeps_a_spoken_correction(self):
    """A CORRECTION turn - a prior value exists, which is when this
    guard fires at all."""
    for msg, value in SPOKEN:
      for field in ("current_revenue", "marketing_total_year1"):
        out = IC._guard_underivable_financials_writes(
            fin_before={field: 1000000}, fin_after={field: value},
            user_message=msg)
        self.assertEqual(
            out.get(field), value,
            "%r: the router corrected %s to %s and the financials guard "
            "reverted it" % (msg, field, value))

  def test_a_value_the_reader_placed_in_ops_is_not_popped(self):
    """Harrowgate's price and kin - both a first capture and a
    correction over an existing value."""
    for leaf, value, msg in OPS_SPOKEN:
      prior = 3.0 if leaf == "unit_price" else 100
      for before_v in (None, prior):
        out = IC._guard_underivable_ops_lever_writes(
            ops_before=_ops(leaf, before_v), ops_after=_ops(leaf, value),
            user_message=msg,
            last_assistant="what is the figure for A-110?")
        got = out["lob_models"][0]["products"][0].get(leaf)
        self.assertEqual(
            got, value,
            "%r (before=%s): the router read %s=%s and the ops guard "
            "dropped it" % (msg, before_v, leaf, value))

  def test_the_arithmetic_corrections_above_the_drop_still_run(self):
    """The restore removes the DROP, not the marked-price conversion:
    "$60 a year" on a monthly product is still converted, not kept raw."""
    ops_b = _ops("unit_price", 4.0)
    ops_a = _ops("unit_price", 60.0)
    ops_b["lob_models"][0]["products"][0]["operating_periods_per_year"] = 12
    ops_a["lob_models"][0]["products"][0]["operating_periods_per_year"] = 12
    out = IC._guard_underivable_ops_lever_writes(
        ops_before=ops_b, ops_after=ops_a,
        user_message="sixty dollars a year",
        last_assistant="what do you charge for A-110?")
    got = out["lob_models"][0]["products"][0]["unit_price"]
    self.assertIsNotNone(got)
    self.assertNotEqual(got, 4.0, "the conversion path reverted instead")


if __name__ == "__main__":
  unittest.main()
