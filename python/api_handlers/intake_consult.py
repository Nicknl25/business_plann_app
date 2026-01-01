import json
from typing import Any, Dict, List, Optional

from flask import jsonify


OPS_CONFIRM_QUESTION = "Does this look right before we move on to Customers & Positioning?"


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


def _build_business_type_candidates(*, conn, messages: List[Dict[str, str]]) -> List[str]:
  """
  Build a small, relevant business_type candidate list by scoring known values against
  early user messages. This keeps finalization deterministic while avoiding a huge list.
  """
  try:
    from difflib import SequenceMatcher

    cur = conn.cursor()
    try:
      cur.execute("SELECT business_types FROM naics_master WHERE business_types IS NOT NULL")
      rows = cur.fetchall() or []
      values: List[str] = []
      for (bt,) in rows:
        if bt is None:
          continue
        for part in str(bt).split(","):
          part_str = str(part).strip()
          if part_str:
            values.append(part_str)
      all_business_types = sorted(set(values), key=lambda x: x.lower())
    finally:
      try:
        cur.close()
      except Exception:
        pass

    user_texts: List[str] = []
    for msg in messages:
      if str(msg.get("role") or "") != "user":
        continue
      content = str(msg.get("content") or "").strip()
      if not content:
        continue
      if "Start the operational intake." in content:
        continue
      user_texts.append(content)
      if len(user_texts) >= 6:
        break

    base = " ".join(user_texts).strip().lower()
    base = " ".join(base.split())
    tokens = {t for t in base.replace("/", " ").replace("-", " ").split() if len(t) >= 3}

    scored = []
    for bt in all_business_types:
      btl = bt.lower()
      token_score = sum(1 for t in tokens if t in btl) if tokens else 0
      ratio = SequenceMatcher(None, base, btl).ratio() if base else 0.0
      scored.append((token_score, ratio, bt))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [bt for _, _, bt in scored[:80]] or (all_business_types[:80] if all_business_types else [])
  except Exception:
    return []


