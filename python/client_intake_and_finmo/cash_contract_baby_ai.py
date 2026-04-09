from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests

try:
  from realism_memo import load_realism_memo_grid_advisory_prompt, normalize_realism_memo_payload  # type: ignore
except Exception:
  try:
    from client_intake_and_finmo.realism_memo import load_realism_memo_grid_advisory_prompt, normalize_realism_memo_payload  # type: ignore
  except Exception:
    def load_realism_memo_grid_advisory_prompt() -> str:
      return "The realism memo is additional context only."

    def normalize_realism_memo_payload(payload: Any) -> Dict[str, Any]:
      return {"status": "not_generated", "issues": []}


_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _prompt_library_dir() -> Path:
  return Path(__file__).resolve().parent / "prompts" / "quarter_grid"


def _load_planning_mode_prompt_file(planning_mode: str) -> str:
  mode = str(planning_mode or "").strip().lower() or "turnaround"
  path = _prompt_library_dir() / f"{mode}.md"
  try:
    return path.read_text(encoding="utf-8").strip()
  except Exception:
    return ""


def planning_mode_text(planning_mode: str) -> str:
  mode = str(planning_mode or "").strip().lower() or "turnaround"
  prompt_file_text = _load_planning_mode_prompt_file(mode)
  if prompt_file_text:
    return prompt_file_text
  return {
    "turnaround": (
      "Assume you are allowed to use every listed variable as part of one coherent repair plan for this actual company. "
      "Realistically, what would make this business profitable as soon as it can become profitable without breaking business reality?"
    ),
    "normalize": (
      "This case may be over-optimistic or commercially overstated rather than distressed. "
      "Normalize the plan to something believable for the company's stage and business model."
    ),
    "rebalance": (
      "This case appears directionally sound but misbalanced. "
      "Rebalance the model to a more believable operating path for the company's stage."
    ),
  }.get(mode, "Build a realistic business plan.")


def _require_openai_key() -> str:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def _openai_model() -> str:
  return (
    os.getenv("CONSISTENCY_GPT_STRATEGY_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "gpt-5.1"
  ).strip() or "gpt-5.1"


def _timeout_env_int(name: str, default: int) -> int:
  raw = (os.getenv(name) or "").strip()
  if not raw:
    return default
  try:
    return max(15, int(raw))
  except Exception:
    return default


def _openai_timeout_seconds() -> Optional[int]:
  return None


def _post_openai(
  *,
  url: str,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  timeout_seconds: Optional[int] = None,
  max_attempts: int = 3,
) -> requests.Response:
  attempts = max(1, int(max_attempts or 1))
  last_exc: Optional[Exception] = None
  for attempt in range(attempts):
    try:
      request_kwargs: Dict[str, Any] = {
        "headers": headers,
        "json": payload,
      }
      if timeout_seconds is not None:
        request_kwargs["timeout"] = max(15, int(timeout_seconds))
      resp = requests.post(url, **request_kwargs)
      if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
        time.sleep(0.75 * (2 ** attempt))
        continue
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as exc:
      last_exc = exc
      if attempt >= attempts - 1:
        raise
      time.sleep(0.75 * (2 ** attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


def _parse_json_response(data: Dict[str, Any]) -> Dict[str, Any]:
  for item in data.get("output") or []:
    if not isinstance(item, dict):
      continue
    for part in item.get("content") or []:
      if not isinstance(part, dict):
        continue
      parsed = part.get("parsed")
      if isinstance(parsed, dict):
        return parsed
      raw = str(part.get("text") or "").strip()
      if not raw:
        continue
      try:
        parsed = json.loads(raw)
      except Exception:
        continue
      if isinstance(parsed, dict):
        return parsed
  return {}


def _safe_float_or_none(value: Any) -> Optional[float]:
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return float(number)


def _normalize_cash_contract(contract: Dict[str, Any]) -> Dict[str, Any]:
  if not isinstance(contract, dict) or not contract:
    return {}
  normalized = dict(contract)
  envelope = normalized.get("cash_shape_envelope")
  if not isinstance(envelope, list):
    return normalized

  normalized_envelope: List[Dict[str, Any]] = []
  for item in envelope:
    if not isinstance(item, dict):
      continue
    quarter_index = int(_safe_float_or_none(item.get("quarter_index")) or 0)
    if quarter_index < 2 or quarter_index > 20:
      continue
    next_item = dict(item)
    next_item["quarter_index"] = quarter_index
    min_pct = _safe_float_or_none(next_item.get("min_pct_change_from_prior"))
    max_pct = _safe_float_or_none(next_item.get("max_pct_change_from_prior"))
    if min_pct is not None and max_pct is not None and min_pct > max_pct:
      next_item["min_pct_change_from_prior"] = max_pct
      next_item["max_pct_change_from_prior"] = min_pct
    normalized_envelope.append(next_item)

  normalized_envelope.sort(key=lambda item: int(item.get("quarter_index") or 0))
  normalized["cash_shape_envelope"] = normalized_envelope
  return normalized


def _realism_memo_prompt_block(source_row: Dict[str, Any]) -> str:
  memo = normalize_realism_memo_payload(
    source_row.get("realism_memo_json") if isinstance(source_row, dict) else {}
  )
  issues = memo.get("issues") if isinstance(memo.get("issues"), list) else []
  if not issues:
    return ""
  issue_lines: List[str] = []
  for item in issues:
    if not isinstance(item, dict):
      continue
    issue = str(item.get("issue") or "").strip()
    detail = str(item.get("detail") or "").strip()
    if not issue or not detail:
      continue
    issue_lines.append(f"- {issue} {detail}".strip())
  if not issue_lines:
    return ""
  return (
    "Advisory realism memo:\n"
    + load_realism_memo_grid_advisory_prompt().strip()
    + "\n"
    + "\n".join(issue_lines)
    + "\n\n"
  )


def _sanitize_payload(value: Any) -> Any:
  if isinstance(value, dict):
    return {str(k or ""): _sanitize_payload(v) for k, v in value.items()}
  if isinstance(value, list):
    return [_sanitize_payload(item) for item in value]
  return value


def _contract_schema() -> Dict[str, Any]:
  return {
    "name": "binding_cash_contract",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "summary": {"type": "string"},
        "strategy_interpretation": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "value": {"type": "string", "enum": ["reinvest", "preserve_cash", "shareholder_return", "balanced"]},
            "label": {"type": "string"},
            "posture": {"type": "string"},
            "visual_intent": {"type": "string"},
            "reality_basis": {"type": "string"},
          },
          "required": ["value", "label", "posture", "visual_intent", "reality_basis"],
        },
        "starting_cash_anchor": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "amount": {"type": "number"},
            "rationale": {"type": "string"},
          },
          "required": ["amount", "rationale"],
        },
        "cash_shape_envelope": {
          "type": "array",
          "minItems": 19,
          "maxItems": 19,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "quarter_index": {"type": "integer", "minimum": 2, "maximum": 20},
              "min_pct_change_from_prior": {"type": "number", "minimum": -100},
              "max_pct_change_from_prior": {"type": "number", "minimum": -100},
              "shape_note": {
                "type": "string",
                "enum": ["buffer_build", "slower_build", "flattening", "deployment_window", "rebuild", "steady_retention"],
              },
              "reason": {"type": "string"},
            },
            "required": [
              "quarter_index",
              "min_pct_change_from_prior",
              "max_pct_change_from_prior",
              "shape_note",
              "reason",
            ],
          },
        },
        "reality_guardrails": {
          "type": "array",
          "minItems": 2,
          "maxItems": 8,
          "items": {"type": "string"},
        },
        "lever_freedom_rule": {"type": "string"},
        "non_overlap_rule": {"type": "string"},
      },
      "required": [
        "summary",
        "strategy_interpretation",
        "starting_cash_anchor",
        "cash_shape_envelope",
        "reality_guardrails",
        "lever_freedom_rule",
        "non_overlap_rule",
      ],
    },
    "strict": True,
  }


def _validation_schema() -> Dict[str, Any]:
  return {
    "name": "binding_cash_contract_validation",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "status": {"type": "string", "enum": ["pass", "fail"]},
        "cash_band_compliance": {"type": "string", "enum": ["pass", "fail"]},
        "grid_internal_consistency": {"type": "string", "enum": ["pass", "fail"]},
        "primary_failure_domain": {"type": "string", "enum": ["none", "cash_bands", "grid_consistency", "both"]},
        "summary": {"type": "string"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "revision_instructions": {"type": "string"},
      },
      "required": [
        "status",
        "cash_band_compliance",
        "grid_internal_consistency",
        "primary_failure_domain",
        "summary",
        "reasons",
        "revision_instructions",
      ],
    },
    "strict": True,
  }


def _call_json_schema_prompt(
  *,
  system_text: str,
  user_text: str,
  schema: Dict[str, Any],
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": [{"type": "input_text", "text": system_text}]},
      {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema["name"],
        "schema": schema["schema"],
        "strict": True,
      }
    },
  }
  response = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers=headers,
    payload=payload,
    timeout_seconds=_openai_timeout_seconds(),
    max_attempts=2,
  )
  if response.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
  return _parse_json_response(response.json())


