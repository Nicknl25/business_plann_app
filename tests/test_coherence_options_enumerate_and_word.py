"""COHERENCE OPTIONS, STEP 1 AND 2 AS CAPABILITY (Nick 2026-09-12).

"The engine's job is to PRICE and to REFUSE. Price every candidate
deterministically; reject anything that widens the gap, breaches a bound
or touches a floor. That's it. It is not the engine's job to guarantee a
moderate option exists, or a rent-held one, or that there are four."

So: the engine can price any subset of the available cost moves at any
depth, and any per-line price or volume move, and it refuses what is not
allowed. Nothing here chooses which combinations appear - that is the
agent's job (step 3). Until it lands the round keeps the generator it
already had. Step 2: every priced option carries a plain why with no lever
id, and the panel shows it under the label.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence.evaluator import StructuralBasis, Thresholds  # noqa: E402

LINE_KEY = "␟"


def _sablecreek():
  """5.28M a year, direct costs 22%, payroll 2.54M a year, space 66,000 a
  quarter, other operating costs 77% of revenue (4.08M a year)."""
  basis = StructuralBasis(q1_revenue_quarterly=1_320_000.0, cogs_pct=0.22, payroll_quarterly=635_000.0,
                          rent_quarterly=66_000.0, gna_pct=0.773, marketing_pct=0.031)
  th = Thresholds(gm_floor=0.35, burden_max=0.60, band_low=0.10, ni_floor=0.05, band_high=0.22)
  bounds = {"cost_floors": {"g_and_a_percent_of_revenue_min": 0.12, "cogs_percent_of_revenue_min": 0.21},
            "facility": {"min_quarterly_rent": 40_000.0}, "team": {},
            "existing_lines": [
              {"lob": "Installations", "product": "install", "price_multiplier_max": 1.2, "volume_multiplier_max": 1.3},
              {"lob": "Monitoring", "product": "monitoring", "price_multiplier_max": 1.15, "volume_multiplier_max": 1.5},
            ]}
  split = [
    {"lob": "Installations", "product": "install", "unit_price": 150_000.0, "annual_units": 27, "utilization_rate": 0.8,
     "annual_revenue": 4_050_000.0, "q1_revenue_quarterly": 1_012_500.0},
    {"lob": "Monitoring", "product": "monitoring", "unit_price": 900.0, "annual_units": 381, "utilization_rate": 0.7,
     "annual_revenue": 342_900.0, "q1_revenue_quarterly": 85_725.0},
  ]
  return basis, th, bounds, split


# The Sablecreek quarter is bound by FIXED-COST BURDEN, which direct costs do
# not touch: a materials move closes nothing there and the engine refuses it
# (closes_nothing). Where a pin needs a materials move that closes something,
# it evaluates against an EBITDA-bound wall instead.
NO_BURDEN = Thresholds(gm_floor=0.35, burden_max=2.0, band_low=0.10, ni_floor=0.05, band_high=0.22)


class TheEnginePricesAnyCandidate(unittest.TestCase):
  def test_a_subset_at_a_depth_is_priced_with_the_patch_scaled(self):
    basis, th, bounds, _ = _sablecreek()
    moves = C.available_cost_moves(basis, th, bounds, {"cogs_basis": "ratio", "_coherence": {}})
    full = C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["gna"], depth=1.0)
    half = C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["gna"], depth=0.5)
    self.assertEqual(half["id"], "costs_gna_d50")
    self.assertEqual(full["id"], "costs_gna")
    v_full = [fp["value"] for fp in full["patch"]["fields"] if fp["field"] == "other_operating_expense"][0]
    v_half = [fp["value"] for fp in half["patch"]["fields"] if fp["field"] == "other_operating_expense"][0]
    cur_monthly = 0.773 * 1_320_000 * 4 / 12
    self.assertAlmostEqual(v_half, (cur_monthly + v_full) / 2, delta=1.0)
    self.assertTrue(full["deep_cut"]); self.assertFalse(half["deep_cut"])
    gap = C._gap(basis, th)
    self.assertGreater(half["closes_quarterly"], 0.5 * gap, "a moderate depth exists and closes most of the gap")

  def test_two_levers_at_once_price_as_one_move(self):
    basis, th, bounds, _ = _sablecreek()
    moves = C.available_cost_moves(basis, th, bounds, {"cogs_basis": "ratio", "_coherence": {}})
    o = C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["gna", "cogs"], depth=0.25)
    self.assertEqual(o["id"], "costs_cogs_gna_d25")
    self.assertEqual({fp["field"] for fp in o["patch"]["fields"]}, {"other_operating_expense", "cogs_percent_of_revenue"})

  def test_the_engine_does_not_choose_the_menu(self):
    """No four-slot rule, no guaranteed moderate or rent-held option: the
    legacy round is exactly the three bundles it always was until the
    agent authors the candidates."""
    basis, th, bounds, _ = _sablecreek()
    r = C._costs_round(basis, NO_BURDEN, bounds, {"cogs_basis": "ratio", "_coherence": {}})
    self.assertEqual([o["id"] for o in r["options"]], ["costs_cogs_gna_rent", "costs_cogs", "costs_gna_rent"])
    r = C._costs_round(basis, th, bounds, {"cogs_basis": "ratio", "_coherence": {}})
    self.assertEqual([o["id"] for o in r["options"]], ["costs_cogs_gna_rent", "costs_gna_rent"],
                     "under the burden wall the materials-only bundle closes nothing and is refused, not shown at $0")
    src = open(C.__file__, encoding="utf-8").read()
    self.assertNotIn("_DEPTHS = (0.25, 0.5, 1.0)", src)
    self.assertNotIn("best qualifying that holds the space", src)


class TheEngineRefuses(unittest.TestCase):
  def test_a_floored_lever_is_not_available_and_is_refused(self):
    basis, th, bounds, _ = _sablecreek()
    moves = C.available_cost_moves(basis, th, bounds, {"cogs_basis": "ratio", "_coherence": {"client_floors": {"rent": True}}})
    self.assertNotIn("rent", moves, "not avoided, NOT GENERATED")
    r = C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["rent"], depth=0.5)
    self.assertEqual(r["rejected"], "lever_floored_or_unavailable")
    r2 = C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["gna", "rent"], depth=0.5)
    self.assertEqual(r2["rejected"], "lever_floored_or_unavailable")

  def test_an_unknown_lever_a_bad_depth_and_no_lever_are_refused(self):
    basis, th, bounds, _ = _sablecreek()
    moves = C.available_cost_moves(basis, th, bounds, {"cogs_basis": "ratio", "_coherence": {}})
    self.assertEqual(C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["crew_cut"])["rejected"], "unknown_lever")
    self.assertEqual(C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["gna"], depth=1.3)["rejected"], "depth_out_of_bounds")
    self.assertEqual(C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["gna"], depth=0)["rejected"], "depth_out_of_bounds")
    self.assertEqual(C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=[])["rejected"], "no_lever")

  def test_a_bound_breach_and_an_unknown_line_are_refused_on_the_revenue_side(self):
    basis, th, bounds, split = _sablecreek()
    k = f"Installations{LINE_KEY}install"
    ok = C.price_revenue_candidate(kind="price", basis=basis, thresholds=th, bounds=bounds, split=split, multipliers={k: 1.1})
    self.assertNotIn("rejected", ok, ok)
    self.assertEqual([p["to"] for p in ok["prices"] if p["product"] == "monitoring"], [900.0], "the other line is left alone")
    breach = C.price_revenue_candidate(kind="price", basis=basis, thresholds=th, bounds=bounds, split=split, multipliers={k: 1.5})
    self.assertEqual(breach["rejected"], "breaches_bound")
    self.assertEqual(C.price_revenue_candidate(kind="price", basis=basis, thresholds=th, bounds=bounds, split=split,
                                               multipliers={"nope": 1.1})["rejected"], "unknown_line")
    self.assertEqual(C.price_revenue_candidate(kind="volume", basis=basis, thresholds=th, bounds=bounds, split=split,
                                               multipliers={k: 0.8})["rejected"], "multiplier_below_one")

  def test_volume_respects_the_fill_the_book_ceiling(self):
    basis, th, bounds, split = _sablecreek()
    k = f"Monitoring{LINE_KEY}monitoring"   # utilization 0.7 -> at most 1/0.7 of today
    ok = C.price_revenue_candidate(kind="volume", basis=basis, thresholds=th, bounds=bounds, split=split, multipliers={k: 1.4})
    self.assertNotIn("rejected", ok, ok)
    over = C.price_revenue_candidate(kind="volume", basis=basis, thresholds=th, bounds=bounds, split=split, multipliers={k: 1.45})
    self.assertEqual(over["rejected"], "breaches_bound")


class TheRailStillRecommendsByReason(unittest.TestCase):
  def test_largest_qualifying_closure_wins_and_none_means_none(self):
    basis, th, bounds, _ = _sablecreek()
    moves = C.available_cost_moves(basis, th, bounds, {"cogs_basis": "ratio", "_coherence": {"client_floors": {"rent": True}}})
    opts = [C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=["gna"], depth=d) for d in (0.25, 0.5, 1.0)]
    best = C.recommend_option(opts)
    self.assertEqual(best["id"], "costs_gna_d50", "halfway: the largest closure that is not a deep cut")
    self.assertEqual(sum(1 for o in opts if o["recommended"]), 1)
    self.assertIsNone(C.recommend_option([opts[2]]), "a deep cut alone recommends nothing")


class EveryOptionSaysWhyInPlainWords(unittest.TestCase):
  def test_why_is_present_and_carries_no_lever_id(self):
    basis, _th, bounds, _ = _sablecreek()
    th = NO_BURDEN
    moves = C.available_cost_moves(basis, th, bounds, {"cogs_basis": "ratio", "_coherence": {}})
    for ids, d in ((["gna"], 0.5), (["cogs"], 1.0), (["gna", "rent"], 0.25), (["cogs", "gna", "rent"], 1.0)):
      o = C.price_cost_candidate(basis=basis, thresholds=th, moves=moves, lever_ids=ids, depth=d)
      self.assertTrue(o.get("why"), o["id"])
      for bad in ("gna", "cogs", "owner_draw", "hire_timing", "_d50", "_d25"):
        self.assertNotRegex(o["why"], rf"(?<![a-z]){re.escape(bad)}(?![a-z])", (o["id"], o["why"]))
      self.assertTrue(any(ch.isdigit() for ch in o["why"]), "the why carries the engine's figure")

  def test_the_materials_sentence_reads_like_nicks_example(self):
    basis, _th, bounds, _ = _sablecreek()
    moves = C.available_cost_moves(basis, NO_BURDEN, bounds, {"cogs_basis": "ratio", "_coherence": {}})
    o = C.price_cost_candidate(basis=basis, thresholds=NO_BURDEN, moves=moves, lever_ids=["cogs"], depth=1.0)
    self.assertIn("suppliers would need to come down about", o["why"])

  def test_the_legacy_round_and_the_question_carry_the_why(self):
    basis, th, bounds, _ = _sablecreek()
    r = C._costs_round(basis, th, bounds, {"cogs_basis": "ratio", "_coherence": {}})
    self.assertTrue(all(o.get("why") for o in r["options"]))
    q = S._round_question(r, "$1,150,219")
    self.assertIn("1)", q)

  def test_the_panel_shows_the_why_under_the_label(self):
    src = open(os.path.join(ROOT, "frontend", "src", "intake_form", "steps", "CoherencePanel.tsx"), encoding="utf-8").read()
    self.assertIn("{o.why ? (", src)
    self.assertIn("why?: string;", src)


if __name__ == "__main__":
  unittest.main()
