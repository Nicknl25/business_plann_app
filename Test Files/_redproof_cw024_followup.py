# -*- coding: utf-8 -*-
"""CW-024 FOLLOW-UP RED-PROOFS: the essentials judge + the posture fix.

Same standard as _redproof_cw024_slate.py: every check reproduces the
broken behavior through the PRODUCTION chain, RED on the pre-build code
(git stash of tracked source), GREEN after.

  RQ1 essentials floors: _costs_round offers ONLY the discretionary
      slice of a judged line, names what stays protected, and the
      deep-cut homework line is superseded by the reasoned wording
  RQ2 thin doctrine: withheld essentials -> ask-first wording retained
      (absence of judgment is never a verdict)
  RQ3 validator rails: thin => withheld whatever GPT said; too-narrow
      bands widen UPWARD (the conservative direction for cuts)
  RQ4 judge-not-list (LIVE): the production seam authors DIFFERENT
      named essentials for two different businesses with identical
      dollar lines - a hardcoded category list cannot do that
  RQ5 roadmap copy: distance framing, promises verbatim, defeat
      framing unrepresentable
  RQ6 two-beat + tripwire (LIVE): a mid-walk corner collapse holds
      with a what-changed disclosure instead of answering a client
      turn with terminal defeat; the roadmap that follows carries the
      receipt and the distance copy
  RQ7 invariant (green on both): gate-entry roadmap keeps its
      immediate timing - the tripwire is mid-walk only
"""
import copy
import io
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
        check(label + f"  [EXC {type(exc).__name__}: {str(exc)[:120]}]", False)


from client_intake_and_finmo.intake_coherence.controller import (  # noqa: E402
    Thresholds, _costs_round,
)
from client_intake_and_finmo.intake_coherence.evaluator import (  # noqa: E402
    basis_from_intake,
)

OPS = {"lob_models": [{"lob_name": "Grounds Care", "products": [{
    "product_name": "Monthly maintenance", "unit_price": 650.0,
    "units_per_period_capacity": 40.0, "operating_periods_per_year": 12.0,
    "utilization_rate": 0.85}]}]}
FIN = {"current_revenue": 265000.0, "baseline_payroll_year1": 120000.0,
       "current_payroll": 120000.0, "payroll_total_year1": 120000.0,
       "other_opex_absolute": 72000.0, "marketing_total_year1": 600.0,
       "cogs_percent_of_revenue": 0.06}
TH = Thresholds(gm_floor=0.3, burden_max=0.85, band_low=0.55,
                ni_floor=0.02, band_high=0.60, judged=True)
BOUNDS = {"existing_lines": [], "team": {},
          "cost_floors": {"g_and_a_percent_of_revenue_min": 0.02}}


def _round_with(essentials):
    basis = basis_from_intake(financials_json=dict(FIN), ops_json=OPS,
                              financials_year1_json={})
    return basis, _costs_round(basis, TH, BOUNDS, dict(FIN),
                               essentials=essentials)


# ---------------- RQ1: only the discretionary slice is offerable
def rq1():
    ess = {"withheld": False, "lines": {"gna": {
        "essential_fraction_band": [0.20, 0.35],
        "named_essentials": "insurance, fuel, and licensing",
        "basis": "test",
    }}}
    basis, rnd = _round_with(ess)
    if not rnd:
        print("  RQ1 no costs round built")
        return False
    gna_moves = [o["moves"]["gna"] for o in rnd["options"] if "gna" in o.get("moves", {})]
    if not gna_moves:
        print("  RQ1 no gna move offered")
        return False
    cur_annual = basis.gna_pct * basis.q1_revenue_quarterly * 4.0
    floor_annual = cur_annual * 0.35
    to_txt = gna_moves[0]["to_display"]
    offered = float(to_txt.replace(",", "").split("$")[1].split(" ")[0].split("(")[0])
    labels = [o["label"] for o in rnd["options"] if "gna" in o.get("moves", {})]
    print(f"  RQ1 current {cur_annual:,.0f}, protected floor {floor_annual:,.0f}, "
          f"offered {offered:,.0f}; display: {to_txt!r}")
    print(f"  RQ1 label: {labels[0]!r}")
    return (offered >= floor_annual - 1.0
            and "insurance, fuel, and licensing" in to_txt
            and any("sized around the costs" in l for l in labels)
            and not any("tell me what's in them first" in l for l in labels))


guarded("RQ1 a judged line's cut stops at the essential share, names what "
        "stays, and the homework line is superseded (old: full-floor cut + "
        "'tell me what's in them first')", rq1)


