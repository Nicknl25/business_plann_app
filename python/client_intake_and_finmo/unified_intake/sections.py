from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from unified_intake.readiness import (
  cogs_ready,
  financials_data_ready,
  gna_ready,
  headcount_ready,
  marketing_ready,
  milestones_ready,
  model_has_required_drivers,
  people_data_ready,
  revenue_ready,
  target_market_data_ready,
)
from unified_intake.redaction import strip_acs_codes
from unified_intake.debug_log import debug_log


@dataclass(frozen=True)
class SectionHandler:
  key: str

  def is_complete(self, snapshot: Dict[str, Any]) -> bool:
    raise NotImplementedError

  def chat_turn(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    starting: bool,
  ) -> Dict[str, Any]:
    raise NotImplementedError

  def finalize(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    conn,
  ) -> Dict[str, Any]:
    raise NotImplementedError


SECTION_ORDER: Tuple[str, ...] = ("ops", "market", "people", "financials")


_LEGACY_SUMMARY_KEYS: Tuple[str, ...] = (
  "business_description_summary",
  "target_market_summary",
  "key_people_summary",
  "financials_summary",
)


def _drop_legacy_summaries(obj: Dict[str, Any]) -> Dict[str, Any]:
  if not isinstance(obj, dict) or not obj:
    return {}
  out = dict(obj)
  for k in _LEGACY_SUMMARY_KEYS:
    out.pop(k, None)
  return out


def expected_focus_from_snapshot(snapshot: Dict[str, Any]) -> str:
  """
  Fixed-order routing only.

  IMPORTANT:
  - This function must stay "dumb" and never embed readiness heuristics.
  - Sequencing is driven by explicit section confirmations, not by whether the raw
    data happens to be filled in.
  """
  confirmations = snapshot.get("confirmations") if isinstance(snapshot, dict) else None
  confirmed = confirmations if isinstance(confirmations, dict) else {}
  for key in SECTION_ORDER:
    if not bool(confirmed.get(key)):
      return key
  return "done"


def _has_nonempty(obj: Dict[str, Any], key: str) -> bool:
  try:
    return bool(str((obj or {}).get(key) or "").strip())
  except Exception:
    return False


_OPS_CARD_CONTENT_MARKERS: Dict[str, Tuple[str, ...]] = {
  "revenue": (
    "utilization",
    "operating weeks",
    "avg units",
    "average units",
    "year 1 average",
    "weekly average",
    "average per week",
  ),
  "fulfillment": (
    "fulfillment",
    "lead time",
    "who fulfills",
    "fulfill orders",
    "fulfills",
  ),
  "ops_concept": (
    "operating unit",
    "primary constraint",
    "process overview",
  ),
  "milestones": (
    "milestone",
    "milestones",
  ),
  "cogs": (
    "cogs",
    "direct costs",
    "direct cost",
    "cost per unit",
    "materials",
    "subcontractors",
    "variable cost",
  ),
  "gna": (
    "overhead",
    "g&a",
    "rent expense",
    "software expense",
    "insurance expense",
    "utilities expense",
    "admin expense",
    "debt payments",
  ),
  "marketing": (
    "marketing budget",
    "primary channels",
    "marketing spend",
  ),
  "headcount": (
    "headcount",
    "staffing",
    "payroll",
    "roles",
    "employees",
    "hiring",
  ),
}

_OPS_COMMIT_MARKERS: Tuple[str, ...] = (
  "assume",
  "assumption",
  "we'll",
  "we will",
  "i'll",
  "i will",
  "we'll use",
  "we will use",
  "we'll treat",
  "we will treat",
  "i'll treat",
  "i will treat",
  "we'll set",
  "we will set",
  "we'll go with",
  "we will go with",
  "i'll go with",
  "i will go with",
  "we'll record",
  "we will record",
  "confirm",
  "does that sound",
  "is that correct",
  "is that accurate",
  "is that all accurate",
  "should i keep using",
  "should we keep using",
  "should i keep",
  "should we keep",
  "lock in",
  "locked",
)


def _detect_ops_card_content(message: str) -> Optional[Tuple[str, str]]:
  text = " ".join(str(message or "").strip().lower().split())
  if not text:
    return None
  if not any(marker in text for marker in _OPS_COMMIT_MARKERS):
    return None
  for card, markers in _OPS_CARD_CONTENT_MARKERS.items():
    for marker in markers:
      if marker and marker in text:
        return card, marker
  return None


class ProposalRequiredError(RuntimeError):
  def __init__(self, route: str) -> None:
    super().__init__(f"Proposal required for {route}; no proposal could be generated.")
    self.route = route


def _require_proposal(*, route: str, suggestion: Dict[str, Any], proposal_patch: Dict[str, Any]) -> None:
  if isinstance(suggestion, dict) and suggestion and isinstance(proposal_patch, dict) and proposal_patch:
    return
  debug_log(
    "proposal_required_missing",
    route=route,
    has_suggestion=bool(suggestion),
    has_patch=bool(proposal_patch),
  )
  raise ProposalRequiredError(route)


