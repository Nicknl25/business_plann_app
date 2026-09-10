"""DERIVED (spec 1.5) - the figures a consultant would compute, precomputed.

Every formula here was recovered from the hand-built Thornfield reference
and verified bit-exact for all 181 keys (2026-09-08). Per-year keys compute
FROM THE ROUNDED model.annual rows, not the raw quarters - that is the
reference's convention. Association order matters for sde_* (owner-comp
addback first).

Transcript-stated constants (the shipping-fee figure, the stated
capacities) exist only in the client's prose, and their key names are
hand-labeled per business - they live in the per-draft PIN below. A draft
without a pin gets every generic family and none of the hand-labeled ones;
absent is never fabricated. The v2 strip removes stated/omission/vs_ keys
before the writer sees anything; the QA report quantifies stated-vs-model
on its own extraction, not on these keys.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.owner_pay import owner_pay_total

_SLUG = lambda name: re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


# per-draft pinned transcript constants and hand-chosen labels
PIN: Dict[str, Dict[str, Any]] = {
    "eae0ac3f": {
        "stated_cost_base": "stated_shipping_packaging_card_fees",
        "stated_cost_monthly": 7000,
        "capacity": [
            ("dtc", "weekly", "Direct online orders"),
            ("wholesale", "weekly", "Wholesale orders"),
            ("subscription", "monthly", "Subscription plans"),
        ],
        "stated_scalars": {
            "stated_current_dtc_orders_weekly": 270,
            "stated_wholesale_accounts": 40,
            "stated_wholesale_orders_weekly": 5,
            "stated_active_subscribers": 300,
            "stated_website_orders_annual": 14000,
            "stated_inventory_turns": 4,
        },
        "ar_days_line": "Wholesale orders",
    },
}


def _jl(v):
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


def build_derived(draft: Dict[str, Any], model: Dict[str, Any],
                  record: Dict[str, Any],
                  warehouse: Dict[str, Any]) -> Dict[str, Any]:
    A: List[Dict[str, Any]] = model["annual"]
    F: Dict[str, Any] = record.get("financials") or {}
    FY1: Dict[str, Any] = record.get("financials_year1") or {}
    MM: Dict[str, Any] = record.get("marketing_model") or {}
    BE = model.get("break_even") or {}
    BEPL = model.get("break_even_q1_per_line") or []
    DSch = model.get("debt_schedule") or []
    fm = _jl(draft.get("finmo_json")) or {}
    Q = sorted((r for r in (fm.get("quarter_rows") or [])
                if int(r.get("quarter_index") or 0) >= 1),
               key=lambda r: int(r["quarter_index"]))
    D: Dict[str, Any] = {}

    D["revenue_cagr_y1_y5"] = (A[4]["revenue"] / A[0]["revenue"]) ** 0.25 - 1
    if F.get("current_revenue"):
        D["revenue_y1_vs_stated_pct"] = A[0]["revenue"] / F["current_revenue"] - 1

    n_emp = F.get("current_num_employees")
    ann_prin = float(F.get("annual_principal_payment") or 0.0)
    owner_pay_annual = owner_pay_total(record.get("people") or {}, F)["annual_total"]
    for y, r in enumerate(A, 1):
        rev = r["revenue"]
        D[f"gross_margin_y{y}"] = r["gross_profit"] / rev
        D[f"ebitda_margin_y{y}"] = r["ebitda"] / rev
        D[f"net_margin_y{y}"] = r["net_income"] / rev
        D[f"payroll_pct_revenue_y{y}"] = r["payroll"] / rev
        D[f"marketing_pct_revenue_y{y}"] = r["marketing"] / rev
        D[f"rent_pct_revenue_y{y}"] = r["lease_rent"] / rev
        D[f"ga_pct_revenue_y{y}"] = r["general_and_administrative"] / rev
        D[f"overhead_pct_revenue_y{y}"] = (
            r["payroll"] + r["marketing"] + r["lease_rent"]
            + r["general_and_administrative"]) / rev
        opcost = (r["cost_of_goods_sold"] + r["payroll"] + r["marketing"]
                  + r["lease_rent"] + r["general_and_administrative"])
        if opcost:
            D[f"cash_months_of_operating_cost_y{y}"] = r["cash"] / (opcost / 12)
        D[f"receivable_days_y{y}"] = r["accounts_receivable"] / rev * 365
        if r["cost_of_goods_sold"]:
            D[f"inventory_days_y{y}"] = r["inventory"] / r["cost_of_goods_sold"] * 365
            D[f"payable_days_y{y}"] = (r["accounts_payable"]
                                       / r["cost_of_goods_sold"] * 365)
        # a debt-free year has no service and no coverage ratio - absent,
        # never a divide-by-zero and never a fabricated "infinite" coverage
        ds_act = r["debt_repayment"] + r["lease_principal_repayments"] + r["interest"]
        ds_sch = ann_prin + r["lease_principal_repayments"] + r["interest"]
        if ds_act:
            D[f"debt_service_actual_y{y}"] = ds_act
            D[f"dscr_actual_y{y}"] = r["ebitda"] / ds_act
        if ds_sch:
            D[f"debt_service_scheduled_y{y}"] = ds_sch
            D[f"dscr_scheduled_y{y}"] = r["ebitda"] / ds_sch
        if n_emp:
            D[f"revenue_per_employee_stated_headcount_y{y}"] = rev / n_emp
        # Item 7 / R4 (Nick, 2026-09-09): the SDE add-back is EVERY
        # owner's pay - the SUM over the owner-titled people rows, the same
        # set and the same source as the workbook's Valuation sheet, so the
        # docx and the workbook agree and neither depends on row order. A
        # roster with no owner-titled row falls back to the legacy mirror
        # (x12), as before.
        if owner_pay_annual is not None:
            D[f"sde_y{y}"] = (owner_pay_annual * 1.03 ** (y - 1)
                              + r["net_income"] + r["interest"]
                              + r["depreciation"] + r["taxes"])

    # planned units per year, from the marketing schedule's own quarters
    # (2026-09-08): five years of revenue with one year of units invited
    # revenue-over-held-price arithmetic that overstates late years by 40%
    # - the model escalates price. The real path exists; the bundle now
    # carries it, so a five-year units column fills from held data.
    ms = _jl(draft.get("marketing_schedule_json")) or {}
    mper = [p for p in (ms.get("periods") or []) if not p.get("is_stub")]
    for y in range(5):
        grp = [p for p in mper if y * 4 < int(p.get("period_index") or 0) <= (y + 1) * 4]
        if len(grp) == 4 and all(p.get("units") is not None for p in grp):
            D[f"planned_units_y{y + 1}"] = round(sum(float(p["units"]) for p in grp))

    D["capex_total_y1_y5"] = sum(r["capital_expenditures"] for r in A)
    D["distributions_total_y1_y5"] = sum(r["owner_distributions"] for r in A)
    if Q:
        trough = min(Q, key=lambda q: q["ending_cash"])
        D["cash_trough_amount"] = trough["ending_cash"]
        D["cash_trough_quarter"] = int(trough["quarter_index"])
        D["cash_trough_date"] = trough["date"]
        fd = next((q for q in Q if (q.get("owner_distributions") or 0) > 0), None)
        if fd:
            D["first_distribution_quarter"] = int(fd["quarter_index"])
    # "retired" presumes the debt EXISTED - a never-borrowed business hits
    # closing_debt==0 in Q1 and must not grow a phantom retirement (the
    # Bellamy cash chart said "term loan retired" for a loan that never was)
    debt_ever = any((r.get("opening_debt") or 0) > 0 or (r.get("closing_debt") or 0) > 0
                    for r in DSch)
    retired = next((r for r in DSch if r["closing_debt"] == 0), None) if debt_ever else None
    if retired:
        D["debt_retired_quarter"] = int(retired["quarter_index"])
        D["debt_retired_date"] = retired["date"]
    D["new_borrowing_total"] = sum(r.get("actual_debt_issuance") or 0 for r in DSch)
    nb = next((r for r in DSch if (r.get("actual_debt_issuance") or 0) > 0), None)
    if nb:
        D["new_borrowing_quarter"] = int(nb["quarter_index"])

    y1a, y5a = BE.get("y1_annualized") or {}, BE.get("y5_annualized") or {}
    if y1a:
        D["break_even_revenue_y1"] = y1a["be_revenue"]
        D["cash_break_even_revenue_y1"] = y1a["cash_be_revenue"]
        D["fixed_costs_y1"] = y1a["fixed_costs"]
        D["contribution_margin_ratio_y1"] = y1a["cm_ratio"]
        D["margin_of_safety_y1"] = y1a["margin_of_safety"]
    if y5a:
        D["break_even_revenue_y5"] = y5a["be_revenue"]
        D["margin_of_safety_y5"] = y5a["margin_of_safety"]

    for pl in BEPL:
        s = _SLUG(pl.get("lob"))
        D[f"{s}_q1_units_planned"] = pl["units_planned"]
        D[f"{s}_q1_break_even_units"] = pl["be_units"]
        D[f"{s}_contribution_per_unit"] = pl["cm_per_unit"]
        D[f"{s}_mix_share_y1"] = pl["mix_share"]

    cogs_by_lob = {pl.get("lob"): pl.get("cogs_pct") for pl in BEPL}
    lobs = FY1.get("lobs") or []
    company_rev = FY1.get("company_revenue_total_year1")
    gps: Dict[str, float] = {}
    for lob in lobs:
        name, s = lob.get("lob_name"), _SLUG(lob.get("lob_name"))
        rev = lob.get("revenue_total_year1")
        if rev is None:
            continue
        D[f"{s}_revenue_y1"] = rev
        prods = lob.get("products") or []
        if prods and prods[0].get("annual_units_year1") is not None:
            D[f"{s}_units_y1"] = prods[0]["annual_units_year1"]
        if company_rev:
            D[f"{s}_revenue_share_y1"] = rev / company_rev
        if cogs_by_lob.get(name) is not None:
            gps[s] = rev * (1 - cogs_by_lob[name])
            D[f"{s}_gross_profit_y1"] = gps[s]
    total_gp = sum(gps.values())
    for s, gp in gps.items():
        D[f"{s}_gross_profit_share_y1"] = gp / total_gp

    band = ((F.get("_coherence") or {}).get("margin_band_judgment") or {}).get("q11") or {}
    if band.get("high") is not None:
        D["sensitivity_ebitda_at_band_high_y1"] = band["high"] * A[0]["revenue"]
        D["sensitivity_ebitda_at_band_low_y1"] = band["low"] * A[0]["revenue"]
        if D.get("debt_service_scheduled_y1"):
            D["sensitivity_dscr_at_band_high_y1"] = (
                band["high"] * A[0]["revenue"] / D["debt_service_scheduled_y1"])
            D["sensitivity_dscr_at_band_low_y1"] = (
                band["low"] * A[0]["revenue"] / D["debt_service_scheduled_y1"])

    # ---- the pinned transcript family (hand-labeled, per business) --------
    pin = next((v for k, v in PIN.items()
                if str(draft.get("draft_id", "")).startswith(k)), None)
    loaded = None
    if F.get("payroll_total_year1") is not None:
        D["model_payroll_y1"] = A[0]["payroll"]
        D["stated_total_wages_annual"] = float(F["payroll_total_year1"])
        loaded = float(F["payroll_total_year1"]) * 1.22
        D["stated_total_wages_loaded_at_22pct"] = loaded
    rest = (record.get("people") or {}).get("rest_of_team_payroll_year1")
    if rest is not None:
        D["stated_rest_of_team_wages_annual"] = rest
    if F.get("annual_interest_payment") and F.get("total_debt_outstanding"):
        D["stated_interest_rate_implied"] = (F["annual_interest_payment"]
                                             / F["total_debt_outstanding"])
    if DSch:
        D["model_loan_annual_rate"] = DSch[0].get("annual_interest_rate")
    if pin:
        base, monthly = pin["stated_cost_base"], pin["stated_cost_monthly"]
        D[f"{base}_monthly"] = monthly
        D[f"{base}_annual"] = monthly * 12
        if F.get("current_revenue"):
            D[f"{base}_pct_of_stated_revenue"] = monthly * 12 / F["current_revenue"]
        if loaded is not None:
            after = A[0]["ebitda"] - monthly * 12 - (loaded - A[0]["payroll"])
            D["ebitda_y1_after_stated_omissions"] = after
            D["ebitda_margin_y1_after_stated_omissions"] = after / A[0]["revenue"]
            D["dscr_scheduled_y1_after_stated_omissions"] = (
                after / D["debt_service_scheduled_y1"])
        prod_by_lob = {l.get("lob_name"): (l.get("products") or [{}])[0]
                       for l in lobs}
        cap_field = {"weekly": "units_per_week_capacity",
                     "monthly": "units_per_month_capacity"}
        stated_caps = {"dtc": 370, "wholesale": 12, "subscription": 400}
        for label, cadence, lob_name in pin["capacity"]:
            D[f"stated_capacity_{label}_{cadence}"] = stated_caps[label]
            D[f"model_capacity_{label}_{cadence}"] = (
                prod_by_lob.get(lob_name, {}).get(cap_field[cadence]))
        D.update(pin["stated_scalars"])
        ar_line = _SLUG(pin["ar_days_line"])
        if F.get("ar_balance") and D.get(f"{ar_line}_revenue_y1"):
            D["stated_ar_days_on_wholesale_revenue"] = (
                F["ar_balance"] / D[f"{ar_line}_revenue_y1"] * 365)

    for src, dst in (("marketing_total_year1", "stated_marketing_annual"),
                     ("marketing_percent_of_revenue", "stated_marketing_pct_revenue"),
                     ("baseline_marketing_percent", "judged_baseline_marketing_pct")):
        if F.get(src) is not None:
            D[dst] = F[src]
    for src, dst in (("expected_customers_or_clients_year1", "expected_customers_y1"),
                     ("expected_units_year1", "expected_units_y1"),
                     ("reachable_market", "reachable_market"),
                     ("capture_rate_year1", "capture_rate_y1")):
        if MM.get(src) is not None:
            D[dst] = MM[src]
    D["model_marketing_y1"] = A[0]["marketing"]

    vrc = warehouse.get("valuation_reference_constants") or []
    sde_row = next((r for r in vrc if r.get("constant_key") == "exit_multiple_sde"
                    and r.get("applies_to") == "ALL"), None)
    if sde_row and "sde_y1" in D:
        lo, df, hi = (float(sde_row["value_min"]), float(sde_row["value_default"]),
                      float(sde_row["value_max"]))
        D["sde_multiple_default"], D["sde_multiple_low"], D["sde_multiple_high"] = df, lo, hi
        D["indicative_value_at_default_multiple_y1"] = D["sde_y1"] * df
        D["indicative_value_low_y1"] = D["sde_y1"] * lo
        D["indicative_value_high_y1"] = D["sde_y1"] * hi

    if Q and len(Q) >= 11 and band.get("low") is not None \
            and F.get("total_debt_outstanding") is not None:
        R = Q[10]["revenue"]
        ceiling = round(band["low"] * R / 1.5 * 4 / 0.1)
        D["debt_ceiling_additional"] = ceiling - int(F["total_debt_outstanding"])
        D["debt_serviceability"] = {
            "judged_q11_band_low": band["low"],
            "projected_q11_revenue": round(R),
            "coverage_floor": 1.5,
            "annual_rate_decimal": 0.1,
            "max_serviceable_quarterly_interest": round(band["low"] * R / 1.5),
            "serviceable_principal_ceiling": ceiling,
            "opening_debt_counted": F["total_debt_outstanding"],
            "additional_debt_cap": ceiling - int(F["total_debt_outstanding"]),
            "rule": ("debt stops where its interest would exceed what the "
                     "executive-judged believable margin can service at the "
                     "lender coverage floor; owner equity funds the remainder"),
        }
    return D
