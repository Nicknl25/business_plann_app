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


class GeographyTravelsWithTheFactTests(unittest.TestCase):
  """Nick, 2026-08-30: 'Three coffee manufacturers operate in Ramsey County'
  and 'Minnesota has 26' are different claims. A count whose geography can
  silently change is a false sentence waiting to happen, so every sentence
  using a geography-scoped market key MUST also require the label fact, and
  the label may only be put by the same code path that puts the counts."""

  GEO_SCOPED_KEYS = (
    "market.establishments",
    "market.residents_per_establishment",
    "market.client_share_of_establishments",
    "market.emp_per_establishment",
    "market.payroll_per_establishment",
    "market.households_per_establishment",
  )

  def test_every_scoped_sentence_requires_the_geography_label(self):
    for s in S.SENTENCES:
      needs = set(s["needs"])
      if needs & set(self.GEO_SCOPED_KEYS):
        self.assertIn("market.competition_geo_label", needs,
                      "%s uses a geography-scoped count without the label" % s["id"])

  def test_no_sentence_uses_the_old_unlabelled_state_keys(self):
    dead = {"market.state_establishments", "market.residents_per_establishment_state",
            "market.client_share_of_state_establishments", "market.emp_per_establishment_state",
            "market.payroll_per_establishment_state", "market.households_per_establishment_state"}
    for s in S.SENTENCES:
      self.assertFalse(set(s["needs"]) & dead,
                       "%s still uses an unlabelled state-scoped key" % s["id"])

  def test_the_label_is_put_by_exactly_one_code_path(self):
    """One put site for the label, in the same block as the counts - read from
    the source rather than trusted."""
    import io as _io, os as _os
    src = _io.open(_os.path.join(ROOT, "python", "writing_phase", "facts", "build.py"),
                   encoding="utf-8").read()
    self.assertEqual(src.count('cat.put("market.competition_geo_label"'), 1,
                     "exactly ONE labelled put site for the geography label")
    self.assertEqual(src.count('cat.put("market.establishments"'), 1,
                     "exactly ONE labelled put site for the count")
    # and the ABSENT path retires label and counts TOGETHER, in one tuple
    absent_block = src[src.index('for k in ("market.competition_geo_label"'):]
    absent_block = absent_block[:absent_block.index(")")]
    self.assertIn('"market.establishments"', absent_block,
                  "the ABSENT path must cover the counts alongside the label")


class BriefAssemblerTests(unittest.TestCase):
  """The brief is the sentence map and nothing else (Nick, 2026-08-30)."""

  def _cat_with(self, keys):
    cat = FactCatalog("d1")
    for k in keys:
      fmt = "text" if any(x in k for x in ("name", "label", "title", "direction", "band", "vs", "scope", "window")) else "count"
      cat.put(k, "x" if fmt == "text" else 1.0, fmt, C.prov_model("t"))
    return cat

  def test_a_section_gets_only_the_keys_its_sentences_need(self):
    from writing_phase.facts import assembler as A
    from writing_phase.facts import sentences as SS
    all_keys = SS.all_required_keys()
    cat = self._cat_with(all_keys)
    asm = A.assemble(cat)
    ops = asm.sections["operations_and_organisation"]
    allowed = set(A.IDENTITY_KEYS)
    for s in SS.sentences_for_section("operations_and_organisation"):
      allowed.update(s["needs"])
    self.assertTrue(set(ops.facts) <= allowed,
                    "ops brief carries keys outside its sentence map: %s"
                    % sorted(set(ops.facts) - allowed))
    self.assertNotIn("quarterly.cash_trough_amount", ops.facts,
                     "a financial-plan key leaked into the ops brief")

  def test_thinness_is_loud_when_a_core_sentence_cannot_fill(self):
    from writing_phase.facts import assembler as A
    from writing_phase.facts import sentences as SS
    core_ids = {s["id"] for s in SS.SENTENCES if s.get("core")}
    self.assertTrue(core_ids, "no core sentences marked")
    keys = set(SS.all_required_keys())
    # remove one key that S36 (ops core) needs
    keys.discard("annual.headcount_y5")
    asm = A.assemble(self._cat_with(sorted(keys)))
    self.assertIn("staffing_and_human_capital", asm.thin_sections)
    st = asm.sections["staffing_and_human_capital"]
    self.assertIn("S36", st.core_unfilled)
    self.assertIn("annual.headcount_y5", st.sentences_unfilled["S36"])

  def test_every_section_with_sentences_has_at_least_one_core(self):
    """A section with no core sentence can never be flagged thin - that is a
    hole in the loudness guarantee, so it is not allowed to happen silently."""
    from writing_phase.facts import sentences as SS
    sections_with = {s["section"] for s in SS.SENTENCES}
    cores = {s["section"] for s in SS.SENTENCES if s.get("core")}
    missing = sections_with - cores
    self.assertEqual(missing, {"funding_request"},
                     "sections without a core anchor: %s (only funding_request "
                     "is allowed - it is conditional and its sentences depend "
                     "on a request existing)" % sorted(missing))


