from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from llm_timing import log_timing

ROOT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _openai_disabled() -> bool:
  _load_root_env()
  mode = str(os.getenv("INTAKE_LANGUAGE_MODE") or "").strip().lower()
  return mode in ("off", "disabled", "0", "false")


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


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _openai_timeout_seconds()
  last_exc: Optional[Exception] = None
  for attempt in range(3):
    started = time.perf_counter()
    try:
      resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
      log_timing(
        "openai.http",
        ms=int((time.perf_counter() - started) * 1000),
        purpose="language",
        url=url,
        model=str((payload or {}).get("model") or ""),
        attempt=attempt + 1,
        timeout_s=timeout,
        status_code=getattr(resp, "status_code", None),
      )
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:
      last_exc = exc
      log_timing(
        "openai.http_timeout",
        ms=int((time.perf_counter() - started) * 1000),
        purpose="language",
        url=url,
        model=str((payload or {}).get("model") or ""),
        attempt=attempt + 1,
        timeout_s=timeout,
        exc=type(exc).__name__,
      )
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
    except requests.exceptions.ConnectionError as exc:
      last_exc = exc
      log_timing(
        "openai.http_connection_error",
        ms=int((time.perf_counter() - started) * 1000),
        purpose="language",
        url=url,
        model=str((payload or {}).get("model") or ""),
        attempt=attempt + 1,
        timeout_s=timeout,
        exc=type(exc).__name__,
      )
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


