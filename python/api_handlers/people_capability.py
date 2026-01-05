import json
from typing import Any, Dict, List

from flask import jsonify


def _parse_json_dict(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _parse_messages(raw: Any) -> List[Dict[str, str]]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return [m for m in raw if isinstance(m, dict)]
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  return [m for m in parsed if isinstance(m, dict)] if isinstance(parsed, list) else []


def _validate_final(final_obj: Dict[str, Any]) -> None:
  if not isinstance(final_obj, dict):
    raise RuntimeError("Final people output must be an object.")
  people = final_obj.get("people")
  if not isinstance(people, list) or not people:
    raise RuntimeError("people must be a non-empty array.")
  for p in people:
    if not isinstance(p, dict):
      raise RuntimeError("people items must be objects.")
    if not str(p.get("full_name") or "").strip():
      raise RuntimeError("people.full_name is required.")
    if not str(p.get("role_title") or "").strip():
      raise RuntimeError("people.role_title is required.")
    if not str(p.get("paragraph") or "").strip():
      raise RuntimeError("people.paragraph is required.")


def post_people_capability_session_handler(*, app, request):
  """
  Ensure a durable People & Capability draft exists for an existing intake draft_id.
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
  Return the People & Capability draft row.
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
  Durable People & Capability conversation.

  Invariant:
  - If the People consult is completed, ALL new messages are routed through the GPT intent router.
  - Deterministic code only applies the explicit patch from GPT (no keyword heuristics).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  raw_message = payload.get("message")
  starting = raw_message is None or not str(raw_message).strip()
  message = raw_message
  if starting:
    message = "Start the People & Capability intake. Ask your first question."

  business_name = payload.get("business_name")
  business_type = payload.get("business_type")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore
    from people_capability_draft import append_messages, create_draft, get_draft as get_pc_draft  # type: ignore
    from people_capability_consultant import (  # type: ignore
      people_capability_chat_turn,
      people_capability_finalize,
    )
    from api_handlers.shared_context import build_shared_context
    from intent_router import route_intent  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import people consult helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  try:
    conn = get_mysql_connection()
    try:
      consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
      client_id = str(consult.get("client_id") or "").strip()

      shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
      operating_model = shared_context.get("operating_model") or {}

      try:
        pc_draft = get_pc_draft(conn, draft_id=str(draft_id).strip())
      except Exception:
        create_draft(conn, draft_id=str(draft_id).strip(), client_id=client_id)
        pc_draft = get_pc_draft(conn, draft_id=str(draft_id).strip())

      pc_status = str(pc_draft.get("status") or "").strip().lower()
      history = _parse_messages(pc_draft.get("messages_json"))
      user_msg = {"role": "user", "content": str(message).strip()}

      # Completed: route all user messages through GPT intent router.
      if pc_status == "completed":
        baseline_people = _parse_json_dict(pc_draft.get("people_json"))

        if starting:
          # Summaries are deprecated; do not show key_people_summary.
          assistant_message = "People & capability intake complete."
          from fact_templates import sanitize_fact_template  # type: ignore

          assistant_message = sanitize_fact_template(assistant_message)
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "done": True,
              "action": "completed",
              "assistant_message": assistant_message,
              "people_json": json.dumps(baseline_people, ensure_ascii=False) if baseline_people else None,
            }
          )

        routed = route_intent(
          consult_type="people",
          user_message=str(message).strip(),
          baseline_json=baseline_people,
          shared_context=shared_context,
          recent_messages=history[-30:] if history else [],
          active_focus="people",
        )
        action = str(routed.get("action") or "").strip()
        assistant_message = str(routed.get("assistant_message") or "").strip()
        patch = routed.get("patch")

        updated_people = baseline_people
        from fact_templates import sanitize_fact_template  # type: ignore

        if action == "edit_patch":
          if not isinstance(patch, dict):
            patch = {}
          if patch:
            updated_people = dict(baseline_people)
            updated_people.update(patch)
            updated_people = {
              k: (sanitize_fact_template(v) if isinstance(v, str) else v)
              for k, v in updated_people.items()
            }
            # Summaries are deprecated; keep the chat response short and rely on structured fields.
            updated_people["key_people_summary"] = None
            assistant_message = sanitize_fact_template(assistant_message or "Updated people & capability drivers.")
          else:
            action = "answer_readonly"
            assistant_message = sanitize_fact_template(assistant_message)
        else:
          assistant_message = sanitize_fact_template(assistant_message)

        assistant_msg = {"role": "assistant", "content": assistant_message}
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, assistant_msg],
          status="completed",
          people_json=updated_people if action == "edit_patch" else None,
          flat_fields=updated_people if action == "edit_patch" else None,
          completed=bool(action == "edit_patch"),
        )

        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "done": True,
            "action": action,
            "assistant_message": assistant_message,
            "people_json": json.dumps(updated_people, ensure_ascii=False) if updated_people else None,
          }
        )

      # In-progress: normal chat turns until finalize-ready.
      context = {
        "client_id": client_id,
        "shared_context": shared_context,
        "business_name": (str(business_name).strip() if business_name else None),
        "business_type": (str(business_type).strip() if business_type else None),
        "business_description_summary": None,
        "unit_name": operating_model.get("unit_name"),
        "unit_price": operating_model.get("unit_price"),
        "shipping_method": operating_model.get("shipping_method"),
      }

      turn = people_capability_chat_turn(
        intake_context=context,
        conversation_messages=[*history, user_msg],
      )
      from fact_templates import sanitize_fact_template  # type: ignore

      assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
      turn_outcome = str(turn.get("turn_outcome") or "").strip().upper()

      if turn_outcome != "SECTION_COMPLETE":
        assistant_msg = {"role": "assistant", "content": assistant_text}
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, assistant_msg],
          status="in_progress",
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

      final_obj = people_capability_finalize(
        intake_context=context,
        # Do NOT include the chat-turn assistant text in the finalizer context; it may contain
        # a draft recap with incorrect literals. The strict finalizer should operate on the
        # conversation + the user's last message only.
        conversation_messages=[*history, user_msg],
      )
      if not isinstance(final_obj, dict):
        final_obj = {}
      for k, v in list(final_obj.items()):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      # Summaries are deprecated; do not show or persist key_people_summary.
      summary_text = "People & capability intake complete."
      final_obj.pop("assistant_message", None)
      final_obj.pop("turn_outcome", None)
      final_obj["key_people_summary"] = None
      _validate_final(final_obj)

      assistant_message = summary_text
      assistant_message = sanitize_fact_template(assistant_message)
      assistant_msg = {"role": "assistant", "content": assistant_message}

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, assistant_msg],
        status="completed",
        people_json=final_obj,
        flat_fields=final_obj,
        completed=True,
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "done": True,
          "action": "completed",
          "assistant_message": assistant_message,
          "people_json": json.dumps(final_obj, ensure_ascii=False),
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
