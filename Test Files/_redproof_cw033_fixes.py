"""CW-033 offline proof, POST-RETRACTION SHAPE. A-113 is retracted
(Nick, 2026-08-14): the interview region no longer lands post-stage
driver corrections - it redirects honestly (see the live proof). What
this file still proves at the function level: the cross-section applier
itself is correct for the surfaces that keep it (T1-T3), the forward
move can never fabricate a receipt or write a wrong line (T4-T6), the
A-115 kind-misread and capex fixes (T7-T8), and the reconcile-by-design
carries its provenance stamp (T9).

THE PRODUCTION CALL CHAIN (named first, per the E2E law):
  POST /api/intake-consult (focus=financials, interview region
  ~intake_consult.py:16100) -> _run_financials_turn_and_sync [wrapper]
    -> _apply_cross_section_driver_correction  <- the door that was never
       wired into the interview region (A-113 root)
    -> _run_financials_turn_and_sync_inner -> route_intent -> stage doors
    -> _unlanded_figures_disclosure -> _apply_forward_move
    -> _apply_scoped_patch (ops driver writes)
  Build half: post_intake_headcount.deterministic_revenue_proposer
  (anchor_scale) + finmo_bridge (stub_scale_factor).

RED PROTOCOL: run this file at the PRE-FIX tree (git stash) - T1/T2/T4/T5/
T7/T8 go red for the A-113/A-115 reasons; run at the fixed tree - all
green. Both outputs are the turn's artifact.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw033_fixes.py"
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers import intake_consult as ic  # noqa: E402
from client_intake_and_finmo.post_intake_headcount.deterministic_revenue_proposer import (  # noqa: E402
    propose_revenue_drivers_deterministic,
)

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def thornfield_ops() -> dict:
    return {
        "lob_models": [
            {"lob_name": "Plant and nursery sales", "products": [
                {"product_name": "Plant and nursery sale", "unit_price": 52.0,
                 "units_per_week_capacity": 340.0, "units_per_period_capacity": 340.0,
                 "utilization_rate": 0.62, "operating_periods_per_year": 52,
                 "unit_cadence": "weekly"}]},
            {"lob_name": "Hard goods retail", "products": [
                {"product_name": "Hard goods sale", "unit_price": 95.0,
                 "units_per_week_capacity": 165.0, "units_per_period_capacity": 165.0,
                 "utilization_rate": 0.57, "operating_periods_per_year": 52,
                 "unit_cadence": "weekly"}]},
            {"lob_name": "Landscaping and installation services", "products": [
                {"product_name": "Landscaping/installation job", "unit_price": 2400.0,
                 "units_per_week_capacity": 5.0, "units_per_period_capacity": 5.0,
                 "utilization_rate": 0.66, "operating_periods_per_year": 52,
                 "unit_cadence": "weekly"}]},
            {"lob_name": "Garden design and consultation", "products": [
                {"product_name": "Design/consultation project", "unit_price": 1250.0,
                 "units_per_week_capacity": 3.0, "units_per_period_capacity": 3.0,
                 "utilization_rate": 0.6, "operating_periods_per_year": 52,
                 "unit_cadence": "weekly"}]},
        ]
    }


def rows_cap(ops: dict) -> dict:
    return {
        p["product_name"]: (p.get("units_per_week_capacity"),
                            p.get("units_per_period_capacity"))
        for l in ops["lob_models"] for p in l["products"]
    }


M99 = ("About 3,100 a month on those. And one thing I need to fix from "
       "earlier - I said we can do 5 install jobs a week, but that was me "
       "thinking of two crews. We're running three crews now, so the "
       "install line's weekly capacity should be 7 jobs, not 5. Everything "
       "else stays as it is.")
M107 = ("Before I answer that - please go back and fix the install line. "
        "Its weekly capacity is wrong. It is currently set to five jobs "
        "per week and it needs to be seven jobs per week, because we run "
        "three crews now. Do not change any other line.")
M111 = ("Accounts payable about 121,000. Also, set the landscaping and "
        "installation line weekly capacity to seven jobs per week.")

print("T1 - the applier lands all three REAL Thornfield wordings on the "
      "NAMED line (A-113)")
for name, msg in (("attempt1-bundled[99]", M99),
                  ("attempt2-both-values[107]", M107),
                  ("attempt3-single-number[111]", M111)):
    rep: dict = {}
    res = ic._apply_cross_section_driver_correction(
        ops_json=thornfield_ops(), user_message=msg, report=rep)
    if res is None:
        check(f"{name} lands", False, f"returned None, report={rep}")
        continue
    ops_after, ack = res
    caps = rows_cap(ops_after)
    check(f"{name} lands install=7 on BOTH capacity cells",
          caps["Landscaping/installation job"] == (7.0, 7.0), str(caps))
    check(f"{name} leaves the other three lines untouched",
          caps["Plant and nursery sale"] == (340.0, 340.0)
          and caps["Hard goods sale"] == (165.0, 165.0)
          and caps["Design/consultation project"] == (3.0, 3.0), "")
    check(f"{name} ack speaks 7, never the corrected-away-from 5",
          "7" in ack and "capacity to 5" not in ack, ack[:90])
    check(f"{name} reports consumed figures incl. old value",
          7.0 in (rep.get("consumed_figures") or [])
          and 5.0 in (rep.get("consumed_figures") or []),
          str(rep.get("consumed_figures")))

print("\nT2 - correction-shaped but unresolvable product REFUSES out loud, "
      "never guesses")
rep2: dict = {}
res2 = ic._apply_cross_section_driver_correction(
    ops_json=thornfield_ops(),
    user_message="Go back and fix that capacity, it should be 9 a week.",
    report=rep2)
check("no line named -> None (no write)", res2 is None, "")
check("...but the refusal is REPORTED (triggered_leaf)",
      bool(rep2.get("triggered_leaf")), str(rep2))
rep2b: dict = {}
res2b = ic._apply_cross_section_driver_correction(
    ops_json=thornfield_ops(),
    user_message="Fix the plant and hard goods lines capacity to 9 a week.",
    report=rep2b)
check("ambiguous (two lines tie) -> None, reported ambiguous",
      res2b is None and rep2b.get("product_unresolved") == "ambiguous",
      str(rep2b))

print("\nT3 - wrong-line safety: a correction naming design never touches "
      "install")
res3 = ic._apply_cross_section_driver_correction(
    ops_json=thornfield_ops(),
    user_message="Set the design consultation line capacity to 4 a week.",
    report={})
if res3 is None:
    check("design correction lands", False, "returned None")
else:
    caps3 = rows_cap(res3[0])
    check("design row carries 4, install untouched",
          caps3["Design/consultation project"][0] == 4.0
          and caps3["Landscaping/installation job"] == (5.0, 5.0), str(caps3))

print("\nT4 - forward-move ops branch: resolved line -> truthful receipt; "
      "unresolved -> honest refusal, NO 'Recorded:', NO write")
shared4 = {"operating_model": thornfield_ops(), "people_capability": {}}
move4 = {"key": "ops.units_per_period_capacity", "value": 7.0,
         "label": "capacity", "attributed": True}
_fin4, sh4, copy4 = ic._apply_forward_move(
    move=move4, stage_shared_context=shared4, next_financials={},
    financials_year1_json={}, conn=None, intake_context={},
    user_message=M99, last_assistant="")
caps4 = rows_cap(sh4["operating_model"])
check("named line: receipt names the line and speaks the read-back",
      copy4.startswith("Recorded:") and "Landscaping/installation job" in copy4,
      copy4[:90])
check("named line: the write is REAL (install 7, others untouched)",
      caps4["Landscaping/installation job"] == (7.0, 7.0)
      and caps4["Plant and nursery sale"] == (340.0, 340.0), str(caps4))
shared4b = {"operating_model": thornfield_ops(), "people_capability": {}}
_fin4b, sh4b, copy4b = ic._apply_forward_move(
    move=dict(move4), stage_shared_context=shared4b, next_financials={},
    financials_year1_json={}, conn=None, intake_context={},
    user_message="The weekly capacity should be 7.", last_assistant="")
caps4b = rows_cap(sh4b["operating_model"])
check("no line named on a multi-line model: NO 'Recorded:', asks which line",
      "Recorded:" not in copy4b and "which line" in copy4b, copy4b[:110])
check("no line named: nothing written anywhere",
      caps4b == rows_cap(thornfield_ops())
      and not [k for k in sh4b["operating_model"] if k not in
               ("lob_models",)], str(caps4b))

print("\nT5 - _apply_scoped_patch: bare driver key on a multi-line model "
      "is DROPPED (no dead flat write)")
ops5 = thornfield_ops()
_b5, ops5_after, _m5, _p5, fin5, _f5 = ic._apply_scoped_patch(
    {"ops.units_per_week_capacity": 7.0}, business_facts={}, ops_json=ops5,
    market_json={}, people_json={}, financials_json={}, fulfillment_json={})
check("no flat driver key written",
      "units_per_week_capacity" not in ops5_after, str(
          {k: v for k, v in ops5_after.items() if k != "lob_models"}))
check("no row changed", rows_cap(ops5_after) == rows_cap(thornfield_ops()), "")

print("\nT6 - single-line models keep the row landing (no regression)")
single = {"lob_models": [{"lob_name": "Cleaning", "products": [
    {"product_name": "Standard clean", "unit_price": 150.0,
     "units_per_week_capacity": 20.0, "units_per_period_capacity": 20.0,
     "utilization_rate": 0.8, "operating_periods_per_year": 52,
     "unit_cadence": "weekly"}]}]}
_b6, ops6_after, _m6, _p6, fin6, _f6 = ic._apply_scoped_patch(
    {"ops.units_per_week_capacity": 25.0}, business_facts={},
    ops_json=copy.deepcopy(single), market_json={}, people_json={},
    financials_json={}, fulfillment_json={})
check("single-line bare driver write still lands on the row",
      ops6_after["lob_models"][0]["products"][0]["units_per_week_capacity"] == 25.0,
      "")

print("\nT7 - A-115(a): a percent-shaped figure is never re-typed as a "
      "price / count / dollar field")
collapse_msg = ("The plants and hard goods lines share one cost structure - "
                "call it one shared rate at 58 percent of revenue for both.")
mv7 = ic._infer_figure_landing(
    figure=58.0, user_message=collapse_msg,
    financials_json={}, people_json={}, ops_json=thornfield_ops())
check("'one shared rate at 58 percent' -> NO move (percent belongs to the "
      "percent doors)", mv7 is None, str(mv7))
mv7b = ic._infer_figure_landing(
    figure=2600.0, user_message="the charge is 2,600 per job now",
    financials_json={}, people_json={}, ops_json=thornfield_ops())
check("a real price statement still attributes to unit price",
      (mv7b or {}).get("key") == "ops.unit_price", str(mv7b))
_fin7, _txt7, mv7c = ic._unlanded_figures_disclosure(
    next_financials={"_per_line_cogs_receipt": {
        "wrote": True,
        "written": [{"line_name": "Plant and nursery sale", "value": 0.58},
                    {"line_name": "Hard goods sale", "value": 0.58}]}},
    stage_shared_context={"operating_model": thornfield_ops(),
                          "people_capability": {}},
    user_message=collapse_msg, last_assistant="")
check("a figure the per-line COGS door consumed never resurfaces as a move",
      mv7c is None, str(mv7c))

print("\nT8 - A-115(b): the capex explicit-no + excluded figure stores ZERO")
M89 = ("Not recently, no. The big stuff was bought over the years - we've "
       "got about 380,000 worth of trucks, a skid steer, the greenhouse "
       "structures, benching, irrigation and yard equipment sitting there, "
       "but none of it was bought this year.")
n8 = ic._normalize_financials_router_patch(
    patch={"financials.current_capex": 380000}, active_stage="current_capex",
    financials_json={"_financials_stage_state": {}}, financials_year1_json={},
    last_assistant="Have you recently made any larger one-time purchases?",
    user_message=M89)
check("the real [89] wording stores current_capex 0",
      n8 is not None and n8.get("current_capex") == 0.0,
      str((n8 or {}).get("current_capex")))
_fin8, _txt8, mv8 = ic._unlanded_figures_disclosure(
    next_financials=dict(n8 or {}),
    stage_shared_context={"operating_model": {}, "people_capability": {
        "rest_of_team_payroll_year1": 330000.0}},
    user_message=M89, last_assistant="")
check("the excluded 380k never becomes a forward move (no rest-of-team "
      "proposal)", mv8 is None, str(mv8))
n8b = ic._normalize_financials_router_patch(
    patch={"financials.current_capex": 20000}, active_stage="current_capex",
    financials_json={"_financials_stage_state": {}}, financials_year1_json={},
    last_assistant="Have you recently made any larger one-time purchases?",
    user_message="Yes - about 20,000 on a new mower this spring.")
check("a positive answer still lands",
      n8b is not None and n8b.get("current_capex") == 20000.0, "")
n8c = ic._normalize_financials_router_patch(
    patch={"financials.current_capex": 380000}, active_stage="current_capex",
    financials_json={"_financials_stage_state": {}}, financials_year1_json={},
    last_assistant="Have you recently made any larger one-time purchases?",
    user_message="No wait, actually it was 380,000 this year.")
check("a correction shape ('No wait...') is never overridden to zero",
      n8c is not None and n8c.get("current_capex") == 380000.0, "")
check("a stray ops move is SUPPRESSED on an applier-triggered turn",
      ic._strip_suppressed_ops_move(
          {"key": "ops.units_per_period_capacity", "value": 1.0,
           "label": "capacity", "attributed": True}, True) is None
      and ic._strip_suppressed_ops_move(
          {"key": "financials.ap_balance", "value": 121000.0,
           "label": "accounts payable", "attributed": True}, True) is not None,
      "ops stripped, non-ops untouched")

print("\nT9 - the reconcile stands BY DESIGN (Nick's retraction ruling) and "
      "is stamped, never silent")
REF = [
    {"lob": "Plants", "unit": "ticket", "capacity_units_per_period": 4420.0,
     "unit_price": 52.0, "utilization_rate": 0.62},
    {"lob": "Hard goods", "unit": "ticket", "capacity_units_per_period": 2145.0,
     "unit_price": 95.0, "utilization_rate": 0.57},
    {"lob": "Install", "unit": "job", "capacity_units_per_period": 91.0,
     "unit_price": 2400.0, "utilization_rate": 0.66},
    {"lob": "Design", "unit": "project", "capacity_units_per_period": 39.0,
     "unit_price": 1250.0, "utilization_rate": 0.6},
]
bottom_up = sum(r["capacity_units_per_period"] * r["unit_price"]
                * r["utilization_rate"] for r in REF)
r9 = propose_revenue_drivers_deterministic(
    current_revenue_reference=copy.deepcopy(REF),
    anchor_q1_revenue_total=bottom_up * 1.00105)
q1caps = [ln["quarters"][0]["capacity_units_per_period"]
          for ln in r9["drivers"]["lines_of_business"]]
check("any gap: the stated-revenue anchor governs (reconcile is design)",
      abs(q1caps[0] / 4420.0 - 1.00105) < 1e-6, str(q1caps[:1]))
check("any gap: the factor is STAMPED, never silent",
      abs(((r9["drivers"].get("anchor_reconcile") or {}).get("factor") or 0)
          - 1.00105) < 1e-6, str(r9["drivers"].get("anchor_reconcile")))
r9b = propose_revenue_drivers_deterministic(
    current_revenue_reference=copy.deepcopy(REF),
    anchor_q1_revenue_total=bottom_up * 1.106527)
q1caps_b = [ln["quarters"][0]["capacity_units_per_period"]
            for ln in r9b["drivers"]["lines_of_business"]]
stamp = (r9b["drivers"].get("anchor_reconcile") or {})
check("10.65% gap: the stated-revenue anchor governs",
      abs(q1caps_b[0] / 4420.0 - 1.106527) < 1e-6, str(q1caps_b[:1]))
check("10.65% gap: the factor is STAMPED, never silent",
      abs((stamp.get("factor") or 0) - 1.106527) < 1e-6
      and stamp.get("basis") == "stated_revenue_anchor", str(stamp))
r9c = propose_revenue_drivers_deterministic(
    current_revenue_reference=copy.deepcopy(REF),
    anchor_q1_revenue_total=bottom_up)
check("exact match: factor 1, no stamp",
      "anchor_reconcile" not in r9c["drivers"], "")

print()
if FAILURES:
    print(f"RESULT: RED - {len(FAILURES)} failing check(s):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("RESULT: GREEN - all checks passed")
