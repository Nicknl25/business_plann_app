"""Every stamp the payroll door writes must pass the REAL payload validator
(2026-09-11).

Two shipped paths failed at payload build because their pins called the
stamping functions directly and never ran validate_payroll_headcount_payload
on a payload carrying the stamp:

1. The reconciliation stamp's `stated_source` label (49a4cadc) was not an
   approved text field. It failed Ferriday & Blythe's live system run
   (d44f717c, 10:20:25) - `payroll_headcount_unapproved_text_field:
   payroll_headcount.stated_payroll_reconciliation.stated_source`.
2. The anchor-AUTHORED block (85ae3f82, ruling 1) - a path that had never
   run live - failed on its `created_wage_basis` label AND on every created
   row: `payroll_headcount_missing_oews_occ_title`. Any business with a
   stated pool and no authored supporting roster would have crashed at
   submit.

The fixture is Holloway & Mercer's real payload (21260361, 2026-09-10),
which validated as stored. Each test adds exactly one stamp and runs the
real validator on it.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.post_intake_headcount import schedule as S  # noqa: E402
from client_intake_and_finmo.post_intake_headcount.lookup import (  # noqa: E402
  validate_payroll_headcount_payload,
)

FIXTURE = os.path.join(HERE, "fixtures", "payroll_payload_holloway_20260910.json")


def _base():
  with open(FIXTURE, encoding="utf-8") as fh:
    return json.load(fh)


def _key_rows(payload):
  return [r for r in payload["rows"] if r.get("staffing_class") == "key_person"]


def _horizon(payload):
  return max(int(r.get("quarter_index") or 0) for r in payload["rows"])


class FixtureTests(unittest.TestCase):
  def test_the_fixture_itself_is_valid(self):
    self.assertEqual(validate_payroll_headcount_payload(_base()), [])


class ReconciliationStampTests(unittest.TestCase):
  def test_reconciliation_stamp_passes_the_validator(self):
    """The Ferriday & Blythe failure, pinned on the real validator."""
    payload = _base()
    S._stamp_stated_payroll_reconciliation(
      payload, payload.get("rest_of_team_anchor"),
      financials_json={"current_payroll": 834000})
    self.assertIn("stated_payroll_reconciliation", payload)
    self.assertEqual(validate_payroll_headcount_payload(payload), [])

  def test_every_stated_source_token_passes(self):
    for fin, anchor in (
        ({"current_payroll": 834000}, None),
        ({"payroll_total_year1": 834000}, None),
        ({}, {"stated_total_payroll": 834000.0,
              "anchor_disposition": "launch_in_band"}),
    ):
      payload = _base()
      if anchor is None:
        payload.pop("rest_of_team_anchor", None)
      else:
        payload["rest_of_team_anchor"] = anchor
      S._stamp_stated_payroll_reconciliation(
        payload, anchor, financials_json=fin)
      self.assertEqual(validate_payroll_headcount_payload(payload), [],
                       payload["stated_payroll_reconciliation"]["stated_source"])


class AuthoredBlockTests(unittest.TestCase):
  def _authored_payload(self, pool=555000):
    payload = _base()
    keys = _key_rows(payload)
    rows, anchor = S._anchor_supporting_rows_to_stated_pool(
      [], people_json={"rest_of_team_payroll_year1": pool},
      key_people_rows=keys, horizon=_horizon(payload))
    self.assertEqual(anchor["anchor_disposition"], "authored_from_stated_pool")
    payload["rows"] = keys + rows
    payload["rest_of_team_anchor"] = anchor
    return payload, rows

  def test_authored_block_passes_the_validator(self):
    """Ruling 1's path, never run live until this pin ran it."""
    payload, _ = self._authored_payload()
    self.assertEqual(validate_payroll_headcount_payload(payload), [])

  def test_authored_block_plus_reconciliation_passes_and_reconciles(self):
    payload, _ = self._authored_payload()
    S._stamp_stated_payroll_reconciliation(
      payload, payload["rest_of_team_anchor"],
      financials_json={"current_payroll": 279000 + 555000})
    self.assertTrue(payload["stated_payroll_reconciliation"]["reconciled"])
    self.assertEqual(validate_payroll_headcount_payload(payload), [])

  def test_authored_rows_carry_an_honest_occupation(self):
    _, rows = self._authored_payload()
    for r in rows:
      self.assertEqual(r["oews_occ_code"], "00-0000")
      self.assertEqual(r["oews_occ_title"], "All Occupations")
      self.assertNotIn("rest-of-team payroll", r["position_title"].lower())


class WagePositioningExclusionTests(unittest.TestCase):
  def test_estimated_wages_never_reach_the_wage_chart(self):
    """An authored block's per-person wage is an estimate; the wage
    positioning reader must not plot it."""
    from writing_phase_v2 import warehouse as WH
    payload = _base()
    keys = _key_rows(payload)
    rows, _ = S._anchor_supporting_rows_to_stated_pool(
      [], people_json={"rest_of_team_payroll_year1": 555000},
      key_people_rows=keys, horizon=_horizon(payload))
    draft = {"payroll_headcount": json.dumps({"rows": rows}),
             "people_json": json.dumps({"people": []}),
             "operating_model_json": "{}"}
    self.assertEqual(WH._wage_rows_from_roster(draft), [])


if __name__ == "__main__":
  unittest.main()
