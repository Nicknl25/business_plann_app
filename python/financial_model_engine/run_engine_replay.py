from __future__ import annotations

import argparse
import json
import os
import re
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

try:
  import mysql.connector  # type: ignore
except Exception:
  mysql = None  # type: ignore

try:
  from dotenv import load_dotenv  # type: ignore
except Exception:
  load_dotenv = None  # type: ignore

try:
  from client_intake_and_finmo import finmo_bridge  # type: ignore
  from client_intake_and_finmo import consistency_flow as consistency_runtime  # type: ignore
  from client_intake_and_finmo.consistency_financials import (  # type: ignore
    build_consistency_financial_summary,
  )
except Exception:
  from client_intake_and_finmo import finmo_bridge  # type: ignore
  from client_intake_and_finmo import consistency_flow as consistency_runtime  # type: ignore
  from client_intake_and_finmo.consistency_financials import (  # type: ignore
    build_consistency_financial_summary,
  )

from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs
from financial_model_engine.solver import (
  LeverControl,
  OutputTarget,
  SolverOptions,
  solve_financial_model,
)


DEFAULT_OUTPUT_DIR = Path(
  r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\New Runner"
)


def _load_env() -> None:
  if load_dotenv is None:
    return
  root_env = ROOT / ".env"
  try:
    if root_env.exists():
      load_dotenv(root_env, override=False)
    else:
      load_dotenv(override=False)
  except Exception:
    pass


def _mysql_env() -> Optional[Dict[str, Any]]:
  host = os.getenv("MYSQL_HOST", "").strip()
  user = os.getenv("MYSQL_USER", "").strip()
  password = os.getenv("MYSQL_PASSWORD", "")
  database = os.getenv("MYSQL_DB", "").strip()
  port_raw = os.getenv("MYSQL_PORT", "3306").strip()
  if not (host and user and database):
    return None
  try:
    port = int(port_raw or "3306")
  except Exception:
    port = 3306
  return {
    "host": host,
    "user": user,
    "password": password,
    "database": database,
    "port": port,
  }


def _mysql_connect():
  cfg = _mysql_env()
  if mysql is None or getattr(mysql, "connector", None) is None or not cfg:
    raise RuntimeError("MySQL connector or MYSQL_* env vars are not available.")
  return mysql.connector.connect(**cfg)


