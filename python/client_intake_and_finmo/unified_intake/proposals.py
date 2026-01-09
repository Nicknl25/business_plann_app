from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from unified_intake.draft_service import apply_chat_patch
from unified_intake.parsing import parse_json_dict as _parse_json_dict


_MODEL_TITLES: Dict[str, str] = {
  "revenue": "Revenue (Year 1 model)",
  "fulfillment": "Fulfillment model",
  "ops_concept": "Operating concept",
  "milestones": "Milestones",
  "cogs": "Direct costs (COGS)",
  "gna": "Overhead (G&A)",
  "marketing": "Marketing budget (Year 1)",
  "headcount": "Headcount (Year 1 payroll)",
  "pricing": "Pricing",
}

_DERIVED_KEYS: Dict[str, Tuple[str, ...]] = {
  "marketing": ("year1_marketing_spend",),
  "headcount": ("year1_payroll",),
  "revenue": ("year1_revenue", "weekly_revenue"),
  "cogs": ("year1_cogs",),
  "gna": ("year1_gna_total",),
}


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


def _json_default(value: Any) -> Any:
  try:
    from decimal import Decimal

    if isinstance(value, Decimal):
      return float(value)
  except Exception:
    pass
  return value


def _hash_payload(payload: Dict[str, Any]) -> str:
  raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def proposal_payload(proposal: Dict[str, Any]) -> Dict[str, Any]:
  return {
    "model": proposal.get("model"),
    "lob_key": proposal.get("lob_key"),
    "lob_name": proposal.get("lob_name"),
    "updates": proposal.get("updates") if isinstance(proposal.get("updates"), list) else [],
    "derived": proposal.get("derived") if isinstance(proposal.get("derived"), list) else [],
  }


def attach_proposal_hash(proposal: Dict[str, Any]) -> Dict[str, Any]:
  payload = proposal_payload(proposal)
  hashed = _hash_payload(payload)
  return {**proposal, "proposal_hash": hashed}


def _get_lob(card: Dict[str, Any], *, lob_key: str) -> Dict[str, Any]:
  lobs = card.get("lobs")
  if not isinstance(lobs, list):
    return {}
  wanted = str(lob_key or "").strip() or "company_total"
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    if str(lob.get("lob_key") or "").strip() == wanted:
      return lob
  return {}


def _lob_name(card: Dict[str, Any], *, lob_key: str) -> Optional[str]:
  lob = _get_lob(card, lob_key=lob_key)
  name = str(lob.get("lob_name") or "").strip() if isinstance(lob, dict) else ""
  return name or None


def _driver_entry(card: Dict[str, Any], *, lob_key: str, key: str) -> Dict[str, Any]:
  lob = _get_lob(card, lob_key=lob_key)
  drivers = lob.get("drivers") if isinstance(lob, dict) else None
  if not isinstance(drivers, dict):
    return {}
  entry = drivers.get(key)
  return dict(entry) if isinstance(entry, dict) else {}


