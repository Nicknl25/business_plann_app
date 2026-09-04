"""THE GUARD ON THE WRITING-PHASE RULE SET (2026-08-30).

Nick's standard: "EVERY RULE NEEDS A CHECK BEHIND IT OR IT ISN'T A RULE."
This file is the check on the checks. It fails if a rule loses its enforcement,
if a check disappears, if the door is bypassed, or if the honest list of
unenforceable rules grows without anyone saying so.

It also pins the two things a machine cannot hold - rule 10, and the INFERRED
qualitative escape hatch - as EXPLICIT expectations, so that if someone later
believes they are enforced, this test tells them otherwise.
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

from writing_phase import checks as C          # noqa: E402
from writing_phase import rules as R           # noqa: E402


class EveryRuleHasACheckOrSaysItDoesNotTests(unittest.TestCase):

  def test_every_rule_id_is_unique_and_sequential(self):
    ids = [r["id"] for r in R.WRITING_RULES]
    self.assertEqual(len(ids), len(set(ids)), "duplicate rule id")
    self.assertEqual(ids, ["R%02d" % n for n in range(1, len(ids) + 1)],
                     "rule ids must run R01..Rnn with no gaps")

  def test_every_rule_names_a_check_or_is_declared_unenforceable(self):
    for rule in R.WRITING_RULES:
      if rule.get("check"):
        self.assertIn(rule["check"], C.CHECK_REGISTRY,
                      "%s names check %r which does not exist"
                      % (rule["id"], rule["check"]))
        self.assertTrue(rule.get("failure_code"),
                        "%s has a check but no failure code" % rule["id"])
      else:
        self.assertEqual(rule["enforcement"], "soft",
                         "%s has no check, so it must be declared soft" % rule["id"])
        self.assertTrue(rule.get("cannot_enforce"),
                        "%s has no check and must say what cannot be enforced"
                        % rule["id"])

  def test_the_unenforceable_set_is_exactly_what_nick_accepted(self):
    """If this list grows, someone must say so out loud rather than let a rule
    quietly become decorative."""
    self.assertEqual([r["id"] for r in R.unenforceable_rules()], ["R10"])

  def test_proxy_rules_admit_what_they_cannot_catch(self):
    for rule in R.rules_by_enforcement("proxy"):
      self.assertTrue(rule.get("cannot_enforce"),
                      "%s is a proxy and must state its blind spot" % rule["id"])

  def test_no_check_exists_without_a_rule(self):
    named = {r["check"] for r in R.WRITING_RULES if r.get("check")}
    self.assertEqual(sorted(set(C.CHECK_REGISTRY) - named), [],
                     "a check exists that no rule references")


class ChecksThatCannotRunMustFailTests(unittest.TestCase):
  """The CoInitialize law. A check that cannot run fails the section; it never
  passes by default. This is the single most important behaviour here."""

  def test_could_not_run_is_never_a_pass(self):
    r = C.CheckResult.could_not_run("R06", "no brief")
    self.assertFalse(r.executed)
    self.assertFalse(r.passed)

  def test_section_with_an_unrunnable_check_does_not_pass(self):
    results = [
      C.CheckResult("R03", True, True),
      C.CheckResult.could_not_run("R06", "no brief supplied"),
    ]
    self.assertFalse(C.section_passes(results))
    self.assertEqual([f.rule_id for f in C.failures(results)], ["R06"])

  def test_a_section_with_no_checks_at_all_does_not_pass(self):
    self.assertFalse(C.section_passes([]))

  def test_every_data_dependent_check_declines_rather_than_passes(self):
    """Called with nothing to work on, these must report could-not-run."""
    for fn, kwargs in (
      (C.check_fact_tokens_resolve, {"section_payload": {"sentences": []}}),
      (C.check_specificity, {"section_payload": {"sentences": []}}),
      (C.check_chart_registry, {}),
      (C.check_section_emission, {}),
      (C.check_basis_of_projections, {}),
      (C.check_proportion, {}),
      (C.check_footer_and_run_id, {}),
      (C.check_document_craft, {}),
      (C.check_editable, {}),
    ):
      res = fn(**kwargs)
      self.assertFalse(res.executed, "%s claimed to run with no inputs" % fn.__name__)
      self.assertFalse(res.passed, "%s passed with no inputs" % fn.__name__)


class TheRulesActuallyCatchTheirViolationTests(unittest.TestCase):
  """Red-on-bug for the rules that carry the most weight."""

  def _payload(self, text, cls="GROUNDED", **extra):
    p = {"section_key": "the_business",
         "sentences": [{"text": text, "class": cls}], "notes": []}
    p.update(extra)
    return p

  def test_R03_catches_a_named_gap_in_prose(self):
    res = C.check_no_absence_language(self._payload(
      "Local competitor counts were not available for this area."))
    self.assertTrue(res.executed)
    self.assertFalse(res.passed)

  def test_R03_also_scans_notes_not_just_prose(self):
    """Nick's ruling C - a BASIS note can break rule 3 just as easily."""
    payload = self._payload("The roastery serves regional accounts.")
    payload["notes"] = [{"id": "1", "kind": "BASIS",
                         "text": "Based on industry norms, as local data is unavailable."}]
    self.assertFalse(C.check_no_absence_language(payload).passed)

  def test_R04_catches_machinery_but_spares_the_basis_paragraph(self):
    self.assertFalse(C.check_no_machinery(self._payload(
      "The model derived the revenue figure.")).passed)
    spared = {"section_key": "financial_plan", "notes": [], "sentences": [
      {"text": "These projections rest on the operator's stated pricing.",
       "class": "GROUNDED", "span": "basis_of_projections"}]}
    self.assertTrue(C.check_no_machinery(spared).passed)

  def test_R17_catches_a_typed_number_and_allows_a_fact_token(self):
    self.assertFalse(C.check_no_computation(self._payload(
      "Revenue grew 14% over the period.")).passed)
    self.assertTrue(C.check_no_computation(self._payload(
      "Revenue reached {{fact:annual.revenue_y1}} in the first year.")).passed)

  def test_R17_allows_structural_year_labels(self):
    self.assertTrue(C.check_no_computation(self._payload(
      "Year 1 establishes the base against which Year 5 is measured.")).passed)

  def test_R18_blocks_quarterly_facts_in_the_body_but_allows_the_two_exceptions(self):
    self.assertFalse(C.check_namespace_scope(self._payload(
      "Revenue in {{fact:quarterly.revenue_q7}} was strong.")).passed)
    self.assertTrue(C.check_namespace_scope(self._payload(
      "Cash bottoms at {{fact:quarterly.cash_trough}}.")).passed)

  def test_R18_lets_the_appendix_carry_quarterly_detail(self):
    payload = self._payload("{{fact:quarterly.revenue_q7}}")
    payload["section_key"] = "appendix"
    self.assertTrue(C.check_namespace_scope(payload).passed)

  def test_R14_framing_may_not_carry_digits_proper_nouns_or_citations(self):
    self.assertFalse(C.check_sentence_classes(self._payload(
      "Redbrook is well positioned.", cls="FRAMING")).passed)
    self.assertFalse(C.check_sentence_classes(self._payload(
      "The business holds 3 advantages.", cls="FRAMING")).passed)

  def test_R14_density_guard_caps_framing(self):
    payload = {"section_key": "the_business", "notes": [], "sentences": [
      {"text": "Positioning remains sound.", "class": "FRAMING"},
      {"text": "The approach is durable.", "class": "FRAMING"},
    ]}
    res = C.check_sentence_classes(payload)
    self.assertFalse(res.passed, "an all-framing section must fail the guard")

  def test_R15_catches_first_and_second_person(self):
    self.assertFalse(C.check_voice(self._payload("We operate three lines.")).passed)
    self.assertTrue(C.check_voice(self._payload(
      "Redbrook Coffee Roasters operates three lines.")).passed)

  def test_R16_catches_a_hedged_grounded_figure(self):
    self.assertFalse(C.check_number_style(self._payload(
      "Revenue was approximately {{fact:annual.revenue_y1}}.")).passed)

  def test_R11_requires_marker_note_bijection_and_a_vintage_on_sources(self):
    orphan = {"section_key": "x", "notes": [],
              "sentences": [{"text": "A claim.[^1]", "class": "GROUNDED"}]}
    self.assertFalse(C.check_notes(orphan).passed)
    no_vintage = {"section_key": "x",
                  "sentences": [{"text": "A claim.[^1]", "class": "GROUNDED"}],
                  "notes": [{"id": "1", "kind": "SOURCE",
                             "source_name": "ACS", "source_vintage": "",
                             "text": "American Community Survey"}]}
    self.assertFalse(C.check_notes(no_vintage).passed)

  def test_R11_forbids_attributing_anything_to_the_software(self):
    payload = {"section_key": "x",
               "sentences": [{"text": "A claim.[^1]", "class": "GROUNDED"}],
               "notes": [{"id": "1", "kind": "BASIS",
                          "text": "GPT determined this from the roster."}]}
    self.assertFalse(C.check_notes(payload).passed)

  def test_R08_figure_numbers_must_be_contiguous_after_a_silent_omission(self):
    """Nick's addition: an omitted chart renumbers. A gap means the text can
    reference a figure that is not there."""
    self.assertFalse(C.check_chart_registry(emitted_charts=[
      {"key": "revenue_by_lob", "figure_number": 1},
      {"key": "margin_structure", "figure_number": 3},
    ]).passed)
    self.assertTrue(C.check_chart_registry(emitted_charts=[
      {"key": "revenue_by_lob", "figure_number": 1},
      {"key": "margin_structure", "figure_number": 2},
    ]).passed)

  def test_R08_refuses_a_chart_that_is_not_on_the_registry(self):
    self.assertFalse(C.check_chart_registry(emitted_charts=[
      {"key": "invented_chart", "figure_number": 1}]).passed)

  def test_R13_core_sections_cannot_go_missing(self):
    every = [s["key"] for s in R.SECTION_REGISTRY if s["core"]]
    self.assertTrue(C.check_section_emission(
      emitted_sections=every, triggers={}).passed)
    self.assertFalse(C.check_section_emission(
      emitted_sections=[k for k in every if k != "disclosures"], triggers={}).passed)

  def test_R13_conditional_section_needs_its_trigger(self):
    every = [s["key"] for s in R.SECTION_REGISTRY if s["core"]]
    with_funding = sorted(every + ["funding_request"],
                          key=lambda k: R.section(k)["order"])
    self.assertFalse(C.check_section_emission(
      emitted_sections=with_funding, triggers={"funding_is_sought": False}).passed)
    self.assertTrue(C.check_section_emission(
      emitted_sections=with_funding, triggers={"funding_is_sought": True}).passed)

  def test_R20_flags_but_never_fails_a_section(self):
    res = C.check_proportion(section_pages={"financial_plan": 12.0})
    self.assertTrue(res.executed)
    self.assertTrue(res.passed, "proportion must never cut or fail a section")
    self.assertTrue(res.offenders, "an out-of-band section must still be flagged")


