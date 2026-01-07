from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from unified_intake.concepts import ensure_concept_summary
from unified_intake.lobs import ensure_lob_model_card, extract_lobs_from_text
from unified_intake.model_engine import (
  apply_company_driver_patch,
  ensure_pricing_from_ops,
  recompute_headcount_company_total,
  recompute_marketing_company_total,
  recompute_revenue_company_total,
)


def _parse_json_list(raw: Any) -> List[Any]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return list(raw)
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  return list(parsed) if isinstance(parsed, list) else []


def _compute_fact_revisions(
  *,
  prev_state: Dict[str, Any],
  next_state: Dict[str, Any],
  patch: Dict[str, Any],
  existing_nonce: int,
  existing_revisions_raw: Any,
  now_ms: int,
) -> Tuple[Optional[int], Optional[List[Dict[str, Any]]]]:
  """
  Record fact revisions as immutable history entries: {field, old, new, nonce, at_ms}.
  Only includes facts (business/ops/market/people/financials).
  """
  try:
    parsed_revs = json.loads(str(existing_revisions_raw)) if existing_revisions_raw else []
    if not isinstance(parsed_revs, list):
      parsed_revs = []
  except Exception:
    parsed_revs = []

  entries: List[Dict[str, Any]] = []
  for raw_key in (patch or {}).keys():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    group, field = key.split(".", 1)
    group = group.strip().lower()
    field = field.strip()
    if group not in ("business", "ops", "market", "people", "financials"):
      continue
    old_value = ((prev_state.get(group) or {}) if isinstance(prev_state.get(group), dict) else {}).get(field)
    new_value = ((next_state.get(group) or {}) if isinstance(next_state.get(group), dict) else {}).get(field)
    if old_value == new_value:
      continue
    entries.append({"field": key, "old": old_value, "new": new_value})

  if not entries:
    return None, None

  next_nonce = int(existing_nonce) + 1
  for e in entries:
    e["nonce"] = next_nonce
    e["at_ms"] = int(now_ms)
  parsed_revs.extend(entries)
  if len(parsed_revs) > 200:
    parsed_revs = parsed_revs[-200:]
  return next_nonce, parsed_revs


def _compute_driver_events(
  *,
  driver_changes: List[Dict[str, Any]],
  existing_nonce: int,
  existing_events_raw: Any,
  now_ms: int,
) -> Tuple[Optional[int], Optional[List[Dict[str, Any]]]]:
  if not driver_changes:
    return None, None
  try:
    parsed = json.loads(str(existing_events_raw)) if existing_events_raw else []
    if not isinstance(parsed, list):
      parsed = []
  except Exception:
    parsed = []
  next_nonce = int(existing_nonce) + 1
  parsed.append(
    {
      "nonce": next_nonce,
      "at_ms": int(now_ms),
      "action": "chat_patch",
      "note": "chat-driven model update",
      "changes": driver_changes,
    }
  )
  if len(parsed) > 500:
    parsed = parsed[-500:]
  return next_nonce, parsed


