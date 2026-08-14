"""CW-033 A-113/A-115 LIVE proof - the un-fakeable standard.

THE PRODUCTION CALL CHAIN (named first, per the E2E law):
  POST /api/intake-consult (focus=financials, INTERVIEW region)
    -> post_intake_consult_handler -> _run_financials_turn_and_sync
       [the new wrapper: _apply_cross_section_driver_correction FIRST]
    -> _run_financials_turn_and_sync_inner -> route_intent (live GPT)
    -> stage doors / forward move -> persisted ops + financials

Clones of the REAL Thornfield draft d9b17850 (the CW-033 run), REWOUND to
the exact turns that failed live, driven with the client's OWN transcript
words against the live :5050 backend and live GPT router. Nothing is
stubbed. The proof is the persisted rows afterwards.

  L1 message [99] verbatim (bundled with the debt answer)
  L2 message [107] verbatim (standalone, names both values)
  L3 message [111] verbatim (standalone, single number, line named)
  L4 a correction naming NO line -> honest refusal, zero writes
  L5 message [89] verbatim (capex explicit no + excluded 380k) -> capex 0
  L6 message [75] verbatim (the 58% collapse) -> no unit-price echo, no
     retention gate, prices untouched

  .venv\\Scripts\\python.exe "Test Files\\_live_cw033_capacity_turns.py"
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
SOURCE_DRAFT = "d9b17850350545e9911fa09b3e333429"

# Financials fields owned by each stage from the given stage ON, so the
# rewound clone re-enters the interview at that stage.
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


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def _fresh_read(conn, draft_id, column):
    try:
        conn.commit()  # REPEATABLE READ trap - end the snapshot first
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute(
        f"SELECT {column} FROM intake_consult_drafts WHERE draft_id=%s",
        (draft_id,),
    )
    row = cur.fetchone()
    cur.close()
    return json.loads((row[0] if row else None) or "{}")


def ops_caps(conn, draft_id):
    ops = _fresh_read(conn, draft_id, "operating_model_json")
    out = {}
    for lob in ops.get("lob_models") or []:
        for p in lob.get("products") or []:
            out[str(p.get("product_name"))] = (
                p.get("units_per_week_capacity"),
                p.get("units_per_period_capacity"),
                p.get("unit_price"),
            )
    return out


def make_clone(conn, tag, msg_cut, strip_fields):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
    src = cur.fetchone()
    cur.close()
    if not src:
        raise RuntimeError("source draft missing")
    clone_id = tag + uuid.uuid4().hex[: 32 - len(tag)]
    client_id = tag.upper() + uuid.uuid4().hex[:10].upper()
    messages = json.loads(src["messages_json"] or "[]")[:msg_cut]
    fin = json.loads(src["financials_json"] or "{}")
    for f in strip_fields:
        fin.pop(f, None)
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
    return clone_id, client_id, messages


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


BASE_CAPS = {
    "Plant and nursery sale": (340.0, 340.0, 52.0),
    "Hard goods sale": (165.0, 165.0, 95.0),
    "Landscaping/installation job": (5.0, 5.0, 2400.0),
    "Design/consultation project": (3.0, 3.0, 1250.0),
}


def run_capacity_case(conn, tag, message, label, expect_install=7.0):
    cid, kid, _ = make_clone(conn, tag, 99, _STRIP_FROM_OTHER_DEBT)
    try:
        before = ops_caps(conn, cid)
        check(f"{label} clone rewound (install still 5)",
              before.get("Landscaping/installation job", (None,))[0] == 5.0,
              str(before.get("Landscaping/installation job")))
        status, reply = post_turn(cid, kid, message)
        print(f"  < [{status}] {reply[:260]}")
        after = ops_caps(conn, cid)
        inst = after.get("Landscaping/installation job")
        check(f"{label} live turn 200", status == 200, str(status))
        if expect_install is None:
            check(f"{label} NOTHING written (refusal case)",
                  after == before, str(inst))
            check(f"{label} reply asks which line, never 'Recorded:'",
                  "Recorded:" not in reply
                  and ("which line" in reply.lower()
                       or "couldn't apply an operations change" in reply.lower()),
                  reply[:120])
        else:
            check(f"{label} install row carries 7 on BOTH capacity cells",
                  inst and inst[0] == expect_install and inst[1] == expect_install,
                  str(inst))
            check(f"{label} the OTHER three lines are untouched",
                  all(after.get(k)[:2] == BASE_CAPS[k][:2]
                      for k in BASE_CAPS if k != "Landscaping/installation job"),
                  str({k: v[:2] for k, v in after.items()}))
            check(f"{label} reply speaks 7 and never 'capacity 5'",
                  ("7" in reply) and ("capacity 5" not in reply.lower())
                  and ("capacity to 5" not in reply.lower()),
                  "")
        return reply
    finally:
        cleanup(conn, cid)


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    sys.path.insert(0, str(REPO_ROOT / "python"))
    sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
    from intake_submission import get_mysql_connection  # type: ignore

    conn = get_mysql_connection()

    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s",
        (SOURCE_DRAFT,),
    )
    msgs = json.loads((cur.fetchone() or {}).get("messages_json") or "[]")
    cur.close()
    M99 = str(msgs[99].get("content"))
    M107 = str(msgs[107].get("content"))
    M111 = str(msgs[111].get("content"))
    M89 = str(msgs[89].get("content"))
    M75 = str(msgs[75].get("content"))
    print("real transcript turns pulled:",
          {i: str(msgs[i].get("content"))[:60] for i in (75, 89, 99, 107, 111)})

    print("\nL1 - [99] verbatim: bundled debt answer + capacity correction")
    r1 = run_capacity_case(conn, "cw33l1", M99, "L1")
    print("\nL2 - [107] verbatim: standalone, names both values")
    run_capacity_case(conn, "cw33l2", M107, "L2")
    print("\nL3 - [111] verbatim: standalone, single number, line named")
    run_capacity_case(conn, "cw33l3", M111, "L3")
    print("\nL4 - correction naming NO line: honest refusal, zero writes")
    run_capacity_case(conn, "cw33l4",
                      "One of the weekly capacity numbers is wrong - it "
                      "should be 9 a week.", "L4", expect_install=None)

    print("\nL5 - [89] verbatim: capex explicit no + excluded 380k")
    c5, k5, _ = make_clone(conn, "cw33l5", 89, _STRIP_FROM_CAPEX)
    try:
        status5, reply5 = post_turn(c5, k5, M89)
        print(f"  < [{status5}] {reply5[:260]}")
        fin5 = _fresh_read(conn, c5, "financials_json")
        check("L5 live turn 200", status5 == 200, str(status5))
        check("L5 current_capex stored as 0 (the client's no honored)",
              fin5.get("current_capex") == 0.0, str(fin5.get("current_capex")))
        check("L5 380,000 NOT captured as capex anywhere",
              fin5.get("current_capex") != 380000.0
              and fin5.get("initial_assets") != 380000.0,
              f"capex={fin5.get('current_capex')} assets={fin5.get('initial_assets')}")
    finally:
        cleanup(conn, c5)

    print("\nL6 - [75] verbatim: the 58% collapse - no unit-price echo, no "
          "retention gate")
    c6, k6, _ = make_clone(conn, "cw33l6", 75, _STRIP_FROM_RENT)
    try:
        before6 = ops_caps(conn, c6)
        status6, reply6 = post_turn(c6, k6, M75)
        print(f"  < [{status6}] {reply6[:300]}")
        after6 = ops_caps(conn, c6)
        fin6 = _fresh_read(conn, c6, "financials_json")
        ops6 = _fresh_read(conn, c6, "operating_model_json")
        rates6 = {p.get("product_name"): (p.get("cogs_percent_of_line_revenue"),
                                          p.get("cogs_cost_structure_group"))
                  for l in ops6.get("lob_models") or []
                  for p in l.get("products") or []}
        check("L6 live turn 200", status6 == 200, str(status6))
        check("L6 NO unit price changed",
              {k: v[2] for k, v in after6.items()}
              == {k: v[2] for k, v in before6.items()},
              str({k: v[2] for k, v in after6.items()}))
        check("L6 reply never says 'Recorded: unit price'",
              "unit price" not in reply6.lower(), reply6[:120])
        _coh = fin6.get("intake_coherence") or {}
        _rt = _coh.get("retention_pending") if isinstance(_coh, dict) else None
        check("L6 retention_pending NOT stamped",
              not _rt and not fin6.get("retention_pending"),
              str(_rt or fin6.get("retention_pending")))
        check("L6 the 58% collapse itself landed on the two named rows",
              rates6.get("Plant and nursery sale", (None, None))[0] == 0.58
              and rates6.get("Hard goods sale", (None, None))[0] == 0.58,
              str(rates6))
    finally:
        cleanup(conn, c6)

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
