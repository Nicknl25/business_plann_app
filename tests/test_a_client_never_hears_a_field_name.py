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
  def test_the_note_helper_requires_a_real_label(self):
    """Source-level: the label test must consult a map, not inspect the string.

    The old body was `return lbl if lbl and lbl != f and "_" not in lbl else ""`
    over a de-underscored value - which is why a raw field name got through."""
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8-sig")
    i = src.index("  def _human(f: str) -> str:")
    body = src[i:src.index("  if own:", i)]
    self.assertIn("_FINANCIALS_FIELD_LABELS.get(f)", body)
    self.assertIn('named.replace(" ", "_").lower() != str(f).lower()', body,
                  "a de-underscored field name must not count as a name")
    self.assertNotIn('"_" not in lbl', body,
                     "the underscore test was the defect - it ran after de-underscoring")

  def test_both_rules_were_fixed_together(self):
    """They were the same mistake in two places; a fix to one only is the kind
    that leaves the defect live on the other path."""
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8-sig")
    i = src.index("def _has_a_client_facing_name(")
    body = src[i:src.index("\ndef ", i + 10)]
    self.assertNotIn("len(leaf.split()) > 1", body,
                     "the word-count test was the same string-for-a-name mistake")
    self.assertIn("_FINANCIALS_FIELD_LABELS.get(raw)", body)


if __name__ == "__main__":
  unittest.main(verbosity=2)
