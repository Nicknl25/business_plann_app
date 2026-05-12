"""Phase 9 P3.9 — Per-run diagnostics persistence and assembly.

For every planning run, capture the diagnostic payload defined by the
directive (planning_mode, cash_strategy_name, business stage / name /
start_date, draft_id, acceptance gate score, full realism check list,
handler firing details, tool call counts, budget extension flag).

Persistence: INSERT-only into `post_intake_run_diagnostics` keyed by
(draft_id, planning_run_id). Never updates, never deletes. Each rerun
appends a new row keyed by the new planning_run_id. Aligns with
project-wide SQL discipline.

The workbook's Diagnostics sheet renders the most recent row for a
draft -- the workbook is a pure reflection, not a source of truth.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


_TABLE_NAME = "post_intake_run_diagnostics"
_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NOT NULL,
  business_name VARCHAR(255) NULL,
  business_naics_6 VARCHAR(6) NULL,
  business_stage VARCHAR(64) NULL,
  business_start_date VARCHAR(32) NULL,
  planning_mode VARCHAR(64) NULL,
  cash_strategy_name VARCHAR(64) NULL,
  acceptance_passed TINYINT(1) NULL,
  acceptance_score VARCHAR(16) NULL,
  handler_fired TINYINT(1) NULL,
  handler_status VARCHAR(64) NULL,
  handler_scope VARCHAR(32) NULL,
  tool_calls_used INT NULL,
  budget_extension_triggered TINYINT(1) NULL,
  diagnostics_json LONGTEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_draft_run (draft_id, planning_run_id),
  KEY ix_draft_id (draft_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _ensure_run_diagnostics_table(conn) -> None:
  cur = conn.cursor()
  try:
    cur.execute(_CREATE_TABLE_SQL)
    try:
      conn.commit()
    except Exception:
      pass
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _text(value: Any) -> str:
  return str(value or "").strip()


def _safe_bool(value: Any) -> Optional[bool]:
  if value is None:
    return None
  if isinstance(value, bool):
    return value
  if isinstance(value, (int, float)):
    return bool(value)
  s = str(value).strip().lower()
  if s in {"true", "1", "yes", "y"}: return True
  if s in {"false", "0", "no", "n"}: return False
  return None


# ----------------------------------------------------------------------------
# Payload assembly.
# ----------------------------------------------------------------------------


def _acceptance_score(verdict: Optional[Dict[str, Any]]) -> Tuple[Optional[bool], Optional[str]]:
  if not isinstance(verdict, dict):
    return None, None
  passed = _safe_bool(verdict.get("passed"))
  checks = verdict.get("checks") or []
  if not isinstance(checks, list):
    return passed, None
  total = len(checks)
  ok = sum(1 for c in checks if isinstance(c, dict) and bool(c.get("passed")))
  return passed, f"{ok}/{total}"


def _per_metric_summary(
  realism_memo_json: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  """Roll up the realism-gate line-level results into a per-metric
  pass/fail summary suitable for both SQL persistence and the workbook
  Diagnostics sheet.

  A metric is `passed=True` iff none of its result rows carry
  status='out_of_band_hard_fail'. status='out_of_band_warn' rolls up
  to passed=False as well (warnings are not catastrophic but they ARE
  band misses, so the diagnostic display flags them). All other
  statuses (in_band / skipped / silenced / muted_gpt_post_exhaustion)
  count as passed.
  """
  if not isinstance(realism_memo_json, dict):
    return []
  rg = realism_memo_json.get("realism_gate") or {}
  ll = (rg.get("line_level") if isinstance(rg, dict) else None) or {}
  results = ll.get("results") if isinstance(ll, dict) else None
  if not isinstance(results, list):
    return []
  by_metric: Dict[str, Dict[str, Any]] = {}
  fail_statuses = {"out_of_band_hard_fail", "out_of_band_warn"}
  for r in results:
    if not isinstance(r, dict):
      continue
    mk = _text(r.get("metric_key"))
    if not mk:
      continue
    status = _text(r.get("status")).lower()
    entry = by_metric.setdefault(mk, {
      "metric_key": mk,
      "passed": True,
      "row_count": 0,
      "hard_fail_count": 0,
      "warn_count": 0,
      "muted": False,
      "skipped_count": 0,
      "in_band_count": 0,
    })
    entry["row_count"] += 1
    if status == "out_of_band_hard_fail":
      entry["hard_fail_count"] += 1
      entry["passed"] = False
    elif status == "out_of_band_warn":
      entry["warn_count"] += 1
      entry["passed"] = False
    elif status == "in_band":
      entry["in_band_count"] += 1
    elif status == "skipped":
      entry["skipped_count"] += 1
    elif status == "muted_gpt_post_exhaustion":
      entry["muted"] = True
  return sorted(by_metric.values(), key=lambda d: d["metric_key"])


def build_run_diagnostics_payload(
  *,
  draft_row: Optional[Dict[str, Any]],
  planning_run_json: Optional[Dict[str, Any]],
  realism_memo_json: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  acceptance_verdict: Optional[Dict[str, Any]],
  draft_id: str,
  planning_run_id: Optional[str],
  cash_strategy_name: Optional[str] = None,
  workbook_path: Optional[str] = None,
) -> Dict[str, Any]:
  """Assemble the diagnostic payload for one planning run.

  Pulled from the various JSON blobs the orchestrator already produces.
  Returns a dict suitable for JSON serialization. The orchestrator
  passes this to `persist_run_diagnostics` and to the workbook builder.
  """
  draft_row = draft_row or {}
  pr = planning_run_json or {}
  pcc = (pr.get("post_cascade_completion") or {}) if isinstance(pr, dict) else {}
  ops = ops_json or {}
  fin = financials_json or {}

  rl = pcc.get("restoration_loop") or {}
  geh = pcc.get("gpt_exhaustion_handler") or {}
  cash_pass = pcc.get("cash_pass") or {}

  business_name = (
    _text(draft_row.get("business_name"))
    or _text(ops.get("business_name"))
    or _text((draft_row.get("model_input_json") or {}).get("business_name") if isinstance(draft_row.get("model_input_json"), dict) else None)
  )
  business_naics_6 = (
    _text(ops.get("business_naics_6"))
    or _text(draft_row.get("business_naics_6"))
  )
  business_stage = (
    _text(ops.get("business_stage"))
    or _text(draft_row.get("business_stage"))
  )
  business_start_date = (
    _text(ops.get("business_start_date"))
    or _text(draft_row.get("business_start_date"))
    or _text(draft_row.get("intake_start_date"))
  )

  planning_mode = (
    _text(pr.get("planning_mode"))
    or _text(draft_row.get("planning_mode"))
  )

  # Cash strategy name: orchestrator hands the name through cash_pass
  # under `cash_strategy_mode` or similar. Best-effort lookup.
  cs_name = cash_strategy_name
  if not cs_name:
    cs_name = (
      _text(cash_pass.get("cash_strategy_mode"))
      or _text(cash_pass.get("mode"))
      or _text(cash_pass.get("strategy"))
      or _text(((cash_pass.get("inputs") or {}).get("cash_strategy_mode") if isinstance(cash_pass.get("inputs"), dict) else None))
    )

  passed, score = _acceptance_score(acceptance_verdict)
  realism_checks = _per_metric_summary(realism_memo_json)

  handler_fired = bool(geh)
  handler_status = _text(geh.get("status")) if handler_fired else None
  handler_scope = _text(rl.get("scope")) or None
  tool_calls_used: Optional[int] = None
  budget_extension_triggered: Optional[bool] = None
  if handler_fired:
    prov = geh.get("provenance") or {}
    tcs = prov.get("tool_calling_session") or {}
    raw_tc = tcs.get("tool_calls_used")
    try:
      tool_calls_used = int(raw_tc) if raw_tc is not None else None
    except Exception:
      tool_calls_used = None
    budget_extension_triggered = _safe_bool(tcs.get("budget_extension_triggered"))

  payload: Dict[str, Any] = {
    "draft_id": draft_id,
    "planning_run_id": planning_run_id,
    "business_name": business_name,
    "business_naics_6": business_naics_6 or None,
    "business_stage": business_stage or None,
    "business_start_date": business_start_date or None,
    "planning_mode": planning_mode or None,
    "cash_strategy_name": cs_name or None,
    "acceptance_passed": passed,
    "acceptance_score": score,
    "realism_checks": realism_checks,
    "handler_fired": handler_fired,
    "handler_status": handler_status,
    "handler_scope": handler_scope,
    "tool_calls_used": tool_calls_used,
    "budget_extension_triggered": budget_extension_triggered,
    "workbook_path": workbook_path,
    "captured_at": datetime.utcnow().isoformat() + "Z",
  }
  return payload


# ----------------------------------------------------------------------------
# Persistence.
# ----------------------------------------------------------------------------


def persist_run_diagnostics(
  conn,
  *,
  payload: Dict[str, Any],
) -> bool:
  """INSERT-only persistence. Returns True if a new row was inserted,
  False if the (draft_id, planning_run_id) already had a row (INSERT
  IGNORE -- never overwrites). Aligns with project-wide SQL discipline:
  never DELETE, never UPDATE existing diagnostic rows.
  """
  if not isinstance(payload, dict):
    return False
  draft_id = _text(payload.get("draft_id"))
  planning_run_id = _text(payload.get("planning_run_id"))
  if not draft_id or not planning_run_id:
    return False
  _ensure_run_diagnostics_table(conn)
  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      INSERT IGNORE INTO {_TABLE_NAME} (
        draft_id, planning_run_id, business_name, business_naics_6,
        business_stage, business_start_date, planning_mode,
        cash_strategy_name, acceptance_passed, acceptance_score,
        handler_fired, handler_status, handler_scope, tool_calls_used,
        budget_extension_triggered, diagnostics_json
      ) VALUES (
        %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s
      )
      """,
      (
        draft_id, planning_run_id,
        payload.get("business_name"), payload.get("business_naics_6"),
        payload.get("business_stage"), payload.get("business_start_date"),
        payload.get("planning_mode"),
        payload.get("cash_strategy_name"),
        1 if payload.get("acceptance_passed") else (0 if payload.get("acceptance_passed") is False else None),
        payload.get("acceptance_score"),
        1 if payload.get("handler_fired") else 0,
        payload.get("handler_status"),
        payload.get("handler_scope"),
        payload.get("tool_calls_used"),
        1 if payload.get("budget_extension_triggered") else (0 if payload.get("budget_extension_triggered") is False else None),
        json.dumps(payload, ensure_ascii=False, default=str),
      ),
    )
    rowcount = int(cur.rowcount or 0)
    try:
      conn.commit()
    except Exception:
      pass
    return rowcount > 0
  finally:
    try:
      cur.close()
    except Exception:
      pass


def load_latest_diagnostics_for_draft(
  conn,
  *,
  draft_id: str,
) -> Optional[Dict[str, Any]]:
  """Fetch the MOST RECENT diagnostic row for a draft. Returns the
  parsed payload dict or None. Used by the workbook Diagnostics sheet
  to render the latest run's diagnostic snapshot.
  """
  draft_id = _text(draft_id)
  if not draft_id:
    return None
  try:
    _ensure_run_diagnostics_table(conn)
  except Exception:
    pass
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"SELECT diagnostics_json FROM {_TABLE_NAME} "
      f"WHERE draft_id = %s ORDER BY id DESC LIMIT 1",
      (draft_id,),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not row:
    return None
  try:
    return json.loads(row.get("diagnostics_json") or "{}")
  except Exception:
    return None