def seed_lobs_if_needed(
  *,
  conn,
  draft_id: str,
  message: str,
  ops_concept_model_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  pricing_model_json: Dict[str, Any],
  revenue_model_json: Dict[str, Any],
  headcount_model_json: Dict[str, Any],
  fulfillment_model_json: Dict[str, Any],
  milestones_model_json: Dict[str, Any],
  cogs_model_json: Dict[str, Any],
  gna_model_json: Dict[str, Any],
) -> Tuple[
  Dict[str, Any],
  Dict[str, Any],
  Dict[str, Any],
  Dict[str, Any],
  Dict[str, Any],
  Dict[str, Any],
  Dict[str, Any],
  Dict[str, Any],
  Dict[str, Any],
]:
  """
  If the user explicitly describes multiple lines of business, seed the {lobs:[...]} structure
  into all model-card JSON columns. This is internal-only state scaffolding.
  """
  now_ms = int(time.time() * 1000)
  try:
    lobs = extract_lobs_from_text(message)
  except Exception:
    lobs = []
  if not lobs:
    return (
      ops_concept_model_json,
      marketing_model_json,
      pricing_model_json,
      revenue_model_json,
      headcount_model_json,
      fulfillment_model_json,
      milestones_model_json,
      cogs_model_json,
      gna_model_json,
    )

  if isinstance(ops_concept_model_json.get("lobs"), list) and ops_concept_model_json.get("lobs"):
    return (
      ops_concept_model_json,
      marketing_model_json,
      pricing_model_json,
      revenue_model_json,
      headcount_model_json,
      fulfillment_model_json,
      milestones_model_json,
      cogs_model_json,
      gna_model_json,
    )

  prev_ops_concept = dict(ops_concept_model_json or {})
  prev_marketing = dict(marketing_model_json or {})
  prev_pricing = dict(pricing_model_json or {})
  prev_revenue = dict(revenue_model_json or {})
  prev_headcount = dict(headcount_model_json or {})
  prev_fulfillment = dict(fulfillment_model_json or {})
  prev_milestones = dict(milestones_model_json or {})
  prev_cogs = dict(cogs_model_json or {})
  prev_gna = dict(gna_model_json or {})

  ops_concept_model_json = ensure_lob_model_card(ops_concept_model_json or {}, lobs)
  marketing_model_json = ensure_lob_model_card(marketing_model_json or {}, lobs)
  pricing_model_json = ensure_lob_model_card(pricing_model_json or {}, lobs)
  revenue_model_json = ensure_lob_model_card(revenue_model_json or {}, lobs)
  headcount_model_json = ensure_lob_model_card(headcount_model_json or {}, lobs)
  fulfillment_model_json = ensure_lob_model_card(fulfillment_model_json or {}, lobs)
  milestones_model_json = ensure_lob_model_card(milestones_model_json or {}, lobs)
  cogs_model_json = ensure_lob_model_card(cogs_model_json or {}, lobs)
  gna_model_json = ensure_lob_model_card(gna_model_json or {}, lobs)

  concept_ctx = {"event": "seed_lobs"}
  ops_concept_model_json, _ = ensure_concept_summary(
    model="ops_concept",
    prev_card=prev_ops_concept,
    card=ops_concept_model_json,
    now_ms=now_ms,
    context=concept_ctx,
  )
  marketing_model_json, _ = ensure_concept_summary(
    model="marketing", prev_card=prev_marketing, card=marketing_model_json, now_ms=now_ms, context=concept_ctx
  )
  pricing_model_json, _ = ensure_concept_summary(
    model="pricing", prev_card=prev_pricing, card=pricing_model_json, now_ms=now_ms, context=concept_ctx
  )
  revenue_model_json, _ = ensure_concept_summary(
    model="revenue", prev_card=prev_revenue, card=revenue_model_json, now_ms=now_ms, context=concept_ctx
  )
  headcount_model_json, _ = ensure_concept_summary(
    model="headcount", prev_card=prev_headcount, card=headcount_model_json, now_ms=now_ms, context=concept_ctx
  )
  fulfillment_model_json, _ = ensure_concept_summary(
    model="fulfillment",
    prev_card=prev_fulfillment,
    card=fulfillment_model_json,
    now_ms=now_ms,
    context=concept_ctx,
  )
  milestones_model_json, _ = ensure_concept_summary(
    model="milestones", prev_card=prev_milestones, card=milestones_model_json, now_ms=now_ms, context=concept_ctx
  )
  cogs_model_json, _ = ensure_concept_summary(
    model="cogs", prev_card=prev_cogs, card=cogs_model_json, now_ms=now_ms, context=concept_ctx
  )
  gna_model_json, _ = ensure_concept_summary(
    model="gna", prev_card=prev_gna, card=gna_model_json, now_ms=now_ms, context=concept_ctx
  )

  from intake_consult_draft import append_messages  # type: ignore

  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    ops_concept_model_json=ops_concept_model_json,
    marketing_model_json=marketing_model_json,
    pricing_model_json=pricing_model_json,
    revenue_model_json=revenue_model_json,
    headcount_model_json=headcount_model_json,
    fulfillment_model_json=fulfillment_model_json,
    milestones_model_json=milestones_model_json,
    cogs_model_json=cogs_model_json,
    gna_model_json=gna_model_json,
  )
  return (
    ops_concept_model_json,
    marketing_model_json,
    pricing_model_json,
    revenue_model_json,
    headcount_model_json,
    fulfillment_model_json,
    milestones_model_json,
    cogs_model_json,
    gna_model_json,
  )


