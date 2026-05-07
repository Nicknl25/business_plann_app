"""Post-intake target-seeking solver package.

Phase 2 of the post-intake solver architecture shift. The solver becomes
target-seeking: tweaks drivers within calibrated movement envelopes to land
FINMO outputs (gross profit, gross margin, EBITDA, current ratio, etc.)
inside calibrated target ranges. Drivers are tweaked within envelopes
informed by NAICS bands, applicability tables, schedule constraints, and
stage policy. GPT participates as a consultant (Phase 3) upstream of the
solver to calibrate bands and targets per business; the solver itself
stays deterministic and auditable.

Modules:
  - driver_movement_assembler: per-lever movement envelope (min/max/default)
  - output_target_assembler: per-metric target range (min/target/max)
  - influence_map: ordered driver list per output metric (read-only over
    the existing mapping table)
  - target_seeking_loop: thin wrapper that drives the solver toward the
    output_target_assembler's ranges using the existing numeric_solver
    fitting engine
  - schedule_tweak: schedule-parameter tweak interface for schedule-locked
    drivers (payroll headcount, debt amortization)
  - sanity_assertion: replaces the deleted finalize warning-aggregation
    block. Asserts the solver respected its calibrated targets.
"""

from __future__ import annotations

from client_intake_and_finmo.post_intake_solver.driver_movement_assembler import (  # noqa: F401
  DRIVER_MOVEMENT_ENVELOPE_KEY,
  assemble_driver_movement_envelope,
  default_value_for_lever,
)
from client_intake_and_finmo.post_intake_solver.output_target_assembler import (  # noqa: F401
  FINMO_OUTPUT_TARGET_KEY,
  assemble_finmo_output_targets,
)
from client_intake_and_finmo.post_intake_solver.influence_map import (  # noqa: F401
  driver_influence_map,
)
from client_intake_and_finmo.post_intake_solver.sanity_assertion import (  # noqa: F401
  assert_solver_respected_targets,
)
from client_intake_and_finmo.post_intake_solver.schedule_tweak import (  # noqa: F401
  request_capex_schedule_recompute,
  request_debt_schedule_recompute,
  request_payroll_schedule_recompute,
)
from client_intake_and_finmo.post_intake_solver.target_seeking_loop import (  # noqa: F401
  run_target_seeking_solver,
)
from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: F401
  run_target_seeking_orchestrated_system_run,
)
from client_intake_and_finmo.post_intake_solver.inner_joint_fit_adapter import (  # noqa: F401
  build_inner_joint_fit_adapter,
)
from client_intake_and_finmo.post_intake_solver.consultant_band_shaping import (  # noqa: F401
  calibrate_driver_movement_envelope_with_gpt,
)
from client_intake_and_finmo.post_intake_solver.consultant_target_shaping import (  # noqa: F401
  calibrate_finmo_output_targets_with_gpt,
)
from client_intake_and_finmo.post_intake_solver.consultant_conflict_adjudication import (  # noqa: F401
  adjudicate_intake_vs_band_conflicts_with_gpt,
)
from client_intake_and_finmo.post_intake_solver.cohort_band_resolver import (  # noqa: F401
  CohortBandResult,
  LEVER_TO_METRIC_COLUMN,
  METRIC_KEY_TO_COLUMN,
  clear_cohort_cache,
  cohort_calibration_source_for_confidence,
  compute_band_from_rows,
  map_revenue_to_cap_categories,
  resolve_cohort_band,
)

__all__ = [
  "CohortBandResult",
  "DRIVER_MOVEMENT_ENVELOPE_KEY",
  "FINMO_OUTPUT_TARGET_KEY",
  "LEVER_TO_METRIC_COLUMN",
  "METRIC_KEY_TO_COLUMN",
  "adjudicate_intake_vs_band_conflicts_with_gpt",
  "assemble_driver_movement_envelope",
  "assemble_finmo_output_targets",
  "assert_solver_respected_targets",
  "build_inner_joint_fit_adapter",
  "calibrate_driver_movement_envelope_with_gpt",
  "calibrate_finmo_output_targets_with_gpt",
  "clear_cohort_cache",
  "cohort_calibration_source_for_confidence",
  "compute_band_from_rows",
  "default_value_for_lever",
  "driver_influence_map",
  "map_revenue_to_cap_categories",
  "request_capex_schedule_recompute",
  "request_debt_schedule_recompute",
  "request_payroll_schedule_recompute",
  "resolve_cohort_band",
  "run_target_seeking_orchestrated_system_run",
  "run_target_seeking_solver",
]
