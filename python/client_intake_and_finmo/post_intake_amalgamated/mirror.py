"""Mirror — the manager's view of the situation, refreshed each tool call.

Per memo §2 + the manager/executive framing: GPT does not see an open
canvas. It sees one decision at a time: the current step, the standards
that apply, the lever headroom available, the validation state of the
plan as it stands, and what the last few moves did to that state. The
session driver (step 5) decides what's "current"; the mirror packages it.

This module is a builder + a couple of small helpers. It does not
talk to GPT and does not own the protocol — those are step 5.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # type: ignore
  EvaluatePlanResult,
  SECTIONS,
)


# P3.40 Contract Layer Cleanup 3/6 -- Contract 7 R10 + R11 closures:
# - R10 RESOLVED: dropped RecentDecision dataclass +
#   Mirror.recent_decisions field + Mirror.record_decision()
#   method + DEFAULT_RECENT_DECISIONS_CAP constant. Reader/writer
#   audit per Cleanup 3/6 confirmed zero production callers of
#   record_decision; recent_decisions had only serialization
#   (Mirror.to_dict + Contract 7 telemetry) and one test reader,
#   no GPT/responder consumer.
# - R11 RESOLVED: dropped Mirror.sequence_position +
#   Mirror.budget fields + the corresponding build_mirror kwargs.
#   Reader/writer audit confirmed zero callers pass these to
#   build_mirror; both always defaulted to empty dict; no
#   downstream reader.


# Cap on the number of failing-check names + failing-lever-margin entries
# that ``Mirror.set_validation_state`` projects into validation_state.
# Keeps the responder's prompt budget bounded even on plans with many
# simultaneous failures.
_VALIDATION_STATE_RENDER_CAP = 12

# The three invariants from the directive. Static. Always shown to GPT so the
# operating contract is unambiguous regardless of round.
_INVARIANTS: Dict[str, str] = {
  "realism": (
    "Operate within cohort-shape bounds derived from real businesses in this NAICS. "
    "No fantasy margins, no impossible ratios, no economically suspect outputs."
  ),
  "viability": (
    "Every plan must pass. No infeasibility escapes. If the math does not work at "
    "first, restructure Q1-onward until it does. Stub 0 is the historical truth and is immutable."
  ),
  "adaptation": (
    "When inputs do not compose, restructure Q1 onward until they do — holistically "
    "across price, payroll, utilization, costs, capex, and funding. Not 'fix one knob'."
  ),
}

_AUTHORITY = (
  "You may revise any value Q1 onward. You may NOT modify Stub 0 (the intake-captured "
  "historical state). You operate within the bands the manager presents; if no in-bounds "
  "configuration is feasible, use relax_lowest_priority_bound and the manager will record it."
)

# The balance_sheet / capex_rd / capex_rd_balance_seed alias triplet (Bug 2).
# `balance_sheet` and `capex_rd` are the two CONTRACT-VALID plan_state keys
# (MirrorContract's plan_state Literal); `capex_rd_balance_seed` is the
# v1-legacy alias name (a valid TOOL section, but NOT a valid plan_state key —
# it would be rejected by the contract's Literal before the F5 invariant runs).
# The read-side closure (session_factory._build_current_payload_for) resolves
# a `capex_rd_balance_seed` read to `balance_sheet`, so it never needs to be
# persisted as a key. The F5 plan_state_alias_sync invariant requires
# balance_sheet == capex_rd, so both must always carry the same payload.
_ALIAS_ANY = ("balance_sheet", "capex_rd_balance_seed", "capex_rd")
_ALIAS_IN_ENUM = ("balance_sheet", "capex_rd")


def _sync_capex_balance_aliases(plan_state: Dict[str, Any], *, prefer: Any = None) -> None:
  """Canonicalize the capex/balance alias triplet in-place so the two
  contract-valid keys (balance_sheet, capex_rd) hold one identical payload
  and the v1-legacy capex_rd_balance_seed key is never persisted.

  Satisfies the F5 plan_state_alias_sync invariant at BOTH the session-entry
  build (build_mirror) and post-commit writes (set_plan_state_section).
  Chosen payload: ``prefer`` when given, else the first non-empty alias
  among (balance_sheet, capex_rd_balance_seed, capex_rd); if an alias key is
  present but all are empty, both keys are set to {} (still F5-consistent).
  No-op when no alias key is present at all (pre-first-commit state).
  """
  if not isinstance(plan_state, dict):
    return
  chosen = prefer
  if chosen is None:
    if not any(k in plan_state for k in _ALIAS_ANY):
      return  # no alias section yet — nothing to sync
    for k in _ALIAS_ANY:
      v = plan_state.get(k)
      if v:  # first non-empty alias wins
        chosen = v
        break
    if chosen is None:
      chosen = {}
  for k in _ALIAS_IN_ENUM:
    plan_state[k] = chosen
  plan_state.pop("capex_rd_balance_seed", None)  # legacy key never persists


@dataclass
class Mirror:
  """The per-decision context handed to GPT.

  P3.40 Contract Layer Cleanup 3/6 -- Contract 7 R10 + R11
  closures dropped 3 phantom-write fields:
    - sequence_position (R11): no caller passed it; always
      defaulted to empty dict.
    - recent_decisions + record_decision() (R10): method
      defined but never called in production; serialized but
      never consumed by GPT/responder.
    - budget (R11): mirror of sequence_position.
  """
  invariants: Dict[str, str] = field(default_factory=dict)
  authority: str = ""
  business_facts: Dict[str, Any] = field(default_factory=dict)
  plan_state: Dict[str, Any] = field(default_factory=dict)
  bands: Dict[str, Any] = field(default_factory=dict)
  validation_state: Dict[str, Any] = field(default_factory=dict)

  def set_validation_state(self, evaluate_plan_result: EvaluatePlanResult) -> None:
    """Refresh the mirror's view of the current standards-check state.

    Stores a small projection (not the full ``to_dict()`` payload) so the
    responder can render it into GPT prompts without blowing the prompt
    budget. Captures the fields the responder actually needs to surface
    current failure context:

      - ``all_pass`` / ``failing_check_count``
      - ``worst_failing_check`` / ``worst_failing_distance``
      - ``failing_check_names``: ordered names of failing checks (cap
        applied to keep prompt budget bounded)
      - ``failing_lever_margins``: only the levers currently outside their
        band, each as ``{lever_id, section, current, band_min, band_max,
        outside_band, pinned_min, pinned_max}`` — same cap
      - ``round_number`` / ``strictness`` / ``evaluated_at``

    The full result remains on ``SessionDriver._last_result`` for
    in-process access; the mirror only carries what GPT needs to see.
    """
    if evaluate_plan_result is None:
      self.validation_state = {}
      return
    cap = _VALIDATION_STATE_RENDER_CAP
    failing_checks = [c for c in evaluate_plan_result.checks if not c.passed]
    failing_check_names = [c.name for c in failing_checks][:cap]
    failing_margins = [
      m for m in evaluate_plan_result.lever_margins
      if getattr(m, "outside_band", False)
    ]
    failing_lever_margins = [
      {
        "lever_id": getattr(m, "lever_id", None),
        "section": getattr(m, "section", None),
        "current": getattr(m, "current", None),
        "band_min": getattr(m, "band_min", None),
        "band_max": getattr(m, "band_max", None),
        "outside_band": getattr(m, "outside_band", False),
        "pinned_min": getattr(m, "pinned_min", False),
        "pinned_max": getattr(m, "pinned_max", False),
      }
      for m in failing_margins[:cap]
    ]
    self.validation_state = {
      "all_pass": bool(evaluate_plan_result.all_pass),
      "round_number": int(evaluate_plan_result.round_number),
      "strictness": str(evaluate_plan_result.strictness or ""),
      "failing_check_count": len(failing_checks),
      "worst_failing_check": evaluate_plan_result.worst_failing_check,
      "worst_failing_distance": evaluate_plan_result.worst_failing_distance,
      "failing_check_names": failing_check_names,
      "failing_check_names_truncated": len(failing_checks) > cap,
      "failing_lever_margins": failing_lever_margins,
      "failing_lever_margins_truncated": len(failing_margins) > cap,
      "evaluated_at": evaluate_plan_result.evaluated_at,
    }

  def set_plan_state_section(self, section: str, payload: Any) -> None:
    """Replace ``plan_state[section]`` with ``payload``.

    Called by SessionDriver after a successful revise_* commit so the
    next cascade tier reads the post-commit payload instead of the
    session-entry snapshot. A commit to ANY member of the capex/balance
    alias triplet (balance_sheet, capex_rd_balance_seed, capex_rd) is
    canonicalized via _sync_capex_balance_aliases so the two contract-valid
    keys (balance_sheet, capex_rd) carry one identical payload and the
    v1-legacy capex_rd_balance_seed key is never persisted — satisfying the
    F5 plan_state_alias_sync invariant (which requires balance_sheet ==
    capex_rd, enforced in to_dict's Contract-7 gate).
    """
    if not isinstance(self.plan_state, dict):
      self.plan_state = {}
    stored = copy.deepcopy(payload) if payload is not None else {}
    if section in _ALIAS_ANY:
      _sync_capex_balance_aliases(self.plan_state, prefer=stored)
    else:
      self.plan_state[section] = stored

  def to_dict(self) -> Dict[str, Any]:
    # P3.40 Cleanup 3/6 -- R10 + R11 dropped sequence_position,
    # recent_decisions, budget keys from the serialized payload.
    payload = {
      "invariants": dict(self.invariants),
      "authority": self.authority,
      "business_facts": copy.deepcopy(self.business_facts),
      "plan_state": copy.deepcopy(self.plan_state),
      "bands": copy.deepcopy(self.bands),
      "validation_state": copy.deepcopy(self.validation_state),
    }
    # P3.40 Contract 7 Commit 3 -- Shape A consumer-side gate. Per
    # spec §5.2.1: the canonical Mirror serialization point. Gate
    # fires at every serialization to catch in-process mutation
    # that violated invariants (F5 alias-sync, F6 i-iv).
    #
    # Normalize empty-dict validation_state to None so the
    # dataclass default round-trips through MirrorContract whose
    # Optional[ValidationStateProjectionContract] field types the
    # pre-populate state as None (matches the production semantic
    # where consumers check ``vs = ... or {}``). The gate
    # validates a normalized copy; the original payload returned
    # to the caller is untouched so existing consumers still see
    # the {} default.
    try:
      from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore  # noqa: E501
        SIDE_CONSUMER as _AS_SIDE_CONSUMER,
        validate_amalgamated_session_at_boundary,
      )
      gate_payload = dict(payload)
      if not gate_payload.get("validation_state"):
        gate_payload["validation_state"] = None
      validate_amalgamated_session_at_boundary(
        gate_payload, side=_AS_SIDE_CONSUMER,
      )
    except ImportError:
      pass  # contract module absent (e.g. partial install) -- skip
    return payload


# The operating_model_json fields that tell the executive WHAT this business
# is and HOW it makes money -- the portrait it needs to judge revenue-lever
# (price/utilization/capacity) choices sensibly for THIS business instead of
# blindly. Kept compact (token-aware); long free-text is capped.
_OM_DIGEST_FIELDS = (
  "business_type", "consumer_type", "business_stage",
  "unit_name", "unit_description", "unit_cadence",
  "unit_price", "units_per_week_capacity", "units_per_period_capacity",
  "utilization_rate", "operating_periods_per_year",
  "capacity_driver", "primary_growth_lever",
  "sales_modality", "shipping_method",
  "geographic_scope", "geographic_coverage",
  "business_description_summary", "competitive_advantage",
)
_OM_DIGEST_TEXT_CAP = 400
_COMPACT_PEOPLE_CAP = 6   # key people surfaced
_COMPACT_SEGMENTS_CAP = 8


def _cap_text(value: Any, cap: int = _OM_DIGEST_TEXT_CAP) -> Any:
  if isinstance(value, str) and len(value) > cap:
    return value[:cap].rstrip() + "…"
  return value


def _build_team_slice(people_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  """Compact people/team slice: who runs the business + planned year-1 roles.
  Grounds GPT's revenue/capacity authoring in who actually delivers the work."""
  if not isinstance(people_json, dict):
    return {}
  slice_: Dict[str, Any] = {}
  people = people_json.get("people")
  if isinstance(people, list) and people:
    key_people = []
    for p in people[:_COMPACT_PEOPLE_CAP]:
      if not isinstance(p, dict):
        continue
      entry = {
        k: _cap_text(p.get(k), 200)
        for k in ("full_name", "role_title", "primary_responsibilities")
        if p.get(k)
      }
      if entry:
        key_people.append(entry)
    if key_people:
      slice_["key_people"] = key_people
  roles_summary = people_json.get("inferred_roles_summary")
  if roles_summary:
    slice_["planned_roles_summary"] = _cap_text(roles_summary)
  roles = people_json.get("inferred_roles")
  if isinstance(roles, list) and roles:
    slice_["planned_roles"] = [
      {k: r.get(k) for k in ("role_title", "annual_wage", "months_until_hire") if r.get(k) is not None}
      for r in roles[:_COMPACT_PEOPLE_CAP] if isinstance(r, dict)
    ]
  return slice_


def _build_target_market_slice(target_market_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  """Compact target-market slice: who the customer is + positioning. Grounds
  GPT's revenue authoring in the demand the business can actually reach."""
  if not isinstance(target_market_json, dict):
    return {}
  tm = target_market_json
  slice_: Dict[str, Any] = {}
  for key in ("consumer_type",):
    if tm.get(key):
      slice_[key] = tm[key]
  if tm.get("marketing_plan_summary"):
    slice_["positioning"] = _cap_text(tm["marketing_plan_summary"])
  if tm.get("gender_age_intent"):
    slice_["audience_demographics"] = tm["gender_age_intent"]
  if tm.get("income_intent"):
    slice_["audience_income"] = tm["income_intent"]
  selections = tm.get("selections")
  if isinstance(selections, list) and selections:
    segs = [s.get("segment") for s in selections[:_COMPACT_SEGMENTS_CAP]
            if isinstance(s, dict) and s.get("segment")]
    if segs:
      slice_["segments"] = segs
  # B2B fields (present + non-null only for B2B businesses).
  for key in ("b2b_industry_terms", "b2b_naics_6", "b2b_size_bands"):
    if tm.get(key):
      slice_[key] = tm[key]
  return slice_


# marketing_model_json carries the DEMAND-SIZING the business was scoped
# against — how big the reachable market is, how many units/customers it
# implies, and the revenue that demand supports. This is the single most
# valuable grounding for revenue authoring: it tells GPT what top line the
# market can actually bear, so authored price x volume stays believable.
_MARKET_DEMAND_FIELDS = (
  "reachable_market", "reachable_market_b2c", "reachable_market_b2b",
  "expected_units_year1", "required_units_year1",
  "expected_customers_or_clients_year1",
  "capture_rate_year1", "marketing_intensity",
  "demand_supports_required_units",
  "required_revenue_year1",
  "marketing_basis_summary",
  "geography_basis",
)


# HOW TO READ THE MARKET DATA — the comprehension layer for every GPT
# decision that reasons about growth, pricing, or market. The intake codes
# carry deep market meaning (b2b vs b2c dynamics, income -> pricing power,
# reachable market -> growth ceiling), but a bare token teaches nothing:
# handed "consumer_type: business" with no semantics, the judgment falls
# back to generic curves. This primer travels WITH the market slices into
# the prompts that need them (revenue growth, lever ceilings, cost
# maturation). Concise by design (~150 tokens) — meaning, not a data dump.
MARKET_SEMANTICS_PRIMER = (
  "HOW TO READ THE MARKET DATA:\n"
  "- consumer_type 'consumer' (B2C) = many small customers; growth comes "
  "from reach, foot traffic, and repeat purchase; pricing power is bounded "
  "by the audience income band. 'business' (B2B) = fewer, larger accounts "
  "won through relationships and longer sales cycles; growth is lumpier "
  "and account-based (a handful of wins or losses moves the year); pricing "
  "follows value delivered per account, not consumer incomes.\n"
  "- audience_income is the customer base's household income range — it "
  "BOUNDS pricing power (a $40-90k audience cannot absorb luxury pricing; "
  "a high-income base can).\n"
  "- reachable_market is how many people/accounts the business can "
  "realistically address — the CEILING all growth must respect. "
  "capture_rate is the share of that market the plan ALREADY assumes "
  "captured; a high rate leaves little headroom to grow by share, so "
  "further growth must come from price, frequency, or expanding reach.\n"
  "- marketing_basis_summary, audience_demographics, and segments DEFINE "
  "who the actual customer base is — reason from them, not from the "
  "industry label."
)


def _build_market_demand_slice(marketing_model_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  """Compact demand-sizing slice from marketing_model_json — reachable market,
  implied units/customers, and the revenue that demand supports. Grounds the
  authored top line in what the market can actually bear."""
  if not isinstance(marketing_model_json, dict):
    return {}
  slice_: Dict[str, Any] = {}
  for key in _MARKET_DEMAND_FIELDS:
    value = marketing_model_json.get(key)
    if value is None or value == "":
      continue
    slice_[key] = _cap_text(value) if isinstance(value, str) else value
  return slice_


_COMPACT_LOB_CAP = 12  # distinct revenue lines surfaced (token-aware)


def _build_lines_of_business_slice(ops_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  """Per-LOB revenue drivers from ops_json.lob_models[].products[].

  Revenue authoring is PER LINE OF BUSINESS: a multi-LOB business (e.g. a law
  firm with Corporate at one price and Individual at another) must be authored
  with each line's DISTINCT price / capacity / utilization — never collapsed
  into a single top-level blended line (the top-level unit_price is None for
  multi-LOB, so authoring from the top would lose every line). One entry per
  (lob, product); single-LOB businesses yield exactly one entry."""
  if not isinstance(ops_json, dict):
    return []
  lob_models = ops_json.get("lob_models")
  if not isinstance(lob_models, list):
    return []
  lines: List[Dict[str, Any]] = []
  for lob in lob_models:
    if not isinstance(lob, dict):
      continue
    lob_name = lob.get("lob_name")
    for product in (lob.get("products") or []):
      if not isinstance(product, dict):
        continue
      entry: Dict[str, Any] = {}
      if lob_name:
        entry["lob"] = lob_name
      if product.get("product_name"):
        entry["unit"] = product["product_name"]
      for src, dst in (
        ("unit_price", "unit_price"),
        ("units_per_period_capacity", "capacity_units_per_period"),
        ("utilization_rate", "utilization_rate"),
      ):
        if product.get(src) is not None:
          entry[dst] = product[src]
      if entry:
        lines.append(entry)
      if len(lines) >= _COMPACT_LOB_CAP:
        return lines
  return lines


def build_operating_model_digest(
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """THE enriched business compact for the Mirror — ONE digest reused for both
  revenue authoring and the executive's cascade judging.

  Carries the operating-model portrait (what it sells, how it prices, how
  capacity is driven), PLUS compact slices of the team (people_json) and the
  target market (target_market_json). This is GPT's full view of business
  reality and, per the revenue-authoring design, the GUARDRAIL: with ops +
  people + market in view, GPT authors revenue drivers grounded in what the
  business can actually do. A digest, not the raw blobs: long text capped."""
  digest: Dict[str, Any] = {}
  if isinstance(ops_json, dict):
    for key in _OM_DIGEST_FIELDS:
      value = ops_json.get(key)
      if value is None or value == "":
        continue
      digest[key] = _cap_text(value)
  team = _build_team_slice(people_json)
  if team:
    digest["team"] = team
  target_market = _build_target_market_slice(target_market_json)
  if target_market:
    digest["target_market"] = target_market
  market_demand = _build_market_demand_slice(marketing_model_json)
  if market_demand:
    digest["market_demand"] = market_demand
  lines_of_business = _build_lines_of_business_slice(ops_json)
  if lines_of_business:
    digest["lines_of_business"] = lines_of_business
  return digest


def build_mirror(
  conn=None,
  *,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  plan_state: Optional[Dict[str, Any]] = None,
  validation_state: Optional[Dict[str, Any]] = None,
  load_bands: bool = True,
) -> Mirror:
  """Build a fresh Mirror. Bands are loaded from
  ``post_intake_cohort_bands`` (Phase 3 step 1) when ``conn``,
  ``draft_id``, and ``planning_run_id`` are all provided.

  Sections without committed plan_state or bands appear as empty dicts —
  GPT sees the shape and can tell what is missing vs what is present.

  P3.40 Cleanup 3/6 -- R10 + R11 dropped the
  ``sequence_position``, ``budget``, and ``recent_decisions_cap``
  kwargs (all phantom-required per v2 §D-3 reader/writer audit:
  zero callers passed them; always defaulted to empty values
  with no downstream consumer).
  """
  bands_payload: Dict[str, Any] = {section: {} for section in SECTIONS}
  _bands_load_error: Optional[str] = None
  if load_bands and conn is not None and draft_id and planning_run_id:
    try:
      from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (  # type: ignore
        get_bands,
      )
      for section in SECTIONS:
        bands_payload[section] = get_bands(
          conn, draft_id=draft_id, planning_run_id=planning_run_id, section=section
        )
    except Exception as _bands_exc:
      # The fail-fast below must name the REAL cause: one section's read
      # exception used to surface as "bands unresolved across all 5
      # sections", which reads as populator-never-ran when rows exist
      # (Ironwood: a contract-vocabulary rejection on one row erased
      # every section's diagnosis).
      _bands_load_error = f"{type(_bands_exc).__name__}: {str(_bands_exc)[:300]}"
      # C3 — record the swallowed exception so the silent fallback to
      # empty bands carries its cause forward. The downstream
      # FAIL_MIRROR_BANDS_UNRESOLVED guard catches the consequence
      # (empty bands); this preserves the underlying DB / lookup
      # exception in diagnostics.
      try:
        from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
          EventCode as _C3EventCode, PhaseCode as _C3PhaseCode,
          Status as _C3Status, safe_emit as _c3_safe_emit,
        )
        _c3_safe_emit(
          conn,
          draft_id=str(draft_id or ""),
          planning_run_id=str(planning_run_id or ""),
          phase=_C3PhaseCode.MIRROR_BUILD,
          event_code=_C3EventCode.MIRROR_BANDS_LOAD_FAILED,
          status=_C3Status.FAILED,
          diagnostic_data={
            "exception_type": type(_bands_exc).__name__,
            "detail": str(_bands_exc)[:480],
          },
        )
      except Exception:
        pass  # observability never breaks the pipeline

  entry_plan_state = {section: dict((plan_state or {}).get(section) or {}) for section in SECTIONS}
  # Bug 2 — the session-entry snapshot copies balance_sheet and capex_rd
  # independently, so an upstream alias divergence (one populated, the other
  # empty/different) would trip the F5 plan_state_alias_sync gate at the
  # INDUSTRY_BASELINE->AMALGAMATED_SESSION boundary. Canonicalize the alias
  # triplet here so the entry mirror is F5-consistent, matching the post-commit
  # sync in set_plan_state_section.
  _sync_capex_balance_aliases(entry_plan_state)
  # Carry the operating_model digest in business_facts (opaque Dict[str,Any]
  # in MirrorContract, so contract-safe) so the executive sees the business
  # portrait when judging revenue-lever proposals.
  _business_facts = dict(business_facts or {})
  _om_digest = build_operating_model_digest(
    ops_json, people_json, target_market_json, marketing_model_json,
  )
  if _om_digest:
    _business_facts["operating_model_digest"] = _om_digest
  mirror = Mirror(
    invariants=dict(_INVARIANTS),
    authority=_AUTHORITY,
    business_facts=_business_facts,
    plan_state=entry_plan_state,
    bands=bands_payload,
    validation_state=dict(validation_state or {}),
  )
  # Step 9b-ii — emit MIRROR_BUILD_STARTED + COMPLETED (or NO_BANDS
  # when bands are empty across all sections). draft_id / planning_run_
  # id are optional on build_mirror; skip the emit when they're absent.
  if conn is not None and draft_id and planning_run_id:
    try:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        EventCode, PhaseCode, Status, safe_emit,
      )
      sections_populated = sum(
        1 for s in SECTIONS if mirror.plan_state.get(s)
      )
      bands_loaded = sum(
        1 for s in SECTIONS
        if isinstance(mirror.bands.get(s), dict) and mirror.bands.get(s)
      )
      safe_emit(
        conn, draft_id=draft_id, planning_run_id=planning_run_id,
        phase=PhaseCode.MIRROR_BUILD,
        event_code=(
          EventCode.MIRROR_BUILD_NO_BANDS if bands_loaded == 0
          else EventCode.MIRROR_BUILD_COMPLETED
        ),
        status=Status.COMPLETED,
        diagnostic_data={
          "sections_populated": sections_populated,
          "bands_loaded": bands_loaded,
          "section_total": len(SECTIONS),
        },
      )
    except Exception:
      pass
  # Step 9d items 3 + 4 — mirror_build fail-fast guards.
  # Item 3: plan_state must be a dict (per-section dicts will be
  # validated by their consumers). Item 4: when conn + IDs are present
  # so bands were expected, bands_loaded must be > 0; an empty bands
  # payload means cohort_bands_populator ran without writing anything,
  # which the populator's own item-1 guard should have caught upstream.
  if not isinstance(mirror.plan_state, dict):
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode, PhaseCode as _PC, raise_fail_fast,
    )
    raise_fail_fast(
      conn, draft_id=str(draft_id or ""), planning_run_id=str(planning_run_id or ""),
      phase=_PC.MIRROR_BUILD,
      code=FailFastCode.FAIL_MIRROR_PLAN_STATE_NOT_DICT,
      detail=f"mirror.plan_state is {type(mirror.plan_state).__name__}, expected dict",
      where="post_intake_amalgamated.mirror.build_mirror",
    )
  if conn is not None and draft_id and planning_run_id:
    _bands_loaded = sum(
      1 for s in SECTIONS
      if isinstance(mirror.bands.get(s), dict) and mirror.bands.get(s)
    )
    if _bands_loaded == 0:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        FailFastCode, PhaseCode as _PC, raise_fail_fast,
      )
      raise_fail_fast(
        conn, draft_id=str(draft_id), planning_run_id=str(planning_run_id),
        phase=_PC.MIRROR_BUILD,
        code=FailFastCode.FAIL_MIRROR_BANDS_UNRESOLVED,
        detail=(
          f"bands load failed: {_bands_load_error}"
          if _bands_load_error
          else (
            f"bands unresolved across all {len(SECTIONS)} sections; "
            f"cohort_bands populator must run before mirror_build"
          )
        ),
        where="post_intake_amalgamated.mirror.build_mirror",
      )
  # P3.40 Contract 7 Commit 3 -- producer-side gate per spec §5.1.
  # Fires only when conn + draft_id + planning_run_id are supplied
  # (production path; bypassed for test stubs that build a partial
  # Mirror without DB context). F14 dataclass-to-dict via
  # ``dataclasses.asdict(mirror)``.
  if conn is not None and draft_id and planning_run_id:
    try:
      from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore  # noqa: E501
        SIDE_PRODUCER as _AS_SIDE_PRODUCER,
        validate_amalgamated_session_at_boundary,
      )
      gate_payload = asdict(mirror)
      # P3.40 Cleanup 3/6 -- R10 + R11 dropped sequence_position
      # / recent_decisions / budget / recent_decisions_cap from
      # Mirror, so no normalization needed for those fields here.
      # Normalize empty-dict validation_state to None so the
      # dataclass default round-trips through MirrorContract's
      # Optional[ValidationStateProjectionContract] typing.
      if not gate_payload.get("validation_state"):
        gate_payload["validation_state"] = None
      validate_amalgamated_session_at_boundary(
        gate_payload, side=_AS_SIDE_PRODUCER,
      )
    except ImportError:
      pass  # contract module absent -- skip (best-effort)
  return mirror


def estimate_token_count(mirror_or_payload: Any) -> int:
  """Rough token estimate — chars / 4 over the JSON-serialized mirror.

  Good enough for Q3 (budget/mirror ceiling) sizing decisions without a
  tokenizer dependency. Real-token-count vs this estimate is within
  ~10-15% for English JSON; conservative direction.
  """
  if isinstance(mirror_or_payload, Mirror):
    payload = mirror_or_payload.to_dict()
  else:
    payload = mirror_or_payload
  try:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
  except Exception:
    serialized = str(payload)
  return max(1, len(serialized) // 4)
