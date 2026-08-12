# -*- coding: utf-8 -*-
"""UNIVERSAL ENGINE PHASE 1 RED-PROOF (capacity under the engine).

  P1  DIVERGENCE UNREPRESENTABLE: canonical-per-cadence derivation at
      the canonical pass - weekly AND contract cadence
  P2  ADOPT-ONCE: a legacy row carrying only the mirror side adopts a
      canonical value, then derives
  P3  THE FERNHILL ROUND-TRIP (property 3, PERSISTENCE): "Capacity,
      80." lands on the canonical cell, PERSISTS, and the next read
      from SQL shows 80 - then the gate's conflict check reconciles
      instead of re-firing (write -> survive -> read-back-correct)
  P4  PRODUCT-PATTERN [87]: "4 people x 20 days = 80... that is the
      capacity number" lands 80, never 20
  P5  NO-OP RECEIPT: an echo write (capacity already 80) never says
      "Recorded:"
  P6  PIN ESCALATION: the operand message cannot repeat verbatim - the
      second repeat escalates to the direct set
  P7  POSITIVE invariant: weekly-cadence capacity statements still
      land ("185 per week" -> week canonical; "40 jobs a week" works)
  P8  MULTI-PRODUCT: derivation covers every row, not just single-
      product models

Protocol: RED on 909f66f (the live bugs), GREEN on the fix.
"""
import copy
import io
import sys
import uuid

sys.path.insert(0, "C:/dev/business_plann_app/python")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv("C:/dev/business_plann_app/.env")

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


def guarded(label, fn):
    try:
        check(label, bool(fn()))
    except Exception as exc:
        check(label + f"  [EXC {type(exc).__name__}: {exc}]", False)


import api_handlers.intake_consult as ic  # noqa: E402
from api_handlers.intake_consult import (  # noqa: E402
    _run_financials_turn_and_sync,
    _next_financials_stage,
    _ensure_financials_stage_defaults,
)
from client_intake_and_finmo.intake_submission import get_mysql_connection  # noqa: E402
from client_intake_and_finmo.intake_consult_draft import (  # noqa: E402
    create_draft, append_messages, get_draft,
)
import json  # noqa: E402

FERN_OPS = {
    "business_naics_6": "541611",
    "lob_models": [{"lob_name": "Consulting", "products": [{
        "product_name": "unit", "unit_name": "consulting day",
        "unit_price": 2400.0, "unit_cadence": "contract",
        "units_per_week_capacity": 80.0,
        "units_per_period_capacity": 45.0,
        "operating_periods_per_year": 12.0,
        "utilization_rate": 0.65}]}],
}
FERN_PEOPLE = {
    "people": [
        {"full_name": "Odette Marchetti", "role_title": "Owner / Principal",
         "annual_wage": 180000.0, "wage_source": "client_override"},
        {"full_name": "Bram Sikorski", "role_title": "Senior Consultant",
         "annual_wage": 145000.0, "wage_source": "client_override"},
    ],
    "rest_of_team_payroll_year1": 296000.0,
}
_conn = get_mysql_connection()


class SpyRouter:
    def __init__(self, ret):
        self.ret = ret

    def __call__(self, **kw):
        return copy.deepcopy(self.ret)


READONLY = {"action": "answer_readonly", "assistant_message": "", "patch": None}


def _fern_fin(missing=None):
    base = {
        "current_revenue": 1497000.0, "cogs_percent_of_revenue": 0.02,
        "cogs_basis": "ratio", "current_cogs": 29940.0,
        "cogs_total_year1": 29940.0, "current_payroll": 621000.0,
        "current_num_employees": 5, "marketing_total_year1": 24000.0,
        "monthly_rent_expense": 4100.0, "gna_total_year1": 60000.0,
        "capex_total_year1": 0.0, "initial_assets": 40000.0,
        "initial_lease": 0.0, "total_debt_outstanding": 0.0,
        "other_monthly_debt_payments": 0.0,
        "annual_interest_payment": 0.0,
        "annual_principal_payment": 0.0, "cash_on_hand": 90000.0,
        "ar_balance": 120000.0, "ap_balance": 30000.0,
        "inventory_balance": 0.0, "cash_strategy": "preserve_cash",
        "funding_preference": "debt",
        "_financials_revenue_intro_done": True,
        "_financials_marketing_stage_done": True,
    }
    fin = _ensure_financials_stage_defaults(base)
    for st in list(getattr(ic, "_FINANCIALS_STAGE_ORDER", ())):
        spec = ic._financials_stage_spec(st)
        for f in (spec.get("completion_fields") or ()):
            if fin.get(f) is None:
                fin[f] = 1.0
    for k in (missing or []):
        fin.pop(k, None)
    return fin


