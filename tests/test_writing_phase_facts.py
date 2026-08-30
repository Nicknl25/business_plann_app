"""Guards on the fact catalogue (2026-08-30). No DB: these pin the contract."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from writing_phase import rules as R                        # noqa: E402
from writing_phase.facts import catalog as C                # noqa: E402
from writing_phase.facts import sentences as S              # noqa: E402
from writing_phase.facts.catalog import ABSENT, Fact, FactCatalog, Provenance  # noqa: E402


class FactContractTests(unittest.TestCase):

  def test_a_fact_cannot_hold_absent_or_none(self):
    for bad in (ABSENT, None):
      with self.assertRaises(ValueError):
        Fact("annual.x", bad, "money", C.prov_model("x"))

  def test_absent_is_falsy_and_distinct_from_zero(self):
    self.assertFalse(ABSENT)
    self.assertIsNot(ABSENT, 0)
    self.assertNotEqual(ABSENT, 0)

  def test_a_fact_needs_a_known_formatter_and_a_namespace(self):
    with self.assertRaises(ValueError):
      Fact("annual.x", 1.0, "no_such_formatter", C.prov_model("x"))
    with self.assertRaises(ValueError):
      Fact("bogus.x", 1.0, "money", C.prov_model("x"))

  def test_source_note_requires_source_and_vintage(self):
    with self.assertRaises(ValueError):
      Provenance(R.CLASS_GROUNDED, R.NOTE_KIND_SOURCE, "b", source_name="ACS", source_vintage=None)

  def test_ruling_e_raw_tables_are_inferred_baseline_is_grounded_source(self):
    raw = C.prov_raw("County Business Patterns", "2022", "x")
    self.assertEqual(raw.grounding, R.CLASS_INFERRED)
    self.assertEqual(raw.note_kind, R.NOTE_KIND_BASIS)
    self.assertEqual(raw.table_vintage, "2022")   # carried, not cited
    base = C.prov_baseline("IRS_SOI", 2021, "gross margin", 4, 120)
    self.assertEqual(base.grounding, R.CLASS_GROUNDED)
    self.assertEqual(base.note_kind, R.NOTE_KIND_SOURCE)


class CatalogBehaviourTests(unittest.TestCase):

  def test_put_absent_is_dropped_and_get_logs_the_reason(self):
    seen = []
    cat = FactCatalog("d1", miss_sink=lambda **kw: seen.append(kw))
    cat.put("market.state_establishments", ABSENT, "count", C.prov_model("x"),
            absent_reason="CBP has no state row for NAICS 111411")
    self.assertFalse(cat.has("market.state_establishments"))
    self.assertIsNone(cat.get("market.state_establishments", section_key="market_and_industry"))
    self.assertEqual(seen[0]["fact_key"], "market.state_establishments")
    self.assertIn("111411", seen[0]["reason"])

  def test_never_computed_keys_are_logged_too(self):
    seen = []
    cat = FactCatalog("d1", miss_sink=lambda **kw: seen.append(kw))
    cat.get("annual.something_nobody_built")
    self.assertEqual(seen[0]["reason"], "never computed")

  def test_get_quiet_does_not_log(self):
    seen = []
    cat = FactCatalog("d1", miss_sink=lambda **kw: seen.append(kw))
    cat.get_quiet("annual.x")
    self.assertEqual(seen, [])

  def test_body_brief_excludes_quarterly_except_the_two_exceptions(self):
    cat = FactCatalog("d1")
    cat.put("quarterly.revenue_q7", 1.0, "money", C.prov_model("x"))
    cat.put("quarterly.cash_trough", 6, "quarter_label", C.prov_model("x"))
    cat.put("annual.revenue_y1", 1.0, "money", C.prov_model("x"))
    body = cat.as_brief(body=True)
    self.assertNotIn("quarterly.revenue_q7", body)
    self.assertIn("quarterly.cash_trough", body)
    self.assertIn("annual.revenue_y1", body)
    self.assertIn("quarterly.revenue_q7", cat.as_brief(body=False))


class FormatterTests(unittest.TestCase):
  """Rule 16: exact under $10,000, nearest thousand above, millions written."""

  def test_money(self):
    self.assertEqual(C.fmt_money(9432), "$9,432")
    self.assertEqual(C.fmt_money(123456), "$123,000")
    self.assertEqual(C.fmt_money(1_400_000), "$1.4 million")
    self.assertEqual(C.fmt_money(3_000_000), "$3 million")
    self.assertEqual(C.fmt_money_exact(123456), "$123,456")

  def test_percent_decimal_only_when_it_means_something(self):
    self.assertEqual(C.fmt_percent(0.12), "12%")
    self.assertEqual(C.fmt_percent(0.124), "12.4%")

  def test_quarter_label_and_months(self):
    self.assertEqual(C.fmt_quarter_label(6), "the second quarter of Year 2")
    self.assertEqual(C.fmt_months(1), "1 month")
    self.assertEqual(C.fmt_months(2.5), "2.5 months")


class SentencesShapeTests(unittest.TestCase):

  def test_every_sentence_names_only_keys_it_uses_and_vice_versa(self):
    import re
    for s in S.SENTENCES:
      used = set(re.findall(r"\{([a-z_.0-9]+)\}", str(s["text"])))
      self.assertEqual(used, set(s["needs"]), "%s: tokens vs needs differ" % s["id"])

  def test_every_sentence_key_is_namespaced_and_body_sentences_are_annual(self):
    for s in S.SENTENCES:
      for k in s["needs"]:
        self.assertIn(k.split(".", 1)[0], R.FACT_NAMESPACES, k)
        if s["section"] != "appendix":
          self.assertTrue(R.namespace_allowed_in_body(k), "%s uses %s in the body" % (s["id"], k))

  def test_sentences_carry_no_typed_numbers(self):
    """Rule 17 at the template level: a sentence template has no digits."""
    import re
    for s in S.SENTENCES:
      stripped = re.sub(r"\{[^}]+\}", "", str(s["text"]))
      stripped = re.sub(r"Year[- ]?[1-5]", "", stripped)   # structural label, allowed by R17
      stripped = stripped.replace("7(a)", "")   # a programme name, not a quantity
      self.assertIsNone(re.search(r"\d", stripped), "%s carries a literal digit" % s["id"])

  def test_thirty_to_forty_plus_observations_and_an_honest_cannot_list(self):
    self.assertGreaterEqual(len(S.SENTENCES), 30)
    self.assertGreaterEqual(len(S.CANNOT_YET), 5)


if __name__ == "__main__":
  unittest.main()
