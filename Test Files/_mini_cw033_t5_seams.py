"""mini CW-033 turn-5 audit, items 3+4 (+R44 reachability): offline seams.

Item 4 - D2/D3 wordings of my own:
  S1  relative clause: "capacity should be 9, which we invoice monthly"
  S2  parenthetical:   "capacity should be 9 (we invoice monthly)"
  S3  'though' clause: "capacity should be 9, though we invoice monthly"
  S4  cadence BEFORE the figure's clause (must not bind)
  S5  slash forms: 40/week, 40/wk, 40 per wk - are they visible at all?
  S6  slash form at the xsec door: does "40/week, not 34" land RAW?
  S7  word-number fallback: "should be nine, not five. We invoice
      monthly." with router value 9.0 - whole-message scan mis-binds?
  S8  D3 bypass per-figure scoping: capacity+cadence+an unrelated figure
      matching a stored value - the unrelated figure stays filtered.

Item 3 - D1's silent edge at the completed wall + the reference miss:
  S9  wall normalizer: does cash_on_hand LAND at the wall (active_stage
      '')? If yes the A3 wall shape has no homeless figure.
  S10 the wall-shape silent kill: mover + turn_written_fields, no note.
  S11 rule (a) reference miss: a mangled dropped value (52) does not
      cover the message's 52,000 - what re-enters, and does rule (b)
      still hold the written field?

R44 reachability (item 2 follow-through):
  S12 the _first builder at the 10966 call-site shape: stage-field
      absent from the normalized patch -> does a named branch claim?

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw033_t5_seams.py"
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

SUMAC = "2ecc759c5d934706ad95123831f9e0c2"
THORN = "d9b17850350545e9911fa09b3e333429"

results = []


def check(tag, ok, detail=""):
    results.append((tag, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}" + (f" -- {detail}" if detail else ""))


def note(tag, detail):
    print(f"[NOTE] {tag} -- {detail}")


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


def main() -> int:
    import api_handlers.intake_consult as ic  # type: ignore

    shapes = _load_shapes()
    c = ic._stated_capacity_cadence

    # ---- S1-S4: clause forms ----
    s1 = c("One fix - the install crew capacity should be 9, which we invoice monthly.", value=9.0)
    check("S1 relative clause 'which we invoice monthly' does NOT bind",
          s1 == "", repr(s1))
    s2 = c("The install crew capacity should be 9 (we invoice monthly).", value=9.0)
    check("S2 parenthetical '(we invoice monthly)' does NOT bind",
          s2 == "", repr(s2))
    s3 = c("Capacity should be 9, though we invoice monthly.", value=9.0)
    check("S3 ', though we invoice monthly' does NOT bind", s3 == "", repr(s3))
    s4 = c("We invoice monthly. The install crew capacity should be 9, not 5.",
           value=9.0)
    check("S4 cadence in an EARLIER sentence does not bind", s4 == "", repr(s4))

    # ---- S5: slash forms ----
    for form in ("Mowing capacity is 40/week.", "Mowing capacity is 40/wk.",
                 "Mowing capacity is 40 per wk."):
        sv = c(form, value=40.0)
        note(f"S5 slash/abbrev form {form!r}", f"cadence read = {sv!r}")
    s5 = c("Mowing capacity is 40/week.", value=40.0)
    check("S5 '40/week' is READ as a weekly cadence (else raw landing)",
          s5 == "week", repr(s5))

    # ---- S6: slash form at the xsec door lands raw? ----
    base_ops = copy.deepcopy(shapes["sumac"]["ops"])
    rep = {}
    res = ic._apply_cross_section_driver_correction(
        ops_json=copy.deepcopy(base_ops),
        user_message="Actually, our mowing route capacity should be 40/week, not 34.",
        report=rep)
    if res is None:
        note("S6 xsec door on '40/week'", f"declined, rep={sorted(rep)}")
        check("S6 '40/week' never lands RAW on the 12-period row", True,
              "door declined (no wrong number)")
    else:
        per = ic._safe_float(
            list(_rows(res[0]).values())[0].get("units_per_period_capacity"))
        check("S6 '40/week' never lands RAW on the 12-period row",
              per is not None and abs(per - 173.3333) < 0.01,
              f"period={per} ack={res[1][:120]}")

    # ---- S7: word-number fallback mis-bind ----
    s7 = c("The install crew capacity should be nine, not five. We invoice monthly.",
           value=9.0)
    check("S7 word-number figure + invoicing cadence elsewhere does NOT "
          "mis-bind month", s7 == "", repr(s7))

    # ---- S8: D3 bypass is per-figure ----
    ops40 = copy.deepcopy(shapes["sumac"]["ops"])
    row40 = list(_rows(ops40).values())[0]
    row40["units_per_period_capacity"] = 40.0
    price = ic._safe_float(row40.get("unit_price"))
    fin = copy.deepcopy(shapes["sumac"]["fin"])
    shared = {"operating_model": ops40,
              "people_capability": copy.deepcopy(shapes["sumac"]["people"])}
    prior = [copy.deepcopy(fin), copy.deepcopy(shared["people_capability"]),
             copy.deepcopy(ops40)]
    msg8 = (f"Sorry - mowing capacity is 40 a week, and the {price:g} "
            "price is unchanged.")
    _, _, mv8 = ic._unlanded_figures_disclosure(
        next_financials=fin, stage_shared_context=shared,
        user_message=msg8, prior_sections=prior, last_assistant="")
    ok8 = (isinstance(mv8, dict)
           and str(mv8.get("key", "")).endswith("capacity")
           and ic._safe_float(mv8.get("value")) == 40.0)
    check("S8 capacity 40 survives; the unrelated stored-price figure is "
          "still filtered (move is capacity, not price)", ok8, str(mv8))

    # ---- S9: does cash_on_hand land at the wall? ----
    wall_rep = {}
    wall_fin = copy.deepcopy(shapes["thorn"]["fin"])
    wall_fin["monthly_rent_expense"] = 999.0
    normalized = ic._normalize_financials_router_patch(
        patch={"financials.monthly_rent_expense": 2400.0,
               "financials.cash_on_hand": 52000.0},
        active_stage="", financials_json=wall_fin,
        financials_year1_json={}, last_assistant="",
        user_message="Our rent is 2,400 a month, and we keep about 52,000 cash on hand.",
        report=wall_rep)
    note("S9 wall normalizer report",
         f"applied={wall_rep.get('applied')} dropped={wall_rep.get('dropped')}")
    check("S9 the wall lands rent 2400",
          "monthly_rent_expense" in (wall_rep.get("applied") or [])
          and ic._safe_float((normalized or {}).get("monthly_rent_expense")) == 2400.0,
          str((normalized or {}).get("monthly_rent_expense")))

    # ---- S10: the wall silent kill (rule b, no note machinery) ----
    fin10 = copy.deepcopy(shapes["thorn"]["fin"])
    fin10["monthly_rent_expense"] = 2400.0
    shared10 = {
        "operating_model": copy.deepcopy(shapes["thorn"]["ops"]),
        "people_capability": copy.deepcopy(shapes["thorn"]["people"]),
    }
    fin_o, _, cp, ask = ic._apply_forward_move(
        move={"key": "financials.monthly_rent_expense", "value": 52000.0,
              "label": "monthly rent", "attributed": True},
        stage_shared_context=shared10, next_financials=fin10,
        financials_year1_json={}, conn=None,
        intake_context={"draft_id": "mini-t5-seams"},
        user_message="Our rent is 2,400 a month, and we keep about 52,000 cash on hand.",
        last_assistant="", turn_written_fields={"monthly_rent_expense"})
    check("S10 wall-shape kill: rent held at 2,400, no copy, no ask "
          "(SILENT - the wall has no note)",
          ic._safe_float(fin_o.get("monthly_rent_expense")) == 2400.0
          and cp == "" and not ask, f"rent={fin_o.get('monthly_rent_expense')} cp={cp!r}")

    # ---- S11: rule (a) reference miss on a mangled dropped value ----
    fin11 = copy.deepcopy(shapes["thorn"]["fin"])
    fin11["monthly_rent_expense"] = 2400.0
    shared11 = {
        "operating_model": copy.deepcopy(shapes["thorn"]["ops"]),
        "people_capability": copy.deepcopy(shapes["thorn"]["people"]),
    }
    _, _, mv11 = ic._unlanded_figures_disclosure(
        next_financials=fin11, stage_shared_context=shared11,
        user_message="Our rent is 2,400 a month, and we keep about 52,000 cash on hand.",
        last_assistant="",
        extra_reference_figures=[52.0])  # the mangled dropped value
    note("S11 mangled ref (52 for 52,000): what re-enters",
         str(mv11))
    if isinstance(mv11, dict):
        fin_o11, _, cp11, _ = ic._apply_forward_move(
            move=mv11, stage_shared_context=shared11, next_financials=fin11,
            financials_year1_json={}, conn=None,
            intake_context={"draft_id": "mini-t5-seams"},
            user_message="Our rent is 2,400 a month, and we keep about 52,000 cash on hand.",
            last_assistant="", turn_written_fields={"monthly_rent_expense"})
        check("S11 rule (b) still holds the written rent against the "
              "re-entered figure",
              ic._safe_float(fin_o11.get("monthly_rent_expense")) == 2400.0,
              f"rent={fin_o11.get('monthly_rent_expense')} move={mv11} cp={cp11[:100]!r}")
    else:
        check("S11 rule (b) still holds the written rent against the "
              "re-entered figure", True, "no move re-entered at all")

    # ---- S12: R44 named-branch reachability at the 10966 call-site shape ----
    for stage in ("current_num_employees", "current_payroll", "marketing"):
        out = ic._build_financials_stage_acknowledgement_first(
            "", stage_name=stage,
            financials_json={"monthly_rent_expense": 2600.0},
            user_message="actually rent is 2,600")
        note(f"S12 {stage} stage, patch lacks the stage field",
             f"ack ships: {out!r}")

    failing = [t for t, ok in results if not ok]
    print()
    if failing:
        print(f"RESULT: RED - {len(failing)} failing:")
        for f in failing:
            print("  -", f)
        return 1
    print(f"RESULT: GREEN - all {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
