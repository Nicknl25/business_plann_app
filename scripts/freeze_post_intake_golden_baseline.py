from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
  sys.path.insert(0, str(PYTHON_ROOT))


def _git_short_sha() -> str:
  try:
    return subprocess.check_output(
      ["git", "rev-parse", "--short", "HEAD"],
      cwd=str(REPO_ROOT),
      text=True,
    ).strip()
  except Exception:
    return ""


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Freeze current post-intake lookup table contents into SQL."
  )
  parser.add_argument(
    "--baseline-name",
    default="post_intake_golden_f949316",
    help="Name stored in post_intake_lookup_table_snapshot.",
  )
  parser.add_argument(
    "--source-commit",
    default="",
    help="Commit/hash this lookup snapshot represents. Defaults to current HEAD.",
  )
  parser.add_argument(
    "--notes",
    default="Golden post-intake baseline after payroll/debt/depreciation schedules and lookup tables worked in E2E.",
  )
  args = parser.parse_args()

  from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
    post_intake_refresh_golden_lookup_snapshot,
  )

  snapshots = post_intake_refresh_golden_lookup_snapshot(
    baseline_name=args.baseline_name,
    source_commit=args.source_commit or _git_short_sha(),
    notes=args.notes,
  )
  print(json.dumps({"snapshot_rows": snapshots}, indent=2, sort_keys=True))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
