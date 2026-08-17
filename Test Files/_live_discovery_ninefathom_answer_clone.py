"""LIVE artifact-level proof that the WORKING discovery case still works after
the reader convergence (Nick's ruling 2026-08-17): the EXACT Nine Fathom
shape (6d2823db, msgs 24-31) through the real handler on the live :5050
backend + live GPT.

PRODUCTION CALL CHAIN: POST /api/intake-consult (focus=ops) ->
_open_stream_discovery_window (window only) -> consultant_chat_turn (THE
reader: conversation + latch + stream_discovery_note -> lob_models snapshot
+ stream_discovery_outcomes) -> _apply_model_ops_patch ->
_sdisc.record_stream_discovery_outcomes (origin stamp + latch + receipt from
STATE) -> carry_stream_discovery -> wrap gate (align_gate_rows_with_
persisted forces the null-driver discovery rows into the gate -> the
cascade asks their numbers) -> next turns capture unit/capacity/price.

Clone = messages[:25] of 6d2823db (msg 24 = the REAL ask is the last
assistant: retail coffee bags, wholesale coffee sales to grocery stores, or
brew gear and merchandise sales), latch reset to pending, discovered rows
stripped. POST the client's REAL msg 25 ("Yeah, we do sell retail coffee
bags ... And yes, we do wholesale coffee sales to grocery stores ... But no,
we don't do brew gear and merchandise sales"). EXPECT: two genuine yeses
land as real discovery_confirmed rows (added by the SHARED reader, stamped
by Python), the no is not added, receipts say so, the cascade then asks
the new line's numbers and the REAL msgs 27/29/31 fill them in.

  .venv\\Scripts\\python.exe "Test Files\\_live_discovery_ninefathom_answer_clone.py"
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5050"
SOURCE_DRAFT = "6d2823db268d483bbb4c8be8c627dc26"
CUT = 25
PRIMARY = "5 lb bag roasted coffee"
YES1 = "retail coffee bags"
YES2 = "wholesale coffee sales to grocery stores"
NO1 = "brew gear and merchandise sales"
FAILURES: list = []
try:
  sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
  pass


def check(label, ok, detail=""):
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
  if not ok:
    FAILURES.append(label)


def _fresh(conn, draft_id, column):
  try:
    conn.commit()
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute(f"SELECT {column} FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
  row = cur.fetchone()
  cur.close()
  return row[0] if row else None


def make_clone(conn, tag):
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  if not src:
    raise RuntimeError("source draft missing")
  clone_id = tag + uuid.uuid4().hex[: 32 - len(tag)]
  client_id = tag.upper() + uuid.uuid4().hex[:10].upper()
  all_msgs = json.loads(src["messages_json"] or "[]")
  messages = all_msgs[:CUT]
  ops = json.loads(src["operating_model_json"] or "{}")
  for k in ("competitive_advantage", "milestones", "_ops_restatement_pending", "_ops_restatement_text"):
    ops.pop(k, None)
  latch = ops.get("stream_discovery") or {}
  for c in latch.get("candidates") or []:
    c["answer"] = None
    for k in ("answered_from", "answer_reason", "first_read", "first_answered_from",
              "clarify_answered_from", "row_product_name", "read_by", "removed_from"):
      c.pop(k, None)
  latch.pop("clarify_asked", None)
  latch.pop("clarify_labels", None)
  lobs = []
  for lob in ops.get("lob_models") or []:
    prods = [p for p in (lob.get("products") or []) if isinstance(p, dict) and p.get("origin") != "discovery_confirmed"]
    if prods:
      lob = dict(lob)
      lob["products"] = prods
      lobs.append(lob)
  ops["lob_models"] = lobs
  overrides = {
    "draft_id": clone_id, "client_id": client_id, "active_focus": "ops",
    "ops_confirmed": 0, "market_confirmed": 0, "people_confirmed": 0, "financials_confirmed": 0,
    "ops_finalize_proposed": 0, "market_finalize_proposed": 0, "people_finalize_proposed": 0,
    "financials_finalize_proposed": 0, "status": "in_progress",
    "completed_at": None, "submitted_at": None, "intake_submission_id": None,
    "messages_json": json.dumps(messages, ensure_ascii=False),
    "operating_model_json": json.dumps(ops, ensure_ascii=False),
    "target_market_json": None, "people_json": None, "financials_json": None,
    "financials_year1_json": None, "marketing_model_json": None,
    "pending_ops_milestone_json": None,
    "planning_run_id": None, "planning_run_status": None,
    "planning_stage": None, "planning_status": None,
  }
  columns = [c for c in src.keys() if c != "id"]
  values = [overrides.get(c) if c in overrides else src[c] for c in columns]
  cur = conn.cursor()
  cur.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
    tuple(values),
  )
  conn.commit()
  cur.close()
  return clone_id, client_id, all_msgs, ops


def post_turn(clone_id, client_id, message):
  resp = requests.post(
    f"{BASE_URL}/api/intake-consult",
    json={"draft_id": clone_id, "client_id": client_id, "message": message},
    timeout=600,
  )
  body = resp.json() if resp.status_code == 200 else {}
  return resp.status_code, str(body.get("assistant_message") or ""), body


def cleanup(conn, clone_id):
  try:
    cur = conn.cursor()
    cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (clone_id,))
    conn.commit()
    cur.close()
  except Exception:
    pass


def rows_of(ops):
  return [(str(l.get("lob_name")), str(p.get("product_name")), p.get("origin"),
           p.get("unit_price"), p.get("units_per_week_capacity"), p.get("utilization_rate"))
          for l in ops.get("lob_models") or [] for p in l.get("products") or []]


def latch_answers(ops):
  return {c.get("label"): c.get("answer") for c in ((ops.get("stream_discovery") or {}).get("candidates") or [])}


def row_names(ops):
  return {c.get("label"): (c.get("row_product_name") or c.get("label")) for c in ((ops.get("stream_discovery") or {}).get("candidates") or [])}


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  conn = get_mysql_connection()
  t0 = time.time()
  cid, kid, all_msgs, ops0 = make_clone(conn, "sdninea")
  try:
    rows0 = rows_of(ops0)
    print(f"clone {cid} of {SOURCE_DRAFT[:8]} rewound to messages[:{CUT}]; rows: {json.dumps(rows0)}")
    check("clone starts with the primary line only, latch pending on the 3 real labels",
          len(rows0) == 1 and rows0[0][1] == PRIMARY and set(latch_answers(ops0)) == {YES1, YES2, NO1} and all(a is None for a in latch_answers(ops0).values()))
    check("last assistant is the REAL ask", "before we wrap up operations" in all_msgs[CUT - 1]["content"].lower())
    reply = all_msgs[25]["content"]
    print(f"  > [25] {reply}")
    status, text, body = post_turn(cid, kid, reply)
    print(f"  < [{status}] {text[:700]}")
    check("answer turn 200", status == 200, str(status))
    ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
    rows = rows_of(ops)
    ans = latch_answers(ops)
    names = row_names(ops)
    print("  rows:", json.dumps(rows))
    print("  latch:", json.dumps(ans))
    check("two genuine yeses -> latch added, the no -> declined", ans.get(YES1) == "added" and ans.get(YES2) == "added" and ans.get(NO1) == "declined", json.dumps(ans))
    for lab in (YES1, YES2):
      hits = [r for r in rows if r[1] == names.get(lab, lab)]
      check(f"[{lab}] -> exactly one row, origin=discovery_confirmed (SHARED reader added it, Python stamped it)", len(hits) == 1 and hits[0][2] == "discovery_confirmed", json.dumps(hits))
    check("no row for the declined label", not any("brew gear" in r[1].lower() or "merchandise" in r[1].lower() for r in rows), json.dumps(rows))
    check("primary row untouched (58/380/.75)", [r for r in rows if r[1] == PRIMARY] == rows0, json.dumps(rows))
    check("exactly 3 rows (primary + two discovered)", len(rows) == 3, str(len(rows)))
    low = text.lower()
    check("receipts from the state: each added line 'is its own line; a few quick numbers'", low.count("is its own line; a few quick numbers") == 2, text[:300])
    check("receipt never mentions the declined stream", "brew gear" not in low, text[:300])
    check("the cascade asks for the new line's numbers (a question follows the receipts)", "?" in text, text[-200:])
    # The client's REAL follow-ups fill the discovered lines through the ordinary cascade.
    for idx in (27, 29, 31, 33):
      msg = all_msgs[idx]["content"]
      print(f"  > [{idx}] {msg[:200]}")
      status, text, body = post_turn(cid, kid, msg)
      print(f"  < [{status}] {text[:400]}")
      check(f"turn [{idx}] 200", status == 200, str(status))
      ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
      rows = rows_of(ops)
      check(f"after [{idx}] both discovered rows still present, still stamped", sum(1 for r in rows if r[2] == "discovery_confirmed") == 2, json.dumps(rows))
    ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
    rows = rows_of(ops)
    print("  final rows:", json.dumps(rows))
    disc = [r for r in rows if r[2] == "discovery_confirmed"]
    check("cascade captured numbers on the discovered rows (price + capacity present on at least one; the client gave 19/260 and 13/140)",
          any(r[3] not in (None, 0) and r[4] not in (None, 0) for r in disc), json.dumps(disc))
    check("latch still added/added/declined after the cascade turns", latch_answers(ops).get(YES1) == "added" and latch_answers(ops).get(YES2) == "added" and latch_answers(ops).get(NO1) == "declined", json.dumps(latch_answers(ops)))
  finally:
    cleanup(conn, cid)
  print(f"\n  ({time.time() - t0:.0f}s)")
  if FAILURES:
    print(f"RED: {len(FAILURES)} failing: {FAILURES}")
    return 1
  print("GREEN: live Nine Fathom genuine-yes clone passed - the working case still works through the SHARED reader")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
