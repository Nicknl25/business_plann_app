"""Calibration knobs for the viability standard (Fix #1 spec §7).

These are the CONFIGURABLE defaults — stage weights, level/trajectory
splits, the pass/refine threshold, convergence targets, posture relaxation.
They are documented defaults, NOT magic numbers buried in scoring logic
(§7): grade.py / standard.py read them from here so calibration is a
one-file change. Exposed via get_policy() so a future SQL/file-backed
override can swap the source without touching the scorers.

Locked vs tunable (per §7):
  - Stage-weight DIRECTION and the level/trajectory split values: locked.
  - Exact stage-weight multipliers and the pass/refine threshold: tunable
    (calibrate against known-good / known-bad plans).
"""

from __future__ import annotations

import copy
from typing import Any, Dict


# The four graded constructs (Construct 5 / breakeven-timing are Tier-2 gates).
GRADED_CONSTRUCTS = ("operating_cash_proxy", "rule_of_40", "nwc_intensity", "ebitda_ramp")


# Stage -> per-construct weight. Direction locked (§4.2): startup/early tilt to
# growth + path-to-margin (rule_of_40, ebitda_ramp); mature tilts to level
# (operating_cash_proxy, nwc_intensity); operational balanced. Moderate tilt —
# lead ~1.5-2x the others (multipliers tunable, §7.1).
STAGE_WEIGHTS: Dict[str, Dict[str, float]] = {
  "startup": {"rule_of_40": 2.0, "ebitda_ramp": 1.5, "operating_cash_proxy": 1.0, "nwc_intensity": 1.0},
  "early": {"rule_of_40": 1.8, "ebitda_ramp": 1.5, "operating_cash_proxy": 1.2, "nwc_intensity": 1.0},
  "operational": {"operating_cash_proxy": 1.5, "nwc_intensity": 1.2, "rule_of_40": 1.2, "ebitda_ramp": 1.0},
  "mature": {"operating_cash_proxy": 2.0, "nwc_intensity": 1.5, "rule_of_40": 1.0, "ebitda_ramp": 1.0},
}

# Stage -> (level_weight, trajectory_weight) within each construct (locked §7.6).
STAGE_LEVEL_TRAJECTORY_SPLIT: Dict[str, tuple] = {
  "startup": (0.30, 0.70),
  "early": (0.40, 0.60),
  "operational": (0.55, 0.45),
  "mature": (0.65, 0.35),
}

# Trajectory = gap-closure (primary) + OLS slope momentum (secondary), §7.4.
TRAJECTORY_GAP_WEIGHT = 0.70
TRAJECTORY_SLOPE_WEIGHT = 0.30

# Convergence targets in HEALTH-percentile space (§7.2): clearing p25 is the
# floor; p50 earns full credit.
CLEAR_HEALTH = 0.25          # p25-clear
FULL_CREDIT_HEALTH = 0.50    # p50-full-credit

# Verdict threshold on the overall Tier-1 score in [0,1] (§7.7). Gates already
# own viability; this only splits pass vs refine. Tunable.
PASS_REFINE_THRESHOLD = 0.55

# Posture (§4.3, §8): a genuine turnaround relaxes the Tier-1 convergence bar.
# Lower the effective convergence target by this much (health-percentile),
# floored at the clear bar.
DISTRESS_CONVERGENCE_RELAX = 0.15


def get_policy() -> Dict[str, Any]:
  """Return a deep copy of the calibration policy (single source of truth)."""
  return copy.deepcopy({
    "graded_constructs": list(GRADED_CONSTRUCTS),
    "stage_weights": STAGE_WEIGHTS,
    "stage_level_trajectory_split": {k: list(v) for k, v in STAGE_LEVEL_TRAJECTORY_SPLIT.items()},
    "trajectory_gap_weight": TRAJECTORY_GAP_WEIGHT,
    "trajectory_slope_weight": TRAJECTORY_SLOPE_WEIGHT,
    "clear_health": CLEAR_HEALTH,
    "full_credit_health": FULL_CREDIT_HEALTH,
    "pass_refine_threshold": PASS_REFINE_THRESHOLD,
    "distress_convergence_relax": DISTRESS_CONVERGENCE_RELAX,
  })
