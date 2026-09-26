"""TWO PRICES FOR ONE ROW IS A QUESTION, NOT A BLEND (Nick 2026-09-26).

The line-split gate lets the consultant decide SILENTLY how many lines a
business has. On 3 of 4 runs with identical client answers it folded three
described lines into two. She then stated two real prices - "$2,400 a tonne"
and "$850 a unit" - and NEITHER COULD LAND, because one row cannot hold two
prices. The app noticed and asked her to average them:

    "I wasn't able to apply that change yet. The 2,400 - is that your
     price? The eight hundred fifty dollars a unit - is that your price?"
    ... "To keep the planning clean, can we pin a single average"

She obliged with $1,750, both stated prices left the model, and every later
correction failed with "I couldn't tell which line you meant" - 24 times -
because by then there was no line to mean.

THE TRIGGER IS ARITHMETIC: one product row, two different stated prices.
Nothing reads her meaning. The answer is hers either way, which is the case
the gate was built for - five variations at ONE price never trips this.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from api_handlers import intake_consult as IC  # noqa: E402


def _fig(value, field="ops.unit_price", words=""):
  return {"value": value, "candidate_fields": [field],
          "client_words": words or str(value)}


def _ops(*product_names):
  return {"lob_models": [{"lob_name": "A line",
                          "products": [{"product_name": n}
                                       for n in product_names]}]}


ONE_ROW = _ops("Fabrication jobs")
TWO_ROWS = _ops("Fabrication jobs", "Repair callouts")


class TwoPricesForOneRowIsAQuestion(unittest.TestCase):

  def test_her_two_prices_against_one_row_ask_about_splitting(self):
    q = IC._two_prices_one_row_question([_fig(2400), _fig(850)], ONE_ROW)
    self.assertTrue(q, "two prices for one row produced no question")
    self.assertIn("2,400", q)
    self.assertIn("850", q)
    self.assertIn("own lines", q.replace("their own lines", "own lines"))

  def test_it_never_proposes_averaging(self):
    """The defect was the app asking her to pin a single average."""
    q = IC._two_prices_one_row_question([_fig(2400), _fig(850)], ONE_ROW)
    low = q.lower()
    for banned in ("average", "typical price", "blend", "single price"):
      self.assertNotIn(banned, low, "the question still steers her to a blend")

  def test_one_price_is_not_a_question(self):
    self.assertEqual(
        "", IC._two_prices_one_row_question([_fig(2400)], ONE_ROW))

  def test_the_same_price_twice_is_not_two_prices(self):
    """Five variations at ONE price is the case the split gate exists for -
    it must never trip this."""
    self.assertEqual(
        "", IC._two_prices_one_row_question(
            [_fig(2400), _fig(2400), _fig(2400.0)], ONE_ROW))

  def test_two_prices_against_two_rows_is_not_this_problem(self):
    """With a row each, the ordinary which-line machinery applies."""
    self.assertEqual(
        "", IC._two_prices_one_row_question([_fig(2400), _fig(850)], TWO_ROWS))

  def test_figures_that_are_not_prices_are_ignored(self):
    figs = [_fig(40, "ops.units_per_week_capacity"),
            _fig(0.7, "ops.utilization_rate")]
    self.assertEqual("", IC._two_prices_one_row_question(figs, ONE_ROW))

  def test_it_takes_precedence_over_the_double_price_ask(self):
    """The old reply asked 'is that your price?' twice, which she cannot
    usefully answer when both are true."""
    figs = [_fig(2400), _fig(850)]
    old = IC._unresolved_figures_ask(figs)
    self.assertEqual(2, old.lower().count("is that your price"),
                     "the old ask no longer has the shape this replaces")
    new = IC._two_prices_one_row_question(figs, ONE_ROW)
    self.assertNotIn("is that your price", new.lower())

  def test_it_holds_for_any_business(self):
    for a, b in ((95.0, 60.0), (85.0, 40.0), (21000.0, 2400.0), (12.5, 4.0)):
      q = IC._two_prices_one_row_question([_fig(a), _fig(b)], ONE_ROW)
      self.assertTrue(q, "%s and %s produced no question" % (a, b))

  def test_a_missing_or_zero_price_is_not_a_second_price(self):
    for bad in (0, None, -5):
      self.assertEqual(
          "", IC._two_prices_one_row_question([_fig(2400), _fig(bad)],
                                              ONE_ROW))


if __name__ == "__main__":
  unittest.main()
