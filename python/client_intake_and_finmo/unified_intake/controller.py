from __future__ import annotations

from datetime import date
import json
import time
from typing import Any, Dict, List, Optional

from flask import jsonify

from llm_timing import timed_span
from unified_intake.debug_log import debug_log
from unified_intake.parsing import (
  parse_json_dict as _parse_json_dict,
  parse_messages as _parse_messages,
)
from unified_intake.draft_service import (  # type: ignore
  apply_chat_patch,
  apply_chat_patch_and_persist,
  seed_lobs_if_needed,
  sync_pricing_from_ops_if_needed,
)
from unified_intake.dependencies import dependency_proposals_for_patch  # type: ignore
from unified_intake.proposals import (  # type: ignore
  append_proposal_event,
  build_patch_from_proposal,
  build_proposals_from_patch,
  proposal_payload,
  validate_proposal_hash,
)
from unified_intake.sections import ProposalRequiredError, expected_focus_from_snapshot, get_section  # type: ignore


def _reply(*, assistant_message: str, turn_outcome: str, next_focus: Optional[str], status_code: int = 200):
  return (
    jsonify(
      {
        "assistant_message": str(assistant_message or ""),
        "turn_outcome": str(turn_outcome or "").strip() or "ERROR",
        "next_focus": (str(next_focus).strip() if next_focus is not None else None),
      }
    ),
    status_code,
  )


def _proposal_error(*, status_code: int = 409):
  return (
    jsonify(
      {
        "detail": "We hit a snag preparing the next step. Please try again in a moment.",
      }
    ),
    status_code,
  )


def _require_nonempty_str(value: Any) -> Optional[str]:
  v = str(value or "").strip()
  return v if v else None


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


def _is_affirmative(message: str) -> bool:
  msg_raw = " ".join(str(message or "").strip().lower().split())
  if not msg_raw or len(msg_raw) > 48:
    return False
  if "?" in msg_raw:
    return False
  msg = msg_raw.strip(" .!?,")
  if not msg:
    return False
  if any(ch.isdigit() for ch in msg):
    return False

  negatives = {
    "no",
    "nope",
    "nah",
    "not",
    "never",
    "dont",
    "don't",
    "idk",
    "unsure",
    "maybe",
    "depends",
    "later",
    "skip",
    "pass",
    "wait",
    "hold",
  }
  if any(token in msg for token in negatives):
    return False

  tokens = msg.split()
  if len(tokens) > 4:
    return False

  if tokens and tokens[0] in {
    "ok",
    "okay",
    "k",
    "kk",
    "sure",
    "good",
    "great",
    "fine",
    "agree",
    "agreed",
    "correct",
    "right",
    "works",
    "alright",
  }:
    return True

  if tokens and tokens[0].startswith(("ye", "ya", "yu")) and len(tokens[0]) <= 8:
    return True

  if len(tokens) >= 2 and tokens[0] == "sounds" and tokens[1] in {"good", "great", "fine", "ok", "okay", "right"}:
    return True

  if msg in {"all right", "sounds good", "sounds great", "sounds fine", "sounds ok", "sounds okay"}:
    return True

  return False


