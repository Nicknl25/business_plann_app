import json
from typing import Any, Dict, List, Optional

from flask import jsonify


def post_intake_consult_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:post_intake_consult (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  client_id = payload.get("client_id")
  raw_message = payload.get("message")
  message = raw_message
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )
  reset = bool(payload.get("reset", False))
  starting = message is None or not str(message).strip()
  if starting:
    message = "Start the operational intake. Ask your first question."

  try:
    from intake_consultant import (  # type: ignore
      consultant_chat_turn,
      consultant_finalize,
    )
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import (  # type: ignore
      append_messages,
      get_draft,
    )
  except Exception as exc:
    app.logger.exception("Failed to import intake consultant helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  try:
    conn = get_mysql_connection()
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
    finally:
      try:
        conn.close()
      except Exception:
        pass

    client_id_str = str(draft.get("client_id") or (client_id or "")).strip()
    draft_status = str(draft.get("status") or "").strip().lower()
    if draft_status in ("completed", "submitted"):
      operating_model_raw = draft.get("operating_model_json")
      if operating_model_raw:
        summary_text = ""
        try:
          parsed = json.loads(str(operating_model_raw))
          if isinstance(parsed, dict):
            summary_text = str(parsed.get("business_description_summary") or "").strip()
        except Exception:
          summary_text = ""
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id_str,
            "done": True,
            "assistant_message": summary_text or "Operational intake complete.",
            "operating_model_json": str(operating_model_raw),
          }
        )

    context = {
      "client_id": client_id_str,
      "business_name": payload.get("business_name"),
      "business_type": payload.get("business_type"),
      "address": payload.get("address"),
      "address_street": payload.get("address_street"),
      "address_city": payload.get("address_city"),
      "address_state": payload.get("address_state"),
      "address_zip": payload.get("address_zip"),
      "address_country": payload.get("address_country"),
    }

    app.logger.info(
      "Intake consult message for draft_id=%s client_id=%s: %s",
      draft_id,
      client_id_str,
      message,
    )
    print(f"Intake consult message draft_id={draft_id} client_id={client_id_str}:", str(message))

    history: List[Dict[str, str]] = []
    try:
      raw_messages = draft.get("messages_json")
      if raw_messages:
        parsed = json.loads(str(raw_messages))
        if isinstance(parsed, list):
          history = [m for m in parsed if isinstance(m, dict)]
    except Exception:
      history = []

    if reset:
      history = []

    user_msg = {"role": "user", "content": str(message).strip()}
    turn = consultant_chat_turn(
      intake_context=context,
      conversation_messages=[*history, user_msg],
    )
    assistant_text = str(turn.get("assistant_message") or "").strip()
    finalize_ready = bool(turn.get("finalize_ready", False))
    assistant_msg = {"role": "assistant", "content": assistant_text}
    new_messages = [user_msg, assistant_msg]

    done = False
    assistant_message = assistant_text
    operating_model_json_out: Optional[str] = None

    if finalize_ready:
      final_obj = consultant_finalize(
        intake_context=context,
        conversation_messages=[*history, *new_messages],
      )
      if not isinstance(final_obj, dict):
        raise RuntimeError("Finalization did not return an object.")

      app.logger.info(
        "Intake consult final for draft_id=%s client_id=%s: %s",
        draft_id,
        client_id_str,
        final_obj,
      )
      print(f"Intake consult final draft_id={draft_id} client_id={client_id_str}:", final_obj)

      conn = get_mysql_connection()
      try:
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="completed",
          operating_model_json=final_obj,
          completed=True,
        )
      finally:
        try:
          conn.close()
        except Exception:
          pass

      done = True
      assistant_message = str(final_obj.get("business_description_summary") or "").strip() or "Operational intake complete."
      operating_model_json_out = json.dumps(final_obj, ensure_ascii=False)
    else:
      conn = get_mysql_connection()
      try:
        # Persist conversation after each turn (durable draft).
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="in_progress",
        )
      finally:
        try:
          conn.close()
        except Exception:
          pass

    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft_id).strip(),
        "client_id": client_id_str,
        "done": done,
        "assistant_message": assistant_message,
        "operating_model_json": operating_model_json_out,
      }
    )
  except Exception as exc:
    app.logger.exception("Failed intake consult: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)


def post_intake_consult_session_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:post_intake_consult_session (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  try:
    from intake_submission import generate_client_id, get_mysql_connection  # type: ignore
    from intake_consult_draft import create_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import generate_client_id: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  client_id = generate_client_id()
  conn = get_mysql_connection()
  try:
    draft = create_draft(conn, client_id=client_id)
    return jsonify({"status": "ok", **draft})
  finally:
    try:
      conn.close()
    except Exception:
      pass


def get_intake_consult_draft_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:get_intake_consult_draft (Phase 1 sweep).
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
    from intake_consult_draft import get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import consult draft helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    draft = get_draft(conn, draft_id=str(draft_id).strip())
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
        "draft_status": draft.get("status"),
        "messages_json": draft.get("messages_json"),
        "operating_model_json": draft.get("operating_model_json"),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass
