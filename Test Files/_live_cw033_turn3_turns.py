"""CW-033 turn 3 -- the four fixes driven through the LIVE router on clones
of the REAL drafts (Thornfield d9b17850, Sumac 2ecc759c), :5050.

  W1 (M1, mini's A4b verbatim): the price-change redirect turn. The reply
     must carry the honest redirect and NOTHING else that claims a write:
     no "I'll update ... to 99", no phantom rent/other-operating-costs
     notes, no "Also recorded:" of on-file values. Price stays 95.
  W2 (M2, mini's D1 verbatim): the keywordless capacity correction
     mid-interview ("7 jobs a week", other-debt stage active) must NOT
     land - redirect spoken, rows byte-equal.
  W3 (M3, mini's D3 verbatim): "40 a week, not 34" on Sumac's contract row
     at the wall lands period 173.33 / wk 40.0 and the receipt speaks
     "40 a week".
  W4 (D2 control): the same wording on Thornfield's weekly install row at
     the wall still lands 7/7 exactly as round 1 proved.
  W5 (B3): the but-we-did capex answer stores the mower's 15,000; the
     excluded 380,000 lands nowhere; the plain explicit-no still stores 0.

  .venv\\Scripts\\python.exe "Test Files\\_live_cw033_turn3_turns.py"
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
    # Clone hygiene (mini's round-2 finding): strip the STALE
    # retention_pending frame the pre-fix source run stamped.
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


def json_contains_value(obj, needle: float) -> list:
    hits = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            if abs(float(o) - needle) < 0.5:
                hits.append(path)

    walk(obj, "$")
    return hits


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    sys.path.insert(0, str(REPO_ROOT / "python"))
    sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
    from intake_submission import get_mysql_connection  # type: ignore

    conn = get_mysql_connection()

    print("W1 - M1/A4b: the price-change redirect turn, full-reply honesty")
    c1, k1 = make_clone(conn, THORN, "vs33w1", 75, _STRIP_FROM_RENT)
    before = ops_rows(conn, c1)
    status, reply = post_turn(
        c1, k1,
        "One more thing - bump the hard goods ticket price to 99 instead of 95.")
    print(f"\nW1 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c1)
    lo = reply.lower()
    check("W1 live turn 200", status == 200, str(status))
    check("W1 price did NOT change",
          after.get("Hard goods sale", {}).get("price") == 95, str(after.get("Hard goods sale")))
    check("W1 rows byte-equal", after == before, "")
    check("W1 the honest redirect leads",
          "haven't changed any operations price" in lo, reply[:140])
    check("W1 NO ack of the suppressed change",
          "update the hard goods" not in lo and "to 99" not in lo
          and "i'll update" not in lo and "i’ll update" not in lo, "")
    check("W1 NO phantom rent note", "rent change" not in lo, "")
    check("W1 NO phantom other-operating-costs note",
          "other operating costs yet" not in lo, "")
    check("W1 NO false 'Also recorded' of on-file values",
          "also recorded" not in lo, "")
    fin1 = _fresh_read(conn, c1, "financials_json")
    _coh1 = fin1.get("_coherence") or {}
    check("W1 no retention stamp",
          not (_coh1.get("retention_pending") if isinstance(_coh1, dict) else None),
          "")
    cleanup(conn, c1)

    print("\nW2 - M2/D1: keywordless capacity correction mid-interview")
    c2, k2 = make_clone(conn, THORN, "vs33w2", 99, _STRIP_FROM_OTHER_DEBT)
    before = ops_rows(conn, c2)
    status, reply = post_turn(
        c2, k2,
        "Hang on, one fix on operations - the install crew can actually do "
        "7 jobs a week, not 5. Please update that.")
    print(f"\nW2 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c2)
    lo = reply.lower()
    check("W2 live turn 200", status == 200, str(status))
    check("W2 NO ops write anywhere mid-interview", after == before,
          str(after.get("Landscaping/installation job")))
    check("W2 the redirect is spoken (door or wrapper)",
          "haven't changed any operations" in lo, reply[:160])
    check("W2 no fabricated receipt",
          "recorded:" not in lo and "i've updated" not in lo, "")
    cleanup(conn, c2)

    print("\nW3 - M3/D3: '40 a week, not 34' on Sumac's contract row at the wall")
    c3, k3 = make_clone(conn, SUMAC, "vs33w3", None, ())
    before = ops_rows(conn, c3)
    note("W3 Sumac rows before", str(before))
    status, reply = post_turn(
        c3, k3, "Our mowing route capacity should be 40 a week, not 34.")
    print(f"\nW3 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c3)
    note("W3 Sumac rows after", str(after))
    row = after.get("Property contract", {})
    check("W3 live turn 200", status == 200, str(status))
    check("W3 the stated cadence CONVERTS (period 173.33)",
          row.get("period") is not None
          and abs(float(row.get("period")) - 173.3333) < 0.01, str(row))
    check("W3 the week twin now says what the client said (40/wk)",
          row.get("wk") is not None and abs(float(row.get("wk")) - 40.0) < 0.01,
          str(row))
    check("W3 the reply speaks the client's own cadence",
          "40 a week" in reply.lower(), reply[:200])
    cleanup(conn, c3)

    print("\nW4 - D2 control: weekly install row at the wall still lands 7/7")
    c4, k4 = make_clone(conn, THORN, "vs33w4", None, ())
    before = ops_rows(conn, c4)
    status, reply = post_turn(
        c4, k4,
        "Hang on, one fix on operations - the install crew can actually do "
        "7 jobs a week, not 5. Please update that.")
    print(f"\nW4 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c4)
    inst = after.get("Landscaping/installation job", {})
    check("W4 live turn 200", status == 200, str(status))
    check("W4 wall landing intact (wk 7)", inst.get("wk") == 7.0, str(inst))
    check("W4 twins agree (period 7)", inst.get("period") == 7.0, str(inst))
    check("W4 other rows byte-equal",
          all(after[k] == before[k] for k in before
              if k != "Landscaping/installation job"), "")
    cleanup(conn, c4)

    print("\nW5 - B3: the but-we-did capex carve-out, both halves")
    c5, k5 = make_clone(conn, THORN, "vs33w5", 89, _STRIP_FROM_CAPEX)
    status, reply = post_turn(
        c5, k5,
        "None of it this year, we've got about 380,000 sitting there - but "
        "we did spend 15,000 on a mower.")
    print(f"\nW5 FULL REPLY < [{status}]\n{reply}\n")
    fin5 = _fresh_read(conn, c5, "financials_json")
    check("W5 live turn 200", status == 200, str(status))
    check("W5 the mower's 15,000 IS the capex",
          fin5.get("current_capex") == 15000.0, str(fin5.get("current_capex")))
    hits = json_contains_value(
        {k: v for k, v in fin5.items() if k != "_coherence"}, 380000.0)
    check("W5 the excluded 380,000 landed NOWHERE in financials",
          not hits, str(hits))
    ppl5 = _fresh_read(conn, c5, "people_json")
    check("W5 380,000 not smuggled into people",
          not json_contains_value(ppl5, 380000.0), "")
    cleanup(conn, c5)

    c6, k6 = make_clone(conn, THORN, "vs33w6", 89, _STRIP_FROM_CAPEX)
    status, reply = post_turn(
        c6, k6,
        "Not really, no. Over the years we've built up about 380,000 worth "
        "of trucks and greenhouse equipment, but none of that was bought "
        "this year.")
    print(f"\nW5b (control) < [{status}] {reply[:200]}")
    fin6 = _fresh_read(conn, c6, "financials_json")
    check("W5b the plain explicit-no still stores 0 (A-115b intact)",
          fin6.get("current_capex") == 0.0, str(fin6.get("current_capex")))
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
