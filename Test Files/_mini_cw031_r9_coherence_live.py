"""mini, CW-031 round 9 audit, item 2 (live half): two disjoint DECLARED
groups on a real Ravenwood clone; separating one member of one group must
leave the other group byte-identical.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r9_coherence_live.py"
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
SOURCE_DRAFT = "1070c6a560a04f3d971019a3787180bf"


def read_rows(conn, draft_id):
  try:
    conn.commit()
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute("SELECT operating_model_json FROM intake_consult_drafts "
              "WHERE draft_id=%s", (draft_id,))
  row = cur.fetchone()
  cur.close()
  ops = json.loads((row[0] if row else None) or "{}")
  out = []
  for lob in ops.get("lob_models") or []:
    for product in (lob.get("products") or []):
      if isinstance(product, dict):
        out.append({
          "name": product.get("product_name") or product.get("name"),
          "pct": product.get("cogs_percent_of_line_revenue"),
          "group": product.get("cogs_cost_structure_group"),
          "basis": product.get("cogs_cost_structure_group_basis"),
        })
  return out


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


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made, bad = [], []
  try:
    d, c = clone(conn)
    made.append(d)
    code, reply = turn(d, c, "Plants and hard goods are both bought-in retail "
                             "- they share one cost structure at 52 percent.")
    rows = read_rows(conn, d)
    print(f"t1 < [{code}] {reply[:300]}")
    print(f"  rows: {[(r['name'], r['pct'], r['group'], r['basis']) for r in rows]}")
    code, reply = turn(d, c, "Install and design share a different structure "
                             "between just the two of them - both run 20 "
                             "percent.")
    rows = read_rows(conn, d)
    print(f"t2 < [{code}] {reply[:300]}")
    print(f"  rows: {[(r['name'], r['pct'], r['group'], r['basis']) for r in rows]}")
    g1 = [r for r in rows if r["group"] and "plant" in str(r["group"])]
    g2 = [r for r in rows if r["group"] and "install" in str(r["group"])
          and "plant" not in str(r["group"])]
    if len(g1) != 2 or len(g2) != 2:
      bad.append(f"setup: two disjoint groups not established "
                 f"({[(r['name'], r['group']) for r in rows]})")
    g2_before = copy.deepcopy(sorted(g2, key=lambda r: str(r["name"])))
    code, reply = turn(d, c, "Break the plants out of that grouping - plant "
                             "sales stand alone now.")
    rows = read_rows(conn, d)
    print(f"t3 < [{code}] {reply[:340]}")
    print(f"  rows: {[(r['name'], r['pct'], r['group'], r['basis']) for r in rows]}")
    plant = next((r for r in rows if "plant" in str(r["name"]).lower()), None)
    hard = next((r for r in rows if "hard" in str(r["name"]).lower()), None)
    g2_after = sorted((r for r in rows if r["name"] in
                       {x["name"] for x in g2_before}), key=lambda r: str(r["name"]))
    if plant is None or plant["group"] is not None:
      bad.append(f"t3: plant still grouped ({plant})")
    if hard is not None and hard["group"] is not None:
      bad.append(f"t3: hard goods kept a label whose membership is gone ({hard})")
    if g2_after != g2_before:
      bad.append(f"t3: THE OTHER GROUP CHANGED ({g2_before} -> {g2_after})")
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
    print("COHERENCE-LIVE RESULT: RED")
    for b in bad:
      print(f"  - {b}")
    return 1
  print("COHERENCE-LIVE RESULT: CLEAN (the untouched group survived "
        "byte-identical)")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
