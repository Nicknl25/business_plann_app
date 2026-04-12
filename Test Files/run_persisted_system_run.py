import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
DUAL_RUNNER_PATH = THIS_DIR / "run_dual_agent_intake.py"


def _load_module(path: Path, name: str):
  spec = importlib.util.spec_from_file_location(name, str(path))
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load module from {path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


_DUAL = _load_module(DUAL_RUNNER_PATH, "run_dual_agent_intake_persisted_system_run")

try:
  import mysql.connector  # type: ignore
except Exception:
  mysql = None  # type: ignore

try:
  from dotenv import load_dotenv  # type: ignore
except Exception:
  load_dotenv = None  # type: ignore


def _string(value: Any) -> str:
  return str(value or "").strip()


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
  host = _string(os.getenv("MYSQL_HOST"))
  user = _string(os.getenv("MYSQL_USER"))
  password = str(os.getenv("MYSQL_PASSWORD") or "")
  database = _string(os.getenv("MYSQL_DB"))
  port_raw = _string(os.getenv("MYSQL_PORT") or "3306")
  if not (host and user and database):
    raise RuntimeError("MYSQL_HOST, MYSQL_USER, and MYSQL_DB must be configured.")
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
  if mysql is None or getattr(mysql, "connector", None) is None:
    raise RuntimeError("mysql-connector-python is not available in this environment.")
  return mysql.connector.connect(**_mysql_env())


def _select_consult_row(conn, *, client_id: str = "", draft_id: str = "") -> Dict[str, Any]:
  client_id_value = _string(client_id)
  draft_id_value = _string(draft_id)
  if not client_id_value and not draft_id_value:
    raise RuntimeError("client_id or draft_id is required.")
  cur = conn.cursor(dictionary=True)
  try:
    row = None
    if client_id_value:
      cur.execute(
        """
        SELECT *
        FROM intake_consult_drafts
        WHERE client_id = %s
        LIMIT 1
        """,
        (client_id_value,),
      )
      row = cur.fetchone()
      if not isinstance(row, dict) or not row:
        cur.execute(
          """
          SELECT *
          FROM intake_consult_drafts
          WHERE draft_id = %s
          LIMIT 1
          """,
          (client_id_value,),
        )
        row = cur.fetchone()
    else:
      cur.execute(
        """
        SELECT *
        FROM intake_consult_drafts
        WHERE draft_id = %s
        LIMIT 1
        """,
        (draft_id_value,),
      )
      row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not isinstance(row, dict) or not row:
    if client_id_value:
      raise RuntimeError(
        f"No persisted intake_consult_drafts row found for client_id={client_id_value!r} or draft_id={client_id_value!r}."
      )
    raise RuntimeError(f"No persisted intake_consult_drafts row found for draft_id={draft_id_value!r}.")
  return row


def _bootstrap_from_row(row: Dict[str, Any]) -> Optional[Any]:
  business_name = _string(row.get("business_name"))
  business_start_date = _string(row.get("business_start_date"))
  address = _string(row.get("business_address"))
  if not address:
    address_parts = [
      _string(row.get("address_street")),
      _string(row.get("address_city")),
      _string(row.get("address_state")),
      _string(row.get("address_zip")),
      _string(row.get("address_country")),
    ]
    address = ", ".join([part for part in address_parts if part])
  if not (business_name or business_start_date or address):
    return None
  return _DUAL.Bootstrap(
    business_name=business_name,
    business_start_date=business_start_date,
    address=address,
    address_street=_string(row.get("address_street")),
    address_city=_string(row.get("address_city")),
    address_state=_string(row.get("address_state")),
    address_zip=_string(row.get("address_zip")),
    address_country=_string(row.get("address_country")),
    private_state="",
  )


def _sql_json_value(value: Any) -> Any:
  if isinstance(value, (dict, list)):
    return json.dumps(value, ensure_ascii=False)
  return value


def _clone_source_into_target_draft(
  conn,
  *,
  source_row: Dict[str, Any],
  target_draft_id: str,
) -> None:
  now = _DUAL._eastern_now().strftime("%Y-%m-%d %H:%M:%S.%f")
  cur = conn.cursor()
  try:
    cur.execute(
      """
      UPDATE intake_consult_drafts
      SET
        status = %s,
        active_focus = %s,
        ops_confirmed = %s,
        market_confirmed = %s,
        people_confirmed = %s,
        financials_confirmed = %s,
        business_name = %s,
        business_address = %s,
        address_street = %s,
        address_city = %s,
        address_state = %s,
        address_zip = %s,
        address_country = %s,
        business_start_date = %s,
        messages_json = %s,
        operating_model_json = %s,
        target_market_json = %s,
        people_json = %s,
        financials_json = %s,
        marketing_model_json = %s,
        financials_year1_json = %s,
        realism_memo_json = %s,
        model_input_json = NULL,
        finmo_json = NULL,
        planning_run_json = %s,
        pending_ops_milestone_json = %s,
        fulfillment_json = %s,
        ops_finalize_proposed = %s,
        market_finalize_proposed = %s,
        people_finalize_proposed = %s,
        financials_finalize_proposed = %s,
        completed_at = %s,
        submitted_at = NULL,
        intake_submission_id = NULL,
        updated_at = %s
      WHERE draft_id = %s
      """,
      (
        "completed",
        "done",
        1 if bool(source_row.get("ops_confirmed")) else 0,
        1 if bool(source_row.get("market_confirmed")) else 0,
        1 if bool(source_row.get("people_confirmed")) else 0,
        1 if bool(source_row.get("financials_confirmed")) else 0,
        _string(source_row.get("business_name")) or None,
        _string(source_row.get("business_address")) or None,
        _string(source_row.get("address_street")) or None,
        _string(source_row.get("address_city")) or None,
        _string(source_row.get("address_state")) or None,
        _string(source_row.get("address_zip")) or None,
        _string(source_row.get("address_country")) or None,
        _string(source_row.get("business_start_date")) or None,
        _sql_json_value(source_row.get("messages_json")),
        _sql_json_value(source_row.get("operating_model_json")),
        _sql_json_value(source_row.get("target_market_json")),
        _sql_json_value(source_row.get("people_json")),
        _sql_json_value(source_row.get("financials_json")),
        _sql_json_value(source_row.get("marketing_model_json")),
        _sql_json_value(source_row.get("financials_year1_json")),
        _sql_json_value(source_row.get("realism_memo_json")),
        _sql_json_value(source_row.get("planning_run_json")),
        _sql_json_value(source_row.get("pending_ops_milestone_json")),
        _sql_json_value(source_row.get("fulfillment_json")),
        1 if bool(source_row.get("ops_finalize_proposed")) else 0,
        1 if bool(source_row.get("market_finalize_proposed")) else 0,
        1 if bool(source_row.get("people_finalize_proposed")) else 0,
        1 if bool(source_row.get("financials_finalize_proposed")) else 0,
        now,
        now,
        _string(target_draft_id),
      ),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _persist_reports(
  *,
  base_url: str,
  output_dir: str,
  persisted_output_dir: str,
  seed: str,
  bootstrap: Optional[Any],
  transcript: list[Dict[str, str]],
  draft_id: Optional[str],
  client_id: Optional[str],
  status: str,
  stop_reason: str,
  trace_file_name: Optional[str],
) -> None:
  written_at = _DUAL._eastern_now()
  artifact_seed = _DUAL._artifact_seed(seed=seed, draft_id=draft_id)
  path = _DUAL._save_run_report(
    output_dir=output_dir,
    seed=artifact_seed,
    bootstrap=bootstrap,
    transcript=transcript,
    draft_id=draft_id,
    status=status,
    stop_reason=stop_reason,
    written_at=written_at,
  )
  if path:
    print(f"Saved run report: {path}")
  persisted_path = _DUAL._save_persisted_state_report(
    base_url=base_url,
    output_dir=persisted_output_dir,
    seed=artifact_seed,
    bootstrap=bootstrap,
    draft_id=draft_id,
    client_id=client_id,
    status=status,
    stop_reason=stop_reason,
    written_at=written_at,
  )
  if persisted_path:
    print(f"Saved persisted state report: {persisted_path}")
  new_runner_path = _DUAL._save_new_runner_report(
    base_url=base_url,
    output_dir=_DUAL.DEFAULT_NEW_RUNNER_DIR,
    seed=artifact_seed,
    bootstrap=bootstrap,
    draft_id=draft_id,
    written_at=written_at,
  )
  if new_runner_path:
    print(f"Saved New Runner report: {new_runner_path}")
  new_runner_grid_path = _DUAL._save_new_runner_grid_report(
    base_url=base_url,
    output_dir=_DUAL.DEFAULT_NEW_RUNNER_DIR,
    seed=artifact_seed,
    draft_id=draft_id,
    written_at=written_at,
  )
  if new_runner_grid_path:
    print(f"Saved New Runner grid report: {new_runner_grid_path}")
  new_runner_solver_path = _DUAL._save_new_runner_solver_report(
    base_url=base_url,
    output_dir=_DUAL.DEFAULT_NEW_RUNNER_DIR,
    seed=artifact_seed,
    draft_id=draft_id,
    written_at=written_at,
  )
  if new_runner_solver_path:
    print(f"Saved New Runner solver report: {new_runner_solver_path}")
  if trace_file_name:
    print(f"Expected terminal log file: {os.path.join(_DUAL.DEFAULT_TERMINAL_LOGS_DIR, trace_file_name)}")


def main(argv: Optional[list[str]] = None) -> int:
  parser = argparse.ArgumentParser(
    description="Clone a persisted intake-complete draft into a fresh session and start system-run."
  )
  parser.add_argument("--client-id", default="", help="Persisted intake_consult_drafts.client_id. If a draft_id is accidentally passed here, the runner will auto-resolve it.")
  parser.add_argument("--draft-id", default="", help="Persisted intake_consult_drafts.draft_id")
  parser.add_argument("--base-url", default="http://127.0.0.1:5050")
  parser.add_argument("--output-dir", default=_DUAL.DEFAULT_TEST_RUNS_DIR)
  parser.add_argument("--persisted-output-dir", default=_DUAL.DEFAULT_TEST_RUNS_DATA_DIR)
  parser.add_argument("--seed", default="persisted-system-run")
  parser.add_argument("--no-trace-reset", action="store_true")
  args = parser.parse_args(argv)

  _load_env()

  transcript: list[Dict[str, str]] = []
  conn = None
  bootstrap = None
  source_draft_id: Optional[str] = None
  source_client_id: Optional[str] = _string(args.client_id)
  source_lookup_draft_id: Optional[str] = _string(args.draft_id)
  draft_id: Optional[str] = None
  client_id: Optional[str] = None
  trace_file_name: Optional[str] = None

  try:
    conn = _mysql_connect()
    source_row = _select_consult_row(conn, client_id=source_client_id or "", draft_id=source_lookup_draft_id or "")
    source_draft_id = _string(source_row.get("draft_id"))
    source_client_id = _string(source_row.get("client_id")) or source_client_id
    bootstrap = _bootstrap_from_row(source_row)

    if not source_draft_id:
      raise RuntimeError(f"Persisted row for client_id={source_client_id!r} is missing draft_id.")
    if str(source_row.get("active_focus") or "").strip().lower() != "done":
      raise RuntimeError(
        f"Source client_id={source_client_id!r} is not intake-complete yet (active_focus={_string(source_row.get('active_focus')) or 'missing'})."
      )

    print(f"Loaded source persisted draft: {source_draft_id}")
    print(f"Source Client ID: {source_client_id}")
    print(f"Business Name: {_string(source_row.get('business_name')) or '(missing)'}")
    print(
      "Source confirmed flags:",
      {
        "ops": bool(source_row.get("ops_confirmed")),
        "market": bool(source_row.get("market_confirmed")),
        "people": bool(source_row.get("people_confirmed")),
        "financials": bool(source_row.get("financials_confirmed")),
      },
    )

    session = _DUAL._post_json(f"{_string(args.base_url)}/api/intake-consult/session", {})
    draft_id = _string(session.get("draft_id"))
    client_id = _string(session.get("client_id"))
    if not draft_id or not client_id:
      raise RuntimeError(f"Failed to create fresh intake session: {session}")

    _clone_source_into_target_draft(conn, source_row=source_row, target_draft_id=draft_id)
    print(f"Cloned source intake state into new draft: {draft_id}")
    print(f"New Client ID: {client_id}")

    run_started_at = _DUAL._eastern_now()
    trace_file_name = _DUAL._build_run_artifact_filename(
      seed=_DUAL._artifact_seed(seed=_string(args.seed), draft_id=draft_id),
      written_at=run_started_at,
    )
    trace_headers = {
      "X-Solver-Trace-Run-Name": trace_file_name,
    }
    if not bool(args.no_trace_reset):
      trace_headers["X-Solver-Trace-Reset"] = "1"

    transcript.append(
      {
        "role": "system",
        "content": (
          f"Cloned source client {source_client_id} draft {source_draft_id} into fresh client {client_id} draft {draft_id} and started system-run."
        ),
        "focus": "system",
      }
    )

    draft_snapshot = _DUAL._get_json(f"{_string(args.base_url)}/api/intake-consult/draft", {"draft_id": draft_id})
    transcript.append(
      {
        "role": "system",
        "content": (
          f"Pre-run snapshot loaded. Active focus={_string(draft_snapshot.get('active_focus')) or 'unknown'}, "
          f"status={_string(draft_snapshot.get('status')) or 'unknown'}."
        ),
        "focus": "system",
      }
    )

    print("Starting system run from persisted state...")
    started = time.perf_counter()
    system_run_response = _DUAL._post_json(
      f"{_string(args.base_url)}/api/intake-consult/system-run",
      {"draft_id": draft_id, "client_id": client_id},
      timeout=None,
      headers=trace_headers,
    )
    system_run_ms = int(round((time.perf_counter() - started) * 1000.0))
    system_message = _string(system_run_response.get("assistant_message")) or "System run complete."
    transcript.append({"role": "assistant", "content": system_message, "focus": "system"})
    print(system_message)
    print(f"System run duration: {system_run_ms} ms")

    draft = _DUAL._get_json(f"{_string(args.base_url)}/api/intake-consult/draft", {"draft_id": draft_id})
    memo = _DUAL._parse_realism_memo(draft.get("realism_memo_json"))
    print(
      "Final flags:",
      {
        "ops_confirmed": draft.get("ops_confirmed"),
        "market_confirmed": draft.get("market_confirmed"),
        "people_confirmed": draft.get("people_confirmed"),
        "financials_confirmed": draft.get("financials_confirmed"),
        "realism_memo_status": memo.get("status"),
        "realism_memo_issue_count": len(memo.get("issues") or []),
      },
    )
    print(f"Draft ID: {draft_id}")
    _persist_reports(
      base_url=_string(args.base_url),
      output_dir=_string(args.output_dir),
      persisted_output_dir=_string(args.persisted_output_dir),
      seed=_string(args.seed),
      bootstrap=bootstrap,
      transcript=transcript,
      draft_id=draft_id,
      client_id=client_id,
      status="completed",
      stop_reason="system run complete",
      trace_file_name=trace_file_name,
    )
    return 0
  except Exception as exc:
    message = str(exc)
    transcript.append({"role": "assistant", "content": message, "focus": "system"})
    print(f"ERROR: {message}")
    if draft_id:
      _persist_reports(
        base_url=_string(args.base_url),
        output_dir=_string(args.output_dir),
        persisted_output_dir=_string(args.persisted_output_dir),
        seed=_string(args.seed),
        bootstrap=bootstrap,
        transcript=transcript,
        draft_id=draft_id,
        client_id=client_id,
        status="failed",
        stop_reason=message,
        trace_file_name=trace_file_name,
      )
    return 1
  finally:
    if conn is not None:
      try:
        conn.close()
      except Exception:
        pass


if __name__ == "__main__":
  raise SystemExit(main())
