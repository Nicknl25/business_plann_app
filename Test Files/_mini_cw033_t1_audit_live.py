"""mini CW-033 turn-1 ARTIFACT audit - live probes, my own wordings.

PRODUCTION CALL CHAIN (named per the E2E law):
  POST /api/intake-consult -> post_intake_consult_handler
    -> focus=financials: _run_financials_turn_and_sync (redirect detect)
       -> _run_financials_turn_and_sync_inner -> route_intent (live GPT)
       -> stage doors / forward move -> persisted ops + financials
    -> focus=ops: section handler -> scoped patch -> edit receipt ->
       followup consultant patch -> A-112 note re-validation (18477)

Clones of REAL drafts (Thornfield d9b17850, Sumac 2ecc759c), live :5050,
live GPT router. Proof = persisted rows, read fresh (commit-first).

  A: A-115a - 58% shared-rate wordings at [75]; retention/price attack.
     RETENTION IS READ AT ITS REAL HOME financials._coherence.retention_pending
     (VS's L6 read fin['intake_coherence'] - a key that never exists).
  B: A-115b - capex explicit-no at [89]; correction lookahead; the
     but-we-did edge (B3) driven live to confirm reach.
  C: A-112 - ops-section multi-line capture, plant row rewound to
     mid-capture; any "haven't recorded"/"couldn't apply" note must not
     name a field stored this turn.
  D: A-113 redirect mid-interview (D1) vs the wall (D2, must LAND with
     both capacity twins moving); D3 single-row boundary on Sumac with a
     message naming a product the model does not have.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw033_t1_audit_live.py"
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


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def note(label: str, detail: str = "") -> None:
    print(f"  [NOTE] {label}" + (f": {detail}" if detail else ""))


def _fresh_read(conn, draft_id, column):
    try:
        conn.commit()  # end the REPEATABLE READ snapshot first
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


def retention_state(conn, draft_id):
    fin = _fresh_read(conn, draft_id, "financials_json")
    coh = fin.get("_coherence")
    rp = coh.get("retention_pending") if isinstance(coh, dict) else None
    return rp, fin


def make_clone(conn, source, tag, msg_cut, strip_fields=(), active_focus="financials",
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
    ops = json.loads(src["operating_model_json"] or "{}")
    if ops_mutate:
        ops = ops_mutate(ops)
    overrides = {
        "draft_id": clone_id,
        "client_id": client_id,
        "active_focus": active_focus,
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

    # =====================================================================
    print("=" * 72)
    print("A: A-115a - the 58% shared-rate class, my own wordings at [75]")
    print("=" * 72)

    A_WORDINGS = [
        ("A1", "Before we do rent - on costs, the plant line and the hard "
               "goods line are really the same thing economically, stock we "
               "buy in and resell. Put them on one shared cost rate of 58 "
               "percent. Landscaping and design keep their own rates."),
        ("A2", "Actually one correction first: use a single shared rate for "
               "both retail lines - call it 58 percent across plants and "
               "hard goods together."),
    ]
    a1_clone = None
    for tag, wording in A_WORDINGS:
        cid, kid = make_clone(conn, THORN, "mn33" + tag.lower(), 75, _STRIP_FROM_RENT)
        before = ops_rows(conn, cid)
        rp_before, _ = retention_state(conn, cid)
        status, reply = post_turn(cid, kid, wording)
        print(f"\n{tag} < [{status}] {reply[:300]}")
        after = ops_rows(conn, cid)
        rp_after, fin_after = retention_state(conn, cid)
        check(f"{tag} live turn 200", status == 200, str(status))
        check(f"{tag} NO unit price changed on any row",
              {k: v["price"] for k, v in after.items()}
              == {k: v["price"] for k, v in before.items()},
              str({k: v["price"] for k, v in after.items()}))
        check(f"{tag} NO capacity/util changed on any row",
              all(after[k]["wk"] == before[k]["wk"]
                  and after[k]["period"] == before[k]["period"]
                  and after[k]["util"] == before[k]["util"] for k in before),
              "")
        check(f"{tag} retention_pending NOT stamped (real home: _coherence)",
              rp_after == rp_before and not rp_after, str(rp_after))
        check(f"{tag} reply has no retention ask (no self-trigger)",
              "customers to stay" not in reply.lower()
              and "realistically keep" not in reply.lower(), reply[:120])
        check(f"{tag} reply never records a unit price",
              "recorded: unit price" not in reply.lower()
              and "unit price $" not in reply.lower(), "")
        check(f"{tag} 58% landed on BOTH named rows as cogs",
              after.get("Plant and nursery sale", {}).get("cogs") == 0.58
              and after.get("Hard goods sale", {}).get("cogs") == 0.58,
              str({k: v["cogs"] for k, v in after.items()}))
        check(f"{tag} shared group stored with basis declared",
              "shared:" in str(after.get("Plant and nursery sale", {}).get("group"))
              and after.get("Plant and nursery sale", {}).get("basis") == "declared"
              and after.get("Hard goods sale", {}).get("basis") == "declared",
              str(after.get("Plant and nursery sale", {}).get("group")))
        check(f"{tag} install/design rates untouched",
              after.get("Landscaping/installation job", {}).get("cogs") == 0.17
              and after.get("Design/consultation project", {}).get("cogs") == 0.03,
              "")
        if tag == "A1":
            a1_clone = (cid, kid)
        else:
            cleanup(conn, cid)

    # A3: the [77] restatement shape on A1's clone - prices restated, none moved.
    if a1_clone:
        cid, kid = a1_clone
        before = ops_rows(conn, cid)
        rp_before, _ = retention_state(conn, cid)
        status, reply = post_turn(
            cid, kid,
            "Just so we're clear, no prices moved - still 52 for a plant "
            "ticket, 95 for hard goods, 2400 per install, 1250 per design. "
            "That 58 percent is only a cost rate.")
        print(f"\nA3 < [{status}] {reply[:300]}")
        after = ops_rows(conn, cid)
        rp_after, _ = retention_state(conn, cid)
        check("A3 live turn 200", status == 200, str(status))
        check("A3 restated prices did NOT move any row",
              {k: v["price"] for k, v in after.items()}
              == {k: v["price"] for k, v in before.items()},
              str({k: v["price"] for k, v in after.items()}))
        check("A3 NO retention stamp on a restatement",
              rp_after == rp_before and not rp_after, str(rp_after))
        check("A3 reply speaks no new price recording",
              "recorded: unit price" not in reply.lower(), reply[:120])
        cleanup(conn, cid)

    # A4: retention-gate attack - a price CHANGE mid-interview must not
    # stamp retention without a landed write (post-retraction: redirect).
    cid, kid = make_clone(conn, THORN, "mn33a4", 75, _STRIP_FROM_RENT)
    before = ops_rows(conn, cid)
    rp_before, _ = retention_state(conn, cid)
    status, reply = post_turn(
        cid, kid,
        "One more thing - bump the hard goods ticket price to 99 instead of 95.")
    print(f"\nA4 < [{status}] {reply[:300]}")
    after = ops_rows(conn, cid)
    rp_after, _ = retention_state(conn, cid)
    check("A4 live turn 200", status == 200, str(status))
    check("A4 price did NOT change (off-path is prevented)",
          after.get("Hard goods sale", {}).get("price") == 95,
          str(after.get("Hard goods sale", {}).get("price")))
    check("A4 NO retention stamp without a landed price write",
          rp_after == rp_before and not rp_after, str(rp_after))
    check("A4 redirect leads / no fabricated price receipt",
          ("haven't changed any operations" in reply.lower())
          or ("recorded" not in reply.lower()), reply[:160])
    cleanup(conn, cid)

    # =====================================================================
    print()
    print("=" * 72)
    print("B: A-115b - capex explicit-no at [89], my own wordings")
    print("=" * 72)

    # B1 + B2 on one clone: explicit no, then the protected correction.
    cid, kid = make_clone(conn, THORN, "mn33b1", 89, _STRIP_FROM_CAPEX)
    status, reply = post_turn(
        cid, kid,
        "Not really, no. Over the years we've built up about 380,000 worth "
        "of trucks and greenhouse equipment, but none of that was bought "
        "this year.")
    print(f"\nB1 < [{status}] {reply[:300]}")
    fin = _fresh_read(conn, cid, "financials_json")
    check("B1 live turn 200", status == 200, str(status))
    check("B1 current_capex stored as 0", fin.get("current_capex") == 0.0,
          str(fin.get("current_capex")))
    hits = json_contains_value(
        {k: v for k, v in fin.items() if k != "_coherence"}, 380000.0)
    check("B1 380,000 captured NOWHERE in financials",
          not hits, str(hits))
    ppl = _fresh_read(conn, cid, "people_json")
    hits_p = json_contains_value(ppl, 380000.0)
    check("B1 380,000 not smuggled into people either", not hits_p, str(hits_p))

    status2, reply2 = post_turn(
        cid, kid,
        "No wait, actually we did spend 380,000 on equipment this year.")
    print(f"\nB2 < [{status2}] {reply2[:300]}")
    fin2 = _fresh_read(conn, cid, "financials_json")
    check("B2 live turn 200", status2 == 200, str(status2))
    check("B2 the lookahead lets the correction LAND (capex 380,000)",
          fin2.get("current_capex") == 380000.0, str(fin2.get("current_capex")))
    cleanup(conn, cid)

    # B3: the known edge - negative lead + a REAL purchase in one answer.
    cid, kid = make_clone(conn, THORN, "mn33b3", 89, _STRIP_FROM_CAPEX)
    status3, reply3 = post_turn(
        cid, kid,
        "No, none of it was bought this year - but we did spend 15,000 on "
        "a mower back in January.")
    print(f"\nB3 < [{status3}] {reply3[:300]}")
    fin3 = _fresh_read(conn, cid, "financials_json")
    note("B3 EDGE current_capex stored", str(fin3.get("current_capex")))
    hits3 = json_contains_value(
        {k: v for k, v in fin3.items() if k != "_coherence"}, 15000.0)
    note("B3 EDGE where 15,000 landed in financials", str(hits3) or "nowhere")
    note("B3 reply", reply3[:200])
    cleanup(conn, cid)

    # =====================================================================
    print()
    print("=" * 72)
    print("C: A-112 - ops-section capture, plant row rewound to mid-capture")
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

    cid, kid = make_clone(conn, THORN, "mn33c1", 9, (), active_focus="ops",
                          ops_mutate=_rewind_plant)
    before = ops_rows(conn, cid)
    note("C1 plant row before", str(before.get("Plant and nursery sale")))
    status, reply = post_turn(
        cid, kid,
        "The register ticket works for me. One plant checkout as the unit. "
        "Tickets average 52 dollars, we can handle about 340 in a full "
        "week, and across the year we really run at about 62 percent of "
        "that.")
    print(f"\nC1 < [{status}] {reply[:400]}")
    after = ops_rows(conn, cid)
    note("C1 plant row after", str(after.get("Plant and nursery sale")))
    check("C1 live turn 200", status == 200, str(status))
    low = reply.lower()
    claims_unrecorded = ("haven't recorded" in low) or ("couldn't apply" in low)
    plant = after.get("Plant and nursery sale", {})
    recorded_now = {
        "unit price": plant.get("price") is not None
        and before.get("Plant and nursery sale", {}).get("price") is None,
        "units per week capacity": plant.get("wk") is not None
        and before.get("Plant and nursery sale", {}).get("wk") is None,
    }
    if claims_unrecorded:
        for label, was_recorded in recorded_now.items():
            named = label in low
            check(f"C1 note never claims '{label}' unrecorded when it stored",
                  not (named and was_recorded),
                  f"named={named} stored_this_turn={was_recorded}")
    else:
        note("C1 no unapplied-note in reply (nothing to contradict)")
    check("C1 the capture itself landed (price 52 / cap 340 on plant row)",
          plant.get("price") == 52 and plant.get("wk") == 340,
          str(plant))
    cleanup(conn, cid)

    # =====================================================================
    print()
    print("=" * 72)
    print("D: A-113 redirect vs the wall, and the single-row boundary")
    print("=" * 72)

    # D1: mid-interview (stage active) - redirect, zero writes.
    cid, kid = make_clone(conn, THORN, "mn33d1", 99, _STRIP_FROM_OTHER_DEBT)
    before = ops_rows(conn, cid)
    status, reply = post_turn(
        cid, kid,
        "Hang on, one fix on operations - the install crew can actually do "
        "7 jobs a week, not 5. Please update that.")
    print(f"\nD1 < [{status}] {reply[:300]}")
    after = ops_rows(conn, cid)
    check("D1 live turn 200", status == 200, str(status))
    check("D1 NO ops write anywhere mid-interview",
          after == before, str(after.get("Landscaping/installation job")))
    check("D1 the honest redirect leads",
          "haven't changed any operations" in reply.lower(), reply[:140])
    check("D1 no fabricated receipt",
          "recorded: capacity" not in reply.lower()
          and "i've updated" not in reply.lower(), "")
    cleanup(conn, cid)

    # D2: the WALL (financials complete, nothing stripped) - the same
    # correction is invited and must LAND, both capacity twins moving.
    cid, kid = make_clone(conn, THORN, "mn33d2", None, ())
    before = ops_rows(conn, cid)
    check("D2 wall clone: install still 5/5",
          before.get("Landscaping/installation job", {}).get("wk") == 5
          and before.get("Landscaping/installation job", {}).get("period") == 5,
          str(before.get("Landscaping/installation job")))
    status, reply = post_turn(
        cid, kid,
        "Hang on, one fix on operations - the install crew can actually do "
        "7 jobs a week, not 5. Please update that.")
    print(f"\nD2 < [{status}] {reply[:300]}")
    after = ops_rows(conn, cid)
    check("D2 live turn 200", status == 200, str(status))
    inst = after.get("Landscaping/installation job", {})
    check("D2 the wall correction LANDS (week twin = 7)",
          inst.get("wk") == 7.0, str(inst))
    check("D2 no evaporation (period twin agrees = 7)",
          inst.get("period") == 7.0, str(inst))
    check("D2 other rows byte-equal",
          all(after[k] == before[k] for k in before
              if k != "Landscaping/installation job"), "")
    check("D2 reply speaks the landing (no silent write)",
          "7" in reply, reply[:160])
    cleanup(conn, cid)

    # D3: single-row boundary - Sumac, message names a product the model
    # does not have. CW-026 contract: lands on the one row as a
    # correctable proposal. Observe and rule.
    cid, kid = make_clone(conn, SUMAC, "mn33d3", None, ())
    before = ops_rows(conn, cid)
    note("D3 Sumac rows before", str(before))
    status, reply = post_turn(
        cid, kid,
        "Our mowing route capacity should be 40 a week, not 34.")
    print(f"\nD3 < [{status}] {reply[:300]}")
    after = ops_rows(conn, cid)
    note("D3 Sumac rows after", str(after))
    check("D3 live turn 200", status == 200, str(status))
    row = after.get("Property contract", {})
    if row.get("wk") == 40.0:
        note("D3 BOUNDARY: landed on the one row (CW-026 worst-case-"
             "correctable-proposal)")
        check("D3 if landed, the reply SPEAKS the landing so it is correctable",
              "40" in reply, reply[:200])
        check("D3 twins agree", row.get("period") == 40.0, str(row))
    elif row.get("wk") == 34.0:
        note("D3 BOUNDARY: refused/asked instead of landing", reply[:200])
    else:
        check("D3 wrote something unexpected", False, str(row))
    cleanup(conn, cid)

    conn.close()
    print()
    if FAILURES:
        print(f"RESULT: RED - {len(FAILURES)} failing check(s):")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("RESULT: GREEN - all live checks passed (see NOTE lines for ruled items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
