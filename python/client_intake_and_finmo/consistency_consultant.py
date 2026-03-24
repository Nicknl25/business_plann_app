from __future__ import annotations



import json

import os

import time

from pathlib import Path

from typing import Any, Dict, List, Optional



import requests



ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

FINALIZE_TOKEN = "[[CONSISTENCY_PASSED]]"

_RETRYABLE_STATUS = {429, 502, 503, 504}





def _load_root_env() -> None:

  try:

    from dotenv import load_dotenv  # type: ignore

  except Exception:

    return

  try:

    load_dotenv(str(ROOT_ENV_PATH))

  except Exception:

    pass





def _require_openai_key() -> str:

  _load_root_env()

  key = (os.getenv("OPENAI_API_KEY") or "").strip()

  if not key:

    raise RuntimeError("OPENAI_API_KEY is not configured.")

  return key





def _openai_model() -> str:

  _load_root_env()

  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"





def _openai_timeout_seconds() -> int:

  _load_root_env()

  raw = (os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS") or "").strip()

  if raw:

    try:

      return max(30, int(raw))

    except Exception:

      return 180

  return 180





def _format_openai_error(resp: requests.Response) -> str:

  if resp.status_code in _RETRYABLE_STATUS:

    return "We're having trouble reaching our AI service right now. Please try again in a minute."

  return f"OpenAI API error {resp.status_code}: {resp.text[:500]}"





def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:

  timeout = _openai_timeout_seconds()

  last_exc: Optional[Exception] = None

  for attempt in range(3):

    try:

      resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

      if resp.status_code in _RETRYABLE_STATUS and attempt < 2:

        time.sleep(0.75 * (2**attempt))

        continue

      return resp

    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:

      last_exc = exc

      if attempt >= 2:

        raise

      time.sleep(0.75 * (2**attempt))

    except requests.exceptions.ConnectionError as exc:

      last_exc = exc

      if attempt >= 2:

        raise

      time.sleep(0.75 * (2**attempt))

  if last_exc:

    raise last_exc

  raise RuntimeError("OpenAI request failed unexpectedly.")





def _parse_responses_text(data: Dict[str, Any]) -> str:

  output = data.get("output") or []

  chunks: list[str] = []

  for item in output:

    for part in item.get("content", []) or []:

      if part.get("type") == "output_text" and part.get("text"):

        chunks.append(str(part["text"]))

  if not chunks:

    raise RuntimeError("OpenAI response contained no output_text.")

  return "\n".join(chunks).strip()






def _parse_responses_json(data: Dict[str, Any]) -> Dict[str, Any]:

  output = data.get("output") or []

  for item in output:

    for part in item.get("content", []) or []:

      if part.get("type") == "output_text" and part.get("text"):

        raw = str(part["text"]).strip()

        try:

          parsed = json.loads(raw)

        except Exception:

          continue

        if isinstance(parsed, dict):

          return parsed

  raise RuntimeError("OpenAI response contained no JSON object.")



def consistency_solver_proposal_message(

  *,

  intake_context: Dict[str, Any],

  solver_state: Dict[str, Any],

) -> str:
  del intake_context
  scenarios = solver_state.get("client_scenarios") if isinstance(solver_state, dict) else None
  if not isinstance(scenarios, list) or not scenarios:
    scenarios = []
  structural_gap = bool((solver_state or {}).get("structural_gap")) if isinstance(solver_state, dict) else False
  intro = "These are the strongest current options." if structural_gap else "Here are your strategic options."
  lines = [intro]
  for index, scenario in enumerate(scenarios, start=1):
    if not isinstance(scenario, dict):
      continue
    year1 = ((scenario.get("key_metrics") or {}).get("year_1") or {}) if isinstance(scenario.get("key_metrics"), dict) else {}
    year5 = ((scenario.get("key_metrics") or {}).get("year_5") or {}) if isinstance(scenario.get("key_metrics"), dict) else {}
    tradeoff = scenario.get("tradeoff") if isinstance(scenario.get("tradeoff"), dict) else {}
    lines.append(
      (
        f"{index}. {str(scenario.get('scenario_name') or '').strip()}\n"
        f"{str(scenario.get('summary') or '').strip()}\n"
        f"Year 1: Revenue {year1.get('revenue')} | EBITDA {year1.get('ebitda')} | EBITDA margin {year1.get('ebitda_margin')} | "
        f"Payroll {year1.get('payroll')} | Marketing {year1.get('marketing')} | Utilization {year1.get('utilization')}\n"
        f"Year 5: Revenue {year5.get('revenue')} | EBITDA {year5.get('ebitda')} | EBITDA margin {year5.get('ebitda_margin')} | "
        f"Payroll {year5.get('payroll')} | Marketing {year5.get('marketing')} | Utilization {year5.get('utilization')}\n"
        f"Upside: {str(tradeoff.get('upside') or '').strip()} Downside: {str(tradeoff.get('downside') or '').strip()}\n"
        f"Confidence: {str(scenario.get('confidence') or '').strip()}"
      ).strip()
    )
  lines.append("Which option number do you want, or what one numeric change do you want?")
  return "\n\n".join([line for line in lines if str(line or "").strip()]).strip()



def _solver_reply_schema() -> Dict[str, Any]:

  return {
    "name": "consistency_solver_reply",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "intent_type": {
          "type": "string",
          "enum": ["select_option", "modify_option", "ask_question", "reject_all", "unclear"],
        },
        "selected_scenario_id": {"type": ["string", "null"]},
        "reason": {"type": "string"},
        "unit_price_absolute": {"type": ["number", "null"]},
        "price_change_percent": {"type": ["number", "null"]},
        "utilization_percent": {"type": ["number", "null"]},
        "marketing_total_year1_absolute": {"type": ["number", "null"]},
        "marketing_reduction_percent": {"type": ["number", "null"]},
        "other_opex_absolute": {"type": ["number", "null"]},
        "other_opex_reduction_percent": {"type": ["number", "null"]},
        "role_title": {"type": ["string", "null"]},
        "months_until_hire": {"type": ["number", "null"]},
        "milestone_timing_months_max": {"type": ["number", "null"]},
      },
      "required": [
        "intent_type",
        "selected_scenario_id",
        "reason",
        "unit_price_absolute",
        "price_change_percent",
        "utilization_percent",
        "marketing_total_year1_absolute",
        "marketing_reduction_percent",
        "other_opex_absolute",
        "other_opex_reduction_percent",
        "role_title",
        "months_until_hire",
        "milestone_timing_months_max",
      ],
    },
  }



