from __future__ import annotations

from typing import Any, Dict, List


def headcount_chat_turn(*, intake_context: Dict[str, Any], conversation_messages: Any) -> Dict[str, Any]:
  """
  Lightweight wrapper: the controller generates deterministic proposals and stores them.
  This function only provides the natural-language framing and asks the user to use Accept/Edit/Add.
  """
  suggestions = intake_context.get("headcount_suggestions") if isinstance(intake_context, dict) else None
  if not isinstance(suggestions, list):
    suggestions = []

  parts: List[str] = []
  parts.append(
    "I'm going to propose a simple Year-1 headcount plan so we can sanity-check staffing cost and keep the Year-1 picture coherent.\n\n"
    "Use the buttons to Accept or Edit. You won't need to invent job-market pay rates - those are inferred from your industry (NAICS) and your state, "
    "and clearly labeled as assumptions when needed."
  )

  def _fmt_role(role: Dict[str, Any]) -> str:
    title = str(role.get("role_title") or "").strip()
    employee_count = role.get("employee_count")
    hourly_rate = role.get("hourly_rate")
    hours_per_week = role.get("hours_per_week")
    weeks_per_year = role.get("weeks_per_year")
    annual_total = role.get("annual_total_wage")
    hourly_rate_source = str(role.get("hourly_rate_source") or "").strip()
    hourly_rate_basis = str(role.get("hourly_rate_basis") or "").strip()
    match_score = role.get("match_score")

    bits: List[str] = []
    if title:
      bits.append(title)
    if employee_count is not None:
      bits.append(f"x{employee_count}")
    if hourly_rate is not None:
      try:
        bits.append(f"${float(hourly_rate):.2f}/hr")
      except Exception:
        bits.append(f"{hourly_rate}/hr")
    if hours_per_week is not None and weeks_per_year is not None:
      bits.append(f"{hours_per_week}h/wk x {weeks_per_year}w/yr")
    if annual_total is not None:
      try:
        bits.append(f"-> ${float(annual_total):,.0f}/yr")
      except Exception:
        bits.append(f"-> {annual_total}/yr")

    if hourly_rate_source in (
      "gpt_fallback",
      "dataset_average_state_naics",
      "dataset_average_state",
      "default_assumption",
    ):
      bits.append("rate: assumed")
    elif hourly_rate_source == "dataset":
      try:
        if match_score is not None:
          bits.append(f"match {float(match_score):.2f}")
      except Exception:
        pass
    if hourly_rate_basis:
      bits.append(hourly_rate_basis)

    return " | ".join([b for b in bits if str(b).strip()])

  for suggestion in suggestions:
    if not isinstance(suggestion, dict):
      continue
    lob_name = str(suggestion.get("lob_name") or "").strip()
    lob_key = str(suggestion.get("lob_key") or "").strip()
    label = lob_name or (lob_key if lob_key and lob_key != "company_total" else "")
    basis = str(suggestion.get("basis") or "").strip()
    roles = suggestion.get("roles_enriched")
    if not isinstance(roles, list):
      roles = []

    header = f"Proposed headcount plan{f' ({label})' if label else ''}:"
    lines: List[str] = []
    for role in roles[:12]:
      if not isinstance(role, dict):
        continue
      line = _fmt_role(role)
      if line:
        lines.append(f"- {line}")
    if lines:
      parts.append(f"{header}\n" + "\n".join(lines))
    else:
      parts.append(f"{header}\n- No hires assumed in Year 1 (edit if you plan to hire).")

    if basis:
      parts.append(f"Why this is a reasonable starting point: {basis}")

    y1 = suggestion.get("year1_payroll")
    if y1 is not None:
      try:
        parts.append(f"Estimated Year-1 payroll: ${float(y1):,.0f}")
      except Exception:
        parts.append(f"Estimated Year-1 payroll: {y1}")

  return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}
