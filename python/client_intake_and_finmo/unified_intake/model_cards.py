from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from flask import jsonify

from unified_intake.parsing import parse_json_dict as _parse_json_dict
from unified_intake.draft_service import apply_chat_patch_and_persist
from unified_intake.proposals import (  # type: ignore
  append_proposal_event,
  build_patch_from_proposal,
  build_proposals_from_patch,
  proposal_payload,
  validate_proposal_hash,
)
from unified_intake.dependencies import dependency_proposals_for_patch  # type: ignore


def _require_nonempty_str(value: Any) -> Optional[str]:
  v = str(value or "").strip()
  return v if v else None


_ALLOWED_MODELS = {
  "marketing",
  "pricing",
  "revenue",
  "headcount",
  "fulfillment",
  "ops_concept",
  "milestones",
  "cogs",
  "gna",
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


def _merge_pending_patch(pending_patch: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
  merged = dict(pending_patch or {})
  for raw_key, value in (patch or {}).items():
    key = str(raw_key or "").strip()
    if not key:
      continue
    merged[key] = value
  return merged


def _remove_pending_patch_keys(pending_patch: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
  updated = dict(pending_patch or {})
  for raw_key in (patch or {}).keys():
    key = str(raw_key or "").strip()
    if not key:
      continue
    updated.pop(key, None)
  return updated


def _model_column(model: str) -> Optional[str]:
  m = str(model or "").strip().lower()
  mapping = {
    "marketing": "marketing_model_json",
    "pricing": "pricing_model_json",
    "revenue": "revenue_model_json",
    "headcount": "headcount_model_json",
    "fulfillment": "fulfillment_model_json",
    "ops_concept": "ops_concept_model_json",
    "milestones": "milestones_model_json",
    "cogs": "cogs_model_json",
    "gna": "gna_model_json",
  }
  return mapping.get(m)


def _lob_keys_from_card(card: Dict[str, Any]) -> List[str]:
  lobs = card.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return ["company_total"]
  out: List[str] = []
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    key = str(lob.get("lob_key") or "").strip()
    if not key:
      continue
    if key not in out:
      out.append(key)
  return out or ["company_total"]


def _format_commit_echo(proposal: Dict[str, Any]) -> str:
  updates = proposal.get("updates") if isinstance(proposal.get("updates"), list) else []
  if not updates:
    return ""

  def _label(key: str) -> str:
    raw = str(key or "").strip()
    if not raw:
      return "value"
    return raw.replace("_", " ").strip()

  def _format_value(value: Any) -> str:
    if value is None:
      return "none"
    if isinstance(value, bool):
      return "yes" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
      return str(value)
    if isinstance(value, str):
      return value
    if isinstance(value, list):
      return f"{len(value)} item" + ("s" if len(value) != 1 else "")
    if isinstance(value, dict):
      return "details captured"
    return str(value)

  parts: List[str] = []
  for u in updates[:4]:
    if not isinstance(u, dict):
      continue
    key = _label(u.get("key"))
    value = _format_value(u.get("value"))
    unit = str(u.get("unit") or "").strip()
    time_basis = str(u.get("time_basis") or "").strip()
    suffix = " / ".join([s for s in (unit, time_basis) if s])
    if suffix:
      parts.append(f"{key}: {value} ({suffix})")
    else:
      parts.append(f"{key}: {value}")
  remaining = len([u for u in updates if isinstance(u, dict)]) - len(parts)
  if remaining > 0:
    parts.append(f"+{remaining} more")
  return "Locked in: " + "; ".join(parts)


def post_intake_model_cards_handler(*, app, request):
  """
  Accept commits a pending proposal (with hash validation).
  Edit creates a new proposal without committing.
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = _require_nonempty_str(payload.get("draft_id"))
  if not draft_id:
    return jsonify({"error": "invalid_request", "detail": "draft_id is required"}), 400

  model = str(payload.get("model") or "").strip().lower()
  if model not in _ALLOWED_MODELS:
    return (
      jsonify(
        {
          "error": "invalid_request",
          "detail": "model must be one of: marketing, pricing, revenue, headcount, fulfillment, ops_concept, milestones, cogs, gna",
        }
      ),
      400,
    )

  updates = payload.get("updates")
  if updates is None:
    updates = []
  if not isinstance(updates, list) or not all(isinstance(u, dict) for u in updates):
    return jsonify({"error": "invalid_request", "detail": "updates must be a list of objects"}), 400

  action = str(payload.get("action") or "").strip().lower()
  if action not in ("accept", "edit"):
    action = "edit"
  proposal_id = _require_nonempty_str(payload.get("proposal_id"))
  proposal_hash = str(payload.get("proposal_hash") or "").strip() or None
  apply_to_all_lobs = bool(payload.get("apply_to_all_lobs"))

  lob_key = _require_nonempty_str(payload.get("lob_key")) or "company_total"

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import append_messages, get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return jsonify({"error": "server_error"}), 500

  conn = get_mysql_connection()
  try:
    consult = get_draft(conn, draft_id=str(draft_id).strip())
    try:
      proposal_nonce = int(consult.get("proposal_revision_nonce") or 0)
    except Exception:
      proposal_nonce = 0
    proposal_events_raw = consult.get("proposal_events_json")
    proposal_events_dirty = False
    pending_patch_json = _parse_json_dict(consult.get("draft_patch_json"))
    if not isinstance(pending_patch_json, dict):
      pending_patch_json = {}
    pending_patch: Dict[str, Any] = dict(pending_patch_json or {})
    pending_patch_dirty = False

    def _record_proposal_event(event: Dict[str, Any]) -> None:
      nonlocal proposal_nonce, proposal_events_raw, proposal_events_dirty
      proposal_nonce, proposal_events_raw = append_proposal_event(
        existing_events_raw=proposal_events_raw,
        existing_nonce=proposal_nonce,
        event=event,
      )
      proposal_events_dirty = True

    business_facts: Dict[str, Any] = {
      "name": consult.get("business_name"),
      "address": consult.get("business_address"),
      "start_date": consult.get("business_start_date"),
      "address_street": consult.get("address_street"),
      "address_city": consult.get("address_city"),
      "address_state": consult.get("address_state"),
      "address_zip": consult.get("address_zip"),
      "address_country": consult.get("address_country"),
    }

    ops_json = _parse_json_dict(consult.get("operating_model_json"))
    market_json = _parse_json_dict(consult.get("target_market_json"))
    people_json = _parse_json_dict(consult.get("people_json"))
    financials_json = _parse_json_dict(consult.get("financials_json"))

    marketing_model_json = _parse_json_dict(consult.get("marketing_model_json"))
    pricing_model_json = _parse_json_dict(consult.get("pricing_model_json"))
    revenue_model_json = _parse_json_dict(consult.get("revenue_model_json"))
    headcount_model_json = _parse_json_dict(consult.get("headcount_model_json"))
    fulfillment_model_json = _parse_json_dict(consult.get("fulfillment_model_json"))
    ops_concept_model_json = _parse_json_dict(consult.get("ops_concept_model_json"))
    milestones_model_json = _parse_json_dict(consult.get("milestones_model_json"))
    cogs_model_json = _parse_json_dict(consult.get("cogs_model_json"))
    gna_model_json = _parse_json_dict(consult.get("gna_model_json"))

    proposals_now = _parse_json_list(consult.get("model_card_proposals_json"))

    if action == "accept":
      if not proposal_id:
        return jsonify({"error": "invalid_request", "detail": "proposal_id is required"}), 400
      proposal = next(
        (
          p
          for p in proposals_now
          if isinstance(p, dict) and str(p.get("id") or "").strip() == str(proposal_id).strip()
        ),
        None,
      )
      if not proposal:
        return jsonify({"error": "invalid_request", "detail": "proposal not found"}), 404
      if not proposal_hash or not validate_proposal_hash(proposal, proposal_hash):
        return jsonify({"error": "invalid_request", "detail": "proposal hash mismatch"}), 409

      patch = build_patch_from_proposal(proposal)
      if patch:
        pending_patch = _remove_pending_patch_keys(pending_patch, patch)
        pending_patch_dirty = True
        updated = apply_chat_patch_and_persist(
          conn=conn,
          draft_id=str(draft_id).strip(),
          consult_row=consult,
          patch=patch,
          business_facts=business_facts,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          marketing_model_json=marketing_model_json,
          pricing_model_json=pricing_model_json,
          revenue_model_json=revenue_model_json,
          headcount_model_json=headcount_model_json,
          fulfillment_model_json=fulfillment_model_json,
          ops_concept_model_json=ops_concept_model_json,
          milestones_model_json=milestones_model_json,
          cogs_model_json=cogs_model_json,
          gna_model_json=gna_model_json,
        )
        marketing_model_json = (
          updated.get("marketing_model_json")
          if isinstance(updated.get("marketing_model_json"), dict)
          else marketing_model_json
        )
        pricing_model_json = (
          updated.get("pricing_model_json") if isinstance(updated.get("pricing_model_json"), dict) else pricing_model_json
        )
        revenue_model_json = (
          updated.get("revenue_model_json") if isinstance(updated.get("revenue_model_json"), dict) else revenue_model_json
        )
        headcount_model_json = (
          updated.get("headcount_model_json")
          if isinstance(updated.get("headcount_model_json"), dict)
          else headcount_model_json
        )
        fulfillment_model_json = (
          updated.get("fulfillment_model_json")
          if isinstance(updated.get("fulfillment_model_json"), dict)
          else fulfillment_model_json
        )
        ops_concept_model_json = (
          updated.get("ops_concept_model_json")
          if isinstance(updated.get("ops_concept_model_json"), dict)
          else ops_concept_model_json
        )
        milestones_model_json = (
          updated.get("milestones_model_json")
          if isinstance(updated.get("milestones_model_json"), dict)
          else milestones_model_json
        )
        cogs_model_json = (
          updated.get("cogs_model_json") if isinstance(updated.get("cogs_model_json"), dict) else cogs_model_json
        )
        gna_model_json = updated.get("gna_model_json") if isinstance(updated.get("gna_model_json"), dict) else gna_model_json

      _record_proposal_event(
        {
          "action": "proposal_committed",
          "proposal_id": proposal_id,
          "model": proposal.get("model"),
          "source": proposal.get("source"),
          "proposal_hash": proposal.get("proposal_hash"),
          "payload": proposal_payload(proposal),
        }
      )

      next_props = [
        p
        for p in proposals_now
        if not (isinstance(p, dict) and str(p.get("id") or "").strip() == str(proposal_id).strip())
      ]
      if not next_props and patch:
        dependent = dependency_proposals_for_patch(
          patch=patch,
          business_facts=business_facts,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          marketing_model_json=marketing_model_json,
          pricing_model_json=pricing_model_json,
          revenue_model_json=revenue_model_json,
          headcount_model_json=headcount_model_json,
          fulfillment_model_json=fulfillment_model_json,
          ops_concept_model_json=ops_concept_model_json,
          milestones_model_json=milestones_model_json,
          cogs_model_json=cogs_model_json,
          gna_model_json=gna_model_json,
        )
        if dependent:
          next_props = dependent
          for p in dependent:
            if isinstance(p, dict):
              _record_proposal_event(
                {
                  "action": "proposal_created",
                  "proposal_id": p.get("id"),
                  "model": p.get("model"),
                  "source": p.get("source"),
                  "payload": proposal_payload(p),
                }
              )
      interaction_mode = "button_only" if next_props else "chat"
      echo = _format_commit_echo(proposal)
      new_messages = [{"role": "assistant", "content": echo}] if echo else []
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=new_messages,
        model_card_proposals=next_props,
        interaction_mode=interaction_mode,
        draft_patch=(pending_patch if pending_patch_dirty else None),
        proposal_events=(proposal_events_raw if proposal_events_dirty else None),
        proposal_revision_nonce=(proposal_nonce if proposal_events_dirty else None),
      )
      return jsonify({"status": "ok", "proposal_id": proposal_id, "interaction_mode": interaction_mode}), 200

    # edit -> create a fresh proposal; do not commit yet.
    if not updates:
      return jsonify({"error": "invalid_request", "detail": "updates are required for edits"}), 400

    model_column = _model_column(model)
    current_card = _parse_json_dict(consult.get(model_column)) if model_column else {}
    target_lob_keys = _lob_keys_from_card(current_card) if apply_to_all_lobs else [lob_key]
    proposals: List[Dict[str, Any]] = []
    for lk in target_lob_keys:
      patch: Dict[str, Any] = {}
      for u in updates:
        key = _require_nonempty_str(u.get("key"))
        if not key:
          continue
        patch[f"{model}.{key}"] = {
          "lob_key": lk,
          "value": u.get("value"),
          "unit": u.get("unit"),
          "time_basis": u.get("time_basis"),
          "rationale": u.get("rationale"),
        }
      if not patch:
        continue
      pending_patch = _merge_pending_patch(pending_patch, patch)
      pending_patch_dirty = True
      proposals.extend(
        build_proposals_from_patch(
          patch=patch,
          business_facts=business_facts,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          marketing_model_json=marketing_model_json,
          pricing_model_json=pricing_model_json,
          revenue_model_json=revenue_model_json,
          headcount_model_json=headcount_model_json,
          fulfillment_model_json=fulfillment_model_json,
          ops_concept_model_json=ops_concept_model_json,
          milestones_model_json=milestones_model_json,
          cogs_model_json=cogs_model_json,
          gna_model_json=gna_model_json,
          source="edit",
        )
      )
    if not proposals:
      return jsonify({"error": "invalid_request", "detail": "unable to build proposal"}), 400

    def _should_replace(existing: Any) -> bool:
      if not isinstance(existing, dict):
        return False
      if proposal_id and str(existing.get("id") or "").strip() == str(proposal_id).strip():
        return True
      if apply_to_all_lobs:
        return str(existing.get("model") or "").strip().lower() == model
      if not proposal_id:
        existing_model = str(existing.get("model") or "").strip().lower()
        existing_lob = str(existing.get("lob_key") or "company_total").strip()
        return existing_model == model and existing_lob == lob_key
      return False

    for p in proposals:
      if isinstance(p, dict):
        _record_proposal_event(
          {
            "action": "proposal_created",
            "proposal_id": p.get("id"),
            "model": p.get("model"),
            "source": p.get("source"),
            "payload": proposal_payload(p),
          }
        )

    next_props = [p for p in proposals_now if not _should_replace(p)]
    next_props.extend(proposals)

    append_messages(
      conn,
      draft_id=str(draft_id).strip(),
      new_messages=[],
      model_card_proposals=next_props,
      interaction_mode="button_only",
      draft_patch=(pending_patch if pending_patch_dirty else None),
      proposal_events=(proposal_events_raw if proposal_events_dirty else None),
      proposal_revision_nonce=(proposal_nonce if proposal_events_dirty else None),
    )
    return jsonify({"status": "ok", "proposal_id": proposals[0].get("id")}), 200
  except Exception as exc:
    app.logger.exception("Failed model-cards persist: %s", exc)
    return jsonify({"error": "server_error", "detail": str(exc)}), 500
  finally:
    try:
      conn.close()
    except Exception:
      pass
