"""Phase 9 P3.33 Phase 3 step 1 — Materialized cohort bands per planning run.

Persists the cohort_band_resolver's percentile output into the new SQL table
``post_intake_cohort_bands`` so the amalgamated GPT session (built in later
commits this phase) can return constraint bands inline in tool responses,
and so the bands a run was authored against are auditable after the fact.

This module does NOT replace cohort_band_resolver. It CALLS the resolver
per (section, lever, metric) and stores the result. Existing in-memory
callers continue to work unchanged; subsequent commits in Phase 3 retire
those callsites as their corresponding handlers are converted to tools.

Step 1 populates the ``drivers`` section (the 7 lever ids the resolver
already exposes via LEVER_TO_METRIC_COLUMN). Future Phase 3 commits add
``stage_ramp``, ``payroll``, ``capex_rd``, and ``balance_sheet`` sections
via ``_SECTION_LEVERS`` as their corresponding tools land, and at that
point ``_robust_clip`` plugs in the canonical economic envelopes (today's
``robust_bound_stage_ramp_contract`` for the stage_ramp section).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from client_intake_and_finmo.post_intake_solver.cohort_band_resolver import (  # type: ignore
  resolve_cohort_band,
)


_TABLE_NAME = "post_intake_cohort_bands"
_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NOT NULL,
  section VARCHAR(64) NOT NULL,
  lever_id VARCHAR(128) NOT NULL,
  metric_key VARCHAR(128) NOT NULL,
  metric_column VARCHAR(64) NULL,
  benchmark_min DECIMAL(18,6) NULL,
  benchmark_target DECIMAL(18,6) NULL,
  benchmark_max DECIMAL(18,6) NULL,
  robust_min DECIMAL(18,6) NULL,
  robust_max DECIMAL(18,6) NULL,
  naics_level_used TINYINT NULL,
  naics_prefix_used VARCHAR(8) NULL,
  cohort_size INT NULL,
  firm_count INT NULL,
  confidence_tier VARCHAR(16) NULL,
  cohort_table VARCHAR(16) NULL,
  data_source VARCHAR(64) NULL,
  resolved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (draft_id, planning_run_id, section, lever_id, metric_key),
  KEY ix_draft_run (draft_id, planning_run_id),
  KEY ix_section (section)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def ensure_cohort_bands_table(conn) -> None:
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


# Section -> [(lever_id, metric_key)]. Step 1 covers only ``drivers`` (the
# 7 ids cohort_band_resolver.LEVER_TO_METRIC_COLUMN maps natively). The
# remaining sections wire in alongside their corresponding tools in later
# Phase 3 commits.
_SECTION_LEVERS: Dict[str, List[Tuple[str, str]]] = {
  "drivers": [
    ("expenses::Cost of Goods Sold",          "expenses::Cost of Goods Sold"),
    ("expenses::Research & Development",      "expenses::Research & Development"),
    ("expenses::General & Administrative",    "expenses::General & Administrative"),
    ("expenses::Marketing",                   "expenses::Marketing"),
    ("balance_sheet::Accounts Receivable Days", "balance_sheet::Accounts Receivable Days"),
    ("balance_sheet::Accounts Payable Days",  "balance_sheet::Accounts Payable Days"),
    ("balance_sheet::Inventory Days",         "balance_sheet::Inventory Days"),
  ],
}


def _robust_clip(
  section: str,
  lever_id: str,
  lo: Optional[float],
  hi: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
  """Clip a cohort percentile band to a canonical economic envelope.

  Phase 3 step 1: pass-through. The ``stage_ramp`` section will use
  ``robust_bound_stage_ramp_contract`` (post_intake_contracts/runner.py)
  when that tool is built. The driver levers have no canonical envelope
  declared today, so we record the raw percentile bounds.
  """
  return lo, hi


def populate_cohort_bands_for_run(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  business_profile: Dict[str, Any],
  sections: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, int]]:
  """Resolve and persist cohort bands for the run.

  Returns ``{section: {"resolved": int, "skipped": int}}``. A lever is
  ``skipped`` when the resolver returns None (cohort too small at every
  widening tier); the caller can decide what fallback to use. Idempotent
  via ON DUPLICATE KEY UPDATE on (draft_id, planning_run_id, section,
  lever_id, metric_key).
  """
  ensure_cohort_bands_table(conn)
  draft_id = str(draft_id or "").strip()
  planning_run_id = str(planning_run_id or "").strip()
  if not draft_id or not planning_run_id:
    raise ValueError("draft_id and planning_run_id are required")

  target_sections = list(sections) if sections else list(_SECTION_LEVERS.keys())
  summary: Dict[str, Dict[str, int]] = {}
  now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
  cur = conn.cursor()
  try:
    for section in target_sections:
      levers = _SECTION_LEVERS.get(section) or []
      resolved = 0
      skipped = 0
      for lever_id, metric_key in levers:
        result = resolve_cohort_band(metric_key=metric_key, business_profile=business_profile)
        if result is None:
          skipped += 1
          continue
        robust_min, robust_max = _robust_clip(section, lever_id, result.benchmark_min, result.benchmark_max)
        cur.execute(
          f"""
          INSERT INTO {_TABLE_NAME}
            (draft_id, planning_run_id, section, lever_id, metric_key,
             metric_column, benchmark_min, benchmark_target, benchmark_max,
             robust_min, robust_max, naics_level_used, naics_prefix_used,
             cohort_size, firm_count, confidence_tier, cohort_table,
             data_source, resolved_at)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
          ON DUPLICATE KEY UPDATE
            metric_column=VALUES(metric_column),
            benchmark_min=VALUES(benchmark_min),
            benchmark_target=VALUES(benchmark_target),
            benchmark_max=VALUES(benchmark_max),
            robust_min=VALUES(robust_min),
            robust_max=VALUES(robust_max),
            naics_level_used=VALUES(naics_level_used),
            naics_prefix_used=VALUES(naics_prefix_used),
            cohort_size=VALUES(cohort_size),
            firm_count=VALUES(firm_count),
            confidence_tier=VALUES(confidence_tier),
            cohort_table=VALUES(cohort_table),
            data_source=VALUES(data_source),
            resolved_at=VALUES(resolved_at)
          """,
          (
            draft_id, planning_run_id, section, lever_id, metric_key,
            result.metric_column,
            result.benchmark_min, result.benchmark_target, result.benchmark_max,
            robust_min, robust_max,
            int(result.naics_level_used) if result.naics_level_used is not None else None,
            (result.naics_prefix_used or None),
            int(result.cohort_size) if result.cohort_size is not None else None,
            int(result.firm_count) if result.firm_count is not None else None,
            result.confidence_tier,
            result.cohort_table,
            result.data_source,
            now,
          ),
        )
        resolved += 1
      summary[section] = {"resolved": resolved, "skipped": skipped}
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return summary


def get_cohort_bands(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  section: Optional[str] = None,
) -> List[Dict[str, Any]]:
  """Raw row read. ``section=None`` returns every section for the run."""
  cur = conn.cursor(dictionary=True)
  try:
    if section:
      cur.execute(
        f"SELECT * FROM {_TABLE_NAME} "
        f"WHERE draft_id=%s AND planning_run_id=%s AND section=%s "
        f"ORDER BY lever_id",
        (draft_id, planning_run_id, section),
      )
    else:
      cur.execute(
        f"SELECT * FROM {_TABLE_NAME} "
        f"WHERE draft_id=%s AND planning_run_id=%s "
        f"ORDER BY section, lever_id",
        (draft_id, planning_run_id),
      )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return [dict(r) for r in rows]


def get_bands(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  section: str,
) -> Dict[str, Any]:
  """Tool-shaped getter — the call the amalgamated GPT session will make.

  Returns a flat dict::

    {
      "section": <section>,
      "draft_id": ..., "planning_run_id": ...,
      "count": <n>,
      "bands": {
        <lever_id>: {
          "metric_key": ..., "metric_column": ...,
          "benchmark_min": float|None, "benchmark_target": ..., "benchmark_max": ...,
          "robust_min": ..., "robust_max": ...,
          "confidence_tier": "high"|"medium"|"low",
          "cohort_size": int, "firm_count": int,
          "naics_level_used": int, "cohort_table": "edgar"|"alpha",
        },
        ...
      }
    }
  """
  rows = get_cohort_bands(conn, draft_id=draft_id, planning_run_id=planning_run_id, section=section)
  bands: Dict[str, Any] = {}
  for row in rows:
    lever_id = str(row.get("lever_id") or "")
    if not lever_id:
      continue
    bands[lever_id] = {
      "metric_key": row.get("metric_key"),
      "metric_column": row.get("metric_column"),
      "benchmark_min": _to_float(row.get("benchmark_min")),
      "benchmark_target": _to_float(row.get("benchmark_target")),
      "benchmark_max": _to_float(row.get("benchmark_max")),
      "robust_min": _to_float(row.get("robust_min")),
      "robust_max": _to_float(row.get("robust_max")),
      "confidence_tier": row.get("confidence_tier"),
      "cohort_size": row.get("cohort_size"),
      "firm_count": row.get("firm_count"),
      "naics_level_used": row.get("naics_level_used"),
      "cohort_table": row.get("cohort_table"),
    }
  return {
    "section": section,
    "draft_id": draft_id,
    "planning_run_id": planning_run_id,
    "count": len(bands),
    "bands": bands,
  }


def _to_float(v: Any) -> Optional[float]:
  if v is None:
    return None
  try:
    return float(v)
  except Exception:
    return None
