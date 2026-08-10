# -*- coding: utf-8 -*-
"""CW-024 SLATE RED-PROOF SUITE (Nick's verification standard).

Every check reproduces the ACTUAL Cedar Ridge failure (draft 7deeafb2,
NAICS 561730) through the PRODUCTION chain and asserts the specific
broken number/state now correct. Protocol: run this suite on the
pre-slate baseline 7b9f481 (git stash of tracked source) -> RED; run on
the slate -> GREEN. The lint (_lint_client_copy.py) is its own
red-proof the same way.

Production chains exercised (named per the E2E discipline):
  RP1  people.total_team_payroll door: _apply_scoped_patch -> THE RECALC
       (_sync_financials_consult_persistence_state) -> current_payroll
  RP2  group-row prevention: THE RECALC people subgraph (dedupe vs rest)
  RP3  retention consumer: apply_router_patch -> revenue + utilization
  RP4  acceptance-mismatch hold: _acceptance_mismatch_hold
  RP5  zero-synthesis prevention: _normalize_financials_router_patch
  RP6  park guard: apply_router_patch (answer never parks; explicit does)
  RP7  unlanded-figure backstop: _stamp_unlanded_figures_note
  RP8  durable price ceiling: _effective_pmax consumes the market fact
  RP9  volume fill-cap: ops_line_split -> _volume_round options
  RP10 cadence receipt: numeric_receipt/receipt_summary (stored cadence)
  RP11 not-recorded note: numeric_receipt dropped vs post-write state
  RP12 CORE corrective-client chain: door -> RECALC -> evaluator basis
  RP13 fitted COGS on uncovered NAICS: _compute_cogs_baseline fallback
       (live GPT fit judge; band must exist - bandless unrepresentable)
"""
import copy
import inspect
import io
import re
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv()
results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


def guarded(label, fn):
    try:
        check(label, bool(fn()))
    except Exception as exc:
        check(label + f"  [EXC {type(exc).__name__}: {exc}]", False)


from api_handlers.intake_consult import (  # noqa: E402
    _apply_scoped_patch,
    _sync_financials_consult_persistence_state,
    _normalize_financials_router_patch,
)
from client_intake_and_finmo.intake_coherence import controller as _ctl  # noqa: E402
from client_intake_and_finmo.intake_coherence.controller import (  # noqa: E402
    Thresholds, _volume_round, _effective_pmax, ops_line_split,
)
from client_intake_and_finmo.intake_coherence.evaluator import (  # noqa: E402
    basis_from_intake,
)
from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
    apply_router_patch, get_state, put_state,
)
from client_intake_and_finmo.capture_receipt import (  # noqa: E402
    numeric_receipt, receipt_summary,
)

# ------------------------------------------------------------------ fixtures
# Cedar Ridge Grounds Care shape: revenue $265k, owner + crew lead on the
# roster, rest-of-team $225k ALSO captured as a group person row -> the
# $361k+ phantom; client's true total team payroll $225,000; 34 of 40
# monthly properties served (utilization 0.85) at $650.

CEDAR_OPS = {
    "business_naics_6": "561730",
    "business_type": "Grounds maintenance and landscaping services",
    "lob_models": [{
        "lob_name": "Grounds Care",
        "products": [{
            "product_name": "Monthly maintenance",
            "unit_price": 650.0,
            "units_per_period_capacity": 40.0,
            "operating_periods_per_year": 12.0,
            "utilization_rate": 0.85,
        }],
    }],
}

CEDAR_PEOPLE_PHANTOM = {
    # owner + lead counted as people AND the crew total in rest -> 361k
    "people": [
        {"full_name": "Dana", "role_title": "Owner / Operations",
         "annual_wage": 76000.0},
        {"full_name": "", "role_title": "Crew Lead", "annual_wage": 60000.0},
    ],
    "rest_of_team_payroll_year1": 225000.0,
}

CEDAR_FIN = {
    "current_revenue": 265000.0,
    "monthly_rent_expense": 1800.0,
    "marketing_total_year1": 4800.0,
    "cogs_percent_of_revenue": 0.06,
    "cogs_basis": "ratio",
}


def _recalc(fin, people, ops):
    fin2, _y1 = _sync_financials_consult_persistence_state(
        financials_json=copy.deepcopy(fin),
        financials_year1_json={},
        people_json=people,
        ops_json=ops,
    )
    return fin2


