"""The four conversation defects the intake persona gate reproduced (Nick
2026-09-11: "Fix all four. They're all the same family and they're all
conversation defects that reach a client").

  1 the owner-pay round trip - a stated annual re-derived from a monthly
  2/3 the capacity one-number trap and issue 577's fallthrough - the ops
    interview's answers sent to a flat router clarifier (behaviour proven
    end to end by the gate's --transcript replay; pinned here at the source)
  4 the figure bounce - a landed figure asked about again

Pins run the app's own functions. IC_PATH points them at another copy of
intake_consult.py - the red-proof runs them against the pre-fix version,
where a missing parameter is passed over (never a crash-red)."""
from __future__ import annotations

import copy
import importlib.util
import inspect
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "python", "client_intake_and_finmo"), os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

_PATH = os.environ.get("IC_PATH") or os.path.join(ROOT, "python", "api_handlers", "intake_consult.py")
_spec = importlib.util.spec_from_file_location("ic_under_test_20260911", _PATH)
IC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(IC)


def _call(fn, **kw):
  """Pass only the parameters the function has - the pre-fix door has no
  user_message, and must fail on the VALUE it writes, not on a TypeError."""
  params = inspect.signature(fn).parameters
  return fn(**{k: v for k, v in kw.items() if k in params})


def _owner_rows(ppl):
  return [p for p in ppl.get("people") or [] if IC._OWNER_TITLE_RE.search(str(p.get("role_title") or ""))]


class OwnerPayDoorTests(unittest.TestCase):
  SAID = "Jess Harlow, owner and lead groomer. 14 years grooming. I pay myself $62,000 a year."

  def test_a_stated_annual_is_kept_when_no_owner_row_holds_it_yet(self):
    """The stated_total run: the router's monthly 5,166.67 reached the door
    with no owner row, and 5,166.67 x 12 wrote 62,000.04."""
    ppl = {"people": []}
    _call(IC._apply_owner_pay_statement, monthly=5166.67, people_json=ppl, financials_json={},
          ops_json={}, user_message=self.SAID)
    self.assertEqual([p["annual_wage"] for p in _owner_rows(ppl)], [62000.0])

  def test_a_genuine_monthly_statement_still_lands(self):
    ppl = {"people": []}
    _call(IC._apply_owner_pay_statement, monthly=5500.0, people_json=ppl, financials_json={},
          ops_json={}, user_message="I pay myself $5,500 a month.")
    self.assertEqual([p["annual_wage"] for p in _owner_rows(ppl)], [66000.0])

  def test_an_unrelated_annual_in_the_message_is_not_taken(self):
    ppl = {"people": []}
    _call(IC._apply_owner_pay_statement, monthly=5166.67, people_json=ppl, financials_json={},
          ops_json={}, user_message="Revenue is about $640,000 a year.")
    self.assertEqual([p["annual_wage"] for p in _owner_rows(ppl)], [62000.04])


class OwnerMergeTests(unittest.TestCase):
  def _merge(self, rows):
    ppl = {"people": copy.deepcopy(rows)}
    fin, _y1 = IC._sync_financials_consult_persistence_state(
      financials_json={}, financials_year1_json={}, people_json=ppl, ops_json={})
    return ppl, fin

  def test_the_merge_keeps_the_stated_wage_over_the_round_trip(self):
    """The exact stated_total shape: Jess's named row (not yet stamped) and
    the owner-pay door's bare row at 62,000.04."""
    ppl, _fin = self._merge([
      {"full_name": "Jess Harlow", "role_title": "Owner and Lead Groomer", "annual_wage": 62000.0,
       "relevant_background": "14 years grooming"},
      {"role_title": "Owner", "annual_wage": 62000.04, "wage_source": "client_override"},
    ])
    self.assertEqual([(p.get("full_name"), p["annual_wage"]) for p in _owner_rows(ppl)],
                     [("Jess Harlow", 62000.0)])

  def test_the_stated_figure_stands_whichever_row_holds_it(self):
    ppl, _fin = self._merge([
      {"full_name": "Jess Harlow", "role_title": "Owner", "annual_wage": 62000.04,
       "wage_source": "client_override", "relevant_background": "14 years"},
      {"role_title": "Owner", "annual_wage": 62000.0, "wage_source": "client_override"},
    ])
    self.assertEqual([p["annual_wage"] for p in _owner_rows(ppl)], [62000.0])

  def test_two_genuinely_different_statements_still_raise_the_hold(self):
    ppl, fin = self._merge([
      {"full_name": "Jess Harlow", "role_title": "Owner", "annual_wage": 62000.0,
       "wage_source": "client_override", "relevant_background": "14 years"},
      {"role_title": "Owner", "annual_wage": 70000.0, "wage_source": "client_override"},
    ])
    self.assertIn("_owner_wage_conflict_hold", fin)


