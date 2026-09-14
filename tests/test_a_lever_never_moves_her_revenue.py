"""A lever moves the plan's revenue, never the revenue she stated.

Nick ruled 2026-09-14: current_revenue may not hold a figure the app worked out.
The coherence walk's levers wrote their result into it - on the store, Dunmore &
Tate 4,600,000 -> 3,450,000, Third Coast 630,000 -> 315,000, Green Meadow 700,000 ->
44,100. They now move a private plan anchor, read only where the intake would
otherwise undo the move she agreed.

These pins state, for any stated revenue and any sequence of moves:
  - no stated revenue above zero -> no anchor, and the plan's revenue is None (the
    drivers carry the plan - Cowork 1103's pre-revenue hazard);
  - a move never touches current_revenue; the plan's revenue is the last move;
  - an anchor built on a figure she has since changed is ignored;
  - her retention answer moves the anchor, not her figure, and the anchor survives
    the state write that clears the frame;
  - no walk code assigns current_revenue or records a current_revenue lever write;
  - the rescale targets the plan's revenue;
  - door B never explains the anchor, and a reply stating it is recorded as an
    anchor leak - while her own figure in a reply is no leak.
"""
from __future__ import annotations

import copy
import itertools
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))


class ThePlanAnchorIsNotHerRevenue(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo import revenue_anchor as RA  # type: ignore
    self.RA = RA

  def test_moves_never_touch_her_figure_and_need_a_stated_revenue(self):
    for stated, moves in itertools.product((None, 0.0, -5.0, 175_000.0, 4_600_000.0),
                                           ([], [0.5], [1.1, 0.9], [0.063, 2.0, 1.0])):
      fin = {} if stated is None else {"current_revenue": stated}
      before = copy.deepcopy(fin)
      for k, ratio in enumerate(moves):
        base = self.RA.plan_revenue(fin) or 0.0
        fin = self.RA.move_plan_revenue(fin, base * ratio if base else 100.0 * ratio, lever="lever%d" % k)
      self.assertEqual(fin.get("current_revenue"), before.get("current_revenue"), (stated, moves))
      if stated is None or stated <= 0:
        self.assertIsNone(self.RA.plan_revenue(fin), (stated, moves))
        self.assertNotIn("plan_revenue_anchor", fin.get("_coherence") or {}, "an anchor without her revenue")
      else:
        want = stated
        for ratio in moves:
          want = round(want * ratio, 2)
        self.assertAlmostEqual(self.RA.plan_revenue(fin), want, delta=0.02 * len(moves) + 0.01)
        rec = (fin.get("_coherence") or {}).get("plan_revenue_anchor")
        self.assertEqual(len((rec or {}).get("moves") or []), len(moves))

  def test_a_stale_anchor_is_ignored(self):
    fin = self.RA.move_plan_revenue({"current_revenue": 700_000.0}, 44_100.0, lever="price")
    self.assertEqual(self.RA.plan_revenue(fin), 44_100.0)
    fin["current_revenue"] = 63_000.0                      # she restates her revenue
    self.assertEqual(self.RA.plan_revenue(fin), 63_000.0)
    self.assertIsNone(self.RA.anchor_record(fin))


class TheRetentionAnswerMovesThePlanNotHer(unittest.TestCase):
  def test_any_fraction_moves_the_anchor_and_leaves_her_figure(self):
    from client_intake_and_finmo.intake_coherence import section as sec  # type: ignore
    from client_intake_and_finmo import revenue_anchor as RA  # type: ignore
    ops = {"lob_models": [{"lob_name": "Service", "products": [
      {"product_name": "Job", "unit_price": 150.0, "units_per_period_capacity": 60.0, "utilization_rate": 0.8,
       "operating_periods_per_year": 12.0}]}]}
    for stated, used, frac in itertools.product((96_000.0, 421_200.0), (1.0, 0.9), (0.9, 0.5, 1.0)):
      fin = {"current_revenue": stated}
      st = dict(sec.get_state(fin))
      st["retention_pending"] = {"prices": [{"product": "Job", "to": 189.0}], "retained_used": used}
      fin = sec.put_state(fin, st)
      fin2, _ops2, applied = sec.apply_retention_answer(fin, copy.deepcopy(ops), frac)
      self.assertTrue(applied)
      self.assertEqual(fin2.get("current_revenue"), stated, "her revenue moved")
      self.assertIsNone(sec.get_state(fin2).get("retention_pending"))
      if abs(frac - used) > 1e-6:
        self.assertAlmostEqual(RA.plan_revenue(fin2), round(stated * frac / used, 2), delta=0.01, msg=(stated, used, frac))
      self.assertNotIn("current_revenue", sec.get_state(fin2).get("_lever_writes") or {})


class NoWalkCodeWritesHerRevenue(unittest.TestCase):
  def test_the_walk_never_assigns_or_records_current_revenue(self):
    for rel in ("python/client_intake_and_finmo/intake_coherence/section.py",
                "python/client_intake_and_finmo/intake_coherence/controller.py"):
      src = (ROOT / rel).read_text(encoding="utf-8-sig")
      self.assertFalse(re.search(r'\[\s*"current_revenue"\s*\]\s*=(?!=)', src), "%s assigns current_revenue" % rel)
      self.assertFalse(re.search(r'_record_lever_write\([^)]*"current_revenue"', src, re.S), rel)
      self.assertNotIn('"current_revenue": round(moved', src, rel)

  def test_the_rescale_targets_the_plan_revenue(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8-sig")
    body = src[src.index("def _rescale_financials_year1_to_current_revenue"):]
    body = body[:body.index("\ndef ")]
    self.assertIn("target_total = _plan_revenue(financials_json)", body)


class AUsedAnswerIsNeverToldItWasLeftAside(unittest.TestCase):
  def test_a_consumed_retention_answer_never_gets_the_left_aside_line(self):
    """Green Meadow clone, 2026-09-14: her retention answer moved the plan anchor,
    no stated field changed so no receipt existed, and the ship gate told her
    "That figure didn't fit the question I asked, so I've left it aside"."""
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8-sig")
    resolver = src[src.index("_coh_ret.apply_retention_answer("):]
    resolver = resolver[:resolver.index("RETENTION_RESOLVE_PERSIST_FAILED")]
    self.assertIn("_retention_consumed_this_turn = True", resolver)
    used_at = src.index("if _prose_claims_figure and not _figure_is_redirects_own and not _door_ack and _retention_used:")
    aside_at = src.index("That figure didn't fit the question I asked, so I've left it aside for now.")
    self.assertLess(used_at, aside_at, "the used-answer branch must be decided before the left-aside line")
    between = src[used_at:aside_at]
    self.assertIn("elif _prose_claims_figure and not _figure_is_redirects_own and not _door_ack:", between)


class ARetiredLeverWriteIsHistoryNotAMove(unittest.TestCase):
  def test_every_reader_ignores_a_current_revenue_lever_write(self):
    """Cowork 1113: three real drafts still carry current_revenue {700000 -> 44100}
    beside a current_revenue of 63,000, and nothing marked it stale."""
    from client_intake_and_finmo.intake_coherence import section as sec  # type: ignore
    stale = {"current_revenue": {"from": 700000.0, "to": 44100.0},
             "marketing_total_year1": {"from": 12000.0, "to": 6000.0}}
    state = {"_lever_writes": stale}
    self.assertEqual(sec.live_lever_writes(state), {"marketing_total_year1": {"from": 12000.0, "to": 6000.0}})
    self.assertEqual(sec.live_lever_writes({}), {})
    sentence = sec.cumulative_effect_sentence(state)
    self.assertNotIn("44,100", sentence)
    self.assertNotIn("700,000", sentence)
    only_stale = sec.cumulative_effect_sentence({"_lever_writes": {"current_revenue": stale["current_revenue"]}})
    self.assertNotIn("44,100", only_stale)
    src = (ROOT / "python" / "client_intake_and_finmo" / "intake_coherence" / "section.py").read_text(encoding="utf-8-sig")
    self.assertNotIn('state.get("_lever_writes") or {}).items()', src, "a reader walks the raw record")
    draft = (ROOT / "python" / "client_intake_and_finmo" / "intake_consult_draft.py").read_text(encoding="utf-8-sig")
    self.assertIn('if k != "current_revenue"} or None', draft)


class DoorBCatchesTheAnchor(unittest.TestCase):
  def test_the_anchor_is_never_explained_and_a_reply_stating_it_is_a_leak(self):
    from client_intake_and_finmo import revenue_anchor as RA  # type: ignore
    from client_intake_and_finmo.intake_guard import door_b as B  # type: ignore
    for stated, anchor in ((700_000.0, 44_100.0), (4_600_000.0, 3_450_000.0), (630_000.0, 315_000.0)):
      fin = RA.move_plan_revenue({"current_revenue": stated}, anchor, lever="price")
      store = {"financials": fin, "ops": {}, "people": {}}
      vals = B.explained_figures(store, None, "", reply_text="", recent_user_texts=[])
      self.assertFalse(any(abs(v - anchor) < 0.5 for v in vals), "the anchor %s was explained" % anchor)
      leak = "Your annual revenue is $%s." % format(int(anchor), ",")
      self.assertEqual(B.anchor_leaks(leak, store), [anchor])
      hers = "You told me the business brings in $%s a year." % format(int(stated), ",")
      self.assertEqual(B.anchor_leaks(hers, store), [], "her own figure is no leak")
    self.assertEqual(B.anchor_leaks("Revenue is $44,100.", {"financials": {"current_revenue": 44_100.0}}), [])


if __name__ == "__main__":
  unittest.main(verbosity=2)
