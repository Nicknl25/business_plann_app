import argparse
import concurrent.futures
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import requests

try:
  import mysql.connector  # type: ignore
except Exception:
  mysql = None  # type: ignore

try:
  from dotenv import load_dotenv
except Exception:
  load_dotenv = None


US_EASTERN = ZoneInfo("America/New_York")


def _default_apps_root() -> str:
  env_root = str(os.getenv("INTAKE_APPS_ROOT") or "").strip()
  if env_root:
    return env_root
  one_drive_root = str(os.getenv("OneDriveCommercial") or os.getenv("OneDrive") or "").strip()
  if one_drive_root:
    return os.path.join(one_drive_root, "Apps")
  return os.path.join(os.path.expanduser("~"), "OneDrive - Tithe Financial Wealth Management", "Apps")


DEFAULT_APPS_ROOT = _default_apps_root()
DEFAULT_TEST_RUNS_DIR = os.path.join(DEFAULT_APPS_ROOT, "Test Runs")
DEFAULT_TEST_RUNS_DATA_DIR = os.path.join(DEFAULT_APPS_ROOT, "Test Runs Data")
DEFAULT_TERMINAL_LOGS_DIR = os.path.join(DEFAULT_APPS_ROOT, "Terminal Logs")
LOCAL_FALLBACK_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "_consistency_replay_output"))
REQUEST_TIMEOUT_SECONDS = None


def _load_env() -> None:
  if load_dotenv:
    try:
      repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
      root_env = os.path.join(repo_root, ".env")
      if os.path.exists(root_env):
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


def _eastern_now() -> datetime:
  return datetime.now(tz=US_EASTERN)


def _safe_filename_part(value: str) -> str:
  text = re.sub(r'[\\/:*?"<>|]+', "", str(value or "").strip())
  text = re.sub(r"\s+", " ", text).strip()
  return text[:180] or "consistency_replay"


def _build_run_artifact_path(*, output_dir: str, seed: str, written_at: datetime) -> str:
  date_part = written_at.strftime("%m-%d-%Y")
  scenario_part = _safe_filename_part(seed)
  return os.path.join(output_dir, f"{date_part} -- {scenario_part}.txt")


def _build_run_artifact_filename(*, seed: str, written_at: datetime) -> str:
  return os.path.basename(_build_run_artifact_path(output_dir="", seed=seed, written_at=written_at))


