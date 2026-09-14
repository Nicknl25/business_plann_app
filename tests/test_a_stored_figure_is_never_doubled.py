"""A stored figure added to itself is not something a reply may say.

Nick ruled 2026-09-14: fix it now. Door B's explained_figures lets a reply state
the sum of two stored financial figures; its inner loop started at the same
index as the outer one, so every stored figure was also added to ITSELF and
double any stored figure read as explained. On the CW-069 clones a reply saying
revenue is 3,359,200 against a stored 1,679,600 would have passed. Unlike every
other defect that day it needed no client sentence at all - only the store.

For generated stores of any size these pins state:
  - twice a stored financial figure is never explained, and a reply stating it
    is a disagreement;
  - the sum of two DIFFERENT stored figures is still explained;
  - a stored figure itself is still explained.
"""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


class NoStoredFigureIsDoubled(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo.intake_guard.door_b import explained_figures, find_disagreements  # type: ignore

    self.explained = explained_figures
    self.disagree = find_disagreements

  def _close(self, vals, x):
    return any(abs(v - x) <= max(0.5, abs(x) * 0.005) for v in vals)

  def test_double_is_never_explained_and_distinct_sums_still_are(self):
    pools = ((1679600.0,), (1679600.0, 95000.0), (420000.0, 61000.0, 18250.0), (250000.0, 250000.5))
    for pool in pools:
      store = {"financials": {"f%d" % i: v for i, v in enumerate(pool)}}
      vals = self.explained(store, None, "", reply_text="", recent_user_texts=[])
      distinct = sorted(set(round(v, 2) for v in pool))
      for v in distinct:
        self.assertTrue(self._close(vals, v), "stored %r stopped being explained" % v)
      for a, b in itertools.combinations(distinct, 2):
        if abs(a - b) > 1.0:
          self.assertTrue(self._close(vals, a + b), "the sum of %r and %r stopped being explained" % (a, b))
      for v in distinct:
        doubled = 2 * v
        others = [x for x in distinct if x != v]
        if any(abs(doubled - (x + y)) <= max(0.5, doubled * 0.005) for x, y in itertools.combinations(distinct, 2)) \
            or any(abs(doubled - x) <= max(0.5, doubled * 0.005) for x in others):
          continue                  # a genuine coincidence with a real pair or figure
        self.assertFalse(self._close(vals, doubled), "double %r (%r) was explained in pool %r" % (v, doubled, pool))

  def test_the_cw069_reply_is_a_disagreement(self):
    store = {"financials": {"current_revenue": 1679600.0}}
    dis = self.disagree("Your revenue works out to $3,359,200 a year.", store, None, "", [])
    self.assertTrue(any(abs((d.get("value") or 0) - 3359200.0) < 1.0 for d in dis), dis)


if __name__ == "__main__":
  unittest.main(verbosity=2)
