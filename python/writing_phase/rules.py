"""THE WRITING-PHASE RULE SET — the single door (2026-08-30).

Every rule the writing phase obeys lives HERE, once. Section modules, the
prompt builder and the verifier all import from this module; none of them
carries a rule of its own. `tests/test_writing_phase_rules.py` fails if a
writing-phase module states a rule this file does not, so a later section
cannot regress the standard without going red. Same shape as
client_statements_output_excel/design.py, which has held the workbook's visual
standard the same way since 2026-08-19.

WHY A DB TABLE AS WELL (see rule_lookup.py): each rule below carries BOTH the
instruction GPT is given AND the parameters its check runs on. They are seeded
into `writing_phase_rule_lookup` as one row, exactly as
post_intake_gpt_contract_lookup (157 rows) already does for the payroll
contract. A rule written into a prompt string and checked by separate code
drifts the first time someone edits one and not the other; a rule that IS one
row cannot. The lesson underneath that: the payroll contract row sat inert
through four live reruns because its seeder had not run, so the seed is
verified live rather than assumed.

WHAT THIS MODULE MUST NEVER DO: write prose, call GPT, render a chart, or
touch a document. It states rules and checks them. It does not author.

ENFORCEMENT VOCABULARY (deliberately small, and honest):
  hard   - mechanically enforced; a section cannot pass without it.
  proxy  - a measurable stand-in for a judgment. Catches crude failures,
           not competent boring writing. Nick's review is the real defence.
  soft   - no machine holds this. Named so nobody believes otherwise.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

RULE_SET_VERSION = "writing_rules_v1"

# ---------------------------------------------------------------------------
# OUTPUT + GATE
# ---------------------------------------------------------------------------
# Nick 2026-08-30 ruling H: the two folders differ in spelling and BOTH STAY.
# The workbook path's misspelling is long-standing; do not "fix" either to
# match the other.
WORKBOOK_OUTPUT_DIR = r"C:\dev\Cilient Plans"          # sic - leave it
PLAN_OUTPUT_DIR = r"C:\dev\Client Written Plans"

# Same naming convention as the workbooks: "<Business Name> -- MM-DD-YYYY HH-MM-SS"
PLAN_FILENAME_FORMAT = "{business_name} -- {stamp}.docx"
PLAN_FILENAME_STAMP_FORMAT = "%m-%d-%Y %H-%M-%S"

# THE GATE. No passed run, no plan. Resolved on the draft's AUTHORITATIVE run
# (intake_consult_drafts.planning_run_id, which after a rescue IS the rescued
# row), never on run_status alone: Nine Fathom 10a81085 carried
# run_status='completed' with passed=False and still produced a delivered
# workbook. A request row is a hint; this condition is the authority.
GATE_REQUIRES = {
  "run_status": "completed",
  "acceptance_verdict_json_passed": True,
  "checks_expected": 18,
}


# ---------------------------------------------------------------------------
# RULE 14 - THE THREE SENTENCE CLASSES
# ---------------------------------------------------------------------------
CLASS_GROUNDED = "GROUNDED"
CLASS_INFERRED = "INFERRED"
CLASS_FRAMING = "FRAMING"
SENTENCE_CLASSES = (CLASS_GROUNDED, CLASS_INFERRED, CLASS_FRAMING)

# Nick's ruling F (2026-08-30): three-class REPLACES the approved two-lane
# density guard of 2026-08-18 (Lane-A >=70% / Lane-B <=30%). These numbers are
# PROVISIONAL by his instruction - tune on the first ten real plans and report
# what the real distribution looks like before treating them as settled.
DENSITY_GUARD = {
  CLASS_GROUNDED: {"min_share": 0.55, "max_share": None},
  CLASS_INFERRED: {"min_share": None, "max_share": 0.30},
  CLASS_FRAMING: {"min_share": None, "max_share": 0.15},
}
DENSITY_GUARD_PROVISIONAL = True
DENSITY_GUARD_TUNE_AFTER_PLANS = 10

# Per-class obligations. These ARE the checks; checks.py reads them.
CLASS_RULES = {
  CLASS_GROUNDED: {
    "must_resolve_fact_tokens": True,   # every number is a {{fact:...}} token
    "may_introduce_number": False,      # ...so it never introduces one itself
    "requires_note_kind": "SOURCE",     # where it bears weight
    "exempt_from_swap_test": False,
  },
  CLASS_INFERRED: {
    "must_resolve_fact_tokens": True,
    # Nick's ruling B (2026-08-30), CONFIRMED AS INTENDED: inference is
    # QUALITATIVE unless Python pre-computed the number into the brief.
    # "roughly 40 competing roasters" is banned as an inferred sentence.
    "may_introduce_number": False,
    "requires_note_kind": "BASIS",
    "exempt_from_swap_test": False,
  },
  CLASS_FRAMING: {
    # Nick's ruling A (2026-08-30): FRAMING STAYS and is EXEMPT from the
    # competitor-swap test - it is connective tissue, not filler. The cap in
    # DENSITY_GUARD is what stops it becoming filler, not the swap test.
    "must_resolve_fact_tokens": False,
    "may_introduce_number": False,
    "forbids_digits": True,
    "forbids_proper_nouns": True,
    "forbids_citations": True,
    "requires_note_kind": None,
    "exempt_from_swap_test": True,
  },
}

# THE RESIDUAL RISK, accepted by Nick 2026-08-30 and recorded so it is never
# mistaken for a solved problem: GROUNDED and FRAMING are tightly checkable.
# INFERRED is checkable only for NUMBERS. A false qualitative claim labelled
# INFERRED - "the regional market rewards single-origin sourcing" - passes
# every mechanical check in this file. Sampled human review is the defence.
INFERRED_QUALITATIVE_ESCAPE_HATCH = True


# ---------------------------------------------------------------------------
# RULE 18 - FACT NAMESPACES (annual body, quarterly workbook/appendix/charts)
# ---------------------------------------------------------------------------
# The body tells a five-year story. Enforcement is a NAMESPACE rule rather than
# a prose rule: a body sentence may only reference facts the namespace allows,
# so "no quarterly detail in the narrative" is checked, not trusted.
NS_ANNUAL = "annual"
NS_QUARTERLY = "quarterly"
NS_ENTITY = "entity"
NS_INDUSTRY = "industry"
NS_MARKET = "market"
# economy.* (Nick, 2026-08-31): rule 7 says no plan ignores its economic
# context, and one inferred clause was the whole appearance. FRED macro and
# the valuation constants' Treasury rate live here - woven into the Basis of
# Projections, the funding comparables and the rate-risk clause, never a
# macro lecture.
NS_ECONOMY = "economy"
FACT_NAMESPACES = (NS_ANNUAL, NS_QUARTERLY, NS_ENTITY, NS_INDUSTRY, NS_MARKET, NS_ECONOMY)

BODY_ALLOWED_NAMESPACES = (NS_ANNUAL, NS_ENTITY, NS_INDUSTRY, NS_MARKET, NS_ECONOMY)

# The two exceptions Nick named, written as SENTENCES and never as body charts
# of their own: the cash trough and break-even. These are the only quarterly
# keys a body sentence may reference.
BODY_QUARTERLY_EXCEPTIONS = (
  "quarterly.cash_trough",          # the quarter
  "quarterly.cash_trough_amount",   # the cash at that quarter - same exception, same sentence
  "quarterly.break_even",
)

APPENDIX_ALLOWED_NAMESPACES = FACT_NAMESPACES  # full 20-quarter statements

# Nick's quarterly-chart ruling (2026-08-30): "The annual rule governs the
# narrative, not the visuals. A cash-trough chart that can't show the trough is
# pointless." Charts may use quarterly series; prose stays annual.
CHARTS_MAY_USE_QUARTERLY = True


# ---------------------------------------------------------------------------
# RULE 16 - NUMBER STYLE (one formatter owns every render)
# ---------------------------------------------------------------------------
# GPT never emits a number. It emits {{fact:key}}; Python renders it. That one
# decision enforces rules 6, 16 and 17 by construction - the same quantity is
# written identically everywhere because it is the same function call. The
# token mechanism is not new: fact_templates.py has carried it on the intake
# side since CW-018 (_FACT_PATTERN, is_allowed_fact_key, sanitize_fact_template).
NUMBER_STYLE = {
  "prose_exact_below": 10_000,          # under $10,000 -> exact
  "prose_round_to_nearest": 1_000,      # above -> nearest thousand
  "prose_millions_written_out": True,   # "$1.4 million"
  "millions_threshold": 1_000_000,
  "percent_decimals_when_meaningful": 1,
  "percent_decimals_default": 0,
  "tables_always_exact": True,
  "appendix_always_exact": True,
  # No range where a figure exists; no "approximately" on a grounded number.
  # This is coherent only because INFERRED may not carry numbers at all
  # (ruling B) - otherwise the two rules would fight.
  "forbid_range_when_figure_exists": True,
  "forbid_hedge_on_grounded_number": True,
}

HEDGE_WORDS = (
  "approximately", "roughly", "around", "about", "circa", "some",
  "in the region of", "or so", "give or take", "ballpark", "estimated at",
)


# ---------------------------------------------------------------------------
# FORBIDDEN LANGUAGE (rules 3, 4, 11, 15)
# ---------------------------------------------------------------------------
# RULE 3 - never tell a reader something was unavailable. Infer, or say
# nothing. Nick's ruling C (2026-08-30): this check runs over the NOTES as well
# as the prose, because "based on industry norms, as local counts were
# unavailable" breaks rule 3 inside a BASIS note.
FORBIDDEN_ABSENCE_PHRASES = (
  "not available", "unavailable", "no data", "data was not", "data is not",
  "not provided", "not disclosed", "unknown", "insufficient data",
  "we were unable", "could not be determined", "no information",
  "lack of data", "limited data", "n/a", "not applicable", "not reported",
  "absent from", "missing from our", "was not captured", "not captured",
)

# RULE 4 - no machinery. The document is not a course in financial modelling.
# The ONLY place forecast-as-forecast language is legal is the Basis of
# Projections paragraph (rule 19), which is why the exception is span-scoped
# rather than word-scoped.
FORBIDDEN_MACHINERY_TERMS = (
  "finmo", "model_input", "finmo_json", "the model", "our model", "the engine",
  "the solver", "solver", "derived by", "the system computed", "the algorithm",
  "quarter grid", "post-intake", "intake", "gpt", "llm", "prompt",
  "the pipeline", "backend", "database", "our database", "the dataset",
  "was calculated by", "the calculation", "we modelled", "we modeled",
)
MACHINERY_EXCEPTION_SPANS = ("basis_of_projections",)

# RULE 11 - never "GPT determined".
FORBIDDEN_ATTRIBUTION_PHRASES = (
  "gpt determined", "gpt found", "ai determined", "the ai", "generated by",
  "our analysis engine", "automatically determined",
)

# RULE 15 - third person, business-named. "Redbrook Coffee Roasters
# operates..." Not we, not you.
FORBIDDEN_PRONOUNS = ("we", "our", "ours", "us", "you", "your", "yours")


# ---------------------------------------------------------------------------
# RULE 11 - SOURCES & NOTES
# ---------------------------------------------------------------------------
NOTE_KIND_SOURCE = "SOURCE"
NOTE_KIND_BASIS = "BASIS"
NOTE_KINDS = (NOTE_KIND_SOURCE, NOTE_KIND_BASIS)

# A SOURCE note must carry a source AND a vintage. Nick's ruling E
# (2026-08-30), which follows directly from the 2026-08-29 data inventory:
# post_intake_industry_baseline_lookup (47,700 active rows) is the ONLY table
# carrying data_source / source_year / sample_size / confidence_tier per value.
# Anything sourced outside it CANNOT produce a compliant SOURCE note and must
# be INFERRED with a BASIS note instead. A mushroom farm's market section
# degrades to inference - and never says why (rule 3).
SOURCE_NOTE_REQUIRES = ("source_name", "source_vintage")
SOURCE_OF_RECORD_TABLE = "post_intake_industry_baseline_lookup"

NOTES_SECTION_TITLE = "Sources & Notes"
NOTES_SECTION_FOLLOWS = "appendix"


# ---------------------------------------------------------------------------
# RULES 12/13 - SECTION REGISTRY (fixed structure, sections that come and go)
# ---------------------------------------------------------------------------
# Core sections ALWAYS appear - thin data makes a SHORTER section, never a
# missing one. Conditional sections appear on their trigger. Numbering and the
# TOC are COMPUTED from what is emitted, never authored, so a plan can never
# read 1,2,3,4,5,6,8,9.
SECTION_REGISTRY: Tuple[Dict[str, Any], ...] = (
  # `core`: appears unless the CLIENT switches it off. `trigger`: a data
  # condition for conditional sections. `omissible`: whether an explicit
  # client choice may exclude it - Disclosures is locked under every
  # configuration (Nick, 2026-08-31). Emission =
  #   (core or trigger fired) and not explicitly OFF, locked ignores OFF.
  # An explicit ON cannot conjure a conditional section whose data condition
  # does not hold - there would be nothing true to write in it.
  {"key": "executive_summary", "title": "Executive Summary",
   "core": True, "trigger": None, "order": 10, "omissible": True,
   "pages_min": 1, "pages_max": 2, "generated_last": True,
   # written FROM WHATEVER SECTIONS ARE PRESENT, never assuming all of them
   "built_from_present_sections": True},
  {"key": "the_business", "title": "The Business",
   "core": True, "trigger": None, "order": 20, "omissible": True,
   "pages_min": 1, "pages_max": 2},
  {"key": "market_and_industry", "title": "Market & Industry",
   "core": True, "trigger": None, "order": 30, "omissible": True,
   "pages_min": 3, "pages_max": 4},
  {"key": "competitive_landscape", "title": "Competitive Landscape",
   "core": True, "trigger": None, "order": 40, "omissible": True,
   "pages_min": 1, "pages_max": 2},
  {"key": "products_and_services", "title": "Products & Services",
   "core": True, "trigger": None, "order": 50, "omissible": True,
   "pages_min": 2, "pages_max": 3,
   "per_line_subsections": True},
  {"key": "marketing_and_sales", "title": "Marketing & Sales",
   "core": True, "trigger": None, "order": 60, "omissible": True,
   "pages_min": 1, "pages_max": 2},
  {"key": "operations_and_organisation", "title": "Operations",
   "core": True, "trigger": None, "order": 70, "omissible": True,
   "pages_min": 1, "pages_max": 2},
  # Management Team stays its own section (Nick, 2026-08-31): a lender reads
  # the team page on its own; a decade of experience is not buried under a
  # hiring ramp.
  {"key": "management_team", "title": "Management Team",
   "core": True, "trigger": None, "order": 80, "omissible": True,
   "pages_min": 1, "pages_max": 2},
  {"key": "staffing_and_human_capital", "title": "Staffing & Human Capital",
   "core": True, "trigger": None, "order": 90, "omissible": True,
   "pages_min": 1, "pages_max": 2},
  {"key": "risks_and_mitigations", "title": "Risks & Mitigations",
   "core": True, "trigger": None, "order": 100, "omissible": True,
   "pages_min": 1, "pages_max": 2},
  {"key": "funding_request", "title": "Funding Request & Use of Funds",
   "core": False, "trigger": "funding_is_sought", "order": 110, "omissible": True,
   "pages_min": 1, "pages_max": 2},
  {"key": "financial_plan", "title": "Financial Plan",
   "core": True, "trigger": None, "order": 120, "omissible": True,
   "pages_min": 4, "pages_max": 6,
   "opens_with_span": "basis_of_projections",
   # the four fixed subsections (map v2): basis / assumptions / forecast /
   # sensitivity, closing with the valuation reference paragraph
   "fixed_subsections": ("basis_of_projections", "assumptions", "forecast", "sensitivity")},
  {"key": "disclosures", "title": "Disclosures",
   "core": True, "trigger": None, "order": 130, "omissible": False,   # LOCKED
   "pages_min": 1, "pages_max": 1},
  {"key": "appendix", "title": "Appendix",
   "core": True, "trigger": None, "order": 140, "omissible": False,
   "pages_min": None, "pages_max": None,
   "landscape": True},
  {"key": "sources_and_notes", "title": NOTES_SECTION_TITLE,
   "core": True, "trigger": None, "order": 150, "omissible": False,
   "pages_min": None, "pages_max": None},
)

# The six PART headings (presentational grouping, adopted 2026-08-31):
PART_HEADINGS = (
  ("The Business", ("executive_summary", "the_business")),
  ("The Market", ("market_and_industry", "competitive_landscape")),
  ("Strategy", ("products_and_services", "marketing_and_sales")),
  ("Operations", ("operations_and_organisation", "management_team", "staffing_and_human_capital")),
  ("The Financials", ("risks_and_mitigations", "funding_request", "financial_plan", "disclosures")),
  ("Record", ("appendix", "sources_and_notes")),
)

# RULE 20 - PROPORTION. Targets, not truncation: out-of-band FLAGS a section
# for review, it never cuts it.
BODY_PAGES_MIN = 16
BODY_PAGES_MAX = 28
PROPORTION_IS_ADVISORY = True   # never truncates. Ever.


# ---------------------------------------------------------------------------
# RULE 8 - CHART REGISTRY (approved as proposed, 2026-08-30)
# ---------------------------------------------------------------------------
# Same chart types in the same places in every plan. One theme module will own
# colour, type and grid so every chart in every plan is visually identical in
# style - the design.py lesson, applied to matplotlib.
#
# Nick's addition (2026-08-30): A CHART WHOSE DATA DOES NOT EXIST IS OMITTED
# SILENTLY AND THE FIGURES RENUMBER. The section never references a figure that
# is not there, and never explains its absence. That is rule 3 applied to
# visuals, and it means figure numbers are COMPUTED from what was emitted -
# never authored, exactly like section numbers.
PLACEMENT_FULL_WIDTH = "full_width"
PLACEMENT_WRAP = "wrap"     # chart sits beside prose, text wraps

CHART_REGISTRY: Tuple[Dict[str, Any], ...] = (
  {"key": "revenue_by_lob", "order": 10,
   "title": "Revenue by Line of Business",
   "section": "market_and_industry", "kind": "stacked_column",
   "namespace": NS_ANNUAL, "placement": PLACEMENT_FULL_WIDTH,
   "requires_facts": ("annual.revenue_by_lob",)},
  {"key": "local_market_composition", "order": 20,
   "title": "Local Market Composition",
   "section": "market_and_industry", "kind": "horizontal_bar",
   "namespace": NS_MARKET, "placement": PLACEMENT_WRAP,
   "requires_facts": ("market.composition",)},
  {"key": "revenue_and_net_income", "order": 30,
   "title": "Revenue and Net Income",
   "section": "financial_plan", "kind": "column_line_combo",
   "namespace": NS_ANNUAL, "placement": PLACEMENT_FULL_WIDTH,
   "requires_facts": ("annual.revenue", "annual.net_income")},
  {"key": "margin_structure", "order": 40,
   "title": "Margin Structure",
   "section": "financial_plan", "kind": "line",
   "namespace": NS_ANNUAL, "placement": PLACEMENT_WRAP,
   "requires_facts": ("annual.gross_margin", "annual.operating_margin",
                      "annual.net_margin")},
  {"key": "cash_position", "order": 50,
   "title": "Cash Position",
   "section": "financial_plan", "kind": "area_with_annotation",
   # QUARTERLY by Nick's ruling - the trough is a quarterly event and a chart
   # that cannot show it is pointless.
   "namespace": NS_QUARTERLY, "placement": PLACEMENT_FULL_WIDTH,
   "requires_facts": ("quarterly.cash_balance", "quarterly.cash_trough")},
  {"key": "break_even", "order": 60,
   "title": "Break-Even Analysis",
   "section": "financial_plan", "kind": "cvp",
   "namespace": NS_QUARTERLY, "placement": PLACEMENT_FULL_WIDTH,
   "requires_facts": ("quarterly.revenue", "quarterly.total_cost",
                      "quarterly.break_even")},
  {"key": "sources_and_uses", "order": 70,
   "title": "Sources and Uses of Capital",
   "section": "funding_request", "kind": "waterfall",
   "namespace": NS_ENTITY, "placement": PLACEMENT_WRAP,
   "requires_facts": ("entity.sources_and_uses",)},
  {"key": "industry_establishments_history", "order": 25,
   "title": "Establishments in the Industry Since NAME_YEAR",
   "section": "market_and_industry", "kind": "line",
   "namespace": NS_INDUSTRY, "placement": PLACEMENT_FULL_WIDTH,
   # 46 years of BDS nobody has touched (depth item 4). Omitted silently
   # where BDS lacks the NAICS - the mushroom farm never sees a gap.
   "requires_facts": ("industry.establishments_history_span",)},
  {"key": "headcount_by_role", "order": 80,
   "title": "Headcount by Role Group",
   "section": "staffing_and_human_capital", "kind": "stacked_area",
   "namespace": NS_ANNUAL, "placement": PLACEMENT_WRAP,
   "requires_facts": ("annual.headcount_by_role_group",)},
)

CHART_CAPTION_FORMAT = "Figure {number} — {title}"
CHART_MUST_BE_CROSS_REFERENCED = True   # rule 22: referenced by number in text
CHART_OMITTED_SILENTLY_WHEN_DATA_ABSENT = True   # Nick 2026-08-30


# ---------------------------------------------------------------------------
# RULES 21/22/23 - DOCUMENT CRAFT
# ---------------------------------------------------------------------------
DOCUMENT_CRAFT = {
  "body_font_family": "serif",
  "body_font_size_pt": 11,
  "heading_font_family": "sans-serif",
  "one_font_pair_only": True,
  "use_real_word_styles": True,       # never manually formatted bold
  "forbid_direct_run_formatting": True,
  "section_breaks_between_majors": True,
  "running_header": "business_name",
  "page_numbers_in_footer": True,
  "one_table_style": True,
  "table_numbers_right_aligned": True,
  "table_subtle_banding": True,
  "table_heavy_gridlines": False,
  "charts_embedded_as_images": True,
  "appendix_landscape": True,
  # rule 23 NARROWED (Nick, 2026-08-30): ban text boxes and ABSOLUTELY
  # POSITIONED shapes; PERMIT anchored images with square or tight wrap -
  # those flow with their paragraph and don't fight an editor, which is what
  # the rule was protecting. Wrapping stays a PER-CHART decision in the chart
  # registry (placement: wrap | full_width), never a global one.
  "forbid_text_boxes": True,
  "forbid_absolutely_positioned": True,
  "allow_anchored_wrapped_images": True,
}

FOOTER_FORMAT = "Confidential · Page {page} of {pages} · Prepared {month_year} · v{version}"
FOOTER_VERSION = "1.0"
# No UUID on a client-facing page. The run identifier goes in the appendix.
RUN_ID_LOCATION = "appendix"
RUN_ID_FORBIDDEN_IN = ("footer", "header", "body")


# ---------------------------------------------------------------------------
# THE WORKBOOK MANIFEST (2026-08-31). The client receives both artifacts, side
# by side. This is everything the writer knows about the model: what each
# sheet is, what a client can change on it, and what lives only there. STATIC
# by design - part of the byte-identical cached shared block - with a tiny
# per-draft stamp added at generation time (filename + run id).
# tests/test_writing_phase_rules.py pins this against the builder's *_SHEET
# constants so a new sheet breaks a test instead of silently missing here.
# ---------------------------------------------------------------------------
WORKBOOK_MANIFEST: Tuple[Dict[str, str], ...] = (
  {"sheet": "Cover", "purpose": "identity page", "editable": "", "only_there": ""},
  {"sheet": "Dashboard", "purpose": "KPIs and headline charts", "editable": "", "only_there": "the at-a-glance view"},
  {"sheet": "FINMO", "purpose": "full quarterly three-statement model with ratios", "editable": "",
   "only_there": "quarterly detail beyond the appendix; the ratio suite"},
  {"sheet": "Valuation", "purpose": "discounted-cash-flow the reader can audit; every input labeled grounded or assumption with its source", "editable": "the assumption block",
   "only_there": "the full valuation walk and its sensitivity grid"},
  {"sheet": "Revenue Drivers", "purpose": "capacity x price x utilization per line", "editable": "", "only_there": ""},
  {"sheet": "Model Inputs", "purpose": "every lever feeding the model", "editable": "the highlighted input cells", "only_there": "the what-if capability"},
  {"sheet": "Payroll Schedule", "purpose": "per-role, per-quarter staffing", "editable": "starting FTE, hires, wages, benefits percent", "only_there": "per-quarter staffing detail"},
  {"sheet": "Debt Schedule", "purpose": "debt and lease amortization", "editable": "new borrowing, rate, term, extra principal", "only_there": "per-quarter amortization"},
  {"sheet": "CapEx Depreciation", "purpose": "PPE chain", "editable": "capital expenditure", "only_there": ""},
  {"sheet": "Working Capital", "purpose": "receivable, payable and inventory drivers", "editable": "the driver rows", "only_there": ""},
  {"sheet": "Cash Equity Schedule", "purpose": "owner capital and distributions", "editable": "all three rows", "only_there": ""},
  {"sheet": "Marketing Schedule", "purpose": "customers, acquisition cost and retention", "editable": "retention, purchases per customer, acquisition cost", "only_there": ""},
  {"sheet": "Model Inputs", "purpose": "", "editable": "", "only_there": ""},
  {"sheet": "Checks", "purpose": "the model's own consistency checks", "editable": "", "only_there": "the audit trail"},
  {"sheet": "Audit Source", "purpose": "provenance", "editable": "", "only_there": ""},
  {"sheet": "Calc", "purpose": "supporting calculation", "editable": "", "only_there": ""},
  {"sheet": "Diagnostics", "purpose": "build diagnostics", "editable": "", "only_there": ""},
)

WORKBOOK_REFERENCE_INSTRUCTION = (
  "The client receives a financial model workbook alongside this document. "
  "Refer to it as 'the accompanying financial model'. Direct the reader to it "
  "for quarterly detail, the valuation walk, and what-if changes - for "
  "example, assumptions can be adjusted on its Model Inputs sheet. Sheet "
  "NAMES are client-facing vocabulary; cell mechanics are machinery and stay "
  "out of the prose. Never quote a figure from the workbook that is not in "
  "your brief. The two artifacts are built from the same model run and must "
  "never be described as differing.")


# ---------------------------------------------------------------------------
# RULE 19 - BASIS OF PROJECTIONS
# ---------------------------------------------------------------------------
BASIS_OF_PROJECTIONS = {
  "span_key": "basis_of_projections",
  "section": "financial_plan",
  "position": "opens_section",
  "required": True,
  "max_occurrences": 1,          # not a disclaimer wall, not repeated
  "max_paragraphs": 1,
}


# ---------------------------------------------------------------------------
# RULES 2/12 - BOILERPLATE EXEMPTION FOR THE SIMILARITY CHECK
# ---------------------------------------------------------------------------
# Nick's ruling D (2026-08-30): registered boilerplate spans are EXEMPT from
# the cross-plan similarity check. Fixed structure, a fixed footer and a fixed
# basis paragraph mean some text is identical across plans BY DESIGN; without
# this exemption the check fires on our own template.
BOILERPLATE_SPANS = (
  "footer",
  "running_header",
  "basis_of_projections",
  "disclosures_standing_text",
  "notes_section_heading",
  "toc",
)

SIMILARITY_GUARD = {
  "ngram_size": 8,
  "max_overlap_share": 0.15,      # vs prior plans in the same NAICS
  "compare_within": "naics_6",
  "exempt_spans": BOILERPLATE_SPANS,
  "provisional": True,            # tune with the density guard
}


# ---------------------------------------------------------------------------
# THE RULES THEMSELVES
# ---------------------------------------------------------------------------
# Each row carries the instruction GPT is given AND the check that holds it.
# `check` names a callable in checks.py; None means no machine holds this and
# the enforcement column says so. `failure_code` is what the verifier reports.
WRITING_RULES: Tuple[Dict[str, Any], ...] = (
  {"id": "R01", "title": "Readable", "enforcement": "proxy",
   "check": "check_readability", "failure_code": "writing_readability_out_of_band",
   "mechanism": "Reading-grade band, max sentence length, per-NAICS jargon blocklist.",
   "cannot_enforce": "Whether it reads as professional.",
   "prompt_instruction": (
     "Write so a wide audience understands it. Professional, never academic. "
     "Use esoteric terms only where no plain word carries the meaning. This is "
     "a business plan, not a thesis.")},

  {"id": "R02", "title": "Tailored", "enforcement": "hard",
   "check": "check_cross_plan_similarity", "failure_code": "writing_plan_not_tailored",
   "mechanism": "8-gram overlap against prior plans in the same NAICS, boilerplate spans exempt.",
   "cannot_enforce": "Whether the depth is real depth.",
   "prompt_instruction": (
     "Write to THIS business. Two businesses in one industry must not produce "
     "plans that sound alike. Draw on what this client actually told us and "
     "what their numbers actually do.")},

  {"id": "R03", "title": "Never name what we do not have", "enforcement": "hard",
   "check": "check_no_absence_language", "failure_code": "writing_named_a_gap",
   "mechanism": "Forbidden-phrase scan over prose AND notes (Nick ruling C).",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Never tell the reader something was unavailable, missing, unknown or not "
     "provided. Where a fact is absent, reason from the industry and from what "
     "IS present, or say nothing at all.")},

  {"id": "R04", "title": "No machinery", "enforcement": "hard",
   "check": "check_no_machinery", "failure_code": "writing_exposed_machinery",
   "mechanism": "Term blocklist; forecast-as-forecast legal only inside the basis_of_projections span.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Never mention the model, the engine, the data pipeline, or how a figure "
     "was produced. Discuss a forecast as a forecast only where the plan "
     "explains what the projections rest on.")},

  {"id": "R05", "title": "No fluff", "enforcement": "proxy",
   "check": "check_specificity", "failure_code": "writing_generic_sentence",
   "mechanism": "Every GROUNDED/INFERRED sentence carries >=1 client-specific token. FRAMING exempt, capped.",
   "cannot_enforce": "Whether a specific sentence is a compelling one.",
   "prompt_instruction": (
     "If a sentence would still read true with a competitor's name swapped in, "
     "cut it. Every factual sentence must be about THIS business.")},

  {"id": "R06", "title": "Grounded in our data", "enforcement": "hard",
   "check": "check_fact_tokens_resolve", "failure_code": "writing_unresolved_fact",
   "mechanism": "Every fact token resolves to a brief fact tracing to finmo_json / model_input_json.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Every figure comes from the brief, referenced as {{fact:key}}. Someone "
     "holding the workbook must be able to tell this document belongs to it.")},

  {"id": "R07", "title": "Industry and economy", "enforcement": "proxy",
   "check": "check_context_present", "failure_code": "writing_context_absent",
   "mechanism": "Market & Industry must carry >=1 industry and >=1 economic reference.",
   "cannot_enforce": "Whether the context actually bears on this business.",
   "prompt_instruction": (
     "Factor the industry and the economic environment in where they bear on "
     "this business. Never recite indicators for their own sake.")},

  {"id": "R08", "title": "Charts", "enforcement": "hard",
   "check": "check_chart_registry", "failure_code": "writing_chart_off_registry",
   "mechanism": "Registry keyed id->section->placement->required facts; renderer refuses unregistered ids.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Charts are placed by the system. Reference a figure by its number where "
     "the text discusses it. Never invent, describe or promise a chart.")},

  {"id": "R09", "title": "Holistic", "enforcement": "soft",
   "check": "check_source_family_coverage", "failure_code": "writing_thin_source_coverage",
   "mechanism": "Proxy only: >=N distinct source families per section.",
   "cannot_enforce": "Whether it reasoned across sources or concatenated them.",
   "prompt_instruction": (
     "Work from the whole picture - the client's own narrative, the numbers, "
     "the industry and the economy. Never restate intake back to the reader.")},

  {"id": "R10", "title": "The bar", "enforcement": "soft",
   "check": None, "failure_code": None,
   "mechanism": "None. This is the aggregate of every other rule.",
   "cannot_enforce": "Everything. No check reads a document and knows it is worth $999.",
   "prompt_instruction": (
     "These start at $999 and must read as though experienced consultants "
     "wrote them. Analysis, context, depth and rigour together are the "
     "product.")},

  {"id": "R11", "title": "Sources and notes", "enforcement": "hard",
   "check": "check_notes", "failure_code": "writing_note_invalid",
   "mechanism": "Marker<->note bijection; kind in {SOURCE,BASIS}; SOURCE needs source+vintage; attribution blocklist.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Mark a claim with a superscript where a source or a basis genuinely "
     "helps - not on everything. SOURCE names where a fact came from. BASIS "
     "names what an assertion rests on. Never write that software determined "
     "anything.")},

  {"id": "R12", "title": "Structure fixed, content never repeats", "enforcement": "hard",
   "check": "check_structure_and_repetition", "failure_code": "writing_structure_violation",
   "mechanism": "Section registry + the R02 similarity guard.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "The sections, the chart types and their placements are fixed. Nothing "
     "else may be shared with another plan.")},

  {"id": "R13", "title": "Sections that come and go", "enforcement": "hard",
   "check": "check_section_emission", "failure_code": "writing_section_emission_invalid",
   "mechanism": "Emission = (core or trigger) and not explicitly OFF; Disclosures locked; explicit ON cannot override a missing data condition; numbering/TOC computed; charts owned by sections; the executive summary builds from whatever is present.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Thin data makes a shorter section, never a missing one. Never refer to a "
     "section or a figure by a number - the system numbers them.")},

  {"id": "R14", "title": "Three sentence classes", "enforcement": "hard",
   "check": "check_sentence_classes", "failure_code": "writing_sentence_class_violation",
   "mechanism": "Class-tagged output; per-class checks in CLASS_RULES; density guard.",
   "cannot_enforce": "A false QUALITATIVE claim labelled INFERRED. Accepted residual risk.",
   "prompt_instruction": (
     "Tag every sentence GROUNDED, INFERRED or FRAMING. GROUNDED states a fact "
     "from the brief. INFERRED reasons from grounded facts and industry "
     "knowledge and may not introduce a number. FRAMING is positioning: no "
     "numbers, no proper nouns, no citations.")},

  {"id": "R15", "title": "Voice", "enforcement": "hard",
   "check": "check_voice", "failure_code": "writing_voice_violation",
   "mechanism": "Pronoun blocklist outside quotations; business name must appear.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Third person, business-named. \"Redbrook Coffee Roasters operates...\" "
     "Never we, never you. Name the owner where it matters.")},

  {"id": "R16", "title": "Numbers", "enforcement": "hard",
   "check": "check_number_style", "failure_code": "writing_number_style_violation",
   "mechanism": "One formatter renders every figure; hedge and range scan on grounded sentences.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Never type a number. Reference it as {{fact:key}} and the system writes "
     "it. Never hedge a figure that exists.")},

  {"id": "R17", "title": "Narrative numbers are statement numbers", "enforcement": "hard",
   "check": "check_no_computation", "failure_code": "writing_gpt_computed",
   "mechanism": "Any bare numeral outside a fact token fails the section.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "You may not compute. Not a sum, not a percentage, not a growth rate. If "
     "a figure belongs in the document it is already in the brief; if it is "
     "not there, you may not write it.")},

  {"id": "R18", "title": "Annual, not quarterly", "enforcement": "hard",
   "check": "check_namespace_scope", "failure_code": "writing_quarterly_in_body",
   "mechanism": "Namespace rule: body may reference annual/entity/industry/market plus two named quarterly keys.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "The body tells a five-year story, Year 1 to Year 5. Quarterly detail "
     "belongs to the workbook. The only quarterly moments you may name are the "
     "cash trough and break-even, and both are written as sentences.")},

  {"id": "R19", "title": "Basis of projections", "enforcement": "hard",
   "check": "check_basis_of_projections", "failure_code": "writing_basis_paragraph_invalid",
   "mechanism": "Required exactly once, opening the financial plan; duplicate detection.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Open the financial plan with one plain paragraph on what the projections "
     "rest on. Not a disclaimer wall, and never repeated.")},

  {"id": "R20", "title": "Proportion", "enforcement": "hard",
   "check": "check_proportion", "failure_code": "writing_proportion_flag",
   "mechanism": "Page estimate per section; out-of-band FLAGS for review and never truncates.",
   "cannot_enforce": None,
   "prompt_instruction": (
     "Write to the length the section deserves. Targets are guidance, not a "
     "limit to pad toward.")},

  {"id": "R21", "title": "Version stamp", "enforcement": "hard",
   "check": "check_footer_and_run_id", "failure_code": "writing_stamp_violation",
   "mechanism": "Footer from template; run id asserted absent from body/header/footer, present in appendix.",
   "cannot_enforce": None,
   "prompt_instruction": "Never write a footer, a page number or a run identifier."},

  {"id": "R22", "title": "Document craft", "enforcement": "hard",
   "check": "check_document_craft", "failure_code": "writing_craft_violation",
   "mechanism": "Real style objects asserted; zero direct-formatted runs; caption+cross-reference per chart; one font pair; one table style.",
   "cannot_enforce": "Whether the result is beautiful.",
   "prompt_instruction": "Never format anything. Structure only; the system styles it."},

  {"id": "R23", "title": "Editable", "enforcement": "hard",
   "check": "check_editable", "failure_code": "writing_not_editable",
   "mechanism": "docx XML assert: no text boxes, no anchored shapes, images inline.",
   "cannot_enforce": None,
   "prompt_instruction": "Never request a text box, a sidebar or a floating element."},
)


# ---------------------------------------------------------------------------
# ACCESSORS - the door. Nothing imports the tuples above directly.
# ---------------------------------------------------------------------------
def rule(rule_id: str) -> Dict[str, Any]:
  for r in WRITING_RULES:
    if r["id"] == rule_id:
      return r
  raise KeyError("no such writing rule: %r" % rule_id)


def rules_by_enforcement(kind: str) -> List[Dict[str, Any]]:
  return [r for r in WRITING_RULES if r["enforcement"] == kind]


def enforceable_rules() -> List[Dict[str, Any]]:
  """Rules a machine actually holds. Everything else is Nick's review."""
  return [r for r in WRITING_RULES if r.get("check")]


def unenforceable_rules() -> List[Dict[str, Any]]:
  """Named out loud so nobody believes a check exists where none does."""
  return [r for r in WRITING_RULES if not r.get("check")]


def section(key: str) -> Dict[str, Any]:
  for s in SECTION_REGISTRY:
    if s["key"] == key:
      return s
  raise KeyError("no such section: %r" % key)


def charts_for_section(section_key: str) -> List[Dict[str, Any]]:
  return sorted(
    [c for c in CHART_REGISTRY if c["section"] == section_key],
    key=lambda c: c["order"],
  )


def body_section_keys() -> List[str]:
  skip = {"appendix", "sources_and_notes"}
  return [s["key"] for s in sorted(SECTION_REGISTRY, key=lambda s: s["order"])
          if s["key"] not in skip]


def namespace_allowed_in_body(fact_key: str) -> bool:
  """Rule 18 as a namespace test rather than a prose test."""
  key = str(fact_key or "").strip()
  if key in BODY_QUARTERLY_EXCEPTIONS:
    return True
  ns = key.split(".", 1)[0] if "." in key else ""
  return ns in BODY_ALLOWED_NAMESPACES
