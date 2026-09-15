"""A CENSUS PAYROLL FIGURE IS CARRIED IN DOLLARS (Nick 2026-09-15, CW-073 Cedarbrook Dog
Grooming 09917eac - the written plan did not build).

County Business Patterns publishes annual payroll in THOUSANDS. The v2 warehouse copied the
raw figure (pay_ann 10130) into the bundle with no unit. The writer, knowing the Census
convention, correctly wrote "$10,130 thousand" in Competitive Landscape and in Staffing; the
checker reads that as $10,130,000 and had only 10,130 to resolve it against - two unresolved
numbers, plan not passed. 491 of 493 numbers resolved; those two were the whole failure.
The warehouse now carries the figure once, in dollars, as pay_ann_usd.
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

from writing_phase_v2.checker import check  # noqa: E402
from writing_phase_v2.warehouse import _pay_ann_usd  # noqa: E402


def _bundle(cbp_row):
  return {"warehouse": {}, "cbp_2022": {"county": {"812910": cbp_row}},
          "record": {"transcript": [{"role": "user", "content": "We groom dogs."}]}}


def _plan(text):
  return {"sections": [{"key": "competitive_landscape", "blocks": [{"type": "paragraph", "text": text}]}],
          "notes": [], "derivations": []}


def _unresolved(bundle, plan):
  findings, _info = check(bundle, plan)
  return [f for f in findings if f.startswith("unresolved number")]


class ACensusPayrollResolvesHoweverItIsWritten(unittest.TestCase):

  CASES = [  # (raw thousands as Census publishes it, the ways a writer states it)
    (10130, ["$10,130 thousand", "$10.13 million", "$10,130,000"]),
    (25354, ["$25,354 thousand", "$25.354 million"]),
    (41762, ["$41,762 thousand"]),
  ]

  def test_carried_in_dollars_every_honest_rendering_resolves(self):
    for raw, renderings in self.CASES:
      for text in renderings:
        with self.subTest(raw=raw, text=text):
          bundle = _bundle({"estab": 57.0, "pay_ann_usd": _pay_ann_usd(raw), "emp": 413.0})
          self.assertEqual(_unresolved(bundle, _plan("Segment payroll is %s." % text)), [])

  def test_the_raw_thousands_figure_is_what_failed(self):
    """The shape that shipped on 09917eac: raw 10130 in the bundle, '$10,130 thousand' in prose."""
    bundle = _bundle({"estab": 57.0, "pay_ann": 10130.0, "emp": 413.0})
    self.assertTrue(_unresolved(bundle, _plan("Segment payroll is $10,130 thousand.")))

  def test_the_conversion_is_exactly_times_one_thousand(self):
    self.assertEqual(_pay_ann_usd(10130), 10130000.0)
    self.assertEqual(_pay_ann_usd("22311"), 22311000.0)
    self.assertIsNone(_pay_ann_usd(None))


if __name__ == "__main__":
  unittest.main()
