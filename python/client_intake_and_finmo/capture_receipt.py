"""Write-then-acknowledge: the numeric receipt (Layer 2 of the capture engine).

The false-confirmation class (CW-008): acknowledgment prose and the patch
are independent outputs of the same GPT call, so the model can SAY "I'll
keep marketing at $2,800/month" while the patch never writes it. The cure
is structural, not disciplinary: the acknowledgment is assembled FROM the
committed write-set, downstream of the write. A receipt can only be built
by diffing the persisted state, so an ack rendered from it cannot claim a
write that did not happen - at any field, by construction.

A clarifier turn is its own shape, not an empty receipt: when the
plausibility gate raises a question, nothing is written yet and the
question IS the turn ("I need to confirm X before I record it") - the
renderer must never read that as "nothing happened".

This module interprets nothing, converts nothing, and judges nothing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Fields that are derived twins or internal state - they change as a
# CONSEQUENCE of client-stated writes and would make receipts noisy.
# They are still diffed (completeness) but rendered only when no primary
# field changed alongside them.
_DERIVED_PREFIXES = ("baseline_", "_")
_DERIVED_FIELDS = {
  "cogs_percent_of_revenue",
  "marketing_percent_of_revenue",
  "cogs_total_year1",
  "payroll_total_year1",
  "current_cogs",
  "current_payroll",
  "marketing_adjustment",
  "payroll_adjustment",
  "cogs_adjustment",
}

_LABELS = {
  "financials.current_revenue": ("annual revenue", "year"),
  "financials.marketing_total_year1": ("marketing budget", "year"),
  "financials.owner_compensation": ("owner compensation", "month"),
  "financials.monthly_rent_expense": ("rent", "month"),
  "financials.other_operating_expense": ("other operating costs", "month"),
  "financials.other_monthly_debt_payments": ("other debt payments", "month"),
  "financials.initial_lease": ("equipment/space lease", "month"),
  "financials.current_num_employees": ("employee count", None),
  "financials.cash_on_hand": ("cash on hand", None),
  "financials.ar_balance": ("accounts receivable", None),
  "financials.ap_balance": ("operating payables", None),
  "financials.inventory_balance": ("inventory", None),
  "financials.total_debt_outstanding": ("outstanding debt", None),
  "financials.initial_equity": ("initial equity", None),
  "financials.initial_assets": ("initial assets", None),
  "financials.current_capex": ("capital spending", None),
  "financials.annual_interest_payment": ("annual interest", "year"),
  "financials.annual_principal_payment": ("annual principal", "year"),
  "people.rest_of_team_payroll_year1": ("rest-of-team payroll", "year"),
  "ops.unit_price": ("unit price", None),
  "ops.units_per_week_capacity": ("weekly capacity", None),
  "ops.units_per_period_capacity": ("capacity per period", None),
  "ops.utilization_rate": ("utilization", None),
}


def _is_number(value: Any) -> bool:
  return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_leaves(obj: Any, prefix: str) -> Dict[str, float]:
  """Every numeric leaf in a JSON-ish structure, keyed by dotted path.
  Underscore-prefixed keys are internal state and excluded."""
  out: Dict[str, float] = {}
  if isinstance(obj, dict):
    for key, value in obj.items():
      name = str(key)
      if name.startswith("_"):
        continue
      out.update(_numeric_leaves(value, f"{prefix}.{name}" if prefix else name))
  elif isinstance(obj, list):
    for index, item in enumerate(obj):
      out.update(_numeric_leaves(item, f"{prefix}[{index}]"))
  elif _is_number(obj):
    out[prefix] = float(obj)
  return out


def numeric_receipt(
  *,
  before: Dict[str, Any],
  after: Dict[str, Any],
  requested_fields: Optional[List[str]] = None,
  clarify_pending: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Diff numeric leaves across {domain: json} snapshots taken before and
  after the turn's appliers ran. `after` must be the PERSISTED (or
  about-to-persist, same-object) state - the receipt is downstream of the
  write by construction."""
  written: List[Tuple[str, Optional[float], float]] = []
  for domain in after:
    b = _numeric_leaves((before or {}).get(domain) or {}, domain)
    a = _numeric_leaves((after or {}).get(domain) or {}, domain)
    for path, new_value in a.items():
      old_value = b.get(path)
      if old_value is None or abs(new_value - old_value) > 1e-9:
        if old_value is None and abs(new_value) < 1e-12:
          continue  # a zero materializing from a default is not a write
        written.append((path, old_value, new_value))
  requested = [str(f) for f in (requested_fields or [])]
  written_fields = {re.sub(r"\[\d+\]", "", p) for p, _, _ in written}
  dropped = [
    f for f in requested
    if f and re.sub(r"\[\d+\]", "", f) not in written_fields
  ]
  return {
    "written": written,
    "dropped": dropped,
    "clarify": clarify_pending or None,
  }


def _fmt(path: str, value: float) -> str:
  base = re.sub(r"\[\d+\]", "", path)
  label, per = _LABELS.get(base, (None, None))
  if label is None:
    leaf = base.rsplit(".", 1)[-1]
    domain = base.split(".", 1)[0]
    label, per = _LABELS.get(f"{domain}.{leaf}", (None, None))
  if label is None:
    tail = base.rsplit(".", 1)[-1].replace("_", " ")
    label = tail
    per = "month" if "monthly" in base else ("year" if ("annual" in base or "year1" in base) else None)
  if 0 < abs(value) < 1 and ("rate" in base or "percent" in base or "share" in base):
    rendered = f"{value * 100:.1f}%"
  elif "num_" in base or "count" in base or "capacity" in base:
    rendered = f"{value:,.0f}"
  else:
    rendered = f"${value:,.0f}"
  return f"{label} → {rendered}" + (f" per {per}" if per else "")


def receipt_summary(receipt: Dict[str, Any], *, limit: int = 4) -> str:
  """Deterministic one-line summary of what ACTUALLY changed - the only
  legal source of numeric acknowledgment content. Empty string when
  nothing was written (callers must then not claim anything was)."""
  written = list((receipt or {}).get("written") or [])
  if not written:
    return ""
  primary = [w for w in written if w[0].rsplit(".", 1)[-1].split("[")[0] not in _DERIVED_FIELDS
             and not any(w[0].rsplit(".", 1)[-1].startswith(p) for p in _DERIVED_PREFIXES)]
  show = primary or written
  parts = [_fmt(path, new) for path, _old, new in show[:limit]]
  extra = len(show) - limit
  text = "; ".join(parts)
  if extra > 0:
    text += f" (and {extra} more)"
  return text
