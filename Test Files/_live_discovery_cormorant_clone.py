"""F1+F2+F3 LIVE spot-check: rewind-clone of the REAL Cormorant draft
(ec1e22ef, Coffee Roaster) to the end-of-ops seam, driven against the live
:5050 backend + live GPT judge. Records the discovery ask VERBATIM (label
grammar is a WATCH item) and the latch (survivors vs proposed vs dropped).

PRODUCTION CALL CHAIN: POST /api/intake-consult (focus=ops) ->
consultant_chat_turn -> gate cascade -> _ops_ready_for_wrap_from_gate_obj
-> _stream_discovery_ask_if_due (evidence -> ONE judge call -> validator
F1/F2/F3 -> template ask, latched) -> the ask holds the turn; next POST ->
_apply_stream_discovery_answer.

Clone = messages[:19] of ec1e22ef (the next POST is the client's real
growth-lever answer, message [19]); interim ops questions are answered
with the client's own real replies from the transcript. The clone is
deleted afterwards.

  .venv\\Scripts\\python.exe "Test Files\\_live_discovery_cormorant_clone.py"
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
SOURCE_DRAFT = "ec1e22ef2fda4beda467401770bfcfed"
CUT = 19
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
  return clone_id, client_id


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


# The client's REAL replies from ec1e22ef, in transcript order after [19].
REPLIES = [
  "Adding more wholesale accounts. That's where the volume is.",
  "That's about right. Bellingham and Whatcom mostly, a handful of Seattle accounts, and the online goes anywhere.",
  "Consistency, mostly. Cafes know the roast will taste the same in March as it did in September, and I'll answer the phone.",
  "I want to be at 360 bags a week average within twelve months. Right now we're around 300.",
]


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  conn = get_mysql_connection()
  cid, kid = make_clone(conn, "sdcorm")
  print(f"clone {cid} of {SOURCE_DRAFT[:8]} rewound to messages[:{CUT}]")
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
    print("\n  LATCH:", json.dumps(latch, indent=1))
    check("discovery ASKED live on the Cormorant clone (asked:true)", latch.get("asked") is True, json.dumps(latch)[:300])
    check("the ask rendered (template prefix present)", bool(ask_text), "")
    if ask_text:
      print("\n  ASK VERBATIM:\n  " + ask_text.replace("\n", "\n  "))
      low = ask_text.lower()
      check("ask is existence-framed", "part of your business today" in low)
      check("forbidden phrases absent", not any(p in low for p in ("consider", " add ", "expand", "could you also", "would you")), low[:200])
      import re as _re
      check("ask carries no digit (size stripped)", not _re.search(r"\d", ask_text[ask_text.lower().index(ASK_MARK):]))
    proposed = latch.get("proposed") or []
    survivors = [s.get("label") for s in latch.get("survivors") or []]
    reasons = {d.get("label"): d.get("reason") for d in latch.get("dropped") or []}
    print("  proposed:", proposed)
    print("  survivors:", survivors)
    print("  dropped:", json.dumps(reasons))
    check("proposed <= 4", 0 < len(proposed) <= 4, str(len(proposed)))
    check("proposed is a prefix-slice of survivors ordered most-first", proposed == [c["label"] for c in (
      [s for s in latch.get("survivors") or [] if s.get("commonality") == "most"]
      + [s for s in latch.get("survivors") or [] if s.get("commonality") != "most"])][:4], json.dumps(latch.get("survivors")))
    check("no proposed label carries a digit", not any(any(ch.isdigit() for ch in l) for l in proposed), json.dumps(proposed))
    check("no proposed label is a bare category-noun duplicate of the primary (wholesale/online stay deduped if judged)",
          not any(l in ("wholesale coffee beans", "online coffee bean sales") for l in proposed), json.dumps(proposed))
    if ask_text:
      status, reply, body = post_turn(cid, kid, "No, none of those. We just do the five pound wholesale bags.")
      print(f"\n  > No, none of those...\n  < [{status}] {reply[:500]}")
      ops = json.loads(_fresh(conn, cid, "operating_model_json") or "{}")
      latch2 = ops.get("stream_discovery") or {}
      answers = {c.get("label"): c.get("answer") for c in latch2.get("candidates") or []}
      print("  answers:", json.dumps(answers))
      check("answer path: every proposed label answered no", answers and all(v == "no" for v in answers.values()), json.dumps(answers))
      check("no origin rows written on a no", not any(p.get("origin") for l in ops.get("lob_models") or [] for p in l.get("products") or []))
  finally:
    cleanup(conn, cid)
  print()
  if FAILURES:
    print(f"RED: {len(FAILURES)} failing: {FAILURES}")
    return 1
  print("GREEN: live Cormorant discovery clone passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
