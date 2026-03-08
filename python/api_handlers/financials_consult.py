import json
from typing import Any, Dict, List, Optional

from flask import jsonify


FIN_CONFIRM_QUESTION = "Does this look right before we move on to Submit intake?"


def _last_assistant_message(messages: List[Dict[str, str]]) -> str:
  for msg in reversed(messages or []):
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    text = str(msg.get("content") or "").strip()
    if text:
      return text
  return ""


def _should_check_revenue_patch(last_assistant: str, user_message: str) -> bool:
  assistant = str(last_assistant or "").lower()
  if "year 1 revenue" in assistant or "year-1 revenue" in assistant:
    return True
  if "revenue math" in assistant:
    return True
  msg = str(user_message or "").lower()
  keywords = [
    "unit price",
    "price per",
    "units per week",
    "units/week",
    "units per month",
    "units/month",
    "per month",
    "monthly",
    "per contract",
    "contracts",
    "retainer",
    "weeks per year",
    "weeks/year",
    "periods per year",
    "periods/year",
    "utilization",
    "capacity",
    "product",
    "line of business",
    "lob",
  ]
  return any(k in msg for k in keywords)


def _extract_revenue_proposal_patch(
  *,
  last_assistant: str,
  route_intent,
  financials_year1_json: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  text = str(last_assistant or "").strip()
  if not text:
    return None
  try:
    proposal_intent = route_intent(
      consult_type="financials_year1",
      user_message=text,
      baseline_json=financials_year1_json,
      shared_context=shared_context,
      recent_messages=[],
      active_focus="financials",
    )
  except Exception:
    return None
  if str(proposal_intent.get("action") or "").strip() != "edit_patch":
    return None
  patch = proposal_intent.get("patch")
  if not isinstance(patch, dict) or not patch:
    return None
  return patch


def _is_guardrail_acknowledgement(message: str) -> bool:
  text = str(message or "").strip().lower()
  if not text:
    return False
  try:
    import re

    patterns = [
      r"\bok\b",
      r"\bokay\b",
      r"\byes\b",
      r"\bsounds good\b",
      r"\blooks good\b",
      r"\bworks for me\b",
      r"\bgo ahead\b",
      r"\bproceed\b",
      r"\bkeep (it|this) (as is|the same)\b",
      r"\bkeep as is\b",
      r"\bleave it\b",
      r"\bno changes\b",
      r"\bno change\b",
      r"\bi understand\b",
      r"\bunderstood\b",
      r"\baccept\b",
      r"\bi'?m ok\b",
      r"\bi am ok\b",
      r"\bfine\b",
      r"\ball good\b",
    ]
    return any(re.search(pat, text) for pat in patterns)
  except Exception:
    return False

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


def _year1_driver_map(year1_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  out: Dict[str, Dict[str, Any]] = {}
  if not isinstance(year1_json, dict):
    return out
  lobs = year1_json.get("lobs")
  if not isinstance(lobs, list):
    return out
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip().lower()
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip().lower()
      if not product_name:
        continue
      key = f"{lob_name}::{product_name}"
      out[key] = {
        "unit_cadence": str(product.get("unit_cadence") or "").strip().lower(),
        "unit_price": product.get("unit_price"),
        "units_per_period_capacity": product.get("units_per_period_capacity"),
        "utilization_rate": product.get("utilization_rate"),
      }
  return out


def _year1_drivers_conflict(existing_year1: Dict[str, Any], base_year1: Dict[str, Any]) -> bool:
  if not isinstance(existing_year1, dict) or not existing_year1:
    return False
  existing_map = _year1_driver_map(existing_year1)
  base_map = _year1_driver_map(base_year1)
  if not existing_map or not base_map:
    return False

  def _num(value: Any) -> Optional[float]:
    try:
      return float(value)
    except Exception:
      return None

  for key, base_driver in base_map.items():
    existing_driver = existing_map.get(key)
    if not existing_driver:
      continue
    base_cadence = str(base_driver.get("unit_cadence") or "").strip().lower()
    existing_cadence = str(existing_driver.get("unit_cadence") or "").strip().lower()
    if base_cadence and existing_cadence and base_cadence != existing_cadence:
      return True
    base_price = _num(base_driver.get("unit_price"))
    existing_price = _num(existing_driver.get("unit_price"))
    if base_price is not None and existing_price is not None and abs(base_price - existing_price) > 0.01:
      return True
    base_capacity = _num(base_driver.get("units_per_period_capacity"))
    existing_capacity = _num(existing_driver.get("units_per_period_capacity"))
    if base_capacity is not None and existing_capacity is not None and abs(base_capacity - existing_capacity) > 0.01:
      return True
    base_util = _num(base_driver.get("utilization_rate"))
    existing_util = _num(existing_driver.get("utilization_rate"))
    if base_util is not None and existing_util is not None and abs(base_util - existing_util) > 0.0001:
      return True
  return False


def _constraints_snippet_already_sent(messages: List[Dict[str, str]]) -> bool:
  for msg in messages or []:
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    content = str(msg.get("content") or "")
    if "operational constraints:" in content.lower():
      return True
  return False


def _append_constraints_snippet(
  assistant_text: str,
  snippet: str,
  messages: List[Dict[str, str]],
  *,
  force: bool = False,
) -> str:
  # Financials no longer shows the deterministic "Operational constraints" block
  # in the client-facing chat output.
  return assistant_text


def _validate_final(final_obj: Dict[str, Any]) -> None:
  if not isinstance(final_obj, dict):
    raise RuntimeError("Final financials JSON must be an object.")
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
    "initial_assets",
    "initial_equity",
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

  lease_raw = final_obj.get("initial_lease")
  if not isinstance(lease_raw, str) or not lease_raw.strip():
    raise RuntimeError("initial_lease must be a non-empty string.")


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
        "financials_year1_json": draft.get("financials_year1_json"),
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
    from intake_consult_draft import append_messages as append_intake_messages  # type: ignore
    from financials_consult_draft import append_messages, create_draft, get_draft as get_fin_draft  # type: ignore
    from financials_consultant import financials_chat_turn, financials_finalize  # type: ignore
    from financials_year1 import (  # type: ignore
      assemble_financials_year1,
      apply_revenue_driver_patch,
      build_revenue_driver_signature,
      build_revenue_guardrail_signals,
      build_revenue_math_line,
      build_revenue_constraints_snippet,
    )
    from api_handlers.fact_propagation import propagate_shared_facts
    from api_handlers.shared_context import build_shared_context
    from api_handlers.revenue_guardrail_state import acknowledge_signature, get_acknowledged_signature
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
      target_market = shared_context.get("target_market") or {}
      people_capability = shared_context.get("people_capability") or {}
      financials_context = shared_context.get("financials") or {}
      raw_start_date = payload.get("business_start_date")
      if raw_start_date is None:
        raw_start_date = payload.get("businessStartDate") or payload.get("business_startDate")
      business_start_date = str(raw_start_date or consult.get("business_start_date") or "").strip() or None

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
        existing_year1 = _parse_json_dict(fin_draft.get("financials_year1_json"))
        base_year1 = assemble_financials_year1(shared_context, None)
        if _year1_drivers_conflict(existing_year1, base_year1):
          financials_year1_json = base_year1
        else:
          financials_year1_json = assemble_financials_year1(shared_context, existing_year1)
        shared_context["financials_year1_json"] = financials_year1_json
        revenue_math_line = build_revenue_math_line(
          financials_year1_json,
          unit_name=str((operating_model or {}).get("unit_name") or "").strip() or None,
        )
        revenue_constraints_snippet = build_revenue_constraints_snippet(
          shared_context,
          financials_year1_json,
          business_start_date=business_start_date,
        )

        if starting:
          assistant_message = "Financials intake complete."
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
              "financials_year1_json": json.dumps(financials_year1_json, ensure_ascii=False)
              if financials_year1_json
              else None,
            }
          )

        last_assistant = _last_assistant_message(history)
        if _should_check_revenue_patch(last_assistant, str(message)):
          revenue_intent = route_intent(
            consult_type="financials_year1",
            user_message=str(message).strip(),
            baseline_json=financials_year1_json,
            shared_context=shared_context,
            recent_messages=history[-30:] if history else [],
            active_focus="financials",
          )
          action = str(revenue_intent.get("action") or "").strip()
          patch = None
          if action == "edit_patch":
            patch = revenue_intent.get("patch")
          elif action == "confirm_proceed":
            patch = _extract_revenue_proposal_patch(
              last_assistant=last_assistant,
              route_intent=route_intent,
              financials_year1_json=financials_year1_json,
              shared_context=shared_context,
            )
          if isinstance(patch, dict) and patch:
            before_year1 = json.loads(json.dumps(financials_year1_json, ensure_ascii=False))
            financials_year1_json = apply_revenue_driver_patch(financials_year1_json, patch)
            updated_consults, propagated = propagate_shared_facts(
              source_consult_type="financials_year1",
              before_json=before_year1,
              after_json=financials_year1_json,
              consult_jsons={
                "ops": operating_model,
                "target_market": target_market,
                "people": people_capability,
                "financials": financials_context,
                "financials_year1": financials_year1_json,
              },
            )
            operating_model = updated_consults.get("ops") or operating_model
            target_market = updated_consults.get("target_market") or target_market
            people_capability = updated_consults.get("people") or people_capability
            financials_context = updated_consults.get("financials") or financials_context
            financials_year1_json = updated_consults.get("financials_year1") or financials_year1_json
            if propagated:
              shared_context["operating_model"] = operating_model
              shared_context["target_market"] = target_market
              shared_context["people_capability"] = people_capability
              shared_context["financials"] = financials_context
              append_intake_messages(
                conn,
                draft_id=str(draft_id).strip(),
                new_messages=[],
                operating_model_json=operating_model,
                target_market_json=target_market,
                people_json=people_capability,
                financials_json=financials_context,
                financials_year1_json=financials_year1_json,
              )
            revenue_math_line = build_revenue_math_line(
              financials_year1_json,
              unit_name=str((operating_model or {}).get("unit_name") or "").strip() or None,
            )
            revenue_constraints_snippet = build_revenue_constraints_snippet(
              shared_context,
              financials_year1_json,
              business_start_date=business_start_date,
            )
            assistant_message = (
              "Updated the revenue drivers. Year 1 revenue:\n\n"
              f"{revenue_math_line}\n\n"
              "Does this look right, or which driver should change?"
            )
            assistant_message = _append_constraints_snippet(
              assistant_message,
              revenue_constraints_snippet,
              history,
              force=True,
            )
            append_messages(
              conn,
              draft_id=str(draft_id).strip(),
              new_messages=[user_msg, {"role": "assistant", "content": assistant_message}],
              status="completed",
              financials_year1_json=financials_year1_json,
              completed=True,
            )
            return jsonify(
              {
                "status": "ok",
                "draft_id": str(draft_id).strip(),
                "client_id": client_id,
                "done": True,
                "action": "edit_patch",
                "assistant_message": assistant_message,
                "financials_json": json.dumps(baseline_financials, ensure_ascii=False)
                if baseline_financials
                else None,
                "financials_year1_json": json.dumps(financials_year1_json, ensure_ascii=False)
                if financials_year1_json
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

          assistant_message = (assistant_message or "Got it.").strip()
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
          financials_year1_json=financials_year1_json,
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
            "financials_year1_json": json.dumps(financials_year1_json, ensure_ascii=False)
            if financials_year1_json
            else None,
          }
        )

      baseline_financials = _parse_json_dict(fin_draft.get("financials_json"))
      updated_financials = baseline_financials
      applied_patch = False
      if not starting:
        routed = route_intent(
          consult_type="financials",
          user_message=str(message).strip(),
          baseline_json=baseline_financials,
          shared_context=shared_context,
          recent_messages=history[-30:] if history else [],
          active_focus="financials",
        )
        if str(routed.get("action") or "").strip() == "edit_patch":
          from fact_templates import sanitize_fact_template  # type: ignore

          patch = routed.get("patch")
          if not isinstance(patch, dict):
            patch = {}
          updated_financials = dict(baseline_financials)
          updated_financials.update(patch)
          updated_financials = {
            k: (sanitize_fact_template(v) if isinstance(v, str) else v)
            for k, v in updated_financials.items()
          }
          applied_patch = True

      existing_year1 = _parse_json_dict(fin_draft.get("financials_year1_json"))
      base_year1 = assemble_financials_year1(shared_context, None)
      if _year1_drivers_conflict(existing_year1, base_year1):
        financials_year1_json = base_year1
      else:
        financials_year1_json = assemble_financials_year1(shared_context, existing_year1)
      shared_context["financials_year1_json"] = financials_year1_json
      revenue_constraints_snippet = build_revenue_constraints_snippet(
        shared_context,
        financials_year1_json,
        business_start_date=business_start_date,
      )
      revenue_driver_patch = None
      guardrail_signals = build_revenue_guardrail_signals(
        shared_context,
        financials_year1_json,
        business_start_date=business_start_date,
      )
      driver_signature = build_revenue_driver_signature(financials_year1_json)
      guardrail_acknowledged = get_acknowledged_signature(str(draft_id).strip()) == driver_signature
      guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged
      if not starting:
        last_assistant = _last_assistant_message(history)
        should_check_revenue = _should_check_revenue_patch(last_assistant, str(message)) or guardrail_triggered
        if should_check_revenue:
          revenue_intent = route_intent(
            consult_type="financials_year1",
            user_message=str(message).strip(),
            baseline_json=financials_year1_json,
            shared_context=shared_context,
            recent_messages=history[-30:] if history else [],
            active_focus="financials",
          )
          action = str(revenue_intent.get("action") or "").strip()
          patch = None
          if action == "edit_patch":
            patch = revenue_intent.get("patch")
          elif action == "confirm_proceed":
            patch = _extract_revenue_proposal_patch(
              last_assistant=last_assistant,
              route_intent=route_intent,
              financials_year1_json=financials_year1_json,
              shared_context=shared_context,
            )
          if isinstance(patch, dict) and patch:
            before_year1 = json.loads(json.dumps(financials_year1_json, ensure_ascii=False))
            revenue_driver_patch = patch
            financials_year1_json = apply_revenue_driver_patch(financials_year1_json, patch)
            updated_consults, propagated = propagate_shared_facts(
              source_consult_type="financials_year1",
              before_json=before_year1,
              after_json=financials_year1_json,
              consult_jsons={
                "ops": operating_model,
                "target_market": target_market,
                "people": people_capability,
                "financials": financials_context,
                "financials_year1": financials_year1_json,
              },
            )
            operating_model = updated_consults.get("ops") or operating_model
            target_market = updated_consults.get("target_market") or target_market
            people_capability = updated_consults.get("people") or people_capability
            financials_context = updated_consults.get("financials") or financials_context
            financials_year1_json = updated_consults.get("financials_year1") or financials_year1_json
            if propagated:
              shared_context["operating_model"] = operating_model
              shared_context["target_market"] = target_market
              shared_context["people_capability"] = people_capability
              shared_context["financials"] = financials_context
              append_intake_messages(
                conn,
                draft_id=str(draft_id).strip(),
                new_messages=[],
                operating_model_json=operating_model,
                target_market_json=target_market,
                people_json=people_capability,
                financials_json=financials_context,
                financials_year1_json=financials_year1_json,
              )
            revenue_constraints_snippet = build_revenue_constraints_snippet(
              shared_context,
              financials_year1_json,
              business_start_date=business_start_date,
            )
            guardrail_signals = build_revenue_guardrail_signals(
              shared_context,
              financials_year1_json,
              business_start_date=business_start_date,
            )
            driver_signature = build_revenue_driver_signature(financials_year1_json)
            guardrail_acknowledged = (
              get_acknowledged_signature(str(draft_id).strip()) == driver_signature
            )
            guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged
            if guardrail_triggered:
              acknowledge_signature(str(draft_id).strip(), driver_signature)
              guardrail_triggered = False

      if (
        guardrail_triggered
        and not revenue_driver_patch
        and not starting
        and _is_guardrail_acknowledgement(str(message))
      ):
        acknowledge_signature(str(draft_id).strip(), driver_signature)
        guardrail_triggered = False

      revenue_math_line = build_revenue_math_line(
        financials_year1_json,
        unit_name=str((operating_model or {}).get("unit_name") or "").strip() or None,
      )

      context = {
        "client_id": client_id,
        "business_name": payload.get("business_name"),
        "business_start_date": business_start_date,
        "shared_context": shared_context,
        "operating_model": operating_model,
        "target_market": shared_context.get("target_market") or {},
        "people_capability": shared_context.get("people_capability") or {},
        "unit_name": operating_model.get("unit_name"),
        "unit_price": operating_model.get("unit_price"),
        "consumer_type": operating_model.get("consumer_type"),
        "financials_year1_json": financials_year1_json,
        "revenue_math_line": revenue_math_line,
        "revenue_constraints_snippet": revenue_constraints_snippet,
        "revenue_driver_patch": revenue_driver_patch,
        "revenue_guardrail_triggered": guardrail_triggered,
        "revenue_guardrail_context_signals": guardrail_signals.get("context_signals") or [],
        "revenue_guardrail_product_signals": guardrail_signals.get("product_signals") or [],
      }

      turn = financials_chat_turn(
        intake_context=context,
        conversation_messages=[*history, user_msg],
      )
      from fact_templates import sanitize_fact_template  # type: ignore

      assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
      should_append_constraints = (
        starting
        or bool(revenue_driver_patch)
        or ("year 1 revenue" in assistant_text.lower() or "year-1 revenue" in assistant_text.lower())
        or (revenue_math_line and revenue_math_line in assistant_text)
      )
      assistant_text = _append_constraints_snippet(
        assistant_text,
        revenue_constraints_snippet,
        history,
        force=should_append_constraints,
      )
      finalize_ready = bool(turn.get("finalize_ready", False))
      if guardrail_triggered:
        finalize_ready = False

      if not finalize_ready:
        assistant_msg = {"role": "assistant", "content": assistant_text}
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, assistant_msg],
          status="in_progress",
          financials_json=updated_financials if applied_patch else None,
          flat_fields=updated_financials if applied_patch else None,
          financials_year1_json=financials_year1_json,
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
            "financials_year1_json": json.dumps(financials_year1_json, ensure_ascii=False)
            if financials_year1_json
            else None,
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

      assistant_message = str(assistant_text or "").strip() or "Financials intake complete."
      assistant_message = sanitize_fact_template(assistant_message)
      assistant_msg = {"role": "assistant", "content": assistant_message}

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, assistant_msg],
        status="completed",
        financials_json=final_obj,
        financials_year1_json=financials_year1_json,
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
          "financials_year1_json": json.dumps(financials_year1_json, ensure_ascii=False)
          if financials_year1_json
          else None,
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