# ---------------- RQ2: thin doctrine keeps ask-first
def rq2():
    _, rnd = _round_with(None)
    if not rnd:
        print("  RQ2 no costs round built")
        return False
    labels = [o["label"] for o in rnd["options"] if "gna" in o.get("moves", {})]
    deep = any(o.get("deep_cut") for o in rnd["options"])
    print(f"  RQ2 deep={deep}; label: {labels[0][:120]!r}")
    if not deep:
        return False  # fixture must produce a deep cut for the doctrine test
    return (any("tell me what's in them first" in l for l in labels)
            and not any("sized around the costs" in l for l in labels))


guarded("RQ2 no judgment -> the ask-first wording stands (absence of "
        "judgment is never a verdict)", rq2)


# ---------------- RQ3: validator rails
def rq3():
    from client_intake_and_finmo.intake_coherence.gpt_essentials_judgment import (
        validate_essentials,
    )
    confident_junk = {
        "gna": {"essential_fraction_band": [0.60, 0.62],
                "named_essentials": "everything", "basis": "vibes"},
        "cogs": {"essential_fraction_band": [0.9, 0.9],
                 "named_essentials": "all of it", "basis": "vibes"},
        "rationale": "sure",
    }
    thin = validate_essentials(judgment=confident_junk,
                               evidence={"level": "thin", "reasons": ["no_business_type"]})
    rich = validate_essentials(judgment=confident_junk,
                               evidence={"level": "rich", "reasons": []})
    g = rich["lines"]["gna"]["essential_fraction_band"]
    c = rich["lines"]["cogs"]["essential_fraction_band"]
    print(f"  RQ3 thin withheld={thin.get('withheld')} lines={thin.get('lines')}; "
          f"rich gna band={g} cogs band={c}")
    return (thin.get("withheld") is True and thin.get("lines") == {}
            and abs(g[1] - 0.70) < 1e-6 and abs(g[0] - 0.60) < 1e-6
            and abs(c[1] - 1.0) < 1e-6 and abs(c[0] - 0.9) < 1e-6)


guarded("RQ3 thin evidence withholds whatever GPT said; narrow bands widen "
        "UPWARD - the cut can only get more protective, never deeper", rq3)


# ---------------- RQ4: judge, not a list (LIVE production seam)
def rq4():
    from client_intake_and_finmo.intake_coherence.section import (
        _ensure_essentials_response,
    )
    fin = {"current_revenue": 265000.0, "current_payroll": 120000.0,
           "monthly_rent_expense": 1800.0, "marketing_total_year1": 4800.0,
           "other_opex_absolute": 72000.0, "cogs_total_year1": 15900.0,
           "other_operating_expense": 6000.0}
    ops_a = {"business_type": "Grounds maintenance and landscaping services",
             "business_naics_6": "561730",
             "business_description_summary":
                 "Crew-based commercial grounds maintenance under monthly "
                 "contracts; trucks, mowers, and trailers serve properties "
                 "across the metro.",
             "lob_models": OPS["lob_models"]}
    ops_b = {"business_type": "Independent software consultancy",
             "business_naics_6": "541511",
             "business_description_summary":
                 "Two-partner remote software consultancy billing weekly "
                 "retainers; work happens on laptops over the internet, no "
                 "vehicles, no field crews.",
             "lob_models": [{"lob_name": "Consulting", "products": [{
                 "product_name": "Weekly retainer", "unit_price": 5000.0,
                 "units_per_period_capacity": 4.0,
                 "operating_periods_per_year": 52.0, "utilization_rate": 0.6}]}]}
    out = []
    for ops in (ops_a, ops_b):
        st = _ensure_essentials_response(
            {}, compact={"business_type": ops["business_type"],
                         "description": ops["business_description_summary"],
                         "naics": ops["business_naics_6"]},
            ops_json=ops, financials_json=dict(fin),
        )
        resp = st.get("essentials_response") or {}
        out.append(resp)
        print(f"  RQ4 {ops['business_type'][:30]!r}: withheld={resp.get('withheld')} "
              f"lines={ {k: v.get('named_essentials') for k, v in (resp.get('lines') or {}).items()} }")
    a, b = out
    if a.get("withheld") or b.get("withheld"):
        return False
    ga, gb = (a.get("lines") or {}).get("gna"), (b.get("lines") or {}).get("gna")
    if not (ga and gb):
        return False
    same_dollars_different_reasoning = (
        ga["named_essentials"].strip().lower() != gb["named_essentials"].strip().lower()
    )
    bands_ok = all(
        0.0 <= v["essential_fraction_band"][0] < v["essential_fraction_band"][1] <= 1.0
        and v["essential_fraction_band"][1] - v["essential_fraction_band"][0] >= 0.0999
        for r in (a, b) for v in (r.get("lines") or {}).values()
    )
    return same_dollars_different_reasoning and bands_ok


