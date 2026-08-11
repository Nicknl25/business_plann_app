# -*- coding: utf-8 -*-
"""CW-025 RANK-1 RED-PROOF SUITE (Nick's verification standard).

THE ENTRY STATE IS THE COMPLETED-FINANCIALS STATE - the exact surface
that broke on Brightline Office Care (draft 3de095cb): every financials
stage complete (`_next_financials_stage(fin) is None`, ASSERTED in
setup, not assumed), the payroll wall standing (94.8% vs 70%), and the
client's ACTUAL correction turns [63]/[65]/[89]/[91] replayed through
the PRODUCTION chain: `_run_financials_turn_and_sync` (the handler's
exact financials entry) -> people doors (_apply_stage_people_door_keys /
_apply_scoped_patch) -> THE RECALC -> real-DB persist
(_persist_and_reload_financials_progress round-trip on a real draft).

Protocol: run on the pre-fix baseline (git stash of tracked source) ->
RED on every R-check; run on the fix -> GREEN. R7 is an invariant
(green on both): questions still get answers.

  R1  [89] completed-state routing: the router RUNS (zero-GPT-call
      bypass unrepresentable) and the total-team door lands ->
      current_payroll 201,000.04 -> 166,000
  R2  [91] rest-of-team door at the completed state -> 166,000.04
  R3  two-beat receipt: a landed correction's receipt rides the turn
      (_door_receipt) so the caller puts it BEFORE any wall verdict;
      the verbatim-wall-with-no-acknowledgment turn is unrepresentable
  R4  [65] prose-only ship gate: "My total annual payroll is $166,000."
      with the lease question pending -> the false "I'll use $0" claim
      cannot ship; the $166,000 is disclosed
  R5  [63] partial-landing backstop: the $24,000 equipment answer lands
      AND the bundled $166,000 correction is disclosed in the same
      reply (real-draft persist chain)
  R6  write-claim ship gate: patchless prose claiming "I've recorded"
      cannot ship when nothing landed
  R7  INVARIANT: a genuine question at the completed state still gets
      its answer (claim-free prose ships)
  R8  LIVE ROUTER at the completed state: the real route_intent, given
      the actual [89] text with the wall as context, emits a people
      door that lands -> current_payroll 166,000 (proves the router
      prompt holds at stage=None, not just the recorded patch)
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
    create_draft, get_draft, append_messages,
)

# ------------------------------------------------------------- fixtures
# Brightline Office Care (561720, Chattanooga): revenue $212k, owner at
# $38,000.04, Tanya Brill $35,000 ALSO inside the $128,000 rest-of-team
# total -> stored payroll $201,000.04; the client's true total $166,000.

WALL_TEXT = (
    "The profit math clears, but one structural wall still stands: your "
    "team costs are 95% of revenue, and a labor-intensive business like "
    "this one is financed at no more than 70% - a lender won't finance a "
    "plan above that level, so I can't close the plan on these numbers. "
    "That payroll is your real, current team - I won't propose cutting "
    "anyone's pay from arithmetic. The honest way through is revenue: at "
    "or above $287,143 a year the plan clears with the team you have "
    "(pricing and volume are the levers we can work right now). If the "
    "team itself is going to change in the real world, tell me how and "
    "I'll put it in properly."
)

MSG_89 = (
    "The team isn't changing, but the number is wrong. Tanya Brill got "
    "counted twice — she's in the $128,000 I gave you for the cleaners, "
    "and you also have her separately at $35,000. My real total payroll "
    "including my own $38,000 is $166,000."
)
MSG_91 = (
    "Please change the rest-of-team payroll from $128,000 to $93,000. "
    "That is the three cleaners who are not Tanya."
)
MSG_65 = "My total annual payroll is $166,000."
MSG_63 = (
    "The van, vacuums, buffer, carts and supplies — about $24,000. And "
    "can I fix something? I think Tanya got counted twice. When I said "
    "the cleaners come to $128,000, that included her $35,000. My whole "
    "payroll including me is $166,000, not more."
)
PROSE_66 = "Got it - I'll use $0 for monthly lease commitment beyond main rent."

BRIGHT_OPS = {
    "business_naics_6": "561720",
    "business_type": "Commercial office cleaning services",
    "lob_models": [{
        "lob_name": "Office Cleaning",
        "products": [{
            "product_name": "Office cleaning visit",
            "unit_price": 85.0,
            "unit_cadence": "weekly",
            "units_per_week_capacity": 60.0,
            "utilization_rate": 0.67,
        }],
    }],
}

BRIGHT_PEOPLE = {
    "people": [
        {"full_name": "", "role_title": "Owner & Cleaning Lead",
         "annual_wage": 38000.04},
        {"full_name": "Tanya Brill", "role_title": "Lead Cleaner",
         "annual_wage": 35000.0},
    ],
    "rest_of_team_payroll_year1": 128000.0,
}

_BASE_FIN = {
    "current_revenue": 212000.0,
    "cogs_percent_of_revenue": 0.09,
    "cogs_basis": "ratio",
    "current_payroll": 201000.04,
    "current_num_employees": 5,
    "marketing_total_year1": 1800.0,
    "monthly_rent_expense": 900.0,
    "gna_total_year1": 9000.0,
    "capex_total_year1": 0.0,
    "initial_assets": 24000.0,
    "initial_lease": 0.0,
    "total_debt_outstanding": 16000.0,
    "other_monthly_debt_payments": 410.0,
    "annual_interest_payment": 1100.0,
    "annual_principal_payment": 3940.0,
    "cash_on_hand": 7000.0,
    "ar_balance": 8500.0,
    "ap_balance": 1200.0,
    "inventory_balance": 1900.0,
    "cash_strategy": "preserve_cash",
    "funding_preference": "debt",
    "_financials_revenue_intro_done": True,
    "_financials_marketing_stage_done": True,
}


def _completed_fin():
    """Build the completed-financials entry state and PROVE it: every
    stage's completion fields present, no active stage remains."""
    fin = _ensure_financials_stage_defaults(copy.deepcopy(_BASE_FIN))
    for st in list(getattr(ic, "_FINANCIALS_STAGE_ORDER", ())):
        spec = ic._financials_stage_spec(st)
        for f in (spec.get("completion_fields") or ()):
            if fin.get(f) is None:
                fin[f] = 1.0
    return fin


