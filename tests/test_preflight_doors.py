"""The preflight checks what a run checks (2026-09-11).

scripts/preflight.py replays the run's entry on stored drafts. It is only
worth anything if it calls the SAME functions the run calls - a copy of the
gate payload or of the recalc would drift and pass while the run fails. These
pins hold the single-builder property.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)
_EXTRA = os.path.join(ROOT, "python", "client_intake_and_finmo")
if _EXTRA not in sys.path:
  sys.path.append(_EXTRA)

import api_handlers.intake_consult as IC  # noqa: E402
from client_intake_and_finmo.post_intake_contracts.intake_draft_contract import (  # noqa: E402
  IntakeDraftContract,
)
from client_intake_and_finmo.post_intake_initial_grid import runner as RN  # noqa: E402


def _pj(v):
  if isinstance(v, dict):
    return v
  return json.loads(v) if v else {}


class GatePayloadTests(unittest.TestCase):
  def test_the_run_builds_its_gate_payload_through_the_one_builder(self):
    src = inspect.getsource(RN.prepare_initial_grid_for_draft)
    self.assertIn("intake_draft_gate_payload(", src)
    self.assertNotIn('"operating_model_json": parse_json_dict', src)

  def test_fulfillment_is_absent_when_the_column_is_null(self):
    self.assertNotIn("fulfillment_json",
                     RN.intake_draft_gate_payload({"fulfillment_json": None}, parse_json_dict=_pj))

  def test_fulfillment_is_present_when_stored(self):
    self.assertIn("fulfillment_json",
                  RN.intake_draft_gate_payload({"fulfillment_json": "{}"}, parse_json_dict=_pj))

  def test_every_payload_field_is_a_contract_field(self):
    payload = RN.intake_draft_gate_payload({"fulfillment_json": "{}"}, parse_json_dict=_pj)
    self.assertEqual(set(payload), set(IntakeDraftContract.model_fields))


class EntryRecalcTests(unittest.TestCase):
  def test_the_run_recalc_uses_the_pure_half(self):
    self.assertIn("_entry_recalc_changes(", inspect.getsource(IC._run_entry_recalc))

  def test_the_pure_half_takes_only_the_draft(self):
    self.assertEqual(list(inspect.signature(IC._entry_recalc_changes).parameters), ["draft"])

  def test_the_pure_half_never_touches_the_db(self):
    src = inspect.getsource(IC._entry_recalc_changes)
    for pattern in (r"\bconn\b", r"append_messages", r"get_draft\("):
      self.assertIsNone(re.search(pattern, src), pattern)


if __name__ == "__main__":
  unittest.main()
