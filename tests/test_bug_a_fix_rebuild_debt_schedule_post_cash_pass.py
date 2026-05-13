"""Phase 9 P3.10 Bug A fix — smoke tests for the debt_schedule build
relocation.

Verifies:
  - The pre-cascade build site at orchestrator.py:1247-1287 is gone
    (no `source_stage="target_seeking_orchestrator_completed"`).
  - _run_post_cascade_completion no longer accepts a
    debt_schedule_payload parameter.
  - The new build site uses
    `source_stage="post_intake_finalize_validation"`.
  - build_debt_schedule_snapshot, when given post-cash-pass model_input
    + finmo, produces a payload whose validate_debt_schedule_payload
    returns ZERO violations of `principal_balance_not_declining_
    without_new_borrowing`.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
import unittest
from typing import Any, Dict, List


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


def _synthetic_amortizing_finmo() -> Dict[str, Any]:
  """A FINMO with $300K opening LTD amortizing $15K/quarter for 20 quarters."""
  rows: List[Dict[str, Any]] = []
  opening = 300000.0
  for q in range(1, 21):
    repayment = 15000.0 if opening > 0 else 0.0
    closing = max(0.0, opening - repayment)
    rows.append({
      "quarter_index": q,
      "date": f"2026-{(((q - 1) % 4) + 1) * 3:02d}-01",
      "long_term_debt": closing,
      "short_term_debt": 0.0,
      "debt_opening_balance": opening,
      "debt_closing_balance": closing,
      "debt_repayment": repayment,
      "debt_issuance": 0.0,
      "debt_interest_rate": 0.1075,
      "debt_interest_expense": int(round(((opening + closing) / 2.0) * 0.1075)),
      "interest": int(round(((opening + closing) / 2.0) * 0.1075)),
    })
    opening = closing
  return {"quarter_rows": rows}


def _synthetic_amortizing_model_input() -> Dict[str, Any]:
  return {
    "sections": {
      "schedules": {
        "rows": [
          {
            "lever_id": "schedules::Debt Issuance (New Borrowing)",
            "controller_write": True,
            "values": [0.0] * 21,
          },
          {
            "lever_id": "schedules::Debt Repayment (Scheduled)",
            "controller_write": True,
            "values": [0.0] + [15000.0] * 20,
          },
        ],
      },
      "expenses": [
        {
          "lever_id": "expenses::Interest Rate",
          "label": "Interest Rate",
          "controller_write": True,
          "values": [0.1075] * 21,
        },
      ],
      "balance_sheet": [
        {
          "lever_id": "balance_sheet::Short Term Debt (% of LTD)",
          "label": "Short Term Debt (% of LTD)",
          "controller_write": True,
          "values": [0.0] * 21,
        },
      ],
    },
  }


class BugAFixRebuildDebtSchedulePostCashPassTest(unittest.TestCase):
  def test_old_pre_cascade_source_stage_marker_absent(self) -> None:
    """The pre-cascade source_stage marker must not appear in the
    orchestrator any longer."""
    orch = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_solver"
      / "orchestrator.py"
    )
    text = orch.read_text(encoding="utf-8")
    self.assertNotIn(
      'source_stage="target_seeking_orchestrator_completed"',
      text,
      "Pre-cascade build site must be deleted (no early build remains)",
    )
    self.assertIn(
      'source_stage="post_intake_finalize_validation"',
      text,
      "New post-cash-pass build site must be present",
    )

  def test_run_post_cascade_completion_signature_no_debt_schedule_payload(self) -> None:
    """The relocated build means _run_post_cascade_completion no longer
    accepts debt_schedule_payload."""
    import inspect
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _run_post_cascade_completion,
    )
    sig = inspect.signature(_run_post_cascade_completion)
    self.assertNotIn(
      "debt_schedule_payload",
      sig.parameters,
      "debt_schedule_payload should be removed from the signature",
    )

  def test_post_cash_pass_snapshot_passes_validator(self) -> None:
    """Given a synthetic model_input + finmo where DEBT_REPAYMENT has
    been set to $15K/quarter (the cash pass output), the rebuilt
    debt_schedule snapshot must produce zero
    principal_balance_not_declining_without_new_borrowing violations."""
    from client_intake_and_finmo.post_intake_debt_schedule import (  # noqa: WPS433
      build_debt_schedule_snapshot,
      validate_debt_schedule_payload,
    )
    finmo = _synthetic_amortizing_finmo()
    model_input = _synthetic_amortizing_model_input()
    payload = build_debt_schedule_snapshot(
      finmo_payload=copy.deepcopy(finmo),
      model_input_json=copy.deepcopy(model_input),
      source_stage="post_intake_finalize_validation",
    )
    self.assertEqual(payload.get("source_stage"), "post_intake_finalize_validation")
    rows = payload.get("rows") or []
    self.assertEqual(len(rows), 20)
    self.assertEqual(int(rows[0].get("opening_debt") or 0), 300000)
    self.assertEqual(int(rows[0].get("closing_debt") or 0), 285000)
    self.assertEqual(int(rows[0].get("total_principal_payment") or 0), 15000)
    self.assertEqual(int(rows[19].get("opening_debt") or 0), 15000)
    self.assertEqual(int(rows[19].get("closing_debt") or 0), 0)
    violations = validate_debt_schedule_payload(debt_schedule=payload)
    flat_violations = [
      v for v in violations
      if v.get("reason") == "principal_balance_not_declining_without_new_borrowing"
    ]
    self.assertEqual(
      flat_violations, [],
      f"Expected no flat-principal violations on amortizing schedule; got {flat_violations}",
    )

  def test_pre_cash_pass_snapshot_still_violates(self) -> None:
    """Sanity: the original (pre-cash-pass) zero-repayment state STILL
    produces violations. This proves the validator behavior hasn't
    changed and the only fix is the input shift."""
    from client_intake_and_finmo.post_intake_debt_schedule import (  # noqa: WPS433
      build_debt_schedule_snapshot,
      validate_debt_schedule_payload,
    )
    rows = []
    for q in range(1, 21):
      rows.append({
        "quarter_index": q,
        "long_term_debt": 300000.0,
        "debt_opening_balance": 300000.0,
        "debt_closing_balance": 300000.0,
        "debt_repayment": 0.0,
        "debt_issuance": 0.0,
        "debt_interest_rate": 0.1075,
        "debt_interest_expense": int(round(300000.0 * 0.1075)),
        "interest": int(round(300000.0 * 0.1075)),
      })
    finmo = {"quarter_rows": rows}
    model_input = {
      "sections": {
        "schedules": {"rows": [
          {"lever_id": "schedules::Debt Issuance (New Borrowing)", "controller_write": True, "values": [0.0] * 21},
          {"lever_id": "schedules::Debt Repayment (Scheduled)", "controller_write": True, "values": [0.0] * 21},
        ]},
        "expenses": [
          {"lever_id": "expenses::Interest Rate", "label": "Interest Rate", "controller_write": True, "values": [0.1075] * 21},
        ],
        "balance_sheet": [],
      },
    }
    payload = build_debt_schedule_snapshot(
      finmo_payload=finmo,
      model_input_json=model_input,
      source_stage="synthetic_pre_cash_state",
    )
    violations = validate_debt_schedule_payload(debt_schedule=payload)
    flat_violations = [
      v for v in violations
      if v.get("reason") == "principal_balance_not_declining_without_new_borrowing"
    ]
    self.assertEqual(
      len(flat_violations), 20,
      f"Expected 20 flat-principal violations on un-amortized schedule; got {len(flat_violations)}",
    )


if __name__ == "__main__":
  unittest.main()
