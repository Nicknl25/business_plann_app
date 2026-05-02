from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
  sys.path.insert(0, str(PYTHON_ROOT))


def main() -> int:
  from client_intake_and_finmo.post_intake_foundation.golden_rule import (  # type: ignore
    post_intake_golden_rule_errors,
  )
  from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
    post_intake_golden_lookup_snapshot_rows,
    post_intake_process_sequence_rows,
  )

  errors = post_intake_golden_rule_errors()
  snapshot_rows = post_intake_golden_lookup_snapshot_rows()
  sequence_rows = post_intake_process_sequence_rows(active_only=True)
  payload = {
    "golden_rule_error_count": len(errors),
    "golden_rule_errors": errors,
    "lookup_snapshot_tables": [
      {
        "table_name": row.get("table_name"),
        "row_count": row.get("row_count"),
        "content_hash": row.get("content_hash"),
        "source_commit": row.get("source_commit"),
      }
      for row in snapshot_rows
    ],
    "active_process_steps": [
      {
        "step_key": row.get("step_key"),
        "step_order": row.get("step_order"),
        "contract_name": row.get("contract_name"),
        "required_lookup_tables": row.get("required_lookup_tables"),
        "horizon_rule": row.get("horizon_rule"),
      }
      for row in sequence_rows
    ],
  }
  print(json.dumps(payload, indent=2, sort_keys=True))
  if errors:
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
