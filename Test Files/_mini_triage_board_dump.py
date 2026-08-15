"""mini TRIAGE TURN (2026-08-14): dump the open board for the triage buckets.

Read-only. Lists every issues row not in a terminal-resolved state, plus
the owner_draw_ceiling row verbatim, so the triage file can cite the
registry as it stands.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from intake_submission import get_mysql_connection  # noqa: E402

conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT issue_id, signature, category, severity, status, "
    "resolution_class, resolution_basis, resolution_confidence "
    "FROM issues WHERE status NOT IN ('resolved') "
    "ORDER BY severity, signature")
rows = cur.fetchall()
print(f"NON-RESOLVED ROWS: {len(rows)}")
for r in rows:
    print(" ", json.dumps({k: str(v) for k, v in r.items()}, ensure_ascii=False))

print()
cur.execute("SHOW COLUMNS FROM issues")
cols = [r["Field"] for r in cur.fetchall()]
print("COLUMNS:", cols)

print()
cur.execute("SELECT * FROM issues WHERE signature LIKE %s", ("%owner_draw_ceiling%",))
for r in cur.fetchall():
    print("OWNER_DRAW_CEILING ROW:")
    print(json.dumps({k: str(v) for k, v in r.items()}, ensure_ascii=False, indent=2))

print()
cur.execute("SELECT COUNT(*) AS n, status FROM issues GROUP BY status")
for r in cur.fetchall():
    print("STATUS COUNT:", r["status"], r["n"])
cur.close()
conn.close()
