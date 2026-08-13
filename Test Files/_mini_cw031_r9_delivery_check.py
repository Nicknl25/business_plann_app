"""mini, CW-031 round 9 audit, item 5: the canary's delivery record.

  - workbook_deliveries row #4 exists for draft 3c56e7c57e5e4e6287d21c448d787b07
    (the round-9 Sunny_V3 canary) and carries a real file path.
  - resolve_workbook_for_draft returns basis='delivery record' for it.
  - table state printed in full (4 rows expected).

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r9_delivery_check.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from intake_submission import get_mysql_connection  # type: ignore
from workbook_delivery_record import resolve_workbook_for_draft  # type: ignore

CANARY_DRAFT = "3c56e7c57e5e4e6287d21c448d787b07"

conn = get_mysql_connection()
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT id, draft_id, planning_run_id, delivered_path, delivered_at "
            "FROM workbook_deliveries ORDER BY id")
rows = cur.fetchall()
print(f"workbook_deliveries rows: {len(rows)}")
for r in rows:
  print(f"  #{r[0]} draft={r[1]} run={r[2]} delivered={r[4]}")
  print(f"      path={r[3]}")

bad = []
canary = [r for r in rows if r[1] == CANARY_DRAFT]
if not canary:
  bad.append(f"no delivery record for canary draft {CANARY_DRAFT}")
else:
  path = canary[0][3]
  exists = Path(path).exists() if path else False
  print(f"canary row: #{canary[0][0]}, file exists on disk: {exists}")
  if not exists:
    bad.append(f"canary workbook path does not exist: {path}")

res = resolve_workbook_for_draft(cur, CANARY_DRAFT)
print(f"resolve_workbook_for_draft({CANARY_DRAFT[:8]}...): basis={res.get('basis')!r}")
print(f"  path={res.get('path')}")
print(f"  detail={res.get('detail')}")
if res.get("basis") != "delivery record":
  bad.append(f"basis is {res.get('basis')!r}, expected 'delivery record'")
if canary and res.get("path") != canary[0][3]:
  bad.append("resolver returned a different path than the delivery record")

cur.close()
conn.close()
print("=" * 78)
if bad:
  print("DELIVERY-CHECK RESULT: RED")
  for b in bad:
    print(f"  - {b}")
  raise SystemExit(1)
print("DELIVERY-CHECK RESULT: CLEAN")