class FigureBounceTests(unittest.TestCase):
  OPS = {"lob_models": [{"products": [
    {"product_name": "Full groom", "units_per_week_capacity": 120, "utilization_rate": 0.8, "unit_price": 85},
    {"product_name": "Bath and tidy", "units_per_week_capacity": 150}]}]}

  def _open(self, figs, ops=None):
    if not hasattr(IC, "_unresolved_figures_open"):
      self.fail("no _unresolved_figures_open - every unresolved figure is asked about")
    return IC._unresolved_figures_open(figs, ops_json=ops or self.OPS, people_json={}, financials_json={})

  def test_a_figure_the_turn_landed_is_not_asked_about(self):
    """stated_total turn 5: utilization 80% landed, and the app still asked
    'is that your financials summary?'."""
    figs = [{"value": 80, "client_words": "About 80 percent of the full-groom slots are booked on average.",
             "candidate_fields": ["ops.units_per_week_capacity", "financials.current_cogs"]}]
    self.assertEqual(self._open(figs), [])

  def test_a_figure_with_only_text_homes_is_not_asked_about(self):
    """monthly_wage turn 16: 'The within about five miles of the salon - is
    that your geographic coverage?'."""
    figs = [{"value": 5, "client_words": "within about five miles of the salon",
             "candidate_fields": ["ops.geographic_coverage"]}]
    self.assertEqual(self._open(figs), [])

  def test_the_in_use_count_of_a_line_is_a_restatement(self):
    """cleaning persona 2026-09-11 turn 6: 'About 85 percent - we have 34
    sites under contract right now' on a 40-site line, and the app asked
    'The 34 sites under contract right now - is that your annual revenue,
    or your capacity per period?'."""
    ops = {"lob_models": [{"products": [
      {"product_name": "Recurring office cleaning", "units_per_period_capacity": 40, "utilization_rate": 0.85}]}]}
    figs = [{"value": 34, "client_words": "34 sites under contract right now",
             "candidate_fields": ["financials.current_revenue", "ops.units_per_period_capacity"]}]
    self.assertEqual(self._open(figs, ops=ops), [])

  def test_a_quantity_without_a_number_is_not_asked_about(self):
    """cleaning persona 2026-09-11 17:14 turn 13: 'we bid on a few
    contracts a year' drew 'The a few contracts a year - is that your
    milestones?'."""
    figs = [{"value": "a few", "client_words": "a few contracts a year", "candidate_fields": ["ops.milestones"]}]
    self.assertEqual(self._open(figs), [])

  def test_the_headroom_of_a_line_is_a_restatement(self):
    """cleaning persona 2026-09-11 17:13 turn 15: 'we could take six more
    sites without hiring' on a 40-site line at 85% drew 'The six more sites
    without hiring - is that your weekly capacity, or your capacity per
    period?'."""
    ops = {"lob_models": [{"products": [
      {"product_name": "Recurring office cleaning", "units_per_period_capacity": 40, "utilization_rate": 0.85}]}]}
    figs = [{"value": 6, "client_words": "six more sites without hiring",
             "candidate_fields": ["ops.units_per_week_capacity", "ops.units_per_period_capacity"]}]
    self.assertEqual(self._open(figs, ops=ops), [])

  def test_a_real_leftover_figure_is_still_asked_about(self):
    """2e4fed43's own case must survive: '$60 a session and we can do 40 a
    week' - the 40 has no home on file, and a numeric one to land wrong in."""
    figs = [{"value": 40, "client_words": "40 a week", "candidate_fields": ["ops.units_per_week_capacity"]}]
    opened = self._open(figs)
    self.assertEqual(len(opened), 1)
    self.assertIn("The 40 a week - is that your weekly capacity?", IC._unresolved_figures_ask(opened))

  def test_the_question_never_echoes_the_whole_sentence(self):
    ask = IC._unresolved_figures_ask([{
      "value": 0.8, "client_words": "About 80 percent of the full-groom slots are booked on average.",
      "candidate_fields": ["ops.units_per_week_capacity"]}])
    self.assertNotIn("About 80 percent of the full-groom", ask)
    self.assertIn("80%", ask)


