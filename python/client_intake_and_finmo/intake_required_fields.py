"""ONE LIST: what the ops conversation must ask IS what the submit gate may
require (Nick 2026-09-12).

Sablecreek Microgrid Systems completed its intake, converged the lender
stress test, and was refused at submit with the raw string
``primary_growth_lever: primary_growth_lever is required`` - a field the
conversation never asked about on that run. Readiness had been judged on
the consultant's proposed object; the persisted ops carried an empty
string; a fallback question for exactly this field existed and was never
asked; the validator required the result; and the client saw a field name.

This module is the single source of truth for the business-wide operating
fields a client must supply in words, the question that asks for each, and
the human name each is called by. The ops readiness check, the ops
follow-up question, the wrap guard at the hand-over to Target Market, and
the submission validator all read from here. A field cannot be required
without a question, and a question cannot exist without a name.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping


# Order matters: it is the order the follow-up questions are asked in.
OPS_BUSINESS_WIDE_REQUIRED = (
  "shipping_method",
  "sales_modality",
  "geographic_scope",
  "geographic_coverage",
  "countries",
  "capacity_driver",
  "primary_growth_lever",
  "legal_entity",
)

# How a client hears each field. A client never sees a raw field name.
FIELD_LABELS: Dict[str, str] = {
  "shipping_method": "how you deliver what you sell",
  "sales_modality": "whether you sell in person, online, or both",
  "geographic_scope": "how far you reach (local, regional, national, or international)",
  "geographic_coverage": "the area you serve",
  "countries": "the countries you sell in",
  "capacity_driver": "what most limits how much you can grow right now",
  "primary_growth_lever": "the main lever you'll push first to grow",
  "legal_entity": "your legal structure",
  "milestones": "one concrete goal for the next 12 months",
  "business_description_summary": "a short description of the business",
  "unit_name": "what you sell, in one word or two",
  "unit_description": "what you sell",
  "units_per_week_capacity": "how much you can deliver in a week",
  "unit_price": "your price",
  "consumer_type": "who you sell to (consumers, businesses, or both)",
  "business_type": "the type of business",
  "client_id": "your client reference",
  "current_revenue": "your current annual revenue",
  "target_market": "your target market",
  "target_market_b2b_industry": "the industries you sell to",
  "target_market_b2b_size": "the size of the businesses you sell to",
  "target_market_b2b_age": "how established the businesses you sell to are",
  "target_market_summary": "a summary of your target market",
  "key_people_summary": "a summary of your key people",
  "first_name": "your first name",
  "last_name": "your last name",
  "email_address": "your email address",
  "business_start_date": "your business start date",
  "business_name": "the business name",
  "address": "the business address",
}

# The question the ops consultant asks when the field is still empty.
OPS_FOLLOWUP_QUESTIONS: Dict[str, str] = {
  "shipping_method": (
    "How does what you sell reach the customer: delivered or shipped to them, "
    "picked up or done on site, or provided digitally?"
  ),
  "sales_modality": (
    "Do you sell mainly in person, mainly online, or a mix of both?"
  ),
  "geographic_scope": (
    "How far does the business reach today: local, regional, national, or international?"
  ),
  "geographic_coverage": (
    "Which area do you serve - the cities, states, or regions where your customers are?"
  ),
  "countries": (
    "Which countries do you sell in? If it's only the United States, just say so."
  ),
  "capacity_driver": (
    "What most limits how much you can grow right now: your available labor/time, "
    "your systems/processes, or having enough customer demand?"
  ),
  "primary_growth_lever": (
    "What do you see as the main lever you'll push first to grow this business: "
    "winning more demand, improving systems/processes, or adding more people/capacity?"
  ),
  "legal_entity": (
    "Which legal structure are you using right now: Sole proprietor, LLC, Partnership, S-corp, or C-corp?"
  ),
}


def has_text(value: Any) -> bool:
  if value is None:
    return False
  if isinstance(value, (list, tuple, set, dict)):
    return len(value) > 0
  return bool(str(value).strip())


def missing_ops_fields(ops: Mapping[str, Any] | None) -> List[str]:
  """The business-wide fields still empty on THIS object - judged on what
  will be persisted, never on a proposal."""
  ops = ops if isinstance(ops, Mapping) else {}
  return [f for f in OPS_BUSINESS_WIDE_REQUIRED if not has_text(ops.get(f))]


def followup_question_for(field: str) -> str:
  return OPS_FOLLOWUP_QUESTIONS.get(str(field or "").strip(), "")


def first_followup_question(ops: Mapping[str, Any] | None) -> str:
  for f in missing_ops_fields(ops):
    q = followup_question_for(f)
    if q:
      return q
  return ""


def human_field_name(field: str) -> str:
  key = str(field or "").strip()
  return FIELD_LABELS.get(key) or key.replace("_", " ")


def describe_missing(errors: Mapping[str, Any] | Iterable[str] | None) -> str:
  """One plain sentence for the client, built from validator errors. No
  field names, no machine strings."""
  keys = list(errors.keys()) if isinstance(errors, Mapping) else list(errors or [])
  names = [human_field_name(k) for k in keys]
  names = [n for n in names if n]
  if not names:
    return "Something in the intake still needs an answer before the plan can be built."
  if len(names) == 1:
    listed = names[0]
  elif len(names) == 2:
    listed = f"{names[0]} and {names[1]}"
  else:
    listed = ", ".join(names[:-1]) + f", and {names[-1]}"
  return (
    f"Before the plan can be built we still need {listed}. "
    "Tell me in the chat and I'll set it, then submit again."
  )
