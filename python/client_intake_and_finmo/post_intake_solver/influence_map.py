"""Driver Influence Map — Phase 2 module 3.

Read-only over the existing mapping table. For each output metric, returns
the ordered list of levers most likely to move it, with sign hint and
priority. Used by the target-seeking solver loop to pick which driver to
tweak next when an output is out-of-range.

Sources of relationship:
  1. realism_check_lookup.governs_model_input_lever_id — primary signal
     (the lever the realism gate was designed to surface).
  2. mapping_table.target_metric_name — the output metric the lever is
     formally pointed at.
  3. mapping_table.repair_direction_rules — sign hint (some levers are
     known increase-this-output, others decrease-it).

The map is deterministic and read-only. The mapping table doesn't change;
the solver just queries it differently. GPT can be consulted (Phase 3,
optional consultant) when ties or ambiguity remain after the deterministic
ordering.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


# Phase 6 Step 11 — multi-lever metric registry.
#
# Realism metrics that are functions of multiple drivers (no single
# governing lever) are promoted to hard_fail without a
# `governs_model_input_lever_id` on the realism row. This registry
# supplies their priority-ordered candidate-lever lists so the cascade
# has a remediation path. The orchestrator's joint feasibility check
# (Phase 5.2 R3) does direct-governance pairwise checks only for
# metrics with a single governing lever; multi-lever metrics fall
# through to the cascade and are remediated via the candidate list.
#
# Priority order = most-direct-impact first. The cascade tries them in
# order; later entries are fallbacks when the earlier lever is pinned
# at envelope edge.
_MULTI_LEVER_METRIC_REGISTRY: Dict[str, List[str]] = {
  "operating_margin_percent": [
    "expenses::Cost of Goods Sold",
    "expenses::Marketing",
    "expenses::Research & Development",
    "expenses::General & Administrative",
  ],
  "net_income_margin": [
    "expenses::Cost of Goods Sold",
    "expenses::Marketing",
    "expenses::Research & Development",
    "expenses::General & Administrative",
    "expenses::Interest Rate",
  ],
  "current_ratio": [
    "balance_sheet::Accounts Receivable Days",
    "balance_sheet::Accounts Payable Days",
    "balance_sheet::Inventory Days",
    "balance_sheet::Short Term Debt (% of LTD)",
  ],
  "quick_ratio": [
    "balance_sheet::Accounts Receivable Days",
    "balance_sheet::Accounts Payable Days",
    "balance_sheet::Short Term Debt (% of LTD)",
  ],
  "debt_to_equity": [
    "schedules::Debt Issuance (New Borrowing)",
    "schedules::Debt Repayment (Scheduled)",
    "balance_sheet::Owner's Capital",
  ],
  "debt_to_assets": [
    "schedules::Debt Issuance (New Borrowing)",
    "schedules::Debt Repayment (Scheduled)",
  ],
  "operating_cash_flow_margin": [
    "balance_sheet::Accounts Receivable Days",
    "balance_sheet::Accounts Payable Days",
    "balance_sheet::Inventory Days",
    "expenses::Cost of Goods Sold",
  ],
  "total_assets_to_revenue": [
    "revenue::*::*::Capacity",
    "revenue::*::*::Unit Price",
    "revenue::*::*::Utilization",
    "balance_sheet::Accounts Receivable Days",
    "balance_sheet::Inventory Days",
  ],
}


def _ordered_unique(items: List[str]) -> List[str]:
  seen = set()
  out: List[str] = []
  for item in items:
    if item and item not in seen:
      seen.add(item)
      out.append(item)
  return out


def _direct_metric_for_lever(mapping_row: Dict[str, Any]) -> str:
  return _clean_text(mapping_row.get("target_metric_name"))


def _sign_hint_from_repair_rules(mapping_row: Dict[str, Any], metric_key: str) -> str:
  rules = mapping_row.get("repair_direction_rules") or {}
  if not isinstance(rules, dict):
    return "ambiguous"
  for key in (metric_key, f"increase_{metric_key}", f"decrease_{metric_key}"):
    direction = _clean_text((rules.get(key) or {}).get("direction") if isinstance(rules.get(key), dict) else rules.get(key))
    direction = direction.lower()
    if direction in {"increase", "decrease", "either"}:
      return direction
  impact_type = _clean_text(mapping_row.get("impact_type")).lower()
  if impact_type in {"positive_correlation", "increases_metric"}:
    return "increase"
  if impact_type in {"negative_correlation", "decreases_metric"}:
    return "decrease"
  return "ambiguous"


def driver_influence_map(
  *,
  mapping_rows: Optional[List[Dict[str, Any]]] = None,
  realism_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """Build the metric -> ordered-lever influence map.

  Returns:
    {
      "contract_version": "driver_influence_map_v1",
      "metrics": {
        metric_key: {
          "primary_lever_id": <lever_id or None>,
          "candidate_levers": [
            {"lever_id", "priority", "sign_hint", "source"},
            ...
          ],
        }
      }
    }
  """
  if mapping_rows is None:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      load_post_intake_driver_target_mapping_rows,
    )
    mapping_rows = load_post_intake_driver_target_mapping_rows()
  if realism_rows is None:
    from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
      post_intake_finalize_realism_check_rows,
    )
    realism_rows = post_intake_finalize_realism_check_rows()

  mapping_by_lever: Dict[str, Dict[str, Any]] = {}
  for row in mapping_rows:
    if not isinstance(row, dict):
      continue
    lever_id = _clean_text(row.get("lever_id"))
    if not lever_id:
      continue
    mapping_by_lever[lever_id] = row

  metrics: Dict[str, Dict[str, Any]] = {}

  # Pass 1 — primary lever per metric: comes from realism_check.governs_model_input_lever_id.
  for row in realism_rows:
    if not isinstance(row, dict):
      continue
    if not bool(row.get("active", True)):
      continue
    metric_key = _clean_text(row.get("metric_key"))
    if not metric_key:
      continue
    primary_lever = _clean_text(row.get("governs_model_input_lever_id"))
    candidate_list: List[Dict[str, Any]] = []
    if primary_lever and primary_lever in mapping_by_lever:
      candidate_list.append({
        "lever_id": primary_lever,
        "priority": 1,
        "sign_hint": _sign_hint_from_repair_rules(mapping_by_lever[primary_lever], metric_key),
        "source": "realism_check.governs_model_input_lever_id",
      })
    metrics[metric_key] = {
      "primary_lever_id": primary_lever or None,
      "candidate_levers": candidate_list,
    }

  # Pass 2 — supplementary levers per metric: every mapping row whose
  # target_metric_name matches the metric_key, ranked after the realism-
  # primary lever.
  for lever_id, mapping_row in mapping_by_lever.items():
    metric = _direct_metric_for_lever(mapping_row)
    if not metric:
      continue
    bucket = metrics.setdefault(metric, {"primary_lever_id": None, "candidate_levers": []})
    if any(item.get("lever_id") == lever_id for item in bucket["candidate_levers"]):
      continue
    if not bool(mapping_row.get("targeting_allowed", True)):
      continue
    bucket["candidate_levers"].append({
      "lever_id": lever_id,
      "priority": 2,
      "sign_hint": _sign_hint_from_repair_rules(mapping_row, metric),
      "source": "mapping_table.target_metric_name",
    })

  # Phase 6 Step 11 — Pass 3: apply the multi-lever registry. Metrics
  # whose realism row promoted them to hard_fail without a single
  # governing lever rely on this priority-ordered list for the
  # cascade's remediation pathway.
  for metric_key, lever_id_list in _MULTI_LEVER_METRIC_REGISTRY.items():
    bucket = metrics.setdefault(metric_key, {"primary_lever_id": None, "candidate_levers": []})
    existing_lever_ids = {
      str(item.get("lever_id") or "").strip() for item in bucket["candidate_levers"]
    }
    for rank, lever_id in enumerate(lever_id_list, start=1):
      lever = _clean_text(lever_id)
      if not lever or lever in existing_lever_ids:
        continue
      mapping_row = mapping_by_lever.get(lever)
      sign_hint = (
        _sign_hint_from_repair_rules(mapping_row, metric_key)
        if isinstance(mapping_row, dict) else "ambiguous"
      )
      bucket["candidate_levers"].append({
        "lever_id": lever,
        "priority": 1 if rank == 1 and bucket["primary_lever_id"] is None else 1 + rank,
        "sign_hint": sign_hint,
        "source": "phase_6_step_11_multi_lever_registry",
      })
      existing_lever_ids.add(lever)
    if bucket["primary_lever_id"] is None and bucket["candidate_levers"]:
      bucket["primary_lever_id"] = bucket["candidate_levers"][0]["lever_id"]

  # Sort candidates by priority within each metric (stable, primary first).
  for metric_payload in metrics.values():
    metric_payload["candidate_levers"].sort(key=lambda item: (int(item.get("priority") or 99), str(item.get("lever_id") or "")))

  return {
    "contract_version": "driver_influence_map_v1",
    "decision_source": "python_proposer",
    "metrics": metrics,
  }
