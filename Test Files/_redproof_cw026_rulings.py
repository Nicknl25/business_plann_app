# -*- coding: utf-8 -*-
"""CW-026 FOUR-RULINGS RED-PROOF SUITE (Nick-approved, built in order).

Protocol: 0-green on the pre-fix baseline ff1da19 (git stash of tracked
source) except the named invariants; full green on the fix. Every check
replays STORED EVIDENCE from the live runs.

  Q1  #3 resolver: the ACTUAL Sumac confirmation ("Yes, Rosalie's
      $37,000 is inside that $99,000. So $62,000 ... is right")
      resolves to 62,000 - frame figures are references
  Q2  #3 resolver contract: fresh figure wins; separate keeps stated
  Q3  #4 echo-guard: the ACTUAL acceptance shape - the router echoes
      the app's own $26,250 anchor; the ratio stamp HOLDS
  Q4  #4 INVARIANT: client-stated dollars still tag dollars (F&F)
  Q5  #1 owner uniqueness: the ACTUAL Sumac duplicate (Delia 34,000 +
      bare Owner 33,999.96) merges to ONE row; rollup 141,999.96 ->
      108,000
  Q6  #1 benchmark-vs-override: OEWS row + bare override row -> one
      named row at the client's wage
  Q7  #1 conflict: two DIFFERENT override wages -> one row + the hold
      stamped, never a silent pick
  Q8  #2 draw ceiling: owner-dominated wall offers
      (payroll_to_clear - others)/12, not payroll_to_clear/12
  Q9  #2 zero-case: others alone above the ceiling -> NO draw exit
      offered; revenue named
"""
import copy
import io
import sys

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

SUMAC_FRAME = {"stated": 99000.0, "named_sum": 37000.0, "remainder": 62000.0}


def q1():
    got = ic._rest_inclusion_resolve(
        pending=dict(SUMAC_FRAME),
        user_message=("Yes, Rosalie's $37,000 is inside that $99,000. "
                      "So $62,000 for the other two is right."))
    return got is not None and abs(got - 62000.0) < 0.5


guarded("Q1 #3 the ACTUAL Sumac confirmation resolves to 62,000 (was 37,000)", q1)


def q2():
    a = ic._rest_inclusion_resolve(
        pending=dict(SUMAC_FRAME), user_message="It's $90,000 for the others.")
    b = ic._rest_inclusion_resolve(
        pending=dict(SUMAC_FRAME), user_message="No, that's separate from her.")
    c = ic._rest_inclusion_resolve(
        pending=dict(SUMAC_FRAME), user_message="Yes, she's included.")
    return (abs((a or 0) - 90000.0) < 0.5 and abs((b or 0) - 99000.0) < 0.5
            and abs((c or 0) - 62000.0) < 0.5)


guarded("Q2 #3 fresh figure wins / separate keeps stated / agreement -> remainder", q2)


def q3():
    fin = {"current_revenue": 175000.0, "cogs_percent_of_revenue": 0.15,
           "cogs_basis": "ratio", "current_cogs": 26250.0,
           "cogs_total_year1": 26250.0,
           "_financials_revenue_intro_done": True}
    applied = ic._normalize_financials_router_patch(
        patch={"financials.current_cogs": 26250.0},
        active_stage="",
        financials_json=fin,
        financials_year1_json={"company_revenue_total_year1": 175000.0},
        last_assistant=("For direct costs - a business like yours typically "
                       "runs about 12%-18% of revenue. I'd start at 15%, "
                       "which works out to around $26,250."),
        user_message="That sounds reasonable, let's go with 15%.",
    )
    got = str((applied or fin).get("cogs_basis"))
    return got == "ratio"


guarded("Q3 #4 the router's echoed $26,250 anchor cannot re-tag dollars (stamp holds)", q3)


def q4():
    fin = {"current_revenue": 175000.0, "cogs_percent_of_revenue": 0.15,
           "cogs_basis": "ratio", "current_cogs": 26250.0,
           "cogs_total_year1": 26250.0,
           "_financials_revenue_intro_done": True}
    applied = ic._normalize_financials_router_patch(
        patch={"financials.current_cogs": 30000.0},
        active_stage="",
        financials_json=fin,
        financials_year1_json={"company_revenue_total_year1": 175000.0},
        last_assistant="",
        user_message="Materials actually run about $30,000 a year.",
    )
    return str((applied or {}).get("cogs_basis")) == "dollars" \
        and abs(float((applied or {}).get("current_cogs") or 0) - 30000.0) < 0.5


guarded("Q4 #4 INVARIANT client-stated dollars still tag dollars (F&F ruling intact)", q4)


