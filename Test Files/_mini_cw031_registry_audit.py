"""CW-031 tier-1 mini audit: read the registry's own tables, trust nothing.

Answers Nick's check 2 (the demotion did not rewrite history) and gathers the
census the RESULT quotes. Read-only: every statement here is a SELECT.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  cur = conn.cursor()

  print("== A. confidence_demoted events ==")
  cur.execute(
    """SELECT COUNT(*), COUNT(DISTINCT issue_id), MIN(created_at), MAX(created_at)
       FROM issue_resolution_events WHERE event_type='confidence_demoted'""")
  print("  count/distinct_issues/first/last:", cur.fetchone())

  print("\n== B. the demoted issues' CURRENT state ==")
  cur.execute(
    """SELECT i.status, i.resolution_basis, i.resolution_confidence, COUNT(*)
       FROM issues i
       WHERE i.issue_id IN (SELECT issue_id FROM issue_resolution_events
                            WHERE event_type='confidence_demoted')
       GROUP BY 1,2,3 ORDER BY 4 DESC""")
  for r in cur.fetchall():
    print("  ", r)

  print("\n== C. does each demotion event record the BEFORE state, and does the")
  print("      recorded before-status/basis match the row's status/basis today? ==")
  cur.execute(
    """SELECT e.issue_id, e.detail_json, i.status, i.resolution_basis, i.resolution_confidence
       FROM issue_resolution_events e JOIN issues i ON i.issue_id=e.issue_id
       WHERE e.event_type='confidence_demoted'""")
  rows = cur.fetchall()
  basis_changed = []
  status_changed = []
  conf_still_confirmed = []
  no_before = []
  for issue_id, detail, status, basis, conf in rows:
    try:
      d = json.loads(detail) if detail else {}
    except Exception:
      d = {}
    before_basis = d.get("resolution_basis") or d.get("basis_before") or d.get("basis")
    before_status = d.get("status") or d.get("status_before")
    if before_basis is None and before_status is None:
      no_before.append(issue_id)
    if before_basis is not None and str(before_basis) != str(basis):
      basis_changed.append((issue_id, before_basis, basis))
    if before_status is not None and str(before_status) != str(status):
      status_changed.append((issue_id, before_status, status))
    if str(conf) == "confirmed":
      conf_still_confirmed.append(issue_id)
  print(f"  demoted rows examined: {len(rows)}")
  print(f"  events with NO before-state recorded: {len(no_before)} {no_before[:6]}")
  print(f"  basis differs from recorded before: {len(basis_changed)} {basis_changed[:6]}")
  print(f"  status differs from recorded before: {len(status_changed)} {status_changed[:6]}")
  print(f"  still 'confirmed' after demotion: {len(conf_still_confirmed)} {conf_still_confirmed[:6]}")
  if rows:
    print("  sample detail:", rows[0][1])

  print("\n== D. pre-existing resolved_confirmed audit rows still present? ==")
  cur.execute(
    """SELECT event_type, COUNT(*), MIN(created_at), MAX(created_at)
       FROM issue_resolution_events GROUP BY event_type ORDER BY 2 DESC""")
  for r in cur.fetchall():
    print("  ", r)

  print("\n== E. resolved_confirmed events whose issue was demoted (history kept?) ==")
  cur.execute(
    """SELECT COUNT(*) FROM issue_resolution_events
       WHERE event_type='resolved_confirmed'
         AND issue_id IN (SELECT issue_id FROM issue_resolution_events
                          WHERE event_type='confidence_demoted')""")
  print("   resolved_confirmed rows on demoted issues:", cur.fetchone()[0])

  print("\n== F. current confidence census across ALL issues ==")
  cur.execute(
    """SELECT status, resolution_basis, resolution_confidence, COUNT(*)
       FROM issues GROUP BY 1,2,3 ORDER BY 4 DESC""")
  for r in cur.fetchall():
    print("  ", r)

  print("\n== G. issues still carrying confirmed ==")
  cur.execute(
    """SELECT issue_id, resolution_basis, LEFT(signature,70) FROM issues
       WHERE resolution_confidence='confirmed'""")
  for r in cur.fetchall():
    print("  ", r)

  cur.close()
  conn.close()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