def _extract_output_text(data: Dict[str, Any]) -> str:
  output = data.get("output") or []
  text_chunks: List[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        text_chunks.append(str(part["text"]))
  return "\n".join(text_chunks).strip()


def _strip_inline_markdown(s: str) -> str:
  try:
    import re

    out = str(s or "")
    out = re.sub(r"```[\\s\\S]*?```", " ", out)  # fenced blocks
    out = out.replace("`", "")
    out = out.replace("**", "")
    out = out.replace("__", "")
    out = out.replace("*", "")
    out = out.replace("_", "")
    out = re.sub(r"\\{\\{[^}]+\\}\\}", "", out)  # placeholder tokens
    return out
  except Exception:
    return str(s or "")


def _format_money(value: Any) -> str:
  try:
    num = float(value)
  except Exception:
    return str(value).strip()
  if abs(num - round(num)) < 0.005:
    return f"${num:,.0f}"
  return f"${num:,.2f}"


def _format_percent(value: Any) -> str:
  try:
    num = float(value)
  except Exception:
    return str(value).strip()
  if abs(num - round(num)) < 0.005:
    return f"{num:.0f}%"
  return f"{num:.1f}%"


def _format_quantity(value: Any) -> str:
  try:
    num = float(value)
  except Exception:
    return str(value).strip()
  if abs(num - round(num)) < 0.005:
    return f"{int(round(num))}"
  return f"{num:.2f}"


def _get_unit_price(intake_context: Dict[str, Any]) -> Optional[float]:
  for key in ("operating_model_json", "ops_json", "ops"):
    obj = intake_context.get(key) if isinstance(intake_context, dict) else None
    if isinstance(obj, dict):
      raw = obj.get("unit_price")
      try:
        val = float(raw)
      except Exception:
        val = None
      if val is not None and val > 0:
        return val
  return None


def _compact_assumption_message(*, kind: str, intake_context: Dict[str, Any]) -> str:
  kind_norm = str(kind or "").strip().lower()
  suggestion_key = {
    "fulfillment": "fulfillment_suggestion",
    "marketing": "marketing_suggestion",
    "revenue": "revenue_suggestion",
    "ops_concept": "ops_concept_suggestion",
    "milestones": "milestones_suggestion",
    "cogs": "cogs_suggestion",
    "gna": "gna_suggestion",
  }.get(kind_norm)
  if not suggestion_key:
    return ""
  suggestion = intake_context.get(suggestion_key) if isinstance(intake_context, dict) else None
  if not isinstance(suggestion, dict):
    if kind_norm != "cogs":
      return ""
    suggestion = {}

  bullets: List[str] = []
  question = "Confirm these assumptions?"

  if kind_norm == "fulfillment":
    fm = str(suggestion.get("fulfillment_model") or "").strip()
    who = str(suggestion.get("who_fulfills") or "").strip()
    lead = str(suggestion.get("lead_time") or "").strip()
    if fm:
      bullets.append(f"- Assume fulfillment model: {fm}.")
    if who:
      bullets.append(f"- Assume fulfillment handled by: {who}.")
    if lead:
      bullets.append(f"- Assume typical lead time: {lead}.")
  elif kind_norm == "marketing":
    budget = suggestion.get("monthly_marketing_budget")
    channels = str(suggestion.get("primary_channels") or "").strip()
    if budget is not None:
      bullets.append(f"- Assume monthly marketing budget: {_format_money(budget)}.")
    if channels:
      bullets.append(f"- Assume primary channels: {channels}.")
  elif kind_norm == "revenue":
    units_cap = suggestion.get("units_per_week_capacity")
    avg_units = suggestion.get("avg_units_per_week_year1")
    weeks = suggestion.get("operating_weeks_per_year")
    unit_price = suggestion.get("unit_price")
    if units_cap is not None:
      bullets.append(f"- Assume weekly capacity: {_format_quantity(units_cap)} units.")
    if avg_units is not None:
      bullets.append(f"- Assume Year 1 average: {_format_quantity(avg_units)} units per week.")
    if weeks is not None:
      bullets.append(f"- Assume operating weeks per year: {_format_quantity(weeks)}.")
    if unit_price is not None:
      bullets.append(f"- Assume unit price: {_format_money(unit_price)}.")
  elif kind_norm == "ops_concept":
    operating_unit = str(suggestion.get("operating_unit") or "").strip()
    primary_constraint = str(suggestion.get("primary_constraint") or "").strip()
    process_overview = str(suggestion.get("process_overview") or "").strip()
    if operating_unit:
      bullets.append(f"- Assume operating unit: {operating_unit}.")
    if primary_constraint:
      bullets.append(f"- Assume primary constraint: {primary_constraint}.")
    if process_overview:
      bullets.append(f"- Assume process overview: {process_overview}.")
  elif kind_norm == "cogs":
    materials = suggestion.get("materials_cost_per_unit")
    direct = suggestion.get("direct_fulfillment_cost_per_unit")
    other = suggestion.get("other_variable_cost_per_unit")
    cost_bits: List[str] = []
    if materials is not None:
      cost_bits.append(f"materials {_format_money(materials)}")
    if direct is not None:
      cost_bits.append(f"direct fulfillment {_format_money(direct)}")
    if other is not None:
      cost_bits.append(f"other variable {_format_money(other)}")
    if cost_bits:
      bullets.append(f"- Assume per-unit COGS: {'; '.join(cost_bits)}.")
    else:
      unit_price = _get_unit_price(intake_context or {})
      if unit_price is not None:
        default_pct = 0.6
        default_cost = max(0.0, unit_price * default_pct)
        bullets.append(f"- Assume per-unit direct costs around {_format_money(default_cost)}.")
        question = "Does that sound right, or should we use a different number?"
      else:
        bullets.append("- Assume direct costs run about 60% of what you charge per unit.")
        question = "Does that sound right, or should we use a different percentage?"

    prod = suggestion.get("production")
    if isinstance(prod, dict):
      stages = prod.get("stages")
      stages_out = []
      if isinstance(stages, list):
        stages_out = [str(s).strip() for s in stages if str(s or "").strip()]
      bottleneck = str(prod.get("primary_bottleneck") or "").strip()
      basis = str(prod.get("unit_throughput_basis") or "").strip()
      yield_assumption = str(prod.get("yield_assumption") or "").strip()
      prod_bits: List[str] = []
      if stages_out:
        joined = " -> ".join(stages_out[:4])
        prod_bits.append(f"stages {joined}")
      if bottleneck:
        prod_bits.append(f"bottleneck {bottleneck}")
      if basis:
        prod_bits.append(f"basis {basis}")
      if yield_assumption:
        prod_bits.append(f"yield {yield_assumption}")
    if prod_bits:
      bullets.append(f"- Assume production: {'; '.join(prod_bits)}.")
  elif kind_norm == "milestones":
    raw_milestones = suggestion.get("milestones")
    if isinstance(raw_milestones, list):
      for m in raw_milestones:
        if not isinstance(m, dict):
          continue
        title = str(m.get("title") or "").strip()
        target_period = str(m.get("target_period") or "").strip()
        if not title or not target_period:
          continue
        description = str(m.get("description") or "").strip()
        if description:
          bullets.append(f"- Proposed milestone: {title} - {description} ({target_period}).")
        else:
          bullets.append(f"- Proposed milestone: {title} ({target_period}).")
        if len(bullets) >= 2:
          break
    if bullets:
      question = "Does this milestone look right, or should we adjust it?"
  elif kind_norm == "gna":
    def _add_money(label: str, value: Any) -> None:
      if value is None:
        return
      if value == 0 and bullets:
        return
      bullets.append(f"- Assume {label}: {_format_money(value)} per month.")

    _add_money("rent/space", suggestion.get("monthly_rent_expense"))
    _add_money("software/tools", suggestion.get("monthly_software_expense"))
    _add_money("insurance", suggestion.get("monthly_insurance_expense"))
    _add_money("utilities", suggestion.get("monthly_utilities_expense"))
    _add_money("admin/overhead", suggestion.get("monthly_admin_expense"))
    _add_money("professional services", suggestion.get("other_operating_expense"))

  if not bullets:
    return ""

  return "\n".join([*bullets, question]).strip()


def _postprocess_client_text(*, kind: str, text: str) -> str:
  """
  Keep output human-readable without truncating or sentence-limiting the LLM.
  This is formatting-only hygiene (no "smart" trimming).
  """
  raw = str(text or "").strip()
  if not raw:
    return ""

  # Strip common markdown without dropping content.
  cleaned = _strip_inline_markdown(raw)

  # Normalize whitespace while preserving paragraph breaks.
  cleaned = cleaned.replace("\r", "\n")
  cleaned = "\n".join([ln.rstrip() for ln in cleaned.split("\n")])
  while "\n\n\n" in cleaned:
    cleaned = cleaned.replace("\n\n\n", "\n\n")
  return cleaned.strip()


_CHECKPOINT_REASSURANCE_MARKERS: tuple[str, ...] = (
  "that's totally fine",
  "that’s totally fine",
  "totally fine",
  "no problem",
  "not a problem",
  "that's okay",
  "that’s okay",
  "all good",
  "we can adjust this later",
  "we can adjust later",
  "we can revisit this later",
  "we can revisit later",
)


def _checkpoint_sentences_from_llm_json(text: str) -> Optional[List[str]]:
  """
  Parse a strict JSON object {"sentences":[...]} and validate 1-2 non-empty strings.
  - No question marks
  - Must include a reassurance phrase in the final sentence
  """
  try:
    parsed = json.loads(str(text or "").strip())
  except Exception:
    return None
  if not isinstance(parsed, dict):
    return None
  sentences = parsed.get("sentences")
  if not isinstance(sentences, list):
    return None
  out: List[str] = []
  for s in sentences:
    if not isinstance(s, str):
      return None
    cleaned = " ".join(s.split()).strip()
    if not cleaned:
      continue
    if "?" in cleaned:
      return None
    out.append(cleaned)
  if not out or len(out) > 2:
    return None
  last = out[-1].lower()
  if not any(m in last for m in _CHECKPOINT_REASSURANCE_MARKERS):
    return None
  return out


def _render_checkpoint_message(*, api_key: str, model: str, context: Dict[str, Any]) -> str:
  system = (
    "You are a senior business consultant running a paid intake.\n"
    "Write only what the client should see in the chat.\n"
    "This message is an end-of-section reflection checkpoint.\n"
    "Return ONLY a JSON object of the form: {\"sentences\":[\"...\",\"...\"]}.\n"
    "Rules:\n"
    "- Use 1-2 short sentences total.\n"
    "- Do NOT ask any questions.\n"
    "- Do NOT introduce new assumptions.\n"
    "- Do NOT include any numbers, dates, or calculations.\n"
    "- Do NOT mention cards, panels, Accept/Edit, JSON, schemas, drivers, derived fields, formulas, or databases.\n"
    "- The last sentence MUST include exactly one brief reassurance (e.g., \"No problem.\" / \"That’s totally fine.\" / \"We can adjust this later.\").\n"
    "- Keep it purely reflective (orientation only), not a recap deck.\n"
  )

  user_obj = {"kind": "checkpoint", "context": context or {}}
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

  last_text = ""
  for attempt in range(2):
    payload: Dict[str, Any] = {
      "model": model,
      "input": [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)},
      ],
    }
    if attempt == 1:
      payload["input"].append(
        {
          "role": "system",
          "content": "Repair: output must be valid JSON with 1-2 sentences, no question marks, and the final sentence must contain a reassurance phrase.",
        }
      )

    resp = _post_openai(url=url, headers=headers, payload=payload)
    if resp.status_code >= 300:
      raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
    last_text = _extract_output_text(resp.json())
    sentences = _checkpoint_sentences_from_llm_json(last_text)
    if sentences:
      return " ".join(sentences).strip()

  return ""


