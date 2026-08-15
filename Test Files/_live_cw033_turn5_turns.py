"""CW-033 turn 5 -- mini's D1-D5 red shapes driven through the LIVE router
on clones of the REAL drafts (Thornfield d9b17850, Sumac 2ecc759c), :5050.

  W1 (D1, mini's A3 verbatim): "Our rent is 2,400 a month, and we keep
     about 52,000 cash on hand." at the rent stage must end
     rent=2400.0 with cash noted - never rent=52000 (the clobber).
  W2 (D2, mini's C1 verbatim): "capacity should be 9, not 5. We invoice
     monthly." at the wall - the install row lands 9 (its own cadence),
     never 2.0769/wk.
  W3 (D3, mini's C3 sequence): t1 "40 a month, not 34" -> period 40
     (identity on the 12-period row); t2 "Sorry - mowing capacity is
     40 a week." -> period 173.3333 (the restatement filter stands
     aside and the door converts).
  W4 (D4, mini's A1 shape): the redirect turn whose message also
     carries rent 2,000 - the landed rent must be NAMED in the reply,
     with all turn-3 honesty checks still holding.
  W5 (D5, mini's C6 shape): a mixed-cadence capacity message at the
     wall - the ask ships ALONE, no completion prose behind it,
     nothing written.

  .venv\\Scripts\\python.exe "Test Files\\_live_cw033_turn5_turns.py"
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5050"
THORN = "d9b17850350545e9911fa09b3e333429"
SUMAC = "2ecc759c5d934706ad95123831f9e0c2"

_STRIP_FROM_OTHER_DEBT = (
    "other_monthly_debt_payments", "annual_interest_payment",
    "annual_principal_payment", "cash_on_hand", "ar_balance", "ap_balance",
    "inventory_balance", "cash_strategy", "funding_preference",
    "funding_split_debt_share",
)
_STRIP_FROM_CAPEX = (
    "current_capex", "initial_assets", "initial_lease", "initial_equity",
    "total_debt_outstanding",
) + _STRIP_FROM_OTHER_DEBT
_STRIP_FROM_RENT = (
    "monthly_rent_expense", "future_rent_expected", "other_operating_expense",
    "current_num_employees",
) + _STRIP_FROM_CAPEX

FAILURES: list = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def note(label, detail=""):
    print(f"  [NOTE] {label}" + (f": {detail}" if detail else ""))


def _fresh_read(conn, draft_id, column):
    try:
        conn.commit()
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute(f"SELECT {column} FROM intake_consult_drafts WHERE draft_id=%s",
                (draft_id,))
    row = cur.fetchone()
    cur.close()
    return json.loads((row[0] if row else None) or "{}")


def ops_rows(conn, draft_id):
    ops = _fresh_read(conn, draft_id, "operating_model_json")
    out = {}
    for lob in ops.get("lob_models") or []:
        for p in lob.get("products") or []:
            out[str(p.get("product_name"))] = {
                "wk": p.get("units_per_week_capacity"),
                "period": p.get("units_per_period_capacity"),
                "price": p.get("unit_price"),
                "util": p.get("utilization_rate"),
            }
    return out


def make_clone(conn, source, tag, msg_cut, strip_fields=()):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (source,))
    src = cur.fetchone()
    cur.close()
    if not src:
        raise RuntimeError(f"source draft missing: {source}")
    clone_id = tag + uuid.uuid4().hex[: 32 - len(tag)]
    client_id = tag.upper() + uuid.uuid4().hex[:10].upper()
    messages = json.loads(src["messages_json"] or "[]")
    if msg_cut is not None:
        messages = messages[:msg_cut]
    fin = json.loads(src["financials_json"] or "{}")
    for f in strip_fields:
        fin.pop(f, None)
    _coh = fin.get("_coherence")
    if isinstance(_coh, dict):
        _coh.pop("retention_pending", None)
    overrides = {
        "draft_id": clone_id,
        "client_id": client_id,
        "active_focus": "financials",
        "financials_confirmed": 0,
        "financials_finalize_proposed": 0,
        "status": "in_progress",
        "completed_at": None,
        "submitted_at": None,
        "intake_submission_id": None,
        "messages_json": json.dumps(messages, ensure_ascii=False),
        "financials_json": json.dumps(fin, ensure_ascii=False),
        "planning_run_id": None,
        "planning_run_status": None,
        "planning_stage": None,
        "planning_status": None,
    }
    columns = [c for c in src.keys() if c != "id"]
    values = [overrides.get(c, src[c]) if c in overrides else src[c] for c in columns]
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))})",
        tuple(values),
    )
    conn.commit()
    cur.close()
    return clone_id, client_id


def post_turn(clone_id, client_id, message):
    resp = requests.post(
        f"{BASE_URL}/api/intake-consult",
        json={"draft_id": clone_id, "client_id": client_id, "message": message},
        timeout=300,
    )
    body = resp.json() if resp.status_code == 200 else {}
    return resp.status_code, str(body.get("assistant_message") or "")


def cleanup(conn, clone_id):
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (clone_id,))
        conn.commit()
        cur.close()
    except Exception:
        pass


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    sys.path.insert(0, str(REPO_ROOT / "python"))
    sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
    from intake_submission import get_mysql_connection  # type: ignore

    conn = get_mysql_connection()

    print("W1 - D1: the two-fact rent answer (mini's A3 verbatim)")
    c1, k1 = make_clone(conn, THORN, "vs33t5a", 75, _STRIP_FROM_RENT)
    status, reply = post_turn(
        c1, k1,
        "Our rent is 2,400 a month, and we keep about 52,000 cash on hand.")
    print(f"\nW1 FULL REPLY < [{status}]\n{reply}\n")
    fin1 = _fresh_read(conn, c1, "financials_json")
    lo = reply.lower()
    check("W1 live turn 200", status == 200, str(status))
    check("W1 rent is the CLIENT'S 2,400 - never the clobbered 52,000",
          fin1.get("monthly_rent_expense") == 2400.0,
          str(fin1.get("monthly_rent_expense")))
    check("W1 cash on hand not falsely stored either",
          fin1.get("cash_on_hand") in (None, 52000.0),
          str(fin1.get("cash_on_hand")))
    check("W1 no receipt speaks 52,000 as rent",
          "rent $52,000" not in lo and "rent 52,000" not in lo, reply[:200])
    cleanup(conn, c1)

    print("\nW2 - D2: cadence in another sentence never binds (mini's C1)")
    c2, k2 = make_clone(conn, THORN, "vs33t5b", None, ())
    before = ops_rows(conn, c2)
    note("W2 install before", str(before.get("Landscaping/installation job")))
    status, reply = post_turn(
        c2, k2,
        "One fix - the install crew capacity should be 9, not 5. "
        "We invoice monthly.")
    print(f"\nW2 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c2)
    inst = after.get("Landscaping/installation job", {})
    check("W2 live turn 200", status == 200, str(status))
    check("W2 the 9 lands in the row's own cadence (wk 9, never 2.08)",
          inst.get("wk") == 9.0, str(inst))
    check("W2 no mis-bound monthly conversion anywhere in the reply",
          "2.0" not in reply and "2.1" not in reply, reply[:200])
    cleanup(conn, c2)

    print("\nW3 - D3: the no-op bypass, both turns (mini's C3 sequence)")
    c3, k3 = make_clone(conn, SUMAC, "vs33t5c", None, ())
    status, reply = post_turn(
        c3, k3, "Our mowing capacity should be 40 a month, not 34.")
    print(f"\nW3 t1 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c3)
    row = after.get("Property contract", {})
    check("W3 t1 live turn 200", status == 200, str(status))
    check("W3 t1 '40 a month' is identity on the 12-period row (period 40)",
          row.get("period") == 40.0, str(row))
    status, reply = post_turn(
        c3, k3, "Sorry - mowing capacity is 40 a week.")
    print(f"\nW3 t2 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c3)
    row = after.get("Property contract", {})
    check("W3 t2 live turn 200", status == 200, str(status))
    check("W3 t2 the restatement filter stands aside and CONVERTS "
          "(period 173.3333)",
          row.get("period") is not None
          and abs(float(row.get("period")) - 173.3333) < 0.01, str(row))
    check("W3 t2 the reply speaks the client's cadence",
          "40 a week" in reply.lower(), reply[:200])
    cleanup(conn, c3)

    print("\nW4 - D4: the landed stage answer is NAMED on the redirect turn")
    c4, k4 = make_clone(conn, THORN, "vs33t5d", 75, _STRIP_FROM_RENT)
    before = ops_rows(conn, c4)
    status, reply = post_turn(
        c4, k4,
        "Bump the hard goods ticket price to 99 instead of 95 - oh, and our "
        "rent is 2,000 a month.")
    print(f"\nW4 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c4)
    fin4 = _fresh_read(conn, c4, "financials_json")
    lo = reply.lower()
    check("W4 live turn 200", status == 200, str(status))
    check("W4 rent landed (2000)", fin4.get("monthly_rent_expense") == 2000.0,
          str(fin4.get("monthly_rent_expense")))
    check("W4 the landed rent is NAMED in the reply",
          "2,000" in reply and "rent" in lo, reply[:240])
    check("W4 price did NOT change",
          after.get("Hard goods sale", {}).get("price") == 95,
          str(after.get("Hard goods sale")))
    check("W4 the honest redirect leads",
          "haven't changed any operations price" in lo, reply[:160])
    check("W4 NO ack of the suppressed 99",
          "to 99" not in lo and "i'll update" not in lo
          and "i’ll update" not in lo, "")
    check("W4 rows byte-equal", after == before, "")
    cleanup(conn, c4)

    print("\nW5 - D5: the mixed-cadence ask HOLDS the turn at the wall")
    c5, k5 = make_clone(conn, SUMAC, "vs33t5e", None, ())
    before = ops_rows(conn, c5)
    status, reply = post_turn(
        c5, k5,
        "Mowing capacity should be 40 a week - though monthly might be "
        "easier for you to track.")
    print(f"\nW5 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c5)
    lo = reply.lower()
    check("W5 live turn 200", status == 200, str(status))
    check("W5 the cadence ask ships",
          "quick check on that capacity change" in lo, reply[:200])
    check("W5 the ask HOLDS the turn (no completion prose behind it)",
          "intake is complete" not in lo, reply[:300])
    # Canonical cell only: the stale week TWIN re-deriving at rest on an
    # ask turn is mini's C6 note (ii), ruled documentation-only - Sumac's
    # source row carries incoherent twins 34/34 on a 12-period row.
    _p_before = before.get("Property contract", {})
    _p_after = after.get("Property contract", {})
    check("W5 the canonical cell is untouched on the ask turn",
          _p_after.get("period") == _p_before.get("period"),
          f"before={_p_before} after={_p_after}")
    if _p_after.get("wk") != _p_before.get("wk"):
        note("W5 stale week twin re-derived at rest (C6 note ii, documented)",
             f"{_p_before.get('wk')} -> {_p_after.get('wk')}")
    cleanup(conn, c5)

    conn.close()
    print()
    if FAILURES:
        print(f"RESULT: RED - {len(FAILURES)} failing check(s):")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("RESULT: GREEN - all live checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
