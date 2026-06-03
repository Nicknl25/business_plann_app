"""Age-derived lifecycle stage (Fix #1 spec §4.1).

Stage is derived from BUSINESS AGE — not the nullable `business_stage`
intake field. Age is the elapsed time since `business_start_date`, which
the codebase already computes as `business_age_months_at_run`
(quarter_grid.py:891 via `_whole_months_between` quarter_grid.py:849-853).

Taxonomy (the 4-stage floors taxonomy, locked §4.1):
  startup      < 12 months   (age_q < 4)
  early        12 – <36 mo    (4 <= age_q < 12)
  operational  36 – <84 mo    (12 <= age_q < 28)
  mature       >= 84 mo       (age_q >= 28)

A future-dated start (start > as-of) maps to startup (pre-revenue).

NOTE (build §4.1): this is a SELF-CONTAINED derivation for the viability
standard. It deliberately does NOT reuse / mutate quarter_grid._stage_family
(which emits only startup/early/operational and never mature). Fixing that
helper in place is risky — its sole consumer compares its output against the
GPT-authored stage_ramp_contract.stage_family and raises
`quarter_grid_stage_ramp_contract_mismatch` on mismatch
(quarter_grid.py:897-911), and "mature" would also flow into ramp/contract
floor paths that branch on "operational". That fix is a separate,
quarter-grid-scoped change; the viability standard does not depend on it.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Tuple


# Stage label constants — the 4-stage floors taxonomy.
STARTUP = "startup"
EARLY = "early"
OPERATIONAL = "operational"
MATURE = "mature"

#: Age bands in MONTHS, as (max_exclusive_months, stage). Structural (locked
#: §4.1), not a calibration knob. The final band has no upper bound.
STAGE_AGE_BANDS: Tuple[Tuple[Optional[int], str], ...] = (
  (12, STARTUP),       # < 12 months
  (36, EARLY),         # 12 - <36 months
  (84, OPERATIONAL),   # 36 - <84 months
  (None, MATURE),      # >= 84 months
)


def _whole_months_between(start: date, end: date) -> int:
  """Whole months elapsed from `start` to `end`.

  Mirrors quarter_grid._whole_months_between (quarter_grid.py:849-853) so
  the standard's age computation matches `business_age_months_at_run`
  exactly. Kept dependency-free (date arithmetic only).
  """
  months = (end.year - start.year) * 12 + (end.month - start.month)
  if end.day < start.day:
    months -= 1
  return int(months)


def business_age_months(start_date: Optional[date], as_of: Optional[date]) -> Optional[int]:
  """Business age in whole months at `as_of`. None when start_date is missing.

  A future-dated start yields a negative value (handled by derive_stage as
  pre-revenue → startup). Prefer passing the already-computed
  `business_age_months_at_run` to derive_stage directly; this helper is for
  call sites that only hold the raw dates.
  """
  if start_date is None or as_of is None:
    return None
  return _whole_months_between(start_date, as_of)


def business_age_quarters(age_months: Optional[int]) -> Optional[int]:
  """Business age in whole quarters (age_months // 3). None when unknown.

  A future-dated start (negative months) clamps to 0 quarters.
  """
  if age_months is None:
    return None
  return max(0, int(age_months) // 3)


def derive_stage(age_months: Optional[int]) -> Optional[str]:
  """Map business age (months) to a 4-stage label, or None when age is unknown.

  Returns startup for a future-dated start (age_months < 0 → pre-revenue).
  None propagates so the caller can decide a default rather than silently
  picking one (no silent degradation, per build guardrails).
  """
  if age_months is None:
    return None
  if age_months < 12:  # includes negative (future-dated / pre-revenue)
    return STARTUP
  for upper, stage in STAGE_AGE_BANDS:
    if upper is None or age_months < upper:
      return stage
  return MATURE
