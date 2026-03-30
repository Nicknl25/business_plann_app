from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "python"
CLIENT_INTAKE_DIR = PYTHON_DIR / "client_intake_and_finmo"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))
if str(CLIENT_INTAKE_DIR) not in sys.path:
  sys.path.insert(0, str(CLIENT_INTAKE_DIR))

from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs
from financial_model_engine.run_engine_replay import (  # type: ignore
  DEFAULT_OUTPUT_DIR,
  _load_env,
  _load_workbook_views,
  _mysql_connect,
  _select_source_draft,
)
from financial_model_engine.solver import (  # type: ignore
  LeverControl,
  OutputTarget,
  SolverOptions,
  solve_financial_model,
)


def _safe_filename_part(value: str) -> str:
  cleaned = "".join(ch for ch in str(value or "").strip() if ch not in '\\/:*?"<>|')
  return cleaned[:180] or "probe_grid_solver"


def _build_report_path(*, output_dir: Path, seed: str, written_at: datetime) -> Path:
  timestamp_part = written_at.strftime("%m-%d-%Y %H-%M-%S")
  return output_dir / f"{timestamp_part} -- {_safe_filename_part(seed)}.txt"


def _write_report(*, output_dir: Path, seed: str, lines: Sequence[str]) -> Path:
  output_dir.mkdir(parents=True, exist_ok=True)
  path = _build_report_path(output_dir=output_dir, seed=seed, written_at=datetime.now())
  path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
  return path


def _parse_response_json(report_path: Path) -> Dict[str, Any]:
  text = report_path.read_text(encoding="utf-8")
  marker = "Response JSON\n-------------\n"
  start = text.index(marker) + len(marker)
  parsed = json.loads(text[start:])
  return parsed if isinstance(parsed, dict) else {}


def _find_latest_grid_report(output_dir: Path, draft_id: str) -> Path:
  pattern = f"*-- {draft_id}.txt"
  candidates = sorted(output_dir.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
  if not candidates:
    raise RuntimeError(f"No quarter-grid probe report found for draft {draft_id} in {output_dir}")
  return candidates[0]


def _float(value: Any) -> Optional[float]:
  if value in {None, ""}:
    return None
  try:
    return float(value)
  except Exception:
    return None


def _controls_from_probe(probe_json: Dict[str, Any]) -> List[LeverControl]:
  controls: List[LeverControl] = []
  for row in probe_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "lever":
      continue
    lever_id = str(row.get("row_id") or "").strip()
    if not lever_id:
      continue
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      quarter_index = int(band.get("quarter_index") or 0)
      if quarter_index < 1:
        continue
      controls.append(
        LeverControl(
          lever_id=lever_id,
          quarter_start=quarter_index,
          quarter_end=quarter_index,
          min_value=_float(band.get("min_value")),
          max_value=_float(band.get("max_value")),
        )
      )
  return controls


def _targets_from_probe(probe_json: Dict[str, Any]) -> List[OutputTarget]:
  targets: List[OutputTarget] = []
  for row in probe_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "output":
      continue
    metric = str(row.get("row_id") or "").strip()
    if not metric:
      continue
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      quarter_index = int(band.get("quarter_index") or 0)
      if quarter_index < 1:
        continue
      targets.append(
        OutputTarget(
          metric=metric,
          quarter_start=quarter_index,
          quarter_end=quarter_index,
          min_value=_float(band.get("min_value")),
          max_value=_float(band.get("max_value")),
        )
      )
  return targets


def _quarter_summary(rows: List[Dict[str, Any]]) -> List[str]:
  lines: List[str] = []
  for row in rows:
    q = int(row.get("quarter_index") or 0)
    lines.append(
      f"Q{q:02d} | Revenue {float(row.get('revenue') or 0.0):,.2f} | "
      f"EBITDA {float(row.get('ebitda') or 0.0):,.2f} | "
      f"Ending Cash {float(row.get('ending_cash') or 0.0):,.2f} | "
      f"Acct Check {float(row.get('accounting_equation_check') or 0.0):,.6f}"
    )
  return lines


def _report_lines(
  *,
  draft_id: str,
  probe_report_path: Path,
  controls: List[LeverControl],
  targets: List[OutputTarget],
  result: Any,
) -> List[str]:
  lines: List[str] = []
  max_accounting_check = max(
    abs(float(row.get("accounting_equation_check") or 0.0))
    for row in (result.solved_outputs or [])
  ) if result.solved_outputs else 0.0
  lines.append(f"Probe Grid Solver: {draft_id}")
  lines.append(f"Probe Report: {probe_report_path}")
  lines.append("")
  lines.append("Solver Summary")
  lines.append("--------------")
  lines.append(f"Controls: {len(controls)}")
  lines.append(f"Targets: {len(targets)}")
  lines.append(f"Objective Before: {result.objective_before}")
  lines.append(f"Objective After: {result.objective_after}")
  lines.append(f"Solver Success: {result.success}")
  lines.append(f"Iterations: {len(result.iterations)}")
  lines.append(f"Accounting Equation Check Max Abs: {max_accounting_check}")
  lines.append("")
  lines.append("Solved Quarter Summary")
  lines.append("----------------------")
  lines.extend(_quarter_summary(result.solved_outputs))
  return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
  parser = argparse.ArgumentParser(description="Run the Python solver directly from a quarter-grid GPT probe report.")
  parser.add_argument("--draft-id", dest="draft_id", required=True)
  parser.add_argument("--grid-report", dest="grid_report")
  parser.add_argument("--output-dir", dest="output_dir", default=str(DEFAULT_OUTPUT_DIR))
  parser.add_argument("--max-iterations", dest="max_iterations", type=int, default=300)
  parser.add_argument("--movement-penalty-weight", dest="movement_penalty_weight", type=float, default=0.000001)
  args = parser.parse_args(list(argv) if argv is not None else None)

  _load_env()
  output_dir = Path(args.output_dir)
  probe_report_path = Path(args.grid_report) if args.grid_report else _find_latest_grid_report(output_dir, args.draft_id)
  probe_json = _parse_response_json(probe_report_path)

  conn = _mysql_connect()
  try:
    source_row = _select_source_draft(conn, source_draft_id=args.draft_id, source_client_id=None)
    model_input_json, _finmo_json, _finmo_path = _load_workbook_views(source_row)
  finally:
    conn.close()

  baseline_inputs = FinancialModelInputs.from_model_input_json(model_input_json)
  controls = _controls_from_probe(probe_json)
  targets = _targets_from_probe(probe_json)
  result = solve_financial_model(
    baseline_inputs,
    controls=controls,
    targets=targets,
    options=SolverOptions(
      max_iterations=max(1, int(args.max_iterations)),
      movement_penalty_weight=float(args.movement_penalty_weight),
    ),
  )

  report_path = _write_report(
    output_dir=output_dir,
    seed=str(args.draft_id),
    lines=_report_lines(
      draft_id=str(args.draft_id),
      probe_report_path=probe_report_path,
      controls=controls,
      targets=targets,
      result=result,
    ),
  )
  print(f"Probe grid solver report saved to: {report_path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
