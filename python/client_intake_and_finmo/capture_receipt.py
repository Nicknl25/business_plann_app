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
  "financials.owner_compensation": ("total owner pay", "month"),
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


_NAME_KEYS = ("product_name", "lob_name", "role", "title", "name")


def _names_by_prefix(obj: Any, prefix: str) -> Dict[str, str]:
  """Every named node in a JSON-ish structure, keyed by its dotted path.

  CW-031 item 6/7: a multi-line business writes the SAME leaf on several
  product rows in one turn, and the receipt rendered each of them with the
  same words - "weekly capacity -> 420; weekly capacity -> 420; weekly
  capacity -> 420 (and 1 more)". The paths differed all along; only the
  rendering collapsed them. This map is what lets a repeated label say which
  line it belongs to.
  """
  out: Dict[str, str] = {}
  if isinstance(obj, dict):
    for key in _NAME_KEYS:
      value = obj.get(key)
      if isinstance(value, str) and value.strip():
        out[prefix] = value.strip()
        break
    for key, value in obj.items():
      name = str(key)
      if name.startswith("_"):
        continue
      out.update(_names_by_prefix(value, f"{prefix}.{name}" if prefix else name))
  elif isinstance(obj, list):
    for index, item in enumerate(obj):
      out.update(_names_by_prefix(item, f"{prefix}[{index}]"))
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
  # A requested field also counts as written when it landed on a NESTED
  # path with the same leaf (CW-010: unit_price wrote into
  # ops.lob_models[].products[].unit_price and the flat-path comparison
  # produced a false "I haven't recorded unit price yet" — a say-do
  # claim in the wrong direction). Leaf match is deliberately generous:
  # a false "dropped" note is worse than a missed one.
  written_leaves = {p.rsplit(".", 1)[-1] for p in written_fields}
  # CW-024 #89: "not recorded yet" is judged against the POST-WRITE
  # state, not the write-set. A field that already holds a value (from
  # this turn or any prior one) cannot be named "not recorded" - and a
  # derived twin (baseline_*, adjustments) is bookkeeping, never a
  # client-facing gap.
  after_leaves: Dict[str, float] = {}
  for domain in after:
    after_leaves.update(_numeric_leaves((after or {}).get(domain) or {}, domain))
  stored_fields = {re.sub(r"\[\d+\]", "", p) for p in after_leaves}
  stored_leaves = {p.rsplit(".", 1)[-1] for p in stored_fields}
  dropped = []
  for f in requested:
    if not f:
      continue
    base = re.sub(r"\[\d+\]", "", f)
    leaf = base.rsplit(".", 1)[-1]
    if base in written_fields or leaf in written_leaves:
      continue
    if base in stored_fields or leaf in stored_leaves:
      continue
    if leaf in _DERIVED_FIELDS or any(leaf.startswith(p) for p in _DERIVED_PREFIXES):
      continue
    dropped.append(f)
  # CW-024 #95: the capacity label's cadence comes from the STORED
  # state (same-turn writes are already in `after`), so "weekly
  # capacity" can never be said against a monthly-stored cadence.
  periods_by_prefix = {
    path.rsplit(".", 1)[0]: value
    for path, value in after_leaves.items()
    if path.rsplit(".", 1)[-1] == "operating_periods_per_year"
  }
  names_by_prefix: Dict[str, str] = {}
  for domain in after:
    names_by_prefix.update(
      _names_by_prefix((after or {}).get(domain) or {}, domain)
    )
  return {
    "written": written,
    "dropped": dropped,
    "clarify": clarify_pending or None,
    "periods_by_prefix": periods_by_prefix,
    "names_by_prefix": names_by_prefix,
  }


# Internal bookkeeping fields must NEVER surface in a client-facing
# receipt line (CW-009: "While finalizing I tidied the numbers:
# confidence → $1" - truthful, but internal state is not the client's
# number). Filtered out entirely, including the only-thing-changed case.
_INTERNAL_FIELDS = {
  "confidence",
  "wage_source",
  "months_until_hire",
}

# A field renders as currency ONLY when its name says money (CW-009:
# "operating periods per year → $12" - the old fallback dollared every
# unrecognized field). Counts render plain; everything else plain.
_MONEY_HINTS = (
  "price", "revenue", "expense", "cost", "cogs", "wage", "payroll",
  "rent", "cash", "debt", "equity", "asset", "balance", "capex",
  "lease", "marketing", "interest", "principal", "compensation",
  "budget", "total", "amount", "spend", "draw", "salary", "funding",
)
_COUNT_HINTS = (
  "num_", "count", "capacity", "periods", "employees", "headcount",
  "years", "months", "weeks", "days", "jobs", "hires", "units",
)


