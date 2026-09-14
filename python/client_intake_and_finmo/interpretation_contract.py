"""THE INTERPRETATION CONTRACT, v1 - IN SHADOW (one-reader build, step 1).

Nick ruled 2026-09-14: a client's sentence is read ONCE, and everything
downstream works from that reading. Before anything is cut over, the v1
contract runs beside the app on every client turn, recorded and never used,
so what it costs and what it reads can be measured instead of assumed (R5).

What it records per turn, per claim: the quantity with what it is per, its
kind, its line, precision, polarity (a no is a fact), firmness with direction
and reason, provenance, whether it answered the question or came alongside,
what it supersedes and what it points at - and, for every claim, the SURFACE:
the smallest span of her message containing the value, its unit and its
qualifier, copied verbatim. Cowork, 1052: the quote proves the words are hers;
the readback proves the reading is hers. A span the reader picks freely is one
it can pick around its own mistake, so the span is chosen by rule.

Answers carry the app's question and an outcome, DECLINE first-class (A-171 read
a no as a yes; A-170 dropped a refusal three times). Derived figures are never
claims - the app computes them later from claims, by a named rule.

Shadow rules, all load-bearing:
  - it reads the sentence at the top of the turn, before any save or branch, on
    a snapshot of the turn's context taken on the request thread;
  - it runs in a background thread, so the client's reply is not slowed and no
    write can change;
  - it is OFF unless INTAKE_SHADOW_INTERPRETATION is on (the start script turns
    it on for the bounded window);
  - its failures are recorded and never raised;
  - the quote check (R2, string equality) is RECORDED here, not enforced.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# v1.1 (Cowork 1062, 2026-09-14): a claim addresses a ROW (line AND product);
# the parts of each surface are named so span width is measured by position; a
# reason is never a claim; a text claim never repeats another claim's figure.
CONTRACT_VERSION = "v1.1"
TABLE = "intake_turn_interpretations_shadow"
URL = "https://api.openai.com/v1/responses"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  turn INT NULL,
  message_sha256 CHAR(64) NULL,
  message_chars INT NULL,
  contract_version VARCHAR(16) NOT NULL,
  model VARCHAR(64) NOT NULL DEFAULT '',
  status VARCHAR(16) NOT NULL,
  error TEXT NULL,
  elapsed_ms INT NULL,
  tokens_in INT NULL,
  tokens_out INT NULL,
  interpretation_json LONGTEXT NULL,
  quote_failures_json TEXT NULL,
  checks_json TEXT NULL,
  created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_draft_turn (draft_id, turn)
)
"""
_ensured = False
_lock = threading.Lock()

KINDS = ["ceiling", "actual", "typical", "concurrent", "cycle_time", "price", "cost", "count", "share", "date",
         "duration", "text", "choice", "identity"]
PERS = ["at_once", "day", "week", "month", "quarter", "year", "unit", "job", "none"]
OUTCOMES = ["accept", "decline", "choose", "provide", "close_list", "unsure", "asks_back"]


def _nullable(t: str) -> Dict[str, Any]:
  return {"type": [t, "null"]}


def _obj(props: Dict[str, Any]) -> Dict[str, Any]:
  return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


