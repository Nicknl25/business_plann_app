from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import LoopConfig
from .orchestrator import OrchestratorAgent
from .utils import repo_root_from_here


def main() -> int:
  parser = argparse.ArgumentParser(description="Dev-only planning helper agents.")
  parser.add_argument("--command", required=True, help="PowerShell command to run the planning test.")
  parser.add_argument("--max-iterations", type=int, default=3, help="Bounded loop count, usually 3 to 5.")
  parser.add_argument("--apply-fixes", action="store_true", help="Allow supported automatic prompt fixes to be applied.")
  parser.add_argument("--allow-high-risk-fixes", action="store_true", help="Allow the fixer to apply high-risk changes too.")
  parser.add_argument("--session-dir", default="", help="Optional custom output folder for logs and reports.")
  args = parser.parse_args()

  repo_root = repo_root_from_here()
  session_dir = Path(args.session_dir).resolve() if str(args.session_dir or "").strip() else ""
  config = LoopConfig(
    command=str(args.command),
    max_iterations=max(1, int(args.max_iterations)),
    apply_fixes=bool(args.apply_fixes),
    allow_high_risk_fixes=bool(args.allow_high_risk_fixes),
    repo_root=str(repo_root),
    session_dir=str(session_dir) if session_dir else "",
  )
  payload = OrchestratorAgent(config).run()
  print(json.dumps(payload, indent=2, ensure_ascii=False))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
