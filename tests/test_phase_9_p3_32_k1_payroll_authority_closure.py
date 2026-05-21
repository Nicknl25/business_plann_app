"""Phase 9 P3.32 K1 (F1+F2) — regression guard for Payroll authority closure.

P3.31 audit identified two leaks where Handler C's canonical Payroll
authority was bypassed:

  Leak A — GPT exhaustion handler's GPT_AUTHORED_LEVER_IDS included
           "expenses::Payroll" (handler.py:50-58 pre-K1). The path
           engine wrote whatever the handler stamped on the
           model_input row, so when GPT proposed payroll anchors
           those anchors landed in model_input.expenses::Payroll
           with NO update to payroll_headcount.quarter_totals.
           Result: Mirror Flavor 1 divergence (Chain A persisted
           FINMO uses GPT's Payroll; Chain B workbook formula uses
           Handler C's untouched payroll_headcount.rows -> SUMIFS
           on Payroll Schedule).

           Active vector for the P3.25 CareFirst $36K/quarter
           Payroll -> $677K Cash Q20 divergence.
           Active vector for the P3.32 Caring Hands Home Health
           Services latent FALSE_PASS (V-4 verifier surfaced
           $44,929 Cash Q20 divergence in workbook
           4207488106054d72afbe16480e1de100.xlsx after P3.28's
           sweep marked it 16/16 GENUINE_PASS).

  Leak B — Restoration target-solver writes whatever lever_id
           appears in failing realism rows' primary_levers
           (lookup.py:544, 605, 1005, 1116). Multiple realism
           rows list "expenses::Payroll" — solver writes to it
           via apply_exact_lever_updates_to_model_input,
           bypassing Handler C. Closed in K1 F3+F4 (separate
           commit / separate test file).

This test file pins the F1+F2 closure of Leak A:

  1. "expenses::Payroll" NOT in GPT_AUTHORED_LEVER_IDS.
  2. "payroll_dollars_per_quarter" NOT a key in _DRIVER_KEY_TO_LEVER_ID.
  3. "payroll_dollars_per_quarter" NOT in the PNL-path tool schema.
  4. "expenses::Payroll" NOT in restoration_loop's
     _GPT_AUTHORED_PNL_LEVER_IDS mirror.
  5. _GPT_AUTHORED_ALL union excludes Payroll.

If a future commit re-introduces Payroll into any of these
surfaces, this test file fails fast and the operator must
re-justify the re-introduction (which would be a doctrine
reversion of P3.32 K1).
"""

from __future__ import annotations

import unittest


_PAYROLL_LEVER_ID = "expenses::Payroll"
_PAYROLL_DRIVER_KEY = "payroll_dollars_per_quarter"


class TestExhaustionHandlerCatalogExcludesPayroll(unittest.TestCase):
  """Leak A surface 1: handler.py constants."""

  def test_gpt_authored_lever_ids_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    self.assertNotIn(
      _PAYROLL_LEVER_ID, GPT_AUTHORED_LEVER_IDS,
      msg=(
        "Phase 9 P3.32 K1 doctrine: expenses::Payroll MUST NOT be "
        "in GPT_AUTHORED_LEVER_IDS. Handler C is canonical writer; "
        "this catalog inclusion was Leak A from P3.31 audit."
      ),
    )

  def test_driver_key_to_lever_id_excludes_payroll_key(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      _DRIVER_KEY_TO_LEVER_ID,
    )
    self.assertNotIn(
      _PAYROLL_DRIVER_KEY, _DRIVER_KEY_TO_LEVER_ID,
      msg=(
        "Phase 9 P3.32 K1: payroll_dollars_per_quarter MUST NOT "
        "map to any lever — Handler C owns Payroll authority."
      ),
    )
    self.assertNotIn(
      _PAYROLL_LEVER_ID, set(_DRIVER_KEY_TO_LEVER_ID.values()),
      msg=(
        "Phase 9 P3.32 K1: no driver key may map to "
        "expenses::Payroll."
      ),
    )

  def test_other_canonical_drivers_still_present(self) -> None:
    """The 7 remaining P&L drivers must still be in the catalog —
    only Payroll is removed. Guards against accidental over-removal."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    for lever in (
      "revenue::Unit Price",
      "revenue::Capacity",
      "revenue::Utilization",
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
      "expenses::Research & Development",
    ):
      self.assertIn(lever, GPT_AUTHORED_LEVER_IDS,
                    msg=f"{lever} must remain in handler authority post-K1.")


class TestRestorationLoopMirrorExcludesPayroll(unittest.TestCase):
  """Leak A surface 2: restoration_loop.py mirror set used by
  the post-cascade trigger classifier."""

  def test_gpt_authored_pnl_lever_set_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      _GPT_AUTHORED_PNL_LEVER_IDS,
    )
    self.assertNotIn(
      _PAYROLL_LEVER_ID, _GPT_AUTHORED_PNL_LEVER_IDS,
      msg=(
        "Phase 9 P3.32 K1: restoration_loop mirror must stay in "
        "lockstep with the handler catalog. expenses::Payroll "
        "MUST NOT be classified as a handler-authored PNL lever."
      ),
    )

  def test_gpt_authored_all_union_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      _GPT_AUTHORED_ALL,
    )
    self.assertNotIn(_PAYROLL_LEVER_ID, _GPT_AUTHORED_ALL)


class TestPnlPathToolSchemaExcludesPayroll(unittest.TestCase):
  """Leak A surface 3: the tool definition GPT receives. If
  payroll_dollars_per_quarter were in the schema's properties /
  required, GPT could still propose payroll values and the handler
  writer (even without the catalog entry) might attempt to apply
  them. Schema-level closure prevents the proposal from existing."""

  def test_pnl_path_schema_required_does_not_include_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      _build_tool_definition,
      SCOPE_PNL_PATH,
    )
    tool_def = _build_tool_definition(SCOPE_PNL_PATH)
    params = tool_def.get("parameters") or {}
    self.assertNotIn(_PAYROLL_DRIVER_KEY, set(params.get("required") or []))
    self.assertNotIn(_PAYROLL_DRIVER_KEY, set((params.get("properties") or {}).keys()))

  def test_bs_only_path_unchanged(self) -> None:
    """K1 does not touch the bs_only_path tool definition — that path
    already drops the 7 P&L anchor fields entirely."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      _build_tool_definition,
      SCOPE_BS_ONLY_PATH,
    )
    tool_def = _build_tool_definition(SCOPE_BS_ONLY_PATH)
    params = tool_def.get("parameters") or {}
    self.assertNotIn(_PAYROLL_DRIVER_KEY, set(params.get("required") or []))
    self.assertIn("working_capital_drivers", set((params.get("properties") or {}).keys()))


class TestExtensionPromptDoesNotMentionPayrollReductions(unittest.TestCase):
  """Leak A surface 4: the system prompt and extension prompt. If the
  prompt language nudges GPT toward "payroll reductions" GPT may try
  to author them even when the schema doesn't include the field —
  attempting via tool calls that the schema validator would reject,
  consuming tool-call budget. Doctrine-level closure removes the
  language."""

  def test_extension_prompt_does_not_mention_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.prompts import (  # noqa: WPS433
      EXTENSION_PROMPT_TEXT,
    )
    self.assertNotIn(
      "payroll", EXTENSION_PROMPT_TEXT.lower(),
      msg=(
        "Phase 9 P3.32 K1: EXTENSION_PROMPT_TEXT must not nudge "
        "GPT toward payroll changes — Handler C owns Payroll."
      ),
    )


if __name__ == "__main__":
  unittest.main()
