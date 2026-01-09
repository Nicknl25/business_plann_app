import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _load_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  load_dotenv(os.path.join(root, ".env"))


def _json_load_maybe(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(str(raw))
  except Exception:
    return None


def _parse_messages(raw: Any) -> List[Dict[str, Any]]:
  parsed = _json_load_maybe(raw)
  if isinstance(parsed, list):
    return [m for m in parsed if isinstance(m, dict)]
  return []


def _parse_proposals(raw: Any) -> List[Dict[str, Any]]:
  parsed = _json_load_maybe(raw)
  if isinstance(parsed, list):
    return [p for p in parsed if isinstance(p, dict)]
  return []


def _assert(condition: bool, message: str) -> None:
  if not condition:
    raise AssertionError(message)


def _proposal_ids_unique(proposals: List[Dict[str, Any]]) -> None:
  ids = [str(p.get("id") or "").strip() for p in proposals if isinstance(p, dict)]
  ids = [i for i in ids if i]
  _assert(len(ids) == len(set(ids)), f"duplicate proposal ids detected: {ids}")


def _format_commit_echo(proposal: Dict[str, Any]) -> str:
  updates = proposal.get("updates") if isinstance(proposal.get("updates"), list) else []
  if not updates:
    return ""

  def _label(key: str) -> str:
    raw = str(key or "").strip()
    if not raw:
      return "value"
    return raw.replace("_", " ").strip()

  def _format_value(value: Any) -> str:
    if value is None:
      return "none"
    if isinstance(value, bool):
      return "yes" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
      return str(value)
    if isinstance(value, str):
      return value
    if isinstance(value, list):
      return f"{len(value)} item" + ("s" if len(value) != 1 else "")
    if isinstance(value, dict):
      return "details captured"
    return str(value)

  parts: List[str] = []
  for u in updates[:4]:
    if not isinstance(u, dict):
      continue
    key = _label(u.get("key"))
    value = _format_value(u.get("value"))
    unit = str(u.get("unit") or "").strip()
    time_basis = str(u.get("time_basis") or "").strip()
    suffix = " / ".join([s for s in (unit, time_basis) if s])
    if suffix:
      parts.append(f"{key}: {value} ({suffix})")
    else:
      parts.append(f"{key}: {value}")
  remaining = len([u for u in updates if isinstance(u, dict)]) - len(parts)
  if remaining > 0:
    parts.append(f"+{remaining} more")
  return "Locked in: " + "; ".join(parts)


def _company_total_lob(card: Dict[str, Any]) -> Dict[str, Any]:
  lobs = card.get("lobs")
  if not isinstance(lobs, list):
    return {"drivers": card.get("drivers") or {}, "derived": card.get("derived") or {}}
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    if str(lob.get("lob_key") or "").strip() == "company_total":
      return lob
  return {}


def _get_field_from_draft(draft: Dict[str, Any], key: str) -> Any:
  key = str(key or "").strip()
  if key.count(".") != 1:
    return None
  group, field = key.split(".", 1)
  group = group.strip().lower()
  field = field.strip()

  if group == "business":
    mapping = {
      "name": "business_name",
      "address": "business_address",
      "start_date": "business_start_date",
      "address_street": "address_street",
      "address_city": "address_city",
      "address_state": "address_state",
      "address_zip": "address_zip",
      "address_country": "address_country",
    }
    return draft.get(mapping.get(field, ""))

  if group == "ops":
    ops = _json_load_maybe(draft.get("operating_model_json")) or {}
    return ops.get(field)
  if group == "market":
    market = _json_load_maybe(draft.get("target_market_json")) or {}
    return market.get(field)
  if group == "people":
    people = _json_load_maybe(draft.get("people_json")) or {}
    return people.get(field)
  if group == "financials":
    fin = _json_load_maybe(draft.get("financials_json")) or {}
    return fin.get(field)

  model_map = {
    "marketing": "marketing_model_json",
    "pricing": "pricing_model_json",
    "revenue": "revenue_model_json",
    "headcount": "headcount_model_json",
    "fulfillment": "fulfillment_model_json",
    "ops_concept": "ops_concept_model_json",
    "milestones": "milestones_model_json",
    "cogs": "cogs_model_json",
    "gna": "gna_model_json",
  }
  column = model_map.get(group)
  card = _json_load_maybe(draft.get(column)) if column else None
  if not isinstance(card, dict):
    return None
  lob = _company_total_lob(card)
  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
  driver = drivers.get(field)
  if isinstance(driver, dict):
    return driver.get("value")
  return None


def _get_derived_entry(draft: Dict[str, Any], model: str, key: str) -> Dict[str, Any]:
  model_map = {
    "marketing": "marketing_model_json",
    "pricing": "pricing_model_json",
    "revenue": "revenue_model_json",
    "headcount": "headcount_model_json",
    "fulfillment": "fulfillment_model_json",
    "ops_concept": "ops_concept_model_json",
    "milestones": "milestones_model_json",
    "cogs": "cogs_model_json",
    "gna": "gna_model_json",
  }
  column = model_map.get(model)
  card = _json_load_maybe(draft.get(column)) if column else None
  if not isinstance(card, dict):
    return {}
  lob = _company_total_lob(card)
  derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
  entry = derived.get(key)
  return dict(entry) if isinstance(entry, dict) else {}


def _post_json(client, url: str, payload: Dict[str, Any], *, retries: int = 1) -> Dict[str, Any]:
  last_body: Dict[str, Any] = {}
  for attempt in range(max(1, retries)):
    res = client.post(url, json=payload)
    body = res.get_json(silent=True) or {}
    last_body = body
    if 200 <= res.status_code < 300:
      return body
    if res.status_code == 409 and "snag" in str(body.get("detail") or "").lower() and attempt < retries - 1:
      time.sleep(0.75)
      continue
    _assert(False, f"{url} failed: HTTP {res.status_code} {body}")
  return last_body


def _get_json(client, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
  res = client.get(url, query_string=params)
  body = res.get_json(silent=True) or {}
  _assert(200 <= res.status_code < 300, f"{url} failed: HTTP {res.status_code} {body}")
  return body


@dataclass
class Scenario:
  name: str
  business_name: str
  address: str
  messages: List[str]
  ops_fallback: str
  market_fallback: str
  people_fallback: str
  financials_fallback: str


def _accept_intake_proposal(
  client, base_payload: Dict[str, Any], proposal: Dict[str, Any]
) -> Dict[str, Any]:
  payload = dict(base_payload)
  payload.update(
    {
      "message": "",
      "response_intent": "accept",
      "proposal_id": proposal.get("id"),
      "proposal_hash": proposal.get("proposal_hash"),
    }
  )
  return _post_json(client, "/api/intake-consult", payload, retries=3)


def _create_session(client) -> Tuple[str, str]:
  res = _post_json(client, "/api/intake-consult/session", {})
  return str(res.get("draft_id") or "").strip(), str(res.get("client_id") or "").strip()


def _fetch_draft(client, draft_id: str) -> Dict[str, Any]:
  return _get_json(client, "/api/intake-consult/draft", {"draft_id": draft_id})


def _ensure_proposal_generated(
  client,
  base_payload: Dict[str, Any],
  scenario: Scenario,
  messages: Iterable[str],
  *,
  max_turns: int = 60,
) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
  queue = list(messages)
  used = 0
  while used < max_turns:
    if queue:
      msg = queue.pop(0)
    else:
      draft = _fetch_draft(client, base_payload["draft_id"])
      active_focus = str(draft.get("active_focus") or "").strip().lower()
      fallbacks = {
        "ops": scenario.ops_fallback,
        "market": scenario.market_fallback,
        "people": scenario.people_fallback,
        "financials": scenario.financials_fallback,
      }
      msg = fallbacks.get(active_focus) or "No additional changes. Please summarize assumptions and continue."
    _post_json(client, "/api/intake-consult", {**base_payload, "message": msg}, retries=3)
    used += 1
    draft = _fetch_draft(client, base_payload["draft_id"])
    proposals = _parse_proposals(draft.get("model_card_proposals_json"))
    _proposal_ids_unique(proposals)
    if proposals:
      return draft, proposals[0], used
  raise AssertionError("No proposal generated after exhausting messages and fallbacks.")


def _accept_all_pending(client, base_payload: Dict[str, Any]) -> None:
  model_card_models = {
    "marketing",
    "pricing",
    "revenue",
    "headcount",
    "fulfillment",
    "ops_concept",
    "milestones",
    "cogs",
    "gna",
  }
  while True:
    draft = _fetch_draft(client, base_payload["draft_id"])
    proposals = _parse_proposals(draft.get("model_card_proposals_json"))
    _proposal_ids_unique(proposals)
    if not proposals:
      return
    proposal = proposals[0]
    model = str(proposal.get("model") or "").strip().lower()
    if model in model_card_models:
      _model_card_accept(client, base_payload["draft_id"], proposal)
    else:
      _accept_intake_proposal(client, base_payload, proposal)


def _drive_to_completion(
  client,
  base_payload: Dict[str, Any],
  scenario: Scenario,
  messages: Iterable[str],
  *,
  max_turns: int = 60
) -> None:
  model_card_models = {
    "marketing",
    "pricing",
    "revenue",
    "headcount",
    "fulfillment",
    "ops_concept",
    "milestones",
    "cogs",
    "gna",
  }
  queue = list(messages)
  turns = 0
  while turns < max_turns:
    draft = _fetch_draft(client, base_payload["draft_id"])
    status = str(draft.get("draft_status") or "").strip().lower()
    if status == "completed":
      return
    proposals = _parse_proposals(draft.get("model_card_proposals_json"))
    _proposal_ids_unique(proposals)
    if proposals:
      proposal = proposals[0]
      model = str(proposal.get("model") or "").strip().lower()
      if model in model_card_models:
        _model_card_accept(client, base_payload["draft_id"], proposal)
      else:
        _accept_intake_proposal(client, base_payload, proposal)
      turns += 1
      continue
    if queue:
      msg = queue.pop(0)
      _post_json(client, "/api/intake-consult", {**base_payload, "message": msg}, retries=3)
      turns += 1
      continue
    active_focus = str(draft.get("active_focus") or "").strip().lower()
    fallbacks = {
      "ops": scenario.ops_fallback,
      "market": scenario.market_fallback,
      "people": scenario.people_fallback,
      "financials": scenario.financials_fallback,
    }
    fallback_msg = fallbacks.get(active_focus)
    if not fallback_msg:
      fallback_msg = "No additional changes. If anything is missing, record 0 and continue."
    _post_json(
      client,
      "/api/intake-consult",
      {**base_payload, "message": fallback_msg},
      retries=3,
    )
    turns += 1
  draft = _fetch_draft(client, base_payload["draft_id"])
  status = str(draft.get("draft_status") or "").strip().lower()
  if status != "completed":
    active_focus = str(draft.get("active_focus") or "").strip().lower()
    messages = _parse_messages(draft.get("messages_json"))
    last_assistant = ""
    for msg in reversed(messages):
      if str(msg.get("role") or "") == "assistant":
        last_assistant = str(msg.get("content") or "")
        break
    safe_tail = last_assistant[:220].encode("ascii", "backslashreplace").decode("ascii")
    print(f"completion_debug status={status} focus={active_focus} last_assistant={safe_tail!r}")
  _assert(status == "completed", f"draft did not complete (status={status})")


def _model_card_edit(
  client,
  draft_id: str,
  model: str,
  updates: List[Dict[str, Any]],
  derived: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  payload = {
    "draft_id": draft_id,
    "action": "edit",
    "model": model,
    "lob_key": "company_total",
    "updates": updates,
    "derived": derived or [],
    "note": "e2e_edit",
  }
  return _post_json(client, "/api/intake-consult/model-cards", payload)


def _model_card_accept(client, draft_id: str, proposal: Dict[str, Any]) -> Dict[str, Any]:
  payload = {
    "draft_id": draft_id,
    "action": "accept",
    "model": proposal.get("model"),
    "lob_key": proposal.get("lob_key") or "company_total",
    "lob_name": proposal.get("lob_name"),
    "updates": proposal.get("updates") or [],
    "derived": proposal.get("derived") or [],
    "proposal_id": proposal.get("id"),
    "proposal_hash": proposal.get("proposal_hash"),
    "apply_to_all_lobs": False,
    "note": "e2e_accept",
  }
  return _post_json(client, "/api/intake-consult/model-cards", payload)


def _seed_ops_models(client, draft_id: str) -> None:
  seeds: List[Tuple[str, List[Dict[str, Any]]]] = [
    (
      "revenue",
      [
        {"key": "units_per_week_capacity", "value": 100, "unit": "units", "time_basis": "week", "rationale": "seed"},
        {"key": "avg_units_per_week_year1", "value": 50, "unit": "units", "time_basis": "week", "rationale": "seed"},
        {"key": "operating_weeks_per_year", "value": 50, "unit": "weeks", "time_basis": "year", "rationale": "seed"},
        {"key": "unit_price", "value": 100, "unit": "USD", "time_basis": "per_unit", "rationale": "seed"},
      ],
    ),
    (
      "fulfillment",
      [
        {"key": "fulfillment_model", "value": "in_house", "unit": None, "time_basis": None, "rationale": "seed"},
        {"key": "who_fulfills", "value": "founder", "unit": None, "time_basis": None, "rationale": "seed"},
        {"key": "lead_time", "value": "7 days", "unit": None, "time_basis": None, "rationale": "seed"},
      ],
    ),
    (
      "ops_concept",
      [
        {"key": "operating_unit", "value": "one unit", "unit": None, "time_basis": None, "rationale": "seed"},
        {"key": "primary_constraint", "value": "capacity", "unit": None, "time_basis": None, "rationale": "seed"},
        {"key": "process_overview", "value": "intake, produce, deliver", "unit": None, "time_basis": None, "rationale": "seed"},
      ],
    ),
    (
      "milestones",
      [
        {
          "key": "milestones",
          "value": [
            {
              "title": "First 50 customers",
              "description": "Reach 50 paying customers.",
              "target_period": "within 6 months",
              "confidence": 0.6,
            }
          ],
          "unit": None,
          "time_basis": None,
          "rationale": "seed",
        }
      ],
    ),
    (
      "headcount",
      [
        {
          "key": "roles",
          "value": [
            {
              "role_title": "Founder",
              "employee_count": 1,
              "hours_per_week": 40,
              "weeks_per_year": 52,
              "hourly_rate_override": 30,
            }
          ],
          "unit": None,
          "time_basis": None,
          "rationale": "seed",
        }
      ],
    ),
    (
      "cogs",
      [
        {"key": "materials_cost_per_unit", "value": 2, "unit": "USD", "time_basis": "per_unit", "rationale": "seed"},
        {
          "key": "direct_fulfillment_cost_per_unit",
          "value": 1,
          "unit": "USD",
          "time_basis": "per_unit",
          "rationale": "seed",
        },
        {
          "key": "other_variable_cost_per_unit",
          "value": 0.5,
          "unit": "USD",
          "time_basis": "per_unit",
          "rationale": "seed",
        },
      ],
    ),
    (
      "gna",
      [
        {"key": "monthly_rent_expense", "value": 500, "unit": "USD", "time_basis": "month", "rationale": "seed"},
        {"key": "monthly_software_expense", "value": 100, "unit": "USD", "time_basis": "month", "rationale": "seed"},
        {"key": "monthly_insurance_expense", "value": 50, "unit": "USD", "time_basis": "month", "rationale": "seed"},
        {"key": "monthly_utilities_expense", "value": 75, "unit": "USD", "time_basis": "month", "rationale": "seed"},
        {"key": "monthly_admin_expense", "value": 50, "unit": "USD", "time_basis": "month", "rationale": "seed"},
        {"key": "other_operating_expense", "value": 200, "unit": "USD", "time_basis": "month", "rationale": "seed"},
      ],
    ),
  ]

  for model, updates in seeds:
    _model_card_edit(client, draft_id, model, updates=updates)
    draft = _fetch_draft(client, draft_id)
    proposals = _parse_proposals(draft.get("model_card_proposals_json"))
    _proposal_ids_unique(proposals)
    proposal = next((p for p in proposals if str(p.get("model") or "") == model), None)
    if proposal:
      _model_card_accept(client, draft_id, proposal)

def _validate_no_silent_commit(
  draft_before: Dict[str, Any], draft_after: Dict[str, Any], proposal: Dict[str, Any]
) -> None:
  patch = proposal.get("patch") if isinstance(proposal.get("patch"), dict) else {}
  _assert(patch, "proposal patch missing; cannot validate commit boundary")
  for key in patch.keys():
    before_val = _get_field_from_draft(draft_before, key)
    after_val = _get_field_from_draft(draft_after, key)
    _assert(
      before_val == after_val,
      f"silent commit detected for {key}: before={before_val!r} after={after_val!r}",
    )


def _validate_committed_values(draft_after: Dict[str, Any], proposal: Dict[str, Any]) -> None:
  patch = proposal.get("patch") if isinstance(proposal.get("patch"), dict) else {}
  _assert(patch, "proposal patch missing; cannot validate commit result")
  for key, payload in patch.items():
    expected = payload.get("value") if isinstance(payload, dict) and "value" in payload else payload
    actual = _get_field_from_draft(draft_after, key)
    _assert(
      actual == expected,
      f"commit mismatch for {key}: expected={expected!r} actual={actual!r}",
    )


def _run_scenario(client, scenario: Scenario) -> None:
  draft_id, client_id = _create_session(client)
  payload_base = {
    "draft_id": draft_id,
    "client_id": client_id or None,
    "business_name": scenario.business_name,
    "address": scenario.address,
    "business_start_date": "2024-01-15",
    "address_street": "123 Main St",
    "address_city": "Sampletown",
    "address_state": "CA",
    "address_zip": "90000",
    "address_country": "USA",
  }

  draft_before = _fetch_draft(client, draft_id)
  draft_after, proposal, used = _ensure_proposal_generated(client, payload_base, scenario, scenario.messages)
  _validate_no_silent_commit(draft_before, draft_after, proposal)

  accept_resp = _accept_intake_proposal(client, payload_base, proposal)
  expected_echo = _format_commit_echo(proposal)
  assistant_message = str(accept_resp.get("assistant_message") or "")
  _assert(
    assistant_message.startswith(expected_echo),
    "post-commit echo missing or mismatched on intake accept",
  )

  draft_committed = _fetch_draft(client, draft_id)
  _validate_committed_values(draft_committed, proposal)

  _accept_all_pending(client, payload_base)

  # Edit flow: marketing budget proposal -> accept -> derived hash check
  _model_card_edit(
    client,
    draft_id,
    "marketing",
    updates=[
      {"key": "monthly_marketing_budget", "value": 2000, "unit": "USD", "time_basis": "month", "rationale": "test"},
      {"key": "primary_channels", "value": "referrals", "unit": None, "time_basis": None, "rationale": "test"},
    ],
  )
  draft = _fetch_draft(client, draft_id)
  proposals = _parse_proposals(draft.get("model_card_proposals_json"))
  _proposal_ids_unique(proposals)
  marketing_prop = next((p for p in proposals if str(p.get("model") or "") == "marketing"), None)
  _assert(marketing_prop is not None, "expected marketing proposal after edit")
  _model_card_accept(client, draft_id, marketing_prop)
  draft_after = _fetch_draft(client, draft_id)
  derived_entry = _get_derived_entry(draft_after, "marketing", "year1_marketing_spend")
  _assert(derived_entry.get("value") == 24000, "marketing derived value not recomputed after accept")
  _assert(derived_entry.get("inputs_hash"), "marketing derived inputs_hash missing")

  # Change input -> derived changes, inputs_hash changes
  prev_hash = derived_entry.get("inputs_hash")
  _model_card_edit(
    client,
    draft_id,
    "marketing",
    updates=[
      {"key": "monthly_marketing_budget", "value": 3000, "unit": "USD", "time_basis": "month", "rationale": "test"},
      {"key": "primary_channels", "value": "referrals", "unit": None, "time_basis": None, "rationale": "test"},
    ],
  )
  draft = _fetch_draft(client, draft_id)
  proposals = _parse_proposals(draft.get("model_card_proposals_json"))
  marketing_prop = next((p for p in proposals if str(p.get("model") or "") == "marketing"), None)
  _assert(marketing_prop is not None, "expected marketing proposal after edit change")
  _model_card_accept(client, draft_id, marketing_prop)
  draft_after = _fetch_draft(client, draft_id)
  derived_entry = _get_derived_entry(draft_after, "marketing", "year1_marketing_spend")
  _assert(derived_entry.get("value") == 36000, "marketing derived value not updated after edit accept")
  _assert(derived_entry.get("inputs_hash") != prev_hash, "marketing derived inputs_hash did not change")

  # Dependency invalidation: pricing unit_price triggers revenue/cogs proposals.
  _model_card_edit(
    client,
    draft_id,
    "pricing",
    updates=[{"key": "unit_price", "value": 9.99, "unit": "USD", "time_basis": "per_unit", "rationale": "test"}],
  )
  draft = _fetch_draft(client, draft_id)
  proposals = _parse_proposals(draft.get("model_card_proposals_json"))
  pricing_prop = next((p for p in proposals if str(p.get("model") or "") == "pricing"), None)
  _assert(pricing_prop is not None, "expected pricing proposal after edit")
  _model_card_accept(client, draft_id, pricing_prop)
  draft_after = _fetch_draft(client, draft_id)
  dependents = _parse_proposals(draft_after.get("model_card_proposals_json"))
  dep_models = sorted({str(p.get("model") or "") for p in dependents})
  _assert(
    any(m in dep_models for m in ("revenue", "cogs")),
    f"expected dependency proposals after pricing accept, got {dep_models}",
  )

  # Post-commit echo should match accepted marketing proposal when model-cards accept is used.
  messages = _parse_messages(draft_after.get("messages_json"))
  last_assistant = ""
  for msg in reversed(messages):
    if str(msg.get("role") or "") == "assistant":
      last_assistant = str(msg.get("content") or "")
      break
  expected_echo = _format_commit_echo(pricing_prop)
  _assert(
    last_assistant.startswith(expected_echo),
    "post-commit echo missing or mismatched after model-cards accept",
  )

  _accept_all_pending(client, payload_base)
  _seed_ops_models(client, draft_id)
  _drive_to_completion(client, payload_base, scenario, scenario.messages[used:])


def main() -> int:
  parser = argparse.ArgumentParser(description="E2E commit-boundary verification for unified intake.")
  parser.add_argument("--skip-service", action="store_true", help="Only run the product scenario.")
  args = parser.parse_args()

  _load_env()
  repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  sys.path.insert(0, os.path.join(repo_root, "python"))
  from api import create_app  # type: ignore

  app = create_app()
  client = app.test_client()

  scenarios = [
    Scenario(
      name="product",
      business_name="DominoForge",
      address="123 Main St, Sampletown, CA 90000, USA",
      messages=[
        "We manufacture custom engraved domino sets (manufacturing business) and sell them online to consumers in the US.",
        "The unit is one finished domino. We can make 500 per week. Price is $5 per domino.",
        "We ship via USPS nationwide and fulfill in-house. Lead time is about 7 days.",
        "Started selling in January 2024.",
        "We target hobbyists and gift buyers across the US. Sales are online only.",
        "Target customers are adults age 25-55 with income roughly $50k-$120k.",
        "We are an LLC with two founders and no other employees.",
        "Monthly marketing budget is $2000. Main channels are Instagram and Etsy ads.",
        "Materials cost is $1 per domino. Other variable cost is $0.50. No other direct fulfillment cost.",
        "Monthly rent is $500. Software is $100. Insurance is $50. Utilities are $75. Other operating is $200.",
        "Last month revenue was $4000, COGS $1200, cash on hand $1500. No debt.",
        "Key people: two founders. One handles production and operations, the other handles sales and marketing. No other employees. Payroll is $0.",
        "People list: [{\"full_name\":\"Alex Founder\",\"role_title\":\"Founder\"},{\"full_name\":\"Jamie Founder\",\"role_title\":\"Founder\"}].",
        "We own about $2000 in equipment and tools. No leases. Initial equity was $5000. Total debt outstanding is $0. Legal entity is an LLC.",
        "Financials: current_revenue=4000, current_cogs=1200, other_operating_expense=200, monthly_rent_expense=500, other_monthly_debt_payments=0, current_payroll=0, current_num_employees=0, current_capex=0, ar_balance=0, ap_balance=0, inventory_balance=500, total_debt_outstanding=0, annual_interest_payment=0, annual_principal_payment=0, owner_compensation=0, cash_on_hand=1500.",
      ],
      ops_fallback="We manufacture custom engraved dominoes; the unit is one finished domino. Capacity is 500 per week, price is $5 per domino, sold online nationwide. Fulfillment is in-house with a 7 day lead time. Started January 2024 and operate as an LLC.",
      market_fallback="Target customers are US hobbyists and gift buyers, ages 25-55 with incomes around $50k-$120k. Sales are online only, primarily via Instagram and Etsy.",
      people_fallback="Key people: Alex Founder (Founder, runs production/operations, 10 years woodworking), Jamie Founder (Founder, runs sales/marketing, 8 years ecommerce). No other people.",
      financials_fallback="As of last month: revenue 4000, cogs 1200, other operating expense 200, rent 500, payroll 0, employees 0, owner compensation 0, capex 0, AR 0, AP 0, inventory 500, total debt outstanding 0, other monthly debt payments 0, annual interest 0, annual principal 0, cash on hand 1500.",
    ),
  ]

  if not args.skip_service:
    scenarios.append(
      Scenario(
        name="service",
        business_name="LedgerLoop",
        address="500 Market St, Sampletown, CA 90000, USA",
        messages=[
          "We provide bookkeeping services for small businesses (service business), mostly remote.",
          "The unit is one monthly bookkeeping package. We can handle 30 clients per month. Price is $400 per client per month.",
          "We deliver remotely. Lead time is about 5 days to close books.",
          "Started selling in 2023.",
          "We are an LLC. The team is just the owner with no employees.",
          "We target US small businesses and get most clients via referrals.",
          "Target customers are owners age 30-55 with income roughly $60k-$150k.",
          "Monthly marketing budget is $500. Main channel is referrals.",
          "Monthly software cost is $150. Insurance is $50. Other operating is $100. Rent is $0. No debt.",
          "Last month revenue was $8000, COGS $300, cash on hand $5000, AR $1000, AP $200.",
          "Key people: the owner/bookkeeper runs the business. No other employees. Payroll is $0.",
          "People list: [{\"full_name\":\"Taylor Owner\",\"role_title\":\"Owner\"}].",
          "We own about $1000 in equipment and tools. No leases. Initial equity was $3000. Total debt outstanding is $0. Legal entity is an LLC.",
          "Financials: current_revenue=8000, current_cogs=300, other_operating_expense=100, monthly_rent_expense=0, other_monthly_debt_payments=0, current_payroll=0, current_num_employees=0, current_capex=0, ar_balance=1000, ap_balance=200, inventory_balance=0, total_debt_outstanding=0, annual_interest_payment=0, annual_principal_payment=0, owner_compensation=0, cash_on_hand=5000.",
        ],
        ops_fallback="We provide monthly bookkeeping packages remotely; the unit is one monthly package. Capacity is 30 clients per month at $400 per client per month. Lead time is about 5 days. Started in 2023 and operate as an LLC.",
        market_fallback="Target customers are US small businesses (B2B). Typical owners are age 30-55 with incomes around $60k-$150k. Clients come mainly from referrals.",
        people_fallback="Key people: Taylor Owner (Owner/Bookkeeper, 12 years bookkeeping, handles client delivery and operations). No other people.",
        financials_fallback="As of last month: revenue 8000, cogs 300, other operating expense 100, rent 0, payroll 0, employees 0, owner compensation 0, capex 0, AR 1000, AP 200, inventory 0, total debt outstanding 0, other monthly debt payments 0, annual interest 0, annual principal 0, cash on hand 5000.",
      )
    )

  for scenario in scenarios:
    print(f"Running scenario: {scenario.name}")
    _run_scenario(client, scenario)
    print(f"Scenario {scenario.name}: PASS")

  print("All scenarios passed.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
