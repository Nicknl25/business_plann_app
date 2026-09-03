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

  def test_small_counts_render_as_words(self):
    self.assertEqual(C.fmt_count(2), "two")
    self.assertEqual(C.fmt_count(9), "nine")
    self.assertEqual(C.fmt_count(12), "12")
    self.assertEqual(C.fmt_count(1697), "1,697")

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
      "geographic_coverage": "Saint Paul and nearby communities in Ramsey County",
      "primary_growth_lever": "add more wholesale accounts",
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
    # milestones dropped from The Business (Nick 2026-09-01): an unmodelled
    # intake aspiration must not dress as the plan's objective. Coverage and
    # the growth lever granted the same day.
    self.assertEqual(sorted(asm.sections["the_business"].narratives),
                     ["business_description_summary", "competitive_advantage",
                      "geographic_coverage", "primary_growth_lever"])
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
             "industry.sba_ask_percentile",
             # the true CVP (2026-09-01)
             "annual.cvp_fixed_costs_y1", "annual.cvp_cm_ratio_y1",
             "annual.cvp_planned_revenue_y1", "annual.break_even_revenue_y1"}
    for c in R.CHART_REGISTRY:
      for k in c["requires_facts"]:
        self.assertIn(k, built, "chart %s requires %s, which nothing builds" % (c["key"], k))


class RendererAndTableTests(unittest.TestCase):
  """Smoke: every renderer draws real PNG bytes on plausible data; the body
  tables build honestly off the fake model."""

  def test_every_chart_kind_renders_png(self):
    from writing_phase.document import theme as T
    pngs = [
      T.fig_industry_history(list(range(1978, 2024)), [2000 + i * 10 for i in range(46)], entry_year=2021),
      T.fig_local_market_composition([{"label": "A", "establishments": 5, "is_client_line": True},
                                      {"label": "B", "establishments": 3, "is_client_line": False}]),
      T.fig_revenue_by_lob([{"lob": "One", "annual": [10, 11, 12, 13, 14]},
                            {"lob": "Two", "annual": [5, 6, 7, 8, 9]}]),
      T.fig_headcount_by_role([{"group": "Baker", "annual": [2, 2, 3, 3, 4]}]),
      T.fig_wage_positioning([{"role": "Baker", "planned_wage": 30000, "p10": 25000,
                               "p25": 27000, "median": 31000, "p75": 36000, "p90": 42000}]),
      T.fig_revenue_net_income([100, 120, 140, 160, 180], [-5, 2, 8, 12, 15], cagr=0.16),
      T.fig_margin_structure([{"year": y, "gross": 0.6, "operating": 0.1 + y / 100, "net": 0.05}
                              for y in range(1, 6)]),
      T.fig_cash_position([50 - i if i < 6 else 40 + i for i in range(20)], 6, months_cover=2.1),
      T.fig_break_even_cvp([100 + i * 5 for i in range(20)], [110 + i * 3 for i in range(20)],
                           break_even_quarter=6, margin_of_safety=0.17),
      T.fig_sensitivity_band([100, 120, 140, 160, 180], 0.75, 0.90),
      T.fig_break_even_volume(400000, 0.54, 930000, 760000),
      T.fig_break_even_volume(400000, 0.54, 930000, 760000, units=60000, unit_price=15.5),
      T.fig_sba_ask_distribution([{"pct": p, "amount": a} for p, a in
                                  ((10, 15000), (25, 50000), (50, 360000), (75, 600000), (90, 1100000))],
                                 180000, "38th", 1140),
    ]
    self.assertEqual(len(pngs), 13)   # twelve designs, the CVP in both axes
    for png in pngs:
      self.assertTrue(png.startswith(b"\x89PNG"), "renderer must emit PNG bytes")
      self.assertGreater(len(png), 4000)

  def test_sources_and_uses_balances_by_construction(self):
    from writing_phase.document import tables as TB
    rows = []
    for i in range(0, 21):
      rows.append({"quarter_index": i, "cash": 50000.0, "revenue": 100000.0,
                   "cogs": 40000.0, "payroll": 20000.0, "marketing": 2000.0,
                   "lease_rent": 3000.0, "g_and_a": 5000.0, "ebitda": 30000.0,
                   "depreciation": 2000.0, "interest": 1000.0, "taxes": 4000.0,
                   "net_income": 23000.0, "operating_cash_flow": 10000.0,
                   "capital_expenditures": 2000.0, "debt_issuance": 5000.0,
                   "debt_repayment": 3000.0, "lease_principal_repayments": 0.0,
                   "distributions": 0.0, "equity": 0.0, "other_equity": 0.0, "financing_cash_flow": 2000.0,
                   "debt_opening_balance": 50000.0, "debt_closing_balance": 52000.0,
                   "debt_interest_expense_only": 900.0})
    # make the cash identity hold: closing Q4 = opening + Y1 net flows
    rows[0]["cash"] = 30000.0
    net = 30000.0 + 4 * (10000.0 + 5000.0 - 2000.0 - 3000.0)
    rows[4]["cash"] = net
    draft = {"finmo_json": {"quarter_rows": rows}}
    spec = TB.build_sources_and_uses(draft)
    self.assertIsNotNone(spec, "a balanced model must yield the table")
    self.assertIn("Total sources", [r[0] for r in spec["rows"]])

  def test_debt_table_refused_when_no_debt(self):
    from writing_phase.document import tables as TB
    rows = [{"quarter_index": i, "debt_opening_balance": 0.0, "debt_closing_balance": 0.0,
             "debt_issuance": 0.0, "debt_repayment": 0.0, "debt_interest_expense_only": 0.0}
            for i in range(0, 21)]
    self.assertIsNone(TB.build_debt_amortization({"finmo_json": {"quarter_rows": rows}}),
                      "no debt anywhere in the plan means no amortization table")

  def test_condensed_statements_has_the_twelve_lines(self):
    from writing_phase.document import tables as TB
    rows = [{"quarter_index": i, "revenue": 100.0, "cogs": 40.0, "payroll": 20.0,
             "marketing": 2.0, "lease_rent": 3.0, "g_and_a": 5.0, "ebitda": 30.0,
             "depreciation": 2.0, "interest": 1.0, "taxes": 4.0, "net_income": 23.0}
            for i in range(0, 21)]
    spec = TB.build_condensed_statements({"finmo_json": {"quarter_rows": rows}})
    self.assertIsNotNone(spec)
    self.assertEqual(len(spec["rows"]), 12)
    self.assertEqual(spec["rows"][2][0], "Gross profit")
    self.assertEqual(spec["rows"][1][1], "(160)", "costs render in parentheses")


