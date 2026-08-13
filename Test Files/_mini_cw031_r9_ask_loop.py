"""mini, CW-031 round 9 audit, item 1: the ask -> declaration loop, attacked
on the answers VS did not prove. VS proved the YES; this drives the NO, the
PARTIAL, and the IGNORE through the live router with mini's own wordings and
reads the rows, never the replies.

  A. NO   - "keep every one of them separate" after the ask: nothing stored,
            nothing invented, rates unchanged.
  B. PART - "just plants and hard goods together, the rest on their own":
            the declared partial group stores (those two rows only, basis
            declared), the others stay ungrouped, and the NEXT write must not
            re-fire the ask (uniformity pre-existed the write).
  C. IGN  - the client answers something unrelated: rows stay ungrouped and
            _assert_ops_per_line_cogs fails them with the ask vocabulary
            (the held-question state), not a silent pass.

Fresh clone of the real Ravenwood draft per case; read-back commits first
(REPEATABLE READ trap).

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r9_ask_loop.py"
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
SOURCE_DRAFT = "1070c6a560a04f3d971019a3787180bf"

ASK_NEEDLE = "one shared cost structure"

_FIN_KEYS = ("cogs_percent_of_revenue", "cogs_basis", "current_cogs",
             "cogs_per_line_overrides", "cogs_shared_structure_groups",
             "cogs_separate_lines")


def read_state(conn, draft_id):
  try:
    conn.commit()
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute("SELECT financials_json, operating_model_json "
              "FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
  row = cur.fetchone()
  cur.close()
  fin = json.loads((row[0] if row else None) or "{}")
  ops = json.loads((row[1] if row else None) or "{}")
  rows = []
  for lob in ops.get("lob_models") or []:
    for product in (lob.get("products") or []):
      if isinstance(product, dict):
        rows.append({
          "name": product.get("product_name") or product.get("name"),
          "pct": product.get("cogs_percent_of_line_revenue"),
          "group": product.get("cogs_cost_structure_group"),
          "basis": product.get("cogs_cost_structure_group_basis"),
        })
  return {k: fin.get(k) for k in _FIN_KEYS}, rows


def clone(conn):
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  clone_id = "m9" + uuid.uuid4().hex[:30]
  client_id = "M9" + uuid.uuid4().hex[:16].upper()
  columns = [c for c in src.keys() if c != "id"]
  values = [(clone_id if c == "draft_id" else client_id if c == "client_id" else src[c])
            for c in columns]
  write = conn.cursor()
  write.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
    f"VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
  conn.commit()
  write.close()
  return clone_id, client_id


def turn(draft_id, client_id, message):
  resp = requests.post(
    f"{BASE_URL}/api/intake-consult",
    json={"draft_id": draft_id, "client_id": client_id, "message": message},
    timeout=300)
  body = resp.json() if resp.status_code == 200 else {}
  return resp.status_code, str(body.get("assistant_message") or "")


def uniform_setup(conn, d, c, show):
  """Two messages ending uniform at N=4; returns the t2 reply (must carry ask)."""
  code, reply = turn(d, c, "For costs: the plant side runs 52 percent of its "
                           "own sales, and hard goods runs 52 percent as well.")
  fin, rows = read_state(conn, d)
  show("t1", code, reply, fin, rows)
  code, reply = turn(d, c, "Install work is 52 percent too, and so is the "
                           "design side.")
  fin, rows = read_state(conn, d)
  show("t2", code, reply, fin, rows)
  return reply, fin, rows


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made, bad = [], []

  def show(label, code, reply, fin, rows):
    print(f"  {label} < [{code}] {reply[:360]}")
    print(f"  rows: {[(r['name'], r['pct'], r['group'], r['basis']) for r in rows]}")

  try:
    # ---- A: the NO ------------------------------------------------------
    print("=" * 78)
    print("A: 'no' after the ask stores nothing and invents nothing")
    d, c = clone(conn)
    made.append(d)
    reply, fin, rows = uniform_setup(conn, d, c, show)
    if ASK_NEEDLE not in reply:
      bad.append("A-t2: the uniform-rate ask never reached the client")
    if any(r["group"] for r in rows):
      bad.append(f"A-t2: uniform completion stored a group")
    code, reply = turn(d, c, "No - each line prices out on its own, keep "
                             "every one of them separate.")
    fin, rows = read_state(conn, d)
    show("A-t3", code, reply, fin, rows)
    if any(r["group"] or r["basis"] for r in rows):
      bad.append(f"A-t3: the NO stored a group "
                 f"({[(r['name'], r['group'], r['basis']) for r in rows if r['group'] or r['basis']]})")
    if any(r["pct"] is None or abs(float(r["pct"]) - 0.52) > 0.001 for r in rows):
      bad.append(f"A-t3: the NO changed a rate ({[(r['name'], r['pct']) for r in rows]})")
    leaked = [k for k in ("cogs_per_line_overrides", "cogs_shared_structure_groups",
                          "cogs_separate_lines") if fin.get(k) is not None]
    if leaked:
      bad.append(f"A-t3: transport key stored {leaked}")

    # ---- B: the PARTIAL -------------------------------------------------
    print("=" * 78)
    print("B: a partial answer stores the declared partial group; the next "
          "write does not re-ask")
    d, c = clone(conn)
    made.append(d)
    reply, fin, rows = uniform_setup(conn, d, c, show)
    if ASK_NEEDLE not in reply:
      bad.append("B-t2: the uniform-rate ask never reached the client")
    code, reply = turn(d, c, "Just put the plants and the hard goods together "
                             "- the other two stand on their own.")
    fin, rows = read_state(conn, d)
    show("B-t3", code, reply, fin, rows)
    grouped = [r for r in rows if r["group"]]
    g_names = sorted(str(r["name"]).lower() for r in grouped)
    if not (len(grouped) == 2
            and all("plant" in n or "hard" in n for n in g_names)
            and {r["basis"] for r in grouped} == {"declared"}):
      bad.append(f"B-t3: partial group wrong "
                 f"({[(r['name'], r['group'], r['basis']) for r in rows]})")
    if len({r["group"] for r in grouped}) != 1:
      bad.append("B-t3: partial group members carry different labels")
    # t4: a write that keeps the state uniform must NOT re-fire the ask
    code, reply = turn(d, c, "Actually, set install work to 52 percent - "
                             "keeping it where it is.")
    fin, rows = read_state(conn, d)
    show("B-t4", code, reply, fin, rows)
    if ASK_NEEDLE in reply:
      bad.append("B-t4: the ask RE-FIRED on a write into pre-existing uniformity")
    grouped_after = [(r["name"], r["group"], r["basis"]) for r in rows if r["group"]]
    if len(grouped_after) != 2:
      bad.append(f"B-t4: the follow-up write disturbed the declared partial "
                 f"group ({grouped_after})")

    # ---- C: the IGNORE --------------------------------------------------
    print("=" * 78)
    print("C: an unrelated answer leaves rows ungrouped; the assertion fails "
          "them with the ask vocabulary")
    d, c = clone(conn)
    made.append(d)
    reply, fin, rows = uniform_setup(conn, d, c, show)
    if ASK_NEEDLE not in reply:
      bad.append("C-t2: the uniform-rate ask never reached the client")
    code, reply = turn(d, c, "We also run a spring workshop series every "
                             "March, just so you know.")
    fin, rows = read_state(conn, d)
    show("C-t3", code, reply, fin, rows)
    if any(r["group"] or r["basis"] for r in rows):
      bad.append(f"C-t3: the ignore stored a group")
    if any(r["pct"] is None or abs(float(r["pct"]) - 0.52) > 0.001 for r in rows):
      bad.append(f"C-t3: the ignore changed a rate ({[(r['name'], r['pct']) for r in rows]})")
    # the artifact assertion on this held state
    import importlib
    ir = importlib.import_module("issue_registry")
    cur = conn.cursor()
    verdict = ir._assert_ops_per_line_cogs(cur, d, {})
    cur.close()
    print(f"  assertion: {verdict}")
    if verdict.get("verdict") != "fail":
      bad.append(f"C: assertion did not fail the held state ({verdict})")
    elif "the app asks" not in str(verdict.get("detail", "")):
      bad.append(f"C: assertion failed WITHOUT the ask vocabulary ({verdict})")
  finally:
    for draft_id in made:
      try:
        cur = conn.cursor()
        cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
        conn.commit()
        cur.close()
      except Exception:
        pass
    print(f"  ({len(made)} clone(s) removed)")
    try:
      conn.close()
    except Exception:
      pass

  print("=" * 78)
  if bad:
    print("ASK-LOOP RESULT: RED")
    for b in bad:
      print(f"  - {b}")
    return 1
  print("ASK-LOOP RESULT: CLEAN (no stores nothing, partial stores the "
        "declared two and never re-asks, ignore holds honestly)")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