def render_client_message(*, kind: str, context: Dict[str, Any]) -> str:
  """
  Generate client-facing language (no card/UI concepts) for a given situation.

  If OpenAI is disabled/unconfigured, returns an empty string (so the backend never
  emits developer-written client copy by default).
  """
  if _openai_disabled():
    return ""

  kind_norm = str(kind or "").strip().lower()
  api_key = _require_openai_key()
  model = _openai_model()

  try:
    intake_context = (context or {}).get("intake_context") if isinstance(context, dict) else {}
    compact = _compact_assumption_message(kind=kind_norm, intake_context=intake_context or {})
    if compact:
      return compact
  except Exception:
    pass

  if kind_norm.startswith("checkpoint"):
    out = _render_checkpoint_message(api_key=api_key, model=model, context=context or {})
    return _postprocess_client_text(kind=kind, text=out)

  system = (
    "You are a senior business consultant running a paid intake.\n"
    "Write only what the client should see in the chat.\n"
    "Rules:\n"
    "- Do NOT mention cards, panels, Accept/Edit, JSON, schemas, drivers, derived fields, formulas, or databases.\n"
    "- Do NOT narrate internal logic, placeholders, branching options, or what you will compute next.\n"
    "- Cover ONE concept per message. Do not bundle multiple topics.\n"
    "- Default behavior: propose a reasonable assumption and ask the client to confirm or correct it.\n"
    "- Only ask the client a question when a hard, non-inferable constraint is missing (e.g., a fixed capacity limit or a legal choice).\n"
    "- Do NOT ask the client to forecast, choose scenarios, or answer \"what feels realistic\".\n"
    "- When the client explains something in their own words, briefly restate your understanding before asking for confirmation.\n"
    "- Only present multiple-choice labels when you truly need a hard constraint; otherwise, ask a simple yes/no to confirm your proposed default.\n"
    "- Never ask the client to pick between alternative scenarios or ramps; propose one default and invite a correction.\n"
    "- You MAY include one brief reassurance when appropriate (e.g., \"No problem.\" / \"That’s totally fine.\" / \"We can adjust this later.\").\n"
    "- You MAY include one short inline numeric insight when it builds trust (use plain language like \"about\" or \"roughly\").\n"
    "- Do NOT show equation-style math (e.g., \"Revenue = X x Y\") or multi-step calculations.\n"
    "- If you ask a question, ask exactly one short question at the end.\n"
    "- Use the provided context, but do not dump it back verbatim.\n"
  )
  if kind_norm in ("fulfillment", "marketing", "cogs", "gna", "milestones", "revenue", "ops_concept"):
    system = (
      "You are a senior business consultant running a paid intake.\n"
      "Write only what the client should see in the chat.\n"
      "Output format:\n"
      "- 2-4 short bullet lines (start each line with '- '), each an assumption-first statement.\n"
      "- Then ONE short confirmation question.\n"
      "Rules:\n"
      "- Be assertive and compact; do not teach or explain.\n"
      "- Avoid narrative phrases like 'how this works', 'in practice', or 'this means'.\n"
      "- Do NOT restate prior context; only state the proposed assumptions.\n"
      "- Do NOT mention cards, panels, Accept/Edit, JSON, schemas, drivers, derived fields, formulas, or databases.\n"
      "- Do NOT show equations or multi-step calculations.\n"
      "- Ask exactly one short question at the end.\n"
    )

  user_obj = {"kind": str(kind or "").strip(), "context": context or {}}

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload: Dict[str, Any] = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)},
    ],
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 300:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
  return _postprocess_client_text(kind=kind, text=_extract_output_text(resp.json()))


def postprocess_freeform_client_text(text: str) -> str:
  """
  Local-only formatting hygiene (no OpenAI call).
  """
  return _postprocess_client_text(kind="freeform", text=str(text or ""))
