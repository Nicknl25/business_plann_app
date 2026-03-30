from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


QUARTER_COUNT = 20


def _safe_float(value: Any, default: float = 0.0) -> float:
  if value in {None, ""}:
    return default
  try:
    return float(value)
  except Exception:
    return default


def _safe_int(value: Any, default: int = 0) -> int:
  if value in {None, ""}:
    return default
  try:
    return int(float(value))
  except Exception:
    return default


def _text(value: Any) -> str:
  return str(value or "").strip()


def _quarter_index(value: Any) -> int:
  quarter_index = _safe_int(value, default=1)
  return min(max(1, quarter_index), QUARTER_COUNT)


def _governed_values(values: List[Any]) -> List[float]:
  normalized = [_safe_float(item) for item in (values or [])]
  if len(normalized) == QUARTER_COUNT + 1:
    return normalized[1:]
  return normalized[:QUARTER_COUNT]


@dataclass(slots=True)
class RevenueDriverSet:
  capacity_units: float = 0.0
  unit_price: float = 0.0
  utilization: float = 0.0

  @property
  def units(self) -> float:
    return max(0.0, self.capacity_units) * max(0.0, self.utilization)

  @property
  def revenue(self) -> float:
    return self.units * max(0.0, self.unit_price)

  def to_dict(self) -> Dict[str, float]:
    return {
      "capacity_units": round(self.capacity_units, 6),
      "unit_price": round(self.unit_price, 6),
      "utilization": round(self.utilization, 6),
      "units": round(self.units, 6),
      "revenue": round(self.revenue, 6),
    }


@dataclass(slots=True)
class ControllerWriteRow:
  section: str
  label: str
  values: List[float] = field(default_factory=list)
  named_range: str = ""
  lever_id: str = ""
  value_kind: str = ""
  input_semantics: str = ""

  def __post_init__(self) -> None:
    if not self.values:
      self.values = [0.0 for _ in range(QUARTER_COUNT)]
    elif len(self.values) < QUARTER_COUNT:
      self.values.extend([0.0 for _ in range(QUARTER_COUNT - len(self.values))])
    elif len(self.values) > QUARTER_COUNT:
      self.values = list(self.values[:QUARTER_COUNT])

  def set_value(self, quarter_index: int, value: Any) -> None:
    self.values[_quarter_index(quarter_index) - 1] = _safe_float(value)

  def get_value(self, quarter_index: int) -> float:
    return _safe_float(self.values[_quarter_index(quarter_index) - 1])

  def to_model_input_row(self) -> Dict[str, Any]:
    return {
      "named_range": self.named_range,
      "controller_write": True,
      "lever_id": self.lever_id,
      "label": self.label,
      "value_kind": self.value_kind,
      "input_semantics": self.input_semantics,
      "values": [round(_safe_float(value), 6) for value in self.values],
    }


@dataclass(slots=True)
class QuarterRevenueProduct:
  lob_name: str
  product_name: str
  revenue_slot_key: str = ""
  drivers: RevenueDriverSet = field(default_factory=RevenueDriverSet)

  def lever_id(self, driver_name: str) -> str:
    return "::".join(
      [
        "revenue",
        _text(self.lob_name),
        _text(self.product_name),
        _text(driver_name),
      ]
    )

  def to_controller_product(self) -> Dict[str, Any]:
    return {
      "product_name": self.product_name,
      "revenue_slot_key": self.revenue_slot_key,
      "capacity_units": round(self.drivers.capacity_units, 6),
      "utilization": round(self.drivers.utilization, 6),
      "units": round(self.drivers.units, 6),
      "price": round(self.drivers.unit_price, 6),
    }


@dataclass(slots=True)
class QuarterRevenueProductGroup:
  lob_name: str
  products: List[QuarterRevenueProduct] = field(default_factory=list)

  @property
  def revenue(self) -> float:
    return sum(item.drivers.revenue for item in self.products)

  def to_controller_group(self) -> Dict[str, Any]:
    return {
      "lob_name": self.lob_name,
      "products": [item.to_controller_product() for item in self.products],
    }


