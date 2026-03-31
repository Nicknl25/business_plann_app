from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "python"
CLIENT_INTAKE_DIR = PYTHON_DIR / "client_intake_and_finmo"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))
if str(CLIENT_INTAKE_DIR) not in sys.path:
  sys.path.insert(0, str(CLIENT_INTAKE_DIR))

from client_intake_and_finmo.quarter_grid import (  # type: ignore
  available_planning_modes,
  build_quarter_grid_prompt,
  build_real_governor_payload,
  call_quarter_grid_openai,
  chunk_quarter_grid_rows,
  extract_quarter_grid_rows,
  validate_quarter_grid_response,
)
from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs, QUARTER_COUNT
from financial_model_engine.run_engine_replay import (  # type: ignore
  DEFAULT_OUTPUT_DIR,
  _load_env,
  _load_workbook_views,
  _mysql_connect,
  _parse_json_object,
  _select_source_draft,
)


def _safe_filename_part(value: str) -> str:
  cleaned = "".join(ch for ch in str(value or "").strip() if ch not in '\\/:*?"<>|')
  return cleaned[:180] or "quarter_grid_probe"


def _build_report_path(*, output_dir: Path, seed: str, written_at: datetime) -> Path:
  timestamp_part = written_at.strftime("%m-%d-%Y %H-%M-%S")
  return output_dir / f"{timestamp_part} -- {_safe_filename_part(seed)}.txt"


def _write_report(*, output_dir: Path, seed: str, lines: Sequence[str]) -> Path:
  output_dir.mkdir(parents=True, exist_ok=True)
  path = _build_report_path(output_dir=output_dir, seed=seed, written_at=datetime.now())
  path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
  return path


def _report_lines(
  *,
  source_row: Dict[str, Any],
  finmo_path: str,
  grid_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
  validation: Dict[str, Any],
  batch_summaries: List[str],
) -> List[str]:
  lines: List[str] = []
  draft_id = str(source_row.get("draft_id") or "").strip()
  client_id = str(source_row.get("client_id") or "").strip()
  lines.append(f"Quarter Grid Probe: {draft_id or client_id}")
  lines.append(f"Source Draft ID: {draft_id}")
  lines.append(f"Source Client ID: {client_id}")
  lines.append(f"Business Name: {str(source_row.get('business_name') or '').strip()}")
  lines.append(f"Finmo Path: {finmo_path}")
  lines.append("")
  lines.append("Probe Summary")
  lines.append("-------------")
  lines.append(str(response_json.get("summary") or ""))
  if batch_summaries:
    lines.append("")
    lines.append("Batch Summaries")
    lines.append("---------------")
    for item in batch_summaries:
      lines.append(f"- {item}")
  lines.append("")
  lines.append("Validation")
  lines.append("----------")
  lines.append(f"Requested Rows: {validation['requested_row_count']}")
  lines.append(f"Returned Rows: {validation['returned_row_count']}")
  lines.append(f"Missing Rows: {len(validation['missing_rows'])}")
  lines.append(f"Extra Rows: {len(validation['extra_rows'])}")
  lines.append(f"Duplicate Rows: {len(validation['duplicate_rows'])}")
  lines.append(f"Malformed Rows: {len(validation['malformed_rows'])}")
  lines.append(f"Flat Rows: {len(validation['flat_rows'])}")
  if validation["missing_rows"]:
    lines.append("Missing Row IDs:")
    for row_id in validation["missing_rows"]:
      lines.append(f"- {row_id}")
  if validation["malformed_rows"]:
    lines.append("Malformed Rows:")
    for item in validation["malformed_rows"]:
      lines.append(f"- {item}")
  if validation["flat_rows"]:
    lines.append("Flat Rows:")
    for row_id in validation["flat_rows"][:100]:
      lines.append(f"- {row_id}")
  lines.append("")
  lines.append("Requested Grid Rows")
  lines.append("-------------------")
  for item in grid_rows:
    lines.append(f"- {item['row_type']} | {item['row_id']}")
  lines.append("")
  lines.append("Response JSON")
  lines.append("-------------")
  lines.append(json.dumps(response_json, indent=2))
  return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
  parser = argparse.ArgumentParser(description="Probe whether GPT can fill a full quarter-by-quarter band grid.")
  parser.add_argument("--draft-id", dest="draft_id")
  parser.add_argument("--client-id", dest="client_id")
  parser.add_argument("--output-dir", dest="output_dir", default=str(DEFAULT_OUTPUT_DIR))
  parser.add_argument("--batch-size", dest="batch_size", type=int, default=12)
  parser.add_argument("--use-real-strategy-prompt", dest="use_real_strategy_prompt", action="store_true")
  parser.add_argument("--planning-mode", dest="planning_mode", choices=available_planning_modes(), default="turnaround")
  args = parser.parse_args(list(argv) if argv is not None else None)

  _load_env()
  conn = _mysql_connect()
  try:
    source_row = _select_source_draft(conn, source_draft_id=args.draft_id, source_client_id=args.client_id)
    model_input_json, _finmo_json, finmo_path = _load_workbook_views(source_row)
  finally:
    conn.close()

  baseline_inputs = FinancialModelInputs.from_model_input_json(model_input_json)
  baseline_outputs = calculate_finmo_model(baseline_inputs).quarter_rows()
  grid_rows = extract_quarter_grid_rows(model_input_json=model_input_json, baseline_outputs=baseline_outputs)
  governor_payload = build_real_governor_payload(
    source_row=source_row,
    model_input_json=model_input_json,
    finmo_json=_finmo_json,
    parse_json_object=_parse_json_object,
  )
  response_rows: List[Dict[str, Any]] = []
  batch_summaries: List[str] = []
  batches = chunk_quarter_grid_rows(grid_rows, args.batch_size)
  for batch_offset, batch_rows in enumerate(batches, start=1):
    prompt = build_quarter_grid_prompt(
      source_row=source_row,
      grid_rows=batch_rows,
      governor_payload=governor_payload,
      batch_index=batch_offset,
      batch_count=len(batches),
      planning_mode=str(args.planning_mode),
    )
    batch_response = call_quarter_grid_openai(
      prompt,
      allowed_row_ids=[str(item.get("row_id") or "") for item in batch_rows],
      use_real_strategy_prompt=bool(args.use_real_strategy_prompt),
      planning_mode=str(args.planning_mode),
    )
    response_rows.extend(batch_response.get("rows") if isinstance(batch_response.get("rows"), list) else [])
    batch_summaries.append(str(batch_response.get("summary") or f"Batch {batch_offset} completed."))
  response_json = {
    "summary": f"Completed {len(batches)} quarter-grid probe batches.",
    "rows": response_rows,
  }
  validation = validate_quarter_grid_response(requested_rows=grid_rows, response_json=response_json)
  report_path = _write_report(
    output_dir=Path(args.output_dir),
    seed=str(source_row.get("draft_id") or source_row.get("client_id") or "quarter-grid-probe"),
    lines=_report_lines(
      source_row=source_row,
      finmo_path=finmo_path,
      grid_rows=grid_rows,
      response_json=response_json,
      validation=validation,
      batch_summaries=batch_summaries,
    ),
  )
  print(f"Quarter grid probe saved to: {report_path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
