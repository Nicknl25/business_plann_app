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
    "I’m going to propose a simple Year‑1 headcount plan so we can sanity‑check staffing cost and keep the Year‑1 picture coherent.\n\n"
    "Use the buttons to Accept or Edit. You won’t need to invent job-market pay rates—those are inferred from your industry (NAICS) and your state."
  )

  def _fmt_role(r: Dict[str, Any]) -> str:
    title = str(r.get("role_title") or "").strip()
    count = r.get("employee_count")
    hourly = r.get("hourly_rate")
    hours_pw = r.get("hours_per_week")
    weeks_py = r.get("weeks_per_year")
    annual_total = r.get("annual_total_wage")
    rate_source = str(r.get("hourly_rate_source") or "").strip()
    match_score = r.get("match_score")
    pieces = []
    if title:
      pieces.append(title)
    if count is not None:
      pieces.append(f"x{count}")
    if hourly is not None:
      try:
        pieces.append(f"${float(hourly):.2f}/hr")
      except Exception:
        pieces.append(f"{hourly}/hr")
    if hours_pw is not None and weeks_py is not None:
      pieces.append(f"{hours_pw}h/wk × {weeks_py}w")
    if annual_total is not None:
      try:
        pieces.append(f"≈ ${float(annual_total):,.0f}/yr")
      except Exception:
        pieces.append(f"≈ {annual_total}/yr")
    if rate_source == "gpt_fallback":
      pieces.append("rate: inferred")
    elif rate_source == "dataset":
      try:
        if match_score is not None:
          pieces.append(f"match {float(match_score):.2f}")
      except Exception:
        pass
    return " — ".join([p for p in pieces if str(p).strip()])

  for s in suggestions:
    if not isinstance(s, dict):
      continue
    lob_name = str(s.get("lob_name") or "").strip()
    lob_key = str(s.get("lob_key") or "").strip()
    label = lob_name or (lob_key if lob_key and lob_key != "company_total" else "")
    basis = str(s.get("basis") or "").strip()
    roles = s.get("roles_enriched")
    if not isinstance(roles, list) or not roles:
      continue
    header = f"Proposed headcount plan{f' ({label})' if label else ''}:"
    lines: List[str] = []
    for r in roles[:12]:
      if isinstance(r, dict):
        line = _fmt_role(r)
        if line:
          lines.append(f"- {line}")
    if lines:
      parts.append(f"{header}\n" + "\n".join(lines))
    if basis:
      parts.append(f"Why this is a reasonable starting point: {basis}")

    y1 = s.get("year1_payroll")
    if y1 is not None:
      try:
        parts.append(f"Estimated Year‑1 payroll: ${float(y1):,.0f}")
      except Exception:
        parts.append(f"Estimated Year‑1 payroll: {y1}")

  return {"assistant_message": "\n\n".join([p for p in parts if p.strip()]).strip(), "turn_outcome": "ASK_NEXT"}