class NarrativeIntoBriefsTests(unittest.TestCase):
  """Nick, 2026-08-30: a section gets the narrative its substance depends on
  and not the rest. A financial narrative must not leak into the ops brief."""

  FAKE_DRAFT = {
    "operating_model_json": {
      "business_description_summary": "A roastery that roasts.",
      "competitive_advantage": "Weekly supply route.",
      "milestones": [{"description": "Reach 50 accounts", "timing": "12 months"}],
      "lob_models": [{"lob_name": "Wholesale", "products": [{"product_name": "Beans"}]}],
      "capacity_driver": "labor", "business_stage": "operating",
    },
    "target_market_json": {"marketing_plan_summary": "Local cafes and grocers."},
    "people_json": {"people": [{"full_name": "Tomas Reyes", "role_title": "Head Roaster",
                                "paragraph": "Tomas has roasted for a decade.",
                                "annual_wage": 61000}]},
    "fulfillment_json": {"delivery": "own van"},
    "financials_json": {"current_revenue": 890000, "cash_on_hand": 48000},
  }

  def _assemble(self):
    from writing_phase.facts import assembler as A
    cat = FactCatalog("d1")
    cat.put("entity.business_name", "X", "text", C.prov_intake("n"))
    return A.assemble(cat, draft=self.FAKE_DRAFT), A

  def test_sections_get_exactly_their_mapped_narratives(self):
    asm, A = self._assemble()
    self.assertEqual(sorted(asm.sections["operations_and_organisation"].narratives),
                     ["fulfillment", "operating_profile"])
    self.assertEqual(sorted(asm.sections["management_team"].narratives), ["people"])
    self.assertEqual(sorted(asm.sections["products_and_services"].narratives),
                     ["lob_products"])
    self.assertIn("marketing_plan_summary", asm.sections["marketing_and_sales"].narratives)
    self.assertEqual(sorted(asm.sections["the_business"].narratives),
                     ["business_description_summary", "competitive_advantage", "milestones"])
    for key, b in asm.sections.items():
      for nk in b.narratives:
        self.assertIn(nk, A.NARRATIVE_MAP.get(key, ()),
                      "%s carries unmapped narrative %s" % (key, nk))

  def test_financial_narrative_cannot_leak_into_the_ops_brief(self):
    import json as _json
    asm, A = self._assemble()
    # planning_context (exec summary) legitimately spans the profiles; every
    # OTHER section's narrative must stay free of raw financial fields.
    for key, b in asm.sections.items():
      if key == "executive_summary":
        continue
      blob = _json.dumps(b.narratives)
      self.assertNotIn("current_revenue", blob,
                       "%s narrative carries financials_json content" % key)
      self.assertNotIn("cash_on_hand", blob)
    ops = asm.sections["operations_and_organisation"]
    self.assertNotIn("marketing_plan_summary", ops.narratives)
    self.assertNotIn("people", ops.narratives,
                     "people paragraphs moved to management_team in map v2")

  def test_wages_stay_out_of_the_people_narrative(self):
    """Numbers travel as facts (rule 17); the narrative carries who people are."""
    import json as _json
    asm, _ = self._assemble()
    mgmt = asm.sections["management_team"]
    self.assertIn("people", mgmt.narratives)
    self.assertNotIn("61000", _json.dumps(mgmt.narratives))

  def test_sections_without_a_grant_get_nothing(self):
    asm, _ = self._assemble()
    self.assertEqual(asm.sections["financial_plan"].narratives, {})
    self.assertEqual(asm.sections["market_and_industry"].narratives, {})


