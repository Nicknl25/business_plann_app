"""Post-intake realism gate (Module 3).

Public surface:
  - `post_intake_finalize_realism_check_rows` — load the realism check lookup
  - `post_intake_finalize_realism_check_for_metric` — single-row lookup
  - `RealismFormulaNotRegistered` — raised when a row references an unknown formula key
  - `validate_industry_realism_bands` — the finalize-stage validator

The realism gate compares produced FINMO ratios against the NAICS-typical
band per metric. Out-of-band values fail-fast (when `gate_kind = "hard_fail"`)
or surface as warnings (`gate_kind = "warn"`). The gate never rewrites
drivers or statements — it surfaces the upstream input that's wrong.
"""

from .lookup import (
  REALISM_CHECK_TABLE_NAME,
  post_intake_finalize_realism_check_for_metric,
  post_intake_finalize_realism_check_rows,
)
from .formulas import (
  RealismFormulaNotRegistered,
  evaluate_realism_formula,
  registered_realism_formula_keys,
)
from .validator import (
  RealismBandViolation,
  RealismCheckResult,
  validate_industry_realism_bands,
)
from .schedule_sanity import validate_schedule_sanity

__all__ = [
  "REALISM_CHECK_TABLE_NAME",
  "RealismBandViolation",
  "RealismCheckResult",
  "RealismFormulaNotRegistered",
  "evaluate_realism_formula",
  "post_intake_finalize_realism_check_for_metric",
  "post_intake_finalize_realism_check_rows",
  "registered_realism_formula_keys",
  "validate_industry_realism_bands",
  "validate_schedule_sanity",
]
