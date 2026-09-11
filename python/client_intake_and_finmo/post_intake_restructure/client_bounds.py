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
     own estimate) has nothing to size it. The app holds no market price or
     demand dataset today, so `market_ceiling` is None until one is wired.
  4. A FAILED REVIEW BLOCKS. Enforced in the handler.
  5. ALWAYS LABELLED. The handler labels the workbook and the email and
     withholds the auto-written plan. `restructure_label_text` is the ONE
     account of what changed.
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
MarketCeiling = Callable[[Dict[str, Any], str], Optional[float]]


def _norm(text: Any) -> str:
  return " ".join(re.sub(r"[^a-z0-9$%]+", " ", str(text or "").lower()).split())


def _stems(text: Any) -> set:
  return {w[:5] for w in _norm(text).split() if len(w) >= 4 and w not in _STOP}


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
    "price_capped": [], "volume_capped": [],
  }

  kept: List[Dict[str, Any]] = []
  for nl in b.get("new_line_candidates") or []:
    if not isinstance(nl, dict):
      continue
    name = f"{nl.get('lob') or ''} {nl.get('product') or ''}".strip()
    ok, why = quote_is_the_clients(nl.get("client_quote"), client_statements, name)
    if ok:
      cap = market_ceiling(nl, "new_line") if market_ceiling else None
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
      fact = market_ceiling(line, kind) if market_ceiling else None
      cap = max(1.0, min(judged, float(fact)) if fact is not None else 1.0)
      if abs(cap - judged) > 1e-9:
        rec[f"{kind}_capped"].append({
          "line": label, "kind": kind, "judged": round(judged, 4), "cap": round(cap, 4),
          "source": "market" if fact is not None else "no_market_data",
        })
      line[key] = cap

  b["client_bounds"] = {k: _merge(prior.get(k) or [], v) for k, v in rec.items()}
  return b


def _money(value: Any) -> str:
  try:
    return f"${float(value):,.0f}"
  except (TypeError, ValueError):
    return str(value)


def restructure_label_text(
  design: Dict[str, Any],
  client_bounds: Optional[Dict[str, Any]] = None,
  *,
  stated: Optional[Dict[str, Any]] = None,
) -> str:
  """The ONE account of a delivered restructure: that it is one, and every
  change from the business the client described."""
  d = design or {}
  cb = client_bounds or {}
  st = stated or {}
  out = [
    "THIS IS A RESTRUCTURED PLAN - NOT THE BUSINESS AS DESCRIBED.",
    "The plan built on the business as the client described it did not pass. The "
    "executive reshaped it, inside the client's own business, to find a version that "
    "works. None of the changes below was stated by the client:",
  ]
  team = (d.get("team") or {}).get("annual_payroll")
  if team is not None:
    was = st.get("payroll_total_year1")
    out.append(f"- Team payroll: {_money(team)} a year"
               + (f" (as described: {_money(was)})" if was is not None else ""))
  rent = (d.get("facility") or {}).get("quarterly_rent_target")
  if rent is not None:
    out.append(f"- Rent: {_money(rent)} a quarter")
  cs = d.get("cost_structure") or {}
  for key, label in (("cogs_percent_of_revenue", "Cost of goods"),
                     ("marketing_percent_of_revenue", "Marketing"),
                     ("g_and_a_percent_of_revenue", "General and admin")):
    if cs.get(key) is not None:
      out.append(f"- {label}: {float(cs[key]):.1%} of revenue")
  mix = d.get("revenue_mix") or {}
  for ln in mix.get("lines") or []:
    out.append(
      f"- {ln.get('product') or ln.get('lob')}: volume x{float(ln.get('volume_multiplier_q11') or 1.0):.2f}, "
      f"price x{float(ln.get('price_multiplier_q11') or 1.0):.2f} by year 3")
  for nl in mix.get("new_lines") or []:
    quote = next((k.get("client_quote") for k in cb.get("new_lines_kept") or []
                  if str(nl.get("product") or "") and str(nl.get("product")) in str(k.get("name"))), "")
    out.append(f"- NEW LINE the client named: {nl.get('product') or nl.get('lob')}"
               + (f' - in their words: "{quote}"' if quote else ""))
  for dp in cb.get("drops_proposed") or []:
    out.append(f"- Proposed but NOT applied (needs the client's decision): winding down {dp.get('line')}")
  held = [f"{c.get('line')} {c.get('kind')}" for c in (cb.get("price_capped") or []) + (cb.get("volume_capped") or [])
          if c.get("source") == "no_market_data"]
  if held:
    out.append("- Held at the client's own figures for lack of market data: " + ", ".join(held[:8]))
  unused = [f"{c.get('name')} ({c.get('reason')})" for c in cb.get("new_lines_dropped") or []]
  if unused:
    out.append("- New lines suggested but not used: " + ", ".join(unused[:6]))
  out.append("No written plan was produced automatically for this restructure.")
  return "\n".join(out)


__all__ = [
  "RESTRUCTURED_LABEL",
  "bound_to_the_clients_business",
  "client_statements_from_messages",
  "quote_is_the_clients",
  "restructure_label_text",
]
