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

  parts = []
  if annual is not None and monthly is not None:
    parts.append(
      f"I'm going to propose a simple Year-1 marketing budget so we can ground demand assumptions and sanity-check the Year-1 picture.\n\n"
      f"Proposed marketing budget:\n"
      f"- Year 1: ${annual:,.0f}\n"
      f"- Monthly equivalent: ${monthly:,.0f}\n"
    )
  elif annual is not None:
    parts.append(
      "I'm going to propose a simple Year-1 marketing budget so we can ground demand assumptions and sanity-check the Year-1 picture.\n\n"
      f"Proposed marketing budget for Year 1: ${annual:,.0f}\n"
    )
  else:
    parts.append(
      "Let's set a simple Year-1 marketing budget so we can ground demand assumptions and sanity-check the Year-1 picture."
    )

  if basis:
    parts.append(f"Why this is a reasonable starting point: {basis}")
  if channels:
    parts.append(f"Primary acquisition channels (assumption): {channels}")

  parts.append('Use the buttons to Accept or Edit the marketing budget proposal(s).')
  return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}