def _proposal_from_list(
  proposals: List[Any],
  proposal_id: Optional[str] = None,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
  items = list(proposals or [])
  if proposal_id:
    items = [
      item
      for item in items
      if isinstance(item, dict) and str(item.get("id") or "").strip() == str(proposal_id).strip()
    ]
  for item in reversed(items):
    if not isinstance(item, dict):
      continue
    if item.get("pending") is False:
      continue
    pid = str(item.get("id") or "").strip() or None
    return item, pid
  return None, None


def _build_model_proposal(*, model: str, patch: Dict[str, Any]) -> Dict[str, Any]:
  now_ms = int(time.time() * 1000)
  model_norm = str(model or "").strip().lower() or "unknown"
  updates: List[Dict[str, Any]] = []
  lob_key = "company_total"
  for raw_key, val in (patch or {}).items():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    model_key, field = key.split(".", 1)
    if str(model_key or "").strip().lower() != model_norm:
      continue
    value = val
    unit = None
    time_basis = None
    rationale = None
    if isinstance(val, dict):
      if val.get("lob_key"):
        lob_key = str(val.get("lob_key") or "").strip() or lob_key
      if "value" in val:
        value = val.get("value")
      unit = val.get("unit")
      time_basis = val.get("time_basis")
      rationale = val.get("rationale")
    updates.append(
      {
        "key": field,
        "value": value,
        "unit": unit,
        "time_basis": time_basis,
        "rationale": rationale,
      }
    )
  return {
    "id": f"{model_norm}_{now_ms}",
    "model": model_norm,
    "title": {
      "revenue": "Revenue (Year 1 model)",
      "fulfillment": "Fulfillment model",
      "ops_concept": "Operating concept",
      "milestones": "Milestones",
      "cogs": "Direct costs (COGS)",
      "gna": "Overhead (G&A)",
    }.get(model_norm, model_norm),
    "lob_key": lob_key,
    "lob_name": None,
    "updates": updates,
    "derived": [],
    "patch": dict(patch),
    "pending": True,
    "created_at_ms": now_ms,
  }


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

def _clip_recent_messages_for_router(
  messages: List[Dict[str, Any]],
  *,
  max_messages: int = 12,
  max_total_chars: int = 4500,
  max_message_chars: int = 700,
) -> List[Dict[str, str]]:
  """
  Build a compact routing context without mutating or truncating the stored chat history.
  This is ONLY used for intent routing context to keep prompts small and reliable.
  """
  tail = list(messages[-max_messages:]) if isinstance(messages, list) else []
  clipped_rev: List[Dict[str, str]] = []
  total = 0
  for msg in reversed(tail):
    if not isinstance(msg, dict):
      continue
    role = str(msg.get("role") or "").strip() or "user"
    content = str(msg.get("content") or "")
    content = " ".join(content.replace("\r", "\n").split())
    if len(content) > max_message_chars:
      content = content[:max_message_chars].rstrip() + "…"
    entry = {"role": role, "content": content}
    size = len(content) + len(role) + 4
    if clipped_rev and (total + size) > max_total_chars:
      break
    if (not clipped_rev) and size > max_total_chars:
      entry["content"] = entry["content"][: max(0, max_total_chars - 16)].rstrip() + "…"
      clipped_rev.append(entry)
      break
    clipped_rev.append(entry)
    total += size
  return list(reversed(clipped_rev))


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


def _build_snapshot(
  *,
  confirmations: Dict[str, bool],
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  pricing_model_json: Dict[str, Any],
  revenue_model_json: Dict[str, Any],
  ops_concept_model_json: Dict[str, Any],
  fulfillment_model_json: Dict[str, Any],
  headcount_model_json: Dict[str, Any],
  milestones_model_json: Dict[str, Any],
  cogs_model_json: Dict[str, Any],
  gna_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  return {
    "confirmations": dict(confirmations or {}),
    "business_facts": dict(business_facts or {}),
    "ops_json": dict(ops_json or {}),
    "market_json": dict(market_json or {}),
    "people_json": dict(people_json or {}),
    "financials_json": dict(financials_json or {}),
    "marketing_model_json": dict(marketing_model_json or {}),
    "pricing_model_json": dict(pricing_model_json or {}),
    "revenue_model_json": dict(revenue_model_json or {}),
    "ops_concept_model_json": dict(ops_concept_model_json or {}),
    "fulfillment_model_json": dict(fulfillment_model_json or {}),
    "headcount_model_json": dict(headcount_model_json or {}),
    "milestones_model_json": dict(milestones_model_json or {}),
    "cogs_model_json": dict(cogs_model_json or {}),
    "gna_model_json": dict(gna_model_json or {}),
  }

def _merge_finalized_section(prev: Dict[str, Any], patch: Any) -> Dict[str, Any]:
  """
  Merge finalizer output into an existing section object without wiping previously-captured
  values when the finalizer returns null/empty placeholders.
  """
  base = dict(prev or {}) if isinstance(prev, dict) else {}
  if not isinstance(patch, dict) or not patch:
    return base

  def _has_meaningful_value(v: Any) -> bool:
    if v is None:
      return False
    if isinstance(v, str):
      return bool(v.strip())
    return True

  out = dict(base)
  for k, v in patch.items():
    if k in ("assistant_message", "turn_outcome"):
      continue
    if _has_meaningful_value(v):
      out[k] = v
  return out


def post_intake_consult_session_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  try:
    from intake_submission import generate_client_id, get_mysql_connection  # type: ignore
    from intake_consult_draft import create_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import intake consult draft helpers: %s", exc)
    return _reply(assistant_message="", turn_outcome="ERROR_SERVER_IMPORTS", next_focus=None, status_code=500)

  client_id = generate_client_id()
  conn = get_mysql_connection()
  try:
    draft = create_draft(conn, client_id=client_id)
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
        "interaction_mode": "chat",
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def get_intake_consult_draft_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  draft_id = request.args.get("draft_id")
  if not _require_nonempty_str(draft_id):
    return jsonify({"error": "invalid_request", "detail": "draft_id is required"}), 400

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return jsonify({"error": "server_error"}), 500

  conn = get_mysql_connection()
  try:
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
    except Exception as exc:
      return jsonify({"error": "not_found", "detail": str(exc)}), 404

    interaction_mode = str(draft.get("interaction_mode") or "chat").strip().lower()
    if interaction_mode not in ("chat", "button_only"):
      interaction_mode = "chat"

    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
        "draft_status": draft.get("status"),
        "active_focus": draft.get("active_focus"),
        "interaction_mode": interaction_mode,
        "ops_confirmed": bool(draft.get("ops_confirmed")),
        "market_confirmed": bool(draft.get("market_confirmed")),
        "people_confirmed": bool(draft.get("people_confirmed")),
        "financials_confirmed": bool(draft.get("financials_confirmed")),
        "consistency_passed": bool(draft.get("consistency_passed")),
        "business_name": draft.get("business_name"),
        "business_address": draft.get("business_address"),
        "address_street": draft.get("address_street"),
        "address_city": draft.get("address_city"),
        "address_state": draft.get("address_state"),
        "address_zip": draft.get("address_zip"),
        "address_country": draft.get("address_country"),
        "business_start_date": draft.get("business_start_date"),
        "messages_json": draft.get("messages_json"),
        "operating_model_json": draft.get("operating_model_json"),
        "target_market_json": draft.get("target_market_json"),
        "people_json": draft.get("people_json"),
        "financials_json": draft.get("financials_json"),
        "ops_concept_model_json": draft.get("ops_concept_model_json"),
        "fulfillment_model_json": draft.get("fulfillment_model_json"),
        "marketing_model_json": draft.get("marketing_model_json"),
        "pricing_model_json": draft.get("pricing_model_json"),
        "revenue_model_json": draft.get("revenue_model_json"),
        "headcount_model_json": draft.get("headcount_model_json"),
        "milestones_model_json": draft.get("milestones_model_json"),
        "cogs_model_json": draft.get("cogs_model_json"),
        "gna_model_json": draft.get("gna_model_json"),
        "model_card_proposals_json": draft.get("model_card_proposals_json"),
        "driver_events_json": draft.get("driver_events_json"),
        "driver_revision_nonce": draft.get("driver_revision_nonce"),
        "year1_revenue": draft.get("year1_revenue"),
        "year1_marketing_spend": draft.get("year1_marketing_spend"),
        "year1_payroll": draft.get("year1_payroll"),
        "year1_cogs": draft.get("year1_cogs"),
        "year1_gna_total": draft.get("year1_gna_total"),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def post_intake_consult_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = _require_nonempty_str(payload.get("draft_id"))
  if not draft_id:
    return _reply(assistant_message="", turn_outcome="ERROR_INVALID_REQUEST", next_focus=None, status_code=400)

  raw_message = payload.get("message")
  message = str(raw_message or "").strip()
  response_intent = str(payload.get("response_intent") or "").strip().lower()
  if response_intent not in ("accept", "reject", "edit"):
    response_intent = ""
  proposal_id = str(payload.get("proposal_id") or "").strip() or None
  proposal_hash = str(payload.get("proposal_hash") or "").strip() or None
  starting = (raw_message is None or not message) and not response_intent

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import append_messages, get_draft  # type: ignore
    from api_handlers.shared_context import build_shared_context  # type: ignore
    from fact_templates import sanitize_fact_template  # type: ignore
    from intent_router import route_intent  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import unified intake helpers: %s", exc)
    return _reply(assistant_message="", turn_outcome="ERROR_SERVER_IMPORTS", next_focus=None, status_code=500)

  conn = get_mysql_connection()
  try:
    with timed_span("unified_intake.get_draft", draft_id=str(draft_id).strip()):
      consult = get_draft(conn, draft_id=str(draft_id).strip())
    draft_status = str(consult.get("status") or "").strip().lower()
    if draft_status == "submitted":
      return _reply(assistant_message="", turn_outcome="ERROR_DUPLICATE_SUBMIT", next_focus=None, status_code=409)

    client_id = str(consult.get("client_id") or "").strip()
    with timed_span("unified_intake.parse_messages", draft_id=str(draft_id).strip()):
      messages = _parse_messages(consult.get("messages_json"))

    with timed_span("unified_intake.parse_state_json", draft_id=str(draft_id).strip()):
      ops_json = _parse_json_dict(consult.get("operating_model_json"))
      market_json = _parse_json_dict(consult.get("target_market_json"))
      people_json = _parse_json_dict(consult.get("people_json"))
      financials_json = _parse_json_dict(consult.get("financials_json"))
      marketing_model_json = _parse_json_dict(consult.get("marketing_model_json"))
      pricing_model_json = _parse_json_dict(consult.get("pricing_model_json"))
      revenue_model_json = _parse_json_dict(consult.get("revenue_model_json"))
      ops_concept_model_json = _parse_json_dict(consult.get("ops_concept_model_json"))
      fulfillment_model_json = _parse_json_dict(consult.get("fulfillment_model_json"))
      headcount_model_json = _parse_json_dict(consult.get("headcount_model_json"))
      milestones_model_json = _parse_json_dict(consult.get("milestones_model_json"))
      cogs_model_json = _parse_json_dict(consult.get("cogs_model_json"))
      gna_model_json = _parse_json_dict(consult.get("gna_model_json"))
      pending_patch_json = _parse_json_dict(consult.get("draft_patch_json"))
      if not isinstance(pending_patch_json, dict):
        pending_patch_json = {}

    model_card_proposals = _parse_json_list(consult.get("model_card_proposals_json"))
    proposals_dirty = False
    try:
      proposal_nonce = int(consult.get("proposal_revision_nonce") or 0)
    except Exception:
      proposal_nonce = 0
    proposal_events_raw = consult.get("proposal_events_json")
    proposal_events_dirty = False
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

    active_focus = _require_nonempty_str(consult.get("active_focus"))
    if not active_focus:
      return _reply(assistant_message="", turn_outcome="ERROR_INVALID_STATE", next_focus=None, status_code=500)
    active_focus_norm = str(active_focus).strip().lower()
    if active_focus_norm not in ("ops", "market", "people", "financials", "done"):
      return _reply(assistant_message="", turn_outcome="ERROR_INVALID_STATE", next_focus=None, status_code=500)

    interaction_mode = str(consult.get("interaction_mode") or "chat").strip().lower()
    if interaction_mode not in ("chat", "button_only"):
      interaction_mode = "chat"
    if interaction_mode == "button_only" and (not starting) and message:
      # UX recovery: legacy drafts may be stuck in button_only mode, which creates a hard dead-end
      # for chat input. Self-heal to chat and continue processing the same message (no retyping).
      try:
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[],
          interaction_mode="chat",
        )
      except Exception:
        pass
      interaction_mode = "chat"

    debug_log(
      "request_start",
      draft_id=draft_id,
      active_focus=active_focus_norm,
      interaction_mode=interaction_mode,
      starting=starting,
      message_len=len(message) if message else 0,
      response_intent=response_intent or None,
      proposal_id=proposal_id,
      proposal_hash=proposal_hash,
    )

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

    # Explicit client-detail updates from UI (no intent inference).
    if payload.get("business_name") is not None:
      name_raw = _require_nonempty_str(payload.get("business_name"))
      if name_raw:
        business_facts["name"] = name_raw
    if payload.get("address") is not None:
      addr_raw = _require_nonempty_str(payload.get("address"))
      if addr_raw:
        business_facts["address"] = addr_raw
    start_date_raw = payload.get("business_start_date")
    if start_date_raw is None:
      start_date_raw = payload.get("businessStartDate") or payload.get("business_startDate")
    if start_date_raw is not None:
      sd_raw = _require_nonempty_str(start_date_raw)
      if sd_raw:
        business_facts["start_date"] = sd_raw
    for key in ("address_street", "address_city", "address_state", "address_zip", "address_country"):
      if payload.get(key) is None:
        continue
      val = _require_nonempty_str(payload.get(key))
      if val:
        business_facts[key] = val

    confirmations: Dict[str, bool] = {
      "ops": bool(consult.get("ops_confirmed")),
      "market": bool(consult.get("market_confirmed")),
      "people": bool(consult.get("people_confirmed")),
      "financials": bool(consult.get("financials_confirmed")),
    }
    interaction_mode_override: Optional[str] = None

    snapshot = _build_snapshot(
      confirmations=confirmations,
      business_facts=business_facts,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      marketing_model_json=marketing_model_json,
      pricing_model_json=pricing_model_json,
      revenue_model_json=revenue_model_json,
      ops_concept_model_json=ops_concept_model_json,
      fulfillment_model_json=fulfillment_model_json,
      headcount_model_json=headcount_model_json,
      milestones_model_json=milestones_model_json,
      cogs_model_json=cogs_model_json,
      gna_model_json=gna_model_json,
    )

    expected_focus = expected_focus_from_snapshot(snapshot)
    expected_focus_norm = str(expected_focus).strip().lower()
    active_focus_for_router = active_focus_norm
    if active_focus_norm != expected_focus_norm:
      debug_log("focus_corrected", from_focus=active_focus_norm, to_focus=expected_focus_norm)
      # Self-heal inconsistent drafts (legacy/partial writes) by snapping focus to the fixed-order expectation,
      # but DO NOT drop the user's message. Proceed in the same request under the corrected focus.
      try:
        from intake_consult_draft import append_messages  # type: ignore

        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[],
          active_focus=expected_focus_norm,
        )
      except Exception:
        pass
      active_focus_norm = expected_focus_norm
      active_focus_for_router = expected_focus_norm

    if active_focus_norm == "done":
      debug_log("request_done", draft_id=draft_id)
      return _reply(assistant_message="", turn_outcome="DONE", next_focus=None, status_code=200)

    with timed_span("unified_intake.build_shared_context", draft_id=str(draft_id).strip()):
      shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())

    if (not starting) and message:
      with timed_span("unified_intake.seed_lobs_if_needed", draft_id=str(draft_id).strip()):
        (
          ops_concept_model_json,
          marketing_model_json,
          pricing_model_json,
          revenue_model_json,
          headcount_model_json,
          fulfillment_model_json,
          milestones_model_json,
          cogs_model_json,
          gna_model_json,
        ) = seed_lobs_if_needed(
          conn=conn,
          draft_id=str(draft_id).strip(),
          message=message,
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

    with timed_span("unified_intake.sync_pricing_from_ops_if_needed", draft_id=str(draft_id).strip()):
      pricing_model_json = sync_pricing_from_ops_if_needed(
        conn=conn,
        draft_id=str(draft_id).strip(),
        ops_json=ops_json,
        pricing_model_json=pricing_model_json,
      )

    draft_business_facts = dict(business_facts or {})
    draft_ops_json = dict(ops_json or {})
    draft_market_json = dict(market_json or {})
    draft_people_json = dict(people_json or {})
    draft_financials_json = dict(financials_json or {})
    draft_marketing_model_json = dict(marketing_model_json or {})
    draft_pricing_model_json = dict(pricing_model_json or {})
    draft_revenue_model_json = dict(revenue_model_json or {})
    draft_ops_concept_model_json = dict(ops_concept_model_json or {})
    draft_fulfillment_model_json = dict(fulfillment_model_json or {})
    draft_headcount_model_json = dict(headcount_model_json or {})
    draft_milestones_model_json = dict(milestones_model_json or {})
    draft_cogs_model_json = dict(cogs_model_json or {})
    draft_gna_model_json = dict(gna_model_json or {})

    if pending_patch:
      try:
        draft_preview = apply_chat_patch(
          patch=pending_patch,
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
      except Exception:
        draft_preview = None
      if isinstance(draft_preview, dict):
        draft_business_facts = (
          draft_preview.get("business_facts") if isinstance(draft_preview.get("business_facts"), dict) else draft_business_facts
        )
        draft_ops_json = draft_preview.get("ops_json") if isinstance(draft_preview.get("ops_json"), dict) else draft_ops_json
        draft_market_json = draft_preview.get("market_json") if isinstance(draft_preview.get("market_json"), dict) else draft_market_json
        draft_people_json = draft_preview.get("people_json") if isinstance(draft_preview.get("people_json"), dict) else draft_people_json
        draft_financials_json = (
          draft_preview.get("financials_json") if isinstance(draft_preview.get("financials_json"), dict) else draft_financials_json
        )
        draft_marketing_model_json = (
          draft_preview.get("marketing_model_json")
          if isinstance(draft_preview.get("marketing_model_json"), dict)
          else draft_marketing_model_json
        )
        draft_pricing_model_json = (
          draft_preview.get("pricing_model_json")
          if isinstance(draft_preview.get("pricing_model_json"), dict)
          else draft_pricing_model_json
        )
        draft_revenue_model_json = (
          draft_preview.get("revenue_model_json")
          if isinstance(draft_preview.get("revenue_model_json"), dict)
          else draft_revenue_model_json
        )
        draft_ops_concept_model_json = (
          draft_preview.get("ops_concept_model_json")
          if isinstance(draft_preview.get("ops_concept_model_json"), dict)
          else draft_ops_concept_model_json
        )
        draft_fulfillment_model_json = (
          draft_preview.get("fulfillment_model_json")
          if isinstance(draft_preview.get("fulfillment_model_json"), dict)
          else draft_fulfillment_model_json
        )
        draft_headcount_model_json = (
          draft_preview.get("headcount_model_json")
          if isinstance(draft_preview.get("headcount_model_json"), dict)
          else draft_headcount_model_json
        )
        draft_milestones_model_json = (
          draft_preview.get("milestones_model_json")
          if isinstance(draft_preview.get("milestones_model_json"), dict)
          else draft_milestones_model_json
        )
        draft_cogs_model_json = (
          draft_preview.get("cogs_model_json") if isinstance(draft_preview.get("cogs_model_json"), dict) else draft_cogs_model_json
        )
        draft_gna_model_json = (
          draft_preview.get("gna_model_json") if isinstance(draft_preview.get("gna_model_json"), dict) else draft_gna_model_json
        )

    # Build baseline for intent routing (internal only).
    baseline_json = {
      "active_focus": active_focus_for_router,
      "business": draft_business_facts,
      "ops": draft_ops_json,
      "market": draft_market_json,
      "people": draft_people_json,
      "financials": draft_financials_json,
      "pricing": draft_pricing_model_json,
      "revenue": draft_revenue_model_json,
      "marketing": draft_marketing_model_json,
      "headcount": draft_headcount_model_json,
      "fulfillment": draft_fulfillment_model_json,
      "ops_concept": draft_ops_concept_model_json,
      "milestones": draft_milestones_model_json,
      "cogs": draft_cogs_model_json,
      "gna": draft_gna_model_json,
    }

    snapshot = _build_snapshot(
      confirmations=confirmations,
      business_facts=draft_business_facts,
      ops_json=draft_ops_json,
      market_json=draft_market_json,
      people_json=draft_people_json,
      financials_json=draft_financials_json,
      marketing_model_json=draft_marketing_model_json,
      pricing_model_json=draft_pricing_model_json,
      revenue_model_json=draft_revenue_model_json,
      ops_concept_model_json=draft_ops_concept_model_json,
      fulfillment_model_json=draft_fulfillment_model_json,
      headcount_model_json=draft_headcount_model_json,
      milestones_model_json=draft_milestones_model_json,
      cogs_model_json=draft_cogs_model_json,
      gna_model_json=draft_gna_model_json,
    )

    intake_context: Dict[str, Any] = {
      "client_id": client_id,
      "draft_id": str(draft_id).strip(),
      "today_iso": date.today().isoformat(),
      "business_name": draft_business_facts.get("name"),
      "business_start_date": draft_business_facts.get("start_date"),
      "address": draft_business_facts.get("address"),
      "consumer_type": str((draft_ops_json or {}).get("consumer_type") or "consumer"),
      "naics_6": None,
      "shared_context": shared_context,
      "operating_model_json": draft_ops_json,
      "fulfillment_model_json": draft_fulfillment_model_json,
      "ops_concept_model_json": draft_ops_concept_model_json,
      "target_market_json": draft_market_json,
      "people_json": draft_people_json,
      "financials_json": draft_financials_json,
    }

    section = get_section(active_focus_norm)

    if starting:
      try:
        with timed_span("unified_intake.section.chat_turn", draft_id=str(draft_id).strip(), focus=active_focus_norm, starting=True):
          turn = section.chat_turn(
            intake_context=intake_context,
            conversation_messages=messages,
            snapshot=snapshot,
            starting=True,
          )
      except ProposalRequiredError as exc:
        app.logger.error("Proposal required failure (starting=%s, focus=%s, route=%s)", True, active_focus_norm, getattr(exc, "route", ""))
        debug_log("proposal_required_error", focus=active_focus_norm, route=getattr(exc, "route", ""))
        return _proposal_error()
      except Exception as exc:
        app.logger.exception("Consultant failed: %s", exc)
        return _reply(assistant_message="", turn_outcome="ERROR_CONSULTANT_FAILED", next_focus=active_focus_norm, status_code=500)

      assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
      turn_outcome = str(turn.get("turn_outcome") or "ASK_NEXT").strip().upper() or "ASK_NEXT"
      proposal_patch = turn.get("_proposal_patch") if isinstance(turn, dict) else None
      if isinstance(proposal_patch, dict) and proposal_patch:
        pending_patch = _merge_pending_patch(pending_patch, proposal_patch)
        pending_patch_dirty = True
      debug_log(
        "section_turn",
        focus=active_focus_norm,
        outcome=turn_outcome,
        assistant_len=len(assistant_text),
        starting=True,
      )
      with timed_span("unified_intake.append_messages", draft_id=str(draft_id).strip(), focus=active_focus_norm, starting=True):
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[{"role": "assistant", "content": assistant_text}],
          active_focus=active_focus_norm,
          model_card_proposals=(model_card_proposals if proposals_dirty else None),
          draft_patch=(pending_patch if pending_patch_dirty else None),
          interaction_mode=interaction_mode_override,
          business_facts=business_facts,
          proposal_events=(proposal_events_raw if proposal_events_dirty else None),
          proposal_revision_nonce=(proposal_nonce if proposal_events_dirty else None),
        )
      return _reply(assistant_message=assistant_text, turn_outcome=turn_outcome, next_focus=active_focus_norm, status_code=200)

    # Non-starting: proposals are created from extractor output; commits only on explicit accept.
    patch: Optional[Dict[str, Any]] = None
    proposal_notice: Optional[str] = None
    commit_echo: Optional[str] = None
    advance_focus = False
    next_focus_override: Optional[str] = None
    confirmations_override: Optional[Dict[str, bool]] = None
    status_override: Optional[str] = None
    completed_override = False
    consistency_override: Optional[bool] = None
    if response_intent:
      if not message:
        message = {"accept": "yes", "reject": "no", "edit": "edit"}.get(response_intent, "")
      if response_intent == "accept":
        proposal, resolved_id = _proposal_from_list(model_card_proposals, proposal_id)
        match_id = str(proposal_id or resolved_id or "").strip()
        if not proposal or not match_id:
          return _reply(
            assistant_message="We need a pending proposal to confirm before we continue.",
            turn_outcome="ERROR_NO_PROPOSAL",
            next_focus=active_focus_norm,
            status_code=409,
          )
        if not proposal_hash or not validate_proposal_hash(proposal, proposal_hash):
          return _reply(
            assistant_message="That proposal changed since you last saw it. Please refresh and confirm again.",
            turn_outcome="ERROR_PROPOSAL_HASH",
            next_focus=active_focus_norm,
            status_code=409,
          )
        patch = build_patch_from_proposal(proposal)
        if patch:
          pending_patch = _remove_pending_patch_keys(pending_patch, patch)
          pending_patch_dirty = True
        if patch:
          with timed_span("unified_intake.apply_chat_patch_and_persist", draft_id=str(draft_id).strip(), focus=active_focus_norm):
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
          business_facts = updated.get("business_facts") if isinstance(updated.get("business_facts"), dict) else business_facts
          ops_json = updated.get("ops_json") if isinstance(updated.get("ops_json"), dict) else ops_json
          market_json = updated.get("market_json") if isinstance(updated.get("market_json"), dict) else market_json
          people_json = updated.get("people_json") if isinstance(updated.get("people_json"), dict) else people_json
          financials_json = updated.get("financials_json") if isinstance(updated.get("financials_json"), dict) else financials_json
          marketing_model_json = updated.get("marketing_model_json") if isinstance(updated.get("marketing_model_json"), dict) else marketing_model_json
          pricing_model_json = updated.get("pricing_model_json") if isinstance(updated.get("pricing_model_json"), dict) else pricing_model_json
          revenue_model_json = updated.get("revenue_model_json") if isinstance(updated.get("revenue_model_json"), dict) else revenue_model_json
          headcount_model_json = updated.get("headcount_model_json") if isinstance(updated.get("headcount_model_json"), dict) else headcount_model_json
          fulfillment_model_json = updated.get("fulfillment_model_json") if isinstance(updated.get("fulfillment_model_json"), dict) else fulfillment_model_json
          ops_concept_model_json = updated.get("ops_concept_model_json") if isinstance(updated.get("ops_concept_model_json"), dict) else ops_concept_model_json
          milestones_model_json = updated.get("milestones_model_json") if isinstance(updated.get("milestones_model_json"), dict) else milestones_model_json
          cogs_model_json = updated.get("cogs_model_json") if isinstance(updated.get("cogs_model_json"), dict) else cogs_model_json
          gna_model_json = updated.get("gna_model_json") if isinstance(updated.get("gna_model_json"), dict) else gna_model_json
        _record_proposal_event(
          {
            "action": "proposal_committed",
            "proposal_id": match_id,
            "model": proposal.get("model"),
            "source": proposal.get("source"),
            "proposal_hash": proposal.get("proposal_hash"),
            "payload": proposal_payload(proposal),
          }
        )
        model_card_proposals = [
          p for p in model_card_proposals if not (isinstance(p, dict) and str(p.get("id") or "") == match_id)
        ]
        if not model_card_proposals and patch:
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
            model_card_proposals = dependent
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
            proposal_notice = "Before we move on, please confirm the updated assumptions shown."
        proposals_dirty = True
        interaction_mode_override = "chat" if not model_card_proposals else "button_only"
        commit_echo = _format_commit_echo(proposal)
        proposal_model = str(proposal.get("model") or "").strip().lower()
        if proposal_model in ("ops", "market", "people", "financials"):
          snapshot_after = _build_snapshot(
            confirmations=confirmations,
            business_facts=business_facts,
            ops_json=ops_json,
            market_json=market_json,
            people_json=people_json,
            financials_json=financials_json,
            marketing_model_json=marketing_model_json,
            pricing_model_json=pricing_model_json,
            revenue_model_json=revenue_model_json,
            ops_concept_model_json=ops_concept_model_json,
            fulfillment_model_json=fulfillment_model_json,
            headcount_model_json=headcount_model_json,
            milestones_model_json=milestones_model_json,
            cogs_model_json=cogs_model_json,
            gna_model_json=gna_model_json,
          )
          section_for_accept = get_section(proposal_model)
          if section_for_accept.is_complete(snapshot_after):
            confirmations_next = dict(confirmations)
            confirmations_next[proposal_model] = True
            snapshot_next = dict(snapshot_after)
            snapshot_next["confirmations"] = confirmations_next
            next_focus_override = expected_focus_from_snapshot(snapshot_next)
            confirmations_override = confirmations_next
            advance_focus = proposal_model == active_focus_norm
            if next_focus_override == "done":
              status_override = "completed"
              completed_override = True
              consistency_override = True
      elif response_intent == "reject":
        if model_card_proposals:
          proposals_dirty = True
          for p in model_card_proposals:
            if isinstance(p, dict):
              _record_proposal_event(
                {
                  "action": "proposal_rejected",
                  "proposal_id": p.get("id"),
                  "model": p.get("model"),
                  "source": p.get("source"),
                  "payload": proposal_payload(p),
                }
              )
          model_card_proposals = []
        if pending_patch:
          pending_patch = {}
          pending_patch_dirty = True
        interaction_mode_override = "chat"
      elif response_intent == "edit":
        interaction_mode_override = "chat"
      debug_log("response_intent", focus=active_focus_norm, intent=response_intent)
    else:
      recent_messages = _clip_recent_messages_for_router(messages)
      if model_card_proposals and not message:
        proposal_notice = "Before we move on, please confirm the assumptions shown."
      else:
        try:
          with timed_span(
            "unified_intake.route_intent",
            draft_id=str(draft_id).strip(),
            focus=active_focus_norm,
            router_focus=active_focus_for_router,
            recent_messages=len(recent_messages or []),
          ):
            intent = route_intent(
              consult_type="unified",
              user_message=message,
              baseline_json=baseline_json,
              shared_context=shared_context,
              recent_messages=recent_messages,
              confirm_question_override="",
              active_focus=active_focus_for_router,
            )
        except Exception as exc:
          app.logger.exception("Intent router failed: %s", exc)
          return _reply(assistant_message="", turn_outcome="ERROR_INTENT_ROUTER_FAILED", next_focus=active_focus_norm, status_code=500)

        patch = intent.get("patch") if isinstance(intent, dict) else None
        if patch is not None and not isinstance(patch, dict):
          patch = None
        debug_log(
          "intent_patch",
          focus=active_focus_norm,
          has_patch=bool(patch),
          patch_keys=sorted(patch.keys()) if isinstance(patch, dict) else [],
        )
        if isinstance(patch, dict) and patch:
          pending_patch = _merge_pending_patch(pending_patch, patch)
          pending_patch_dirty = True
          try:
            draft_preview = apply_chat_patch(
              patch=pending_patch,
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
          except Exception:
            draft_preview = None
          if isinstance(draft_preview, dict):
            draft_business_facts = (
              draft_preview.get("business_facts") if isinstance(draft_preview.get("business_facts"), dict) else draft_business_facts
            )
            draft_ops_json = draft_preview.get("ops_json") if isinstance(draft_preview.get("ops_json"), dict) else draft_ops_json
            draft_market_json = draft_preview.get("market_json") if isinstance(draft_preview.get("market_json"), dict) else draft_market_json
            draft_people_json = draft_preview.get("people_json") if isinstance(draft_preview.get("people_json"), dict) else draft_people_json
            draft_financials_json = (
              draft_preview.get("financials_json")
              if isinstance(draft_preview.get("financials_json"), dict)
              else draft_financials_json
            )
            draft_marketing_model_json = (
              draft_preview.get("marketing_model_json")
              if isinstance(draft_preview.get("marketing_model_json"), dict)
              else draft_marketing_model_json
            )
            draft_pricing_model_json = (
              draft_preview.get("pricing_model_json")
              if isinstance(draft_preview.get("pricing_model_json"), dict)
              else draft_pricing_model_json
            )
            draft_revenue_model_json = (
              draft_preview.get("revenue_model_json")
              if isinstance(draft_preview.get("revenue_model_json"), dict)
              else draft_revenue_model_json
            )
            draft_ops_concept_model_json = (
              draft_preview.get("ops_concept_model_json")
              if isinstance(draft_preview.get("ops_concept_model_json"), dict)
              else draft_ops_concept_model_json
            )
            draft_fulfillment_model_json = (
              draft_preview.get("fulfillment_model_json")
              if isinstance(draft_preview.get("fulfillment_model_json"), dict)
              else draft_fulfillment_model_json
            )
            draft_headcount_model_json = (
              draft_preview.get("headcount_model_json")
              if isinstance(draft_preview.get("headcount_model_json"), dict)
              else draft_headcount_model_json
            )
            draft_milestones_model_json = (
              draft_preview.get("milestones_model_json")
              if isinstance(draft_preview.get("milestones_model_json"), dict)
              else draft_milestones_model_json
            )
            draft_cogs_model_json = (
              draft_preview.get("cogs_model_json")
              if isinstance(draft_preview.get("cogs_model_json"), dict)
              else draft_cogs_model_json
            )
            draft_gna_model_json = (
              draft_preview.get("gna_model_json") if isinstance(draft_preview.get("gna_model_json"), dict) else draft_gna_model_json
            )
          baseline_json = {
            "active_focus": active_focus_for_router,
            "business": draft_business_facts,
            "ops": draft_ops_json,
            "market": draft_market_json,
            "people": draft_people_json,
            "financials": draft_financials_json,
            "pricing": draft_pricing_model_json,
            "revenue": draft_revenue_model_json,
            "marketing": draft_marketing_model_json,
            "headcount": draft_headcount_model_json,
            "fulfillment": draft_fulfillment_model_json,
            "ops_concept": draft_ops_concept_model_json,
            "milestones": draft_milestones_model_json,
            "cogs": draft_cogs_model_json,
            "gna": draft_gna_model_json,
          }
          snapshot = _build_snapshot(
            confirmations=confirmations,
            business_facts=draft_business_facts,
            ops_json=draft_ops_json,
            market_json=draft_market_json,
            people_json=draft_people_json,
            financials_json=draft_financials_json,
            marketing_model_json=draft_marketing_model_json,
            pricing_model_json=draft_pricing_model_json,
            revenue_model_json=draft_revenue_model_json,
            ops_concept_model_json=draft_ops_concept_model_json,
            fulfillment_model_json=draft_fulfillment_model_json,
            headcount_model_json=draft_headcount_model_json,
            milestones_model_json=draft_milestones_model_json,
            cogs_model_json=draft_cogs_model_json,
            gna_model_json=draft_gna_model_json,
          )
          intake_context = {
            **intake_context,
            "business_name": draft_business_facts.get("name"),
            "business_start_date": draft_business_facts.get("start_date"),
            "address": draft_business_facts.get("address"),
            "consumer_type": str((draft_ops_json or {}).get("consumer_type") or "consumer"),
            "operating_model_json": draft_ops_json,
            "fulfillment_model_json": draft_fulfillment_model_json,
            "ops_concept_model_json": draft_ops_concept_model_json,
            "target_market_json": draft_market_json,
            "people_json": draft_people_json,
            "financials_json": draft_financials_json,
          }
        elif model_card_proposals:
          proposal_notice = "Before we move on, please confirm the assumptions shown."

    snapshot = _build_snapshot(
      confirmations=confirmations,
      business_facts=business_facts,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      marketing_model_json=marketing_model_json,
      pricing_model_json=pricing_model_json,
      revenue_model_json=revenue_model_json,
      ops_concept_model_json=ops_concept_model_json,
      fulfillment_model_json=fulfillment_model_json,
      headcount_model_json=headcount_model_json,
      milestones_model_json=milestones_model_json,
      cogs_model_json=cogs_model_json,
      gna_model_json=gna_model_json,
    )

    user_msg = {"role": "user", "content": message}
    if advance_focus:
      assistant_text = commit_echo or ""
      if proposal_notice:
        assistant_text = "\n\n".join([t for t in (assistant_text, proposal_notice) if str(t or "").strip()]).strip()
      with timed_span("unified_intake.append_messages", draft_id=str(draft_id).strip(), focus=active_focus_norm, note="section_confirmed"):
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          model_card_proposals=(model_card_proposals if proposals_dirty else None),
          draft_patch=(pending_patch if pending_patch_dirty else None),
          interaction_mode=interaction_mode_override,
          active_focus=("done" if next_focus_override == "done" else next_focus_override),
          confirmations=confirmations_override,
          business_facts=business_facts,
          proposal_events=(proposal_events_raw if proposal_events_dirty else None),
          proposal_revision_nonce=(proposal_nonce if proposal_events_dirty else None),
          status=status_override,
          completed=completed_override,
          consistency_passed=consistency_override,
        )
      return _reply(
        assistant_message=assistant_text,
        turn_outcome="SECTION_COMPLETE",
        next_focus=(None if next_focus_override == "done" else next_focus_override),
        status_code=200,
      )
    try:
      with timed_span("unified_intake.section.chat_turn", draft_id=str(draft_id).strip(), focus=active_focus_norm, starting=False):
        turn = section.chat_turn(
          intake_context=intake_context,
          conversation_messages=[*messages, user_msg],
          snapshot=snapshot,
          starting=False,
        )
    except ProposalRequiredError as exc:
      app.logger.error("Proposal required failure (starting=%s, focus=%s, route=%s)", False, active_focus_norm, getattr(exc, "route", ""))
      debug_log("proposal_required_error", focus=active_focus_norm, route=getattr(exc, "route", ""))
      return _proposal_error()
    except Exception as exc:
      app.logger.exception("Consultant failed: %s", exc)
      return _reply(assistant_message="", turn_outcome="ERROR_CONSULTANT_FAILED", next_focus=active_focus_norm, status_code=500)

    assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
    turn_outcome = str(turn.get("turn_outcome") or "ASK_NEXT").strip().upper() or "ASK_NEXT"
    if commit_echo:
      assistant_text = "\n\n".join([t for t in (commit_echo, assistant_text) if str(t or "").strip()]).strip()
    if proposal_notice:
      assistant_text = "\n\n".join([t for t in (assistant_text, proposal_notice) if str(t or "").strip()]).strip()
    proposal_patch = turn.get("_proposal_patch") if isinstance(turn, dict) else None
    if isinstance(proposal_patch, dict) and proposal_patch:
      pending_patch = _merge_pending_patch(pending_patch, proposal_patch)
      pending_patch_dirty = True
      try:
        draft_preview = apply_chat_patch(
          patch=pending_patch,
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
      except Exception:
        draft_preview = None
      if isinstance(draft_preview, dict):
        draft_business_facts = (
          draft_preview.get("business_facts") if isinstance(draft_preview.get("business_facts"), dict) else draft_business_facts
        )
        draft_ops_json = draft_preview.get("ops_json") if isinstance(draft_preview.get("ops_json"), dict) else draft_ops_json
        draft_market_json = (
          draft_preview.get("market_json") if isinstance(draft_preview.get("market_json"), dict) else draft_market_json
        )
        draft_people_json = (
          draft_preview.get("people_json") if isinstance(draft_preview.get("people_json"), dict) else draft_people_json
        )
        draft_financials_json = (
          draft_preview.get("financials_json") if isinstance(draft_preview.get("financials_json"), dict) else draft_financials_json
        )
        draft_marketing_model_json = (
          draft_preview.get("marketing_model_json")
          if isinstance(draft_preview.get("marketing_model_json"), dict)
          else draft_marketing_model_json
        )
        draft_pricing_model_json = (
          draft_preview.get("pricing_model_json")
          if isinstance(draft_preview.get("pricing_model_json"), dict)
          else draft_pricing_model_json
        )
        draft_revenue_model_json = (
          draft_preview.get("revenue_model_json")
          if isinstance(draft_preview.get("revenue_model_json"), dict)
          else draft_revenue_model_json
        )
        draft_ops_concept_model_json = (
          draft_preview.get("ops_concept_model_json")
          if isinstance(draft_preview.get("ops_concept_model_json"), dict)
          else draft_ops_concept_model_json
        )
        draft_fulfillment_model_json = (
          draft_preview.get("fulfillment_model_json")
          if isinstance(draft_preview.get("fulfillment_model_json"), dict)
          else draft_fulfillment_model_json
        )
        draft_headcount_model_json = (
          draft_preview.get("headcount_model_json")
          if isinstance(draft_preview.get("headcount_model_json"), dict)
          else draft_headcount_model_json
        )
        draft_milestones_model_json = (
          draft_preview.get("milestones_model_json")
          if isinstance(draft_preview.get("milestones_model_json"), dict)
          else draft_milestones_model_json
        )
        draft_cogs_model_json = (
          draft_preview.get("cogs_model_json") if isinstance(draft_preview.get("cogs_model_json"), dict) else draft_cogs_model_json
        )
        draft_gna_model_json = (
          draft_preview.get("gna_model_json") if isinstance(draft_preview.get("gna_model_json"), dict) else draft_gna_model_json
        )
        snapshot = _build_snapshot(
          confirmations=confirmations,
          business_facts=draft_business_facts,
          ops_json=draft_ops_json,
          market_json=draft_market_json,
          people_json=draft_people_json,
          financials_json=draft_financials_json,
          marketing_model_json=draft_marketing_model_json,
          pricing_model_json=draft_pricing_model_json,
          revenue_model_json=draft_revenue_model_json,
          ops_concept_model_json=draft_ops_concept_model_json,
          fulfillment_model_json=draft_fulfillment_model_json,
          headcount_model_json=draft_headcount_model_json,
          milestones_model_json=draft_milestones_model_json,
          cogs_model_json=draft_cogs_model_json,
          gna_model_json=draft_gna_model_json,
        )
        intake_context = {
          **intake_context,
          "business_name": draft_business_facts.get("name"),
          "business_start_date": draft_business_facts.get("start_date"),
          "address": draft_business_facts.get("address"),
          "consumer_type": str((draft_ops_json or {}).get("consumer_type") or "consumer"),
          "operating_model_json": draft_ops_json,
          "fulfillment_model_json": draft_fulfillment_model_json,
          "ops_concept_model_json": draft_ops_concept_model_json,
          "target_market_json": draft_market_json,
          "people_json": draft_people_json,
          "financials_json": draft_financials_json,
        }
      if not model_card_proposals:
        proposals = build_proposals_from_patch(
          patch=proposal_patch,
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
          source="section_patch",
        )
        if proposals:
          model_card_proposals = proposals
          proposals_dirty = True
          interaction_mode_override = "button_only"
          proposal_notice = "Before we move on, please confirm the assumptions shown."
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
    if turn_outcome != "SECTION_COMPLETE" and section.is_complete(snapshot):
      turn_outcome = "SECTION_COMPLETE"
    debug_log(
      "section_turn",
      focus=active_focus_norm,
      outcome=turn_outcome,
      assistant_len=len(assistant_text),
      starting=False,
    )

    if turn_outcome != "SECTION_COMPLETE":
      with timed_span(
        "unified_intake.append_messages",
        draft_id=str(draft_id).strip(),
        focus=active_focus_norm,
        starting=False,
      ):
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          active_focus=active_focus_norm,
          model_card_proposals=(model_card_proposals if proposals_dirty else None),
          draft_patch=(pending_patch if pending_patch_dirty else None),
          interaction_mode=interaction_mode_override,
          business_facts=business_facts,
          proposal_events=(proposal_events_raw if proposal_events_dirty else None),
          proposal_revision_nonce=(proposal_nonce if proposal_events_dirty else None),
        )
      return _reply(assistant_message=assistant_text, turn_outcome=turn_outcome, next_focus=active_focus_norm, status_code=200)

    # SECTION_COMPLETE: generate a proposal from the final structured output (no implicit commits).
    try:
      with timed_span("unified_intake.section.finalize", draft_id=str(draft_id).strip(), focus=active_focus_norm):
        final_obj = section.finalize(
          intake_context=intake_context,
          conversation_messages=[*messages, user_msg],
          snapshot=snapshot,
          conn=conn,
        )
    except Exception as exc:
      app.logger.exception("Finalizer failed: %s", exc)
      with timed_span("unified_intake.append_messages", draft_id=str(draft_id).strip(), focus=active_focus_norm, note="finalizer_failed"):
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          active_focus=active_focus_norm,
          draft_patch=(pending_patch if pending_patch_dirty else None),
          interaction_mode=interaction_mode_override,
          business_facts=business_facts,
          proposal_events=(proposal_events_raw if proposal_events_dirty else None),
          proposal_revision_nonce=(proposal_nonce if proposal_events_dirty else None),
        )
      return _reply(assistant_message=assistant_text, turn_outcome="ERROR_FINALIZER_FAILED", next_focus=active_focus_norm, status_code=500)

    final_patch: Dict[str, Any] = {}
    allowed_groups_by_section: Dict[str, Tuple[str, ...]] = {
      "ops": (
        "business",
        "ops",
        "pricing",
        "revenue",
        "fulfillment",
        "ops_concept",
        "milestones",
        "cogs",
        "gna",
      ),
      "market": ("business", "market", "marketing", "pricing"),
      "people": ("business", "people", "headcount"),
      "financials": ("business", "financials"),
    }
    allowed_groups = allowed_groups_by_section.get(active_focus_norm, (active_focus_norm,))

    if pending_patch:
      for raw_key, value in pending_patch.items():
        key = str(raw_key or "").strip()
        if key.count(".") != 1:
          continue
        group, _ = key.split(".", 1)
        if group.strip().lower() in allowed_groups:
          final_patch[key] = value

    if isinstance(final_obj, dict):
      for key, value in final_obj.items():
        if key in ("assistant_message", "turn_outcome"):
          continue
        final_patch[f"{active_focus_norm}.{key}"] = value

    if not final_patch:
      debug_log("section_final_patch_missing", focus=active_focus_norm)
      return _proposal_error()

    proposals = build_proposals_from_patch(
      patch=final_patch,
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
      source="section_final",
    )
    if not proposals:
      debug_log("section_final_proposals_missing", focus=active_focus_norm)
      return _proposal_error()

    model_card_proposals = proposals
    proposals_dirty = True
    interaction_mode_override = "button_only"
    assistant_text = "\n\n".join(
      [t for t in (assistant_text, "Before we move on, please confirm the assumptions shown.") if str(t or "").strip()]
    ).strip()
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

    with timed_span("unified_intake.append_messages", draft_id=str(draft_id).strip(), focus=active_focus_norm, note="section_complete_proposal"):
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        model_card_proposals=(model_card_proposals if proposals_dirty else None),
        draft_patch=(pending_patch if pending_patch_dirty else None),
        interaction_mode=interaction_mode_override,
        active_focus=active_focus_norm,
        business_facts=business_facts,
        proposal_events=(proposal_events_raw if proposal_events_dirty else None),
        proposal_revision_nonce=(proposal_nonce if proposal_events_dirty else None),
      )

    return _reply(
      assistant_message=assistant_text,
      turn_outcome="ASK_NEXT",
      next_focus=active_focus_norm,
      status_code=200,
    )
  except Exception as exc:
    app.logger.exception("Failed intake consult: %s", exc)
    return _reply(assistant_message="", turn_outcome="ERROR_SERVER", next_focus=None, status_code=500)
  finally:
    try:
      conn.close()
    except Exception:
      pass
