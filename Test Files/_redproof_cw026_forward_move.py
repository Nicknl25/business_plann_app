# -*- coding: utf-8 -*-
"""CW-026 FORWARD-MOVE RED-PROOF SUITE (Nick's structural rule).

THE RULE UNDER TEST: at the completed-financials state (ASSERTED in
setup - `_next_financials_stage(fin) is None`), every correction turn
produces a FORWARD MOVE - the value lands (attributed by the message's
own words) or an inferred landing is applied-and-proposed. The
"I couldn't tell where to record it - you tell me" dead-end is
unrepresentable. Sumac Ridge Grounds shape (draft 2ecc759c): price $520,
34 properties, payroll 133k true.

CORRECTION TYPES ENUMERATED (Nick: name every type tested):
  F1  PRICE      "My unit price is now 650 instead of 520."  (the
      actual Sumac [101] text, patchless router - the live failure)
  F2  VOLUME     "I can take on 40 properties now."
  F3  PAYROLL    "My total payroll is $133,000."       (rank-1 pin)
  F4  PAYROLL DURABILITY - two-turn: lands, then SURVIVES a reload +
      benign next turn (the Sumac live revert 133,000->141,999.96)
  F5  REST-OF-TEAM  "The crew comes to $62,000 for the other two."
  F6  OWNER PAY  "I pay myself $4,000 a month."
  F7  COGS       "Materials run about $30,000 a year."
  F8  MARKETING  "Marketing is really $2,400 a year."
  F9  RENT       "The rent is $500 a month."
  F10 REVENUE    "Revenue is about $190,000."
  F11 GARBAGE    "Put 777 in there."  - still a forward move (proposal),
      never a dead stop
  F12 INVARIANT  a question carrying a figure gets its ANSWER, no landing
  F13 LIVE ROUTER price  (real GPT on the actual [101] text)
  F14 LIVE ROUTER payroll

Protocol: 0-green on the pre-fix baseline (git stash) except the pinned
F3/F12 invariants; full green on the fix. Entry chain:
_run_financials_turn_and_sync -> doors/normalize/forward-move ->
THE RECALC -> real-DB persists (people + ops + financials).
"""
import copy
import io
import json
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
    create_draft, get_draft, append_messages,
)

WALL = (
    "The profit math clears, but one structural wall still stands: your "
    "team costs are 76% of revenue, and a labor-intensive business like "
    "this one is financed at no more than 70% - a lender won't finance a "
    "plan above that level. The honest way through is revenue (pricing "
    "and volume are the levers we can work right now)."
)

SUMAC_OPS = {
    "business_naics_6": "561730",
    "business_type": "Commercial grounds maintenance",
    "unit_price": 520.0,
    "units_per_period_capacity": 34.0,
    "operating_periods_per_year": 12.0,
    "utilization_rate": 0.82,
    "lob_models": [{
        "lob_name": "Grounds Care",
        "products": [{
            "product_name": "Property contract",
            "unit_name": "property contract",
            "unit_price": 520.0,
            "unit_cadence": "contract",
            "units_per_period_capacity": 34.0,
            "operating_periods_per_year": 12.0,
            "utilization_rate": 0.82,
        }],
    }],
}

SUMAC_PEOPLE = {
    "people": [
        {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
         "annual_wage": 34000.0},
        {"full_name": "Rosalie Fenn", "role_title": "Crew Lead",
         "annual_wage": 37000.0},
    ],
    "rest_of_team_payroll_year1": 62000.0,
}

_BASE_FIN = {
    "current_revenue": 175000.0,
    "cogs_percent_of_revenue": 0.15,
    "cogs_basis": "ratio",
    "current_payroll": 133000.0,
    "current_num_employees": 4,
    "marketing_total_year1": 1200.0,
    "monthly_rent_expense": 340.0,
    "gna_total_year1": 8000.0,
    "capex_total_year1": 0.0,
    "initial_assets": 18000.0,
    "initial_lease": 0.0,
    "total_debt_outstanding": 9000.0,
    "other_monthly_debt_payments": 260.0,
    "annual_interest_payment": 700.0,
    # 2,600 not 2,400: the F8 marketing correction is $2,400 and the
    # backstop treats any figure matching a stored value as a
    # restatement - a fixture collision, not app behavior.
    "annual_principal_payment": 2600.0,
    "cash_on_hand": 6000.0,
    "ar_balance": 9000.0,
    "ap_balance": 1500.0,
    "inventory_balance": 1100.0,
    "cash_strategy": "preserve_cash",
    "funding_preference": "debt",
    "_financials_revenue_intro_done": True,
    "_financials_marketing_stage_done": True,
}


def _completed_fin():
    fin = _ensure_financials_stage_defaults(copy.deepcopy(_BASE_FIN))
    for st in list(getattr(ic, "_FINANCIALS_STAGE_ORDER", ())):
        spec = ic._financials_stage_spec(st)
        for f in (spec.get("completion_fields") or ()):
            if fin.get(f) is None:
                fin[f] = 1.0
    return fin


