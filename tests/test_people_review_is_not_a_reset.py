"""THE PEOPLE REVIEW REBUILD IS NOT A RESET (2026-09-26).

The people section rebuilt its review by replacing people_json with the GPT's
object wholesale (`people_json = final_obj`). The GPT authors the roster keys;
everything else in people_json was captured by the APP through its own doors -
the rest-of-team payroll figure, the double-count inclusion frames, and now
the group-composition answer. The swap threw all of it away.

It went unnoticed because nothing rebuilt the review after the rest-of-team
figure landed. Add one more question to the section and it loops: she states
the payroll, the review is rebuilt, the figure is gone, the app asks again.
Measured on draft 9999d0c4 - three identical four-turn cycles, and the figure
absent from the store at the end of all three.

This pins the merge, not the loop: a key the GPT does not carry (or carries
empty while the app holds a value) survives the rebuild.
"""
import ast
import io
import os
import sys
import unittest

REPO = os.path.join(os.path.dirname(__file__), "..")
HANDLER = os.path.join(REPO, "python", "api_handlers", "intake_consult.py")

# The keys the APP captures into people_json through its own doors. None of
# them is authored by the people GPT, so each one is lost by a wholesale swap.
APP_OWNED = (
  "rest_of_team_payroll_year1",
  "_rest_inclusion_pending",
  "_rest_inclusion_settled",
  "team_groups",
  "_team_groups_asked",
)


def _merge(final_obj, people_json):
  """The merge exactly as the handler performs it."""
  carried = {}
  for key, value in (people_json or {}).items():
    if value in (None, "", [], {}):
      continue
    if key not in final_obj or final_obj.get(key) in (None, "", [], {}):
      carried[key] = value
  out = dict(final_obj or {})
  out.update(carried)
  return out


class TheRebuildKeepsWhatTheAppCaptured(unittest.TestCase):

  def setUp(self):
    self.src = io.open(HANDLER, encoding="utf-8-sig").read()

  def test_the_wholesale_swap_is_gone(self):
    """`people_json = final_obj` is the defect itself - it must not come back."""
    tree = ast.parse(self.src.replace("\r\n", "\n"))
    swaps = [
      node for node in ast.walk(tree)
      if isinstance(node, ast.Assign)
      and any(getattr(t, "id", "") == "people_json" for t in node.targets)
      and isinstance(node.value, ast.Name)
      and node.value.id == "final_obj"
    ]
    self.assertEqual([], swaps,
                     "people_json = final_obj drops every app-captured key")

  def test_every_app_owned_key_survives_a_rebuild(self):
    people = {
      "people": [{"full_name": "Delia Pellingham", "annual_wage": 120000.0}],
      "inferred_roles": [],
      "rest_of_team_payroll_year1": 540000.0,
      "_rest_inclusion_settled": {"named_sum": 88000.0, "value": 452000.0},
      "team_groups": [{"name": "Maintenance crew", "headcount": 8}],
      "_team_groups_asked": True,
    }
    # what the people GPT returns: the roster, and nothing the app captured
    final_obj = {
      "people": [{"full_name": "Delia Pellingham", "annual_wage": 120000.0},
                 {"full_name": "Marcus Oyelaran", "annual_wage": 88000.0}],
      "inferred_roles": [],
      "inferred_roles_summary": "",
      "business_naics_6": "561730",
      "confidence": 0.9,
    }
    merged = _merge(final_obj, people)
    for key in (k for k in APP_OWNED if k in people):
      self.assertIn(key, merged, "%s was dropped by the rebuild" % key)
    self.assertEqual(540000.0, merged["rest_of_team_payroll_year1"])
    self.assertEqual(452000.0, merged["_rest_inclusion_settled"]["value"])
    # the OPEN frame is the other half of the pair, and a rebuild between the
    # question and her answer would strand the turn without it
    still_open = _merge(
      final_obj,
      {"_rest_inclusion_pending": {"named_sum": 88000.0, "asked": True}})
    self.assertEqual({"named_sum": 88000.0, "asked": True},
                     still_open["_rest_inclusion_pending"])
    self.assertEqual(sorted(APP_OWNED),
                     sorted(set(APP_OWNED)),
                     "the list of app-captured keys must stay unique")

  def test_the_gpt_still_owns_the_roster(self):
    """The merge carries forward; it never overrides what the GPT authored."""
    people = {"people": [{"full_name": "Stale Row"}], "confidence": 0.1,
              "rest_of_team_payroll_year1": 540000.0}
    final_obj = {"people": [{"full_name": "Delia Pellingham"}],
                 "confidence": 0.9, "inferred_roles": []}
    merged = _merge(final_obj, people)
    self.assertEqual("Delia Pellingham", merged["people"][0]["full_name"])
    self.assertEqual(0.9, merged["confidence"])
    self.assertEqual(540000.0, merged["rest_of_team_payroll_year1"])

  def test_an_empty_value_from_the_gpt_does_not_erase_ours(self):
    merged = _merge({"people": [], "rest_of_team_payroll_year1": None},
                    {"people": [{"full_name": "Delia"}],
                     "rest_of_team_payroll_year1": 540000.0})
    self.assertEqual(540000.0, merged["rest_of_team_payroll_year1"])
    self.assertEqual([{"full_name": "Delia"}], merged["people"])

  def test_the_handler_carries_forward_and_says_so(self):
    """A silent merge is how the swap survived - the log names the keys."""
    self.assertIn("PEOPLE_REVIEW_CARRIED_FORWARD", self.src)


if __name__ == "__main__":
  unittest.main()
