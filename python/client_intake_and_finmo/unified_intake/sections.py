from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from unified_intake.readiness import (
  financials_data_ready,
  headcount_ready,
  marketing_ready,
  milestones_ready,
  model_has_required_drivers,
  people_data_ready,
  revenue_ready,
  target_market_data_ready,
)
from unified_intake.redaction import strip_acs_codes


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
    "ops": ["what you sell", "how delivery works", "how fulfillment happens"],
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

    return (
      _has_nonempty(ops_json, "business_type")
      and _has_nonempty(ops_json, "unit_name")
      and _has_nonempty(ops_json, "units_per_week_capacity")
      and revenue_ready(revenue_model_json)
      and model_has_required_drivers(fulfillment_model_json, ("fulfillment_model", "who_fulfills", "lead_time"))
      and model_has_required_drivers(ops_concept_model_json, ("operating_unit", "primary_constraint", "process_overview"))
      and milestones_ready(milestones_model_json)
    )

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

    messages = _start_messages(focus="ops", messages=conversation_messages) if starting else list(conversation_messages or [])

    ops_has_min_for_models = bool(str((ops_json or {}).get("business_type") or "").strip()) and bool(
      str((ops_json or {}).get("unit_name") or "").strip()
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

    out: Dict[str, Any]
    if ops_has_min_for_models and (not revenue_ready(revenue_model_json)) and revenue_chat_turn:
      out = revenue_chat_turn(intake_context=intake_context, conversation_messages=messages)
    elif (
      ops_has_min_for_models
      and revenue_ready(revenue_model_json)
      and (not model_has_required_drivers(fulfillment_model_json, ("fulfillment_model", "who_fulfills", "lead_time")))
      and fulfillment_chat_turn
    ):
      out = fulfillment_chat_turn(intake_context=intake_context, conversation_messages=messages)
    elif (
      ops_has_min_for_models
      and revenue_ready(revenue_model_json)
      and (not model_has_required_drivers(ops_concept_model_json, ("operating_unit", "primary_constraint", "process_overview")))
      and ops_concept_chat_turn
    ):
      out = ops_concept_chat_turn(intake_context=intake_context, conversation_messages=messages)
    elif ops_has_min_for_models and revenue_ready(revenue_model_json) and (not milestones_ready(milestones_model_json)) and milestones_chat_turn:
      out = milestones_chat_turn(intake_context=intake_context, conversation_messages=messages)
    else:
      out = consultant_chat_turn(intake_context=intake_context, conversation_messages=messages)

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