class RegistryShapeTests(unittest.TestCase):

  def test_every_chart_belongs_to_a_registered_section(self):
    keys = {s["key"] for s in R.SECTION_REGISTRY}
    for c in R.CHART_REGISTRY:
      self.assertIn(c["section"], keys, "chart %s has no section" % c["key"])

  def test_charts_owned_by_a_conditional_section_vanish_with_it(self):
    conditional = {s["key"] for s in R.SECTION_REGISTRY if not s["core"]}
    owned = [c["key"] for c in R.CHART_REGISTRY if c["section"] in conditional]
    self.assertIn("sba_ask_distribution", owned,
                  "the funding chart must belong to the funding section")
    self.assertNotIn("sources_and_uses", [c["key"] for c in R.CHART_REGISTRY],
                     "the waterfall is OUT (Nick 2026-08-31) - sources & uses is a body TABLE")

  def test_only_the_two_financial_charts_use_quarterly_series(self):
    """Nick's ruling: prose stays annual, charts show the moment."""
    q = sorted(c["key"] for c in R.CHART_REGISTRY if c["namespace"] == R.NS_QUARTERLY)
    self.assertEqual(q, ["break_even", "cash_position"])

  def test_body_page_targets_sum_into_the_agreed_band(self):
    lo = sum(s["pages_min"] for s in R.SECTION_REGISTRY
             if s["pages_min"] and s["key"] in set(R.body_section_keys()))
    hi = sum(s["pages_max"] for s in R.SECTION_REGISTRY
             if s["pages_max"] and s["key"] in set(R.body_section_keys()))
    self.assertLessEqual(lo, R.BODY_PAGES_MAX)
    self.assertGreaterEqual(hi, R.BODY_PAGES_MIN)

  def test_the_two_output_paths_stay_different(self):
    """Nick's ruling H - the workbook path's misspelling is deliberate and
    neither path may be 'fixed' to match the other."""
    self.assertNotEqual(R.PLAN_OUTPUT_DIR, R.WORKBOOK_OUTPUT_DIR)
    self.assertIn("Cilient", R.WORKBOOK_OUTPUT_DIR)
    self.assertIn("Client Written Plans", R.PLAN_OUTPUT_DIR)

  def test_density_guard_is_marked_provisional(self):
    self.assertTrue(R.DENSITY_GUARD_PROVISIONAL,
                    "the 55/30/15 split is provisional until ten real plans")

  def test_the_inferred_escape_hatch_is_recorded_not_hidden(self):
    self.assertTrue(R.INFERRED_QUALITATIVE_ESCAPE_HATCH)
    self.assertIn("QUALITATIVE", R.rule("R14")["cannot_enforce"].upper())


