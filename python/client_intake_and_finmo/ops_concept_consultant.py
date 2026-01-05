from __future__ import annotations

from typing import Any, Dict


def ops_concept_chat_turn(*, intake_context: Dict[str, Any], conversation_messages: Any) -> Dict[str, Any]:
  """
  Lightweight wrapper: the controller generates deterministic proposals and stores them.
  This function only provides the natural-language framing and asks the user to use Accept/Edit.
  """
  ctx = intake_context if isinstance(intake_context, dict) else {}
  ops_concept_card = ctx.get("ops_concept_card")
  suggestion = ctx.get("ops_concept_suggestion")

  def _card_has_any_drivers(card: Dict[str, Any]) -> bool:
    try:
      lobs = card.get("lobs")
      if not isinstance(lobs, list):
        return False
      for lob in lobs:
        if not isinstance(lob, dict):
          continue
        drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
        if any(isinstance(v, dict) and v.get("value") not in (None, "", [], {}) for v in drivers.values()):
          return True
    except Exception:
      return False
    return False

  def _pick_fields_from_lob(lob: Dict[str, Any]) -> Dict[str, str]:
    drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}

    def _v(key: str) -> str:
      item = drivers.get(key)
      val = item.get("value") if isinstance(item, dict) else None
      return str(val or "").strip()

    return {
      "operating_unit": _v("operating_unit"),
      "primary_constraint": _v("primary_constraint"),
      "process_overview": _v("process_overview"),
    }

  parts = [
    "Now I'm going to propose a concise operating concept so the day-to-day reality is explicit (without a long summary paragraph).",
    "Use the buttons to Accept or Edit the operating concept drivers.",
  ]

  if isinstance(ops_concept_card, dict) and _card_has_any_drivers(ops_concept_card):
    lobs = ops_concept_card.get("lobs")
    if isinstance(lobs, list) and lobs:
      user_lobs = [
        l
        for l in lobs
        if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
      ]
      targets = user_lobs if user_lobs else [l for l in lobs if isinstance(l, dict)]
      for lob in targets[:4]:
        title = str(lob.get("lob_name") or lob.get("lob_key") or "").strip() or "Operating concept"
        fields = _pick_fields_from_lob(lob)
        lines = [f"{title}:"]
        if fields["operating_unit"]:
          lines.append(f"- Operating unit: {fields['operating_unit']}")
        if fields["primary_constraint"]:
          lines.append(f"- Primary constraint: {fields['primary_constraint']}")
        if fields["process_overview"]:
          lines.append(f"- Process overview: {fields['process_overview']}")
        parts.insert(1, "\n".join(lines))
    return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}

  if isinstance(suggestion, dict):
    unit = str(suggestion.get("operating_unit") or "").strip()
    constraint = str(suggestion.get("primary_constraint") or "").strip()
    overview = str(suggestion.get("process_overview") or "").strip()
    basis = str(suggestion.get("basis") or "").strip()
    lines = ["Proposed operating concept:"]
    if unit:
      lines.append(f"- Operating unit: {unit}")
    if constraint:
      lines.append(f"- Primary constraint: {constraint}")
    if overview:
      lines.append(f"- Process overview: {overview}")
    if basis:
      lines.append(f"- Why this fits: {basis}")
    parts.insert(1, "\n".join(lines))

  return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}

