"""CW-033 turn 3 -- mini's four fixes, proven on the real module (offline).

M1  F1(b) at the financials-interview ship gate: no sentence of the reply
    may claim a write the turn did not make. Here the ack-fallback half:
    router free prose that claims a write or acks a stated figure never
    ships as the acknowledgement (the live A4b halves are proven in
    Test Files/_live_cw033_turn3_turns.py).
M2  The ops write door refuses mid-interview regardless of wording: while
    a financials stage is active, _apply_forward_move's ops branch returns
    the honest redirect and writes nothing. At the wall it lands unchanged.
M3  A stated cadence is never silently re-based: "40 a week" on a contract
    row (12 periods/yr) converts to 173.33/period, the receipt speaks
    "40 a week", an ambiguous cadence asks, and the weekly-row control
    lands 7/7 exactly as before.
B3  The capex but-we-did carve-out: a negative lead that ALSO states a
    real purchase is not a none-answer; the landing numeric is scoped to
    the post-carve-out clause so the excluded base still cannot land.

Uses REAL draft shapes read from the DB (Thornfield d9b17850 multi-line,
Sumac 2ecc759c contract row) - no server needed.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw033_turn3_fixes.py"
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

THORN = "d9b17850350545e9911fa09b3e333429"
SUMAC = "2ecc759c5d934706ad95123831f9e0c2"

_STRIP_FROM_RENT = (
    "monthly_rent_expense", "future_rent_expected", "other_operating_expense",
    "current_num_employees", "current_capex", "initial_assets",
    "initial_lease", "initial_equity", "total_debt_outstanding",
    "other_monthly_debt_payments", "annual_interest_payment",
    "annual_principal_payment", "cash_on_hand", "ar_balance", "ap_balance",
    "inventory_balance", "cash_strategy", "funding_preference",
    "funding_split_debt_share",
)

D1_WORDING = (
    "Hang on, one fix on operations - the install crew can actually do "
    "7 jobs a week, not 5. Please update that."
)
D3_WORDING = "Our mowing route capacity should be 40 a week, not 34."
A4B_PROSE = "Got it — I’ll update the hard goods checkout ticket price to 99."
A4B_MSG = (
    "One more thing - bump the hard goods ticket price to 99 instead of 95."
)
B3_MSG = (
    "No, none of it was bought this year - but we did spend 15,000 on a "
    "mower back in January."
)
B3_BOTH_HALVES = (
    "None of it this year, we've got about 380,000 sitting there - but we "
    "did spend 15,000 on a mower."
)
B1_MSG = (
    "Not really, no. Over the years we've built up about 380,000 worth of "
    "trucks and greenhouse equipment, but none of that was bought this year."
)


def _load_shapes():
    """Fetch the two real drafts' financials + ops once."""
    load_dotenv(REPO_ROOT / ".env", override=False)
    from intake_submission import get_mysql_connection  # type: ignore

    conn = get_mysql_connection()
    out = {}
    cur = conn.cursor(dictionary=True)
    for name, did in (("thorn", THORN), ("sumac", SUMAC)):
        cur.execute(
            "SELECT financials_json, operating_model_json, people_json "
            "FROM intake_consult_drafts WHERE draft_id=%s", (did,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"source draft missing: {did}")
        out[name] = {
            "fin": json.loads(row["financials_json"] or "{}"),
            "ops": json.loads(row["operating_model_json"] or "{}"),
            "people": json.loads(row["people_json"] or "{}"),
        }
    cur.close()
    conn.close()
    return out


def _rows(ops):
    return {
        str(p.get("product_name")): p
        for lm in (ops.get("lob_models") or [])
        for p in (lm.get("products") or [])
        if isinstance(p, dict)
    }


def _fwd(ic, *, shapes_key, shapes, fin_mut=(), move=None, message=""):
    """Run _apply_forward_move on a deepcopy of a real draft shape."""
    fin = copy.deepcopy(shapes[shapes_key]["fin"])
    for f in fin_mut:
        fin.pop(f, None)
    shared = {
        "operating_model": copy.deepcopy(shapes[shapes_key]["ops"]),
        "people_capability": copy.deepcopy(shapes[shapes_key]["people"]),
    }
    fin_out, shared_out, cp = ic._apply_forward_move(
        move=dict(move), stage_shared_context=shared,
        next_financials=fin, financials_year1_json={},
        conn=None, intake_context={"draft_id": "redproof-cw033"},
        user_message=message, last_assistant="",
    )
    return fin_out, shared_out, cp


def run_checks(ic, shapes, check):
    """Each section is exception-shielded so a PRE-FIX module (missing
    helpers, old signatures) reds the section's checks instead of killing
    the run - red for the right reason, legible either way."""
    for _section in (_checks_m2_m3, _checks_m1, _checks_b3):
        try:
            _section(ic, shapes, check)
        except Exception as e:  # noqa: BLE001
            check(f"{_section.__name__} completed without error", False, repr(e))


def _checks_m2_m3(ic, shapes, check):
    CAP_MOVE = {"key": "ops.units_per_week_capacity", "value": 7.0,
                "label": "capacity", "attributed": True}

    # ---- M2: the write door owns the boundary --------------------------
    _, sh, cp = _fwd(ic, shapes_key="thorn", shapes=shapes,
                     fin_mut=_STRIP_FROM_RENT, move=CAP_MOVE,
                     message=D1_WORDING)
    inst = _rows(sh["operating_model"]).get("Landscaping/installation job", {})
    check("M2a mid-interview ops move REFUSES with the redirect",
          "haven't changed any operations capacity" in cp, cp[:160])
    check("M2b mid-interview: NOTHING written (install still 5)",
          ic._safe_float(inst.get("units_per_week_capacity")) == 5.0,
          str(inst.get("units_per_week_capacity")))

    _, sh, cp = _fwd(ic, shapes_key="thorn", shapes=shapes,
                     move=CAP_MOVE, message=D1_WORDING)
    inst = _rows(sh["operating_model"]).get("Landscaping/installation job", {})
    check("M2c WALL control: the same correction LANDS (wk 7)",
          ic._safe_float(inst.get("units_per_week_capacity")) == 7.0,
          str(inst))
    check("M2d WALL control: twins agree (period 7)",
          ic._safe_float(inst.get("units_per_period_capacity")) == 7.0,
          str(inst))
    check("M2e WALL receipt speaks the client's cadence (7 a week)",
          "7 a week" in cp, cp[:160])

    # ---- M3: stated cadence converts, never re-bases -------------------
    M3_MOVE = {"key": "ops.units_per_period_capacity", "value": 40.0,
               "label": "capacity", "attributed": True}
    _, sh, cp = _fwd(ic, shapes_key="sumac", shapes=shapes,
                     move=M3_MOVE, message=D3_WORDING)
    row = list(_rows(sh["operating_model"]).values())[0]
    per = ic._safe_float(row.get("units_per_period_capacity"))
    wk = ic._safe_float(row.get("units_per_week_capacity"))
    check("M3a '40 a week' on a contract row converts (period 173.33)",
          per is not None and abs(per - 40.0 * 52.0 / 12.0) < 0.01, str(per))
    check("M3b the derived week twin now says what the client said (40/wk)",
          wk is not None and abs(wk - 40.0) < 0.01, str(wk))
    check("M3c the receipt speaks the client's own cadence",
          "40 a week" in cp, cp[:200])
    check("M3d the receipt discloses the modeled per-period figure",
          "173.3" in cp, cp[:200])

    _, sh, cp = _fwd(ic, shapes_key="sumac", shapes=shapes,
                     move=M3_MOVE,
                     message="Our route capacity should be 40 a day, not 34.")
    row = list(_rows(sh["operating_model"]).values())[0]
    check("M3e an unconvertible cadence ASKS instead of writing",
          "Quick check on that capacity change" in cp, cp[:160])
    check("M3f ask branch wrote nothing (period still 34)",
          ic._safe_float(row.get("units_per_period_capacity")) == 34.0,
          str(row.get("units_per_period_capacity")))

    if not hasattr(ic, "_reconcile_stated_capacity_cadence"):
        check("M3g/M3h/M3i cadence reconciler exists", False, "helper absent")
        return
    r = ic._reconcile_stated_capacity_cadence(
        value=40.0, message="make it 40 a month",
        row={"unit_cadence": "contract", "operating_periods_per_year": 12},
        leaf="units_per_period_capacity")
    check("M3g 'a month' on a 12-period row is identity (no conversion)",
          not r.get("ask") and r.get("value") == 40.0 and not r.get("converted"),
          str(r))
    r = ic._reconcile_stated_capacity_cadence(
        value=480.0, message="480 a year",
        row={"unit_cadence": "contract", "operating_periods_per_year": 12},
        leaf="units_per_period_capacity")
    check("M3h '480 a year' converts to 40/period",
          not r.get("ask") and abs((r.get("value") or 0) - 40.0) < 0.01, str(r))
    r = ic._reconcile_stated_capacity_cadence(
        value=40.0, message="40 a week, or maybe 160 a month",
        row={"unit_cadence": "contract", "operating_periods_per_year": 12},
        leaf="units_per_period_capacity")
    check("M3i two cadences in one message ASKS", bool(r.get("ask")), str(r))

def _checks_m1(ic, shapes, check):
    del shapes
    # ---- M1: the ack fallback never out-claims the receipt -------------
    ack = ic._build_financials_stage_acknowledgement_first(
        A4B_PROSE, stage_name="rent", financials_json={},
        user_message=A4B_MSG)
    check("M1a router prose claiming a write never ships as the ack",
          "update the hard goods" not in ack and "99" not in ack, ack[:160])
    ack = ic._build_financials_stage_acknowledgement_first(
        "Thanks - noted, and one thought on positioning.",
        stage_name="rent", financials_json={}, user_message="hello there")
    check("M1b benign prose without a write-claim still ships",
          "positioning" in ack, ack[:160])

def _checks_b3(ic, shapes, check):
    # ---- B3: the capex carve-out ---------------------------------------
    check("B3a a but-we-did answer is NOT a none-answer",
          ic._capex_answer_expresses_none(B3_MSG) is False, B3_MSG[:60])
    check("B3d the plain explicit-no still expresses none (A-115b intact)",
          ic._capex_answer_expresses_none(B1_MSG) is True, B1_MSG[:60])
    check("B3e 'No wait' correction still never matches none",
          ic._capex_answer_expresses_none(
              "No wait, actually we did spend 380,000 on equipment this year."
          ) is False, "")
    if not hasattr(ic, "_capex_carveout_figure"):
        check("B3b/B3c/B3f/B3g carve-out helper exists", False, "helper absent")
        return
    check("B3b the carve-out figure is the mower's 15,000",
          ic._capex_carveout_figure(B3_MSG) == 15000.0,
          str(ic._capex_carveout_figure(B3_MSG)))
    check("B3c both-halves message: carve-out figure is 15,000 (not 380k)",
          ic._capex_carveout_figure(B3_BOTH_HALVES) == 15000.0,
          str(ic._capex_carveout_figure(B3_BOTH_HALVES)))

    # The normalizer half: the router captured the EXCLUDED base; the
    # landing numeric is scoped to the carve-out clause.
    fin = copy.deepcopy(shapes["thorn"]["fin"])
    for f in ("current_capex", "initial_assets"):
        fin.pop(f, None)
    _stage = ""
    for _st in ic._FINANCIALS_STAGE_ORDER:
        if "current_capex" in (
            ic._financials_stage_spec(_st).get("patch_targets") or ()):
            _stage = _st
            break
    out = ic._normalize_financials_router_patch(
        patch={"financials.current_capex": 380000.0}, active_stage=_stage,
        financials_json=fin, financials_year1_json={},
        last_assistant="", user_message=B3_BOTH_HALVES)
    check("B3f router-captured 380k is SCOPED to the carved-out 15,000",
          isinstance(out, dict) and out.get("current_capex") == 15000.0,
          str((out or {}).get("current_capex")))
    out = ic._normalize_financials_router_patch(
        patch={"financials.current_capex": 0.0}, active_stage=_stage,
        financials_json=fin, financials_year1_json={},
        last_assistant="", user_message=B3_MSG)
    check("B3g a router-forced 0 is corrected to the carved-out 15,000",
          isinstance(out, dict) and out.get("current_capex") == 15000.0,
          str((out or {}).get("current_capex")))
    out = ic._normalize_financials_router_patch(
        patch={"financials.current_capex": 380000.0}, active_stage=_stage,
        financials_json=fin, financials_year1_json={},
        last_assistant="", user_message=B1_MSG)
    check("B3h the plain explicit-no still stores 0",
          isinstance(out, dict) and out.get("current_capex") == 0.0,
          str((out or {}).get("current_capex")))


def main() -> int:
    import api_handlers.intake_consult as ic  # type: ignore

    shapes = _load_shapes()
    results = []

    def check(tag, ok, detail=""):
        results.append((tag, bool(ok)))
        print(f"[{'PASS' if ok else 'FAIL'}] {tag}"
              + (f" -- {detail}" if detail else ""))

    run_checks(ic, shapes, check)
    failing = [t for t, ok in results if not ok]
    print()
    if failing:
        print(f"RESULT: RED - {len(failing)} failing check(s):")
        for f in failing:
            print("  -", f)
        return 1
    print(f"RESULT: GREEN - all {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
