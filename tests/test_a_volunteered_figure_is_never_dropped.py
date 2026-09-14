"""A figure the router names is never dropped in silence - asked for or volunteered.

CW-069, Marchetti and Oyelaran Environmental Labs 2031efa2, turn 11. Asked how
many samples the lab can take in a busy week, she said: "Four hundred and
eighty a week is what the lab can take... In practice we're doing about three
hundred and forty most weeks." The router's own output (response store) named
both correctly: ops.product_overrides {Lab testing job: {units_per_week_capacity:
480, avg_units_per_period_year1: 340}}. The per-line door landed the 480 and
ignored the 340 - its field list did not hold the name - with no log line. With
no actual stored, utilisation read as unanswered and the consultant offered
"about 70%" of 480 for her to plan on: 336 a week, not her 340.

Cowork's reading across two businesses: the figure ASKED FOR is kept and the
figure VOLUNTEERED in the same sentence is dropped. The mechanism under it is a
door refusing a field a router offers, in silence - which is what these pins
state, for any business (Nick: every fix is for ANY business):

  - every per-line driver a router prompt names is accepted by the per-line
    door and carried through a consultant restatement;
  - a field the door does not accept is logged, never dropped in silence;
  - an actual count lands as said, on any cadence, any number of lines, any
    figures, and utilisation is its arithmetic - capacity x utilisation returns
    her count exactly, never above one;
  - a restatement cannot erase the count, and one count broadcast across rows
    is guarded like one price.
"""
from __future__ import annotations

import copy
import itertools
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_NAMES = ("Alpha work", "Bravo service", "Charlie product", "Delta kit", "Echo package")
_QUIET = "nothing about any of them"


def _draft(n, cadence, lob="Main business"):
  # rows as the store holds them: the normaliser gives every weekly row 52
  # periods and every monthly row 12 on its first pass
  periods = {"weekly": 52, "monthly": 12}.get(cadence)
  return {"lob_models": [{"lob_name": lob, "products": [
    {"product_name": _NAMES[i], "unit_cadence": cadence, "operating_periods_per_year": periods}
    for i in range(n)]}]}


def _route(ops, name, values, msg=""):
  from api_handlers.intake_consult import (  # type: ignore
    _apply_scoped_patch, _normalize_ops_capacity_compat,
  )
  _b, out, _m, _p, _f, _fu = _apply_scoped_patch(
    {"ops.product_overrides": {name: values}},
    business_facts={}, ops_json=ops, market_json={}, people_json={}, financials_json={},
    fulfillment_json={}, user_message=msg)
  return _normalize_ops_capacity_compat(out)


def _row(ops, name):
  for lm in ops.get("lob_models") or []:
    for p in lm.get("products") or []:
      if p.get("product_name") == name:
        return p
  raise AssertionError("no row %r" % name)


class TheDoorAcceptsEveryPerLineFieldARouterOffers(unittest.TestCase):
  def test_every_router_named_per_line_driver_is_accepted_and_carried(self):
    from api_handlers.intake_consult import (  # type: ignore
      _CARRIED_PER_LINE_KEYS, _OPS_PER_LINE_NUMERIC_FIELDS, _PER_LINE_DRIVER_FIELDS,
    )
    src = (ROOT / "python" / "client_intake_and_finmo" / "intent_router.py").read_text(encoding="utf-8-sig")
    offered = set()
    # the list is split across two string literals: `...driver field "` / `"(unit_cadence, ...)`
    for m in re.finditer(r"global driver field\W*\(([^)]*)\)", src):
      offered.update(x.strip() for x in m.group(1).split(",") if x.strip())
    self.assertTrue(offered, "the router's per-line driver list was not found - this pin reads nothing")
    # ...and every ops field the multi-line rules name as needing its line
    bare = [l for l in src.splitlines() if "has NO line attached to it" in l]
    self.assertTrue(bare, "the router's per-line bare-field rule was not found")
    offered.update(re.findall(r"ops\.([a-z_0-9]+)", bare[0]))
    offered.update(_OPS_PER_LINE_NUMERIC_FIELDS)
    self.assertEqual(sorted(offered - set(_PER_LINE_DRIVER_FIELDS)), [],
                     "a router offers a per-line field the door would drop")
    self.assertEqual(sorted(offered - {"unit_cadence"} - set(_CARRIED_PER_LINE_KEYS)), [],
                     "a per-line field a restatement would erase")

  def test_the_router_gives_what_a_line_actually_does_a_field_the_door_takes(self):
    """CW-069 replay turn 13: with no rule naming it, the router offered the
    actual only as an unresolved figure with nowhere to land."""
    from api_handlers.intake_consult import _PER_LINE_DRIVER_FIELDS  # type: ignore
    src = (ROOT / "python" / "client_intake_and_finmo" / "intent_router.py").read_text(encoding="utf-8-sig")
    rule = [l for l in src.splitlines() if "WHAT THEY ACTUALLY DO" in l]
    self.assertTrue(rule, "no router rule for what a line actually does")
    named = set(re.findall(r"\bavg_units_per_[a-z_0-9]+", rule[0]))
    self.assertTrue(named, "the rule names no field")
    self.assertEqual(sorted(named - set(_PER_LINE_DRIVER_FIELDS)), [], "the rule names a field the door drops")

  def test_a_field_the_door_does_not_accept_is_logged_never_silent(self):
    with self.assertLogs(level="WARNING") as logs:
      _route(_draft(2, "weekly"), _NAMES[1], {"units_per_week_capacity": 50, "made_up_driver": 7})
    self.assertTrue(any("OPS_PER_LINE_DRIVERS_IGNORED" in line and "made_up_driver" in line
                        for line in logs.output), logs.output)