# ------------------------------------------------ RP1: the correction door
def rp1():
    people = copy.deepcopy(CEDAR_PEOPLE_PHANTOM)
    fin = copy.deepcopy(CEDAR_FIN)
    _b, _o, _m, people2, fin2, _f2 = _apply_scoped_patch(
        {"people.total_team_payroll": 225000.0},
        business_facts={}, ops_json=copy.deepcopy(CEDAR_OPS), market_json={},
        people_json=people, financials_json=fin, fulfillment_json={},
    )
    fin3 = _recalc(fin2, people2, copy.deepcopy(CEDAR_OPS))
    got = float(fin3.get("current_payroll") or 0.0)
    print(f"  RP1 current_payroll after door+RECALC: {got:,.0f} (want 225,000)")
    return abs(got - 225000.0) < 1.0


guarded("RP1 'our total team payroll is $225,000' LANDS: current_payroll == 225k "
        "(old: no door, phantom 361k kept)", rp1)


# --------------------------------------- RP2: group-row unrepresentable
def rp2():
    people = {
        "people": [
            {"full_name": "Dana", "role_title": "Owner / Operations",
             "annual_wage": 76000.0},
            {"role_title": "Grounds Maintenance Crew (4 members)",
             "annual_wage": 225000.0},
        ],
        "rest_of_team_payroll_year1": 225000.0,
    }
    fin = _recalc(copy.deepcopy(CEDAR_FIN), people, copy.deepcopy(CEDAR_OPS))
    rollup = float(fin.get("current_payroll") or 0.0)
    no_group_rows = not any(
        "member" in str(p.get("role_title") or "").lower()
        for p in people.get("people") or []
    )
    print(f"  RP2 rollup with crew stated twice: {rollup:,.0f} (want 301,000, "
          f"old double-counts to 526,000); group rows gone: {no_group_rows}")
    return abs(rollup - 301000.0) < 1.0 and no_group_rows


guarded("RP2 a crew-of-N row cannot persist as a person: dedupe vs rest-of-team "
        "(old: crew counted twice)", rp2)


# --------------------------------------- RP3: retention answer consumed
def rp3():
    fin = copy.deepcopy(CEDAR_FIN)
    state = {"retention_pending": {"prices": [], "retained_used": 0.80}}
    fin = put_state(fin, state)
    ops = copy.deepcopy(CEDAR_OPS)
    remaining, ops2, fin2, notes = apply_router_patch(
        patch={"coherence.retention_answer": {"kept": 30, "of": 34}},
        ops_json=ops, financials_json=fin,
    )
    want_rev = round(265000.0 * (30.0 / 34.0) / 0.80, 2)
    got_rev = float(fin2.get("current_revenue") or 0.0)
    util = float(ops2["lob_models"][0]["products"][0]["utilization_rate"])
    want_util = round(min(1.0, 0.85 * (30.0 / 34.0) / 0.80), 4)
    cleared = "retention_pending" not in get_state(fin2)
    print(f"  RP3 revenue {got_rev:,.2f} (want {want_rev:,.2f}); "
          f"utilization {util} (want {want_util}); pending cleared: {cleared}; "
          f"notes: {notes}")
    return (abs(got_rev - want_rev) < 1.0 and abs(util - want_util) < 0.001
            and cleared and "retention_answer" in notes)


guarded("RP3 '30 of my 34' OVERRIDES the 0.80 default and re-lands revenue + "
        "utilization (old: answer dropped, default kept)", rp3)


# ------------------------------------ RP4: acceptance-mismatch is a hold
def rp4():
    from api_handlers.intake_consult import _acceptance_mismatch_hold
    q = _acceptance_mismatch_hold(
        stage_name="marketing",
        user_message="sure, that works - but honestly I don't spend anything "
                     "like that today",
    )
    clean = _acceptance_mismatch_hold(
        stage_name="marketing", user_message="yes, that works for me",
    )
    print(f"  RP4 mismatch -> hold question: {bool(q)}; clean accept -> no hold: "
          f"{clean is None}")
    return bool(q) and clean is None


guarded("RP4 'sure, but that's not what I spend' cannot record as a clean accept "
        "(old: recorded as agreement)", rp4)


