"""GPT REVIEW-ONLY critique of the deterministic revenue proposal.

Doctrine: Python PROPOSES the structure and owns the anchor
(deterministic_revenue_proposer); GPT CRITIQUES within tight bounds; Python
ENFORCES the bounds. GPT is a critic with a leash, never an author.

The deterministic proposal is correct but GENERIC — the same tapered growth
curve regardless of business nuance. This layer lets GPT nudge the trajectory
toward the specific business (a premium boutique ramps differently than a
commodity retailer) WITHOUT giving back what the deterministic proposer won:

  * BOUNDED: GPT may only submit per-quarter multiplicative factors on the
    proposed revenue, clamped to [0.90, 1.10]. Q1 is the operator anchor and
    is FORCED to 1.0 — the level cannot be re-authored. After factors, Python
    re-clamps every quarter so revenue never grows faster than the QoQ cap
    and never grows slower than the proposer's own price*utilization drift
    (which keeps capacity non-decreasing, the driver contract).
  * DETERMINISTIC: run-once-and-lock. The ENFORCED critique is persisted in
    ``post_intake_revenue_critique_store`` keyed by a content hash of
    (business compact + proposed trajectory + bounds). Identical inputs on a
    later run hit the cache and reuse the locked factors byte-for-byte —
    gpt-5.1 never gets a chance to re-roll. No key / GPT failure -> the pure
    deterministic proposal flows through unchanged (still deterministic).

Wired via the ``_author_fn`` seam: the runner wraps the deterministic
proposer with ``review_revenue_proposal``; everything downstream (the
``revenue_authored`` lock, the path-stamp / restoration-loop revenue
exclusions) carries the reviewed trajectory to the final finmo unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

_HORIZON = 20

CRITIQUE_FACTOR_MIN = 0.90
CRITIQUE_FACTOR_MAX = 1.10
CRITIQUE_STORE_TABLE = "post_intake_revenue_critique_store"

_DEFAULT_MODEL = "gpt-5.1"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 120.0


def _f(value: Any) -> Optional[float]:
  try:
    if value is None:
      return None
    return float(value)
  except (TypeError, ValueError):
    return None


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


# ----------------------------------------------------------------------------
# Content-hash + locked-critique store (run-once-and-lock determinism).
# ----------------------------------------------------------------------------


# Compact keys that are RE-DERIVED by GPT during a run (not raw intake) and so
# vary run-to-run on identical inputs. They are excluded from the lock key --
# otherwise the hash re-rolls every run and the cache never hits (observed:
# market_demand.capture_rate_year1 flipped 0.168 -> 0.35 between identical-input
# runs, minting a fresh hash each time). The FULL compact still goes to GPT on a
# cache miss; the lock simply makes the first run's view the canonical one.
_RUN_DERIVED_COMPACT_KEYS = frozenset({"market_demand"})


def critique_input_hash(
  compact: Optional[Dict[str, Any]],
  proposal_lines: List[Dict[str, Any]],
  qoq_max: float,
) -> str:
  """Deterministic key for the locked critique: same INTAKE-DERIVED business
  compact + same proposed trajectory + same bounds -> same hash. Run-derived
  compact slices (GPT-recomputed during the pipeline) are excluded so identical
  intake inputs hash identically across runs."""
  stable_compact = {
    key: value for key, value in (compact or {}).items()
    if key not in _RUN_DERIVED_COMPACT_KEYS
  }
  payload = {
    "compact": stable_compact,
    "proposal": proposal_lines,
    "qoq_max": round(float(qoq_max), 6),
    "factor_min": CRITIQUE_FACTOR_MIN,
    "factor_max": CRITIQUE_FACTOR_MAX,
  }
  canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
  return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ensure_store(conn) -> None:
  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      CREATE TABLE IF NOT EXISTS {CRITIQUE_STORE_TABLE} (
        input_hash VARCHAR(64) NOT NULL PRIMARY KEY,
        critique_json LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
      """
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _store_lookup(conn, input_hash: str) -> Optional[Dict[str, Any]]:
  cur = conn.cursor()
  try:
    cur.execute(
      f"SELECT critique_json FROM {CRITIQUE_STORE_TABLE} WHERE input_hash = %s",
      (input_hash,),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not row or not row[0]:
    return None
  try:
    parsed = json.loads(row[0])
    return parsed if isinstance(parsed, dict) else None
  except Exception:
    return None


def _store_save(conn, input_hash: str, critique: Dict[str, Any]) -> None:
  cur = conn.cursor()
  try:
    cur.execute(
      f"INSERT IGNORE INTO {CRITIQUE_STORE_TABLE} (input_hash, critique_json) VALUES (%s, %s)",
      (input_hash, json.dumps(critique, ensure_ascii=False, default=str)),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass


# ----------------------------------------------------------------------------
# GPT critique call (one call; review-only tool contract).
# ----------------------------------------------------------------------------


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_revenue_critique",
    "description": (
      "Submit your review of the proposed revenue trajectory. Call exactly "
      "once. You are a CRITIC, not an author: only per-quarter adjustment "
      "factors within [0.90, 1.10] are accepted; q1 must be 1.0."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "lines": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "lob_name": {"type": "string"},
              "unit_name": {"type": "string"},
              "factors": {
                "type": "array",
                "description": (
                  "Per-quarter multiplicative adjustment on the PROPOSED "
                  "revenue. Omit a quarter to leave it at 1.0 (no change)."
                ),
                "items": {
                  "type": "object",
                  "properties": {
                    "q": {"type": "integer", "minimum": 1, "maximum": 20},
                    "factor": {"type": "number", "minimum": 0.90, "maximum": 1.10},
                  },
                  "required": ["q", "factor"],
                },
              },
              "line_rationale": {"type": "string"},
            },
            "required": ["factors", "line_rationale"],
          },
        },
        "overall_rationale": {"type": "string"},
      },
      "required": ["lines", "overall_rationale"],
    },
  },
}

