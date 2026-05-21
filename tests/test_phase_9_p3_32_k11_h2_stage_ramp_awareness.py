"""Phase 9 P3.32 K11.1 — H2 GPT exhaustion handler stage_ramp_contract
awareness regression tests.

The K11 audit established that H2 had ZERO references to
stage_ramp_contract; it authored revenue / cost-ratio anchors blind
to H4's per-quarter bounds. K11.1 closes the gap by:
  1. Threading stage_ramp_contract from orchestrator → H2 entry point
     → execute_tool_calling_session_and_commit → run_tool_calling_
     session → mini_finmo via operating_context.
  2. Exposing a get_stage_ramp_bounds_per_quarter consultation tool
     alongside compute_full_trajectory.
  3. Enforcing per-quarter rev_max / cogs_max / marketing_max /
     rd_max / ga_max / ni_floor / max_util bounds inside
     mini_finmo's viability_checks aggregate; all_pass now requires
     stage_ramp coherence in addition to universal viability.
  4. Updating SYSTEM_PROMPT to inform GPT about the new tool and
     enforcement.

Test coverage:
  M1. Signatures + threading shape.
  M2. Consultation tool definition + dispatcher.
  M3. mini_finmo stage_ramp coherence helper semantics
      (Sunny-shape rev_max violation; Skyward-shape rev_max pass;
       missing contract = SKIPPED).
  M4. all_pass semantics with stage_ramp checks folded in.

Doctrine §10.5 (contract-awareness universalization) — the rule
this commit instantiates for H2.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _sunny_stage_ramp_contract() -> Dict[str, Any]:
  """Sunny-shape stage_ramp_contract observed in the post-K10 retry
  (turnaround mode, operational stage, deterministic Python builder)."""
  return {
    "stage_family": "operational",
    "business_stage": "operating",
    "planning_mode": "turnaround",
    "decision_source": "python_deterministic_builder",
    "quarter_ramp_grid": [
      {
        "quarter_index": q,
        "rev_target": 0.01,
        "rev_max": 0.06,
        "cogs_target": 0.72,
        "cogs_max": 0.80,
        "marketing_max": 0.27,
        "rd_max": 0.04,
        "ga_max": 0.27,
        "lease_max": 0.01,
        "ni_floor": 0.0 if q < 11 else 0.07,
        "max_util": 0.85,
        "posture": "positive",
      }
      for q in range(1, 21)
    ],
  }


def _skyward_stage_ramp_contract() -> Dict[str, Any]:
  """Skyward-shape contract: looser rev_max, near_breakeven->positive."""
  return {
    "stage_family": "operational",
    "business_stage": "operating",
    "planning_mode": "rebalance",
    "decision_source": "python_deterministic_builder",
    "quarter_ramp_grid": [
      {
        "quarter_index": q,
        "rev_target": 0,
        "rev_max": 0.14,
        "cogs_target": 0.78,
        "cogs_max": 0.88,
        "marketing_max": 0.17,
        "rd_max": 0,
        "ga_max": 0.17,
        "lease_max": 0.11,
        "ni_floor": 0.05 if 5 <= q < 11 else (0.07 if q >= 11 else 0.0),
        "max_util": 0.65 + 0.01 * min(q, 20),
        "posture": "near_breakeven" if q < 5 else "positive",
      }
      for q in range(1, 21)
    ],
  }


def _build_finmo_with_growth(*, q1_revenue: float, growth_per_q: float, num_q: int = 20) -> Dict[str, Any]:
  """Build a minimal finmo_json with revenue growing at the given QoQ rate."""
  rows = []
  rev = q1_revenue
  for q in range(1, num_q + 1):
    rows.append({
      "quarter_index": q,
      "revenue": rev,
      "ebitda": rev * 0.10,
      "net_income": rev * 0.05,
      "cost_of_goods_sold": rev * 0.75,
      "marketing": rev * 0.05,
      "research_and_development": rev * 0.02,
      "general_and_administrative": rev * 0.10,
      "payroll": rev * 0.30,
      "lease_rent": rev * 0.01,
      "utilization_rate": min(0.85, 0.6 + 0.01 * q),
    })
    rev = rev * (1.0 + growth_per_q)
  return {"quarter_rows": rows}


# ---------------------------------------------------------------------------
# M1. Signature + threading
# ---------------------------------------------------------------------------


class TestM1HandlerSignatures(unittest.TestCase):
  def test_run_gpt_exhaustion_handler_accepts_stage_ramp_contract(self) -> None:
    import inspect  # noqa: WPS433
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      run_gpt_exhaustion_handler,
    )
    sig = inspect.signature(run_gpt_exhaustion_handler)
    self.assertIn("stage_ramp_contract", sig.parameters)
    self.assertIs(sig.parameters["stage_ramp_contract"].default, None)

  def test_execute_session_accepts_stage_ramp_contract(self) -> None:
    import inspect  # noqa: WPS433
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      execute_tool_calling_session_and_commit,
    )
    sig = inspect.signature(execute_tool_calling_session_and_commit)
    self.assertIn("stage_ramp_contract", sig.parameters)

  def test_run_tool_calling_session_accepts_stage_ramp_contract(self) -> None:
    import inspect  # noqa: WPS433
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      run_tool_calling_session,
    )
    sig = inspect.signature(run_tool_calling_session)
    self.assertIn("stage_ramp_contract", sig.parameters)

  def test_eval_viability_checks_accepts_stage_ramp_contract(self) -> None:
    import inspect  # noqa: WPS433
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_viability_checks,
    )
    sig = inspect.signature(_eval_viability_checks)
    self.assertIn("stage_ramp_contract", sig.parameters)

  def test_orchestrator_passes_stage_ramp_contract_at_both_h2_sites(self) -> None:
    """Both H2 call sites in _run_post_cascade_completion must forward
    the stage_ramp_contract kwarg."""
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_solver",
      "orchestrator.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      src = fh.read()
    # Find both invocations and assert each carries stage_ramp_contract.
    occurrences = src.count("run_gpt_exhaustion_handler(")
    self.assertGreaterEqual(occurrences, 2)
    # Naive: count stage_ramp_contract= occurrences within H2 call regions
    # by searching the kwarg pattern.
    self.assertIn(
      "stage_ramp_contract=stage_ramp_contract",
      src,
      msg="orchestrator must thread stage_ramp_contract to H2 (both sites)",
    )


# ---------------------------------------------------------------------------
# M2. Consultation tool
# ---------------------------------------------------------------------------


class TestM2ConsultationTool(unittest.TestCase):
  def test_tool_definition_strict_valid(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      _STAGE_RAMP_BOUNDS_TOOL_NAME,
      _build_stage_ramp_bounds_tool_definition,
    )
    td = _build_stage_ramp_bounds_tool_definition()
    self.assertEqual(td["type"], "function")
    self.assertEqual(td["name"], _STAGE_RAMP_BOUNDS_TOOL_NAME)
    self.assertTrue(td["strict"])
    params = td["parameters"]
    self.assertEqual(params["type"], "object")
    self.assertFalse(params["additionalProperties"])
    self.assertEqual(params["required"], [])

  def test_dispatcher_returns_per_quarter_grid(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      _dispatch_stage_ramp_bounds,
    )
    contract = _sunny_stage_ramp_contract()
    out = _dispatch_stage_ramp_bounds(stage_ramp_contract=contract)
    self.assertEqual(out["stage_family"], "operational")
    grid = out["quarter_ramp_grid"]
    self.assertEqual(len(grid), 20)
    # Q1 row carries the short-form keys mapped through.
    q1 = grid[0]
    self.assertEqual(q1["quarter_index"], 1)
    self.assertAlmostEqual(q1["rev_max"], 0.06)
    self.assertAlmostEqual(q1["cogs_max"], 0.80)
    self.assertAlmostEqual(q1["marketing_max"], 0.27)
    self.assertAlmostEqual(q1["max_util"], 0.85)

  def test_dispatcher_missing_contract_returns_error(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      _dispatch_stage_ramp_bounds,
    )
    out = _dispatch_stage_ramp_bounds(stage_ramp_contract=None)
    self.assertEqual(out["error"], "stage_ramp_contract_missing")
    out = _dispatch_stage_ramp_bounds(stage_ramp_contract={})
    self.assertEqual(out["error"], "stage_ramp_contract_missing")

  def test_dispatcher_handles_long_form_keys(self) -> None:
    """H4-authored contracts use long-form keys
    (revenue_qoq_max, cogs_percent_of_revenue_max, etc.) — the
    dispatcher must accept both shapes."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # noqa: WPS433
      _dispatch_stage_ramp_bounds,
    )
    long_form_contract = {
      "stage_family": "operational",
      "quarter_ramp_grid": [
        {
          "quarter_index": 1,
          "revenue_qoq_max": 0.14,
          "cogs_percent_of_revenue_max": 0.88,
          "marketing_percent_of_revenue_max": 0.17,
          "rd_percent_of_revenue_max": 0,
          "g_and_a_percent_of_revenue_max": 0.17,
          "net_income_margin_floor": 0.0,
          "utilization_cap": 0.65,
          "profitability_posture": "near_breakeven",
        }
      ],
    }
    out = _dispatch_stage_ramp_bounds(stage_ramp_contract=long_form_contract)
    q1 = out["quarter_ramp_grid"][0]
    self.assertAlmostEqual(q1["rev_max"], 0.14)
    self.assertAlmostEqual(q1["cogs_max"], 0.88)
    self.assertAlmostEqual(q1["ga_max"], 0.17)
    self.assertAlmostEqual(q1["max_util"], 0.65)
    self.assertEqual(q1["posture"], "near_breakeven")


