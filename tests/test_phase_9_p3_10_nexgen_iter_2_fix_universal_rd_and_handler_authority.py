"""Phase 9 P3.10 NexGen iter 2 fix — universal R&D + handler authority.

Verifies the two combined fixes for the iter 2 hard-fail
(stage_ramp_expense for R&D stuck flat at 20.81% across Q11-Q20):

1. Handler authority gap closed: `expenses::Research & Development` is
   in `_GPT_AUTHORED_PNL_LEVER_IDS` (restoration_loop trigger
   classifier), `GPT_AUTHORED_LEVER_IDS` (handler authored levers),
   `_DRIVER_KEY_TO_LEVER_ID` (handler writer), and the tool-calling
   session JSON schema's pnl_path required parameters. The handler
   can now author R&D anchors when ramp violations route to it.

2. NAICS-2 R&D applicability machinery deleted: the hardcoded
   `_DEFAULT_R_AND_D_APPLICABILITY_ROWS` lookup table + helpers
   (post_intake_r_and_d_applicability_for_naics2,
   load_post_intake_r_and_d_applicability_rows,
   _ensure_r_and_d_applicability_lookup_table) are gone. The
   deterministic NAICS wrapper (_derive_r_and_d_applicability_from_naics)
   is a no-op. The "GPT estimator"
   (_estimate_r_and_d_applicability_with_gpt) is a constant universal
   stub returning r_and_d_enabled=True with no GPT call. The
   finmo_bridge disable-code (zeroing R&D when not_applicable) is
   removed.

Universal-app: same code path for every business, regardless of NAICS.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


# A diverse mix of NAICS-2 sectors that previously had different
# applicability defaults (required, not_applicable, optional). After the
# fix, every one returns the same universal decision.
_NAICS_MIX = (
  ("511210", "Information / Software (was: required)"),
  ("455211", "Retail (was: not_applicable)"),
  ("332999", "Manufacturing (was: optional)"),
  ("722511", "Accommodation/Food (was: not_applicable)"),
  ("541511", "Professional Services (was: required)"),
  ("513210", "NexGen — Software (was: required)"),
  ("488510", "Express — Freight brokerage (was: not_applicable)"),
  ("311811", "Sunny — Bakery (was: not_applicable)"),
)


class NexGenIter2HandlerAuthorityTest(unittest.TestCase):
  def test_rd_in_solver_trigger_pnl_lever_set(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      _GPT_AUTHORED_PNL_LEVER_IDS,
    )
    self.assertIn("expenses::Research & Development", _GPT_AUTHORED_PNL_LEVER_IDS)

  def test_rd_in_handler_authored_lever_ids(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    self.assertIn("expenses::Research & Development", GPT_AUTHORED_LEVER_IDS)

  def test_rd_in_handler_driver_key_to_lever_id_map(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      _DRIVER_KEY_TO_LEVER_ID,
    )
    self.assertEqual(
      _DRIVER_KEY_TO_LEVER_ID.get("r_and_d_percent_of_revenue"),
      "expenses::Research & Development",
    )

  def test_rd_in_pnl_path_tool_schema_required_and_properties(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      _build_tool_definition,
      SCOPE_PNL_PATH,
    )
    tool_def = _build_tool_definition(SCOPE_PNL_PATH)
    params = tool_def.get("parameters") or {}
    required = params.get("required") or []
    properties = params.get("properties") or {}
    self.assertIn("r_and_d_percent_of_revenue", required,
                  "R&D must be in the pnl_path tool schema's required params")
    self.assertIn("r_and_d_percent_of_revenue", properties,
                  "R&D must have a properties schema in the pnl_path tool")


class NexGenIter2UniversalRDApplicabilityTest(unittest.TestCase):
  def test_naics2_lookup_machinery_removed_from_post_intake_mapping(self) -> None:
    """All hardcoded NAICS-2 R&D applicability symbols are gone."""
    from client_intake_and_finmo import post_intake_mapping as _mapping
    for symbol in (
      "_DEFAULT_R_AND_D_APPLICABILITY_ROWS",
      "_R_AND_D_APPLICABILITY_TABLE_NAME",
      "_ENSURE_R_AND_D_APPLICABILITY_TABLE_READY",
      "_ENSURE_R_AND_D_APPLICABILITY_TABLE_LOCK",
      "_ensure_r_and_d_applicability_lookup_table",
      "load_post_intake_r_and_d_applicability_rows",
      "post_intake_r_and_d_applicability_for_naics2",
    ):
      self.assertFalse(
        hasattr(_mapping, symbol),
        f"{symbol} must be deleted from post_intake_mapping",
      )

  def test_deterministic_naics_wrapper_is_no_op(self) -> None:
    """The deterministic NAICS wrapper always returns None — no
    NAICS-2 archetype branching anywhere."""
    from client_intake_and_finmo.post_intake_contracts.runner import (  # noqa: WPS433
      _derive_r_and_d_applicability_from_naics,
    )
    for naics, label in _NAICS_MIX:
      result = _derive_r_and_d_applicability_from_naics(
        business_facts={},
        ops_json={"business_naics_6": naics},
        financials_json={},
        financials_year1_json={},
        model_input_json={},
      )
      self.assertIsNone(result, f"NAICS {naics} ({label}) should not branch")

  def test_estimator_returns_universal_enabled_for_every_naics(self) -> None:
    """Every NAICS gets `r_and_d_enabled=True` with the universal
    decision_source tag and a non-empty rationale."""
    from client_intake_and_finmo.post_intake_contracts.runner import (  # noqa: WPS433
      _estimate_r_and_d_applicability_with_gpt,
    )
    for naics, label in _NAICS_MIX:
      result = _estimate_r_and_d_applicability_with_gpt(
        business_facts={},
        ops_json={"business_naics_6": naics},
        financials_json={},
        financials_year1_json={},
        model_input_json={},
      )
      self.assertIsInstance(result, dict, f"NAICS {naics} ({label})")
      self.assertTrue(result.get("r_and_d_enabled"),
                      f"NAICS {naics} ({label}) should be universally enabled")
      self.assertEqual(result.get("decision_source"),
                       "universal_post_phase_9_p3_10",
                       f"NAICS {naics} ({label})")
      self.assertTrue(result.get("rationale"),
                      f"NAICS {naics} ({label}) must have rationale")
      # The universal stub does not expose naics_provenance — the
      # lookup table is gone.
      self.assertNotIn("naics_provenance", result,
                       f"NAICS {naics} ({label}) leaked NAICS provenance")

  def test_estimator_makes_no_openai_call(self) -> None:
    """The universal stub is a constant — no OPENAI_API_KEY required.
    Smoke-test by clearing the env var."""
    from client_intake_and_finmo.post_intake_contracts.runner import (  # noqa: WPS433
      _estimate_r_and_d_applicability_with_gpt,
    )
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
      result = _estimate_r_and_d_applicability_with_gpt(
        business_facts={},
        ops_json={"business_naics_6": "513210"},
        financials_json={},
        financials_year1_json={},
        model_input_json={},
      )
      self.assertTrue(result.get("r_and_d_enabled"))
    finally:
      if saved is not None:
        os.environ["OPENAI_API_KEY"] = saved


class NexGenIter2RealismRuleNoNAICSBranchTest(unittest.TestCase):
  def test_r_and_d_when_applicable_rule_has_no_naics_2_set(self) -> None:
    """The validator's r_and_d_when_applicable rule no longer carves
    out NAICS-2 sectors {51, 54}; the skip is universal whenever R&D
    is zero across the entire 20-quarter forecast."""
    import pathlib
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_realism"
      / "validator.py"
    )
    text = p.read_text(encoding="utf-8")
    # Find the rule body region
    start = text.index('if rule == "r_and_d_when_applicable":')
    end = text.index("if rule ==", start + 1)  # next rule
    branch = text[start:end]
    self.assertNotIn("r_and_d_expected_naics_2", branch,
                     "The NAICS-2 hardcoded set must be removed")
    self.assertNotIn('{"51", "54"}', branch,
                     "The {51, 54} archetype carve-out must be removed")
    self.assertNotIn("skip_r_and_d_not_applicable_to_business", branch,
                     "The not_applicable_to_business skip reason was "
                     "tied to applicability decision; replace with the "
                     "universal skip_r_and_d_zero_across_forecast")
    self.assertIn("skip_r_and_d_zero_across_forecast", branch,
                  "The new universal skip reason must be present")


class NexGenIter2FinmoBridgeRDDisableRemovedTest(unittest.TestCase):
  def test_finmo_bridge_no_longer_disables_rd_row(self) -> None:
    """The conditional disable in finmo_bridge that zeroed R&D values
    when r_and_d_enabled=False is removed. R&D flows through every
    business."""
    import pathlib
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "finmo_bridge.py"
    )
    text = p.read_text(encoding="utf-8")
    self.assertNotIn("r_and_d_disabled_by_business_applicability", text,
                     "The disable derived_driver tag must be gone")
    self.assertNotIn(
      "if isinstance(r_and_d_row, dict) and not bool(r_and_d_policy.get(\"r_and_d_enabled\"))",
      text,
      "The conditional disable branch must be removed",
    )


if __name__ == "__main__":
  unittest.main()
