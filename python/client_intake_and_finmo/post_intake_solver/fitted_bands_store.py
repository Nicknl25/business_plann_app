"""Persistence for business-fitted, per-quarter bands (band-fitting transform).

The band-fitting transform (post_intake_headcount.band_fitting) produces, per
metric (COGS/Marketing/G&A/R&D %-of-revenue + net_income_margin), a per-quarter
TARGET trajectory fitted to the specific business plus the industry envelope it
was validated against. Those fitted bands are computed once (after revenue
authoring) and then read across stages — by the cascade's lever_margins
(post_intake_amalgamated.evaluate_plan) and the realism gate — so they must
persist for the run.

One JSON row per (draft_id, planning_run_id):
  fitted_json   = {metric_key: {quarter_str: target_value}}   (1..20)
  envelope_json = {metric_key: {min, target, max}}            (the scaled bounds)
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

_TABLE_NAME = "post_intake_fitted_bands"
_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NOT NULL,
  fitted_json JSON NOT NULL,
  envelope_json JSON NULL,
  resolved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (draft_id, planning_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def ensure_fitted_bands_table(conn) -> None:
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


def store_fitted_bands(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  fitted: Dict[str, Dict[int, float]],
  envelope: Optional[Dict[str, Dict[str, float]]] = None,
) -> None:
  """Upsert the fitted per-quarter bands for a run. Keys are stringified so the
  JSON round-trips cleanly (read side coerces quarters back to int)."""
  if not draft_id or not planning_run_id or not isinstance(fitted, dict):
    return
  ensure_fitted_bands_table(conn)
  fitted_str = {
    str(metric): {str(q): float(v) for q, v in (traj or {}).items()}
    for metric, traj in fitted.items()
    if isinstance(traj, dict)
  }
  fitted_json = json.dumps(fitted_str)
  envelope_json = json.dumps(envelope or {})
  cur = conn.cursor()
  try:
    cur.execute(
      f"INSERT INTO {_TABLE_NAME} (draft_id, planning_run_id, fitted_json, envelope_json) "
      f"VALUES (%s, %s, %s, %s) "
      f"ON DUPLICATE KEY UPDATE fitted_json=VALUES(fitted_json), "
      f"envelope_json=VALUES(envelope_json), resolved_at=CURRENT_TIMESTAMP",
      (draft_id, planning_run_id, fitted_json, envelope_json),
    )
    try:
      conn.commit()
    except Exception:
      pass
  finally:
    try:
      cur.close()
    except Exception:
      pass


def get_fitted_bands(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
) -> Dict[str, Any]:
  """Return ``{"fitted": {metric: {q(int): value}}, "envelope": {...}}`` or
  ``{}`` when none stored. Never raises — band-fitting is a soft enhancement."""
  if not draft_id or not planning_run_id:
    return {}
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"SELECT fitted_json, envelope_json FROM {_TABLE_NAME} "
      f"WHERE draft_id=%s AND planning_run_id=%s",
      (draft_id, planning_run_id),
    )
    row = cur.fetchone()
  except Exception:
    return {}
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not row:
    return {}
  def _load(blob):
    if isinstance(blob, (dict, list)):
      return blob
    try:
      return json.loads(blob) if blob else {}
    except Exception:
      return {}
  fitted_raw = _load(row.get("fitted_json"))
  envelope = _load(row.get("envelope_json"))
  fitted: Dict[str, Dict[int, float]] = {}
  for metric, traj in (fitted_raw or {}).items():
    if not isinstance(traj, dict):
      continue
    qmap: Dict[int, float] = {}
    for q_str, v in traj.items():
      try:
        qmap[int(q_str)] = float(v)
      except (TypeError, ValueError):
        continue
    if qmap:
      fitted[str(metric)] = qmap
  return {"fitted": fitted, "envelope": envelope or {}}


__all__ = ["ensure_fitted_bands_table", "store_fitted_bands", "get_fitted_bands"]