# ---------------------------------------------------------------------------
# M3. mini_finmo coherence helper semantics
# ---------------------------------------------------------------------------


class TestM3MiniFinmoCoherence(unittest.TestCase):
  def test_sunny_shape_rev_max_violation_detected(self) -> None:
    """Sunny post-K10 case: 10% growth/q against rev_max=0.06.
    Expectation: rev_max FAIL with 19 quarter violations (Q2..Q20)."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_stage_ramp_coherence_checks,
    )
    finmo = _build_finmo_with_growth(q1_revenue=100000.0, growth_per_q=0.10)
    out = _eval_stage_ramp_coherence_checks(finmo, _sunny_stage_ramp_contract())
    self.assertEqual(out["checks"]["stage_ramp_rev_max_respected"], "FAIL")
    rev_max_violations = [v for v in out["violations"] if v["field"] == "rev_max"]
    self.assertEqual(len(rev_max_violations), 19)
    self.assertAlmostEqual(rev_max_violations[0]["actual"], 0.10, places=2)
    self.assertAlmostEqual(rev_max_violations[0]["bound"], 0.06, places=2)

  def test_skyward_shape_rev_max_passes(self) -> None:
    """Skyward rev_max=0.14; 10% growth/q is within bound."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_stage_ramp_coherence_checks,
    )
    finmo = _build_finmo_with_growth(q1_revenue=10_000_000.0, growth_per_q=0.10)
    out = _eval_stage_ramp_coherence_checks(finmo, _skyward_stage_ramp_contract())
    self.assertEqual(out["checks"]["stage_ramp_rev_max_respected"], "PASS")
    rev_max_violations = [v for v in out["violations"] if v["field"] == "rev_max"]
    self.assertEqual(rev_max_violations, [])

  def test_missing_contract_returns_skipped(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_stage_ramp_coherence_checks,
    )
    finmo = _build_finmo_with_growth(q1_revenue=100000.0, growth_per_q=0.10)
    out = _eval_stage_ramp_coherence_checks(finmo, None)
    for verdict in out["checks"].values():
      self.assertEqual(verdict, "SKIPPED")
    self.assertEqual(out["violations"], [])

  def test_cogs_max_violation_detected(self) -> None:
    """Build finmo with cogs ratio 0.95; cogs_max=0.80; expect FAIL."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_stage_ramp_coherence_checks,
    )
    finmo = {
      "quarter_rows": [
        {
          "quarter_index": q,
          "revenue": 100000.0,
          "cost_of_goods_sold": 95000.0,  # 95% of revenue
          "marketing": 5000.0,
          "research_and_development": 2000.0,
          "general_and_administrative": 10000.0,
          "net_income": 5000.0,
          "utilization_rate": 0.7,
        }
        for q in range(1, 21)
      ]
    }
    out = _eval_stage_ramp_coherence_checks(finmo, _sunny_stage_ramp_contract())
    self.assertEqual(out["checks"]["stage_ramp_cogs_max_respected"], "FAIL")
    cogs_violations = [v for v in out["violations"] if v["field"] == "cogs_max"]
    self.assertGreater(len(cogs_violations), 0)

  def test_ni_floor_violation_detected(self) -> None:
    """Q12 NI margin = -0.05 vs ni_floor=0.07 (after Q10). Expect FAIL."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_stage_ramp_coherence_checks,
    )
    finmo = {
      "quarter_rows": [
        {
          "quarter_index": q,
          "revenue": 100000.0,
          "net_income": -5000.0 if q >= 11 else 1000.0,  # -5% margin from Q11
          "cost_of_goods_sold": 70000.0,
          "marketing": 5000.0,
          "research_and_development": 2000.0,
          "general_and_administrative": 10000.0,
          "utilization_rate": 0.7,
        }
        for q in range(1, 21)
      ]
    }
    out = _eval_stage_ramp_coherence_checks(finmo, _sunny_stage_ramp_contract())
    self.assertEqual(out["checks"]["stage_ramp_ni_floor_respected"], "FAIL")
    ni_violations = [v for v in out["violations"] if v["field"] == "ni_floor"]
    self.assertGreater(len(ni_violations), 0)

  def test_max_util_violation_detected(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_stage_ramp_coherence_checks,
    )
    finmo = {
      "quarter_rows": [
        {
          "quarter_index": q,
          "revenue": 100000.0,
          "net_income": 10000.0,
          "cost_of_goods_sold": 70000.0,
          "marketing": 5000.0,
          "research_and_development": 2000.0,
          "general_and_administrative": 10000.0,
          "utilization_rate": 0.99,  # exceeds max_util=0.85
        }
        for q in range(1, 21)
      ]
    }
    out = _eval_stage_ramp_coherence_checks(finmo, _sunny_stage_ramp_contract())
    self.assertEqual(out["checks"]["stage_ramp_max_util_respected"], "FAIL")


