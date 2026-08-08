"""PASS-2 design-pass suite - all three specs on the live shapes.

Spec 1: 561720 worked example (87.2% - 60.4% -> ~26.8%), retail negative
        control, and the NEVER-GUESS guardrail (no payroll coverage ->
        no conversion).
Spec 2: the Catawba install-division-manager inversion narrative
        end-to-end through the real default loop (GPT + OEWS rows
        stubbed), plus the monotonicity rail and client-override
        exemption.
Spec 3: the Oak City three-product pricing summary verbatim, snake_case
        humanization (the Catawba leak), single-product degrade.
"""
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")

from dotenv import load_dotenv

load_dotenv()

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


# ============ SPEC 1 - labor-heavy basis reconciliation ============
from client_intake_and_finmo.labor_basis import (  # noqa: E402
    cohort_payroll_share, maybe_labor_adjust_cogs_band,
)

# The 561720 worked example - real baseline data.
share = cohort_payroll_share("561720")
check("S1 cohort payroll share resolves for 561720 (cascade)",
      share is not None and 0.5 < share < 0.7)
adj = maybe_labor_adjust_cogs_band(
    naics_6="561720", band_min=0.866712, band_target=0.872091,
    band_max=0.877609, labor_heavy_business=True)
check("S1 561720 converts to a materials band (~26.8% target)",
      adj is not None and 0.22 < adj["target"] < 0.32)
check("S1 ordering preserved and provenance stamped",
      adj is not None and adj["min"] <= adj["target"] <= adj["max"]
      and adj["provenance"]["basis"] == "labor_adjusted"
      and adj["provenance"]["overlap_sum"] > 1.0)
check("S1 the Ironclad stated 6-8% now sits below-but-near the band, not 10x under",
      adj is not None and adj["min"] / 0.07 < 4.5)

# NEG: business signal absent -> no conversion.
check("S1 NEG no business signal -> None",
      maybe_labor_adjust_cogs_band(
          naics_6="561720", band_min=0.8667, band_target=0.8721,
          band_max=0.8776, labor_heavy_business=False) is None)
# NEG: retail/manufacturing-style band (sum <= 1) -> no conversion.
check("S1 NEG overlap sum <= 1 -> None (materials-heavy cohort untouched)",
      maybe_labor_adjust_cogs_band(
          naics_6="561720", band_min=0.25, band_target=0.35,
          band_max=0.45, labor_heavy_business=True) is None)
# THE GUARDRAIL: no payroll coverage anywhere -> no conversion, ever.
check("S1 GUARDRAIL no payroll coverage -> None (never a guessed subtraction)",
      maybe_labor_adjust_cogs_band(
          naics_6="000000", band_min=0.8667, band_target=0.8721,
          band_max=0.8776, labor_heavy_business=True) is None)

# Seam 2 end-to-end: the ramp builder's band resolver.
from client_intake_and_finmo.post_intake_contracts.runner import (  # noqa: E402
    _cohort_band_target_and_max,
)

t_labor, m_labor = _cohort_band_target_and_max(
    metric_key="cogs_percent_of_revenue", business_naics_6="561720",
    default_target=0.45, default_max=0.65, labor_heavy_business=True)
t_raw, m_raw = _cohort_band_target_and_max(
    metric_key="cogs_percent_of_revenue", business_naics_6="561720",
    default_target=0.45, default_max=0.65, labor_heavy_business=False)
# The reader resolves 561720 via the EDGAR walk (target ~0.57, max
# ~0.87); subtracting the 60.4% payroll share pins the target at the
# floor while the max stays informative (~0.27) - the labor-heavy ramp
# target drops toward the materials basis instead of 57% labor-inclusive.
check("S1 seam-2: labor-heavy janitorial ramp target converts toward materials basis",
      t_labor < 0.1 and t_raw > 0.5)

# ============ SPEC 2 - OEWS seniority ============
import client_intake_and_finmo.people_roles as pr  # noqa: E402

check("S2 layer-1 tokens: 'Install Division Manager' now tiers senior",
      pr._seniority_tier("Install Division Manager") == "senior")
check("S2 compose raise-only: junior token + senior narrative -> senior",
      pr._compose_seniority("junior", "senior") == "senior")
check("S2 compose: token None + narrative owner -> owner",
      pr._compose_seniority(None, "owner") == "owner")
check("S2 compose: junior token alone still lowers (pct25 path intact)",
      pr._compose_seniority("junior", None) == "junior")

# End-to-end through the REAL default loop, Catawba narrative, GPT +
# OEWS rows stubbed. Fake occupations arranged to reproduce the live
# CROSS-OCCUPATION inversion: the manager's occupation medians BELOW the
# junior's occupation pct25.
FAKE_ROWS = [
    {"occ_title": "Landscaping and Groundskeeping Workers", "a_pct10": 30000,
     "a_pct25": 34000, "a_median": 38000, "a_pct75": 45000, "tot_emp": 900},
    {"occ_title": "Office and Administrative Support Workers", "a_pct10": 36000,
     "a_pct25": 42000, "a_median": 50000, "a_pct75": 58000, "tot_emp": 400},
]

def _fake_fetch(conn, **kwargs):
    return list(FAKE_ROWS)