def sync_pricing_from_ops_if_needed(
  *,
  conn,
  draft_id: str,
  ops_json: Dict[str, Any],
  pricing_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  """
  Keep pricing model in lockstep with Ops unit_price when Ops is updated via chat.
  """
  now_ms = int(time.time() * 1000)
  prev_pricing = dict(pricing_model_json or {})
  try:
    next_pricing = ensure_pricing_from_ops(ops_json=ops_json, pricing_model_json=pricing_model_json)
  except Exception:
    next_pricing = None
  if not next_pricing or next_pricing == pricing_model_json:
    return pricing_model_json

  next_pricing, _ = ensure_concept_summary(
    model="pricing",
    prev_card=prev_pricing,
    card=next_pricing,
    now_ms=now_ms,
    context={"event": "sync_pricing_from_ops"},
  )

  from intake_consult_draft import append_messages  # type: ignore

  append_messages(conn, draft_id=str(draft_id).strip(), new_messages=[], pricing_model_json=next_pricing)
  return next_pricing


def apply_chat_patch_and_persist(
  *,
  conn,
  draft_id: str,
  consult_row: Dict[str, Any],
  patch: Dict[str, Any],
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  pricing_model_json: Dict[str, Any],
  revenue_model_json: Dict[str, Any],
  headcount_model_json: Dict[str, Any],
  fulfillment_model_json: Dict[str, Any],
  ops_concept_model_json: Dict[str, Any],
  milestones_model_json: Dict[str, Any],
  cogs_model_json: Dict[str, Any],
  gna_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  """
  Apply a chat-driven patch (facts + model drivers) and persist immediately to SQL.
  This is the only place where model driver semantics and recompute orchestration occur.
  """
  now_ms = int(time.time() * 1000)

  prev_state = {
    "business": dict(business_facts or {}),
    "ops": dict(ops_json or {}),
    "market": dict(market_json or {}),
    "people": dict(people_json or {}),
    "financials": dict(financials_json or {}),
  }

  prev_marketing = dict(marketing_model_json or {})
  prev_pricing = dict(pricing_model_json or {})
  prev_revenue = dict(revenue_model_json or {})
  prev_headcount = dict(headcount_model_json or {})
  prev_fulfillment = dict(fulfillment_model_json or {})
  prev_ops_concept = dict(ops_concept_model_json or {})
  prev_milestones = dict(milestones_model_json or {})
  prev_cogs = dict(cogs_model_json or {})
  prev_gna = dict(gna_model_json or {})

  # Split patch into facts vs model drivers. Patch semantics are handled here (not controller).
  fact_patch: Dict[str, Any] = {}
  model_patch: Dict[str, Any] = {}
  for raw_key, val in (patch or {}).items():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    group, field = key.split(".", 1)
    group = group.strip().lower()
    field = field.strip()
    if not group or not field:
      continue
    if group in ("business", "ops", "market", "people", "financials"):
      # Disambiguation: plain-language staffing plans occasionally land in people.people.
      if group == "people" and field == "people":
        try:
          maybe_roles = val
          if isinstance(maybe_roles, list) and any(
            isinstance(r, dict)
            and any(
              k in r
              for k in (
                "employee_count",
                "count",
                "hours_per_week",
                "weeks_per_year",
                "hourly_rate_override",
                "hourly_rate",
              )
            )
            for r in maybe_roles
          ):
            model_patch["headcount.roles"] = maybe_roles
            continue
        except Exception:
          pass
      fact_patch[key] = val
    else:
      model_patch[key] = val

  # Apply fact patch.
  for raw_key, value in (fact_patch or {}).items():
    group, field = raw_key.split(".", 1)
    group = group.strip().lower()
    field = field.strip()
    if group == "business":
      business_facts[field] = value
      if field == "address":
        # If the canonical address string changes via chat-driven patch, clear parts.
        for part_key in ("address_street", "address_city", "address_state", "address_zip", "address_country"):
          business_facts[part_key] = None
    elif group == "ops":
      ops_json[field] = value
    elif group == "market":
      market_json[field] = value
    elif group == "people":
      people_json[field] = value
    elif group == "financials":
      financials_json[field] = value

  # Apply model driver patches (opaque to controller; semantic here/model_engine).
  driver_changes: List[Dict[str, Any]] = []
  for raw_key, value in (model_patch or {}).items():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    model, field = key.split(".", 1)
    model = model.strip().lower()
    field = field.strip()
    if not model or not field:
      continue

    driver_value = value
    lob_key = "company_total"
    rationale_override: Optional[str] = None
    unit_override: Optional[str] = None
    time_basis_override: Optional[str] = None
    if isinstance(value, dict):
      if "lob_key" in value:
        lob_key = str(value.get("lob_key") or "").strip() or "company_total"
      if "value" in value:
        driver_value = value.get("value")
      if value.get("rationale") is not None:
        rationale_override = str(value.get("rationale") or "").strip() or None
      if value.get("unit") is not None:
        unit_override = str(value.get("unit") or "").strip() or None
      if value.get("time_basis") is not None:
        time_basis_override = str(value.get("time_basis") or "").strip() or None

    if model == "marketing":
      marketing_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=marketing_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "marketing", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})
    elif model == "pricing":
      pricing_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=pricing_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "pricing", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})
    elif model == "revenue":
      revenue_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=revenue_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "revenue", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})
    elif model == "headcount":
      headcount_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=headcount_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "headcount", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})
    elif model == "fulfillment":
      fulfillment_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=fulfillment_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "fulfillment", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})
    elif model == "ops_concept":
      ops_concept_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=ops_concept_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "ops_concept", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})
    elif model == "milestones":
      milestones_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=milestones_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "milestones", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})
    elif model == "cogs":
      cogs_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=cogs_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "cogs", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})
    elif model == "gna":
      gna_model_json, ops_json, changed = apply_company_driver_patch(
        model=model,
        field=field,
        value=driver_value,
        card=gna_model_json,
        ops_json=ops_json,
        now_ms=now_ms,
        rationale=rationale_override,
        unit_override=unit_override,
        time_basis_override=time_basis_override,
        lob_key=lob_key,
      )
      if changed:
        driver_changes.append({"model": "gna", "lob_key": lob_key, "path": f"drivers.{field}", "new": driver_value})

  # Deterministic recompute of derived/rollup columns.
  year1_marketing_spend_out: Any = None
  year1_payroll_out: Any = None
  year1_revenue_out: Any = None
  year1_cogs_out: Any = None
  year1_gna_total_out: Any = None

  try:
    if marketing_model_json != prev_marketing:
      marketing_model_json, year1_marketing_spend_out = recompute_marketing_company_total(
        marketing_model_json, now_ms=now_ms
      )
    if headcount_model_json != prev_headcount:
      headcount_model_json, year1_payroll_out = recompute_headcount_company_total(
        headcount_model_json, now_ms=now_ms
      )

    # Revenue derived values depend on both Revenue drivers and certain Ops facts (e.g., unit_price, capacity).
    ops_prev = prev_state.get("ops") if isinstance(prev_state.get("ops"), dict) else {}
    revenue_inputs_changed = (
      revenue_model_json != prev_revenue
      or any(k.startswith("revenue.") for k in (model_patch or {}).keys())
      or any(
        (ops_prev.get(k) != ops_json.get(k))
        for k in ("units_per_week_capacity", "unit_price", "unit_name", "starting_revenue")
      )
    )
    if revenue_inputs_changed:
      revenue_model_json, ops_json, year1_revenue_out = recompute_revenue_company_total(
        revenue_model_json, ops_json=ops_json, now_ms=now_ms
      )

    # Pricing card is a projection of Ops unit_price; keep it in lockstep in the same chat turn.
    try:
      from unified_intake.model_engine import ensure_pricing_from_ops  # type: ignore
    except Exception:
      ensure_pricing_from_ops = None  # type: ignore
    if ensure_pricing_from_ops:
      try:
        synced_pricing = ensure_pricing_from_ops(ops_json=ops_json, pricing_model_json=pricing_model_json)
      except Exception:
        synced_pricing = None
      if isinstance(synced_pricing, dict) and synced_pricing and synced_pricing != pricing_model_json:
        pricing_model_json = synced_pricing
        try:
          driver_changes.append(
            {
              "model": "pricing",
              "lob_key": "company_total",
              "path": "drivers.unit_price",
              "new": synced_pricing.get("unit_price"),
            }
          )
        except Exception:
          pass

    if cogs_model_json != prev_cogs or revenue_inputs_changed:
      from unified_intake.model_engine import recompute_cogs_company_total  # type: ignore

      cogs_model_json, year1_cogs_out = recompute_cogs_company_total(
        cogs_model_json, revenue_card=revenue_model_json, now_ms=now_ms
      )
    if gna_model_json != prev_gna:
      from unified_intake.model_engine import recompute_gna_company_total  # type: ignore

      gna_model_json, year1_gna_total_out = recompute_gna_company_total(gna_model_json, now_ms=now_ms)
  except Exception:
    pass

  # Concept summaries (authoritative narrative layer for plan writing) must stay in lockstep with drivers/rationales.
  concept_ctx = {
    "business": {
      "name": business_facts.get("name"),
      "address": business_facts.get("address"),
      "start_date": business_facts.get("start_date"),
    },
    "ops": {
      "business_type": (ops_json or {}).get("business_type"),
      "consumer_type": (ops_json or {}).get("consumer_type"),
      "unit_name": (ops_json or {}).get("unit_name"),
    },
  }
  try:
    marketing_model_json, _ = ensure_concept_summary(
      model="marketing", prev_card=prev_marketing, card=marketing_model_json, now_ms=now_ms, context=concept_ctx
    )
    pricing_model_json, _ = ensure_concept_summary(
      model="pricing", prev_card=prev_pricing, card=pricing_model_json, now_ms=now_ms, context=concept_ctx
    )
    revenue_model_json, _ = ensure_concept_summary(
      model="revenue", prev_card=prev_revenue, card=revenue_model_json, now_ms=now_ms, context=concept_ctx
    )
    headcount_model_json, _ = ensure_concept_summary(
      model="headcount", prev_card=prev_headcount, card=headcount_model_json, now_ms=now_ms, context=concept_ctx
    )
    fulfillment_model_json, _ = ensure_concept_summary(
      model="fulfillment", prev_card=prev_fulfillment, card=fulfillment_model_json, now_ms=now_ms, context=concept_ctx
    )
    ops_concept_model_json, _ = ensure_concept_summary(
      model="ops_concept",
      prev_card=prev_ops_concept,
      card=ops_concept_model_json,
      now_ms=now_ms,
      context=concept_ctx,
    )
    milestones_model_json, _ = ensure_concept_summary(
      model="milestones", prev_card=prev_milestones, card=milestones_model_json, now_ms=now_ms, context=concept_ctx
    )
    cogs_model_json, _ = ensure_concept_summary(
      model="cogs", prev_card=prev_cogs, card=cogs_model_json, now_ms=now_ms, context=concept_ctx
    )
    gna_model_json, _ = ensure_concept_summary(
      model="gna", prev_card=prev_gna, card=gna_model_json, now_ms=now_ms, context=concept_ctx
    )
  except Exception:
    pass

  # Audit logs.
  try:
    current_fact_nonce = int(consult_row.get("fact_revision_nonce") or 0)
  except Exception:
    current_fact_nonce = 0
  fact_nonce_out, fact_revisions_out = _compute_fact_revisions(
    prev_state=prev_state,
    next_state={
      "business": business_facts,
      "ops": ops_json,
      "market": market_json,
      "people": people_json,
      "financials": financials_json,
    },
    patch=fact_patch,
    existing_nonce=current_fact_nonce,
    existing_revisions_raw=consult_row.get("fact_revisions_json"),
    now_ms=now_ms,
  )

  try:
    current_driver_nonce = int(consult_row.get("driver_revision_nonce") or 0)
  except Exception:
    current_driver_nonce = 0
  driver_nonce_out, driver_events_out = _compute_driver_events(
    driver_changes=driver_changes,
    existing_nonce=current_driver_nonce,
    existing_events_raw=consult_row.get("driver_events_json"),
    now_ms=now_ms,
  )

  from intake_consult_draft import append_messages  # type: ignore

  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    business_facts=(business_facts if fact_patch else None),
    operating_model_json=(ops_json if (fact_patch or driver_changes) else None),
    target_market_json=(market_json if any(k.startswith("market.") for k in fact_patch.keys()) else None),
    people_json=(people_json if any(k.startswith("people.") for k in fact_patch.keys()) else None),
    financials_json=(financials_json if any(k.startswith("financials.") for k in fact_patch.keys()) else None),
    marketing_model_json=(marketing_model_json if marketing_model_json != prev_marketing else None),
    pricing_model_json=(pricing_model_json if pricing_model_json != prev_pricing else None),
    revenue_model_json=(revenue_model_json if revenue_model_json != prev_revenue else None),
    headcount_model_json=(headcount_model_json if headcount_model_json != prev_headcount else None),
    fulfillment_model_json=(fulfillment_model_json if fulfillment_model_json != prev_fulfillment else None),
    ops_concept_model_json=(ops_concept_model_json if ops_concept_model_json != prev_ops_concept else None),
    milestones_model_json=(milestones_model_json if milestones_model_json != prev_milestones else None),
    cogs_model_json=(cogs_model_json if cogs_model_json != prev_cogs else None),
    gna_model_json=(gna_model_json if gna_model_json != prev_gna else None),
    year1_marketing_spend=year1_marketing_spend_out,
    year1_payroll=year1_payroll_out,
    year1_revenue=year1_revenue_out,
    year1_cogs=year1_cogs_out,
    year1_gna_total=year1_gna_total_out,
    driver_events=driver_events_out,
    driver_revision_nonce=driver_nonce_out,
    fact_revision_nonce=fact_nonce_out,
    fact_revisions=fact_revisions_out,
  )

  return {
    "business_facts": business_facts,
    "ops_json": ops_json,
    "market_json": market_json,
    "people_json": people_json,
    "financials_json": financials_json,
    "marketing_model_json": marketing_model_json,
    "pricing_model_json": pricing_model_json,
    "revenue_model_json": revenue_model_json,
    "headcount_model_json": headcount_model_json,
    "fulfillment_model_json": fulfillment_model_json,
    "ops_concept_model_json": ops_concept_model_json,
    "milestones_model_json": milestones_model_json,
    "cogs_model_json": cogs_model_json,
    "gna_model_json": gna_model_json,
  }