class NoteMarkerAndSourceHonestyTests(unittest.TestCase):
  """Three defects found LIVE on the first authored section (2026-09-01):
  [^n] is R11's own sanctioned notation and must not fail R17 as a typed
  digit nor glue sentences together for R01's length scan; and ruling E holds
  at the note level - a SOURCE note over a BASIS fact is an invented vintage
  waiting to happen (GPT produced exactly that on the first live call)."""


  def test_a_malformed_token_fails_r06(self):
    """{{entity.x}} without fact: matches no scan and renders as garbage in
    the docx (live, 2026-09-03) - R06 refuses it."""
    res = C.check_fact_tokens_resolve(
      {"sentences": [{"text": "It is an {{entity.legal_entity}} in Kansas."}]},
      brief_facts={"entity.legal_entity": {"rendered": "S-corp"}})
    self.assertFalse(res.passed)
    self.assertTrue(any("malformed" in o for o in res.offenders))

  def test_malformed_tokens_with_unambiguous_intent_are_normalized(self):
    """The orphan-note precedent: a brief-key written as {{key}} is fixed to
    {{fact:key}} and RECORDED; a non-key stays for R06 to refuse."""
    from writing_phase import author as AU
    from writing_phase.facts.assembler import SectionBrief
    brief = SectionBrief("the_business",
                         facts={"entity.legal_entity": {"rendered": "S-corp"}})
    payload = {"sentences": [
      {"text": "It is an {{entity.legal_entity}} with {{bogus.key}} inside."}],
      "notes": []}
    AU._normalize_malformed_tokens(payload, brief)
    self.assertIn("{{fact:entity.legal_entity}}", payload["sentences"][0]["text"])
    self.assertIn("{{bogus.key}}", payload["sentences"][0]["text"])
    self.assertEqual(payload["normalized_tokens"], ["entity.legal_entity"])

  def test_a_note_marker_is_not_a_typed_number(self):
    res = C.check_no_computation({"sentences": [
      {"text": "{{fact:industry.five_year_survival_rate}} survive five years.[^1]"}]})
    self.assertTrue(res.executed and res.passed,
                    "R17 failed a sentence on its own citation marker")
    res2 = C.check_no_computation({"sentences": [{"text": "It sold 41 units.[^1]"}]})
    self.assertFalse(res2.passed, "a real typed digit must still fail")

  def test_markers_do_not_merge_sentences_for_readability(self):
    body = ("Short claim here.[^1] " + "word " * 30).strip() + "."
    res = C.check_readability({"sentences": [{"text": body}]})
    self.assertTrue(res.passed,
                    "two legal sentences merged across a marker and failed R01")

  def test_a_source_note_needs_a_source_fact_behind_it(self):
    payload = {
      "sentences": [{"class": "INFERRED",
                     "text": "{{fact:industry.five_year_survival_rate}} survive.[^1]"}],
      "notes": [{"id": "1", "kind": "SOURCE", "text": "U.S. Census Bureau, BDS",
                 "source_name": "BDS", "source_vintage": "latest available release"}],
    }
    brief_facts = {"industry.five_year_survival_rate":
                   {"rendered": "56.2%", "note_kind": "BASIS", "grounding": "INFERRED"}}
    res = C.check_notes(payload, brief_facts=brief_facts)
    self.assertFalse(res.passed, "a SOURCE note over a BASIS fact must fail R11")
    payload["notes"][0]["kind"] = "BASIS"
    self.assertTrue(C.check_notes(payload, brief_facts=brief_facts).passed)
    # without a brief the structural checks still run exactly as before
    self.assertTrue(C.check_notes(payload).executed)

  def test_a_hedge_offends_only_on_the_number_not_near_it(self):
    """'built around a weekly route' is idiom; 'around {{fact:x}}' is a hedge
    on a grounded figure. Found live 2026-09-01."""
    ok = C.check_number_style({"sentences": [
      {"text": "Built around dependable weekly supply of {{fact:annual.revenue_y1}}."}]})
    self.assertTrue(ok.passed, "an idiomatic 'around' away from the token must pass")
    bad = C.check_number_style({"sentences": [
      {"text": "Revenue of around {{fact:annual.revenue_y1}} in Year 1."}]})
    self.assertFalse(bad.passed, "a hedge on the token itself must still fail")

  def test_a_digit_inside_the_business_name_is_not_a_computation(self):
    """R15 requires the name; a client called 'Studio 54' must not fail R17
    for complying. Found live 2026-09-01 on 'Bluestem Grounds P6 Retest'."""
    ok = C.check_no_computation(
      {"sentences": [{"text": "Bluestem Grounds P6 Retest maintains its routes."}]},
      business_name="Bluestem Grounds P6 Retest")
    self.assertTrue(ok.passed, "the literal business name must be exempt")
    bad = C.check_no_computation(
      {"sentences": [{"text": "Bluestem Grounds P6 Retest maintains 40 properties."}]},
      business_name="Bluestem Grounds P6 Retest")
    self.assertFalse(bad.passed, "other digits must still fail")

  def test_trade_vocabulary_digits_and_hyphenated_pronouns_are_not_violations(self):
    """Found live 2026-09-01: 'B2B' failed R17 on its own 2, and the product
    name 'grow-your-own kits' failed R15 as second person."""
    r17 = C.check_no_computation({"sentences": [
      {"text": "A scaled B2B SaaS operator with D2C retail lines."}]})
    self.assertTrue(r17.passed, "B2B/D2C are words, not computations")
    r15 = C.check_voice({"sentences": [
      {"text": "It sells grow-your-own kits at farmers markets."}]})
    self.assertTrue(r15.passed, "a hyphenated product name is not second person")
    r15b = C.check_voice({"sentences": [{"text": "Your business will thrive."}]})
    self.assertFalse(r15b.passed, "real second person must still fail")

  def test_machinery_terms_match_words_not_substrings(self):
    """'llm' fired on 'fulfillment' live, 2026-09-01. Ordinary business prose
    must pass; the real term must still fail."""
    ok = C.check_no_machinery({"sentences": [
      {"text": "Implementation and order fulfillment are handled remotely."}]})
    self.assertTrue(ok.passed, "'fulfillment' is not machinery")
    bad = C.check_no_machinery({"sentences": [{"text": "An LLM drafted this."}]})
    self.assertFalse(bad.passed, "a real machinery term must still fail")

  def test_demonstrative_anaphora_and_word_rendered_hedges_are_legal(self):
    """2026-09-02 batch findings: 'That combination of...' is anchored
    cross-record reasoning, and 'built around two lines' hedges nothing when
    the token renders as a word."""
    r05 = C.check_specificity(
      {"sentences": [
        {"class": "GROUNDED", "paragraph": 1,
         "text": "Halbrook holds {{fact:entity.stated_cash_on_hand}} in cash."},
        {"class": "INFERRED", "paragraph": 1,
         "text": "That combination of liquidity and leverage supports growth."}]},
      client_tokens={"Halbrook"})
    self.assertTrue(r05.passed, "a sentence coheres with its anchored paragraph")
    bf = {"annual.lob_count": {"rendered": "two"},
          "entity.stated_revenue_per_employee": {"rendered": "$117,000"}}
    ok = C.check_number_style({"sentences": [
      {"text": "Work is built around {{fact:annual.lob_count}} complementary lines."}]},
      brief_facts=bf)
    self.assertTrue(ok.passed, "a word-rendered token cannot be hedged")
    bad = C.check_number_style({"sentences": [
      {"text": "It generates approximately {{fact:entity.stated_revenue_per_employee}} per person."}]},
      brief_facts=bf)
    self.assertFalse(bad.passed, "a hedge on a digit-rendered figure must still fail")


  def test_r15_requires_the_business_named_somewhere_in_the_section(self):
    """The anchor that makes anaphora legal (Nick 2026-09-02): the section
    must NAME the business at least once; after that 'the company' is fine."""
    ok = C.check_voice(
      {"sentences": [{"text": "Halbrook keeps the same crews on the same routes."},
                     {"text": "The company rarely loses a property manager."}]},
      business_name="Halbrook Grounds Management")
    self.assertTrue(ok.passed)
    bad = C.check_voice(
      {"sentences": [{"text": "The company keeps crews on fixed routes."}]},
      business_name="Halbrook Grounds Management")
    self.assertFalse(bad.passed, "a section that never names the business fails R15")








