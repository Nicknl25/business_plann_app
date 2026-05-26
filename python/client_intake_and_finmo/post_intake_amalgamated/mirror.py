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
    session-entry snapshot. Aliases are kept in sync — balance_sheet
    and capex_rd_balance_seed mirror each other (the read-side closure
    at session_factory._build_current_payload_for treats them as
    aliases), so a write to one also writes the other.
    """
    if not isinstance(self.plan_state, dict):
      self.plan_state = {}
    stored = copy.deepcopy(payload) if payload is not None else {}
    self.plan_state[section] = stored
    if section in ("balance_sheet", "capex_rd_balance_seed", "capex_rd"):
      self.plan_state["balance_sheet"] = stored
      self.plan_state["capex_rd_balance_seed"] = stored

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


def build_mirror(
  conn=None,
  *,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  business_facts: Optional[Dict[str, Any]] = None,
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

  mirror = Mirror(
    invariants=dict(_INVARIANTS),
    authority=_AUTHORITY,
    business_facts=dict(business_facts or {}),
    plan_state={section: dict((plan_state or {}).get(section) or {}) for section in SECTIONS},
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
          f"bands unresolved across all {len(SECTIONS)} sections; "
          f"cohort_bands populator must run before mirror_build"
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
