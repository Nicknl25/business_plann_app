# -*- coding: utf-8 -*-
"""CW-027 RED-PROOF SUITE (Nick's one-shot: diagnose + fix + prove).

  W1  #1 REJECTED FIGURE: the verbatim Wren Hollow [67] line ("Nowhere
      near $28,000") at the marketing stage - the $4,800 lands, the
      NEGATED $28,000 (also the app's own proposal figure) can never be
      captured; the stated $99,840 COGS survives untouched
  W2  #1 INVARIANT: a bundled STATEMENT figure still moves forward
      (the reference filter never eats real corrections)
  W3  #2 RETENTION CONSUMED: the verbatim [97] answer ("Call it 90%
      staying") resolves the live frame at ANY surface - utilization
      0.78 -> 0.702, revenue scales, frame cleared
  W4  #2 INVARIANT: a bare figure without keep/stay/retain context is
      NOT a retention answer

Protocol: RED on 18f5ca5 (the live bugs), GREEN on the fix.
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

WREN_PROPOSAL = (
    "I'll start with direct costs of $99,840 a year (32% of revenue) - "
    "correct me if your actual materials cost differs.\n\nFor marketing, "
    "a reasonable starting point is about 9% of revenue, which works out "
    "to around $28,080 a year.\n\nDoes that broadly match what it will "
    "take to attract and convert customers, or should we adjust it?"
)
MSG_67 = ("I spend about $4,800 a year on Google ads and that's it. "
          "Nowhere near $28,000.")
MSG_97 = ("I'd keep most of them. Maybe I lose one in ten - the price "
          "shoppers who were only calling me because I was cheapest. "
          "Call it 90% staying.")

WREN_OPS = {
    "business_naics_6": "811412",
    "lob_models": [{"lob_name": "Appliance Repair", "products": [{
        "product_name": "completed service job", "unit_price": 189.0,
        "unit_cadence": "weekly", "units_per_week_capacity": 55.0,
        "utilization_rate": 0.78}]}],
}
WREN_PEOPLE = {
    "people": [
        {"full_name": "Tobias Reyes", "role_title": "Owner / Lead Technician",
         "annual_wage": 46000.0, "wage_source": "client_override"},
        {"full_name": "Junie Delacroix", "role_title": "Lead Technician",
         "annual_wage": 52000.0, "wage_source": "client_override"},
    ],
    "rest_of_team_payroll_year1": 132000.0,
}


def _wren_fin_marketing_stage():
    fin = _ensure_financials_stage_defaults({
        "current_revenue": 312000.0,
        "cogs_percent_of_revenue": 0.32,
        "cogs_basis": "dollars",
        "current_cogs": 99840.0,
        "cogs_total_year1": 99840.0,
        "current_payroll": 230000.0,
        "_financials_revenue_intro_done": True,
    })
    return fin


_conn = get_mysql_connection()


def _draft():
    d = create_draft(_conn, client_id=f"rp27{uuid.uuid4().hex[:8]}")
    return str(d.get("draft_id") or d.get("id") or "").strip()


class SpyRouter:
    def __init__(self, ret):
        self.ret = ret

    def __call__(self, **kw):
        return copy.deepcopy(self.ret)


def _run_marketing(message, router, fin):
    did = _draft()
    append_messages(_conn, draft_id=did, new_messages=[],
                    people_json=copy.deepcopy(WREN_PEOPLE),
                    financials_json=fin, active_focus="financials")
    turn, fin_out = _run_financials_turn_and_sync(
        route_intent=router, conn=_conn,
        intake_context={"draft_id": did},
        conversation_messages=[{"role": "assistant", "content": WREN_PROPOSAL}],
        business_facts={"name": "Wren Hollow Appliance Repair"},
        shared_context={"people_capability": copy.deepcopy(WREN_PEOPLE),
                        "operating_model": copy.deepcopy(WREN_OPS),
                        "marketing": {}},
        last_assistant=WREN_PROPOSAL,
        user_message=message,
        financials_json=fin,
        financials_year1_json={"company_revenue_total_year1": 312000.0},
    )
    return turn, fin_out


def w1():
    fin = _wren_fin_marketing_stage()
    if _next_financials_stage(fin) != "marketing":
        print("  (setup: marketing stage not active:",
              _next_financials_stage(fin), ")")
        return False
    spy = SpyRouter({"action": "edit_patch",
                     "assistant_message": "Got it - $4,800 a year.",
                     "patch": {"financials.marketing_total_year1": 4800}})
    turn, fin_out = _run_marketing(MSG_67, spy, fin)
    msg = str((turn or {}).get("assistant_message") or "")
    cogs_ok = abs(float(fin_out.get("current_cogs") or 0) - 99840.0) < 0.5
    mkt_ok = abs(float(fin_out.get("marketing_total_year1") or 0) - 4800.0) < 0.5
    no_capture = "$28,000" not in msg
    return cogs_ok and mkt_ok and no_capture


guarded("W1 #1 the verbatim [67]: $4,800 lands, the NEGATED $28,000 cannot capture, $99,840 COGS survives", w1)


def w2():
    fin = _wren_fin_marketing_stage()
    spy = SpyRouter({"action": "edit_patch",
                     "assistant_message": "Got it - $4,800 a year.",
                     "patch": {"financials.marketing_total_year1": 4800}})
    turn, fin_out = _run_marketing(
        "About $4,800 a year on ads. And my total payroll is really "
        "$210,000 by the way.", spy, fin)
    return abs(float(fin_out.get("current_payroll") or 0) - 210000.0) < 1.5


guarded("W2 #1 INVARIANT: a bundled STATEMENT figure ($210,000 payroll) still moves forward", w2)


def w3():
    from client_intake_and_finmo.intake_coherence import section as sec
    fin = {"current_revenue": 421200.0, "cogs_percent_of_revenue": 0.32,
           "cogs_basis": "dollars", "current_cogs": 134784.0,
           "cogs_total_year1": 134784.0}
    st = sec.get_state(fin)
    st = dict(st)
    st["retention_pending"] = {
        "prices": [{"product": "completed service job", "to": 189.0}],
        "retained_used": 1.0,
    }
    fin = sec.put_state(fin, st)
    ops = copy.deepcopy(WREN_OPS)
    ans = ic._parse_retention_answer(MSG_97)
    if ans is None:
        print("  (parser returned None)")
        return False
    fin2, ops2, applied = sec.apply_retention_answer(fin, ops, ans)
    st2 = sec.get_state(fin2)
    util = ((ops2.get("lob_models") or [{}])[0].get("products") or [{}])[0].get(
        "utilization_rate")
    rev = float(fin2.get("current_revenue") or 0)
    return (applied and st2.get("retention_pending") is None
            and abs(util - 0.702) < 0.002
            and abs(rev - 379080.0) < 2.0)


guarded("W3 #2 the verbatim [97] resolves the frame: util 0.78->0.702, revenue 421,200->379,080, frame cleared", w3)


def w4():
    a = ic._parse_retention_answer("Revenue is about $190,000.")
    b = ic._parse_retention_answer("Change my price to $650.")
    return a is None and b is None


guarded("W4 #2 INVARIANT: bare figures are not retention answers", w4)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
