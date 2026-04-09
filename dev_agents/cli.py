from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import LoopConfig
from .orchestrator import OrchestratorAgent
from .utils import repo_root_from_here


def main() -> int:
  parser = argparse.ArgumentParser(description="Dev-only planning helper agents.")
  parser.add_argument("--command", default="", help="PowerShell command to run the planning test.")
  parser.add_argument("--command-file", default="", help="Path to a PowerShell script or text file containing the planning command.")
  parser.add_argument("--max-iterations", type=int, default=5, help="Bounded loop count. Defaults to 5.")
  parser.add_argument("--apply-fixes", action="store_true", help="Apply fixes between iterations. Defaults to on.")
  parser.add_argument("--allow-high-risk-fixes", action="store_true", help="Allow high-risk fixes too. Defaults to on.")
  parser.add_argument("--session-dir", default="", help="Optional custom output folder for logs and reports.")
  args = parser.parse_args()

  repo_root = repo_root_from_here()
  session_dir = Path(args.session_dir).resolve() if str(args.session_dir or "").strip() else ""
  command = str(args.command or "").strip()
  command_file = str(args.command_file or "").strip()
  if not command and not command_file:
    parser.error("one of --command or --command-file is required")
  if command_file:
    command_path = Path(command_file)
    if not command_path.is_absolute():
      command_path = (repo_root / command_path).resolve()
    if not command_path.exists():
      parser.error(f"command file not found: {command_path}")
    suffix = command_path.suffix.lower()
    if suffix == ".ps1":
      command = f"& '{str(command_path)}'"
    else:
      command = command_path.read_text(encoding="utf-8").strip()
      if not command:
        parser.error(f"command file is empty: {command_path}")
  config = LoopConfig(
    command=command,
    max_iterations=max(1, int(args.max_iterations)),
    apply_fixes=True,
    allow_high_risk_fixes=True,
    repo_root=str(repo_root),
    session_dir=str(session_dir) if session_dir else "",
  )
  payload = OrchestratorAgent(config).run()
  print(json.dumps(payload, indent=2, ensure_ascii=False))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