def _fin_missing(field):
    fin = _completed_fin()
    fin.pop(field, None)
    fin.pop("_financials_stage_confirms", None)
    return fin


def _shared(people=None):
    return {
        "people_capability": copy.deepcopy(people or BRIGHT_PEOPLE),
        "operating_model": copy.deepcopy(BRIGHT_OPS),
        "marketing": {},
    }


class SpyRouter:
    def __init__(self, ret):
        self.calls = []
        self.ret = ret

    def __call__(self, **kw):
        self.calls.append(kw)
        return copy.deepcopy(self.ret)


_conn = get_mysql_connection()


def _fresh_draft():
    d = create_draft(_conn, client_id=f"rp25{uuid.uuid4().hex[:8]}")
    draft_id = str(d.get("draft_id") or d.get("id") or "").strip()
    append_messages(
        _conn, draft_id=draft_id, new_messages=[],
        people_json=copy.deepcopy(BRIGHT_PEOPLE),
        financials_json=_completed_fin(),
        active_focus="financials",
    )
    return draft_id


def _run(fin, message, router, people=None, draft_id=None, last=WALL_TEXT):
    shared = _shared(people)
    turn, fin_out = _run_financials_turn_and_sync(
        route_intent=router,
        conn=_conn,
        intake_context={"draft_id": draft_id or _fresh_draft()},
        conversation_messages=[{"role": "assistant", "content": last}],
        business_facts={"name": "Brightline Office Care"},
        shared_context=shared,
        last_assistant=last,
        user_message=message,
        financials_json=fin,
        financials_year1_json={"company_revenue_total_year1": 212000.0},
    )
    return turn, fin_out


# ------------------------------------------------------- entry state proof
_entry = _completed_fin()
_active = _next_financials_stage(_entry)
print(f"SETUP entry state: completed-financials (active stage = {_active!r})")
if _active is not None:
    print("SETUP FAILED: entry state is not the completed-financials state")
    sys.exit(2)


# R1 --- [89]: the router RUNS at the completed state and the door lands
def r1():
    spy = SpyRouter({
        "action": "edit_patch",
        "assistant_message": "",
        "patch": {"people.total_team_payroll": 166000},
    })
    turn, fin_out = _run(_completed_fin(), MSG_89, spy)
    routed = len(spy.calls) >= 1
    landed = abs((fin_out.get("current_payroll") or 0) - 166000.0) < 1.5
    return routed and landed


guarded("R1 [89] completed-state routing: router runs, total door lands 201,000.04 -> 166,000", r1)


# R2 --- [91]: the rest-of-team door at the completed state
def r2():
    spy = SpyRouter({
        "action": "edit_patch",
        "assistant_message": "",
        "patch": {"people.rest_of_team_payroll_year1": 93000},
    })
    turn, fin_out = _run(_completed_fin(), MSG_91, spy)
    return abs((fin_out.get("current_payroll") or 0) - 166000.04) < 1.5