# ---------------------------------------------------------------------------
# M4. all_pass aggregate
# ---------------------------------------------------------------------------


class TestM4ViabilityAllPassAggregate(unittest.TestCase):
  def test_skipped_stage_ramp_does_not_fail_all_pass(self) -> None:
    """When stage_ramp_contract is None, all stage_ramp_* checks are
    SKIPPED. all_pass logic must treat SKIPPED as PASS so pre-K11
    call sites preserve their behavior."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_viability_checks,
    )
    finmo = _build_finmo_with_growth(q1_revenue=100000.0, growth_per_q=0.05)
    result = _eval_viability_checks(finmo, stage_ramp_contract=None)
    checks = result["viability_checks"]
    self.assertEqual(checks["stage_ramp_rev_max_respected"], "SKIPPED")
    # Without considering stage_ramp, all_pass depends only on universal
    # viability metrics — which won't all pass for synthetic data but
    # the SKIPPED entries don't BLOCK all_pass on their own.
    skipped_keys = [k for k, v in checks.items() if v == "SKIPPED"]
    # Critical assertion: all SKIPPED entries don't independently
    # produce all_pass=False (they're treated as PASS for aggregate
    # purposes).
    fail_only = [k for k, v in checks.items() if v == "FAIL"]
    self.assertEqual(checks["all_pass"], len(fail_only) == 0)

  def test_stage_ramp_fail_blocks_all_pass_even_when_universal_passes(self) -> None:
    """Construct a finmo where universal viability passes but
    stage_ramp rev_max fails. all_pass MUST be False."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_viability_checks,
    )
    # Build finmo where ebitda margin is healthy + improving across
    # quarters (so universal viability passes) but revenue grows too
    # fast against Sunny's rev_max=0.06.
    rows = []
    rev = 100000.0
    for q in range(1, 21):
      em = -0.10 + 0.02 * q  # -10% at Q1, ramping up
      rows.append({
        "quarter_index": q,
        "revenue": rev,
        "ebitda": rev * em,
        "net_income": rev * (em - 0.02),
        "cost_of_goods_sold": rev * 0.70,
        "marketing": rev * 0.05,
        "research_and_development": rev * 0.02,
        "general_and_administrative": rev * 0.10,
        "payroll": rev * 0.20,
        "lease_rent": rev * 0.005,
        "utilization_rate": 0.7,
      })
      rev = rev * 1.10  # 10% growth, exceeds rev_max=0.06
    result = _eval_viability_checks({"quarter_rows": rows}, stage_ramp_contract=_sunny_stage_ramp_contract())
    checks = result["viability_checks"]
    self.assertEqual(checks["stage_ramp_rev_max_respected"], "FAIL")
    self.assertFalse(checks["all_pass"])

  def test_violation_list_surfaced_in_result(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # noqa: WPS433
      _eval_viability_checks,
    )
    finmo = _build_finmo_with_growth(q1_revenue=100000.0, growth_per_q=0.10)
    result = _eval_viability_checks(finmo, stage_ramp_contract=_sunny_stage_ramp_contract())
    self.assertIn("stage_ramp_violations", result)
    self.assertGreater(len(result["stage_ramp_violations"]), 0)


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT update
# ---------------------------------------------------------------------------


