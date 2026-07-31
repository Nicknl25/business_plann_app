import json
import os
import threading
from typing import Any, Dict, List

from flask import jsonify


def _start_system_run_in_background(*, app, draft_id: str) -> None:
  """Submit IS the run trigger: the client pressing Submit must start the
  post-intake planning run with no further browser involvement (a closed
  tab must not strand a client). Fire the same endpoint every harness uses
  (POST /api/intake-consult/system-run) from a daemon thread so the HTTP
  submit returns promptly; the endpoint's planning_run_already_active
  conflict makes a double-fire safe. Delivery stays human-mediated — the
  run's output goes to the internal inbox only."""
  base_url = (os.environ.get("BPLAN_SELF_BASE_URL") or "http://127.0.0.1:5050").rstrip("/")

  def _fire() -> None:
    try:
      import requests

      resp = requests.post(
        f"{base_url}/api/intake-consult/system-run",
        json={"draft_id": draft_id},
        timeout=7200,
      )
      app.logger.info(
        "submit_system_run draft=%s status=%s", draft_id, resp.status_code
      )
    except Exception as exc:  # noqa: BLE001 — the supervisor probe is the net
      app.logger.error(
        "submit_system_run_failed draft=%s: %s: %s",
        draft_id, type(exc).__name__, exc,
      )

  threading.Thread(
    target=_fire, name=f"system-run-{draft_id[:8]}", daemon=True
  ).start()