class WriterPayloadTests(unittest.TestCase):
  """Nick's ruling, 2026-08-30: machinery never reaches the writer, finmo goes
  to the body annual, shared block first for caching."""

  DRAFT = {
    "operating_model_json": {"business_naics_6": "311920"},
    "target_market_json": {}, "financials_json": {}, "people_json": {},
    "fulfillment_json": {}, "marketing_schedule_json": {}, "payroll_headcount": {},
    "realism_memo_json": {"MEMO_MARKER_XYZ": 1},
    "model_input_json": {"MODEL_INPUT_MARKER_XYZ": 1},
    "finmo_json": {"contract_version": "v1", "break_even": {"summary": {}},
                   "quarter_rows": [
                     {"quarter_index": q, "revenue": 100.0, "cash": 50.0}
                     for q in range(0, 21)]},
  }

  def test_excluded_payloads_never_reach_the_shared_block(self):
    from writing_phase import payload as PL
    shared = PL.build_shared_block(self.DRAFT)
    self.assertNotIn("MEMO_MARKER_XYZ", shared)
    self.assertNotIn("MODEL_INPUT_MARKER_XYZ", shared)
    self.assertEqual(PL.EXCLUDED_PAYLOADS, ("realism_memo_json", "model_input_json"))

  def test_finmo_body_is_annual_five_plus_break_even(self):
    from writing_phase import payload as PL
    body = PL.finmo_annual_body(self.DRAFT["finmo_json"])
    self.assertEqual(len(body["annual_rows"]), 5)
    self.assertIn("break_even", body)
    self.assertNotIn("quarter_rows", body)
    self.assertEqual(body["annual_rows"][0]["revenue"], 400.0)   # flow: summed
    self.assertEqual(body["annual_rows"][0]["cash"], 50.0)       # balance: year-end
    import json as _json
    self.assertNotIn("quarter_rows", _json.dumps(body))

  def test_shared_block_is_the_identical_prefix_of_every_call(self):
    from writing_phase import payload as PL
    from writing_phase.facts.assembler import SectionBrief
    shared = PL.build_shared_block(self.DRAFT)
    a = PL.build_prompt(shared, PL.build_section_block(SectionBrief("the_business")))
    b = PL.build_prompt(shared, PL.build_section_block(SectionBrief("financial_plan")))
    self.assertTrue(a.startswith(shared) and b.startswith(shared))
    self.assertNotEqual(a, b)


class OmissionByChoiceTests(unittest.TestCase):
  """Nick, 2026-08-31: a client may include or exclude sections - same
  mechanism as the data trigger, different input. Disclosures is locked."""

  def _core(self):
    return [s["key"] for s in R.SECTION_REGISTRY if s["core"]]

  def test_explicit_off_drops_an_omissible_core_section(self):
    from writing_phase import checks as C2
    emitted = [k for k in self._core() if k != "market_and_industry"]
    res = C2.check_section_emission(emitted_sections=emitted, triggers={},
                                    overrides={"market_and_industry": False})
    self.assertTrue(res.passed, res.offenders)

  def test_a_core_section_cannot_vanish_without_an_explicit_choice(self):
    from writing_phase import checks as C2
    emitted = [k for k in self._core() if k != "market_and_industry"]
    res = C2.check_section_emission(emitted_sections=emitted, triggers={}, overrides={})
    self.assertFalse(res.passed)

  def test_disclosures_is_locked_under_every_configuration(self):
    from writing_phase import checks as C2
    self.assertFalse(next(s for s in R.SECTION_REGISTRY if s["key"] == "disclosures")["omissible"])
    emitted = [k for k in self._core() if k != "disclosures"]
    res = C2.check_section_emission(emitted_sections=emitted, triggers={},
                                    overrides={"disclosures": False})
    self.assertFalse(res.passed, "an explicit exclusion must not drop disclosures")

  def test_explicit_on_cannot_conjure_a_conditional_without_its_data(self):
    from writing_phase import checks as C2
    emitted = sorted(self._core() + ["funding_request"],
                     key=lambda k: R.section(k)["order"])
    res = C2.check_section_emission(emitted_sections=emitted,
                                    triggers={"funding_is_sought": False},
                                    overrides={"funding_request": True})
    self.assertFalse(res.passed)

  def test_the_executive_summary_builds_from_present_sections(self):
    spec = R.section("executive_summary")
    self.assertTrue(spec.get("generated_last"))
    self.assertTrue(spec.get("built_from_present_sections"))


class WorkbookManifestTests(unittest.TestCase):
  def test_manifest_covers_every_builder_sheet(self):
    """A new sheet must break this test, never silently miss the manifest."""
    import re as _re, io as _io, glob as _glob
    names = set()
    for f in _glob.glob(os.path.join(ROOT, "client_statements_output_excel", "*.py")):
      names |= set(_re.findall(r'^[A-Z_]+_SHEET = "([^"]+)"',
                               _io.open(f, encoding="utf-8").read(), _re.M))
    manifest = {m["sheet"] for m in R.WORKBOOK_MANIFEST}
    self.assertEqual(sorted(names - manifest), [],
                     "builder sheets missing from WORKBOOK_MANIFEST")

  def test_the_shared_block_carries_manifest_and_instruction(self):
    from writing_phase import payload as PL
    shared = PL.build_shared_block({"finmo_json": {"quarter_rows": []}},
                                   workbook_stamp={"filename": "X.xlsx", "run_id": "r1"})
    self.assertIn("ACCOMPANYING WORKBOOK", shared)
    self.assertIn("accompanying financial model", shared)
    self.assertIn("X.xlsx", shared)


if __name__ == "__main__":
  unittest.main()


