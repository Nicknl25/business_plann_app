"""Standalone resolution-sensing pass over the shared issue database.

Normally this runs automatically inside persona_run_vitals_finalize.py after
every watched persona run. This CLI exists for manual passes: re-evaluating
a specific past run, or sweeping the latest N completed runs after a fix
lands via a non-persona path (e.g. an intake-bypass canary).

  .venv\\Scripts\\python.exe scripts\\issue_resolution_check.py --draft-id <id>
  .venv\\Scripts\\python.exe scripts\\issue_resolution_check.py --latest 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv) -> int:
  parser = argparse.ArgumentParser(description="Evaluate issue resolution against completed runs.")
  parser.add_argument("--draft-id", default="", help="Evaluate this specific run.")
  parser.add_argument("--latest", type=int, default=0,
                      help="Evaluate the latest N completed planning runs instead.")
  parser.add_argument("--hard-clean-threshold", type=int, default=None)
  parser.add_argument("--soft-runs-threshold", type=int, default=None)
  args = parser.parse_args(argv)

  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  from client_intake_and_finmo import issue_registry  # type: ignore

  kwargs = {}
  if args.hard_clean_threshold is not None:
    kwargs["hard_clean_threshold"] = args.hard_clean_threshold
  if args.soft_runs_threshold is not None:
    kwargs["soft_runs_threshold"] = args.soft_runs_threshold

  draft_ids = []
  conn = get_mysql_connection()
  try:
    if args.draft_id.strip():
      draft_ids = [args.draft_id.strip()]
    elif args.latest > 0:
      cur = conn.cursor()
      try:
        cur.execute(
          """
          SELECT draft_id FROM planning_runs
          WHERE run_status = 'completed'
          ORDER BY completed_at DESC LIMIT %s
          """,
          (args.latest,),
        )
        draft_ids = [str(r[0]) for r in cur.fetchall()]
      finally:
        cur.close()
    else:
      parser.error("pass --draft-id or --latest N")
    for draft_id in draft_ids:
      summary = issue_registry.evaluate_run_for_resolution(
        conn, draft_id=draft_id, **kwargs
      )
      print(json.dumps(summary, ensure_ascii=False, default=str), flush=True)
  finally:
    try:
      conn.close()
    except Exception:
      pass
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
