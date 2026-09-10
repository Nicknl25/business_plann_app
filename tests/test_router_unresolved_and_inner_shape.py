"""The router's honest third option + inner-shape enforcement
(Nick's rulings 2026-09-10, the $60/$40 oscillation and the Bramblewood
raw-shape rows).

1. UNRESOLVED: the router is no longer forced to attribute every figure.
   A figure it cannot confidently place comes back in unresolved_figures,
   unwritten; the app asks ("The 40 - is that your weekly capacity?") and
   the answer to that named-field question lands by the existing
   agree-with-proposal rule. A confident wrong write is the defect;
   removing the confidence requirement makes it unrepresentable.

2. INNER SHAPE: value_json was a bare string checked only at top-level
   type, so 12 router-shaped people rows (name/title/annual_pay) reached
   the INTAKE->POST_INTAKE boundary before anything objected. The inner
   schemas now reach the prompt (structured_shapes_doc) AND are enforced
   server-side: wrong keys reject into confirm_clarify; ABSENT keys stay
   legal because the merge door fills partial rows by design.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intent_router import (  # noqa: E402
  _clean_unresolved_figures,
  _final_schema,
  _structured_shapes_doc,
  _validate_value_inner,
  _value_schema_by_consult_field,
)
from api_handlers.intake_consult import (  # noqa: E402
  _unresolved_figures_ask,
)

PEOPLE_SCHEMA = _value_schema_by_consult_field(consult_type="people").get("people")


class InnerShapeTests(unittest.TestCase):
  def test_raw_router_shape_rejects(self):
    """The Bramblewood rows: name/title/annual_pay are not canonical keys."""
    self.assertFalse(_validate_value_inner(
      [{"name": "Dr. Ingrid Solvang", "title": "Clinical Director",
        "annual_pay": 118000}], PEOPLE_SCHEMA))

  def test_partial_correction_row_stays_legal(self):
    """The merge door fills partial rows - a wage correction must pass."""
    self.assertTrue(_validate_value_inner(
      [{"full_name": "Maria Gonzalez", "annual_wage": 95000}], PEOPLE_SCHEMA))

  def test_wrong_inner_type_rejects(self):
    self.assertFalse(_validate_value_inner(
      [{"full_name": "A", "experience_years": 15}], PEOPLE_SCHEMA))

  def test_loose_schema_validates_trivially(self):
    self.assertTrue(_validate_value_inner({"anything": 1}, {}))

  def test_shapes_doc_names_canonical_keys(self):
    doc = _structured_shapes_doc(["people"], consult_type_norm="people")
    self.assertIn("full_name", doc)
    self.assertIn("role_title", doc)
    self.assertNotIn('"name"', doc)


class UnresolvedFiguresTests(unittest.TestCase):
  def test_schema_carries_the_honest_third_option(self):
    sch = _final_schema(allowed_patch_fields=["ops.unit_price"],
                        consult_type="ops")
    params = sch["schema"] if "schema" in sch else sch
    blob = str(params)
    self.assertIn("unresolved_figures", blob)
    self.assertIn("candidate_fields", blob)

  def test_clean_parses_and_filters(self):
    out = _clean_unresolved_figures(
      [{"value_json": "40", "client_words": "40 a week",
        "candidate_fields": ["units_per_week_capacity", "not_allowed"]}],
      ["units_per_week_capacity", "unit_price"])
    self.assertEqual(out[0]["value"], 40)
    self.assertEqual(out[0]["candidate_fields"], ["units_per_week_capacity"])

  def test_ask_names_the_candidates(self):
    ask = _unresolved_figures_ask([
      {"value": 40, "client_words": "40 a week",
       "candidate_fields": ["ops.units_per_week_capacity", "ops.unit_price"]}])
    self.assertIn("40 a week", ask)
    self.assertIn("weekly capacity", ask)
    self.assertIn("price", ask)
    self.assertTrue(ask.endswith("?"))

  def test_ask_with_no_candidates_still_asks(self):
    ask = _unresolved_figures_ask([{"value": 40, "client_words": "",
                                    "candidate_fields": []}])
    self.assertIn("which figure", ask)


if __name__ == "__main__":
  unittest.main()
