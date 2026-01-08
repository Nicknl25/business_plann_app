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
  apply_chat_patch_and_persist,
  seed_lobs_if_needed,
  sync_pricing_from_ops_if_needed,
)
from unified_intake.sections import expected_focus_from_snapshot, get_section  # type: ignore


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


def _proposal_patch_from_list(proposals: List[Any]) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
  for item in reversed(list(proposals or [])):
    if not isinstance(item, dict):
      continue
    if item.get("pending") is False:
      continue
    patch = item.get("patch")
    if isinstance(patch, dict) and patch:
      pid = str(item.get("id") or "").strip() or None
      return patch, pid
  return None, None


def _build_model_proposal(*, model: str, patch: Dict[str, Any]) -> Dict[str, Any]:
  now_ms = int(time.time() * 1000)
  model_norm = str(model or "").strip().lower() or "unknown"
  return {
    "id": f"{model_norm}_{now_ms}",
    "model": model_norm,
    "patch": dict(patch),
    "pending": True,
    "created_at_ms": now_ms,
  }


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
  starting = raw_message is None or not message

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

    model_card_proposals = _parse_json_list(consult.get("model_card_proposals_json"))
    proposals_dirty = False

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

    # Build baseline for intent routing (internal only).
    baseline_json = {
      "active_focus": active_focus_for_router,
      "business": business_facts,
      "ops": ops_json,
      "market": market_json,
      "people": people_json,
      "financials": financials_json,
      "pricing": pricing_model_json,
      "revenue": revenue_model_json,
      "marketing": marketing_model_json,
      "headcount": headcount_model_json,
      "fulfillment": fulfillment_model_json,
      "ops_concept": ops_concept_model_json,
      "milestones": milestones_model_json,
      "cogs": cogs_model_json,
      "gna": gna_model_json,
    }

    intake_context: Dict[str, Any] = {
      "client_id": client_id,
      "draft_id": str(draft_id).strip(),
      "today_iso": date.today().isoformat(),
      "business_name": business_facts.get("name"),
      "business_start_date": business_facts.get("start_date"),
      "address": business_facts.get("address"),
      "consumer_type": str((ops_json or {}).get("consumer_type") or "consumer"),
      "naics_6": None,
      "shared_context": shared_context,
      "operating_model_json": ops_json,
      "fulfillment_model_json": fulfillment_model_json,
      "ops_concept_model_json": ops_concept_model_json,
      "target_market_json": market_json,
      "people_json": people_json,
      "financials_json": financials_json,
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
      except Exception as exc:
        app.logger.exception("Consultant failed: %s", exc)
        return _reply(assistant_message="", turn_outcome="ERROR_CONSULTANT_FAILED", next_focus=active_focus_norm, status_code=500)

      assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
      turn_outcome = str(turn.get("turn_outcome") or "ASK_NEXT").strip().upper() or "ASK_NEXT"
      proposal_patch = turn.get("_proposal_patch") if isinstance(turn, dict) else None
      proposal_model = str((turn or {}).get("_proposal_model") or "").strip().lower() if isinstance(turn, dict) else ""
      if isinstance(proposal_patch, dict) and proposal_patch:
        model_card_proposals = [_build_model_proposal(model=proposal_model, patch=proposal_patch)]
        proposals_dirty = True
        debug_log(
          "proposal_stored",
          focus=active_focus_norm,
          model=proposal_model,
          patch_keys=sorted(proposal_patch.keys()),
        )
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
          business_facts=business_facts,
        )
      return _reply(assistant_message=assistant_text, turn_outcome=turn_outcome, next_focus=active_focus_norm, status_code=200)

    # Non-starting: infer patch and persist immediately before consultant runs.
    recent_messages = _clip_recent_messages_for_router(messages)
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
    if (not patch) and _is_affirmative(message):
      auto_patch, proposal_id = _proposal_patch_from_list(model_card_proposals)
      if isinstance(auto_patch, dict) and auto_patch:
        patch = auto_patch
        proposals_dirty = True
        if proposal_id:
          model_card_proposals = [
            p for p in model_card_proposals if not (isinstance(p, dict) and str(p.get("id") or "") == proposal_id)
          ]
        debug_log(
          "auto_patch",
          focus=active_focus_norm,
          patch_keys=sorted(patch.keys()) if isinstance(patch, dict) else [],
        )
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
    try:
      with timed_span("unified_intake.section.chat_turn", draft_id=str(draft_id).strip(), focus=active_focus_norm, starting=False):
        turn = section.chat_turn(
          intake_context=intake_context,
          conversation_messages=[*messages, user_msg],
          snapshot=snapshot,
          starting=False,
        )
    except Exception as exc:
      app.logger.exception("Consultant failed: %s", exc)
      return _reply(assistant_message="", turn_outcome="ERROR_CONSULTANT_FAILED", next_focus=active_focus_norm, status_code=500)

    assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
    turn_outcome = str(turn.get("turn_outcome") or "ASK_NEXT").strip().upper() or "ASK_NEXT"
    proposal_patch = turn.get("_proposal_patch") if isinstance(turn, dict) else None
    proposal_model = str((turn or {}).get("_proposal_model") or "").strip().lower() if isinstance(turn, dict) else ""
    if isinstance(proposal_patch, dict) and proposal_patch:
      model_card_proposals = [_build_model_proposal(model=proposal_model, patch=proposal_patch)]
      proposals_dirty = True
      debug_log(
        "proposal_stored",
        focus=active_focus_norm,
        model=proposal_model,
        patch_keys=sorted(proposal_patch.keys()),
      )
    debug_log(
      "section_turn",
      focus=active_focus_norm,
      outcome=turn_outcome,
      assistant_len=len(assistant_text),
      starting=False,
    )

    if turn_outcome != "SECTION_COMPLETE":
      with timed_span("unified_intake.append_messages", draft_id=str(draft_id).strip(), focus=active_focus_norm, starting=False):
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          active_focus=active_focus_norm,
          model_card_proposals=(model_card_proposals if proposals_dirty else None),
          business_facts=business_facts,
        )
      return _reply(assistant_message=assistant_text, turn_outcome=turn_outcome, next_focus=active_focus_norm, status_code=200)

    # SECTION_COMPLETE: persist structured JSON, then advance focus (no same-turn next-section prompt).
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
          business_facts=business_facts,
        )
      return _reply(assistant_message=assistant_text, turn_outcome="ERROR_FINALIZER_FAILED", next_focus=active_focus_norm, status_code=500)

    if active_focus_norm == "ops":
      ops_json = _merge_finalized_section(ops_json, final_obj)
    elif active_focus_norm == "market":
      market_json = _merge_finalized_section(market_json, final_obj)
    elif active_focus_norm == "people":
      people_json = _merge_finalized_section(people_json, final_obj)
    elif active_focus_norm == "financials":
      financials_json = _merge_finalized_section(financials_json, final_obj)

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

    section_complete = section.is_complete(snapshot)
    debug_log("section_finalize", focus=active_focus_norm, complete=section_complete)
    if not section_complete:
      # Safety recovery: if a consultant signals completion but the section is still incomplete,
      # keep the user moving (no 409s, no retyping, no dead ends).
      debug_log("completion_recovery", focus=active_focus_norm)
      try:
        followup = section.chat_turn(
          intake_context=intake_context,
          conversation_messages=[*messages, user_msg],
          snapshot=snapshot,
          starting=False,
        )
      except Exception:
        followup = {}
      followup_text = sanitize_fact_template(str((followup or {}).get("assistant_message") or "").strip())
      with timed_span("unified_intake.append_messages", draft_id=str(draft_id).strip(), focus=active_focus_norm, note="completion_recovery"):
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": (followup_text or assistant_text)}],
          operating_model_json=ops_json if active_focus_norm == "ops" else None,
          target_market_json=market_json if active_focus_norm == "market" else None,
          people_json=people_json if active_focus_norm == "people" else None,
          financials_json=financials_json if active_focus_norm == "financials" else None,
          model_card_proposals=(model_card_proposals if proposals_dirty else None),
          active_focus=active_focus_norm,
          business_facts=business_facts,
        )
      return _reply(
        assistant_message=(followup_text or assistant_text),
        turn_outcome="ASK_NEXT",
        next_focus=active_focus_norm,
        status_code=200,
      )

    confirmations_next = dict(confirmations)
    confirmations_next[active_focus_norm] = True
    snapshot_for_next = dict(snapshot)
    snapshot_for_next["confirmations"] = confirmations_next
    next_focus = expected_focus_from_snapshot(snapshot_for_next)
    status_out: Optional[str] = None
    completed_out = False
    consistency_passed_out = False
    if next_focus == "done":
      status_out = "completed"
      completed_out = True
      consistency_passed_out = True

    with timed_span("unified_intake.append_messages", draft_id=str(draft_id).strip(), focus=active_focus_norm, note="section_complete"):
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json if active_focus_norm == "ops" else None,
        target_market_json=market_json if active_focus_norm == "market" else None,
        people_json=people_json if active_focus_norm == "people" else None,
        financials_json=financials_json if active_focus_norm == "financials" else None,
        model_card_proposals=(model_card_proposals if proposals_dirty else None),
        confirmations={active_focus_norm: True},
        active_focus=("done" if next_focus == "done" else next_focus),
        business_facts=business_facts,
        status=status_out,
        completed=completed_out,
        consistency_passed=consistency_passed_out,
      )

    debug_log("section_advanced", focus=active_focus_norm, next_focus=next_focus)
    return _reply(
      assistant_message=assistant_text,
      turn_outcome="SECTION_COMPLETE",
      next_focus=(None if next_focus == "done" else next_focus),
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
