from __future__ import annotations

import os
import threading
import copy
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set


try:
  from .intake_submission import get_mysql_connection
except Exception:  # pragma: no cover - supports legacy sys.path imports
  from intake_submission import get_mysql_connection  # type: ignore


_MAPPING_TABLE_NAME = "post_intak_mapping_lookup"
_FINMO_ROW_PREFIX = "finmo_json.quarter_rows[*]."
_REVENUE_PATTERN_PREFIX = "revenue::*::*::"
_ENSURE_MAPPING_TABLE_READY = False
_ENSURE_MAPPING_TABLE_LOCK = threading.Lock()
_POST_INTAKE_PLANNING_MODES = {"turnaround", "normalize", "rebalance"}


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _clean_bool(value: Any, *, default: bool = False) -> bool:
  raw = _clean_text(value).lower()
  if not raw:
    return bool(default)
  return raw in {"1", "true", "yes", "y", "active"}


def _split_tokens(value: Any) -> List[str]:
  raw = _clean_text(value).lower()
  if not raw:
    return []
  normalized = raw.replace(";", "|").replace(",", "|")
  return [item.strip() for item in normalized.split("|") if item.strip()]


def stage_planning_ramp_policy(
  *,
  stage_family: Any,
  planning_mode: Any,
  planning_mode_reason: Any = "",
  business_stage: Any = "",
) -> Dict[str, Any]:
  """Deterministic lifecycle policy shared by ramp GPT, validation, and quarter-grid."""
  family = _clean_text(stage_family).lower() or "operational"
  raw_mode = _clean_text(planning_mode).lower()
  mode = raw_mode if raw_mode in _POST_INTAKE_PLANNING_MODES else "turnaround"
  reason = _clean_text(planning_mode_reason).lower()
  normalized_stage = _clean_text(business_stage).lower()
  distress_tokens = ("distress", "rescue", "insolven", "survival", "turnaround")
  explicit_distress_context = bool(
    mode == "turnaround"
    or any(token in reason for token in distress_tokens)
  )

  policy: Dict[str, Any] = {
    "policy_version": "stage_planning_ramp_policy_v1",
    "business_stage": normalized_stage,
    "stage_family": family,
    "planning_mode": mode,
    "planning_mode_reason": reason,
    "explicit_distress_context": explicit_distress_context,
    "profitability_postures": ["loss_allowed", "improving_losses", "near_breakeven", "positive"],
    "stage_rules": [],
    "validator_rules": {
      "q10_min_net_income_margin_floor": -0.02,
      "q11_to_q20_min_net_income_margin_floor": 0.0,
    },
  }

  if family == "startup":
    policy["stage_rules"] = [
      "Pre-revenue is a binding lifecycle state, not descriptive background.",
      "Q1-Q4 must read like launch and ramp, not a mature operating run-rate.",
      "Do not start Q1 at or near the late-horizon revenue, utilization, or capacity run-rate.",
      "Capacity may exist ahead of demand, but revenue should come from staged utilization and price realization rather than instant full-scale operations.",
      "Revenue, utilization, capacity, staffing support, capex, and profitability must ramp together.",
      "Because Payroll is derived from revenue using OEWS/FTE logic, revenue must not ramp faster than the deterministic stage_ramp_contract allows.",
      "Early losses or modest profitability may be realistic; instant mature profitability is not the goal.",
    ]
    policy["early_revenue_share_ceiling_of_late_run_rate"] = {
      "Q1": 0.25,
      "Q2": 0.40,
      "Q3": 0.60,
      "Q4": 0.80,
    }
  elif family == "early":
    policy["stage_rules"] = [
      "Early-stage is a binding lifecycle state, not descriptive background.",
      "Q1-Q4 should still show a ramp and absorption curve.",
      "Do not jump immediately to a mature run-rate without operating evidence.",
      "Losses may be acceptable early if funded and improving.",
      "Loss_allowed posture is not acceptable after Q8; by then losses must be improving or better.",
    ]
    policy["early_revenue_share_ceiling_of_late_run_rate"] = {
      "Q1": 0.55,
      "Q2": 0.70,
      "Q3": 0.85,
    }
    policy["validator_rules"]["loss_allowed_latest_quarter"] = 8
  elif explicit_distress_context:
    policy["stage_rules"] = [
      "Treat the business as already operating but in turnaround/distress posture.",
      "Losses may exist early, but they must improve under the ramp contract rather than persist as an unresolved mature loss state.",
      "Do not model a mature company as a launch-stage startup; operational scale already exists even when profitability is damaged.",
      "Capacity expansion must be supported by operating recovery and stage reality.",
    ]
    policy["validator_rules"]["operational_distress_allows_early_losses"] = True
  else:
    policy["profitability_postures"] = ["near_breakeven", "positive"]
    policy["stage_rules"] = [
      "Treat the business as already operating unless facts contradict that.",
      "Avoid fantasy resets; mature operating losses are not acceptable without explicit turnaround/distress planning mode.",
      "The operating path should generally begin near breakeven or profitable; do not model an established company like a startup launch.",
      "By Q5 the plan must use a positive profitability posture.",
      "Capacity expansion must be supported by operating earnings and stage reality.",
    ]
    policy["validator_rules"].update(
      {
        "operational_requires_nonnegative_from_q1": True,
        "operational_requires_positive_from_q5": True,
        "q1_to_q20_min_net_income_margin_floor": 0.0,
        "q5_to_q20_min_net_income_margin_floor": 0.02,
      }
    )
  return policy


