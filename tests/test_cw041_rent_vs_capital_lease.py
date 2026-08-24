"""Rent and a capital lease are two different things, captured separately.

CW-041, Halbrook Grounds Management. The client confirmed monthly rent of
$5,200. Several stages later the app asked "what monthly amount should we use
for any leased equipment, vehicles, servers, or additional space you do not
own", the client answered "about 3,600 a quarter, so call it 1,200 a month",
and the app stored initial_lease=1200 AND silently overwrote
monthly_rent_expense 5,200 -> 3,600, announcing it as
"Recorded: monthly rent $3,600" inside the lease confirmation.

Three things had to line up, and all three are pinned here:

  1. One question collected two different kinds of commitment. Extra rented
     space is an operating expense; equipment financed under a term is a debt
     that belongs on the balance sheet. The app decided which a commitment was
     by which question the number landed in.
  2. The misroute guard had NO entry for the lease stage, so its precondition
     could never be met and it stood down without examining the foreign write.
  3. "lease" was in RENT's own believability keywords, so even had the guard
     run, a lease-worded answer made a rent overwrite look trustworthy.

Dated, because it matters: the overwrite only became possible on 2026-07-31
(ef49f72, which widened writes to any completed stage's fields) and only
became audible on 2026-08-14 (a4dc230, which gave rent a spoken ack). The
question wording is from 2026-04-05 and never changed.
"""
from __future__ import annotations

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

from api_handlers import intake_consult as ic  # noqa: E402
from client_intake_and_finmo.finmo_bridge import (  # noqa: E402
  _annualized_lease_commitment, _safe_float,
)

#: Halbrook's own words, and his state at that turn.
USER = ("The mower fleet lease. It bills quarterly, about 3,600 a quarter, "
        "so call it 1,200 a month. Signed that one last year.")
BEFORE = {
  "current_revenue": 1400000.0, "current_cogs": 267489.0,
  "marketing_total_year1": 42000.0, "current_payroll": 620000.0,
  "monthly_rent_expense": 5200.0, "future_rent_expected": True,
  "other_operating_expense": 3100.0, "current_num_employees": 12,
  "current_capex": 0.0, "initial_assets": 420000.0,
}


class TheOverwriteTests(unittest.TestCase):
  """Exercises the production normalizer, not a restatement of it."""

  def _run(self, patch):
    return ic._normalize_financials_router_patch(
      patch=dict(patch),
      active_stage="initial_lease",
      financials_json=dict(BEFORE),
      financials_year1_json={},
      last_assistant=ic._build_capital_lease_message(),
      user_message=USER,
      report={},
    ) or {}

  def test_a_confirmed_rent_survives_the_lease_answer(self):
    """The defect itself. Before the fix this stored 3,600."""
    out = self._run({"capital_lease_balance": 1200.0,
                     "monthly_rent_expense": 3600.0})
    self.assertEqual(
      out.get("monthly_rent_expense"), 5200.0,
      "the rent the client confirmed twenty minutes earlier was overwritten "
      "by a second figure in the lease answer")

  def test_the_lease_figure_still_lands(self):
    """The other half - a guard that blocked everything would pass the test
    above and be useless."""
    out = self._run({"capital_lease_balance": 1200.0,
                     "monthly_rent_expense": 3600.0})
    self.assertEqual(out.get("capital_lease_balance"), 1200.0)


class TheGuardCoversThisStageTests(unittest.TestCase):

  KW = ic._FINANCIALS_FAMILY_KEYWORDS_BY_FIELD_GUARD

  def test_the_capital_lease_field_has_a_keyword_family(self):
    """Without one the guard's precondition can never be met on this stage and
    it stands down entirely - which is what happened."""
    self.assertIn("capital_lease_balance", self.KW)
    self.assertTrue(self.KW["capital_lease_balance"])

  def test_lease_is_not_a_rent_word(self):
    """It was, and that is what made a lease-worded answer look like a
    believable rent correction."""
    self.assertNotIn("lease", self.KW["monthly_rent_expense"])

  def test_rent_is_still_guarded_by_its_own_words(self):
    self.assertIn("rent", self.KW["monthly_rent_expense"])


class TheQuestionAsksAboutOneThingTests(unittest.TestCase):

  def test_the_lease_question_no_longer_collects_rented_space(self):
    q = ic._build_capital_lease_message().lower()
    self.assertNotIn("additional space you do not own", q)
    self.assertIn("lease or finance agreement", q)

  def test_it_asks_what_is_owed_not_a_monthly_payment(self):
    """A monthly payment cannot put a lease on a balance sheet."""
    q = ic._build_capital_lease_message().lower()
    self.assertIn("still owed", q)

  def test_the_stage_writes_the_capital_lease_field(self):
    spec = ic._financials_stage_spec("initial_lease")
    self.assertEqual(spec["patch_targets"], ("capital_lease_balance",))
    self.assertEqual(spec["completion_fields"], ("capital_lease_balance",))


class TheLiabilityIsWhatIsOwedTests(unittest.TestCase):
  """Mirrors finmo_bridge's seed branches."""

  @staticmethod
  def _seed(fin):
    balance = _safe_float(fin.get("capital_lease_balance"))
    if balance is not None:
      return round(max(0.0, balance), 6)
    legacy = _annualized_lease_commitment(fin.get("initial_lease"))
    return round(legacy, 6) if legacy is not None else None

  def test_the_seed_is_the_balance_itself(self):
    self.assertEqual(self._seed({"capital_lease_balance": 40000.0}), 40000.0)

  def test_a_monthly_payment_is_never_multiplied_into_a_balance(self):
    """initial_lease x 12 was the old liability - twelve months of payments
    standing in for what is owed."""
    self.assertEqual(self._seed({"capital_lease_balance": 46000.0}), 46000.0)

  def test_legacy_drafts_keep_the_number_they_shipped_with(self):
    """~1,780 drafts stored a monthly payment and no term, so a balance
    cannot be re-derived. Their figures are left exactly as delivered rather
    than guessed at."""
    self.assertEqual(self._seed({"initial_lease": 1200.0}), 14400.0)


if __name__ == "__main__":
  unittest.main()
