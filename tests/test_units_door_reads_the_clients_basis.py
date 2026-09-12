"""THE UNITS DOOR - fourth door in its class (Nick 2026-09-12).

Sablecreek message 107: "My other operating expense should go to 633,312 a
year and my monthly rent stays at 22,000." Message 108: "updated your
other operating costs to $633,312 per month just as you specified." The
store went to 7,599,744 a year where the client had asked for a cut from
4,080,000; the client had to do the division themselves.

The basis registry (field_basis.py) already declares each field's unit and
tells the router to convert the client's stated basis to it. This adds the
door's CHECK that the router did: a figure the client called yearly cannot
land in a monthly field unconverted. With no unit in the client's words the
router's value stands - the check reads words, it never guesses. And a
monthly money figure is read back with its yearly total beside it.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo import field_basis as fb  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.capture_receipt import _fmt, numeric_receipt, receipt_summary  # noqa: E402

SABLECREEK_107 = "My other operating expense should go to 633,312 a year and my monthly rent stays at 22,000. Set those two fields and re-run."


class TheClientsWordsCarryTheUnit(unittest.TestCase):
  def test_a_year_is_annual(self):
    self.assertEqual(fb.stated_basis_in_text(SABLECREEK_107, 633312), fb.ANNUAL)
    self.assertEqual(fb.stated_basis_in_text("about $4.08m per year", 4_080_000), fb.ANNUAL)
    self.assertEqual(fb.stated_basis_in_text("165k annually on marketing", 165_000), fb.ANNUAL)

  def test_a_month_is_monthly_and_a_quarter_is_quarterly(self):
    self.assertEqual(fb.stated_basis_in_text("my rent is 22,000 a month on a signed lease", 22000), fb.MONTHLY)
    self.assertEqual(fb.stated_basis_in_text("52,776/month", 52776), fb.MONTHLY)
    self.assertEqual(fb.stated_basis_in_text("we spend 66,000 a quarter on the space", 66000), fb.QUARTERLY)

  def test_no_unit_means_no_opinion(self):
    self.assertIsNone(fb.stated_basis_in_text("set other operating expense to 633,312", 633312))
    self.assertIsNone(fb.stated_basis_in_text("", 1))
    self.assertIsNone(fb.stated_basis_in_text("633,312 a year", 52776), "a different number's unit is not this number's")

  def test_conversion_arithmetic(self):
    self.assertAlmostEqual(fb.convert_between(633312, fb.ANNUAL, fb.MONTHLY), 52776.0)
    self.assertAlmostEqual(fb.convert_between(22000, fb.MONTHLY, fb.ANNUAL), 264000.0)
    self.assertAlmostEqual(fb.convert_between(66000, fb.QUARTERLY, fb.MONTHLY), 22000.0)
    self.assertAlmostEqual(fb.convert_between(5, fb.AMOUNT, fb.MONTHLY), 5.0)


class TheDoorChecksTheRoutersConversion(unittest.TestCase):
  def _door(self, patch, text):
    return S.apply_router_patch(patch=dict(patch), ops_json={}, financials_json={"_coherence": {"status": "walking"}},
                                user_text=text)

  def test_the_sablecreek_turn_lands_in_the_declared_basis(self):
    remaining, _o, _f, notes = self._door({"financials.other_operating_expense": 633312}, SABLECREEK_107)
    self.assertEqual(remaining["financials.other_operating_expense"], 52776.0)
    self.assertIn("basis_converted:other_operating_expense:annual->monthly", notes)

  def test_a_router_that_converted_is_left_alone(self):
    remaining, _o, _f, notes = self._door({"financials.other_operating_expense": 52776}, SABLECREEK_107)
    self.assertEqual(remaining["financials.other_operating_expense"], 52776)
    self.assertFalse(any(n.startswith("basis_converted") for n in notes), notes)

  def test_a_monthly_statement_into_a_monthly_field_is_untouched(self):
    remaining, _o, _f, notes = self._door({"financials.monthly_rent_expense": 22000}, SABLECREEK_107)
    self.assertEqual(remaining["financials.monthly_rent_expense"], 22000)
    self.assertFalse(any(n.startswith("basis_converted") for n in notes), notes)

  def test_a_monthly_statement_into_an_annual_field_is_multiplied(self):
    remaining, _o, _f, notes = self._door({"financials.marketing_total_year1": 13750},
                                          "we spend about 13,750 a month on marketing")
    self.assertEqual(remaining["financials.marketing_total_year1"], 165000.0)
    self.assertIn("basis_converted:marketing_total_year1:monthly->annual", notes)

  def test_no_unit_in_the_words_writes_the_routers_value_as_is(self):
    remaining, _o, _f, notes = self._door({"financials.other_operating_expense": 633312},
                                          "set other operating expense to 633,312")
    self.assertEqual(remaining["financials.other_operating_expense"], 633312)
    self.assertFalse(any(n.startswith("basis_converted") for n in notes), notes)


class TheReceiptReadsBackBothUnits(unittest.TestCase):
  def test_a_monthly_money_figure_carries_its_year(self):
    line = _fmt("financials.other_operating_expense", 52776.0)
    self.assertIn("$52,776 per month", line)
    self.assertIn("($633,312 a year)", line)
    rent = _fmt("financials.monthly_rent_expense", 22000.0)
    self.assertIn("$22,000 per month", rent)
    self.assertIn("($264,000 a year)", rent)

  def test_the_copied_unit_would_have_been_visible_in_the_receipt(self):
    """What Sablecreek would have read had the door not caught it."""
    line = _fmt("financials.other_operating_expense", 633312.0)
    self.assertIn("($7,599,744 a year)", line)

  def test_an_annual_field_stays_annual(self):
    line = _fmt("financials.marketing_total_year1", 165000.0)
    self.assertIn("per year", line)
    self.assertNotIn("a year)", line)

  def test_through_the_real_receipt(self):
    rec = numeric_receipt(before={"financials": {"other_operating_expense": 340000}},
                          after={"financials": {"other_operating_expense": 52776}},
                          requested_fields=["financials.other_operating_expense"])
    text = receipt_summary(rec)
    self.assertIn("$52,776 per month", text)
    self.assertIn("$633,312 a year", text)


if __name__ == "__main__":
  unittest.main()