# ---------------------------------------- RP5: turn 38 replayed verbatim
def rp5():
    # The EXACT Cedar Ridge turn 38 (issue-DB evidence): capex question
    # pending, the client sends a standalone payroll correction, the
    # router returns answer_readonly prose CLAIMING a zero write plus a
    # patch that entirely drops. Production chain entered at
    # _run_financials_turn_and_sync with the recorded router output
    # injected (route_intent is a parameter); everything downstream -
    # stage resolution, door, normalize, reply assembly - is production.
    from api_handlers.intake_consult import (
        _run_financials_turn_and_sync, _FINANCIALS_STAGE_ORDER,
        _FINANCIALS_STAGE_SPECS, _next_financials_stage,
    )
    fin = dict(copy.deepcopy(CEDAR_FIN))
    fin.update({
        "current_revenue": 265000.0, "_financials_revenue_intro_done": 1,
        "current_cogs": 15900.0, "current_payroll": 361000.0,
        "marketing_total_year1": 4800.0, "monthly_rent_expense": 1800.0,
        "future_rent_expected": "no", "other_operating_expense": 900.0,
        "current_num_employees": 5,
    })
    for st in _FINANCIALS_STAGE_ORDER:
        if st == "current_capex":
            break
        for f in _FINANCIALS_STAGE_SPECS[st]["completion_fields"]:
            if fin.get(f) in (None, ""):
                fin[f] = 1
    if _next_financials_stage(fin) != "current_capex":
        print(f"  RP5 fixture wrong: pending stage is "
              f"{_next_financials_stage(fin)!r}")
        return False

    def recorded_router(**kwargs):
        return {
            "action": "answer_readonly",
            "assistant_message": (
                "Got it - I will use 0 for current capital spending for "
                "now. What would you say the main equipment currently in "
                "the business is worth, all together?"
            ),
            "patch": {"financials.current_capex": 0.0,
                      "financials.payroll_total_year1": 225000.0},
        }

    turn, fin_out = _run_financials_turn_and_sync(
        route_intent=recorded_router,
        conn=None,
        intake_context={"draft_id": "redproof-cedar"},
        conversation_messages=[],
        business_facts={},
        shared_context={"people_capability": copy.deepcopy(CEDAR_PEOPLE_PHANTOM),
                        "operating_model": copy.deepcopy(CEDAR_OPS)},
        last_assistant="What would you say the main equipment, devices, "
                       "furniture, and fixtures currently in the business "
                       "are worth, all together? A rough estimate is fine.",
        user_message="Before the equipment question - my total annual "
                     "payroll is 225,000. Please correct it to 225,000.",
        financials_json=fin,
        financials_year1_json={"company_revenue_total_year1": 265000.0},
    )
    msg = str(turn.get("assistant_message") or "")
    capex_zeroed = float(fin_out.get("current_capex") or -1.0) == 0.0
    claims_zero = "use 0" in msg.lower() or "use $0" in msg.lower()
    print(f"  RP5 reply: {msg[:180]!r}")
    print(f"  RP5 capex zeroed: {capex_zeroed}; reply claims zero: {claims_zero}")
    return not capex_zeroed and not claims_zero


guarded("RP5 turn 38 verbatim: the reply cannot claim 'I will use 0' and no "
        "zero lands (old: prose shipped the false confirmation)", rp5)


# ----------------------------------------------------- RP6: park guard
def rp6():
    fin = put_state(copy.deepcopy(CEDAR_FIN), {"status": "active"})
    kwargs = dict(
        patch={"coherence.parked": "true",
               "financials.monthly_rent_expense": 2200.0},
        ops_json=copy.deepcopy(CEDAR_OPS), financials_json=fin,
    )
    if "user_text" in inspect.signature(apply_router_patch).parameters:
        kwargs["user_text"] = ("our rent is actually 2200 a month and "
                               "utilities run about 400")
    _r, _o, fin2, notes = apply_router_patch(**kwargs)
    parked = get_state(fin2).get("status") == _ctl.STATUS_PARKED
    print(f"  RP6 answer turn parked: {parked} (want False); notes: {notes}")
    if parked or "park_ignored_no_explicit_intent" not in notes:
        return False
    # invariant (green on both): an EXPLICIT stop still parks
    kwargs2 = dict(patch={"coherence.parked": "true"},
                   ops_json=copy.deepcopy(CEDAR_OPS),
                   financials_json=put_state(copy.deepcopy(CEDAR_FIN),
                                             {"status": "active"}))
    if "user_text" in inspect.signature(apply_router_patch).parameters:
        kwargs2["user_text"] = "let's stop here for today - save it for now"
    _r2, _o2, fin3, _n2 = apply_router_patch(**kwargs2)
    explicit_parks = get_state(fin3).get("status") == _ctl.STATUS_PARKED
    print(f"  RP6 explicit stop still parks: {explicit_parks}")
    return explicit_parks