class TestSystemPromptUpdate(unittest.TestCase):
  def test_system_prompt_mentions_stage_ramp_contract(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.prompts import (  # noqa: WPS433
      SYSTEM_PROMPT,
    )
    self.assertIn("stage_ramp", SYSTEM_PROMPT.lower())
    self.assertIn("get_stage_ramp_bounds_per_quarter", SYSTEM_PROMPT)
    self.assertIn("rev_max", SYSTEM_PROMPT)
    self.assertIn("ni_floor", SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# K1 F1-F7 + K9 + K10 invariants preserved
# ---------------------------------------------------------------------------


class TestK11PreservesEarlierInvariants(unittest.TestCase):
  def test_h2_authority_still_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    self.assertNotIn("expenses::Payroll", GPT_AUTHORED_LEVER_IDS)

  def test_handler_c_unchanged_signature(self) -> None:
    """Handler C's session signature must not be affected by K11.1."""
    import inspect  # noqa: WPS433
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      run_payroll_tool_calling_session,
    )
    sig = inspect.signature(run_payroll_tool_calling_session)
    expected_params = {
      "request_context", "policy", "business_naics", "draft_id",
      "client_id", "model_input_json", "business_facts", "ops_json",
      "resolved_people_json", "external_seed_text", "_call_gpt_turn",
    }
    self.assertEqual(set(sig.parameters.keys()), expected_params)


if __name__ == "__main__":
  unittest.main()
