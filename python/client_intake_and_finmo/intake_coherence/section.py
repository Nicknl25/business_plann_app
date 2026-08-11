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

import copy
import logging
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

# Fields a client may correct DURING a lever turn by disputing a panel
# number ("that payroll figure is wrong - we actually pay X"). The router
# patches the underlying field (basis-normalized via field_bases) and the
# panel recomputes from it next turn. Everything outside this set plus
# the active round's declared targets is DROPPED by the lever whitelist:
# Harborline CW-001 showed the router can hallucinate a full state dump
# as a "patch" (25 fields, duplicated with conflicting bases) — applied
# wholesale it vandalized four correct captures.
DISPUTABLE_FIELDS = (
  # CW-022 #8: owner pay disputes travel as people.owner_pay_monthly and
  # land on the OWNER ROLE (financials.owner_compensation is a derived
  # mirror nothing writes).
  "people.owner_pay_monthly",
  # CW-024 #109 (prevention shape): DOOR COMPLETENESS - the stated team
  # total and roster edits land mid-round like any stated fact. The
  # Cedar Ridge client corrected payroll seven times with no door.
  "people.total_team_payroll",
  "people.remove_role",
  "financials.other_operating_expense",
  "financials.monthly_rent_expense",
  "financials.marketing_total_year1",
  "financials.current_revenue",
  "financials.payroll_adjustment",
)

_MONEY_RE = re.compile(r"\$[\d,]+")


class CoherenceJudgmentUnavailable(RuntimeError):
  """The gate could not author an executive judgment (transient GPT
  failure). Intake-time contract: the turn HOLDS — an honest "give me a
  moment", never a verdict and never a silent constant (doctrine: no
  plan ships on substituted judgment). The draft persists; the next
  turn re-enters the gate and re-authors."""

  def __init__(self, judgment: str, detail: str = "") -> None:
    self.judgment = judgment
    self.detail = detail
    super().__init__(f"coherence_judgment_unavailable: {judgment}: {detail}")


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
    if o.get("volumes"):
      entry["volumes"] = o["volumes"]
    if o.get("moves"):
      entry["moves"] = {k: v.get("to_display") for k, v in (o.get("moves") or {}).items()}
    options.append(entry)
  patch_targets = ["coherence.option", "coherence.assert_floor"]
  if isinstance(state.get("retention_pending"), dict):
    patch_targets.append("coherence.retention_answer")
  if rnd.get("key") == _ctl.ROUND_PRICING:
    patch_targets.append("ops.product_overrides")
  else:
    for o in rnd.get("options") or []:
      for fp in ((o.get("patch") or {}).get("fields") or []):
        patch_targets.append(f"{fp.get('group')}.{fp.get('field')}")
  from client_intake_and_finmo.field_basis import basis_of
  disputable = list(DISPUTABLE_FIELDS)
  return {
    "current_question": f"coherence_{rnd.get('key')}",
    "round_key": rnd.get("key"),
    "options": options,
    "patch_targets": sorted(set(patch_targets)),
    "disputable_fields": disputable,
    "field_bases": {
      f: basis_of(f) for f in sorted(set(patch_targets + disputable))
      if not f.startswith("coherence.") and not f.endswith("product_overrides")
    },
    "gap_open_display": _fmt(_f(state.get("gap_open"))),
  }


# ------------------------------------------------- F-core artifact stamps

def _financials_identity_basis(
  state: Dict[str, Any], financials_json: Dict[str, Any]
) -> Dict[str, Any]:
  """PHASE 2 (Nick-ruled invalidation honesty): the judged artifacts
  were authored FROM financials facts, so the identity includes the
  CLIENT-STATED financials basis - a stated-fact CORRECTION re-judges.
  The walk's OWN lever writes are excluded (CW-020: lever moves
  re-evaluate, never re-judge): each _lever_writes entry records
  {"from": pre-lever value, "to": written value}; while the current
  value is still the lever's "to", the basis substitutes "from" - so
  the digest stays byte-identical to the one the band was authored
  under (excluding-by-drop would itself re-key on lever accept). A
  later client correction to a DIFFERENT value re-enters the digest."""
  fin = financials_json if isinstance(financials_json, dict) else {}
  lever_writes = state.get("_lever_writes") if isinstance(state.get("_lever_writes"), dict) else {}

  def _incl(field: str, value: Optional[float], places: int = 2) -> Optional[float]:
    if value is None:
      return None
    entry = lever_writes.get(field)
    tol = max(10.0 ** -places, 1e-6 * abs(value))
    if isinstance(entry, dict):
      to_v = _f(entry.get("to")) if entry.get("to") is not None else None
      if to_v is not None and abs(to_v - value) <= tol:
        fr_v = _f(entry.get("from")) if entry.get("from") is not None else None
        # substitute the pre-lever value: identity as authored
        return round(float(fr_v), places) if fr_v is not None else None
    elif entry is not None:
      lw = _f(entry)
      if lw is not None and abs(lw - value) <= tol:
        return None  # legacy scalar entry: exclude
    return round(float(value), places)

  basis: Dict[str, Any] = {}
  for field in (
    "current_revenue", "baseline_payroll_year1", "other_opex_absolute",
    "marketing_total_year1", "monthly_rent_expense",
  ):
    v = _incl(field, _f(fin.get(field)) if fin.get(field) is not None else None)
    if v is not None:
      basis[field] = v
  if str(fin.get("cogs_basis") or "").strip().lower() == "dollars":
    v = _incl("current_cogs", _f(fin.get("current_cogs")) if fin.get("current_cogs") is not None else None)
    if v is not None:
      basis["cogs_dollars"] = v
  else:
    v = fin.get("cogs_percent_of_revenue")
    if v is not None:
      vv = _incl("cogs_percent_of_revenue", _f(v), places=6)
      if vv is not None:
        basis["cogs_ratio"] = vv
  return basis


def _record_lever_write(
  lever_writes: Dict[str, Any], field: str,
  from_value: Optional[float], to_value: Optional[float],
) -> None:
  """Record a walk lever's write as {"from", "to"}. When levers chain
  (a second accept moves the same field again), the epoch ORIGIN is
  preserved: if the pre-write value is the previous entry's "to", keep
  the previous "from" - the identity substitutes the value the band
  was authored under, however many levers later. A client correction
  re-keys the digest, which resets the epoch (_lever_writes cleared)."""
  if to_value is None:
    return
  prev = lever_writes.get(field)
  if isinstance(prev, dict) and prev.get("to") is not None and from_value is not None:
    prev_to = _f(prev.get("to"))
    if prev_to is not None and abs(prev_to - from_value) <= max(0.01, 1e-6 * abs(from_value)):
      from_value = _f(prev.get("from")) if prev.get("from") is not None else None
  lever_writes[field] = {"from": from_value, "to": float(to_value)}


