"""mini CW-033 turn-5 audit - LIVE attacks on the reopen surface (item 1),
the verbatim-ship blast radius (item 5), and the xsec door in section
focus (item 7), on :5050 with my own wordings.

  L1a multi-line reopen, wording that names NO line - the interception
      must not stand down into a raw landing on some row.
  L1b multi-line reopen, the line named the app's way - converts on THAT
      row only (173.3333 on the 12-period contract row).
  L1c multi-line reopen, the OTHER row (weekly) told a monthly figure -
      converts onto the right row (26/mo -> 6.0/wk on Snow), contract
      untouched.
  L2  ask path at reopen: mixed cadence holds the turn, writes nothing.
  L3  no-cadence control at reopen: behaves exactly as before (raw
      row-cadence landing, no interception).
  L4  "40 a week" at reopen: converts, receipt leads in the client's
      cadence (and whatever twin the router echoed, the stated figure
      wins).
  L5  ordinary reopen correction WITHOUT a capacity conversion (price)
      still naturalizes / replies normally - the verbatim-skip is scoped.
  L7a xsec door, focus=market, ambiguous cadence: the ask LEADS the
      section reply, nothing written.
  L7b xsec door, focus=market, differing cadence: converts (173.3333),
      ack speaks the client's cadence.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw033_t5_live.py"
"""
from __future__ import annotations

import copy
import json
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5050"
SUMAC = "2ecc759c5d934706ad95123831f9e0c2"

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
                "cadence": p.get("unit_cadence"),
                "ppy": p.get("operating_periods_per_year"),
            }
    return out


