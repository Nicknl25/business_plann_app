from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
  sys.path.insert(0, str(PYTHON_ROOT))

from client_intake_and_finmo.app_agents.validation import evaluate_app_agents_run  # noqa: E402


def _load_json(path: Path) -> dict:
  return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Validate an app_agents_run_json payload.")
  parser.add_argument("--shared-context", required=True, help="Path to shared context JSON")
  parser.add_argument("--run-payload", required=True, help="Path to app_agents_run_json payload")
  parser.add_argument("--scenario-id", default="manual", help="Scenario label for the validation result")
  args = parser.parse_args(argv)

  shared_context = _load_json(Path(args.shared_context))
  run_payload = _load_json(Path(args.run_payload))
  result = evaluate_app_agents_run(
    scenario_id=str(args.scenario_id or "manual"),
    shared_context=shared_context,
    app_agents_run_json=run_payload,
  )
  print(json.dumps(result, indent=2, ensure_ascii=False))
  return 0 if bool(result.get("overall_pass")) else 1


if __name__ == "__main__":
  raise SystemExit(main())

