import json
from typing import Any, Dict, List

from flask import jsonify


def post_financials_consult_session_handler(*, app, request):
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
    from financials_consult_draft import create_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import financials draft helpers: %s", exc)
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


def get_financials_consult_draft_handler(*, app, request):
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
    from financials_consult_draft import get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import financials draft helpers: %s", exc)
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
        "financials_json": draft.get("financials_json"),
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


def post_financials_consult_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  raw_message = payload.get("message")
  message = raw_message
  edit_finalize = bool(payload.get("edit_finalize", False))
  reopen = bool(payload.get("reopen", False)) or edit_finalize
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  starting = message is None or not str(message).strip()
  if starting:
    message = "Start the financials intake. Ask your first question."

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore
    from financials_consult_draft import (  # type: ignore
      append_messages,
      create_draft,
      get_draft as get_fin_draft,
      reopen_draft,
    )
    from financials_consultant import (  # type: ignore
      financials_chat_turn,
      financials_finalize,
    )
  except Exception as exc:
    app.logger.exception("Failed to import financials consult helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  def _validate_final(final_obj: Dict[str, Any]) -> None:
    if not isinstance(final_obj, dict):
      raise RuntimeError("Final financials JSON must be an object.")
    summary = str(final_obj.get("financials_summary") or "").strip()
    if not summary:
      raise RuntimeError("Final financials JSON missing financials_summary.")
    conf = final_obj.get("confidence")
    try:
      conf_val = float(conf)
    except Exception as exc:
      raise RuntimeError("Final financials JSON missing valid confidence.") from exc
    if conf_val <= 0 or conf_val > 1:
      raise RuntimeError("confidence must be between 0 and 1.")

    numeric_fields = [
      "current_revenue",
      "current_cogs",
      "other_operating_expense",
      "monthly_rent_expense",
      "other_monthly_debt_payments",
      "current_payroll",
      "current_num_employees",
      "current_capex",
      "ar_balance",
      "ap_balance",
      "inventory_balance",
      "total_debt_outstanding",
      "annual_interest_payment",
      "annual_principal_payment",
      "owner_compensation",
      "cash_on_hand",
    ]

    numeric_vals: Dict[str, float] = {}
    for field in numeric_fields:
      try:
        numeric_vals[field] = float(final_obj.get(field))
      except Exception as exc:
        raise RuntimeError(f"{field} must be a number.") from exc
      if numeric_vals[field] < 0:
        raise RuntimeError(f"{field} must be >= 0.")

    debt = numeric_vals["total_debt_outstanding"]
    if debt <= 1e-9:
      if numeric_vals["annual_interest_payment"] > 1e-9 or numeric_vals["annual_principal_payment"] > 1e-9:
        raise RuntimeError(
          "annual_interest_payment and annual_principal_payment must be 0 when total_debt_outstanding is 0."
        )

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

      # Ensure the financials draft row exists.
      try:
        fin_draft = get_fin_draft(conn, draft_id=str(draft_id).strip())
      except Exception:
        create_draft(conn, draft_id=str(draft_id).strip(), client_id=client_id)
        fin_draft = get_fin_draft(conn, draft_id=str(draft_id).strip())

      fin_status = str(fin_draft.get("status") or "").strip().lower()
      if fin_status == "completed" and not reopen:
        fin_raw = fin_draft.get("financials_json")
        fin_summary = ""
        if fin_raw:
          try:
            fin_obj = json.loads(str(fin_raw))
            if isinstance(fin_obj, dict):
              fin_summary = str(fin_obj.get("financials_summary") or "").strip()
          except Exception:
            fin_summary = ""
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "done": True,
            "assistant_message": fin_summary or "Financials intake complete.",
            "financials_json": str(fin_raw) if fin_raw is not None else None,
          }
        )
      if fin_status == "completed" and reopen:
        reopen_draft(conn, draft_id=str(draft_id).strip())
        fin_draft = get_fin_draft(conn, draft_id=str(draft_id).strip())
        fin_status = str(fin_draft.get("status") or "").strip().lower()

      history: List[Dict[str, str]] = []
      try:
        raw_messages = fin_draft.get("messages_json")
        if raw_messages:
          parsed = json.loads(str(raw_messages))
          if isinstance(parsed, list):
            history = [m for m in parsed if isinstance(m, dict)]
      except Exception:
        history = []

      context = {
        "client_id": client_id,
        "business_name": payload.get("business_name"),
        "business_start_date": payload.get("business_start_date"),
        "unit_name": operating_model.get("unit_name"),
        "unit_price": operating_model.get("unit_price"),
        "business_description_summary": operating_model.get("business_description_summary"),
        "consumer_type": operating_model.get("consumer_type"),
      }

      user_msg = {"role": "user", "content": str(message).strip()}

      if edit_finalize:
        final_obj = financials_finalize(
          intake_context=context,
          conversation_messages=[*history, user_msg],
        )
        _validate_final(final_obj)
        assistant_message = str(final_obj.get("financials_summary") or "").strip() or "Financials intake complete."
        assistant_msg = {"role": "assistant", "content": assistant_message}
        new_messages = [user_msg, assistant_msg]
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="completed",
          financials_json=final_obj,
          flat_fields=final_obj,
          completed=True,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "done": True,
            "assistant_message": assistant_message,
            "financials_json": json.dumps(final_obj, ensure_ascii=False),
          }
        )

      turn = financials_chat_turn(
        intake_context=context,
        conversation_messages=[*history, user_msg],
      )
      assistant_text = str(turn.get("assistant_message") or "").strip()
      finalize_ready = bool(turn.get("finalize_ready", False))
      assistant_msg = {"role": "assistant", "content": assistant_text}
      new_messages = [user_msg, assistant_msg]

      done = False
      assistant_message = assistant_text
      financials_json_out = None

      if finalize_ready:
        final_obj = financials_finalize(
          intake_context=context,
          conversation_messages=[*history, *new_messages],
        )
        _validate_final(final_obj)
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=new_messages,
          status="completed",
          financials_json=final_obj,
          flat_fields=final_obj,
          completed=True,
        )
        done = True
        assistant_message = str(final_obj.get("financials_summary") or "").strip() or "Financials intake complete."
        financials_json_out = json.dumps(final_obj, ensure_ascii=False)
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
          "financials_json": financials_json_out,
        }
      )
    finally:
      try:
        conn.close()
      except Exception:
        pass
  except Exception as exc:
    app.logger.exception("Failed financials consult: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)
