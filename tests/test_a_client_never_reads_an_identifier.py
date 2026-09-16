"""A CLIENT NEVER READS A RAW IDENTIFIER (Cowork 1283, Cedarbrook Dog Grooming 09917eac).

The stream-discovery ask went to the client as "a lot of pet_grooming_salons also offer
nail trimming..." - a machine token in a sentence a person reads. business_type is a field
the ROUTER can write (intent_router schema), and the app's own catalogue label is applied on
a later persist path, so a model-written token can be latched into the ask before the app has
tidied it. The door that composes the sentence is therefore the one that has to hold: whatever
arrives, the client reads English.

This pins the CLASS, not the instance - any trade, any token shape.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_coherence.gpt_stream_discovery import (  # noqa: E402
  compose_stream_discovery_ask,
  pluralize_business_type,
)

IDENTIFIER = re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]|[A-Za-z0-9]-[A-Za-z0-9]{0,2}_")


class NoIdentifierSurvivesToTheClient(unittest.TestCase):

  # (what a model might write, what the client must end up reading)
  SHAPES = [
    ("pet_grooming_salon", "pet grooming salons"),
    ("coffee_roaster", "coffee roasters"),
    ("steel_investment_casting_foundry", "steel investment casting foundries"),
    ("auto_body_shop", "auto body shops"),
    ("dry_cleaning_service", "dry cleaning services"),
    ("physical_therapy_practice", "physical therapy practices"),
  ]

  def test_a_token_is_read_back_as_english(self):
    for raw, expected in self.SHAPES:
      with self.subTest(raw=raw):
        self.assertEqual(pluralize_business_type(raw), expected)

  def test_no_underscore_reaches_the_sentence(self):
    for raw, _expected in self.SHAPES:
      with self.subTest(raw=raw):
        ask = compose_stream_discovery_ask(raw, ["nail trimming", "ear cleaning"])
        self.assertNotIn("_", ask, "a machine token reached a sentence a client reads")
        self.assertIsNone(IDENTIFIER.search(ask))

  def test_the_labels_are_held_to_the_same_standard(self):
    """The trade is not the only thing interpolated - a label is client-facing too."""
    ask = compose_stream_discovery_ask("Barber Shop", ["beard_trim", "hot towel shave"])
    self.assertIn("beard", ask)

  def test_a_clean_business_type_is_untouched(self):
    """The fix must not reword the businesses that were already right."""
    for raw, expected in [
      ("Barber Shop", "barber shops"),
      ("Architectural Millwork Shop", "architectural millwork shops"),
      ("Ornamental Metalwork Shop", "ornamental metalwork shops"),
      ("Cellulose Fiber Plant", "cellulose fiber plants"),
      ("Orthopedic Appliance Manufacturer", "orthopedic appliance manufacturers"),
    ]:
      with self.subTest(raw=raw):
        self.assertEqual(pluralize_business_type(raw), expected)

  def test_nothing_at_all_still_reads_as_a_sentence(self):
    self.assertEqual(pluralize_business_type(""), "businesses like yours")
    self.assertEqual(pluralize_business_type(None), "businesses like yours")


if __name__ == "__main__":
  unittest.main()
