from __future__ import annotations

from typing import Any, Dict, List


def headcount_chat_turn(*, intake_context: Dict[str, Any], conversation_messages: Any) -> Dict[str, Any]:
  try:
    from unified_intake.language import render_client_message  # type: ignore
  except Exception:
    render_client_message = None  # type: ignore

  tail = []
  try:
    if isinstance(conversation_messages, list):
      tail = conversation_messages[-10:]
  except Exception:
    tail = []

  text = ""
  if render_client_message:
    try:
      text = render_client_message(
        kind="headcount",
        context={
          "intake_context": intake_context or {},
          "messages_tail": tail,
        },
      )
    except Exception:
      text = ""
  return {"assistant_message": str(text or "").strip(), "turn_outcome": "ASK_NEXT"}
