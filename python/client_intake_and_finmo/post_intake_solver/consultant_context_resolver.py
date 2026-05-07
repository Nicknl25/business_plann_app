"""Phase 5.2 — Consultant context resolver.

Reads ``post_intake_gpt_context_lookup`` for the (contract_name, include_phase)
rows declared for a given Phase 3 consultant call, resolves each declared
``source_path`` from the row's ``source_kind`` handler, applies declared
transforms / budgets, and returns a dict keyed by each row's ``context_key``.

Architectural guarantees (per Phase 5.2 spec):

  R1: The table is the contract.
    - Adding context to a consultant means adding a row, not editing this
      module. The orchestrator passes only (contract_name, include_phase,
      scope_key, draft_id, planning_run_id, conn) plus a small bag of
      runtime_objects produced upstream (envelope_proposal, targets_proposal,
      cohort match results) that aren't persisted to a SQL surface.
    - This module never hand-builds candidate dicts; every key in the
      returned payload comes from a row in the table.

  Fail-fast on misconfiguration. Each failure mode raises
  ``post_intake_fail_fast_raise`` with a structured diagnostic identifying
  the failing row, source_path, and source_kind:

    - consultant_context_lookup_no_rows — table has no active include_in_prompt
      rows for (contract_name, include_phase).
    - consultant_context_scope_key_unresolved — a required row has source_path
      placeholders the supplied scope_key cannot fill.
    - consultant_context_unsupported_source_kind — row declares a source_kind
      this resolver has no handler for.
    - consultant_context_source_resolution_failed — a required row's source
      handler returned nothing.
    - consultant_context_transform_failed — a row's transform_kind handler
      threw or produced an invalid value.
    - consultant_context_budget_exceeded — a row's resolved value exceeds
      its declared max_chars after JSON serialization.

Source-kind handlers (this module's only resolution surface):

  - runtime_object: dot-path navigation through a dict the orchestrator
    passes via ``runtime_objects``. Used for in-memory artifacts produced
    upstream of Phase 3 (envelope_proposal driver entries, targets_proposal
    metric entries, cohort match summaries).
  - intake_field: SELECT a single column from intake_consult_drafts WHERE
    draft_id = %s. The source_path is the column name.
  - intake_json_field: SELECT a JSON column from intake_consult_drafts and
    walk a dot-path inside it. The source_path is "column_name:dot.path".
  - data_query: dispatch to a registered Python data lookup (industry
    baseline, R&D applicability, stage ramp policy, etc.). The source_path
    is "lookup_name:k1=v1,k2=v2"; values containing `{placeholder}` syntax
    are filled from scope_key before dispatch.

Scope_key:
  Dict like {"lever_id": "expenses::Cost of Goods Sold"} or
  {"metric_key": "ebitda_margin"}. Any source_path containing a {placeholder}
  matching a scope_key key is interpolated; if a placeholder is unresolved
  and the row is required=1, raises consultant_context_scope_key_unresolved.
  If scope_key was not supplied for a row that needs it and the row is
  required=0, the row is silently skipped (per-scope rows don't apply to
  a global call).
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple


_PHASE_3_PHASE_KEY = "phase_3_gpt"
_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _ff_raise(code: str, message: str, *, details: Dict[str, Any]) -> None:
  from client_intake_and_finmo.fail_fast.post_intake_fail_fast.fail_fast import (  # type: ignore
    post_intake_fail_fast_raise,
  )
  from client_intake_and_finmo.fail_fast.common import FailFastError  # type: ignore
  result = post_intake_fail_fast_raise(
    code,
    message,
    stage=_PHASE_3_PHASE_KEY,
    details=details,
  )
  # Phase 3 GPT context resolver fail-fast: always raise on misconfiguration,
  # regardless of CONVERGENCE_TEST_MODE. Misconfiguration in the context
  # table is structural and silent degradation here corrupts every consultant
  # call downstream.
  raise FailFastError(
    code, message,
    phase=result.get("phase") or "POST_INTAKE",
    stage=_PHASE_3_PHASE_KEY,
    details=details,
  )


def _interpolate_placeholders(
  template: str, scope_key: Optional[Dict[str, Any]],
) -> Tuple[str, List[str]]:
  unresolved: List[str] = []
  if not template:
    return template, unresolved
  scope = scope_key if isinstance(scope_key, dict) else {}

  def _replace(match: re.Match) -> str:
    name = match.group(1)
    if name in scope and scope[name] not in (None, ""):
      return str(scope[name])
    unresolved.append(name)
    return match.group(0)

  return _PLACEHOLDER_RE.sub(_replace, template), unresolved


# ---------------------------------------------------------------------------
# source_kind handlers
# ---------------------------------------------------------------------------


def _resolve_runtime_object(
  source_path: str, runtime_objects: Dict[str, Any],
) -> Any:
  """Walk a dot-path through ``runtime_objects``.

  Returns None when any path segment is missing or non-dict (callers
  decide whether None is fatal based on the row's ``required`` flag).
  """
  path = _clean_text(source_path)
  if not path:
    return None
  current: Any = runtime_objects if isinstance(runtime_objects, dict) else {}
  for segment in path.split("."):
    if segment == "":
      continue
    if isinstance(current, dict):
      if segment not in current:
        return None
      current = current[segment]
      continue
    if isinstance(current, list):
      try:
        idx = int(segment)
      except ValueError:
        return None
      if idx < 0 or idx >= len(current):
        return None
      current = current[idx]
      continue
    return None
  return copy.deepcopy(current)


def _resolve_intake_field(
  source_path: str, *, draft_id: str, conn: Any,
) -> Any:
  column = _clean_text(source_path)
  if not column or not draft_id or conn is None:
    return None
  cur = conn.cursor(dictionary=True)
  try:
    # Whitelist column name (alphanumeric + underscore) — never interpolate
    # arbitrary text into SQL.
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", column):
      return None
    cur.execute(
      f"SELECT `{column}` AS value FROM intake_consult_drafts WHERE draft_id=%s LIMIT 1",
      (draft_id,),
    )
    row = cur.fetchone()
  finally:
    cur.close()
  if not row:
    return None
  return row.get("value")


def _resolve_intake_json_field(
  source_path: str, *, draft_id: str, conn: Any,
) -> Any:
  raw = _clean_text(source_path)
  if ":" not in raw:
    return None
  column, _, json_path = raw.partition(":")
  column = _clean_text(column)
  json_path = _clean_text(json_path)
  if not column:
    return None
  raw_value = _resolve_intake_field(column, draft_id=draft_id, conn=conn)
  if raw_value is None:
    return None
  try:
    parsed = (
      raw_value if isinstance(raw_value, (dict, list))
      else json.loads(raw_value)
    )
  except Exception:
    return None
  if not json_path:
    return parsed
  current: Any = parsed
  for segment in json_path.split("."):
    if segment == "":
      continue
    if isinstance(current, dict):
      if segment not in current:
        return None
      current = current[segment]
      continue
    if isinstance(current, list):
      try:
        idx = int(segment)
      except ValueError:
        return None
      if idx < 0 or idx >= len(current):
        return None
      current = current[idx]
      continue
    return None
  return copy.deepcopy(current)


# data_query registry — each entry is a callable that takes (kwargs_dict)
# and returns the value to embed in the consultant prompt.
def _data_query_industry_baseline(*, metric_key: str, naics_6: str) -> Any:
  if not metric_key or not naics_6:
    return None
  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
    return post_intake_industry_baseline_for_naics(
      metric_key=str(metric_key), naics_6=str(naics_6),
    )
  except Exception:
    return None


def _data_query_r_and_d_applicability(*, naics_2: str) -> Any:
  if not naics_2:
    return None
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      post_intake_r_and_d_applicability_for_naics2,
    )
    return post_intake_r_and_d_applicability_for_naics2(str(naics_2))
  except Exception:
    return None


def _data_query_baseline_applicability(
  *, metric_key: str, naics_2: str,
) -> Any:
  if not metric_key or not naics_2:
    return None
  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_baseline_applicability_for_naics2,
    )
    return post_intake_baseline_applicability_for_naics2(
      metric_key=str(metric_key), naics_2=str(naics_2),
    )
  except Exception:
    return None


def _data_query_mapping_row(*, lever_id: str) -> Any:
  if not lever_id:
    return None
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      post_intake_driver_target_mapping_entry,
    )
    return post_intake_driver_target_mapping_entry(str(lever_id))
  except Exception:
    return None


def _data_query_realism_row(*, metric_key: str) -> Any:
  if not metric_key:
    return None
  try:
    from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
      post_intake_finalize_realism_check_rows,
    )
    rows = post_intake_finalize_realism_check_rows() or []
  except Exception:
    return None
  for row in rows:
    if not isinstance(row, dict):
      continue
    if _clean_text(row.get("metric_key")) == _clean_text(metric_key):
      return copy.deepcopy(row)
  return None


_DATA_QUERY_REGISTRY: Dict[str, Callable[..., Any]] = {
  "industry_baseline_for_naics": _data_query_industry_baseline,
  "r_and_d_applicability_for_naics2": _data_query_r_and_d_applicability,
  "baseline_applicability_for_naics2": _data_query_baseline_applicability,
  "mapping_row_for_lever": _data_query_mapping_row,
  "realism_row_for_metric": _data_query_realism_row,
}


def _resolve_data_query(
  source_path: str, scope_key: Optional[Dict[str, Any]],
) -> Tuple[Any, List[str]]:
  raw = _clean_text(source_path)
  unresolved: List[str] = []
  if ":" not in raw:
    return None, unresolved
  name, _, args_blob = raw.partition(":")
  name = _clean_text(name)
  if name not in _DATA_QUERY_REGISTRY:
    raise ValueError(f"data_query_not_registered: {name}")
  kwargs: Dict[str, str] = {}
  for fragment in (args_blob or "").split(","):
    fragment = _clean_text(fragment)
    if not fragment:
      continue
    if "=" not in fragment:
      continue
    k, _, v = fragment.partition("=")
    interpolated, missing = _interpolate_placeholders(_clean_text(v), scope_key)
    unresolved.extend(missing)
    kwargs[_clean_text(k)] = interpolated
  if unresolved:
    return None, unresolved
  return _DATA_QUERY_REGISTRY[name](**kwargs), unresolved


# ---------------------------------------------------------------------------
# transform handlers
# ---------------------------------------------------------------------------


def _slim_lever_entry(value: Any) -> Any:
  """Strip the bulky cohort_query.attempts diagnostic trace from a lever
  envelope entry so the per-call payload stays inside its budget. The
  trace is purely for offline debugging — it has no signal for GPT.
  """
  if not isinstance(value, dict):
    return value
  slimmed = copy.deepcopy(value)
  prov = slimmed.get("provenance")
  if isinstance(prov, dict):
    cohort = prov.get("cohort_band")
    if isinstance(cohort, dict) and isinstance(cohort.get("cohort_query"), dict):
      cohort["cohort_query"] = {
        "attempts_count": len(cohort["cohort_query"].get("attempts") or []),
        "winning_attempt_index": cohort["cohort_query"].get("winning_attempt_index"),
      }
  return slimmed


def _slim_metric_entry(value: Any) -> Any:
  """Same idea as _slim_lever_entry but for finmo target metric entries."""
  if not isinstance(value, dict):
    return value
  slimmed = copy.deepcopy(value)
  prov = slimmed.get("provenance")
  if isinstance(prov, dict):
    cohort = prov.get("cohort_band")
    if isinstance(cohort, dict) and isinstance(cohort.get("cohort_query"), dict):
      cohort["cohort_query"] = {
        "attempts_count": len(cohort["cohort_query"].get("attempts") or []),
        "winning_attempt_index": cohort["cohort_query"].get("winning_attempt_index"),
      }
  return slimmed


def _transform_value(
  value: Any, *, transform_kind: str, max_items: Optional[int],
) -> Any:
  kind = _clean_text(transform_kind).lower() or "copy"
  if kind == "copy":
    if isinstance(value, list) and max_items is not None:
      return value[: int(max_items)]
    return value
  if kind == "request_char_budget":
    # Marker rows; the value column is unused in resolved payload
    # (filtered out below by include_in_prompt=0). Returning None makes
    # the row a no-op when it slips through.
    return None
  if kind == "slim_lever_entry":
    return _slim_lever_entry(value)
  if kind == "slim_metric_entry":
    return _slim_metric_entry(value)
  if kind == "slim_mapping_row":
    return _slim_mapping_row(value)
  raise ValueError(f"unsupported_transform_kind: {kind}")


def _slim_mapping_row(value: Any) -> Any:
  """Trim a post_intak_mapping_lookup row to the GPT-relevant fields.

  The full row carries formula contracts, repair direction rules, and
  schedule wiring metadata that has no signal for band-shaping
  amendments. GPT needs the lever's value_kind, control owner,
  absolute live-value bounds, applicability default, and the metric
  it governs.
  """
  if not isinstance(value, dict):
    return value
  keep = (
    "lever_id", "lever_kind", "section_name", "value_kind",
    "control_owner", "schedule_locked",
    "minimum_live_value", "maximum_live_value",
    "target_metric_name", "financial_model_field",
    "applicability_default", "applicability_rule_key",
    "targeting_allowed",
  )
  return {k: copy.deepcopy(value.get(k)) for k in keep if k in value}


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------


def resolve_consultant_context(
  *,
  contract_name: str,
  include_phase: str,
  scope_key: Optional[Dict[str, Any]],
  draft_id: str,
  planning_run_id: str,
  conn: Any,
  runtime_objects: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Resolve the consultant context dict declared by the SQL table.

  See module docstring for the full contract. Returns a dict keyed by
  each row's context_key. Raises post_intake_fail_fast_raise on any
  misconfiguration.
  """
  contract = _clean_text(contract_name)
  phase = _clean_text(include_phase)
  scope = scope_key if isinstance(scope_key, dict) else None
  runtime = runtime_objects if isinstance(runtime_objects, dict) else {}

  from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
    post_intake_gpt_context_lookup,
  )
  rows = post_intake_gpt_context_lookup().rows(
    contract_name=contract,
    include_phase=phase,
    include_in_prompt=True,
  )
  if not rows:
    _ff_raise(
      "consultant_context_lookup_no_rows",
      f"no active include_in_prompt rows for contract_name={contract!r} "
      f"include_phase={phase!r}",
      details={
        "contract_name": contract,
        "include_phase": phase,
        "scope_key": scope or {},
      },
    )

  resolved: Dict[str, Any] = {}
  skipped_optional: List[str] = []

  for row in rows:
    context_key = _clean_text(row.get("context_key"))
    if not context_key:
      continue
    source_kind = _clean_text(row.get("source_kind")).lower()
    raw_source_path = _clean_text(row.get("source_path"))
    transform_kind = _clean_text(row.get("transform_kind")).lower() or "copy"
    required = bool(row.get("required"))
    max_items = row.get("max_items")
    max_chars = row.get("max_chars")
    failure_code = _clean_text(row.get("failure_code")) or context_key

    interpolated_path, unresolved = _interpolate_placeholders(raw_source_path, scope)
    if unresolved:
      if required:
        _ff_raise(
          "consultant_context_scope_key_unresolved",
          f"required row {context_key!r} has unresolved placeholders "
          f"{unresolved!r} in source_path={raw_source_path!r}; "
          f"scope_key={scope!r}",
          details={
            "contract_name": contract, "include_phase": phase,
            "context_key": context_key, "source_path": raw_source_path,
            "unresolved_placeholders": unresolved,
            "scope_key": scope or {},
            "row_failure_code": failure_code,
          },
        )
      skipped_optional.append(context_key)
      continue

    try:
      if source_kind == "runtime_object":
        value = _resolve_runtime_object(interpolated_path, runtime)
      elif source_kind == "intake_field":
        value = _resolve_intake_field(
          interpolated_path, draft_id=_clean_text(draft_id), conn=conn,
        )
      elif source_kind == "intake_json_field":
        value = _resolve_intake_json_field(
          interpolated_path, draft_id=_clean_text(draft_id), conn=conn,
        )
      elif source_kind == "data_query":
        value, _ = _resolve_data_query(interpolated_path, scope)
      else:
        _ff_raise(
          "consultant_context_unsupported_source_kind",
          f"row {context_key!r} declares source_kind={source_kind!r} "
          "but no handler is registered",
          details={
            "contract_name": contract, "include_phase": phase,
            "context_key": context_key, "source_kind": source_kind,
            "row_failure_code": failure_code,
          },
        )
        continue
    except Exception as exc:
      _ff_raise(
        "consultant_context_source_resolution_failed",
        f"row {context_key!r} source_kind={source_kind!r} "
        f"path={interpolated_path!r} raised {type(exc).__name__}: {exc}",
        details={
          "contract_name": contract, "include_phase": phase,
          "context_key": context_key, "source_kind": source_kind,
          "source_path": interpolated_path,
          "exception": f"{type(exc).__name__}: {str(exc)[:200]}",
          "row_failure_code": failure_code,
        },
      )
      continue

    if value is None:
      if required:
        _ff_raise(
          "consultant_context_source_resolution_failed",
          f"required row {context_key!r} resolved to None "
          f"(source_kind={source_kind!r}, source_path={interpolated_path!r})",
          details={
            "contract_name": contract, "include_phase": phase,
            "context_key": context_key, "source_kind": source_kind,
            "source_path": interpolated_path,
            "scope_key": scope or {},
            "row_failure_code": failure_code,
          },
        )
      skipped_optional.append(context_key)
      continue

    try:
      transformed = _transform_value(
        value, transform_kind=transform_kind, max_items=max_items,
      )
    except Exception as exc:
      _ff_raise(
        "consultant_context_transform_failed",
        f"row {context_key!r} transform_kind={transform_kind!r} "
        f"raised {type(exc).__name__}: {exc}",
        details={
          "contract_name": contract, "include_phase": phase,
          "context_key": context_key, "transform_kind": transform_kind,
          "exception": f"{type(exc).__name__}: {str(exc)[:200]}",
          "row_failure_code": failure_code,
        },
      )
      continue

    if transformed is None:
      # request_char_budget rows (transform returns None) are intentionally
      # not in the prompt payload — the budget is enforced at payload-size
      # check time below.
      continue

    if max_chars is not None:
      try:
        encoded_size = len(json.dumps(transformed, ensure_ascii=False, default=str))
      except Exception:
        encoded_size = 0
      if encoded_size > int(max_chars):
        _ff_raise(
          "consultant_context_budget_exceeded",
          f"row {context_key!r} resolved value of {encoded_size} chars "
          f"exceeds max_chars={int(max_chars)}",
          details={
            "contract_name": contract, "include_phase": phase,
            "context_key": context_key, "size_chars": encoded_size,
            "max_chars": int(max_chars),
            "row_failure_code": failure_code,
          },
        )

    resolved[context_key] = transformed

  return resolved