class ThreeStatementTableTests(unittest.TestCase):

  @staticmethod
  def _rows():
    rows = []
    cash = 30000.0
    for i in range(0, 21):
      r = {"quarter_index": i, "cash": cash, "accounts_receivable": 5000.0, "inventory": 2000.0,
           "prepaid_expenses": 0.0, "ppe": 40000.0, "right_of_use_asset": 0.0,
           "accounts_payable": 3000.0, "deferred_revenue": 0.0, "short_term_debt": 1000.0,
           "long_term_debt": 20000.0, "capital_lease_obligation": 0.0,
           "owners_capital": 10000.0, "retained_earnings": 0.0,
           "net_income": 4000.0, "depreciation": 500.0, "changes_in_current_assets": -100.0,
           "changes_in_current_liabilities": 50.0, "operating_cash_flow": 4450.0,
           "capital_expenditures": 200.0, "investing_cash_flow": -200.0,
           "debt_issuance": 0.0, "debt_repayment": 250.0, "lease_principal_repayments": 0.0,
           "distributions": 0.0, "financing_cash_flow": -250.0}
      if i >= 1:
        cash += 4450.0 - 200.0 - 250.0
        r["cash"] = cash
      r["current_assets"] = r["cash"] + 5000.0 + 2000.0
      r["total_assets"] = r["current_assets"] + 40000.0
      r["current_liabilities"] = 3000.0 + 1000.0
      r["total_liabilities"] = r["current_liabilities"] + 20000.0
      r["total_equity"] = r["total_assets"] - r["total_liabilities"]
      r["retained_earnings"] = r["total_equity"] - 10000.0
      r["total_liabilities_and_equity"] = r["total_liabilities"] + r["total_equity"]
      rows.append(r)
    return rows

  def test_balance_sheet_builds_and_all_zero_lines_drop(self):
    from writing_phase.document import tables as TB
    spec = TB.build_balance_sheet({"finmo_json": {"quarter_rows": self._rows()}})
    self.assertIsNotNone(spec)
    labels = [r[0] for r in spec["rows"]]
    self.assertIn("Total assets", labels)
    self.assertNotIn("Deferred revenue", labels, "an all-zero detail line says nothing")
    self.assertIn("Total liabilities & equity", labels)

  def test_balance_sheet_refused_when_it_does_not_balance(self):
    from writing_phase.document import tables as TB
    rows = self._rows()
    rows[8]["total_liabilities_and_equity"] += 5000.0
    self.assertIsNone(TB.build_balance_sheet({"finmo_json": {"quarter_rows": rows}}))

  def test_cash_flow_reconciles_to_year_end_cash(self):
    from writing_phase.document import tables as TB
    spec = TB.build_cash_flow({"finmo_json": {"quarter_rows": self._rows()}})
    self.assertIsNotNone(spec)
    labels = [r[0] for r in spec["rows"]]
    self.assertEqual(labels[-1], "Cash at year end")
    self.assertIn("Debt repaid", labels)
    self.assertNotIn("Debt drawn", labels)
    self.assertEqual(len(TB.BODY_TABLE_BUILDERS), 6)