def _derived_entries(card: Dict[str, Any], *, lob_key: str, keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
  lob = _get_lob(card, lob_key=lob_key)
  derived = lob.get("derived") if isinstance(lob, dict) else None
  if not isinstance(derived, dict):
    return []
  out: List[Dict[str, Any]] = []
  for key in keys:
    entry = derived.get(key)
    if not isinstance(entry, dict):
      continue
    out.append(
      {
        "key": key,
        "value": entry.get("value"),
        "unit": entry.get("unit"),
        "time_basis": entry.get("time_basis"),
        "derivation": entry.get("derivation"),
      }
    )
  return out


def build_proposals_from_patch(
  *,
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
  source: str,
  now_ms: Optional[int] = None,
) -> List[Dict[str, Any]]:
  now_ms = int(now_ms or int(time.time() * 1000))
  preview = apply_chat_patch(
    patch=dict(patch or {}),
    business_facts=dict(business_facts or {}),
    ops_json=dict(ops_json or {}),
    market_json=dict(market_json or {}),
    people_json=dict(people_json or {}),
    financials_json=dict(financials_json or {}),
    marketing_model_json=dict(marketing_model_json or {}),
    pricing_model_json=dict(pricing_model_json or {}),
    revenue_model_json=dict(revenue_model_json or {}),
    headcount_model_json=dict(headcount_model_json or {}),
    fulfillment_model_json=dict(fulfillment_model_json or {}),
    ops_concept_model_json=dict(ops_concept_model_json or {}),
    milestones_model_json=dict(milestones_model_json or {}),
    cogs_model_json=dict(cogs_model_json or {}),
    gna_model_json=dict(gna_model_json or {}),
    now_ms=now_ms,
  )

  cards_by_model: Dict[str, Dict[str, Any]] = {
    "marketing": _parse_json_dict(preview.get("marketing_model_json")),
    "pricing": _parse_json_dict(preview.get("pricing_model_json")),
    "revenue": _parse_json_dict(preview.get("revenue_model_json")),
    "headcount": _parse_json_dict(preview.get("headcount_model_json")),
    "fulfillment": _parse_json_dict(preview.get("fulfillment_model_json")),
    "ops_concept": _parse_json_dict(preview.get("ops_concept_model_json")),
    "milestones": _parse_json_dict(preview.get("milestones_model_json")),
    "cogs": _parse_json_dict(preview.get("cogs_model_json")),
    "gna": _parse_json_dict(preview.get("gna_model_json")),
  }

  proposals: List[Dict[str, Any]] = []
  grouped: Dict[Tuple[str, str], List[Tuple[str, Any]]] = {}
  for raw_key, raw_value in (patch or {}).items():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    group, field = key.split(".", 1)
    group = group.strip().lower()
    field = field.strip()
    if not group or not field:
      continue
    lob_key = "company_total"
    if isinstance(raw_value, dict):
      if raw_value.get("lob_key"):
        lob_key = str(raw_value.get("lob_key") or "").strip() or "company_total"
    grouped.setdefault((group, lob_key), []).append((field, raw_value))

  for (group, lob_key), items in grouped.items():
    if group in ("business", "ops", "market", "people", "financials"):
      updates = [
        {
          "key": field,
          "value": (raw_value.get("value") if isinstance(raw_value, dict) and "value" in raw_value else raw_value),
        }
        for field, raw_value in items
      ]
      proposal = {
        "id": f"{group}_{now_ms}_{len(proposals)+1}",
        "model": group,
        "title": _MODEL_TITLES.get(group, group.replace("_", " ").title()),
        "lob_key": None,
        "lob_name": None,
        "updates": updates,
        "derived": [],
        "patch": {
          f"{group}.{field}": (
            raw_value.get("value") if isinstance(raw_value, dict) and "value" in raw_value else raw_value
          )
          for field, raw_value in items
        },
        "pending": True,
        "source": source,
        "created_at_ms": now_ms,
      }
      proposals.append(attach_proposal_hash(proposal))
      continue

    card = cards_by_model.get(group) if isinstance(cards_by_model.get(group), dict) else {}
    updates: List[Dict[str, Any]] = []
    patch_out: Dict[str, Any] = {}
    for field, raw_value in items:
      entry = _driver_entry(card, lob_key=lob_key, key=field)
      value = entry.get("value") if entry else raw_value
      unit = entry.get("unit") if entry else None
      time_basis = entry.get("time_basis") if entry else None
      rationale = entry.get("rationale") if entry else None
      updates.append(
        {
          "key": field,
          "value": value,
          "unit": unit,
          "time_basis": time_basis,
          "rationale": rationale,
        }
      )
      patch_out[f"{group}.{field}"] = {
        "lob_key": lob_key,
        "value": value,
        "unit": unit,
        "time_basis": time_basis,
        "rationale": rationale,
      }

    derived = _derived_entries(card, lob_key=lob_key, keys=_DERIVED_KEYS.get(group, ()))
    proposal = {
      "id": f"{group}_{now_ms}_{len(proposals)+1}",
      "model": group,
      "title": _MODEL_TITLES.get(group, group.replace("_", " ").title()),
      "lob_key": lob_key,
      "lob_name": _lob_name(card, lob_key=lob_key),
      "updates": updates,
      "derived": derived,
      "patch": patch_out,
      "pending": True,
      "source": source,
      "created_at_ms": now_ms,
    }
    proposals.append(attach_proposal_hash(proposal))

  return proposals


def proposal_from_updates(
  *,
  model: str,
  lob_key: str,
  lob_name: Optional[str],
  updates: List[Dict[str, Any]],
  derived: Optional[List[Dict[str, Any]]] = None,
  source: str,
  now_ms: Optional[int] = None,
) -> Dict[str, Any]:
  now_ms = int(now_ms or int(time.time() * 1000))
  proposal = {
    "id": f"{model}_{now_ms}",
    "model": model,
    "title": _MODEL_TITLES.get(model, model.replace("_", " ").title()),
    "lob_key": str(lob_key or "").strip() or "company_total",
    "lob_name": str(lob_name or "").strip() or None,
    "updates": updates,
    "derived": derived or [],
    "patch": {},
    "pending": True,
    "source": source,
    "created_at_ms": now_ms,
  }
  return attach_proposal_hash(proposal)


def build_patch_from_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
  patch = proposal.get("patch")
  if isinstance(patch, dict) and patch:
    return dict(patch)
  model = str(proposal.get("model") or "").strip().lower()
  lob_key = str(proposal.get("lob_key") or "company_total").strip() or "company_total"
  updates = proposal.get("updates") if isinstance(proposal.get("updates"), list) else []
  if model in ("business", "ops", "market", "people", "financials"):
    out: Dict[str, Any] = {}
    for u in updates:
      if not isinstance(u, dict):
        continue
      key = str(u.get("key") or "").strip()
      if not key:
        continue
      out[f"{model}.{key}"] = u.get("value")
    return out
  out: Dict[str, Any] = {}
  for u in updates:
    if not isinstance(u, dict):
      continue
    key = str(u.get("key") or "").strip()
    if not key:
      continue
    out[f"{model}.{key}"] = {
      "lob_key": lob_key,
      "value": u.get("value"),
      "unit": u.get("unit"),
      "time_basis": u.get("time_basis"),
      "rationale": u.get("rationale"),
    }
  return out


def validate_proposal_hash(proposal: Dict[str, Any], proposed_hash: str) -> bool:
  expected = str(proposal.get("proposal_hash") or "").strip()
  if not expected:
    expected = _hash_payload(proposal_payload(proposal))
  return expected and str(proposed_hash or "").strip() == expected


def append_proposal_event(
  *,
  existing_events_raw: Any,
  existing_nonce: int,
  event: Dict[str, Any],
  now_ms: Optional[int] = None,
  max_events: int = 500,
) -> Tuple[int, List[Dict[str, Any]]]:
  try:
    parsed = json.loads(str(existing_events_raw)) if existing_events_raw else []
    if not isinstance(parsed, list):
      parsed = []
  except Exception:
    parsed = []

  next_nonce = int(existing_nonce) + 1
  entry = dict(event or {})
  entry["nonce"] = next_nonce
  entry["at_ms"] = int(now_ms or int(time.time() * 1000))
  parsed.append(entry)
  if len(parsed) > max_events:
    parsed = parsed[-max_events:]
  return next_nonce, parsed
