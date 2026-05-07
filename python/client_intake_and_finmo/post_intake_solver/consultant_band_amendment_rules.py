"""Phase 5.2 — Band-amendment buffer rules.

Three architectural guarantees enforced at the consultant validation
layer (band shaping + conflict adjudication). GPT can narrow bands but
cannot narrow them past a buffer the solver needs to operate within.

  1. Strict min < max — no point bands. The previous invariant was
     ``min ≤ default ≤ max`` which trivially passes for ``[0, 0, 0]``.
     New invariant: ``min < max`` strictly. Point bands are rejected.

  2. Applicability flip restriction — GPT can flip applicable=true →
     applicable=false only when the original (Python-proposer) lever
     entry's provenance.applicability.reason indicates a declared rule
     in the assembler (``per_lever_applicability:*`` or a baseline
     applicability lookup hit). For levers with no rule declared
     (``no_applicability_rule_default_applicable``), GPT can tighten
     the band but cannot zero it via the applicability flag.

  3. Width buffer — for amendments that don't flip applicability, the
     resulting band width must be at least the larger of:
       a. 25% of the Python proposer's default band width
       b. A per-lever-type absolute minimum (per ``value_kind``).

Each violation raises ``post_intake_fail_fast_raise`` with a structured
diagnostic identifying the lever, the rule that fired, and the relevant
proposed/original values. The orchestrator catches these and forwards
them to the adaptation cascade (Tier 1 walk-back).
"""

from __future__ import annotations

from typing import Any, Dict, Optional


_PHASE_3_PHASE_KEY = "phase_3_gpt"

_PYTHON_DEFAULT_WIDTH_RETENTION_FRACTION = 0.25

# Per-value_kind absolute minimum band width. Picked to match the
# spec's examples: 2 pp for percent-of-revenue ratios, 5 days for
# days-based levers, 0.05 for unit ratios.
_ABSOLUTE_MIN_WIDTH_BY_VALUE_KIND: Dict[str, float] = {
  "percent_of_revenue": 0.02,
  "ratio_to_revenue": 0.02,
  "ratio": 0.05,
  "days": 5.0,
  "day_count": 5.0,
}

_APPLICABILITY_REASON_NO_RULE = "no_applicability_rule_default_applicable"


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _ff_raise(code: str, message: str, *, details: Dict[str, Any]) -> None:
  from client_intake_and_finmo.fail_fast.post_intake_fail_fast.fail_fast import (  # type: ignore
    post_intake_fail_fast_raise,
  )
  from client_intake_and_finmo.fail_fast.common import FailFastError  # type: ignore
  result = post_intake_fail_fast_raise(
    code, message, stage=_PHASE_3_PHASE_KEY, details=details,
  )
  raise FailFastError(
    code, message,
    phase=result.get("phase") or "POST_INTAKE",
    stage=_PHASE_3_PHASE_KEY,
    details=details,
  )


def _absolute_min_width(value_kind: str) -> float:
  kind = _clean_text(value_kind).lower()
  return float(_ABSOLUTE_MIN_WIDTH_BY_VALUE_KIND.get(kind, 0.0))


def _python_proposer_band_width(original_entry: Dict[str, Any]) -> Optional[float]:
  mn = _safe_float(original_entry.get("min_allowed"))
  mx = _safe_float(original_entry.get("max_allowed"))
  if mn is None or mx is None:
    return None
  return max(0.0, float(mx) - float(mn))


def validate_band_amendment(
  *,
  lever_id: str,
  original_entry: Dict[str, Any],
  proposed_applicable: bool,
  proposed_min: Optional[float],
  proposed_max: Optional[float],
  proposed_default: Optional[float],
) -> None:
  """Apply the three buffer mechanics to one lever amendment.

  Raises FailFastError on any violation. Caller (the consultant) then
  walks the affected lever back to the Python default via the cascade
  Tier 1 path. ``original_entry`` is the Python-proposer envelope row
  before any GPT amendment.

  Args:
    lever_id: which lever this amendment targets.
    original_entry: the Python proposer's envelope entry (before GPT).
    proposed_applicable / min / max / default: GPT's proposed values.
  """
  lever = _clean_text(lever_id)
  original = original_entry if isinstance(original_entry, dict) else {}
  original_applicable = bool(original.get("applicable", True))
  applicability_meta = (
    original.get("provenance", {}) if isinstance(original.get("provenance"), dict) else {}
  )
  applicability = applicability_meta.get("applicability") or {}
  applicability_reason = _clean_text(applicability.get("reason")).lower()

  # Mechanic 2: applicability flip restriction
  if original_applicable and not bool(proposed_applicable):
    if applicability_reason == _APPLICABILITY_REASON_NO_RULE:
      _ff_raise(
        "band_amendment_invalid_applicability_flip",
        f"GPT proposed applicable=false for {lever!r} but no applicability "
        f"rule is declared (provenance.applicability.reason="
        f"{applicability_reason!r}); flips require a declared rule",
        details={
          "lever_id": lever,
          "proposed_applicable": False,
          "original_applicable": True,
          "applicability_reason": applicability_reason,
        },
      )
    return  # legal flip; no band-width checks needed (band is point-zero by design)

  # Mechanic 1: strict min < max for the proposed band.
  mn = _safe_float(proposed_min)
  mx = _safe_float(proposed_max)
  if mn is None or mx is None:
    return  # nothing proposed for those fields; existing values remain
  if mx <= mn:
    _ff_raise(
      "band_amendment_invalid_point_band",
      f"GPT proposed point band for {lever!r}: min={mn} >= max={mx}",
      details={
        "lever_id": lever, "proposed_min": mn, "proposed_max": mx,
        "proposed_default": _safe_float(proposed_default),
      },
    )

  proposed_width = float(mx) - float(mn)

  # Mechanic 3: width buffer.
  py_width = _python_proposer_band_width(original)
  retention_floor = (
    float(py_width) * _PYTHON_DEFAULT_WIDTH_RETENTION_FRACTION
    if py_width is not None and py_width > 0
    else 0.0
  )
  absolute_floor = _absolute_min_width(_clean_text(original.get("value_kind")))
  required_width = max(retention_floor, absolute_floor)
  if required_width > 0 and proposed_width < required_width:
    _ff_raise(
      "band_amendment_violates_width_buffer",
      f"GPT proposed band width={proposed_width:.6f} for {lever!r} "
      f"is below required minimum={required_width:.6f} "
      f"(retention_floor={retention_floor:.6f}, absolute_floor={absolute_floor:.6f})",
      details={
        "lever_id": lever,
        "proposed_min": mn, "proposed_max": mx,
        "proposed_width": proposed_width,
        "python_default_width": py_width,
        "retention_floor": retention_floor,
        "absolute_floor": absolute_floor,
        "required_width": required_width,
        "value_kind": _clean_text(original.get("value_kind")),
      },
    )