guarded("RP6 a turn that ANSWERS cannot park the session; explicit stop-intent "
        "still can (old: router park unconditional)", rp6)


# ------------------------------------- RP7: unlanded-figure backstop
def rp7():
    from api_handlers.intake_consult import _stamp_unlanded_figures_note
    fin = _stamp_unlanded_figures_note(
        financials_json=copy.deepcopy(CEDAR_FIN),
        people_json=copy.deepcopy(CEDAR_PEOPLE_PHANTOM),
        ops_json=copy.deepcopy(CEDAR_OPS),
        user_message="again - with the seasonal help our real payroll is "
                     "$218,500, not what you have",
        applied_notes=[], patch={},
    )
    note = fin.get("_unlanded_note")
    print(f"  RP7 _unlanded_note stamp: {note!r}")
    figs = (note or {}).get("figures") if isinstance(note, dict) else None
    return bool(figs) and any(abs(float(f) - 218500.0) < 0.01 for f in figs)


guarded("RP7 a money figure that lands NOWHERE is disclosed next turn "
        "(old: seven corrections vanished silently)", rp7)


# ------------------------------ RP8: price ceiling is a durable fact
def rp8():
    # Epoch 2 re-authoring after an acceptance: authored price walked up
    # to the old ceiling, relative multiplier re-granted. The FACT holds.
    bl = {"price_multiplier_max": 1.15, "unit_price_at_authoring": 109.25,
          "price_ceiling_market_fact": 109.25}
    line = {"unit_price": 109.25}
    eff = _effective_pmax(line, bl)
    offer = 109.25 * eff
    print(f"  RP8 offer ceiling after acceptance: ${offer:,.2f} "
          f"(want $109.25, old ladder: $125.64)")
    return abs(offer - 109.25) < 0.01


guarded("RP8 accepting a price cannot raise the ceiling: the market fact caps "
        "the next offer (old: ratchet re-granted +15%)", rp8)


# ------------------------------------------ RP9: volume fill-cap
def rp9():
    fin = dict(copy.deepcopy(CEDAR_FIN))
    fin["current_payroll"] = 301000.0
    split = ops_line_split(copy.deepcopy(CEDAR_OPS), fin)
    if not split:
        print("  RP9 no split lines derived")
        return False
    annual_units_now = float(split[0].get("annual_units") or 0.0)
    th = Thresholds(gm_floor=0.3, burden_max=0.85, band_low=0.55,
                    ni_floor=0.02, band_high=0.60, judged=True)
    basis = basis_from_intake(financials_json=fin,
                              ops_json=copy.deepcopy(CEDAR_OPS),
                              financials_year1_json={})
    bounds = {"existing_lines": [{
        "lob": "Grounds Care", "product": "Monthly maintenance",
        "volume_multiplier_max": 1.5,
        "annual_units_at_authoring": annual_units_now,
    }]}
    rnd = _volume_round(basis, th, bounds, split)
    if not rnd:
        print("  RP9 no volume round built (no gap?)")
        return False
    capacity_annual = 40.0 * 12.0
    worst = 0.0
    for o in rnd.get("options") or []:
        for v in o.get("volumes") or []:
            worst = max(worst, float(v.get("to_annual_units") or 0.0))
    print(f"  RP9 largest offered annual units: {worst:,.0f} "
          f"(stored capacity {capacity_annual:,.0f}; old offer ~612)")
    return 0.0 < worst <= capacity_annual + 1.0


guarded("RP9 volume options stop at 100% of stored capacity "
        "(old: offered 42-51 properties against a 40 ceiling)", rp9)


# --------------------------------- RP10: cadence-true capacity receipt
def rp10():
    before = {"lob_models": [{"lob_name": "Grounds Care", "products": [{
        "product_name": "Monthly maintenance", "unit_price": 650.0,
        "units_per_week_capacity": 34.0, "operating_periods_per_year": 12.0,
    }]}]}
    after = copy.deepcopy(before)
    after["lob_models"][0]["products"][0]["units_per_week_capacity"] = 40.0
    receipt = numeric_receipt(before={"ops": before}, after={"ops": after})
    line = receipt_summary(receipt)
    print(f"  RP10 receipt line: {line!r}")
    return "monthly capacity" in line and "weekly capacity" not in line