def interpret_consistency_solver_reply(

  *,

  user_message: str,

  last_assistant: str,

  solver_state: Dict[str, Any],

) -> Dict[str, Any]:

  if not str(user_message or "").strip():

    return {}

  scenarios = solver_state.get("client_scenarios") if isinstance(solver_state, dict) else None
  if not isinstance(scenarios, list) or not scenarios:
    scenarios = solver_state.get("scenarios") if isinstance(solver_state, dict) else None

  if not isinstance(scenarios, list) or not scenarios:

    return {}

  api_key = _require_openai_key()

  model = _openai_model()

  schema_wrapper = _solver_reply_schema()

  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are interpreting a client's reply to controller-built consistency optimization options.\n"
          "The controller owns the math. You must not invent new calculations.\n"
          "Return select_option when the client clearly chooses one of the listed options.\n"
          "Return modify_option when the client chooses an option but wants one numeric change, such as a different price change, utilization level, marketing cut, other operating expense cut, hire timing, or milestone timing.\n"
          "When the client gives a percent like 5%, return the percent number only (for example 5, not 0.05).\n"
          "When the client gives utilization like 75%, return 75 in utilization_percent.\n"
          "Only populate numeric override fields when the user explicitly changes that thing.\n"
          "If the client is only asking what an option means, return ask_question.\n"
          "If the client rejects everything without choosing a path, return reject_all.\n"
          "If meaning is ambiguous, return unclear."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "assistant_message": str(last_assistant or "").strip(),
            "solver_state": {
              "status": solver_state.get("status") if isinstance(solver_state, dict) else None,
              "structural_gap": solver_state.get("structural_gap") if isinstance(solver_state, dict) else None,
              "client_scenarios": scenarios,
            },
            "user_message": str(user_message or "").strip(),
          },
          ensure_ascii=False,
        ),
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema_wrapper["name"],
        "schema": schema_wrapper["schema"],
        "strict": True,
      }
    },
  }

  url = "https://api.openai.com/v1/responses"

  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

  resp = _post_openai(url=url, headers=headers, payload=payload)

  if resp.status_code >= 400:

    return {}

  try:

    parsed = _parse_responses_json(resp.json())

  except Exception:

    return {}

  return parsed if isinstance(parsed, dict) else {}


