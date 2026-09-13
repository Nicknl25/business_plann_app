"""THE THREE COMMITMENT QUESTIONS (Nick 2026-09-12): lease signed and term,
contracted price, staffing ceiling - asked in financials, on the required
list, and read by the walk's rent, price and volume levers as floors.
Every client so far had to volunteer these mid-walk after being offered a
move they could not take.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo import intake_required_fields as RF  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from client_intake_and_finmo.intake_coherence import evaluator as EV  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from api_handlers import intake_consult as H  # noqa: E402


class TheyAreOnTheOneRequiredList(unittest.TestCase):
  def test_every_required_commitment_has_a_question_and_a_human_name(self):
    for f in RF.FINANCIALS_COMMITMENTS_REQUIRED:
      self.assertTrue(RF.commitment_question_for(f), f)
      self.assertNotEqual(RF.human_field_name(f), f.replace("_", " "), f)

  def test_missing_reads_the_persisted_object(self):
    self.assertEqual(RF.missing_financials_commitments({"monthly_rent_expense": 4500}),
                     ["lease_signed", "price_contracted", "staffing_ceiling"])
    self.assertEqual(RF.missing_financials_commitments({"monthly_rent_expense": 4500, "lease_signed": True,
                                                        "price_contracted": False, "staffing_ceiling": 0}),
                     ["lease_term_months"], "a signed lease is not answered until its term is")
    self.assertEqual(RF.missing_financials_commitments({"monthly_rent_expense": 4500, "lease_signed": True, "lease_term_months": 36,
                                                        "price_contracted": False, "staffing_ceiling": 0}), [])
    self.assertEqual(RF.missing_financials_commitments({"monthly_rent_expense": 0, "price_contracted": True, "staffing_ceiling": 12}),
                     [], "no rent, no lease question")

  def test_the_submit_gate_requires_them_in_the_clients_words(self):
    from client_intake_and_finmo import intake_submit_service as SUB
    src = inspect.getsource(SUB.process_intake_submission)
    self.assertIn("missing_financials_commitments(payload)", src)
    sentence = RF.describe_missing(["lease_signed", "staffing_ceiling"])
    self.assertIn("whether your rent is under a signed lease", sentence)
    self.assertIn("the most people you will employ", sentence)
    self.assertNotIn("lease_signed", sentence)


class TheFinancialsConversationAsksThem(unittest.TestCase):
  def test_the_stages_sit_where_the_facts_are(self):
    order = list(H._FINANCIALS_STAGE_ORDER)
    self.assertLess(order.index("cogs"), order.index("price_commitment"))
    self.assertEqual(order.index("lease_commitment"), order.index("monthly_rent_expense") + 1)
    self.assertEqual(order.index("staffing_ceiling"), order.index("current_num_employees") + 1)
    for st in ("lease_commitment", "price_commitment", "staffing_ceiling"):
      self.assertTrue(H._financials_stage_spec(st).get("patch_targets"), st)

  def test_the_questions_carry_the_clients_own_figures(self):
    q = H._build_lease_commitment_message(financials_json={"monthly_rent_expense": 4500})
    self.assertIn("$4,500", q); self.assertIn("signed lease", q); self.assertIn("month to month", q)
    q2 = H._build_staffing_ceiling_message(financials_json={"current_num_employees": 7})
    self.assertTrue(q2.startswith("You have 7 people today."), q2)
    self.assertIn("ceiling", q2)

  def test_a_signed_lease_is_not_complete_until_its_term_is(self):
    self.assertFalse(H._financials_stage_complete("lease_commitment", {"monthly_rent_expense": 4500}))
    self.assertFalse(H._financials_stage_complete("lease_commitment", {"monthly_rent_expense": 4500, "lease_signed": True}))
    self.assertTrue(H._financials_stage_complete("lease_commitment", {"monthly_rent_expense": 4500, "lease_signed": True, "lease_term_months": 30}))
    self.assertTrue(H._financials_stage_complete("lease_commitment", {"monthly_rent_expense": 4500, "lease_signed": False}))

  def test_no_rent_means_the_lease_question_is_never_asked(self):
    fin = {"monthly_rent_expense": 0}
    self.assertTrue(H._financials_stage_complete("lease_commitment", fin))
    self.assertEqual(RF.missing_financials_commitments(H._ensure_financials_stage_defaults(fin)),
                     ["price_contracted", "staffing_ceiling"])

  def test_a_yes_no_answer_lands_as_a_boolean_never_a_string(self):
    self.assertIs(H._coerce_yes_no(True), True); self.assertIs(H._coerce_yes_no("no"), False)
    self.assertIs(H._coerce_yes_no("month to month"), False); self.assertIsNone(H._coerce_yes_no("it depends"))

  def test_the_router_may_land_them(self):
    from client_intake_and_finmo import intent_router as IR
    src = inspect.getsource(IR)
    for f in ("lease_signed", "lease_term_months", "price_contracted", "staffing_ceiling"):
      self.assertGreaterEqual(src.count(f'"{f}"'), 2, f)   # schema + allowlist
    self.assertIn("current_stage.name is lease_commitment", src)
    self.assertIn("current_stage.name is price_commitment", src)
    self.assertIn("current_stage.name is staffing_ceiling", src)


ISOLDE = {
  "current_revenue": 3493100.0, "cogs_percent_of_revenue": 0.10277, "baseline_payroll_year1": 1900000.0,
  "payroll_basis_people_roles": [{"role_title": "Founder", "year1_payroll_amount": 205000.0}],
  "monthly_rent_expense": 9500.0, "other_operating_expense": 190000.0, "marketing_total_year1": 120000.0,
  "current_num_employees": 22, "staffing_ceiling": 26,
}


class TheWalkReadsThemAsFloors(unittest.TestCase):
  def _state_after_one_gate(self, fin):
    """One pass of the gate's state stamping via the seed block: run the
    function that owns it with a converged shape so it returns quickly."""
    fin = dict(fin)
    fin["_coherence"] = {"status": "walking", "margin_band_judgment": None}
    # the seed block runs inside gate_and_turn; drive it through the smallest
    # public path: the state helper + the block's own condition
    st = S.get_state(fin)
    return fin, st

  def test_a_signed_lease_and_a_contracted_price_hold_rent_and_pricing_from_the_first_round(self):
    src = inspect.getsource(S.gate_and_turn)
    self.assertIn('state["intake_commitments_seeded"] = True', src)
    self.assertIn('_floors["rent"] = True', src)
    self.assertIn("_floors[_ctl.ROUND_PRICING] = True", src)
    # and the seed is honoured by the pricer: a pricing floor refuses every price move
    fin = dict(ISOLDE, lease_signed=True, lease_term_months=30, price_contracted=True)
    basis = EV.basis_from_intake(financials_json=fin, growth_to_q11=1.0, payroll_load=1.22)
    th = EV.Thresholds(gm_floor=0.8, burden_max=0.7, band_low=0.1, ni_floor=0.06)
    split = [{"lob": "Imaging", "product": "Per-study imaging", "q1_revenue_quarterly": basis.q1_revenue_quarterly,
              "unit_price": 245.0, "annual_units": 9100.0, "utilization_rate": 0.7}]
    bounds = {"existing_lines": [{"lob": "Imaging", "product": "Per-study imaging", "price_multiplier_max": 1.2, "volume_multiplier_max": 1.5}]}
    o = C.price_revenue_candidate(kind="price", basis=basis, thresholds=th, bounds=bounds, split=split,
                                  multipliers={"Imaging␟Per-study imaging": 1.1}, floors={C.ROUND_PRICING: True})
    self.assertEqual(o.get("rejected"), "lever_floored_or_unavailable")
    # a rent floor removes the rent move from the menu
    moves = C.available_cost_moves(basis, th, {"team": {}, "facility": {"min_quarterly_rent": 20000.0}, "cost_floors": {}},
                                   dict(fin, _coherence={"client_floors": {"rent": True}}))
    self.assertNotIn("rent", moves)

  def test_the_staffing_ceiling_caps_volume(self):
    self.assertAlmostEqual(C.staffing_volume_cap({"staffing_ceiling": 26, "current_num_employees": 22}), 26 / 22, places=6)
    self.assertIsNone(C.staffing_volume_cap({"staffing_ceiling": 0, "current_num_employees": 22}), "0 = no ceiling")
    self.assertEqual(C.staffing_volume_cap({"staffing_ceiling": 10, "current_num_employees": 22}), 1.0, "a ceiling below today's count holds volume where it is")
    basis = EV.basis_from_intake(financials_json=ISOLDE, growth_to_q11=1.0, payroll_load=1.22)
    th = EV.Thresholds(gm_floor=0.8, burden_max=0.7, band_low=0.1, ni_floor=0.06)
    split = [{"lob": "Imaging", "product": "Per-study imaging", "q1_revenue_quarterly": basis.q1_revenue_quarterly,
              "unit_price": 245.0, "annual_units": 9100.0, "utilization_rate": 0.5}]
    bounds = {"existing_lines": [{"lob": "Imaging", "product": "Per-study imaging", "price_multiplier_max": 1.2, "volume_multiplier_max": 1.6}]}
    o = C.price_revenue_candidate(kind="volume", basis=basis, thresholds=th, bounds=bounds, split=split,
                                  multipliers={"Imaging␟Per-study imaging": 1.3}, floors={},
                                  staffing_cap=C.staffing_volume_cap(ISOLDE))
    self.assertEqual(o.get("rejected"), "breaches_bound")
    self.assertEqual(o.get("held_by"), "staffing_ceiling")
    self.assertAlmostEqual(o.get("believable_max"), round(26 / 22, 4), places=4)
    o2 = C.price_revenue_candidate(kind="volume", basis=basis, thresholds=th, bounds=bounds, split=split,
                                   multipliers={"Imaging␟Per-study imaging": 1.15}, floors={},
                                   staffing_cap=C.staffing_volume_cap(ISOLDE))
    self.assertNotIn("rejected", o2, o2)

  def test_the_corner_and_the_author_see_the_same_ceiling(self):
    for fn in (C.corner_check, S._arithmetic_cannot_work, S._authored_round):
      self.assertIn("staffing_volume_cap(financials_json)", inspect.getsource(fn), fn.__name__)


if __name__ == "__main__":
  unittest.main()