def _shared(people=None, ops=None):
    return {
        "people_capability": copy.deepcopy(people or SUMAC_PEOPLE),
        "operating_model": copy.deepcopy(ops or SUMAC_OPS),
        "marketing": {},
    }


class SpyRouter:
    def __init__(self, ret):
        self.calls = []
        self.ret = ret

    def __call__(self, **kw):
        self.calls.append(kw)
        return copy.deepcopy(self.ret)


PATCHLESS = {"action": "answer_readonly", "assistant_message": "", "patch": None}
_conn = get_mysql_connection()


def _fresh_draft(fin=None, people=None):
    d = create_draft(_conn, client_id=f"rp26{uuid.uuid4().hex[:8]}")
    draft_id = str(d.get("draft_id") or d.get("id") or "").strip()
    append_messages(
        _conn, draft_id=draft_id, new_messages=[],
        people_json=copy.deepcopy(people or SUMAC_PEOPLE),
        financials_json=fin or _completed_fin(),
        active_focus="financials",
    )
    return draft_id


def _assembled_year1(fin, people=None, ops=None):
    """The handler assembles year1 from the live shared context every
    turn - a minimal stub here would make the Recalc's rescale refuse
    (nothing rescalable) and mask real behavior. Production-shaped."""
    from client_intake_and_finmo.financials_year1 import assemble_financials_year1
    shared = {
        "operating_model": copy.deepcopy(ops or SUMAC_OPS),
        "people_capability": copy.deepcopy(people or SUMAC_PEOPLE),
        "financials": copy.deepcopy(fin),
    }
    return assemble_financials_year1(shared, None) or {}


def _run(message, router, fin=None, people=None, ops=None, draft_id=None):
    shared = _shared(people, ops)
    did = draft_id or _fresh_draft(fin=fin, people=people)
    fin = fin or _completed_fin()
    turn, fin_out = _run_financials_turn_and_sync(
        route_intent=router,
        conn=_conn,
        intake_context={"draft_id": did},
        conversation_messages=[{"role": "assistant", "content": WALL}],
        business_facts={"name": "Sumac Ridge Grounds"},
        shared_context=shared,
        last_assistant=WALL,
        user_message=message,
        financials_json=fin,
        financials_year1_json=_assembled_year1(fin, people=people, ops=ops),
    )
    return turn, fin_out, did


def _draft_sections(draft_id):
    row = get_draft(_conn, draft_id=draft_id)

    def _j(key):
        v = row.get(key)
        if isinstance(v, str):
            try:
                return json.loads(v or "{}")
            except Exception:
                return {}
        return dict(v or {})

    return (_j("financials_json"), _j("people_json"),
            _j("operating_model_json"))


DEAD_END = "couldn't tell where to record"

_entry = _completed_fin()
_active = _next_financials_stage(_entry)
print(f"SETUP entry state: completed-financials (active stage = {_active!r})")
if _active is not None:
    print("SETUP FAILED")
    sys.exit(2)


def _msg_of(turn):
    return str((turn or {}).get("assistant_message") or "")


# F1 PRICE (the actual Sumac [101] failure, patchless router)
def f1():
    turn, fin_out, did = _run("My unit price is now 650 instead of 520.",
                              SpyRouter(PATCHLESS))
    msg = _msg_of(turn)
    _f, _p, _o = _draft_sections(did)
    prod = ((_o.get("lob_models") or [{}])[0].get("products") or [{}])[0]
    landed = abs((prod.get("unit_price") or 0) - 650.0) < 0.5
    return landed and "unit price" in msg and DEAD_END not in msg


guarded("F1 PRICE attributed + lands on ops.unit_price 520->650 (persisted), no dead-end", f1)


# F2 VOLUME
def f2():
    turn, fin_out, did = _run("I can take on 40 properties now.",
                              SpyRouter(PATCHLESS))
    _f, _p, _o = _draft_sections(did)
    prod = ((_o.get("lob_models") or [{}])[0].get("products") or [{}])[0]
    flat = _o.get("units_per_period_capacity")
    landed = abs((prod.get("units_per_period_capacity") or flat or 0) - 40.0) < 0.5
    return landed and DEAD_END not in _msg_of(turn)


guarded("F2 VOLUME attributed + lands capacity 34->40", f2)


# F3 PAYROLL (rank-1 pin: recorded door patch)
def f3():
    spy = SpyRouter({"action": "edit_patch", "assistant_message": "",
                     "patch": {"people.total_team_payroll": 120000}})
    turn, fin_out, did = _run("My total payroll is $120,000.", spy)
    return abs((fin_out.get("current_payroll") or 0) - 120000.0) < 1.5


guarded("F3 PAYROLL door lands 133,000->120,000 (rank-1 pin)", f3)


