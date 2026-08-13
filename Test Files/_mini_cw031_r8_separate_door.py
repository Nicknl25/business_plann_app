"""CW-031 round-8 mini audit -- item 1's decisive artifact: the inferred
collapse invites correction ("say so if any of them should be separate")
-- does that invitation HAVE a door?

Turn 1: rates for two lines at 55 percent (no collapse said).
Turn 2: rates for the other two at 55 percent (post-write net should mint an
        INFERRED all-lines group and speak the invitation).
Turn 3: the client takes the invitation up: design consult should be separate.
Read the rows after every turn: does anything remove or shrink the group?

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r8_separate_door.py"
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

TURNS = [
  "For direct costs: plant sales run about 55 percent of that line, and hard goods run about 55 percent as well.",
  "Install projects are about 55 percent too, and design consults also come in around 55 percent.",
  "Actually, design consults should stay separate with their own rate - don't lump them in with the other lines.",
]


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
        out.append((product.get("product_name"),
                    product.get("cogs_percent_of_line_revenue"),
                    product.get("cogs_cost_structure_group"),
                    product.get("cogs_cost_structure_group_basis")))
  return out


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  draft_id = "m8" + uuid.uuid4().hex[:30]
  client_id = "M8" + uuid.uuid4().hex[:16].upper()
  columns = [c for c in src.keys() if c != "id"]
  values = [(draft_id if c == "draft_id" else client_id if c == "client_id" else src[c])
            for c in columns]
  write = conn.cursor()
  write.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
    f"VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
  conn.commit()
  write.close()

  try:
    for i, message in enumerate(TURNS, 1):
      print("=" * 78)
      print(f"TURN {i}: {message}")
      resp = requests.post(
        f"{BASE_URL}/api/intake-consult",
        json={"draft_id": draft_id, "client_id": client_id, "message": message},
        timeout=300)
      body = resp.json() if resp.status_code == 200 else {}
      print(f"  < [{resp.status_code}] {str(body.get('assistant_message') or '')[:500]}")
      for row in read_rows(conn, draft_id):
        print(f"  row: {row}")
  finally:
    try:
      cur = conn.cursor()
      cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
      conn.commit()
      cur.close()
      print("  (clone removed)")
    except Exception:
      pass
    try:
      conn.close()
    except Exception:
      pass
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
