import json
from typing import Any, Dict, List

from flask import jsonify


def post_financials_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:post_financials (Phase 1 sweep).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  app.logger.info("Intake payload received: %s", payload)
  print("Intake payload received:", payload)
  try:
    from intake_pipeline import (  # type: ignore
      IntakeValidationError,
      process_intake_submission,
    )
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft, mark_submitted  # type: ignore
    from target_market_draft import get_draft as get_target_market_draft  # type: ignore
    from people_capability_draft import get_draft as get_people_capability_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import intake pipeline: %s", exc)
    return (jsonify({"error": "server_error", "detail": "pipeline unavailable"}), 500)

  try:
    draft_id = payload.get("draft_id")
    if not draft_id or not str(draft_id).strip():
      raise IntakeValidationError({"draft_id": "draft_id is required"})

    conn = get_mysql_connection()
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
    finally:
      try:
        conn.close()
      except Exception:
        pass

    draft_status = str(draft.get("status") or "").strip().lower()
    if draft_status == "submitted":
      return (
        jsonify(
          {
            "error": "duplicate_submit",
            "detail": "This draft was already submitted.",
            "intake_submission_id": draft.get("intake_submission_id"),
          }
        ),
        409,
      )
    if draft_status != "completed":
      raise IntakeValidationError(
        {"draft_id": "Consult draft must be completed before submitting intake."}
      )

    operating_model_raw = draft.get("operating_model_json")
    if not operating_model_raw:
      raise IntakeValidationError(
        {"draft_id": "Consult draft is missing operating_model_json."}
      )
    try:
      operating_model = json.loads(str(operating_model_raw))
    except Exception as exc:
      raise IntakeValidationError(
        {"draft_id": "operating_model_json is invalid JSON."}
      ) from exc
    if not isinstance(operating_model, dict):
      raise IntakeValidationError(
        {"draft_id": "operating_model_json must be a JSON object."}
      )

    consumer_type = str(operating_model.get("consumer_type") or "").strip().lower()
    if consumer_type not in ("consumer", "b2b", "mixed"):
      consumer_type = "consumer"

    # Require the target market consult to be completed as well.
    conn = get_mysql_connection()
    try:
      try:
        tm_draft = get_target_market_draft(conn, draft_id=str(draft_id).strip())
      except Exception as exc:
        raise IntakeValidationError(
          {"draft_id": "Target market consult must be started and completed before submitting intake."}
        ) from exc
    finally:
      try:
        conn.close()
      except Exception:
        pass
    tm_status = str(tm_draft.get("status") or "").strip().lower()
    if tm_status != "completed":
      raise IntakeValidationError(
        {"draft_id": "Target market consult must be completed before submitting intake."}
      )
    tm_raw = tm_draft.get("target_market_json")
    if not tm_raw:
      raise IntakeValidationError(
        {"draft_id": "Target market consult is missing target_market_json."}
      )
    try:
      tm_obj = json.loads(str(tm_raw))
    except Exception as exc:
      raise IntakeValidationError(
        {"draft_id": "target_market_json is invalid JSON."}
      ) from exc
    if not isinstance(tm_obj, dict):
      raise IntakeValidationError(
        {"draft_id": "target_market_json must be a JSON object."}
      )

    target_market_summary = str(tm_obj.get("target_market_summary") or "").strip()
    if not target_market_summary:
      raise IntakeValidationError(
        {"draft_id": "Target market consult is missing target_market_summary."}
      )

    target_market_csv: str = ""
    if consumer_type in ("consumer", "mixed"):
      # Flatten ACS codes across segments to a CSV for intake_submissions.target_market.
      codes: List[str] = []
      selections = tm_obj.get("selections")
      if isinstance(selections, list):
        for sel in selections:
          if not isinstance(sel, dict):
            continue
          acs = sel.get("acs_codes")
          if isinstance(acs, list):
            for code in acs:
              code_str = str(code).strip()
              if code_str and code_str not in codes:
                codes.append(code_str)
      target_market_csv = ",".join(codes)
      if not target_market_csv:
        raise IntakeValidationError(
          {"draft_id": "Target market consult did not produce any ACS codes."}
        )

    b2b_industry = str(tm_obj.get("target_market_b2b_industry") or "").strip()
    b2b_size = str(tm_obj.get("target_market_b2b_size") or "").strip()
    b2b_age = str(tm_obj.get("target_market_b2b_age") or "").strip()
    if consumer_type in ("b2b", "mixed"):
      if not b2b_industry:
        raise IntakeValidationError(
          {"draft_id": "Target market consult is missing target_market_b2b_industry."}
        )
      if not b2b_size:
        raise IntakeValidationError(
          {"draft_id": "Target market consult is missing target_market_b2b_size."}
        )
      if not b2b_age:
        raise IntakeValidationError(
          {"draft_id": "Target market consult is missing target_market_b2b_age."}
        )

    # Require the People & Capability consult to be completed as well.
    conn = get_mysql_connection()
    try:
      try:
        pc_draft = get_people_capability_draft(conn, draft_id=str(draft_id).strip())
      except Exception as exc:
        raise IntakeValidationError(
          {"draft_id": "People & Capability consult must be started and completed before submitting intake."}
        ) from exc
    finally:
      try:
        conn.close()
      except Exception:
        pass

    pc_status = str(pc_draft.get("status") or "").strip().lower()
    if pc_status != "completed":
      raise IntakeValidationError(
        {"draft_id": "People & Capability consult must be completed before submitting intake."}
      )
    pc_raw = pc_draft.get("people_json")
    if not pc_raw:
      raise IntakeValidationError(
        {"draft_id": "People & Capability consult is missing people_json."}
      )
    try:
      pc_obj = json.loads(str(pc_raw))
    except Exception as exc:
      raise IntakeValidationError(
        {"draft_id": "people_json is invalid JSON."}
      ) from exc
    if not isinstance(pc_obj, dict):
      raise IntakeValidationError(
        {"draft_id": "people_json must be a JSON object."}
      )

    key_people_summary = str(pc_obj.get("key_people_summary") or "").strip()
    if not key_people_summary:
      raise IntakeValidationError(
        {"draft_id": "People & Capability consult is missing key_people_summary."}
      )

    # Ensure the submission is keyed to the consult draft's client_id and model.
    # Merge operating_model as defaults only so it never overwrites client-entered values
    # (especially Financials fields like total_debt_outstanding).
    payload = dict(payload)
    payload["client_id"] = str(draft.get("client_id") or "").strip()
    for k, v in operating_model.items():
      if k not in payload or payload.get(k) in (None, ""):
        payload[k] = v
    payload["target_market"] = (target_market_csv or None)
    payload["target_market_summary"] = target_market_summary
    payload["target_market_b2b_industry"] = (b2b_industry or None)
    payload["target_market_b2b_size"] = (b2b_size or None)
    payload["target_market_b2b_age"] = (b2b_age or None)
    payload["key_people_summary"] = key_people_summary
    if "confidence" in payload:
      payload["operating_model_confidence"] = payload.pop("confidence")

    result = process_intake_submission(payload)

    intake_submission_id = result.get("intake_submission_id")
    if intake_submission_id is not None:
      conn = get_mysql_connection()
      try:
        mark_submitted(
          conn,
          draft_id=str(draft_id).strip(),
          intake_submission_id=int(intake_submission_id),
        )
      finally:
        try:
          conn.close()
        except Exception:
          pass
    return jsonify(result)
  except IntakeValidationError as exc:
    return (jsonify({"error": "invalid_request", "errors": exc.errors}), 400)
  except Exception as exc:
    app.logger.exception("Failed processing intake submission: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)