class UnresolvedOnlyClarifyTests(unittest.TestCase):
  """monthly_wage 2026-09-11 16:52: the router put Dana's '$4,333.33 a
  month' in unresolved_figures with an empty patch, its malformed-patch
  fallback answered 'I had trouble applying that change' - for a figure the
  record already held ($52,000 a year)."""
  CANNED = "I had trouble applying that change. Can you rephrase what you want to update?"
  PEOPLE = {"people": [{"full_name": "Dana Okafor", "role_title": "Head Groomer", "annual_wage": 52000.0}]}

  def _resolve(self, figs, people=None, ops=None):
    if not hasattr(IC, "_unresolved_clarify_resolution"):
      self.fail("no _unresolved_clarify_resolution - the canned message reaches the client")
    return IC._unresolved_clarify_resolution(
      figs=figs, router_msg=self.CANNED, ops_json=ops or {}, people_json=people or self.PEOPLE,
      financials_json={})

  def test_a_monthly_restatement_of_a_wage_on_file_goes_to_the_consultant(self):
    figs = [{"value": 4333.33, "client_words": "$4,333.33 a month",
             "candidate_fields": ["people.people", "people.total_team_payroll", "financials.current_payroll"]}]
    self.assertEqual(self._resolve(figs), ("continue_chat", ""))

  def test_a_truly_open_figure_gets_the_plain_question_never_the_canned_one(self):
    figs = [{"value": 40, "client_words": "40 a week", "candidate_fields": ["ops.units_per_week_capacity"]}]
    action, msg = self._resolve(figs, people={"people": []})
    self.assertEqual(action, "confirm_clarify")
    self.assertNotIn("I had trouble applying", msg)
    self.assertIn("The 40 a week - is that your weekly capacity?", msg)


class OpsInterviewOwnsItsAnswersTests(unittest.TestCase):
  def test_an_ops_clarify_goes_to_the_consultant(self):
    """Behaviour proven end to end: the gate's --transcript replay of the
    monthly_wage run that hit issue 577 LOOPs on the pre-fix handler and
    runs on through the ops stage on the fix. Pinned here at the source."""
    src = inspect.getsource(IC.post_intake_consult_handler)
    self.assertIn('if action == "confirm_clarify" and str(focus or "").strip().lower() == "ops":', src)
    self.assertIn("OPS_CLARIFY_TO_CONSULTANT", src)

  def test_a_people_clarify_goes_to_the_consultant(self):
    """Issue 577's other half (2026-09-11 23:46, the gate's stated_total and
    cleaning runs): "Yes - Dana Okafor, head groomer, 9 years grooming. She
    earns $52,000 a year" drew confirm_clarify from a live router, the
    handler spoke "what would you like us to put down for people?" and
    returned past the consultant and the extractor - Dana was never stored.
    Two sibling runs drew edit_patch on the identical message: variance,
    not a finding. A people clarify goes to the people consultant."""
    src = inspect.getsource(IC.post_intake_consult_handler)
    self.assertIn('if action == "confirm_clarify" and str(focus or "").strip().lower() == "people":', src)
    self.assertIn("PEOPLE_CLARIFY_TO_CONSULTANT", src)
    # the handover must sit BEFORE the generic clarify branch that returns
    self.assertLess(src.find("PEOPLE_CLARIFY_TO_CONSULTANT"),
                    src.find('if action == "confirm_clarify":\n      assistant_text = sanitize_fact_template(router_msg)'))


if __name__ == "__main__":
  unittest.main()
