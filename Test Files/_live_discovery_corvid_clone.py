"""LIVE artifact-level red-proof for the discovery reader CONVERGENCE (Nick's
ruling 2026-08-17, Option A) on the EXACT Corvid Press transcript
(e3af1f24, msgs 22-26), through the real handler on the live :5050
backend + live GPT.

PRODUCTION CALL CHAIN: POST /api/intake-consult (focus=ops) ->
_open_stream_discovery_window (window detection only) -> consultant_chat_turn
(THE reader: full conversation + latch + stream_discovery_note; returns the
authoritative lob_models snapshot + stream_discovery_outcomes) ->
_apply_model_ops_patch -> _sdisc.record_stream_discovery_outcomes (origin
stamp + latch answer + receipt from STATE) -> carry_stream_discovery (no
resurrection) + note_stream_discovery_removals -> wrap gate
(align_gate_rows_with_persisted) -> competitive advantage / milestone ->
consultant_finalize (+ carry restore_dropped=True) -> ops done.

CASE A (merged): clone = messages[:23] of e3af1f24 (msg 22 = the ask is the
last assistant), latch reset to pending, phantom row stripped. POST the
client's REAL msg 23 ("Digital printing is already part of our commercial
print line ... not a separate thing. No copying ... No graphic design ...
And no bindery ..."). EXPECT: NO phantom row, model has 2 lines not 3,
latch records merged_into:<line> for digital printing + declined for the
three, receipt says it stays inside (no 'is its own line').

CASE B (removed): clone = messages[:25] AS PERSISTED (phantom null-driver
row present, latch answer yes). POST the client's REAL msg 25 ("No, don't
make digital printing a separate line ... Please drop that line."). EXPECT:
row removed, latch records removed, receipt says dropped; then the REAL
msgs 27 + 29 drive ops through competitive advantage + milestone to
finalize -> the row is NOT resurrected at any turn or at finalize, no
null-driver row remains, ops hands off to market.

PRE (old code): A mints the phantom (RED); B resurrects it (RED).
Clones deleted after.

  .venv\\Scripts\\python.exe "Test Files\\_live_discovery_corvid_clone.py" [A|B|AB]
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
SOURCE_DRAFT = "e3af1f2463c7493f8e5cf91e9decebb9"
PHANTOM = "Digital printing services"
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


def make_clone(conn, tag, cut, *, reset_latch, strip_phantom):
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  if not src:
    raise RuntimeError("source draft missing")
  clone_id = tag + uuid.uuid4().hex[: 32 - len(tag)]
  client_id = tag.upper() + uuid.uuid4().hex[:10].upper()
  messages = json.loads(src["messages_json"] or "[]")[:cut]
  ops = json.loads(src["operating_model_json"] or "{}")
  for k in ("competitive_advantage", "milestones", "_ops_restatement_pending", "_ops_restatement_text"):
    ops.pop(k, None)
  latch = ops.get("stream_discovery") or {}
  if reset_latch:
    for c in latch.get("candidates") or []:
      c["answer"] = None
      for k in ("answered_from", "answer_reason", "first_read", "first_answered_from",
                "clarify_answered_from", "row_product_name", "read_by", "removed_from"):
        c.pop(k, None)
    latch.pop("clarify_asked", None)
    latch.pop("clarify_labels", None)
  if strip_phantom:
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
  return clone_id, client_id, messages, ops


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


def phantom_rows(rows):
  return [r for r in rows if "digital printing" in r[1].lower() or r[2] == "discovery_confirmed"]


def null_driver_rows(rows):
  return [r for r in rows if r[3] in (None, 0) or r[4] in (None, 0)]


def latch_answers(ops):
  return {c.get("label"): c.get("answer") for c in ((ops.get("stream_discovery") or {}).get("candidates") or [])}


def case_a(conn):
  print("\n=== CASE A (merged): 'already part of our commercial print line, not a separate thing' ===")
  cid, kid, msgs, ops0 = make_clone(conn, "sdcorva", 23, reset_latch=True, strip_phantom=True)
  try:
    rows0 = rows_of(ops0)
    print(f"  clone {cid} rewound to messages[:23]; rows: {json.dumps(rows0)}")
    check("A: clone starts with the two real lines, latch pending", len(rows0) == 2 and all(a is None for a in latch_answers(ops0).values()))
    check("A: last assistant is the ask", "before we wrap up operations" in msgs[-1]["content"].lower())
    src_msgs = json.loads(_fresh(conn, SOURCE_DRAFT, "messages_json"))
    reply23 = src_msgs[23]["content"]
    print(f"  > [23] {reply23}")
    status, reply, body = post_turn(cid, kid, reply23)
    print(f"  < [{status}] {reply[:900]}")
    check("A: answer turn 200", status == 200, str(status))
    ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
    rows = rows_of(ops)
    ans = latch_answers(ops)
    print("  rows:", json.dumps(rows))
    print("  latch:", json.dumps(ans))
    check("A: NO phantom line (no digital-printing row, no discovery_confirmed row)", not phantom_rows(rows), json.dumps(phantom_rows(rows)))
    check("A: model has 2 lines, not 3", len(rows) == 2, str(len(rows)))
    check("A: the two real lines untouched", [r for r in rows if r[1] != PHANTOM] == rows0, json.dumps(rows))
    check("A: latch records merged_into:<line> for digital printing", str(ans.get(PHANTOM) or "").startswith("merged_into:"), str(ans.get(PHANTOM)))
    check("A: latch records declined for the other three", all(ans.get(k) == "declined" for k in ans if k != PHANTOM), json.dumps(ans))
    low = reply.lower()
    check("A: receipt is honest - never 'is its own line'", "is its own line" not in low, reply[:200])
    check("A: receipt says it stays inside the existing line", "stays inside" in low, reply[:200])
    check("A: no capacity question for the phantom", "how many digital printing" not in low, reply[:200])
    check("A: no longer pending (never re-asked)", all(a is not None for a in ans.values()), json.dumps(ans))
  finally:
    cleanup(conn, cid)


def case_b(conn):
  print("\n=== CASE B (removed): 'Please drop that line' on a clone where the line WAS created ===")
  cid, kid, msgs, ops0 = make_clone(conn, "sdcorvb", 25, reset_latch=False, strip_phantom=False)
  try:
    rows0 = rows_of(ops0)
    print(f"  clone {cid} rewound to messages[:25] AS PERSISTED; rows: {json.dumps(rows0)}")
    check("B: clone starts WITH the phantom null-driver row (latch yes)", len(phantom_rows(rows0)) == 1 and latch_answers(ops0).get(PHANTOM) == "yes")
    src_msgs = json.loads(_fresh(conn, SOURCE_DRAFT, "messages_json"))
    reply25 = src_msgs[25]["content"]
    print(f"  > [25] {reply25}")
    status, reply, body = post_turn(cid, kid, reply25)
    print(f"  < [{status}] {reply[:900]}")
    check("B: drop turn 200", status == 200, str(status))
    ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
    rows = rows_of(ops)
    ans = latch_answers(ops)
    print("  rows:", json.dumps(rows))
    print("  latch:", json.dumps(ans))
    check("B: row REMOVED on the drop turn (not resurrected by carry-forward)", not phantom_rows(rows), json.dumps(phantom_rows(rows)))
    check("B: model has 2 lines", len(rows) == 2, str(len(rows)))
    check("B: latch records removed", ans.get(PHANTOM) == "removed", str(ans.get(PHANTOM)))
    check("B: receipt says it is dropped", "dropped" in reply.lower(), reply[:200])
    # Drive ops to finalize with the client's REAL later replies.
    # The client's REAL later replies (27 = advantage confirm, 29 = goal),
    # then a plain confirmation for any extra question the live flow asks
    # (the live consultant may re-confirm a price etc.), up to 6 turns.
    script = [src_msgs[27]["content"], src_msgs[29]["content"]]
    for n in range(6):
      if body.get("active_focus") and body.get("active_focus") != "ops":
        break
      msg = script.pop(0) if script else "Yes, that's right."
      print(f"  > [+{n}] {msg[:200]}")
      status, reply, body = post_turn(cid, kid, msg)
      print(f"  < [{status}] {reply[:500]}")
      check(f"B: turn +{n} 200", status == 200, str(status))
      ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
      rows = rows_of(ops)
      check(f"B: after turn +{n} the row is STILL gone (no resurrection at the next turn)", not phantom_rows(rows), json.dumps(rows))
    focus = _fresh(conn, cid, "active_focus")
    ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
    rows = rows_of(ops)
    ans = latch_answers(ops)
    print("  final focus:", focus, "rows:", json.dumps(rows), "latch:", json.dumps(ans))
    check("B: ops finalized -> handed off (focus advanced past ops)", str(focus) != "ops", str(focus))
    check("B: at finalize the row is NOT resurrected", not phantom_rows(rows), json.dumps(rows))
    check("B: NO null-driver row reaches the boundary", not null_driver_rows(rows), json.dumps(null_driver_rows(rows)))
    check("B: latch still records removed after finalize (auditable record survived)", ans.get(PHANTOM) == "removed", str(ans.get(PHANTOM)))
    check("B: two real lines intact with their drivers", sorted(r[1] for r in rows) == sorted(r[1] for r in rows0 if r[1] != PHANTOM), json.dumps(rows))
  finally:
    cleanup(conn, cid)


def main() -> int:
  which = (sys.argv[1] if len(sys.argv) > 1 else "AB").upper()
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  conn = get_mysql_connection()
  t0 = time.time()
  if "A" in which:
    case_a(conn)
  if "B" in which:
    case_b(conn)
  print(f"\n  ({time.time() - t0:.0f}s)")
  if FAILURES:
    print(f"RED: {len(FAILURES)} failing: {FAILURES}")
    return 1
  print("GREEN: live Corvid discovery clone(s) passed - merged stays inside, drop stays dropped, no phantom at the boundary")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
