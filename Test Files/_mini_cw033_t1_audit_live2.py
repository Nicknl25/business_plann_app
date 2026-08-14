"""mini CW-033 turn-1 audit, ROUND 2 - clone-hygiene-fixed reruns.

Round 1's A-retention 'FAIL's were probe baseline bugs: the SOURCE
Thornfield draft's financials carry a STALE _coherence.retention_pending
frame stamped by the original pre-fix run at [78]; clones inherited it.
Round 2 strips it at clone time, so the assertion is 'no NEW stamp'.

  A1b: the 58% collapse wording - full row diff (round 1 saw a
       capacity/util change somewhere; find it).
  A4b: the price-change redirect turn - FULL reply + financials diff:
       did anything write, and is "I'll update ... to 99" invention?
  C1b: the [9] ops capture with financials EMPTIED (round 1's full
       financials was an unreachable state and misrouted 340 into rent).

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw033_t1_audit_live2.py"
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
THORN = "d9b17850350545e9911fa09b3e333429"

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
                "cogs": p.get("cogs_percent_of_line_revenue"),
                "group": p.get("cogs_cost_structure_group"),
                "basis": p.get("cogs_cost_structure_group_basis"),
            }
    return out


def retention(conn, draft_id):
    fin = _fresh_read(conn, draft_id, "financials_json")
    coh = fin.get("_coherence")
    return (coh.get("retention_pending") if isinstance(coh, dict) else None), fin


def make_clone(conn, source, tag, msg_cut, strip_fields=(), active_focus="financials",
               ops_mutate=None, fin_replace=None):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (source,))
    src = cur.fetchone()
    cur.close()
    clone_id = tag + uuid.uuid4().hex[: 32 - len(tag)]
    client_id = tag.upper() + uuid.uuid4().hex[:10].upper()
    messages = json.loads(src["messages_json"] or "[]")
    if msg_cut is not None:
        messages = messages[:msg_cut]
    if fin_replace is not None:
        fin = dict(fin_replace)
    else:
        fin = json.loads(src["financials_json"] or "{}")
        for f in strip_fields:
            fin.pop(f, None)
        # CLONE HYGIENE: drop the stale retention frame the pre-fix run
        # stamped at [78]; keep the rest of the walk state.
        coh = fin.get("_coherence")
        if isinstance(coh, dict) and "retention_pending" in coh:
            coh = dict(coh)
            coh.pop("retention_pending", None)
            fin["_coherence"] = coh
    ops = json.loads(src["operating_model_json"] or "{}")
    if ops_mutate:
        ops = ops_mutate(ops)
    overrides = {
        "draft_id": clone_id, "client_id": client_id,
        "active_focus": active_focus, "financials_confirmed": 0,
        "financials_finalize_proposed": 0, "status": "in_progress",
        "completed_at": None, "submitted_at": None,
        "intake_submission_id": None,
        "messages_json": json.dumps(messages, ensure_ascii=False),
        "financials_json": json.dumps(fin, ensure_ascii=False),
        "operating_model_json": json.dumps(ops, ensure_ascii=False),
        "planning_run_id": None, "planning_run_status": None,
        "planning_stage": None, "planning_status": None,
    }
    columns = [c for c in src.keys() if c != "id"]
    values = [overrides.get(c, src[c]) if c in overrides else src[c] for c in columns]
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))})",
        tuple(values))
    conn.commit()
    cur.close()
    return clone_id, client_id


def post_turn(clone_id, client_id, message):
    resp = requests.post(
        f"{BASE_URL}/api/intake-consult",
        json={"draft_id": clone_id, "client_id": client_id, "message": message},
        timeout=300)
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

    print("=" * 72)
    print("A1b: the 58% collapse, clean baseline, full row diff")
    print("=" * 72)
    cid, kid = make_clone(conn, THORN, "mn33e1", 75, _STRIP_FROM_RENT)
    before = ops_rows(conn, cid)
    rp_b, fin_b = retention(conn, cid)
    status, reply = post_turn(
        cid, kid,
        "Before we do rent - on costs, the plant line and the hard goods "
        "line are really the same thing economically, stock we buy in and "
        "resell. Put them on one shared cost rate of 58 percent. "
        "Landscaping and design keep their own rates.")
    print(f"\nA1b < [{status}] {reply[:400]}")
    after = ops_rows(conn, cid)
    rp_a, fin_a = retention(conn, cid)
    check("A1b live turn 200", status == 200, str(status))
    for name in before:
        for f in ("wk", "period", "price", "util"):
            if before[name][f] != after[name][f]:
                note(f"A1b DIFF {name}.{f}", f"{before[name][f]} -> {after[name][f]}")
    check("A1b NO price/capacity/util changed on any row",
          all(before[n][f] == after[n][f] for n in before
              for f in ("wk", "period", "price", "util")), "")
    check("A1b NO NEW retention stamp", not rp_a, str(rp_a))
    for k in sorted(set(fin_b) | set(fin_a)):
        if k == "_coherence":
            continue
        if fin_b.get(k) != fin_a.get(k):
            note(f"A1b FIN DIFF {k}", f"{fin_b.get(k)!r} -> {fin_a.get(k)!r}")
    check("A1b 58% on both rows, basis declared",
          after.get("Plant and nursery sale", {}).get("cogs") == 0.58
          and after.get("Hard goods sale", {}).get("cogs") == 0.58
          and after.get("Plant and nursery sale", {}).get("basis") == "declared", "")
    cleanup(conn, cid)

    print()
    print("=" * 72)
    print("A4b: the price-change redirect - full reply + financials diff")
    print("=" * 72)
    cid, kid = make_clone(conn, THORN, "mn33e4", 75, _STRIP_FROM_RENT)
    before = ops_rows(conn, cid)
    rp_b, fin_b = retention(conn, cid)
    status, reply = post_turn(
        cid, kid,
        "One more thing - bump the hard goods ticket price to 99 instead "
        "of 95.")
    print(f"\nA4b FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, cid)
    rp_a, fin_a = retention(conn, cid)
    check("A4b live turn 200", status == 200, str(status))
    check("A4b price did NOT change", after.get("Hard goods sale", {}).get("price") == 95,
          str(after.get("Hard goods sale", {}).get("price")))
    check("A4b NO NEW retention stamp", not rp_a, str(rp_a))
    for k in sorted(set(fin_b) | set(fin_a)):
        if k == "_coherence":
            continue
        if fin_b.get(k) != fin_a.get(k):
            note(f"A4b FIN DIFF {k}", f"{fin_b.get(k)!r} -> {fin_a.get(k)!r}")
    check("A4b redirect leads", "haven't changed any operations" in reply.lower(),
          reply[:120])
    low = reply.lower()
    check("A4b reply does NOT ack the suppressed price change",
          ("update the hard goods" not in low) and ("to 99" not in low)
          and ("99" not in low or "1,99" in low), reply[:400])
    cleanup(conn, cid)

    print()
    print("=" * 72)
    print("C1b: [9] ops capture, financials EMPTY (reachable state)")
    print("=" * 72)

    def _rewind_plant(ops):
        ops = copy.deepcopy(ops)
        for lob in ops.get("lob_models") or []:
            for p in lob.get("products") or []:
                if "Plant" in str(p.get("product_name")):
                    for f in ("unit_price", "units_per_week_capacity",
                              "units_per_period_capacity", "utilization_rate"):
                        p.pop(f, None)
        return ops

    cid, kid = make_clone(conn, THORN, "mn33e5", 9, (), active_focus="ops",
                          ops_mutate=_rewind_plant, fin_replace={})
    before = ops_rows(conn, cid)
    note("C1b plant row before", str(before.get("Plant and nursery sale")))
    status, reply = post_turn(
        cid, kid,
        "The register ticket works for me. One plant checkout as the unit. "
        "Tickets average 52 dollars, we can handle about 340 in a full "
        "week, and across the year we really run at about 62 percent of "
        "that.")
    print(f"\nC1b FULL REPLY < [{status}]\n{reply}\n")
    after = ops_rows(conn, cid)
    fin_a = _fresh_read(conn, cid, "financials_json")
    note("C1b plant row after", str(after.get("Plant and nursery sale")))
    note("C1b financials keys now", str(sorted(k for k in fin_a if not k.startswith('_'))))
    check("C1b live turn 200", status == 200, str(status))
    low = reply.lower()
    plant_b = before.get("Plant and nursery sale", {})
    plant = after.get("Plant and nursery sale", {})
    claims = ("haven't recorded" in low) or ("couldn't apply" in low)
    if claims:
        for label, field in (("unit price", "price"),
                             ("units per week capacity", "wk"),
                             ("capacity", "wk")):
            stored_now = plant.get(field) is not None and plant_b.get(field) is None
            named = label in low
            check(f"C1b note never claims '{label}' unrecorded when stored",
                  not (named and stored_now),
                  f"named={named} stored={stored_now}")
    else:
        note("C1b no unapplied-note in reply")
    note("C1b did the capture land?",
         f"price={plant.get('price')} wk={plant.get('wk')} util={plant.get('util')}")
    check("C1b nothing wrote 340 into a financials field",
          all(v != 340 for v in fin_a.values() if isinstance(v, (int, float))),
          str({k: v for k, v in fin_a.items() if v == 340}))
    cleanup(conn, cid)

    conn.close()
    print()
    if FAILURES:
        print(f"RESULT: RED - {len(FAILURES)} failing check(s):")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("RESULT: GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