def make_clone(conn, source, tag, *, focus="done", add_snow_row=False):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (source,))
    src = cur.fetchone()
    cur.close()
    if not src:
        raise RuntimeError(f"source draft missing: {source}")
    clone_id = tag + uuid.uuid4().hex[: 32 - len(tag)]
    client_id = tag.upper() + uuid.uuid4().hex[:10].upper()
    fin = json.loads(src["financials_json"] or "{}")
    _coh = fin.get("_coherence")
    if isinstance(_coh, dict):
        _coh.pop("retention_pending", None)
    ops = json.loads(src["operating_model_json"] or "{}")
    if add_snow_row:
        lm = (ops.get("lob_models") or [None])[0]
        base_row = copy.deepcopy(lm["products"][0])
        base_row.update({
            "product_name": "Snow removal visit",
            "unit_cadence": "weekly",
            "units_per_week_capacity": 60,
            "units_per_period_capacity": 60,
            "operating_periods_per_year": 52,
            "unit_price": 180,
        })
        lm["products"].append(base_row)
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
        "financials_json": json.dumps(fin, ensure_ascii=False),
        "operating_model_json": json.dumps(ops, ensure_ascii=False),
        "planning_run_id": None,
        "planning_run_status": None,
        "planning_stage": None,
        "planning_status": None,
    }
    if focus == "done":
        # The consistency trigger requires a valid planning_run_json on a
        # done draft; a minimal synthetic frame satisfies it without
        # binding the clone to any REAL run (no run id anywhere).
        overrides["planning_run_json"] = json.dumps(
            {"stage": "clone_probe", "status": "completed"})
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

    print("L1a - multi-line reopen, NO line named")
    c, k = make_clone(conn, SUMAC, "mn33t5a", add_snow_row=True)
    before = ops_rows(conn, c)
    note("L1a before", str(before))
    status, reply = post_turn(c, k, "One fix - capacity should be 40 a week.")
    print(f"\nL1a FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    pc, sn = after.get("Property contract", {}), after.get("Snow removal visit", {})
    raw_40_somewhere = (pc.get("period") == 40.0 or sn.get("wk") == 40.0
                        or sn.get("period") == 40.0)
    converted_right = pc.get("period") is not None and abs(
        float(pc.get("period") or 0) - 173.3333) < 0.01
    unchanged = after == before
    check("L1a live 200", status == 200, str(status))
    check("L1a NEVER a raw 40 landed on a row whose cadence differs "
          "(period 40 on contract row = the C3 t1 wrong number)",
          not (pc.get("period") == 40.0), f"contract={pc} snow={sn}")
    note("L1a outcome", "unchanged (asked/refused)" if unchanged else
         f"changed: contract={pc} snow={sn} converted_right={converted_right}")
    cleanup(conn, c)

    print("\nL1b - multi-line reopen, contract line named the app's way")
    c, k = make_clone(conn, SUMAC, "mn33t5b", add_snow_row=True)
    status, reply = post_turn(
        c, k, "The Property contract capacity should be 40 a week, not 34.")
    print(f"\nL1b FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    pc, sn = after.get("Property contract", {}), after.get("Snow removal visit", {})
    check("L1b live 200", status == 200, str(status))
    check("L1b contract row CONVERTS (period 173.3333)",
          pc.get("period") is not None
          and abs(float(pc.get("period") or 0) - 173.3333) < 0.01, str(pc))
    check("L1b snow row untouched", sn.get("wk") == 60 and sn.get("period") == 60,
          str(sn))
    check("L1b receipt speaks the client's cadence", "40 a week" in reply.lower(),
          reply[:200])
    cleanup(conn, c)

    print("\nL1c - multi-line reopen, the OTHER (weekly) row told a monthly figure")
    c, k = make_clone(conn, SUMAC, "mn33t5c", add_snow_row=True)
    status, reply = post_turn(
        c, k, "Snow removal capacity should be 26 a month.")
    print(f"\nL1c FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    pc, sn = after.get("Property contract", {}), after.get("Snow removal visit", {})
    check("L1c live 200", status == 200, str(status))
    check("L1c snow row converts (26/mo -> 6.0/wk)",
          sn.get("wk") is not None and abs(float(sn.get("wk") or 0) - 6.0) < 0.01,
          str(sn))
    check("L1c contract row untouched", pc.get("period") == 34 and pc.get("wk") == 34,
          str(pc))
    cleanup(conn, c)

    print("\nL2 - ask path at reopen (mixed cadence)")
    c, k = make_clone(conn, SUMAC, "mn33t5d")
    before = ops_rows(conn, c)
    status, reply = post_turn(
        c, k, "Mowing capacity should be 40 a week - though monthly might be "
              "easier for you to track.")
    print(f"\nL2 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    lo = reply.lower()
    check("L2 live 200", status == 200, str(status))
    check("L2 the ask ships", "quick check on that capacity change" in lo,
          reply[:200])
    check("L2 the ask holds the turn (no completion prose, no second question)",
          "intake is complete" not in lo and "every number you just set" not in lo,
          reply[:300])
    check("L2 canonical cell untouched",
          after.get("Property contract", {}).get("period")
          == before.get("Property contract", {}).get("period"),
          f"before={before.get('Property contract')} after={after.get('Property contract')}")
    cleanup(conn, c)

    print("\nL3 - no-cadence control at reopen")
    c, k = make_clone(conn, SUMAC, "mn33t5e")
    status, reply = post_turn(c, k, "Mowing capacity should be 45, not 34.")
    print(f"\nL3 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    pc = after.get("Property contract", {})
    check("L3 live 200", status == 200, str(status))
    check("L3 cadence-free correction lands raw as before (period 45)",
          pc.get("period") == 45.0, str(pc))
    cleanup(conn, c)

    print("\nL4 - '40 a week' at reopen: convert + verbatim receipt leads")
    c, k = make_clone(conn, SUMAC, "mn33t5f")
    status, reply = post_turn(c, k, "Sorry - mowing capacity is 40 a week.")
    print(f"\nL4 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    pc = after.get("Property contract", {})
    check("L4 live 200", status == 200, str(status))
    check("L4 converts (period 173.3333, wk 40)",
          pc.get("period") is not None
          and abs(float(pc.get("period") or 0) - 173.3333) < 0.01
          and pc.get("wk") == 40.0, str(pc))
    check("L4 the verbatim receipt LEADS the reply",
          reply.strip().lower().startswith("recorded: capacity 40 a week"),
          reply[:160])
    check("L4 no cadence-word inversion anywhere ('40 a month' never spoken)",
          "40 a month" not in reply.lower(), reply[:300])
    cleanup(conn, c)

    print("\nL5 - ordinary reopen correction (price) still replies normally")
    c, k = make_clone(conn, SUMAC, "mn33t5g")
    status, reply = post_turn(
        c, k, "Actually our mowing price should be 550, not 520.")
    print(f"\nL5 FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    pc = after.get("Property contract", {})
    check("L5 live 200", status == 200, str(status))
    check("L5 price lands (550)", pc.get("price") == 550.0, str(pc))
    check("L5 the reply acknowledges the price change (not a bare/verbatim "
          "capacity receipt)",
          "550" in reply and not reply.strip().lower().startswith(
              "recorded: capacity"), reply[:200])
    cleanup(conn, c)

    print("\nL7a - xsec door, focus=market, ambiguous cadence: ask LEADS")
    c, k = make_clone(conn, SUMAC, "mn33t5h", focus="market")
    before = ops_rows(conn, c)
    status, reply = post_turn(
        c, k, "Actually, our mowing route capacity should be 40 a week, or "
              "call it 170 a month, not 34.")
    print(f"\nL7a FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    lo = reply.lower()
    check("L7a live 200", status == 200, str(status))
    check("L7a nothing written",
          after.get("Property contract", {}).get("period")
          == before.get("Property contract", {}).get("period")
          and after.get("Property contract", {}).get("wk")
          == before.get("Property contract", {}).get("wk"),
          f"after={after.get('Property contract')}")
    check("L7a the cadence ask LEADS the section reply",
          "quick check on that capacity change" in lo[:260], reply[:260])
    cleanup(conn, c)

    print("\nL7b - xsec door, focus=market, differing cadence: converts")
    c, k = make_clone(conn, SUMAC, "mn33t5i", focus="market")
    status, reply = post_turn(
        c, k, "Actually, our mowing route capacity should be 40 a week, not 34.")
    print(f"\nL7b FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, c)
    pc = after.get("Property contract", {})
    check("L7b live 200", status == 200, str(status))
    check("L7b converts (period 173.3333, never raw 40)",
          pc.get("period") is not None
          and abs(float(pc.get("period") or 0) - 173.3333) < 0.01, str(pc))
    check("L7b ack speaks the client's cadence", "40 a week" in reply.lower(),
          reply[:240])
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
