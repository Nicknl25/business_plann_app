"""Adaptive Operating Doctrine — Phase 9.

Single source of truth for stage profile, planning mode, viability deadlines,
allowed adaptation families, and client-input authority. Every downstream
consumer reads from the AdaptivePolicyContract returned by
compute_adaptive_policy(). Raw planning_mode / business_stage strings are not
to be consulted outside this module's policy output.
"""

from client_intake_and_finmo.post_intake_adaptive_planning.policy import (
  ADAPTATION_FAMILIES,
  ALLOWED_PLANNING_MODES,
  ALLOWED_PRIMARY_OBJECTIVES,
  ALLOWED_STAGE_PROFILES,
  AdaptivePolicyContract,
  compute_adaptive_policy,
)

__all__ = [
  "ADAPTATION_FAMILIES",
  "ALLOWED_PLANNING_MODES",
  "ALLOWED_PRIMARY_OBJECTIVES",
  "ALLOWED_STAGE_PROFILES",
  "AdaptivePolicyContract",
  "compute_adaptive_policy",
]
