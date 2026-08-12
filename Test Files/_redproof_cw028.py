# -*- coding: utf-8 -*-
"""CW-028 RED-PROOF SUITE (Alder & Vine, all five Nick-approved fixes).

  X1  TWIN INVARIANT: weekly cadence => period twin DERIVES from the
      weekly value at every canonical pass (the loop's trigger dies)
  X2  LOOP PIN: the anchor-vs-ops hold can never re-issue verbatim -
      the repeat exposes its operands (the stored drivers)
  X3  RATIO-TWIN: the verbatim [55] ("48% of the sale price") - the
      landed ratio's percent form cannot re-capture as unit price
  X4  ARITHMETIC-OF-LANDED: the verbatim [81] ("$9,360... $2,600
      interest... $6,760 principal") - the client's own total cannot
      capture as another field
  X5  COUNT-OF-PERSONS: the verbatim [85] ("The two designers have
      accounts") - a people-count cannot capture as capacity
  X6  POSITIVE capacity (Nick's explicit ask): real small-figure
      capacity statements STILL capture ("40 properties now",
      "about 40 jobs a week")
  X7  COMPOUND WORD-NUMBERS: "one hundred and eighty-five checkouts"
      attributes capacity 185, never the 85 fragment
  X8  OWNER-COPY: the rest-of-team question never names the owner
      alongside "yourself"
  X9  REPAIR RECEIPT: an extra applied (non-stage) field is named in
      the ack - a fix is always visible

Protocol: RED on af791ec (the live bugs), GREEN on the fix. X6 is the
named invariant (green on both).
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
    create_draft, append_messages,
)

ALDER_OPS = {
    "business_naics_6": "449129",
    "lob_models": [{"lob_name": "Retail", "products": [{
        "product_name": "In-store sales transaction", "unit_price": 68.0,
        "unit_cadence": "weekly", "units_per_week_capacity": 185.0,
        "units_per_period_capacity": 2.0,
        "operating_periods_per_year": 52.0, "utilization_rate": 0.8}]}],
}
ALDER_PEOPLE = {
    "people": [
        {"full_name": "Marisol Okafor", "role_title": "Owner & Buyer",
         "annual_wage": 62000.0, "wage_source": "client_override"},
        {"full_name": "Priya Raghunathan", "role_title": "Store Manager",
         "annual_wage": 46000.0, "wage_source": "client_override"},
    ],
    "rest_of_team_payroll_year1": 19000.0,
}
_conn = get_mysql_connection()


class SpyRouter:
    def __init__(self, ret):
        self.ret = ret

    def __call__(self, **kw):
        return copy.deepcopy(self.ret)


def _fin(missing=None, extra=None):
    base = {
        "current_revenue": 530000.0, "cogs_percent_of_revenue": 0.48,
        "cogs_basis": "ratio", "current_cogs": 254400.0,
        "cogs_total_year1": 254400.0, "current_payroll": 127000.0,
        "current_num_employees": 3, "marketing_total_year1": 6000.0,
        "monthly_rent_expense": 3900.0, "gna_total_year1": 21000.0,
        "capex_total_year1": 0.0, "initial_assets": 45000.0,
        "initial_lease": 0.0, "total_debt_outstanding": 32000.0,
        "other_monthly_debt_payments": 780.0,
        "annual_interest_payment": 2600.0,
        "annual_principal_payment": 6760.0, "cash_on_hand": 28000.0,
        "ar_balance": 2000.0, "ap_balance": 15000.0,
        "inventory_balance": 96000.0, "cash_strategy": "preserve_cash",
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
        fin.pop("_financials_stage_confirms", None)
    for k, v in (extra or {}).items():
        fin[k] = v
    return fin


def _run(message, router, fin, ops=None, last=""):
    d = create_draft(_conn, client_id=f"rp28{uuid.uuid4().hex[:8]}")
    did = str(d.get("draft_id") or "").strip()
    append_messages(_conn, draft_id=did, new_messages=[],
                    people_json=copy.deepcopy(ALDER_PEOPLE),
                    financials_json=fin, active_focus="financials")
    turn, fin_out = _run_financials_turn_and_sync(
        route_intent=router, conn=_conn,
        intake_context={"draft_id": did},
        conversation_messages=[{"role": "assistant", "content": last}],
        business_facts={"name": "Alder & Vine Home Goods"},
        shared_context={"people_capability": copy.deepcopy(ALDER_PEOPLE),
                        "operating_model": copy.deepcopy(ops or ALDER_OPS),
                        "marketing": {}},
        last_assistant=last,
        user_message=message,
        financials_json=fin,
        financials_year1_json={"company_revenue_total_year1": 530000.0},
    )
    return turn, fin_out


def _msg_of(turn):
    return str((turn or {}).get("assistant_message") or "")


# X1 --- twin invariant through THE RECALC
def x1():
    ops = copy.deepcopy(ALDER_OPS)
    fin, _y1 = ic._sync_financials_consult_persistence_state(
        financials_json=_fin(), financials_year1_json={},
        marketing_model_json={}, people_json=copy.deepcopy(ALDER_PEOPLE),
        ops_json=ops)
    pr = ops["lob_models"][0]["products"][0]
    return abs(float(pr.get("units_per_period_capacity") or 0) - 185.0) < 0.5


guarded("X1 TWIN INVARIANT: weekly cadence heals period twin 2 -> 185 at the canonical pass", x1)


# X2 --- loop pin: second identical hold exposes operands
def x2():
    from client_intake_and_finmo.intake_coherence import section as sec
    ops = copy.deepcopy(ALDER_OPS)   # stale twin kept: ceiling ~7,072
    fin = {"current_revenue": 530000.0, "_financials_revenue_intro_done": True}
    t1, fin1, _ = sec.gate_and_turn(
        ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=fin,
        financials_year1_json={}, user_text="Capacity is 185 per week.")
    m1 = _msg_of(t1)
    t2, fin2, _ = sec.gate_and_turn(
        ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=dict(fin1),
        financials_year1_json={}, user_text="Capacity is 185 per week.")
    m2 = _msg_of(t2)
    if "doesn't add up" not in m1:
        print("  (X2 setup: first hold did not fire)")
        return False
    return m2 != m1 and "computing from" in m2 and "$68.00" in m2


guarded("X2 LOOP PIN: the repeat hold differs and shows the stored drivers", x2)


# X3 --- ratio-twin: the verbatim [55]
def x3():
    fin = _fin(missing=["current_cogs"])
    if _next_financials_stage(fin) != "cogs":
        print("  (X3 setup: cogs stage not active:", _next_financials_stage(fin), ")")
        return False
    spy = SpyRouter({"action": "edit_patch", "assistant_message": "",
                     "patch": {"financials.cogs_percent_of_revenue": 0.48,
                               "financials.cogs_total_year1": 254400.0,
                               "financials.current_cogs": 254400.0}})
    turn, fin_out = _run(
        "It's a bit higher than that - what we pay for the goods themselves "
        "runs about 48% of the sale price. So call it $254,000 a year.",
        spy, fin,
        last=("For direct costs - a business like yours typically runs about "
              "42%-50% of revenue. I'd start at 46%, which works out to "
              "around $243,800."))
    msg = _msg_of(turn)
    return "unit price" not in msg.lower() and "$48" not in msg


guarded("X3 RATIO-TWIN [55]: the landed 48% cannot re-capture as unit price $48", x3)


# X4 --- arithmetic-of-landed: the verbatim [81]
def x4():
    fin = _fin(missing=["annual_principal_payment"])
    if _next_financials_stage(fin) != "annual_principal_payment":
        print("  (X4 setup:", _next_financials_stage(fin), ")")
        return False
    spy = SpyRouter({"action": "edit_patch", "assistant_message": "",
                     "patch": {"financials.annual_principal_payment": 6760}})
    turn, fin_out = _run(
        "The payments come to $9,360 a year, so if $2,600 is interest the "
        "principal part is about $6,760.",
        spy, fin,
        last="What is your best estimate of the annual principal you expect to repay?")
    msg = _msg_of(turn)
    mkt_ok = abs(float(fin_out.get("marketing_total_year1") or 0) - 6000.0) < 0.5
    return mkt_ok and "9,360" not in msg


guarded("X4 ARITHMETIC [81]: the client's own $9,360 total cannot capture as marketing", x4)


# X5 --- count-of-persons: the verbatim [85]
def x5():
    fin = _fin(missing=["ar_balance"])
    if _next_financials_stage(fin) != "ar_balance":
        print("  (X5 setup:", _next_financials_stage(fin), ")")
        return False
    # Live sequence fidelity: at [85] the stored capacity was CLEAN -
    # the mis-capture CREATED the 2 (a pre-stored 2 would vacuously
    # pass old code via the restatement skip).
    ops = copy.deepcopy(ALDER_OPS)
    ops["lob_models"][0]["products"][0]["units_per_period_capacity"] = 185.0
    spy = SpyRouter({"action": "edit_patch", "assistant_message": "",
                     "patch": {"financials.ar_balance": 2000}})
    turn, fin_out = _run(
        "Hardly anything - people pay at the counter. The two designers "
        "have accounts and might owe us $2,000 between them at any time.",
        spy, fin, ops=ops,
        last="About how much do customers currently owe you for completed work?")
    msg = _msg_of(turn)
    return "capacity" not in msg.lower() \
        and abs(float(fin_out.get("ar_balance") or 0) - 2000.0) < 0.5


guarded("X5 COUNT-OF-PERSONS [85]: 'the two designers' cannot capture as capacity", x5)


# X6 --- POSITIVE capacity invariant (Nick's explicit ask)
def x6():
    ok = True
    for m in ("I can take on 40 properties now.",
              "I do about 40 jobs a week."):
        fin = _fin()
        turn, fin_out = _run(m, SpyRouter(
            {"action": "answer_readonly", "assistant_message": "", "patch": None}),
            fin, last="The wall: pricing and volume are the levers we can work.")
        msg = _msg_of(turn)
        if "capacity" not in msg.lower() or "40" not in msg:
            print(f"  (X6 miss on: {m!r} -> {msg[:120]!r})")
            ok = False
    return ok


guarded("X6 POSITIVE invariant: real small-figure capacity statements STILL capture 40", x6)


# X7 --- compound word-numbers attribute capacity 185
def x7():
    figs = ic._message_figures(
        "My weekly capacity is one hundred and eighty-five checkouts.")
    if 185.0 not in figs or 85.0 in figs:
        return False
    # UNIVERSAL ENGINE update: the stored week here must DIFFER from the
    # stated 185 - under the engine the old divergent fixture (week 185
    # beside period 2) is unrepresentable, and a restatement of an
    # already-true row value correctly lands nothing.
    fin = _fin()
    ops = copy.deepcopy(ALDER_OPS)
    ops["lob_models"][0]["products"][0]["units_per_week_capacity"] = 100.0
    ops["lob_models"][0]["products"][0]["units_per_period_capacity"] = 100.0
    turn, fin_out = _run(
        "My weekly capacity is one hundred and eighty-five checkouts.",
        SpyRouter({"action": "answer_readonly", "assistant_message": "",
                   "patch": None}),
        fin, ops=ops,
        last="Which is right - the revenue figure or one of the drivers?")
    msg = _msg_of(turn)
    return "185" in msg and "capacity 85" not in msg


guarded("X7 WORD-NUMBERS: 'one hundred and eighty-five' attributes 185, never 85", x7)


# X8 --- owner-copy: the rest question never names the owner
def x8():
    q = ic._build_rest_of_team_payroll_question(
        "", people_json=copy.deepcopy(ALDER_PEOPLE))
    return "Marisol" not in q and "Priya Raghunathan" in q


guarded("X8 OWNER-COPY: 'Beyond yourself and...' never names the owner as a third party", x8)


# X9 --- repair receipt: extra applied fields are named
def x9():
    fin = _fin(missing=["cash_on_hand"])
    if _next_financials_stage(fin) != "cash_on_hand":
        print("  (X9 setup:", _next_financials_stage(fin), ")")
        return False
    spy = SpyRouter({"action": "edit_patch", "assistant_message": "",
                     "patch": {"financials.cash_on_hand": 28000,
                               "financials.marketing_total_year1": 5200}})
    turn, fin_out = _run(
        "Cash is $28,000. And put marketing back to $5,200 a year.",
        spy, fin, last="About how much cash does the business have on hand?")
    msg = _msg_of(turn)
    return "Also recorded" in msg and "5,200" in msg


guarded("X9 REPAIR RECEIPT: the ack names the extra applied field (fix always visible)", x9)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
