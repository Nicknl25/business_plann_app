import json
from typing import Any, Dict, List, Optional

from flask import jsonify


FIN_CONFIRM_QUESTION = "Does this look right before we move on to Submit intake?"


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
    if (
      numeric_vals["annual_interest_payment"] > 1e-9
      or numeric_vals["annual_principal_payment"] > 1e-9
    ):
      raise RuntimeError(
        "annual_interest_payment and annual_principal_payment must be 0 when total_debt_outstanding is 0."
      )


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
  starting = raw_message is None or not str(raw_message).strip()
  message = raw_message
  if starting:
    message = "Start the financials intake. Ask your first question."

  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore
    from financials_consult_draft import append_messages, create_draft, get_draft as get_fin_draft  # type: ignore
    from financials_consultant import financials_chat_turn, financials_finalize  # type: ignore
    from api_handlers.shared_context import build_shared_context
    from intent_router import route_intent  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import financials consult helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  try:
    conn = get_mysql_connection()
    try:
      consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
      client_id = str(consult.get("client_id") or "").strip()

      shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
      operating_model = shared_context.get("operating_model") or {}

      try:
        fin_draft = get_fin_draft(conn, draft_id=str(draft_id).strip())
      except Exception:
        create_draft(conn, draft_id=str(draft_id).strip(), client_id=client_id)
        fin_draft = get_fin_draft(conn, draft_id=str(draft_id).strip())

      fin_status = str(fin_draft.get("status") or "").strip().lower()
      history = _parse_messages(fin_draft.get("messages_json"))
      user_msg = {"role": "user", "content": str(message).strip()}

      # Completed: route all user messages through GPT intent router.
      if fin_status == "completed":
        baseline_financials = _parse_json_dict(fin_draft.get("financials_json"))

        if starting:
          summary = str(baseline_financials.get("financials_summary") or "").strip()
          assistant_message = (summary or "Financials intake complete.").strip()
          from fact_templates import sanitize_fact_template  # type: ignore

          assistant_message = sanitize_fact_template(assistant_message)
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "done": True,
              "action": "await_confirmation",
              "assistant_message": assistant_message,
              "financials_json": json.dumps(baseline_financials, ensure_ascii=False)
              if baseline_financials
              else None,
            }
          )

        routed = route_intent(
          consult_type="financials",
          user_message=str(message).strip(),
          baseline_json=baseline_financials,
          shared_context=shared_context,
          recent_messages=history[-30:] if history else [],
          active_focus="financials",
        )
        action = str(routed.get("action") or "").strip()
        assistant_message = str(routed.get("assistant_message") or "").strip()
        patch = routed.get("patch")

        updated_financials = baseline_financials
        if action == "edit_patch":
          from fact_templates import sanitize_fact_template  # type: ignore

          if not isinstance(patch, dict):
            patch = {}
          updated_financials = dict(baseline_financials)
          updated_financials.update(patch)
          updated_financials = {
            k: (sanitize_fact_template(v) if isinstance(v, str) else v)
            for k, v in updated_financials.items()
          }

          summary_for_ui = str(updated_financials.get("financials_summary") or "").strip()
          assistant_message = summary_for_ui or (assistant_message or "Got it.").strip()
          assistant_message = sanitize_fact_template(assistant_message)
        else:
          from fact_templates import sanitize_fact_template  # type: ignore

          assistant_message = sanitize_fact_template(assistant_message)

        assistant_msg = {"role": "assistant", "content": assistant_message}
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, assistant_msg],
          status="completed",
          financials_json=updated_financials if action == "edit_patch" else None,
          flat_fields=updated_financials if action == "edit_patch" else None,
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
            "financials_json": json.dumps(updated_financials, ensure_ascii=False)
            if updated_financials
            else None,
          }
        )

      context = {
        "client_id": client_id,
        "business_name": payload.get("business_name"),
        "business_start_date": payload.get("business_start_date"),
        "shared_context": shared_context,
        "operating_model": operating_model,
        "target_market": shared_context.get("target_market") or {},
        "people_capability": shared_context.get("people_capability") or {},
        "unit_name": operating_model.get("unit_name"),
        "unit_price": operating_model.get("unit_price"),
        "business_description_summary": operating_model.get("business_description_summary"),
        "consumer_type": operating_model.get("consumer_type"),
      }

      turn = financials_chat_turn(
        intake_context=context,
        conversation_messages=[*history, user_msg],
      )
      from fact_templates import sanitize_fact_template  # type: ignore

      assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
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
            "client_id": client_id,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
            "financials_json": None,
          }
        )

      final_obj = financials_finalize(
        intake_context=context,
        conversation_messages=[*history, user_msg, {"role": "assistant", "content": assistant_text}],
      )
      from fact_templates import sanitize_fact_template  # type: ignore

      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      _validate_final(final_obj)

      summary_text = str(final_obj.get("financials_summary") or "").strip() or "Financials intake complete."
      assistant_message = str(assistant_text or "").strip()
      if not assistant_message:
        assistant_message = summary_text
      assistant_message = sanitize_fact_template(assistant_message)
      assistant_msg = {"role": "assistant", "content": assistant_message}

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, assistant_msg],
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
          "action": "await_confirmation",
          "assistant_message": assistant_message,
          "financials_json": json.dumps(final_obj, ensure_ascii=False),
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
