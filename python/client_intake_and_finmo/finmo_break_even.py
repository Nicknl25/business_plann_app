"""W1 — break-even as a DERIVED READ-OUT of the finished model.

Ruled in docs/WRITING_PHASE_RESEARCH_2.md (R5) and Nick's W1 brief
(2026-08-18). This module is a pure post-process: it reads the typed
model inputs (``FinancialModelInputs``) and the engine's computed
quarter rows and returns ``finmo_json["break_even"]``. It writes NOTHING
back into any driver, row, or engine value — no feedback, no engine
math. ``finmo_model.py`` is untouched.

Methodology (ruled):
  fixed_q     = payroll + lease + depreciation + interest   (P&L $ amounts)
  variable_q  = sum of the expense ratios the engine multiplies by
                REVENUE (COGS, Marketing, R&D, G&A today) — classified
                from ``FORMULA_REGISTRY`` ("Revenue * expenses::<label>")
                and the row's ``value_kind == "ratio"``, NOT from a
                hardcoded label list, so a new revenue-ratio row is
                picked up and the ``Interest Rate`` / ``Taxes`` /
                ``Depreciation`` ratio rows (which the engine applies to
                debt / pre-tax income / PPE) are never misfiled.
  cm_ratio    = 1 - variable_q
  be_revenue  = fixed_q / cm_ratio          (HEADLINE, ruled formula)
  be_revenue_ebitda_basis = (payroll + lease) / cm_ratio
                (the revenue at which EBITDA crosses zero — the basis
                ``first_ebitda_positive_quarter`` is measured on)
  cash_be_revenue = (payroll + lease + interest + scheduled principal
                (debt repayment + capital-lease principal)) / cm_ratio
                (depreciation is non-cash and excluded; principal added)
  be_revenue_g_and_a_fixed_sensitivity: G&A $ moved into fixed and its
                ratio removed from variable — the economically-honest
                alternative, DISCLOSED alongside, never the headline.
  per_line[]  = blended-mix BE units: be_revenue * mix_share / price.
                NO line-standalone BE (fixed costs are not attributable
                per line and must not be fabricated).
Owner compensation sits inside payroll (prior ruling) → included in
fixed → BE is lender-correct; the ``methodology.notes`` say so.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
  from financial_model_engine.finmo_model import FORMULA_REGISTRY
  from financial_model_engine.model_inputs import _adapter_default_semantics
except Exception:  # pragma: no cover - path shim mirrors finmo_bridge
  import sys
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[1]
  if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
  from financial_model_engine.finmo_model import FORMULA_REGISTRY
  from financial_model_engine.model_inputs import _adapter_default_semantics

BREAK_EVEN_VERSION = "break_even_v1"

_METHODOLOGY_NOTES = [
  "Fixed costs = payroll + lease/rent + depreciation + interest, taken from the model's P&L amounts each quarter.",
  "Variable costs = the expense ratios the model applies to revenue (cost of goods sold, marketing, research & development, general & administrative). They are treated as variable because the model treats them that way; general & administrative is shown as a fixed-cost sensitivity as well.",
  "Owner compensation is inside payroll, so break-even includes it (lender-correct).",
  "Depreciation and interest are balance-driven in the model; treating them as fixed within a quarter is an approximation.",
  "Headline break-even revenue = fixed costs / contribution-margin ratio (pre-tax accounting basis). EBITDA-basis break-even excludes depreciation and interest; cash break-even excludes depreciation but adds scheduled principal payments.",
  "Per-line break-even units use the plan's revenue mix (blended break-even revenue x mix share / unit price). No line-standalone break-even is computed because fixed costs are not attributable per line.",
]


def _f(value: Any) -> float:
  try:
    out = float(value)
  except Exception:
    return 0.0
  if out != out:  # NaN
    return 0.0
  return out


def _r(value: Optional[float], digits: int = 6) -> Optional[float]:
  if value is None:
    return None
  return round(float(value), digits)


def _revenue_ratio_expense_labels() -> List[str]:
  """P&L labels whose registered engine formula is ``Revenue * expenses::<label>``
  (FORMULA_REGISTRY is the engine's own declaration of what scales with
  revenue). Today: Cost of Goods Sold, Marketing, Research & Development,
  General & Administrative. Interest Rate / Taxes / Depreciation are ratio
  rows too but are NOT applied to revenue and so are excluded here."""
  return [
    str(key)
    for key, formula in FORMULA_REGISTRY.items()
    if str(formula or "").startswith("Revenue * expenses::")
  ]


def _pl_field_for_label(label: str) -> str:
  """P&L label -> FinmoQuarterResult field ('Cost of Goods Sold' ->
  'cost_of_goods_sold', 'Research & Development' -> 'research_and_development')."""
  return str(label).strip().lower().replace("&", "and").replace("/", " ").replace("  ", " ").replace(" ", "_")


def _variable_ratio_components(
  book: Any,
  row: Dict[str, Any],
  quarter_index: int,
  revenue_ratio_labels: List[str],
) -> Dict[str, float]:
  """Per-quarter variable ratios. CLASSIFICATION keys off the expense row's
  value_kind == 'ratio' (falling back to the engine's default table when the
  row was created by a typed setter and carries none) AND the engine applying
  the row to revenue (FORMULA_REGISTRY). The VALUE is what the engine actually
  charged this quarter: P&L amount / revenue (falls back to the driver ratio
  when revenue is zero). Keys are the P&L labels."""
  out: Dict[str, float] = {}
  expense_rows = getattr(book, "expense_rows", {}) or {}
  revenue = _f(row.get("revenue"))
  for label, erow in expense_rows.items():
    value_kind = str(getattr(erow, "value_kind", "") or "").strip()
    if not value_kind:
      value_kind = _adapter_default_semantics("expenses", str(label))[0]
    if value_kind != "ratio":
      continue
    if str(label) not in revenue_ratio_labels:
      continue
    field = _pl_field_for_label(str(label))
    if revenue > 0 and field in row:
      out[str(label)] = max(0.0, _f(row.get(field)) / revenue)
    else:
      try:
        out[str(label)] = max(0.0, _f(erow.get_value(quarter_index)))
      except Exception:
        out[str(label)] = 0.0
  return out


def _component_key(label: str) -> str:
  mapping = {
    "Cost of Goods Sold": "cogs",
    "Marketing": "marketing",
    "Research & Development": "r_and_d",
    "General & Administrative": "g_and_a",
  }
  return mapping.get(label, label.lower().replace(" & ", "_and_").replace(" ", "_"))


def _quarter_block(
  *,
  book: Any,
  row: Dict[str, Any],
  quarter_index: int,
  revenue_ratio_labels: List[str],
) -> Dict[str, Any]:
  payroll = _f(row.get("payroll"))
  lease = _f(row.get("lease_rent"))
  depreciation = _f(row.get("depreciation"))
  interest = _f(row.get("interest"))
  fixed_costs = payroll + lease + depreciation + interest
  scheduled_principal = _f(row.get("debt_repayment")) + _f(row.get("lease_principal_repayments"))

  revenue = _f(row.get("revenue"))
  ratio_by_label = _variable_ratio_components(book, row, quarter_index, revenue_ratio_labels)
  # Per-line COGS: when EVERY product carries a per-line percent the engine
  # charges SUM(line_rev x line_pct); P&L COGS / revenue is then the mix-
  # weighted blend - the honest quarter figure - and that is what is read.
  variable_components = {_component_key(label): _r(v) for label, v in ratio_by_label.items()}
  cogs_key = _component_key("Cost of Goods Sold")
  variable_ratio = sum(_f(v) for v in variable_components.values())
  cm_ratio = 1.0 - variable_ratio

  g_and_a_amount = _f(row.get("general_and_administrative"))
  g_and_a_ratio = _f(variable_components.get("g_and_a"))

  def _be(fixed: float, cm: float) -> Optional[float]:
    if cm <= 0:
      return None
    return fixed / cm

  be_revenue = _be(fixed_costs, cm_ratio)
  be_revenue_ebitda_basis = _be(payroll + lease, cm_ratio)
  cash_be_revenue = _be(payroll + lease + interest + scheduled_principal, cm_ratio)
  be_g_and_a_fixed = _be(fixed_costs + g_and_a_amount, cm_ratio + g_and_a_ratio)
  margin_of_safety = None
  if be_revenue is not None and revenue > 0:
    margin_of_safety = (revenue - be_revenue) / revenue

  # Per-line (blended mix): drivers from the typed quarter.
  per_line: List[Dict[str, Any]] = []
  try:
    quarter = book.quarter(quarter_index)
  except Exception:
    quarter = None
  if quarter is not None:
    blended_cogs = _f(variable_components.get(cogs_key))
    other_ratio = variable_ratio - blended_cogs
    for group in getattr(quarter, "revenue_groups", []) or []:
      for product in getattr(group, "products", []) or []:
        drivers = getattr(product, "drivers", None)
        price = _f(getattr(drivers, "unit_price", 0.0))
        units_planned = _f(getattr(drivers, "units", 0.0))
        line_revenue = _f(getattr(drivers, "revenue", 0.0))
        line_cogs = getattr(product, "cogs_percent", None)
        cogs_pct = _f(line_cogs) if line_cogs is not None else blended_cogs
        cm_per_unit = price * (1.0 - cogs_pct - other_ratio)
        mix_share = (line_revenue / revenue) if revenue > 0 else 0.0
        be_units = None
        if be_revenue is not None and price > 0:
          be_units = be_revenue * mix_share / price
        per_line.append(
          {
            "slot_key": str(getattr(product, "revenue_slot_key", "") or ""),
            "lob": str(getattr(product, "lob_name", "") or ""),
            "product": str(getattr(product, "product_name", "") or ""),
            "price": _r(price),
            "units_planned": _r(units_planned),
            "cogs_pct": _r(cogs_pct),
            "cogs_pct_source": "per_line" if line_cogs is not None else "blended",
            "cm_per_unit": _r(cm_per_unit),
            "mix_share": _r(mix_share),
            "be_units": _r(be_units),
          }
        )

  return {
    "quarter_index": int(quarter_index),
    "fixed_costs": _r(fixed_costs),
    "fixed_components": {
      "payroll": _r(payroll),
      "lease": _r(lease),
      "depreciation": _r(depreciation),
      "interest": _r(interest),
    },
    "variable_ratio": _r(variable_ratio),
    "variable_components": variable_components,
    "cm_ratio": _r(cm_ratio),
    "be_revenue": _r(be_revenue),
    "be_revenue_ebitda_basis": _r(be_revenue_ebitda_basis),
    "cash_be_revenue": _r(cash_be_revenue),
    "scheduled_principal": _r(scheduled_principal),
    "be_revenue_g_and_a_fixed_sensitivity": _r(be_g_and_a_fixed),
    "planned_revenue": _r(revenue),
    "ebitda": _r(_f(row.get("ebitda"))),
    "margin_of_safety": _r(margin_of_safety),
    "per_line": per_line,
  }


def _period_aggregate(quarters: List[Dict[str, Any]], key_fixed: str = "fixed_costs") -> Dict[str, Any]:
  """Annualized BE over a set of quarters: sum(fixed) / (1 - sum(variable $)/sum(revenue))."""
  if not quarters:
    return {"be_revenue": None, "cash_be_revenue": None, "be_revenue_ebitda_basis": None, "planned_revenue": None, "margin_of_safety": None}
  revenue = sum(_f(q.get("planned_revenue")) for q in quarters)
  variable_dollars = sum(_f(q.get("variable_ratio")) * _f(q.get("planned_revenue")) for q in quarters)
  fixed = sum(_f(q.get(key_fixed)) for q in quarters)
  ebitda_fixed = sum(_f(q["fixed_components"].get("payroll")) + _f(q["fixed_components"].get("lease")) for q in quarters)
  cash_fixed = sum(
    _f(q["fixed_components"].get("payroll")) + _f(q["fixed_components"].get("lease")) + _f(q["fixed_components"].get("interest")) + _f(q.get("scheduled_principal"))
    for q in quarters
  )
  cm = 1.0 - (variable_dollars / revenue) if revenue > 0 else None
  def _be(f: float) -> Optional[float]:
    if cm is None or cm <= 0:
      return None
    return f / cm
  be = _be(fixed)
  return {
    "quarters": [int(q.get("quarter_index")) for q in quarters],
    "fixed_costs": _r(fixed),
    "cm_ratio": _r(cm),
    "be_revenue": _r(be),
    "be_revenue_ebitda_basis": _r(_be(ebitda_fixed)),
    "cash_be_revenue": _r(_be(cash_fixed)),
    "planned_revenue": _r(revenue),
    "margin_of_safety": _r((revenue - be) / revenue) if (be is not None and revenue > 0) else None,
  }


def compute_break_even_block(*, book: Any, quarter_rows_raw: List[Dict[str, Any]]) -> Dict[str, Any]:
  """Return the ``finmo_json["break_even"]`` block. Pure; no side effects."""
  revenue_ratio_labels = _revenue_ratio_expense_labels()
  quarters: List[Dict[str, Any]] = []
  for idx, row in enumerate(quarter_rows_raw, start=1):
    if not isinstance(row, dict):
      continue
    q_index = int(_f(row.get("quarter_index")) or idx)
    quarters.append(
      _quarter_block(book=book, row=row, quarter_index=q_index, revenue_ratio_labels=revenue_ratio_labels)
    )

  first_positive: Optional[int] = None
  for q in quarters:
    if _f(q.get("ebitda")) >= 0.0:
      first_positive = int(q["quarter_index"])
      break

  q1 = quarters[0] if quarters else None
  y1 = _period_aggregate([q for q in quarters if 1 <= int(q["quarter_index"]) <= 4])
  y5 = _period_aggregate([q for q in quarters if 17 <= int(q["quarter_index"]) <= 20])
  summary = {
    "first_ebitda_positive_quarter": first_positive,
    "q1": {
      "be_revenue": q1.get("be_revenue") if q1 else None,
      "be_revenue_ebitda_basis": q1.get("be_revenue_ebitda_basis") if q1 else None,
      "cash_be_revenue": q1.get("cash_be_revenue") if q1 else None,
      "planned_revenue": q1.get("planned_revenue") if q1 else None,
      "margin_of_safety": q1.get("margin_of_safety") if q1 else None,
      "be_revenue_g_and_a_fixed_sensitivity": q1.get("be_revenue_g_and_a_fixed_sensitivity") if q1 else None,
    },
    "y1_annualized": y1,
    "y5_annualized": y5,
    "cash_be_revenue": q1.get("cash_be_revenue") if q1 else None,
  }
  return {
    "version": BREAK_EVEN_VERSION,
    "basis": {
      "headline": "pre_tax_accounting",
      "fixed_components": ["payroll", "lease", "depreciation", "interest"],
      "variable_components": [_component_key(label) for label in revenue_ratio_labels],
      "owner_compensation_in_payroll": True,
      "line_standalone_break_even": False,
    },
    "methodology": {"notes": list(_METHODOLOGY_NOTES)},
    "summary": summary,
    "quarters": quarters,
  }
