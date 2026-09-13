"""If the app has no name for a field, it does not say that field to a client.

Thackeray & Nunes Stoneworks 53a7603f (2026-09-13). The client was told:

  "(One note: I haven't recorded how much you can deliver in a week and
   units per period capacity yet - we'll get to that in a moment.)"

`units per period capacity` is a raw field name. The guard that was supposed to
stop it rejected any label containing an underscore - but it tested the label
AFTER de-underscoring, so every raw field name passed. A string test standing in
for "do we have a name for this".

The same mistake was in _has_a_client_facing_name, which asked whether the
de-underscored leaf had more than one word. Both now ask the NAME MAPS.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


class OnlyAFieldWeHaveNamedIsSpokenToAClient(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import _has_a_client_facing_name  # type: ignore

    self.askable = _has_a_client_facing_name

  def test_fields_we_have_named_are_askable(self):
    for field in ("units_per_period_capacity", "units_per_week_capacity",
                  "monthly_rent_expense", "cash_on_hand", "current_revenue",
                  "unit_price"):
      self.assertTrue(self.askable(field), f"{field} has a name and should be askable")

  def test_an_internal_key_is_never_askable(self):
    """`selections` is the key that reached an Alderman & Fitch client."""
    for field in ("selections", "market.selections", "foo_bar_baz", "_guard"):
      self.assertFalse(self.askable(field),
                       f"{field} has no client-facing name and must not be said")

  def test_de_underscoring_alone_does_not_make_a_name(self):
    """The exact defect: a raw key with underscores reads as multi-word once
    they are swapped for spaces, and that is not a name."""
    self.assertFalse(self.askable("some_unmapped_internal_thing"))


class TheUnrecordedNoteSpeaksOnlyNames(unittest.TestCase):
  """Rewritten 2026-09-13 (Nick): these two tests used to read the SOURCE of
  the rule and assert the text of its body.

  They failed the moment the rule was extracted to a module-level function so
  it could be tested properly - a change that made the code strictly better.
  That is the whole indictment of the form: a pin that asserts a rule EXISTS
  goes red on an improvement and stays green on a body that contains the right
  words and does the wrong thing. It never once asked what a client would hear.

  It is the same defect as a test that never runs the path, and it is how three
  separate deletions of issue 589 reached a client - each found by a person,
  never by a test.

  So: ask the rule what it would SAY.
  """

  def setUp(self):
    from api_handlers.intake_consult import _client_label_for_field  # type: ignore

    self.label = _client_label_for_field

  def test_a_field_we_never_named_is_said_as_nothing(self):
    """The note lists only what comes back non-empty, so "" is the whole
    guarantee: the field is simply not mentioned."""
    for field in ("units_per_period_capacity", "selections", "market.selections",
                  "some_unmapped_internal_thing", "_guard", "foo_bar_baz"):
      self.assertEqual(self.label(field), "",
                       "%r would have been spoken to a client" % field)

  def test_a_field_we_named_is_said_in_that_name(self):
    for field, expected in (("monthly_rent_expense", "rent"),
                            ("cash_on_hand", "cash on hand")):
      self.assertEqual(self.label(field), expected)

  def test_a_name_comes_from_a_map_never_from_string_surgery(self):
    """The exact defect: `units_per_period_capacity` de-underscores to
    `units per period capacity`, which LOOKS like a phrase and is a field name.

    The first version of this test asserted "the label never equals the
    de-underscored key" and failed on `cash_on_hand` -> "cash on hand", which
    is a real name we chose that happens to coincide. Same trap as asserting
    "the answer is not 30" about a conversion: a coincidence between the right
    answer and the wrong one is not the thing to test.

    What actually separates them is provenance, and behaviourally that shows up
    as: a field no map names comes back EMPTY, however plausible de-underscoring
    it would look.
    """
    for unmapped in ("units_per_period_capacity", "some_unmapped_internal_thing",
                     "operating_periods_per_year", "concurrent_capacity_units",
                     "selections"):
      self.assertEqual(
        self.label(unmapped), "",
        "%r has no name in any map, so string surgery produced one" % unmapped)
    # and nothing we DO say ever carries a key's underscores
    for field in ("monthly_rent_expense", "cash_on_hand", "units_per_week_capacity"):
      self.assertNotIn("_", self.label(field))

  def test_one_rule_serves_both_callers(self):
    """It lived twice - here and as a closure called `_human` - and the first
    fix corrected only one of them. Both now ask the same function, so the two
    can no longer disagree about what has a name."""
    from api_handlers.intake_consult import _has_a_client_facing_name  # type: ignore

    for field in ("selections", "some_unmapped_internal_thing", "_guard"):
      self.assertEqual(self.label(field), "")
      self.assertFalse(_has_a_client_facing_name(field))


class TheAskSpeaksAPhraseNotAKey(unittest.TestCase):
  """`_ASK_FIELD_NAMES` holds de-underscored raw keys ("units per period
  capacity"), which is the string-for-a-name pattern still sitting in the
  gate list. It is harmless only because the humaniser renders a real phrase
  over the top of it - so that rendering is what gets pinned, not the list.
  """

  def test_every_askable_capacity_field_renders_as_a_phrase(self):
    from api_handlers.intake_consult import _humanize_field_for_ask  # type: ignore

    for field, expected in (
      ("ops.units_per_period_capacity", "capacity per period"),
      ("ops.units_per_week_capacity", "weekly capacity"),
      ("financials.current_revenue", "annual revenue"),
      ("ops.unit_price", "price"),
    ):
      said = _humanize_field_for_ask(field)
      self.assertEqual(said, expected)
      self.assertNotIn("_", said)
      self.assertNotEqual(said, field.split(".")[-1].replace("_", " "),
                          "the ask spoke the key back as though it were a name")


if __name__ == "__main__":
  unittest.main(verbosity=2)