class WideningRuleTests(unittest.TestCase):
  """Nick 2026-09-01: NAICS coverage is never a data gap. Every builder that
  touches CBP, BDS or the baseline walks 6 -> 4 -> 3 -> sector and the scope
  label travels with the fact into the prose."""

  def test_scopes_widen_in_order_with_labels(self):
    from writing_phase.facts.build import naics_scopes
    class _Cur:
      def execute(self, *a, **k): pass
      def fetchall(self): return []
    scopes = naics_scopes(_Cur(), "111411", "Mushroom Production")
    self.assertEqual([s[0] for s in scopes], [6, 4, 3, 2])
    self.assertEqual(scopes[0][2], "Mushroom Production")
    self.assertIn("mushroom production", scopes[1][2])
    self.assertIn("agriculture", scopes[3][2])

  def test_every_scoped_market_sentence_requires_the_industry_scope_label(self):
    scoped = {"market.establishments", "market.residents_per_establishment",
              "market.client_share_of_establishments", "market.emp_per_establishment",
              "market.payroll_per_establishment", "market.households_per_establishment"}
    for s in S.SENTENCES:
      if set(s["needs"]) & scoped:
        self.assertIn("market.industry_scope_label", s["needs"],
                      "%s counts establishments without saying at what industry scope" % s["id"])

  def test_single_series_revenue_buildup_renders(self):
    from writing_phase.document import theme as T
    png = T.fig_revenue_by_lob([{"lob": "Revenue", "annual": [100, 110, 120, 130, 140]}], basis="total revenue")
    self.assertTrue(png.startswith(b"\x89PNG"))

  def test_time_break_even_renders_without_a_crossing(self):
    from writing_phase.document import theme as T
    png = T.fig_break_even_cvp([100 + i for i in range(20)], [120 + i for i in range(20)], None, margin_of_safety=-0.2)
    self.assertTrue(png.startswith(b"\x89PNG"))