SUMAC_DUP_PEOPLE = {
    "people": [
        {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
         "annual_wage": 34000.0, "wage_source": "client_override",
         "relevant_background": "ten years of commercial grounds"},
        {"full_name": "", "role_title": "Owner",
         "annual_wage": 33999.96, "wage_source": "client_override"},
        {"full_name": "Rosalie Fenn", "role_title": "Crew Lead",
         "annual_wage": 37000.0, "wage_source": "client_override"},
    ],
    "rest_of_team_payroll_year1": 37000.0,
}
OPS = {
    "business_naics_6": "561730",
    "lob_models": [{"lob_name": "Grounds", "products": [{
        "product_name": "Property contract", "unit_price": 520.0,
        "unit_cadence": "contract", "units_per_period_capacity": 34.0,
        "operating_periods_per_year": 12.0, "utilization_rate": 0.82}]}],
}


def _sync(people):
    fin, _ = ic._sync_financials_consult_persistence_state(
        financials_json={"current_revenue": 175000.0,
                         "_financials_revenue_intro_done": True},
        financials_year1_json={},
        marketing_model_json={},
        people_json=people,
        ops_json=copy.deepcopy(OPS),
    )
    return fin, people


def q5():
    people = copy.deepcopy(SUMAC_DUP_PEOPLE)
    fin, people = _sync(people)
    owners = [p for p in people.get("people") or []
              if ic._OWNER_TITLE_RE.search(str(p.get("role_title") or ""))]
    rollup = float(fin.get("current_payroll") or 0)
    return len(owners) == 1 and abs(rollup - 108000.0) < 1.5 \
        and str(owners[0].get("full_name")) == "Delia Rennick"


guarded("Q5 #1 the ACTUAL Sumac duplicate merges: one owner row, 141,999.96 -> 108,000", q5)


def q6():
    people = {
        "people": [
            {"full_name": "Delia Rennick", "role_title": "Owner and Crew Lead",
             "annual_wage": 63960.0, "wage_source": "oews_pct75",
             "relevant_background": "ten years"},
            {"full_name": "", "role_title": "Owner",
             "annual_wage": 34000.0, "wage_source": "client_override"},
        ],
        "rest_of_team_payroll_year1": 0.0,
    }
    fin, people = _sync(people)
    rows = people.get("people") or []
    return len(rows) == 1 and str(rows[0].get("full_name")) == "Delia Rennick" \
        and abs(float(rows[0].get("annual_wage") or 0) - 34000.0) < 0.5 \
        and str(rows[0].get("wage_source")) == "client_override"


guarded("Q6 #1 benchmark row + override row -> one NAMED row at the client's wage", q6)


def q7():
    people = {
        "people": [
            {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
             "annual_wage": 34000.0, "wage_source": "client_override",
             "relevant_background": "ten years"},
            {"full_name": "", "role_title": "Owner",
             "annual_wage": 52000.0, "wage_source": "client_override"},
        ],
        "rest_of_team_payroll_year1": 0.0,
    }
    fin, people = _sync(people)
    rows = people.get("people") or []
    hold = fin.get("_owner_wage_conflict_hold")
    return len(rows) == 1 and isinstance(hold, dict) \
        and abs(float(hold.get("kept") or 0) - 34000.0) < 0.5 \
        and abs(float(hold.get("other") or 0) - 52000.0) < 0.5


guarded("Q7 #1 two DIFFERENT override wages -> one row + the hold (never a silent pick)", q7)


def q8():
    from client_intake_and_finmo.intake_coherence.section import _owner_draw_exit_tail
    tail = _owner_draw_exit_tail(
        {"kind": "owner_dominated", "owner_annual": 100000.0,
         "staffed_annual": 30000.0, "phasable_annual": 0.0},
        {"payroll_to_clear": 122500.0, "revenue_to_clear": 190000.0},
    )
    # (122,500 - 30,000) / 12 = 7,708/mo; the broken shape was 10,208.
    return "$7,708" in tail and "$10,208" not in tail \
        and "rest of the team paid as-is" in tail


guarded("Q8 #2 draw ceiling = (payroll_to_clear - others)/12 -> $7,708, not $10,208", q8)


def q9():
    from client_intake_and_finmo.intake_coherence.section import _owner_draw_exit_tail
    tail = _owner_draw_exit_tail(
        {"kind": "owner_dominated", "owner_annual": 60000.0,
         "staffed_annual": 130000.0, "phasable_annual": 0.0},
        {"payroll_to_clear": 122500.0, "revenue_to_clear": 271000.0},
    )
    return "draw at or below" not in tail and "$271,000" in tail \
        and "revenue is the honest way through" in tail


guarded("Q9 #2 zero-case: no draw exit offered; revenue named as the way through", q9)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
