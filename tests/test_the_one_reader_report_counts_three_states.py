"""The one-reader report puts every client turn in exactly one state, and
missing is never agreement.

Nick asked for the real reader count once the shadow data is in; Cowork (1055)
set the measure: agreed / disagreed / shadow missing or errored, with turns the
router never read counted apart - because the long multi-claim sentences most
likely to break a new reader would otherwise vanish into "agreed".

For generated turns of every shape these pins state:
  - each turn lands in one state, and the state is right;
  - a missing or errored shadow is shadow_missing, never agreed, and names why;
  - a turn with no router reading of her message is router_less, even when the
    proposal extractor read the app's own reply;
  - disagreement names which figures only one side had;
  - every other reader's extra and missed figures are measured against the one
    reading, and only reads of HER message count;
  - the distinct reader count is the number of readers that read her words;
  - the report reads records only - and the endpoint exists.
"""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

D = "a" * 32


def router(turn, patch, client=True, status="ok", unresolved=None):
  return {"draft_id": D, "turn": turn, "is_client_message": client, "status": status, "patch": patch,
          "unresolved_figures": unresolved or []}


def shadow(turn, values, status="ok", error=None):
  claims = [{"value_number": v, "value_low": None, "value_high": None} if not isinstance(v, tuple)
            else {"value_number": None, "value_low": v[0], "value_high": v[1]} for v in values]
  return {"draft_id": D, "turn": turn, "status": status, "error": error,
          "interpretation": {"claims": claims, "unresolved": []} if status == "ok" else None}


def reader(turn, name, result, client=True):
  return {"draft_id": D, "turn": turn, "reader": name, "call_site": "x.py:1 f", "is_client_text": client,
          "result": result, "error": None}


class EveryTurnLandsInOneState(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo import one_reader_report as R  # type: ignore
    self.R = R

  def test_generated_turns_land_in_the_right_state(self):
    cases = 0
    for r_vals, s_vals, s_status in itertools.product(
        ((), (480,), (480, 340), (6, 34, 26)), ((), (480,), (480, 340), (480, 341), (5, 6)), ("ok", "error", "absent")):
      patch = {"ops.product_overrides": {"Row": {"f%d" % i: v for i, v in enumerate(r_vals)}}} if r_vals else {}
      rows_s = [] if s_status == "absent" else [shadow(1, s_vals, status=s_status, error="HTTP 500" if s_status == "error" else None)]
      out = self.R.build([router(1, patch)], rows_s, [])
      turn = out["turns"][0]
      self.assertEqual(out["client_turns"], 1)
      self.assertEqual(sum(out["states"].values()), 1)
      if s_status != "ok":
        self.assertEqual(turn["state"], "shadow_missing", (r_vals, s_vals, s_status))
        self.assertTrue(turn["shadow_error"])
      elif sorted(set(r_vals)) == sorted(set(s_vals)):
        self.assertEqual(turn["state"], "agreed_on_nothing" if not r_vals else "agreed", (r_vals, s_vals))
      else:
        self.assertEqual(turn["state"], "disagreed", (r_vals, s_vals))
        self.assertEqual(sorted(turn["router_only"]), sorted(set(r_vals) - set(s_vals)))
        self.assertEqual(sorted(turn["shadow_only"]), sorted(set(s_vals) - set(r_vals)))
      cases += 1
    self.assertEqual(cases, 60)

  def test_missing_is_never_agreement(self):
    for rows_s in ([], [shadow(3, (), status="error", error="GptLockMiss: strict replay")]):
      out = self.R.build([router(3, {})], rows_s, [])
      self.assertNotIn("agreed", out["states"])
      self.assertNotIn("agreed_on_nothing", out["states"])
      self.assertEqual(out["states"], {"shadow_missing": 1})

  def test_a_turn_the_router_never_read_is_router_less(self):
    # the only router row read the app's own reply (the proposal extractor)
    out = self.R.build([router(4, {"ops.unit_price": 95}, client=False)], [shadow(4, (95,))],
                       [reader(4, "door_a_numbers_in_words", [95.0])])
    self.assertEqual(out["states"], {"router_less": 1})
    self.assertEqual(out["turns"][0]["shadow_figures"], [95.0])

  def test_unresolved_figures_count_as_the_router_reading(self):
    out = self.R.build([router(5, {}, unresolved=[{"value": 340, "client_words": "about 340"}])], [shadow(5, (340,))], [])
    self.assertEqual(out["states"], {"agreed": 1})

  def test_a_range_is_compared_by_its_ends(self):
    out = self.R.build([router(6, {"a": 5, "b": 6})], [shadow(6, ((5, 6),))], [])
    self.assertEqual(out["states"], {"agreed": 1})


class EveryOtherReaderIsMeasuredAgainstTheOneReading(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo import one_reader_report as R  # type: ignore
    self.R = R

  def test_extra_and_missed_for_any_reader_result(self):
    s_vals = (480, 340)
    for result, extra, missed in (
        ([480.0, 4.0, 100.0, 80.0, 3.0, 40.0, 340.0], [3.0, 4.0, 40.0, 80.0, 100.0], []),
        ([480.0], [], [340.0]),
        ({"ops.x": 480, "ops.y": 340}, [], []),
        ([[480.0, 340.0], []], [], []),
    ):
      out = self.R.build([router(11, {"a": 480, "b": 340})], [shadow(11, s_vals)], [reader(11, "r", result)])
      got = out["turns"][0]["readers"]["r"]
      self.assertEqual(got["extra"], extra, result)
      self.assertEqual(got["missed"], missed, result)

  def test_only_reads_of_her_message_count(self):
    out = self.R.build([router(12, {"a": 480})], [shadow(12, (480,))],
                       [reader(12, "on_the_reply", [999.0], client=False), reader(12, "on_her", [480.0])])
    self.assertNotIn("on_the_reply", out["turns"][0]["readers"])
    self.assertEqual(out["distinct_readers_of_her_words"], 1)

  def test_the_distinct_count_and_disagreement_turns(self):
    rows_r = [router(t, {"a": 480, "b": 340}) for t in (1, 2, 3)]
    rows_s = [shadow(t, (480, 340)) for t in (1, 2, 3)]
    rows_n = ([reader(t, "door_c_numbers_in_words", [480.0]) for t in (1, 2, 3)]
              + [reader(t, "message_figures", [480.0, 340.0]) for t in (1, 2)]
              + [reader(3, "retention_answer", None)])
    out = self.R.build(rows_r, rows_s, rows_n)
    self.assertEqual(out["distinct_readers_of_her_words"], 3)
    by = {r["reader"]: r for r in out["readers"]}
    self.assertEqual(by["door_c_numbers_in_words"]["turns"], 3)
    self.assertEqual(by["door_c_numbers_in_words"]["turns_disagreeing_with_the_one_reading"], 3)
    self.assertEqual(by["message_figures"]["turns_disagreeing_with_the_one_reading"], 0)

  def test_the_endpoint_exists_and_the_report_never_reads_her_words(self):
    src = (ROOT / "python" / "api.py").read_text(encoding="utf-8-sig")
    self.assertIn('"/api/one-reader-report"', src)
    mod = (ROOT / "python" / "client_intake_and_finmo" / "one_reader_report.py").read_text(encoding="utf-8-sig")
    for forbidden in ("messages_json", "user_message", "_turn_user_text", "client_words\"]"):
      self.assertNotIn(forbidden, mod)


if __name__ == "__main__":
  unittest.main(verbosity=2)