guarded("RQ4 LIVE the seam authors DIFFERENT named essentials for two "
        "businesses with identical dollar lines - reasoning, not a category "
        "list (old: no judge existed)", rq4)


# ---------------- RQ5: roadmap copy is distance, not defeat
def rq5():
    from client_intake_and_finmo.intake_coherence.section import _roadmap_message
    msg = _roadmap_message({
        "corner_gap_display": "$41,753",
        "milestones": [
            {"title": "a volume ceiling that moves",
             "detail": "standing accounts beyond the current setup"},
        ],
    })
    print(f"  RQ5 message head: {msg[:140]!r}")
    promises = ("Your numbers stay right here - when one of those changes, "
                "come back and we rerun the same arithmetic. Nothing ships "
                "saying the business doesn't work on paper, and nothing gets "
                "faked to say it does.")
    return ("distance, not worth" in msg
            and promises in msg
            and "I have to be straight with you" not in msg
            and "a plan that says you fail" not in msg
            and "Which of those is closest to something you're already doing?" in msg)


guarded("RQ5 the roadmap speaks distance and invitation with both promises "
        "verbatim; the defeat framing is unrepresentable (old: 'I have to be "
        "straight with you... a plan that says you fail')", rq5)


# ---------------- RQ6 + RQ7: the gate itself (LIVE authoring)
from client_intake_and_finmo.intake_coherence.section import gate_and_turn  # noqa: E402

# The mid-walk collapse, DETERMINISTIC: state pre-stamped exactly as a
# stale-pop leaves it (walking status survives; bounds stand; corner
# POPPED so the gate's own corner_check recomputes) - every judged
# artifact present so no ensure authors. The recompute fails the corner
# while the file is walking: the Cedar class, through gate_and_turn.
WALK_OPS = {"business_type": "Commercial cleaning services",
            "business_naics_6": "561720",
            "business_description_summary":
                "Commercial office cleaning under recurring monthly "
                "contracts with night crews.",
            "lob_models": [{"lob_name": "Cleaning", "products": [{
                "product_name": "Monthly office contract", "unit_price": 1200.0,
                "units_per_period_capacity": 22.0,
                "operating_periods_per_year": 12.0, "utilization_rate": 0.8}]}]}
WALK_FIN = {"current_revenue": 253440.0, "baseline_payroll_year1": 260000.0,
            "current_payroll": 260000.0, "payroll_total_year1": 260000.0,
            "other_opex_absolute": 55000.0, "marketing_total_year1": 12000.0,
            "cogs_percent_of_revenue": 0.07, "monthly_rent_expense": 2500.0}


def _stamped_walking_state(fin, ops):
    from client_intake_and_finmo.intake_coherence.section import (
        _compute_band_identity_digest,
    )
    state = {
        "margin_band_judgment": {
            "q11": {"low": 0.12, "high": 0.22},
            "gross_margin_floor_q11": 0.30,
            "fixed_cost_burden_max_q11": 0.90,
            "ni_margin_floor_q11": 0.02,
            "labor_intensity_class": "high",
            "labor_treatment": "all_labor_in_payroll_line",
        },
        "judged_growth": {"qoq_start": 0.05, "qoq_end": 0.02,
                          "source": "test", "year1_annual_growth": 0.2,
                          "mature_annual_growth": 0.08},
        "demand_response": {"evidence_level": "thin", "withheld": True,
                            "price_response": None, "marketing_response": None,
                            "volume_headroom": None, "notes": []},
        "essentials_response": {"evidence_level": "thin", "withheld": True,
                                "lines": {}, "notes": []},
        "status": "walking",
        "gap_open": 9000.0, "gap_initial": 12000.0,
        "round": {"key": "cost_structure"},
        "rounds_done": [],
        "_lever_writes": {"marketing_total_year1":
                          {"from": 23850.0, "to": 12000.0}},
        # Bounds so tight the recomputed corner cannot clear the band.
        "bounds": {
            "feasible_region_exists": True,
            "existing_lines": [{
                "lob": "Cleaning", "product": "Monthly office contract",
                "price_multiplier_max": 1.02, "volume_multiplier_max": 1.0,
                "unit_price_at_authoring": 1200.0,
                "annual_units_at_authoring": 211.0,
            }],
            "cost_floors": {"g_and_a_percent_of_revenue_min": 0.21,
                            "marketing_percent_of_revenue_min": 0.045,
                            "cogs_percent_of_revenue_min": 0.07},
            # The Cedar shape exactly: the judged team floor sits ABOVE
            # the stated payroll - even the corner carries it.
            "team": {"min_annual_payroll": 275000.0},
            "facility": {"min_quarterly_rent": 7500.0},
        },
    }
    digest, _ = _compute_band_identity_digest(
        state, ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=fin,
    )
    state["digest_hash"] = digest
    return state


