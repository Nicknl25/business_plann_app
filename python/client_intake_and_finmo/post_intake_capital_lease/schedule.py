"""Capital lease deterministic schedule builder and validators.

Phase 9 P3.16 — integrate capital lease as a first-class concept
parallel to debt. Pre-iter behavior: lease balance flowed into total
liabilities with no offsetting asset, so retained earnings absorbed
the shortfall; no lease interest; no separate lease asset depreciation;
the Debt Schedule sheet's Capital Lease section was orphaned. This
module:

  - Computes the deterministic per-quarter lease schedule (opening,
    principal payment with clipping, interest at SBA rate, closing).
  - Produces a snapshot from FINMO's per-quarter lease fields so the
    payload can be validated against in-memory FINMO state (Mirror
    Flavor 2 — independent mirror that hard-fails on drift).
  - Provides 9 validators (Type 1 — business-logic checks) and 6
    machinery fail-fasts (Type 2 — infrastructure invariants).

Capital lease has NO dedicated handler. Downstream effects (cash
pressure, interest drag) are absorbed by existing handlers (funding,
restoration). See iter P3.16 §"NO HANDLER" for the reasoning.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from client_intake_and_finmo.fail_fast import fail_fast_raise  # type: ignore


CAPITAL_LEASE_CONTRACT_VERSION = "post_intake_capital_lease_schedule_v1"
CAPITAL_LEASE_DEPRECIATION_QUARTERS = 20
CAPITAL_LEASE_RECONCILE_TOLERANCE = 1  # whole-dollar tolerance per spec


def term_end_residual_tolerance(quarters_elapsed: int, rounding_unit: float = 1.0) -> int:
  """Derived-from-rounding-math tolerance for the term-end zero check
  (CW-016 Ironbridge build failure). Schedule rows store whole-dollar
  ints while FINMO amortizes in floats, and validator #9 re-derives the
  balance by summing the ROUNDED per-quarter principals: each principal
  contributes up to unit/2 of drift, plus unit/2 each for the seed and
  the closing's own rounding. Max legitimate residue after q quarters is
  therefore unit/2 * q + unit - not a guessed constant and not
  scale-relative, because rounding drift scales with the NUMBER of
  rounding operations, never with lease size. Anything above this bound
  cannot be rounding and IS a genuinely un-closed schedule (a $5,000
  residue still fails at any horizon; the old flat tolerance of 1
  failed a real plan over a $5 crumb at Q12, where this bound is 7)."""
  q = max(0, int(quarters_elapsed))
  unit = max(0.0, float(rounding_unit))
  return int((unit / 2.0) * q + unit)


_FAIL_FAST_PHASE = "POST_INTAKE"
_FAIL_FAST_STAGE = "capital_lease_schedule"


def _safe_float(value: Any) -> Optional[float]:
  if value is None:
    return None
  if isinstance(value, bool):
    return 1.0 if value else 0.0
  try:
    text = str(value).strip().replace(",", "")
    if text == "":
      return None
    return float(text)
  except Exception:
    return None


def _safe_int(value: Any) -> int:
  return int(round(float(_safe_float(value) or 0.0)))


def _live_quarter_rows(finmo_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = finmo_payload if isinstance(finmo_payload, dict) else {}
  rows = [row for row in (payload.get("quarter_rows") or []) if isinstance(row, dict)]
  return sorted(
    [row for row in rows if int(_safe_float(row.get("quarter_index")) or 0) >= 1],
    key=lambda item: int(_safe_float(item.get("quarter_index")) or 0),
  )


def _schedule_seed_value(model_input_json: Optional[Dict[str, Any]], key: str) -> Optional[float]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  return _safe_float(schedules.get(key))


def _interest_rate_from_finmo(finmo_payload: Optional[Dict[str, Any]]) -> float:
  for row in _live_quarter_rows(finmo_payload):
    rate = _safe_float(row.get("debt_interest_rate"))
    if rate is not None and rate > 0.0:
      return float(rate)
  return 0.0


def capital_lease_opening_seed(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_payload: Optional[Dict[str, Any]],
) -> int:
  seed = _schedule_seed_value(model_input_json, "lease_opening_balance_seed")
  if seed is not None:
    return int(round(max(0.0, float(seed))))
  rows = _live_quarter_rows(finmo_payload)
  if rows:
    opening = _safe_float(rows[0].get("lease_opening_balance_total"))
    if opening is not None:
      return int(round(max(0.0, float(opening))))
  return 0


def build_capital_lease_schedule(
  *,
  opening_balance: float,
  principal_payments_per_quarter: List[float],
  interest_rate: float,
  horizon_quarters: int = CAPITAL_LEASE_DEPRECIATION_QUARTERS,
  depreciation_quarters: int = CAPITAL_LEASE_DEPRECIATION_QUARTERS,
) -> Dict[str, Any]:
  """Build the deterministic capital lease schedule.

  Invariants enforced (machinery fail-fasts — Type 2 per doctrine §5b):
    - opening_balance >= 0
    - interest_rate >= 0
    - horizon_quarters >= 1
    - per-quarter principal clipped to remaining balance
    - closing[q] = opening[q] - principal[q] (no addition path here —
      new leases out of scope per iter P3.16)
    - asset depreciates straight-line at opening/depreciation_quarters,
      clipped to remaining ROU value
  """
  opening_balance_value = max(0.0, float(_safe_float(opening_balance) or 0.0))
  rate = float(_safe_float(interest_rate) or 0.0)
  if rate < 0.0:
    fail_fast_raise(
      "capital_lease_interest_components_misaligned",
      f"capital lease interest rate must be non-negative; received {rate!r}",
      phase=_FAIL_FAST_PHASE,
      stage=_FAIL_FAST_STAGE,
      details={"interest_rate": rate},
    )
  horizon = int(horizon_quarters)
  if horizon < 1:
    fail_fast_raise(
      "capital_lease_routing_double_count",
      f"horizon_quarters must be >= 1; received {horizon!r}",
      phase=_FAIL_FAST_PHASE,
      stage=_FAIL_FAST_STAGE,
      details={"horizon_quarters": horizon},
    )
  dep_quarters = int(depreciation_quarters)
  if dep_quarters < 1:
    fail_fast_raise(
      "capital_lease_asset_not_depreciating",
      f"depreciation_quarters must be >= 1; received {dep_quarters!r}",
      phase=_FAIL_FAST_PHASE,
      stage=_FAIL_FAST_STAGE,
      details={"depreciation_quarters": dep_quarters},
    )
  requested = [max(0.0, float(_safe_float(item) or 0.0)) for item in (principal_payments_per_quarter or [])]
  while len(requested) < horizon:
    requested.append(0.0)
  per_quarter_depreciation = (opening_balance_value / float(dep_quarters)) if opening_balance_value > 0 else 0.0
  rows: List[Dict[str, Any]] = []
  obligation = opening_balance_value
  rou_asset = opening_balance_value
  for quarter_index in range(1, horizon + 1):
    quarter_opening = obligation
    requested_principal = requested[quarter_index - 1]
    principal_payment = min(requested_principal, max(0.0, quarter_opening))
    closing = max(0.0, quarter_opening - principal_payment)
    if principal_payment > quarter_opening + 1e-6:
      fail_fast_raise(
        "capital_lease_principal_exceeds_obligation",
        f"Q{quarter_index} principal payment {principal_payment} exceeds opening obligation {quarter_opening}",
        phase=_FAIL_FAST_PHASE,
        stage=_FAIL_FAST_STAGE,
        details={"quarter_index": quarter_index, "principal_payment": principal_payment, "opening": quarter_opening},
      )
    interest_payment = float(round(quarter_opening * rate, 6))
    rou_opening = rou_asset
    asset_depreciation = min(per_quarter_depreciation, max(0.0, rou_opening))
    rou_closing = max(0.0, rou_opening - asset_depreciation)
    rows.append(
      {
        "quarter_index": quarter_index,
        "opening_balance": int(round(quarter_opening)),
        "requested_principal_payment": int(round(requested_principal)),
        "principal_payment": int(round(principal_payment)),
        "interest_payment": int(round(interest_payment)),
        "closing_balance": int(round(closing)),
        "rou_asset_opening": int(round(rou_opening)),
        "lease_asset_depreciation": int(round(asset_depreciation)),
        "rou_asset_closing": int(round(rou_closing)),
        "interest_rate": round(float(rate), 6),
      }
    )
    obligation = closing
    rou_asset = rou_closing
  return {
    "contract_version": CAPITAL_LEASE_CONTRACT_VERSION,
    "status": "ready" if opening_balance_value > 0 else "skipped_no_lease",
    "horizon_quarters": horizon,
    "depreciation_quarters": dep_quarters,
    "opening_balance_seed": int(round(opening_balance_value)),
    "interest_rate": round(float(rate), 6),
    "schedule_method": "declining_balance_straight_line_depreciation",
    "rows": rows,
  }


def build_capital_lease_schedule_snapshot(
  *,
  finmo_payload: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]] = None,
  source_stage: str = "",
  horizon_quarters: int = CAPITAL_LEASE_DEPRECIATION_QUARTERS,
  depreciation_quarters: int = CAPITAL_LEASE_DEPRECIATION_QUARTERS,
) -> Dict[str, Any]:
  """Read FINMO's per-quarter lease fields and emit a parallel schedule
  payload (Mirror Flavor 2 per doctrine §4).

  The snapshot is what gets validated against FINMO at finalize time;
  any drift between the two implementations is a machinery bug.
  """
  opening_seed = capital_lease_opening_seed(
    model_input_json=model_input_json,
    finmo_payload=finmo_payload,
  )
  rate = _interest_rate_from_finmo(finmo_payload)
  finmo_rows_by_quarter = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in _live_quarter_rows(finmo_payload)
  }
  schedule_rows: List[Dict[str, Any]] = []
  per_quarter_depreciation = (float(opening_seed) / float(depreciation_quarters)) if opening_seed > 0 else 0.0
  for quarter_index in range(1, int(horizon_quarters) + 1):
    finmo_row = finmo_rows_by_quarter.get(quarter_index) or {}
    opening = _safe_int(finmo_row.get("lease_opening_balance_total"))
    principal = _safe_int(finmo_row.get("lease_principal_repayments"))
    closing = _safe_int(finmo_row.get("lease_closing_balance_total"))
    interest = _safe_int(finmo_row.get("lease_interest_expense"))
    rou_opening = _safe_int(finmo_row.get("right_of_use_asset_opening"))
    rou_closing = _safe_int(finmo_row.get("right_of_use_asset"))
    asset_dep = _safe_int(finmo_row.get("lease_asset_depreciation_expense"))
    schedule_rows.append(
      {
        "quarter_index": quarter_index,
        "date": finmo_row.get("date"),
        "opening_balance": opening,
        "principal_payment": principal,
        "interest_payment": interest,
        "closing_balance": closing,
        "rou_asset_opening": rou_opening,
        "rou_asset_closing": rou_closing,
        "lease_asset_depreciation": asset_dep,
        "interest_rate": round(float(rate), 6),
        "finmo_formula": (
          "closing = max(0, opening - principal); "
          "interest = opening * interest_rate; "
          "asset_depreciation = opening_balance_seed / depreciation_quarters (clipped to remaining ROU)"
        ),
      }
    )
  return {
    "contract_version": CAPITAL_LEASE_CONTRACT_VERSION,
    "schedule_role": "persisted_final_capital_lease_schedule",
    "source_stage": str(source_stage or "").strip(),
    "horizon_quarters": int(horizon_quarters),
    "depreciation_quarters": int(depreciation_quarters),
    "opening_balance_seed": int(opening_seed),
    "interest_rate": round(float(rate), 6),
    "per_quarter_depreciation": int(round(per_quarter_depreciation)),
    "schedule_method": "declining_balance_straight_line_depreciation",
    "rows": schedule_rows,
  }


def validate_capital_lease_schedule_payload(
  *,
  capital_lease_schedule: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]] = None,
  horizon_quarters: int = CAPITAL_LEASE_DEPRECIATION_QUARTERS,
  depreciation_quarters: int = CAPITAL_LEASE_DEPRECIATION_QUARTERS,
  tolerance: int = CAPITAL_LEASE_RECONCILE_TOLERANCE,
) -> List[Dict[str, Any]]:
  """Type 1 validators (business-logic checks per doctrine §5b).

  Returns a list of structured violations. Empty list == passed. Nine
  validators in total, matching iter P3.16 §"VALIDATORS".
  """
  payload = capital_lease_schedule if isinstance(capital_lease_schedule, dict) else {}
  rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
  horizon = int(horizon_quarters)
  dep_quarters = int(depreciation_quarters)
  violations: List[Dict[str, Any]] = []
  intake_seed = capital_lease_opening_seed(
    model_input_json=model_input_json,
    finmo_payload=None,
  )
  payload_seed = _safe_int(payload.get("opening_balance_seed"))
  if rows:
    q1_opening = _safe_int(rows[0].get("opening_balance"))
    q1_rou_opening = _safe_int(rows[0].get("rou_asset_opening"))
  else:
    q1_opening = 0
    q1_rou_opening = 0
  # 1. capital_lease_obligation_at_q0
  if abs(payload_seed - intake_seed) > tolerance or abs(q1_opening - intake_seed) > tolerance:
    violations.append(
      {
        "reason": "capital_lease_obligation_at_q0",
        "intake_seed": intake_seed,
        "payload_seed": payload_seed,
        "q1_opening_balance": q1_opening,
      }
    )
  # 2. capital_lease_asset_at_q0
  if abs(q1_rou_opening - intake_seed) > tolerance:
    violations.append(
      {
        "reason": "capital_lease_asset_at_q0",
        "intake_seed": intake_seed,
        "q1_rou_opening": q1_rou_opening,
      }
    )
  rate = float(_safe_float(payload.get("interest_rate")) or 0.0)
  per_quarter_depreciation = float(intake_seed) / float(dep_quarters) if intake_seed > 0 else 0.0
  total_principal = 0
  obligation = intake_seed
  for index, row in enumerate(rows):
    quarter = _safe_int(row.get("quarter_index"))
    opening = _safe_int(row.get("opening_balance"))
    principal = _safe_int(row.get("principal_payment"))
    interest = _safe_int(row.get("interest_payment"))
    closing = _safe_int(row.get("closing_balance"))
    rou_closing = _safe_int(row.get("rou_asset_closing"))
    asset_dep = _safe_int(row.get("lease_asset_depreciation"))
    # 3. capital_lease_obligation_amortizes_correctly
    if abs(closing - max(0, opening - principal)) > tolerance:
      violations.append(
        {
          "quarter_index": quarter,
          "reason": "capital_lease_obligation_amortizes_correctly",
          "opening": opening,
          "principal": principal,
          "closing": closing,
        }
      )
    # 4. capital_lease_asset_depreciates_linearly
    expected_rou = max(0, int(round(intake_seed - per_quarter_depreciation * (index + 1))))
    if intake_seed > 0 and abs(rou_closing - expected_rou) > tolerance:
      violations.append(
        {
          "quarter_index": quarter,
          "reason": "capital_lease_asset_depreciates_linearly",
          "expected_rou": expected_rou,
          "actual_rou": rou_closing,
          "per_quarter_depreciation": int(round(per_quarter_depreciation)),
        }
      )
    # 5. capital_lease_interest_at_sba_rate
    expected_interest = int(round(opening * rate))
    if abs(interest - expected_interest) > tolerance:
      violations.append(
        {
          "quarter_index": quarter,
          "reason": "capital_lease_interest_at_sba_rate",
          "opening": opening,
          "interest_rate": rate,
          "expected_interest": expected_interest,
          "actual_interest": interest,
        }
      )
    # principal exceeds obligation (companion to invariant)
    if principal > opening + tolerance:
      violations.append(
        {
          "quarter_index": quarter,
          "reason": "principal_payment_exceeds_obligation",
          "opening": opening,
          "principal": principal,
        }
      )
    # negative asset depreciation guard
    if asset_dep < 0:
      violations.append(
        {
          "quarter_index": quarter,
          "reason": "lease_asset_depreciation_negative",
          "asset_depreciation": asset_dep,
        }
      )
    obligation = closing
    total_principal += principal
  # 9. lease_obligation_zero_at_term_end — once intake principal payments
  # are sufficient to retire the lease, obligation must be 0 thereafter.
  if intake_seed > 0 and total_principal >= intake_seed:
    found_nonzero_after_payoff = False
    running = intake_seed
    for row_index, row in enumerate(rows):
      principal = _safe_int(row.get("principal_payment"))
      closing = _safe_int(row.get("closing_balance"))
      running = max(0, running - principal)
      if running == 0 and closing > term_end_residual_tolerance(row_index + 1):
        found_nonzero_after_payoff = True
        violations.append(
          {
            "quarter_index": _safe_int(row.get("quarter_index")),
            "reason": "lease_obligation_zero_at_term_end",
            "closing_balance": closing,
          }
        )
        break
    if not found_nonzero_after_payoff:
      # explicit pass record — nothing to add
      pass
  quarters_seen = sorted(_safe_int(row.get("quarter_index")) for row in rows)
  if quarters_seen != list(range(1, horizon + 1)):
    violations.append(
      {
        "reason": "horizon_invalid",
        "expected_quarters": list(range(1, horizon + 1)),
        "actual_quarters": quarters_seen,
      }
    )
  return violations


def assert_capital_lease_schedule_payload_ready(
  capital_lease_schedule: Optional[Dict[str, Any]],
  *,
  model_input_json: Optional[Dict[str, Any]] = None,
  stage: str,
) -> None:
  violations = validate_capital_lease_schedule_payload(
    capital_lease_schedule=capital_lease_schedule,
    model_input_json=model_input_json,
  )
  if violations:
    fail_fast_raise(
      "capital_lease_builder_balance_drift",
      f"{stage}: capital_lease_schedule_payload_invalid: {violations[:20]}",
      phase=_FAIL_FAST_PHASE,
      stage=stage,
      details={"violations": violations[:20]},
    )
    # If fail_fast disabled in production mode, still surface via RuntimeError
    raise RuntimeError(f"{stage}: capital_lease_schedule_payload_invalid: {violations[:20]}")


def assert_finmo_matches_capital_lease_schedule(
  *,
  capital_lease_schedule: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
  tolerance: int = CAPITAL_LEASE_RECONCILE_TOLERANCE,
) -> None:
  """Cross-check that the snapshot payload agrees with FINMO's per-
  quarter fields. Drift here means snapshot reader / FINMO drift —
  hard-stop with named diagnostic.
  """
  payload = capital_lease_schedule if isinstance(capital_lease_schedule, dict) else {}
  rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
  finmo_by_quarter = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in _live_quarter_rows(finmo_json)
  }
  violations: List[Dict[str, Any]] = []
  for row in rows:
    quarter = _safe_int(row.get("quarter_index"))
    finmo_row = finmo_by_quarter.get(quarter) or {}
    comparisons = [
      ("opening_balance", "lease_opening_balance_total"),
      ("principal_payment", "lease_principal_repayments"),
      ("closing_balance", "lease_closing_balance_total"),
      ("interest_payment", "lease_interest_expense"),
      ("rou_asset_closing", "right_of_use_asset"),
      ("lease_asset_depreciation", "lease_asset_depreciation_expense"),
    ]
    for snapshot_field, finmo_field in comparisons:
      expected = _safe_int(row.get(snapshot_field))
      actual = _safe_int(finmo_row.get(finmo_field))
      if abs(expected - actual) > tolerance:
        violations.append(
          {
            "quarter_index": quarter,
            "snapshot_field": snapshot_field,
            "finmo_field": finmo_field,
            "snapshot_value": expected,
            "finmo_value": actual,
          }
        )
        break
  if violations:
    fail_fast_raise(
      "capital_lease_builder_balance_drift",
      f"{stage}: capital_lease_finmo_reconciliation_failed: {violations[:20]}",
      phase=_FAIL_FAST_PHASE,
      stage=stage,
      details={"violations": violations[:20]},
    )
    raise RuntimeError(f"{stage}: capital_lease_finmo_reconciliation_failed: {violations[:20]}")


def detect_orphaned_capital_lease_schedule(
  *,
  capital_lease_schedule: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  """Machinery fail-fast: workbook capital lease section showing
  non-zero values when no lease was authored. Helps catch the pre-iter
  orphan case from re-emerging after this iter.
  """
  intake_seed = capital_lease_opening_seed(
    model_input_json=model_input_json,
    finmo_payload=None,
  )
  payload = capital_lease_schedule if isinstance(capital_lease_schedule, dict) else {}
  rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
  if intake_seed > 0:
    return []
  orphaned: List[Dict[str, Any]] = []
  for row in rows:
    opening = _safe_int(row.get("opening_balance"))
    principal = _safe_int(row.get("principal_payment"))
    interest = _safe_int(row.get("interest_payment"))
    rou = _safe_int(row.get("rou_asset_closing"))
    if opening > 0 or principal > 0 or interest > 0 or rou > 0:
      orphaned.append(
        {
          "quarter_index": _safe_int(row.get("quarter_index")),
          "opening": opening,
          "principal": principal,
          "interest": interest,
          "rou": rou,
        }
      )
  return orphaned


def assert_no_orphaned_capital_lease_schedule(
  *,
  capital_lease_schedule: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  orphaned = detect_orphaned_capital_lease_schedule(
    capital_lease_schedule=capital_lease_schedule,
    model_input_json=model_input_json,
  )
  if orphaned:
    fail_fast_raise(
      "capital_lease_orphaned_schedule_in_workbook",
      f"{stage}: orphaned_capital_lease_section: {orphaned[:20]}",
      phase=_FAIL_FAST_PHASE,
      stage=stage,
      details={"orphaned_rows": orphaned[:20]},
    )
    raise RuntimeError(f"{stage}: orphaned_capital_lease_section: {orphaned[:20]}")


def fail_fast_lease_interest_components_misaligned(
  *,
  finmo_payload: Optional[Dict[str, Any]],
  stage: str,
  tolerance: int = CAPITAL_LEASE_RECONCILE_TOLERANCE,
) -> None:
  """Machinery fail-fast: P&L `interest` line must equal the sum of
  debt_interest_expense + lease_interest_expense per quarter.
  """
  violations: List[Dict[str, Any]] = []
  for row in _live_quarter_rows(finmo_payload):
    quarter = _safe_int(row.get("quarter_index"))
    interest_total = _safe_int(row.get("interest"))
    debt_interest = _safe_int(row.get("debt_interest_expense"))
    lease_interest = _safe_int(row.get("lease_interest_expense"))
    if abs(interest_total - (debt_interest + lease_interest)) > tolerance:
      violations.append(
        {
          "quarter_index": quarter,
          "interest_total": interest_total,
          "debt_interest": debt_interest,
          "lease_interest": lease_interest,
        }
      )
  if violations:
    fail_fast_raise(
      "capital_lease_interest_components_misaligned",
      f"{stage}: interest_total_does_not_equal_components_sum: {violations[:20]}",
      phase=_FAIL_FAST_PHASE,
      stage=stage,
      details={"violations": violations[:20]},
    )
    raise RuntimeError(f"{stage}: interest_total_does_not_equal_components_sum: {violations[:20]}")


def fail_fast_lease_depreciation_components_misaligned(
  *,
  finmo_payload: Optional[Dict[str, Any]],
  stage: str,
  tolerance: int = CAPITAL_LEASE_RECONCILE_TOLERANCE,
) -> None:
  """Machinery fail-fast: P&L `depreciation` line must equal the sum
  of ppe_depreciation_expense + lease_asset_depreciation_expense per
  quarter.
  """
  violations: List[Dict[str, Any]] = []
  for row in _live_quarter_rows(finmo_payload):
    quarter = _safe_int(row.get("quarter_index"))
    depreciation_total = _safe_int(row.get("depreciation"))
    ppe_dep = _safe_int(row.get("ppe_depreciation_expense"))
    lease_dep = _safe_int(row.get("lease_asset_depreciation_expense"))
    if abs(depreciation_total - (ppe_dep + lease_dep)) > tolerance:
      violations.append(
        {
          "quarter_index": quarter,
          "depreciation_total": depreciation_total,
          "ppe_depreciation": ppe_dep,
          "lease_asset_depreciation": lease_dep,
        }
      )
  if violations:
    fail_fast_raise(
      "capital_lease_asset_not_depreciating",
      f"{stage}: depreciation_total_does_not_equal_components_sum: {violations[:20]}",
      phase=_FAIL_FAST_PHASE,
      stage=stage,
      details={"violations": violations[:20]},
    )
    raise RuntimeError(f"{stage}: depreciation_total_does_not_equal_components_sum: {violations[:20]}")


def fail_fast_capital_lease_routing_double_count(
  *,
  finmo_payload: Optional[Dict[str, Any]],
  stage: str,
  tolerance: int = CAPITAL_LEASE_RECONCILE_TOLERANCE,
) -> None:
  """Machinery fail-fast: financing CF must subtract lease principal
  exactly once. Detect double-count by checking that the FCF formula
  uses each quarter's lease_principal_repayments exactly.
  """
  violations: List[Dict[str, Any]] = []
  for row in _live_quarter_rows(finmo_payload):
    quarter = _safe_int(row.get("quarter_index"))
    debt_issuance = _safe_int(row.get("debt_issuance"))
    debt_repayment = _safe_int(row.get("debt_repayment"))
    equity = _safe_int(row.get("equity"))
    distributions = _safe_int(row.get("owner_distributions"))
    lease_principal = _safe_int(row.get("lease_principal_repayments"))
    fcf_total = _safe_int(row.get("financing_cash_flow"))
    expected = debt_issuance - debt_repayment + equity - distributions - lease_principal
    if abs(fcf_total - expected) > tolerance:
      violations.append(
        {
          "quarter_index": quarter,
          "fcf_total": fcf_total,
          "expected": expected,
          "debt_issuance": debt_issuance,
          "debt_repayment": debt_repayment,
          "equity": equity,
          "distributions": distributions,
          "lease_principal": lease_principal,
        }
      )
  if violations:
    fail_fast_raise(
      "capital_lease_routing_double_count",
      f"{stage}: financing_cf_does_not_match_expected_components: {violations[:20]}",
      phase=_FAIL_FAST_PHASE,
      stage=stage,
      details={"violations": violations[:20]},
    )
    raise RuntimeError(f"{stage}: financing_cf_does_not_match_expected_components: {violations[:20]}")