class TheBusinessSectionTests(unittest.TestCase):
  """Nick's rulings of 2026-09-01 for The Business: tenure sentences scoped
  and paired by age, milestones out entirely, a founded-year fact, and a
  producer for R05's client tokens."""

  def test_both_tenure_sentences_exist_and_carry_the_scope_label(self):
    by_id = {s["id"]: s for s in S.SENTENCES}
    for sid, rate_key in (("S11", "industry.first_year_exit_rate"),
                          ("S61", "industry.five_year_survival_rate")):
      s = by_id[sid]
      self.assertEqual(s["section"], "the_business")
      self.assertIn(rate_key, s["needs"])
      self.assertIn("industry.bds_scope_label", s["needs"],
                    "%s states a BDS rate without saying at what scope" % sid)
      self.assertIn("entity.years_operating", s["needs"])

  def test_milestones_are_granted_nowhere(self):
    from writing_phase.facts import assembler as A
    for key, grants in A.NARRATIVE_MAP.items():
      self.assertNotIn("milestones", grants,
                       "%s still grants milestones (dropped 2026-09-01)" % key)
    pool = A.extract_narratives({"operating_model_json": {
      "milestones": [{"description": "Reach 50 accounts", "timing": "12 months"}]}})
    self.assertNotIn("milestones", pool, "milestones still reach the narrative pool")

  def test_founded_year_is_built_from_the_start_date(self):
    from writing_phase.facts import build as B
    class _Cur:
      def execute(self, *a, **k):
        pass
      def fetchone(self):
        return None
    cat = FactCatalog("d1")
    B.build_entity(cat, _Cur(), {"business_name": "Harrow Lane Grooming",
                                 "business_start_date": "2016-05-17"}, {})
    f = cat.get_quiet("entity.founded_year")
    self.assertIsNotNone(f, "founded_year not built")
    self.assertEqual(f.render(), "2016")
    self.assertEqual(cat.get_quiet("entity.founded_month_year").render(), "May 2016")
    self.assertIsNone(cat.get_quiet("entity.milestone_statement"),
                      "milestone fact must NOT exist (Nick 2026-09-01)")

  def test_client_tokens_producer_feeds_r05(self):
    from writing_phase import checks as CK
    draft = {
      "business_name": "Halbrook Grounds Management LLC",
      "people_json": {"people": [{"full_name": "Rafael Ostrowski"}]},
      "operating_model_json": {"geographic_coverage":
        "Overland Park, Lenexa and Olathe (Johnson County, Kansas); United States"},
    }
    toks = CK.client_tokens_for_draft(draft, extra=["Overland Park, Kansas"])
    for expected in ("Halbrook Grounds Management LLC", "Halbrook Grounds Management",
                     "Halbrook", "Rafael Ostrowski", "Ostrowski", "Lenexa", "Olathe"):
      self.assertIn(expected, toks)
    self.assertNotIn("United States", toks, "a generic place is not a client token")
    # and the check actually runs green with it - no more fails-closed day one
    payload = {"sentences": [{"class": "INFERRED",
                              "text": "Halbrook holds its routes inside Johnson County."}]}
    res = CK.check_specificity(payload, client_tokens=toks)
    self.assertTrue(res.executed and res.passed)
    res2 = CK.check_specificity(
      {"sentences": [{"class": "INFERRED",
                      "text": "The company keeps the same crews on the same routes."}]},
      client_tokens=toks)
    self.assertTrue(res2.executed and res2.passed,
                    "a back-reference is legal - rule 15 is a section-level "
                    "rule (Nick 2026-09-02)")
    res3 = CK.check_specificity(
      {"sentences": [{"class": "INFERRED",
                      "text": "Customers value dependable, high-quality service."}]},
      client_tokens=toks)
    self.assertTrue(res3.executed)
    self.assertFalse(res3.passed, "a truly swappable sentence must still fail R05")

  def test_narrative_thinness_is_loud_at_assembly(self):
    from writing_phase.facts import assembler as A
    cat = FactCatalog("d1")
    cat.put("entity.business_name", "X", "text", C.prov_intake("n"))
    # a draft with NO description and NO transcript - the replay-built shape
    asm = A.assemble(cat, draft={"operating_model_json": {"competitive_advantage": "Tight routes."}})
    self.assertIn("the_business", asm.thin_sections)
    self.assertIn("business_description_summary",
                  asm.sections["the_business"].narrative_unfilled)
    self.assertTrue(asm.transcript_absent)
    # with the description present the narrative side goes quiet again
    asm2 = A.assemble(cat, draft={
      "operating_model_json": {"business_description_summary": "A shop that grooms."},
      "messages_json": [{"role": "user", "content": "We groom dogs."}]})
    self.assertNotIn("business_description_summary",
                     asm2.sections["the_business"].narrative_unfilled)
    self.assertFalse(asm2.transcript_absent)
    # no draft supplied = no narrative check; facts-only assemblies stay clean
    asm3 = A.assemble(cat)
    self.assertEqual(asm3.sections["the_business"].narrative_unfilled, [])