guarded("RP10 capacity receipt speaks the STORED cadence: 'monthly capacity', "
        "never 'weekly' against a monthly model (old: hardcoded weekly)", rp10)


# ------------------------------ RP11: 'not recorded' reads the store
def rp11():
    after_fin = {"monthly_rent_expense": 1800.0, "baseline_marketing": 4800.0,
                 "marketing_adjustment": 0.0}
    receipt = numeric_receipt(
        before={"financials": after_fin}, after={"financials": after_fin},
        requested_fields=["financials.baseline_marketing",
                          "financials.marketing_adjustment",
                          "financials.monthly_rent_expense"],
    )
    print(f"  RP11 dropped: {receipt['dropped']!r} (want [])")
    return receipt["dropped"] == []


guarded("RP11 already-stored and derived fields cannot appear in a 'not "
        "recorded yet' note (old: raw baseline_* names read to the client)", rp11)


# ------------------- RP12 CORE: the corrective-client chain end to end
def rp12():
    # The Cedar Ridge conversation, replayed: phantom roster -> client
    # states the true total -> door -> RECALC -> the gate's own evaluator
    # basis carries 225k. This is the number every verdict downstream
    # reads; on the old code the walk negotiated 361k+ to the end.
    people = copy.deepcopy(CEDAR_PEOPLE_PHANTOM)
    fin = copy.deepcopy(CEDAR_FIN)
    _b, _o, _m, people2, fin2, _f2 = _apply_scoped_patch(
        {"people.total_team_payroll": 225000.0},
        business_facts={}, ops_json=copy.deepcopy(CEDAR_OPS), market_json={},
        people_json=people, financials_json=fin, fulfillment_json={},
    )
    fin3 = _recalc(fin2, people2, copy.deepcopy(CEDAR_OPS))
    basis = basis_from_intake(financials_json=fin3,
                              ops_json=copy.deepcopy(CEDAR_OPS),
                              financials_year1_json={})
    if basis is None:
        print("  RP12 no basis derived")
        return False
    payroll_annual = basis.payroll_quarterly * 4.0
    print(f"  RP12 evaluator payroll basis: {payroll_annual:,.0f}/yr "
          f"(want 225,000 - the verdict now judges the client's real team)")
    return abs(payroll_annual - 225000.0) < 1.0


guarded("RP12 CORE the gate's evaluator judges the CORRECTED payroll, not the "
        "phantom (old: verdict built on $361k)", rp12)


# ------------------ RP13: fitted COGS band on an uncovered NAICS (GPT)
def rp13():
    from api_handlers.intake_consult import _compute_cogs_baseline

    class _Cur:
        def execute(self, *a, **k):
            return None

        def fetchall(self):
            return []

        def fetchone(self):
            return None

        def close(self):
            return None

    class _Conn:
        def cursor(self, *a, **k):
            return _Cur()

    baseline = _compute_cogs_baseline(
        conn=_Conn(),
        ops_json=copy.deepcopy(CEDAR_OPS),
        shared_context={"business_facts": {
            "business_type": "Grounds maintenance and landscaping services",
            "business_stage": "existing",
        }},
        financials_year1_json={"company_revenue_total_year1": 265000.0},
    )
    if not isinstance(baseline, dict):
        print(f"  RP13 baseline: {baseline!r}")
        return False
    band = baseline.get("cogs_fit_band")
    pct = float(baseline.get("baseline_cogs_percent") or 0.0)
    print(f"  RP13 uncovered-NAICS proposal: {pct:.1%} band={band!r} "
          f"rationale={str(baseline.get('cogs_basis_rationale'))[:90]!r}")
    ok_band = (isinstance(band, (list, tuple)) and len(band) == 2
               and float(band[0]) < float(band[1]))
    # Cedar's true materials ran ~6%; the old flat estimator said 42%.
    return ok_band and 0.0 < pct < 0.30


guarded("RP13 uncovered NAICS 561730 gets a FITTED BAND proposal, never a "
        "bandless flat guess (old: flat 42% on ~6% true materials)", rp13)


print()
print(f"{sum(results)}/{len(results)} red-proof checks green")
sys.exit(0 if all(results) else 1)
