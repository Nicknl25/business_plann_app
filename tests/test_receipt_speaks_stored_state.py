"""THE RECEIPT SPEAKS WHAT WAS STORED (Nick 2026-09-11).

"The receipt reads the request and the store reads the roster, and the
no-op suppression guarantees a reverted figure gets spoken. Compose the
receipt from what was actually stored, after everything that can move it
has run."

Pelletier Orthotics 8bb68a68, turn 71: the client said "our real wage bill
is 953,000". The router wrote financials.current_payroll = 953,000, the
guard admitted it, and the reply read "Also recorded: current payroll
$953,000". Stored, forty milliseconds later: 1,139,000 - THE RECALC
restamped current_payroll from the roster inside
_advance_persisted_financials_stage, which had received the receipt as a
FINISHED STRING. The same shape hit Halvorsen Tide the same hour
("Also recorded: current payroll $762,000", stored 856,000).

Two defects, both pinned here:

1. THE DOOR. The stage flow only called the people door when the patch
   ALREADY carried a people.* key - but the remap that turns
   financials.current_payroll into people.total_team_payroll lives INSIDE
   that door. A financials-shaped payroll correction therefore never
   reached the one door that folds it, on the active-stage path only; the
   completed-state path calls the door unconditionally and works.

2. THE RECEIPT. "Also recorded:" was composed from normalized_patch (the
   REQUEST) before the advance ran the recalc. It is now composed AFTER the
   sync, from persisted_financials (the STORE), against the turn-entry
   snapshot: a value the recalc reverted equals its before-state and is
   never spoken; a value that landed is spoken with the stored figure.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

_PATH = os.environ.get("IC_PATH") or os.path.join(ROOT, "python", "api_handlers", "intake_consult.py")
_spec = importlib.util.spec_from_file_location("ic_receipt_under_test", _PATH)
IC = importlib.util.module_from_spec(_spec)
sys.modules["ic_receipt_under_test"] = IC
_spec.loader.exec_module(IC)


def _src() -> str:
  with open(_PATH, encoding="utf-8") as fh:
    return fh.read()


class TheStageFlowCallsTheDoorUnconditionally(unittest.TestCase):
  def test_the_door_is_not_gated_on_people_keys_already_present(self):
    """The remap financials.current_payroll -> people.total_team_payroll is
    INSIDE _apply_stage_people_door_keys, so a caller that only enters the
    door when a people.* key is already present can never remap anything.
    The completed-state call has no such gate; the stage-flow call must
    not either."""
    src = _src()
    marker = "PEOPLE-DOOR keys land even inside the stage flow"
    i = src.find(marker)
    self.assertGreater(i, 0, "the CW-024 #109/#115 stage-flow door block is missing")
    block = src[i:i + 1600]
    call = block.find("_apply_stage_people_door_keys(")
    self.assertGreater(call, 0, "the stage flow no longer calls the door")
    between = block[:call]
    self.assertNotRegex(
      between, r"if _people_keys\s*:",
      "the stage flow gates the door on people keys the door itself creates "
      "- a financials-shaped payroll correction can never be remapped")

  def test_the_door_remaps_a_financials_shaped_payroll_write(self):
    """The door's own contract, pinned so the caller fix above means
    something: current_payroll in, total_team_payroll consumed, and the
    financials-shaped key never survives to land on the derived field."""
    patch, fin, shared, ack = IC._apply_stage_people_door_keys(
      patch={"financials.current_payroll": 953000.0},
      stage_shared_context={"people_capability": {"people": []}, "operating_model": {}},
      next_financials={"current_payroll": 1139000.0},
      conn=None, intake_context={"draft_id": ""},
    )
    self.assertNotIn("financials.current_payroll", patch)
    self.assertNotIn("current_payroll", patch)


class TheReceiptIsComposedFromTheStore(unittest.TestCase):
  def test_a_reverted_figure_is_not_spoken(self):
    """THE PELLETIER SHAPE: the request said 953,000; the store, after the
    recalc, still says 1,139,000 - exactly what it said before the turn.
    Nothing changed, so nothing is recorded, so nothing is spoken."""
    text = IC._compose_stored_receipt(
      persisted_financials={"current_payroll": 1139000.0, "payroll_total_year1": 1139000.0},
      receipt_fields=["current_payroll", "payroll_total_year1"],
      receipt_before={"current_payroll": 1139000.0, "payroll_total_year1": 1139000.0},
    )
    self.assertEqual(text, "")

  def test_a_landed_figure_is_spoken_with_the_stored_value(self):
    """The spoken number is the STORED one - even when it differs from
    the request, the client hears what the plan will actually carry."""
    text = IC._compose_stored_receipt(
      persisted_financials={"monthly_rent_expense": 14800.0},
      receipt_fields=["monthly_rent_expense"],
      receipt_before={"monthly_rent_expense": 12000.0},
    )
    self.assertIn("Also recorded:", text)
    self.assertIn("monthly rent expense", text)
    self.assertIn("14,800", text)

  def test_a_ratio_field_renders_as_a_percent(self):
    text = IC._compose_stored_receipt(
      persisted_financials={"cogs_percent_of_revenue": 0.21},
      receipt_fields=["cogs_percent_of_revenue"],
      receipt_before={"cogs_percent_of_revenue": 0.16},
    )
    self.assertIn("21", text)
    self.assertNotIn("$0", text)

  def test_at_most_three_fields_are_spoken(self):
    fields = ["a_amount", "b_amount", "c_amount", "d_amount"]
    text = IC._compose_stored_receipt(
      persisted_financials={f: 10.0 for f in fields},
      receipt_fields=fields,
      receipt_before={f: 1.0 for f in fields},
    )
    self.assertEqual(text.count(" amount"), 3)

  def test_the_advance_takes_the_field_list_not_a_finished_sentence(self):
    """The receipt cannot be truthful if it is frozen before the recalc
    runs. The advance therefore composes it itself, after the sync."""
    import inspect
    sig = inspect.signature(IC._advance_persisted_financials_stage)
    self.assertIn("receipt_fields", sig.parameters)
    self.assertIn("receipt_before", sig.parameters)

  def test_the_edit_patch_path_no_longer_bakes_the_receipt_from_the_request(self):
    """No 'Also recorded' may be composed from normalized_patch before the
    advance runs - that is the exact line that spoke $953,000."""
    src = _src()
    self.assertNotRegex(
      src,
      r"_xv = _safe_float\(normalized_patch\.get\(_xf\)\)",
      "the receipt is still read from the request, not the store")


if __name__ == "__main__":
  unittest.main()
