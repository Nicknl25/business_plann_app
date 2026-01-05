from __future__ import annotations

from typing import Any, Dict


def revenue_chat_turn(*, intake_context: Dict[str, Any], conversation_messages: Any) -> Dict[str, Any]:
  """
  Lightweight wrapper: the controller generates deterministic proposals and stores them.
  This function only provides the natural-language framing and asks the user to use Accept/Edit.
  """
  ctx = intake_context if isinstance(intake_context, dict) else {}
  revenue_card = ctx.get("revenue_card")
  suggestion = ctx.get("revenue_suggestion")

  unit_name = str(ctx.get("unit_name") or "").strip() or "units"
  unit_singular = unit_name.rstrip("s") or unit_name

  def _as_float(v: Any) -> float | None:
    if v is None:
      return None
    if isinstance(v, (int, float)):
      return float(v)
    raw = str(v).strip().replace(",", "").replace("$", "")
    if not raw:
      return None
    try:
      return float(raw)
    except Exception:
      return None

  def _value(drivers: Dict[str, Any], key: str) -> Any:
    item = drivers.get(key)
    return item.get("value") if isinstance(item, dict) else None

  def _summarize_one(*, title: str, drivers: Dict[str, Any]) -> str:
    capacity = _as_float(_value(drivers, "units_per_week_capacity"))
    avg_units = _as_float(_value(drivers, "avg_units_per_week_year1"))
    util = _as_float(_value(drivers, "utilization_rate"))
    if avg_units is None and util is not None and capacity is not None:
      avg_units = float(util) * float(capacity)
    weeks = _as_float(_value(drivers, "operating_weeks_per_year")) or 52.0
    unit_price = _as_float(_value(drivers, "unit_price"))

    weekly_rev = (avg_units * unit_price) if (avg_units is not None and unit_price is not None) else None
    year1_rev = (weekly_rev * weeks) if (weekly_rev is not None and weeks is not None) else None

    lines = [f"{title}:"]
    if capacity is not None:
      lines.append(f"- Busy-week capacity: {capacity:,.0f} {unit_name}/week")
    if avg_units is not None:
      lines.append(f"- Year-1 average volume: {avg_units:,.0f} {unit_name}/week")
    if util is not None:
      lines.append(f"- Utilization: {util * 100:,.0f}%")
    if unit_price is not None:
      lines.append(f"- Revenue per {unit_singular}: ${unit_price:,.0f}")
    if weeks is not None:
      lines.append(f"- Operating weeks/year: {weeks:,.0f}")

    if weekly_rev is not None and year1_rev is not None:
      lines.append("Math:")
      lines.append(f"- Weekly revenue: {avg_units:,.0f} x ${unit_price:,.0f} = ${weekly_rev:,.0f}/week")
      lines.append(f"- Year-1 revenue: ${weekly_rev:,.0f} x {weeks:,.0f} = ${year1_rev:,.0f}")
    return "\n".join(lines)

  parts = [
    "I'm going to propose a simple Year-1 revenue model so we can sanity-check the Year-1 picture.",
    "You won't need to invent numbers from scratch - you can Accept or Edit the assumptions (edits recompute immediately).",
  ]

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

  # Preferred path: render from the persisted revenue model card (trust surface),
  # but fall back to the proposal suggestion if the card is still empty.
  if isinstance(revenue_card, dict) and _card_has_any_drivers(revenue_card):
    lobs = revenue_card.get("lobs")
    if isinstance(lobs, list) and lobs:
      user_lobs = [
        l
        for l in lobs
        if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
      ]
      targets = user_lobs if user_lobs else [l for l in lobs if isinstance(l, dict)]
      if len(targets) > 1:
        for lob in targets:
          title = str(lob.get("lob_name") or lob.get("lob_key") or "").strip() or "Line of business"
          drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
          parts.append(_summarize_one(title=title, drivers=drivers))
      elif targets:
        lob = targets[0]
        drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
        parts.append(_summarize_one(title="Assumptions", drivers=drivers))
    parts.append("Use the buttons to Accept or Edit the revenue model drivers.")
    return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}

  # Fallback: render from a proposer suggestion (first-time proposal).
  if isinstance(suggestion, dict):
    drivers = {
      "units_per_week_capacity": {"value": suggestion.get("units_per_week_capacity")},
      "avg_units_per_week_year1": {"value": suggestion.get("avg_units_per_week_year1")},
      "operating_weeks_per_year": {"value": suggestion.get("operating_weeks_per_year")},
      "unit_price": {"value": suggestion.get("unit_price")},
    }
    parts.append(_summarize_one(title="Assumptions", drivers=drivers))

  parts.append("Use the buttons to Accept or Edit the revenue model assumptions.")
  return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}
