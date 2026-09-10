"""The machinery word list is retired as a gate (Nick's ruling 2026-09-10).

Five ordinary-English false positives (unavailable, pipeline, the
year-vs-code hits, BizBuySell, and "patient intake" at a PT practice)
ended the pattern approach: the judgment moves to where the meaning is,
the way declared arithmetic did. The writer declares system referents
under the principle "the document speaks as the business's plan - it
never refers to how it was produced, what analysed it, or what decided
anything in it." A declared sentence is a violation whatever words it
used; no word triggers anything on its own. The old regex survives only
as a silent MACHINERY_AUDIT counter; the list is deleted when the
divergence holds at zero.

Pinned: (1) machinery-shaped ordinary English ("handles benefits
verification and patient intake") produces NO vocabulary finding;
(2) a missing system_referents key is a finding; (3) every declared
referent is a finding, machinery word or not; (4) undeclared regex hits
count on the silent audit info line, never as findings.
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


def _plan(text, system_referents=None):
  plan = {
    "title": "Pin Plan",
    "sections": [{"key": "operations", "title": "Operations",
                  "blocks": [{"type": "paragraph", "text": text}]}],
    "notes": [],
    "derivations": [],
    "omitted_sections": [],
  }
  if system_referents is not None:
    plan["system_referents"] = system_referents
  return plan


def _run(plan):
  bundle = {"warehouse": {}, "model": {}, "derived": {},
            "record": {"transcript": []}}
  findings, info = check(bundle, plan)
  return findings, info


class SystemReferentsTests(unittest.TestCase):
  def test_patient_intake_is_not_a_vocabulary_finding(self):
    """The fifth false positive, dead: 'intake' in ordinary English."""
    findings, info = _run(_plan(
      "The front desk handles benefits verification and patient intake "
      "for every visit.", system_referents=[]))
    self.assertFalse([f for f in findings if f.startswith("vocabulary [")],
                     findings)
    self.assertTrue(any("machinery audit: 1 undeclared" in i for i in info),
                    info)

  def test_missing_declaration_key_is_a_finding(self):
    findings, _ = _run(_plan("A plain sentence about the business."))
    self.assertTrue(any("no system_referents declaration" in f
                        for f in findings), findings)

  def test_declared_referent_is_a_violation_without_machinery_words(self):
    """'The projections prepared for this plan' - no machinery word, and
    a violation because the WRITER judged it refers to our system."""
    findings, _ = _run(_plan(
      "Growth follows the projections prepared for this plan.",
      system_referents=[{"section": "operations",
                         "sentence": "Growth follows the projections "
                                     "prepared for this plan."}]))
    self.assertTrue(any(f.startswith("self-reference declared [operations]")
                        for f in findings), findings)

  def test_clean_plan_with_empty_declaration_has_neither(self):
    findings, info = _run(_plan(
      "The clinic serves forty patients a week.", system_referents=[]))
    self.assertFalse([f for f in findings
                      if "system_referents" in f
                      or f.startswith("self-reference")
                      or f.startswith("vocabulary [")], findings)
    self.assertTrue(any("machinery audit: 0 undeclared" in i for i in info),
                    info)


if __name__ == "__main__":
  unittest.main()
