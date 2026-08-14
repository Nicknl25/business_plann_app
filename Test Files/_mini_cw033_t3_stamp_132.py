"""mini CW-033 turn 4, task item 6: close #132 on the artifact read of M1.

#132 (ack_claims_a_capacity_write) is the honesty row: a reply claims an
ops write the turn did not make. Turn 3's M1 fix landed four gates; this
turn's adversarial live audit attacked the seams with fresh wordings and
the class held on every turn - no reply claimed a write or receipted an
unlanded figure (A1 redirect+stage-answer, A2 parse-fail, A4 no-op
restatement, B1 volunteered first-capture, B2 volunteered utilization:
_mini_cw033_t3_live_20260814.txt). The rule is pinned permanently as gate
leg R44 (proven behavioural at 6d38c54). Stamp via the registry's own
human-override door. --apply to write.
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
    "CW-033 M1 fixed (02effe1) and artifact-audited by mini turn 4: five "
    "adversarial live turns with fresh wordings (redirect+stage-answer, "
    "figure-parse fail, no-op restatement, volunteered first-capture, "
    "volunteered utilization) - zero replies claimed an unmade write or "
    "receipted an unlanded figure; rows read back untouched "
    "(_mini_cw033_t3_live_20260814.txt A1/A2/A4/B1/B2). Rule pinned as "
    "gate leg R44 (reply-never-acks-unlanded-ops-figure), proven "
    "behavioural red at 6d38c54 / green at 02effe1."
)

conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT issue_id, signature, category, severity, status, "
    "resolution_class, resolution_basis, resolution_confidence FROM issues "
    "WHERE signature LIKE %s", ("%ack_claims_a_capacity_write%",))
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
    out = issue_registry.resolve_manually(
        conn, signature=str(r["signature"]), note=NOTE)
    print(f"stamped {r['signature']}: status={out.get('status')} "
          f"basis={out.get('resolution_basis')} "
          f"confidence={out.get('resolution_confidence')}")

cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT signature, status, resolution_basis, resolution_confidence "
    "FROM issues WHERE signature LIKE %s", ("%ack_claims_a_capacity_write%",))
for r in cur.fetchall():
    print("VERIFY:", json.dumps({k: str(v) for k, v in r.items()}))
cur.close()
conn.close()