class AnActualCountLandsForAnyBusiness(unittest.TestCase):
  _SHAPES = {
    "weekly": (("units_per_week_capacity", "avg_units_per_period_year1"),
               ("units_per_week_capacity", "avg_units_per_week_year1"),
               ("units_per_period_capacity", "avg_units_per_period_year1")),
    "monthly": (("units_per_period_capacity", "avg_units_per_period_year1"),),
  }

  def test_the_count_is_kept_as_said_and_utilisation_returns_it(self):
    cases = 0
    for cadence, shapes in self._SHAPES.items():
      for (cap_key, act_key), n, cap, act in itertools.product(
          shapes, (2, 3, 5), (12, 45, 480, 2600), (3, 30, 340, 2000)):
        if act > cap:
          continue
        target = _NAMES[n - 1]
        ops = _route(_draft(n, cadence), target, {cap_key: cap, act_key: act})
        row = _row(ops, target)
        label = "%s %s=%s %s=%s n=%d" % (cadence, cap_key, cap, act_key, act, n)
        self.assertEqual(row.get(act_key), act, "her count did not land as said: " + label)
        util = row.get("utilization_rate")
        self.assertIsNotNone(util, "no utilisation from her count: " + label)
        self.assertLessEqual(util, 1.0, label)
        self.assertAlmostEqual(cap * util, act, delta=1e-9 * max(1.0, act),
                               msg="capacity x utilisation is not her count: " + label)
        for other in _NAMES[:n - 1]:
          self.assertIsNone(_row(ops, other).get("utilization_rate"), "bled onto another row: " + label)
          self.assertNotIn(act_key, _row(ops, other), "bled onto another row: " + label)
        cases += 1
    self.assertGreater(cases, 50)

  def test_an_actual_above_any_capacity_is_kept_and_never_utilisation_above_one(self):
    for cap, act in ((12, 30), (480, 520), (45, 2000)):
      with self.assertLogs(level="WARNING") as logs:
        ops = _route(_draft(2, "weekly"), _NAMES[0],
                     {"units_per_week_capacity": cap, "avg_units_per_period_year1": act})
      row = _row(ops, _NAMES[0])
      self.assertEqual(row.get("avg_units_per_period_year1"), act)
      self.assertIsNone(row.get("utilization_rate"), "utilisation invented from %s over %s" % (act, cap))
      self.assertTrue(any("ACTUAL_ABOVE_STATED_CAPACITY" in line for line in logs.output))

  def test_the_cw069_router_patch_lands_both_figures(self):
    """The regression record: the router's exact output on 2031efa2 turn 11."""
    ops = {"lob_models": [
      {"lob_name": "Lab testing services", "products": [
        {"product_name": "Lab testing job", "unit_cadence": "weekly", "operating_periods_per_year": 52,
         "unit_price": 95, "units_per_week_capacity": None, "units_per_period_capacity": None,
         "utilization_rate": None}]},
      {"lob_name": "Site assessment projects", "products": [
        {"product_name": "Site assessment project", "unit_cadence": "contract",
         "units_per_week_capacity": None, "units_per_period_capacity": None,
         "operating_periods_per_year": None, "utilization_rate": None}]},
    ]}
    out = _route(ops, "Lab testing job", {"units_per_week_capacity": 480, "avg_units_per_period_year1": 340})
    lab, site = _row(out, "Lab testing job"), _row(out, "Site assessment project")
    self.assertEqual(lab.get("units_per_week_capacity"), 480)
    self.assertEqual(lab.get("avg_units_per_period_year1"), 340)
    self.assertAlmostEqual(480 * lab["utilization_rate"], 340, delta=1e-9)
    self.assertIsNone(site.get("utilization_rate"))
    self.assertNotIn("avg_units_per_period_year1", site)


