"""CW-031 round-7 mini audit -- ITEM 2, THE CLASS BEYOND THE LEAF NAME.

VS closed 1b by hiding two leaf names from the receipt and asked whether the
class has other members: "any patch key that carries a client figure in a unit
the stored field does not use, on any door."

It does, and it is one field family over. financials.cogs_percent_of_revenue is
the BLENDED direct-cost rate -- the number the engine consumes when cogs_basis
is "ratio", which is Ravenwood's own basis. Its unit is never declared:

  stage door       intake_consult.py:7890  _normalize_ratio_like -> divides by
                   100 only when the figure exceeds 1.0. That is the exact rule
                   round 7 deleted from the per-line door, still live here.
  correction door  intake_consult.py:11858 next_financials[field] = value, with
                   no conversion at all. cogs_percent_of_revenue is not in
                   _RECALC_DERIVED_FINANCIALS_FIELDS, so the raw router figure
                   is what gets stored.

This drives both doors LIVE with the wording that separates the readings and
reads the stored artifact.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r7_blend_unit.py"
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

CASES = [
  {
    "id": "L1",
    "message": ("Across the whole business, our direct costs come to about "
                "1 percent of revenue."),
    "means": 0.01,
    "why": "the small-percent reading the magnitude rule gets backwards",
  },
  {
    "id": "L2",
    "message": ("Company-wide, direct costs are about 71 percent of revenue."),
    "means": 0.71,
    "why": "a large percent -- the reading the magnitude rule gets right",
  },
]


def read_fin(conn, draft_id):
  try:
    conn.commit()
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute("SELECT financials_json FROM intake_consult_drafts WHERE draft_id=%s",
              (draft_id,))
  row = cur.fetchone()
  cur.close()
  fin = json.loads((row[0] if row else None) or "{}")
  return {k: fin.get(k) for k in
          ("cogs_percent_of_revenue", "cogs_basis", "current_cogs", "cogs_total_year1")}


def clone(conn):
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  clone_id = "mini" + uuid.uuid4().hex[:28]
  client_id = "MINI" + uuid.uuid4().hex[:14].upper()
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


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made, rows = [], []
  try:
    for case in CASES:
      draft_id, client_id = clone(conn)
      made.append(draft_id)
      before = read_fin(conn, draft_id)
      print("=" * 78)
      print(f"{case['id']}  {case['why']}")
      print(f"  clone {draft_id[:16]}   before: {before}")
      print(f"  > {case['message']}")
      resp = requests.post(
        f"{BASE_URL}/api/intake-consult",
        json={"draft_id": draft_id, "client_id": client_id, "message": case["message"]},
        timeout=300)
      body = resp.json() if resp.status_code == 200 else {}
      print(f"  < [{resp.status_code}] {str(body.get('assistant_message') or '')[:300]}")
      after = read_fin(conn, draft_id)
      print(f"  after : {after}")
      stored = after.get("cogs_percent_of_revenue")
      verdict = "UNCHANGED"
      if stored != before.get("cogs_percent_of_revenue"):
        verdict = "CORRECT" if stored is not None and abs(float(stored) - case["means"]) < 1e-6 \
          else f"WRONG-NUMBER (meant {case['means']}, stored {stored})"
      print(f"  VERDICT: {verdict}\n")
      rows.append((case["id"], verdict, before.get("cogs_percent_of_revenue"), stored))
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
  for case_id, verdict, before, after in rows:
    print(f"  {case_id}: {verdict:<40} {before} -> {after}")
  return 1 if any("WRONG" in r[1] for r in rows) else 0


if __name__ == "__main__":
  raise SystemExit(main())
