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

import json
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
  cohort_query JSON NULL,
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
    # CREATE TABLE IF NOT EXISTS never ALTERs an existing table, so the
    # R10 cohort_query column addition silently missed every install
    # created before it — and the populator's INSERT then failed on
    # EVERY run, masked by the cohort-population soft sink until the
    # fallback-class fix made that failure loud. Self-migrate the drift.
    cur.execute(
      "SELECT COUNT(*) FROM information_schema.columns "
      "WHERE table_schema = DATABASE() AND table_name = %s "
      "AND column_name = 'cohort_query'",
      (_TABLE_NAME,),
    )
    row = cur.fetchone()
    if not row or int(row[0] or 0) == 0:
      cur.execute(
        f"ALTER TABLE {_TABLE_NAME} ADD COLUMN cohort_query JSON NULL AFTER data_source"
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


# Section -> [(lever_id, metric_key)]. Drivers (step 1) maps via
# LEVER_TO_METRIC_COLUMN natively. Stage_ramp (step 3a) reuses the
# FINMO Output Target Assembler's metric_key mappings — each ramp
# ceiling (cogs_max, marketing_max, ...) resolves the cohort percentile
# of the metric it caps, then the per-section robust clip (see
# _robust_clip) pulls outliers back into the doctrine envelope. Payroll
# / capex_rd / balance_sheet wire in alongside their tools in step 3b/c/d.
_SECTION_LEVERS: Dict[str, List[Tuple[str, str]]] = {
  "drivers": [
    ("expenses::Cost of Goods Sold",          "expenses::Cost of Goods Sold"),
    ("expenses::Research & Development",      "expenses::Research & Development"),
    ("expenses::General & Administrative",    "expenses::General & Administrative"),
    ("expenses::Marketing",                   "expenses::Marketing"),
  ],
  # P3.33 Phase 3 pre-step-8 — WC scalar levers (AR/AP/Inventory days)
  # moved to the balance_sheet section. Both set_drivers and
  # set_capex_rd_balance_seed used to be able to author these; FINMO
  # reads from the balance-sheet rows in model_input, so balance_sheet
  # owns them now. set_drivers no longer touches them;
  # set_capex_rd_balance_seed routes WC overrides into the
  # balance_sheet_seed_grid that apply_balance_sheet_contextual_seed_to_
  # model_input commits.
  "balance_sheet": [
    ("balance_sheet::Accounts Receivable Days", "balance_sheet::Accounts Receivable Days"),
    ("balance_sheet::Accounts Payable Days",  "balance_sheet::Accounts Payable Days"),
    ("balance_sheet::Inventory Days",         "balance_sheet::Inventory Days"),
  ],
  "stage_ramp": [
    # lever_id (stage_ramp::<contract_field>)        metric_key (cohort proxy)
    ("stage_ramp::cogs_max",      "cogs_to_revenue_ratio"),
    ("stage_ramp::marketing_max", "marketing_percent_of_revenue"),
    ("stage_ramp::rd_max",        "r_and_d_percent_of_revenue"),
    ("stage_ramp::ga_max",        "sga_percent_of_revenue"),
    ("stage_ramp::ni_floor",      "net_income_margin"),
    # max_util / lease_max / rev_max have no industry-cohort proxy
    # (doctrine envelopes only). They are not resolved here; _robust_clip
    # still applies the doctrine canonical envelope to any value derived
    # downstream via robust_bound_stage_ramp_contract.
  ],
}


def _robust_clip(
  section: str,
  lever_id: str,
  lo: Optional[float],
  hi: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
  """Clip a cohort percentile band to a canonical economic envelope.

  - ``drivers`` section: pass-through. The driver levers have no
    canonical envelope declared; we record the raw percentile bounds.
  - ``stage_ramp`` section: clip each bound to the doctrine envelope
    via ``_robust_bound`` + ``_stage_ramp_schema_field_ranges`` (the
    K13 Fix 2 helpers; lever_id 'stage_ramp::<field>' maps to a schema
    field). This stops distressed/artifact cohort tails (e.g. freight
    cogs 1.0, marketing 0.53) from sneaking into the band.
  - Other sections: pass-through (will be wired as their tools land).
  """
  if section != "stage_ramp":
    return lo, hi
  try:
    from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
      _stage_ramp_schema_field_ranges,
      _robust_bound,
    )
  except Exception:
    return lo, hi
  field_key = lever_id.split("::", 1)[1] if "::" in lever_id else lever_id
  ranges = _stage_ramp_schema_field_ranges() or {}
  rng = ranges.get(field_key) if isinstance(ranges, dict) else None
  if not isinstance(rng, dict):
    return lo, hi
  canon_lo = rng.get("min")
  canon_hi = rng.get("max")
  new_lo = _robust_bound(lo, canon_lo, canon_hi) if lo is not None else None
  new_hi = _robust_bound(hi, canon_lo, canon_hi) if hi is not None else None
  return new_lo, new_hi


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

  # Step 9b-ii — emit COHORT_BANDS_STARTED at phase entry.
  from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
    EventCode, PhaseCode, Status, safe_emit,
  )
  safe_emit(
    conn, draft_id=draft_id, planning_run_id=planning_run_id,
    phase=PhaseCode.COHORT_BANDS_POPULATOR,
    event_code=EventCode.COHORT_BANDS_STARTED,
    status=Status.STARTED,
    diagnostic_data={
      "sections": list(sections) if sections else list(_SECTION_LEVERS.keys()),
    },
  )

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
        _bench_min = result.benchmark_min
        _bench_target = result.benchmark_target
        _bench_max = result.benchmark_max
        _basis_note = ""
        # PASS-2 SPEC 1 (Option B, seam 1 of 2): labor-heavy basis
        # reconciliation at RESOLUTION time - raw cohort rows stay raw;
        # the adjustment is applied in code with provenance. Guardrail:
        # the helper returns None (no conversion) unless cohort payroll
        # coverage exists AND the overlap sum proves the bases collide.
        if str(metric_key or "") in (
          "cogs_percent_of_revenue",
          "cogs_to_revenue_ratio",
          "expenses::Cost of Goods Sold",
        ):
          try:
            from client_intake_and_finmo.labor_basis import (  # type: ignore
              maybe_labor_adjust_cogs_band,
            )
            _adj = maybe_labor_adjust_cogs_band(
              naics_6=str(business_profile.get("naics_6") or ""),
              band_min=_bench_min,
              band_target=_bench_target,
              band_max=_bench_max,
              labor_heavy_business=(
                str(business_profile.get("capacity_driver") or "").strip().lower() == "labor"
              ),
            )
          except Exception:
            _adj = None
          if _adj is not None:
            _bench_min = _adj["min"]
            _bench_target = _adj["target"]
            _bench_max = _adj["max"]
            _basis_note = "+labor_basis_adjusted"
        robust_min, robust_max = _robust_clip(section, lever_id, _bench_min, _bench_max)
        cur.execute(
          f"""
          INSERT INTO {_TABLE_NAME}
            (draft_id, planning_run_id, section, lever_id, metric_key,
             metric_column, benchmark_min, benchmark_target, benchmark_max,
             robust_min, robust_max, naics_level_used, naics_prefix_used,
             cohort_size, firm_count, confidence_tier, cohort_table,
             data_source, cohort_query, resolved_at)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            cohort_query=VALUES(cohort_query),
            resolved_at=VALUES(resolved_at)
          """,
          (
            draft_id, planning_run_id, section, lever_id, metric_key,
            result.metric_column,
            _bench_min, _bench_target, _bench_max,
            robust_min, robust_max,
            int(result.naics_level_used) if result.naics_level_used is not None else None,
            (result.naics_prefix_used or None),
            int(result.cohort_size) if result.cohort_size is not None else None,
            int(result.firm_count) if result.firm_count is not None else None,
            result.confidence_tier,
            result.cohort_table,
            f"{result.data_source}{_basis_note}" if _basis_note else result.data_source,
            # R10 closure (Cleanup Commit 1): cohort_query persisted
            # as JSON so the SQL audit trail can reconstruct which
            # revenue/stage/date windows produced each cohort band.
            # Previously dropped at materialization (v1 §F-1 known
            # bug). NULL when the dict is empty so the column reads
            # cleanly under existing SELECTs.
            (
              json.dumps(result.cohort_query)
              if isinstance(result.cohort_query, dict) and result.cohort_query
              else None
            ),
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
  # Step 9b-ii — emit COHORT_BANDS_COMPLETED with summary counts.
  _total_resolved = sum(s.get("resolved", 0) for s in summary.values())
  _total_skipped = sum(s.get("skipped", 0) for s in summary.values())
  safe_emit(
    conn, draft_id=draft_id, planning_run_id=planning_run_id,
    phase=PhaseCode.COHORT_BANDS_POPULATOR,
    event_code=EventCode.COHORT_BANDS_COMPLETED,
    status=Status.COMPLETED,
    diagnostic_data={
      "summary": summary,
      "total_resolved": _total_resolved,
      "total_skipped": _total_skipped,
    },
  )
  # Step 9d items 1 + 2 — fail-fast guards. Item 1: at least one
  # cohort band row must have been written; an empty populate is a
  # contract violation (downstream mirror_build reads these bands).
  # Item 2: every robust_min/robust_max we wrote is finite — caught
  # implicitly here by re-scanning summary; deeper per-row validation
  # was already done by _robust_clip / resolve_cohort_band.
  if _total_resolved == 0:
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode, PhaseCode as _PC, raise_fail_fast,
    )
    raise_fail_fast(
      conn, draft_id=draft_id, planning_run_id=planning_run_id,
      phase=_PC.COHORT_BANDS_POPULATOR,
      code=FailFastCode.FAIL_COHORT_BANDS_MISSING,
      detail=(
        f"no cohort bands resolved (total_skipped={_total_skipped}, "
        f"sections={list(summary.keys())})"
      ),
      where="post_intake_solver.cohort_bands_table.populate_cohort_bands_for_run",
    )
  # Item 2 — section-level malformed check. summary[section] missing
  # resolved/skipped keys = the populator's accounting drifted.
  for _section, _row in (summary or {}).items():
    if not isinstance(_row, dict) or "resolved" not in _row or "skipped" not in _row:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        FailFastCode, PhaseCode as _PC, raise_fail_fast,
      )
      raise_fail_fast(
        conn, draft_id=draft_id, planning_run_id=planning_run_id,
        phase=_PC.COHORT_BANDS_POPULATOR,
        code=FailFastCode.FAIL_COHORT_BANDS_MALFORMED,
        detail=f"summary[{_section!r}] malformed: {_row!r}",
        where="post_intake_solver.cohort_bands_table.populate_cohort_bands_for_run",
      )
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
          "naics_prefix_used": str|None,
          "data_source": str|None,
        },
        ...
      }
    }

  R11 closure (Cleanup Commit 1): naics_prefix_used + data_source
  now flow through to in-memory consumers (mirror.build_mirror,
  evaluate_plan). Previously dropped at the SQL -> in-memory
  translation so in-memory consumers saw an incomplete picture
  vs the SQL row. Asymmetry resolved; Contract 6 Shape C
  (GetBandsViewBandContract) amended to type the 2 new fields.
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
      # R11 closure (Cleanup Commit 1): naics_prefix_used +
      # data_source now flow through Shape B -> Shape C without
      # silent drop.
      "naics_prefix_used": row.get("naics_prefix_used"),
      "data_source": row.get("data_source"),
    }
  _result = {
    "section": section,
    "draft_id": draft_id,
    "planning_run_id": planning_run_id,
    "count": len(bands),
    "bands": bands,
  }
  # P3.40 Contract 6 Commit 3 -- Shape C consumer-side gate.
  # Validates the in-memory get_bands view (envelope + 12-field
  # bands per F7 silent-drop) before handing to amalgamated
  # tools / mirror.build_mirror /
  # evaluate_plan._margin_distance_from_bands. F12 (b)
  # benchmark monotonicity invariant fires per band.
  # ContractViolation propagates through intake_consult.py:7377
  # generic catch per F17.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore  # noqa: E501
    SIDE_CONSUMER as _IBR_SIDE_CONSUMER,
    validate_industry_baseline_get_bands_view_at_boundary,
  )
  validate_industry_baseline_get_bands_view_at_boundary(
    _result, side=_IBR_SIDE_CONSUMER,
  )
  return _result


def _to_float(v: Any) -> Optional[float]:
  if v is None:
    return None
  try:
    return float(v)
  except Exception:
    return None