class TheCountSurvivesEveryWriterForAnyBusiness(unittest.TestCase):
  def test_a_restatement_omitting_the_count_erases_nothing(self):
    from api_handlers.intake_consult import _apply_model_ops_patch  # type: ignore

    for n, act_key in itertools.product((2, 3, 5), ("avg_units_per_period_year1", "avg_units_per_week_year1")):
      store = _draft(n, "weekly")
      for i, p in enumerate(store["lob_models"][0]["products"]):
        p.update({"units_per_week_capacity": 100 + i, act_key: 60 + i})
      snapshot = {"lob_models": [{"lob_name": "Main business", "products": [
        {"product_name": _NAMES[i], "unit_cadence": "weekly"} for i in range(n)]}]}
      out = _apply_model_ops_patch(copy.deepcopy(store), snapshot, user_message="nothing new")
      for i in range(n):
        self.assertEqual(_row(out, _NAMES[i]).get(act_key), 60 + i, "n=%d %s row %d erased" % (n, act_key, i))

  def test_one_count_broadcast_across_rows_is_guarded_like_one_price(self):
    from api_handlers.intake_consult import _guard_multiline_ops_rows  # type: ignore

    for n, act_key, value in itertools.product(
        (2, 3, 5), ("avg_units_per_period_year1", "avg_units_per_week_year1"), (7.0, 340.0)):
      prev = _draft(n, "weekly")
      patch = copy.deepcopy(prev)
      for p in patch["lob_models"][0]["products"]:
        p[act_key] = value
      restored = _guard_multiline_ops_rows(prev, patch, _QUIET)
      self.assertTrue(restored, "a broadcast %s=%r across %d rows was not caught" % (act_key, value, n))
      for p in patch["lob_models"][0]["products"]:
        self.assertNotIn(act_key, p)


class EveryFieldTheConsultantReadsHasWords(unittest.TestCase):
  """CW-069 clone replay: her 340 landed, and the reply called it "your average
  units per week in the first year" - the key, paraphrased. A field needs words
  before it ships, and the words must reach the model that reads the key."""

  def test_every_field_in_a_context_comes_with_its_words(self):
    import json
    import random
    from client_intake_and_finmo.intake_required_fields import FIELD_LABELS, words_for_fields_in  # type: ignore

    keys = sorted(FIELD_LABELS)
    rng = random.Random(20260913)
    for _ in range(60):
      chosen = rng.sample(keys, k=rng.randint(1, min(8, len(keys))))
      ctx = json.dumps({"ops": {"lob_models": [{"products": [{k: 1 for k in chosen}]}]}})
      got = dict(words_for_fields_in(ctx))
      self.assertEqual(sorted(got), sorted(chosen), chosen)
      for k in chosen:
        self.assertEqual(got[k], FIELD_LABELS[k])

  def test_every_per_line_field_the_door_takes_has_words(self):
    from api_handlers.intake_consult import _PER_LINE_DRIVER_FIELDS  # type: ignore
    from client_intake_and_finmo.intake_required_fields import FIELD_LABELS  # type: ignore

    self.assertEqual([f for f in _PER_LINE_DRIVER_FIELDS if f not in FIELD_LABELS], [],
                     "a per-line field the door writes has no words the client can hear")


if __name__ == "__main__":
  unittest.main(verbosity=2)
