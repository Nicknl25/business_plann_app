import json
from typing import Any, Dict, List

from flask import jsonify


def post_people_capability_session_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:post_people_capability_session (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore
    from people_capability_draft import create_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import people draft helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
    client_id = str(consult.get("client_id") or "").strip()
    if not client_id:
      raise RuntimeError("Consult draft missing client_id.")
    create_draft(conn, draft_id=str(draft_id).strip(), client_id=client_id)
    return jsonify({"status": "ok", "draft_id": str(draft_id).strip(), "client_id": client_id})
  finally:
    try:
      conn.close()
    except Exception:
      pass


def get_people_capability_draft_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:get_people_capability_draft (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  draft_id = request.args.get("draft_id")
  if not draft_id:
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from people_capability_draft import get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import people draft helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
      return jsonify(
        {
          "status": "ok",
          "draft_id": draft.get("draft_id"),
          "client_id": draft.get("client_id"),
          "draft_status": draft.get("status"),
          "messages_json": draft.get("messages_json"),
          "people_json": draft.get("people_json"),
        }
      )
    except Exception as exc:
      return (
        jsonify({"error": "not_found", "detail": str(exc)}),
        404,
      )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def post_people_capability_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:post_people_capability (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  message = payload.get("message")
  business_name = payload.get("business_name")
  business_type = payload.get("business_type")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  starting = message is None or not str(message).strip()
  if starting:
    message = "Start the People & Capability intake. Ask your first question."

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore
    from people_capability_draft import append_messages, create_draft, get_draft as get_pc_draft  # type: ignore
    from people_capability_consultant import (  # type: ignore
      people_capability_chat_turn,
      people_capability_finalize,
    )
  except Exception as exc:
    app.logger.exception("Failed to import people consult helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  def _validate_final(final_obj: Dict[str, Any]) -> None:
    if not isinstance(final_obj, dict):
      raise RuntimeError("Final people JSON must be an object.")
    summary = str(final_obj.get("key_people_summary") or "").strip()
    if not summary:
      raise RuntimeError("Final people JSON missing key_people_summary.")
    conf = final_obj.get("confidence")
    try:
      conf_val = float(conf)
    except Exception as exc:
      raise RuntimeError("Final people JSON missing valid confidence.") from exc
    if conf_val <= 0 or conf_val > 1:
      raise RuntimeError("confidence must be between 0 and 1.")
    people = final_obj.get("people")
    if not isinstance(people, list):
      raise RuntimeError("Final people JSON missing people array.")
    if len(people) == 0:
      raise RuntimeError("At least one person is required in this section.")
    for p in people:
      if not isinstance(p, dict):
        raise RuntimeError("people items must be objects.")
      if not str(p.get("full_name") or "").strip():
        raise RuntimeError("people.full_name is required.")
      if not str(p.get("role_title") or "").strip():
        raise RuntimeError("people.role_title is required.")
      if not str(p.get("paragraph") or "").strip():
        raise RuntimeError("people.paragraph is required.")

  try:
    conn = get_mysql_connection()
    try:
      consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
      client_id = str(consult.get("client_id") or "").strip()
      operating_raw = consult.get("operating_model_json")
      operating_model: Dict[str, Any] = {}
      if operating_raw:
        try:
          parsed = json.loads(str(operating_raw))
          if isinstance(parsed, dict):
            operating_model = parsed
        except Exception:
          operating_model = {}

      # Ensure the people draft row exists.
      try:
        pc_draft = get_pc_draft(conn, draft_id=str(draft_id).strip())
      except Exception:
        create_draft(conn, draft_id=str(draft_id).strip(), client_id=client_id)
        pc_draft = get_pc_draft(conn, draft_id=str(draft_id).strip())

      pc_status = str(pc_draft.get("status") or "").strip().lower()
      if pc_status == "completed":
        pc_raw = pc_draft.get("people_json")
        pc_summary = ""
        if pc_raw:
          try:
            pc_obj = json.loads(str(pc_raw))
            if isinstance(pc_obj, dict):
              pc_summary = str(pc_obj.get("key_people_summary") or "").strip()
          except Exception:
            pc_summary = ""
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "done": True,
            "assistant_message": pc_summary or "People & capability intake complete.",
          }
        )

      history: List[Dict[str, str]] = []
      try:
        raw_messages = pc_draft.get("messages_json")
        if raw_messages:
          parsed = json.loads(str(raw_messages))
          if isinstance(parsed, list):
            history = [m for m in parsed if isinstance(m, dict)]
      except Exception:
        history = []

      context = {
        "client_id": client_id,
        "business_name": (str(business_name).strip() if business_name else None),
        "business_type": (str(business_type).strip() if business_type else None),
        "business_description_summary": operating_model.get("business_description_summary"),
        "unit_name": operating_model.get("unit_name"),
        "unit_price": operating_model.get("unit_price"),
        "shipping_method": operating_model.get("shipping_method"),
      }

      user_msg = {"role": "user", "content": str(message).strip()}
      turn = people_capability_chat_turn(
        intake_context=context,
        conversation_messages=[*history, user_msg],
      )
      assistant_text = str(turn.get("assistant_message") or "").strip()
      finalize_ready = bool(turn.get("finalize_ready", False))
      assistant_msg = {"role": "assistant", "content": assistant_text}
      new_messages = [user_msg, assistant_msg]

      done = False
      assistant_message = assistant_text

      if finalize_ready:
        final_obj = people_capability_finalize(
          intake_context=context,
          conversation_messages=[*history, *new_messages],
        )
        _validate_final(final_obj)
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="completed",
          people_json=final_obj,
          completed=True,
        )
        done = True
        assistant_message = str(final_obj.get("key_people_summary") or "").strip() or "People & capability intake complete."
      else:
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="in_progress",
        )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "done": done,
          "assistant_message": assistant_message,
        }
      )
    finally:
      try:
        conn.close()
      except Exception:
        pass
  except Exception as exc:
    app.logger.exception("Failed people capability consult: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)