def _write_artifact_lines(
  *,
  output_dir: str,
  seed: str,
  written_at: datetime,
  lines: Sequence[str],
  fallback_suffix: str,
) -> Optional[str]:
  attempted: List[Tuple[str, Exception]] = []
  candidate_seeds = [seed]
  suffix = str(fallback_suffix or "").strip()
  if suffix:
    candidate_seeds.append(f"{seed} -- {suffix}")
  else:
    candidate_seeds.append(f"{seed} -- {written_at.strftime('%H%M%S')}")
  candidate_dirs = [output_dir]
  normalized_output = os.path.normcase(os.path.abspath(output_dir))
  if LOCAL_FALLBACK_ROOT and normalized_output != os.path.normcase(os.path.abspath(LOCAL_FALLBACK_ROOT)):
    leaf = os.path.basename(os.path.normpath(output_dir)) or "artifacts"
    candidate_dirs.append(os.path.join(LOCAL_FALLBACK_ROOT, leaf))
  for candidate_dir in candidate_dirs:
    try:
      os.makedirs(candidate_dir, exist_ok=True)
    except Exception as exc:
      attempted.append((candidate_dir, exc))
      continue
    for candidate_seed in candidate_seeds:
      path = _build_run_artifact_path(output_dir=candidate_dir, seed=candidate_seed, written_at=written_at)
      try:
        with open(path, "w", encoding="utf-8") as handle:
          handle.write("\n".join(lines).rstrip() + "\n")
        return path
      except Exception as exc:
        attempted.append((path, exc))
  for path, exc in attempted:
    print(f"[runner_artifact_write_error] {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
  return None


def _request_json_error(response: requests.Response) -> RuntimeError:
  text = response.text.strip()
  try:
    payload = response.json()
    text = json.dumps(payload, ensure_ascii=False)
  except Exception:
    pass
  return RuntimeError(f"HTTP {response.status_code}: {text}")


def _post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
  resp = requests.post(url, json=payload, headers=headers or {}, timeout=REQUEST_TIMEOUT_SECONDS)
  if resp.status_code >= 400:
    raise _request_json_error(resp)
  data = resp.json()
  if not isinstance(data, dict):
    raise RuntimeError(f"Expected JSON object from {url}, got: {type(data).__name__}")
  return data


def _get_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
  resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
  if resp.status_code >= 400:
    raise _request_json_error(resp)
  data = resp.json()
  if not isinstance(data, dict):
    raise RuntimeError(f"Expected JSON object from {url}, got: {type(data).__name__}")
  return data


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


def _json_or_none(value: Any) -> Optional[str]:
  if value is None:
    return None
  if isinstance(value, str):
    return value
  return json.dumps(value, ensure_ascii=False)


def _parse_multi_args(values: Optional[Sequence[str]]) -> List[str]:
  parsed: List[str] = []
  for raw in values or []:
    for part in str(raw or "").split(","):
      item = str(part or "").strip()
      if item:
        parsed.append(item)
  return parsed


def _job_name(*, draft_id: Optional[str], client_id: Optional[str]) -> str:
  source_id = str(draft_id or client_id or "").strip()
  return source_id or "consistency_replay"


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


def _clean_financials_for_replay(raw_financials: Any) -> str:
  financials = _parse_json_object(raw_financials)
  financials.pop("_consistency_solver_state", None)
  financials.pop("_consistency_close_stage", None)
  return json.dumps(financials, ensure_ascii=False)


def _has_nonempty_mapping(raw: Any) -> bool:
  return bool(_parse_json_object(raw))


def _has_any_numeric_value(mapping: Dict[str, Any], keys: Sequence[str], *, allow_zero: bool = True) -> bool:
  for key in keys:
    if key not in mapping:
      continue
    try:
      value = float(mapping.get(key))
    except Exception:
      continue
    if allow_zero or value > 0:
      return True
  return False


def _section_readiness(source_row: Dict[str, Any]) -> Dict[str, bool]:
  operating_model = _parse_json_object(source_row.get("operating_model_json"))
  target_market = _parse_json_object(source_row.get("target_market_json"))
  people = _parse_json_object(source_row.get("people_json"))
  financials = _parse_json_object(source_row.get("financials_json"))
  financials_year1 = _parse_json_object(source_row.get("financials_year1_json"))
  marketing_model = _parse_json_object(source_row.get("marketing_model_json"))

  ops_ready = bool(operating_model) and any(
    str(operating_model.get(key) or "").strip()
    for key in ("business_type", "capacity_driver", "sales_modality", "unit_name", "unit_cadence")
  )
  market_ready = bool(target_market) and (
    bool(marketing_model)
    or any(str(target_market.get(key) or "").strip() for key in ("customer_type", "market_type", "target_market_summary"))
  )
  people_ready = bool(people) and (
    isinstance(people.get("people"), list)
    or isinstance(people.get("inferred_roles"), list)
    or bool(people.get("team_summary"))
  )
  financials_ready = bool(financials) and bool(financials_year1) and all(
    (
      _has_any_numeric_value(financials_year1, ("company_revenue_total_year1",), allow_zero=False),
      _has_any_numeric_value(financials, ("current_cogs", "cogs_total_year1", "baseline_cogs"), allow_zero=True),
      _has_any_numeric_value(financials, ("current_payroll", "payroll_total_year1", "baseline_payroll_year1"), allow_zero=True),
      _has_any_numeric_value(financials, ("marketing_total_year1", "baseline_marketing"), allow_zero=True)
      or "marketing_percent_of_revenue" in financials,
    )
  )
  marketing_ready = bool(marketing_model) and (
    bool(marketing_model.get("ready"))
    or _has_any_numeric_value(marketing_model, ("expected_units_year1", "required_units_year1", "reachable_market"), allow_zero=True)
  )
  return {
    "ops": ops_ready,
    "market": market_ready,
    "people": people_ready,
    "financials": financials_ready,
    "marketing_model": marketing_ready,
  }


def _source_row_consistency_ready(source_row: Dict[str, Any]) -> Tuple[bool, str, Dict[str, bool]]:
  consistency_passed = int(source_row.get("consistency_passed") or 0)
  business_name = str(source_row.get("business_name") or "").strip() or "unknown business"
  source_draft_id = str(source_row.get("draft_id") or "").strip() or "unknown draft"
  readiness = _section_readiness(source_row)

  if consistency_passed == 1:
    return True, "", readiness
  if all(readiness.get(key) for key in ("ops", "market", "people", "financials", "marketing_model")):
    return True, "", readiness
  missing = [name for name, ready in readiness.items() if not ready]
  return (
    False,
    f"source draft {source_draft_id} for '{business_name}' is missing consistency inputs: {', '.join(missing) or 'unknown'}",
    readiness,
  )


def _hydrate_replay_draft(
  conn,
  *,
  target_draft_id: str,
  source_row: Dict[str, Any],
  readiness: Dict[str, bool],
) -> None:
  excluded = {
    "draft_id",
    "client_id",
    "created_at",
    "updated_at",
    "completed_at",
    "submitted_at",
  }
  payload: Dict[str, Any] = {}
  for key, value in source_row.items():
    if key in excluded:
      continue
    payload[key] = value

  payload["messages_json"] = json.dumps([], ensure_ascii=False)
  payload["status"] = "in_progress"
  payload["active_focus"] = "consistency"
  payload["ops_confirmed"] = 1 if readiness.get("ops") else 0
  payload["market_confirmed"] = 1 if readiness.get("market") else 0
  payload["people_confirmed"] = 1 if readiness.get("people") else 0
  payload["financials_confirmed"] = 1 if readiness.get("financials") else 0
  payload["consistency_passed"] = 0
  payload["completed_at"] = None
  payload["submitted_at"] = None
  payload["planning_run_json"] = None
  payload["model_input_json"] = source_row.get("model_input_json")
  payload["finmo_json"] = source_row.get("finmo_json")
  payload["financials_json"] = _clean_financials_for_replay(source_row.get("financials_json"))

  set_parts: List[str] = []
  values: List[Any] = []
  for key, value in payload.items():
    set_parts.append(f"{key} = %s")
    values.append(value)
  set_parts.append("updated_at = UTC_TIMESTAMP()")
  values.append(target_draft_id)

  sql = f"UPDATE intake_consult_drafts SET {', '.join(set_parts)} WHERE draft_id = %s"
  cur = conn.cursor()
  try:
    cur.execute(sql, tuple(values))
    conn.commit()
  finally:
    cur.close()


def _fetch_persisted_state_snapshot(*, base_url: str, draft_id: Optional[str]) -> Dict[str, Any]:
  if not str(draft_id or "").strip():
    return {
      "status": "missing_draft_id",
      "detail": "No draft_id was available, so persisted state could not be fetched.",
    }

  draft_id_value = str(draft_id).strip()
  debug_url = f"{base_url}/debug/state/{draft_id_value}"
  try:
    payload = _get_json(debug_url, {})
    return {
      "status": "ok",
      "source": "debug/state",
      "payload": payload,
    }
  except Exception as exc:
    fallback_url = f"{base_url}/api/intake-consult/draft"
    try:
      fallback = _get_json(fallback_url, {"draft_id": draft_id_value})
      return {
        "status": "fallback",
        "source": "api/intake-consult/draft",
        "detail": f"Primary persisted-state fetch failed: {exc}",
        "payload": fallback,
      }
    except Exception as fallback_exc:
      return {
        "status": "error",
        "source": "debug/state",
        "detail": str(exc),
        "fallback_error": str(fallback_exc),
      }


def _save_run_report(
  *,
  output_dir: str,
  seed: str,
  transcript: List[Dict[str, str]],
  source_draft_id: Optional[str],
  source_client_id: Optional[str],
  replay_draft_id: Optional[str],
  replay_client_id: Optional[str],
  status: str,
  stop_reason: str,
  written_at: Optional[datetime] = None,
) -> Optional[str]:
  try:
    now = written_at or _eastern_now()
    lines: List[str] = []
    lines.append(f"Consistency Replay: {seed}")
    lines.append(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if source_draft_id:
      lines.append(f"Source Draft ID: {source_draft_id}")
    if source_client_id:
      lines.append(f"Source Client ID: {source_client_id}")
    if replay_draft_id:
      lines.append(f"Replay Draft ID: {replay_draft_id}")
    if replay_client_id:
      lines.append(f"Replay Client ID: {replay_client_id}")
    lines.append(f"Status: {status}")
    lines.append(f"Stop Reason: {stop_reason}")
    lines.append("")
    lines.append("Transcript")
    lines.append("----------")
    lines.append("")
    for item in transcript:
      role = str(item.get("role") or "?")
      focus = str(item.get("focus") or "").strip()
      content = str(item.get("content") or "").strip()
      if focus:
        lines.append(f"{role} [{focus}]: {content}")
      else:
        lines.append(f"{role}: {content}")
      lines.append("")
    return _write_artifact_lines(
      output_dir=output_dir,
      seed=seed,
      written_at=now,
      lines=lines,
      fallback_suffix="run-report",
    )
  except Exception as exc:
    print(f"[runner_artifact_build_error] run-report: {type(exc).__name__}: {exc}", file=sys.stderr)
    return None


def _save_persisted_state_report(
  *,
  base_url: str,
  output_dir: str,
  seed: str,
  source_draft_id: Optional[str],
  source_client_id: Optional[str],
  replay_draft_id: Optional[str],
  replay_client_id: Optional[str],
  status: str,
  stop_reason: str,
  written_at: Optional[datetime] = None,
) -> Optional[str]:
  try:
    now = written_at or _eastern_now()
    snapshot = _fetch_persisted_state_snapshot(base_url=base_url, draft_id=replay_draft_id)
    lines: List[str] = []
    lines.append(f"Consistency Replay: {seed}")
    lines.append(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if source_draft_id:
      lines.append(f"Source Draft ID: {source_draft_id}")
    if source_client_id:
      lines.append(f"Source Client ID: {source_client_id}")
    if replay_draft_id:
      lines.append(f"Replay Draft ID: {replay_draft_id}")
    if replay_client_id:
      lines.append(f"Replay Client ID: {replay_client_id}")
    lines.append(f"Status: {status}")
    lines.append(f"Stop Reason: {stop_reason}")
    lines.append("")
    lines.append("Persisted State")
    lines.append("---------------")
    lines.append("")
    lines.append(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))
    return _write_artifact_lines(
      output_dir=output_dir,
      seed=seed,
      written_at=now,
      lines=lines,
      fallback_suffix="persisted-state",
    )
  except Exception as exc:
    print(f"[runner_artifact_build_error] persisted-state: {type(exc).__name__}: {exc}", file=sys.stderr)
    return None


def _print_artifact_paths(
  *,
  report_path: Optional[str],
  persisted_path: Optional[str],
  trace_file_name: str,
) -> None:
  if report_path:
    print(f"Saved run report: {report_path}")
  if persisted_path:
    print(f"Saved persisted state report: {persisted_path}")
  print(f"Expected terminal log file: {os.path.join(DEFAULT_TERMINAL_LOGS_DIR, trace_file_name)}")


def _choose_seed(
  *,
  source_row: Dict[str, Any],
  source_draft_id: Optional[str],
  source_client_id: Optional[str],
) -> str:
  source_id = str(source_draft_id or source_row.get("draft_id") or "").strip()
  if source_id:
    return source_id
  source_client = str(source_client_id or source_row.get("client_id") or "").strip()
  if source_client:
    return source_client
  return "consistency_replay"


def _run_consistency_replay(
  *,
  base_url: str,
  source_draft_id: Optional[str],
  source_client_id: Optional[str],
  output_dir: str,
  persisted_output_dir: str,
  max_turns: int,
) -> int:
  conn = _mysql_connect()
  transcript: List[Dict[str, str]] = []
  replay_draft_id: Optional[str] = None
  replay_client_id: Optional[str] = None
  source_row = _select_source_draft(
    conn,
    source_draft_id=source_draft_id,
    source_client_id=source_client_id,
  )
  ready, readiness_reason, readiness = _source_row_consistency_ready(source_row)
  if not ready:
    raise RuntimeError(readiness_reason)
  seed = _choose_seed(
    source_row=source_row,
    source_draft_id=source_draft_id,
    source_client_id=source_client_id,
  )
  run_started_at = _eastern_now()
  trace_file_name = _build_run_artifact_filename(seed=seed, written_at=run_started_at)
  try:
    session = _post_json(f"{base_url}/api/intake-consult/session", {})
    replay_draft_id = str(session.get("draft_id") or "").strip() or None
    replay_client_id = str(session.get("client_id") or "").strip() or None
    if not replay_draft_id:
      raise RuntimeError(f"Failed to create replay draft session: {session}")

    _hydrate_replay_draft(
      conn,
      target_draft_id=replay_draft_id,
      source_row=source_row,
      readiness=readiness,
    )

    headers = {
      "X-Solver-Trace-Run-Name": trace_file_name,
      "X-Solver-Trace-Reset": "1",
    }
    response: Dict[str, Any] = {}
    for turn_index in range(max_turns):
      payload = {
        "draft_id": replay_draft_id,
        "client_id": replay_client_id,
        "message": "",
      }
      if turn_index > 0:
        transcript.append({"role": "runner", "focus": "consistency", "content": "[auto-continue]"})
      response = _post_json(f"{base_url}/api/intake-consult", payload, headers=headers if turn_index == 0 else {"X-Solver-Trace-Run-Name": trace_file_name})
      assistant_message = str(response.get("assistant_message") or "").strip()
      active_focus = str(response.get("active_focus") or "").strip().lower()
      transcript.append({"role": "assistant", "focus": active_focus, "content": assistant_message})
      print(f"\n[{active_focus or 'unknown'}][assistant] {assistant_message}")
      if response.get("done"):
        written_at = _eastern_now()
        report_path = _save_run_report(
          output_dir=output_dir,
          seed=seed,
          transcript=transcript,
          source_draft_id=str(source_row.get("draft_id") or ""),
          source_client_id=str(source_row.get("client_id") or ""),
          replay_draft_id=replay_draft_id,
          replay_client_id=replay_client_id,
          status="completed",
          stop_reason="consistency completed",
          written_at=written_at,
        )
        persisted_path = _save_persisted_state_report(
          base_url=base_url,
          output_dir=persisted_output_dir,
          seed=seed,
          source_draft_id=str(source_row.get("draft_id") or ""),
          source_client_id=str(source_row.get("client_id") or ""),
          replay_draft_id=replay_draft_id,
          replay_client_id=replay_client_id,
          status="completed",
          stop_reason="consistency completed",
          written_at=written_at,
        )
        _print_artifact_paths(report_path=report_path, persisted_path=persisted_path, trace_file_name=trace_file_name)
        print(f"Replay Draft ID: {replay_draft_id}")
        return 0
      if active_focus and active_focus != "consistency":
        written_at = _eastern_now()
        stop_reason = f"unexpected focus '{active_focus}' during consistency replay"
        report_path = _save_run_report(
          output_dir=output_dir,
          seed=seed,
          transcript=transcript,
          source_draft_id=str(source_row.get("draft_id") or ""),
          source_client_id=str(source_row.get("client_id") or ""),
          replay_draft_id=replay_draft_id,
          replay_client_id=replay_client_id,
          status="stopped",
          stop_reason=stop_reason,
          written_at=written_at,
        )
        persisted_path = _save_persisted_state_report(
          base_url=base_url,
          output_dir=persisted_output_dir,
          seed=seed,
          source_draft_id=str(source_row.get("draft_id") or ""),
          source_client_id=str(source_row.get("client_id") or ""),
          replay_draft_id=replay_draft_id,
          replay_client_id=replay_client_id,
          status="stopped",
          stop_reason=stop_reason,
          written_at=written_at,
        )
        _print_artifact_paths(report_path=report_path, persisted_path=persisted_path, trace_file_name=trace_file_name)
        print(f"Replay Draft ID: {replay_draft_id}")
        return 1
      if not assistant_message and turn_index == 0:
        break

    written_at = _eastern_now()
    stop_reason = f"max turns reached ({max_turns})"
    report_path = _save_run_report(
      output_dir=output_dir,
      seed=seed,
      transcript=transcript,
      source_draft_id=str(source_row.get("draft_id") or ""),
      source_client_id=str(source_row.get("client_id") or ""),
      replay_draft_id=replay_draft_id,
      replay_client_id=replay_client_id,
      status="stopped",
      stop_reason=stop_reason,
      written_at=written_at,
    )
    persisted_path = _save_persisted_state_report(
      base_url=base_url,
      output_dir=persisted_output_dir,
      seed=seed,
      source_draft_id=str(source_row.get("draft_id") or ""),
      source_client_id=str(source_row.get("client_id") or ""),
      replay_draft_id=replay_draft_id,
      replay_client_id=replay_client_id,
      status="stopped",
      stop_reason=stop_reason,
      written_at=written_at,
    )
    _print_artifact_paths(report_path=report_path, persisted_path=persisted_path, trace_file_name=trace_file_name)
    print(f"Replay Draft ID: {replay_draft_id}")
    return 1
  except Exception as exc:
    written_at = _eastern_now()
    stop_reason = f"{type(exc).__name__}: {exc}"
    transcript.append({"role": "runner", "focus": "consistency", "content": f"[error] {stop_reason}"})
    report_path = _save_run_report(
      output_dir=output_dir,
      seed=seed,
      transcript=transcript,
      source_draft_id=str(source_row.get("draft_id") or ""),
      source_client_id=str(source_row.get("client_id") or ""),
      replay_draft_id=replay_draft_id,
      replay_client_id=replay_client_id,
      status="failed",
      stop_reason=stop_reason,
      written_at=written_at,
    )
    persisted_path = _save_persisted_state_report(
      base_url=base_url,
      output_dir=persisted_output_dir,
      seed=seed,
      source_draft_id=str(source_row.get("draft_id") or ""),
      source_client_id=str(source_row.get("client_id") or ""),
      replay_draft_id=replay_draft_id,
      replay_client_id=replay_client_id,
      status="failed",
      stop_reason=stop_reason,
      written_at=written_at,
    )
    _print_artifact_paths(report_path=report_path, persisted_path=persisted_path, trace_file_name=trace_file_name)
    if replay_draft_id:
      print(f"Replay Draft ID: {replay_draft_id}")
    raise
  finally:
    try:
      conn.close()
    except Exception:
      pass


def main() -> int:
  print(
    "run_consistency_replay.py is deprecated. Live intake now ends at financials, then generates realism_memo_json for system-run.",
    file=sys.stderr,
  )
  print(
    "Use a live runner or direct-seeded runner and inspect the saved persisted state / New Runner report for the realism memo instead.",
    file=sys.stderr,
  )
  return 2


if __name__ == "__main__":
  raise SystemExit(main())
