from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from llm_timing import log_timing, timed_span


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

def _openai_concept_summary_model() -> str:
  _load_root_env()
  raw = (
    os.getenv("OPENAI_CONCEPT_SUMMARY_MODEL")
    or os.getenv("OPENAI_SUMMARY_MODEL")
    or os.getenv("OPENAI_FAST_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "gpt-5.1"
  )
  return str(raw).strip() or "gpt-5.1"


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
        purpose="concept_summary",
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
        purpose="concept_summary",
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
        purpose="concept_summary",
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


def _sentences_from_llm_json(text: str) -> Optional[List[str]]:
  """
  Parse a strict JSON object {"sentences":[...]} and validate 1-5 non-empty strings.
  If the model violates constraints, return None (caller should fallback; no truncation).
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
    out.append(cleaned)
  if not out:
    return None
  if len(out) > 5:
    return None
  if any("?" in s for s in out):
    return None
  return out


def _card_lobs(card: Dict[str, Any]) -> List[Dict[str, Any]]:
  if not isinstance(card, dict):
    return []
  lobs = card.get("lobs")
  if isinstance(lobs, list):
    return [lob for lob in lobs if isinstance(lob, dict)]
  drivers = card.get("drivers") if isinstance(card.get("drivers"), dict) else {}
  derived = card.get("derived") if isinstance(card.get("derived"), dict) else {}
  return [
    {
      "lob_key": "company_total",
      "lob_name": None,
      "drivers": dict(drivers),
      "derived": dict(derived),
    }
  ]


def _normalize_driver_obj(obj: Any) -> Optional[Dict[str, Any]]:
  if not isinstance(obj, dict):
    return None
  out: Dict[str, Any] = {}
  for k, v in obj.items():
    if str(k or "").strip() == "updated_at_ms":
      continue
    if k in ("value", "unit", "time_basis", "rationale"):
      if isinstance(v, str):
        out[k] = v.strip()
      else:
        out[k] = v
  if not out:
    return None
  return out


def concept_signature(card: Dict[str, Any]) -> str:
  """
  Stable signature for concept regeneration:
  - includes lob keys/names and driver value/unit/time_basis/rationale
  - ignores timestamps and derived values
  - ignores any existing concept_* keys
  """
  lobs_in = _card_lobs(card or {})
  lobs_out: List[Dict[str, Any]] = []
  for lob in lobs_in:
    drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
    drivers_out: Dict[str, Any] = {}
    for k in sorted(drivers.keys(), key=lambda x: str(x).lower()):
      dv = _normalize_driver_obj(drivers.get(k))
      if dv is None:
        continue
      drivers_out[str(k)] = dv
    lobs_out.append(
      {
        "lob_key": str(lob.get("lob_key") or "").strip(),
        "lob_name": str(lob.get("lob_name") or "").strip() or None,
        "drivers": drivers_out,
      }
    )
  payload = {"lobs": lobs_out}
  return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _get_company_driver_value(card: Dict[str, Any], key: str) -> Any:
  try:
    lobs = _card_lobs(card)
    for lob in lobs:
      if str(lob.get("lob_key") or "").strip() != "company_total":
        continue
      drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
      dv = drivers.get(key)
      if isinstance(dv, dict):
        return dv.get("value")
  except Exception:
    return None
  return None


def _deterministic_concept_summary(*, model: str, card: Dict[str, Any]) -> str:
  """
  Deterministic fallback (no network): concise conceptual summary from drivers only.
  Must be <= ~5 sentences by construction (no truncation).
  """
  model_norm = str(model or "").strip().lower()
  lines: List[str] = []

  def _add(sentence: str) -> None:
    s = str(sentence or "").strip()
    if not s:
      return
    if len(lines) >= 5:
      return
    lines.append(s)

  if model_norm == "pricing":
    price = _get_company_driver_value(card, "unit_price") or card.get("unit_price")
    if price not in (None, ""):
      _add(f"Pricing is set on a per-unit basis, with a current target of {price} per unit.")
    else:
      _add("Pricing is defined on a per-unit basis, and can be adjusted as we refine positioning.")
  elif model_norm == "marketing":
    budget = _get_company_driver_value(card, "monthly_marketing_budget")
    channels = _get_company_driver_value(card, "primary_channels")
    if budget not in (None, ""):
      _add(f"The initial marketing plan is anchored around a monthly budget of about {budget}.")
    else:
      _add("The marketing plan is anchored around a clear monthly budget and a focused acquisition approach.")
    if channels not in (None, ""):
      _add(f"Primary acquisition focus: {channels}.")
  elif model_norm == "revenue":
    unit_price = _get_company_driver_value(card, "unit_price")
    capacity = _get_company_driver_value(card, "units_per_week_capacity")
    avg_units = _get_company_driver_value(card, "avg_units_per_week_year1")
    weeks = _get_company_driver_value(card, "operating_weeks_per_year")
    if unit_price not in (None, "") and avg_units not in (None, ""):
      _add(f"Revenue is modeled as selling about {avg_units} units per week at {unit_price} per unit.")
    elif capacity not in (None, ""):
      _add(f"Revenue capacity is anchored around the ability to deliver about {capacity} units per week.")
    else:
      _add("Revenue is modeled using a simple capacity-and-pace approach tied to the operating unit.")
    if weeks not in (None, ""):
      _add(f"The model assumes roughly {weeks} operating weeks per year.")
  elif model_norm == "headcount":
    roles = _get_company_driver_value(card, "roles")
    if isinstance(roles, list) and roles:
      total = 0
      for r in roles:
        if not isinstance(r, dict):
          continue
        try:
          total += int(r.get("employee_count") or r.get("count") or 0)
        except Exception:
          pass
      _add(f"Headcount is planned around {len(roles)} role(s), totaling about {total} people in Year 1.")
    else:
      _add("Headcount is planned as a small Year-1 team, with roles and staffing levels adjustable as we refine workload.")
  elif model_norm == "fulfillment":
    fm = _get_company_driver_value(card, "fulfillment_model")
    who = _get_company_driver_value(card, "who_fulfills")
    lead = _get_company_driver_value(card, "lead_time")
    if fm not in (None, ""):
      _add(f"Fulfillment is structured as: {fm}.")
    else:
      _add("Fulfillment is defined as a clear, repeatable delivery approach for the core offer.")
    if who not in (None, ""):
      _add(f"Day-to-day fulfillment is handled by: {who}.")
    if lead not in (None, ""):
      _add(f"Typical turnaround/lead time is: {lead}.")
  elif model_norm == "ops_concept":
    unit = _get_company_driver_value(card, "operating_unit")
    constraint = _get_company_driver_value(card, "primary_constraint")
    overview = _get_company_driver_value(card, "process_overview")
    if unit not in (None, ""):
      _add(f"The operating unit is defined as: {unit}.")
    else:
      _add("The operating concept defines how work is scoped into a clear unit of delivery.")
    if constraint not in (None, ""):
      _add(f"The primary constraint to plan around is: {constraint}.")
    if overview not in (None, ""):
      _add(f"Process overview: {overview}.")
  elif model_norm == "milestones":
    ms = _get_company_driver_value(card, "milestones")
    if isinstance(ms, list) and ms:
      titles = []
      for m in ms:
        if not isinstance(m, dict):
          continue
        t = str(m.get("title") or "").strip()
        if t:
          titles.append(t)
        if len(titles) >= 2:
          break
      if titles:
        _add(f"Milestones are defined as a short sequence of concrete goals, starting with: {', '.join(titles)}.")
      else:
        _add("Milestones are defined as a short sequence of concrete goals with clear timing.")
    else:
      _add("Milestones are captured as a small set of concrete goals with clear timing and ownership.")
  elif model_norm == "cogs":
    cpu = _get_company_driver_value(card, "cost_per_unit")
    pct = _get_company_driver_value(card, "cogs_percent_of_revenue")
    if cpu not in (None, ""):
      _add(f"Unit economics assume direct costs of about {cpu} per unit delivered.")
    elif pct not in (None, ""):
      _add(f"Unit economics assume direct costs run about {pct}% of revenue.")
    else:
      _add("Unit economics capture the direct costs tied to delivering each unit of the offer.")
  elif model_norm == "gna":
    _add("Overhead is captured as recurring monthly operating expenses needed to run the business consistently.")
  else:
    _add("This model captures the key assumptions and approach for this part of the plan.")

  # Ensure 1–5 sentences by construction.
  lines = [ln.strip() for ln in lines if ln and ln.strip()]
  if not lines:
    return ""
  # Ensure proper punctuation and no questions.
  out_sentences: List[str] = []
  for ln in lines:
    ln = ln.replace("?", "").strip()
    if not ln:
      continue
    if not ln.endswith((".", "!")):
      ln = f"{ln}."
    out_sentences.append(ln)
  return " ".join(out_sentences).strip()


def generate_concept_summary(
  *,
  model: str,
  card: Dict[str, Any],
  context: Optional[Dict[str, Any]] = None,
) -> str:
  """
  Generate a concise concept summary for a model card.
  Enforces constraints by validation (no truncation): if the LLM output violates, fall back.
  """
  model_norm = str(model or "").strip().lower()
  card_obj = dict(card or {})
  ctx = context or {}

  if _openai_disabled():
    return _deterministic_concept_summary(model=model_norm, card=card_obj)

  try:
    api_key = _require_openai_key()
  except Exception:
    return _deterministic_concept_summary(model=model_norm, card=card_obj)

  system = (
    "You write an INTERNAL concept summary used for business plan writing.\n"
    "Output must be STRICT JSON with this exact shape: {\"sentences\": [\"...\", ...]}.\n"
    "Rules:\n"
    "- 2 to 5 sentences total.\n"
    "- No questions (no question marks).\n"
    "- No bullet lists, numbered lists, or headings.\n"
    "- No formulas, no equation-style math, no multi-step calculation walkthroughs.\n"
    "- Do not mention cards, drivers, derived fields, JSON, schemas, SQL, or databases.\n"
    "- Use only information present in the provided structured context; avoid new assumptions.\n"
    "- If a value is missing, describe the approach qualitatively rather than guessing numbers.\n"
    "- Keep each sentence concise and business-native.\n"
  )

  user_obj = {
    "model": model_norm,
    "context": ctx,
    "card": card_obj,
  }

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload: Dict[str, Any] = {
    "model": _openai_concept_summary_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)},
    ],
  }

  try:
    with timed_span("concept_summary.generate", model=model_norm, openai_model=str(payload.get("model") or "")):
      resp = _post_openai(url=url, headers=headers, payload=payload)
    if resp.status_code >= 300:
      return _deterministic_concept_summary(model=model_norm, card=card_obj)
    raw_text = _extract_output_text(resp.json())
  except Exception:
    return _deterministic_concept_summary(model=model_norm, card=card_obj)

  sentences = _sentences_from_llm_json(raw_text)
  if not sentences:
    return _deterministic_concept_summary(model=model_norm, card=card_obj)
  return " ".join(s.rstrip(".!?").strip() + "." for s in sentences).strip()


def ensure_concept_summary(
  *,
  model: str,
  prev_card: Dict[str, Any],
  card: Dict[str, Any],
  now_ms: int,
  context: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], bool]:
  """
  Ensure `concept_summary` exists and is up-to-date for a model card.
  Regenerates when driver/rationale signature changes (timestamps ignored).
  """
  prev_sig = concept_signature(prev_card or {})
  next_sig = concept_signature(card or {})
  existing = str((card or {}).get("concept_summary") or "").strip()
  if existing and prev_sig == next_sig:
    return card or {}, False

  summary = generate_concept_summary(model=model, card=card or {}, context=context)
  if not summary:
    return card or {}, False
  next_card = dict(card or {})
  next_card["concept_summary"] = summary
  next_card["concept_updated_at_ms"] = int(now_ms)
  return next_card, True
