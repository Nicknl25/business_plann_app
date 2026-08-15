"""STREAM DISCOVERY - LIVE proof on rewound clones (the un-fakeable standard).

THE PRODUCTION CALL CHAIN (named first, per the E2E law):
  POST /api/intake-consult (focus=ops, the growth-lever answer = the last
  ops question before wrap)
    -> post_intake_consult_handler -> consultant_chat_turn (live GPT)
    -> _apply_model_ops_patch -> gate cascade (consultant_finalize snapshot)
    -> _ops_ready_for_wrap_from_gate_obj TRUE
    -> _stream_discovery_ask_if_due  [NEW: evidence gate -> ONE judge call
       -> validator -> template ask, latched]  -> holds the turn
  next POST (the client's answer)
    -> _apply_stream_discovery_answer [NEW: per-candidate read, Python
       appends the confirmed row w/ origin, receipt leads] -> continue_chat
    -> consultant_chat_turn -> carry_stream_discovery -> cascade asks the
       new row's numbers -> ... -> competitive advantage -> milestone ->
       consultant_finalize -> carry -> ops_json = final_obj -> market.

Clones of the REAL Thornfield draft d9b17850 (garden centre, 4 lines),
REWOUND to message [31] (the growth-lever answer, the turn that reached
the competitive-advantage proposal live), driven against the live :5050
backend and live GPT. Nothing is stubbed. The proof is the persisted
operating_model_json afterwards.

  A. RICH clone: expect the discovery ask (or a latched no-ask with a
     stored reason if the judge finds nothing common); on an ask, answer
     YES to the first candidate and drive the cascade to wrap; assert the
     row + origin + latch survive finalize and the draft reaches market.
  B. THIN clone (pre-revenue): NO ask, latched reason thin, and the
     competitive-advantage proposal fires exactly as today.

  .venv\\Scripts\\python.exe "Test Files\\_live_stream_discovery_clones.py"
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5050"
SOURCE_DRAFT = "d9b17850350545e9911fa09b3e333429"
CUT = 31  # messages[:31] -> the next POST is the growth-lever answer [31]

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


def read_ops(conn, draft_id):
  return json.loads(_fresh(conn, draft_id, "operating_model_json") or "{}")


def make_clone(conn, tag, *, pre_revenue=False):
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
  if pre_revenue:
    ops["business_stage"] = "pre-revenue"
  overrides = {
    "draft_id": clone_id,
    "client_id": client_id,
    "active_focus": "ops",
    "ops_confirmed": 0, "market_confirmed": 0, "people_confirmed": 0, "financials_confirmed": 0,
    "ops_finalize_proposed": 0, "market_finalize_proposed": 0, "people_finalize_proposed": 0,
    "financials_finalize_proposed": 0,
    "status": "in_progress",
    "completed_at": None, "submitted_at": None, "intake_submission_id": None,
    "messages_json": json.dumps(messages, ensure_ascii=False),
    "operating_model_json": json.dumps(ops, ensure_ascii=False),
    "target_market_json": None, "people_json": None, "financials_json": None,
    "financials_year1_json": None, "marketing_model_json": None,
    "pending_ops_milestone_json": None,
    "planning_run_id": None, "planning_run_status": None,
    "planning_stage": None, "planning_status": None,
  }
  if pre_revenue and "business_start_date" in src:
    overrides["business_start_date"] = "2027-03-01"
  columns = [c for c in src.keys() if c != "id"]
  values = [overrides.get(c) if c in overrides else src[c] for c in columns]
  cur = conn.cursor()
  cur.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
    tuple(values),
  )
  conn.commit()
  cur.close()
  return clone_id, client_id, messages


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


GROWTH_LEVER_ANSWER = (
  "Hiring a third install crew is the big one. And the other thing I want inside the next "
  "twelve months is to buy the two-acre parcel behind us and put up a heated propagation "
  "greenhouse so we grow more of our own stock instead of buying everything in. I'd want that "
  "greenhouse standing before the spring of the year after."
)


def auto_answer(question: str, label: str) -> str:
  # Route on the LAST question sentence only (receipts/acks precede it).
  qs = re.findall(r"[^.!?\n]*\?", question)
  q = (qs[-1] if qs else question).lower()
  full = question.lower()
  if "sets you apart" in q or ("competitive advantage" in full and "something else" in q):
    return "That's a fair read."
  if "competitive advantage" in q or "your edge" in q or "sound right" in q or "look right" in q:
    return "That's a fair read."
  if "12 months" in q or "milestone" in q or "concrete goal" in q:
    return "Buy the two-acre parcel behind us and have a heated propagation greenhouse standing on it within twelve months."
  if "utilization" in q or "utilisation" in q or "% of" in q or "percent of" in q:
    return "Call it 70%."
  if "turn over" in q or "turns per year" in q or "how many times" in q:
    return "About 4 turns a year."
  if "price" in q or "charge" in q or "cost" in q or "$" in q or "fee for" in q or "fee do" in q:
    return f"About $400 per {label} job."
  if "capacity" in q or "how many" in q or "per week" in q or "a week" in q or "orders" in q:
    return f"About 3 {label} jobs a week at full stretch."
  if "unit" in q or "cadence" in q or "measure" in q or "count" in q or "book" in q:
    return f"One {label} job at a time, booked weekly."
  if "monthly" in q or "weekly" in q:
    return "Weekly."
  return "Yes, that's right."


def run_rich(conn):
  print("\n=== A. RICH clone (operating garden centre, 4 lines) ===")
  cid, kid, _ = make_clone(conn, "sdrich")
  try:
    status, reply, body = post_turn(cid, kid, GROWTH_LEVER_ANSWER)
    print(f"  < [{status}] {reply[:400]}")
    check("A live turn 200", status == 200, str(status))
    ops = read_ops(conn, cid)
    latch = ops.get("stream_discovery") or {}
    tries = 0
    while "asked" not in latch and tries < 3 and status == 200:
      # GPT variance: the consultant sometimes asks its own last question
      # before declaring finalize-ready; the seam is reached on the next turn.
      tries += 1
      status, reply, body = post_turn(cid, kid, "Our edge is the integrated design-to-install flow and growing our own perennials.")
      print(f"  (seam not reached yet; +{tries}) < [{status}] {reply[:300]}")
      ops = read_ops(conn, cid)
      latch = ops.get("stream_discovery") or {}
    check("A latch written at the seam", bool(latch) and "asked" in latch, json.dumps(latch)[:300])
    print("  latch:", json.dumps(latch)[:600])
    if not latch.get("asked"):
      check("A no-ask is latched with a reason", bool(latch.get("reason")), json.dumps(latch))
      check("A no-ask => competitive advantage proposal fires as today",
            "competitive advantage" in reply.lower(), reply[:120])
      print("  (judge found nothing genuinely common for this business - the silence path; the "
            "propose->yes->capture path is exercised by the offline red-proof and awaits the Cowork run)")
      return
    from client_intake_and_finmo.intake_coherence import gpt_stream_discovery as sd  # type: ignore
    check("A reply IS the template ask", sd.is_stream_discovery_ask(reply), reply[:160])
    check("A ask lists exactly the latched candidates",
          reply == sd.compose_stream_discovery_ask(ops.get("business_type"), [c["label"] for c in latch["candidates"]]),
          reply)
    low = reply.lower()
    check("A forbidden-phrase grep on the emitted ask finds nothing",
          not any(p in low for p in sd.FORBIDDEN_ASK_PHRASES), low)
    check("A ask held the turn (no competitive advantage yet)", "competitive advantage" not in low)
    check("A NO row appended before the answer",
          not any(p.get("origin") for l in ops.get("lob_models") or [] for p in l.get("products") or []))
    labels = [c["label"] for c in latch["candidates"]]
    first = labels[0]
    n_rows_before = sum(len(l.get("products") or []) for l in ops.get("lob_models") or [])
    answer = f"Yes, {first} is part of it." + (" The others no." if len(labels) > 1 else "")
    status, reply, body = post_turn(cid, kid, answer)
    print(f"  > {answer}")
    print(f"  < [{status}] {reply[:700]}")
    check("A answer turn 200", status == 200, str(status))
    ops = read_ops(conn, cid)
    latch = ops.get("stream_discovery") or {}
    answers = {c["label"]: c.get("answer") for c in latch.get("candidates") or []}
    check("A latch stores yes for the named candidate", answers.get(first) == "yes", json.dumps(answers))
    check("A other candidates stored no (never re-asked)",
          all(v == "no" for k, v in answers.items() if k != first), json.dumps(answers))
    rows = [(l.get("lob_name"), p) for l in ops.get("lob_models") or [] for p in l.get("products") or []]
    disc = [(ln, p) for ln, p in rows if p.get("origin") == "discovery_confirmed"]
    check("A EXACTLY ONE row carries origin=discovery_confirmed", len(disc) == 1, json.dumps([(ln, p.get("product_name")) for ln, p in disc]))
    check("A the row is named for the label", disc and disc[0][1].get("product_name", "").lower() == first.lower(), disc and disc[0][1].get("product_name"))
    check("A row count grew by exactly one", len(rows) == n_rows_before + 1, f"{n_rows_before} -> {len(rows)}")
    check("A receipt LEADS the reply", reply.lower().startswith("noted -") and first.lower() in reply.lower()[:160], reply[:160])
    check("A reply asks the next question (no dead end)", "?" in reply)
    # drive to wrap
    adv_seen = 0
    ms_seen = 0
    for i in range(14):
      focus = _fresh(conn, cid, "active_focus")
      if focus and focus != "ops":
        break
      if "competitive advantage" in reply.lower():
        adv_seen += 1
      if "concrete goal" in reply.lower() or "12 months" in reply.lower():
        ms_seen += 1
      ans = auto_answer(reply, first)
      status, reply, body = post_turn(cid, kid, ans)
      print(f"  > {ans}")
      print(f"  < [{status}] {reply[:900]}")
      if status != 200:
        break
    focus = _fresh(conn, cid, "active_focus")
    ops = read_ops(conn, cid)
    check("A draft reached market (wrap clean)", focus == "market", str(focus))
    check("A competitive-advantage proposal fired exactly once after the ask resolved", adv_seen == 1, str(adv_seen))
    check("A milestone question asked (unchanged neighbor)", ms_seen >= 1, str(ms_seen))
    latch = ops.get("stream_discovery") or {}
    check("A latch SURVIVED finalize (ops_json = final_obj)", latch.get("asked") is True and latch.get("candidates"), json.dumps(latch)[:200])
    rows = [(l.get("lob_name"), p) for l in ops.get("lob_models") or [] for p in l.get("products") or []]
    disc = [(ln, p) for ln, p in rows if p.get("origin") == "discovery_confirmed"]
    check("A origin SURVIVED finalize on exactly one row", len(disc) == 1, json.dumps([(ln, p.get("product_name")) for ln, p in disc]))
    if disc:
      p = disc[0][1]
      print("  discovered row after finalize:", json.dumps(p))
      # Price + capacity are the client's own figures. Utilization is
      # PROPOSED-then-agreed by the existing ops prompt law for EVERY row
      # (intake_consultant.py 'Utilization handling') - a discovered row is
      # an ordinary row, so it is reported here, not pinned.
      check("A discovered row's price + capacity are the client's stated figures (400 / 3)",
            float(p.get("unit_price") or 0) == 400.0 and float(p.get("units_per_week_capacity") or p.get("units_per_period_capacity") or 0) == 3.0,
            json.dumps(p))
      print(f"  utilization on the discovered row (proposed-then-agreed, existing law): {p.get('utilization_rate')}")
    check("A stream_discovery_pending is False after wrap", not sd.stream_discovery_pending(ops))
    check("A the four original rows kept", len(rows) == n_rows_before + 1, str(len(rows)))
  finally:
    cleanup(conn, cid)


def run_thin(conn):
  print("\n=== B. THIN clone (pre-revenue) ===")
  cid, kid, _ = make_clone(conn, "sdthin", pre_revenue=True)
  try:
    status, reply, body = post_turn(cid, kid, GROWTH_LEVER_ANSWER)
    print(f"  < [{status}] {reply[:400]}")
    check("B live turn 200", status == 200, str(status))
    ops = read_ops(conn, cid)
    latch = ops.get("stream_discovery") or {}
    tries = 0
    while "asked" not in latch and tries < 3 and status == 200:
      tries += 1
      check(f"B no ask on the way to the seam (+{tries})", "before we wrap up operations: a lot of" not in reply.lower(), reply[:120])
      status, reply, body = post_turn(cid, kid, "Our edge is the integrated design-to-install flow and growing our own perennials.")
      print(f"  (seam not reached yet; +{tries}) < [{status}] {reply[:300]}")
      ops = read_ops(conn, cid)
      latch = ops.get("stream_discovery") or {}
    print("  latch:", json.dumps(latch))
    check("B NO ask (thin)", "before we wrap up operations: a lot of" not in reply.lower(), reply[:120])
    check("B latched asked:false reason:thin", latch.get("asked") is False and latch.get("reason") == "thin", json.dumps(latch))
    check("B thin reason names the stage", any("stage_not_discoverable" in r for r in (latch.get("evidence") or {}).get("reasons") or []), json.dumps(latch))
    check("B competitive-advantage proposal fires exactly as today", "competitive advantage" in reply.lower(), reply[:160])
    check("B no origin rows", not any(p.get("origin") for l in ops.get("lob_models") or [] for p in l.get("products") or []))
  finally:
    cleanup(conn, cid)


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  conn = get_mysql_connection()
  which = sys.argv[1] if len(sys.argv) > 1 else "both"
  if which in ("both", "thin"):
    run_thin(conn)
  if which in ("both", "rich"):
    run_rich(conn)
  print()
  if FAILURES:
    print(f"RED: {len(FAILURES)} failing: {FAILURES}")
    return 1
  print("GREEN: live stream-discovery clones passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
