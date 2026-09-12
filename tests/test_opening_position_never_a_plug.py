"""Cowork issue 700 (Isolde & Parry, 2026-09-12): a business that has never
traded opened with 140,000 of Retained Earnings used as a balancing plug -
stated assets 3,240,000 against 3,100,000 of founders' capital and no debt.

Two fixes: on a never-traded business the residual is an OPENING ADJUSTMENT
carried in Other Equity (retained earnings open at zero, in the stub and on
the input row the model reads); and the intake points out the mismatch at
the financials boundary, in the client's own figures, and asks which to
revise - once.
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

from client_intake_and_finmo import finmo_bridge as FB  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402


def _model_input(business_start, anchor, owners_capital=3100000.0):
  return {
    "start_date": anchor, "business_start_date": business_start,
    "sections": {
      "balance_sheet": [
        {"label": "Owner's Capital", "values": [owners_capital, 0.0, 0.0]},
        {"label": "Other Equity", "values": [0.0, 0.0, 0.0]},
      ],
      "schedules": {"cash_opening_balance_seed": 700000.0, "inventory_opening_balance_seed": 240000.0,
                    "ppe_opening_balance_seed": 2300000.0},
    },
  }


class TheResidualIsAnOpeningAdjustmentNotRetainedEarnings(unittest.TestCase):
  def test_never_traded_carries_the_residual_in_other_equity(self):
    mi = _model_input("2026-10-01", "2026-09-12")
    m = FB._build_balance_sheet_intake_stub_metrics(mi)
    self.assertAlmostEqual(m["total_assets"], 3240000.0, places=2)
    self.assertEqual(m["retained_earnings"], 0.0, "nothing traded, nothing retained")
    self.assertAlmostEqual(m["other_equity"], 140000.0, places=2)
    self.assertAlmostEqual(m["total_equity"], 3240000.0, places=2)
    row = next(r for r in mi["sections"]["balance_sheet"] if r["label"] == "Other Equity")
    self.assertAlmostEqual(row["values"][0], 140000.0, places=2, msg="the model's opening equity row carries it too")
    self.assertIn("opening adjustment", row["opening_adjustment"]["why"])

  def test_a_trading_business_keeps_its_retained_earnings(self):
    mi = _model_input("2019-03-15", "2026-09-12")
    m = FB._build_balance_sheet_intake_stub_metrics(mi)
    self.assertAlmostEqual(m["retained_earnings"], 140000.0, places=2)
    self.assertEqual(m["other_equity"], 0.0)

  def test_a_never_traded_business_that_balances_gets_no_adjustment(self):
    mi = _model_input("2026-10-01", "2026-09-12", owners_capital=3240000.0)
    m = FB._build_balance_sheet_intake_stub_metrics(mi)
    self.assertEqual(m["retained_earnings"], 0.0)
    self.assertEqual(m["other_equity"], 0.0)
    row = next(r for r in mi["sections"]["balance_sheet"] if r["label"] == "Other Equity")
    self.assertNotIn("opening_adjustment", row)


class TheIntakeAsksWhichFigureToRevise(unittest.TestCase):
  def test_isoldes_position_is_named_in_her_own_figures(self):
    fin = {"cash_on_hand": 700000.0, "inventory_balance": 240000.0, "initial_assets": 2300000.0, "initial_equity": 3100000.0,
           "total_debt_outstanding": 0.0}
    ob = S.opening_balance_mismatch(fin)
    self.assertEqual(ob, {"owned": 3240000.0, "owed": 0.0, "put_in": 3100000.0, "gap": 140000.0})
    self.assertEqual(S.open_hold_questions(fin), [], "a trading business with more owned than put in has retained earnings - nothing to ask")
    holds = S.open_hold_questions(fin, never_traded=True)
    self.assertEqual([k for k, _t in holds], ["opening_balance"])
    q = holds[0][1]
    self.assertIn("$3,240,000", q); self.assertIn("$3,100,000", q); self.assertIn("$140,000", q)
    self.assertIn("Which figure should I revise", q)

  def test_asked_once_never_twice_and_a_balanced_position_is_silent(self):
    fin = {"cash_on_hand": 700000.0, "inventory_balance": 240000.0, "initial_assets": 2300000.0, "initial_equity": 3100000.0}
    holds = S.open_hold_questions(fin, never_traded=True)
    fin2 = S.mark_holds_asked(fin, holds)
    self.assertIn(S.OPENING_BALANCE_ASKED_KEY, fin2)
    self.assertEqual(S.open_hold_questions(fin2, never_traded=True), [], "asked once; an unchanged answer stands")
    balanced = {"cash_on_hand": 700000.0, "inventory_balance": 240000.0, "initial_assets": 2300000.0, "initial_equity": 3240000.0}
    self.assertIsNone(S.opening_balance_mismatch(balanced))
    debt_covers = {"initial_assets": 3240000.0, "initial_equity": 3100000.0, "total_debt_outstanding": 140000.0}
    self.assertIsNone(S.opening_balance_mismatch(debt_covers))
    never_stated = {"initial_assets": 3240000.0}
    self.assertIsNone(S.opening_balance_mismatch(never_stated), "no equity figure, nothing to compare")


if __name__ == "__main__":
  unittest.main()


class OnlyANeverTradedBusinessIsAsked(unittest.TestCase):
  def test_the_handler_reads_the_start_date_against_the_clients_today(self):
    from api_handlers import intake_consult as H
    self.assertTrue(H._business_never_traded({"start_date": "2026-10-01"}, {"current_date": "2026-09-12"}))
    self.assertTrue(H._business_never_traded({"start_date": "10/01/2026"}, {"current_date": "2026-09-12"}))
    self.assertFalse(H._business_never_traded({"start_date": "2019-03-15"}, {"current_date": "2026-09-12"}))
    self.assertFalse(H._business_never_traded({}, {"current_date": "2026-09-12"}))
