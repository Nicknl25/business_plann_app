import json
from typing import Any, Dict


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

  try:
    from intake_consult_draft import get_draft as get_consult_draft  # type: ignore

    consult = get_consult_draft(conn, draft_id=str(draft_id).strip())
    operating_model = _parse_json_maybe(consult.get("operating_model_json"))
  except Exception:
    operating_model = {}

  try:
    from target_market_draft import get_draft as get_tm_draft  # type: ignore

    tm = get_tm_draft(conn, draft_id=str(draft_id).strip())
    target_market = _parse_json_maybe(tm.get("target_market_json"))
  except Exception:
    target_market = {}

  try:
    from people_capability_draft import get_draft as get_pc_draft  # type: ignore

    pc = get_pc_draft(conn, draft_id=str(draft_id).strip())
    people_capability = _parse_json_maybe(pc.get("people_json"))
  except Exception:
    people_capability = {}

  try:
    from financials_consult_draft import get_draft as get_fin_draft  # type: ignore

    fin = get_fin_draft(conn, draft_id=str(draft_id).strip())
    financials = _parse_json_maybe(fin.get("financials_json"))
  except Exception:
    financials = {}

  return {
    "operating_model": operating_model,
    "target_market": target_market,
    "people_capability": people_capability,
    "financials": financials,
  }

