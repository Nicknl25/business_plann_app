from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ArtifactBundle, CommandResult
from .utils import ensure_repo_python_path, json_loads_dict, load_dotenv_fallback, repo_root_from_here, safe_float


TEST_RUNS_DIR = Path(r"C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\Test Runs")
TEST_RUNS_DATA_DIR = Path(r"C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\Test Runs Data")
NEW_RUNNER_DIR = Path(r"C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\New Runner")
TERMINAL_LOGS_DIR = Path(r"C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\Terminal Logs")


def _read_text_if_exists(path: Path) -> str:
  try:
    return path.read_text(encoding="utf-8")
  except Exception:
    return ""


def _load_agent_context(repo_root: Path) -> Dict[str, Any]:
  guidance_dir = repo_root / "dev_agents"
  files = {
    "playbook": guidance_dir / "PLAYBOOK_APP_AGENTS.md",
    "critical_context": guidance_dir / "CRITICAL_CONTEXT_APP_AGENTS.md",
    "app_map": guidance_dir / "APP_MAP_APP_AGENTS.md",
    "evaluation_rules": guidance_dir / "EVAL_RULES_APP_AGENTS.md",
    "learnings": guidance_dir / "LEARNINGS_APP_AGENTS.md",
    "readme": guidance_dir / "README.md",
  }
  texts = {name: _read_text_if_exists(path) for name, path in files.items()}
  recent_sessions: List[Dict[str, Any]] = []
  runs_dir = guidance_dir / "runs"
  if runs_dir.exists():
    for session_dir in sorted(
      [item for item in runs_dir.iterdir() if item.is_dir()],
      key=lambda item: item.stat().st_mtime,
      reverse=True,
    )[:5]:
      summary_path = session_dir / "executive_summary.json"
      summary = json_loads_dict(_read_text_if_exists(summary_path))
      if summary:
        recent_sessions.append({
          "session_dir": str(session_dir),
          "summary": summary,
        })
  return {
    "expected_runtime_commit": "",
    "runtime_files": [
      "python/client_intake_and_finmo/app_agents/planner.py",
      "python/client_intake_and_finmo/app_agents/shared_context.py",
      "python/client_intake_and_finmo/app_agents/solver_bridge.py",
      "python/client_intake_and_finmo/app_agents/realism_agent.py",
      "python/client_intake_and_finmo/app_agents/operations_agent.py",
      "python/client_intake_and_finmo/app_agents/capital_agent.py",
      "python/client_intake_and_finmo/app_agents/grid_agent.py",
      "python/api_handlers/intake_consult.py",
      "python/client_intake_and_finmo/intake_consult_draft.py",
    ],
    "production_ai_shape": "app_agents_four_agent_planner",
    "fix_scope": "any_file_inside_repo",
    "deleted_legacy_planner_modules": [
      "python/client_intake_and_finmo/quarter_grid.py",
      "python/client_intake_and_finmo/realism_memo.py",
    ],
    "guidance_files": {name: str(path) for name, path in files.items()},
    "guidance_text": texts,
    "recent_sessions": recent_sessions,
  }


def _bootstrap_repo() -> Path:
  root = repo_root_from_here()
  load_dotenv_fallback(root)
  ensure_repo_python_path(root)
  return root


def run_planning_command(*, command: str, cwd: Path) -> CommandResult:
  def _decode_output(raw: Any) -> str:
    if raw is None:
      return ""
    if isinstance(raw, str):
      return raw
    if isinstance(raw, bytes):
      for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
          return raw.decode(encoding)
        except Exception:
          continue
      return raw.decode("utf-8", errors="replace")
    return str(raw)

  started_at = datetime.now()
  env = dict(os.environ)
  env["PYTHONUTF8"] = "1"
  env["PYTHONIOENCODING"] = "utf-8"
  proc = subprocess.run(
    ["powershell", "-NoProfile", "-Command", str(command)],
    cwd=str(cwd),
    text=False,
    capture_output=True,
    env=env,
  )
  ended_at = datetime.now()
  stdout_text = _decode_output(proc.stdout)
  stderr_text = _decode_output(proc.stderr)
  output = "\n".join([stdout_text, stderr_text]).strip()
  match = re.search(r"Draft ID:\s*([A-Za-z0-9_-]+)", output, flags=re.IGNORECASE)
  return CommandResult(
    command=command,
    returncode=int(proc.returncode),
    stdout=stdout_text,
    stderr=stderr_text,
    started_at=started_at,
    ended_at=ended_at,
    detected_draft_id=str(match.group(1)).strip() if match else "",
  )


def _get_mysql_connection():
  _bootstrap_repo()
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
  return get_mysql_connection()


def _fetch_draft_row(*, draft_id: str = "", since: Optional[datetime] = None, allow_latest_fallback: bool = True) -> Dict[str, Any]:
  conn = _get_mysql_connection()
  cur = conn.cursor(dictionary=True)
  try:
    row = None
    if draft_id:
      cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1", (str(draft_id).strip(),))
      row = cur.fetchone()
    elif since is not None:
      cur.execute(
        """
        SELECT *
        FROM intake_consult_drafts
        WHERE COALESCE(updated_at, created_at) >= %s
        ORDER BY COALESCE(updated_at, created_at) DESC
        LIMIT 1
        """,
        (since.strftime("%Y-%m-%d %H:%M:%S"),),
      )
      row = cur.fetchone()
    else:
      row = None
    if not row and allow_latest_fallback:
      cur.execute(
        "SELECT * FROM intake_consult_drafts ORDER BY COALESCE(updated_at, created_at) DESC LIMIT 1"
      )
      row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
    try:
      conn.close()
    except Exception:
      pass
  return dict(row or {})


def _locate_saved_paths(draft_id: str) -> Dict[str, str]:
  located: Dict[str, str] = {}
  patterns = {
    "run_report": list(TEST_RUNS_DIR.glob(f"*{draft_id}*.txt")),
    "state_report": list(TEST_RUNS_DATA_DIR.glob(f"*{draft_id}*.txt")),
    "new_runner_report": list(NEW_RUNNER_DIR.glob(f"*{draft_id}.txt")),
    "quarter_grid_report": list(NEW_RUNNER_DIR.glob(f"*{draft_id}*quarter-grid.txt")),
    "solver_report": list(NEW_RUNNER_DIR.glob(f"*{draft_id}*solver.txt")),
    "terminal_log": list(TERMINAL_LOGS_DIR.glob(f"*{draft_id}*.txt")),
  }
  for key, matches in patterns.items():
    if matches:
      latest = sorted(matches, key=lambda item: item.stat().st_mtime, reverse=True)[0]
      located[key] = str(latest)
  return located


