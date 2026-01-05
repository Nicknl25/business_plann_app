import json
from typing import Any, Dict

from flask import jsonify


def _parse_json_maybe(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def build_shared_context(conn, *, draft_id: str) -> Dict[str, Any]:
  """
  Load the latest finalized outputs from each consult draft table and return them as
  a single shared, read-only context object.

  This is intentionally conservative: if a draft row or JSON blob is missing, the
  corresponding value is an empty dict.
  """
  operating_model: Dict[str, Any] = {}
  target_market: Dict[str, Any] = {}
  people_capability: Dict[str, Any] = {}
  financials: Dict[str, Any] = {}
  model_cards: Dict[str, Any] = {}

  # Preferred: unified draft table (single canonical model).
  try:
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore

    consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
    operating_model = _parse_json_maybe(consult.get("operating_model_json"))
    target_market = _parse_json_maybe(consult.get("target_market_json"))
    people_capability = _parse_json_maybe(consult.get("people_json"))
    financials = _parse_json_maybe(consult.get("financials_json"))
    model_cards = {
      "ops_concept": _parse_json_maybe(consult.get("ops_concept_model_json")),
      "fulfillment": _parse_json_maybe(consult.get("fulfillment_model_json")),
      "marketing": _parse_json_maybe(consult.get("marketing_model_json")),
      "pricing": _parse_json_maybe(consult.get("pricing_model_json")),
      "headcount": _parse_json_maybe(consult.get("headcount_model_json")),
      "year1_rollups": {
        "year1_revenue": consult.get("year1_revenue"),
        "year1_marketing_spend": consult.get("year1_marketing_spend"),
        "year1_payroll": consult.get("year1_payroll"),
      },
      "proposals": consult.get("model_card_proposals_json"),
    }
  except Exception:
    # Fall back to legacy per-consult drafts below.
    operating_model = {}
    target_market = {}
    people_capability = {}
    financials = {}
    model_cards = {}

  try:
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore

    consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
    # Legacy fallback: operating_model_json is still stored in intake_consult_drafts.
    if not operating_model:
      operating_model = _parse_json_maybe(consult.get("operating_model_json"))
  except Exception:
    operating_model = {}

  try:
    from target_market_draft import get_draft as get_tm_draft  # type: ignore

    tm = get_tm_draft(conn, draft_id=str(draft_id).strip())
    if not target_market:
      target_market = _parse_json_maybe(tm.get("target_market_json"))
  except Exception:
    target_market = {}

  try:
    from people_capability_draft import get_draft as get_pc_draft  # type: ignore

    pc = get_pc_draft(conn, draft_id=str(draft_id).strip())
    if not people_capability:
      people_capability = _parse_json_maybe(pc.get("people_json"))
  except Exception:
    people_capability = {}

  try:
    from financials_consult_draft import get_draft as get_fin_draft  # type: ignore

    fin = get_fin_draft(conn, draft_id=str(draft_id).strip())
    if not financials:
      financials = _parse_json_maybe(fin.get("financials_json"))
  except Exception:
    financials = {}

  return {
    "operating_model": operating_model,
    "target_market": target_market,
    "people_capability": people_capability,
    "financials": financials,
    "model_cards": model_cards,
  }


def get_shared_context_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  draft_id = request.args.get("draft_id")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helper: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft_id).strip(),
        "shared_context": shared_context,
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass
