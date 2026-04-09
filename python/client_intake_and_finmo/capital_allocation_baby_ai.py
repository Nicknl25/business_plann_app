from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _sanitize_payload(value: Any) -> Any:
  if isinstance(value, dict):
    return {str(k or ""): _sanitize_payload(v) for k, v in value.items()}
  if isinstance(value, list):
    return [_sanitize_payload(item) for item in value]
  return value


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


def _allocation_schema(allowed_row_ids: List[str]) -> Dict[str, Any]:
  return {
    "name": "capital_allocation_plan",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "summary": {"type": "string"},
        "rows": {
          "type": "array",
          "minItems": len(allowed_row_ids),
          "maxItems": len(allowed_row_ids),
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "row_id": {"type": "string", "enum": allowed_row_ids},
              "quarter_bands": {
                "type": "array",
                "minItems": 20,
                "maxItems": 20,
                "items": {
                  "type": "object",
                  "additionalProperties": False,
                  "properties": {
                    "quarter_index": {"type": "integer", "minimum": 1, "maximum": 20},
                    "min_value": {"type": "number"},
                    "max_value": {"type": "number"},
                  },
                  "required": ["quarter_index", "min_value", "max_value"],
                },
              },
            },
            "required": ["row_id", "quarter_bands"],
          },
        },
      },
      "required": ["summary", "rows"],
    },
    "strict": True,
  }


def build_capital_allocation_plan(
  *,
  source_row: Dict[str, Any],
  governor_payload: Dict[str, Any],
  target_rows: List[Dict[str, Any]],
  planning_mode: str,
) -> Dict[str, Any]:
  if not isinstance(target_rows, list) or not target_rows:
    return {}

  allowed_row_ids = [
    str(item.get("row_id") or "").strip()
    for item in target_rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  ]
  if not allowed_row_ids:
    return {}

  schema = _allocation_schema(allowed_row_ids)
  realism_memo_block = _realism_memo_prompt_block(source_row)
  system_text = (
    "You are a baby-AI capital allocation planner. Your only job is to set the quarter-by-quarter bands for the capital-allocation rows that express how the business deploys, retains, or extracts cash.\n"
    "You are not the full business planner. You are not allowed to write the entire grid or choose rows outside the listed capital-allocation set.\n"
    "Your plan must work for any cash strategy: reinvest, preserve_cash, shareholder_return, or balanced.\n"
    "Ground your judgment in the governor payload, especially the business reality, the selected cash strategy, and the binding cash constraint.\n"
    + planning_mode_text(planning_mode)
  )
  user_text = "".join(
    [
      "Create the capital-allocation row plan for this business.\n",
      "These rows are the discretionary capital-allocation layer that should make the selected cash strategy visible in the non-cash grid.\n",
      "Use the binding cash constraint as law. Your job is to make these rows realistic and strategy-consistent under that cash law.\n",
      "This is universal across all strategies, not reinvest-only.\n",
      "The target rows intentionally show only Q1 row values. Q2 through Q20 values are intentionally blank and must not be inferred, preserved, or treated as hidden defaults.\n",
      "Interpret the strategy like this:\n",
      "- reinvest: more credible internal deployment into growth and capacity\n",
      "- preserve_cash: more restrained deployment and stronger retention posture\n",
      "- shareholder_return: less trapped internal buildup and more willingness to release excess capital where the model supports it\n",
      "- balanced: a middle path with selective deployment and selective retention\n",
      "Treat Q1 as the anchored forecast quarter. Keep Q1 close to the real starting position unless the business context clearly demands otherwise.\n",
      "Treat Q2 through Q20 as fair game for meaningful realistic change.\n",
      "Do not preserve flat spread-placeholder schedule rows after Q1 just because intake spread a starting number across the horizon.\n",
      "The target rows should carry real capital-allocation behavior, not maintenance behavior.\n",
      "If the business is highly cash-generative, use these rows to create believable absorption, retention, or extraction behavior consistent with strategy and business reality.\n",
      "Do not create fantasy swings, but do not leave the rows timid or placeholder-like if the cash law requires real movement.\n",
      "Read the cash contract's quarter roles and deployment windows as binding guidance for these rows.\n",
      "If the cash path contains deployment_window or flattening quarters, these rows must show visible capital-allocation behavior in those same windows rather than tiny cosmetic changes.\n",
      "Avoid token moves. If a row changes by only a trivial amount and does not materially help explain the cash posture, that is a weak answer.\n",
      "Every listed row in every quarter is an active planning decision.\n",
      "Do not leave any row-quarter cell on autopilot, and do not carry Q1 or prior-quarter values forward by inertia.\n",
      "A row may stay flat only when flatness is itself the deliberate realistic answer for that specific row and quarter.\n",
      "For reinvest, do not let capital-allocation rows collapse into maintenance behavior. Use credible step-ups in capex, growth payroll, marketing support, debt action, or other listed rows when the business can plausibly absorb them.\n",
      "For preserve_cash, it is acceptable for deployment rows to stay more restrained, but they should still reflect deliberate retention rather than accidental flatness.\n",
      "For shareholder_return, avoid leaving excess capital trapped in neutral maintenance rows once a believable buffer exists; use the listed rows to show lower internal retention where the model supports it.\n",
      "For balanced, mix selective deployment and retention without letting every row drift into repetitive placeholder behavior.\n",
      "Rows with schedule or capital-allocation semantics must be willing to depart materially after Q1 when needed.\n",
      "In particular, do not leave Capital Expenditures, Principal Repayments, debt movement rows, or Net Additions as tiny or repeated placeholder-like ranges if the cash posture requires real deployment.\n",
      "When the first failing quarter shows cash still above band, widen the relevant schedule-style deployment rows materially in that quarter and the immediately following window rather than making only cosmetic increases.\n",
      "Do not leave 'schedules::Plus: Net Additions' at 0 to 0 across long stretches unless the business reality truly supports no additions at all.\n",
      "When a row's sign semantics allow it, negative values are allowed if that is the realistic way to express deployment, repayment, or contraction under the strategy.\n",
      "Use wider or higher deployment ranges in the explicit deployment windows than in ordinary quarters when the business can support that behavior.\n",
      "The output should make it obvious that management is making capital-allocation decisions, not just paying routine bills.\n",
      "For each row and quarter, return a min/max band.\n",
      "Make every quarter coherent. min_value must be less than or equal to max_value.\n",
      "Make Q1 relatively anchored. Make Q2-Q20 behave like a real capital-allocation plan.\n",
      "Do not add rows. Do not omit rows. Preserve every row_id exactly as given.\n\n",
      realism_memo_block,
      "Governor context payload:\n",
      json.dumps(_sanitize_payload(governor_payload), ensure_ascii=False),
      "\n\nCapital-allocation rows you must fill:\n",
      json.dumps(_sanitize_payload(target_rows), ensure_ascii=False),
      "\n",
    ]
  )

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
