"""Field-basis registry: the ONE source of truth for what unit of time (or
kind of number) each client-stated financials field stores.

Why this exists (Harborline false park, run CW-001): three layers held two
contradictory beliefs about ``owner_compensation``'s basis — the router and
the coherence evaluator treated it as monthly while an apply-layer heuristic
annualized it x12 — so a correct "$10,000 a month" became $120,000/month
($1.44M/yr) and parked a profitable firm. The cure is declarative, not more
heuristics: every layer that needs a field's basis reads it from HERE.

Consumers:
- the intent-router frame (``financials_controller.current_stage.basis`` and
  ``coherence_controller.field_bases``): the router normalizes the client's
  STATED basis to the field's declared basis — convert, never copy. Intent
  inference stays in the router; this module only declares facts.
- stage clarifier texts (the wording must agree with the declared basis).
- coherence option construction (a patch value must equal the displayed
  target expressed in the target field's declared basis).

There must be NO other basis logic anywhere: no apply-layer conversions, no
hardcoded thresholds. A field missing here has basis "amount" (a plain
number with no time dimension) — add it when a time-based field is born.
"""

from __future__ import annotations

from typing import Dict

MONTHLY = "monthly"
ANNUAL = "annual"
QUARTERLY = "quarterly"
COUNT = "count"
RATIO = "ratio"
AMOUNT = "amount"  # plain dollar amount, no time dimension

FIELD_BASIS: Dict[str, str] = {
  # -- monthly-stored fields -------------------------------------------------
  # CW-022 #8: owner pay's client-facing field moved to the people scope
  # (the financials owner_compensation is a derived mirror the router
  # never writes).
  "owner_pay_monthly": MONTHLY,
  # CW-024 #109: the stated team total is ANNUAL by definition.
  "total_team_payroll": ANNUAL,
  "other_operating_expense": MONTHLY,
  "monthly_rent_expense": MONTHLY,
  "other_monthly_debt_payments": MONTHLY,
  # -- annual-stored fields --------------------------------------------------
  "current_revenue": ANNUAL,
  "current_cogs": ANNUAL,
  "cogs_total_year1": ANNUAL,
  "marketing_total_year1": ANNUAL,
  "payroll_total_year1": ANNUAL,
  "current_payroll": ANNUAL,
  "baseline_payroll_year1": ANNUAL,
  "payroll_adjustment": ANNUAL,
  "rest_of_team_payroll_year1": ANNUAL,
  "other_opex_absolute": ANNUAL,
  "annual_interest_payment": ANNUAL,
  "annual_principal_payment": ANNUAL,
  # -- counts / ratios / plain amounts --------------------------------------
  "current_num_employees": COUNT,
  "cogs_percent_of_revenue": RATIO,
  "marketing_percent_of_revenue": RATIO,
  "funding_split_debt_share": RATIO,
  "current_capex": AMOUNT,
  "initial_assets": AMOUNT,
  "initial_lease": MONTHLY,
  "initial_equity": AMOUNT,
  "total_debt_outstanding": AMOUNT,
  "cash_on_hand": AMOUNT,
  "ar_balance": AMOUNT,
  "ap_balance": AMOUNT,
  "inventory_balance": AMOUNT,
}


def basis_of(field: str) -> str:
  """Declared basis for a field (group prefixes like ``financials.`` are
  tolerated). Unknown fields are plain amounts."""
  name = str(field or "").strip()
  if "." in name:
    name = name.rsplit(".", 1)[1]
  return FIELD_BASIS.get(name, AMOUNT)


def basis_phrase(field: str) -> str:
  """Human phrase for prompts/clarifiers: 'per month', 'per year', ..."""
  return {
    MONTHLY: "per month",
    ANNUAL: "per year",
    QUARTERLY: "per quarter",
    COUNT: "a whole-number count",
    RATIO: "a fraction of revenue",
    AMOUNT: "a dollar amount",
  }[basis_of(field)]


def annual_to_field_basis(field: str, annual_value: float) -> float:
  """Convert an annual dollar target into the field's stored basis — used
  by coherence option construction so the machine patch value equals the
  displayed target. Only meaningful for time-based dollar fields."""
  b = basis_of(field)
  v = float(annual_value)
  if b == MONTHLY:
    return v / 12.0
  if b == QUARTERLY:
    return v / 4.0
  return v
