"""CW-033 turn 5 -- mini's turn-4 defects (D1-D5) + the ruled X2 build,
proven on the real module (offline; the live halves are in
Test Files/_live_cw033_turn5_turns.py).

D1  A dropped-field figure never re-enters the forward mover, and the
    mover never overwrites a field this turn's stage patch just wrote
    (the 2,400-rent / 52,000-cash clobber).
D2  A cadence binds only when it shares a clause with the stated figure
    ("...should be 9, not 5. We invoice monthly." -> cadence unstated).
D3  The disclosure's stored-value/restatement filters stand aside for a
    capacity-keyword message that states a cadence, so "capacity is 40 a
    week" against a stored per-period 40 reaches the door and CONVERTS.
D4  The rent stage's write-derived ack names the landed value (never a
    bare "Got it." hiding the landing).
D5  An ASK holds the turn: the completed-wall branch ships the cadence
    ask alone, never followed by "the intake is complete".
X2  The CW-017b cross-section door reconciles a stated cadence: convert
    or ask, receipt in the client's own cadence, never a raw re-base.

Runs at pre-fix commits too: sections are exception-shielded and the
forward-mover helper tolerates the old 3-tuple return.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw033_turn5_fixes.py"
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

A3_MSG = "Our rent is 2,400 a month, and we keep about 52,000 cash on hand."
C1_MSG = ("One fix - the install crew capacity should be 9, not 5. "
          "We invoice monthly.")
C1_CLAUSE_MSG = ("One fix - the install crew capacity should be 9, not 5, "
                 "and we invoice monthly")
X2_MSG = "Actually, our mowing route capacity should be 40 a week, not 34."
C3_T2_MSG = "Sorry - mowing capacity is 40 a week."
C6_MSG = ("Mowing capacity should be 40 a week - though monthly might be "
          "easier for you to track.")


def _load_shapes():
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


def _fwd(ic, *, fin, shared, move, message, **kw):
    """_apply_forward_move, tolerant of the pre-fix 3-tuple return."""
    res = ic._apply_forward_move(
        move=dict(move), stage_shared_context=shared,
        next_financials=fin, financials_year1_json={},
        conn=None, intake_context={"draft_id": "redproof-cw033-t5"},
        user_message=message, last_assistant="", **kw,
    )
    if len(res) == 3:
        return res[0], res[1], res[2], False
    return res


def run_checks(ic, shapes, check):
    for _section in (_checks_d2, _checks_d1, _checks_d3, _checks_d4,
                     _checks_d5, _checks_x2):
        try:
            _section(ic, shapes, check)
        except Exception as e:  # noqa: BLE001
            check(f"{_section.__name__} completed without error", False, repr(e))


def _checks_d2(ic, shapes, check):
    del shapes
    c = ic._stated_capacity_cadence
    check("D2a a cadence in ANOTHER sentence never binds (C1 -> unstated)",
          c(C1_MSG, value=9.0) == "", repr(c(C1_MSG, value=9.0)))
    check("D2b same-sentence cadence still binds (X2 -> week)",
          c(X2_MSG, value=40.0) == "week", repr(c(X2_MSG, value=40.0)))
    check("D2c 'handle 26 jobs a month' -> month",
          c("Actually the install crew can handle 26 jobs a month.",
            value=26.0) == "month", "")
    check("D2d two cadences in the figure's own clause -> mixed",
          c(C6_MSG, value=40.0) == "mixed", repr(c(C6_MSG, value=40.0)))
    check("D2e ', and we invoice monthly' clause never binds",
          c(C1_CLAUSE_MSG, value=9.0) == "", repr(c(C1_CLAUSE_MSG, value=9.0)))
    check("D2f digits absent -> whole-message scan stands (never a silent "
          "re-base)",
          c("the crew handles seven jobs a week", value=7.0) == "week", "")
    check("D2g decimal is not its integer ('9.23 a week' has no figure 9... "
          "cadence falls back to whole-message)",
          c("we run 9.23 a week. We invoice monthly.", value=9.0) in ("mixed",),
          repr(c("we run 9.23 a week. We invoice monthly.", value=9.0)))


def _checks_d1(ic, shapes, check):
    RENT_MOVE = {"key": "financials.monthly_rent_expense", "value": 52000.0,
                 "label": "monthly rent", "attributed": True}

    fin = copy.deepcopy(shapes["thorn"]["fin"])
    fin["monthly_rent_expense"] = 2400.0
    shared = {
        "operating_model": copy.deepcopy(shapes["thorn"]["ops"]),
        "people_capability": copy.deepcopy(shapes["thorn"]["people"]),
    }
    fin_out, _, cp, ask = _fwd(
        ic, fin=fin, shared=shared, move=RENT_MOVE, message=A3_MSG,
        turn_written_fields={"monthly_rent_expense"},
    )
    check("D1b the mover never overwrites this turn's own stage write",
          ic._safe_float(fin_out.get("monthly_rent_expense")) == 2400.0,
          str(fin_out.get("monthly_rent_expense")))
    check("D1b the refused move claims nothing", cp == "" and not ask, cp[:120])

    fin2 = copy.deepcopy(shapes["thorn"]["fin"])
    fin2["monthly_rent_expense"] = 2400.0
    shared2 = {
        "operating_model": copy.deepcopy(shapes["thorn"]["ops"]),
        "people_capability": copy.deepcopy(shapes["thorn"]["people"]),
    }
    fin_out2, _, cp2, _ = _fwd(ic, fin=fin2, shared=shared2, move=RENT_MOVE,
                               message=A3_MSG)
    check("D1c CONTROL: without the write-set the clobber is real (the guard "
          "does the work)",
          ic._safe_float(fin_out2.get("monthly_rent_expense")) == 52000.0,
          str(fin_out2.get("monthly_rent_expense")))

    # D1a mechanism: the dropped field's own figure, passed as a door
    # reference (the branch wiring), kills the re-landing at the
    # disclosure layer.
    fin3 = copy.deepcopy(shapes["thorn"]["fin"])
    fin3["monthly_rent_expense"] = 2400.0
    shared3 = {
        "operating_model": copy.deepcopy(shapes["thorn"]["ops"]),
        "people_capability": copy.deepcopy(shapes["thorn"]["people"]),
    }
    _, _, mv = ic._unlanded_figures_disclosure(
        next_financials=fin3, stage_shared_context=shared3,
        user_message=A3_MSG, last_assistant="",
        extra_reference_figures=[52000.0],
    )
    check("D1a a dropped-field figure handed over as a reference never "
          "produces a move",
          mv is None, str(mv))


def _checks_d3(ic, shapes, check):
    fin = copy.deepcopy(shapes["sumac"]["fin"])
    ops = copy.deepcopy(shapes["sumac"]["ops"])
    row = list(_rows(ops).values())[0]
    row["units_per_period_capacity"] = 40.0
    shared = {"operating_model": ops,
              "people_capability": copy.deepcopy(shapes["sumac"]["people"])}
    prior = [copy.deepcopy(fin), copy.deepcopy(shared["people_capability"]),
             copy.deepcopy(ops)]
    _, _, mv = ic._unlanded_figures_disclosure(
        next_financials=fin, stage_shared_context=shared,
        user_message=C3_T2_MSG, prior_sections=prior, last_assistant="",
    )
    check("D3a stated-cadence capacity figure SURVIVES the restatement "
          "filters (stored 40, '40 a week')",
          isinstance(mv, dict)
          and str(mv.get("key", "")).endswith("capacity")
          and ic._safe_float(mv.get("value")) == 40.0, str(mv))
    if isinstance(mv, dict):
        fin_o, shared_o, cp, ask = _fwd(ic, fin=fin, shared=shared, move=mv,
                                        message=C3_T2_MSG)
        row_o = list(_rows(shared_o["operating_model"]).values())[0]
        per = ic._safe_float(row_o.get("units_per_period_capacity"))
        check("D3b the surviving figure CONVERTS at the door (period 173.33)",
              per is not None and abs(per - 173.3333) < 0.01, str(per))
        check("D3b receipt speaks the client's cadence", "40 a week" in cp,
              cp[:160])
    else:
        check("D3b the surviving figure CONVERTS at the door (period 173.33)",
              False, "no move survived")

    # Fresh stored-40 shape: the D3b mover mutated `ops` through to
    # 173.33 (the persist-seam law working), so the control rebuilds.
    ops40 = copy.deepcopy(shapes["sumac"]["ops"])
    list(_rows(ops40).values())[0]["units_per_period_capacity"] = 40.0
    _, _, mv2 = ic._unlanded_figures_disclosure(
        next_financials=copy.deepcopy(shapes["sumac"]["fin"]),
        stage_shared_context={
            "operating_model": ops40,
            "people_capability": copy.deepcopy(shapes["sumac"]["people"]),
        },
        user_message="Sorry - mowing capacity is 40.",
        prior_sections=[copy.deepcopy(shapes["sumac"]["fin"]),
                        copy.deepcopy(shapes["sumac"]["people"]),
                        copy.deepcopy(ops40)],
        last_assistant="",
    )
    check("D3c CONTROL: a cadence-free restatement of the stored value "
          "still dies (no false motion)",
          mv2 is None, str(mv2))


def _checks_d4(ic, shapes, check):
    del shapes
    ack = ic._build_financials_stage_acknowledgement(
        stage_name="monthly_rent_expense",
        financials_json={"monthly_rent_expense": 2000.0},
    )
    check("D4a the rent ack NAMES the landed value",
          "2,000" in ack and "monthly rent" in ack, ack[:120])
    ack2 = ic._build_financials_stage_acknowledgement(
        stage_name="cash_on_hand", financials_json={"cash_on_hand": 52000.0},
    )
    check("D4b other scalar stages unchanged (cash on hand named as before)",
          "52,000" in ack2 and "cash on hand" in ack2, ack2[:120])


def _checks_d5(ic, shapes, check):
    def _stub_route_intent(**kw):
        return {"action": "continue_chat", "assistant_message": "", "patch": None}

    fin = copy.deepcopy(shapes["sumac"]["fin"])
    shared = {
        "operating_model": copy.deepcopy(shapes["sumac"]["ops"]),
        "people_capability": copy.deepcopy(shapes["sumac"]["people"]),
    }
    turn, _ = ic._run_financials_turn_and_sync_inner(
        route_intent=_stub_route_intent, conn=None,
        intake_context={"draft_id": "redproof-cw033-t5"},
        conversation_messages=[], business_facts={},
        shared_context=shared, last_assistant="",
        user_message=C6_MSG, financials_json=fin,
        financials_year1_json={},
    )
    reply = str((turn or {}).get("assistant_message") or "")
    lo = reply.lower()
    check("D5a the mixed-cadence ASK ships",
          "quick check on that capacity change" in lo, reply[:200])
    check("D5b the ask HOLDS the turn (no 'intake is complete' behind it)",
          "intake is complete" not in lo, reply[:300])


def _checks_x2(ic, shapes, check):
    def _door(ops, msg):
        rep = {}
        try:
            res = ic._apply_cross_section_driver_correction(
                ops_json=ops, user_message=msg, report=rep)
        except TypeError:
            res = ic._apply_cross_section_driver_correction(
                ops_json=ops, user_message=msg)
        return res, rep

    base_ops = copy.deepcopy(shapes["sumac"]["ops"])
    res, rep = _door(copy.deepcopy(base_ops), X2_MSG)
    if res is None:
        check("X2a the xsec door CONVERTS '40 a week' on the contract row",
              False, f"door declined, report={rep}")
    else:
        ops_o, ack = res
        row = list(_rows(ops_o).values())[0]
        per = ic._safe_float(row.get("units_per_period_capacity"))
        check("X2a the xsec door CONVERTS '40 a week' on the contract row "
              "(period 173.33, never a raw 40)",
              per is not None and abs(per - 173.3333) < 0.01, str(per))
        check("X2a the ack speaks the client's own cadence",
              "40 a week" in ack, ack[:200])

    res2, rep2 = _door(
        copy.deepcopy(base_ops),
        "Actually, our mowing route capacity should be 40 a week, or "
        "call it 170 a month, not 34.",
    )
    check("X2b an ambiguous cadence ASKS through the refusal path "
          "(no landing, report carries the ask)",
          res2 is None and bool(rep2.get("cadence_ask")),
          f"res={'landed' if res2 else 'None'} rep_keys={sorted(rep2)}")

    ops3 = copy.deepcopy(base_ops)
    list(_rows(ops3).values())[0]["units_per_period_capacity"] = 40.0
    res3, _ = _door(ops3, X2_MSG)
    if res3 is None:
        check("X2c the no-op edge converts too (stored 40, '40 a week' -> "
              "173.33)", False, "door declined")
    else:
        ops_o3, ack3 = res3
        per3 = ic._safe_float(
            list(_rows(ops_o3).values())[0].get("units_per_period_capacity"))
        check("X2c the no-op edge converts too (stored 40, '40 a week' -> "
              "173.33)",
              per3 is not None and abs(per3 - 173.3333) < 0.01, str(per3))

    res4, _ = _door(
        copy.deepcopy(base_ops),
        "Actually, our mowing route capacity should be 40, not 34.",
    )
    if res4 is None:
        check("X2d CONTROL: a cadence-free correction lands raw as today",
              False, "door declined")
    else:
        per4 = ic._safe_float(
            list(_rows(res4[0]).values())[0].get("units_per_period_capacity"))
        check("X2d CONTROL: a cadence-free correction lands raw as today "
              "(period 40)",
              per4 is not None and abs(per4 - 40.0) < 0.01, str(per4))

    ops5 = copy.deepcopy(base_ops)
    row5 = list(_rows(ops5).values())[0]
    row5["unit_cadence"] = "weekly"
    row5["units_per_week_capacity"] = 34.0
    res5, _ = _door(ops5, X2_MSG)
    if res5 is None:
        check("X2e CONTROL: matching cadence is identity (weekly row, 40/wk)",
              False, "door declined")
    else:
        wk5 = ic._safe_float(
            list(_rows(res5[0]).values())[0].get("units_per_week_capacity"))
        check("X2e CONTROL: matching cadence is identity (weekly row, 40/wk)",
              wk5 is not None and abs(wk5 - 40.0) < 0.01, str(wk5))


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
