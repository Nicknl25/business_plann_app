"""Merrifield 2026-09-25: the author must be able to make the opening
balance sheet balance.

The delivered plan said the business "carries $185,000 of cash, $95,000 of
receivables, $52,000 of inventory and $240,000 of plant against $38,000 of
payables, $310,000 of term debt and a $48,000 capital lease on the van and
compressor, leaving equity of $224,000." No reader can reconcile that:
572 - 396 is 176, not 224.

THE MODEL WAS RIGHT (620,000 = 396,000 + 224,000). The bundle handed the
author the capital lease OBLIGATION but not the RIGHT-OF-USE ASSET that
offsets it, so the only asset figures it had were 48,000 short. A writer
given half a balance sheet writes half a balance sheet.

This pins the property, not the sentence: for any business, the opening
figures the author receives must add up on both sides.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from writing_phase_v2 import bundle as B  # noqa: E402

ASSETS = ("cash", "accounts_receivable", "inventory", "prepaid_expenses",
          "ppe", "right_of_use_asset", "accumulated_depreciation")
LIABILITIES = ("accounts_payable", "short_term_debt", "deferred_revenue",
               "long_term_debt", "capital_lease_obligation")
EQUITY = ("owners_capital", "retained_earnings", "other_equity")

# Real shapes: Merrifield (a lease), one with no lease at all, one that has
# never traded (the residual sits in other_equity), one with short-term debt.
STUBS = [
    dict(cash=185000.0, accounts_receivable=95000.0, inventory=52000.0,
         prepaid_expenses=0.0, ppe=240000.0, right_of_use_asset=48000.0,
         accumulated_depreciation=0.0, total_assets=620000.0,
         accounts_payable=38000.0, short_term_debt=0.0, deferred_revenue=0.0,
         long_term_debt=310000.0, capital_lease_obligation=48000.0,
         total_liabilities=396000.0, owners_capital=120000.0,
         retained_earnings=104000.0, other_equity=0.0,
         total_equity=224000.0, total_liabilities_and_equity=620000.0),
    dict(cash=60000.0, accounts_receivable=0.0, inventory=4000.0,
         prepaid_expenses=0.0, ppe=85000.0, right_of_use_asset=0.0,
         accumulated_depreciation=0.0, total_assets=149000.0,
         accounts_payable=3000.0, short_term_debt=0.0, deferred_revenue=0.0,
         long_term_debt=0.0, capital_lease_obligation=0.0,
         total_liabilities=3000.0, owners_capital=120000.0,
         retained_earnings=26000.0, other_equity=0.0,
         total_equity=146000.0, total_liabilities_and_equity=149000.0),
    dict(cash=210000.0, accounts_receivable=0.0, inventory=280000.0,
         prepaid_expenses=1000.0, ppe=1600000.0, right_of_use_asset=0.0,
         accumulated_depreciation=0.0, total_assets=2091000.0,
         accounts_payable=340000.0, short_term_debt=25000.0,
         deferred_revenue=0.0, long_term_debt=1425000.0,
         capital_lease_obligation=0.0, total_liabilities=1790000.0,
         owners_capital=400000.0, retained_earnings=0.0,
         other_equity=-99000.0, total_equity=301000.0,
         total_liabilities_and_equity=2091000.0),
]


def _model(stub):
  draft = {"finmo_json": {"quarter_rows": [dict(stub, slot_index=0)]}}
  return B.build_model(draft)["opening_balance_sheet"]


class TheAuthorCanBalanceTheOpeningSheet(unittest.TestCase):

  def test_every_line_the_engine_writes_reaches_the_author(self):
    for stub in STUBS:
      got = _model(stub)
      for key in ASSETS + LIABILITIES + EQUITY + (
          "total_assets", "total_liabilities", "total_equity"):
        self.assertIn(key, got, "the author never sees %r" % key)

  def test_the_assets_it_is_given_sum_to_total_assets(self):
    """The Merrifield failure exactly: the asset lines the author had were
    48,000 short of total_assets, so its sentence could not add up."""
    for stub in STUBS:
      got = _model(stub)
      parts = sum(float(got.get(k) or 0.0) for k in ASSETS)
      self.assertAlmostEqual(
          parts, float(got["total_assets"]), places=2,
          msg="asset lines sum to %s but total_assets is %s - the author "
              "cannot write a sentence that reconciles"
              % (parts, got["total_assets"]))

  def test_the_liabilities_and_equity_it_is_given_sum_to_the_same(self):
    for stub in STUBS:
      got = _model(stub)
      liab = sum(float(got.get(k) or 0.0) for k in LIABILITIES)
      eq = sum(float(got.get(k) or 0.0) for k in EQUITY)
      self.assertAlmostEqual(liab, float(got["total_liabilities"]), places=2)
      self.assertAlmostEqual(eq, float(got["total_equity"]), places=2)
      self.assertAlmostEqual(liab + eq, float(got["total_assets"]), places=2)

  def test_a_lease_never_appears_without_its_asset(self):
    """A liability the author can name with no matching asset is what
    produced the unreconcilable sentence."""
    for stub in STUBS:
      got = _model(stub)
      if float(got.get("capital_lease_obligation") or 0.0) > 0:
        self.assertGreater(
            float(got.get("right_of_use_asset") or 0.0), 0.0,
            "the author is given a capital lease with no right-of-use asset")


if __name__ == "__main__":
  unittest.main()
