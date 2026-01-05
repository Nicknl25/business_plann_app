from __future__ import annotations

from typing import Any, Dict


def marketing_chat_turn(*, intake_context: Dict[str, Any], conversation_messages: Any) -> Dict[str, Any]:
  """
  Lightweight wrapper: the controller generates deterministic proposals and stores them.
  This function only provides the natural-language framing and asks the user to use Accept/Edit.
  """
  suggestion = intake_context.get("marketing_suggestion") if isinstance(intake_context, dict) else None
  if not isinstance(suggestion, dict):
    suggestion = {}

  annual = suggestion.get("year1_marketing_spend")
  monthly = suggestion.get("monthly_marketing_budget")
  basis = str(suggestion.get("basis") or "").strip()
  channels = str(suggestion.get("primary_channels") or "").strip()

  def _as_number(val: Any) -> float | None:
    if val is None:
      return None
    if isinstance(val, (int, float)):
      return float(val)
    raw = str(val).strip()
    if not raw:
      return None
    try:
      return float(raw)
    except Exception:
      return None

  annual_num = _as_number(annual)
  monthly_num = _as_number(monthly)

  parts = []
  if annual_num is not None and monthly_num is not None:
    if annual_num == 0 and monthly_num == 0:
      parts.append(
        "I'm going to propose whether marketing spend should exist at all in Year 1, based on your industry (NAICS) and operating reality.\n\n"
        "Proposed marketing budget:\n"
        "- Year 1: $0\n"
        "- Monthly equivalent: $0\n"
      )
    else:
      parts.append(
        "I'm going to propose a simple Year-1 marketing budget so we can ground demand assumptions and sanity-check the Year-1 picture.\n\n"
        "Proposed marketing budget:\n"
        f"- Year 1: ${annual_num:,.0f}\n"
        f"- Monthly equivalent: ${monthly_num:,.0f}\n"
      )
  elif annual_num is not None:
    if annual_num == 0:
      parts.append(
        "I'm going to propose whether marketing spend should exist at all in Year 1, based on your industry (NAICS) and operating reality.\n\n"
        "Proposed marketing budget for Year 1: $0\n"
      )
    else:
      parts.append(
        "I'm going to propose a simple Year-1 marketing budget so we can ground demand assumptions and sanity-check the Year-1 picture.\n\n"
        f"Proposed marketing budget for Year 1: ${annual_num:,.0f}\n"
      )
  else:
    parts.append(
      "I'm going to propose whether marketing spend should exist at all in Year 1, based on your industry (NAICS) and operating reality."
    )

  if basis:
    parts.append(f"Why this is a reasonable starting point: {basis}")
  if channels:
    parts.append(f"Primary acquisition channels (assumption): {channels}")

  parts.append('Use the buttons to Accept or Edit the marketing budget proposal(s).')
  return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}
