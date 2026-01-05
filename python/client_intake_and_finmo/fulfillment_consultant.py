from __future__ import annotations

from typing import Any, Dict


def fulfillment_chat_turn(*, intake_context: Dict[str, Any], conversation_messages: Any) -> Dict[str, Any]:
  """
  Lightweight wrapper: the controller generates deterministic proposals and stores them.
  This function only provides the natural-language framing and asks the user to use Accept/Edit.
  """
  ctx = intake_context if isinstance(intake_context, dict) else {}
  fulfillment_card = ctx.get("fulfillment_card")
  suggestion = ctx.get("fulfillment_suggestion")

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
      "fulfillment_model": _v("fulfillment_model"),
      "who_fulfills": _v("who_fulfills"),
      "lead_time": _v("lead_time"),
    }

  parts = [
    "Next I'm going to lock a simple fulfillment model (how customers receive what they buy), so the operating picture is coherent.",
    "Use the buttons to Accept or Edit the fulfillment model drivers.",
  ]

  if isinstance(fulfillment_card, dict) and _card_has_any_drivers(fulfillment_card):
    lobs = fulfillment_card.get("lobs")
    if isinstance(lobs, list) and lobs:
      user_lobs = [
        l
        for l in lobs
        if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
      ]
      targets = user_lobs if user_lobs else [l for l in lobs if isinstance(l, dict)]
      for lob in targets[:4]:
        title = str(lob.get("lob_name") or lob.get("lob_key") or "").strip() or "Fulfillment"
        fields = _pick_fields_from_lob(lob)
        lines = [f"{title}:"]
        if fields["fulfillment_model"]:
          lines.append(f"- Fulfillment model: {fields['fulfillment_model']}")
        if fields["who_fulfills"]:
          lines.append(f"- Who fulfills: {fields['who_fulfills']}")
        if fields["lead_time"]:
          lines.append(f"- Typical lead time: {fields['lead_time']}")
        parts.insert(1, "\n".join(lines))
    return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}

  if isinstance(suggestion, dict):
    model = str(suggestion.get("fulfillment_model") or "").strip()
    who = str(suggestion.get("who_fulfills") or "").strip()
    lead = str(suggestion.get("lead_time") or "").strip()
    basis = str(suggestion.get("basis") or "").strip()
    lines = ["Proposed fulfillment model:"]
    if model:
      lines.append(f"- Model: {model}")
    if who:
      lines.append(f"- Who fulfills: {who}")
    if lead:
      lines.append(f"- Typical lead time: {lead}")
    if basis:
      lines.append(f"- Why this fits: {basis}")
    parts.insert(1, "\n".join(lines))

  return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}

