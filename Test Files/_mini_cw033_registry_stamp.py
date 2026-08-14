"""mini CW-033 item 6: stamp the A-113-family registry rows off-path.

Nick's retraction (2026-08-14) reclassified the A-113 family as OFF-PATH
BY DESIGN: post-stage per-line driver corrections are prevented and
redirected, never supported, so 'the correction never lands' is the
design working, not a bug. The rows still read open-blocker/open-major.

Mechanism: the registry's own human-override door (resolve_manually),
with the ruling and the live artifact in the note. --apply to write.
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

from client_intake_and_finmo import issue_registry  # noqa: E402
from intake_submission import get_mysql_connection  # noqa: E402

APPLY = "--apply" in sys.argv

NOTE = (
    "A-113 retracted by Nick 2026-08-14 (guided-flow / forward-only law): "
    "post-stage per-line driver corrections are OFF-PATH - prevented and "
    "redirected, never supported. 'Never lands' is the design working. "
    "Mid-interview redirect + zero-write proven live: "
    "_live_cw033_20260814.txt (VS L1-L4) and "
    "_mini_cw033_t1_live2_20260814.txt (mini A4b: redirect leads, price "
    "unchanged). Off-path/observation stamp per HANDOFF task item 6."
)

conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT issue_id, signature, category, severity, status, resolution_class, "
    "resolution_basis, resolution_confidence FROM issues "
    "WHERE signature LIKE %s OR signature LIKE %s",
    ("%capacity_correction_after_stage_close_never_lands%",
     "%ack_claims_a_capacity_write%"))
rows = cur.fetchall()
cur.close()
print(f"matched {len(rows)} rows:")
for r in rows:
    print(" ", json.dumps({k: str(v) for k, v in r.items()}))

if not APPLY:
    print("\nDRY RUN - rerun with --apply to stamp")
    conn.close()
    sys.exit(0)

for r in rows:
    if str(r["status"]) not in ("open", "recurring"):
        print(f"skip {r['signature']}: status={r['status']}")
        continue
    # mini's adjudication: ONLY #264 ('never lands') is off-path-by-design.
    # #132 is an HONESTY row (ack claims a write that did not happen) -
    # always in scope, and mini's A4b artifact (2026-08-14) shows the class
    # live as a price variant on the interview path. It stays open.
    if "ack_claims" in str(r["signature"]):
        print(f"KEPT OPEN (honesty row, class recurred live): {r['signature']}")
        continue
    out = issue_registry.resolve_manually(
        conn, signature=str(r["signature"]), note=NOTE)
    print(f"stamped {r['signature']}: status={out.get('status')} "
          f"basis={out.get('resolution_basis')} "
          f"confidence={out.get('resolution_confidence')}")

# verify
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT signature, status, resolution_basis, resolution_confidence "
    "FROM issues WHERE signature LIKE %s OR signature LIKE %s",
    ("%capacity_correction_after_stage_close_never_lands%",
     "%ack_claims_a_capacity_write%"))
for r in cur.fetchall():
    print("VERIFY:", json.dumps({k: str(v) for k, v in r.items()}))
cur.close()
conn.close()
