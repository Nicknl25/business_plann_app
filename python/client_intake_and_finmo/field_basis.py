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

import re
from typing import Dict, Optional

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
  # CW-041: a BALANCE, not a rate over time - it is what is still owed.
  "capital_lease_balance": AMOUNT,
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


# ---------------------------------------------------------------- stated basis
# NICK 2026-09-12 (the units door, fourth in its class): "My other operating
# expense should go to 633,312 a year" was stored in the MONTHLY field and
# read back as "just as you specified". The router is asked to convert the
# client's stated basis to the declared one; this is the door's check that
# it did. It reads the client's OWN words for the number that was written:
# a figure the client called yearly cannot land in a monthly field
# unconverted. It is not a heuristic about what a number "probably" means -
# with no unit stated it says nothing, and the door writes the router's
# value as-is.
_NUM = r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|m|million)?"
_ANNUAL_WORDS = r"(?:(?:a|per|each|every)\s+(?:year|yr)|/\s*(?:year|yr)|annually|annual|yearly|per\s+annum|p\.?a\.?)"
_MONTHLY_WORDS = r"(?:(?:a|per|each|every)\s+(?:month|mo)|/\s*(?:month|mo)|monthly)"
_QUARTERLY_WORDS = r"(?:(?:a|per|each|every)\s+(?:quarter|qtr)|/\s*(?:quarter|qtr)|quarterly)"
_STATED_RE = re.compile(
  _NUM + r"\s*(?:dollars\s*)?(?P<unit>" + _ANNUAL_WORDS + "|" + _MONTHLY_WORDS + "|" + _QUARTERLY_WORDS + ")",
  re.I,
)


def _num_from(match) -> Optional[float]:
  raw = str(match.group(1) or "").replace(",", "")
  try:
    v = float(raw)
  except ValueError:
    return None
  mult = str(match.group(2) or "").lower()
  if mult in ("k", "thousand"):
    v *= 1_000.0
  elif mult in ("m", "million"):
    v *= 1_000_000.0
  return v


def stated_basis_in_text(text: str, value: float) -> Optional[str]:
  """The basis the client stated for THIS number in their own words -
  MONTHLY / ANNUAL / QUARTERLY - or None when the number does not appear
  with a unit. Matches the figure within half a percent so "633,312 a
  year" pairs with 633312.0 and with 633312.49."""
  try:
    target = abs(float(value))
  except (TypeError, ValueError):
    return None
  for m in _STATED_RE.finditer(str(text or "")):
    v = _num_from(m)
    if v is None:
      continue
    tol = max(0.5, target * 0.005)
    if abs(v - target) > tol:
      continue
    unit = str(m.group("unit") or "").lower()
    if re.fullmatch(_MONTHLY_WORDS, unit, re.I):
      return MONTHLY
    if re.fullmatch(_QUARTERLY_WORDS, unit, re.I):
      return QUARTERLY
    if re.fullmatch(_ANNUAL_WORDS, unit, re.I):
      return ANNUAL
  return None


_PER_YEAR = {MONTHLY: 12.0, QUARTERLY: 4.0, ANNUAL: 1.0}


def convert_between(value: float, from_basis: str, to_basis: str) -> float:
  """Move a dollar figure between time bases. Same basis, or a basis with
  no time dimension, returns the value unchanged."""
  if from_basis == to_basis or from_basis not in _PER_YEAR or to_basis not in _PER_YEAR:
    return float(value)
  annual = float(value) * _PER_YEAR[from_basis]
  return annual / _PER_YEAR[to_basis]


def reconcile_stated_basis(field: str, value: float, user_text: str):
  """(value_in_declared_basis, note). If the client stated a basis for this
  number that differs from the field's declared basis, the value is
  converted and the note names the move; otherwise the value is returned
  untouched with an empty note."""
  declared = basis_of(field)
  if declared not in _PER_YEAR:
    return float(value), ""
  stated = stated_basis_in_text(user_text, value)
  if not stated or stated == declared:
    return float(value), ""
  converted = round(convert_between(float(value), stated, declared), 2)
  leaf = str(field or "").rsplit(".", 1)[-1]
  return converted, f"basis_converted:{leaf}:{stated}->{declared}"
