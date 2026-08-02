"""Print the draft_id of a LIVE persona intake (in_progress, touched <10 min,
no terminal planning run), or nothing. Used by start_persona_backend.ps1's
no-hot-patching guard: never restart the backend mid-run."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "python" / "client_intake_and_finmo"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")
from intake_submission import get_mysql_connection  # noqa: E402

conn = get_mysql_connection()
try:
  cur = conn.cursor()
  cur.execute(
    """
    SELECT d.draft_id FROM intake_consult_drafts d
    LEFT JOIN planning_runs r ON r.draft_id = d.draft_id
      AND r.started_at = (
        SELECT MAX(r2.started_at) FROM planning_runs r2 WHERE r2.draft_id = d.draft_id
      )
    WHERE d.status = 'in_progress'
      AND d.updated_at > NOW() - INTERVAL 10 MINUTE
      AND (r.planning_run_id IS NULL OR r.run_status = 'running')
    LIMIT 1
    """
  )
  row = cur.fetchone()
  if row and row[0]:
    print(str(row[0]))
finally:
  conn.close()
