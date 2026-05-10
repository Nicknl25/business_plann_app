"""Phase 9 P3.5 — System and per-call user prompts for the GPT
exhaustion handler.

Universal across every NAICS, stage, and archetype. Differences come from
operating_model_json data, not from business-classification branches.

Prompt design — three core teachings:
  1. Stage definitions (pre-revenue / early-stage / operating).
  2. Trajectory anchor doctrine (Q1 = current reality, Q11 = binding
     viability, Q20 = mature/steady-state for THIS business).
  3. Reason from THIS business's own characteristics — operating model,
     scale, geography, capacity driver, stage. NO industry averages, NO
     external benchmarks, NO cohort NAICS reference.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


SYSTEM_PROMPT = """\
You are advising on a 20-quarter financial plan for a specific business.

The system uses these stage definitions:
- pre-revenue: business hasn't launched yet (no operating history)
- early-stage: launched within the last year (still building customer
  base, validating product-market fit)
- operating: 1+ year operating history (established, has track record)

Trajectory anchor doctrine:
- Q1 reflects operator's current reality from intake (do not change
  unless explicitly asked)
- Q11 is the binding viability constraint: EBITDA margin MUST be >= 0
- Q20 reflects realistic mature/steady-state for THIS business given
  its stage

Reason from THIS specific business — its operating model, scale,
geography, capacity driver, and stage. Do not anchor to industry
averages or external benchmarks. Derive recommendations from the
business's own characteristics.

