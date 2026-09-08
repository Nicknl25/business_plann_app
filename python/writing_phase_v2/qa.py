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

    stated_wages = F.get("payroll_total_year1")
    if stated_wages and A:
        model_payroll = A[0]["payroll"]
        if abs(model_payroll - stated_wages) / stated_wages > 0.05:
            findings.append({
                "kind": "payroll_gap",
                "what": ("model Year-1 payroll %.0f vs stated total wages %.0f "
                         "(gap %.0f before loading)"
                         % (model_payroll, stated_wages,
                            stated_wages - model_payroll)),
            })

    heads = F.get("current_num_employees")
    qt = (v1["model"].get("payroll") or {}).get("quarter_totals") or []
    fte = (qt[0] or {}).get("fte") if qt else None
    if heads and fte and abs(float(fte) - float(heads)) >= 1:
        findings.append({
            "kind": "headcount",
            "what": "modelled FTE %.1f vs stated headcount %d" % (float(fte), heads),
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
