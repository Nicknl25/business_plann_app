from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from flask import jsonify

from unified_intake.parsing import parse_json_dict as _parse_json_dict
from unified_intake.draft_service import apply_chat_patch_and_persist


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


def post_intake_model_cards_handler(*, app, request):
  """
  Persist model-card driver updates (Accept/Edit) to the consult draft immediately.

  This endpoint is internal-only infrastructure. It must:
  - write to SQL immediately (same semantics as chat patching)
  - recompute derived rollups deterministically
  - never change routing/confirmations/focus
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

    model_column = _model_column(model)
    current_card = _parse_json_dict(consult.get(model_column)) if model_column else {}
    target_lob_keys = _lob_keys_from_card(current_card) if apply_to_all_lobs else [lob_key]

    # Apply updates per LOB so we can represent multiple LOB targets without key collisions in the patch dict.
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

      # Refresh consult row so driver/fact nonces advance deterministically across multiple LOB writes.
      consult = get_draft(conn, draft_id=str(draft_id).strip())
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

    if action == "accept" and proposal_id:
      consult = get_draft(conn, draft_id=str(draft_id).strip())
      proposals = _parse_json_list(consult.get("model_card_proposals_json"))
      next_props = [
        p
        for p in proposals
        if not (isinstance(p, dict) and str(p.get("id") or "").strip() == str(proposal_id).strip())
      ]
      if next_props != proposals:
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[],
          model_card_proposals=next_props,
        )

    return jsonify({"status": "ok"}), 200
  except Exception as exc:
    app.logger.exception("Failed model-cards persist: %s", exc)
    return jsonify({"error": "server_error", "detail": str(exc)}), 500
  finally:
    try:
      conn.close()
    except Exception:
      pass
