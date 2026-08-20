"""R-MKTG-03 phase 1 — the marketing schedule as a DECOMPOSITION of the
settled percent.

Pure post-process, on the ``finmo_break_even`` precedent: it reads values that
are already final and returns a payload. It writes nothing back into any
driver, row, or engine value. No solver, no intake, no GPT-to-client change.

WHY A DECOMPOSITION AND NOT A DERIVATION (R-MKTG-02, Nick's ruling). The
marketing percent is settled before this module runs — the client's stated
ratio seeds the stub and Q1, and the restoration-loop solver writes Q2-Q20
against an ``ebitda_margin`` target. Deriving marketing dollars from a CAC
assumption would produce a DIFFERENT number than the plan the client agreed.
So the identity runs the other way and **CAC is the plug**::

    marketing_$_q   = settled_percent_q * revenue_q      (already true)
    customers_q     = units_q / repeat_units_per_customer
    retained_q      = customers_(q-1) * retention        <- the assumption
    new_customers_q = customers_q - retained_q
    CAC_q           = marketing_$_q / new_customers_q    <- absorbs the residual

Because CAC absorbs every residual, the percentage is never recomputed and
cannot drift. The payload carries the settled driver value VERBATIM;
``marketing_percent_implied_by_dollars`` re-derives it from the dollars purely
as a consistency check, and agrees to ~5e-11 — float noise on a ratio, which is
why the payload does not use the re-derived figure as the number.

WHAT IS EXACT AND WHAT IS ASSUMED. Revenue, marketing dollars, the percent and
units are exact. Customers and retained inherit the repeat rate; new customers
inherit both; **CAC inherits everything**. CAC is the number a client will
quote and the softest number here, and ``exactness`` on every line says so, so
the tab can label it rather than guess.

Q1 SEEDS FROM THE STUB (ruling): column C carries its own revenue and its own
per-line drivers, so the stub's customer count is real. No invented
first-quarter convention, and no artificially low Q1 CAC.

THE FOUR CLASS RULES (R-MKTG-02 §3, measured against 400 real drafts — every
one of these shapes exists in production):

  R1  CAC is suppressed ONLY when the customer base does not grow
      (``new_customers <= 0``), which happens whenever
      ``retention * prior >= current`` — a client typing retention = 1.0 on a
      flat plan produces exactly that, and spend divided across customers you
      did not acquire is genuinely undefined. A count that is small but REAL
      still gets its CAC, flagged ``thin_acquisition_count``; suppressing those
      erased a legitimate advisory firm's $24,590 CAC in every quarter.
  R2  Zero marketing spend -> CAC is None rather than 0/0. NOTE: the draft
      that looked like this in the 400-sweep (Cedarhill Animal Hospital) has
      zero STATED marketing at intake but a non-zero planned spend, so it
      exercises R4, not R2. R2 is covered by the unit test's synthetic
      all-zero-marketing payload.
  R3  Pre-revenue -> the stub's customers are legitimately 0, so Q1's new
      customers equal Q1's customers and CAC is simply first-quarter CAC.
      NO special case; it must merely not be mistaken for a bug.
  R4  No meaningful entity count -> emit the EXACT lines only and mark the
      assumed block ``not_modelled``. The schedule degrades to its exact half
      rather than inventing an audience. This is the workbook-side answer to a
      B2B referral-dominant business.

BASIS-AGNOSTIC (measured): ``market_basis_type`` (consumer / b2b / mixed)
changes only the NOUN on the reachable-market context line. The arithmetic runs
off units, repeat rate and retention, none of which care whether the entity is
a household or a firm, so there is no b2b branch.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

#: NUMERICAL floor only. Its single job is to stop a division that would be
#: meaningless - it is not a judgment about how small a real business can be.
#:
#: It was 0.5 (half a customer a quarter) and that was CONSUMER-SHAPED, which
#: Nick caught before the tab was built around it. Measured across every b2b and
#: mixed draft in production: Fernhill Advisory - 10 clients a year, $129,600 of
#: revenue per client - was suppressed in 20 of 20 quarters, hiding a CAC of
#: $24,590 that is entirely sane for that business. Four other b2b firms lost a
#: quarter each. A threshold that erases a legitimate advisory firm's headline
#: acquisition cost is measuring the wrong thing.
EPSILON_NEW_CUSTOMERS = 1e-6

#: Below this the count is real but THIN - roughly one customer a year or less.
#: The CAC is still computed and shown, and flagged so the tab can say the
#: acquisition count behind it is small. Showing a marked number teaches the
#: client something; hiding it teaches nothing.
THIN_NEW_CUSTOMERS_PER_QUARTER = 0.25

#: Emitted when a line is exact arithmetic on settled values.
EXACT = "exact"
#: Emitted when a line inherits an assumption. The tab labels these.
ASSUMED = "assumed"

PERIOD_COUNT = 21          # stub + 20 quarters


def _num(value: Any) -> float:
  try:
    if value is None:
      return 0.0
    return float(value)
  except (TypeError, ValueError):
    return 0.0


def _series(rows: Any, label: str) -> List[float]:
  """The 21-period series for a P&L label, or an empty list."""
  for row in rows or []:
    if isinstance(row, dict) and str(row.get("label") or "").strip() == label:
      values = row.get("values")
      if isinstance(values, list):
        return [_num(v) for v in values]
  return []


def _annual_units_per_product(ops_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  """Per-product annual unit capacity from the REVENUE DRIVERS (ruling: those
  are what drive revenue, so they are the unit source - not the audience
  model's own count, which disagrees slightly and does not drive anything)."""
  out: List[Dict[str, Any]] = []
  for lob in (ops_json or {}).get("lob_models") or []:
    if not isinstance(lob, dict):
      continue
    for product in lob.get("products") or []:
      if not isinstance(product, dict):
        continue
      capacity = _num(product.get("units_per_period_capacity"))
      utilisation = _num(product.get("utilization_rate"))
      periods = _num(product.get("operating_periods_per_year"))
      out.append({
        "lob_name": lob.get("lob_name"),
        "product_name": product.get("product_name"),
        "annual_units": capacity * utilisation * periods,
        "unit_price": _num(product.get("unit_price")),
      })
  return out


def compute_marketing_schedule(
  *,
  finmo_json: Dict[str, Any],
  model_input_json: Dict[str, Any],
  operating_model_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
  retention_judgment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """-> the ``marketing_schedule_json`` payload.

  ``retention_judgment`` is the GPT expert estimate (see
  ``gpt_retention_judgment``); when absent the schedule still emits its EXACT
  lines and marks the assumed block unavailable, so a failed GPT call degrades
  rather than blocks.
  """
  marketing_model_json = marketing_model_json or {}
  pl_rows = (finmo_json or {}).get("pl") or []

  revenue = _series(pl_rows, "Revenue")
  marketing_dollars = _series(pl_rows, "Marketing")
  if not revenue:
    return {
      "status": "unavailable",
      "reason": "no_revenue_series_in_finmo_json",
      "periods": [],
    }

  # The settled driver row. Read for DISCLOSURE and for the tie-back assertion;
  # never recomputed.
  settled_percent: List[float] = []
  for section_row in ((model_input_json or {}).get("sections") or {}).get("expenses") or []:
    if isinstance(section_row, dict) and section_row.get("lever_id") == "expenses::Marketing":
      values = section_row.get("values")
      if isinstance(values, list):
        settled_percent = [_num(v) for v in values]
      break

  products = _annual_units_per_product(operating_model_json)
  annual_units = sum(p["annual_units"] for p in products)

  # Repeat units per customer: the audience model's own implied rate. It is the
  # only entity-per-unit signal that exists today, and it is an assumption.
  expected_units = _num(marketing_model_json.get("expected_units_year1"))
  expected_customers = _num(marketing_model_json.get("expected_customers_or_clients_year1"))
  repeat_units_per_customer = (expected_units / expected_customers) if expected_customers > 0 else 0.0

  retention = None
  retention_meta: Dict[str, Any] = {"available": False}
  if isinstance(retention_judgment, dict) and retention_judgment.get("ok"):
    retention = retention_judgment.get("retention_rate")
    retention = _num(retention) if retention is not None else None
    retention_meta = {
      "available": retention is not None,
      "retention_rate": retention,
      # Nick's ruling: an expert estimate is NOT a citation. It is labelled as
      # what it is, and never dressed in the third-party clothing the
      # valuation constants legitimately wear.
      "basis": "ASSUMPTION",
      "basis_detail": "expert_estimate",
      "source": "GPT expert estimate from the business model — not a sourced figure",
      "rationale": retention_judgment.get("rationale"),
      "confidence_tier": retention_judgment.get("confidence_tier") or "low",
      "model": retention_judgment.get("model"),
    }
  elif isinstance(retention_judgment, dict):
    retention_meta = {"available": False, "error": retention_judgment.get("error")}

  # R4: without a usable entity count the assumed half is not modelled.
  entity_math_available = (
    repeat_units_per_customer > 0.0
    and annual_units > 0.0
    and retention is not None
  )

  # R2: a plan with no marketing spend has no acquisition economics to show.
  total_marketing = sum(marketing_dollars) if marketing_dollars else 0.0
  zero_marketing = total_marketing <= 0.0

  periods: List[Dict[str, Any]] = []
  previous_customers: Optional[float] = None
  quarterly_units_base = annual_units / 4.0 if annual_units else 0.0
  reference_revenue = revenue[1] if len(revenue) > 1 and revenue[1] else 0.0

  for index in range(min(PERIOD_COUNT, len(revenue))):
    period_revenue = revenue[index]
    period_marketing = marketing_dollars[index] if index < len(marketing_dollars) else 0.0

    # Units scale with revenue against the Q1 reference, so a ramping plan
    # carries a ramping unit count rather than a flat one.
    units = 0.0
    if quarterly_units_base and reference_revenue:
      units = quarterly_units_base * (period_revenue / reference_revenue)

    # UNITS ARE QUARTERLY, THE REPEAT RATE IS ANNUAL. Dividing one by the other
    # understated customers four-fold and overstated CAC four-fold - Harrow came
    # out at 162 customers against the audience model's own 650, and the error
    # only surfaced when the tab was rendered and the two disagreed. A customer
    # buying 10.85 times a year buys 2.71 times a quarter.
    quarterly_repeat = repeat_units_per_customer / 4.0
    customers = (units / quarterly_repeat) if quarterly_repeat > 0 else 0.0
    # R3: at the stub there is no prior quarter, so retained is 0 and every
    # customer is new. For a pre-revenue business the stub's customers are
    # legitimately 0 and Q1's new customers equal Q1's customers.
    retained = (previous_customers * retention) if (previous_customers is not None and retention is not None) else 0.0
    new_customers = customers - retained

    cac: Optional[float] = None
    cac_note: Optional[str] = None
    # R1, restated. CAC is undefined when the customer base does not GROW - you
    # cannot divide spend across customers you did not acquire - and that is the
    # only case worth suppressing. A count that is small but real (a b2b firm
    # adding a client a year) has a large and perfectly meaningful CAC.
    if not entity_math_available:
      cac_note = "not_modelled"
    elif zero_marketing:
      cac_note = "no_marketing_spend"
    elif new_customers <= EPSILON_NEW_CUSTOMERS:
      cac_note = "no_net_acquisition"
    else:
      cac = period_marketing / new_customers
      if new_customers < THIN_NEW_CUSTOMERS_PER_QUARTER:
        cac_note = "thin_acquisition_count"

    # THE SETTLED VALUE ITSELF, not a recomputation of it. Dividing dollars by
    # revenue reproduces the percent to ~5e-11, which is close enough to look
    # exact and is not; carrying the driver value verbatim makes the payload
    # bit-for-bit the number the plan was built on. The recomputed figure is
    # kept beside it ONLY as the tie-back check.
    implied_percent = (period_marketing / period_revenue) if period_revenue else 0.0
    settled_here = settled_percent[index] if index < len(settled_percent) else implied_percent
    periods.append({
      "period_index": index,
      "is_stub": index == 0,
      "revenue": round(period_revenue, 6),
      "marketing_dollars": round(period_marketing, 6),
      "marketing_percent_of_revenue": settled_here,
      "marketing_percent_implied_by_dollars": round(implied_percent, 12),
      "units": round(units, 6) if entity_math_available else None,
      "customers": round(customers, 6) if entity_math_available else None,
      "retained_customers": round(retained, 6) if entity_math_available else None,
      "new_customers": round(new_customers, 6) if entity_math_available else None,
      "customer_acquisition_cost": round(cac, 6) if cac is not None else None,
      # Why a CAC is absent, or why it should be read with care. The tab shows
      # this rather than leaving a client to wonder at a blank cell.
      "customer_acquisition_cost_note": cac_note,
    })
    previous_customers = customers if entity_math_available else None

  # THE TIE-BACK, asserted rather than assumed. Because CAC is the plug the
  # decomposition cannot move the percent - this proves it did not.
  tie_back_exact = True
  tie_back_max_delta = 0.0
  if settled_percent:
    for row in periods:
      i = int(row["period_index"])
      if i < len(settled_percent):
        delta = abs(row["marketing_percent_implied_by_dollars"] - settled_percent[i])
        tie_back_max_delta = max(tie_back_max_delta, delta)
        # 1e-9 is float noise on a ratio, not disagreement. The PAYLOAD carries
        # the settled value verbatim; this only proves the dollars are
        # consistent with it.
        if delta > 1e-9:
          tie_back_exact = False

  if zero_marketing:
    schedule_class = "zero_marketing"          # R2
  elif not entity_math_available:
    schedule_class = "not_modelled"            # R4
  else:
    schedule_class = "audience_modelled"

  basis_type = str(marketing_model_json.get("market_basis_type") or "").strip() or None
  return {
    "status": "ok",
    "schedule_class": schedule_class,
    "contract_version": "marketing_schedule_v1",
    "periods": periods,
    "tie_back": {
      "exact": tie_back_exact,
      "max_abs_delta": tie_back_max_delta,
      "settled_percent_available": bool(settled_percent),
      "note": (
        "The payload carries the settled driver percent VERBATIM. "
        "marketing_percent_implied_by_dollars re-derives it from the dollars "
        "as a consistency check; max_abs_delta is float noise on a ratio, not "
        "disagreement. CAC is the plug, so the percent is never recomputed."
      ),
    },
    "exactness": {
      "revenue": EXACT,
      "marketing_dollars": EXACT,
      "marketing_percent_of_revenue": EXACT,
      "marketing_percent_implied_by_dollars": EXACT,
      "units": EXACT,
      "customers": ASSUMED,
      "retained_customers": ASSUMED,
      "new_customers": ASSUMED,
      "customer_acquisition_cost": ASSUMED,
      "customer_acquisition_cost_note": EXACT,
    },
    "assumptions": {
      "retention": retention_meta,
      "repeat_units_per_customer": {
        "value": repeat_units_per_customer or None,
        "period": "per_year",
        "note": "Divided by 4 before use, because the unit lines are quarterly",
        "basis": "ASSUMPTION",
        "basis_detail": "implied_from_audience_model",
        "source": (
          "expected_units_year1 / expected_customers_or_clients_year1 from the "
          "intake-time audience estimate — an implied rate, not a measured one"
        ),
        "available": repeat_units_per_customer > 0.0,
      },
    },
    "context": {
      "market_basis_type": basis_type,
      "reachable_market": marketing_model_json.get("reachable_market"),
      "reachable_market_b2c": marketing_model_json.get("reachable_market_b2c"),
      "reachable_market_b2b": marketing_model_json.get("reachable_market_b2b"),
      # The noun the tab should use. The arithmetic is basis-agnostic; only
      # the label changes.
      "entity_noun": (
        "firms" if basis_type == "b2b"
        else "households and firms" if basis_type == "mixed"
        else "customers"
      ),
      "capture_rate_year1": marketing_model_json.get("capture_rate_year1"),
      "annual_units_from_revenue_drivers": annual_units or None,
      "products": products,
    },
  }
