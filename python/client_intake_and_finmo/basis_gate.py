"""Layer 1: the universal plausibility gate.

One shared signal every numeric capture site consults - the writers call
``gate_numeric`` for each registry-numeric field they are about to write,
and the gate returns one verdict:

  pass     -> write as-is
  convert  -> write the deterministically converted value (client MARKED a
              basis that differs from the field's canonical basis on a
              path that never converted before; arithmetic here, never GPT)
  clarify  -> write NOTHING; the returned pending payload raises the
              propose-confirm clarifier (Model A: the app shows its
              arithmetic, the client confirms in any words)

The gate SUBSUMES the per-site detectors (period fingerprints, per-product
probe, scope axis, stage-amount smallness, percent-vs-dollar) - they are
internals here, keyed by the FIELD CLASS from the basis registry, not by
call site. Add a field to the registry tomorrow and it is covered because
capture consults the gate, not because someone remembered a check.

HARD CONSTRAINTS (by design, per Nick): this is a NORMALIZER, not a
judge - it resolves basis and flags implausibility; it never decides what
a number should be. It is not a second interpreter: the router/consultant
GPTs still decide WHAT the client said; the gate only handles the number
they extracted.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from field_basis import basis_of  # the single basis authority

# Canonical periods-per-year for basis arithmetic (shared with the
# resolution applier in intake_consult).
PERIODS_PER_YEAR = {"weekly": 52.0, "monthly": 12.0, "annual": 1.0}

# Field-class map for fields the legacy registry expresses as MONTHLY/
# ANNUAL/AMOUNT/COUNT/RATIO. Driver fields are cadence-relative and are
# declared here (field path -> class).
_DRIVER_PRICE_FIELDS = {"ops.unit_price"}
_COUNT_FIELDS = {
  "ops.units_per_week_capacity",
  "ops.units_per_period_capacity",
  "ops.operating_periods_per_year",
  "financials.current_num_employees",
}
_RATIO_FIELDS = {"ops.utilization_rate", "financials.funding_split_debt_share"}
_ANNUAL_WAGE_FIELDS = {"people.annual_wage", "people.rest_of_team_payroll_year1"}


def field_class(field: str) -> str:
  """The gate's view of a field: monthly | annual | amount | count |
  ratio | driver_price | unknown. Financials fields defer to the
  field_basis registry (the existing authority)."""
  name = str(field or "").strip()
  if name in _DRIVER_PRICE_FIELDS:
    return "driver_price"
  if name in _COUNT_FIELDS:
    return "count"
  if name in _RATIO_FIELDS:
    return "ratio"
  if name in _ANNUAL_WAGE_FIELDS:
    return "annual"
  leaf = name.rsplit(".", 1)[-1]
  try:
    declared = str(basis_of(leaf) or "").strip().lower()
  except Exception:
    declared = ""
  if declared in ("monthly", "annual", "count", "ratio", "amount"):
    return declared
  return "unknown"


def gate_numeric(
  *,
  field: str,
  value: float,
  stated_basis: Optional[str],
  user_message: str,
  context: Optional[Dict[str, Any]] = None,
  detectors: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """The one shared verdict. `detectors` carries the caller-provided
  detector callables (defined beside the clarify machinery so the gate
  has no import cycle): keys revenue_driver, stage_amount,
  percent_vs_dollar. Context carries financials_json / financials_year1 /
  anchors as available - missing context simply narrows what can be
  checked (never blocks a write)."""
  ctx = context or {}
  det = detectors or {}
  cls = field_class(field)
  basis = str(stated_basis or "").strip().lower()

  # 1) DETERMINISTIC CONVERSION - the client MARKED a basis that differs
  # from canonical on a path that historically copied verbatim. Arithmetic
  # lives here, never in the GPT.
  if basis in PERIODS_PER_YEAR and cls in ("monthly", "annual"):
    canonical_periods = PERIODS_PER_YEAR["monthly" if cls == "monthly" else "annual"]
    stated_periods = PERIODS_PER_YEAR[basis]
    if abs(canonical_periods - stated_periods) > 1e-9:
      converted = float(value) * (stated_periods / canonical_periods)
      return {
        "verdict": "convert",
        "value": converted,
        "provenance": {
          "stated_value": float(value),
          "stated_basis": basis,
          "canonical": cls,
          "factor": stated_periods / canonical_periods,
        },
      }

  # 2) CLASS-KEYED PLAUSIBILITY - the subsumed detectors, selected by the
  # field's class, not the call site.
  pending = None
  try:
    if field == "financials.current_revenue" and det.get("revenue_driver"):
      pending = det["revenue_driver"](
        ctx.get("financials_json") or {}, ctx.get("financials_year1_json") or {}
      )
    elif cls == "annual" and field.endswith("_total_year1"):
      # CW-009 checkpoint-a: percent-vs-dollar must be BIDIRECTIONAL. When
      # the router reads an unmarked bare figure as dollars, no percent
      # field is written, so the ratio-class dispatch below never runs -
      # check the dollar side here for totals that have a percent twin.
      leaf = field.rsplit(".", 1)[-1]
      twin = leaf.replace("_total_year1", "_percent_of_revenue")
      if twin != leaf and det.get("dollar_vs_percent"):
        pending = det["dollar_vs_percent"](
          field_name=leaf,
          dollar_value=float(value),
          financials_json=ctx.get("financials_json") or {},
          user_message=user_message,
        )
      if not pending and det.get("stage_amount"):
        pending = det["stage_amount"](
          field_name=leaf,
          financials_json=ctx.get("financials_json") or {},
        )
    elif cls == "ratio" and field.endswith("_percent_of_revenue") and det.get("percent_vs_dollar"):
      pending = det["percent_vs_dollar"](
        field_name=field.rsplit(".", 1)[-1],
        percent_value=float(value),
        financials_json=ctx.get("financials_json") or {},
        user_message=user_message,
      )
  except Exception:
    pending = None
  if pending:
    return {"verdict": "clarify", "pending": pending}

  return {"verdict": "pass", "value": float(value)}
