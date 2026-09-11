"""THE RESTRUCTURE STAYS THE CLIENT'S BUSINESS (Nick 2026-09-11).

"A client can be handed a plan for a business they didn't describe, with three
lines they never mentioned, and nothing tells them. That's not a restructure,
that's a different company."

Five rules, applied to the executive's bounds on the POST-INTAKE restructure
path only. The intake coherence walk keeps its own bounds: it proposes options
to a client who is present and consents to each one.

  1. NEW LINES ONLY IF THE CLIENT NAMED THEM. Each new line must carry the
     client's own words, verbatim, naming it, and the quote is checked against
     what the client actually typed. No quote, no line.
  2. NO DROPPING A CLIENT'S LINE WITHOUT ASKING. A post-intake run cannot ask,
     so no line is ever dropped. A proposed drop is recorded and surfaced as a
     question for the client, never applied.
  3. PRICE AND VOLUME CEILINGS TIED TO MARKET DATA. A ceiling is the lower of
     the executive's judgment and a recorded market figure. With no market
     figure there is no headroom above the client's own price and capacity,
     and a new line (whose price and size would otherwise be the executive's
     own estimate) has nothing to size it. FOR NOW (Nick 2026-09-11) the
     intake's judged price ceiling is the market figure for PRICE
     (`intake_price_ceiling`) - the same judgment the coherence stage uses to
     decide whether a price is believable, which the client has seen. It
     exists only where the intake authored bounds. `market_ceiling` stays the
     plug point: when a real source exists, it replaces the estimate.
  4. A FAILED REVIEW BLOCKS. Enforced in the handler.
  5. ALWAYS LABELLED. The handler labels the workbook (name, cover and a
     What Changed sheet) and the email, and withholds the auto-written plan.
     `restructure_changes` is the ONE list of what changed, read from the TWO
     DELIVERED MODELS (the plan as described, before the restructure, and the
     plan that ships) - never from the design, whose targets do not all land
     (the team payroll target is recorded, never applied to named people).
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

RESTRUCTURED_LABEL = "RESTRUCTURED PLAN - not the business as described"

_MIN_QUOTE_CHARS = 12
_MIN_QUOTE_WORDS = 3
_STOP = frozenset((
  "the and for with our your from that this into new line lines product products "
  "service services offering offerings sales revenue stream streams"
).split())

#: market_ceiling(entry, kind) -> the market-backed ceiling, or None when no
#: market figure exists. kind "price" / "volume" return a MULTIPLIER of the
#: current level; kind "new_line" returns a quarterly revenue cap in dollars.
#: It may return (value, source_name) to name where the figure came from.
MarketCeiling = Callable[[Dict[str, Any], str], Any]

INTAKE_PRICE_SOURCE = "intake_price_band"
_FACT_SEP = "␟"   # the coherence stage keys its price facts "lob<U+241F>product"


def _norm(text: Any) -> str:
  return " ".join(re.sub(r"[^a-z0-9$%]+", " ", str(text or "").lower()).split())


def _stems(text: Any) -> set:
  return {w[:5] for w in _norm(text).split() if len(w) >= 4 and w not in _STOP}


def _line_key(*parts: Any) -> str:
  return _norm(" ".join(str(p or "") for p in parts))


def _unpack(result: Any) -> Tuple[Optional[float], str]:
  if isinstance(result, tuple):
    value, source = result[0], str(result[1] or "market")
  else:
    value, source = result, "market"
  try:
    return (float(value) if value is not None else None), source
  except (TypeError, ValueError):
    return None, source


def intake_price_ceiling(
  financials_json: Optional[Dict[str, Any]],
  current_prices: Optional[Dict[str, Any]],
) -> Optional[MarketCeiling]:
  """The intake's judged price ceiling as the market figure for PRICE.

  The coherence stage stores it as a durable dollar ceiling per line
  (_coherence.price_market_facts) - the judgment it uses to decide whether a
  price is believable, re-judged only when the client's market facts change.
  `current_prices` is the model's current price per line, keyed "lob/product".
  Returns None when the intake authored no ceilings (no market figure); for
  volume and new lines it has nothing and returns None."""
  state = (financials_json or {}).get("_coherence")
  facts = (state or {}).get("price_market_facts") if isinstance(state, dict) else None
  ceilings: Dict[str, float] = {}
  for key, fact in (facts or {}).items():
    if _FACT_SEP not in str(key) or not isinstance(fact, dict):
      continue
    lob, product = str(key).split(_FACT_SEP, 1)
    try:
      dollars = float(fact.get("ceiling_dollars") or 0.0)
    except (TypeError, ValueError):
      continue
    if dollars > 0:
      ceilings[_line_key(lob, product)] = dollars
  if not ceilings:
    return None
  prices: Dict[str, float] = {}
  for key, price in (current_prices or {}).items():
    try:
      if float(price) > 0:
        prices[_norm(key)] = float(price)
    except (TypeError, ValueError):
      continue

  def ceiling(entry: Dict[str, Any], kind: str) -> Any:
    if kind != "price":
      return None
    key = _line_key(entry.get("lob"), entry.get("product"))
    dollars, price = ceilings.get(key), prices.get(key)
    if not dollars or not price:
      return None
    return (dollars / price, INTAKE_PRICE_SOURCE)

  return ceiling


def client_statements_from_messages(messages: Any) -> List[str]:
  """Everything the client typed during the intake, in order."""
  out: List[str] = []
  for m in messages if isinstance(messages, list) else []:
    if isinstance(m, dict) and str(m.get("role") or "").strip().lower() == "user":
      text = str(m.get("content") or "").strip()
      if text:
        out.append(text)
  return out


def quote_is_the_clients(quote: Any, statements: List[str], line_name: str = "") -> Tuple[bool, str]:
  """(ok, reason). The quote must be the client's own words - found in what
  they typed, not a paraphrase - and it must name the line."""
  q = _norm(quote)
  if len(q) < _MIN_QUOTE_CHARS or len(q.split()) < _MIN_QUOTE_WORDS:
    return False, "no_client_quote"
  if not any(q in _norm(s) for s in statements or []):
    return False, "quote_not_in_the_clients_words"
  name = _stems(line_name)
  if name and not (name & _stems(q)):
    return False, "quote_does_not_name_the_line"
  return True, "named_by_the_client"


def _merge(prior: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out = list(prior or [])
  for item in new:
    if item not in out:
      out.append(item)
  return out


def bound_to_the_clients_business(
  bounds: Dict[str, Any],
  *,
  client_statements: List[str],
  market_ceiling: Optional[MarketCeiling] = None,
) -> Dict[str, Any]:
  """The executive's validated bounds, held to the client's own business.
  Idempotent: re-applying after a review tightening changes nothing more and
  keeps the record of what was held back."""
  b = copy.deepcopy(bounds or {})
  prior = b.get("client_bounds") if isinstance(b.get("client_bounds"), dict) else {}
  rec: Dict[str, List[Dict[str, Any]]] = {
    "new_lines_kept": [], "new_lines_dropped": [], "drops_proposed": [],
    "price_capped": [], "volume_capped": [], "headroom_allowed": [],
  }

  kept: List[Dict[str, Any]] = []
  for nl in b.get("new_line_candidates") or []:
    if not isinstance(nl, dict):
      continue
    name = f"{nl.get('lob') or ''} {nl.get('product') or ''}".strip()
    ok, why = quote_is_the_clients(nl.get("client_quote"), client_statements, name)
    if ok:
      cap, _src = _unpack(market_ceiling(nl, "new_line")) if market_ceiling else (None, "")
      if cap is None or cap <= 0:
        ok, why = False, "no_market_data"
      else:
        nl["q11_quarterly_revenue_max"] = round(min(float(nl.get("q11_quarterly_revenue_max") or 0.0), float(cap)), 2)
    entry = {"name": name, "client_quote": str(nl.get("client_quote") or "")[:300], "reason": why}
    if ok:
      kept.append(nl)
      rec["new_lines_kept"].append(entry)
    else:
      rec["new_lines_dropped"].append(entry)
  b["new_line_candidates"] = kept

  for line in b.get("existing_lines") or []:
    if not isinstance(line, dict):
      continue
    label = f"{line.get('lob') or ''}/{line.get('product') or ''}"
    if line.get("can_drop"):
      rec["drops_proposed"].append({"line": label, "rationale": str(line.get("rationale") or "")[:300]})
      line["can_drop"] = False
    for key, kind in (("price_multiplier_max", "price"), ("volume_multiplier_max", "volume")):
      judged = float(line.get(key) or 1.0)
      fact, source = _unpack(market_ceiling(line, kind)) if market_ceiling else (None, "")
      cap = max(1.0, min(judged, fact) if fact is not None else 1.0)
      if abs(cap - judged) > 1e-9:
        rec[f"{kind}_capped"].append({
          "line": label, "kind": kind, "judged": round(judged, 4), "cap": round(cap, 4),
          "source": source if fact is not None else "no_market_data",
        })
      if cap > 1.0 + 1e-9:
        rec["headroom_allowed"].append({"line": label, "kind": kind, "cap": round(cap, 4), "source": source})
      line[key] = cap

  b["client_bounds"] = {k: _merge(prior.get(k) or [], v) for k, v in rec.items()}
  return b


# --------------------------------------------------------------------------
# What changed - the TWO DELIVERED MODELS, never the design.
# --------------------------------------------------------------------------
def _money(value: Any) -> str:
  try:
    return f"${float(value):,.0f}"
  except (TypeError, ValueError):
    return str(value)


_SOURCE_WORDS = {
  INTAKE_PRICE_SOURCE: "raised within the price ceiling judged at intake",
  "market": "raised within the recorded market figure",
}

RESTRUCTURE_HEADLINE = "RESTRUCTURED PLAN - NOT THE BUSINESS AS DESCRIBED"
RESTRUCTURE_EXPLAINER = (
  "The plan built on the business as the client described it did not pass. The "
  "executive reshaped it, inside the client's own business, to find a version that "
  "works. None of the changes below was stated by the client.")

_METRICS = (
  ("Revenue", "revenue", ()),
  ("Payroll cost, incl. employer costs", "payroll", ()),
  ("Rent", "lease_rent", ()),
  ("Cost of goods", "cogs", ("cost_of_goods_sold",)),
  ("Marketing", "marketing", ()),
  ("General and admin", "g_and_a", ("general_and_administrative",)),
  ("EBITDA", "ebitda", ()),
)
_PERIODS = (("year 1", range(1, 5)), ("year 3", range(9, 13)))
_DRIVER_Q = 11   # the mature quarter the restructure designs to


def _quarters(finmo: Any) -> Dict[int, Dict[str, Any]]:
  out: Dict[int, Dict[str, Any]] = {}
  for r in (finmo or {}).get("quarter_rows") or [] if isinstance(finmo, dict) else []:
    if isinstance(r, dict):
      try:
        out[int(float(r.get("quarter_index") or 0))] = r
      except (TypeError, ValueError):
        continue
  return out


def _period_sum(quarters: Dict[int, Dict[str, Any]], key: str, aliases: Tuple[str, ...], idx: range) -> Optional[float]:
  total, seen = 0.0, False
  for i in idx:
    row = quarters.get(i) or {}
    value = row.get(key)
    for alias in aliases:
      if value is None:
        value = row.get(alias)
    try:
      total += float(value)
      seen = True
    except (TypeError, ValueError):
      continue
  return total if seen else None


def _drivers(model_input: Any) -> Dict[Tuple[str, str], Dict[str, float]]:
  out: Dict[Tuple[str, str], Dict[str, float]] = {}
  rows = ((model_input or {}).get("sections") or {}).get("revenue") if isinstance(model_input, dict) else None
  for r in rows or []:
    if not isinstance(r, dict):
      continue
    driver = str(r.get("driver") or "").strip()
    if driver not in ("Unit Price", "Capacity"):
      continue
    try:
      value = float((r.get("values") or [])[_DRIVER_Q])
    except (TypeError, ValueError, IndexError):
      continue
    out.setdefault((str(r.get("lob") or ""), str(r.get("product") or "")), {})[driver] = value
  return out


def _moved(before: Optional[float], after: Optional[float]) -> bool:
  if before is None or after is None:
    return before != after
  return abs(after - before) > max(0.005, 0.005 * max(abs(before), abs(after)))


def restructure_changes(
  design: Dict[str, Any],
  client_bounds: Optional[Dict[str, Any]] = None,
  *,
  before: Optional[Dict[str, Any]] = None,
  after: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
  """THE ONE LIST of what a delivered restructure changed, rows of
  {area, as_described, restructured, note}. Every figure is read from the two
  DELIVERED MODELS - `before` (the plan built on the client's description,
  before the restructure) and `after` (the plan that ships), each
  {"finmo": finmo_json, "model_input": model_input_json}. A design target that
  never landed cannot appear. The design and client_bounds contribute only
  what no model shows: the client's words, a wind-down NOT applied, headroom
  held back. The workbook's What Changed sheet and the email render these."""
  cb = client_bounds or {}
  qb, qa = _quarters((before or {}).get("finmo")), _quarters((after or {}).get("finmo"))
  rows: List[Dict[str, str]] = []

  def row(area: str, was: Any, now: Any, note: str = "") -> None:
    rows.append({"area": area, "as_described": str(was or ""), "restructured": str(now or ""),
                 "note": note})

  for label, key, aliases in _METRICS:
    for period, idx in _PERIODS:
      b, a = _period_sum(qb, key, aliases, idx), _period_sum(qa, key, aliases, idx)
      if b is None and a is None:
        continue
      note = "unchanged"
      if _moved(b, a):
        note = ""
        if key not in ("revenue", "ebitda"):
          rb = _period_sum(qb, "revenue", (), idx)
          ra = _period_sum(qa, "revenue", (), idx)
          if rb and ra and b is not None and a is not None:
            note = f"{b / rb:.1%} of revenue -> {a / ra:.1%}"
      row(f"{label} ({period})", _money(b) if b is not None else "", _money(a) if a is not None else "", note)

  db = _drivers((before or {}).get("model_input"))
  da = _drivers((after or {}).get("model_input"))
  headroom = {(h.get("line"), h.get("kind")): h.get("source") for h in cb.get("headroom_allowed") or []}
  for (lob, product), after_vals in da.items():
    name = product or lob
    before_vals = db.get((lob, product))
    if before_vals is None:
      quote = next((k.get("client_quote") for k in cb.get("new_lines_kept") or []
                    if product and product in str(k.get("name"))), "")
      row(f"New line: {name}", "not in the plan", "in the plan",
          f'the client named it: "{quote}"' if quote else "")
      continue
    label = f"{lob}/{product}"
    for driver, word, kind in (("Unit Price", "price", "price"), ("Capacity", "capacity", "volume")):
      b, a = before_vals.get(driver), after_vals.get(driver)
      if not _moved(b, a):
        continue
      fmt = _money if driver == "Unit Price" else (lambda v: f"{float(v):,.0f}" if v is not None else "")
      row(f"{name}: {word} (year 3)", fmt(b), fmt(a), _SOURCE_WORDS.get(headroom.get((label, kind)), ""))

  for dp in cb.get("drops_proposed") or []:
    row(f"{dp.get('line')}", "in the plan", "kept in the plan",
        "winding it down was proposed - NOT applied; it needs the client's decision")
  held = [f"{c.get('line')} ({c.get('kind')})" for c in (cb.get("price_capped") or []) + (cb.get("volume_capped") or [])
          if c.get("source") == "no_market_data"]
  if held:
    # What was held is the restructure's OWN price/volume lever - the rows
    # above show every difference the delivered model actually has.
    row("Restructure price and volume levers", "", "held at 1.0x - not used",
        "no market figure for: " + ", ".join(held[:8]))
  unused = [f"{c.get('name')} ({c.get('reason')})" for c in cb.get("new_lines_dropped") or []]
  if unused:
    row("New lines suggested but not used", "", "not in the plan", ", ".join(unused[:6]))
  return rows


def restructure_label_text(rows: List[Dict[str, str]]) -> str:
  """The email's account of a delivered restructure - the same rows the
  workbook's What Changed sheet shows."""
  out = [RESTRUCTURE_HEADLINE + ".", RESTRUCTURE_EXPLAINER]
  for r in rows or []:
    line = f"- {r.get('area')}: "
    if r.get("as_described"):
      line += f"{r['as_described']} as described -> "
    line += str(r.get("restructured") or "")
    if r.get("note"):
      line += f" ({r['note']})"
    out.append(line)
  out.append("The workbook's What Changed sheet lists the same changes. "
             "No written plan was produced automatically for this restructure.")
  return "\n".join(out)


__all__ = [
  "INTAKE_PRICE_SOURCE",
  "RESTRUCTURED_LABEL",
  "bound_to_the_clients_business",
  "client_statements_from_messages",
  "intake_price_ceiling",
  "quote_is_the_clients",
  "restructure_changes",
  "restructure_label_text",
]
