"""The judgment run window opens at the draft's creation, never before.

Bright Smiles Dental (186029c6, 2026-09-10): the window's 5-minute lead
admitted the tail of the massage-studio run that finished 59 seconds
before the dental draft existed. Its growth judgment tied the genuine
one at corroboration score 2 (both corroborate only on small round
scalars - 0.03/0.06/0.08 live in any financials_json) and the recovery
fail-louded: "growth: 2 corroboration-tied candidate store rows in the
run window - refusing to guess". The silent variant is worse: a key
with ONLY the foreign row is accepted with no gate at all.

A judgment about a draft cannot predate the draft's existence - the
store rows and the draft row are stamped by the same DB clock, so there
is no skew to buffer. Window = [created_at, updated_at + 2h].
Genuinely concurrent runs can still tie inside that window; those keep
the fail-loud, which is the design ("refusing to guess").
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from writing_phase_v2 import judgments as JG  # noqa: E402

CREATED = dt.datetime(2026, 9, 10, 11, 39, 8)
UPDATED = dt.datetime(2026, 9, 10, 11, 59, 19)


def _draft(**over):
  d = {"created_at": CREATED, "updated_at": UPDATED,
       "financials_json": json.dumps(
           {"_coherence": {"a": 0.03, "b": 0.06, "c": 0.08}}),
       "model_input_json": None, "marketing_model_json": None}
  d.update(over)
  return d


def _cc_row(tool, payload, ts):
  return {"created_at": ts, "response_text": json.dumps(
      {"choices": [{"message": {"tool_calls": [{"function": {
          "name": tool, "arguments": json.dumps(payload)}}]}}]})}


class _FakeCursor:
  def __init__(self, rows):
    self._rows = rows
    self.window = None

  def execute(self, sql, params):
    lo, hi = params
    self.window = (lo, hi)
    self._out = [r for r in self._rows if lo <= r["created_at"] <= hi]

  def fetchall(self):
    return self._out


class _FakeConn:
  def __init__(self, rows):
    self.cur = _FakeCursor(rows)

  def cursor(self, dictionary=True):
    return self.cur


FOREIGN = _cc_row("submit_growth_judgment",
                  {"year1_annual_growth": 0.08, "mature_annual_growth": 0.03,
                   "rationale": "massage studio"},
                  CREATED - dt.timedelta(minutes=2, seconds=16))
GENUINE = _cc_row("submit_growth_judgment",
                  {"year1_annual_growth": 0.06, "mature_annual_growth": 0.03,
                   "rationale": "dental clinic"},
                  CREATED + dt.timedelta(minutes=12, seconds=56))


class RunWindowTests(unittest.TestCase):
  def test_window_opens_at_creation(self):
    lo, hi = JG._run_window(_draft())
    self.assertEqual(lo, CREATED)
    self.assertEqual(hi, UPDATED + dt.timedelta(hours=2))

  def test_prior_runs_tail_is_excluded(self):
    """The Bright Smiles shape: foreign row 2m16s before the draft
    existed, genuine row inside the run - recovery returns the genuine
    payload instead of raising the corroboration tie."""
    out = JG.recover_from_store(_FakeConn([FOREIGN, GENUINE]), _draft())
    self.assertEqual(out["growth"]["rationale"], "dental clinic")

  def test_lone_foreign_row_is_not_silently_adopted(self):
    """The worse, silent variant: with no genuine row, a foreign row
    before creation must yield ABSENT, not the massage studio's growth."""
    out = JG.recover_from_store(_FakeConn([FOREIGN]), _draft())
    self.assertNotIn("growth", out)

  def test_concurrent_tie_still_refuses(self):
    """Two candidates genuinely inside the window with equal positive
    scores keep the fail-loud."""
    other = _cc_row("submit_growth_judgment",
                    {"year1_annual_growth": 0.08,
                     "mature_annual_growth": 0.03,
                     "rationale": "second iteration"},
                    CREATED + dt.timedelta(minutes=13))
    with self.assertRaises(LookupError) as cm:
      JG.recover_from_store(_FakeConn([other, GENUINE]), _draft())
    self.assertIn("refusing to guess", str(cm.exception))


if __name__ == "__main__":
  unittest.main()
