"""Viability standard orchestrator → verdict (Fix #1 spec §3, §7, §8).

Ties the units together into one judgement:
  age (§4.1) -> stage + business_age_quarters
  bands (§5) -> resolve_viability_bands for the age-derived stage's cohort
  gates (§3) -> Tier 2 A/B (own viability; +4q / bar-relax under posture §4.3/§8)
  grade (§6) -> Tier 1 competitiveness, age-anchored convergence deadline
  verdict (§7) -> gates own non-viability; Tier 1 maps to pass / refine ONLY.

Verdict values:
  "non_viable" — a Tier-2 gate failed (gates own viability). Grade still
                 computed for the refine/diagnostic signal.
  "pass"       — gates clear AND Tier-1 overall >= pass/refine threshold.
  "refine"     — gates clear but Tier-1 weak (or ungraded for lack of cohort
                 bands — surfaced via notes, never silently passed).

POSTURE (§8): `explicit_distress_context` (the retained planning_mode posture
signal) loosens Gate A (+4q) and the Tier-1 convergence bar; Gate B stays firm.
This module does NOT read planning_mode itself — the caller passes the flag
(wiring is Unit 9), keeping the standard decoupled from mode selection.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from . import policy as _policy
from .cohort_bands import resolve_viability_bands
from .gates import evaluate_gates, gate_a_deadline_plan_quarter
from .grade import grade as _grade
from .stage import business_age_months as _age_months
from .stage import business_age_quarters as _age_quarters
from .stage import derive_stage

VERDICT_PASS = "pass"
VERDICT_REFINE = "refine"
VERDICT_NON_VIABLE = "non_viable"


def evaluate_viability(
  finmo_json: Optional[Dict[str, Any]],
  *,
  business_age_months: Optional[int] = None,
  business_start_date: Optional[date] = None,
  as_of: Optional[date] = None,
  business_profile: Optional[Dict[str, Any]] = None,
  explicit_distress_context: bool = False,
) -> Dict[str, Any]:
  """Judge a plan's economic viability and return a structured verdict.

  Age (months) is taken directly when given, else computed from
  business_start_date + as_of. business_profile supplies {naics_6,
  target_annual_revenue} for cohort resolution (stage is age-derived and
  injected here, NOT read from the nullable business_stage field, §4.1).
  """
  notes = []
  profile = dict(business_profile or {})

  # --- age + stage (§4.1) ---
  age_m = business_age_months
  if age_m is None and business_start_date is not None:
    age_m = _age_months(business_start_date, as_of)
  age_q = _age_quarters(age_m)
  stage = derive_stage(age_m)
  if stage is None:
    # business_start_date is a required intake field; if age is truly
    # unavailable, default to the most-lenient stage rather than silently
    # mis-staging, and record it.
    stage = "startup"
    age_q = age_q if age_q is not None else 0
    notes.append("business_age_unavailable_defaulted_stage_startup")

  distress = bool(explicit_distress_context)

  # --- cohort bands (§5), for the age-derived stage ---
  band_profile = {
    "naics_6": profile.get("naics_6") or profile.get("business_naics_6"),
    "target_annual_revenue": profile.get("target_annual_revenue"),
    "stage": stage,
  }
  try:
    bands = resolve_viability_bands(band_profile) if band_profile["naics_6"] else {}
  except Exception as exc:  # never let band resolution crash the verdict
    bands = {}
    notes.append(f"cohort_bands_unavailable: {type(exc).__name__}")
  if not bands:
    notes.append("cohort_bands_unresolved (naics missing or db unreachable)")

  # --- Tier 2 gates (§3) ---
  gates = evaluate_gates(finmo_json, business_age_quarters=age_q, distress=distress)

  # --- Tier 1 grade (§6) — always computed (refine signal even on gate fail) ---
  deadline_plan_q = gate_a_deadline_plan_quarter(business_age_quarters=age_q, distress=distress)
  grade_result = _grade(finmo_json, bands, stage=stage, deadline_plan_q=deadline_plan_q, distress=distress)
  tier1 = grade_result.get("overall_score")

  # --- verdict (§7): gates own non-viability; Tier 1 -> pass/refine only ---
  threshold = _policy.PASS_REFINE_THRESHOLD
  if not gates["all_pass"]:
    verdict = VERDICT_NON_VIABLE
  elif tier1 is None:
    verdict = VERDICT_REFINE
    notes.append("tier1_ungraded_no_cohort_bands -> refine (viable per gates, grade indeterminate)")
  else:
    verdict = VERDICT_PASS if tier1 >= threshold else VERDICT_REFINE

  return {
    "verdict": verdict,
    "viable": bool(gates["all_pass"]),
    "stage": stage,
    "business_age_months": age_m,
    "business_age_quarters": age_q,
    "distress": distress,
    "tier1_score": tier1,
    "pass_refine_threshold": threshold,
    "gates": gates,
    "grade": grade_result,
    "bands_provenance": {
      col: {
        "available": b.get("available"),
        "naics_level_used": b.get("naics_level_used"),
        "firm_count": b.get("firm_count"),
        "cohort_table": b.get("cohort_table"),
      }
      for col, b in bands.items()
    },
    "notes": notes,
  }