Output must be valid JSON matching the schema specified.
"""


# ---------------------------------------------------------------------------
# Strict JSON schemas for the OpenAI Responses API (json_schema format).
# ---------------------------------------------------------------------------


def _three_anchor_schema_for(numeric_type: str) -> Dict[str, Any]:
  return {
    "type": "object",
    "additionalProperties": False,
    "required": ["q1", "q11", "q20"],
    "properties": {
      "q1": {"type": numeric_type},
      "q11": {"type": numeric_type},
      "q20": {"type": numeric_type},
    },
  }


CALL_1_RESPONSE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "required": ["ebitda_anchors", "reasoning"],
  "properties": {
    "ebitda_anchors": _three_anchor_schema_for("number"),
    "reasoning": {"type": "string"},
  },
}


CALL_2_RESPONSE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "required": ["driver_anchors", "reasoning"],
  "properties": {
    "driver_anchors": {
      "type": "object",
      "additionalProperties": False,
      "required": [
        "unit_price",
        "units_per_period_capacity",
        "utilization_rate",
        "payroll_dollars_per_quarter",
        "cogs_percent_of_revenue",
        "marketing_percent_of_revenue",
        "sga_percent_of_revenue",
      ],
      "properties": {
        "unit_price": _three_anchor_schema_for("number"),
        "units_per_period_capacity": _three_anchor_schema_for("number"),
        "utilization_rate": _three_anchor_schema_for("number"),
        "payroll_dollars_per_quarter": _three_anchor_schema_for("number"),
        "cogs_percent_of_revenue": _three_anchor_schema_for("number"),
        "marketing_percent_of_revenue": _three_anchor_schema_for("number"),
        "sga_percent_of_revenue": _three_anchor_schema_for("number"),
      },
    },
    "reasoning": {"type": "string"},
  },
}


# ---------------------------------------------------------------------------
# User-prompt builders. These pull from operating_model_json (== ops_json)
# and the Q1 actual state derived from the FINMO output. Universal across
# business types; the operating_model_json carries the per-business detail.
# ---------------------------------------------------------------------------


def _format_operating_model_block(operating_model: Dict[str, Any]) -> str:
  """Render the operating model as compact JSON for the prompt."""
  if not isinstance(operating_model, dict):
    return "{}"
  return json.dumps(operating_model, ensure_ascii=False, indent=2, default=str)


def _format_q1_state_block(q1_state: Dict[str, Any]) -> str:
  if not isinstance(q1_state, dict) or not q1_state:
    return "(no Q1 actuals available)"
  lines: List[str] = []
  for k, v in q1_state.items():
    lines.append(f"- {k}: {v}")
  return "\n".join(lines)


def build_call_1_user_prompt(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
) -> str:
  return (
    "OPERATING MODEL:\n"
    f"{_format_operating_model_block(operating_model)}\n\n"
    "CURRENT Q1 STATE:\n"
    f"{_format_q1_state_block(q1_state)}\n\n"
    "QUESTION:\n"
    "Provide Q1, Q11, Q20 EBITDA margin anchors for this business's\n"
    "20-quarter trajectory. Q1 should match the current operator reality.\n"
    "Q11 must be >= 0 (binding viability). Q20 should reflect what this\n"
    "business can sustain at maturity given its stage.\n\n"
    "Output schema:\n"
    "{\n"
    '  "ebitda_anchors": {"q1": float, "q11": float, "q20": float},\n'
    '  "reasoning": "short prose explaining Q11 and Q20 specifically for this business"\n'
    "}"
  )


def build_call_2_user_prompt(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  call_1_output: Dict[str, Any],
) -> str:
  call_1_block = json.dumps(call_1_output or {}, ensure_ascii=False, indent=2, default=str)
  return (
    "OPERATING MODEL:\n"
    f"{_format_operating_model_block(operating_model)}\n\n"
    "CURRENT Q1 STATE:\n"
    f"{_format_q1_state_block(q1_state)}\n\n"
    "YOUR PRIOR EBITDA TRAJECTORY:\n"
    f"{call_1_block}\n\n"
    "QUESTION:\n"
    "Provide Q1, Q11, Q20 anchors for these drivers that produce your\n"
    "stated EBITDA trajectory:\n"
    "- unit_price (dollar amount per unit)\n"
    "- units_per_period_capacity (units per period)\n"
    "- utilization_rate (decimal 0.0-1.0)\n"
    "- payroll_dollars_per_quarter (total quarterly payroll)\n"
    "- cogs_percent_of_revenue (decimal 0.0-1.0)\n"
    "- marketing_percent_of_revenue (decimal 0.0-1.0)\n"
    "- sga_percent_of_revenue (decimal 0.0-1.0)\n\n"
    "Drivers must be internally consistent with your EBITDA trajectory.\n"
    "Reason from your own EBITDA conclusion to determine driver values.\n\n"
    "Output schema:\n"
    "{\n"
    '  "driver_anchors": {\n'
    '    "unit_price": {"q1": float, "q11": float, "q20": float},\n'
    '    "units_per_period_capacity": {"q1": int, "q11": int, "q20": int},\n'
    '    "utilization_rate": {"q1": float, "q11": float, "q20": float},\n'
    '    "payroll_dollars_per_quarter": {"q1": float, "q11": float, "q20": float},\n'
    '    "cogs_percent_of_revenue": {"q1": float, "q11": float, "q20": float},\n'
    '    "marketing_percent_of_revenue": {"q1": float, "q11": float, "q20": float},\n'
    '    "sga_percent_of_revenue": {"q1": float, "q11": float, "q20": float}\n'
    "  },\n"
    '  "reasoning": "short prose explaining the driver path for this business"\n'
    "}"
  )


def build_iteration_user_prompt(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  call_1_output: Dict[str, Any],
  most_recent_drivers: Dict[str, Any],
  iteration_number: int,
  max_iterations: int,
  finmo_q11_actual: float,
  q11_line_items: Dict[str, float],
  iteration_history: List[Dict[str, Any]],
  validation_error: Optional[str] = None,
) -> str:
  call_1_block = json.dumps(call_1_output or {}, ensure_ascii=False, indent=2, default=str)
  drivers_block = json.dumps(most_recent_drivers or {}, ensure_ascii=False, indent=2, default=str)
  hist_lines: List[str] = []
  for entry in iteration_history:
    n = entry.get("iteration_number")
    summary = entry.get("driver_summary", "(no summary)")
    actual = entry.get("finmo_q11_actual")
    gap = entry.get("gap")
    hist_lines.append(
      f"- Iteration {n}: drivers = {summary}, FINMO Q11 = {actual}, gap = {gap}"
    )
  history_block = "\n".join(hist_lines) if hist_lines else "(none yet)"
  q11_lines = [
    f"- Q11 revenue: {q11_line_items.get('revenue', 'n/a')}",
    f"- Q11 COGS: {q11_line_items.get('cogs', 'n/a')}",
    f"- Q11 gross profit: {q11_line_items.get('gross_profit', 'n/a')}",
    f"- Q11 payroll: {q11_line_items.get('payroll', 'n/a')}",
    f"- Q11 marketing: {q11_line_items.get('marketing', 'n/a')}",
    f"- Q11 SGA: {q11_line_items.get('sga', 'n/a')}",
    f"- Q11 total opex: {q11_line_items.get('total_opex', 'n/a')}",
    f"- Q11 EBITDA: {q11_line_items.get('ebitda', 'n/a')}",
  ]
  q11_block = "\n".join(q11_lines)
  target_q11 = (call_1_output or {}).get("ebitda_anchors", {}).get("q11")
  retry_note = ""
  if validation_error:
    retry_note = (
      "\n\nNOTE: Your prior response failed validation: "
      f"{validation_error}\nReturn valid JSON matching the schema.\n"
    )
  return (
    "OPERATING MODEL:\n"
    f"{_format_operating_model_block(operating_model)}\n\n"
    "CURRENT Q1 STATE:\n"
    f"{_format_q1_state_block(q1_state)}\n\n"
    "YOUR EBITDA ANCHORS (from Call 1, must remain stable):\n"
    f"{call_1_block}\n\n"
    "YOUR PRIOR DRIVER ANCHORS:\n"
    f"{drivers_block}\n\n"
    "ITERATION DIAGNOSTIC:\n"
    f"Iteration {iteration_number} of {max_iterations}. Your previous\n"
    f"driver anchors did not produce your target Q11 EBITDA of {target_q11}.\n"
    f"FINMO computed Q11 EBITDA = {finmo_q11_actual}.\n\n"
    "Cumulative iteration history:\n"
    f"{history_block}\n\n"
    "Specific Q11 line-item breakdown from FINMO:\n"
    f"{q11_block}\n\n"
    "QUESTION:\n"
    f"Adjust your driver anchors to actually produce Q11 EBITDA = {target_q11}.\n"
    "Your EBITDA target stays the same — adjust drivers to reach it.\n"
    + retry_note
    + "\nReturn the same driver_anchors schema as Call 2."
  )