guarded("R2 [91] rest-of-team door at the completed state -> 166,000.04", r2)


# R3 --- two-beat receipt: landed correction's receipt rides the turn
def r3():
    spy = SpyRouter({
        "action": "edit_patch",
        "assistant_message": "",
        "patch": {"people.total_team_payroll": 166000},
    })
    turn, _fin_out = _run(_completed_fin(), MSG_89, spy)
    receipt = str((turn or {}).get("_door_receipt") or "")
    msg = str((turn or {}).get("assistant_message") or "")
    return ("Recorded" in receipt) and ("Recorded" in msg)


guarded("R3 two-beat: receipt rides the turn and the message (no bare wall replay)", r3)


# R4 --- [65]: prose-only ship gate at the pending-lease stage
def r4():
    fin = _fin_missing("initial_lease")
    if _next_financials_stage(fin) != "initial_lease":
        print("  (R4 setup: initial_lease stage not active)")
        return False
    spy = SpyRouter({
        "action": "answer_readonly",
        "assistant_message": PROSE_66,
        "patch": None,
    })
    turn, _fin_out = _run(fin, MSG_65, spy,
                          last="What monthly amount should we use for any leased equipment?")
    msg = str((turn or {}).get("assistant_message") or "")
    return ("$166,000" in msg) and ("I'll use $0" not in msg)


guarded("R4 [65] prose-only: false $0 claim cannot ship; $166,000 disclosed", r4)


# R5 --- [63]: partial landing - equipment lands AND the correction is disclosed
def r5():
    fin = _fin_missing("initial_assets")
    if _next_financials_stage(fin) != "initial_assets":
        print("  (R5 setup: initial_assets stage not active)")
        return False
    spy = SpyRouter({
        "action": "edit_patch",
        "assistant_message": "Got it - I'll use $24,000 for initial assets.",
        "patch": {"financials.initial_assets": 24000},
    })
    draft_id = _fresh_draft()
    turn, fin_out = _run(fin, MSG_63, spy, draft_id=draft_id,
                         last="What would you say the main equipment is worth?")
    msg = str((turn or {}).get("assistant_message") or "")
    persisted = get_draft(_conn, draft_id=draft_id)
    import json as _json
    fin_db = _json.loads(persisted.get("financials_json") or "{}") \
        if isinstance(persisted.get("financials_json"), str) \
        else dict(persisted.get("financials_json") or {})
    landed = abs((fin_db.get("initial_assets") or fin_out.get("initial_assets") or 0) - 24000.0) < 0.5
    return landed and ("$166,000" in msg)


guarded("R5 [63] partial landing: $24,000 lands AND $166,000 disclosed in the same reply", r5)


# R6 --- write-claim ship gate: patchless "recorded" prose cannot ship
def r6():
    fin = _fin_missing("initial_lease")
    spy = SpyRouter({
        "action": "answer_readonly",
        "assistant_message": "I've recorded that for you.",
        "patch": None,
    })
    turn, _fin_out = _run(fin, "That's everything I think.", spy,
                          last="What monthly amount should we use for any leased equipment?")
    msg = str((turn or {}).get("assistant_message") or "")
    return "I've recorded that for you." not in msg


guarded("R6 write-claim gate: patchless 'recorded' prose is unrepresentable", r6)


# R7 --- INVARIANT: a question at the completed state still gets its answer
def r7():
    spy = SpyRouter({
        "action": "answer_readonly",
        "assistant_message": (
            "The 70% level is what lenders in labor-heavy industries "
            "typically finance against - above it the loan doesn't clear."
        ),
        "patch": None,
    })
    turn, _fin_out = _run(_completed_fin(), "Why does the 70% ceiling matter?", spy)
    msg = str((turn or {}).get("assistant_message") or "")
    return "70%" in msg and "lenders" in msg


guarded("R7 INVARIANT question at completed state: claim-free answer ships", r7)


# R8 --- LIVE ROUTER at the completed state (the actual [89] text)
def r8():
    from client_intake_and_finmo.intent_router import route_intent
    calls = []

    def live_spy(**kw):
        calls.append(kw)
        return route_intent(**kw)

    turn, fin_out = _run(_completed_fin(), MSG_89, live_spy)
    landed = abs((fin_out.get("current_payroll") or 0) - 166000.0) < 1.5
    return len(calls) >= 1 and landed


guarded("R8 LIVE router at completed state: [89] emits a people door, lands 166,000", r8)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