def _normalized_metric_id_from_field(financial_model_field: Any) -> str:
  field = _clean_text(financial_model_field)
  if not field.startswith(_FINMO_ROW_PREFIX):
    return ""
  metric_name = field[len(_FINMO_ROW_PREFIX):].strip().lower()
  return metric_name


def _normalized_lookup_key(lever_id: Any) -> str:
  raw = _clean_text(lever_id)
  if raw.startswith("revenue::"):
    if raw.endswith("::Capacity"):
      return f"{_REVENUE_PATTERN_PREFIX}Capacity"
    if raw.endswith("::Unit Price"):
      return f"{_REVENUE_PATTERN_PREFIX}Unit Price"
    if raw.endswith("::Utilization"):
      return f"{_REVENUE_PATTERN_PREFIX}Utilization"
  return raw


def _ensure_env_loaded() -> None:
  if os.getenv("MYSQL_HOST") and os.getenv("MYSQL_USER") and (os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE")):
    return
  env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
  if not os.path.exists(env_path):
    return
  try:
    with open(env_path, "r", encoding="utf-8") as handle:
      for line in handle:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
          continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
  except Exception:
    return


def _ensure_mapping_lookup_table(conn) -> None:
  global _ENSURE_MAPPING_TABLE_READY
  if _ENSURE_MAPPING_TABLE_READY:
    return
  with _ENSURE_MAPPING_TABLE_LOCK:
    if _ENSURE_MAPPING_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MAPPING_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          lever_id VARCHAR(255) NOT NULL,
          driver_category VARCHAR(64) NOT NULL,
          target_driver VARCHAR(128) NOT NULL,
          model_input_field LONGTEXT NOT NULL,
          financial_model_field VARCHAR(255) NOT NULL,
          impact_type VARCHAR(32) NOT NULL,
          post_intake_issue_codes LONGTEXT NULL,
          post_intake_phase VARCHAR(32) NOT NULL,
          control_owner VARCHAR(32) NOT NULL,
          value_kind VARCHAR(32) NOT NULL,
          input_semantics VARCHAR(64) NOT NULL,
          driver_bundle VARCHAR(64) NULL,
          cash_strategy_role VARCHAR(64) NULL,
          targeting_allowed TINYINT(1) NOT NULL DEFAULT 0,
          diagnostic_only TINYINT(1) NOT NULL DEFAULT 0,
          mapping_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intak_mapping_lookup_lever (lever_id),
          KEY idx_post_intak_mapping_lookup_target_driver (target_driver),
          KEY idx_post_intak_mapping_lookup_phase (post_intake_phase),
          KEY idx_post_intak_mapping_lookup_status (mapping_status),
          KEY idx_post_intak_mapping_lookup_cash_role (cash_strategy_role)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      conn.commit()
      _ENSURE_MAPPING_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


@lru_cache(maxsize=1)
def load_post_intake_driver_target_mapping_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_mapping_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          lever_id,
          driver_category,
          target_driver,
          model_input_field,
          financial_model_field,
          impact_type,
          post_intake_issue_codes,
          post_intake_phase,
          control_owner,
          value_kind,
          input_semantics,
          driver_bundle,
          cash_strategy_role,
          targeting_allowed,
          diagnostic_only,
          mapping_status,
          notes
        FROM {_MAPPING_TABLE_NAME}
        ORDER BY id ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    lever_id = _clean_text(raw_row.get("lever_id"))
    if not lever_id:
      continue
    row = {
      "lever_id": lever_id,
      "driver_category": _clean_text(raw_row.get("driver_category")).lower(),
      "target_driver": _clean_text(raw_row.get("target_driver")),
      "model_input_field": _clean_text(raw_row.get("model_input_field")),
      "financial_model_field": _clean_text(raw_row.get("financial_model_field")),
      "impact_type": _clean_text(raw_row.get("impact_type")).lower(),
      "post_intake_issue_codes": _split_tokens(raw_row.get("post_intake_issue_codes")),
      "post_intake_phase": _clean_text(raw_row.get("post_intake_phase")).lower(),
      "control_owner": _clean_text(raw_row.get("control_owner")).lower(),
      "value_kind": _clean_text(raw_row.get("value_kind")).lower(),
      "input_semantics": _clean_text(raw_row.get("input_semantics")).lower(),
      "driver_bundle": _clean_text(raw_row.get("driver_bundle")).lower(),
      "cash_strategy_role": _clean_text(raw_row.get("cash_strategy_role")).lower(),
      "targeting_allowed": _clean_bool(raw_row.get("targeting_allowed")),
      "diagnostic_only": _clean_bool(raw_row.get("diagnostic_only")),
      "mapping_status": _clean_text(raw_row.get("mapping_status")).lower() or "active",
      "notes": _clean_text(raw_row.get("notes")),
    }
    row["target_metric_name"] = _normalized_metric_id_from_field(row.get("financial_model_field"))
    row["lookup_lever_id"] = _normalized_lookup_key(lever_id)
    rows.append(row)
  if not rows:
    raise RuntimeError(f"{_MAPPING_TABLE_NAME}_empty: post-intake mapping lookup table has no rows")
  return rows


def _active_mapping_rows() -> List[Dict[str, Any]]:
  return [
    dict(row)
    for row in load_post_intake_driver_target_mapping_rows()
    if _clean_text(row.get("mapping_status")).lower() == "active"
  ]


def _phase_matches(row: Dict[str, Any], phase: Any = None) -> bool:
  requested = _clean_text(phase).lower()
  if not requested:
    return True
  row_phase = _clean_text(row.get("post_intake_phase")).lower()
  return row_phase in {requested, "both"}


class PostIntakeMappingLookup:
  """Single gateway for the SQL-backed post-intake mapping table."""

  def __init__(self, rows: Iterable[Dict[str, Any]]) -> None:
    self._rows = [dict(row) for row in rows if isinstance(row, dict)]
    self._active_rows = [
      dict(row)
      for row in self._rows
      if _clean_text(row.get("mapping_status")).lower() == "active"
    ]
    self._by_lookup_lever: Dict[str, Dict[str, Any]] = {}
    for row in self._active_rows:
      lookup_key = _clean_text(row.get("lookup_lever_id"))
      if lookup_key and lookup_key not in self._by_lookup_lever:
        self._by_lookup_lever[lookup_key] = dict(row)

  def rows(self, *, active_only: bool = True, phase: Any = None) -> List[Dict[str, Any]]:
    source_rows = self._active_rows if active_only else self._rows
    return [
      dict(row)
      for row in source_rows
      if _phase_matches(row, phase)
    ]

  def entry_for_lever(self, lever_id: Any, *, required: bool = False) -> Optional[Dict[str, Any]]:
    lookup_key = _normalized_lookup_key(lever_id)
    entry = self._by_lookup_lever.get(lookup_key)
    if isinstance(entry, dict):
      return dict(entry)
    if required:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_lever: "
        f"{_clean_text(lever_id) or 'missing'}"
      )
    return None

  def lever_allowed_for_issue(
    self,
    lever_id: Any,
    issue_code: Any,
    *,
    phase: Any = None,
  ) -> bool:
    issue = _clean_text(issue_code).lower()
    if not issue:
      return False
    entry = self.entry_for_lever(lever_id)
    if not isinstance(entry, dict):
      return False
    if issue not in set(entry.get("post_intake_issue_codes") or []):
      return False
    if bool(entry.get("diagnostic_only")):
      return False
    return _phase_matches(entry, phase)

  def target_metric_for_lever(self, lever_id: Any, *, required: bool = False) -> str:
    entry = self.entry_for_lever(lever_id, required=required)
    metric_name = _clean_text((entry or {}).get("target_metric_name")).lower()
    if required and not metric_name:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_target_metric: "
        f"{_clean_text(lever_id) or 'missing'}"
      )
    return metric_name

  def target_metrics_for_levers(self, lever_ids: Optional[Iterable[Any]]) -> List[str]:
    ordered: List[str] = []
    for lever_id in (lever_ids or []):
      metric_name = self.target_metric_for_lever(lever_id)
      if metric_name and metric_name not in ordered:
        ordered.append(metric_name)
    return ordered

  def target_metric_ids(
    self,
    *,
    phase: Any = "convergence",
    targeting_allowed_only: bool = True,
  ) -> List[str]:
    ordered: List[str] = []
    for row in self.rows(active_only=True, phase=phase):
      if targeting_allowed_only and not bool(row.get("targeting_allowed")):
        continue
      if bool(row.get("diagnostic_only")):
        continue
      metric_name = _clean_text(row.get("target_metric_name")).lower()
      if metric_name and metric_name not in ordered:
        ordered.append(metric_name)
    return ordered

  def rows_for_issue(self, issue_code: Any, *, phase: Any = None) -> List[Dict[str, Any]]:
    normalized_issue = _clean_text(issue_code).lower()
    if not normalized_issue:
      return []
    return [
      dict(row)
      for row in self.rows(active_only=True, phase=phase)
      if normalized_issue in set(row.get("post_intake_issue_codes") or [])
      and not bool(row.get("diagnostic_only"))
    ]

  def lever_ids_for_issue(self, issue_code: Any, *, phase: Any = None) -> List[str]:
    ordered: List[str] = []
    for row in self.rows_for_issue(issue_code, phase=phase):
      lever_id = _clean_text(row.get("lever_id"))
      if lever_id and lever_id not in ordered:
        ordered.append(lever_id)
    return ordered

  def target_metrics_for_issue(self, issue_code: Any, *, phase: Any = None) -> List[str]:
    return self.target_metrics_for_levers(
      self.lever_ids_for_issue(issue_code, phase=phase)
    )

  def issue_candidate_lever_ids(
    self,
    issue_code: Any,
    *,
    preferred_lever_ids: Optional[Iterable[Any]] = None,
    phase: Any = None,
    fallback_to_table: bool = True,
  ) -> List[str]:
    ordered: List[str] = []
    issue = _clean_text(issue_code).lower()
    if not issue:
      return ordered
    for lever_id in (preferred_lever_ids or []):
      normalized_lever = _clean_text(lever_id)
      if (
        normalized_lever
        and self.lever_allowed_for_issue(normalized_lever, issue, phase=phase)
        and normalized_lever not in ordered
      ):
        ordered.append(normalized_lever)
    if fallback_to_table and not ordered:
      for lever_id in self.lever_ids_for_issue(issue, phase=phase):
        if lever_id and lever_id not in ordered:
          ordered.append(lever_id)
    return ordered

  def issue_mapping_contract(
    self,
    issue_code: Any,
    *,
    preferred_lever_ids: Optional[Iterable[Any]] = None,
    phase: Any = None,
    allowed_target_metric_names: Optional[Iterable[Any]] = None,
    require: bool = True,
  ) -> Dict[str, Any]:
    issue = _clean_text(issue_code).lower()
    allowed_metrics = {
      _clean_text(item).lower()
      for item in (allowed_target_metric_names or [])
      if _clean_text(item)
    }
    candidate_levers = self.issue_candidate_lever_ids(
      issue,
      preferred_lever_ids=preferred_lever_ids,
      phase=phase,
      fallback_to_table=True,
    )
    target_metrics = [
      metric
      for metric in self.target_metrics_for_levers(candidate_levers)
      if metric and (not allowed_metrics or metric in allowed_metrics)
    ]
    if require and not candidate_levers:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_levers: "
        f"{issue or 'missing'} has no table-backed candidate levers."
      )
    if require and not target_metrics:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_targets: "
        f"{issue or 'missing'} has no table-backed target metrics from mapped candidate levers."
      )
    return {
      "issue_code": issue,
      "mapping_source": _MAPPING_TABLE_NAME,
      "candidate_lever_ids": copy.deepcopy(candidate_levers),
      "next_required_lever_ids": copy.deepcopy(candidate_levers),
      "target_metric_names": copy.deepcopy(target_metrics),
      "metric_targets": copy.deepcopy(target_metrics),
      "mapping_rows": self.compact_lookup_for_levers(candidate_levers),
    }

  def lever_ids_for_target_drivers(
    self,
    target_drivers: Iterable[Any],
    *,
    phase: Any = None,
  ) -> List[str]:
    targets: Set[str] = {
      _clean_text(item).lower()
      for item in (target_drivers or [])
      if _clean_text(item)
    }
    ordered: List[str] = []
    for row in self.rows(active_only=True, phase=phase):
      target_driver = _clean_text(row.get("target_driver")).lower()
      lever_id = _clean_text(row.get("lever_id"))
      if target_driver in targets and lever_id and lever_id not in ordered:
        ordered.append(lever_id)
    return ordered

  def single_lever_id_for_target_driver(self, target_driver: Any, *, phase: Any = None) -> str:
    target = _clean_text(target_driver).lower()
    lever_ids = self.lever_ids_for_target_drivers({target}, phase=phase)
    if len(lever_ids) != 1:
      raise RuntimeError(
        "post_intake_driver_target_mapping_single_lever_required: "
        f"target_driver={target or 'missing'} matched {len(lever_ids)} rows."
      )
    return lever_ids[0]

  def lever_ids_for_cash_roles(self, cash_strategy_roles: Iterable[Any]) -> List[str]:
    roles: Set[str] = {
      _clean_text(item).lower()
      for item in (cash_strategy_roles or [])
      if _clean_text(item)
    }
    ordered: List[str] = []
    for row in self.rows(active_only=True, phase="cash_pass"):
      role = _clean_text(row.get("cash_strategy_role")).lower()
      lever_id = _clean_text(row.get("lever_id"))
      if role in roles and lever_id and lever_id not in ordered:
        ordered.append(lever_id)
    return ordered

  def compact_lookup_for_levers(self, lever_ids: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
    requested = [
      _clean_text(item)
      for item in (lever_ids or [])
      if _clean_text(item)
    ]
    source_rows: List[Dict[str, Any]]
    if requested:
      source_rows = []
      seen_lookup_keys: Set[str] = set()
      for lever_id in requested:
        entry = self.entry_for_lever(lever_id)
        if not isinstance(entry, dict):
          continue
        lookup_key = _clean_text(entry.get("lookup_lever_id"))
        if lookup_key and lookup_key in seen_lookup_keys:
          continue
        if lookup_key:
          seen_lookup_keys.add(lookup_key)
        source_rows.append(entry)
    else:
      source_rows = self.rows(active_only=True)
    compact: List[Dict[str, Any]] = []
    for row in source_rows:
      lever_id = _clean_text(row.get("lever_id"))
      if not lever_id:
        continue
      compact.append(
        {
          "lever_id": lever_id,
          "driver_category": _clean_text(row.get("driver_category")).lower(),
          "target_driver": _clean_text(row.get("target_driver")),
          "target_metric_name": _clean_text(row.get("target_metric_name")).lower(),
          "model_input_field": _clean_text(row.get("model_input_field")),
          "financial_model_field": _clean_text(row.get("financial_model_field")),
          "impact_type": _clean_text(row.get("impact_type")).lower(),
          "post_intake_issue_codes": copy.deepcopy(row.get("post_intake_issue_codes") or []),
          "post_intake_phase": _clean_text(row.get("post_intake_phase")).lower(),
          "control_owner": _clean_text(row.get("control_owner")).lower(),
          "value_kind": _clean_text(row.get("value_kind")).lower(),
          "input_semantics": _clean_text(row.get("input_semantics")).lower(),
          "driver_bundle": _clean_text(row.get("driver_bundle")).lower(),
          "cash_strategy_role": _clean_text(row.get("cash_strategy_role")).lower(),
          "targeting_allowed": bool(row.get("targeting_allowed")),
          "diagnostic_only": bool(row.get("diagnostic_only")),
        }
      )
    return compact

  def validation_errors(self, expected_lever_ids: Optional[Iterable[Any]] = None) -> List[str]:
    errors: List[str] = []
    seen_lookup_keys: set[str] = set()
    valid_phases = {"convergence", "cash_pass", "both", "derived_only"}
    valid_control_owners = {"gpt_editable", "python_derived", "cash_pass", "locked"}
    valid_statuses = {"active", "retired", "review"}
    for row in self._rows:
      status = _clean_text(row.get("mapping_status")).lower()
      if status not in valid_statuses:
        errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported mapping_status {status}")
      if status != "active":
        continue
      lookup_key = _clean_text(row.get("lookup_lever_id"))
      if not lookup_key:
        errors.append("mapping row is missing lookup_lever_id")
        continue
      if lookup_key in seen_lookup_keys:
        errors.append(f"duplicate mapping row for {lookup_key}")
      seen_lookup_keys.add(lookup_key)
      metric_name = _clean_text(row.get("target_metric_name")).lower()
      if not metric_name:
        errors.append(
          f"{_clean_text(row.get('lever_id'))} has unsupported financial_model_field "
          f"{_clean_text(row.get('financial_model_field'))}"
        )
      if not _clean_text(row.get("model_input_field")):
        errors.append(f"{_clean_text(row.get('lever_id'))} is missing model_input_field")
      impact_type = _clean_text(row.get("impact_type")).lower()
      if impact_type not in {"direct", "derived"}:
        errors.append(
          f"{_clean_text(row.get('lever_id'))} has unsupported impact_type "
          f"{_clean_text(row.get('impact_type'))}"
        )
      phase = _clean_text(row.get("post_intake_phase")).lower()
      if phase not in valid_phases:
        errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported post_intake_phase {phase}")
      owner = _clean_text(row.get("control_owner")).lower()
      if owner not in valid_control_owners:
        errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported control_owner {owner}")
      if not _clean_text(row.get("value_kind")):
        errors.append(f"{_clean_text(row.get('lever_id'))} is missing value_kind")
      if not _clean_text(row.get("input_semantics")):
        errors.append(f"{_clean_text(row.get('lever_id'))} is missing input_semantics")
      if phase == "cash_pass" and owner not in {"cash_pass", "locked"}:
        errors.append(f"{_clean_text(row.get('lever_id'))} cash_pass row must be owned by cash_pass or locked")
      if phase == "derived_only" and owner != "python_derived":
        errors.append(f"{_clean_text(row.get('lever_id'))} derived_only row must be owned by python_derived")
    expected_lookup_keys = {
      _normalized_lookup_key(item)
      for item in (expected_lever_ids or [])
      if _clean_text(item)
    }
    missing_lookup_keys = sorted(key for key in expected_lookup_keys if key and key not in seen_lookup_keys)
    for lookup_key in missing_lookup_keys:
      errors.append(f"missing driver-target mapping for writable lever {lookup_key}")
    return errors


@lru_cache(maxsize=1)
def post_intake_mapping_lookup() -> PostIntakeMappingLookup:
  return PostIntakeMappingLookup(load_post_intake_driver_target_mapping_rows())


@lru_cache(maxsize=1)
def post_intake_driver_target_mapping_by_lever() -> Dict[str, Dict[str, Any]]:
  return {
    _clean_text(row.get("lookup_lever_id")): dict(row)
    for row in post_intake_mapping_lookup().rows(active_only=True)
    if _clean_text(row.get("lookup_lever_id"))
  }


def post_intake_driver_target_mapping_entry(lever_id: Any) -> Optional[Dict[str, Any]]:
  return post_intake_mapping_lookup().entry_for_lever(lever_id)


def post_intake_direct_target_metric_for_lever(lever_id: Any) -> str:
  return post_intake_mapping_lookup().target_metric_for_lever(lever_id)


def post_intake_direct_target_metric_names_for_levers(lever_ids: Optional[Iterable[Any]]) -> List[str]:
  return post_intake_mapping_lookup().target_metrics_for_levers(lever_ids)


def post_intake_driver_target_metric_ids(
  *,
  phase: Any = "convergence",
  targeting_allowed_only: bool = True,
) -> List[str]:
  return post_intake_mapping_lookup().target_metric_ids(
    phase=phase,
    targeting_allowed_only=targeting_allowed_only,
  )


def post_intake_driver_target_mapping_rows_for_issue(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[Dict[str, Any]]:
  return post_intake_mapping_lookup().rows_for_issue(issue_code, phase=phase)


def post_intake_driver_target_lever_ids_for_issue(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[str]:
  return post_intake_mapping_lookup().lever_ids_for_issue(issue_code, phase=phase)


def post_intake_driver_target_lever_allowed_for_issue(
  lever_id: Any,
  issue_code: Any,
  *,
  phase: Any = None,
) -> bool:
  return post_intake_mapping_lookup().lever_allowed_for_issue(
    lever_id,
    issue_code,
    phase=phase,
  )


def post_intake_issue_candidate_lever_ids(
  issue_code: Any,
  *,
  preferred_lever_ids: Optional[Iterable[Any]] = None,
  phase: Any = None,
  fallback_to_table: bool = True,
) -> List[str]:
  return post_intake_mapping_lookup().issue_candidate_lever_ids(
    issue_code,
    preferred_lever_ids=preferred_lever_ids,
    phase=phase,
    fallback_to_table=fallback_to_table,
  )


def post_intake_target_metric_names_for_issue(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[str]:
  return post_intake_mapping_lookup().target_metrics_for_issue(issue_code, phase=phase)


def post_intake_issue_mapping_contract(
  issue_code: Any,
  *,
  preferred_lever_ids: Optional[Iterable[Any]] = None,
  phase: Any = None,
  allowed_target_metric_names: Optional[Iterable[Any]] = None,
  require: bool = True,
) -> Dict[str, Any]:
  return post_intake_mapping_lookup().issue_mapping_contract(
    issue_code,
    preferred_lever_ids=preferred_lever_ids,
    phase=phase,
    allowed_target_metric_names=allowed_target_metric_names,
    require=require,
  )


def post_intake_driver_target_lever_ids_for_target_drivers(
  target_drivers: Iterable[Any],
  *,
  phase: Any = None,
) -> List[str]:
  return post_intake_mapping_lookup().lever_ids_for_target_drivers(
    target_drivers,
    phase=phase,
  )


def post_intake_driver_target_single_lever_id_for_target_driver(
  target_driver: Any,
  *,
  phase: Any = None,
) -> str:
  return post_intake_mapping_lookup().single_lever_id_for_target_driver(
    target_driver,
    phase=phase,
  )


def post_intake_driver_target_lever_ids_for_cash_roles(
  cash_strategy_roles: Iterable[Any],
) -> List[str]:
  return post_intake_mapping_lookup().lever_ids_for_cash_roles(cash_strategy_roles)


def post_intake_compact_mapping_lookup_for_levers(
  lever_ids: Optional[Iterable[Any]] = None,
) -> List[Dict[str, Any]]:
  return post_intake_mapping_lookup().compact_lookup_for_levers(lever_ids)


def post_intake_driver_target_mapping_errors(expected_lever_ids: Optional[Iterable[Any]] = None) -> List[str]:
  return post_intake_mapping_lookup().validation_errors(expected_lever_ids)