def _parse_json_object(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return dict(raw)
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
  timestamp_part = written_at.strftime("%m-%d-%Y %H-%M-%S")
  return output_dir / f"{timestamp_part} -- {_safe_filename_part(seed)}.txt"


def _write_report(*, output_dir: Path, seed: str, lines: Sequence[str]) -> Path:
  output_dir.mkdir(parents=True, exist_ok=True)
  path = _build_report_path(output_dir=output_dir, seed=seed, written_at=datetime.now())
  path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
  return path


def _select_source_draft(
  conn,
  *,
  source_draft_id: Optional[str],
  source_client_id: Optional[str],
) -> Dict[str, Any]:
  cur = conn.cursor(dictionary=True)
  try:
    if source_draft_id:
      cur.execute(
        "SELECT * FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1",
        (source_draft_id,),
      )
    elif source_client_id:
      cur.execute(
        "SELECT * FROM intake_consult_drafts WHERE client_id = %s LIMIT 1",
        (source_client_id,),
      )
    else:
      raise RuntimeError("One of --draft-id or --client-id is required.")
    row = cur.fetchone()
  finally:
    cur.close()
  if not isinstance(row, dict) or not row:
    raise RuntimeError("Source draft not found.")
  return row


def _load_workbook_views(source_row: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
  model_input_json = _parse_json_object(source_row.get("model_input_json"))
  finmo_json = _parse_json_object(source_row.get("finmo_json"))
  finmo_path = str(source_row.get("finmo_path") or "").strip()
  if not model_input_json:
    model_input_json = finmo_bridge.build_python_model_input_json(
      business_facts={},
      ops_json=_parse_json_object(source_row.get("operating_model_json")),
      people_json=_parse_json_object(source_row.get("people_json")),
      financials_json=_parse_json_object(source_row.get("financials_json")),
      financials_year1_json=_parse_json_object(source_row.get("financials_year1_json")),
      marketing_model_json=_parse_json_object(source_row.get("marketing_model_json")),
      controller_input_seed=[],
      forecast_quarters=[],
      business_name=str(source_row.get("business_name") or "").strip(),
    ) or {}
  if model_input_json:
    model_input_json = finmo_bridge.normalize_model_input_forecast_anchor(model_input_json=model_input_json) or {}
  if not finmo_path:
    if model_input_json:
      finmo_json = finmo_bridge.build_python_finmo_json(
        model_input_json=model_input_json,
        finmo_path=finmo_path,
      ) or {}
      return model_input_json, finmo_json, finmo_path
    raise RuntimeError("Draft is missing model_input_json/finmo_json and has no finmo_path.")
  finmo_json = finmo_bridge.build_python_finmo_json(
    model_input_json=model_input_json,
    finmo_path=finmo_path,
  ) or {}
  return model_input_json, finmo_json, finmo_path


def _build_strategy_selection(
  *,
  source_row: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  finmo_path: str,
) -> Dict[str, Any]:
  ops_json = _parse_json_object(source_row.get("operating_model_json"))
  target_market_json = _parse_json_object(source_row.get("target_market_json"))
  people_json = _parse_json_object(source_row.get("people_json"))
  financials_json = _parse_json_object(source_row.get("financials_json"))
  financials_year1_json = _parse_json_object(source_row.get("financials_year1_json"))
  fulfillment_json = _parse_json_object(source_row.get("fulfillment_json"))
  marketing_model_json = _parse_json_object(source_row.get("marketing_model_json"))

  baseline_summary = consistency_runtime._baseline_summary_from_finmo(finmo_json) or build_consistency_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  state_model = consistency_runtime._build_consistency_state_model(
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    baseline_summary=baseline_summary,
    diagnostic_state=None,
    finmo_path=finmo_path,
    business_facts={},
    model_input_json=model_input_json,
    finmo_json=finmo_json,
  )
  direct_inputs = consistency_runtime._build_controller_inputs(state_model=state_model)
  state_model["direct_inputs"] = direct_inputs
  strategy_layer = consistency_runtime._build_strategy_layer(
    state_model=state_model,
    direct_inputs=direct_inputs,
    baseline_summary=baseline_summary,
    diagnostic_state=None,
    viability_mode=True,
  )
  selection = (
    strategy_layer.get("strategy_selection")
    if isinstance(strategy_layer.get("strategy_selection"), dict)
    else {}
  )
  return {
    "baseline_summary": baseline_summary,
    "state_model": state_model,
    "direct_inputs": direct_inputs,
    "strategy_layer": strategy_layer,
    "selection": selection,
  }


def _build_solver_controls(selection: Dict[str, Any]) -> List[LeverControl]:
  controls: List[LeverControl] = []
  for raw_item in selection.get("lever_adjustment_plan") or []:
    if not isinstance(raw_item, dict):
      continue
    lever_id = str(raw_item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    min_value = raw_item.get("min_value")
    max_value = raw_item.get("max_value")
    exact_value = None
    if min_value is not None and max_value is not None:
      try:
        if abs(float(min_value) - float(max_value)) <= 1e-12:
          exact_value = float(min_value)
      except Exception:
        exact_value = None
    controls.append(
      LeverControl(
        lever_id=lever_id,
        quarter_start=int(raw_item.get("quarter_start") or 1),
        quarter_end=int(raw_item.get("quarter_end") or raw_item.get("quarter_start") or 1),
        min_value=_safe_maybe_float(min_value),
        max_value=_safe_maybe_float(max_value),
        exact_value=exact_value,
      )
    )
  return controls


def _safe_maybe_float(value: Any) -> Optional[float]:
  if value in {None, ""}:
    return None
  try:
    return float(value)
  except Exception:
    return None


def _build_output_targets(selection: Dict[str, Any]) -> List[OutputTarget]:
  targets: List[OutputTarget] = []
  for raw_item in selection.get("controlled_output_targets") or []:
    if not isinstance(raw_item, dict):
      continue
    line_item = str(raw_item.get("line_item") or "").strip()
    if not line_item:
      continue
    targets.append(
      OutputTarget(
        metric=line_item,
        quarter_start=int(raw_item.get("quarter_start") or 1),
        quarter_end=int(raw_item.get("quarter_end") or raw_item.get("quarter_start") or 1),
        min_value=_safe_maybe_float(raw_item.get("min_value")),
        max_value=_safe_maybe_float(raw_item.get("max_value")),
      )
    )
  return targets


def _format_currency(value: Any) -> str:
  try:
    return f"{float(value):,.2f}"
  except Exception:
    return str(value)


def _format_controls(controls: List[LeverControl]) -> List[str]:
  lines: List[str] = []
  for control in controls:
    q_start, q_end = control.normalized_quarters()
    if control.exact_value is not None:
      band_text = f"exact={control.exact_value}"
    else:
      band_text = f"min={control.min_value}, max={control.max_value}"
    lines.append(f"- {control.lever_id} | Q{q_start}-Q{q_end} | {band_text}")
  return lines


def _format_targets(targets: List[OutputTarget]) -> List[str]:
  lines: List[str] = []
  for target in targets:
    q_start, q_end = target.normalized_quarters()
    lines.append(
      f"- {target.metric} | Q{q_start}-Q{q_end} | min={target.min_value}, max={target.max_value}"
    )
  return lines


def _format_quarter_summary(title: str, rows: List[Dict[str, Any]]) -> List[str]:
  lines = [title, "-" * len(title)]
  for row in rows:
    if not isinstance(row, dict):
      continue
    lines.append(
      f"Q{int(row.get('quarter_index') or 0):02d} | Year {int(row.get('year') or 0)} Q{int(row.get('quarter') or 0)} | Revenue {_format_currency(row.get('revenue'))} | EBITDA {_format_currency(row.get('ebitda'))} | Net Income {_format_currency(row.get('net_income'))} | Ending Cash {_format_currency(row.get('ending_cash'))}"
    )
  lines.append("")
  return lines


_ANNUAL_FLOW_KEYS = {
  "revenue",
  "cost_of_goods_sold",
  "cogs",
  "gross_profit",
  "marketing",
  "research_and_development",
  "lease_rent",
  "payroll",
  "general_and_administrative",
  "g_and_a",
  "ebitda",
  "interest",
  "depreciation",
  "taxes",
  "net_income",
  "capital_expenditures",
  "changes_in_current_assets",
  "changes_in_current_liabilities",
  "operating_cash_flow",
  "investing_cash_flow",
  "financing_cash_flow",
  "net_cash_flow",
  "debt_additions_repayments_net",
  "debt_receive_repay",
  "lease_principal_repayments",
  "lease_net_additions",
}

_ANNUAL_SKIP_KEYS = {
  "year",
  "quarter",
  "quarter_index",
  "slot_index",
  "date",
  "days_in_quarter",
}

_ANNUAL_KEY_ORDER = [
  "revenue",
  "cost_of_goods_sold",
  "gross_profit",
  "marketing",
  "research_and_development",
  "lease_rent",
  "payroll",
  "general_and_administrative",
  "ebitda",
  "interest",
  "depreciation",
  "taxes",
  "net_income",
  "operating_cash_flow",
  "investing_cash_flow",
  "financing_cash_flow",
  "net_cash_flow",
  "beginning_cash",
  "ending_cash",
  "cash",
  "accounts_receivable",
  "inventory",
  "prepaid_expenses",
  "current_assets",
  "ppe",
  "accumulated_depreciation",
  "total_assets",
  "accounts_payable",
  "deferred_revenue",
  "short_term_debt",
  "long_term_debt",
  "debt_opening_balance",
  "debt_closing_balance",
  "debt_interest_rate",
  "current_liabilities",
  "lease_opening_balance_total",
  "lease_closing_balance_total",
  "total_liabilities",
  "owners_capital",
  "other_equity",
  "retained_earnings",
  "equity",
  "total_equity",
  "total_liabilities_and_equity",
  "accounting_equation_check",
]


def _format_annual_summary(title: str, rows: List[Dict[str, Any]]) -> List[str]:
  lines = [title, "-" * len(title)]
  grouped: Dict[int, List[Dict[str, Any]]] = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    year = int(row.get("year") or 0)
    if year <= 0:
      continue
    grouped.setdefault(year, []).append(row)
  for year in sorted(grouped.keys()):
    group = sorted(grouped[year], key=lambda item: int(item.get("quarter_index") or 0))
    if not group:
      continue
    keys = set()
    for row in group:
      for key, value in row.items():
        if key in _ANNUAL_SKIP_KEYS:
          continue
        if isinstance(value, (int, float)):
          keys.add(key)
    ordered_keys = [key for key in _ANNUAL_KEY_ORDER if key in keys]
    ordered_keys.extend(sorted(key for key in keys if key not in ordered_keys))
    lines.append(f"Year {year}")
    for key in ordered_keys:
      if key == "accounting_equation_check":
        value = max(abs(float(row.get(key) or 0.0)) for row in group)
      elif key in _ANNUAL_FLOW_KEYS:
        value = sum(float(row.get(key) or 0.0) for row in group)
      else:
        value = float(group[-1].get(key) or 0.0)
      lines.append(f"- {key}: {value:,.2f}")
    lines.append("")
  return lines


def _format_iteration_trace(iterations: Sequence[Any]) -> List[str]:
  lines = ["Solver Iterations", "-----------------"]
  for iteration in iterations:
    objective_value = getattr(iteration, "objective_value", None)
    iteration_index = getattr(iteration, "iteration_index", None)
    lines.append(f"- Iteration {iteration_index}: objective={objective_value}")
  lines.append("")
  return lines


def _selection_coverage_issues(selection: Dict[str, Any]) -> List[str]:
  issues = selection.get("coverage_issues") if isinstance(selection.get("coverage_issues"), list) else []
  return [str(item or "").strip() for item in issues if str(item or "").strip()]


def _selection_has_output_targets(selection: Dict[str, Any]) -> bool:
  targets = selection.get("controlled_output_targets")
  return isinstance(targets, list) and any(isinstance(item, dict) for item in targets)


def _blueprint_is_usable(
  *,
  selection: Dict[str, Any],
  strategy_layer: Dict[str, Any],
) -> bool:
  gpt_usable = getattr(consistency_runtime, "_gpt_blueprint_is_usable", None)
  if callable(gpt_usable):
    try:
      if not bool(gpt_usable(selection)):
        return False
    except Exception:
      return False
  if _selection_coverage_issues(selection):
    return False
  if not _selection_has_output_targets(selection):
    return False
  strategies = strategy_layer.get("strategies") if isinstance(strategy_layer.get("strategies"), list) else []
  return bool(strategies)


def run_engine_replay(
  *,
  source_draft_id: Optional[str],
  source_client_id: Optional[str],
  output_dir: Path,
  max_iterations: int,
) -> Path:
  _load_env()
  conn = _mysql_connect()
  try:
    source_row = _select_source_draft(
      conn,
      source_draft_id=source_draft_id,
      source_client_id=source_client_id,
    )
  finally:
    conn.close()

  model_input_json, finmo_json, finmo_path = _load_workbook_views(source_row)
  baseline_inputs = FinancialModelInputs.from_model_input_json(model_input_json)
  baseline_outputs = calculate_finmo_model(baseline_inputs).quarter_rows()

  strategy_payload = _build_strategy_selection(
    source_row=source_row,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    finmo_path=finmo_path,
  )
  selection = strategy_payload["selection"]
  strategy_layer = strategy_payload["strategy_layer"] if isinstance(strategy_payload.get("strategy_layer"), dict) else {}
  controls = _build_solver_controls(selection)
  targets = _build_output_targets(selection)

  seed = str(source_row.get("draft_id") or source_row.get("client_id") or "financial_model_engine")
  lines: List[str] = [
    f"Financial Model Engine Replay: {seed}",
    f"Source Draft ID: {source_row.get('draft_id') or ''}",
    f"Source Client ID: {source_row.get('client_id') or ''}",
    f"Business Name: {source_row.get('business_name') or ''}",
    f"Finmo Path: {finmo_path}",
    "",
    "Strategy Layer",
    "--------------",
    f"Source: {strategy_layer.get('source') or ''}",
    f"Blueprint Usable: {_blueprint_is_usable(selection=selection, strategy_layer=strategy_layer)}",
  ]
  coverage_issues = _selection_coverage_issues(selection)
  if coverage_issues:
    lines.extend(
      [
        "Coverage Issues",
        "---------------",
        *[f"- {item}" for item in coverage_issues],
        "",
      ]
    )
  else:
    lines.append("")
  lines.extend(
    [
    "Selected Strategies",
    "-------------------",
    ]
  )
  for strategy_id in selection.get("selected_strategy_ids") or []:
    lines.append(f"- {strategy_id}")

  if not _blueprint_is_usable(selection=selection, strategy_layer=strategy_layer):
    lines.extend(
      [
        "",
        "Runner Status",
        "-------------",
        "No solve was run because the real GPT blueprint is still invalid for solver use.",
        "The next fix needs to be in the governor contract output itself, not in SciPy.",
        "",
        "Controlled Levers",
        "-----------------",
        *(_format_controls(controls) or ["- none"]),
        "",
        "Controlled Output Targets",
        "-------------------------",
        *(_format_targets(targets) or ["- none"]),
        "",
      ]
    )
    lines.extend(_format_quarter_summary("Baseline Quarter Summary", baseline_outputs))
    lines.extend(_format_annual_summary("Baseline Annual Summary", baseline_outputs))
    lines.extend(
      [
        "Selection JSON",
        "--------------",
        json.dumps(selection, indent=2, ensure_ascii=False, default=str),
        "",
      ]
    )
    return _write_report(output_dir=output_dir, seed=seed, lines=lines)

  result = solve_financial_model(
    baseline_inputs,
    controls=controls,
    targets=targets,
    options=SolverOptions(max_iterations=max_iterations),
  )
  solved_outputs = result.solved_outputs
  max_abs_check = max(abs(float(row.get("accounting_equation_check") or 0.0)) for row in solved_outputs) if solved_outputs else 0.0

  lines.extend(
    [
      "",
      "Solver Summary",
      "--------------",
      f"Objective Before: {result.objective_before}",
      f"Objective After: {result.objective_after}",
      f"Solver Success: {result.success}",
      f"Accounting Equation Check Max Abs: {max_abs_check}",
      "",
      "Controlled Levers",
      "-----------------",
      *(_format_controls(controls) or ["- none"]),
      "",
      "Controlled Output Targets",
      "-------------------------",
      *(_format_targets(targets) or ["- none"]),
      "",
    ]
  )
  lines.extend(_format_iteration_trace(result.iterations))
  lines.extend(_format_quarter_summary("Baseline Quarter Summary", baseline_outputs))
  lines.extend(_format_annual_summary("Baseline Annual Summary", baseline_outputs))
  lines.extend(_format_quarter_summary("Solved Quarter Summary", solved_outputs))
  lines.extend(_format_annual_summary("Solved Annual Summary", solved_outputs))
  lines.extend(
    [
      "Selection JSON",
      "--------------",
      json.dumps(selection, indent=2, ensure_ascii=False, default=str),
      "",
      "Solved Model Input JSON",
      "-----------------------",
      json.dumps(result.solved_model_input_json, indent=2, ensure_ascii=False, default=str),
      "",
      "Solved Quarterly Outputs",
      "------------------------",
      json.dumps(solved_outputs, indent=2, ensure_ascii=False, default=str),
    ]
  )
  return _write_report(output_dir=output_dir, seed=seed, lines=lines)


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Run the isolated financial_model_engine with the real GPT governor contract from a source draft."
  )
  parser.add_argument("--draft-id", help="Source intake_consult_drafts.draft_id")
  parser.add_argument("--client-id", help="Source intake_consult_drafts.client_id")
  parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
  parser.add_argument("--max-iterations", type=int, default=100)
  args = parser.parse_args()

  try:
    report_path = run_engine_replay(
      source_draft_id=str(args.draft_id or "").strip() or None,
      source_client_id=str(args.client_id or "").strip() or None,
      output_dir=Path(str(args.output_dir or DEFAULT_OUTPUT_DIR)),
      max_iterations=max(1, int(args.max_iterations or 100)),
    )
    print(f"Saved engine replay report: {report_path}")
    return 0
  except KeyboardInterrupt:
    print("Stopped by user.")
    return 130
  except Exception as exc:
    print(f"STOP: engine replay error: {type(exc).__name__}: {exc}")
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