_CADENCE_LABELS = {1.0: "annual", 4.0: "quarterly", 12.0: "monthly", 52.0: "weekly"}


def _fmt(path: str, value: float, periods_by_prefix: Optional[Dict[str, float]] = None) -> str:
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
  # CW-017 (d): capacity labels are CADENCE-AWARE when the same turn
  # recorded the product's operating cadence - "a weekly capacity of
  # 160" on a 1-period/year product misstates the record the client
  # just corrected. Label from periods; static label only when the
  # cadence is not in this receipt.
  _leaf_raw = path.rsplit(".", 1)[-1]
  if _leaf_raw in ("units_per_week_capacity", "units_per_period_capacity"):
    _cadence = _CADENCE_LABELS.get(
      (periods_by_prefix or {}).get(path.rsplit(".", 1)[0]) or 0.0
    )
    if _cadence:
      label = f"{_cadence} capacity"
    elif _leaf_raw == "units_per_period_capacity":
      # CW-031 item 8: units_per_period_capacity is per WHATEVER period this
      # product runs on. With no cadence in the receipt, the static label
      # asserted "weekly" over a monthly unit. Say what is known instead.
      label = "capacity"
  leaf_name = base.rsplit(".", 1)[-1]
  if 0 < abs(value) < 1 and ("rate" in base or "percent" in base or "share" in base):
    rendered = f"{value * 100:.1f}%"
  elif any(h in leaf_name for h in _COUNT_HINTS):
    rendered = f"{value:,.0f}"
    per = None if "per_" in leaf_name or "periods" in leaf_name else per
  elif any(h in leaf_name for h in _MONEY_HINTS):
    rendered = f"${value:,.0f}"
  else:
    rendered = f"{value:,.0f}"
  return f"{label} → {rendered}" + (f" per {per}" if per else "")


def receipt_summary(receipt: Dict[str, Any], *, limit: int = 4) -> str:
  """Deterministic one-line summary of what ACTUALLY changed - the only
  legal source of numeric acknowledgment content. Empty string when
  nothing was written (callers must then not claim anything was)."""
  written = [
    w for w in ((receipt or {}).get("written") or [])
    if w[0].rsplit(".", 1)[-1].split("[")[0] not in _INTERNAL_FIELDS
  ]
  if not written:
    return ""
  primary = [w for w in written if w[0].rsplit(".", 1)[-1].split("[")[0] not in _DERIVED_FIELDS
             and not any(w[0].rsplit(".", 1)[-1].startswith(p) for p in _DERIVED_PREFIXES)]
  show = primary or written
  # CW-024 #95: stored-state cadence map (stamped by numeric_receipt)
  # first; write-set fallback keeps old receipts renderable.
  periods_by_prefix = dict((receipt or {}).get("periods_by_prefix") or {})
  for w in written:
    if w[0].rsplit(".", 1)[-1] == "operating_periods_per_year":
      periods_by_prefix[w[0].rsplit(".", 1)[0]] = float(w[2])
  names_by_prefix = dict((receipt or {}).get("names_by_prefix") or {})

  # CW-031 items 6 and 7. Rendering ran per path and never looked across the
  # line, so one turn touching four product rows produced four identical
  # phrases ("weekly capacity -> 420" x4, "utilization -> 62.0%" x3) and a
  # single row written twice produced the doubled line ("weekly capacity ->
  # 180; weekly capacity -> 180"). Both are rendering faults, not write
  # faults: identical phrasing collapses distinct rows, so name the row when
  # its phrase would otherwise repeat, and say a thing once when it is the
  # same thing.
  rendered = [
    (path, _fmt(path, new, periods_by_prefix)) for path, _old, new in show
  ]
  # Keyed on the LABEL, not the whole phrase: four lines reporting four
  # different capacities still read as one anonymous list of numbers unless
  # each says whose capacity it is.
  counts: Dict[str, int] = {}
  for _path, text_part in rendered:
    label_only = text_part.split(" → ")[0]
    counts[label_only] = counts.get(label_only, 0) + 1
  qualified: List[str] = []
  seen: set = set()
  for path, text_part in rendered:
    if counts.get(text_part.split(" → ")[0], 0) > 1:
      owner = names_by_prefix.get(path.rsplit(".", 1)[0])
      if owner:
        text_part = f"{owner}: {text_part}"
    if text_part in seen:
      continue
    seen.add(text_part)
    qualified.append(text_part)
  text = "; ".join(qualified[:limit])
  extra = len(qualified) - limit
  if extra > 0:
    text += f" (and {extra} more)"
  return text