def rq6():
    ops = copy.deepcopy(WALK_OPS)
    fin = dict(WALK_FIN)
    fin["_coherence"] = _stamped_walking_state(fin, ops)
    turn1, fin1, _ = gate_and_turn(
        ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=fin,
        financials_year1_json={},
        user_text="ok, what's next?")
    st1 = fin1.get("_coherence") or {}
    msg1 = str((turn1 or {}).get("assistant_message") or "")
    print(f"  RQ6 turn1 status={st1.get('status')!r} hold="
          f"{bool(st1.get('corner_collapse_hold'))} "
          f"corner_passed={(st1.get('corner') or {}).get('passed')}")
    print(f"  RQ6 turn1 msg: {msg1[:150]!r}")
    if not ((st1.get("corner") or {}).get("passed") is False):
        print("  RQ6 fixture wrong: corner did not fail on recompute")
        return False
    if st1.get("status") == "roadmap":
        print("  RQ6 RED SHAPE: terminal defeat as the direct answer")
        return False
    if not (st1.get("status") == "walking" and st1.get("corner_collapse_hold")
            and "usually means an input is off" in msg1
            and "What changed on my side" in msg1
            and "I have to be straight with you" not in msg1):
        return False
    # The client confirms the inputs; the roadmap arrives WITH the pick
    # receipt first and the distance copy.
    turn2, fin2, _ = gate_and_turn(
        ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=dict(fin1),
        financials_year1_json={},
        user_text="those figures are all correct, that's really my payroll")
    st2 = fin2.get("_coherence") or {}
    msg2 = str((turn2 or {}).get("assistant_message") or "")
    print(f"  RQ6 turn2 status={st2.get('status')!r} msg: {msg2[:150]!r}")
    return (st2.get("status") == "roadmap"
            and msg2.startswith("First:")
            and "distance, not worth" in msg2
            and "I have to be straight with you" not in msg2)


guarded("RQ6 LIVE a mid-walk corner collapse HOLDS with a what-changed "
        "disclosure, then delivers the distance roadmap on confirmation "
        "(old: terminal defeat as the direct answer to the client's turn)", rq6)


def rq7():
    # Corner fails at GATE ENTRY (never walked): the roadmap keeps its
    # immediate timing - no tripwire hold. Tiny revenue, huge team.
    fin = {"current_revenue": 60000.0, "baseline_payroll_year1": 150000.0,
           "current_payroll": 150000.0, "payroll_total_year1": 150000.0,
           "other_opex_absolute": 30000.0, "marketing_total_year1": 3000.0,
           "cogs_percent_of_revenue": 0.05, "monthly_rent_expense": 2000.0}
    ops = {"business_type": "Residential cleaning service",
           "business_naics_6": "561720",
           "business_description_summary": "Small residential cleaning outfit.",
           "lob_models": [{"lob_name": "Cleaning", "products": [{
               "product_name": "House clean", "unit_price": 150.0,
               "units_per_period_capacity": 8.0,
               "operating_periods_per_year": 52.0, "utilization_rate": 0.96}]}]}
    turn, fin_out, _ = gate_and_turn(
        ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=fin,
        financials_year1_json={})
    st = fin_out.get("_coherence") or {}
    msg = str((turn or {}).get("assistant_message") or "")
    print(f"  RQ7 status={st.get('status')!r} hold="
          f"{bool(st.get('corner_collapse_hold'))} msg: {msg[:110]!r}")
    if st.get("status") == "roadmap":
        return not st.get("corner_collapse_hold") and "distance, not worth" in msg
    print("  RQ7 fixture did not roadmap at entry - adjust fixture")
    return False


guarded("RQ7 invariant: gate-entry roadmap stays immediate (tripwire is "
        "mid-walk only) and speaks the distance copy", rq7)


print()
print(f"{sum(results)}/{len(results)} follow-up red-proof checks green")
sys.exit(0 if all(results) else 1)
