"""Nick's payroll directive (2026-09-09 evening), item 7 / R4 TURN C, pinned.

"Add back EVERY owner's pay. SDE is what a single owner-operator would take
out; mirroring whichever row is first is arbitrary and order-dependent,
which is worse than either answer. Nothing touching valuation should depend
on row order."

The deal breaker: a two-owner client's Valuation sheet added back ONE
owner's pay - whichever row the merge left first. Scratch Marchetti (two
co-owners, 155,000 + 142,000 = 74,250/qtr actually paid) showed
"EBITDA + $35,500/qtr owner pay" with Rasheed's row first, 38,750 with
Ottoline's - and the docx's sde_y1..y5 and the valuation prose moved with it.

Pinned here:
  * the SDE add-back on the Valuation sheet is the SUM of every owner-titled
    person's pay (74,250/qtr on the Marchetti shape), the note says how many
    owners it adds back, and a one-owner business reads byte-for-byte as it
    did (Sumac 48,000 -> "EBITDA + $12,000/qtr owner pay");
  * writing_phase_v2/derived.py sde_y1..y5 and writing_phase/facts/
    valuation.py (the sheet's Python twin) use the same sum from the same
    source;
  * the financials.owner_compensation mirror is a stated function of the SET
    (sum / 12) in both writers (_sync_owner_pay_one_home and the owner-pay
    statement door);
  * SINGLE-ROW-PATCH REORDER: the same two-owner roster in both orders yields
    the same SDE row, the same mirror and the same derived sde_y1..y5;
  * ONE owner-title regex: the handler's _OWNER_TITLE_RE IS
    client_intake_and_finmo.owner_pay.OWNER_TITLE_RE.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

from _p3_40_contract_2_fixtures import valid_workbook_payload_dict  # noqa: E402
from api_handlers import intake_consult as IC  # noqa: E402
from client_statements_output_excel.data import DraftWorkbookData  # noqa: E402
from client_statements_output_excel.workbook_builder import (  # noqa: E402
  build_client_financial_model_workbook,
)
from writing_phase import facts as _facts_pkg  # noqa: E402,F401
from writing_phase.facts import valuation as V  # noqa: E402
from writing_phase_v2 import derived as DV  # noqa: E402


OTTOLINE = {
  "full_name": "Ottoline Marchetti", "role_title": "Principal Architect and Co-Owner",
  "annual_wage": 155000.0, "wage_source": "client_override",
}
RASHEED = {
  "full_name": "Rasheed Fennimore", "role_title": "Design Director and Co-Owner",
  "annual_wage": 142000.0, "wage_source": "client_override",
}
DRAFTER = {
  "full_name": "Priya Nair", "role_title": "Architectural Drafter",
  "annual_wage": 60000.0, "wage_source": "client_override",
}
DELIA = {
  "full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
  "annual_wage": 48000.0, "wage_source": "client_override",
}
ROSALIE = {
  "full_name": "Rosalie Fenn", "role_title": "Crew Lead",
  "annual_wage": 37000.0, "wage_source": "client_override",
}

MARCHETTI_RASHEED_FIRST = {"people": [copy.deepcopy(RASHEED), copy.deepcopy(OTTOLINE), copy.deepcopy(DRAFTER)]}
MARCHETTI_OTTOLINE_FIRST = {"people": [copy.deepcopy(OTTOLINE), copy.deepcopy(RASHEED), copy.deepcopy(DRAFTER)]}
SUMAC = {"people": [copy.deepcopy(DELIA), copy.deepcopy(ROSALIE)]}


def _draft_row(people, mirror_monthly):
  return {
    "draft_id": "pin-sde-every-owner",
    "business_name": "Pin SDE",
    "people_json": json.dumps(people),
    "financials_json": json.dumps({"owner_compensation": mirror_monthly}),
  }


def _build(people, mirror_monthly):
  payload = valid_workbook_payload_dict()
  data = DraftWorkbookData(
    draft_row=_draft_row(people, mirror_monthly),
    model_input_json=payload.get("model_input_json") or {},
    finmo_json=payload.get("finmo_json") or {},
    payroll_headcount=payload.get("payroll_headcount") or {},
    debt_schedule=payload.get("debt_schedule") or {},
    planning_run_json=payload.get("planning_run_json") or {},
    run_diagnostics=payload.get("run_diagnostics"),
  )
  return build_client_financial_model_workbook(data)


def _sde_row(wb):
  ws = wb["Valuation"]
  for r in range(1, ws.max_row + 1):
    label = ws.cell(row=r, column=1).value
    if isinstance(label, str) and label.startswith("Seller's discretionary earnings"):
      return {
        "note": ws.cell(row=r, column=2).value,
        "q1": ws.cell(row=r, column=3).value,
        "total": ws.cell(row=r, column=23).value,
      }
  raise AssertionError("no SDE row on the Valuation sheet")


class _Row(dict):
  """derived.py reads model.annual rows by subscript; every unpinned key
  reads 1.0 so the arithmetic runs and only the owner-pay term is under test."""

  def __missing__(self, key):
    return 1.0


def _derived(people, mirror_monthly):
  annual = [_Row(revenue=1000.0, net_income=10.0, interest=2.0, depreciation=3.0, taxes=4.0)
            for _ in range(5)]
  record = {"people": people, "financials": {"owner_compensation": mirror_monthly}}
  return DV.build_derived({"draft_id": "pin"}, {"annual": annual}, record, {})


class _NoCur:
  def execute(self, *a, **k):
    raise RuntimeError("no constants table in the pin")

  def fetchall(self):
    return []


def _fact(people, mirror_monthly):
  qrows = [{"quarter_index": i, "revenue": 1000.0, "ebitda": 100.0} for i in range(0, 21)]
  draft = {
    "people_json": json.dumps(people),
    "financials_json": json.dumps({"owner_compensation": mirror_monthly}),
    "finmo_json": json.dumps({"quarter_rows": qrows}),
    "model_input_json": json.dumps({}),
    "operating_model_json": json.dumps({}),
  }
  return V.compute_valuation(_NoCur(), draft)


class ValuationSheetAddsBackEveryOwner(unittest.TestCase):
  def test_two_owner_roster_adds_back_both_rasheed_first(self):
    """THE DEAL BREAKER SHAPE: mirror carries Rasheed (11,833.33/mo) because
    the door emitted his row first; the sheet must add back 74,250/qtr."""
    row = _sde_row(_build(MARCHETTI_RASHEED_FIRST, 11833.33))
    self.assertEqual(row["note"], "EBITDA + $74,250/qtr owner pay (2 owners)")
    self.assertIn("+74250.0", str(row["q1"]))

  def test_two_owner_roster_adds_back_both_ottoline_first(self):
    row = _sde_row(_build(MARCHETTI_OTTOLINE_FIRST, 12916.67))
    self.assertEqual(row["note"], "EBITDA + $74,250/qtr owner pay (2 owners)")
    self.assertIn("+74250.0", str(row["q1"]))

  def test_one_owner_business_unchanged_byte_for_byte(self):
    """Sumac: one owner at 48,000 -> 12,000/qtr, the note exactly as HEAD wrote it."""
    row = _sde_row(_build(SUMAC, 4000.0))
    self.assertEqual(row["note"], "EBITDA + $12,000/qtr owner pay")
    self.assertIn("+12000.0", str(row["q1"]))

  def test_no_owner_row_falls_back_to_the_legacy_mirror(self):
    row = _sde_row(_build({"people": [copy.deepcopy(ROSALIE)]}, 4000.0))
    self.assertEqual(row["note"], "EBITDA + $12,000/qtr owner pay")

  def test_single_row_patch_reorder_yields_the_same_sde_row(self):
    a = _sde_row(_build(MARCHETTI_RASHEED_FIRST, 11833.33))
    b = _sde_row(_build(MARCHETTI_OTTOLINE_FIRST, 12916.67))
    self.assertEqual(a, b)


class DerivedAndFactTwinUseTheSameSum(unittest.TestCase):
  def test_derived_sde_uses_every_owner(self):
    d = _derived(MARCHETTI_RASHEED_FIRST, 11833.33)
    self.assertAlmostEqual(d["sde_y1"], 297000.0 + 10 + 2 + 3 + 4, places=6)
    self.assertAlmostEqual(d["sde_y5"], 297000.0 * 1.03 ** 4 + 19, places=6)

  def test_derived_one_owner_unchanged(self):
    d = _derived(SUMAC, 4000.0)
    self.assertAlmostEqual(d["sde_y1"], 48000.0 + 19, places=6)

  def test_derived_reorder_is_identical(self):
    a = _derived(MARCHETTI_RASHEED_FIRST, 11833.33)
    b = _derived(MARCHETTI_OTTOLINE_FIRST, 12916.67)
    for y in range(1, 6):
      self.assertEqual(a[f"sde_y{y}"], b[f"sde_y{y}"])

  def test_fact_twin_owner_comp_q_is_the_sum_per_quarter(self):
    f = _fact(MARCHETTI_RASHEED_FIRST, 11833.33)
    self.assertEqual(f["owner_comp_q"], 74250.0)
    self.assertAlmostEqual(f["sde_y5"], 4 * (100.0 + 74250.0), places=6)
    g = _fact(MARCHETTI_OTTOLINE_FIRST, 12916.67)
    self.assertEqual(f["owner_comp_q"], g["owner_comp_q"])
    self.assertEqual(f["sde_y5"], g["sde_y5"])

  def test_fact_twin_one_owner_unchanged(self):
    f = _fact(SUMAC, 4000.0)
    self.assertEqual(f["owner_comp_q"], 12000.0)


class MirrorIsOrderIndependent(unittest.TestCase):
  def test_sync_two_owner_mirror_is_the_sum_in_both_orders(self):
    fa = IC._sync_owner_pay_one_home(
      financials_json={"owner_compensation": 11833.33}, people_json=copy.deepcopy(MARCHETTI_RASHEED_FIRST))
    fb = IC._sync_owner_pay_one_home(
      financials_json={"owner_compensation": 12916.67}, people_json=copy.deepcopy(MARCHETTI_OTTOLINE_FIRST))
    self.assertEqual(fa["owner_compensation"], 24750.0)
    self.assertEqual(fb["owner_compensation"], 24750.0)

  def test_sync_one_owner_mirror_unchanged(self):
    f = IC._sync_owner_pay_one_home(
      financials_json={"owner_compensation": 4000.0}, people_json=copy.deepcopy(SUMAC))
    self.assertEqual(f["owner_compensation"], 4000.0)

  def test_sync_legacy_field_without_owner_row_still_materializes_the_role(self):
    ppl = {"people": [copy.deepcopy(ROSALIE)]}
    f = IC._sync_owner_pay_one_home(financials_json={"owner_compensation": 4000.0}, people_json=ppl)
    owners = [p for p in ppl["people"] if IC._OWNER_TITLE_RE.search(p.get("role_title") or "")]
    self.assertEqual(len(owners), 1)
    self.assertEqual(owners[0]["annual_wage"], 48000.0)
    self.assertEqual(f["owner_compensation"], 4000.0)

  def test_owner_pay_statement_door_mirror_carries_every_owner(self):
    ppl = copy.deepcopy(MARCHETTI_OTTOLINE_FIRST)
    f = IC._apply_owner_pay_statement(monthly=5000.0, people_json=ppl, financials_json={})
    # the statement landed on the first owner row (the door's own rule,
    # unchanged); the MIRROR carries both owners: 60,000 + 142,000 = 202,000 / 12
    self.assertEqual(ppl["people"][0]["annual_wage"], 60000.0)
    self.assertAlmostEqual(f["owner_compensation"], round(202000.0 / 12.0, 2), places=2)

  def test_owner_pay_statement_door_one_owner_unchanged(self):
    ppl = copy.deepcopy(SUMAC)
    f = IC._apply_owner_pay_statement(monthly=4000.0, people_json=ppl, financials_json={})
    self.assertEqual(f["owner_compensation"], 4000.0)


class OneOwnerTitleRegex(unittest.TestCase):
  def test_handler_regex_is_the_shared_pattern(self):
    from client_intake_and_finmo import owner_pay
    self.assertIs(IC._OWNER_TITLE_RE, owner_pay.OWNER_TITLE_RE)

  def test_helper_sums_owner_rows_only_and_order_free(self):
    from client_intake_and_finmo.owner_pay import owner_pay_total
    a = owner_pay_total(MARCHETTI_RASHEED_FIRST)
    b = owner_pay_total(MARCHETTI_OTTOLINE_FIRST)
    self.assertEqual(a, {"annual_total": 297000.0, "owners": 2, "source": "people_rows"})
    self.assertEqual(a, b)

  def test_helper_ignores_owner_rows_without_a_wage(self):
    from client_intake_and_finmo.owner_pay import owner_pay_total
    ppl = {"people": [dict(OTTOLINE), {"role_title": "Owner", "annual_wage": None}]}
    self.assertEqual(owner_pay_total(ppl)["annual_total"], 155000.0)
    self.assertEqual(owner_pay_total(ppl)["owners"], 1)

  def test_helper_legacy_mirror_when_no_owner_row(self):
    from client_intake_and_finmo.owner_pay import owner_pay_total
    t = owner_pay_total({"people": [dict(ROSALIE)]}, {"owner_compensation": 4000.0})
    self.assertEqual(t, {"annual_total": 48000.0, "owners": 1, "source": "legacy_mirror"})
    self.assertEqual(owner_pay_total({"people": []}, {}), {"annual_total": None, "owners": 0, "source": None})


if __name__ == "__main__":
  unittest.main()