def _mk_draft(fin, ops, people=None):
    d = create_draft(_conn, client_id=f"rp30{uuid.uuid4().hex[:8]}")
    did = str(d.get("draft_id") or "").strip()
    append_messages(_conn, draft_id=did, new_messages=[],
                    people_json=copy.deepcopy(people or FERN_PEOPLE),
                    financials_json=fin,
                    operating_model_json=copy.deepcopy(ops),
                    active_focus="financials")
    return did


def _turn(did, message, router, fin, ops, people=None, last=""):
    shared = {"people_capability": copy.deepcopy(people or FERN_PEOPLE),
              "operating_model": ops, "marketing": {}}
    turn, fin_out = _run_financials_turn_and_sync(
        route_intent=router, conn=_conn,
        intake_context={"draft_id": did},
        conversation_messages=[{"role": "assistant", "content": last}],
        business_facts={"name": "Fernhill Advisory"},
        shared_context=shared,
        last_assistant=last,
        user_message=message,
        financials_json=fin,
        financials_year1_json={"company_revenue_total_year1": 1497000.0},
    )
    return turn, fin_out, shared


def _db_ops(did):
    row = get_draft(_conn, draft_id=did)
    return json.loads(row.get("operating_model_json") or "{}")


def _row0(ops):
    return ((ops.get("lob_models") or [{}])[0].get("products") or [{}])[0]


# P1 --- divergence unrepresentable, both cadences
def p1():
    ops_w = {"lob_models": [{"products": [{
        "unit_cadence": "weekly", "units_per_week_capacity": 185.0,
        "units_per_period_capacity": 2.0, "operating_periods_per_year": 52.0}]}]}
    ic._derive_capacity_cells(ops_w)
    r = _row0(ops_w)
    if abs(float(r["units_per_period_capacity"]) - 185.0) > 1e-6:
        return False
    ops_c = copy.deepcopy(FERN_OPS)
    ic._derive_capacity_cells(ops_c)
    r = _row0(ops_c)
    want_wk = 45.0 * 12.0 / 52.0
    return abs(float(r["units_per_week_capacity"]) - want_wk) < 0.01


guarded("P1 DIVERGENCE UNREPRESENTABLE: weekly per:=week; contract week derives per*periods/52", p1)


# P2 --- adopt-once for legacy mirror-only rows
def p2():
    ops = {"lob_models": [{"products": [{
        "unit_cadence": "contract", "units_per_week_capacity": 12.0,
        "operating_periods_per_year": 12.0}]}]}
    ic._derive_capacity_cells(ops)
    r = _row0(ops)
    return abs(float(r.get("units_per_period_capacity") or 0) - 52.0) < 0.01


guarded("P2 ADOPT-ONCE: a mirror-only legacy row gains its canonical cell", p2)


# P3 --- THE FERNHILL ROUND-TRIP (write -> survive -> read-back)
def p3():
    fin = _fern_fin()
    if _next_financials_stage(fin) is not None:
        print("  (P3 setup: not completed-state:", _next_financials_stage(fin), ")")
        return False
    ops = copy.deepcopy(FERN_OPS)
    did = _mk_draft(fin, ops)
    turn, fin_out, shared = _turn(
        did, "Capacity, 80.", SpyRouter(READONLY), fin, ops,
        last=("Before I run the final checks, one thing doesn't add up: your "
              "stated annual revenue ($1,497,000) is more than your operation "
              "can physically produce even flat-out - at your stated capacity "
              "and prices, 100% utilization tops out around $1,296,000 a year."))
    msg = str((turn or {}).get("assistant_message") or "")
    if "capacity" not in msg.lower() or "80" not in msg:
        print(f"  (P3 no landing receipt: {msg[:140]!r})")
        return False
    # THE LIVE MECHANISM (the Fernhill persist seam): after the turn
    # function returns, the HANDLER persists sections from ITS OWN
    # references. If the landing went to a rebound copy instead of
    # mutating through, this persist carries the stale object and the
    # landing evaporates - three receipted corrections died here.
    append_messages(_conn, draft_id=did, new_messages=[],
                    operating_model_json=ops)
    db = _db_ops(did)
    r = _row0(db)
    per = float(r.get("units_per_period_capacity") or 0)
    if abs(per - 80.0) > 1e-6:
        print(f"  (P3 SQL read-back: period = {per!r}, want 80 - the landing "
              "did not survive)")
        return False
    from client_intake_and_finmo.intake_coherence import section as sec
    fin2 = dict(fin_out)
    t2, fin3, _ = sec.gate_and_turn(
        ops_json=db, people_json=copy.deepcopy(FERN_PEOPLE), market_json={},
        marketing_model_json={}, financials_json=fin2,
        financials_year1_json={}, user_text="")
    m2 = str((t2 or {}).get("assistant_message") or "")
    return "doesn't add up" not in m2


