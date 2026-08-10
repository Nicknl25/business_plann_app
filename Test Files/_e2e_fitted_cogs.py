"""FITTED COGS PROPOSAL E2E (Nick-ruled, fitted-proposals slate).

Production path: cogs stage default -> _resolve_cogs_baseline_or_raise
-> _compute_cogs_baseline (cohort row AS EVIDENCE -> fit judge ->
plain-estimator fallback) -> stage default patch (ratio stamp + band)
-> the FINMO stub fields the engine reads.
Nick's proof: janitorial 561720 (cohort cost-of-revenue ~88%, crew
labor inside) now proposes a MATERIALS-ONLY anchor (~5-10%), never the
88% - with the basis reconciling why; uncovered NAICS keeps the honest
fallback; the range rides into the client-facing wording.
RED evidence: the raw cohort average landed as the materials anchor -
the 10x janitorial misfit an accepting client shipped into the plan.
"""
import os
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


from api_handlers.intake_consult import (  # noqa: E402
    _build_cogs_baseline_message, _build_financials_stage_acknowledgement,
    _financials_stage_default_patch, _resolve_cogs_baseline_or_raise,
)

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)

# A janitorial business shaped like the real misfit case: labor-heavy
# commercial cleaning, materials are supplies only.
OPS_JANITORIAL = {
    "business_naics_6": "561720",
    "business_type": "Commercial Janitorial Services",
    "business_description_summary": (
        "Commercial cleaning company serving offices under recurring "
        "contracts; crews clean nightly; materials are cleaning supplies "
        "and consumables."),
    "unit_name": "monthly contract",
    "lob_models": [{"lob_name": "Commercial cleaning", "products": [{
        "product_name": "Monthly office contract", "unit_price": 2000.0,
        "units_per_period_capacity": 20.0, "operating_periods_per_year": 12.0,
        "utilization_rate": 0.8}]}],
}
SHARED = {"operating_model": OPS_JANITORIAL,
          "people_capability": {"people": [
              {"role_title": "Owner & Operations", "annual_wage": 60000.0}],
              "rest_of_team_payroll_year1": 180000.0}}
Y1 = {"company_revenue_total_year1": 384000.0}

# F1: THE JANITORIAL PROOF - the proposal is materials-only, never the
# cohort 88%.
baseline = _resolve_cogs_baseline_or_raise(
    conn=conn, ops_json=OPS_JANITORIAL, shared_context=SHARED,
    financials_year1_json=Y1)
pct = float(baseline.get("baseline_cogs_percent") or 0.0)
rationale = str(baseline.get("cogs_basis_rationale") or "")
band = baseline.get("cogs_fit_band")
cohort = baseline.get("cogs_fit_cohort_cost_of_revenue")
print(f"   proposed={pct:.4f} band={band} cohort_evidence={cohort}")
print(f"   rationale: {rationale[:260]}")
check(f"F1 janitorial 561720 proposes MATERIALS-ONLY ({pct:.1%}), not "
      "the ~88% cohort cost-of-revenue",
      0.005 <= pct <= 0.20)
check("F1b the cohort evidence was seen (~88%) and the band is sane",
      cohort is not None and float(cohort) > 0.5
      and isinstance(band, list) and band[0] < band[1] <= 0.30)
check("F1c the basis RECONCILES the cohort number (mentions labor/"
      "payroll and materials)",
      any(w in rationale.lower() for w in ("labor", "payroll", "crew"))
      and any(w in rationale.lower() for w in ("material", "supplie", "consumable")))

# F2: the stage default patch (the STUB the engine reads) carries the
# fitted number + the ratio stamp + the band.
patch = _financials_stage_default_patch(
    stage_name="cogs", shared_context=SHARED, financials_year1_json=Y1,
    business_facts={}, conn=conn)
check("F2 stub fields fitted: cogs pct == proposal, dollars == pct x "
      f"revenue ({patch['cogs_total_year1']:>10,.0f})",
      abs(patch["cogs_percent_of_revenue"] - pct) < 1e-6
      and abs(patch["cogs_total_year1"] - pct * 384000.0) < 1.0)
check("F2b proposal stamps cogs_basis='ratio' (a proposal is never a "
      "stated dollar - Nick ruling #3)",
      patch.get("cogs_basis") == "ratio")

# F2b-PROD (CW-024 #112 restoration): the ratio stamp must SURVIVE the
# PRODUCTION apply path - _normalize_financials_router_patch filtered
# the unknown field and the touched-twin inference re-tagged 'dollars'
# (the Cedar Ridge run shipped an app-proposed 42% masquerading as
# durable client dollars). The dict-level F2b above was exactly the
# test hole: it proved the builder, not the applied result.
from api_handlers.intake_consult import _normalize_financials_router_patch  # noqa: E402

_router_patch = {f"financials.{k}": v for k, v in patch.items()}
_applied = _normalize_financials_router_patch(
    patch=_router_patch, active_stage="cogs",
    financials_json={"_financials_revenue_intro_done": True},
    financials_year1_json=Y1, last_assistant="", user_message="")
check("F2b-PROD the ratio stamp survives the production apply "
      f"(cogs_basis={( _applied or {}).get('cogs_basis')!r}, twins landed)",
      isinstance(_applied, dict) and _applied.get("cogs_basis") == "ratio"
      and abs(float(_applied.get("cogs_total_year1") or 0) - patch["cogs_total_year1"]) < 1.0)
check("F2c the band rides the patch for the ack",
      isinstance(patch.get("cogs_fit_band"), list))

# F3: the client-facing wording speaks the RANGE and invites correction
# (Nick ruling #2 - the accept-trap softener).
msg = _build_cogs_baseline_message(baseline)
check("F3 proposal message speaks the range and asks to adjust",
      "typically runs" in msg and "-" in msg and "adjust" in msg)
ack = _build_financials_stage_acknowledgement(
    stage_name="cogs",
    financials_json={"cogs_total_year1": patch["cogs_total_year1"],
                     "cogs_percent_of_revenue": pct,
                     "cogs_fit_band": band})
check("F3b ack is range-flavored and invites correction, never flat "
      "fact", "typically runs" in ack and "correct me" in ack)

# F4: an UNCOVERED NAICS also goes through the fit judge (CW-024
# #110/#111 - the plain estimator is deleted): no fabricated cohort
# evidence field, a real band, sane pct.
OPS_UNCOVERED = dict(OPS_JANITORIAL, business_naics_6="812910",
                     business_type="Pet grooming",
                     business_description_summary="Mobile pet grooming.")
baseline_u = _resolve_cogs_baseline_or_raise(
    conn=conn, ops_json=OPS_UNCOVERED,
    shared_context={"operating_model": OPS_UNCOVERED},
    financials_year1_json=Y1)
check("F4 uncovered NAICS: fit-judge fallback with a band, no cohort "
      f"evidence field, sane pct ({float(baseline_u['baseline_cogs_percent']):.1%})",
      "cogs_fit_cohort_cost_of_revenue" not in baseline_u
      and isinstance(baseline_u.get("cogs_fit_band"), list)
      and 0.0 < float(baseline_u["baseline_cogs_percent"]) <= 0.6)

conn.close()
print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
