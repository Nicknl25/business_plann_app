"""Round-1 deterministic payroll producer — tests.

Authority: docs/architecture/payroll_producer_spec.md. Verifies the dollar-path
producer that REPLACES build_pending_payroll_stub on the canonical
set_payroll_schedule(contract=None) path:

  1. FTE sized from revenue via the dollar path reproduces the builder's
     payroll dollars EXACTLY (same wage path) — verify item #1.
  2. The producer's contract PASSES validate_payroll_headcount_contract_payload
     and builds — verify item #2.
  3. The staffing mix weights track OEWS tot_emp employment share — Part C.
  4. No productivity coefficient sizes FTE: doubling revenue scales supporting
     FTE proportionally (Fix #2 OQ-1 wall avoided) — Part B.
  5. The four confirmed values are sourced as NAMED policy/constants — Step 1.

These are integration tests: they read the real OEWS catalog + headcount
policy from MySQL. When no DB is configured they skip (honest, CI-safe).
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

try:  # load .env so get_mysql_connection has MYSQL_* available
  from dotenv import load_dotenv
  load_dotenv(os.path.join(HERE, os.pardir, ".env"))
except Exception:
  pass

H = 20
NAICS = "722511"  # limited-service restaurants — broad OEWS detailed coverage


def _db_available() -> bool:
  try:
    from client_intake_and_finmo.intake_submission import get_mysql_connection
    conn = get_mysql_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM oews_state_wages LIMIT 1")
    cur.fetchone()
    conn.close()
    return True
  except Exception:
    return False


def _inputs(*, revenue_q1=100000, revenue_step=20000, with_key_person=True):
  ops = {"business_naics_6": NAICS}
  finmo = {"quarter_rows": [
    {"quarter_index": q, "revenue": revenue_q1 + (q - 1) * revenue_step}
    for q in range(1, H + 1)
  ]}
  model_input = {"sections": {"revenue": [
    {"revenue_slot_key": "slot1", "driver": "capacity",
     "values": [5000 + (q - 1) * 500 for q in range(1, H + 1)], "lob": "L", "product": "P"},
    {"revenue_slot_key": "slot1", "driver": "unit price", "values": [20.0] * H},
    {"revenue_slot_key": "slot1", "driver": "utilization", "values": [0.5] * H},
  ]}, "periods": [{"is_stub": True}] + [{"is_stub": False} for _ in range(H)]}
  financials = {"payroll_total_year1": 200000}
  year1 = {"company_revenue_total_year1": 800000}
  people = {"people": [{"role_title": "Owner / General Manager",
                        "full_name": "Jane Doe", "annual_wage": 120000}]} if with_key_person else {}
  return dict(business_facts={}, ops_json=ops, people_json=people,
              financials_json=financials, financials_year1_json=year1,
              model_input_json=model_input, finmo_json=finmo)


@unittest.skipUnless(_db_available(), "MySQL/OEWS not configured")
class PayrollProducerRound1Test(unittest.TestCase):

  def _author(self, **overrides):
    from client_intake_and_finmo.post_intake_headcount.schedule import (
      author_round1_payroll_contract,
    )
    kw = _inputs()
    kw.update(overrides)
    return author_round1_payroll_contract(**kw)

  def test_contract_passes_canonical_validator(self) -> None:
    """Verify #2 — producer output passes validate_payroll_headcount_contract_payload."""
    from client_intake_and_finmo.post_intake_headcount.schedule import (
      validate_payroll_headcount_contract_payload,
    )
    contract = self._author()
    normalized = validate_payroll_headcount_contract_payload(payload=contract)
    # every contract-required root field present + enum-valid
    self.assertIn(contract["capacity_labor_model"],
                  {"labor_driven", "hybrid", "system_driven", "expert_driven"})
    self.assertIn(contract["labor_intensity_class"], {"low", "medium", "high", "expert"})
    self.assertGreater(contract["capacity_units_per_supporting_fte"], 0.0)
    self.assertTrue(contract["rationale"].strip())
    # THE GRID IS EMPTY OR IT COVERS THE HORIZON (2026-08-27). It used to be
    # "at least 20 rows, always", which asserted every business employs
    # supporting staff; a business whose named people are its whole payroll
    # is a real shape and now returns an empty grid. THIS fixture is exactly
    # that case - Jane Doe at 120,000/yr costs 36,600 a quarter against a
    # 25,000 payroll budget - so zero supporting titles is the correct
    # answer for it. The populated shape is covered by the no-key-person and
    # higher-revenue fixtures below.
    grid = contract["payroll_headcount_grid"]
    if grid:
      self.assertGreaterEqual(len(grid), 20)
      self.assertEqual({int(row["q"]) for row in grid}, set(range(1, 21)),
                       "a non-empty grid must still cover every quarter Q1-Q20")
    self.assertEqual(normalized["labor_intensity_class"], contract["labor_intensity_class"])

  def test_an_unfunded_supporting_block_is_empty_and_a_funded_one_covers_the_horizon(self) -> None:
    """The two legal shapes, side by side on the same producer: a business
    whose named people outcost the payroll budget carries NO supporting
    titles (rather than six floored at 0.01 of a person), and one that can
    afford them carries rows for every quarter."""
    unfunded = self._author()["payroll_headcount_grid"]
    self.assertEqual(unfunded, [], "named people outcost the budget - expected no supporting titles")
    from client_intake_and_finmo.post_intake_headcount.schedule import (
      author_round1_payroll_contract,
    )
    funded = author_round1_payroll_contract(
      **_inputs(with_key_person=False))["payroll_headcount_grid"]
    self.assertGreaterEqual(len(funded), 20)
    self.assertEqual({int(row["q"]) for row in funded}, set(range(1, 21)))
    self.assertTrue(all(float(row["ending_fte"]) >= 0.25 for row in funded),
                    "a carried title must be at least a quarter of a real person")

  def test_fte_reproduces_builder_payroll_exactly(self) -> None:
    """Verify #1 — the producer's FTE, fed to the builder, reproduces the
    builder's payroll dollars to the dollar (same wage path)."""
    from client_intake_and_finmo.post_intake_headcount.schedule import (
      validate_payroll_headcount_contract_payload,
      build_payroll_headcount_payload_from_contract,
      post_intake_headcount_policy_for,
    )
    contract = self._author(people_json={})  # supporting-only so quarter totals are pure
    normalized = validate_payroll_headcount_contract_payload(payload=contract)
    payload = build_payroll_headcount_payload_from_contract(
      normalized, draft_id="t", policy_code="default",
      model_input_json=_inputs()["model_input_json"], business_facts={},
      ops_json={"business_naics_6": NAICS}, people_json={})
    benefits = round(float(post_intake_headcount_policy_for("default").get(
      "default_payroll_tax_benefits_pct") or 0.22), 2)
    for q in (5, 10, 20):
      built = {r["oews_occ_title"]: r for r in payload["rows"]
               if int(r["quarter_index"]) == q and r["staffing_class"] == "supporting_staff"}
      predicted_total = 0
      builder_total = 0
      for r in [g for g in normalized["payroll_headcount_grid"] if int(g["quarter_index"]) == q]:
        br = built[r["oews_occ_title"]]
        avg = round((float(r["starting_fte"]) + float(r["ending_fte"])) / 2.0, 2)
        wage = int(br["annual_wage"])
        wage_cost = int(round(avg * wage / 4.0))
        taxes = int(round(wage_cost * benefits))
        predicted_total += int(wage_cost + taxes)
        builder_total += int(br["total_quarterly_payroll"])
      self.assertEqual(predicted_total, builder_total,
                       f"Q{q}: producer-predicted payroll must equal builder output")

  def test_built_ratio_within_class_band(self) -> None:
    """The built payroll/revenue ratio lands inside the resolved class band."""
    from client_intake_and_finmo.post_intake_headcount.schedule import (
      validate_payroll_headcount_contract_payload,
      build_payroll_headcount_payload_from_contract,
    )
    from client_intake_and_finmo.post_intake_headcount.lookup import (
      headcount_payroll_revenue_sanity_bounds, post_intake_headcount_policy_for,
    )
    contract = self._author(people_json={})
    normalized = validate_payroll_headcount_contract_payload(payload=contract)
    payload = build_payroll_headcount_payload_from_contract(
      normalized, draft_id="t", policy_code="default",
      model_input_json=_inputs()["model_input_json"], business_facts={},
      ops_json={"business_naics_6": NAICS}, people_json={})
    band = headcount_payroll_revenue_sanity_bounds(
      post_intake_headcount_policy_for("default"),
      labor_intensity_class=contract["labor_intensity_class"])
    qt = {r["quarter_index"]: r for r in payload["quarter_totals"]}
    for q in (10, 20):
      rev = 100000 + (q - 1) * 20000
      ratio = qt[q]["payroll"] / rev
      self.assertGreaterEqual(ratio, band["min_pct"])
      self.assertLessEqual(ratio, band["max_pct"])

  def test_mix_weights_track_tot_emp(self) -> None:
    """Part C — the supporting title with the largest OEWS tot_emp gets the
    largest aggregate FTE in the schedule."""
    from client_intake_and_finmo.post_intake_headcount import schedule as S
    catalog = S._oews_title_catalog_for_business(
      business_facts={}, ops_json={"business_naics_6": NAICS}, people_json={})
    by_title = {c["occ_title"]: c for c in catalog["title_candidates"]}
    contract = self._author(people_json={})
    fte_by_title: dict = {}
    for r in contract["payroll_headcount_grid"]:
      fte_by_title[r["oews_occ_title"]] = fte_by_title.get(r["oews_occ_title"], 0.0) + float(r["ending_fte"])
    # title with most aggregate FTE should be the one with the largest tot_emp
    top_fte_title = max(fte_by_title, key=lambda t: fte_by_title[t])
    selected_emp = {t: float(by_title[t].get("tot_emp") or 0.0) for t in fte_by_title}
    top_emp_title = max(selected_emp, key=lambda t: selected_emp[t])
    self.assertEqual(top_fte_title, top_emp_title)

  def test_fte_scales_with_revenue_not_productivity(self) -> None:
    """Part B / Fix #2 OQ-1 — FTE is driven by revenue dollars, not a
    productivity coefficient. Doubling revenue ~doubles supporting FTE."""
    base = self._author(people_json={})
    doubled = self._author(people_json={}, finmo_json={"quarter_rows": [
      {"quarter_index": q, "revenue": 2 * (100000 + (q - 1) * 20000)} for q in range(1, H + 1)]})

    def _support_fte_q(contract, q):
      return sum(float(r["ending_fte"]) for r in contract["payroll_headcount_grid"]
                 if int(r.get("q") or r.get("quarter_index") or 0) == q)
    # Q20 has ample budget (no early-quarter floor distortion).
    base_fte = _support_fte_q(base, 20)
    doubled_fte = _support_fte_q(doubled, 20)
    self.assertGreater(base_fte, 0.0)
    self.assertAlmostEqual(doubled_fte / base_fte, 2.0, delta=0.1)

  def test_named_policy_defaults_present(self) -> None:
    """Step 1 — the four confirmed values are named (not inline literals)."""
    from client_intake_and_finmo.post_intake_headcount import schedule as S
    from client_intake_and_finmo.post_intake_headcount.lookup import (
      post_intake_headcount_policy_for,
    )
    self.assertEqual(S.ROUND1_INTENSITY_TO_CAPACITY_LABOR_MODEL, {
      "low": "system_driven", "medium": "hybrid",
      "high": "labor_driven", "expert": "expert_driven"})
    self.assertEqual(S.ROUND1_MIX_TOP_N, 6)
    self.assertEqual(S.ROUND1_REVENUE_SOURCE_PRIORITY[0], "finmo_revenue")
    # benefits is a named DB policy value (= 0.22), not re-declared inline
    self.assertAlmostEqual(
      float(post_intake_headcount_policy_for("default")["default_payroll_tax_benefits_pct"]),
      0.22, places=4)