def build_binding_cash_contract(
  *,
  source_row: Dict[str, Any],
  governor_payload: Dict[str, Any],
  grid_rows: List[Dict[str, Any]],
  planning_mode: str,
) -> Dict[str, Any]:
  cash_strategy_context = governor_payload.get("cash_strategy_context") if isinstance(governor_payload, dict) else {}
  if not isinstance(cash_strategy_context, dict) or not str(cash_strategy_context.get("value") or "").strip():
    return {}
  schema = _contract_schema()
  realism_memo_block = _realism_memo_prompt_block(source_row)
  system_text = (
    "You are a baby-AI cash constraint engine. Your only job is to create a binding, reality-based cash-shape contract for the main quarter-grid planner.\n"
    "You are not the business planner. You are not allowed to write the grid, choose levers, or choose exact row values.\n"
    "Your contract must center on cash itself: starting cash, quarter-to-quarter cash evolution, business reality, and the selected cash strategy.\n"
    "Ground your cash judgment primarily in the cash_reality_context when it is present.\n"
    + planning_mode_text(planning_mode)
  )
  user_text = "".join(
    [
      "Create the binding cash-shape contract for this business.\n",
      "This contract is cash-first, not lever-first.\n",
      "Base your reasoning on the actual business model, business type, opening cash, scale, debt load, operating reality, realism issues, and the selected cash strategy.\n",
      "When cash_reality_context is present in the governor payload, treat it as your primary grounding packet for business reality.\n",
      "The provided row context intentionally shows only Quarter 1 values. Quarter 2 through Quarter 20 row values are intentionally blank and carry no planning authority.\n",
      "Do not reconstruct, preserve, or stay near any synthetic later-quarter spread pattern from the row context.\n",
      "Your main deliverable is a realistic quarter-by-quarter cash_shape_envelope for the Cash output row.\n",
      "The envelope must be sequential, not simultaneous.\n",
      "Do not prescribe Quarter 1 cash. Quarter 1 cash will be supplied by the app from the existing Q1 grid path.\n",
      "Return envelope entries only for Quarter 2 through Quarter 20.\n",
      "Treat the client's intake cash as opening cash only, not as a Quarter 1 ending-cash target.\n",
      "Quarter 2 should be expressed as a percentage-change band from the Quarter 1 ending cash anchor that the app supplies.\n",
      "Quarter 3 and later should each be expressed as a percentage-change band from the prior quarter's resulting cash band.\n",
      "For each quarter, provide only:\n",
      "- min_pct_change_from_prior / max_pct_change_from_prior\n",
      "Use whole percent points, not ratio decimals. Examples: use 30 for 30%, -15 for -15%, 5 for 5%. Do not use 0.3 for 30% or -0.15 for -15%.\n",
      "Always put the lower percentage in min_pct_change_from_prior and the higher percentage in max_pct_change_from_prior, even when both are positive.\n",
      "Those percentage-change bands will be converted by the app into actual cash bands before the main planner sees them.\n",
      "The envelope is not an exact target. It is a realistic allowed cash range for each quarter.\n",
      "Build one sequential cash path from the app-supplied Quarter 1 ending cash anchor forward, quarter by quarter.\n",
      "Because Quarter 1 is app-owned, your sequential path begins at Quarter 2.\n",
      "Every quarter from Quarter 2 through Quarter 20 is an active cash decision.\n",
      "Do not leave any later quarter on autopilot, and do not carry prior-quarter cash behavior forward by inertia.\n",
      "A repeated or flat-looking quarter is acceptable only when that repetition is itself the deliberate realistic answer for that specific period.\n",
      "Your cash path must be feasible for the business, not just strategy-consistent in theory.\n",
      "Think about realistic cash absorption capacity: how much surplus cash this business can credibly redeploy, retain, defer, or extract through normal levers such as capex, staffing, marketing, debt behavior, working capital, and timing.\n",
      "Do not prescribe a cash path that would require more deployment than the business could realistically absorb.\n",
      "If the business is likely to generate more cash than it can credibly redeploy in a given horizon, relax the cash path instead of forcing an unrealistically low balance.\n",
      "If a quarter would only be feasible with implausibly small retained cash or implausibly large deployment, widen that quarter and the next few quarters rather than forcing the planner into infeasible bands.\n",
      "Do not pin cash near the opening cash seed for long stretches unless the business reality truly supports near-total ongoing absorption of surplus cash.\n",
      "Use the available grid rows as clues to the kinds of levers the main planner can actually use later.\n",
      "Use the shape_note field to indicate the expected quarter behavior such as buffer_build, slower_build, flattening, deployment_window, rebuild, or steady_retention.\n",
      "Honor the selected strategy aggressively enough that it is visible in the cash path, not just mentioned in prose.\n",
      "Do not default to mostly-positive bands every quarter when the selected strategy and business reality support visible deployment or flatter periods.\n",
      "Make the envelope materially distinct enough that the chosen cash strategy creates visible cash movement rather than a generic staircase.\n",
      "But keep it reality-based for this specific business. Do not create theatrical or fantasy cash swings.\n",
      "Avoid lazy, repetitive, or sloppy quarter bands. The periods should read like a deliberate, grounded cash path.\n",
      "Make sure each quarter's min_pct_change_from_prior is less than or equal to its max_pct_change_from_prior so the converted cash bands are coherent.\n",
      "Use tighter bands in the quarters that are meant to visibly express the strategy. Do not leave deployment_window, flattening, or steady_retention quarters with so much upside that the cash posture disappears.\n",
      "Quarter-role semantics matter:\n",
      "- buffer_build: positive build is allowed, especially early, but avoid needless huge upside unless business reality clearly supports it\n",
      "- slower_build: still positive overall, but narrower and more moderated than a pure build quarter\n",
      "- deployment_window: this quarter should visibly consume or constrain cash; for reinvest or shareholder_return, do not casually use a generous positive max band if the business can support a flatter or negative quarter\n",
      "- flattening: keep this near-flat or mildly negative/positive; do not let it look like an ordinary growth quarter\n",
      "- rebuild: allow recovery after deployment, but keep it disciplined and not explosively generous by default\n",
      "- steady_retention: use a controlled believable path; bands here should usually be narrower than early build phases\n",
      "If the selected strategy is reinvest, be willing to use real deployment quarters with flat or negative movement when the business can credibly absorb cash into hiring, capex, marketing, or other realistic uses.\n",
      "If the selected strategy is preserve_cash, favor positive but disciplined accumulation and avoid unnecessarily wide upside bands.\n",
      "If the selected strategy is shareholder_return, once a believable cushion exists, be willing to use flatter or negative quarters rather than letting cash compound upward by default.\n",
      "If the selected strategy is balanced, mix build, flattening, and selective deployment without collapsing into a pure staircase.\n",
      "The lever_freedom_rule should explicitly say that the main planner may use any realistic lever in the grid to satisfy the cash constraint and is not limited to preselected cash rows.\n",
      "The non_overlap_rule should explain how you avoided vague, repetitive, or internally muddled bands across the horizon.\n",
      "Do not prescribe specific levers or restrict the planner to a short list of rows. The main planner may use any lever necessary later.\n",
      "Do not choose exact numeric row values or do the planner's job.\n",
      "Do make the cash contract concrete enough that a validator can later judge pass/fail against the returned Cash row bands.\n\n",
      realism_memo_block,
      "Governor context payload:\n",
      json.dumps(_sanitize_payload(governor_payload), ensure_ascii=False),
      "\n\nAvailable grid rows:\n",
      json.dumps(_sanitize_payload(grid_rows), ensure_ascii=False),
      "\n",
    ]
  )
  return _normalize_cash_contract(
    _call_json_schema_prompt(system_text=system_text, user_text=user_text, schema=schema)
  )


