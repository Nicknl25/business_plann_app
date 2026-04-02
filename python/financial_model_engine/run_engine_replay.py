from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "python"
CLIENT_DIR = PYTHON_DIR / "client_intake_and_finmo"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))
if str(CLIENT_DIR) not in sys.path:
  sys.path.insert(0, str(CLIENT_DIR))

try:
  import mysql.connector  # type: ignore
except Exception:
  mysql = None  # type: ignore

try:
  from dotenv import load_dotenv  # type: ignore
except Exception:
  load_dotenv = None  # type: ignore

from client_intake_and_finmo.quarter_grid import determine_planning_mode, generate_live_quarter_grid_plan, solve_live_quarter_grid_plan
from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs


DEFAULT_OUTPUT_DIR = Path(r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\New Runner")


def _load_env() -> None:
  if load_dotenv is None:
    return
  env_path = ROOT / ".env"
  try:
    if env_path.exists():
      load_dotenv(env_path, override=False)
    else:
      load_dotenv(override=False)
  except Exception:
    pass


def _mysql_env() -> Dict[str, Any]:
  host = os.getenv("MYSQL_HOST", "").strip()
  user = os.getenv("MYSQL_USER", "").strip()
  password = os.getenv("MYSQL_PASSWORD", "")
  database = os.getenv("MYSQL_DB", "").strip()
  port_raw = os.getenv("MYSQL_PORT", "3306").strip()
  if not (host and user and database):
    raise RuntimeError("MYSQL_* env vars are not available.")
  try:
    port = int(port_raw or "3306")
  except Exception:
    port = 3306
  return {"host": host, "user": user, "password": password, "database": database, "port": port}


def _mysql_connect():
  if mysql is None or getattr(mysql, "connector", None) is None:
    raise RuntimeError("mysql-connector-python is not available.")
  return mysql.connector.connect(**_mysql_env())


def _parse_json_object(raw: Any) -> Dict[str, Any]:
  if isinstance(raw, dict):
    return dict(raw)
  if raw is None:
    return {}
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _safe_filename_part(value: str) -> str:
  text = re.sub(r'[\\/:*?"<>|]+', "", str(value or "").strip())
  text = re.sub(r"\s+", " ", text).strip()
  return text[:180] or "financial_model_engine"


def _build_report_path(*, output_dir: Path, seed: str, written_at: datetime) -> Path:
  return output_dir / f"{written_at.strftime('%m-%d-%Y %H-%M-%S')} -- {_safe_filename_part(seed)}.txt"


def _build_named_report_path(*, output_dir: Path, seed: str, written_at: datetime, suffix: str) -> Path:
  return output_dir / f"{written_at.strftime('%m-%d-%Y %H-%M-%S')} -- {_safe_filename_part(seed)} -- {_safe_filename_part(suffix)}.txt"


def _select_source_row(conn, *, draft_id: Optional[str], client_id: Optional[str]) -> Dict[str, Any]:
  cur = conn.cursor(dictionary=True)
  try:
    if draft_id:
      cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1", (str(draft_id).strip(),))
    elif client_id:
      cur.execute("SELECT * FROM intake_consult_drafts WHERE client_id = %s LIMIT 1", (str(client_id).strip(),))
    else:
      raise RuntimeError("Provide --draft-id or --client-id.")
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not isinstance(row, dict) or not row:
    raise RuntimeError("Source draft not found.")
  return row


def _select_source_draft(conn, source_draft_id: Optional[str], source_client_id: Optional[str]) -> Dict[str, Any]:
  return _select_source_row(conn, draft_id=source_draft_id, client_id=source_client_id)


def _load_python_views(source_row: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
  model_input_json = _parse_json_object(source_row.get("model_input_json"))
  finmo_json = _parse_json_object(source_row.get("finmo_json"))
  if not model_input_json:
    raise RuntimeError("Draft is missing model_input_json.")
  if not finmo_json:
    baseline_inputs = FinancialModelInputs.from_model_input_json(model_input_json)
    finmo_json = calculate_finmo_model(baseline_inputs).to_finmo_json()
  return model_input_json, finmo_json


def _load_workbook_views(source_row: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], str]:
  model_input_json, finmo_json = _load_python_views(source_row)
  return model_input_json, finmo_json, ""


def _annual_summary(quarter_rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, float]]:
  summary: Dict[int, Dict[str, float]] = {}
  for row in quarter_rows:
    quarter_index = int(row.get("quarter_index") or 0)
    if quarter_index <= 0:
      continue
    year_index = ((quarter_index - 1) // 4) + 1
    year_bucket = summary.setdefault(year_index, {})
    for key, value in row.items():
      if key in {"quarter_index", "quarter"}:
        continue
      try:
        number = float(value)
      except Exception:
        continue
      if key in {
        "ending_cash",
        "cash",
        "accounts_receivable",
        "inventory",
        "prepaids",
        "ppe",
        "accumulated_depreciation",
        "accounts_payable",
        "deferred_revenue",
        "lease_closing_balance_total",
        "other_long_term_liabilities",
        "short_term_debt",
        "long_term_debt",
        "owners_capital",
        "other_equity",
        "retained_earnings",
        "total_assets",
        "total_liabilities_and_equity",
        "accounting_equation_check",
      }:
        year_bucket[key] = number
      else:
        year_bucket[key] = year_bucket.get(key, 0.0) + number
  return summary


def _report_lines(
  *,
  source_row: Dict[str, Any],
  planning_choice: Dict[str, Any],
  planning_result: Dict[str, Any],
  solver_result: Dict[str, Any],
) -> List[str]:
  solved_finmo = solver_result.get("solved_finmo_json") if isinstance(solver_result.get("solved_finmo_json"), dict) else {}
  quarter_rows = [row for row in (solved_finmo.get("quarter_rows") or []) if isinstance(row, dict)]
  solver_summary = solver_result.get("solver_summary") if isinstance(solver_result.get("solver_summary"), dict) else {}
  validation = planning_result.get("validation") if isinstance(planning_result.get("validation"), dict) else {}
  metadata = planning_result.get("metadata") if isinstance(planning_result.get("metadata"), dict) else {}
  annual = _annual_summary(quarter_rows)

  lines = [
    f"Business Name: {str(source_row.get('business_name') or '').strip()}",
    f"Draft ID: {str(source_row.get('draft_id') or '').strip()}",
    f"Planning Mode: {planning_choice.get('planning_mode') or ''}",
    f"Planning Mode Reason: {planning_choice.get('planning_mode_reason') or ''}",
    f"Prompt File: {planning_choice.get('prompt_file') or ''}",
    f"GPT Rows Requested: {metadata.get('requested_row_count')}",
    f"GPT Rows Returned: {metadata.get('returned_row_count')}",
    f"Missing Rows: {len(validation.get('missing_rows') or [])}",
    f"Extra Rows: {len(validation.get('extra_rows') or [])}",
    f"Malformed Rows: {len(validation.get('malformed_rows') or [])}",
    f"Solver Success: {bool(solver_summary.get('success'))}",
    f"Solver Iterations: {solver_summary.get('iterations')}",
    f"Solver Objective Before: {solver_summary.get('objective_before')}",
    f"Solver Objective After: {solver_summary.get('objective_after')}",
    f"Accounting Equation Check Max Abs: {solver_summary.get('accounting_equation_check_max_abs')}",
    "",
    "GPT Narrative:",
    str(planning_result.get("gpt_narrative") or "").strip(),
    "",
    "Quarterly Summary:",
  ]
  for row in quarter_rows:
    quarter_index = int(row.get("quarter_index") or 0)
    if quarter_index <= 0:
      continue
    lines.append(
      " | ".join(
        [
          f"Q{quarter_index}",
          f"Revenue {float(row.get('revenue') or 0.0):,.2f}",
          f"EBITDA {float(row.get('ebitda') or 0.0):,.2f}",
          f"Cash {float(row.get('ending_cash') or 0.0):,.2f}",
          f"Acct Check {float(row.get('accounting_equation_check') or 0.0):,.6f}",
        ]
      )
    )
  lines.append("")
  lines.append("Annual Summary:")
  for year_index in sorted(annual.keys()):
    lines.append(f"Year {year_index}:")
    for key in sorted(annual[year_index].keys()):
      lines.append(f"  {key}: {annual[year_index][key]:,.2f}")
  return lines


def _grid_report_lines(
  *,
  source_row: Dict[str, Any],
  planning_choice: Dict[str, Any],
  planning_result: Dict[str, Any],
) -> List[str]:
  metadata = planning_result.get("metadata") if isinstance(planning_result.get("metadata"), dict) else {}
  validation = metadata.get("validation") if isinstance(metadata.get("validation"), dict) else {}
  response_json = metadata.get("response_json") if isinstance(metadata.get("response_json"), dict) else {}
  grid_rows = [item for item in (response_json.get("rows") or []) if isinstance(item, dict)]
  lines = [
    f"Business Name: {str(source_row.get('business_name') or '').strip()}",
    f"Draft ID: {str(source_row.get('draft_id') or '').strip()}",
    f"Planning Mode: {planning_choice.get('planning_mode') or ''}",
    f"Prompt File: {planning_choice.get('prompt_file') or ''}",
    f"Requested Rows: {metadata.get('requested_row_count')}",
    f"Returned Rows: {metadata.get('returned_row_count')}",
    f"Batch Count: {metadata.get('batch_count')}",
    f"Runtime Seconds: {metadata.get('runtime_seconds')}",
    f"Missing Rows: {len(validation.get('missing_rows') or [])}",
    f"Extra Rows: {len(validation.get('extra_rows') or [])}",
    f"Malformed Rows: {len(validation.get('malformed_rows') or [])}",
    f"Duplicate Rows: {len(validation.get('duplicate_rows') or [])}",
    "",
    "GPT Narrative:",
    str(planning_result.get("gpt_narrative") or "").strip(),
    "",
    "Grid Rows:",
  ]
  for item in grid_rows:
    row_id = str(item.get("row_id") or "").strip()
    row_type = str(item.get("row_type") or "").strip()
    lines.append(f"{row_id} [{row_type}]")
    for band in [band for band in (item.get("quarter_bands") or []) if isinstance(band, dict)]:
      lines.append(
        f"  Q{int(band.get('quarter_index') or 0)}: {float(band.get('min_value') or 0.0):,.6f} to {float(band.get('max_value') or 0.0):,.6f}"
      )
    lines.append("")
  return lines


def _solver_report_lines(
  *,
  source_row: Dict[str, Any],
  solver_result: Dict[str, Any],
) -> List[str]:
  solved_finmo = solver_result.get("solved_finmo_json") if isinstance(solver_result.get("solved_finmo_json"), dict) else {}
  quarter_rows = [row for row in (solved_finmo.get("quarter_rows") or []) if isinstance(row, dict)]
  solver_summary = solver_result.get("solver_summary") if isinstance(solver_result.get("solver_summary"), dict) else {}
  annual = _annual_summary(quarter_rows)
  lines = [
    f"Business Name: {str(source_row.get('business_name') or '').strip()}",
    f"Draft ID: {str(source_row.get('draft_id') or '').strip()}",
    f"Solver Success: {bool(solver_summary.get('success'))}",
    f"Iterations: {solver_summary.get('iterations')}",
    f"Control Count: {solver_summary.get('control_count')}",
    f"Target Count: {solver_summary.get('target_count')}",
    f"Objective Before: {solver_summary.get('objective_before')}",
    f"Objective After: {solver_summary.get('objective_after')}",
    f"Accounting Equation Check Max Abs: {solver_summary.get('accounting_equation_check_max_abs')}",
    "",
    "Quarterly Summary:",
  ]
  for row in quarter_rows:
    quarter_index = int(row.get("quarter_index") or 0)
    if quarter_index <= 0:
      continue
    lines.append(
      " | ".join(
        [
          f"Q{quarter_index}",
          f"Revenue {float(row.get('revenue') or 0.0):,.2f}",
          f"EBITDA {float(row.get('ebitda') or 0.0):,.2f}",
          f"Cash {float(row.get('ending_cash') or 0.0):,.2f}",
          f"Acct Check {float(row.get('accounting_equation_check') or 0.0):,.6f}",
        ]
      )
    )
  lines.append("")
  lines.append("Annual Summary:")
  for year_index in sorted(annual.keys()):
    lines.append(f"Year {year_index}:")
    for key in sorted(annual[year_index].keys()):
      lines.append(f"  {key}: {annual[year_index][key]:,.2f}")
  return lines


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--draft-id", default="", help="intake_consult_drafts.draft_id")
  parser.add_argument("--client-id", default="", help="intake_consult_drafts.client_id")
  parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
  args = parser.parse_args()

  _load_env()
  output_dir = Path(str(args.output_dir or DEFAULT_OUTPUT_DIR))
  output_dir.mkdir(parents=True, exist_ok=True)

  conn = _mysql_connect()
  try:
    source_row = _select_source_row(conn, draft_id=str(args.draft_id or "").strip() or None, client_id=str(args.client_id or "").strip() or None)
  finally:
    conn.close()

  model_input_json, finmo_json = _load_python_views(source_row)
  planning_choice = determine_planning_mode(
    ops_json=_parse_json_object(source_row.get("operating_model_json")),
    target_market_json=_parse_json_object(source_row.get("target_market_json")),
    people_json=_parse_json_object(source_row.get("people_json")),
    financials_json=_parse_json_object(source_row.get("financials_json")),
    financials_year1_json=_parse_json_object(source_row.get("financials_year1_json")),
    fulfillment_json=_parse_json_object(source_row.get("fulfillment_json")),
    marketing_model_json=_parse_json_object(source_row.get("marketing_model_json")),
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    business_facts={},
  )
  planning_result = generate_live_quarter_grid_plan(
    business_name=str(source_row.get("business_name") or "").strip(),
    planning_mode=str(planning_choice.get("planning_mode") or "").strip(),
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    ops_json=_parse_json_object(source_row.get("operating_model_json")),
    target_market_json=_parse_json_object(source_row.get("target_market_json")),
    people_json=_parse_json_object(source_row.get("people_json")),
    financials_json=_parse_json_object(source_row.get("financials_json")),
    financials_year1_json=_parse_json_object(source_row.get("financials_year1_json")),
    fulfillment_json=_parse_json_object(source_row.get("fulfillment_json")),
    marketing_model_json=_parse_json_object(source_row.get("marketing_model_json")),
    business_facts={},
  )
  solver_result = solve_live_quarter_grid_plan(
    baseline_model_input_json=model_input_json,
    grid_json=planning_result.get("grid_json") if isinstance(planning_result.get("grid_json"), dict) else {},
  )
  written_at = datetime.now()
  report_path = _build_report_path(
    output_dir=output_dir,
    seed=str(args.draft_id or args.client_id or source_row.get("draft_id") or "engine_replay"),
    written_at=written_at,
  )
  report_path.write_text(
    "\n".join(_report_lines(source_row=source_row, planning_choice=planning_choice, planning_result=planning_result, solver_result=solver_result)),
    encoding="utf-8",
  )
  grid_report_path = _build_named_report_path(
    output_dir=output_dir,
    seed=str(args.draft_id or args.client_id or source_row.get("draft_id") or "engine_replay"),
    written_at=written_at,
    suffix="quarter-grid",
  )
  grid_report_path.write_text(
    "\n".join(_grid_report_lines(source_row=source_row, planning_choice=planning_choice, planning_result=planning_result)),
    encoding="utf-8",
  )
  solver_report_path = _build_named_report_path(
    output_dir=output_dir,
    seed=str(args.draft_id or args.client_id or source_row.get("draft_id") or "engine_replay"),
    written_at=written_at,
    suffix="solver",
  )
  solver_report_path.write_text(
    "\n".join(_solver_report_lines(source_row=source_row, solver_result=solver_result)),
    encoding="utf-8",
  )
  print(str(report_path))
  print(str(grid_report_path))
  print(str(solver_report_path))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