class CapacityOverwriteLoopBrokenTest(unittest.TestCase):
  """Part E — apply_payroll_supported_capacity_to_model_input no longer
  overwrites revenue.Capacity from FTE. The revenue->FTE->capacity->revenue
  loop is formally broken: capacity stays the step-10 anchor. No DB needed."""

  def _run(self):
    from client_intake_and_finmo.post_intake_headcount.schedule import (
      apply_payroll_supported_capacity_to_model_input,
    )
    from client_intake_and_finmo.post_intake_sequence import (
      post_intake_sequence_step_scope,
    )
    anchor = [0.0] + [5000 + (q - 1) * 500 for q in range(1, H + 1)]  # [stub]+20 live
    mi = {"sections": {"revenue": [{"revenue_slot_key": "s1", "driver": "capacity",
          "values": list(anchor), "label": "Capacity"}]},
          "periods": [{"is_stub": True}] + [{"is_stub": False} for _ in range(H)]}
    sched = {"capacity_units_per_supporting_fte": 1500.0, "payroll_headcount_grid": [
      {"q": q, "oews_occ_title": "X", "starting_fte": 2.0, "hires": 0.0,
       "ending_fte": 2.0, "payroll_tax_benefits_pct": 0.22} for q in range(1, H + 1)]}
    with post_intake_sequence_step_scope(
      step_key="payroll_headcount_schedule", phase="initial_grid",
      executor_function="apply_payroll_supported_capacity_to_model_input",
      step_kind="orchestration",
    ):
      out = apply_payroll_supported_capacity_to_model_input(mi, sched, live_count=H)
    cap_row = [r for r in out["sections"]["revenue"] if r["driver"] == "capacity"][0]
    return anchor, cap_row, out

  def test_capacity_stays_step10_anchor_not_fte_derived(self) -> None:
    anchor, cap_row, _ = self._run()
    self.assertEqual(cap_row["values"], anchor, "capacity must be unchanged (step-10 anchor)")
    # FTE-derived would be 2.0 * 1500 = 3000 in every quarter; assert it is NOT.
    self.assertTrue(all(abs(float(v) - 3000.0) > 1e-6 for v in cap_row["values"][1:]),
                    "capacity must NOT equal the FTE-derived value (loop broken)")

  def test_marker_preserved_for_finmo_freeze(self) -> None:
    _, cap_row, out = self._run()
    self.assertEqual(cap_row.get("derived_driver"), "payroll_supported_capacity")
    self.assertEqual(cap_row["payroll_supported_capacity"]["capacity_source"],
                     "revenue_primary_step10_anchor")
    rt = out["derived_driver_runtime"]["payroll_supported_capacity"]
    self.assertEqual(rt["mode"], "revenue_primary_consistency_check")

  def test_equality_verifier_no_longer_enforces_fte_derivation(self) -> None:
    """The capacity==FTE*productivity enforcer is gone; only the structural
    marker check remains (marked rows -> no violations)."""
    from client_intake_and_finmo.post_intake_headcount import schedule as S
    _, _, out = self._run()
    violations = S._payroll_supported_capacity_model_input_violations(
      out, {"capacity_units_per_supporting_fte": 1500.0,
            "payroll_headcount_grid": [{"q": q, "oews_occ_title": "X", "starting_fte": 2.0,
             "hires": 0.0, "ending_fte": 2.0, "payroll_tax_benefits_pct": 0.22}
            for q in range(1, H + 1)]}, live_count=H)
    self.assertEqual(violations, [], "marked anchor capacity must pass (no equality enforcement)")


if __name__ == "__main__":
  unittest.main()