class IdentityGuardAndIdentifierTests(unittest.TestCase):
  """Nick 2026-09-01: the n-gram guard cannot see a same-business pair, so
  identity is matched deterministically; and digit-bearing identifiers the
  client stated become facts so the writer never steers around them."""

  A = {"business_name": "Willowbank Animal Hospital", "address_zip": "27615",
       "business_start_date": "11/08/2019",
       "operating_model_json": {"business_naics_6": "541940"},
       "people_json": {"people": [{"full_name": "Dr. Alan Whitfield"}]}}
  B = {"business_name": "Cedarhill Animal Hospital", "address_zip": "27615",
       "business_start_date": "2019-11-08",
       "operating_model_json": {"business_naics_6": "541940"},
       "people_json": {"people": [{"full_name": "Alan Whitfield"}]}}
  D = {"business_name": "Halbrook Grounds Management", "address_zip": "66212",
       "business_start_date": "2020-03-16",
       "operating_model_json": {"business_naics_6": "561730"},
       "people_json": {"people": [{"full_name": "Rafael Ostrowski"}]}}
  E = {"business_name": "Bluestem Grounds P6 Retest", "address_zip": "27601",
       "business_start_date": "04/01/2019",
       "operating_model_json": {"business_naics_6": "561730"},
       "people_json": {"people": [{"full_name": "John Parker"}]}}

  def test_fires_on_the_same_business_across_date_formats_and_titles(self):
    from writing_phase import checks as CK
    v = CK.identity_match(self.A, self.B)
    self.assertTrue(v["fired"], "same owner+date+zip must fire")
    self.assertIn("owner_names", v["matched"])
    self.assertIn("start_date", v["matched"])
    self.assertIn("zip", v["matched"])

  def test_silent_on_two_real_businesses_sharing_only_naics(self):
    from writing_phase import checks as CK
    v = CK.identity_match(self.D, self.E)
    self.assertFalse(v["fired"], "NAICS alone must never fire")
    self.assertEqual(set(v["matched"]) - {"naics"}, set())

  def test_owner_alone_does_not_fire(self):
    from writing_phase import checks as CK
    a = dict(self.A); b = dict(self.B)
    b = {**self.B, "address_zip": "99999", "business_start_date": "01/01/2010"}
    v = CK.identity_match(a, b)
    self.assertFalse(v["fired"], "a serial owner with a new business is not a duplicate")

  def test_stated_certifications_and_coverage_zip_become_facts(self):
    from writing_phase.facts import build as B
    class _Cur:
      def execute(self, *a, **k):
        pass
      def fetchone(self):
        return None
    cat = FactCatalog("d1")
    B.build_entity(cat, _Cur(), {
      "business_name": "Bluestem Grounds P6 Retest",
      "business_start_date": "06/01/2021",
      "operating_model_json": {
        "competitive_advantage": "Tight-tolerance work with AS9100-track quality and ISO 9001 discipline.",
        "geographic_coverage": "Raleigh NC 27615 and nearby communities"}}, {})
    certs = cat.get_quiet("entity.stated_certifications")
    self.assertIsNotNone(certs)
    self.assertEqual(certs.render(), "AS9100, ISO 9001")
    self.assertEqual(cat.get_quiet("entity.coverage_zip").render(), "27615")

  def test_a_token_from_the_business_name_is_never_a_certification(self):
    from writing_phase.facts import build as B
    class _Cur:
      def execute(self, *a, **k):
        pass
      def fetchone(self):
        return None
    cat = FactCatalog("d1")
    B.build_entity(cat, _Cur(), {
      "business_name": "Apex AB1234 Logistics",
      "operating_model_json": {
        "competitive_advantage": "AB1234 Logistics runs its own fleet."}}, {})
    self.assertIsNone(cat.get_quiet("entity.stated_certifications"),
                      "the business's own name must not extract as a certification")

  def test_the_depth_facts_of_the_stated_today_position(self):
    """Nick 2026-09-02: ten facts in, four numbers out was the depth gap.
    Revenue per person, cash and debt today are computed by Python."""
    from writing_phase.facts import build as B
    class _Cur:
      def execute(self, *a, **k):
        pass
      def fetchone(self):
        return None
    cat = FactCatalog("d1")
    B.build_entity(cat, _Cur(), {
      "business_name": "Halbrook Grounds Management",
      "business_start_date": "2020-03-16",
      "financials_json": {"current_revenue": 1400000.0, "current_num_employees": 12,
                          "cash_on_hand": 145000.0, "total_debt_outstanding": 180000.0}}, {})
    self.assertEqual(cat.get_quiet("entity.stated_revenue_per_employee").render(), "$117,000")
    self.assertEqual(cat.get_quiet("entity.stated_cash_on_hand").render(), "$145,000")
    self.assertEqual(cat.get_quiet("entity.stated_debt_outstanding").render(), "$180,000")
    self.assertEqual(cat.get_quiet("entity.founded_month_year").render(), "March 2020")
    # zero debt is words, not a figure - the fact stays absent
    cat2 = FactCatalog("d2")
    B.build_entity(cat2, _Cur(), {"business_name": "X",
      "financials_json": {"current_revenue": 100000, "current_num_employees": 0,
                          "total_debt_outstanding": 0}}, {})
    self.assertIsNone(cat2.get_quiet("entity.stated_debt_outstanding"))
    self.assertIsNone(cat2.get_quiet("entity.stated_revenue_per_employee"))


  def test_observation_floor_and_tenure_fact_pruning(self):
    """Nick 2026-09-02: observations are a FLOOR - every one that resolves
    must arrive - and the wrong-age tenure FACT leaves the brief entirely."""
    from writing_phase import author as AU
    from writing_phase import payload as PL
    from writing_phase.facts.assembler import SectionBrief
    brief = SectionBrief("the_business", facts={
      "entity.business_name": {"rendered": "X"},
      "entity.stated_current_revenue": {"rendered": "$1.4 million"},
      "entity.stated_employees": {"rendered": "12"},
      "industry.five_year_survival_rate": {"rendered": "52.3%"},
      "industry.bds_scope_label": {"rendered": "the services industry"},
      "entity.years_operating": {"rendered": "7th"},
    })
    covered = {"section_key": "the_business", "sentences": [
      {"text": "It holds {{fact:entity.stated_current_revenue}} in trailing revenue "
               "with {{fact:entity.stated_employees}} people."},
      {"text": "In {{fact:industry.bds_scope_label}}, "
               "{{fact:industry.five_year_survival_rate}} survive five years; it is in "
               "its {{fact:entity.years_operating}} year."}], "notes": []}
    res = AU.observation_floor_check(covered, brief, exclude_sentence_ids=("S11",))
    self.assertTrue(res.passed, "covered observations must pass: %s" % res.offenders)
    dropped = {"section_key": "the_business", "sentences": [
      {"text": "In {{fact:industry.bds_scope_label}}, "
               "{{fact:industry.five_year_survival_rate}} survive five years; it is in "
               "its {{fact:entity.years_operating}} year."}], "notes": []}
    res2 = AU.observation_floor_check(dropped, brief, exclude_sentence_ids=("S11",))
    self.assertFalse(res2.passed, "dropping the resolved S48 must fail the floor")
    self.assertTrue(any("S48" in o for o in res2.offenders))
    block = PL.build_section_block(brief, exclude_sentence_ids=("S11",),
                                   exclude_fact_keys=("industry.first_year_exit_rate",))
    self.assertNotIn("first_year_exit_rate", block,
                     "the wrong-age tenure fact must leave the brief entirely")
    self.assertIn("MUST COVER", block)
    self.assertNotIn('"template"', block,
                     "sentence templates must not ship to the writer (Nick 2026-09-02)")
    # the tenure floor now demands the RATE itself, not any-of
    res4 = AU.observation_floor_check(
      {"section_key": "the_business", "sentences": [
        {"text": "It is in its {{fact:entity.years_operating}} year."},
        {"text": "It holds {{fact:entity.stated_current_revenue}} with "
                 "{{fact:entity.stated_employees}} people."}], "notes": []},
      brief, exclude_sentence_ids=("S11",))
    self.assertFalse(res4.passed, "tenure without the rate must fail the floor")
    self.assertTrue(any("five_year_survival_rate" in o for o in res4.offenders))


  def test_scope_label_is_words_when_the_master_has_a_title(self):
    """Nick 2026-09-02: never print a NAICS code - the label is the industry
    in words at the level the data was drawn at."""
    from writing_phase.facts.build import naics_scopes
    class _Cur:
      def execute(self, sql, params=None):
        self._p = (params or [""])[0]
      def fetchall(self):
        return []
      def fetchone(self):
        return {"5617": ("Services to Buildings and Dwellings",),
                "561": ("Administrative and Support Services",)}.get(self._p)
    scopes = naics_scopes(_Cur(), "561730", "Landscaping Services")
    # Nick 2026-09-02: the NAICS-4 title is a code wearing words - anchor on
    # the client's own trade and say the data is drawn wider
    self.assertEqual(scopes[1][2], "the trade group that includes landscaping services")
    self.assertEqual(scopes[2][2], "the broader trade group that includes landscaping services")
    for lvl, _, label in scopes:
      if lvl != 6:
        self.assertNotIn("NAICS", label)