def _start_messages(*, focus: str, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
  focus_norm = str(focus or "").strip().lower()
  if focus_norm == "ops":
    instruction = "Start the operational intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions)."
  elif focus_norm == "market":
    instruction = "Start the target market intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions)."
  elif focus_norm == "people":
    instruction = "Start the People & Capability intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions)."
  elif focus_norm == "financials":
    instruction = "Start the financials intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions)."
  else:
    instruction = "Continue."
  return [*list(messages or []), {"role": "user", "content": instruction}]


def _checkpoint_context_for_section(*, section_key: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
  business = snapshot.get("business_facts") if isinstance(snapshot.get("business_facts"), dict) else {}
  ops = snapshot.get("ops_json") if isinstance(snapshot.get("ops_json"), dict) else {}
  consumer_type = str((ops or {}).get("consumer_type") or "").strip().lower()
  if consumer_type not in ("consumer", "b2b", "mixed"):
    consumer_type = ""

  topics_by_section: Dict[str, List[str]] = {
    "ops": ["what you sell", "how delivery works"],
    "market": ["who you're selling to", "how you'll reach them"],
    "people": ["the key people and responsibilities"],
    "financials": ["the current financial picture and baseline operating costs"],
  }
  return {
    "section": str(section_key or "").strip().lower(),
    "business_name": str((business or {}).get("name") or "").strip(),
    "consumer_type": consumer_type,
    "aligned_topics": topics_by_section.get(str(section_key or "").strip().lower(), []),
  }


def _maybe_inject_checkpoint(
  *,
  out: Dict[str, Any],
  section_key: str,
  snapshot: Dict[str, Any],
  section_complete: bool,
) -> Dict[str, Any]:
  if not isinstance(out, dict):
    return {}
  if str(out.get("turn_outcome") or "").strip().upper() != "SECTION_COMPLETE":
    return out
  if not bool(section_complete):
    return out

  try:
    from unified_intake.language import render_client_message  # type: ignore
  except Exception:
    return out

  try:
    checkpoint = render_client_message(
      kind="checkpoint",
      context=_checkpoint_context_for_section(section_key=section_key, snapshot=snapshot),
    )
  except Exception:
    checkpoint = ""

  if isinstance(checkpoint, str) and checkpoint.strip():
    next_out = dict(out)
    next_out["assistant_message"] = checkpoint.strip()
    return next_out
  return out


class OpsSection(SectionHandler):
  def __init__(self) -> None:
    super().__init__(key="ops")

  def is_complete(self, snapshot: Dict[str, Any]) -> bool:
    ops_json = snapshot.get("ops_json") if isinstance(snapshot.get("ops_json"), dict) else {}
    revenue_model_json = snapshot.get("revenue_model_json") if isinstance(snapshot.get("revenue_model_json"), dict) else {}
    fulfillment_model_json = snapshot.get("fulfillment_model_json") if isinstance(snapshot.get("fulfillment_model_json"), dict) else {}
    ops_concept_model_json = snapshot.get("ops_concept_model_json") if isinstance(snapshot.get("ops_concept_model_json"), dict) else {}
    milestones_model_json = snapshot.get("milestones_model_json") if isinstance(snapshot.get("milestones_model_json"), dict) else {}
    cogs_model_json = snapshot.get("cogs_model_json") if isinstance(snapshot.get("cogs_model_json"), dict) else {}
    gna_model_json = snapshot.get("gna_model_json") if isinstance(snapshot.get("gna_model_json"), dict) else {}

    business_type_ready = _has_nonempty(ops_json, "business_type")
    unit_name_ready = _has_nonempty(ops_json, "unit_name")
    capacity_ready = _has_nonempty(ops_json, "units_per_week_capacity")
    revenue_ready_now = revenue_ready(revenue_model_json)
    fulfillment_ready_now = model_has_required_drivers(fulfillment_model_json, ("fulfillment_model", "who_fulfills", "lead_time"))
    ops_concept_ready_now = model_has_required_drivers(ops_concept_model_json, ("operating_unit", "primary_constraint", "process_overview"))
    milestones_ready_now = milestones_ready(milestones_model_json)
    cogs_ready_now = cogs_ready(cogs_model_json)
    gna_ready_now = gna_ready(gna_model_json)

    complete = (
      business_type_ready
      and unit_name_ready
      and capacity_ready
      and revenue_ready_now
      and fulfillment_ready_now
      and ops_concept_ready_now
      and milestones_ready_now
      and cogs_ready_now
      and gna_ready_now
    )
    debug_log(
      "ops_is_complete",
      business_type=business_type_ready,
      unit_name=unit_name_ready,
      units_per_week_capacity=capacity_ready,
      revenue=revenue_ready_now,
      fulfillment=fulfillment_ready_now,
      ops_concept=ops_concept_ready_now,
      milestones=milestones_ready_now,
      cogs=cogs_ready_now,
      gna=gna_ready_now,
      complete=complete,
    )
    return complete

  def chat_turn(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    starting: bool,
  ) -> Dict[str, Any]:
    from intake_consultant import consultant_chat_turn  # type: ignore

    ops_json = snapshot.get("ops_json") if isinstance(snapshot.get("ops_json"), dict) else {}
    revenue_model_json = snapshot.get("revenue_model_json") if isinstance(snapshot.get("revenue_model_json"), dict) else {}
    fulfillment_model_json = snapshot.get("fulfillment_model_json") if isinstance(snapshot.get("fulfillment_model_json"), dict) else {}
    ops_concept_model_json = snapshot.get("ops_concept_model_json") if isinstance(snapshot.get("ops_concept_model_json"), dict) else {}
    milestones_model_json = snapshot.get("milestones_model_json") if isinstance(snapshot.get("milestones_model_json"), dict) else {}
    cogs_model_json = snapshot.get("cogs_model_json") if isinstance(snapshot.get("cogs_model_json"), dict) else {}
    gna_model_json = snapshot.get("gna_model_json") if isinstance(snapshot.get("gna_model_json"), dict) else {}

    messages = _start_messages(focus="ops", messages=conversation_messages) if starting else list(conversation_messages or [])

    ops_has_min_for_models = bool(str((ops_json or {}).get("business_type") or "").strip()) and bool(
      str((ops_json or {}).get("unit_name") or "").strip()
    )
    revenue_ready_now = revenue_ready(revenue_model_json)
    fulfillment_ready_now = model_has_required_drivers(fulfillment_model_json, ("fulfillment_model", "who_fulfills", "lead_time"))
    ops_concept_ready_now = model_has_required_drivers(ops_concept_model_json, ("operating_unit", "primary_constraint", "process_overview"))
    milestones_ready_now = milestones_ready(milestones_model_json)
    cogs_ready_now = cogs_ready(cogs_model_json)
    gna_ready_now = gna_ready(gna_model_json)
    debug_log(
      "ops_chat_state",
      starting=starting,
      ops_has_min_for_models=ops_has_min_for_models,
      revenue_ready=revenue_ready_now,
      fulfillment_ready=fulfillment_ready_now,
      ops_concept_ready=ops_concept_ready_now,
      milestones_ready=milestones_ready_now,
      cogs_ready=cogs_ready_now,
      gna_ready=gna_ready_now,
    )

    try:
      from revenue_consultant import revenue_chat_turn  # type: ignore
    except Exception:
      revenue_chat_turn = None  # type: ignore
    try:
      from fulfillment_consultant import fulfillment_chat_turn  # type: ignore
    except Exception:
      fulfillment_chat_turn = None  # type: ignore
    try:
      from ops_concept_consultant import ops_concept_chat_turn  # type: ignore
    except Exception:
      ops_concept_chat_turn = None  # type: ignore
    try:
      from milestones_consultant import milestones_chat_turn  # type: ignore
    except Exception:
      milestones_chat_turn = None  # type: ignore
    try:
      from cogs_consultant import cogs_chat_turn  # type: ignore
    except Exception:
      cogs_chat_turn = None  # type: ignore
    try:
      from gna_consultant import gna_chat_turn  # type: ignore
    except Exception:
      gna_chat_turn = None  # type: ignore

    out: Dict[str, Any]
    route = "ops"
    proposal_patch: Dict[str, Any] = {}
    proposal_model = ""
    if ops_has_min_for_models and (not revenue_ready_now):
      route = "revenue"
      if not revenue_chat_turn:
        raise ProposalRequiredError(route)
      suggestion = {}
      try:
        from model_card_proposer import propose_revenue_suggestions  # type: ignore

        raw_lobs = revenue_model_json.get("lobs") if isinstance(revenue_model_json, dict) else None
        lobs_in: List[Dict[str, str]] = []
        if isinstance(raw_lobs, list):
          for l in raw_lobs:
            if not isinstance(l, dict):
              continue
            lobs_in.append(
              {
                "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                "lob_name": str(l.get("lob_name") or "").strip(),
              }
            )
        suggested = propose_revenue_suggestions(
          business_name=str((intake_context or {}).get("business_name") or "").strip(),
          business_type=str((ops_json or {}).get("business_type") or "").strip(),
          naics_6=(intake_context or {}).get("naics_6"),
          today_iso=str((intake_context or {}).get("today_iso") or "").strip(),
          business_start_date=str((intake_context or {}).get("business_start_date") or "").strip() or None,
          ops_json=ops_json,
          shared_context=(intake_context or {}).get("shared_context") or {},
          lobs=lobs_in,
        )
        if suggested and isinstance(suggested[0], dict):
          suggestion = suggested[0]
      except Exception as exc:
        raise ProposalRequiredError(route) from exc
      if isinstance(suggestion, dict) and suggestion:
        units_cap = suggestion.get("units_per_week_capacity")
        avg_units = suggestion.get("avg_units_per_week_year1")
        weeks = suggestion.get("operating_weeks_per_year")
        unit_price = suggestion.get("unit_price")
        if units_cap is not None:
          proposal_patch["revenue.units_per_week_capacity"] = {
            "lob_key": "company_total",
            "value": units_cap,
            "unit": "units",
            "time_basis": "week",
          }
        if avg_units is not None:
          proposal_patch["revenue.avg_units_per_week_year1"] = {
            "lob_key": "company_total",
            "value": avg_units,
            "unit": "units",
            "time_basis": "week",
          }
        if weeks is not None:
          proposal_patch["revenue.operating_weeks_per_year"] = {
            "lob_key": "company_total",
            "value": weeks,
            "unit": "weeks",
            "time_basis": "year",
          }
        if unit_price is not None:
          proposal_patch["revenue.unit_price"] = {
            "lob_key": "company_total",
            "value": unit_price,
            "unit": "USD",
            "time_basis": "per_unit",
          }
        if proposal_patch:
          proposal_model = "revenue"
      _require_proposal(route=route, suggestion=suggestion if isinstance(suggestion, dict) else {}, proposal_patch=proposal_patch)
      out = revenue_chat_turn(intake_context={**intake_context, "revenue_suggestion": suggestion}, conversation_messages=messages)
    elif ops_has_min_for_models and revenue_ready_now and (not fulfillment_ready_now):
      route = "fulfillment"
      if not fulfillment_chat_turn:
        raise ProposalRequiredError(route)
      suggestion = {}
      try:
        from model_card_proposer import propose_fulfillment_suggestions  # type: ignore

        raw_lobs = fulfillment_model_json.get("lobs") if isinstance(fulfillment_model_json, dict) else None
        lobs_in: List[Dict[str, str]] = []
        if isinstance(raw_lobs, list):
          for l in raw_lobs:
            if not isinstance(l, dict):
              continue
            lobs_in.append(
              {
                "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                "lob_name": str(l.get("lob_name") or "").strip(),
              }
            )
        suggested = propose_fulfillment_suggestions(
          business_name=str((intake_context or {}).get("business_name") or "").strip(),
          business_type=str((ops_json or {}).get("business_type") or "").strip(),
          naics_6=(intake_context or {}).get("naics_6"),
          today_iso=str((intake_context or {}).get("today_iso") or "").strip(),
          business_start_date=str((intake_context or {}).get("business_start_date") or "").strip() or None,
          ops_json=ops_json,
          shared_context=(intake_context or {}).get("shared_context") or {},
          lobs=lobs_in,
        )
        if suggested and isinstance(suggested[0], dict):
          suggestion = suggested[0]
      except Exception as exc:
        raise ProposalRequiredError(route) from exc
      if isinstance(suggestion, dict) and suggestion:
        fulfillment_model = str(suggestion.get("fulfillment_model") or "").strip()
        who_fulfills = str(suggestion.get("who_fulfills") or "").strip()
        lead_time = str(suggestion.get("lead_time") or "").strip()
        if fulfillment_model:
          proposal_patch["fulfillment.fulfillment_model"] = {
            "lob_key": "company_total",
            "value": fulfillment_model,
          }
        if who_fulfills:
          proposal_patch["fulfillment.who_fulfills"] = {
            "lob_key": "company_total",
            "value": who_fulfills,
          }
        if lead_time:
          proposal_patch["fulfillment.lead_time"] = {
            "lob_key": "company_total",
            "value": lead_time,
          }
        if proposal_patch:
          proposal_model = "fulfillment"
      _require_proposal(route=route, suggestion=suggestion if isinstance(suggestion, dict) else {}, proposal_patch=proposal_patch)
      out = fulfillment_chat_turn(intake_context={**intake_context, "fulfillment_suggestion": suggestion}, conversation_messages=messages)
    elif ops_has_min_for_models and revenue_ready_now and (not ops_concept_ready_now):
      route = "ops_concept"
      if not ops_concept_chat_turn:
        raise ProposalRequiredError(route)
      suggestion = {}
      try:
        from model_card_proposer import propose_ops_concept_suggestions  # type: ignore

        raw_lobs = ops_concept_model_json.get("lobs") if isinstance(ops_concept_model_json, dict) else None
        lobs_in: List[Dict[str, str]] = []
        if isinstance(raw_lobs, list):
          for l in raw_lobs:
            if not isinstance(l, dict):
              continue
            lobs_in.append(
              {
                "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                "lob_name": str(l.get("lob_name") or "").strip(),
              }
            )
        suggested = propose_ops_concept_suggestions(
          business_name=str((intake_context or {}).get("business_name") or "").strip(),
          business_type=str((ops_json or {}).get("business_type") or "").strip(),
          naics_6=(intake_context or {}).get("naics_6"),
          today_iso=str((intake_context or {}).get("today_iso") or "").strip(),
          business_start_date=str((intake_context or {}).get("business_start_date") or "").strip() or None,
          ops_json=ops_json,
          shared_context=(intake_context or {}).get("shared_context") or {},
          lobs=lobs_in,
        )
        if suggested and isinstance(suggested[0], dict):
          suggestion = suggested[0]
      except Exception as exc:
        raise ProposalRequiredError(route) from exc
      if isinstance(suggestion, dict) and suggestion:
        operating_unit = str(suggestion.get("operating_unit") or "").strip()
        primary_constraint = str(suggestion.get("primary_constraint") or "").strip()
        process_overview = str(suggestion.get("process_overview") or "").strip()
        if operating_unit:
          proposal_patch["ops_concept.operating_unit"] = {
            "lob_key": "company_total",
            "value": operating_unit,
          }
        if primary_constraint:
          proposal_patch["ops_concept.primary_constraint"] = {
            "lob_key": "company_total",
            "value": primary_constraint,
          }
        if process_overview:
          proposal_patch["ops_concept.process_overview"] = {
            "lob_key": "company_total",
            "value": process_overview,
          }
        if proposal_patch:
          proposal_model = "ops_concept"
      _require_proposal(route=route, suggestion=suggestion if isinstance(suggestion, dict) else {}, proposal_patch=proposal_patch)
      out = ops_concept_chat_turn(intake_context={**intake_context, "ops_concept_suggestion": suggestion}, conversation_messages=messages)
    elif ops_has_min_for_models and revenue_ready_now and (not milestones_ready_now):
      route = "milestones"
      if not milestones_chat_turn:
        raise ProposalRequiredError(route)
      suggestion = {}
      try:
        from model_card_proposer import propose_milestones_suggestions  # type: ignore

        raw_lobs = milestones_model_json.get("lobs") if isinstance(milestones_model_json, dict) else None
        lobs_in: List[Dict[str, str]] = []
        if isinstance(raw_lobs, list):
          for l in raw_lobs:
            if not isinstance(l, dict):
              continue
            lobs_in.append(
              {
                "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                "lob_name": str(l.get("lob_name") or "").strip(),
              }
            )
        suggested = propose_milestones_suggestions(
          business_name=str((intake_context or {}).get("business_name") or "").strip(),
          business_type=str((ops_json or {}).get("business_type") or "").strip(),
          naics_6=(intake_context or {}).get("naics_6"),
          today_iso=str((intake_context or {}).get("today_iso") or "").strip(),
          business_start_date=str((intake_context or {}).get("business_start_date") or "").strip() or None,
          ops_json=ops_json,
          shared_context=(intake_context or {}).get("shared_context") or {},
          lobs=lobs_in,
        )
        if suggested and isinstance(suggested[0], dict):
          suggestion = suggested[0]
      except Exception as exc:
        raise ProposalRequiredError(route) from exc
      milestones_list = suggestion.get("milestones") if isinstance(suggestion, dict) else None
      if isinstance(milestones_list, list) and milestones_list:
        proposal_patch["milestones.milestones"] = {
          "lob_key": "company_total",
          "value": milestones_list,
        }
        proposal_model = "milestones"
      _require_proposal(route=route, suggestion=suggestion if isinstance(suggestion, dict) else {}, proposal_patch=proposal_patch)
      out = milestones_chat_turn(
        intake_context={**intake_context, "milestones_suggestion": suggestion},
        conversation_messages=messages,
      )
    elif ops_has_min_for_models and revenue_ready_now and (not cogs_ready_now):
      route = "cogs"
      if not cogs_chat_turn:
        raise ProposalRequiredError(route)
      suggestion = {}
      try:
        from model_card_proposer import propose_cogs_suggestions  # type: ignore

        raw_lobs = cogs_model_json.get("lobs") if isinstance(cogs_model_json, dict) else None
        lobs_in: List[Dict[str, str]] = []
        if isinstance(raw_lobs, list):
          for l in raw_lobs:
            if not isinstance(l, dict):
              continue
            lobs_in.append(
              {
                "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                "lob_name": str(l.get("lob_name") or "").strip(),
              }
            )
        suggested = propose_cogs_suggestions(
          business_name=str((intake_context or {}).get("business_name") or "").strip(),
          business_type=str((ops_json or {}).get("business_type") or "").strip(),
          naics_6=(intake_context or {}).get("naics_6"),
          today_iso=str((intake_context or {}).get("today_iso") or "").strip(),
          business_start_date=str((intake_context or {}).get("business_start_date") or "").strip() or None,
          ops_json=ops_json,
          fulfillment_model_json=fulfillment_model_json,
          shared_context=(intake_context or {}).get("shared_context") or {},
          lobs=lobs_in,
        )
        if suggested and isinstance(suggested[0], dict):
          suggestion = suggested[0]
      except Exception as exc:
        raise ProposalRequiredError(route) from exc
      if isinstance(suggestion, dict):
        if suggestion.get("materials_cost_per_unit") is not None:
          proposal_patch["cogs.materials_cost_per_unit"] = {
            "lob_key": "company_total",
            "value": suggestion.get("materials_cost_per_unit"),
            "unit": "USD",
            "time_basis": "per_unit",
          }
        if suggestion.get("direct_fulfillment_cost_per_unit") is not None:
          proposal_patch["cogs.direct_fulfillment_cost_per_unit"] = {
            "lob_key": "company_total",
            "value": suggestion.get("direct_fulfillment_cost_per_unit"),
            "unit": "USD",
            "time_basis": "per_unit",
          }
        if suggestion.get("other_variable_cost_per_unit") is not None:
          proposal_patch["cogs.other_variable_cost_per_unit"] = {
            "lob_key": "company_total",
            "value": suggestion.get("other_variable_cost_per_unit"),
            "unit": "USD",
            "time_basis": "per_unit",
          }
        if suggestion.get("cogs_percent_of_revenue") is not None:
          proposal_patch["cogs.cogs_percent_of_revenue"] = {
            "lob_key": "company_total",
            "value": suggestion.get("cogs_percent_of_revenue"),
            "unit": None,
            "time_basis": None,
          }
        if suggestion.get("production") is not None:
          proposal_patch["cogs.production"] = {
            "lob_key": "company_total",
            "value": suggestion.get("production"),
          }
      if proposal_patch:
        proposal_model = "cogs"
      _require_proposal(route=route, suggestion=suggestion if isinstance(suggestion, dict) else {}, proposal_patch=proposal_patch)
      out = cogs_chat_turn(intake_context={**intake_context, "cogs_suggestion": suggestion}, conversation_messages=messages)
    elif ops_has_min_for_models and revenue_ready_now and (not gna_ready_now):
      route = "gna"
      if not gna_chat_turn:
        raise ProposalRequiredError(route)
      suggestion = {}
      try:
        from model_card_proposer import propose_gna_suggestions  # type: ignore

        raw_lobs = gna_model_json.get("lobs") if isinstance(gna_model_json, dict) else None
        lobs_in: List[Dict[str, str]] = []
        if isinstance(raw_lobs, list):
          for l in raw_lobs:
            if not isinstance(l, dict):
              continue
            lobs_in.append(
              {
                "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                "lob_name": str(l.get("lob_name") or "").strip(),
              }
            )
        suggested = propose_gna_suggestions(
          business_name=str((intake_context or {}).get("business_name") or "").strip(),
          business_type=str((ops_json or {}).get("business_type") or "").strip(),
          naics_6=(intake_context or {}).get("naics_6"),
          today_iso=str((intake_context or {}).get("today_iso") or "").strip(),
          business_start_date=str((intake_context or {}).get("business_start_date") or "").strip() or None,
          ops_json=ops_json,
          shared_context=(intake_context or {}).get("shared_context") or {},
          lobs=lobs_in,
        )
        if suggested and isinstance(suggested[0], dict):
          suggestion = suggested[0]
      except Exception as exc:
        raise ProposalRequiredError(route) from exc
      if isinstance(suggestion, dict):
        if suggestion.get("monthly_rent_expense") is not None:
          proposal_patch["gna.monthly_rent_expense"] = {
            "lob_key": "company_total",
            "value": suggestion.get("monthly_rent_expense"),
            "unit": "USD",
            "time_basis": "month",
          }
        if suggestion.get("monthly_software_expense") is not None:
          proposal_patch["gna.monthly_software_expense"] = {
            "lob_key": "company_total",
            "value": suggestion.get("monthly_software_expense"),
            "unit": "USD",
            "time_basis": "month",
          }
        if suggestion.get("monthly_insurance_expense") is not None:
          proposal_patch["gna.monthly_insurance_expense"] = {
            "lob_key": "company_total",
            "value": suggestion.get("monthly_insurance_expense"),
            "unit": "USD",
            "time_basis": "month",
          }
        if suggestion.get("monthly_utilities_expense") is not None:
          proposal_patch["gna.monthly_utilities_expense"] = {
            "lob_key": "company_total",
            "value": suggestion.get("monthly_utilities_expense"),
            "unit": "USD",
            "time_basis": "month",
          }
        if suggestion.get("monthly_admin_expense") is not None:
          proposal_patch["gna.monthly_admin_expense"] = {
            "lob_key": "company_total",
            "value": suggestion.get("monthly_admin_expense"),
            "unit": "USD",
            "time_basis": "month",
          }
        if suggestion.get("other_operating_expense") is not None:
          proposal_patch["gna.other_operating_expense"] = {
            "lob_key": "company_total",
            "value": suggestion.get("other_operating_expense"),
            "unit": "USD",
            "time_basis": "month",
          }
        if suggestion.get("other_monthly_debt_payments") is not None:
          proposal_patch["gna.other_monthly_debt_payments"] = {
            "lob_key": "company_total",
            "value": suggestion.get("other_monthly_debt_payments"),
            "unit": "USD",
            "time_basis": "month",
          }
      if proposal_patch:
        proposal_model = "gna"
      _require_proposal(route=route, suggestion=suggestion if isinstance(suggestion, dict) else {}, proposal_patch=proposal_patch)
      out = gna_chat_turn(intake_context={**intake_context, "gna_suggestion": suggestion}, conversation_messages=messages)
    else:
      out = consultant_chat_turn(intake_context=intake_context, conversation_messages=messages)
      if isinstance(out, dict):
        assistant_message = str(out.get("assistant_message") or "")
        violation = _detect_ops_card_content(assistant_message)
        if violation:
          card, marker = violation
          debug_log("ops_card_content_violation", card=card, marker=marker)
          raise ProposalRequiredError(card)

    if proposal_patch and isinstance(out, dict):
      out = dict(out)
      out["_proposal_patch"] = proposal_patch
      out["_proposal_model"] = proposal_model

    debug_log("ops_chat_route", route=route)
    return _maybe_inject_checkpoint(out=out, section_key="ops", snapshot=snapshot, section_complete=self.is_complete(snapshot))

  def finalize(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    conn,
  ) -> Dict[str, Any]:
    from intake_consultant import consultant_finalize  # type: ignore

    try:
      from unified_intake.naics import build_business_type_candidates  # type: ignore
    except Exception:
      build_business_type_candidates = None  # type: ignore
    if build_business_type_candidates:
      try:
        intake_context = dict(intake_context or {})
        intake_context["business_type_candidates"] = build_business_type_candidates(conn=conn, messages=conversation_messages)
      except Exception:
        pass

    out = consultant_finalize(intake_context=intake_context, conversation_messages=conversation_messages)
    return _drop_legacy_summaries(out) if isinstance(out, dict) else {}


class MarketSection(SectionHandler):
  def __init__(self) -> None:
    super().__init__(key="market")

  def is_complete(self, snapshot: Dict[str, Any]) -> bool:
    ops_json = snapshot.get("ops_json") if isinstance(snapshot.get("ops_json"), dict) else {}
    market_json = snapshot.get("market_json") if isinstance(snapshot.get("market_json"), dict) else {}
    marketing_model_json = snapshot.get("marketing_model_json") if isinstance(snapshot.get("marketing_model_json"), dict) else {}

    consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
    if consumer_type not in ("consumer", "b2b", "mixed"):
      consumer_type = "consumer"

    return target_market_data_ready(market_json=market_json, consumer_type=consumer_type) and marketing_ready(marketing_model_json)

  def chat_turn(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    starting: bool,
  ) -> Dict[str, Any]:
    from marketing_consultant import marketing_chat_turn  # type: ignore
    from target_market_consultant import target_market_chat_turn  # type: ignore

    ops_json = snapshot.get("ops_json") if isinstance(snapshot.get("ops_json"), dict) else {}
    market_json = snapshot.get("market_json") if isinstance(snapshot.get("market_json"), dict) else {}
    marketing_model_json = snapshot.get("marketing_model_json") if isinstance(snapshot.get("marketing_model_json"), dict) else {}

    consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
    if consumer_type not in ("consumer", "b2b", "mixed"):
      consumer_type = "consumer"

    messages = _start_messages(focus="market", messages=conversation_messages) if starting else list(conversation_messages or [])

    if target_market_data_ready(market_json=market_json, consumer_type=consumer_type) and (not marketing_ready(marketing_model_json)):
      out = marketing_chat_turn(intake_context=intake_context, conversation_messages=messages)
    else:
      out = target_market_chat_turn(intake_context=intake_context, conversation_messages=messages)

    if isinstance(out, dict) and isinstance(out.get("assistant_message"), str):
      out = dict(out)
      out["assistant_message"] = strip_acs_codes(str(out.get("assistant_message") or ""))

    return _maybe_inject_checkpoint(out=out, section_key="market", snapshot=snapshot, section_complete=self.is_complete(snapshot))

  def finalize(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    conn,
  ) -> Dict[str, Any]:
    from target_market_consultant import target_market_finalize  # type: ignore

    ops_json = snapshot.get("ops_json") if isinstance(snapshot.get("ops_json"), dict) else {}
    consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
    if consumer_type not in ("consumer", "b2b", "mixed"):
      consumer_type = "consumer"

    mapping_rows: List[Dict[str, Any]] = []
    if consumer_type != "b2b":
      mapping_rows = _fetch_target_market_mapping_rows(conn)

    out = target_market_finalize(
      intake_context={**(intake_context or {}), "consumer_type": consumer_type},
      conversation_messages=conversation_messages,
      mapping_rows=mapping_rows,
    )
    return _drop_legacy_summaries(out) if isinstance(out, dict) else {}


class PeopleSection(SectionHandler):
  def __init__(self) -> None:
    super().__init__(key="people")

  def is_complete(self, snapshot: Dict[str, Any]) -> bool:
    people_json = snapshot.get("people_json") if isinstance(snapshot.get("people_json"), dict) else {}
    headcount_model_json = snapshot.get("headcount_model_json") if isinstance(snapshot.get("headcount_model_json"), dict) else {}
    return people_data_ready(people_json=people_json) and headcount_ready(headcount_model_json)

  def chat_turn(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    starting: bool,
  ) -> Dict[str, Any]:
    from headcount_consultant import headcount_chat_turn  # type: ignore
    from people_capability_consultant import people_capability_chat_turn  # type: ignore

    people_json = snapshot.get("people_json") if isinstance(snapshot.get("people_json"), dict) else {}
    headcount_model_json = snapshot.get("headcount_model_json") if isinstance(snapshot.get("headcount_model_json"), dict) else {}

    messages = _start_messages(focus="people", messages=conversation_messages) if starting else list(conversation_messages or [])

    out: Dict[str, Any]
    if people_data_ready(people_json=people_json) and (not headcount_ready(headcount_model_json)):
      out = headcount_chat_turn(intake_context=intake_context, conversation_messages=messages)
    else:
      out = people_capability_chat_turn(intake_context=intake_context, conversation_messages=messages)

    return _maybe_inject_checkpoint(out=out, section_key="people", snapshot=snapshot, section_complete=self.is_complete(snapshot))

  def finalize(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    conn,
  ) -> Dict[str, Any]:
    from people_capability_consultant import people_capability_finalize  # type: ignore

    out = people_capability_finalize(intake_context=intake_context, conversation_messages=conversation_messages)
    return _drop_legacy_summaries(out) if isinstance(out, dict) else {}


class FinancialsSection(SectionHandler):
  def __init__(self) -> None:
    super().__init__(key="financials")

  def is_complete(self, snapshot: Dict[str, Any]) -> bool:
    financials_json = snapshot.get("financials_json") if isinstance(snapshot.get("financials_json"), dict) else {}
    return financials_data_ready(financials_json=financials_json)

  def chat_turn(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    starting: bool,
  ) -> Dict[str, Any]:
    from financials_consultant import financials_chat_turn  # type: ignore

    messages = _start_messages(focus="financials", messages=conversation_messages) if starting else list(conversation_messages or [])
    out = financials_chat_turn(intake_context=intake_context, conversation_messages=messages)
    return _maybe_inject_checkpoint(out=out, section_key="financials", snapshot=snapshot, section_complete=self.is_complete(snapshot))

  def finalize(
    self,
    *,
    intake_context: Dict[str, Any],
    conversation_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    conn,
  ) -> Dict[str, Any]:
    from financials_consultant import financials_finalize  # type: ignore

    out = financials_finalize(intake_context=intake_context, conversation_messages=conversation_messages)
    return _drop_legacy_summaries(out) if isinstance(out, dict) else {}


_SECTIONS: Dict[str, SectionHandler] = {
  "ops": OpsSection(),
  "market": MarketSection(),
  "people": PeopleSection(),
  "financials": FinancialsSection(),
}


def get_section(key: str) -> SectionHandler:
  k = str(key or "").strip().lower()
  if k not in _SECTIONS:
    raise KeyError(f"Unknown section: {key}")
  return _SECTIONS[k]


def _fetch_target_market_mapping_rows(conn) -> List[Dict[str, Any]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute("SELECT acs_code, description, segment, min_value, max_value FROM target_market_mapping")
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  def _parse_nullable_float(value: Any) -> Any:
    if value is None or value == "":
      return None
    try:
      return float(value)
    except Exception:
      return None

  mapping_rows: List[Dict[str, Any]] = []
  for r in rows:
    if not isinstance(r, dict):
      continue
    mapping_rows.append(
      {
        "acs_code": str(r.get("acs_code") or "").strip(),
        "description": str(r.get("description") or "").strip(),
        "segment": str(r.get("segment") or "").strip(),
        "min_value": _parse_nullable_float(r.get("min_value")),
        "max_value": _parse_nullable_float(r.get("max_value")),
      }
    )

  allowed_segments = {
    "Gender & Age",
    "Income",
    "Education",
    "Household Structure",
    "Housing Economics",
    "Employment",
  }

  cleaned: List[Dict[str, Any]] = []
  for r in mapping_rows:
    if not r["acs_code"] or not r["segment"]:
      continue
    if r["segment"] not in allowed_segments:
      continue
    if r["segment"] == "Household Structure":
      desc_norm = " ".join(str(r["description"]).split()).strip().lower()
      if desc_norm == "total households":
        continue
    cleaned.append(r)
  if not cleaned:
    raise RuntimeError("target_market_mapping table is empty; load it before running the target market consult.")
  return cleaned
