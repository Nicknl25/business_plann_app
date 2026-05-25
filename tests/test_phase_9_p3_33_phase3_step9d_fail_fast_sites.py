"""P3.33 Phase 3 step 9d — fail-fast site source-shape regression.

Every FailFastCode catalogued in the inventory must appear by *value*
(snake_case fail_ string) in the module that owns its assertion site.
This is a regression guard: if a guard gets accidentally deleted in a
later edit, this test fails immediately.

The (FailFastCode -> module path) table below is the source of truth
for where each guard lives. The 24 codes match the corrected inventory
(item 13 / FLOOR_BUDGET was dropped — floor primitives are one-shot).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


from client_intake_and_finmo.post_intake_diagnostics.fail_fast_codes import (
  FailFastCode,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


# Each FailFastCode -> the relative path of the module asserting it.
# Maintained alongside the inventory document; updates here mean a
# code's home moved (rare but possible).
CODE_HOMES: Dict[FailFastCode, str] = {
  FailFastCode.FAIL_COHORT_BANDS_MISSING:
    "python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py",
  FailFastCode.FAIL_COHORT_BANDS_MALFORMED:
    "python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py",
  FailFastCode.FAIL_MIRROR_PLAN_STATE_NOT_DICT:
    "python/client_intake_and_finmo/post_intake_amalgamated/mirror.py",
  FailFastCode.FAIL_MIRROR_BANDS_UNRESOLVED:
    "python/client_intake_and_finmo/post_intake_amalgamated/mirror.py",
  FailFastCode.FAIL_MIRROR_FINMO_BASELINE_BUILD:
    "python/client_intake_and_finmo/post_intake_initial_grid/runner.py",
  FailFastCode.FAIL_ROUND1_SET_TOOL_REJECTED:
    "python/client_intake_and_finmo/post_intake_initial_grid/runner.py",
  FailFastCode.FAIL_ROUND1_PLAN_STATE_INCOMPLETE:
    "python/client_intake_and_finmo/post_intake_initial_grid/runner.py",
  FailFastCode.FAIL_EVALUATE_PLAN_EXCEPTION:
    "python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py",
  FailFastCode.FAIL_EVALUATE_PLAN_MALFORMED:
    "python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py",
  FailFastCode.FAIL_CASCADE_MODE_UNKNOWN:
    "python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py",
  FailFastCode.FAIL_CASCADE_TIER_UNKNOWN:
    "python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py",
  FailFastCode.FAIL_CASCADE_HALTED_WITHOUT_RESOLUTION:
    "python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py",
  FailFastCode.FAIL_FLOOR_PRIMITIVE_FAILED:
    "python/client_intake_and_finmo/post_intake_amalgamated/protocol/floor.py",
  FailFastCode.FAIL_SESSION_TERMINAL_STATE_UNKNOWN:
    "python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py",
  FailFastCode.FAIL_FINMO_NO_QUARTER_ROWS:
    "python/client_intake_and_finmo/post_intake_initial_grid/runner.py",
  FailFastCode.FAIL_FINMO_SCHEMA_MISSING:
    "python/client_intake_and_finmo/post_intake_initial_grid/runner.py",
  FailFastCode.FAIL_TARGET_SEEKING_MODE_UNKNOWN:
    "python/client_intake_and_finmo/post_intake_solver/orchestrator.py",
  FailFastCode.FAIL_TARGET_SEEKING_REASON_UNKNOWN:
    "python/client_intake_and_finmo/post_intake_solver/orchestrator.py",
  FailFastCode.FAIL_CASH_PASS_RESULT_MALFORMED:
    "python/client_intake_and_finmo/post_intake_solver/orchestrator.py",
  FailFastCode.FAIL_REALISM_BAND_SOURCE_MISSING:
    "python/client_intake_and_finmo/post_intake_solver/orchestrator.py",
  FailFastCode.FAIL_REALISM_COUNT_MISMATCH:
    "python/client_intake_and_finmo/post_intake_solver/orchestrator.py",
  FailFastCode.FAIL_FINALIZE_STAGE_NOT_FINALIZED:
    "python/client_intake_and_finmo/post_intake_solver/orchestrator.py",
  FailFastCode.FAIL_WORKBOOK_ACCEPT_NO_RUN_ID:
    "python/client_intake_and_finmo/post_intake_acceptance/gate.py",
  FailFastCode.FAIL_WORKBOOK_ACCEPT_NO_DRAFT_ID:
    "python/client_intake_and_finmo/post_intake_acceptance/gate.py",
  FailFastCode.FAIL_MODEL_INPUT_CONTRACT_VIOLATION:
    "python/client_intake_and_finmo/post_intake_contracts/enforcement.py",
}


class FailFastSiteSourceShapeTest(unittest.TestCase):
  def test_every_code_has_a_home(self) -> None:
    self.assertEqual(set(FailFastCode), set(CODE_HOMES.keys()),
                     msg="CODE_HOMES out of sync with FailFastCode enum")

  def test_each_home_contains_its_code_reference(self) -> None:
    """The guard at each site must reference its FailFastCode — either
    as ``FailFastCode.<NAME>`` (enum) or as the snake_case ``code_value``
    string (the session_driver helper takes a string)."""
    for code, rel_path in CODE_HOMES.items():
      src_path = REPO_ROOT / rel_path
      self.assertTrue(src_path.exists(), msg=f"missing source: {src_path}")
      src = src_path.read_text(encoding="utf-8", errors="ignore")
      ref_name = code.name           # e.g. "FAIL_COHORT_BANDS_MISSING"
      ref_value = code.value         # e.g. "fail_cohort_bands_missing"
      self.assertTrue(
        (ref_name in src) or (ref_value in src),
        msg=f"neither {ref_name} nor {ref_value!r} referenced in {rel_path}",
      )

  def test_homes_resolve_to_real_files(self) -> None:
    for rel_path in set(CODE_HOMES.values()):
      self.assertTrue(
        (REPO_ROOT / rel_path).is_file(),
        msg=f"not a file: {rel_path}",
      )


if __name__ == "__main__":
  unittest.main()
