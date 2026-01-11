from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify

from intake_consult_draft import append_messages, create_draft, get_draft, update_draft
from intake_submission import get_mysql_connection

from .system_prompt import SYSTEM_PROMPT


MODEL_COLUMNS: Tuple[str, ...] = (
  "operating_model_json",
  "operating_structure_json",
  "customer_model_json",
  "fulfillment_model_json",
  "revenue_model_json",
  "cogs_model_json",
  "gna_model_json",
  "marketing_model_json",
  "headcount_model_json",
  "people_json",
  "milestones_model_json",
  "target_market_json",
)


def _log_event(app, *, event: str, draft_id: str, **extra: Any) -> None:
  payload: Dict[str, Any] = {"event": event, "draft_id": str(draft_id).strip()}
  for key, value in extra.items():
    if value is None:
      continue
    payload[key] = value
  app.logger.info("intake_consult_event %s", json.dumps(payload, ensure_ascii=True))


def _focus_token(model_key: str) -> str:
  key = str(model_key or "").strip()
  if key.endswith("_json"):
    return key[: -len("_json")]
  return key


def _parse_json_maybe(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(str(raw))
  except Exception:
    return raw


def _parse_messages(raw: Any) -> List[Dict[str, Any]]:
  parsed = _parse_json_maybe(raw)
  if isinstance(parsed, list):
    return [m for m in parsed if isinstance(m, dict)]
  return []


def _json_safe(value: Any) -> Any:
  if isinstance(value, dict):
    return {str(k): _json_safe(v) for k, v in value.items()}
  if isinstance(value, list):
    return [_json_safe(item) for item in value]
  if isinstance(value, (datetime, date)):
    return value.isoformat()
  if isinstance(value, Decimal):
    return str(value)
  return value


def _normalize_messages_json(raw: Any) -> str:
  parsed = _parse_messages(raw)
  return json.dumps(parsed, ensure_ascii=True)


def _build_draft_state(draft: Dict[str, Any]) -> Dict[str, Any]:
  state: Dict[str, Any] = {}
  for key, value in (draft or {}).items():
    if str(key).endswith("_json"):
      state[key] = _json_safe(_parse_json_maybe(value) or {})
    else:
      state[key] = _json_safe(value)
  return state


def _is_valid_patch_message(message: str) -> bool:
  trimmed = str(message or "").strip()
  if not (trimmed.startswith("{") and trimmed.endswith("}")):
    return False
  try:
    parsed = json.loads(trimmed)
  except Exception:
    return False
  if not isinstance(parsed, dict) or len(parsed) != 1:
    return False
  key = next(iter(parsed.keys()))
  value = parsed.get(key)
  return key in MODEL_COLUMNS and isinstance(value, dict)



def _call_llm(*, messages_json: List[Dict[str, Any]], draft_state: Dict[str, Any], user_message: str) -> str:
  try:
    from openai import OpenAI  # type: ignore
  except Exception as exc:  # pragma: no cover
    raise RuntimeError("OpenAI client is not available in this environment.") from exc

  api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not api_key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")

  model = (
    (os.getenv("INTAKE_CONSULT_MODEL") or "").strip()
    or (os.getenv("OPENAI_MODEL") or "").strip()
    or "gpt-4.1-mini"
  )
  client = OpenAI(api_key=api_key)

  payload = {
    "messages_json": messages_json,
    "draft_state": draft_state,
    "user_message": user_message,
  }
  user_content = json.dumps(payload, ensure_ascii=True)

  response = client.chat.completions.create(
    model=model,
    messages=[
      {"role": "system", "content": SYSTEM_PROMPT},
      {"role": "user", "content": user_content},
    ],
  )
  content = response.choices[0].message.content if response.choices else ""
  return str(content or "")


def post_intake_consult_session_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  try:
    conn = get_mysql_connection()
  except Exception as exc:
    app.logger.exception("Failed to connect to MySQL: %s", exc)
    return jsonify({"error": "server_error"}), 500

  try:
    draft = create_draft(conn)
    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft.get("draft_id") or "").strip(),
        "client_id": str(draft.get("client_id") or "").strip(),
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
  if not draft_id or not str(draft_id).strip():
    return jsonify({"error": "invalid_request", "detail": "draft_id is required"}), 400

  try:
    conn = get_mysql_connection()
  except Exception as exc:
    app.logger.exception("Failed to connect to MySQL: %s", exc)
    return jsonify({"error": "server_error"}), 500

  try:
    draft = get_draft(conn, draft_id=str(draft_id).strip())
    if not draft:
      return jsonify({"error": "not_found", "detail": "draft_id was not found"}), 404

    messages_json = _normalize_messages_json(draft.get("messages_json"))
    draft_status = draft.get("draft_status") or draft.get("status") or ""

    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft_id).strip(),
        "draft_status": str(draft_status),
        "active_focus": str(draft.get("active_focus") or ""),
        "interaction_mode": str(draft.get("interaction_mode") or "chat"),
        "ops_confirmed": bool(draft.get("ops_confirmed")),
        "market_confirmed": bool(draft.get("market_confirmed")),
        "people_confirmed": bool(draft.get("people_confirmed")),
        "financials_confirmed": bool(draft.get("financials_confirmed")),
        "consistency_passed": bool(draft.get("consistency_passed")),
        "business_name": draft.get("business_name"),
        "business_address": draft.get("business_address") or draft.get("address"),
        "business_start_date": draft.get("business_start_date"),
        "address_street": draft.get("address_street"),
        "address_city": draft.get("address_city"),
        "address_state": draft.get("address_state"),
        "address_zip": draft.get("address_zip"),
        "address_country": draft.get("address_country"),
        "messages_json": messages_json,
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
  draft_id = str(payload.get("draft_id") or "").strip()
  if not draft_id:
    return jsonify({"error": "invalid_request", "detail": "draft_id is required"}), 400

  try:
    conn = get_mysql_connection()
  except Exception as exc:
    app.logger.exception("Failed to connect to MySQL: %s", exc)
    return jsonify({"error": "server_error"}), 500

  try:
    draft = get_draft(conn, draft_id=draft_id)
    if not draft:
      return jsonify({"error": "not_found", "detail": "draft_id was not found"}), 404

    business_updates: Dict[str, Any] = {}
    if "business_name" in payload:
      business_updates["business_name"] = str(payload.get("business_name") or "").strip() or None
    if "address" in payload:
      business_updates["business_address"] = str(payload.get("address") or "").strip() or None
    if "business_start_date" in payload:
      business_updates["business_start_date"] = str(payload.get("business_start_date") or "").strip() or None
    for key in ("address_street", "address_city", "address_state", "address_zip", "address_country"):
      if key in payload:
        business_updates[key] = str(payload.get(key) or "").strip() or None

    if business_updates:
      update_draft(conn, draft_id=draft_id, updates=business_updates)
      draft.update(business_updates)

    user_message = str(payload.get("message") or "")
    messages_json = _parse_messages(draft.get("messages_json"))
    draft_state = _build_draft_state(draft)

    _log_event(app, event="llm_call_start", draft_id=draft_id, phase="initial")
    llm_started = time.time()
    try:
      assistant_content = _call_llm(
        messages_json=messages_json,
        draft_state=draft_state,
        user_message=user_message,
      )
    finally:
      duration_ms = int((time.time() - llm_started) * 1000)
      _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="initial")

    patch_target: Optional[str] = None
    patch_payload: Optional[Dict[str, Any]] = None
    patch_key_logged: Optional[str] = None
    trimmed = assistant_content.strip()
    if trimmed.startswith("{") and trimmed.endswith("}"):
      try:
        parsed = json.loads(trimmed)
      except Exception:
        parsed = None
      if isinstance(parsed, dict):
        if len(parsed) == 1:
          key = next(iter(parsed.keys()))
          value = parsed.get(key)
          if key in MODEL_COLUMNS and isinstance(value, dict):
            patch_target = key
            patch_payload = value
            patch_key_logged = key
        _log_event(app, event="patch_received", draft_id=draft_id, target_key=patch_key_logged or "")

    if patch_target and isinstance(patch_payload, dict):
      focus_value = _focus_token(patch_target)
      update_draft(
        conn,
        draft_id=draft_id,
        updates={patch_target: patch_payload, "active_focus": focus_value},
      )
      _log_event(app, event="patch_persisted", draft_id=draft_id, target_key=patch_target)
    elif trimmed.startswith("{") and trimmed.endswith("}"):
      _log_event(app, event="patch_ignored", draft_id=draft_id, target_key=patch_key_logged or "")

    assistant_content_for_chat = assistant_content
    if patch_target:
      draft = get_draft(conn, draft_id=draft_id)
      if draft:
        draft_state = _build_draft_state(draft)
      _log_event(app, event="llm_call_start", draft_id=draft_id, phase="continuation")
      llm_started = time.time()
      try:
        assistant_content_for_chat = _call_llm(
          messages_json=messages_json,
          draft_state=draft_state,
          user_message="",
        )
      finally:
        duration_ms = int((time.time() - llm_started) * 1000)
        _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="continuation")

    new_messages: List[Dict[str, str]] = []
    if user_message.strip():
      new_messages.append({"role": "user", "content": user_message})
    if assistant_content_for_chat.strip():
      new_messages.append({"role": "assistant", "content": assistant_content_for_chat})
    if new_messages:
      append_messages(conn, draft_id=draft_id, new_messages=new_messages)

    assistant_is_patch = _is_valid_patch_message(assistant_content_for_chat)
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft_id,
        "assistant_message": assistant_content_for_chat,
        "assistant_is_patch": assistant_is_patch,
        "active_focus": _focus_token(patch_target) if patch_target else str(draft.get("active_focus") or ""),
      }
    )
  except Exception as exc:
    app.logger.exception("Failed to run consult: %s", exc)
    return jsonify({"error": "server_error", "detail": str(exc)}), 500
  finally:
    try:
      conn.close()
    except Exception:
      pass