# F4 PAYROLL DURABILITY (the Sumac live revert: 133,000 came back one
# turn after the receipt). The next turn's HANDLER PREAMBLE runs THE
# RECALC over the PERSISTED sections - so the durability leg replays
# exactly that: reload from the DB, run the canonical sync, assert the
# correction survived. On the broken code the fold retired the
# adjustment in memory but people were never persisted, so this leg
# rebuilds 133,000 from the stale roster.
def f4():
    spy = SpyRouter({"action": "edit_patch", "assistant_message": "",
                     "patch": {"people.total_team_payroll": 120000}})
    turn, fin_out, did = _run("My total payroll is $120,000.", spy)
    if abs((fin_out.get("current_payroll") or 0) - 120000.0) > 1.5:
        return False
    fin_db, ppl_db, ops_db = _draft_sections(did)
    fin_next, _y1 = ic._sync_financials_consult_persistence_state(
        financials_json=fin_db,
        financials_year1_json=_assembled_year1(fin_db, people=ppl_db, ops=ops_db),
        marketing_model_json={},
        people_json=ppl_db,
        ops_json=ops_db,
    )
    return abs((fin_next.get("current_payroll") or 0) - 120000.0) < 1.5


guarded("F4 PAYROLL DURABILITY: correction survives reload + next turn (no revert)", f4)


# F5 REST-OF-TEAM
def f5():
    turn, fin_out, did = _run(
        "The crew comes to $70,000 for the other guys.", SpyRouter(PATCHLESS))
    _f, _p, _o = _draft_sections(did)
    return abs((_p.get("rest_of_team_payroll_year1") or 0) - 70000.0) < 0.5


guarded("F5 REST-OF-TEAM attributed + lands 62,000->70,000", f5)


# F6 OWNER PAY
def f6():
    turn, fin_out, did = _run("I pay myself $4,000 a month.",
                              SpyRouter(PATCHLESS))
    _f, _p, _o = _draft_sections(did)
    _owner = next((x for x in (_p.get("people") or [])
                   if ic._OWNER_TITLE_RE.search(str(x.get("role_title") or ""))), {})
    return abs((_owner.get("annual_wage") or 0) - 48000.0) < 1.0


guarded("F6 OWNER PAY attributed + owner role wage -> 48,000/yr", f6)


# F7 COGS
def f7():
    turn, fin_out, did = _run("Materials run about $30,000 a year.",
                              SpyRouter(PATCHLESS))
    return abs((fin_out.get("current_cogs") or 0) - 30000.0) < 0.5 \
        and str(fin_out.get("cogs_basis")) == "dollars"


guarded("F7 COGS attributed + lands 30,000 (stated dollars tag dollars)", f7)


# F8 MARKETING
def f8():
    turn, fin_out, did = _run("Marketing is really $2,400 a year.",
                              SpyRouter(PATCHLESS))
    return abs((fin_out.get("marketing_total_year1") or 0) - 2400.0) < 0.5


guarded("F8 MARKETING attributed + lands 1,200->2,400", f8)


# F9 RENT
def f9():
    turn, fin_out, did = _run("The rent is $500 a month now.",
                              SpyRouter(PATCHLESS))
    return abs((fin_out.get("monthly_rent_expense") or 0) - 500.0) < 0.5


guarded("F9 RENT attributed + lands 340->500", f9)


# F10 REVENUE
def f10():
    turn, fin_out, did = _run("Revenue is about $190,000.",
                              SpyRouter(PATCHLESS))
    return abs((fin_out.get("current_revenue") or 0) - 190000.0) < 1.0


guarded("F10 REVENUE attributed + lands 175,000->190,000", f10)


# F11 GARBAGE still moves forward
def f11():
    turn, fin_out, did = _run("Put 777 in there.", SpyRouter(PATCHLESS))
    msg = _msg_of(turn)
    return ("It looks like you mean" in msg) and (DEAD_END not in msg)


guarded("F11 GARBAGE input: inferred proposal ships, dead-end unrepresentable", f11)


# F12 INVARIANT: question with a figure gets its answer, no landing
def f12():
    spy = SpyRouter({
        "action": "answer_readonly",
        "assistant_message": (
            "For grounds care at your scale, $500,000 is above the "
            "typical single-crew range - most reach it with 3+ crews."
        ),
        "patch": None,
    })
    turn, fin_out, did = _run(
        "Is $500,000 revenue realistic for a business like mine?", spy)
    msg = _msg_of(turn)
    return "$500,000" in msg and abs(
        (fin_out.get("current_revenue") or 0) - 175000.0) < 1.0


guarded("F12 INVARIANT question: answer ships, 500,000 never lands", f12)


# F13/F14 LIVE ROUTER
def f13():
    from client_intake_and_finmo.intent_router import route_intent
    turn, fin_out, did = _run("My unit price is now 650 instead of 520.",
                              route_intent)
    _f, _p, _o = _draft_sections(did)
    prod = ((_o.get("lob_models") or [{}])[0].get("products") or [{}])[0]
    return abs((prod.get("unit_price") or 0) - 650.0) < 0.5


guarded("F13 LIVE router PRICE: the actual [101] text lands 650", f13)


def f14():
    from client_intake_and_finmo.intent_router import route_intent
    turn, fin_out, did = _run(
        "The payroll number is wrong - my actual total payroll including "
        "my own pay is $126,000.", route_intent)
    return abs((fin_out.get("current_payroll") or 0) - 126000.0) < 1.5


guarded("F14 LIVE router PAYROLL: stated total lands 126,000", f14)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