def validate_binding_cash_contract(
  *,
  source_row: Dict[str, Any],
  governor_payload: Dict[str, Any],
  contract: Dict[str, Any],
  grid_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
  planning_mode: str,
) -> Dict[str, Any]:
  if not isinstance(contract, dict) or not contract:
    return {
      "status": "pass",
      "cash_band_compliance": "pass",
      "grid_internal_consistency": "pass",
      "primary_failure_domain": "none",
      "summary": "No binding cash contract present.",
      "reasons": [],
      "revision_instructions": "",
    }
  schema = _validation_schema()
  realism_memo_block = _realism_memo_prompt_block(source_row)
  system_text = (
    "You are a baby-AI cash constraint validator. Your only job is to judge whether the finished grid obeys the binding cash constraint.\n"
    "You are not allowed to rewrite the grid, choose exact row values, or invent new business logic. Judge pass/fail only.\n"
    "Judge only the quarter-grid response itself: its returned row bands, row patterns, and the Cash output row bands.\n"
    "Do not judge downstream solver behavior, implied final financial statements, or any outcome that is not directly visible in the grid.\n"
    "Use the contract itself, the opening-cash anchor, the feasibility-owned Q1 cash anchor when present, the sequential quarter-to-quarter cash-change guidance, and the Cash output row bands.\n"
    "Treat the cash_shape_envelope as the primary compliance standard for the Cash row.\n"
    "Honor the contract's lever_freedom_rule: do not fail the grid just because the planner used different realistic levers than you might have chosen.\n"
    "Your review has two layers only: first cash-band compliance, then non-cash grid internal consistency with that hard cash law.\n"
    "If authoritative_cash_bands are present, they are the controlling cash implementation and should dominate your cash-band judgment.\n"
    "Do not blend those two layers together. A cash-band failure is different from a non-cash grid-consistency failure.\n"
    "Treat synthetic spread-placeholder rows as non-authoritative and not as a justification for keeping discretionary later-quarter rows near a flat starting pattern.\n"
    "Q1 is a feasibility-owned anchor quarter, not a strategy-expression quarter. Do not fail Q1 just because it does not visually express the selected cash strategy.\n"
    "Q2 through Q20 should be judged on whether they respond realistically to the cash law and visibly express the selected strategy rather than whether they stay close to any spread-placeholder pattern.\n"
    "You should also judge whether the contract itself is strategy-committed enough. If the selected strategy is reinvest, shareholder_return, or balanced, do not accept a cash path that still behaves like a comfortable staircase unless the business reality clearly forces that outcome.\n"
    "Quarter-role semantics matter: deployment_window and flattening quarters should not be treated as ordinary upward-growth quarters when the strategy calls for visible deployment or constraint.\n"
    "Bands that are so wide on the upside that they erase the intended posture should count against cash-band compliance.\n"
    "Do not require the non-cash rows to look ideal; only require them to be plausibly consistent with operating inside the hard cash bands.\n"
    "Be strict, but do not require theatrical swings.\n"
    + planning_mode_text(planning_mode)
  )
  user_text = "".join(
    [
      "Validate whether this candidate quarter grid obeys the binding cash constraint.\n",
      "Step 1: decide cash_band_compliance.\n",
      "The row context intentionally shows only Quarter 1 values. Do not infer later-quarter defaults or give authority to any synthetic spread pattern beyond Quarter 1.\n",
      "Focus first on whether the Cash output row stays within the realistic sequential cash law quarter by quarter.\n",
      "Treat Q1 as the app-owned feasibility anchor when q1_cash_anchor is present in the contract.\n",
      "Judge strategy expression primarily from Q2 through Q20, not from Q1.\n",
      "If authoritative_cash_bands are present in the contract, treat those app-derived dollar cash bands as the controlling implementation of the envelope and judge the Cash row against them first.\n",
      "If the Cash row matches the authoritative cash bands, mark cash_band_compliance as pass unless there is a clear contradiction inside the contract itself.\n",
      "Do not automatically pass cash_band_compliance just because the app-derived bands were copied correctly; if those bands themselves are too soft to express the selected strategy and quarter roles, that is still a cash-band problem.\n",
      "Also fail cash_band_compliance if the contract itself appears infeasible for this business: for example, if the cash path assumes more sustained deployment or absorption than the available business levers could plausibly support.\n",
      "Step 2: decide grid_internal_consistency.\n",
      "Then check whether the non-cash rows are plausibly consistent with operating inside that hard cash law.\n",
      "Use broad internal-consistency questions only: do the non-cash rows make it believable that management could operate inside those cash bands, given the business context and reality guardrails?\n",
      "Do not treat mimicry of spread-placeholder rows in Q2 through Q20 as evidence of realism by itself, especially on discretionary schedule rows such as capex, debt movement, or other capital-allocation rows.\n",
      "Do not fail the grid just because you would have preferred different lever choices. The planner may use any lever necessary so long as the cash constraint is obeyed realistically.\n",
      "If cash_band_compliance passes and the non-cash rows are at least plausibly coherent with the hard cash bands, the overall status should pass.\n",
      "Do not fail the grid for solver-stage implications or inferred accounting outcomes that are not directly observable from the returned bands.\n",
      "If it fails, explain why and give revision instructions for the primary planner GPT.\n",
      "Do not propose exact numbers.\n\n",
      realism_memo_block,
      "Governor context payload:\n",
      json.dumps(_sanitize_payload(governor_payload), ensure_ascii=False),
      "\n\nQ1-anchored row context:\n",
      json.dumps(_sanitize_payload(grid_rows), ensure_ascii=False),
      "\n\nBinding cash constraint:\n",
      json.dumps(_sanitize_payload(contract), ensure_ascii=False),
      "\n\nCandidate grid response:\n",
      json.dumps(_sanitize_payload(response_json), ensure_ascii=False),
      "\n",
    ]
  )
  return _call_json_schema_prompt(system_text=system_text, user_text=user_text, schema=schema)
