"""Three fixes batched 2026-09-26, all of the same family: the app
replacing what the client said with something it worked out itself.

  1. THE INCLUSION QUESTION RECURSED. She said the rest of the team is paid
     620,000. Asked whether Dev's 95,000 was inside it, she said no. The
     ANSWER became rest-of-team, and the next turn built a FRESH frame from
     that answer and subtracted Dev again: 620,000 -> 525,000 -> 430,000,
     finally storing the figure she had just said "wouldn't be right".

  2. NO REVENUE ECHO (Nick 2026-09-14, undone by the 12-September revert).
     current_revenue is what SHE says the business brings in now;
     company_revenue_total_year1 is what the app's drivers compute. Writing
     the second into the first each pass replaced her figure with its
     arithmetic - Merrifield carried 1,192,050, Keir 4,767,400 against a
     stated 3,800,000.

  3. A NAMELESS DRAFT WAS ACCEPTED. Submit returned 200 and started a run
     that died in contract validation, after she had answered 61 questions
     and been told it worked.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from api_handlers import intake_consult as IC  # noqa: E402


def _people(named, settled=None, pending=None):
  p = {"people": [{"full_name": n, "role_title": "Fabricator",
                   "annual_wage": w} for n, w in named]}
  if settled is not None:
    p["_rest_inclusion_settled"] = settled
  if pending is not None:
    p["_rest_inclusion_pending"] = pending
  return p


class HerFigureIsNotReplacedByOurs(unittest.TestCase):

  # ---- 1. the inclusion question is asked once per roster ---------------

  def test_a_settled_roster_does_not_ask_again(self):
    """The recursion: her answer became the new 'stated' and the named
    wage was subtracted a second time."""
    people = _people([("Dev Ramanathan", 95000.0)],
                     settled={"named_sum": 95000.0, "value": 525000.0})
    out = IC._rest_inclusion_check(
        patch={"people.rest_of_team_payroll_year1": 525000.0},
        people_json=people,
        user_message="525,000 altogether for the rest of the team",
        messages=[])
    self.assertIsNone(out, "the app re-opened a settled inclusion frame")

  def test_a_roster_that_really_changed_may_ask_again(self):
    """Settling must not silence a genuine new question."""
    people = _people([("Dev Ramanathan", 95000.0), ("Ana Ruiz", 60000.0)],
                     settled={"named_sum": 95000.0, "value": 525000.0})
    out = IC._rest_inclusion_check(
        patch={"people.rest_of_team_payroll_year1": 620000.0},
        people_json=people, user_message="620,000 altogether", messages=[])
    self.assertIsNotNone(out, "a changed roster must be able to ask")

  def test_the_first_ask_still_happens(self):
    people = _people([("Dev Ramanathan", 95000.0)])
    out = IC._rest_inclusion_check(
        patch={"people.rest_of_team_payroll_year1": 620000.0},
        people_json=people, user_message="620,000 altogether", messages=[])
    self.assertIsNotNone(out)
    self.assertEqual(525000.0, out["frame"]["remainder"])

  def test_her_no_keeps_her_own_figure(self):
    """'Dev is not inside that' means the 620,000 stands, not 525,000."""
    got = IC._rest_inclusion_resolve(
        pending={"stated": 620000.0, "named_sum": 95000.0,
                 "remainder": 525000.0},
        user_message="No, the six hundred and twenty thousand is just for "
                     "the nine fabricators, it doesn't include Dev.")
    self.assertEqual(620000.0, got)

  # ---- 2. no revenue echo ------------------------------------------------

  def test_the_app_never_overwrites_a_revenue_she_gave(self):
    import inspect
    src = inspect.getsource(IC)
    i = src.index('next_financials["current_revenue"] = float(revenue_year1)')
    window = src[max(0, i - 900):i]
    self.assertIn('_safe_float(next_financials.get("current_revenue")) is None',
                  window,
                  "the derived year-one revenue can still overwrite hers")

  # ---- 3. a nameless draft is refused at submit --------------------------

  def test_submit_refuses_a_draft_with_no_business_name(self):
    import inspect
    from api_handlers import financials as FIN

    src = inspect.getsource(FIN)
    self.assertIn("I still need the business's name", src,
                  "submit still accepts a nameless draft")
    self.assertLess(src.index("I still need the business's name"),
                    src.index('business_facts = {'),
                    "the check must run before the snapshot is built")


if __name__ == "__main__":
  unittest.main()