def _extract_authoritative_cash_bands(gpt_meta: Dict[str, Any], app_agents_run_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  contract = gpt_meta.get("cash_constraint_contract") if isinstance(gpt_meta.get("cash_constraint_contract"), dict) else {}
  items = contract.get("authoritative_cash_bands") if isinstance(contract.get("authoritative_cash_bands"), list) else []
  if items:
    return [dict(item) for item in items if isinstance(item, dict)]
  grid_agent = app_agents_run_json.get("grid_agent") if isinstance(app_agents_run_json.get("grid_agent"), dict) else {}
  grid_json = grid_agent.get("grid_json") if isinstance(grid_agent.get("grid_json"), dict) else {}
  rows = grid_json.get("rows") if isinstance(grid_json.get("rows"), list) else []
  for row in rows:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_id") or "").strip() != "Cash":
      continue
    out: List[Dict[str, Any]] = []
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      out.append(
        {
          "quarter_index": int(safe_float(band.get("quarter_index")) or 0),
          "min_value": safe_float(band.get("min_value")),
          "max_value": safe_float(band.get("max_value")),
        }
      )
    return out
  return []


def _extract_authoritative_capital_rows(gpt_meta: Dict[str, Any], app_agents_run_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  rows = gpt_meta.get("authoritative_capital_rows") if isinstance(gpt_meta.get("authoritative_capital_rows"), list) else []
  if rows:
    return [dict(item) for item in rows if isinstance(item, dict)]
  grid_agent = app_agents_run_json.get("grid_agent") if isinstance(app_agents_run_json.get("grid_agent"), dict) else {}
  grid_json = grid_agent.get("grid_json") if isinstance(grid_agent.get("grid_json"), dict) else {}
  capital_tokens = ("capital expenditures", "capex", "owner", "equity", "debt", "principal", "cash")
  out: List[Dict[str, Any]] = []
  for row in grid_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    row_id = str(row.get("row_id") or "").strip()
    lowered = row_id.lower()
    if row_id == "Cash" or any(token in lowered for token in capital_tokens):
      out.append(dict(row))
  return out


def _run_local_solver(*, baseline_model_input_json: Dict[str, Any], grid_response_json: Dict[str, Any]) -> Dict[str, Any]:
  if not baseline_model_input_json or not grid_response_json:
    return {}
  _bootstrap_repo()
  from client_intake_and_finmo.app_agents.solver_bridge import solve_solver_grid_plan  # type: ignore

  try:
    result = solve_solver_grid_plan(
      baseline_model_input_json=dict(baseline_model_input_json),
      grid_json=dict(grid_response_json),
    )
  except Exception as exc:
    return {"error": str(exc)}
  solver_result = result.get("solver_result")
  solved_outputs = getattr(solver_result, "solved_outputs", None) if solver_result is not None else None
  return {
    "solver_summary": dict(result.get("solver_summary") or {}),
    "solved_outputs": [dict(item) for item in (solved_outputs or []) if isinstance(item, dict)],
  }


def build_artifact_bundle(
  *,
  draft_id: str = "",
  command_result: Optional[CommandResult] = None,
) -> ArtifactBundle:
  repo_root = _bootstrap_repo()
  since = command_result.started_at - timedelta(seconds=30) if command_result is not None else None
  row = _fetch_draft_row(
    draft_id=draft_id or (command_result.detected_draft_id if command_result else ""),
    since=since,
    allow_latest_fallback=False if command_result is not None else True,
  )
  resolved_draft_id = str(row.get("draft_id") or draft_id or (command_result.detected_draft_id if command_result else "")).strip()
  fresh_run = False
  if resolved_draft_id and command_result is not None:
    row_updated = row.get("updated_at") or row.get("created_at")
    if command_result.detected_draft_id and str(command_result.detected_draft_id).strip() == resolved_draft_id:
      fresh_run = True
    elif row_updated is not None:
      try:
        row_dt = row_updated if isinstance(row_updated, datetime) else datetime.fromisoformat(str(row_updated))
        fresh_run = row_dt >= (command_result.started_at - timedelta(seconds=30))
      except Exception:
        fresh_run = False
  planning_run_json = json_loads_dict(row.get("planning_run_json"))
  app_agents_run_json = json_loads_dict(row.get("app_agents_run_json"))
  prompt_file = str((repo_root / "python" / "client_intake_and_finmo" / "app_agents" / "prompts" / "grid_agent.md").resolve())
  prompt_file_text = ""
  if prompt_file:
    try:
      prompt_file_text = Path(prompt_file).read_text(encoding="utf-8")
    except Exception:
      prompt_file_text = ""
  gpt_meta = planning_run_json.get("gpt_grid_metadata") if isinstance(planning_run_json.get("gpt_grid_metadata"), dict) else {}
  app_agents_trace = [dict(item) for item in (gpt_meta.get("app_agents_trace") or []) if isinstance(item, dict)]
  grid_agent = app_agents_run_json.get("grid_agent") if isinstance(app_agents_run_json.get("grid_agent"), dict) else {}
  grid_response_json = grid_agent.get("grid_json") if isinstance(grid_agent.get("grid_json"), dict) else {}
  baseline_model_input_json = json_loads_dict(row.get("model_input_json"))
  local_solver = _run_local_solver(
    baseline_model_input_json=baseline_model_input_json,
    grid_response_json=grid_response_json,
  )
  stored_solver_summary = planning_run_json.get("solver_summary") if isinstance(planning_run_json.get("solver_summary"), dict) else {}
  if not stored_solver_summary:
    stored_solver_summary = dict(local_solver.get("solver_summary") or {})
  return ArtifactBundle(
    draft_id=resolved_draft_id,
    is_fresh_run=fresh_run,
    agent_context=_load_agent_context(repo_root),
    row=row,
    planning_run_json=planning_run_json,
    app_agents_run_json=app_agents_run_json,
    prompt_file=prompt_file,
    prompt_file_text=prompt_file_text,
    gpt_narrative=str(grid_agent.get("summary") or planning_run_json.get("gpt_narrative") or "").strip(),
    gpt_grid_metadata=gpt_meta,
    app_agents_trace=app_agents_trace,
    grid_response_json=grid_response_json,
    solver_summary=stored_solver_summary,
    local_solver_summary=dict(local_solver.get("solver_summary") or {}),
    local_solved_outputs=[dict(item) for item in (local_solver.get("solved_outputs") or []) if isinstance(item, dict)],
    authoritative_cash_bands=_extract_authoritative_cash_bands(gpt_meta, app_agents_run_json),
    authoritative_capital_rows=_extract_authoritative_capital_rows(gpt_meta, app_agents_run_json),
    saved_paths=_locate_saved_paths(resolved_draft_id),
    command_result=command_result,
  )


def extract_cash_violations(bundle: ArtifactBundle) -> List[Dict[str, Any]]:
  bands_by_q: Dict[int, Dict[str, Any]] = {}
  for item in bundle.authoritative_cash_bands:
    quarter_index = int(safe_float(item.get("quarter_index")) or 0)
    if quarter_index:
      bands_by_q[quarter_index] = item
  solved_by_q: Dict[int, Dict[str, Any]] = {}
  for item in bundle.local_solved_outputs:
    quarter_index = int(safe_float(item.get("quarter_index")) or 0)
    if quarter_index:
      solved_by_q[quarter_index] = item
  violations: List[Dict[str, Any]] = []
  for quarter_index in sorted(set(bands_by_q.keys()) | set(solved_by_q.keys())):
    band = bands_by_q.get(quarter_index) or {}
    solved = solved_by_q.get(quarter_index) or {}
    ending_cash = safe_float(solved.get("ending_cash"))
    band_min = safe_float(band.get("min_value"))
    band_max = safe_float(band.get("max_value"))
    if ending_cash is None or band_min is None or band_max is None:
      continue
    tolerance = max(100.0, 0.001 * max(abs(band_min), abs(band_max), 1.0))
    delta = 0.0
    direction = "inside"
    if ending_cash < (band_min - tolerance):
      delta = ending_cash - band_min
      direction = "below_min"
    elif ending_cash > (band_max + tolerance):
      delta = ending_cash - band_max
      direction = "above_max"
    violations.append(
      {
        "quarter_index": quarter_index,
        "band_min": band_min,
        "band_max": band_max,
        "ending_cash": ending_cash,
        "delta": delta,
        "direction": direction,
      }
    )
  return violations
