"""NAICS-keyed industry baseline resolver.

Public surface used by post-intake silent-zero substitution sites and the
finalize realism gate. The resolver walks the documented coverage cascade
(NAICS-6 -> 5 -> 4 -> 3 -> 2 -> 0 -> no_coverage) over
`post_intake_industry_baseline_lookup` and stamps trust + provenance on every
returned payload.
"""

from .lookup import (
  PostIntakeIndustryBaselineNoCoverage,
  baseline_seed_provenance,
  post_intake_baseline_applicability_for_naics2,
  post_intake_industry_baseline_for_naics,
  post_intake_industry_metric_governs_lever,
  post_intake_industry_metric_registry_row,
)

__all__ = [
  "PostIntakeIndustryBaselineNoCoverage",
  "baseline_seed_provenance",
  "post_intake_baseline_applicability_for_naics2",
  "post_intake_industry_baseline_for_naics",
  "post_intake_industry_metric_governs_lever",
  "post_intake_industry_metric_registry_row",
]
