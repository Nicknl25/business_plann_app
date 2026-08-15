"""LIVE spot-check for HANDOFF turn 1 (LOB nesting + serial comma):
rewind-clone of the REAL Nine Fathom draft (6d2823db, Coffee Roaster) to
the end-of-ops seam, driven against the live :5050 backend + live GPT judge.

PRODUCTION CALL CHAIN: POST /api/intake-consult (focus=ops) ->
consultant_chat_turn -> gate cascade -> _ops_ready_for_wrap_from_gate_obj
-> _stream_discovery_ask_if_due (judge -> validator -> compose_stream_
discovery_ask/join_labels -> latched ask) -> next POST -> _apply_stream_
discovery_answer -> append_confirmed_stream_rows (OWN LOB per stream).

Clone = messages[:23] of 6d2823db (message [23] is the client's real
growth-lever answer, the turn that fired the ask live). Discovered rows and
the latch are stripped from the cloned ops so discovery runs fresh. The
judge is live GPT so the proposed labels may differ from run #2; the
checks are shape checks: serial comma iff 3+ labels; every yes -> its OWN
LOB named for the label; primary row/drivers untouched. Clone deleted after.

  .venv\\Scripts\\python.exe "Test Files\\_live_discovery_ninefathom_clone.py"
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
SOURCE_DRAFT = "6d2823db268d483bbb4c8be8c627dc26"
CUT = 23
ASK_MARK = "before we wrap up operations: a lot of"
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
  messages = json.loads(src["messages_json"] or "[]")[:CUT]
  ops = json.loads(src["operating_model_json"] or "{}")
  for k in ("competitive_advantage", "milestones", "primary_growth_lever", "stream_discovery"):
    ops.pop(k, None)
  # strip the discovered rows so discovery runs fresh on the primary line only
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
  return clone_id, client_id, ops


def post_turn(clone_id, client_id, message):
  resp = requests.post(
    f"{BASE_URL}/api/intake-consult",
    json={"draft_id": clone_id, "client_id": client_id, "message": message},
    timeout=420,
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


# The client's REAL replies from 6d2823db, in transcript order from [23].
REPLIES = [
  "Finding more orders to fill the roaster I've already got. The machine isn't the problem, the accounts are.",
  "Consistency, mostly. Cafes know the roast will taste the same in March as it did in September, and I'll answer the phone.",
  "I want to be at 360 bags a week average within twelve months.",
]


def rows_of(ops):
  return [(str(l.get("lob_name")), str(p.get("product_name")), p.get("origin"),
           p.get("unit_price"), p.get("units_per_week_capacity"), p.get("utilization_rate"))
          for l in ops.get("lob_models") or [] for p in l.get("products") or []]


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  conn = get_mysql_connection()
  cid, kid, ops0 = make_clone(conn, "sdnine")
  rows0 = rows_of(ops0)
  print(f"clone {cid} of {SOURCE_DRAFT[:8]} rewound to messages[:{CUT}]")
  print("  primary rows:", json.dumps(rows0))
  check("clone starts with the primary line only", len(rows0) == 1 and rows0[0][1] == "5 lb bag roasted coffee")
  ask_text = None
  latch = {}
  try:
    for i, msg in enumerate(REPLIES):
      print(f"\n  > [{CUT + 2 * i}] {msg}")
      status, reply, body = post_turn(cid, kid, msg)
      print(f"  < [{status}] {reply[:700]}")
      check(f"turn {i} 200", status == 200, str(status))
      ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
      latch = ops.get("stream_discovery") or {}
      if ASK_MARK in reply.lower():
        ask_text = reply
        break
      if "asked" in latch:
        break
    check("discovery ASKED live on the Nine Fathom clone (asked:true)", latch.get("asked") is True, json.dumps(latch)[:300])
    check("the ask rendered (template prefix present)", bool(ask_text), "")
    proposed = list(latch.get("proposed") or [])
    print("  proposed:", proposed)
    if ask_text:
      print("\n  ASK VERBATIM:\n  " + ask_text.replace("\n", "\n  "))
      low = ask_text.lower()
      check("forbidden phrases absent", not any(p in low for p in ("consider", " add ", "expand", "could you also", "would you")), low[:200])
      check("revenue-line clause present", "include it as a revenue line" in low)
      if len(proposed) >= 3:
        expected = ", ".join(proposed[:-1]) + ", or " + proposed[-1]
        check("3+ labels: SERIAL COMMA rendered live (A, B, or C)", expected in ask_text, expected)
      elif len(proposed) == 2:
        check("2 labels: A or B (no comma)", (proposed[0] + " or " + proposed[1]) in ask_text and ", or " not in ask_text)
      else:
        check("1 label renders bare", bool(proposed) and proposed[0] in ask_text)
    if ask_text and proposed:
      yes = proposed[:2]
      no = proposed[2:]
      reply_txt = "Yes, we do " + " and we do ".join(yes) + "."
      if no:
        reply_txt += " No, we don't do " + " or ".join(no) + "."
      status, reply, body = post_turn(cid, kid, reply_txt)
      print(f"\n  > {reply_txt}\n  < [{status}] {reply[:600]}")
      check("answer turn 200", status == 200, str(status))
      ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
      latch2 = ops.get("stream_discovery") or {}
      answers = {c.get("label"): c.get("answer") for c in latch2.get("candidates") or []}
      print("  answers:", json.dumps(answers))
      rows = rows_of(ops)
      print("  rows:", json.dumps(rows))
      confirmed = [l for l, a in answers.items() if a == "yes"]
      check("at least one yes landed (reader read the yes)", len(confirmed) >= 1, json.dumps(answers))
      for label in confirmed:
        hits = [r for r in rows if r[1] == label]
        check(f"[{label}] -> exactly one row, origin=discovery_confirmed", len(hits) == 1 and hits[0][2] == "discovery_confirmed", json.dumps(hits))
        check(f"[{label}] -> its OWN LOB named for the label (never nested)", bool(hits) and hits[0][0] == label, hits[0][0] if hits else "")
      lob_names = {r[0] for r in rows}
      check("no LOB carries two discovered rows", all(sum(1 for r in rows if r[0] == ln and r[2] == "discovery_confirmed") <= 1 for ln in lob_names), json.dumps(rows))
      declined = [l for l, a in answers.items() if a != "yes"]
      check("no row landed for a declined label", not any(r[1] in declined for r in rows), json.dumps(rows))
      prim = [r for r in rows if r[1] == "5 lb bag roasted coffee"]
      check("primary row untouched (LOB + drivers 58/380/.75)", prim == [rows0[0]], json.dumps(prim))
      check("receipt says its own line and never under <line>", "is its own line;" in reply and " own line under " not in reply, reply[:300])
  finally:
    cleanup(conn, cid)
  print()
  if FAILURES:
    print(f"RED: {len(FAILURES)} failing: {FAILURES}")
    return 1
  print("GREEN: live Nine Fathom discovery clone passed (own LOB per stream + serial comma)")
  return 0


if __name__ == "__main__":
  sys.exit(main())
