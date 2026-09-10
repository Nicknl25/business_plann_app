"""Numbers carried in dict KEYS are part of the checker's universe.

Bright Smiles Dental (186029c6, 2026-09-10): the writer quoted the BDS
size band - "only 380 firms in the entire trade employ between 100 and
499 people" - from the warehouse fact
    warehouse/bds_firm_size_2023/firms_by_size/{"e) 100 to 499": 380}.
The 380 resolved (numeric value); the 499 exists ONLY in the key label,
which _universe never walked, so a true, sourced figure failed the final
check and the plan was stamped FAILED. Keyed band labels ARE data - the
band edge is as quotable as the count it labels.
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

from writing_phase_v2.checker import _universe  # noqa: E402


def _bundle(**over):
  b = {"warehouse": {"bds_firm_size_2023": {"firms_by_size": {
          "a) 1 to 4": 37935, "e) 100 to 499": 380}}},
       "record": {"transcript": []}}
  b.update(over)
  return b


class KeyLabelUniverseTests(unittest.TestCase):
  def test_band_edge_in_a_key_resolves(self):
    nearest = _universe(_bundle(), {})
    hit = nearest(499.0, 0.5, 0.0)
    self.assertIsNotNone(hit)
    self.assertIn("~key", hit[1])

  def test_value_still_resolves(self):
    nearest = _universe(_bundle(), {})
    self.assertIsNotNone(nearest(380.0, 0.5, 0.0))

  def test_transcript_keys_stay_out(self):
    """The transcript exclusion holds for keys exactly as it does for
    string values."""
    b = _bundle()
    b["record"]["transcript"] = [
        {"role": "user", "content": "hello", "key 777 label": 1}]
    nearest = _universe(b, {})
    self.assertIsNone(nearest(777.0, 0.5, 0.0))


if __name__ == "__main__":
  unittest.main()
