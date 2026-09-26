"""THE ONE EXTRA INTAKE QUESTION: how she groups the rest of the team.

Nick, 2026-09-26: payroll as an FTE roll-forward, "one extra intake question
for group composition". The roll-forward builds position GROUPS; without her
words the blocks are named after OEWS occupation titles ("Structural Metal
Fabricators and Fitters"), which is a government label, not what she calls
her people.

What has to be true for the question to be worth asking at all:
  * it is asked ONCE, after the rest-of-team payroll question, and only when
    there is a pool to group;
  * her answer reaches the router as a field the router is allowed to write
    (a field missing from the allowlist is a field the patch is thrown away
    at, silently - it has happened);
  * the shape the router is told to emit is the shape the applier keeps and
    the roll-forward reads;
  * the names land on the payroll rows the workbook renders.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from api_handlers import intake_consult as IC  # noqa: E402
from client_intake_and_finmo import intent_router as ROUTER  # noqa: E402
from client_intake_and_finmo.post_intake_headcount import (  # noqa: E402
    rollforward_payload as RP,
)


def _people(**kw):
  base = {
    "people": [
      {"full_name": "Rosalind Keir", "role_title": "Owner and General Manager",
       "annual_wage": 140000.0},
      {"full_name": "Dev Ramanathan", "role_title": "Shop Foreman",
       "annual_wage": 95000.0},
    ],
  }
  base.update(kw)
  return base


class TheQuestionIsAskedWhenItMatters(unittest.TestCase):

  def test_it_waits_for_the_rest_of_team_answer(self):
    """Until she has said there IS a pool, there is nothing to group."""
    people = _people()
    self.assertTrue(IC._rest_of_team_payroll_pending(
      people, {}, financials_json={"current_num_employees": 12}))
    self.assertFalse(IC._team_groups_pending(
      people, {}, financials_json={"current_num_employees": 12}))

  def test_it_fires_once_the_pool_is_stated(self):
    people = _people(rest_of_team_payroll_year1=620000.0)
    self.assertTrue(IC._team_groups_pending(
      people, {}, financials_json={"current_num_employees": 12}))

  def test_it_does_not_fire_when_there_is_no_pool(self):
    """"There isn't anyone else" routes as 0 - and 0 people have no groups."""
    people = _people(rest_of_team_payroll_year1=0.0)
    self.assertFalse(IC._team_groups_pending(
      people, {}, financials_json={"current_num_employees": 2}))

  def test_it_does_not_fire_for_a_single_unnamed_person(self):
    people = _people(rest_of_team_payroll_year1=0.0)
    self.assertFalse(IC._team_groups_pending(
      people, {}, financials_json={"current_num_employees": 3}))

  def test_it_fires_on_an_unnamed_pool_with_no_stated_money(self):
    people = _people(rest_of_team_payroll_year1=0.0)
    self.assertTrue(IC._team_groups_pending(
      people, {}, financials_json={"current_num_employees": 9}))

  def test_it_is_asked_exactly_once(self):
    """A router that fails to route her sentence costs the grouping, never a
    loop - a run must not die on a technicality (Nick 2026-09-14)."""
    people = _people(rest_of_team_payroll_year1=620000.0)
    financials = {"current_num_employees": 12}
    first = IC._team_groups_turn(ack="Got it.", people_json=people, ops_json={},
                                 financials_json=financials)
    self.assertTrue(first)
    self.assertTrue(people.get("_team_groups_asked"))
    second = IC._team_groups_turn(ack="Got it.", people_json=people, ops_json={},
                                  financials_json=financials)
    self.assertIsNone(second)

  def test_it_does_not_come_back_after_she_answers(self):
    people = _people(rest_of_team_payroll_year1=620000.0,
                     team_groups=[{"name": "Shop crew", "headcount": 9}])
    self.assertFalse(IC._team_groups_pending(
      people, {}, financials_json={"current_num_employees": 12}))

  def test_the_question_carries_its_marker_and_her_count(self):
    people = _people(rest_of_team_payroll_year1=620000.0)
    text = IC._build_team_groups_question(
      "Got it.", people_json=people,
      financials_json={"current_num_employees": 12})
    self.assertIn(IC._TEAM_GROUPS_MARKER, text)
    self.assertIn("10", text)          # 12 stated less the 2 named
    self.assertIn("Got it.", text)
    self.assertNotIn("team_groups", text)   # ONE MOUTH: never a field name
    self.assertNotIn("OEWS", text)


class HerAnswerLandsInTheShapeEverythingReads(unittest.TestCase):

  def test_the_router_is_allowed_to_write_the_field(self):
    schemas = ROUTER._value_schema_by_consult_field(consult_type="people")
    self.assertIn("team_groups", schemas)
    unified = ROUTER._value_schema_by_consult_field(consult_type="unified")
    self.assertIn("people.team_groups", unified)

  def test_the_field_is_on_the_routers_allowlist(self):
    """A field missing here is a field the router's patch is thrown away at,
    silently - that is how a client's volunteered figure was lost once."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(ROUTER).replace("\r\n", "\n"))
    # allowed_fields = { "ops": [...], "people": [...], ... }[consult_type]
    literals = [
      node for node in ast.walk(tree)
      if isinstance(node, ast.Dict)
      and any(getattr(k, "value", None) == "people" for k in node.keys)
      and any(getattr(k, "value", None) == "financials" for k in node.keys)
      and all(isinstance(v, ast.List) for v in node.values)
    ]
    self.assertTrue(literals, "route_intent's allowed_fields is not a literal "
                              "any more - this check needs rewriting")
    node = literals[0]
    people_list = next(
      v for k, v in zip(node.keys, node.values)
      if getattr(k, "value", None) == "people")
    # read the names off the literal - one of the other lists splices a
    # starred constant, so the whole dict is not literal_eval-able
    names = [e.value for e in people_list.elts if isinstance(e, ast.Constant)]
    self.assertIn("team_groups", names)
    self.assertIn("rest_of_team_payroll_year1", names)

  def test_the_shape_reaches_the_prompt(self):
    """A schema the prompt never shows is a schema the model cannot obey."""
    doc = ROUTER._structured_shapes_doc(["people.team_groups"],
                                        consult_type_norm="unified")
    self.assertIn("people.team_groups", doc)
    self.assertIn("name", doc)
    self.assertIn("headcount", doc)

  def test_the_shape_is_enforced_at_the_router(self):
    unified = ROUTER._value_schema_by_consult_field(consult_type="unified")
    schema = unified["people.team_groups"]
    self.assertTrue(ROUTER._validate_value_inner(
      [{"name": "Shop crew", "headcount": 9}], schema))
    self.assertFalse(ROUTER._validate_value_inner(
      [{"group": "Shop crew"}], schema))

  def test_the_instruction_is_only_sent_when_the_question_is_live(self):
    """Not in the people block: that block rides EVERY people turn, and a
    line there re-keys every recorded router response."""
    import inspect
    src = inspect.getsource(ROUTER.route_intent)
    self.assertEqual(1, src.count("Group composition handling"))
    guard = src.index('current_question") or "") == "team_groups"')
    instruction = src.index("Group composition handling")
    self.assertLess(guard, instruction, "the instruction must sit INSIDE the "
                                        "team_groups guard")
    # and nothing else opens a branch between the guard and the instruction,
    # so the instruction cannot be reached on a turn without the frame
    between = src[guard:instruction]
    self.assertNotIn("\n  if ", between)
    self.assertNotIn("\n  elif ", between)
    # the always-on people block must end before the guard
    self.assertLess(src.index("People edits:"), guard)

  def test_her_answer_is_not_read_as_done_adding_people(self):
    """THE LOOP THIS COST A RUN (2026-09-26, draft a1be960d). "I think of them
    as two crews: eight on maintenance and four on installation" reads to the
    done-adding detector as "no more individuals", so the review was
    regenerated and the router never saw her grouping: t30 asks, t31 review,
    t32 rest-of-team, t33 asks again, four times over. The rest-of-team
    question already carried this guard - the group question needs the same
    one, in the same condition."""
    import inspect
    from api_handlers import intake_consult as _ic
    src = inspect.getsource(_ic)
    # the done-adding condition, read back to the `if (` that opens it
    call = src.index("_detect_people_done_adding_via_openai(\n        last_assistant")
    block = src[src.rindex("    if (", 0, call):call]
    self.assertIn("and not rest_payroll_question_live", block)
    self.assertIn("and not team_groups_question_live", block)

  def test_the_review_payload_carries_the_apps_captures_forward(self):
    """The review is rebuilt from the GPT's object; the app's own captured
    fields must survive it or the answer's home is gone by the next turn."""
    import inspect
    from api_handlers import intake_consult as _ic
    sig = inspect.signature(_ic._build_people_review_payload)
    self.assertIn("existing_people_json", sig.parameters)
    src = inspect.getsource(_ic._build_people_review_payload)
    self.assertIn("PEOPLE_REVIEW_CARRIED_FORWARD", src)

  def test_the_applier_keeps_her_words_and_drops_the_nameless(self):
    rows = IC._normalized_team_groups([
      {"name": "Shop floor", "headcount": 4},
      {"name": "  ", "headcount": 3},
      {"group_name": "Office", "people": 2},
      "Drivers",
      17,
    ])
    self.assertEqual(
      [{"name": "Shop floor", "group_name": "Shop floor", "headcount": 4.0},
       {"name": "Office", "group_name": "Office", "headcount": 2.0},
       {"name": "Drivers", "group_name": "Drivers"}],
      rows)

  def test_the_receipt_says_what_landed(self):
    groups = IC._normalized_team_groups(
      [{"name": "Shop floor", "headcount": 4}, {"name": "Office", "headcount": 2}])
    bits = [(f"{g['name']} ({g['headcount']:,.0f})" if g.get("headcount")
             else str(g["name"])) for g in groups]
    self.assertEqual("Shop floor (4), Office (2)", ", ".join(bits))

  def test_the_headcount_leaf_has_words(self):
    """Without them the receipt de-underscores the key and reads a client
    back "your headcount is now 9" for one group of a team of fourteen."""
    from client_intake_and_finmo import capture_receipt as CR
    self.assertIn("people.headcount", CR._LABELS)

  def test_her_group_name_reaches_the_payroll_rows(self):
    """End to end: the question's answer names the block the workbook draws."""
    rows = []
    for q in range(1, 21):
      rows.append({
        "quarter_index": q, "staffing_class": "key_person",
        "person_name": "Rosalind Keir", "position_title": "Owner and General Manager",
        "starting_fte": 1.0, "hires": 0.0, "ending_fte": 1.0,
        "annual_wage": 140000, "payroll_taxes_benefits_percent": 0.22,
        "wage_source": "client_override"})
      rows.append({
        "quarter_index": q, "staffing_class": "supporting_staff",
        "position_title": "Structural Metal Fabricators and Fitters",
        "oews_occ_title": "Structural Metal Fabricators and Fitters",
        "starting_fte": 9.0, "hires": 0.0, "ending_fte": 9.0,
        "annual_wage": 68889, "payroll_taxes_benefits_percent": 0.22,
        "wage_source": "oews_median"})
    payload = {"schedule_horizon_quarters": 20, "rows": rows}
    RP.normalize_payload_to_group_rollforward(
      payload, horizon=20, annual_salary_increase=0.03,
      people_json={"team_groups": IC._normalized_team_groups(
        [{"name": "Shop crew", "headcount": 9}])})
    names = {r["group_name"] for r in payload["rows"]}
    self.assertIn("Shop crew", names)
    self.assertNotIn("Structural Metal Fabricators and Fitters", names)
    self.assertIn("Owner and General Manager", names)
    self.assertEqual([], RP.identities_from_payload_rows(payload["rows"]))


if __name__ == "__main__":
  unittest.main()