def _marketing_rewrite_schema() -> Dict[str, Any]:

  return {
    "name": "consistency_marketing_rewrite",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "marketing_plan_summary": {"type": "string"},
        "marketing_basis_summary": {"type": "string"},
      },
      "required": ["marketing_plan_summary", "marketing_basis_summary"],
    },
  }


def rewrite_marketing_state_after_consistency(

  *,

  intake_context: Dict[str, Any],

  existing_marketing_plan_summary: str,

  existing_marketing_basis_summary: str,

  scenario_context: Optional[Dict[str, Any]] = None,

) -> Dict[str, str]:

  api_key = _require_openai_key()

  model = _openai_model()

  schema_wrapper = _marketing_rewrite_schema()

  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are updating persisted marketing summaries after a consistency-driven business-plan adjustment.\n"
          "Rewrite the stored marketing_plan_summary and marketing_basis_summary so they stay aligned with the current plan.\n"
          "Use the full persisted context provided. Reflect the current Year-1 marketing budget and percent of revenue, and if a consistency scenario changed marketing, acknowledge the updated posture in plain business language.\n"
          "Keep the same business, geography, stage, and target-market framing unless the context clearly changed them.\n"
          "Do not invent new strategy unrelated to the current plan.\n"
          "marketing_plan_summary should stay as a concise strategic narrative.\n"
          "marketing_basis_summary should stay as a concise rationale for the current quantified marketing setup.\n"
          "Return JSON only."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "intake_context": intake_context,
            "existing_marketing_plan_summary": str(existing_marketing_plan_summary or "").strip(),
            "existing_marketing_basis_summary": str(existing_marketing_basis_summary or "").strip(),
            "scenario_context": scenario_context or {},
          },
          ensure_ascii=False,
        ),
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema_wrapper["name"],
        "schema": schema_wrapper["schema"],
        "strict": True,
      }
    },
  }

  url = "https://api.openai.com/v1/responses"

  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

  resp = _post_openai(url=url, headers=headers, payload=payload)

  if resp.status_code >= 400:

    raise RuntimeError(_format_openai_error(resp))

  parsed = _parse_responses_json(resp.json())
  return parsed if isinstance(parsed, dict) else {}