guarded("P3 FERNHILL ROUND-TRIP: 'Capacity, 80.' lands canonical, SURVIVES to SQL, the conflict clears", p3)


# P4 --- product-pattern figure selection [87]
def p4():
    fin = _fern_fin()
    ops = copy.deepcopy(FERN_OPS)
    did = _mk_draft(fin, ops)
    turn, fin_out, shared = _turn(
        did,
        "My four billable people can each deliver about 20 billable days in "
        "a month, so the team can put out about 80 billable days a month. "
        "That is the capacity number.",
        SpyRouter(READONLY), fin, ops,
        last="Which of those stored numbers is wrong?")
    msg = str((turn or {}).get("assistant_message") or "")
    return "80" in msg and "capacity 20" not in msg.lower()


guarded("P4 PRODUCT-PATTERN [87]: 4 x 20 = 80 lands the TOTAL, never the factor", p4)


# P5 --- no-op writes never receipt (the LIVE Fernhill shape: the
# people-door echo - "Recorded: total team payroll $621,000" on a
# stated total equal to the stored rollup. A capacity-echo fixture is
# vacuous on old code: the restatement skip already suppressed it
# before the mover ran, and the crash-red variant proves nothing.)
def p5():
    fin = _fern_fin()
    ops = copy.deepcopy(FERN_OPS)
    did = _mk_draft(fin, ops)
    door = {"action": "edit_patch", "assistant_message": "",
            "patch": {"people.total_team_payroll": 621000}}
    turn, fin_out, shared = _turn(
        did, "My total payroll is $621,000, as I said.",
        SpyRouter(door), fin, ops,
        last="Which of those stored numbers is wrong?")
    msg = str((turn or {}).get("assistant_message") or "")
    return "Recorded:" not in msg


guarded("P5 NO-OP RECEIPT: an echo write (already 80) never says Recorded:", p5)


# P6 --- pin escalation: repeat-of-repeat differs
def p6():
    from client_intake_and_finmo.intake_coherence import section as sec
    ops = copy.deepcopy(FERN_OPS)
    fin = {"current_revenue": 1497000.0, "_financials_revenue_intro_done": True}
    msgs = []
    for i in range(3):
        t, fin, _ = sec.gate_and_turn(
            ops_json=ops, people_json={}, market_json={},
            marketing_model_json={}, financials_json=dict(fin),
            financials_year1_json={}, user_text="hm.")
        msgs.append(str((t or {}).get("assistant_message") or ""))
    if "doesn't add up" not in msgs[0]:
        print("  (P6 setup: first hold did not fire)")
        return False
    distinct = len(set(msgs)) == 3
    escalated = "name the stored number" in msgs[2].lower()
    return distinct and escalated


guarded("P6 PIN ESCALATION: three holds, three different messages, the third offers the direct set", p6)


# P7 --- POSITIVE invariant: weekly statements still land
def p7():
    figs = ic._message_figures("My weekly capacity is one hundred and "
                               "eighty-five checkouts.")
    if 185.0 not in figs:
        return False
    ops = {"lob_models": [{"products": [{
        "product_name": "checkout", "unit_price": 68.0,
        "unit_cadence": "weekly", "units_per_week_capacity": 100.0,
        "units_per_period_capacity": 100.0,
        "operating_periods_per_year": 52.0, "utilization_rate": 0.8}]}]}
    fin = _fern_fin()
    did = _mk_draft(fin, ops)
    turn, fin_out, shared = _turn(
        did, "Capacity is 185 per week.", SpyRouter(READONLY), fin, ops,
        last="Which is right - the revenue figure or one of the drivers?")
    db = _db_ops(did)
    r = _row0(db)
    return (abs(float(r.get("units_per_week_capacity") or 0) - 185.0) < 0.5
            and abs(float(r.get("units_per_period_capacity") or 0) - 185.0) < 0.5)


guarded("P7 POSITIVE: '185 per week' lands on the weekly canonical and the twin derives", p7)


# P8 --- multi-product derivation
def p8():
    ops = {"lob_models": [{"products": [
        {"unit_cadence": "weekly", "units_per_week_capacity": 30.0,
         "units_per_period_capacity": 4.0, "operating_periods_per_year": 52.0},
        {"unit_cadence": "contract", "units_per_period_capacity": 10.0,
         "units_per_week_capacity": 99.0, "operating_periods_per_year": 12.0},
    ]}]}
    ic._derive_capacity_cells(ops)
    p_a, p_b = ops["lob_models"][0]["products"]
    ok_a = abs(float(p_a["units_per_period_capacity"]) - 30.0) < 1e-6
    ok_b = abs(float(p_b["units_per_week_capacity"]) - 10.0 * 12.0 / 52.0) < 0.01
    return ok_a and ok_b


guarded("P8 MULTI-PRODUCT: every row derives, not just single-product models", p8)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
