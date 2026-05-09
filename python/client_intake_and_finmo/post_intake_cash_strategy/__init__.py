"""Phase 9 Phase F — mode-based cash strategy entry point.

Replaces the Phase 8 minimal cash strategy (Q1 lump-sum dump) at
orchestrator.py with a per-quarter mode-driven funding policy.

Three client-selectable modes per the doctrine and the f949316 baseline:
  preserve_cash      — fund only when buffer breached, prefer non-debt
  balanced           — just-in-time funding, modest distributions when stable
  shareholder_return — protect buffer first, distribute true surplus

Industry-derived parameters (buffer base, interest rate, loan term)
come from post_intake_adaptive_planning.industry_profile.
"""

from client_intake_and_finmo.post_intake_cash_strategy.orchestrator_invocation import (
  CashStrategyResult,
  run_mode_based_cash_strategy,
)

__all__ = ["CashStrategyResult", "run_mode_based_cash_strategy"]