@dataclass(slots=True)
class ExpenseDriverSet:
  cogs_percent: float = 0.0
  marketing_percent: float = 0.0
  r_and_d_percent: float = 0.0
  lease_amount: float = 0.0
  payroll_amount: float = 0.0
  g_and_a_percent: float = 0.0
  interest_rate: float = 0.0
  depreciation_percent: float = 0.0
  tax_percent: float = 0.0
  capex: float = 0.0
  working_capital: Dict[str, Any] = field(default_factory=dict)

  def to_controller_expenses(self) -> Dict[str, Any]:
    return {
      "cogs_percent": round(self.cogs_percent, 6),
      "marketing_percent": round(self.marketing_percent, 6),
      "r_and_d_percent": round(self.r_and_d_percent, 6),
      "lease_amount": round(self.lease_amount, 6),
      "payroll_amount": round(self.payroll_amount, 6),
      "g_and_a_percent": round(self.g_and_a_percent, 6),
      "interest_rate": round(self.interest_rate, 6),
      "depreciation_percent": round(self.depreciation_percent, 6),
      "tax_percent": round(self.tax_percent, 6),
      "capex": round(self.capex, 6),
      "working_capital": self.working_capital,
    }


@dataclass(slots=True)
class FinancialModelQuarter:
  quarter_index: int
  revenue_groups: List[QuarterRevenueProductGroup] = field(default_factory=list)
  expenses: ExpenseDriverSet = field(default_factory=ExpenseDriverSet)

  @property
  def revenue(self) -> float:
    return sum(group.revenue for group in self.revenue_groups)

  def find_or_create_group(self, lob_name: str) -> QuarterRevenueProductGroup:
    target_lob = _text(lob_name)
    for group in self.revenue_groups:
      if _text(group.lob_name) == target_lob:
        return group
    next_group = QuarterRevenueProductGroup(lob_name=target_lob)
    self.revenue_groups.append(next_group)
    return next_group

  def find_or_create_product(
    self,
    *,
    lob_name: str,
    product_name: str,
    revenue_slot_key: str = "",
  ) -> QuarterRevenueProduct:
    group = self.find_or_create_group(lob_name)
    target_product = _text(product_name)
    target_slot_key = _text(revenue_slot_key)
    for product in group.products:
      if target_slot_key and _text(product.revenue_slot_key) == target_slot_key:
        return product
      if _text(product.product_name) == target_product:
        return product
    next_product = QuarterRevenueProduct(
      lob_name=group.lob_name,
      product_name=target_product,
      revenue_slot_key=target_slot_key,
    )
    group.products.append(next_product)
    return next_product

  def to_controller_seed_entry(self) -> Dict[str, Any]:
    payload = {
      "quarter_index": self.quarter_index,
      "revenue_products": [group.to_controller_group() for group in self.revenue_groups],
      "revenue": round(self.revenue, 6),
    }
    payload.update(self.expenses.to_controller_expenses())
    return payload