class ProseQualityChecksTests(unittest.TestCase):
  """Nick's second 2026-09-02 ruling: structural or not at all. The summary
  closer is fact-reference structure; the word band is a limit. Repeated
  arguments, intensifiers, genericity and narrative bleed are DECLARED
  review-caught (the ledger in rules.py) - no pretend thresholds."""

  def test_summary_closer_is_fact_reference_structure(self):
    base = [{"text": "Crews stay on {{fact:entity.coverage_zip}} routes.", "paragraph": 1},
            {"text": "Revenue is {{fact:entity.stated_current_revenue}}.", "paragraph": 2}]
    # re-cites a fact, introduces none -> a summary, structurally
    recap = base + [{"text": "That tenure and {{fact:entity.stated_current_revenue}} define the company.", "paragraph": 3}]
    self.assertFalse(C.check_summary_closer({"sentences": recap}).passed)
    # introduces a first-use fact -> not a summary
    fresh = base + [{"text": "The next route adds {{fact:entity.stated_cash_on_hand}} of reserve.", "paragraph": 3}]
    self.assertTrue(C.check_summary_closer({"sentences": fresh}).passed)
    # fully qualitative closer -> exempt; its new-claim half is review's
    qual = base + [{"text": "The crews' continuity is what property managers remember.", "paragraph": 3}]
    self.assertTrue(C.check_summary_closer({"sentences": qual}).passed)


  def test_readability_measures_segments_not_colon_sentences(self):
    """A well-formed colon-list sentence reads as its parts (live,
    2026-09-02); a true run-on still fails."""
    listy = ("In a trade where turnover is common, continuity is an advantage: "
             + "properties stay maintained with less oversight, "
             + "issues are spotted early, and managers entrust bigger work "
             + "to crews that proved themselves on routine visits.")
    self.assertTrue(C.check_readability({"sentences": [{"text": listy}]}).passed)
    runon = ("word " * 50).strip() + "."
    self.assertFalse(C.check_readability({"sentences": [{"text": runon}]}).passed)

  def test_length_band_fails_outside(self):
    short = {"sentences": [{"text": "Too short."}]}
    self.assertFalse(C.check_length_band(short).passed)
    body = {"sentences": [{"text": ("word " * 25).strip() + "."} for _ in range(16)]}
    self.assertTrue(C.check_length_band(body).passed)

  def test_the_removed_heuristics_stay_removed(self):
    """A word-list check quietly reintroduced would betray the ledger."""
    for gone in ("check_repeated_argument", "check_unearned_intensifiers",
                 "check_section_bleed"):
      self.assertFalse(hasattr(C, gone), "%s must stay removed - the ledger "
                       "declares it review-caught" % gone)
    self.assertFalse(hasattr(R, "SECTION_BLEED_VOCAB"))
    self.assertFalse(hasattr(R, "UNEARNED_INTENSIFIERS"))
    self.assertFalse(hasattr(R, "TYPICALITY_MARKERS"))


if __name__ == "__main__":
  unittest.main()