def _fake_match(*, role_title, notes, business_type, candidate_titles):
    if "manager" in role_title.lower():
        # The narrative carries the seniority; occupation is the WORKER row.
        return ("Landscaping and Groundskeeping Workers", "senior")
    return ("Office and Administrative Support Workers", "junior")

_orig_fetch = pr._fetch_oews_rows_with_fallback
_orig_match = pr._match_occ_title_with_gpt
pr._fetch_oews_rows_with_fallback = _fake_fetch
pr._match_occ_title_with_gpt = _fake_match
try:
    ROLES = [
        {"role_title": "Install Division Manager",
         "notes": "Eighteen-year certified installer running the entire install division.",
         "annual_wage": None, "wage_source": ""},
        {"role_title": "Office Assistant",
         "notes": "Entry-level admin support.",
         "annual_wage": None, "wage_source": ""},
        {"role_title": "Crew Member",
         "notes": "Client told us exactly what she pays this role.",
         "annual_wage": 52000, "wage_source": "client_override"},
    ]
    out = pr.apply_oews_wages(
        None, roles=ROLES, business_type="Landscaping Service",
        business_stage="operating", business_naics_6="561730")
    by_title = {r["role_title"]: r for r in out}
    mgr = by_title["Install Division Manager"]
    jr = by_title["Office Assistant"]
    check("S2 manager lands pct75 of its occupation ($45,000)",
          mgr["annual_wage"] == 45000)
    check("S2 junior lands pct25 of its occupation ($42,000)",
          jr["annual_wage"] == 42000)
    check("S2 NO INVERSION: senior >= junior (was $38,000 < $42,000 live)",
          mgr["annual_wage"] >= jr["annual_wage"])
    check("S2 client-stated wage untouched and exempt",
          by_title["Crew Member"]["annual_wage"] == 52000
          and by_title["Crew Member"]["wage_source"] == "client_override")
    check("S2 no internal tier key leaks into the role rows",
          all("_seniority_tier" not in r for r in out))

    # The monotonicity rail proper: force the senior occupation's pct75
    # BELOW the junior default - the rail must raise it.
    FAKE_ROWS[0]["a_pct75"] = 40000  # senior would land 40k < junior 42k
    out2 = pr.apply_oews_wages(
        None, roles=[dict(ROLES[0]), dict(ROLES[1])],
        business_type="Landscaping Service", business_stage="operating",
        business_naics_6="561730")
    by2 = {r["role_title"]: r for r in out2}
    check("S2 RAIL: cross-occupation inversion raised to the junior floor",
          by2["Install Division Manager"]["annual_wage"] == 42000
          and by2["Install Division Manager"]["wage_source"] == "oews_seniority_floor")
    check("S2 RAIL raise-only: junior unchanged", by2["Office Assistant"]["annual_wage"] == 42000)
finally:
    pr._fetch_oews_rows_with_fallback = _orig_fetch
    pr._match_occ_title_with_gpt = _orig_match

# ============ SPEC 3 - product pricing summary ============
from client_intake_and_finmo.fact_templates import (  # noqa: E402
    build_product_pricing_summary, render_fact_template,
)

OAK_OPS = {"lob_models": [{"lob_name": "Facilities", "products": [
    {"product_name": "Facility service contracts",
     "unit_name": "building-month of bundled service", "unit_price": 1200,
     "unit_cadence": "monthly"},
    {"product_name": "Deep clean & restoration projects", "unit_name": "project",
     "unit_price": 19500, "unit_cadence": "contract"},
    {"product_name": "On-call repair & service jobs", "unit_name": "job",
     "unit_price": 1450, "unit_cadence": "contract"},
]}]}
summary = build_product_pricing_summary(OAK_OPS)
check("S3 Oak City trio renders paired, grammatical, complete",
      summary == "$1,200 per building-month of bundled service, "
                 "$19,500 per project, and $1,450 per job")

rendered = render_fact_template(
    "Pricing: {{fact:ops.product_pricing_summary}}.",
    shared_context={"operating_model": OAK_OPS}, business_facts={})
check("S3 placeholder resolves through the template path",
      "$19,500 per project" in rendered and "-$" not in rendered)

# The Catawba leak: snake_case never reaches the client.
SNAKE_OPS = {"lob_models": [{"products": [
    {"product_name": "maintenance_contracts", "unit_name": "commercial_property_month",
     "unit_price": 1200, "unit_cadence": "monthly"},
    {"product_name": "install_projects", "unit_price": 86000, "unit_cadence": "contract"},
]}]}
s2 = build_product_pricing_summary(SNAKE_OPS)
check("S3 snake_case humanized in the summary",
      "commercial property month" in s2 and "_" not in s2)
rendered_names = render_fact_template(
    "billed per {{fact:ops.unit_name}}",
    shared_context={"operating_model": SNAKE_OPS}, business_facts={})
check("S3 unit_name renders humanize too (shared formatter)",
      "_" not in rendered_names)

SINGLE = {"lob_models": [{"products": [
    {"product_name": "Dozen donuts", "unit_price": 18, "unit_cadence": "daily"},
]}]}
check("S3 single product degrades to the scalar form",
      build_product_pricing_summary(SINGLE) == "$18 per Dozen donuts")

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