def _compute_band_identity_digest(
  state: Dict[str, Any],
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  market_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
  """The band-identity digest (CW-017 #5 + CW-020 strips + the phase-2
  financials basis), factored so BOTH _ensure_margin_band and the
  roadmap re-evaluation check compute the same identity. Returns
  (digest_hash, compact)."""
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (
    build_operating_model_digest,
  )
  compact = build_operating_model_digest(
    ops_json, people_json, market_json, marketing_model_json,
  )
  # CW-017 #5 (approved 2026-08-07): the BAND-IDENTITY hash excludes
  # lever VALUES - knob edits (price/capacity/utilization) re-EVALUATE,
  # they never re-JUDGE; only identity-level changes (what it sells,
  # structure, cadence, market, team) re-author the band. Revenue
  # authoring keeps the FULL digest (levers must be in view there).
  # Vanguard: a $4,000->$4,300 price repair re-keyed the digest and
  # re-rolled the judged band 6-11%% -> 4-8%% in 86 seconds, so the
  # same figure was promised against two different bands in one
  # session.
  identity = copy.deepcopy(compact) if isinstance(compact, dict) else {}
  for _lever_key in (
    "unit_price", "units_per_week_capacity",
    "units_per_period_capacity", "utilization_rate",
  ):
    identity.pop(_lever_key, None)
  for _line in identity.get("lines_of_business") or []:
    if isinstance(_line, dict):
      for _lever_key in ("unit_price", "capacity_units_per_period", "utilization_rate"):
        _line.pop(_lever_key, None)
  # CW-020 (Oak City): KNOB-DERIVED values are knob values. The
  # market_demand slice carries numbers RECOMPUTED from prices/revenue
  # every turn (required_units = revenue/price etc.) - a $1,300->$1,450
  # price repair re-keyed the identity through them and re-rolled the
  # band {7,14}->{8,16}. The market's IDENTITY is who/where it is
  # (basis summary, geography) - the derived sizing numerics are
  # revenue-authoring context and are stripped from the band identity.
  _md = identity.get("market_demand")
  if isinstance(_md, dict):
    for _derived_key in (
      "reachable_market", "reachable_market_b2c", "reachable_market_b2b",
      "expected_units_year1", "required_units_year1",
      "expected_customers_or_clients_year1", "capture_rate_year1",
      "marketing_intensity", "demand_supports_required_units",
      "required_revenue_year1",
    ):
      _md.pop(_derived_key, None)
  # PHASE 2: the client-stated financials basis joins the identity -
  # corrections re-judge; the walk's own lever writes are excluded.
  identity["_financials_basis"] = _financials_identity_basis(state, financials_json)
  return _ctl.stable_digest_hash(identity), compact


def _payroll_share_wall_result(
  state: Dict[str, Any],
  *,
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  """WALLS TABLE v1 (phase 3): the payroll-share tier wall, evaluated
  on the engine's own judged basis (stated annual payroll / annual
  revenue anchor - the exact ratio the engine's payload validator
  enforces raw). The labor-intensity class comes from the margin-band
  judgment (the executive judges the TYPE's staffing character at
  F-core, same fence). No judged class, or no stated payroll/revenue
  -> None: absence of judgment is never a verdict."""
  band = state.get("margin_band_judgment")
  cls = (band or {}).get("labor_intensity_class") if isinstance(band, dict) else None
  if not cls:
    return None
  from client_intake_and_finmo.intake_coherence.walls import payroll_share_wall
  # THE ENGINE'S OWN RATIO, verbatim (keystone lesson: the first cut
  # used the gate's eval basis - year1-prorated payroll - and read the
  # REAL Sparrow draft at 0.53 while the engine killed it at 0.72. The
  # wall must judge the exact arithmetic the engine judges:
  # payroll_total_year1 over the year1 revenue anchor).
  from client_intake_and_finmo.post_intake_headcount.schedule import (
    _intake_implied_operating_intensity,
  )
  _intensity = _intake_implied_operating_intensity(
    financials=financials_json if isinstance(financials_json, dict) else {},
    year1=financials_year1_json if isinstance(financials_year1_json, dict) else {},
  )
  _implied = _intensity.get("implied_payroll_percent_of_revenue")
  if _implied is None:
    return None
  # payroll_share_wall wants the dollar pair for the priced exits; feed
  # it the same numbers the ratio came from.
  _pay = _f(financials_json.get("payroll_total_year1"))
  _rev = (_pay / float(_implied)) if _pay > 0 and float(_implied) > 0 else 0.0
  return payroll_share_wall(
    labor_intensity_class=cls,
    payroll_annual=_pay,
    revenue_annual=_rev,
  )


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
  digest_hash, compact = _compute_band_identity_digest(
    state,
    ops_json=ops_json, people_json=people_json, market_json=market_json,
    marketing_model_json=marketing_model_json, financials_json=financials_json,
  )
  if state.get("margin_band_judgment") and state.get("digest_hash") == digest_hash:
    # PHASE 3 MIGRATION BACKFILL (found by the keystone rerun): stamps
    # authored before the walls table carry no labor_intensity_class,
    # and with the identity unchanged they never re-author - so the
    # payroll wall was silently DEAD on every legacy draft (Sparrow's
    # 17:23 rerun stamp replayed "clears every structural test" at a
    # 72% share). The band must NOT re-roll on an unchanged identity
    # (CW-017), so the missing judgment is authored ALONE - same judge,
    # same fence, band numbers untouched. Transient failure leaves it
    # absent (no wall this turn, retried next turn) and logs loudly.
    _mbj = state.get("margin_band_judgment")
    if isinstance(_mbj, dict) and not _mbj.get("labor_intensity_class"):
      try:
        from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (
          gpt_author_labor_intensity_class_once,
        )
        _res = gpt_author_labor_intensity_class_once(compact=compact)
        if _res.get("ok"):
          state = dict(state)
          _mbj = dict(_mbj)
          _mbj["labor_intensity_class"] = _res["labor_intensity_class"]
          _mbj["notes"] = list(_mbj.get("notes") or []) + [
            "labor_intensity_class_backfilled"
          ]
          state["margin_band_judgment"] = _mbj
        else:
          logging.getLogger("intake_coherence.section").error(
            "labor_intensity_class backfill failed (%s) - the payroll "
            "wall stays absent for this draft until a later turn "
            "succeeds", _res.get("error"),
          )
      except Exception:
        logging.getLogger("intake_coherence.section").exception(
          "labor_intensity_class backfill crashed - wall absent this turn",
        )
    # DEMAND JUDGE BACKFILL (same pattern): stamps authored before the
    # judge shipped carry no demand_response - author it alone, band
    # numbers untouched.
    state = _ensure_demand_response(
      state, compact=compact, marketing_model_json=marketing_model_json,
      market_json=market_json, ops_json=ops_json,
      financials_json=financials_json,
    )
    state = _ensure_essentials_response(
      state, compact=compact, ops_json=ops_json,
      financials_json=financials_json,
    )
    return state
  state = dict(state)
  # Identity-level change: EVERY judged artifact keyed to the old
  # identity is stale — the band re-authors below; growth, bounds,
  # corner, and the live round must re-derive on the new identity.
  # EXCEPT judged growth while a round is LIVE: the goalposts must not
  # move mid-negotiation (CW-002: a mid-walk re-derivation shifted q11
  # revenue 187.6k -> 175.1k, so the client's accepted rent cut closed
  # $75 of a $2,700 move). Growth re-derives when the walk is over.
  if state.get("digest_hash") and state.get("digest_hash") != digest_hash:
    stale_keys = ["growth_error", "bounds", "bounds_error", "corner", "round",
                  "demand_response", "essentials_response",
                  "corner_collapse_hold"]
    round_live = state.get("status") == _ctl.STATUS_WALKING and state.get("round")
    if round_live:
      state["growth_frozen_during_round"] = True
    else:
      stale_keys.append("judged_growth")
    # PHASE 2: a roadmap is a verdict about the OLD identity - an
    # identity change (including a corrected stated fact) clears it so
    # the gate re-evaluates, exactly as the roadmap's own wording
    # promises ("tell me and we'll rerun the same arithmetic").
    if state.get("status") == _ctl.STATUS_ROADMAP:
      stale_keys.append("roadmap")
      state.pop("status", None)
    for stale_key in stale_keys:
      state.pop(stale_key, None)
    # PHASE 2: a genuine identity change (digest moved even WITH the
    # lever substitutions active) resets the lever epoch - the band
    # re-authors at the current values, so future digests compare
    # against them raw. Restamp with the epoch cleared.
    if state.get("_lever_writes"):
      state.pop("_lever_writes", None)
      digest_hash, compact = _compute_band_identity_digest(
        state,
        ops_json=ops_json, people_json=people_json, market_json=market_json,
        marketing_model_json=marketing_model_json, financials_json=financials_json,
      )
  state["digest_hash"] = digest_hash
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
  # MEASURED BASIS — from the evaluator itself, so the judge is told the
  # exact quantities its thresholds will be tested against (one source
  # of truth; the old inline computation double-counted owner comp).
  ann = _f(annual_revenue)
  measured_basis: Dict[str, Any] = {}
  eval_basis = basis_from_intake(financials_json=financials_json,
                                 financials_year1_json=financials_year1_json,
                                 ops_json=ops_json)
  if eval_basis is not None and ann > 0:
    payroll_annual = eval_basis.payroll_quarterly * 4.0
    rent_annual = eval_basis.rent_quarterly * 4.0
    measured_basis = {
      "cogs_pct": round(eval_basis.cogs_pct, 6),
      "marketing_pct": round(eval_basis.marketing_pct, 6),
      "payroll_share": round(payroll_annual / ann, 6),
      "rent_share": round(rent_annual / ann, 6),
      "gna_pct": round(eval_basis.gna_pct, 6),
    }
    facts["payroll_percent_of_revenue"] = measured_basis["payroll_share"]
    facts["rent_percent_of_revenue"] = measured_basis["rent_share"]
    facts["measured_basis_note"] = (
      "ALL labor sits in the payroll line (payroll share "
      f"{measured_basis['payroll_share']:.0%} of stated revenue); COGS is "
      f"materials/non-labor only ({measured_basis['cogs_pct']:.0%}). Your "
      "burden ceiling is tested against payroll+rent+G&A in exactly this "
      "basis."
    )

  def _author(note: str = "", retry_nonce: int = 0) -> Dict[str, Any]:
    result = gpt_author_margin_band_once(
      compact=compact, stated_cost_facts=facts or None, arbitration_note=note,
      retry_nonce=retry_nonce,
    )
    if not (result.get("ok") and result.get("judgment")):
      # Failure is never a verdict and never doctrine constants: hold the
      # turn and re-author next turn. (Absence ≠ failure — a stamp that
      # already exists was returned above.)
      raise CoherenceJudgmentUnavailable(
        "margin_band", str(result.get("error") or "author_failed")[:300]
      )
    return validate_margin_band_judgment(
      judgment=result["judgment"], measured_basis=measured_basis or None,
    )

  validated = _author()
  if validated.get("basis_contradiction"):
    # Locked-GPT arbitration (the fitted-band anchor pattern): ONE
    # re-authoring with the contradiction spelled out. Judgment stays
    # the owner — nothing is clamped. Still contradictory -> hold.
    #
    # CW-010 eternal-hold guard: under the GPT response lock an unchanged
    # arbitration payload replays the same locked contradiction forever —
    # fail-loud became fail-forever. A HELD turn's re-author carries the
    # consecutive-hold count (stamped by the handler's hold branch) as a
    # fresh-roll nonce: first-call and first-arbitration determinism are
    # untouched, and successful runs never see a nonce. The tripwire is
    # deterministic arithmetic on the judgment's own numbers, so a
    # passing re-attempt IS basis-consistent — there is no slipping past
    # the guard by luck. After 3 fresh re-attempts the hold escalates
    # with a distinct exhausted signature (ERROR log -> issue filing ->
    # human review), never a verdict and never an infinite silent spin.
    hold_retries = 0
    try:
      hold_retries = int(financials_json.get("_judgment_hold_retries") or 0)
    except Exception:
      hold_retries = 0
    validated = _author(
      "Your burden ceiling of "
      f"{(validated.get('fixed_cost_burden_max_q11') or 0):.0%} combined with this "
      f"file's measured materials-only COGS ({measured_basis.get('cogs_pct', 0):.0%}) "
      "implies a business obeying your ceiling would earn far above your "
      "own judged healthy band — meaning the ceiling was authored as if "
      "labor lived in COGS. In THIS file all labor "
      f"({measured_basis.get('payroll_share', 0):.0%} of revenue) is in the "
      "payroll line. Re-author the ceiling and floors in that basis.",
      retry_nonce=hold_retries,
    )
    if validated.get("basis_contradiction"):
      if hold_retries >= 3:
        try:
          logging.getLogger("api").error(
            "MARGIN_BAND_HOLD_EXHAUSTED: %d fresh arbitration re-attempts "
            "all basis-contradictory; human review required",
            hold_retries,
          )
        except Exception:
          pass
        raise CoherenceJudgmentUnavailable(
          "margin_band_basis_exhausted",
          f"burden ceiling basis-contradictory after {hold_retries} fresh "
          "re-attempts; escalated for human review",
        )
      raise CoherenceJudgmentUnavailable(
        "margin_band_basis",
        "burden ceiling basis-contradictory with measured cost placement after arbitration",
      )
  financials_json.pop("_judgment_hold_retries", None)
  state["margin_band_judgment"] = validated
  state.pop("margin_band_error", None)
  # THE DEMAND JUDGE rides the same F-core seam (Nick-ruled #5):
  # authored with the band, invalidated with the band. THE ESSENTIALS
  # JUDGE rides it too (CW-024).
  state = _ensure_demand_response(
    state, compact=compact, marketing_model_json=marketing_model_json,
    market_json=market_json, ops_json=ops_json,
    financials_json=financials_json,
  )
  state = _ensure_essentials_response(
    state, compact=compact, ops_json=ops_json,
    financials_json=financials_json,
  )
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
  raises CoherenceJudgmentUnavailable — the turn holds and re-authors
  next turn (failure is never the fence; the fence remains the
  gate-entry TIER, not a failure fallback)."""
  if state.get("judged_growth"):
    return state
  state = dict(state)
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
  if not (result.get("ok") and result.get("judgment")):
    raise CoherenceJudgmentUnavailable(
      "judged_growth", str(result.get("error") or "author_failed")[:300]
    )
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
  return state


def _ensure_demand_response(
  state: Dict[str, Any],
  *,
  compact: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  market_json: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Dict[str, Any]:
  """THE DEMAND JUDGE stamp (Nick-ruled #5: the F-core seam). Authored
  once per identity alongside the band; identity change clears it with
  the other judged artifacts. FAIL-SOFT by design: demand ENRICHES the
  levers, it never gates - a failed authoring logs loudly and retries
  at the next gate entry, and the levers fall back to their pre-demand
  behavior (absence of judgment is never a verdict). The THIN rule is
  enforced in the validator: thin evidence -> verdicts withheld."""
  if state.get("demand_response"):
    return state
  try:
    from client_intake_and_finmo.intake_coherence.gpt_demand_judgment import (
      demand_evidence_level,
      gpt_author_demand_response_once,
      validate_demand_response,
    )
    evidence = demand_evidence_level(marketing_model_json, market_json)
    if evidence["level"] != "rich":
      # Withheld-by-evidence needs no GPT call: stamp the honest thin
      # verdict directly (visibly thin, nothing fabricated).
      state = dict(state)
      state["demand_response"] = validate_demand_response(
        judgment={}, evidence=evidence,
      )
      return state
    split = _ctl.ops_line_split(ops_json, financials_json)
    price_facts = {
      "lines": [
        {"lob": l["lob"], "product": l["product"],
         "unit_price": l["unit_price"],
         "annual_units": round(_f(l.get("annual_units")))}
        for l in split
      ],
      "stated_annual_revenue": _f(financials_json.get("current_revenue")),
    }
    result = gpt_author_demand_response_once(
      compact=compact, marketing_model=marketing_model_json or {},
      price_facts=price_facts,
    )
    if not (result.get("ok") and result.get("judgment")):
      logging.getLogger("intake_coherence.section").error(
        "DEMAND_JUDGE_AUTHOR_FAILED (%s) - levers keep pre-demand "
        "behavior until a later gate entry succeeds",
        result.get("error"),
      )
      return state
    state = dict(state)
    state["demand_response"] = validate_demand_response(
      judgment=result["judgment"], evidence=evidence,
    )
  except Exception:
    logging.getLogger("intake_coherence.section").exception(
      "DEMAND_JUDGE_AUTHOR_CRASHED - levers keep pre-demand behavior",
    )
  return state


def _ensure_essentials_response(
  state: Dict[str, Any],
  *,
  compact: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Dict[str, Any]:
  """THE ESSENTIALS JUDGE stamp (CW-024, Nick-ruled supersede of the
  CW-022 #5 ask-first): authored once per identity alongside the band
  and the demand judgment; identity change clears it with the other
  judged artifacts. FAIL-SOFT: essentials ENRICH the costs round, they
  never gate - a failed authoring logs loudly and retries at the next
  gate entry, and the round keeps the ask-first wording (absence of
  judgment is never a verdict). THIN evidence is enforced in the
  validator: withheld verdicts, ask-first preserved."""
  if state.get("essentials_response"):
    return state
  try:
    from client_intake_and_finmo.intake_coherence.gpt_essentials_judgment import (
      essentials_evidence_level,
      gpt_author_essentials_once,
      validate_essentials,
    )
    evidence = essentials_evidence_level(ops_json, financials_json)
    if evidence["level"] != "rich":
      state = dict(state)
      state["essentials_response"] = validate_essentials(
        judgment={}, evidence=evidence,
      )
      return state
    _rev = _f(financials_json.get("current_revenue"))
    _gna_ann = _f(financials_json.get("other_opex_absolute"))
    if _gna_ann <= 0:
      _gna_ann = _f(financials_json.get("other_operating_expense")) * 12.0
    _cogs_ann = _f(financials_json.get("cogs_total_year1"))
    if _cogs_ann <= 0:
      _cogs_ann = _f(financials_json.get("current_cogs"))
    if _cogs_ann <= 0 and _rev > 0:
      _cogs_ann = _f(financials_json.get("cogs_percent_of_revenue")) * _rev
    cost_lines = {
      "other_operating_costs_annual": round(_gna_ann, 2),
      "direct_costs_annual": round(_cogs_ann, 2),
      "annual_revenue_stated": round(_rev, 2),
      "for_context_not_inside_these_lines": {
        "payroll_annual": _f(financials_json.get("current_payroll")),
        "rent_monthly": _f(financials_json.get("monthly_rent_expense")),
        "marketing_annual": _f(financials_json.get("marketing_total_year1")),
      },
    }
    result = gpt_author_essentials_once(compact=compact, cost_lines=cost_lines)
    if not (result.get("ok") and result.get("judgment")):
      logging.getLogger("intake_coherence.section").error(
        "ESSENTIALS_JUDGE_AUTHOR_FAILED (%s) - costs round keeps the "
        "ask-first wording until a later gate entry succeeds",
        result.get("error"),
      )
      return state
    state = dict(state)
    state["essentials_response"] = validate_essentials(
      judgment=result["judgment"], evidence=evidence,
    )
  except Exception:
    logging.getLogger("intake_coherence.section").exception(
      "ESSENTIALS_JUDGE_AUTHOR_CRASHED - costs round keeps ask-first wording",
    )
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
  # Payroll comes from the blessed accessor - people baseline + approved
  # adjustment, with the owner-comp NON-ADDITIVE guard (evaluator.py:345).
  # The old inline sum here added owner comp x12 unconditionally onto the
  # legacy echo fields, double-counting the owner in the bounds input for
  # every owner-in-people business - the exact divergence the evaluator
  # was fixed to avoid. One computation, one owner-guard, both sites.
  basis = basis_from_intake(financials_json=financials_json, ops_json=ops_json)
  q1_payroll = (
    round(basis.payroll_quarterly, 2)
    if basis is not None and basis.payroll_quarterly > 0
    else None
  )
  return {
    "q1_revenue": round(ann_rev / 4.0, 2) if ann_rev > 0 else None,
    "q1_payroll": q1_payroll,
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
  if not (raw.get("ok") and raw.get("bounds")):
    # An author failure must never read as "no believable region": that
    # branch delivers a roadmap — a life-sized verdict on the client's
    # business — and a network error is not a verdict.
    raise CoherenceJudgmentUnavailable(
      "bounds", str(raw.get("error") or "author_failed")[:300]
    )
  state["bounds"] = validate_restructure_bounds(
    bounds=raw["bounds"],
    stated_owner_annual_wage=stated_owner_annual_wage(people_json),
  )
  # CW-022 #3 (intake-pure, author file untouched): the author judged
  # the price ceiling against the prices it was SHOWN, but stores only a
  # ratio. Stamp each line's authoring-time unit price into OUR stored
  # copy so every walk consumer can hold the ABSOLUTE dollar ceiling —
  # re-based ratios inflated a judged $108 into a $144 offer (the
  # ratchet). Storage-time stamp; nothing post-intake reads this copy.
  try:
    _split0 = _ctl.ops_line_split(ops_json, financials_json)
    _matched0 = _ctl.match_bounds_lines(_split0, state["bounds"])
    # CW-024 #113 (Nick-ruled, prevention shape): the judged price
    # ceiling is a DURABLE MARKET FACT in dollars. It survives identity
    # re-keys (the fact lives outside every stale-pop list) and can be
    # re-judged ONLY when the MARKET-side slice changes - a client
    # accepting a price is not market evidence and cannot move it. This
    # kills the cross-epoch ratchet ($650->$910->$1,183->$1,597: each
    # re-authoring judged a relative multiplier against the price it
    # was shown, which was the just-accepted one). The VALVE: a client-
    # STATED market fact changes market_json, which changes the slice
    # hash, which honestly re-opens the judgment - statements yes,
    # acceptance never.
    _market_slice_hash = _ctl.stable_digest_hash({
      "market": {k: market_json.get(k) for k in (
        "consumer_type", "selections", "gender_age_intent", "income_intent",
        "marketing_plan_summary")} if isinstance(market_json, dict) else {},
      "business_type": (ops_json or {}).get("business_type"),
      "naics": (ops_json or {}).get("business_naics_6"),
      "geography": (ops_json or {}).get("geographic_coverage"),
    })
    _facts = dict(state.get("price_market_facts") or {})
    for _ln, _bl in zip(_split0, _matched0):
      if isinstance(_bl, dict) and _bl.get("unit_price_at_authoring") is None:
        _p0 = _f(_ln.get("unit_price"))
        if _p0 > 0:
          _bl["unit_price_at_authoring"] = float(_p0)
      # PHASE 4: same ratchet fix for the volume ceiling - the judged
      # multiple holds in UNITS, stamped at authoring time.
      if isinstance(_bl, dict) and _bl.get("annual_units_at_authoring") is None:
        _u0 = _f(_ln.get("annual_units"))
        if _u0 > 0:
          _bl["annual_units_at_authoring"] = float(_u0)
      if isinstance(_bl, dict):
        _lkey = f"{_ln.get('lob')}␟{_ln.get('product')}"
        _prior_fact = _facts.get(_lkey)
        if (
          isinstance(_prior_fact, dict)
          and _prior_fact.get("market_slice_hash") == _market_slice_hash
          and _f(_prior_fact.get("ceiling_dollars")) > 0
        ):
          # Same market -> the prior judged ceiling STANDS, whatever
          # this re-authoring says.
          _bl["price_ceiling_market_fact"] = float(_prior_fact["ceiling_dollars"])
        else:
          _p_auth = _f(_bl.get("unit_price_at_authoring"))
          _pmax_rel = max(1.0, _f(_bl.get("price_multiplier_max"), 1.0))
          if _p_auth > 0:
            _facts[_lkey] = {
              "ceiling_dollars": round(_p_auth * _pmax_rel, 2),
              "market_slice_hash": _market_slice_hash,
            }
            _bl["price_ceiling_market_fact"] = _facts[_lkey]["ceiling_dollars"]
    state["price_market_facts"] = _facts
  except Exception:
    pass
  state.pop("bounds_error", None)
  return state


def _q20_hold(eval_result: Optional[Dict[str, Any]],
              band: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  """Q20 SECOND POINT (Nick-ruled, INTERNAL ONLY): consume the
  already-authored mature (Q20) band as a direction check. With
  percent costs scaling and fixed costs flat, the structure's margin
  at flat-from-Q11 revenue equals its Q11 margin - so margin_q11 >=
  q20.low answers 'can this structure HOLD maturity without relying on
  unspecified post-Q11 growth'. Stamped for state/panel/telemetry;
  never a verdict, never a client-facing question (the ruling), and
  NOT a trajectory simulator."""
  if not isinstance(eval_result, dict) or not isinstance(band, dict):
    return None
  q20 = band.get("q20") if isinstance(band.get("q20"), dict) else None
  q11 = eval_result.get("q11") if isinstance(eval_result.get("q11"), dict) else None
  if not q20 or not q11:
    return None
  rev = _f(q11.get("revenue"))
  if rev <= 0 or q20.get("low") is None:
    return None
  margin = _f(q11.get("ebitda")) / rev
  q20_low = _f(q20.get("low"))
  return {
    "passed": margin >= q20_low - 1e-9,
    "margin_q11": round(margin, 4),
    "q20_low": round(q20_low, 4),
    "direction": "holds_mature_floor" if margin >= q20_low - 1e-9
                 else "relies_on_post_q11_growth",
  }


def refresh_eval_stamps(
  financials_json: Dict[str, Any],
  *,
  ops_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  """PHASE 5 (display refresh): restamp the deterministic verdict
  arithmetic EVERY TURN once the F-core judgments exist, so the panel
  reads live numbers between gate entries instead of gate-time
  snapshots (the completion-attempt-only regime was the last surface
  violating rule 4). Judgments are NEVER authored here - a draft
  without a band stamp is left untouched - and the walk's narrative
  state (status, round, gap_initial, rounds_done) is not moved. Any
  failure leaves the stored stamps exactly as they were (display
  refresh must never break a turn)."""
  state = get_state(financials_json)
  band = state.get("margin_band_judgment")
  if not band:
    return financials_json
  try:
    from client_intake_and_finmo.intake_coherence.evaluator import (
      growth_multiple_from_judged,
    )
    growth_mult = growth_multiple_from_judged(
      state.get("judged_growth"), ops_json=ops_json,
    )
    eval_fence = _ctl.evaluate_current(
      financials_json=financials_json, ops_json=ops_json,
      financials_year1_json=financials_year1_json,
      margin_band=band, growth_to_q11=None,
    )
    if eval_fence is None:
      return financials_json
    eval_judged = None
    if growth_mult:
      eval_judged = _ctl.evaluate_current(
        financials_json=financials_json, ops_json=ops_json,
        financials_year1_json=financials_year1_json,
        margin_band=band, growth_to_q11=growth_mult,
      )
    # The gate's own tier choice (two-tier law): judged while walking
    # or when the fence fails; fence otherwise.
    use_judged = eval_judged is not None and (
      state.get("status") == _ctl.STATUS_WALKING
      or not eval_fence.get("passed")
    )
    eval_result = eval_judged if use_judged else eval_fence
    eval_result["basis_growth"] = {
      "used": "judged" if use_judged else "fence",
      "judged_multiple": round(growth_mult, 4) if growth_mult else None,
    }
    gap = _f(eval_result.get("gap_quarterly"))
    state = dict(state)
    state["eval"] = {
      "passed": bool(eval_result.get("passed")),
      "failed": eval_result.get("failed"),
      "gap_quarterly": gap,
      "q11": eval_result.get("q11"),
      "thresholds": eval_result.get("thresholds"),
      "binding": binding_constraint(eval_result),
      "q20_hold": _q20_hold(eval_result, band),
    }
    state["gap_open"] = gap
    eval_flat = _ctl.evaluate_current(
      financials_json=financials_json, ops_json=ops_json,
      financials_year1_json=financials_year1_json,
      margin_band=band, growth_to_q11=1.0,
    )
    state["eval_flat"] = {
      "passed": bool((eval_flat or {}).get("passed")) if isinstance(eval_flat, dict) else None,
      "q11": (eval_flat or {}).get("q11") if isinstance(eval_flat, dict) else None,
    }
    # The judged shortfall is a LIVE disclosure, not a latch: it stands
    # only while the judged tier actually fails on the current numbers.
    if eval_judged is not None and not use_judged and not eval_judged.get("passed"):
      state["eval_judged_shortfall"] = _f(eval_judged.get("gap_quarterly"))
    else:
      state.pop("eval_judged_shortfall", None)
    # Walls refresh with the same cadence (phase 3's wall, live).
    # ANCHOR BASIS here, deliberately: this refresh runs MID-Recalc,
    # where financials_year1_json can be a transiently rebuilt (ramped)
    # total the engine never reads - on the real Sparrow draft that
    # stamped the wall passed-at-53% in the same turn the gate blocked
    # at 72%. The gate's own computation (stored year1, the engine's
    # exact read) is the authoritative verdict and restamps at every
    # completion attempt; the display refresh uses the anchor so it
    # cannot contradict the gate on the drafts we actually see (stored
    # year1 echoes the anchor).
    wall = _payroll_share_wall_result(
      state, ops_json=ops_json, financials_json=financials_json,
      financials_year1_json={},
    )
    if wall is not None:
      state["walls"] = {"payroll_share": wall}
    else:
      state.pop("walls", None)
    return put_state(financials_json, state)
  except Exception:
    return financials_json


# --------------------------------------------------------- patch handling

_EXPLICIT_PARK_RE = re.compile(
  r"save it for now|park it|pause (?:this|it|here)|stop here|hold off"
  r"|come back (?:to this )?later|that'?s enough for (?:now|today)"
  r"|let'?s stop|put (?:this|it) on hold", re.I,
)


def apply_router_patch(
  *,
  patch: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  user_text: str = "",
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

  # Client-asserted floor: "the lease is signed", "those are employment
  # contracts" — a committed cost the walk may never propose cutting.
  # Recorded in state; the round rebuilds without that lever (CW-002:
  # options re-proposed cutting a signed 3-year lease twice).
  asserted = remaining.pop("coherence.assert_floor", remaining.pop("assert_floor", None))
  if asserted is not None:
    cost = str(asserted).strip().lower()
    alias = {"overhead": "gna", "opex": "gna", "other": "gna",
             "supplies": "cogs", "materials": "cogs"}
    cost = alias.get(cost, cost)
    if cost in ("rent", "payroll", "marketing", "gna", "cogs"):
      state = dict(state)
      floors = dict(state.get("client_floors") or {})
      floors[cost] = True
      state["client_floors"] = floors
      state.pop("round", None)  # rebuild options honoring the assertion
      next_fin = put_state(next_fin, state)
      notes.append(f"client_floor:{cost}")

  # CW-024 #118 CONSUMER: the client's retention answer re-lands the
  # numbers over the judge's conservative edge (client truth > judge,
  # as ruled). Value: a fraction (0-1] or {kept, of}. Scales the
  # utilization and anchor from the landed retained_used to the
  # client's own fraction; lever writes keep CW-020.
  _ret_answer = remaining.pop("coherence.retention_answer",
                              remaining.pop("retention_answer", None))
  if _ret_answer is not None:
    next_fin, next_ops, _ret_applied = apply_retention_answer(
      next_fin, next_ops, _ret_answer,
    )
    if _ret_applied:
      notes.append("retention_answer")

  parked = remaining.pop("coherence.parked", remaining.pop("parked", None))
  if parked is not None and str(parked).strip().lower() in ("true", "1", "yes"):
    # CW-024 #116 (Nick-ruled, prevention shape): a park can only come
    # from an EXPLICIT stop-intent in the client's own words. A turn
    # that ANSWERS the app's questions cannot be a park - the Cedar
    # Ridge client itemized their cost lines and named the wrong figure
    # and got parked with Send disabled. A router park without the
    # marker is ignored and the turn continues as whatever else it
    # carried.
    _answered_something = "retention_answer" in notes or bool(
      [k for k in remaining if str(k).split(".")[-1] not in ("parked",)]
      and any(str(k).startswith(("people.", "financials.", "ops."))
              for k in remaining)
    )
    if _EXPLICIT_PARK_RE.search(str(user_text or "")) and not _answered_something:
      state = dict(state)
      state["status"] = _ctl.STATUS_PARKED
      next_fin = put_state(next_fin, state)
      notes.append("parked")
      return remaining, next_ops, next_fin, notes
    notes.append("park_ignored_no_explicit_intent")

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
        _old_rev = _f(next_fin.get("current_revenue"))
        _cpct_before = _f(next_fin.get("cogs_percent_of_revenue"))
        if spec.get("current_revenue"):
          # CW-022 #7: a price-only move holds COGS DOLLARS (volume
          # held), so the stated cogs PERCENT must rescale with the
          # anchor — leaving it fixed silently inflated the client's
          # stated supplies dollars by the price ratio (Fetch & Fluff:
          # $5,900 became $14,676).
          _new_rev = float(spec["current_revenue"])
          next_fin["current_revenue"] = _new_rev
          if _old_rev > 0 and _new_rev > 0 and abs(_new_rev - _old_rev) > 0.005 * _old_rev:
            _k = _old_rev / _new_rev
            if _cpct_before > 0:
              next_fin["cogs_percent_of_revenue"] = round(_cpct_before * _k, 6)
        # CW-022 #4: an accepted price lever owes the client the demand
        # question - stamp it; the next gate message leads with it.
        _st_pc = get_state(next_fin)
        _st_pc = dict(_st_pc)
        _st_pc["price_clarifier_due"] = {
          "prices": [
            {"product": p.get("product"), "to": p.get("unit_price")}
            for p in (spec.get("prices") or [])
          ],
          # CW-024 #118: the landing's assumed retention rides along so
          # the client's answer can replace it precisely.
          "retained_used": _f(spec.get("retained_fraction"), 1.0) or 1.0,
        }
        # PHASE 2: record the lever's own writes so the band-identity
        # digest can exclude them (lever moves re-evaluate, never
        # re-judge - CW-020); a later CLIENT correction to a different
        # value re-enters the digest and re-judges.
        # DEMAND JUDGE landing (Nick-ruled #2): an accepted price move
        # carries its judged retained-demand consequence INTO THE TRUTH
        # - utilization scales by the conservative retained edge (so
        # ops-implied revenue equals the landed anchor and the
        # anchor-vs-ops check holds), and COGS follows the retained
        # volume (ratio-basis pct x retained; dollars-basis stated
        # dollars x retained). The client's clarifier answer afterwards
        # re-lands whatever they actually expect (client > judge).
        _retained = _f(spec.get("retained_fraction"))
        if _retained is not None and 0.0 < _retained < 1.0 - 1e-9:
          _vol_specs = []
          for _l in (next_ops.get("lob_models") or []):
            if not isinstance(_l, dict):
              continue
            for _p in (_l.get("products") or []):
              if not isinstance(_p, dict):
                continue
              _u = _f(_p.get("utilization_rate"), 1.0)
              _vol_specs.append({
                "lob": _l.get("lob_name") or _l.get("lob") or "",
                "product": _p.get("product_name") or _p.get("product") or "",
                "utilization_rate": round(max(0.01, _u * _retained), 4),
              })
          next_ops = _apply_volume_spec(next_ops, _vol_specs)
          _cpct_mid = _f(next_fin.get("cogs_percent_of_revenue"))
          if _cpct_mid > 0:
            next_fin["cogs_percent_of_revenue"] = round(_cpct_mid * _retained, 6)
          if str(next_fin.get("cogs_basis") or "").strip().lower() == "dollars":
            _cogs_from_r = _f(next_fin.get("current_cogs"))
            for _cf in ("current_cogs", "cogs_total_year1"):
              _cv = _f(next_fin.get(_cf))
              if _cv > 0:
                next_fin[_cf] = round(_cv * _retained, 2)
        _lw = dict(_st_pc.get("_lever_writes") or {})
        if spec.get("current_revenue"):
          _record_lever_write(
            _lw, "current_revenue",
            _old_rev if _old_rev > 0 else None, float(spec["current_revenue"]))
        _cpct_now = _f(next_fin.get("cogs_percent_of_revenue"))
        if _cpct_now > 0 and _cpct_now != _cpct_before:
          _record_lever_write(
            _lw, "cogs_percent_of_revenue",
            _cpct_before if _cpct_before > 0 else None, float(_cpct_now))
        if (
          str(next_fin.get("cogs_basis") or "").strip().lower() == "dollars"
          and _retained is not None and 0.0 < _retained < 1.0 - 1e-9
        ):
          _cd_now = _f(next_fin.get("current_cogs"))
          if _cd_now > 0:
            _record_lever_write(
              _lw, "current_cogs", round(_cd_now / _retained, 2), _cd_now)
        _st_pc["_lever_writes"] = _lw
        next_fin = put_state(next_fin, _st_pc)
        notes.append(f"option:{option_id}:prices")
      elif spec.get("kind") == "ops_volume":
        # PHASE 4: the volume lever. Volume carries COGS: the anchor
        # moves with the units; ratio-basis COGS needs nothing (the pct
        # holds and the Recalc re-derives dollars from the new anchor);
        # dollars-basis stated COGS scales with the volume ratio.
        next_ops = _apply_volume_spec(next_ops, spec.get("volumes") or [])
        _old_rev_v = _f(next_fin.get("current_revenue"))
        if spec.get("current_revenue"):
          _new_rev_v = float(spec["current_revenue"])
          next_fin["current_revenue"] = _new_rev_v
          _st_vw = dict(get_state(next_fin))
          _lw = dict(_st_vw.get("_lever_writes") or {})
          _record_lever_write(
            _lw, "current_revenue",
            _old_rev_v if _old_rev_v > 0 else None, _new_rev_v)
          if (
            str(next_fin.get("cogs_basis") or "").strip().lower() == "dollars"
            and _old_rev_v > 0 and _new_rev_v > 0
          ):
            _kv = _new_rev_v / _old_rev_v
            _cogs_from = _f(next_fin.get("current_cogs"))
            for _cf in ("current_cogs", "cogs_total_year1"):
              _cv = _f(next_fin.get(_cf))
              if _cv > 0:
                next_fin[_cf] = round(_cv * _kv, 2)
            if _cogs_from > 0:
              _record_lever_write(
                _lw, "current_cogs", _cogs_from, round(_cogs_from * _kv, 2))
          _st_vw["_lever_writes"] = _lw
          next_fin = put_state(next_fin, _st_vw)
        notes.append(f"option:{option_id}:volume")
      elif spec.get("kind") == "financials_fields":
        _st_cw = dict(get_state(next_fin))
        _lw = dict(_st_cw.get("_lever_writes") or {})
        for fp in spec.get("fields") or []:
          if fp.get("group") == "financials" and fp.get("field"):
            _field = str(fp["field"])
            _value = fp.get("value")
            # PHASE 2: record the lever write in the terms the identity
            # digest reads (the Recalc will re-derive the twins) -
            # pre-write value captured BEFORE the field lands.
            if _field == "payroll_adjustment":
              _base = _f(next_fin.get("baseline_payroll_year1"))
              _record_lever_write(
                _lw, "baseline_payroll_year1",
                _base if _base > 0 else None,
                round((_base or 0.0) + (_f(_value) or 0.0), 2))
            elif _field == "other_operating_expense":
              _opex = _f(next_fin.get("other_opex_absolute"))
              _record_lever_write(
                _lw, "other_opex_absolute",
                _opex if _opex > 0 else None,
                round((_f(_value) or 0.0) * 12.0, 2))
            else:
              _prior = _f(next_fin.get(_field)) if next_fin.get(_field) is not None else None
              _record_lever_write(_lw, _field, _prior, _f(_value))
            next_fin[_field] = _value
          elif fp.get("group") and fp.get("field"):
            # PAYROLL CAUSE-SPLIT (Nick-ruled): people-group option
            # fields (owner_pay_monthly, phase_planned_hires) route to
            # the generic scoped apply, which owns the one-door and
            # pseudo-field mechanics. The accepted lever's baseline
            # effect is excluded from the identity (CW-020) via the
            # expected post-Recalc baseline.
            remaining[f"{fp['group']}.{fp['field']}"] = fp.get("value")
            _delta = _f(fp.get("expected_baseline_delta"))
            if _delta is not None and abs(_delta) > 0.005:
              _base = _f(next_fin.get("baseline_payroll_year1"))
              _record_lever_write(
                _lw, "baseline_payroll_year1",
                _base if _base > 0 else None,
                round((_base or 0.0) + _delta, 2))
        # DEMAND-COUPLED marketing landing (Nick-ruled): the accepted
        # cut lands its judged demand consequence - anchor and
        # utilization scale by the conservative retained edge; the
        # projection and the truth agree (never pure savings).
        _dl = spec.get("demand_landing")
        _dmult = _f((_dl or {}).get("demand_mult_lo")) if isinstance(_dl, dict) else None
        if _dmult is not None and 0.0 < _dmult < 1.0 - 1e-9:
          _rev_before_m = _f(next_fin.get("current_revenue"))
          if _rev_before_m > 0:
            _rev_after_m = round(_rev_before_m * _dmult, 2)
            next_fin["current_revenue"] = _rev_after_m
            _record_lever_write(
              _lw, "current_revenue", _rev_before_m, _rev_after_m)
          _vol_specs_m = []
          for _l in (next_ops.get("lob_models") or []):
            if not isinstance(_l, dict):
              continue
            for _p in (_l.get("products") or []):
              if not isinstance(_p, dict):
                continue
              _u = _f(_p.get("utilization_rate"), 1.0)
              _vol_specs_m.append({
                "lob": _l.get("lob_name") or _l.get("lob") or "",
                "product": _p.get("product_name") or _p.get("product") or "",
                "utilization_rate": round(max(0.01, _u * _dmult), 4),
              })
          next_ops = _apply_volume_spec(next_ops, _vol_specs_m)
          if str(next_fin.get("cogs_basis") or "").strip().lower() == "dollars":
            for _cf in ("current_cogs", "cogs_total_year1"):
              _cv = _f(next_fin.get(_cf))
              if _cv > 0:
                next_fin[_cf] = round(_cv * _dmult, 2)
        _st_cw["_lever_writes"] = _lw
        next_fin = put_state(next_fin, _st_cw)
        notes.append(f"option:{option_id}:costs")

  overrides = remaining.pop("ops.product_overrides", remaining.pop("product_overrides", None))
  if isinstance(overrides, dict) and overrides:
    result = _apply_custom_prices(next_ops, next_fin, overrides, state)
    next_ops, next_fin, clamped = result
    notes.append("custom_prices" + (":clamped" if clamped else ""))

  # LEVER-TURN WHITELIST (mirrors the ops-interview patch narrowing):
  # whatever survives to the generic apply may only be the active round's
  # declared targets or a disputable stated-fact field. Everything else
  # is dropped and logged — a router echo of current state must never
  # reach the draft (Harborline CW-001 wholesale-echo vandalism).
  allowed = set(DISPUTABLE_FIELDS)
  for o in rnd.get("options") or []:
    for fp in ((o.get("patch") or {}).get("fields") or []):
      if fp.get("group") and fp.get("field"):
        allowed.add(f"{fp['group']}.{fp['field']}")
  dropped = sorted(k for k in remaining if k not in allowed)
  for k in dropped:
    remaining.pop(k, None)
  if dropped:
    notes.append("dropped:" + ",".join(dropped))

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
    # Live ops keys are lob_name/product_name (ops_line_split's own
    # fallbacks); the bare lob/product/name keys are the legacy shape.
    # Matching only the legacy keys silently dropped every custom price
    # on live drafts (ablation batch A side-finding).
    lob_name = str(l.get("lob") or l.get("lob_name") or l.get("name") or "").strip().lower()
    prods = [dict(p) if isinstance(p, dict) else p for p in (l.get("products") or [])]
    for p in prods:
      if not isinstance(p, dict):
        continue
      n_products += 1
      key = (lob_name, str(p.get("product") or p.get("product_name") or p.get("name") or "").strip().lower())
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


def _apply_volume_spec(ops_json: Dict[str, Any], volumes: List[Dict[str, Any]]) -> Dict[str, Any]:
  """Land per-line volume moves (utilization + capacity) on the ops
  truth - the _apply_price_spec analog. The landing was computed
  utilization-first by the round; this just writes the knobs."""
  next_ops = dict(ops_json or {})
  lobs = [dict(l) if isinstance(l, dict) else l for l in (next_ops.get("lob_models") or [])]
  by_name: Dict[Any, Dict[str, Any]] = {}
  for spec in volumes or []:
    by_name[(str(spec.get("lob") or "").strip().lower(),
             str(spec.get("product") or "").strip().lower())] = spec
  n_products = 0
  for l in lobs:
    if not isinstance(l, dict):
      continue
    lob_name = str(l.get("lob") or l.get("lob_name") or l.get("name") or "").strip().lower()
    prods = [dict(p) if isinstance(p, dict) else p for p in (l.get("products") or [])]
    for p in prods:
      if not isinstance(p, dict):
        continue
      n_products += 1
      key = (lob_name, str(p.get("product") or p.get("product_name") or p.get("name") or "").strip().lower())
      spec = by_name.get(key)
      if not spec:
        continue
      _util = _f(spec.get("utilization_rate"))
      _cap = _f(spec.get("units_per_period_capacity"))
      if _util > 0:
        p["utilization_rate"] = min(1.0, _util)
      if _cap > 0:
        # write whichever capacity key this product carries (live vs legacy)
        if p.get("units_per_period_capacity") is not None or p.get("units_per_week_capacity") is None:
          p["units_per_period_capacity"] = _cap
        else:
          p["units_per_week_capacity"] = _cap
    l["products"] = prods
  next_ops["lob_models"] = lobs
  # keep the flat convenience fields in step for single-line models
  if n_products == 1 and volumes:
    only = volumes[0] or {}
    if _f(only.get("utilization_rate")) > 0 and next_ops.get("utilization_rate") is not None:
      next_ops["utilization_rate"] = min(1.0, _f(only.get("utilization_rate")))
    if _f(only.get("units_per_period_capacity")) > 0:
      for flat_key in ("units_per_period_capacity", "units_per_week_capacity"):
        if next_ops.get(flat_key) is not None:
          next_ops[flat_key] = _f(only.get("units_per_period_capacity"))
          break
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
    # CW-022 #3: custom prices clamp to the ABSOLUTE judged ceiling.
    pmax = _ctl._effective_pmax(line, bl)
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
        f"{fact['product']} is at ${fact['current_price']:,.2f} and similar "
        f"businesses in your market charge up to about ${fact['believable_max']:,.2f}"
      )
    opts = []
    for i, o in enumerate(rnd.get("options") or [], start=1):
      price_bits = ", ".join(
        f"{p['product']} at ${p['to']:,.2f}" for p in (o.get("prices") or [])
      )
      rec = " - this is the one I'd suggest" if o.get("recommended") else ""
      # CW-022 #7: a widening projection is said out loud, never "$0".
      closes_bit = (
        f"which would actually WIDEN the gap by about {o['closes_display']} on "
        "these numbers - something is off, tell me which figure looks wrong"
        if o.get("widens")
        else f"which closes about {o['closes_display']} of the gap"
      )
      opts.append(f"{i}) {o['label'].capitalize()}: {price_bits}, {closes_bit}{rec}")
    _ra = (rnd.get("facts") or {}).get("retained_assumption")
    _ra_txt = ""
    if isinstance(_ra, dict) and _ra.get("fraction_lo") is not None:
      _ra_txt = (
        f"These projections assume you keep at least "
        f"{float(_ra['fraction_lo']):.0%} of your current customers at the "
        "higher price (based on what your market's own numbers show) - you "
        "know your customers best, so your answer beats that estimate. "
      )
    return (
      "The biggest lever is pricing. " + "; ".join(lines) + ". "
      + " ".join(opts) + ". " + _ra_txt +
      "You can also give me exact prices and I'll keep them in line with what your market pays. "
      "Which fits your business? Whatever you pick, I'll recompute on the spot - "
      f"we're closing a {gap_display} a quarter gap so this plan can work on paper."
    )
  if key == _ctl.ROUND_VOLUME:
    lines = []
    for fact in (rnd.get("facts") or {}).get("lines") or []:
      lines.append(
        f"{fact['product']} runs about {fact['current_annual_units']:,} a year now, "
        f"and your market realistically has room for up to "
        f"{fact['believable_max_annual_units']:,}"
      )
    opts = []
    for i, o in enumerate(rnd.get("options") or [], start=1):
      vol_bits = ", ".join(
        f"{v['product']} to about {v['to_annual_units']:,} a year"
        for v in (o.get("volumes") or [])
      )
      rec = " - this is the one I'd suggest" if o.get("recommended") else ""
      closes_bit = (
        f"which would actually WIDEN the gap by about {o['closes_display']} on "
        "these numbers - something is off, tell me which figure looks wrong"
        if o.get("widens")
        else f"which closes about {o['closes_display']} of the gap"
      )
      opts.append(f"{i}) {o['label'].capitalize()}: {vol_bits}, {closes_bit}{rec}")
    return (
      "Another real lever is volume - serving more of the demand your market "
      "already has. " + "; ".join(lines) + ". "
      + " ".join(opts) + ". "
      "More volume carries its own direct costs - I've counted that. "
      "Which fits how your business actually books work? I'll recompute on the spot - "
      f"we're closing a {gap_display} a quarter gap so this plan can work on paper."
    )
  if key == _ctl.ROUND_COSTS:
    # CW-022 #5: internal move keys never reach the client ("gna" leaked
    # verbatim at Fetch & Fluff turn 112).
    _move_labels = {
      "gna": "your other operating costs",
      "marketing": "marketing",
      "rent": "the space",
      "payroll": "the team",
      "owner_draw": "your own pay (your choice entirely)",
      "hire_timing": "when the planned hires start",
      "cogs": "your direct costs (supplies/materials)",
    }
    opts = []
    for i, o in enumerate(rnd.get("options") or [], start=1):
      move_bits = ", ".join(
        f"{_move_labels.get(name, name)} from {m.get('from_display')} to {m.get('to_display')}"
        for name, m in (o.get("moves") or {}).items()
      )
      rec = " - this is the one I'd suggest" if o.get("recommended") else ""
      closes_bit = (
        f"which would actually WIDEN the gap by about {o['closes_display']} on "
        "these numbers - something is off, tell me which figure looks wrong"
        if o.get("widens")
        else f"closing about {o['closes_display']}"
      )
      opts.append(f"{i}) {o['label'].capitalize()}: {move_bits}, {closes_bit}{rec}")
    return (
      "Next lever: the cost structure is carrying more than a mature quarter needs, "
      "and every floor here reflects what it really takes to run your business. "
      + " ".join(opts) + ". "
      "Which works for you? I'll recompute right away - "
      f"{gap_display} a quarter is what's left to make this work on paper."
    )
  if key == _ctl.ROUND_NEW_LINES:
    offers = []
    for o in (rnd.get("options") or [])[:2]:
      offers.append(
        f"{o.get('product')} (worth up to {_fmt(_f(o.get('q11_quarterly_revenue_max')))} a quarter"
        + (
          f" at {round(_f(o.get('gross_margin_pct')) * 100)}% margin)"
          if o.get("gross_margin_pct") is not None
          else ", margin not yet specified)"
        )
      )
    return (
      "There are also revenue lines your operation could carry, sized against your real "
      "capacity: " + " and ".join(offers) + ". Adding one means we revisit your operating "
      "setup together - tell me if you want to, or we can keep working with what's here. "
      f"Either way, {gap_display} a quarter is what's left to make this work on paper."
    )
  return f"Let's keep going - {gap_display} a quarter left to make this work on paper."


def binding_constraint(eval_result: Dict[str, Any]) -> Dict[str, Any]:
  """The inequality that actually computes the gap, with client-facing
  displays. CW-002 lesson: narrating the band floor while the burden
  ceiling drove the gap put a self-contradiction on screen ('keeps 3x
  the requirement, yet a gap') and pushed the chat layer into
  confabulating internal mechanics. One truth on screen."""
  q11 = eval_result.get("q11") or {}
  th = eval_result.get("thresholds") or {}
  rev = _f(q11.get("revenue"))
  ebitda = _f(q11.get("ebitda"))
  fixed = _f(q11.get("payroll")) + _f(q11.get("rent")) + _f(q11.get("gna"))
  gm = (rev - _f(q11.get("cogs"))) / rev if rev > 0 else 0.0
  candidates = []
  failed = set(eval_result.get("failed") or [])
  if "fixed_cost_burden" in failed and rev > 0:
    over = fixed - _f(th.get("burden_max")) * rev
    candidates.append((over, {
      "key": "fixed_cost_burden",
      "sentence": (
        f"your fixed running costs - payroll {_fmt(_f(q11.get('payroll')))}, "
        f"rent {_fmt(_f(q11.get('rent')))}, overhead {_fmt(_f(q11.get('gna')))} - "
        f"come to {_fmt(fixed)} a quarter, {_pct(fixed / rev)} of revenue, "
        f"where a business like yours needs to carry at most {_pct(_f(th.get('burden_max')))}"
      ),
      "actual_display": f"{_fmt(fixed)} ({_pct(fixed / rev)} of revenue)",
      "limit_display": f"at most {_pct(_f(th.get('burden_max')))} of revenue",
    }))
  if "ebitda_band_low" in failed or "ebitda_positive" in failed:
    floor_d = _f(q11.get("band_low_floor_dollars"))
    candidates.append((max(0.0, floor_d - ebitda), {
      "key": "ebitda_band_low",
      "sentence": (
        f"the quarter keeps {_fmt(ebitda)}, where a business like yours needs to keep "
        f"at least {_fmt(floor_d)} ({_pct(_f(th.get('band_low')))} of revenue)"
      ),
      "actual_display": f"keeps {_fmt(ebitda)}",
      "limit_display": f"at least {_fmt(floor_d)} ({_pct(_f(th.get('band_low')))})",
    }))
  if "ni_floor" in failed and rev > 0:
    candidates.append(((_f(th.get("ni_floor")) - _f(q11.get("ni_margin"))) * rev, {
      "key": "ni_floor",
      "sentence": (
        f"after loan costs and depreciation the quarter clears {_pct(_f(q11.get('ni_margin')))} "
        f"of revenue, where a lender needs at least {_pct(_f(th.get('ni_floor')))}"
      ),
      "actual_display": f"clears {_pct(_f(q11.get('ni_margin')))}",
      "limit_display": f"at least {_pct(_f(th.get('ni_floor')))}",
    }))
  if "gross_margin" in failed and rev > 0:
    candidates.append(((_f(th.get("gm_floor")) - gm) * rev, {
      "key": "gross_margin",
      "sentence": (
        f"after direct costs the quarter keeps {_pct(gm)} of each dollar, where this kind "
        f"of business needs at least {_pct(_f(th.get('gm_floor')))}"
      ),
      "actual_display": f"gross margin {_pct(gm)}",
      "limit_display": f"at least {_pct(_f(th.get('gm_floor')))}",
    }))
  if not candidates:
    return {
      "key": "ebitda_band_low",
      "sentence": (
        f"the quarter keeps {_fmt(ebitda)}, where a business like yours needs to keep at "
        f"least {_fmt(_f(q11.get('band_low_floor_dollars')))}"
      ),
      "actual_display": f"keeps {_fmt(ebitda)}",
      "limit_display": f"at least {_fmt(_f(q11.get('band_low_floor_dollars')))}",
    }
  candidates.sort(key=lambda c: c[0], reverse=True)
  return candidates[0][1]


def _opening(eval_result: Dict[str, Any], band_low: float) -> str:
  q11 = eval_result.get("q11") or {}
  binding = binding_constraint(eval_result)
  return (
    "Before we wrap up, I put your numbers together the way a lender will read them - "
    "your business once it's up and running, a few years in, on the strongest realistic "
    "growth path for it. Even there it doesn't quite hold: about "
    f"{_fmt(_f(q11.get('revenue')))} comes in, and {binding['sentence']}. "
    f"That's the whole gap: about {_fmt(_f(eval_result.get('gap_quarterly')))} a quarter. "
    "Here's the good news: we already checked the most favorable realistic version of "
    "your business, and a version that works exists - nothing here has happened yet, "
    "it's all still on paper, which is exactly where we fix it. One thing at a time, "
    "biggest first."
  )


def _roadmap_message(payload: Dict[str, Any]) -> str:
  # POSTURE (c) (Nick-ruled): DISTANCE framing, never failure framing.
  # The client's real, running business is the starting point; the gap
  # is a measured distance with named paths that use what they already
  # have; the close is an invitation, not homework. The two hard
  # promises (numbers stay saved and rerunnable; nothing ships
  # pretending, nothing fakes) are kept VERBATIM.
  miles = "; ".join(
    f"{m['title']} ({m['detail']})" for m in payload.get("milestones") or []
  )
  return (
    "Here's where things honestly stand. The business you've described is real "
    "and running - what we're measuring is distance, not worth. On today's "
    "shape, even the strongest realistic version of the numbers sits about "
    f"{payload.get('corner_gap_display')} a quarter away from a plan a lender "
    "would fund, and a plan that papered over that wouldn't survive the first "
    "hard question. So here are the fastest real paths to close that distance, "
    "built from what you already have, biggest first: " + miles + ". "
    "Which of those is closest to something you're already doing? Start there "
    "and the distance shrinks fastest - tell me which one and we'll shape it "
    "together. Your numbers stay right here - when one of those changes, come back "
    "and we rerun the same arithmetic. Nothing ships saying the business doesn't work "
    "on paper, and nothing gets faked to say it does."
  )


def _converged_suffix(
  eval_result: Dict[str, Any],
  thresholds_info: Dict[str, Any],
  flat_q11: Optional[Dict[str, Any]] = None,
  judged_gap: Optional[float] = None,
) -> str:
  q11 = eval_result.get("q11") or {}
  margin = _f(q11.get("ebitda_margin"))
  band_low = _f(thresholds_info.get("band_low"))
  band_high = thresholds_info.get("band_high")
  if band_high is not None and margin > _f(band_high):
    # Above the believable ceiling: honest phrasing — the engine will
    # temper the full plan into the band; never claim "inside".
    # CW-018 #3: "comfortably above the floor" read as a clean pass of
    # a figure that is ALSO above the believable ceiling (Vanguard:
    # 11.5% narrated against a 6-11% band). The wording now names the
    # tempering explicitly and points the reader at the range, not the
    # higher stress figure.
    band_txt = (
      f"that stress figure actually sits above the {_pct(band_low)}-"
      f"{_pct(_f(band_high))} that healthy businesses like yours actually "
      f"run, so the full build will temper it back to that level "
      f"- treat {_pct(_f(band_high))} as the honest ceiling, not the "
      f"figure above it"
    )
  elif band_high is not None:
    band_txt = (
      f"inside the {_pct(band_low)}-{_pct(_f(band_high))} that healthy "
      "businesses like yours actually run"
    )
  else:
    band_txt = "above the floor healthy businesses like yours actually run at"
  # THE PROMISE NAMES ITS TIER — permanently, not as interim copy. This
  # verdict is the structural checks coherence can run in the room; the
  # cash pass, the engine's own path-shaping, and landing noise always
  # sit outside it. "Your plan works" is never honest at this tier.
  # FRAMING RULE (CW-003): the figure below is the FENCE-POINT evaluation —
  # the strongest believable growth path — never the client's expected
  # quarter. Presenting a structural stress test as "your typical quarter"
  # made a 48.5% figure sit on screen beside its own 24% ceiling with no
  # explanation. The bar-clearing is what's being announced; say so.
  # CW-022 #6 (Nick-ruled): BOTH tiers disclosed, always. The flat
  # (today's-scale) figure is the number the client can check against
  # their own life - its absence is why Fetch & Fluff's founder had to
  # out-audit the tool ("that doesn't match my life at all").
  flat_txt = ""
  if isinstance(flat_q11, dict):
    _flat_eb = _f(flat_q11.get("ebitda"))
    if _flat_eb >= 0:
      flat_txt = (
        f" At today's scale, before any growth, the same structure keeps "
        f"about {_fmt(_flat_eb)} a quarter."
      )
    else:
      flat_txt = (
        f" At today's scale the same structure doesn't yet cover its costs "
        f"(about {_fmt(abs(_flat_eb))} short a quarter) - the growth path is "
        "what closes that."
      )
  if judged_gap is not None and judged_gap > 0:
    # Fence-pass + judged-fail: NEVER "clears every test". The boolean
    # divergence between the two computed tiers routes to consult
    # wording - the judged eval was always computed here and used to be
    # DISCARDED at this exact spot.
    return (
      " One thing worth sitting with together before you lean on this: at the "
      "strongest realistic version of your business, the structure can work - "
      f"a mature quarter at that stress point keeps about {_fmt(_f(q11.get('ebitda')))} "
      f"({_pct(margin)} of revenue), {band_txt}. But at the growth we'd actually "
      f"plan for, it still comes up about {_fmt(judged_gap)} a quarter short."
      + flat_txt +
      " If you want, we can work those levers together right now - pricing, "
      "costs, or another line of revenue - or you can submit and the full build "
      "will run its own final checks. Every number you just set is yours."
    )
  return (
    " One more thing worth knowing: your numbers clear every structural test we can "
    "run right now. That's a stress test, not a forecast - at the strongest realistic "
    f"version of your business, a mature quarter would keep about {_fmt(_f(q11.get('ebitda')))} "
    f"({_pct(margin)} of revenue), {band_txt}."
    + flat_txt +
    " The full build will shape the realistic "
    "quarter-by-quarter path and run its own final checks - and every number you just "
    "set is yours."
  )


# ------------------------------------------------------------------ gate

def _ops_implied_and_ceiling(ops_json: Dict[str, Any]) -> Tuple[float, float]:
  """(CW-022 #2) The operation's own annual revenue arithmetic:
  implied = sum(price x capacity x periods x utilization) and the
  physical ceiling = the same at utilization 1.0. Zero when the model
  carries no unit-driven products (non-unit businesses skip the check)."""
  implied = 0.0
  ceiling = 0.0
  for lob in (ops_json or {}).get("lob_models") or []:
    if not isinstance(lob, dict):
      continue
    for p in lob.get("products") or []:
      if not isinstance(p, dict):
        continue
      price = _f(p.get("unit_price"))
      cap = _f(p.get("units_per_period_capacity"))
      periods = _f(p.get("operating_periods_per_year")) or 12.0
      util = _f(p.get("utilization_rate"))
      util = util if 0.0 < util <= 1.0 else 1.0
      if price > 0 and cap > 0:
        implied += price * cap * periods * util
        ceiling += price * cap * periods
  return implied, ceiling


def apply_retention_answer(
  financials_json: Dict[str, Any],
  ops_json: Dict[str, Any],
  answer: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
  """CW-024 #118 consumer, ONE authority (CW-027: also invoked by the
  handler's any-surface frame resolver - the Wren Hollow 90% answer
  arrived at the done-focus surface where no round was live, the app
  SAID it would rerun, and never applied it). The client's retention
  answer re-lands the numbers over the judge's conservative edge
  (client truth > judge, as ruled): a fraction (0-1] or {kept, of}
  scales revenue, utilization (clamped), and dollar-basis COGS from the
  landed retained_used to the client's own fraction, then clears the
  frame. Returns (financials, ops, applied)."""
  state = get_state(financials_json)
  pending = state.get("retention_pending")
  if not isinstance(pending, dict):
    return financials_json, ops_json, False
  frac = None
  if isinstance(answer, dict):
    k, o = _f(answer.get("kept")), _f(answer.get("of"))
    if k > 0 and o > 0:
      frac = min(1.0, k / o)
  else:
    frac = _f(answer)
    if frac is not None and frac > 1.0:
      frac = frac / 100.0
  next_fin = dict(financials_json)
  next_ops = ops_json
  used = _f(pending.get("retained_used"), 1.0) or 1.0
  if frac is not None and 0.0 < frac <= 1.0 and abs(frac - used) > 1e-6:
    adj = frac / used
    rev0 = _f(next_fin.get("current_revenue"))
    if rev0 > 0:
      rev1 = round(rev0 * adj, 2)
      next_fin["current_revenue"] = rev1
      state = dict(state)
      lw = dict(state.get("_lever_writes") or {})
      _record_lever_write(lw, "current_revenue", rev0, rev1)
      state["_lever_writes"] = lw
    vols = []
    for l in (next_ops.get("lob_models") or []):
      if not isinstance(l, dict):
        continue
      for p in (l.get("products") or []):
        if not isinstance(p, dict):
          continue
        u = _f(p.get("utilization_rate"), 1.0)
        vols.append({
          "lob": l.get("lob_name") or l.get("lob") or "",
          "product": p.get("product_name") or p.get("product") or "",
          "utilization_rate": round(max(0.01, min(1.0, u * adj)), 4),
        })
    next_ops = _apply_volume_spec(next_ops, vols)
    if str(next_fin.get("cogs_basis") or "").strip().lower() == "dollars":
      for cf in ("current_cogs", "cogs_total_year1"):
        cv = _f(next_fin.get(cf))
        if cv > 0:
          next_fin[cf] = round(cv * adj, 2)
  state = dict(state)
  state.pop("retention_pending", None)
  next_fin = put_state(next_fin, state)
  return next_fin, next_ops, True


def _owner_draw_exit_tail(cause: Dict[str, Any], wall_pay: Dict[str, Any]) -> str:
  """CW-026 ruling #2 (Nick-approved): the owner-draw exit at the
  payroll wall. The draw ceiling is what's left of the payroll ceiling
  AFTER the rest of the team - the old copy offered payroll_to_clear/12
  (the WHOLE team ceiling) as the owner's personal draw, telling an
  underpaid founder she had 3.6x headroom when she'd need to cut. At
  zero or below, the draw exit is NOT offered at all: an unreachable
  exit is unrepresentable as a choice, and revenue is named as the way
  through."""
  others_annual = (
    _f((cause or {}).get("staffed_annual"))
    + _f((cause or {}).get("phasable_annual"))
  )
  draw_ceiling = _f((wall_pay or {}).get("payroll_to_clear")) - others_annual
  revenue_txt = _fmt(_f((wall_pay or {}).get("revenue_to_clear")))
  if draw_ceiling > 0:
    return (
      "Most of that payroll is your own pay, which makes this yours to "
      f"choose: revenue at or above {revenue_txt} a year clears it with "
      "your pay as-is, or your own draw at or below "
      f"{_fmt(draw_ceiling / 12.0)} a month - with the rest of the team "
      "paid as-is - clears it at today's revenue. Which fits how you "
      "want to run it - or is one of the numbers not what you meant?"
    )
  return (
    "Most of that payroll is your own pay, but even at a minimal draw "
    "the rest of the team is above the line on its own - so revenue is "
    f"the honest way through: at or above {revenue_txt} a year the plan "
    "clears with everyone paid as-is. Or if the team itself is going to "
    "change in the real world, tell me how and I'll put it in properly."
  )


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

  # NO CONVERGED LATCH (CW-005): convergence used to be a terminal latch
  # replaying a frozen text snapshot - Brightwater corrected $9,500 ->
  # $1,900 after converging (via the reopen path) and the banner + readback
  # kept quoting the pre-correction $209,441/57.9% forever. Convergence is
  # a VERDICT ABOUT THE CURRENT NUMBERS, not a permanent badge: every
  # completion attempt re-runs the deterministic evaluation below with the
  # already-authored stamps (no GPT), so the suffix and panel figures are
  # always computed from the model as it stands. If a post-convergence
  # correction makes the numbers fail, the normal walk flow engages -
  # intake cannot close on a promise the corrected numbers no longer earn.

  if state.get("status") == _ctl.STATUS_ROADMAP:
    # PHASE 2 (Nick-ruled): the roadmap is NOT a latch. If the identity
    # (including the client-stated financials basis) changed since the
    # roadmap was delivered, clear it and fall through to a fresh
    # evaluation - the wording's promise, kept.
    _rm_digest, _ = _compute_band_identity_digest(
      state,
      ops_json=ops_json, people_json=people_json, market_json=market_json,
      marketing_model_json=marketing_model_json, financials_json=financials_json,
    )
    if state.get("digest_hash") and state.get("digest_hash") != _rm_digest:
      state = dict(state)
      for _k in ("roadmap", "corner", "bounds", "round", "status",
                 "_lever_writes", "demand_response", "essentials_response",
                 "corner_collapse_hold"):
        state.pop(_k, None)
      financials_json = put_state(financials_json, state)
      # fall through to the normal gate flow below (the fresh
      # _ensure_margin_band restamps the digest at the new epoch)
    else:
      # Roadmap stands (identity unchanged) — keep the door open without
      # repeating the whole speech, never complete, and ENGAGE with what
      # the client just said (a canned line every turn reads as a loop).
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
          "You are the intake consultant. The client's numbers currently sit about "
          f"{payload.get('corner_gap_display') or 'a meaningful amount'} per mature quarter "
          "away from a plan a lender would fund - a DISTANCE to close, never a failure "
          "of the client or the business. You have already delivered the paths that close "
          "it: "
          + "; ".join(f"{m.get('title')} ({m.get('detail')})" for m in payload.get("milestones") or [])
          + ". The client just said: \"" + str(user_text).strip()[:600] + "\". "
          "Reply in 2-4 warm, plain sentences: respond to what they actually said, connect "
          "it to the closest path where it fits (their existing customers and strengths are "
          "the vehicle), and close by reminding them their numbers stay saved and nothing "
          "ships until the plan can work on paper. Never frame it as their failure. Do not "
          "invent any new figure. Keep the phrase 'work on paper'."
        )
        message = _safe_naturalize(fallback, lambda _t: naturalize(context))
      return {"assistant_message": message}, financials_json, ""

  # CW-022 #2 (Nick-ruled): ANCHOR-vs-OPS COHERENCE before any verdict.
  # The stated revenue anchor and the operation's own arithmetic must be
  # in the same reality before the gate evaluates anything - at Fetch &
  # Fluff's turn 112 they diverged 26x (a corrupted anchor) and the walk
  # ran four rounds of dollar narration on garbage. Two deliberate
  # CONSENT TRIGGERS (holds that ask, never verdicts): (a) anchor
  # outside [0.5x, 2x] of the ops-implied revenue - the capture side
  # already probes at 1.5x, this is the gate's backstop; (b) anchor
  # above the PHYSICAL ceiling (capacity x price x periods at 100%
  # utilization) - a plan cannot promise revenue the stated operation
  # cannot produce. Non-unit-driven models (implied == 0) skip.
  _stated_anchor = _f(financials_json.get("current_revenue"))
  _implied, _phys_ceiling = _ops_implied_and_ceiling(ops_json)
  if _stated_anchor > 0 and _implied > 0:
    _ratio = _stated_anchor / _implied
    _hold_reason = None
    if _stated_anchor > _phys_ceiling * 1.02:
      _hold_reason = (
        f"your stated annual revenue ({_fmt(_stated_anchor)}) is more than your "
        f"operation can physically produce even flat-out - at your stated "
        f"capacity and prices, 100% utilization tops out around "
        f"{_fmt(_phys_ceiling)} a year"
      )
    elif _ratio < 0.5 or _ratio > 2.0:
      _hold_reason = (
        f"your stated annual revenue ({_fmt(_stated_anchor)}) doesn't line up "
        f"with what your operation's own numbers produce - capacity x price x "
        f"utilization works out to about {_fmt(_implied)} a year"
      )
    if _hold_reason:
      message = (
        "Before I run the final checks, one thing doesn't add up: "
        + _hold_reason
        + ". Which is right - should I correct the revenue figure, or is one "
        "of the drivers (price, capacity, or utilization) out of date?"
      )
      return {"assistant_message": message}, financials_json, ""

  # CW-022 #4 (Nick-ruled): the price-acceptance clarifier. An accepted
  # price lever stamps price_clarifier_due; the very next gate message
  # leads with the demand question - the client is the best demand
  # oracle for an operating business (Fetch & Fluff volunteered exactly
  # this fact unprompted and nothing could consume it).
  _pc_question = ""
  _pc = state.get("price_clarifier_due")
  if isinstance(_pc, dict):
    state = dict(state)
    state.pop("price_clarifier_due", None)
    _pc_bits = ", ".join(
      f"{p.get('product')} at ${_f(p.get('to')):,.2f}"
      for p in (_pc.get("prices") or []) if p.get("to") is not None
    )
    if _pc_bits:
      _pc_question = (
        f"Quick check on the new price before we lean on it: at {_pc_bits}, "
        "do you expect your current customers to stay? If some would leave, "
        "tell me how many you'd realistically keep and I'll rerun the "
        "numbers on that. "
      )
      # CW-024 #118 (Nick-ruled: no question without a consumer). The
      # clarifier now registers its CONSUMER: a pending frame carrying
      # the retained fraction the landing assumed, so the client's own
      # answer ("30 of my 34") re-lands the numbers OVER the judge's
      # conservative edge - the ruled precedence, finally wired.
      state["retention_pending"] = {
        "prices": _pc.get("prices") or [],
        "retained_used": _f(_pc.get("retained_used"), 1.0) or 1.0,
      }
    financials_json = put_state(financials_json, state)

  # CW-024 #109 BACKSTOP surface: a money figure that landed nowhere is
  # disclosed on the very next message - never a silent drop.
  _unl = financials_json.get("_unlanded_note")
  if isinstance(_unl, dict) and _unl.get("figures"):
    _figs_txt = ", ".join(f"{_fmt(f)}" for f in _unl["figures"][:3])
    financials_json = dict(financials_json)
    financials_json.pop("_unlanded_note", None)
    _pc_question = (
      f"First - you gave me {_figs_txt} and I couldn't tell where it "
      "belongs, so I haven't recorded it. Tell me which line that figure "
      "is (for example: team payroll, revenue, rent, supplies) and I'll "
      "set it before anything else. "
    ) + _pc_question

  # SUB-RULING (ii) surface (Nick, cause-split slate): the fold applied
  # what was honest and HELD the remainder - the very next gate message
  # says so and asks HOW, and the plan carries no phantom credit.
  # (CW-026 ruling #2's owner-draw tail lives in _owner_draw_exit_tail.)
  _fold_hold = financials_json.get("_payroll_fold_hold")
  if isinstance(_fold_hold, dict) and _f(_fold_hold.get("unapplied")) != 0:
    _unap = abs(_f(_fold_hold.get("unapplied")))
    financials_json = dict(financials_json)
    financials_json.pop("_payroll_fold_hold", None)
    _pc_question = (
      f"On the team number: I applied what could honestly land, but the "
      f"remaining {_fmt(_unap)} a year would mean changing specific "
      "people's pay - I won't assume that. If it's real, tell me how it "
      "happens (fewer hours, a role change, a departure) and I'll put it "
      "in properly; otherwise the plan runs without it. "
    ) + _pc_question

  # CW-026 ruling #1 surface: two DIFFERENT client statements about the
  # owner's own pay merged to one row - the kept figure stands for now,
  # and the very next gate message asks which one is real. Never a
  # silent pick.
  _owner_hold = financials_json.get("_owner_wage_conflict_hold")
  if isinstance(_owner_hold, dict) and _f(_owner_hold.get("other")) > 0:
    financials_json = dict(financials_json)
    financials_json.pop("_owner_wage_conflict_hold", None)
    _pc_question = (
      f"One check on your own pay: I have two different figures from you "
      f"- {_fmt(_f(_owner_hold.get('kept')))} and "
      f"{_fmt(_f(_owner_hold.get('other')))} a year. I'm using "
      f"{_fmt(_f(_owner_hold.get('kept')))} for now - tell me which one "
      "is right and I'll set it. "
    ) + _pc_question

  # CW-022 #5 (floor-assertion backstop): a mid-walk protest that a cost
  # line cannot be cut must LAND even inside a multi-intent turn (Fetch
  # & Fluff's "I can't cut that, I'd be driving uninsured" never reached
  # client_floors because the router chose another action that turn).
  # Deterministic, conservative phrases only; floors only ever ADD.
  if state.get("status") == _ctl.STATUS_WALKING and str(user_text or "").strip():
    _low = str(user_text).lower()
    if re.search(r"(can'?t|cannot|won'?t|not going to|refuse to)\s+(cut|touch|reduce|trim|drop)", _low) \
       or "non-negotiable" in _low or "non negotiable" in _low:
      _floor_words = (
        ("gna", ("insurance", "fuel", "maintenance", "utilities", "software",
                 "licens", "bills", "overhead", "other costs")),
        ("marketing", ("marketing", "advertis", "ads")),
        ("rent", ("rent", "lease", "the space")),
        ("payroll", ("payroll", "team", "staff", "wages", "salar")),
        ("cogs", ("supplies", "materials", "ingredients", "direct costs",
                  "cost of goods")),
      )
      _cf = dict(state.get("client_floors") or {})
      _floor_hit = False
      for _bucket, _words in _floor_words:
        if not _cf.get(_bucket) and any(w in _low for w in _words):
          _cf[_bucket] = True
          _floor_hit = True
      if _floor_hit:
        state = dict(state)
        state["client_floors"] = _cf
        financials_json = put_state(financials_json, state)

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
    # The inequality that computes the gap, in client-facing terms — the
    # panel renders THIS, never a fixed band-floor template (CW-002).
    "binding": binding_constraint(eval_result),
    # Q20 SECOND POINT (Nick-ruled): internal direction check only.
    "q20_hold": _q20_hold(eval_result, band),
  }
  state["gap_open"] = gap
  if state.get("gap_initial") is None and gap > 0:
    state["gap_initial"] = gap

  # ---------- WALLS (phase 3): engine acceptance walls in view ----------
  # The payroll-share tier wall is enforced RAW by the engine's payload
  # builder (its exception bypasses every retry loop - deterministic
  # refusal). Sparrow converged at intake and died there at 0.72 vs the
  # high-class 0.70, three runs in a row. The gate now evaluates the
  # SAME wall on the same basis and refuses to converge into a build
  # the engine will certainly reject - the walk stays open with both
  # honest dollar exits named. Recomputed live every turn (the Recalc
  # keeps the ratio current); never stamped stale.
  _wall_pay = _payroll_share_wall_result(
    state, ops_json=ops_json, financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  if _wall_pay is not None:
    state["walls"] = {"payroll_share": _wall_pay}
  else:
    state.pop("walls", None)
  if eval_result.get("passed") and _wall_pay is not None and not _wall_pay.get("passed"):
    if state.get("status") == _ctl.STATUS_CONVERGED:
      state.pop("status", None)
    _cls_word = {"low": "capital-driven", "medium": "balanced-labor",
                 "high": "labor-intensive", "expert": "expert-labor"}.get(
                   str(_wall_pay.get("class")), str(_wall_pay.get("class")))
    # CAUSE-AWARE EXITS (Nick-ruled Option A): the wall names the exit
    # that matches WHY payroll is what it is - never a generic
    # cut-the-team dial. Owner-dominated -> the owner's own draw;
    # planned hires -> timing; existing staff -> revenue is the honest
    # closer (a real team change is the client's to volunteer).
    _cause = _ctl.payroll_cause_split(financials_json)
    _head = (
      "The profit math clears, but one structural wall still stands: your "
      f"team costs are {_wall_pay['value']:.0%} of revenue, and a "
      f"{_cls_word} business like this one is financed at no more than "
      f"{_wall_pay['max_pct']:.0%} - a lender won't finance a plan above that "
      "level, so I can't close the plan on these numbers. "
    )
    if _cause["kind"] == "owner_dominated":
      _tail = _owner_draw_exit_tail(_cause, _wall_pay)
    elif _cause["kind"] == "planned_hires":
      _tail = (
        "A real part of that payroll is hires you haven't made yet, so "
        "timing is an honest lever: revenue at or above "
        f"{_fmt(_wall_pay['revenue_to_clear'])} a year clears it on the "
        "current plan, or starting the planned hires later in the year "
        "brings year-1 team cost down without cutting anyone. Which fits "
        "your reality - or is one of the numbers not what you meant?"
      )
    else:
      _tail = (
        "That payroll is your real, current team - I won't propose cutting "
        "anyone's pay from arithmetic. The honest way through is revenue: "
        f"at or above {_fmt(_wall_pay['revenue_to_clear'])} a year the plan "
        "clears with the team you have (pricing and volume are the levers "
        "we can work right now). If the team itself is going to change in "
        "the real world, tell me how and I'll put it in properly."
      )
    financials_json = put_state(financials_json, state)
    return {"assistant_message": _head + _tail}, financials_json, ""

  # ---------- PASS: converge, complete with the readback ----------
  if eval_result.get("passed"):
    state["status"] = _ctl.STATUS_CONVERGED
    state.pop("round", None)
    # CW-022 #6: the flat (today's-scale) tier is free arithmetic -
    # always computed for disclosure; and a fence-tier pass whose
    # already-computed judged tier FAILS is disclosed as a divergence
    # (boolean trigger, no thresholds - the judged eval used to be
    # discarded right here).
    eval_flat = None
    try:
      eval_flat = _ctl.evaluate_current(
        financials_json=financials_json, ops_json=ops_json,
        financials_year1_json=financials_year1_json, margin_band=band,
        growth_to_q11=1.0,
      )
    except Exception:
      eval_flat = None
    flat_q11 = (eval_flat or {}).get("q11") if isinstance(eval_flat, dict) else None
    state["eval_flat"] = {
      "passed": bool((eval_flat or {}).get("passed")) if isinstance(eval_flat, dict) else None,
      "q11": flat_q11,
    }
    judged_gap = None
    if eval_judged is not None and not use_judged and not eval_judged.get("passed"):
      judged_gap = _f(eval_judged.get("gap_quarterly"))
      state["eval_judged_shortfall"] = judged_gap
    suffix = _converged_suffix(
      eval_result, eval_result.get("thresholds") or {},
      flat_q11=flat_q11, judged_gap=judged_gap,
    )
    if _pc_question:
      suffix = _pc_question + suffix
    state["converged_suffix"] = suffix
    financials_json = put_state(financials_json, state)
    return None, financials_json, suffix

  # ---------- FAIL: bounds once, corner-first ----------
  def _pick_receipt() -> str:
    """POSTURE (a) (Nick-ruled two-beat): the client's just-landed move
    is acknowledged BEFORE any verdict - engaging can never earn
    terminal defeat as its direct answer (Cedar Ridge turn 117: 'trim
    direct costs only' was answered with the defeat speech and no
    receipt). Deterministic from the same gap state the walking ack
    uses; a move that didn't help is still received honestly."""
    if prev_gap is None:
      return ""
    if gap < _f(prev_gap) - 0.5:
      closed = _f(prev_gap) - gap
      initial = _f(state.get("gap_initial")) or closed
      pct_total = min(100, round((1 - gap / initial) * 100)) if initial > 0 else 0
      return (
        f"First: that change is in, and it moved the plan - the gap closed "
        f"by {_fmt(closed)} a quarter ({pct_total}% of the way). "
      )
    if state.get("round"):
      return (
        "First: that change is recorded exactly as you chose it. It didn't "
        "move the numbers the way we hoped, so here's the honest picture. "
      )
    return ""

  _LEVER_LABELS = {
    "current_revenue": "annual revenue",
    "marketing_total_year1": "the marketing budget",
    "cogs_total_year1": "direct costs",
    "current_cogs": "direct costs",
    "cogs_percent_of_revenue": "the direct-cost share",
    "other_operating_expense": "other operating costs",
    "monthly_rent_expense": "rent",
    "payroll_adjustment": "team payroll",
  }

  def _recent_changes_display() -> str:
    """The walk's own writes, in plain words - what the tripwire
    disclosure points at."""
    parts = []
    for fld, w in (state.get("_lever_writes") or {}).items():
      if not isinstance(w, dict):
        continue
      label = _LEVER_LABELS.get(str(fld), str(fld).replace("_", " "))
      _fr, _to = w.get("from"), w.get("to")
      if "percent" in str(fld) or "share" in label:
        parts.append(f"{label} {_f(_fr) * 100:.0f}% to {_f(_to) * 100:.0f}%"
                     if _fr is not None else f"{label} to {_f(_to) * 100:.0f}%")
      else:
        parts.append(f"{label} {_fmt(_f(_fr))} to {_fmt(_f(_to))}"
                     if _fr is not None else f"{label} to {_fmt(_f(_to))}")
    return "; ".join(parts[:5]) if parts else "the adjustments we made together"

  def _deliver_roadmap(corner_obj, bounds_obj, was_walking):
    """POSTURE (b) (Nick-ruled): a corner that collapses MID-WALK is a
    TRIPWIRE, not a verdict - mid-course, worse-after-a-change usually
    means an input is off, not the business (Cedar Ridge: the phantom).
    One hold turn disclosing what changed; a correction re-keys the
    identity and re-derives everything, a confirmation (or unchanged
    inputs next turn) delivers the roadmap - WITH the pick receipt
    first (posture a). At GATE ENTRY (never walked), the roadmap keeps
    its immediate timing."""
    nonlocal financials_json
    if was_walking and not state.get("corner_collapse_hold"):
      state["corner_collapse_hold"] = {
        "gap_quarterly": _f(corner_obj.get("gap_quarterly")),
      }
      financials_json = put_state(financials_json, state)
      msg = (
        _pick_receipt()
        + "Before I take this any further: the strongest version of your "
        "numbers just got worse, and mid-course that usually means an "
        "input is off rather than the business. What changed on my side: "
        + _recent_changes_display() + ". If one of those figures isn't "
        "right, tell me the real one and I'll rerun everything. If they're "
        "all right, say so and I'll lay out the full picture straight."
      )
      return {"assistant_message": msg}, financials_json, ""
    state["status"] = _ctl.STATUS_ROADMAP
    state.pop("corner_collapse_hold", None)
    payload = _ctl.roadmap_payload(
      corner=corner_obj, eval_result=eval_result, bounds=bounds_obj or {},
    )
    state["roadmap"] = payload
    financials_json = put_state(financials_json, state)
    return {
      "assistant_message": (_pick_receipt() + _roadmap_message(payload)).strip(),
    }, financials_json, ""

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

  _was_walking = state.get("status") == _ctl.STATUS_WALKING

  if not bounds.get("feasible_region_exists", True):
    # ONLY the executive's honest "no believable region" answer routes
    # here. An author failure raised CoherenceJudgmentUnavailable in
    # _ensure_bounds — a transient error is a hold, never a roadmap.
    corner = {"passed": False, "q11": {}, "gap_quarterly": gap}
    state["corner"] = corner
    return _deliver_roadmap(corner, bounds, _was_walking)

  if state.get("corner") is None:
    state["corner"] = _ctl.corner_check(
      basis=corner_basis, thresholds=thresholds, bounds=bounds,
      ops_json=ops_json, financials_json=financials_json,
    )
  corner = state["corner"]

  if not corner.get("passed"):
    return _deliver_roadmap(corner, bounds, _was_walking)

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
      f"We're close but not quite there - {_fmt(gap)} a quarter still open, and "
      "every realistic adjustment is already in. We can revisit any number "
      "you'd like to change, or leave everything saved right here and pick it up "
      "when you're ready - nothing goes out until it can work on paper."
    )
    return {"assistant_message": msg}, financials_json, ""

  state["round"] = rnd
  question = _round_question(rnd, _fmt(gap))
  if _pc_question:
    question = _pc_question + question
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
  "CoherenceJudgmentUnavailable",
  "apply_router_patch", "gate_and_turn", "park_message", "reask_message",
]
