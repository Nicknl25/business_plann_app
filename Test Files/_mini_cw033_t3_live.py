"""CW-033 turn 4 (mini audit of turn 3) -- adversarial live probes with
mini's OWN wordings, per the turn-3 TASK. Read rows, not replies.

  A1 (M1 seam): redirect turn ALSO carrying a genuine stage answer --
      the 2000 rent must land + be receipted, the 99 must not be spoken
      as recorded, the rent note must not die with the phantom filter.
  A2 (M1 seam): redirect turn whose figure-parse FAILS (two candidate
      capacities, no unique mark) -- consumed_figures carries candidates,
      filters must still hold, nothing written, nothing claimed.
  A3 (M1 seam): NON-redirect turn with a genuinely dropped stated field
      (cash on hand at the rent stage) -- the say-do note must STILL
      ship (the phantom filter is redirect-turns-only by design).
  A4 (M1 seam): Also-recorded change filter -- a restated on-file value
      (current revenue 1,730,000) must not be spoken as newly recorded.
  B1 (M2): volunteered price FIRST-CAPTURE on a nulled-price row
      mid-interview -- the door refuses on stage-active alone.
  B2 (M2): volunteered utilization mid-interview -- same.
  C1 (M3 attack): cadence word present but NOT the capacity's
      ("We invoice monthly" after a capacity correction on a weekly row).
  C2 (M3): weekly row told a monthly figure -- must convert 26/mo -> 6/wk.
  C3 (M3 no-op edge): stored period=40 then "40 a week" -- must CONVERT
      to 173.33, never silently no-op.
  C4 (M3): VS's D3 rerun -- Sumac "40 a week, not 34" -> 173.33/40.
  C5 (M3): VS's D2 control rerun -- Thornfield "7 jobs a week" -> 7/7.
  C6 (M3): mixed cadences in one message -- must ASK, write nothing.
  X1 (xsec door): the SAME cadence wording through the CW-017b
      market/people door (focus=people) -- does it land 40 RAW on the
      12-period row (wrong number, wk 9.23)?

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw033_t3_live.py"
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


def make_clone(conn, source, tag, msg_cut, strip_fields=(), focus="financials",
               ops_mutate=None):
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
    ops = json.loads(src["operating_model_json"] or "{}")
    if ops_mutate is not None:
        ops_mutate(ops)
    overrides = {
        "draft_id": clone_id,
        "client_id": client_id,
        "active_focus": focus,
        "financials_confirmed": 0,
        "financials_finalize_proposed": 0,
        "status": "in_progress",
        "completed_at": None,
        "submitted_at": None,
        "intake_submission_id": None,
        "messages_json": json.dumps(messages, ensure_ascii=False),
        "financials_json": json.dumps(fin, ensure_ascii=False),
        "operating_model_json": json.dumps(ops, ensure_ascii=False),
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

    # ---------------------------------------------------------------- A1
    print("A1 - M1 seam: redirect + genuine stage answer in one message")
    c, k = make_clone(conn, THORN, "mn33a1", 75, _STRIP_FROM_RENT)
    before = ops_rows(conn, c)
    status, reply = post_turn(
        c, k,
        "Bump the hard goods ticket price to 99 instead of 95 - oh, and our "
        "rent is 2,000 a month.")
    print(f"\nA1 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    fin = _fresh_read(conn, c, "financials_json")
    lo = reply.lower()
    check("A1 200", status == 200, str(status))
    check("A1 price stays 95 (no ops write)",
          after.get("Hard goods sale", {}).get("price") == 95,
          str(after.get("Hard goods sale")))
    check("A1 rows byte-equal", after == before)
    check("A1 rent 2000 LANDED",
          fin.get("monthly_rent_expense") == 2000.0,
          str(fin.get("monthly_rent_expense")))
    check("A1 redirect leads", "haven't changed any operations price" in lo,
          reply[:140])
    check("A1 no ack of the suppressed 99",
          "to 99" not in lo and "i'll update" not in lo
          and "i’ll update" not in lo)
    check("A1 the rent landing is RECEIPTED (2,000 spoken)",
          "2,000" in reply or "2000" in reply, reply[:200])
    check("A1 no false Also-recorded", "also recorded" not in lo)
    cleanup(conn, c)

    # ---------------------------------------------------------------- A2
    print("\nA2 - M1 seam: redirect whose figure-parse FAILS (6 vs 8, no mark)")
    c, k = make_clone(conn, THORN, "mn33a2", 75, _STRIP_FROM_RENT)
    before = ops_rows(conn, c)
    status, reply = post_turn(
        c, k,
        "The install crew capacity is wrong - some weeks we do 6 jobs, "
        "other weeks 8.")
    print(f"\nA2 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    lo = reply.lower()
    check("A2 200", status == 200, str(status))
    check("A2 no ops write", after == before,
          str(after.get("Landscaping/installation job")))
    check("A2 redirect spoken", "haven't changed any operations" in lo,
          reply[:160])
    check("A2 no 'Recorded:' claim", "recorded:" not in lo)
    check("A2 neither candidate spoken as landed",
          "to 6" not in lo and "to 8" not in lo and "i've updated" not in lo)
    fin = _fresh_read(conn, c, "financials_json")
    check("A2 no financials write of 6/8",
          fin.get("monthly_rent_expense") is None)
    cleanup(conn, c)

    # ---------------------------------------------------------------- A3
    print("\nA3 - M1 seam: NON-redirect turn, dropped stated field -> note ships")
    c, k = make_clone(conn, THORN, "mn33a3", 75, _STRIP_FROM_RENT)
    status, reply = post_turn(
        c, k,
        "Our rent is 2,400 a month, and we keep about 52,000 cash on hand.")
    print(f"\nA3 FULL REPLY < [{status}]\n{reply}\n")
    fin = _fresh_read(conn, c, "financials_json")
    lo = reply.lower()
    check("A3 200", status == 200, str(status))
    check("A3 rent 2400 landed", fin.get("monthly_rent_expense") == 2400.0,
          str(fin.get("monthly_rent_expense")))
    _coh_landed = fin.get("cash_on_hand") == 52000.0
    _noted = ("cash on hand" in lo and
              ("haven't recorded" in lo or "couldn't apply" in lo
               or "we'll get" in lo or "later" in lo or "yet" in lo))
    _proposed = "52,000" in reply and ("looks like you mean" in lo)
    check("A3 the 52,000 is HONESTLY handled (landed, noted, or proposed)",
          _coh_landed or _noted or _proposed,
          f"cash_on_hand={fin.get('cash_on_hand')} reply={reply[:200]}")
    check("A3 no silent swallow of 52,000",
          _coh_landed or "52,000" in reply or "cash on hand" in lo)
    note("A3 outcome", "landed" if _coh_landed else
         ("noted" if _noted else ("proposed" if _proposed else "OTHER")))
    cleanup(conn, c)

    # ---------------------------------------------------------------- A4
    print("\nA4 - M1 seam: Also-recorded must skip a no-op restated value")
    c, k = make_clone(conn, THORN, "mn33a4", 75, _STRIP_FROM_RENT)
    status, reply = post_turn(
        c, k,
        "Rent is 3,200 a month. Current revenue is still 1,730,000 by the way.")
    print(f"\nA4 FULL REPLY < [{status}]\n{reply}\n")
    fin = _fresh_read(conn, c, "financials_json")
    lo = reply.lower()
    check("A4 200", status == 200, str(status))
    check("A4 rent 3200 landed", fin.get("monthly_rent_expense") == 3200.0,
          str(fin.get("monthly_rent_expense")))
    check("A4 current revenue NOT spoken as newly recorded",
          not ("also recorded" in lo and "revenue" in lo.split("also recorded", 1)[-1]),
          reply[:250])
    check("A4 stored current_revenue unchanged",
          fin.get("current_revenue") == 1730000.0,
          str(fin.get("current_revenue")))
    cleanup(conn, c)

    # ---------------------------------------------------------------- B1
    print("\nB1 - M2: volunteered price FIRST-CAPTURE on a nulled row, mid-interview")

    def _null_install_price(ops):
        for lob in ops.get("lob_models") or []:
            for p in lob.get("products") or []:
                if "installation" in str(p.get("product_name", "")).lower():
                    p["unit_price"] = None

    c, k = make_clone(conn, THORN, "mn33b1", 99, _STRIP_FROM_OTHER_DEBT,
                      ops_mutate=_null_install_price)
    before = ops_rows(conn, c)
    note("B1 install row before", str(before.get("Landscaping/installation job")))
    status, reply = post_turn(
        c, k, "By the way - we charge 650 per install job.")
    print(f"\nB1 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    lo = reply.lower()
    inst = after.get("Landscaping/installation job", {})
    check("B1 200", status == 200, str(status))
    check("B1 NO price write mid-interview (row still null)",
          inst.get("price") is None, str(inst))
    check("B1 no other ops write", after == before)
    check("B1 no fabricated receipt",
          "recorded:" not in lo and "i've updated" not in lo
          and "i've set" not in lo)
    check("B1 the refusal/redirect is honest when spoken",
          ("haven't changed any operations" in lo) or ("650" not in reply)
          or ("haven't recorded" in lo), reply[:200])
    cleanup(conn, c)

    # ---------------------------------------------------------------- B2
    print("\nB2 - M2: volunteered utilization mid-interview")
    c, k = make_clone(conn, THORN, "mn33b2", 99, _STRIP_FROM_OTHER_DEBT)
    before = ops_rows(conn, c)
    status, reply = post_turn(
        c, k, "We're running at about 85% utilization on installs these days.")
    print(f"\nB2 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    lo = reply.lower()
    check("B2 200", status == 200, str(status))
    check("B2 NO utilization write mid-interview", after == before,
          str(after.get("Landscaping/installation job")))
    check("B2 no fabricated receipt",
          "recorded:" not in lo and "i've updated" not in lo)
    cleanup(conn, c)

    # ---------------------------------------------------------------- C1
    print("\nC1 - M3 attack: unrelated cadence word ('We invoice monthly')")
    c, k = make_clone(conn, THORN, "mn33c1", None, ())
    status, reply = post_turn(
        c, k,
        "One fix - the install crew capacity should be 9, not 5. We invoice "
        "monthly.")
    print(f"\nC1 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    inst = after.get("Landscaping/installation job", {})
    lo = reply.lower()
    check("C1 200", status == 200, str(status))
    _landed_9 = inst.get("wk") == 9.0
    _misbound = inst.get("wk") is not None and abs(float(inst.get("wk") or 0) - 9 * 12 / 52.0) < 0.01
    _asked = inst.get("wk") == 5.0 and ("quick check" in lo or "?" in reply)
    note("C1 install row after", str(inst))
    note("C1 outcome", "landed 9/wk (cadence ignored monthly - fine)" if _landed_9
         else ("MISBOUND to 2.08/wk (WRONG NUMBER)" if _misbound
               else ("asked" if _asked else "OTHER")))
    check("C1 the number is never silently wrong (9 landed, or asked; NOT 2.08)",
          _landed_9 or _asked, str(inst) + " | " + reply[:200])
    cleanup(conn, c)

    # ---------------------------------------------------------------- C2
    print("\nC2 - M3: weekly row told a monthly figure (26/mo -> 6/wk)")
    c, k = make_clone(conn, THORN, "mn33c2", None, ())
    status, reply = post_turn(
        c, k,
        "Actually the install crew can handle 26 jobs a month.")
    print(f"\nC2 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    inst = after.get("Landscaping/installation job", {})
    check("C2 200", status == 200, str(status))
    check("C2 converts 26/mo -> 6.0/wk",
          inst.get("wk") is not None and abs(float(inst.get("wk")) - 6.0) < 0.01,
          str(inst))
    check("C2 receipt speaks the client's cadence ('26 a month')",
          "26 a month" in reply.lower(), reply[:200])
    cleanup(conn, c)

    # ---------------------------------------------------------------- C3
    print("\nC3 - M3 no-op edge: store 40, then '40 a week' must CONVERT")
    c, k = make_clone(conn, SUMAC, "mn33c3", None, ())
    status1, reply1 = post_turn(
        c, k, "Our mowing capacity should be 40 a month, not 34.")
    mid = ops_rows(conn, c).get("Property contract", {})
    print(f"\nC3 turn1 < [{status1}] {reply1[:200]}")
    note("C3 row after turn1", str(mid))
    check("C3 turn1 lands 40 (month==period identity on 12-period row)",
          mid.get("period") == 40.0, str(mid))
    status2, reply2 = post_turn(
        c, k, "Sorry - mowing capacity is 40 a week.")
    print(f"\nC3 turn2 FULL REPLY < [{status2}]\n{reply2}\n")
    after = ops_rows(conn, c).get("Property contract", {})
    note("C3 row after turn2", str(after))
    check("C3 200/200", status1 == 200 and status2 == 200)
    check("C3 turn2 CONVERTS (period 173.33), never a silent no-op",
          after.get("period") is not None
          and abs(float(after.get("period")) - 173.3333) < 0.01, str(after))
    check("C3 week twin reads 40", after.get("wk") is not None
          and abs(float(after.get("wk")) - 40.0) < 0.01, str(after))
    cleanup(conn, c)

    # ---------------------------------------------------------------- C4
    print("\nC4 - M3: VS's D3 rerun (Sumac '40 a week, not 34')")
    c, k = make_clone(conn, SUMAC, "mn33c4", None, ())
    status, reply = post_turn(
        c, k, "Our mowing route capacity should be 40 a week, not 34.")
    print(f"\nC4 FULL REPLY < [{status}]\n{reply}\n")
    row = ops_rows(conn, c).get("Property contract", {})
    check("C4 200", status == 200, str(status))
    check("C4 period 173.33", row.get("period") is not None
          and abs(float(row.get("period")) - 173.3333) < 0.01, str(row))
    check("C4 wk 40", row.get("wk") is not None
          and abs(float(row.get("wk")) - 40.0) < 0.01, str(row))
    check("C4 reply speaks '40 a week'", "40 a week" in reply.lower(),
          reply[:200])
    cleanup(conn, c)

    # ---------------------------------------------------------------- C5
    print("\nC5 - M3: VS's D2 control rerun (Thornfield 7 jobs a week)")
    c, k = make_clone(conn, THORN, "mn33c5", None, ())
    status, reply = post_turn(
        c, k,
        "Hang on, one fix on operations - the install crew can actually do "
        "7 jobs a week, not 5. Please update that.")
    print(f"\nC5 FULL REPLY < [{status}]\n{reply}\n")
    inst = ops_rows(conn, c).get("Landscaping/installation job", {})
    check("C5 200", status == 200, str(status))
    check("C5 wk 7", inst.get("wk") == 7.0, str(inst))
    check("C5 period 7", inst.get("period") == 7.0, str(inst))
    cleanup(conn, c)

    # ---------------------------------------------------------------- C6
    print("\nC6 - M3: mixed cadences must ASK, write nothing")
    c, k = make_clone(conn, SUMAC, "mn33c6", None, ())
    before = ops_rows(conn, c)
    status, reply = post_turn(
        c, k,
        "Mowing capacity should be 40 a week - call it about 170 a month.")
    print(f"\nC6 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    check("C6 200", status == 200, str(status))
    check("C6 nothing written", after == before,
          str(after.get("Property contract")))
    check("C6 the ask is spoken", "quick check" in reply.lower()
          or "?" in reply, reply[:200])
    cleanup(conn, c)

    # ---------------------------------------------------------------- X1
    print("\nX1 - xsec door (focus=people): cadence wording on the 12-period row")
    c, k = make_clone(conn, SUMAC, "mn33x1", None, (), focus="people")
    before = ops_rows(conn, c)
    note("X1 row before", str(before.get("Property contract")))
    status, reply = post_turn(
        c, k,
        "Actually, our mowing route capacity should be 40 a week, not 34.")
    print(f"\nX1 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c).get("Property contract", {})
    note("X1 row after", str(after))
    check("X1 200", status == 200, str(status))
    _raw40 = after.get("period") == 40.0
    _conv = after.get("period") is not None and abs(
        float(after.get("period") or 0) - 173.3333) < 0.01
    _untouched = after == before.get("Property contract")
    note("X1 outcome",
         "RAW 40 LANDED on the 12-period row (wk %.2f) - WRONG NUMBER" %
         float(after.get("wk") or 0) if _raw40 else
         ("converted correctly" if _conv else
          ("untouched" if _untouched else "OTHER")))
    check("X1 the client's '40 a week' is never stored as 9.23/wk",
          not _raw40, str(after))
    cleanup(conn, c)

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
