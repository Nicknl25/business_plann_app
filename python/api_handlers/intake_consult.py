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
  edit_finalize = bool(payload.get("edit_finalize", False))
  reopen = bool(payload.get("reopen", False)) or edit_finalize
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
      reopen_draft,
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
    if draft_status == "submitted":
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
    if draft_status == "completed" and reopen:
      conn = get_mysql_connection()
      try:
        reopen_draft(conn, draft_id=str(draft_id).strip())
      finally:
        try:
          conn.close()
        except Exception:
          pass
      conn = get_mysql_connection()
      try:
        draft = get_draft(conn, draft_id=str(draft_id).strip())
      finally:
        try:
          conn.close()
        except Exception:
          pass
      draft_status = str(draft.get("status") or "").strip().lower()
    elif draft_status == "completed":
      operating_model_raw = draft.get("operating_model_json")
      if operating_model_raw:
        summary_text = ""
        try:
          parsed = json.loads(str(operating_model_raw))
          if isinstance(parsed, dict):
            summary_text = str(parsed.get("business_description_summary") or "").strip()
        except Exception:
          summary_text = ""
      else:
        summary_text = ""
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id_str,
          "done": True,
          "assistant_message": summary_text or "Operational intake complete.",
          "operating_model_json": str(operating_model_raw) if operating_model_raw else None,
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
    if edit_finalize:
      business_type_candidates: List[str] = []
      all_business_types: List[str] = []
      try:
        from difflib import SequenceMatcher

        conn = get_mysql_connection()
        try:
          cur = conn.cursor()
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
          try:
            conn.close()
          except Exception:
            pass

        # Build a condensed description from the earliest user messages.
        user_texts: List[str] = []
        for msg in [*history, user_msg]:
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
        business_type_candidates = [bt for _, _, bt in scored[:80]]
      except Exception as exc:
        app.logger.exception("Failed building business type candidates: %s", exc)
        business_type_candidates = []
        all_business_types = []

      final_context = dict(context)
      if business_type_candidates:
        final_context["business_type_candidates"] = business_type_candidates
      else:
        final_context["business_type_candidates"] = all_business_types[:80] if all_business_types else []

      final_obj = consultant_finalize(
        intake_context=final_context,
        conversation_messages=[*history, user_msg],
      )
      if not isinstance(final_obj, dict):
        raise RuntimeError("Finalization did not return an object.")

      bt_out = str(final_obj.get("business_type") or "").strip()
      if not bt_out:
        if business_type_candidates:
          bt_out = str(business_type_candidates[0]).strip()
        elif all_business_types:
          bt_out = str(all_business_types[0]).strip()
      if all_business_types and bt_out and bt_out not in set(all_business_types):
        try:
          from difflib import SequenceMatcher

          pool = business_type_candidates or all_business_types[:200]
          best = ""
          best_score = -1.0
          for cand in pool:
            score = SequenceMatcher(None, bt_out.lower(), cand.lower()).ratio()
            if score > best_score:
              best = cand
              best_score = score
          if best:
            bt_out = best
        except Exception:
          pass
      final_obj["business_type"] = bt_out

      assistant_message = (
        str(final_obj.get("business_description_summary") or "").strip()
        or "Operational intake complete."
      )
      assistant_msg = {"role": "assistant", "content": assistant_message}
      new_messages = [user_msg, assistant_msg]

      conn = get_mysql_connection()
      try:
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="completed",
          operating_model_json=final_obj,
          flat_fields=final_obj,
          completed=True,
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
          "done": True,
          "assistant_message": assistant_message,
          "operating_model_json": json.dumps(final_obj, ensure_ascii=False),
        }
      )

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
      # Provide business type candidates to the finalization step so the model can
      # choose a single best-fit value from the existing business_types list.
      business_type_candidates: List[str] = []
      all_business_types: List[str] = []
      try:
        from difflib import SequenceMatcher

        conn = get_mysql_connection()
        try:
          cur = conn.cursor()
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
          try:
            conn.close()
          except Exception:
            pass

        # Build a condensed description from the earliest user messages.
        user_texts: List[str] = []
        for msg in [*history, *new_messages]:
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
        business_type_candidates = [bt for _, _, bt in scored[:80]]
      except Exception as exc:
        app.logger.exception("Failed building business type candidates: %s", exc)
        business_type_candidates = []
        all_business_types = []

      if business_type_candidates:
        context = dict(context)
        context["business_type_candidates"] = business_type_candidates
      else:
        # Fallback: still provide something non-empty for the finalizer.
        context = dict(context)
        context["business_type_candidates"] = all_business_types[:80] if all_business_types else []

      final_obj = consultant_finalize(
        intake_context=context,
        conversation_messages=[*history, *new_messages],
      )
      if not isinstance(final_obj, dict):
        raise RuntimeError("Finalization did not return an object.")

      # Ensure business_type is present, non-empty, and matches an existing value.
      bt_out = str(final_obj.get("business_type") or "").strip()
      if not bt_out:
        if business_type_candidates:
          bt_out = str(business_type_candidates[0]).strip()
        elif all_business_types:
          bt_out = str(all_business_types[0]).strip()
      if all_business_types and bt_out and bt_out not in set(all_business_types):
        # If the model picked something outside the known list, snap to the closest candidate.
        try:
          from difflib import SequenceMatcher

          pool = business_type_candidates or all_business_types[:200]
          best = ""
          best_score = -1.0
          for cand in pool:
            score = SequenceMatcher(None, bt_out.lower(), cand.lower()).ratio()
            if score > best_score:
              best = cand
              best_score = score
          if best:
            bt_out = best
        except Exception:
          pass
      final_obj["business_type"] = bt_out

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
          flat_fields=final_obj,
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
