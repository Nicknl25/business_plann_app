"""COHERENCE SECTION GATE — intake does not close while the plan fails.

This module is the thin brain intake_consult.py calls at every
financials→done completion site. It owns the coherence state (persisted
under financials_json["_coherence"], the same underscore-private family
as the stage flags), the two F-core artifacts (margin band, bounds —
each authored ONCE and stamped with the compact-digest hash), the
silent corner-first check, the lever walk, and the three honest exits.

Doctrine (locked):
  - Q11-anchored structural inequalities only. Early-quarter losses are
    never evaluated, never mentioned.
  - Funding is OUT: never questioned, never gated. At most a readback.
  - FAIL surfaces immediately (monotone — stable on the configuration);
    PASS surfaces only at its firm-up point (a completion attempt).
  - Corner-first: if even the most favorable believable corner fails,
    the client is never walked through corrections that can't sum.
  - One binding constraint at a time, largest dollar first; the gap
    must visibly move; movement acknowledged in dollars.
  - Exits: converged (intake completes, readback appended), parked
    (draft stays open, nothing ships, no bullying), roadmap (no plan;
    milestones in the client's own numbers; the numbers stay).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from client_intake_and_finmo.intake_coherence import controller as _ctl
from client_intake_and_finmo.intake_coherence.evaluator import (
  basis_from_intake,
  thresholds_from_margin_band,
)

# App-authored marker present in EVERY coherence question and re-ask so
# the router frame survives retries (string-matching on app-authored
# text only — never on client language).
COHERENCE_MARKER = "work on paper"

_MONEY_RE = re.compile(r"\$[\d,]+")


def _f(value: Any, default: float = 0.0) -> float:
  try:
    if value in (None, ""):
      return default
    n = float(value)
  except (TypeError, ValueError):
    return default
  return default if n != n else n


def _fmt(v: float) -> str:
  return ("-$" if v < 0 else "$") + f"{abs(v):,.0f}"


def _pct(v: float) -> str:
  return f"{v * 100:.1f}%"


# ------------------------------------------------------------------ state

def get_state(financials_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  state = (financials_json or {}).get("_coherence")
  return dict(state) if isinstance(state, dict) else {}


def put_state(financials_json: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
  next_fin = dict(financials_json or {})
  next_fin["_coherence"] = state
  return next_fin


def walking_round_live(
  financials_json: Optional[Dict[str, Any]],
  last_assistant: Optional[str],
) -> bool:
  state = get_state(financials_json)
  return (
    state.get("status") in (_ctl.STATUS_WALKING, _ctl.STATUS_PARKED)
    and bool(state.get("round"))
    and COHERENCE_MARKER in str(last_assistant or "")
  )


def router_frame(financials_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  """The coherence_controller frame for the intent router when a round
  question is live: the round's options with their concrete numbers, so
  the router maps intent → an option id or a concrete field patch."""
  state = get_state(financials_json)
  rnd = state.get("round")
  if not isinstance(rnd, dict):
    return None
  options = []
  for o in rnd.get("options") or []:
    entry = {"id": o.get("id"), "label": o.get("label")}
    if o.get("prices"):
      entry["prices"] = o["prices"]
    if o.get("moves"):
      entry["moves"] = {k: v.get("to_display") for k, v in (o.get("moves") or {}).items()}
    options.append(entry)
  patch_targets = ["coherence.option"]
  if rnd.get("key") == _ctl.ROUND_PRICING:
    patch_targets.append("ops.product_overrides")
  else:
    for o in rnd.get("options") or []:
      for fp in ((o.get("patch") or {}).get("fields") or []):
        patch_targets.append(f"{fp.get('group')}.{fp.get('field')}")
  return {
    "current_question": f"coherence_{rnd.get('key')}",
    "round_key": rnd.get("key"),
    "options": options,
    "patch_targets": sorted(set(patch_targets)),
    "gap_open_display": _fmt(_f(state.get("gap_open"))),
  }


# ------------------------------------------------- F-core artifact stamps

def _ensure_margin_band(
  state: Dict[str, Any],
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  market_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  """Author the margin band ONCE at F-core, stamped with the compact
  digest hash. Knob edits re-evaluate; only an identity-level digest
  change re-judges. Post-intake reuses this stamp (initial_grid runner
  checks it before authoring)."""
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (
    build_operating_model_digest,
  )
  compact = build_operating_model_digest(
    ops_json, people_json, market_json, marketing_model_json,
  )
  digest_hash = _ctl.stable_digest_hash(compact)
  if state.get("margin_band_judgment") and state.get("digest_hash") == digest_hash:
    return state
  state = dict(state)
  # Identity-level change: EVERY judged artifact keyed to the old
  # identity is stale — the band re-authors below; growth, bounds,
  # corner, and the live round must re-derive on the new identity.
  if state.get("digest_hash") and state.get("digest_hash") != digest_hash:
    for stale_key in ("judged_growth", "growth_error", "bounds", "bounds_error", "corner", "round"):
      state.pop(stale_key, None)
  state["digest_hash"] = digest_hash
  try:
    from client_intake_and_finmo.post_intake_headcount.band_fitting import (
      operator_cost_levels,
    )
    from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (
      gpt_author_margin_band_once,
      validate_margin_band_judgment,
    )
    from client_intake_and_finmo.post_intake_solver.structural_feasibility_check import (
      authoritative_annual_revenue,
    )
    annual_revenue = authoritative_annual_revenue(
      ops_json=ops_json,
      financials_year1_json=financials_year1_json,
      financials_json=financials_json,
    )
    facts = dict(operator_cost_levels(financials_json, annual_revenue) or {})
    # The runner enriches payroll%/rent% from the engine's Q1 row; at
    # intake the same quantities come from the stated facts directly.
    ann = _f(annual_revenue)
    if ann > 0:
      payroll = _f(financials_json.get("current_payroll")) or _f(financials_json.get("payroll_total_year1"))
      payroll += _f(financials_json.get("owner_compensation")) * 12.0
      if payroll > 0:
        facts["payroll_percent_of_revenue"] = round(payroll / ann, 6)
      rent = _f(financials_json.get("monthly_rent_expense")) * 12.0
      if rent > 0:
        facts["rent_percent_of_revenue"] = round(rent / ann, 6)
    result = gpt_author_margin_band_once(compact=compact, stated_cost_facts=facts or None)
    if result.get("ok") and result.get("judgment"):
      state["margin_band_judgment"] = validate_margin_band_judgment(judgment=result["judgment"])
      state.pop("margin_band_error", None)
    else:
      state["margin_band_error"] = str(result.get("error") or "author_failed")[:300]
  except Exception as exc:  # noqa: BLE001 — thresholds fall back to doctrine constants
    state["margin_band_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
  return state


def _ensure_growth_judgment(
  state: Dict[str, Any],
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  market_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Dict[str, Any]:
  """Author the growth judgment ONCE at the gate (same seat, same
  inputs, same clamps as the initial-grid runner). Stamped to
  state["judged_growth"]; post-intake reuses the stamp. A failed call
  leaves no stamp — the evaluator falls back to the authorable fence,
  exactly the pre-judgment behavior."""
  if state.get("judged_growth"):
    return state
  state = dict(state)
  try:
    from client_intake_and_finmo.post_intake_amalgamated.mirror import (
      build_operating_model_digest,
    )
    from client_intake_and_finmo.post_intake_headcount.deterministic_revenue_proposer import (
      _DEFAULT_QOQ_MAX,
    )
    from client_intake_and_finmo.post_intake_headcount.gpt_growth_judgment import (
      annual_to_qoq,
      gpt_author_growth_judgment_once,
    )
    compact = build_operating_model_digest(
      ops_json, people_json, market_json, marketing_model_json,
    )
    ann_rev = _f(financials_json.get("current_revenue"))
    result = gpt_author_growth_judgment_once(
      compact=compact,
      current_annual_revenue=ann_rev if ann_rev > 0 else None,
    )
    if result.get("ok") and result.get("judgment"):
      j = result["judgment"]
      rail = float(_DEFAULT_QOQ_MAX)
      state["judged_growth"] = {
        "qoq_start": round(min(max(annual_to_qoq(j["year1_annual_growth"]), 0.0), rail), 6),
        "qoq_end": round(min(max(annual_to_qoq(j["mature_annual_growth"]), 0.0), rail), 6),
        "source": "coherence_gate_growth_judgment",
        "year1_annual_growth": j["year1_annual_growth"],
        "mature_annual_growth": j["mature_annual_growth"],
      }
      state.pop("growth_error", None)
    else:
      state["growth_error"] = str(result.get("error") or "author_failed")[:300]
  except Exception as exc:  # noqa: BLE001 — fence fallback stands
    state["growth_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
  return state


def _intake_current_structure(
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Dict[str, Any]:
  """The bounds author's current_structure payload, built from intake's
  own facts (mirror of the post-intake _rs_current_structure shape)."""
  from client_intake_and_finmo.intake_coherence.evaluator import GROWTH_FENCE_Q11
  split = _ctl.ops_line_split(ops_json, financials_json)
  ann_rev = _f(financials_json.get("current_revenue"))
  prices = {}
  lines_quarterly = {}
  for line in split:
    key = f"{line['lob']}/{line['product']}"
    prices[key] = line["unit_price"]
    q1 = _f(line.get("q1_revenue_quarterly"))
    lines_quarterly[key] = {"q1": round(q1, 2), "q11": round(q1 * GROWTH_FENCE_Q11, 2)}
  payroll = _f(financials_json.get("current_payroll")) or _f(financials_json.get("payroll_total_year1"))
  payroll += _f(financials_json.get("owner_compensation")) * 12.0
  return {
    "q1_revenue": round(ann_rev / 4.0, 2) if ann_rev > 0 else None,
    "q1_payroll": round(payroll / 4.0, 2) if payroll > 0 else None,
    "q1_rent": round(_f(financials_json.get("monthly_rent_expense")) * 3.0, 2),
    "q1_unit_prices": prices,
    "revenue_lines_quarterly": lines_quarterly,
  }


def _ensure_bounds(
  state: Dict[str, Any],
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  market_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Dict[str, Any]:
  """Author the bounds box ONCE (only reached on structural FAIL).
  Same digest identity as the margin band."""
  if state.get("bounds"):
    return state
  state = dict(state)
  try:
    from client_intake_and_finmo.post_intake_amalgamated.mirror import (
      build_operating_model_digest,
    )
    from client_intake_and_finmo.post_intake_restructure.constraint_author import (
      gpt_author_restructure_bounds_once,
      validate_restructure_bounds,
    )
    from client_intake_and_finmo.post_intake_restructure.designer import (
      stated_owner_annual_wage,
    )
    compact = build_operating_model_digest(
      ops_json, people_json, market_json, marketing_model_json,
    )
    stated = {
      k: financials_json.get(k)
      for k in (
        "current_revenue", "current_cogs", "payroll_total_year1",
        "current_num_employees", "total_debt_outstanding",
        "cash_on_hand", "initial_equity", "initial_assets",
      )
      if financials_json.get(k) is not None
    }
    raw = gpt_author_restructure_bounds_once(
      compact=compact,
      stated_facts=stated,
      current_structure=_intake_current_structure(ops_json, financials_json),
      failure_summary=None,
    )
    if raw.get("ok") and raw.get("bounds"):
      state["bounds"] = validate_restructure_bounds(
        bounds=raw["bounds"],
        stated_owner_annual_wage=stated_owner_annual_wage(people_json),
      )
      state.pop("bounds_error", None)
    else:
      state["bounds_error"] = str(raw.get("error") or "author_failed")[:300]
  except Exception as exc:  # noqa: BLE001
    state["bounds_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
  return state


# --------------------------------------------------------- patch handling

def apply_router_patch(
  *,
  patch: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[str]]:
  """Intercept coherence-scoped keys before the generic scoped apply.

  Handles: coherence.option (an offered option id → its stored patch
  spec), coherence.parked (the honest park), and ops.product_overrides
  (custom per-line prices, clamped into the believable range with the
  revenue anchor moved in the same write). Returns (remaining_patch,
  ops_json, financials_json, applied_notes)."""
  state = get_state(financials_json)
  rnd = state.get("round") if isinstance(state.get("round"), dict) else {}
  remaining = dict(patch or {})
  notes: List[str] = []
  next_ops = dict(ops_json or {})
  next_fin = dict(financials_json or {})

  parked = remaining.pop("coherence.parked", remaining.pop("parked", None))
  if parked is not None and str(parked).strip().lower() in ("true", "1", "yes"):
    state = dict(state)
    state["status"] = _ctl.STATUS_PARKED
    next_fin = put_state(next_fin, state)
    notes.append("parked")
    return remaining, next_ops, next_fin, notes

  option_id = remaining.pop("coherence.option", remaining.pop("option", None))
  if option_id is not None and str(option_id).strip().lower() in ("decline", "declined", "none", "keep"):
    # Declining a lever is a respected answer: mark the round walked so
    # the planner moves to the next lever instead of re-asking (the
    # canary proved a verbatim re-ask reads as a loop to everyone).
    state = dict(state)
    done = list(state.get("rounds_done") or [])
    rkey = rnd.get("key")
    if rkey and rkey not in done:
      done.append(rkey)
    state["rounds_done"] = done
    state.pop("round", None)
    next_fin = put_state(next_fin, state)
    notes.append(f"declined:{rkey}")
    option_id = None
  if option_id is not None:
    chosen = None
    for o in rnd.get("options") or []:
      if str(o.get("id")) == str(option_id).strip():
        chosen = o
        break
    if chosen:
      spec = chosen.get("patch") or {}
      if spec.get("kind") == "ops_prices":
        next_ops = _apply_price_spec(next_ops, spec.get("prices") or [])
        if spec.get("current_revenue"):
          next_fin["current_revenue"] = float(spec["current_revenue"])
        notes.append(f"option:{option_id}:prices")
      elif spec.get("kind") == "financials_fields":
        for fp in spec.get("fields") or []:
          if fp.get("group") == "financials" and fp.get("field"):
            next_fin[str(fp["field"])] = fp.get("value")
        notes.append(f"option:{option_id}:costs")

  overrides = remaining.pop("ops.product_overrides", remaining.pop("product_overrides", None))
  if isinstance(overrides, dict) and overrides:
    result = _apply_custom_prices(next_ops, next_fin, overrides, state)
    next_ops, next_fin, clamped = result
    notes.append("custom_prices" + (":clamped" if clamped else ""))

  return remaining, next_ops, next_fin, notes


def _apply_price_spec(ops_json: Dict[str, Any], prices: List[Dict[str, Any]]) -> Dict[str, Any]:
  next_ops = dict(ops_json or {})
  lobs = [dict(l) if isinstance(l, dict) else l for l in (next_ops.get("lob_models") or [])]
  by_name = {}
  for spec in prices or []:
    by_name[(str(spec.get("lob") or "").strip().lower(),
             str(spec.get("product") or "").strip().lower())] = _f(spec.get("unit_price"))
  n_products = 0
  for l in lobs:
    if not isinstance(l, dict):
      continue
    lob_name = str(l.get("lob") or l.get("name") or "").strip().lower()
    prods = [dict(p) if isinstance(p, dict) else p for p in (l.get("products") or [])]
    for p in prods:
      if not isinstance(p, dict):
        continue
      n_products += 1
      key = (lob_name, str(p.get("product") or p.get("name") or "").strip().lower())
      if key in by_name and by_name[key] > 0:
        p["unit_price"] = by_name[key]
    l["products"] = prods
  next_ops["lob_models"] = lobs
  # keep the flat convenience field in step for single-line models
  if n_products == 1 and prices:
    only = _f((prices[0] or {}).get("unit_price"))
    if only > 0 and next_ops.get("unit_price") is not None:
      next_ops["unit_price"] = only
  return next_ops


def _apply_custom_prices(
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  overrides: Dict[str, Any],
  state: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
  """Custom prices, clamped into the believable range (bounds), with
  the revenue anchor moved by the derived ratio."""
  bounds = state.get("bounds") or {}
  split = _ctl.ops_line_split(ops_json, financials_json)
  matched = _ctl.match_bounds_lines(split, bounds)
  clamped = False
  specs = []
  old_total = sum(l["q1_revenue_quarterly"] for l in split) or 1.0
  new_total = 0.0
  for line, bl in zip(split, matched):
    pmax = max(1.0, _f((bl or {}).get("price_multiplier_max"), 1.0))
    wanted = None
    for ov_name, ov_val in overrides.items():
      ov_price = ov_val.get("unit_price") if isinstance(ov_val, dict) else ov_val
      if str(ov_name).strip().lower() in (line["product"].lower(), line["lob"].lower()):
        wanted = _f(ov_price)
        break
    if wanted and wanted > 0:
      lo, hi = line["unit_price"], round(line["unit_price"] * pmax, 2)
      new_price = min(max(wanted, lo), hi)
      clamped = clamped or abs(new_price - wanted) > 0.005
      specs.append({"lob": line["lob"], "product": line["product"], "unit_price": new_price})
      new_total += line["q1_revenue_quarterly"] * (new_price / line["unit_price"])
    else:
      new_total += line["q1_revenue_quarterly"]
  next_ops = _apply_price_spec(ops_json, specs) if specs else dict(ops_json or {})
  next_fin = dict(financials_json or {})
  if specs and old_total > 0:
    ann = _f(next_fin.get("current_revenue"))
    if ann > 0:
      next_fin["current_revenue"] = round(ann * (new_total / old_total), 2)
  return next_ops, next_fin, clamped


# ------------------------------------------------------------- questions

def _round_question(rnd: Dict[str, Any], gap_display: str) -> str:
  key = rnd.get("key")
  if key == _ctl.ROUND_PRICING:
    lines = []
    for fact in (rnd.get("facts") or {}).get("lines") or []:
      lines.append(
        f"{fact['product']} is at ${fact['current_price']:,.2f} and the believable "
        f"range for your market runs up to ${fact['believable_max']:,.2f}"
      )
    opts = []
    for i, o in enumerate(rnd.get("options") or [], start=1):
      price_bits = ", ".join(
        f"{p['product']} at ${p['to']:,.2f}" for p in (o.get("prices") or [])
      )
      rec = " - this is the one I'd suggest" if o.get("recommended") else ""
      opts.append(f"{i}) {o['label'].capitalize()}: {price_bits}, which closes about "
                  f"{o['closes_display']} of the gap{rec}")
    return (
      "The biggest lever is pricing. " + "; ".join(lines) + ". "
      + " ".join(opts) + ". "
      "You can also give me exact prices and I'll keep them inside the believable range. "
      "Which fits your business? Whatever you pick, I'll recompute on the spot - "
      f"we're closing a {gap_display} a quarter gap so this plan can work on paper."
    )
  if key == _ctl.ROUND_COSTS:
    opts = []
    for i, o in enumerate(rnd.get("options") or [], start=1):
      move_bits = ", ".join(
        f"{name} from {m.get('from_display')} to {m.get('to_display')}"
        for name, m in (o.get("moves") or {}).items()
      )
      rec = " - this is the one I'd suggest" if o.get("recommended") else ""
      opts.append(f"{i}) {o['label'].capitalize()}: {move_bits}, closing about "
                  f"{o['closes_display']}{rec}")
    return (
      "Next lever: the cost structure is carrying more than a mature quarter needs, "
      "and every floor here was judged against what it really takes to run your business. "
      + " ".join(opts) + ". "
      "Which works for you? I'll recompute right away - "
      f"{gap_display} a quarter is what's left to make this work on paper."
    )
  if key == _ctl.ROUND_NEW_LINES:
    offers = []
    for o in (rnd.get("options") or [])[:2]:
      offers.append(
        f"{o.get('product')} (worth up to {_fmt(_f(o.get('q11_quarterly_revenue_max')))} a quarter at "
        f"{round(_f(o.get('gross_margin_pct'), 0.5) * 100)}% margin)"
      )
    return (
      "There are also revenue lines your operation could carry, judged against your real "
      "capacity: " + " and ".join(offers) + ". Adding one means we revisit your operating "
      "setup together - tell me if you want to, or we can keep working with what's here. "
      f"Either way, {gap_display} a quarter is what's left to make this work on paper."
    )
  return f"Let's keep going - {gap_display} a quarter left to make this work on paper."


def _opening(eval_result: Dict[str, Any], band_low: float) -> str:
  q11 = eval_result.get("q11") or {}
  return (
    "Before we wrap up, I put your numbers together the way a lender will read them - "
    "your business once it's up and running, at a typical mature quarter. Right now it "
    f"doesn't quite hold: about {_fmt(_f(q11.get('revenue')))} comes in and the quarter keeps "
    f"{_fmt(_f(q11.get('ebitda')))}, where a business like yours needs to keep at least "
    f"{_fmt(_f(q11.get('band_low_floor_dollars')))} ({_pct(band_low)} of revenue). "
    f"That's a gap of about {_fmt(_f(eval_result.get('gap_quarterly')))} a quarter. "
    "Here's the good news: we already checked the most favorable believable version of "
    "your business, and a version that works exists - nothing here has happened yet, "
    "it's all still on paper, which is exactly where we fix it. One thing at a time, "
    "biggest first."
  )


def _roadmap_message(payload: Dict[str, Any]) -> str:
  miles = "; ".join(
    f"{m['title']} ({m['detail']})" for m in payload.get("milestones") or []
  )
  return (
    "I have to be straight with you, because this plan will face a lender: we checked "
    "every believable version of the numbers you've described - prices at the top of "
    "the market range, every cost at its floor, every opportunity added - and even that "
    f"best case comes up short (about {payload.get('corner_gap_display')} a quarter at "
    "the ceiling). That's not a judgment of you; it's arithmetic about this shape of "
    "the business, and writing a plan that pretends otherwise would not survive the "
    "first hard question. So instead of a plan that says you fail, let's build the "
    "roadmap to the business that can have a plan. What would have to become true: "
    + miles + ". Your numbers stay right here - when one of those changes, come back "
    "and we rerun the same arithmetic. Nothing ships saying the business doesn't work "
    "on paper, and nothing gets faked to say it does."
  )


def _converged_suffix(eval_result: Dict[str, Any], thresholds_info: Dict[str, Any]) -> str:
  q11 = eval_result.get("q11") or {}
  margin = _f(q11.get("ebitda_margin"))
  band_low = _f(thresholds_info.get("band_low"))
  band_high = thresholds_info.get("band_high")
  if band_high is not None and margin > _f(band_high):
    # Above the believable ceiling: honest phrasing — the engine will
    # temper the full plan into the band; never claim "inside".
    band_txt = (
      f"comfortably above the {_pct(band_low)} floor judged for your kind of business "
      f"(the full plan will keep it within the believable {_pct(_f(band_high))} ceiling)"
    )
  elif band_high is not None:
    band_txt = (
      f"inside the {_pct(band_low)}-{_pct(_f(band_high))} range judged believable "
      "for your kind of business"
    )
  else:
    band_txt = "above the floor judged believable for your kind of business"
  # THE PROMISE NAMES ITS TIER — permanently, not as interim copy. This
  # verdict is the structural checks coherence can run in the room; the
  # cash pass, the engine's own path-shaping, and landing noise always
  # sit outside it. "Your plan works" is never honest at this tier.
  return (
    " One more thing worth knowing: your numbers clear every structural test we can "
    f"run right now - a typical mature quarter keeps about {_fmt(_f(q11.get('ebitda')))} "
    f"({_pct(margin)} of revenue), {band_txt}. The full build will shape the "
    "quarter-by-quarter path and run its own final checks - and every number you just "
    "set is yours."
  )


# ------------------------------------------------------------------ gate

def gate_and_turn(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  market_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  naturalize: Optional[Callable[[str], str]] = None,
  user_text: str = "",
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], str]:
  """The completion gate. Returns (turn, financials_json, suffix):

    turn is None            → completion may proceed; append `suffix`
                              (the converged readback) to the message.
    turn is a dict          → completion is blocked; persist
                              financials_json (carries the state) and
                              send turn["assistant_message"].
  """
  state = get_state(financials_json)

  if state.get("status") == _ctl.STATUS_CONVERGED:
    return None, financials_json, str(state.get("converged_suffix") or "")

  if state.get("status") == _ctl.STATUS_ROADMAP:
    # Roadmap already delivered — keep the door open without repeating
    # the whole speech, never complete, and actually ENGAGE with what
    # the client just said (a canned line every turn reads as a loop —
    # the walk E2E's runner literally flagged it as one).
    fallback = (
      "We're in roadmap territory - the full picture is a few messages up. "
      "Ask me anything about those numbers or milestones, and when one of them "
      "changes in the real world, tell me and we'll rerun the same arithmetic. "
      "Nothing ships until the plan can work on paper."
    )
    message = fallback
    if naturalize is not None and str(user_text or "").strip():
      payload = state.get("roadmap") or {}
      context = (
        "You are the intake consultant. The client's business plan cannot work yet: even "
        "the most favorable believable configuration falls short by about "
        f"{payload.get('corner_gap_display') or 'a meaningful amount'} per mature quarter. "
        "You have already delivered the full roadmap: "
        + "; ".join(f"{m.get('title')} ({m.get('detail')})" for m in payload.get("milestones") or [])
        + ". The client just said: \"" + str(user_text).strip()[:600] + "\". "
        "Reply in 2-4 warm, plain sentences: respond to what they actually said, connect it "
        "to the roadmap milestones where it fits, and close by reminding them their numbers "
        "stay saved and nothing ships until the plan can work on paper. Do not invent any "
        "new figure. Keep the phrase 'work on paper'."
      )
      message = _safe_naturalize(fallback, lambda _t: naturalize(context))
    return {"assistant_message": message}, financials_json, ""

  state = _ensure_margin_band(
    state,
    ops_json=ops_json, people_json=people_json, market_json=market_json,
    marketing_model_json=marketing_model_json,
    financials_json=financials_json, financials_year1_json=financials_year1_json,
  )
  state = _ensure_growth_judgment(
    state,
    ops_json=ops_json, people_json=people_json, market_json=market_json,
    marketing_model_json=marketing_model_json, financials_json=financials_json,
  )
  band = state.get("margin_band_judgment")
  from client_intake_and_finmo.intake_coherence.evaluator import (
    growth_multiple_from_judged,
  )
  growth_mult = growth_multiple_from_judged(
    state.get("judged_growth"), ops_json=ops_json,
  )
  # TWO-TIER EVALUATION. The fence answers the gate-entry question —
  # "can the engine author a pass from this structure" — which includes
  # cost-restatement freedom the closed form cannot see (empirically
  # 7/7 against the fleet; judged-basis entry flips Meridian, whose
  # engine pass came from fitted costs, not growth). The judged
  # multiple answers "will THIS configuration hold at the ramp the
  # engine will actually author" — the standard a WALK-built
  # configuration must meet before we promise on it (Redux: fence
  # said converged, the judged point said keep walking — the false
  # convergence). Judged-pass implies fence-pass (lower revenue, same
  # costs), so convergence stays monotone.
  eval_fence = _ctl.evaluate_current(
    financials_json=financials_json,
    ops_json=ops_json,
    financials_year1_json=financials_year1_json,
    margin_band=band,
    growth_to_q11=None,
  )
  eval_judged = None
  if growth_mult and eval_fence is not None:
    eval_judged = _ctl.evaluate_current(
      financials_json=financials_json,
      ops_json=ops_json,
      financials_year1_json=financials_year1_json,
      margin_band=band,
      growth_to_q11=growth_mult,
    )
  use_judged = eval_judged is not None and (
    state.get("status") == _ctl.STATUS_WALKING
    or (eval_fence is not None and not eval_fence.get("passed"))
  )
  eval_result = eval_judged if use_judged else eval_fence
  if eval_result is not None:
    eval_result["basis_growth"] = {
      "used": "judged" if use_judged else "fence",
      "judged_multiple": round(growth_mult, 4) if growth_mult else None,
    }
  if eval_result is None:
    # No revenue basis at all — nothing structural to say; let the
    # existing flow complete (the engine's own thin-input ladders own
    # this case).
    financials_json = put_state(financials_json, state)
    return None, financials_json, ""

  prev_gap = state.get("gap_open")
  gap = _f(eval_result.get("gap_quarterly"))
  state["eval"] = {
    "passed": bool(eval_result.get("passed")),
    "failed": eval_result.get("failed"),
    "gap_quarterly": gap,
    "q11": eval_result.get("q11"),
    "thresholds": eval_result.get("thresholds"),
  }
  state["gap_open"] = gap
  if state.get("gap_initial") is None and gap > 0:
    state["gap_initial"] = gap

  # ---------- PASS: converge, complete with the readback ----------
  if eval_result.get("passed"):
    state["status"] = _ctl.STATUS_CONVERGED
    state.pop("round", None)
    suffix = _converged_suffix(eval_result, eval_result.get("thresholds") or {})
    state["converged_suffix"] = suffix
    financials_json = put_state(financials_json, state)
    return None, financials_json, suffix

  # ---------- FAIL: bounds once, corner-first ----------
  state = _ensure_bounds(
    state,
    ops_json=ops_json, people_json=people_json, market_json=market_json,
    marketing_model_json=marketing_model_json, financials_json=financials_json,
  )
  bounds = state.get("bounds")
  from client_intake_and_finmo.intake_coherence.evaluator import GROWTH_FENCE_Q11
  # Corner = exists-authorable at the FENCE (matches the restructure
  # solver's own outcome semantics — 2/2 on the fleet). The walk's
  # rounds/gap = the judged basis, so lever math and the gap the
  # client watches are the same arithmetic that decides convergence.
  corner_basis = basis_from_intake(
    financials_json=financials_json,
    ops_json=ops_json,
    financials_year1_json=financials_year1_json,
    growth_to_q11=GROWTH_FENCE_Q11,
  )
  basis = basis_from_intake(
    financials_json=financials_json,
    ops_json=ops_json,
    financials_year1_json=financials_year1_json,
    growth_to_q11=growth_mult if (growth_mult and use_judged) else GROWTH_FENCE_Q11,
  )
  thresholds = thresholds_from_margin_band(band)

  if not bounds or not bounds.get("feasible_region_exists", True):
    # The executive's honest "no believable region" answer, or the
    # author failed — either way we cannot walk levers we don't have.
    corner = {"passed": False, "q11": {}, "gap_quarterly": gap}
    state["corner"] = corner
    state["status"] = _ctl.STATUS_ROADMAP
    payload = _ctl.roadmap_payload(corner=corner, eval_result=eval_result, bounds=bounds or {})
    state["roadmap"] = payload
    financials_json = put_state(financials_json, state)
    return {"assistant_message": _roadmap_message(payload)}, financials_json, ""

  if state.get("corner") is None:
    state["corner"] = _ctl.corner_check(
      basis=corner_basis, thresholds=thresholds, bounds=bounds,
      ops_json=ops_json, financials_json=financials_json,
    )
  corner = state["corner"]

  if not corner.get("passed"):
    state["status"] = _ctl.STATUS_ROADMAP
    payload = _ctl.roadmap_payload(corner=corner, eval_result=eval_result, bounds=bounds)
    state["roadmap"] = payload
    financials_json = put_state(financials_json, state)
    return {"assistant_message": _roadmap_message(payload)}, financials_json, ""

  # ---------- WALKING ----------
  first_walk = state.get("status") != _ctl.STATUS_WALKING
  state["status"] = _ctl.STATUS_WALKING

  ack = ""
  if prev_gap is not None and gap < _f(prev_gap) - 0.5:
    closed = _f(prev_gap) - gap
    initial = _f(state.get("gap_initial")) or closed
    pct_total = min(100, round((1 - gap / initial) * 100)) if initial > 0 else 0
    ack = (
      f"That moved the plan - the gap just closed by {_fmt(closed)} a quarter. "
      f"You're {pct_total}% of the way there, {_fmt(gap)} to go. "
    )
    done = list(state.get("rounds_done") or [])
    active = (state.get("round") or {}).get("key")
    if active and active not in done:
      done.append(active)
      state["rounds_done"] = done

  rnd = _ctl.plan_rounds(
    basis=basis, thresholds=thresholds, bounds=bounds,
    ops_json=ops_json, financials_json=financials_json,
    rounds_done=state.get("rounds_done"),
  )
  if rnd is None:
    # replan allowing revisits before giving up
    rnd = _ctl.plan_rounds(
      basis=basis, thresholds=thresholds, bounds=bounds,
      ops_json=ops_json, financials_json=financials_json,
      rounds_done=None,
    )
    state["rounds_done"] = []
  if rnd is None:
    state.pop("round", None)
    financials_json = put_state(financials_json, state)
    msg = (
      f"We're close but not quite there - {_fmt(gap)} a quarter still open, and the "
      "levers inside the believable ranges are used up. We can revisit any number "
      "you'd like to change, or leave everything saved right here and pick it up "
      "when you're ready - nothing goes out until it can work on paper."
    )
    return {"assistant_message": msg}, financials_json, ""

  state["round"] = rnd
  question = _round_question(rnd, _fmt(gap))
  message = (ack + question) if not first_walk else (_opening(eval_result, thresholds.band_low) + "\n\n" + question)
  if naturalize is not None:
    message = _safe_naturalize(message, naturalize)
  financials_json = put_state(financials_json, state)
  return {"assistant_message": message}, financials_json, ""


def park_message() -> str:
  return (
    "Understood - we'll leave it right here. Everything you've told me is saved, and "
    "nothing goes out saying the business doesn't work. Whenever you're ready to pick "
    "it back up, we'll continue exactly where we left off and make it work on paper."
  )


def reask_message(financials_json: Dict[str, Any]) -> Optional[str]:
  """Deterministic natural re-ask backstop (marker included) when the
  router falls through while a round question is live."""
  state = get_state(financials_json)
  rnd = state.get("round")
  if not isinstance(rnd, dict):
    return None
  gap = _fmt(_f(state.get("gap_open")))
  return (
    "No rush - to keep us moving: " + _round_question(rnd, gap)
  )


def _safe_naturalize(text: str, naturalize: Callable[[str], str]) -> str:
  """GPT phrasing with a hard guarantee: every dollar figure and the
  marker must survive verbatim, else the deterministic text stands."""
  try:
    candidate = str(naturalize(text) or "").strip()
  except Exception:  # noqa: BLE001
    return text
  if not candidate or COHERENCE_MARKER not in candidate:
    return text
  for token in _MONEY_RE.findall(text):
    if token not in candidate:
      return text
  return candidate


__all__ = [
  "COHERENCE_MARKER",
  "get_state", "put_state", "walking_round_live", "router_frame",
  "apply_router_patch", "gate_and_turn", "park_message", "reask_message",
]
