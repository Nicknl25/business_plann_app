"""THE UPSTREAM QA REPORT (spec 1.7) - the detectors that produced the v1
discrepancy list, surfaced to the OPERATOR. Never to the writer, never to
the client - an error in our model is an engineering defect to fix
upstream, and no amount of writing cures it.

Honest ledger: the prose-level detectors (stated plan absent from the
model, retention vs stated subscribers, transcript-corrected fields,
omitted stated costs outside the pinned families) need transcript
extraction and are DECLARED not-run rather than pretended.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

NOT_RUN = [
    "omitted_stated_cost (generic transcript extraction not built; pinned "
    "families only)",
    "retention_vs_stated_subscribers (prose-level)",
    "stated_plan_absent_from_model (prose-level)",
    "multiply_corrected_fields (intake correction history)",
    "marketing_schedule_defects (schedule internals)",
]


def build_qa_report(v1: Dict[str, Any], cls: Dict[str, Any]) -> Dict[str, Any]:
    F = v1["record"].get("financials") or {}
    FY1 = v1["record"].get("financials_year1") or {}
    A = v1["model"]["annual"]
    D = v1.get("derived") or {}
    findings: List[Dict[str, Any]] = []

    if cls.get("record_code_fits") is False:
        findings.append({
            "kind": "classification",
            "what": ("record NAICS %s judged not to fit the business; bundle "
                     "fetched for: %s"
                     % (v1["meta"].get("industry_code_on_record"),
                        "; ".join(g["description"] for g in cls.get("groups", [])))),
            "why": cls.get("why"),
        })

    # PAYROLL (Nick's ruling 2026-09-10): the tie-out lives at the STUB.
    # The stub carries the client's stated payroll BY CONSTRUCTION
    # (finmo_bridge: payroll_total_year1 / 4 - verified to the cent on
    # Bramblewood), so stated-vs-model is not a tie-out question anywhere
    # in the forecast. Q1..Q20 is a FORECAST: it hires, inflates and
    # re-shapes, and a Year-1 that differs from today's payroll is the
    # forecast doing its job - the old "payroll_gap" check compared a
    # forecast to an actual with a 5% tie-out tolerance and reported
    # normal behaviour as a defect on every plan that hires (Bellamy,
    # Sunny, Bramblewood). What CAN be wrong is the forecast's LAUNCH
    # POINT: a Q1 wage bill far off today's stated payroll means the
    # author invented or erased staff on day one (Bramblewood: +3.0
    # supporting FTE on a fully enumerated roster, 1.67x stated). So: a
    # plausibility BAND on annualized Q1 wages - UNLOADED, like the
    # stated figure; the old check also compared a loaded model number
    # to unloaded stated wages - mirroring the authoring-side fact
    # band's 0.70-1.30.
    stated_wages = F.get("payroll_total_year1")
    roster_q1 = (v1["model"].get("payroll") or {}).get("roster_q1") or []
    if stated_wages and roster_q1:
        launch_wages = sum(
            max(0.0, float(r.get("ending_fte") or 0.0))
            * max(0.0, float(r.get("annual_wage") or 0.0))
            for r in roster_q1
        )
        ratio = launch_wages / float(stated_wages)
        if ratio < 0.70 or ratio > 1.30:
            findings.append({
                "kind": "payroll_launch_band",
                "what": ("forecast launch (Q1) annualized wages %.0f vs stated "
                         "current wages %.0f (%.2fx stated; plausibility band "
                         "0.70-1.30). The stub carries the stated figure by "
                         "construction; Year 1 onward is a forecast."
                         % (launch_wages, float(stated_wages), ratio)),
            })

    # HEADCOUNT: identical shape, identical ruling - a launch-point band,
    # not a tie-out. (The prior check read qt[0]["fte"], a key that does
    # not exist - quarter_totals carries "ending_fte" - so it had never
    # fired on any plan; this is its first working form.)
    heads = F.get("current_num_employees")
    qt = (v1["model"].get("payroll") or {}).get("quarter_totals") or []
    fte = (qt[0] or {}).get("ending_fte") if qt else None
    if heads and fte:
        hratio = float(fte) / float(heads)
        if (hratio < 0.70 or hratio > 1.30) and abs(float(fte) - float(heads)) >= 1:
            findings.append({
                "kind": "headcount_launch_band",
                "what": ("forecast launch (Q1) FTE %.1f vs stated headcount %d "
                         "(%.2fx stated; plausibility band 0.70-1.30)"
                         % (float(fte), heads, hratio)),
            })

    ds = v1["model"].get("debt_schedule") or []
    if ds and F.get("annual_interest_payment") and F.get("total_debt_outstanding"):
        implied = F["annual_interest_payment"] / F["total_debt_outstanding"]
        carried = ds[0].get("annual_interest_rate")
        if carried and (implied / carried > 1.5 or carried / implied > 1.5):
            findings.append({
                "kind": "loan_rate",
                "what": ("model carries the loan at %.2f%%; stated interest "
                         "implies %.2f%%" % (carried * 100, implied * 100)),
            })

    resc = (FY1.get("_rescale_provenance") or {})
    if resc.get("factor") not in (None, 1, 1.0):
        findings.append({
            "kind": "rescaled_capacity",
            "what": ("financials_year1 capacities carry rescale factor %s "
                     "(source_total %s -> target_total %s) - stated capacities "
                     "were altered by the model"
                     % (resc.get("factor"), resc.get("source_total"),
                        resc.get("target_total"))),
        })

    band = ((F.get("_coherence") or {}).get("margin_band_judgment") or {}) \
        .get("q11") or {}
    m = D.get("ebitda_margin_y1")
    if m is not None and band.get("low") is not None:
        if not (band["low"] <= m <= band["high"]):
            findings.append({
                "kind": "projections_vs_judged_band",
                "what": ("Year-1 EBITDA margin %.1f%% sits outside the judged "
                         "band %.0f%%-%.0f%%"
                         % (m * 100, band["low"] * 100, band["high"] * 100)),
            })

    # pinned stated-cost family (Thornfield's shipping/card fees and kin)
    for k in D:
        if k.endswith("_annual") and k.startswith("stated_") and "wages" not in k:
            base = k[:-7]
            if f"{base}_pct_of_stated_revenue" in D:
                findings.append({
                    "kind": "omitted_cost",
                    "what": ("%s: %.0f/yr (%.1f%% of stated revenue) stated by "
                             "the owner and absent from the projections"
                             % (base, D[k],
                                D[f"{base}_pct_of_stated_revenue"] * 100)),
                })

    return {
        "business_name": v1["meta"]["business_name"],
        "draft_id": v1["meta"]["draft_id"],
        "planning_run_id": v1["meta"]["planning_run_id"],
        "prepared": v1["meta"]["bundle_prepared"],
        "audience": "operator only - never the writer, never the client",
        "findings": findings,
        "detectors_not_run": NOT_RUN,
    }