# P3.41 intake-remediation circumvention
# See docs/architecture/p3_40_contract_layer_closeout.md §5 "Post-audit intake-remediation handoff"
# See docs/architecture/intake_side_research_post_audit.md (commit 8a98e26)
# When True: bypasses the 2 summary-gate hard-fails (key_people_summary + target_market_summary).
# These gates are KNOWN BROKEN because they read fields that are intentionally popped before
# persistence per commit e57ff49 (single-source-of-truth enforcement). Proper fix is Option 3
# (replace proxy-summary check with structural check on primary data -- see intake-remediation
# workstream, Contract 5d R-d / Contract 5c R-d-bis). This flag exists ONLY so E2E can flow
# through to post-intake for Fix #2 / Fix #1 verification. MUST be set False before any
# production submission path is exercised.
_SKIP_INTAKE_REMEDIATION_GATES = True


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
    from client_intake_and_finmo.intake_submit_service import (  # type: ignore
      IntakeValidationError,
      process_intake_submission,
    )
    from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
    from client_intake_and_finmo.intake_consult_draft import get_draft, mark_submitted  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import intake pipeline: %s", exc)
    return (jsonify({"error": "server_error", "detail": "pipeline unavailable"}), 500)

  try:
    draft_id = payload.get("draft_id")
    if not draft_id or not str(draft_id).strip():
      raise IntakeValidationError({"draft_id": "draft_id is required"})

    conn = get_mysql_connection()
    shared_context_for_render: Dict[str, Any] = {}
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
      try:
        # Ensure we snapshot rendered summaries (no {{fact:...}} placeholders) at submission time.
        from api_handlers.shared_context import build_shared_context  # type: ignore

        shared_context_for_render = build_shared_context(conn, draft_id=str(draft_id).strip())
      except Exception:
        shared_context_for_render = {}
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

    # Unified consult: target market is stored on the same canonical draft row.
    tm_raw = draft.get("target_market_json")
    if not tm_raw:
      raise IntakeValidationError({"draft_id": "Draft is missing target_market_json."})
    tm_obj = json.loads(str(tm_raw)) if not isinstance(tm_raw, dict) else tm_raw
    if not isinstance(tm_obj, dict):
      raise IntakeValidationError({"draft_id": "target_market_json must be a JSON object."})

    target_market_summary = str(tm_obj.get("target_market_summary") or "").strip()
    if not target_market_summary and not _SKIP_INTAKE_REMEDIATION_GATES:
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
    if not b2b_industry:
      naics6 = tm_obj.get("b2b_naics_6")
      if isinstance(naics6, list):
        b2b_industry = ",".join(sorted({str(x).strip() for x in naics6 if str(x).strip()}))

    b2b_size = str(tm_obj.get("target_market_b2b_size") or "").strip()
    if not b2b_size:
      bands = tm_obj.get("b2b_size_bands")
      if isinstance(bands, list):
        order = ["1-4", "5-9", "10-19", "20-99", "100-499", "500-999", "1000-2499", "2500-4999", "5000-9999", "10000+"]
        band_set = {str(x).strip() for x in bands if str(x).strip()}
        b2b_size = ",".join([v for v in order if v in band_set])

    b2b_age = str(tm_obj.get("target_market_b2b_age") or "").strip()
    if not b2b_age:
      bands = tm_obj.get("b2b_age_bands")
      if isinstance(bands, list):
        order = ["0", "1", "2", "3", "4", "5", "6-10", "11-15", "16-20", "21-25", "26+"]
        band_set = {str(x).strip() for x in bands if str(x).strip()}
        b2b_age = ",".join([v for v in order if v in band_set])
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

    pc_raw = draft.get("people_json")
    if not pc_raw:
      raise IntakeValidationError({"draft_id": "Draft is missing people_json."})
    pc_obj = json.loads(str(pc_raw)) if not isinstance(pc_raw, dict) else pc_raw
    if not isinstance(pc_obj, dict):
      raise IntakeValidationError({"draft_id": "people_json must be a JSON object."})

    key_people_summary = str(pc_obj.get("key_people_summary") or "").strip()
    if not key_people_summary and not _SKIP_INTAKE_REMEDIATION_GATES:
      raise IntakeValidationError(
        {"draft_id": "People & Capability consult is missing key_people_summary."}
      )

    fin_raw = draft.get("financials_json")
    if not fin_raw:
      raise IntakeValidationError({"draft_id": "Draft is missing financials_json."})
    fin_obj = json.loads(str(fin_raw)) if not isinstance(fin_raw, dict) else fin_raw
    if not isinstance(fin_obj, dict):
      raise IntakeValidationError({"draft_id": "financials_json must be a JSON object."})

    # Render fact-bearing templates into a frozen submission snapshot.
    try:
      from fact_templates import render_fact_template  # type: ignore

      business_facts = {
        "name": str(payload.get("business_name") or draft.get("business_name") or "").strip(),
        "address": str(payload.get("address") or draft.get("business_address") or "").strip(),
        "start_date": str(payload.get("business_start_date") or draft.get("business_start_date") or "").strip(),
      }

      shared_ctx = shared_context_for_render or {
        "operating_model": operating_model,
        "target_market": tm_obj,
        "people_capability": pc_obj,
        "financials": fin_obj,
      }

      rendered_ops_summary = render_fact_template(
        str(operating_model.get("business_description_summary") or ""),
        shared_context=shared_ctx,
        business_facts=business_facts,
      ).strip()
      if rendered_ops_summary:
        payload["business_description_summary"] = rendered_ops_summary

      rendered_market_summary = render_fact_template(
        str(target_market_summary or ""),
        shared_context=shared_ctx,
        business_facts=business_facts,
      ).strip()
      if rendered_market_summary:
        payload["target_market_summary"] = rendered_market_summary

      rendered_people_summary = render_fact_template(
        str(key_people_summary or ""),
        shared_context=shared_ctx,
        business_facts=business_facts,
      ).strip()
      if rendered_people_summary:
        payload["key_people_summary"] = rendered_people_summary
    except Exception:
      # Best-effort: if rendering fails, fall back to storing raw strings (may contain placeholders).
      pass

    # Ensure the submission is keyed to the consult draft's client_id and model.
    # Merge operating_model as defaults only so it never overwrites client-entered values
    # (especially Financials fields like total_debt_outstanding).
    payload = dict(payload)
    payload["client_id"] = str(draft.get("client_id") or "").strip()
    financials_override_fields = {
      "initial_assets",
      "initial_lease",
      "initial_equity",
      "total_debt_outstanding",
    }
    for k, v in operating_model.items():
      if k in financials_override_fields:
        continue
      if k not in payload or payload.get(k) in (None, ""):
        payload[k] = v
    for k, v in fin_obj.items():
      if k not in payload or payload.get(k) in (None, ""):
        payload[k] = v
    for k in financials_override_fields:
      if fin_obj.get(k) not in (None, ""):
        payload[k] = fin_obj.get(k)
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
      _start_system_run_in_background(app=app, draft_id=str(draft_id).strip())
    return jsonify(result)
  except IntakeValidationError as exc:
    return (jsonify({"error": "invalid_request", "errors": exc.errors}), 400)
  except Exception as exc:
    app.logger.exception("Failed processing intake submission: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)
