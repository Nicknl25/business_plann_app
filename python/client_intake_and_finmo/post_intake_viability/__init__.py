"""Fix #1 — Viability Standard.

The evaluation that JUDGES a plan's economic viability (the goalposts) and
produces the verdict. Operating-engine-only: EBITDA + operating working
capital + cumulative operating earnings; nothing the funding pass touches.

Spec: docs/architecture/fix_1_viability_standard_spec.md.

This package builds the STANDARD (the judgement). It does NOT build the
adaptation/cascade engine that revises plans toward viability — that is a
separate later build.

Modules (built in dependency order):
  stage      — age-derived 4-stage taxonomy (§4.1)
  constructs — the 5 firm-side operating constructs (§2)
  gates      — Tier 2 absolute gates A/B (§3, §4.1b, §4.3)
  grade      — Tier 1 level+trajectory competitiveness grade (§3, §5)
  policy     — calibration knobs (stage weights, pass/refine threshold) (§7)
  standard   — orchestrator: gates + grade -> verdict (§3)
"""

from __future__ import annotations

from .stage import (  # noqa: F401
  STAGE_AGE_BANDS,
  business_age_months,
  business_age_quarters,
  derive_stage,
)
from .constructs import firm_constructs  # noqa: F401
from .cohort_bands import (  # noqa: F401
  CONSTRUCT_COHORT_REFERENCES,
  VIABILITY_METRIC_DIRECTIONS,
  resolve_viability_bands,
)
from .gates import (  # noqa: F401
  evaluate_gate_a,
  evaluate_gate_b,
  evaluate_gates,
  gate_a_deadline_plan_quarter,
)