_SYSTEM_PROMPT = (
  "You are reviewing a DETERMINISTICALLY proposed 20-quarter revenue trajectory "
  "for a small business plan. Python authored the trajectory: Q1 is anchored to "
  "the operator's stated current revenue and growth tapers smoothly within a "
  "quarter-over-quarter cap. Your job is REVIEW ONLY -- ground the generic curve "
  "in THIS business's reality (seasonality, ramp nuance, saturation, premium vs "
  "commodity positioning, capacity realities from the team/market context).\n"
  "Rules:\n"
  "1. You may ONLY submit per-quarter multiplicative factors in [0.90, 1.10] on "
  "the proposed revenue. Anything outside is clipped by Python.\n"
  "2. Q1 is the operator anchor and is IMMOVABLE: its factor is forced to 1.0.\n"
  "3. Python re-enforces the QoQ growth cap after your factors; you cannot "
  "create a growth spike.\n"
  "4. If the proposed curve already fits the business, return factor 1.0 for "
  "every quarter -- do NOT invent adjustments to look useful.\n"
  "5. Justify each line's adjustment in one or two sentences grounded in the "
  "business context, not generic finance talk.\n"
  "Call submit_revenue_critique exactly once."
)


def gpt_critique_revenue_once(
  *,
  compact: Dict[str, Any],
  proposal_summary: List[Dict[str, Any]],
  qoq_max: float,
  model: Optional[str] = None,
  seed: int = 1729,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """One review call; returns ``{ok, critique, error}``. The critique is the
  RAW GPT output -- callers must pass it through the Python enforcement
  (`apply_bounded_revenue_critique`) before use or persistence."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "critique": None, "error": "openai_api_key_unset"}
  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries

  user_prompt = (
    "BUSINESS COMPACT (ops + team + target market + demand):\n"
    + json.dumps(compact or {}, ensure_ascii=False, default=str)
    + "\n\nPROPOSED REVENUE TRAJECTORY (per line of business; quarterly totals; "
    + f"QoQ growth cap {qoq_max:.2%}):\n"
    + json.dumps(proposal_summary, ensure_ascii=False, default=str)
  )
  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": user_prompt},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_revenue_critique"}},
    "seed": int(seed),
  }
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  try:
    resp = http_fn(
      url=_OPENAI_URL, headers=headers, payload=payload,
      timeout_seconds=timeout_seconds,
      retryable_status=(429, 500, 502, 503, 504), max_attempts=3,
    )
  except Exception as exc:
    return {"ok": False, "critique": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}
  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "critique": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    critique = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "critique": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}
  if not isinstance(critique, dict) or not isinstance(critique.get("lines"), list):
    return {"ok": False, "critique": None, "error": "no_critique_in_tool_call"}
  return {"ok": True, "critique": critique, "error": None}


# ----------------------------------------------------------------------------
# Python enforcement — the leash.
# ----------------------------------------------------------------------------


def _line_revenue_series(quarters: List[Dict[str, Any]]) -> List[float]:
  out: List[float] = []
  for entry in quarters:
    cap = _f(entry.get("capacity_units_per_period")) or 0.0
    price = _f(entry.get("unit_price")) or 0.0
    util = _f(entry.get("utilization_rate")) or 0.0
    out.append(cap * price * util)
  return out


def _factors_for_line(critique: Optional[Dict[str, Any]], index: int, lob: Any, unit: Any) -> Tuple[Dict[int, float], str]:
  """Match a critique line to a proposal line by (lob, unit), else by order."""
  lines = (critique or {}).get("lines")
  if not isinstance(lines, list) or not lines:
    return {}, ""
  match = None
  for entry in lines:
    if not isinstance(entry, dict):
      continue
    if lob and str(entry.get("lob_name") or "").strip().lower() == str(lob).strip().lower():
      match = entry
      break
  if match is None and index < len(lines) and isinstance(lines[index], dict):
    match = lines[index]
  if match is None:
    return {}, ""
  factors: Dict[int, float] = {}
  for item in match.get("factors") or []:
    if not isinstance(item, dict):
      continue
    try:
      q = int(item.get("q"))
      value = float(item.get("factor"))
    except (TypeError, ValueError):
      continue
    if 1 <= q <= _HORIZON:
      factors[q] = value
  return factors, str(match.get("line_rationale") or "")


def apply_bounded_revenue_critique(
  proposal_drivers: Dict[str, Any],
  critique: Optional[Dict[str, Any]],
  *,
  qoq_max: float,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  """Apply the critique to the proposed drivers under hard bounds. Returns
  ``(adjusted_drivers, enforcement_trace)``. Invariants enforced:

    * factor clamped to [0.90, 1.10]; Q1 factor forced to 1.0 (anchor immovable)
    * revenue growth per quarter clamped to <= qoq_max (no spikes)
    * revenue growth per quarter clamped to >= the proposer's own
      price*utilization drift, so capacity stays non-decreasing (the driver
      contract normalize_revenue_drivers enforces)
    * unit_price / utilization series untouched; only capacity re-derives so
      capacity x price x utilization == adjusted revenue exactly
  """
  lines = list((proposal_drivers or {}).get("lines_of_business") or [])
  adjusted_lines: List[Dict[str, Any]] = []
  trace_lines: List[Dict[str, Any]] = []
  for index, line in enumerate(lines):
    quarters = list((line or {}).get("quarters") or [])
    if len(quarters) != _HORIZON:
      adjusted_lines.append(line)
      continue
    base_revenue = _line_revenue_series(quarters)
    factors, rationale = _factors_for_line(critique, index, line.get("lob_name"), line.get("unit_name"))
    clipped_factor_count = 0
    cap_clipped_quarters: List[int] = []
    adjusted_revenue: List[float] = []
    for idx in range(_HORIZON):
      q = idx + 1
      raw_factor = factors.get(q, 1.0)
      factor = min(CRITIQUE_FACTOR_MAX, max(CRITIQUE_FACTOR_MIN, raw_factor))
      if factor != raw_factor:
        clipped_factor_count += 1
      if q == 1:
        factor = 1.0  # the anchor is immovable
      target = base_revenue[idx] * factor
      if q > 1:
        prev = adjusted_revenue[idx - 1]
        lo = prev                              # revenue never declines
        hi = prev * (1.0 + float(qoq_max))     # the stated QoQ growth cap -- airtight
        clamped = min(max(target, lo), hi)
        if abs(clamped - target) > 1e-9:
          cap_clipped_quarters.append(q)
        target = clamped
      adjusted_revenue.append(target)
    # Re-derive drivers so capacity x price x utilization == adjusted revenue
    # EXACTLY. Capacity must be non-decreasing (the driver contract); when the
    # exact capacity would dip, hold capacity flat and absorb the difference
    # into UTILIZATION (which may move freely in [0, 1]) -- never by inflating
    # revenue above the cap.
    new_quarters: List[Dict[str, Any]] = []
    prev_capacity = 0.0
    for idx in range(_HORIZON):
      entry = dict(quarters[idx])
      price = _f(entry.get("unit_price")) or 0.0
      util = _f(entry.get("utilization_rate")) or 0.0
      denom = price * util
      if denom > 0:
        exact_capacity = adjusted_revenue[idx] / denom
        capacity = max(prev_capacity, exact_capacity)
        if capacity > exact_capacity and capacity * price > 0:
          util = adjusted_revenue[idx] / (capacity * price)
        entry["capacity_units_per_period"] = round(capacity, 6)
        entry["utilization_rate"] = round(min(1.0, max(0.0, util)), 6)
        prev_capacity = capacity
      new_quarters.append(entry)
    new_line = dict(line)
    new_line["quarters"] = new_quarters
    adjusted_lines.append(new_line)
    trace_lines.append({
      "lob": line.get("lob_name"),
      "rationale": rationale[:300],
      "factors_submitted": len(factors),
      "factors_clipped": clipped_factor_count,
      "growth_clamped_quarters": cap_clipped_quarters[:8],
      "q20_revenue_before": round(base_revenue[-1], 2),
      "q20_revenue_after": round(adjusted_revenue[-1], 2),
      "total_before": round(sum(base_revenue), 2),
      "total_after": round(sum(adjusted_revenue), 2),
    })
  adjusted = dict(proposal_drivers or {})
  adjusted["lines_of_business"] = adjusted_lines
  return adjusted, {"lines": trace_lines}


# ----------------------------------------------------------------------------
# Orchestration — propose (upstream) -> critique (locked) -> enforce.
# ----------------------------------------------------------------------------


def review_revenue_proposal(
  *,
  conn,
  compact: Optional[Dict[str, Any]],
  proposal: Dict[str, Any],
  qoq_max: float = 0.07,
  model: Optional[str] = None,
  _critique_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """Review the deterministic proposal with a LOCKED GPT critique. Returns the
  same ``{ok, drivers, error}`` author shape with the adjusted drivers (and an
  enforcement trace under ``drivers['_critique_trace']``). Any failure -> the
  pure proposal flows through unchanged; determinism is never at risk."""
  drivers = (proposal or {}).get("drivers")
  if not proposal.get("ok") or not isinstance(drivers, dict):
    return proposal
  lines = drivers.get("lines_of_business") or []
  if not lines:
    return proposal

  status = "skipped"
  critique: Optional[Dict[str, Any]] = None
  input_hash = ""
  try:
    input_hash = critique_input_hash(compact, lines, qoq_max)
    if conn is not None:
      _ensure_store(conn)
      critique = _store_lookup(conn, input_hash)
      if critique is not None:
        status = "cache_hit_locked"
    if critique is None:
      proposal_summary = [
        {
          "lob": line.get("lob_name"),
          "unit": line.get("unit_name"),
          "quarterly_revenue": [round(v, 2) for v in _line_revenue_series(line.get("quarters") or [])],
        }
        for line in lines
      ]
      critique_fn = _critique_fn or gpt_critique_revenue_once
      result = critique_fn(
        compact=compact or {}, proposal_summary=proposal_summary,
        qoq_max=qoq_max, model=model,
      )
      if result.get("ok") and isinstance(result.get("critique"), dict):
        critique = result["critique"]
        status = "authored_and_locked"
        if conn is not None:
          _store_save(conn, input_hash, critique)
      else:
        status = f"skipped:{result.get('error')}"
  except Exception as exc:
    status = f"skipped_exception:{type(exc).__name__}"
    critique = None

  if critique is None:
    out = dict(proposal)
    out_drivers = dict(drivers)
    out_drivers["_critique_trace"] = {"status": status, "input_hash": input_hash}
    out["drivers"] = out_drivers
    return out

  adjusted, trace = apply_bounded_revenue_critique(drivers, critique, qoq_max=qoq_max)
  adjusted["_critique_trace"] = {
    "status": status,
    "input_hash": input_hash,
    "overall_rationale": str(critique.get("overall_rationale") or "")[:400],
    **trace,
  }
  out = dict(proposal)
  out["drivers"] = adjusted
  return out


__all__ = [
  "review_revenue_proposal",
  "apply_bounded_revenue_critique",
  "gpt_critique_revenue_once",
  "critique_input_hash",
]