def consistency_chat_turn(

  *,

  intake_context: Dict[str, Any],

  conversation_messages: List[Dict[str, str]],

) -> Dict[str, Any]:
  del intake_context, conversation_messages
  # Legacy consistency chat is disabled. The live intake path now uses the
  # deterministic table-review -> solver flow in intake_consult.py.
  return {"assistant_message": "", "finalize_ready": True}

  """

  Consistency check conversation turn.



  Returns:

    { "assistant_message": str, "finalize_ready": bool }

  """

  api_key = _require_openai_key()

  model = _openai_model()



  system = f"""

You are a senior business consultant performing a Consistency Check on a business intake model.



This is NOT financial modeling. This is coherence and reality checking across the already-collected intake facts.



Goals:

- Detect contradictions or obviously missing reality inputs across operations, target market, people, and financials.

- Resolve them with the minimum number of clarifying questions.

- Do NOT proceed until the model is coherent.

- Be a reconciler, not a resetter. Prefer the smallest coherent interpretation or adjustment that preserves the captured model.

- A deterministic controller-built Year-1 financial summary may be present in the context as consistency_financial_summary and consistency_financial_table_markdown. Treat those values as authoritative for Year-1 financial math. Do not recalculate them yourself.



Rules of engagement:

- Ask ONE thing per message. Never bundle multiple questions.

- Infer when possible; clarify only when inference is ambiguous.

- If the user gives an edit/correction (e.g., "change rent to 900"), accept it and continue without restarting.

- No lecturing, no scolding. Be direct and practical.

- Treat business_stage as a soft plausibility prior. Use it to decide whether to infer-and-confirm a likely explanation or ask a clarification.

- Never assume a value is true just because a stage makes it plausible; propose the likely interpretation and confirm it.

- Use the full persisted context already provided in JSON. Do not ignore a broad set of captured facts because one label appears stale.

- Distinguish three categories of truth before you reason:
  1. current snapshot facts
  2. Year-1 / launch-plan modeled values
  3. milestone or growth claims

- current snapshot facts describe what is true as of the snapshot date.

- Year-1 / launch-plan modeled values describe the planned launch-year business, not necessarily the current snapshot. These must NOT be zeroed out just because the business is pre-revenue or opening soon.

- milestone or growth claims are targets that must be checked against capacity, staffing, timing, geography, and market reach.

- inferred roles, hiring timing, modeled payroll, modeled revenue, modeled COGS, and modeled marketing are planning values unless the context clearly says they are current realized values.

- pre-revenue means the current snapshot may still be light or zero. It does NOT mean planned launch-year staffing, payroll, revenue, COGS, or marketing should be wiped out.

- Taxes may appear as 0 in the controller-built financial summary because tax modeling is not implemented yet. Treat that as an intentional placeholder, not a contradiction.

- early-stage usually means the business has begun operating or ramping but is not yet fully stable. Treat uneven staffing, ramping revenue, early strain, and partially built systems as potentially coherent if the rest of the model supports that.

- operating means the business already has a functioning base of clients, workflows, and known channels. Do not force operating businesses back into startup-style interpretations unless the concrete facts clearly require it.

- Use business_stage explicitly when checking narrative coherence:
  - operating businesses should not sound like they are still purely in discovery/testing mode unless the facts clearly support that.
  - pre-revenue businesses should not be described like mature scaled operators with established retention, channel optimization, or repeat demand unless the facts clearly support that.
  - early-stage businesses should usually read like they are ramping, proving repeatability, and managing early strain rather than behaving like either a launch-only concept or a mature optimized operator.

- If business_stage conflicts with many concrete operating facts, treat that as a stage interpretation issue to reconcile first. Do NOT zero out other values by default.

- For early-stage and operating businesses, do not erase current operating facts just because some modeled Year-1 values or milestone targets are also present. First decide whether the model is mixing current-state and forward-plan values, then reconcile that mix explicitly.


What to check (illustrative, not exhaustive):

- Economic flow contradictions (e.g., lease exists but rent/debt payments are 0; revenue exists but AR/cash both 0; inventory business with inventory 0, etc.)

- Capacity vs revenue plausibility (e.g., units/week and price imply revenue scale; flag only if wildly inconsistent).

- People reality vs payroll/owner pay (e.g., founder working but owner_compensation 0 — clarify once).

- Debt/funding consistency (e.g., assets exist but no equity/loans captured).

- Marketing consistency (e.g., marketing budget exists but marketing percent does not line up with revenue, or market-support signals do not plausibly support the modeled Year-1 demand).

- Stage/narrative consistency (e.g., operating business with startup-style marketing language, pre-revenue business described like a mature scaled operator, or staffing/revenue/acquisition language that materially conflicts with the stated stage).

- Milestone realism (e.g., the stated 12-month target requires more capacity, staffing, utilization, geography reach, or timing than the current plan supports).

- Year-1 financial viability using the deterministic controller-built financial summary when provided.

- Distinguish true contradictions from valid planning structure:
  - A pre-revenue business may still have a non-zero Year-1 modeled payroll, revenue, COGS, marketing budget, and planned roles.
  - An early-stage business may show both real current operations and larger Year-1 modeled targets at the same time.
  - An operating business may show optimization, retention, repeat demand, and existing payroll while still carrying future hiring plans and milestone targets.
  - Do NOT treat planned roles or modeled Year-1 values as current snapshot employees or current historical revenue unless the context says so.

- If the model contains both current-state values and forward-plan values, prefer reconciling them by naming the distinction clearly rather than treating one side as invalid by default.


Resolution behavior:

- Surface the single most important inconsistency first.

- Ask a concise clarifying question to reconcile it.

- Once reconciled, move to the next most important inconsistency.

- Prefer the lightest coherent fix:
  - reinterpret a stale label
  - reclassify a value as planned instead of current
  - adjust a milestone target
  - push a milestone timing assumption
  - ask for one specific correction

- Do NOT flatten values to zero unless the user clearly confirms they should be zero.

- When checking milestones, reason from the full captured plan and decide whether the milestone is:
  - plausible as stated
  - plausible only with driver changes
  - not plausible on the current plan

- If a milestone is not plausible, propose one concrete revision and ask for confirmation.

- When the main issue is financial viability, use the controller-built financial summary/table as the source of truth for revenue, EBITDA, interest, taxes, and net income. Do not make up alternative numbers.

- Do NOT build your own financial table, financial snapshot, launch-plan rollup, or line-item paragraph summary. The controller owns the Year-1 financial table and will show it later.

- Do NOT restate controller-owned financial line items in prose once the model is coherent enough to proceed. Your job is to reconcile the model, not to present the final financial close.

- Keep each issue tight:
  - what conflicts
  - what it most likely means
  - one recommended adjustment
  - one question

- When everything is coherent enough to proceed, say so briefly and then append the token {FINALIZE_TOKEN} on its own line.



Fact-bearing templates (STRICT):

- The intake is a living model. Any text that references already-known facts must stay correct if those facts change later.

- For any value that already exists in the provided context JSON, do NOT print the literal value.

- Instead, reference the fact using this placeholder syntax exactly:

  {{{{fact:business.name}}}}

  {{{{fact:ops.unit_price}}}}

  {{{{fact:financials.initial_lease}}}}

  {{{{fact:financials.other_operating_expense}}}}

  {{{{fact:financials.current_revenue}}}}



  {{{{fact:financials.marketing_total_year1}}}}

- You may ONLY use existing, whitelisted fact keys. Do NOT invent new keys, paths, or formats.

- Allowed groups/fields you may reference:

  - business: name, address, start_date

  - ops: consumer_type, business_type, business_stage, unit_name, unit_description, unit_cadence, units_per_week_capacity, units_per_period_capacity, unit_price, shipping_method, sales_modality, geographic_scope, geographic_coverage, countries, milestones, capacity_driver, primary_growth_lever, legal_entity

  - market: consumer_type, target_market_summary

  - people: key_people_summary

  - financials: current_revenue, current_cogs, marketing_total_year1, marketing_percent_of_revenue, other_operating_expense, monthly_rent_expense, future_rent_expected, other_monthly_debt_payments, current_payroll, current_num_employees, current_capex, ar_balance, ap_balance, inventory_balance, initial_assets, initial_lease, initial_equity, total_debt_outstanding, annual_interest_payment, annual_principal_payment, owner_compensation, cash_on_hand

""".strip()



  context_blob = json.dumps(intake_context, ensure_ascii=False)

  context_msg = "Current intake model context (JSON):\n" + context_blob



  url = "https://api.openai.com/v1/responses"

  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

  payload = {

    "model": model,

    "input": [

      {"role": "system", "content": system},

      {"role": "user", "content": context_msg},

      *conversation_messages,

    ],

  }



  resp = _post_openai(url=url, headers=headers, payload=payload)

  if resp.status_code >= 400:

    raise RuntimeError(_format_openai_error(resp))



  text = _parse_responses_text(resp.json())

  finalize_ready = FINALIZE_TOKEN in text

  text = text.replace(FINALIZE_TOKEN, "").strip()

  return {"assistant_message": text, "finalize_ready": finalize_ready}