SCHEMA: Dict[str, Any] = _obj({
  "claims": {"type": "array", "items": _obj({
    "id": {"type": "string"},
    "subject": {"type": "string"},
    "line": _nullable("string"),
    "product": _nullable("string"),
    "kind": {"type": "string", "enum": KINDS},
    "value_number": _nullable("number"),
    "value_low": _nullable("number"),
    "value_high": _nullable("number"),
    "value_text": _nullable("string"),
    "per": {"type": "string", "enum": PERS},
    "currency": _nullable("string"),
    "is_percent": {"type": "boolean"},
    "precision": {"type": "string", "enum": ["exact", "approximate"]},
    "surface": {"type": "string"},
    "value_surface": _nullable("string"),
    "unit_surface": _nullable("string"),
    "qualifier_surface": _nullable("string"),
    "polarity": {"type": "string", "enum": ["affirm", "negate"]},
    "firmness": {"type": "string", "enum": ["fixed", "moveable", "unknown"]},
    "firmness_direction": {"type": "string", "enum": ["up_only", "down_only", "both", "none"]},
    "firmness_reason_surface": _nullable("string"),
    "provenance": {"type": "string", "enum": ["stated", "agreed_to_proposal", "correction"]},
    "role": {"type": "string", "enum": ["answered", "alongside"]},
    "supersedes": _nullable("string"),
    "refers_to": {"type": "array", "items": {"type": "string"}},
  })},
  "answers": {"type": "array", "items": _obj({
    "question_quote": {"type": "string"},
    "outcome": {"type": "string", "enum": OUTCOMES},
    "option": _nullable("string"),
    "surface": {"type": "string"},
  })},
  "unresolved": {"type": "array", "items": _obj({
    "surface": {"type": "string"},
    "value_number": _nullable("number"),
    "why": {"type": "string", "enum": ["which_line", "which_basis", "which_field", "unclear"]},
    "candidates": {"type": "array", "items": {"type": "string"}},
  })},
  "client_questions": {"type": "array", "items": _obj({"surface": {"type": "string"}})},
})

SYSTEM = (
  "You interpret ONE message a small-business owner has just sent, for a planning intake. You do not reply to her "
  "and you do not decide what the app does next. You record what she said, claim by claim, so nothing else ever has "
  "to read her words again.\n\n"
  "CLAIMS - one per fact she stated. A sentence can hold several; record every one, including facts she volunteered "
  "beside the answer (role alongside) as well as the answer itself (role answered).\n"
  "- subject: what the fact is about, in the app's terms where one fits (for example ops.capacity, ops.price, "
  "financials.rent, people.headcount, business.legal_entity), otherwise a short plain phrase.\n"
  "- line and product: the ROW it is about. line is a line_of_business and product a product, each copied exactly "
  "from `lines`. Null for both when it is about the whole business. When she names a line that holds several products "
  "and does not say which one, do NOT pick one: put the figure in unresolved with why which_line.\n"
  "- kind: ceiling (the most possible - 'flat out', 'the most we could'), actual (what really happens - 'in practice', "
  "'we usually finish'), typical (a usual figure or range), concurrent (how many at once), cycle_time (how long one "
  "takes), price, cost, count, share, date, duration, text, choice, identity.\n"
  "- value: value_number for one figure; value_low and value_high for a range ('five or six' is 5 to 6, never 5.5); "
  "value_text for a fact that is not a number. Write numbers as she meant them ('three hundred and forty' is 340; "
  "'1.2 million' is 1200000).\n"
  "- per: what it is per - at_once, day, week, month, quarter, year, unit, job, or none. 'Six at once' is at_once; "
  "'480 a week' is week; 'ten weeks per frame' is kind cycle_time, per unit.\n"
  "- precision: approximate when she hedged (about, around, roughly, most weeks), else exact.\n"
  "- SURFACE, BY RULE: the smallest contiguous span of HER MESSAGE that contains the value AND its unit or denominator "
  "AND any qualifier, copied character for character - same spelling, same case, same punctuation, spelled numbers "
  "left spelled. Not a paraphrase, not a summary, not a span you shorten to look tidy. If the value, unit and "
  "qualifier are far apart, the span runs from the first to the last of them.\n"
  "- value_surface, unit_surface, qualifier_surface: the exact words inside surface that carry the value, the unit or "
  "denominator, and the qualifier - each copied character for character, null when there is none. surface starts at "
  "the first of them and ends at the last; words before the first or after the last do not belong in surface.\n"
  "- A REASON IS NEVER A CLAIM OF ITS OWN: it goes in firmness_reason_surface of the claim it limits. A text claim "
  "never repeats a figure that is already the value of another claim.\n"
  "- polarity: negate for a fact stated as absence or refusal ('we have never borrowed', 'we hardly ever deal with "
  "homeowners'). A no is a fact, not a missing value.\n"
  "- firmness: fixed when she says it cannot move and why ('that's the building', 'the accreditation caps us'), "
  "moveable when she says it can; direction up_only / down_only when she limits only one way; "
  "firmness_reason_surface is her reason, verbatim.\n"
  "- provenance: stated; agreed_to_proposal when she is agreeing to a figure the app proposed in its last message; "
  "correction when she is correcting something - then supersedes names what it replaces in plain words.\n"
  "- refers_to: what a pronoun or 'the other one' points at, in plain words.\n"
  "NEVER COMPUTE. A ratio, a share, turns per year, a monthly figure from a yearly one - none of these is a claim. "
  "Record only what she said; the app does the arithmetic.\n\n"
  "ANSWERS - for each question in the app's last message that her message answers: question_quote copied verbatim "
  "from that message, and an outcome: accept, DECLINE, choose (with option), provide, close_list ('that's everyone'), "
  "unsure, asks_back. A decline is an answer, not the absence of one.\n\n"
  "UNRESOLVED - a figure you cannot place with confidence (which line, which basis, which field): its surface, its "
  "value, why, and candidate subjects. An honest gap is better than a confident wrong claim.\n\n"
  "CLIENT_QUESTIONS - anything she asked, as its surface.\n\n"
  "If her message states nothing, return empty lists."
)