class ChartSeriesTests(unittest.TestCase):
  """The series builders behind the approved charts (Nick 2026-08-31): same
  ABSENT discipline as the scalars, provenance on every series."""

  @staticmethod
  def _fake_draft(quarters=20):
    rows = []
    for i in range(1, quarters + 1):
      rows.append({"quarter_index": i, "revenue": 1000.0 + i, "cogs": 400.0,
                   "ebitda": 200.0, "depreciation": 50.0, "net_income": 100.0,
                   "cash": 5000.0 + i})
    ph = {"rows": [
      {"quarter_index": q, "position_title": "Baker", "staffing_class": "supporting_staff",
       "ending_fte": 2.0, "annual_wage": 30000, "oews_occ_code": "51-3011"}
      for q in (4, 8, 12, 16, 20)
    ] + [
      {"quarter_index": q, "position_title": "Owner", "staffing_class": "key_person",
       "ending_fte": 1.0, "annual_wage": 60000}
      for q in (4, 8, 12, 16, 20)
    ]}
    # raw dicts: the builder's _j accepts them, no serialisation needed
    return {"finmo_json": {"quarter_rows": rows}, "payroll_headcount": ph}

  def test_series_built_with_provenance(self):
    from writing_phase.facts.build import build_chart_series
    cat = FactCatalog("d1")
    build_chart_series(cat, self._fake_draft())
    for k in ("annual.revenue_series", "annual.net_income_series",
              "annual.margin_structure_series", "quarterly.cash_balance_series",
              "quarterly.revenue_series", "quarterly.total_cost_series",
              "annual.headcount_by_role_group"):
      f = cat.get(k)
      self.assertIsNotNone(f, "%s must build" % k)
      self.assertTrue(f.provenance.basis, "%s must carry provenance" % k)
    self.assertEqual(len(cat.get("annual.revenue_series").value), 5)
    self.assertEqual(len(cat.get("quarterly.cash_balance_series").value), 20)

  def test_total_cost_is_revenue_less_net_income(self):
    from writing_phase.facts.build import build_chart_series
    cat = FactCatalog("d1")
    build_chart_series(cat, self._fake_draft())
    rev = cat.get("quarterly.revenue_series").value
    cost = cat.get("quarterly.total_cost_series").value
    self.assertAlmostEqual(rev[0] - cost[0], 100.0 * 1, places=2)

  def test_margins_mirror_the_annual_arithmetic(self):
    from writing_phase.facts.build import build_chart_series
    cat = FactCatalog("d1")
    build_chart_series(cat, self._fake_draft())
    m = cat.get("annual.margin_structure_series").value[0]
    rev_y1 = sum(1000.0 + i for i in range(1, 5))
    self.assertAlmostEqual(m["gross"], (rev_y1 - 1600.0) / rev_y1, places=4)
    self.assertAlmostEqual(m["operating"], (800.0 - 200.0) / rev_y1, places=4)

  def test_headcount_grouped_by_title_when_few(self):
    from writing_phase.facts.build import build_chart_series
    cat = FactCatalog("d1")
    build_chart_series(cat, self._fake_draft())
    groups = {g["group"]: g["annual"] for g in cat.get("annual.headcount_by_role_group").value}
    self.assertEqual(set(groups), {"Baker", "Owner"})
    self.assertEqual(groups["Baker"], [2.0] * 5)

  def test_missing_quarters_is_absent_with_reason_never_a_crash(self):
    from writing_phase.facts.build import build_chart_series
    misses = []
    cat = FactCatalog("d1", miss_sink=lambda **kw: misses.append(kw))
    build_chart_series(cat, self._fake_draft(quarters=8))
    self.assertIsNone(cat.get("annual.revenue_series"))
    self.assertTrue(any("20 quarters" in str(m) for m in misses),
                    "the miss log must carry the reason")

  def test_registry_series_requirements_have_a_builder_home(self):
    """Every requires_facts key on every chart is either a known scalar or one
    of the series this turn built - no chart may point at a fact nothing
    produces (the sketch-registry defect, closed 2026-08-31)."""
    built = {"annual.revenue_series", "annual.net_income_series",
             "annual.margin_structure_series", "quarterly.cash_balance_series",
             "quarterly.revenue_series", "quarterly.total_cost_series",
             "annual.headcount_by_role_group", "annual.revenue_by_lob",
             "market.composition", "entity.wage_positioning",
             "industry.sba_amount_distribution", "industry.establishments_history",
             "industry.establishments_history_span",
             # scalars proven in coverage
             "quarterly.cash_trough", "quarterly.cash_trough_amount",
             "quarterly.break_even", "annual.marketing_demand_low",
             "annual.marketing_demand_high", "entity.funding_request",
             "industry.sba_ask_percentile"}
    for c in R.CHART_REGISTRY:
      for k in c["requires_facts"]:
        self.assertIn(k, built, "chart %s requires %s, which nothing builds" % (c["key"], k))
