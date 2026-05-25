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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # type: ignore
  EvaluatePlanResult,
  SECTIONS,
)


DEFAULT_RECENT_DECISIONS_CAP = 10

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
class RecentDecision:
  """One ring-buffer entry. Summaries only — not full payloads."""
  tool_name: str
  inputs_summary: str
  delta_all_pass: Optional[int] = None          # -1 (regressed), 0 (no change), +1 (now passing)
  delta_worst_distance: Optional[float] = None  # new_worst - old_worst (positive = improved)
  result_summary: str = ""
  at: Optional[str] = None

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class Mirror:
  """The per-decision context handed to GPT."""
  invariants: Dict[str, str] = field(default_factory=dict)
  authority: str = ""
  business_facts: Dict[str, Any] = field(default_factory=dict)
  plan_state: Dict[str, Any] = field(default_factory=dict)
  sequence_position: Dict[str, Any] = field(default_factory=dict)
  bands: Dict[str, Any] = field(default_factory=dict)
  validation_state: Dict[str, Any] = field(default_factory=dict)
  recent_decisions: List[RecentDecision] = field(default_factory=list)
  budget: Dict[str, Any] = field(default_factory=dict)
  recent_decisions_cap: int = DEFAULT_RECENT_DECISIONS_CAP

  def record_decision(
    self,
    *,
    tool_name: str,
    inputs_summary: str,
    delta_all_pass: Optional[int] = None,
    delta_worst_distance: Optional[float] = None,
    result_summary: str = "",
  ) -> None:
    entry = RecentDecision(
      tool_name=tool_name, inputs_summary=inputs_summary,
      delta_all_pass=delta_all_pass, delta_worst_distance=delta_worst_distance,
      result_summary=result_summary,
      at=datetime.now(timezone.utc).isoformat(),
    )
    self.recent_decisions.append(entry)
    if len(self.recent_decisions) > self.recent_decisions_cap:
      self.recent_decisions = self.recent_decisions[-self.recent_decisions_cap:]

  def set_validation_state(self, evaluate_plan_result: EvaluatePlanResult) -> None:
    """Memo §2 requirement: validation_state carries evaluate_plan output
    VERBATIM, not a summary. The step-5 session driver reads this directly."""
    self.validation_state = evaluate_plan_result.to_dict()

  def to_dict(self) -> Dict[str, Any]:
    return {
      "invariants": dict(self.invariants),
      "authority": self.authority,
      "business_facts": copy.deepcopy(self.business_facts),
      "plan_state": copy.deepcopy(self.plan_state),
      "sequence_position": copy.deepcopy(self.sequence_position),
      "bands": copy.deepcopy(self.bands),
      "validation_state": copy.deepcopy(self.validation_state),
      "recent_decisions": [d.to_dict() for d in self.recent_decisions],
      "budget": copy.deepcopy(self.budget),
    }


def build_mirror(
  conn=None,
  *,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  plan_state: Optional[Dict[str, Any]] = None,
  sequence_position: Optional[Dict[str, Any]] = None,
  validation_state: Optional[Dict[str, Any]] = None,
  budget: Optional[Dict[str, Any]] = None,
  recent_decisions_cap: int = DEFAULT_RECENT_DECISIONS_CAP,
  load_bands: bool = True,
) -> Mirror:
  """Build a fresh Mirror. Bands are loaded from
  ``post_intake_cohort_bands`` (Phase 3 step 1) when ``conn``,
  ``draft_id``, and ``planning_run_id`` are all provided.

  Sections without committed plan_state or bands appear as empty dicts —
  GPT sees the shape and can tell what is missing vs what is present.
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
    sequence_position=dict(sequence_position or {}),
    bands=bands_payload,
    validation_state=dict(validation_state or {}),
    budget=dict(budget or {}),
    recent_decisions_cap=int(recent_decisions_cap),
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