def enabled() -> bool:
  return (os.getenv("INTAKE_SHADOW_INTERPRETATION") or "").strip().lower() in ("1", "true", "on", "yes")


def _connect():
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
  return get_mysql_connection()


def _post(**kw):
  from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore
  return post_openai_with_retries(**kw)


def _ensure(conn) -> None:
  global _ensured
  if _ensured:
    return
  with _lock:
    if _ensured:
      return
    cur = conn.cursor()
    try:
      cur.execute(_DDL)
      # v1.1 added checks_json; a table created by v1 gains it (errno 1060 =
      # the column is already there)
      try:
        cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN checks_json TEXT NULL")
      except Exception as exc:
        if getattr(exc, "errno", None) != 1060:
          raise
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      cur.close()
    _ensured = True


def _strip_private(obj: Any) -> Any:
  if isinstance(obj, dict):
    return {k: _strip_private(v) for k, v in obj.items() if not str(k).startswith("_")}
  if isinstance(obj, list):
    return [_strip_private(v) for v in obj]
  return obj


def build_input(*, message: str, messages: List[Dict[str, Any]], sections: Dict[str, Any], focus: str,
                confirm_question: str) -> str:
  """The shadow's whole input, serialised NOW - on the request thread, before the
  turn mutates anything - so it reads what the real turn reads at the same point.

  CONTEXT PARITY WITH THE LIVE ROUTER (Cowork 1055, 2026-09-14): the router is
  given the app's LAST MESSAGE only, plus the draft state. The shadow gets the same
  history, so a disagreement measures the contract, not a difference in context.
  A prior-claims digest, when it comes, is a separate labelled change."""
  convo = [m for m in (messages or []) if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
  last_assistant = next((str(m.get("content") or "") for m in reversed(convo) if m.get("role") == "assistant"), "")
  lines = []
  for lm in ((sections or {}).get("ops") or {}).get("lob_models") or []:
    for p in (lm or {}).get("products") or []:
      if isinstance(p, dict):
        lines.append({"line_of_business": lm.get("lob_name"), "product": p.get("product_name"),
                      "cadence": p.get("unit_cadence")})
  body = {
    "message": str(message or ""),
    "last_assistant_message": last_assistant,
    "context": "parity_last_assistant_only",
    "focus": focus,
    "confirm_question": confirm_question or "",
    "lines": lines,
    "known_facts": _strip_private(sections or {}),
  }
  return json.dumps(body, ensure_ascii=False, default=str)


def quote_failures(interpretation: Dict[str, Any], message: str) -> List[str]:
  """R2, recorded not enforced: every surface must appear verbatim in her message."""
  text = str(message or "")
  bad: List[str] = []
  for group in ("claims", "answers", "unresolved", "client_questions"):
    for i, item in enumerate((interpretation or {}).get(group) or []):
      surface = str((item or {}).get("surface") or "")
      if not surface or surface not in text:
        bad.append("%s[%d]" % (group, i))
    if group == "claims":
      for i, item in enumerate((interpretation or {}).get("claims") or []):
        reason = (item or {}).get("firmness_reason_surface")
        if reason and str(reason) not in text:
          bad.append("claims[%d].firmness_reason_surface" % i)
  return bad


def _figure_strings(v: Any) -> List[str]:
  try:
    f = float(v)
  except (TypeError, ValueError):
    return []
  out = {"%g" % f}
  if f == int(f):
    out.add(str(int(f)))
    out.add(format(int(f), ","))
  return [s for s in out if s]


def contract_checks(interpretation: Dict[str, Any], message: str) -> Dict[str, Any]:
  """Checks on the contract's OWN OUTPUT (Cowork 1062). None of them reads her
  words for meaning: they are string presence and string position.
    quote_failures       - a surface not verbatim in her message (R2)
    subspan_failures     - a value/unit/qualifier part not verbatim inside its surface
    span_excess_chars    - characters of surface outside the stretch from its first
                           named part to its last (the smallest-span rule, measured)
    figure_in_text_claim - a text claim whose value_text repeats, in digits, the value
                           of a numeric claim in the same interpretation
    reason_as_claim      - a text claim that repeats another claim's firmness reason
  Named limit: a repeated figure spelled out in words is not caught."""
  interp = interpretation or {}
  claims = [c for c in (interp.get("claims") or []) if isinstance(c, dict)]
  checks: Dict[str, Any] = {"quote_failures": quote_failures(interp, message), "subspan_failures": [],
                            "span_excess_chars": {}, "figure_in_text_claim": [], "reason_as_claim": []}
  for i, c in enumerate(claims):
    surface = str(c.get("surface") or "")
    positions = []
    for part in ("value_surface", "unit_surface", "qualifier_surface"):
      p = c.get(part)
      if not p:
        continue
      at = surface.find(str(p))
      if at < 0:
        checks["subspan_failures"].append("claims[%d].%s" % (i, part))
      else:
        positions.append((at, at + len(str(p))))
    if positions:
      start, end = min(a for a, _ in positions), max(b for _, b in positions)
      excess = len(surface) - (end - start)
      if excess > 0:
        checks["span_excess_chars"]["claims[%d]" % i] = excess
  figures = set()
  for c in claims:
    for key in ("value_number", "value_low", "value_high"):
      if c.get(key) is not None:
        figures.update(_figure_strings(c.get(key)))
  reasons = [str(c.get("firmness_reason_surface")).strip() for c in claims if c.get("firmness_reason_surface")]
  for i, c in enumerate(claims):
    text = c.get("value_text")
    if not text or c.get("value_number") is not None:
      continue
    text = str(text)
    if any(f in text for f in figures):
      checks["figure_in_text_claim"].append("claims[%d]" % i)
    stripped = text.strip()
    if any(stripped and (stripped in r or r in stripped) for r in reasons if r):
      checks["reason_as_claim"].append("claims[%d]" % i)
  return checks


def _parse(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  for item in (data or {}).get("output") or []:
    for part in (item or {}).get("content") or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
      if part.get("type") == "output_text" and part.get("text"):
        try:
          parsed = json.loads(part["text"])
          if isinstance(parsed, dict):
            return parsed
        except Exception:
          continue
  return None


def run(*, draft_id: str, turn: int, message: str, input_json: str) -> Dict[str, Any]:
  """One shadow interpretation, recorded. Never raises."""
  model = (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"
  t0 = time.monotonic()
  row: Dict[str, Any] = {"draft_id": draft_id, "turn": turn, "status": "error", "error": None, "model": model,
                         "interpretation": None, "quote_failures": [], "checks": None, "tokens_in": None,
                         "tokens_out": None}
  try:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
      raise RuntimeError("no OPENAI_API_KEY")
    payload = {
      "model": model,
      "input": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": input_json}],
      "text": {"format": {"type": "json_schema", "name": "intake_interpretation_v1", "schema": SCHEMA,
                          "strict": True}},
    }
    resp = _post(url=URL, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                 payload=payload, timeout_seconds=float(os.getenv("INTAKE_SHADOW_TIMEOUT_SECONDS") or 60),
                 retryable_status=(429, 500, 502, 503, 504), max_attempts=2)
    if getattr(resp, "status_code", 500) >= 400:
      raise RuntimeError("HTTP %s: %s" % (resp.status_code, str(getattr(resp, "text", ""))[:300]))
    data = resp.json()
    usage = data.get("usage") or {}
    row["tokens_in"], row["tokens_out"] = usage.get("input_tokens"), usage.get("output_tokens")
    parsed = _parse(data)
    if parsed is None:
      raise RuntimeError("no parseable interpretation in the response")
    row["interpretation"] = parsed
    row["checks"] = contract_checks(parsed, message)
    row["quote_failures"] = row["checks"]["quote_failures"]
    row["status"] = "ok"
  except Exception as exc:  # noqa: BLE001 - shadow failures are recorded, never raised
    row["error"] = ("%s: %s" % (type(exc).__name__, exc))[:2000]
  row["elapsed_ms"] = int((time.monotonic() - t0) * 1000.0)
  _record(row, message)
  return row


def _record(row: Dict[str, Any], message: str) -> None:
  try:
    conn = _connect()
    try:
      _ensure(conn)
      cur = conn.cursor()
      try:
        cur.execute(
          f"INSERT INTO {TABLE} (draft_id, turn, message_sha256, message_chars, contract_version, model, status, error, "
          "elapsed_ms, tokens_in, tokens_out, interpretation_json, quote_failures_json, checks_json) "
          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
          (row["draft_id"], row["turn"], hashlib.sha256(str(message or "").encode("utf-8")).hexdigest(),
           len(str(message or "")), CONTRACT_VERSION, row["model"], row["status"], row["error"], row["elapsed_ms"],
           row["tokens_in"], row["tokens_out"],
           json.dumps(row["interpretation"], ensure_ascii=False) if row["interpretation"] is not None else None,
           json.dumps(row["quote_failures"]),
           json.dumps(row["checks"]) if row.get("checks") is not None else None))
        try:
          conn.commit()
        except Exception:
          pass
      finally:
        cur.close()
    finally:
      try:
        conn.close()
      except Exception:
        pass
  except Exception as exc:  # noqa: BLE001
    logger.error("SHADOW_INTERPRETATION_WRITE_FAILED draft=%s turn=%s: %s", row.get("draft_id"), row.get("turn"), exc)


def start(*, draft_id: str, turn: int, message: str, messages: List[Dict[str, Any]], sections: Dict[str, Any],
          focus: str, confirm_question: str) -> Optional[threading.Thread]:
  """Start the shadow for this turn, or do nothing. The input is snapshotted here;
  the per-run identity (draft, for the response cache and usage ledger) is carried
  into the thread with a copied context."""
  if not enabled() or not str(message or "").strip() or not str(draft_id or "").strip():
    return None
  input_json = build_input(message=message, messages=messages, sections=sections, focus=focus,
                           confirm_question=confirm_question)
  ctx = contextvars.copy_context()
  th = threading.Thread(target=ctx.run, args=(run,),
                        kwargs={"draft_id": str(draft_id), "turn": turn, "message": str(message), "input_json": input_json},
                        name="shadow-interp-%s-%s" % (str(draft_id)[:8], turn), daemon=True)
  th.start()
  return th


def for_draft(conn, draft_id: str) -> List[Dict[str, Any]]:
  _ensure(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(f"SELECT id, turn, message_chars, contract_version, model, status, error, elapsed_ms, tokens_in, "
                f"tokens_out, interpretation_json, quote_failures_json, checks_json, created_at FROM {TABLE} "
                f"WHERE draft_id=%s ORDER BY id", (str(draft_id),))
    out = []
    for r in cur.fetchall():
      row = dict(r)
      for src, dst in (("interpretation_json", "interpretation"), ("quote_failures_json", "quote_failures"),
                       ("checks_json", "checks")):
        raw = row.pop(src, None)
        try:
          row[dst] = json.loads(raw) if raw else None
        except Exception:
          row[dst] = raw
      out.append(row)
    return out
  finally:
    cur.close()