@dataclass(slots=True)
class FinancialModelInputs:
  start_date: str = ""
  business_name: str = ""
  quarter_count: int = QUARTER_COUNT
  quarters: List[FinancialModelQuarter] = field(default_factory=list)
  expense_rows: Dict[str, ControllerWriteRow] = field(default_factory=dict)
  balance_sheet_rows: Dict[str, ControllerWriteRow] = field(default_factory=dict)
  schedule_rows: Dict[str, ControllerWriteRow] = field(default_factory=dict)
  debt_opening_balance_seed: float = 0.0
  lease_opening_balance_seed: float = 0.0

  def __post_init__(self) -> None:
    if not self.quarters:
      self.quarters = [
        FinancialModelQuarter(quarter_index=index)
        for index in range(1, self.quarter_count + 1)
      ]

  @classmethod
  def empty(
    cls,
    *,
    start_date: str = "",
    business_name: str = "",
    quarter_count: int = QUARTER_COUNT,
  ) -> "FinancialModelInputs":
    return cls(
      start_date=_text(start_date),
      business_name=_text(business_name),
      quarter_count=max(1, _safe_int(quarter_count, QUARTER_COUNT)),
      quarters=[],
    )

  @classmethod
  def from_model_input_json(cls, model_input_json: Dict[str, Any]) -> "FinancialModelInputs":
    sections = (model_input_json.get("sections") or {}) if isinstance(model_input_json.get("sections"), dict) else {}
    next_book = cls.empty(
      start_date=_text(model_input_json.get("start_date")),
      business_name=_text(model_input_json.get("business_name")),
      quarter_count=QUARTER_COUNT,
    )
    for row in sections.get("revenue") or []:
      if not isinstance(row, dict):
        continue
      values = list(row.get("values") or [])
      for index, raw_value in enumerate(_governed_values(values), start=1):
        product = next_book.quarter(index).find_or_create_product(
          lob_name=_text(row.get("lob")) or "LOB 1",
          product_name=_text(row.get("product")) or "Product 1",
          revenue_slot_key=_text(row.get("revenue_slot_key")),
        )
        driver = _text(row.get("driver"))
        if driver == "Capacity":
          product.drivers.capacity_units = _safe_float(raw_value)
        elif driver == "Unit Price":
          product.drivers.unit_price = _safe_float(raw_value)
        elif driver == "Utilization":
          product.drivers.utilization = _safe_float(raw_value)
    next_book._load_simple_rows(
      section_name="expenses",
      rows=sections.get("expenses") or [],
      named_range="model_input_expenses",
      target=next_book.expense_rows,
    )
    next_book._load_simple_rows(
      section_name="balance_sheet",
      rows=sections.get("balance_sheet") or [],
      named_range="model_input_balancehseet",
      target=next_book.balance_sheet_rows,
    )
    schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
    next_book.debt_opening_balance_seed = _safe_float(schedules.get("debt_opening_balance_seed"))
    next_book.lease_opening_balance_seed = _safe_float(schedules.get("lease_opening_balance_seed"))
    next_book._load_simple_rows(
      section_name="schedules",
      rows=schedules.get("rows") or [],
      named_range="model_input_schedules",
      target=next_book.schedule_rows,
    )
    next_book._sync_known_expense_drivers_from_rows()
    return next_book

  @classmethod
  def from_controller_seed(
    cls,
    controller_input_seed: List[Dict[str, Any]],
    *,
    start_date: str = "",
    business_name: str = "",
  ) -> "FinancialModelInputs":
    next_book = cls.empty(start_date=start_date, business_name=business_name)
    for item in controller_input_seed or []:
      if not isinstance(item, dict):
        continue
      quarter = next_book.quarter(_quarter_index(item.get("quarter_index")))
      for group in item.get("revenue_products") or []:
        if not isinstance(group, dict):
          continue
        lob_name = _text(group.get("lob_name")) or "LOB 1"
        for product in group.get("products") or []:
          if not isinstance(product, dict):
            continue
          product_entry = quarter.find_or_create_product(
            lob_name=lob_name,
            product_name=_text(product.get("product_name")) or "Product 1",
            revenue_slot_key=_text(product.get("revenue_slot_key")),
          )
          product_entry.drivers.capacity_units = _safe_float(product.get("capacity_units"))
          product_entry.drivers.unit_price = _safe_float(product.get("price"))
          product_entry.drivers.utilization = _safe_float(product.get("utilization"))
      quarter.expenses.cogs_percent = _safe_float(item.get("cogs_percent"))
      quarter.expenses.marketing_percent = _safe_float(item.get("marketing_percent"))
      quarter.expenses.r_and_d_percent = _safe_float(item.get("r_and_d_percent"))
      quarter.expenses.lease_amount = _safe_float(item.get("lease_amount"))
      quarter.expenses.payroll_amount = _safe_float(item.get("payroll_amount"))
      quarter.expenses.g_and_a_percent = _safe_float(item.get("g_and_a_percent"))
      quarter.expenses.interest_rate = _safe_float(item.get("interest_rate"))
      quarter.expenses.depreciation_percent = _safe_float(item.get("depreciation_percent"))
      quarter.expenses.tax_percent = _safe_float(item.get("tax_percent"))
      quarter.expenses.capex = _safe_float(item.get("capex"))
      quarter.expenses.working_capital = item.get("working_capital") if isinstance(item.get("working_capital"), dict) else {}
    next_book._sync_rows_from_known_expense_drivers()
    return next_book

  def quarter(self, quarter_index: int) -> FinancialModelQuarter:
    normalized = _quarter_index(quarter_index)
    while len(self.quarters) < normalized:
      self.quarters.append(FinancialModelQuarter(quarter_index=len(self.quarters) + 1))
    return self.quarters[normalized - 1]

  def set_revenue_drivers(
    self,
    *,
    quarter_index: int,
    lob_name: str,
    product_name: str,
    capacity_units: Optional[float] = None,
    unit_price: Optional[float] = None,
    utilization: Optional[float] = None,
    revenue_slot_key: str = "",
  ) -> None:
    product = self.quarter(quarter_index).find_or_create_product(
      lob_name=lob_name,
      product_name=product_name,
      revenue_slot_key=revenue_slot_key,
    )
    if capacity_units is not None:
      product.drivers.capacity_units = _safe_float(capacity_units)
    if unit_price is not None:
      product.drivers.unit_price = _safe_float(unit_price)
    if utilization is not None:
      product.drivers.utilization = _safe_float(utilization)

  def set_expense_drivers(
    self,
    *,
    quarter_index: int,
    cogs_percent: Optional[float] = None,
    marketing_percent: Optional[float] = None,
    r_and_d_percent: Optional[float] = None,
    lease_amount: Optional[float] = None,
    payroll_amount: Optional[float] = None,
    g_and_a_percent: Optional[float] = None,
    interest_rate: Optional[float] = None,
    depreciation_percent: Optional[float] = None,
    tax_percent: Optional[float] = None,
    capex: Optional[float] = None,
    working_capital: Optional[Dict[str, Any]] = None,
  ) -> None:
    expenses = self.quarter(quarter_index).expenses
    if cogs_percent is not None:
      expenses.cogs_percent = _safe_float(cogs_percent)
    if marketing_percent is not None:
      expenses.marketing_percent = _safe_float(marketing_percent)
    if r_and_d_percent is not None:
      expenses.r_and_d_percent = _safe_float(r_and_d_percent)
    if lease_amount is not None:
      expenses.lease_amount = _safe_float(lease_amount)
    if payroll_amount is not None:
      expenses.payroll_amount = _safe_float(payroll_amount)
    if g_and_a_percent is not None:
      expenses.g_and_a_percent = _safe_float(g_and_a_percent)
    if interest_rate is not None:
      expenses.interest_rate = _safe_float(interest_rate)
    if depreciation_percent is not None:
      expenses.depreciation_percent = _safe_float(depreciation_percent)
    if tax_percent is not None:
      expenses.tax_percent = _safe_float(tax_percent)
    if capex is not None:
      expenses.capex = _safe_float(capex)
    if working_capital is not None:
      expenses.working_capital = working_capital
    self._sync_row_from_known_expense_driver(_quarter_index(quarter_index))

  def set_simple_driver(
    self,
    *,
    section: str,
    label: str,
    quarter_index: int,
    value: Any,
    named_range: str = "",
    lever_id: str = "",
    value_kind: str = "",
    input_semantics: str = "",
  ) -> None:
    target = self._simple_row_target(section)
    key = _text(label)
    if key not in target:
      target[key] = ControllerWriteRow(
        section=_text(section),
        label=key,
        named_range=named_range,
        lever_id=lever_id,
        value_kind=value_kind,
        input_semantics=input_semantics,
      )
    target[key].set_value(quarter_index, value)
    if _text(section) == "expenses":
      self._sync_known_expense_driver_from_row(key, _quarter_index(quarter_index))

  def set_schedule_seed(self, *, debt_opening_balance_seed: Optional[Any] = None, lease_opening_balance_seed: Optional[Any] = None) -> None:
    if debt_opening_balance_seed is not None:
      self.debt_opening_balance_seed = _safe_float(debt_opening_balance_seed)
    if lease_opening_balance_seed is not None:
      self.lease_opening_balance_seed = _safe_float(lease_opening_balance_seed)

  def to_controller_seed(self) -> List[Dict[str, Any]]:
    return [quarter.to_controller_seed_entry() for quarter in self.quarters]

  def to_model_input_json(self) -> Dict[str, Any]:
    revenue_rows: List[Dict[str, Any]] = []
    ordered_slot_keys: List[str] = []
    for quarter in self.quarters:
      for group in quarter.revenue_groups:
        for product in group.products:
          slot_key = _text(product.revenue_slot_key) or f"{_text(group.lob_name)}::{_text(product.product_name)}"
          if slot_key not in ordered_slot_keys:
            ordered_slot_keys.append(slot_key)
    revenue_products: Dict[str, Dict[str, Any]] = {}
    for slot_key in ordered_slot_keys:
      revenue_products[slot_key] = {"capacity": [0.0 for _ in range(self.quarter_count)], "unit_price": [0.0 for _ in range(self.quarter_count)], "utilization": [0.0 for _ in range(self.quarter_count)], "lob": "", "product": "", "revenue_slot_key": slot_key}
    for quarter in self.quarters:
      for group in quarter.revenue_groups:
        for product in group.products:
          slot_key = _text(product.revenue_slot_key) or f"{_text(group.lob_name)}::{_text(product.product_name)}"
          entry = revenue_products.setdefault(slot_key, {"capacity": [0.0 for _ in range(self.quarter_count)], "unit_price": [0.0 for _ in range(self.quarter_count)], "utilization": [0.0 for _ in range(self.quarter_count)], "lob": "", "product": "", "revenue_slot_key": slot_key})
          entry["lob"] = _text(group.lob_name)
          entry["product"] = _text(product.product_name)
          idx = quarter.quarter_index - 1
          entry["capacity"][idx] = round(product.drivers.capacity_units, 6)
          entry["unit_price"][idx] = round(product.drivers.unit_price, 6)
          entry["utilization"][idx] = round(product.drivers.utilization, 6)
    for slot_key in ordered_slot_keys:
      entry = revenue_products[slot_key]
      lob = entry["lob"] or "LOB 1"
      product = entry["product"] or "Product 1"
      revenue_rows.extend(
        [
          {
            "named_range": "model_input_revenue",
            "controller_write": True,
            "lever_id": "::".join(["revenue", lob, product, "Capacity"]),
            "lob": lob,
            "product": product,
            "driver": "Capacity",
            "revenue_slot_key": entry["revenue_slot_key"],
            "values": entry["capacity"],
          },
          {
            "named_range": "model_input_revenue",
            "controller_write": True,
            "lever_id": "::".join(["revenue", lob, product, "Unit Price"]),
            "lob": lob,
            "product": product,
            "driver": "Unit Price",
            "revenue_slot_key": entry["revenue_slot_key"],
            "values": entry["unit_price"],
          },
          {
            "named_range": "model_input_revenue",
            "controller_write": True,
            "lever_id": "::".join(["revenue", lob, product, "Utilization"]),
            "lob": lob,
            "product": product,
            "driver": "Utilization",
            "revenue_slot_key": entry["revenue_slot_key"],
            "values": entry["utilization"],
          },
        ]
      )
    return {
      "engine_contract_version": "financial_model_inputs_v1",
      "business_name": self.business_name,
      "start_date": self.start_date,
      "sections": {
        "revenue": revenue_rows,
        "expenses": [row.to_model_input_row() for row in self.expense_rows.values()],
        "balance_sheet": [row.to_model_input_row() for row in self.balance_sheet_rows.values()],
        "schedules": {
          "debt_opening_balance_seed": round(self.debt_opening_balance_seed, 6),
          "lease_opening_balance_seed": round(self.lease_opening_balance_seed, 6),
          "rows": [row.to_model_input_row() for row in self.schedule_rows.values()],
        },
      },
    }

  def to_dict(self) -> Dict[str, Any]:
    return {
      "engine_contract_version": "financial_model_inputs_v1",
      "business_name": self.business_name,
      "start_date": self.start_date,
      "quarter_count": self.quarter_count,
      "quarters": [quarter.to_controller_seed_entry() for quarter in self.quarters],
      "sections": {
        "expenses": [row.to_model_input_row() for row in self.expense_rows.values()],
        "balance_sheet": [row.to_model_input_row() for row in self.balance_sheet_rows.values()],
        "schedules": {
          "debt_opening_balance_seed": round(self.debt_opening_balance_seed, 6),
          "lease_opening_balance_seed": round(self.lease_opening_balance_seed, 6),
          "rows": [row.to_model_input_row() for row in self.schedule_rows.values()],
        },
      },
    }

  def _load_simple_rows(
    self,
    *,
    section_name: str,
    rows: List[Dict[str, Any]],
    named_range: str,
    target: Dict[str, ControllerWriteRow],
  ) -> None:
    for row in rows:
      if not isinstance(row, dict):
        continue
      label = _text(row.get("label"))
      if not label:
        continue
      target[label] = ControllerWriteRow(
        section=section_name,
        label=label,
        values=_governed_values(list(row.get("values") or [])),
        named_range=_text(row.get("named_range")) or named_range,
        lever_id=_text(row.get("lever_id")),
        value_kind=_text(row.get("value_kind")),
        input_semantics=_text(row.get("input_semantics")),
      )

  def _simple_row_target(self, section: str) -> Dict[str, ControllerWriteRow]:
    normalized = _text(section)
    if normalized == "expenses":
      return self.expense_rows
    if normalized == "balance_sheet":
      return self.balance_sheet_rows
    if normalized == "schedules":
      return self.schedule_rows
    raise ValueError(f"Unsupported controller-write section: {section}")

  def _sync_rows_from_known_expense_drivers(self) -> None:
    for quarter in self.quarters:
      self._sync_row_from_known_expense_driver(quarter.quarter_index)

  def _sync_row_from_known_expense_driver(self, quarter_index: int) -> None:
    quarter = self.quarter(quarter_index)
    mappings = {
      "Cost of Goods Sold": quarter.expenses.cogs_percent,
      "Marketing": quarter.expenses.marketing_percent,
      "Research & Development": quarter.expenses.r_and_d_percent,
      "Lease": quarter.expenses.lease_amount,
      "Payroll": quarter.expenses.payroll_amount,
      "General & Administrative": quarter.expenses.g_and_a_percent,
      "Interest Rate": quarter.expenses.interest_rate,
      "Depreciation": quarter.expenses.depreciation_percent,
      "Taxes": quarter.expenses.tax_percent,
    }
    for label, value in mappings.items():
      if label not in self.expense_rows:
        self.expense_rows[label] = ControllerWriteRow(
          section="expenses",
          label=label,
          named_range="model_input_expenses",
          lever_id="::".join(["expenses", label]),
        )
      self.expense_rows[label].set_value(quarter_index, value)

  def _sync_known_expense_drivers_from_rows(self) -> None:
    for quarter in self.quarters:
      for label, row in self.expense_rows.items():
        self._sync_known_expense_driver_from_row(label, quarter.quarter_index)

  def _sync_known_expense_driver_from_row(self, label: str, quarter_index: int) -> None:
    quarter = self.quarter(quarter_index)
    row = self.expense_rows.get(_text(label))
    if row is None:
      return
    value = row.get_value(quarter_index)
    if label == "Cost of Goods Sold":
      quarter.expenses.cogs_percent = value
    elif label == "Marketing":
      quarter.expenses.marketing_percent = value
    elif label == "Research & Development":
      quarter.expenses.r_and_d_percent = value
    elif label == "Lease":
      quarter.expenses.lease_amount = value
    elif label == "Payroll":
      quarter.expenses.payroll_amount = value
    elif label == "General & Administrative":
      quarter.expenses.g_and_a_percent = value
    elif label == "Interest Rate":
      quarter.expenses.interest_rate = value
    elif label == "Depreciation":
      quarter.expenses.depreciation_percent = value
    elif label == "Taxes":
      quarter.expenses.tax_percent = value