def post_intake_consult_handler(*, app, request):
  """
  GPT-led operational intake consultant conversation (iterative).

  IMPORTANT ARCHITECTURE INVARIANT:
  - GPT is the sole authority for intent interpretation in post-completion messages.
  - Deterministic code only applies the explicit patch returned by GPT.
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  client_id = payload.get("client_id")
  raw_message = payload.get("message")
  reset = bool(payload.get("reset", False))
  starting = raw_message is None or not str(raw_message).strip()
  message = raw_message
  if starting:
    message = "Start the operational intake. Ask your first question."

  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_consultant import consultant_chat_turn, consultant_finalize  # type: ignore
    from intent_router import route_intent  # type: ignore
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import append_messages, get_draft  # type: ignore
    from api_handlers.shared_context import build_shared_context
  except Exception as exc:
    app.logger.exception("Failed to import intake consult helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  try:
    conn = get_mysql_connection()
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
      client_id_str = str(draft.get("client_id") or (client_id or "")).strip()
      draft_status = str(draft.get("status") or "").strip().lower()

      if draft_status == "submitted":
        operating_model_raw = draft.get("operating_model_json")
        parsed = _parse_json_dict(operating_model_raw)
        summary_text = str(parsed.get("business_description_summary") or "").strip()
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id_str,
            "done": True,
            "action": "submitted",
            "assistant_message": summary_text or "Operational intake complete.",
            "operating_model_json": json.dumps(parsed, ensure_ascii=False) if parsed else None,
          }
        )

      history = _parse_messages(draft.get("messages_json"))
      if reset:
        history = []

      shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
      intake_context: Dict[str, Any] = {
        "client_id": client_id_str,
        "business_name": payload.get("business_name"),
        "business_type": payload.get("business_type"),
        "address": payload.get("address"),
        "address_street": payload.get("address_street"),
        "address_city": payload.get("address_city"),
        "address_state": payload.get("address_state"),
        "address_zip": payload.get("address_zip"),
        "address_country": payload.get("address_country"),
        "shared_context": shared_context,
      }

      user_msg = {"role": "user", "content": str(message).strip()}

      # Completed consult: route ALL user messages through GPT intent router.
      if draft_status == "completed":
        baseline_operating_model = _parse_json_dict(draft.get("operating_model_json"))

        if starting:
          summary = str(baseline_operating_model.get("business_description_summary") or "").strip()
          assistant_message = f"{(summary or 'Operational intake complete.').strip()}\n\n{OPS_CONFIRM_QUESTION}".strip()
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id_str,
              "done": True,
              "action": "await_confirmation",
              "assistant_message": assistant_message,
              "operating_model_json": json.dumps(baseline_operating_model, ensure_ascii=False)
              if baseline_operating_model
              else None,
            }
          )

        routed = route_intent(
          consult_type="ops",
          user_message=str(message).strip(),
          baseline_json=baseline_operating_model,
          shared_context=shared_context,
          recent_messages=history[-30:] if history else [],
        )

        action = str(routed.get("action") or "").strip()
        assistant_message = str(routed.get("assistant_message") or "").strip()
        patch = routed.get("patch")

        updated_operating_model = baseline_operating_model
        if action == "edit_patch":
          if not isinstance(patch, dict):
            patch = {}
          updated_operating_model = dict(baseline_operating_model)
          updated_operating_model.update(patch)

        assistant_msg = {"role": "assistant", "content": assistant_message}
        new_messages = [user_msg, assistant_msg]

        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="completed",
          operating_model_json=updated_operating_model if action == "edit_patch" else None,
          flat_fields=updated_operating_model if action == "edit_patch" else None,
          completed=bool(action == "edit_patch"),
        )

        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id_str,
            "done": True,
            "action": action,
            "assistant_message": assistant_message,
            "operating_model_json": json.dumps(updated_operating_model, ensure_ascii=False)
            if updated_operating_model
            else None,
          }
        )

      # In-progress consult: normal chat turns until finalize-ready.
      app.logger.info(
        "Intake consult message for draft_id=%s client_id=%s: %s",
        draft_id,
        client_id_str,
        message,
      )
      print(f"Intake consult message draft_id={draft_id} client_id={client_id_str}:", str(message))

      turn = consultant_chat_turn(
        intake_context=intake_context,
        conversation_messages=[*history, user_msg],
      )
      assistant_text = str(turn.get("assistant_message") or "").strip()
      finalize_ready = bool(turn.get("finalize_ready", False))

      if not finalize_ready:
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
            "client_id": client_id_str,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
            "operating_model_json": None,
          }
        )

      # Finalize with schema.
      business_type_candidates = _build_business_type_candidates(conn=conn, messages=[*history, user_msg])
      final_context = dict(intake_context)
      final_context["business_type_candidates"] = business_type_candidates

      final_obj = consultant_finalize(
        intake_context=final_context,
        conversation_messages=[*history, user_msg, {"role": "assistant", "content": assistant_text}],
      )
      if not isinstance(final_obj, dict):
        raise RuntimeError("Finalization did not return an object.")

      summary_text = str(final_obj.get("business_description_summary") or "").strip() or "Operational intake complete."
      assistant_message = f"{summary_text}\n\n{OPS_CONFIRM_QUESTION}".strip()

      assistant_msg = {"role": "assistant", "content": assistant_message}
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, assistant_msg],
        status="completed",
        operating_model_json=final_obj,
        flat_fields=final_obj,
        completed=True,
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id_str,
          "done": True,
          "action": "await_confirmation",
          "assistant_message": assistant_message,
          "operating_model_json": json.dumps(final_obj, ensure_ascii=False),
        }
      )
    finally:
      try:
        conn.close()
      except Exception:
        pass
  except Exception as exc:
    app.logger.exception("Failed intake consult: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)


def post_intake_consult_session_handler(*, app, request):
  """
  Create a new durable pre-submit consultant draft and return {draft_id, client_id}.
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
  Return the operational consult draft row.
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

