from __future__ import annotations

from typing import Any, Dict, List


def milestones_chat_turn(*, intake_context: Dict[str, Any], conversation_messages: Any) -> Dict[str, Any]:
  """
  Lightweight wrapper: the controller generates deterministic proposals and stores them.
  This function only provides the natural-language framing and asks the user to use Accept/Edit/Add.
  """
  suggestions = intake_context.get("milestones_suggestions") if isinstance(intake_context, dict) else None
  if not isinstance(suggestions, list):
    suggestions = []

  parts: List[str] = []
  parts.append(
    "I'm going to propose a small set of concrete milestones so we lock an execution target and keep the Year-1 picture coherent.\n\n"
    "Use the buttons to Accept, Edit, or Add milestones. You won't need to invent anything from scratch."
  )

  def _fmt_one(m: Dict[str, Any]) -> str:
    title = str(m.get("title") or "").strip()
    target = str(m.get("target_period") or "").strip()
    desc = str(m.get("description") or "").strip()
    conf = m.get("confidence")
    conf_text = ""
    try:
      conf_num = float(conf)
      conf_text = f" (confidence {conf_num:.2f})"
    except Exception:
      conf_text = ""

    if desc:
      return f"- {title} - {target}{conf_text}\n  {desc}"
    return f"- {title} - {target}{conf_text}"

  for s in suggestions:
    if not isinstance(s, dict):
      continue
    lob_name = str(s.get("lob_name") or "").strip()
    lob_key = str(s.get("lob_key") or "").strip()
    label = lob_name or (lob_key if lob_key and lob_key != "company_total" else "")
    ms = s.get("milestones")
    if not isinstance(ms, list) or not ms:
      continue
    header = f"Proposed milestones{f' ({label})' if label else ''}:"
    lines: List[str] = []
    for m in ms[:6]:
      if isinstance(m, dict):
        lines.append(_fmt_one(m))
    if lines:
      parts.append(f"{header}\n" + "\n".join(lines))

  return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}

