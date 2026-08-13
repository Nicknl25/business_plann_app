"""CW-031 round 9 -- the LIVE half: drive the round-9 rules through the real
router and read the ARTIFACT, not the reply.

What offline cannot prove:

  L1  THE SEPARATION DOOR END TO END: a declared all-lines collapse, then the
      client takes the invitation up ("design consults should stay separate").
      Round 8's live proof showed the words landing and the state staying;
      now the row's group must CLEAR and the stale label must retire from the
      rows left behind.
  L2  THE ASK -> DECLARATION LOOP: rates stated across two messages complete
      uniformity at N=4. The net must STORE NOTHING and the reply must carry
      the ask; the client's "yes" on the next turn must arrive as a DECLARED
      all-lines group through the router's own emission.
  L3  F1, mini's exact wording: "Our blended direct-cost ratio is 0.44."
      Acceptable: the blend stores 0.44 (router patches the stated fraction),
      OR an honest no-record reply. Unacceptable: a reply that acknowledges
      0.44 while nothing stored it.
  L4  F1's second wording: "Please set cogs percent of revenue to 38."
      Same bar, meaning 0.38.

Every case is a FRESH clone of the real Ravenwood draft, live POSTs, and the
artifact read back with commit() FIRST (REPEATABLE READ shows stale state on a
long-lived connection otherwise).

  .venv\\Scripts\\python.exe "Test Files\\_live_cw031_round9_turns.py"
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
  clone_id = "r9" + uuid.uuid4().hex[:30]
  client_id = "R9" + uuid.uuid4().hex[:16].upper()
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


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made, bad = [], []

  def show(label, code, reply, fin, rows):
    print(f"  < [{code}] {reply[:420]}")
    print(f"  rows: {[(r['name'], r['pct'], r['group'], r['basis']) for r in rows]}")
    print(f"  fin : { {k: v for k, v in fin.items() if v is not None} }")

  try:
    # ---- L1: declared collapse, then separation --------------------------
    print("=" * 78)
    print("L1 separation clears the group (round 8's live gap)")
    d, c = clone(conn)
    made.append(d)
    code, reply = turn(d, c, "Honestly every one of our lines runs at about "
                             "55 percent for direct costs - treat them all "
                             "as one cost structure.")
    fin, rows = read_state(conn, d)
    show("L1-t1", code, reply, fin, rows)
    groups = {r["group"] for r in rows}
    if not (len(groups) == 1 and next(iter(groups))
            and {r["basis"] for r in rows} == {"declared"}):
      bad.append("L1-t1: declared all-lines collapse did not store")
    code, reply = turn(d, c, "Actually, design consults should stay separate "
                             "with their own rate - it's about 12 percent.")
    fin, rows = read_state(conn, d)
    show("L1-t2", code, reply, fin, rows)
    design = next((r for r in rows if "design" in str(r["name"]).lower()), None)
    others = [r for r in rows if "design" not in str(r["name"]).lower()]
    if design is None or design["group"] is not None:
      bad.append(f"L1-t2: design still carries group {design and design['group']!r}")
    if any(o["group"] for o in others):
      bad.append("L1-t2: stale label not retired from remaining rows "
                 f"({[(o['name'], o['group']) for o in others if o['group']]})")
    if design is not None and design["pct"] is not None \
       and abs(float(design["pct"]) - 0.12) > 0.001:
      bad.append(f"L1-t2: design rate {design['pct']} != 0.12 (wrong number)")

    # ---- L2: the ask -> declaration loop ---------------------------------
    print("=" * 78)
    print("L2 uniform rates ask, never store; a yes is the declaration")
    d, c = clone(conn)
    made.append(d)
    code, reply = turn(d, c, "Plant sales run about 55 percent in direct "
                             "costs, and hard goods are 55 percent too.")
    fin, rows = read_state(conn, d)
    show("L2-t1", code, reply, fin, rows)
    code, reply = turn(d, c, "Install projects are also 55 percent, and "
                             "design consults are 55 percent as well.")
    fin, rows = read_state(conn, d)
    show("L2-t2", code, reply, fin, rows)
    stored_groups = [r for r in rows if r["group"]]
    if stored_groups:
      bad.append(f"L2-t2: uniform completion STORED a group "
                 f"({[(r['name'], r['group'], r['basis']) for r in stored_groups]})")
    asked = "one shared cost structure" in reply
    if not asked:
      print("  NOTE: ask sentence not found in reply (checking next turn anyway)")
    code, reply = turn(d, c, "Yes - treat them all as one cost structure.")
    fin, rows = read_state(conn, d)
    show("L2-t3", code, reply, fin, rows)
    groups = {r["group"] for r in rows}
    bases = {r["basis"] for r in rows}
    if not (len(groups) == 1 and next(iter(groups)) and bases == {"declared"}):
      bad.append(f"L2-t3: the yes did not land as a declared all-lines group "
                 f"(groups={groups}, bases={bases})")
    if not asked:
      bad.append("L2-t2: the uniform-rate ask never reached the client")

    # ---- L3/L4: F1 -------------------------------------------------------
    for case_id, message, means in (
      ("L3", "Our blended direct-cost ratio is 0.44.", 0.44),
      ("L4", "Please set cogs percent of revenue to 38.", 0.38),
    ):
      print("=" * 78)
      print(f"{case_id} F1: a figure no receipt carries may not be acknowledged")
      d, c = clone(conn)
      made.append(d)
      before_fin, _ = read_state(conn, d)
      code, reply = turn(d, c, message)
      fin, rows = read_state(conn, d)
      show(case_id, code, reply, fin, rows)
      stored = fin.get("cogs_percent_of_revenue")
      was = before_fin.get("cogs_percent_of_revenue")
      landed = stored is not None and abs(float(stored) - means) <= 0.001
      unchanged = (stored is None) or (
        was is not None and abs(float(stored) - float(was)) < 1e-9)
      reply_l = reply.lower()
      echoes = any(tok in reply_l for tok in (
        f"{means:g}", f"{means * 100:g}%", f"{means * 100:g} percent",
        message.split()[-1].rstrip(".").lower()))
      honest = any(tok in reply_l for tok in (
        "haven't recorded", "wasn't able", "couldn't", "didn't record",
        "which field", "which line"))
      if landed:
        print(f"  VERDICT: stated fraction LANDED ({stored})")
      elif unchanged and honest:
        print("  VERDICT: honest no-record (acceptable; router did not patch)")
      elif unchanged and not echoes:
        print("  VERDICT: no claim, no write (acceptable)")
      else:
        bad.append(f"{case_id}: reply acknowledged the figure while storing "
                   f"nothing (stored={stored}, was={was}, reply={reply[:160]!r})")
      leaked = [k for k in ("cogs_per_line_overrides",
                            "cogs_shared_structure_groups", "cogs_separate_lines")
                if fin.get(k) is not None]
      if leaked:
        bad.append(f"{case_id}: transport key stored {leaked}")
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
    print("LIVE RESULT: RED")
    for b in bad:
      print(f"  - {b}")
    return 1
  print("LIVE RESULT: CLEAN (L1 separation, L2 ask->declaration, L3/L4 honest)")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
