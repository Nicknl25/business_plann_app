"""COHERENCE MUST HAVE AN EXIT, AND A REFUSAL BINDS (Nick 2026-09-12).

Batch two, four businesses, no plan shipped. Halloran and Meriwether asked
to wrap up the intake four times and were answered with a lever every
time: the park only fired on a fixed phrase list. Sablecreek said "the
warehouse is a signed five-year lease, so rent cannot move" and the
router picked the rent-and-overhead option anyway; the walk cut a signed
lease and closed with "every number you just set is yours".

Rulings:
  - "'Wrap up the intake' is an exit. So is anything a person says when
    they want to stop. A fixed phrase list is the keyword problem again -
    the client's intent goes through the router like everything else."
  - "A refusal is a fact and it binds."
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

from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402


def _rent_and_overhead_option():
  return {
    "id": "costs_gna_rent",
    "label": "Right-size overhead and space",
    "patch": {"kind": "financials_fields", "fields": [
      {"group": "financials", "field": "monthly_rent_expense", "value": 13333.33},
      {"group": "financials", "field": "other_operating_expense", "value": 52776.0},
    ]},
  }


def _walking(options=None, floors=None, key="cost_structure"):
  state = {"status": C.STATUS_WALKING, "digest_hash": "d", "gap_open": 904510.27,
           "gap_initial": 904510.27,
           "round": {"key": key, "options": list(options or [_rent_and_overhead_option()])}}
  if floors:
    state["client_floors"] = dict(floors)
  return {"monthly_rent_expense": 22000, "other_operating_expense": 340000, "_coherence": state}


def _apply(patch, fin, text=""):
  return S.apply_router_patch(patch=dict(patch), ops_json={}, financials_json=fin, user_text=text)


class TheExitGoesThroughTheRouter(unittest.TestCase):
  def test_the_routers_park_is_honoured_with_no_phrase_at_all(self):
    remaining, _ops, fin, notes = _apply({"coherence.parked": True}, _walking(),
                                         "Please wrap up the intake with what we have.")
    self.assertIn("parked", notes)
    self.assertEqual(S.get_state(fin)["status"], C.STATUS_PARKED)
    self.assertEqual(remaining, {})

  def test_a_turn_that_answers_a_question_is_never_a_park(self):
    """CW-024 #116 stays: the Cedar Ridge client itemized their cost lines
    and got parked with Send disabled."""
    _r, _o, fin, notes = _apply({"coherence.parked": True, "financials.monthly_rent_expense": 22000},
                                _walking(), "my rent is 22,000 a month, save it for now")
    self.assertIn("park_ignored_turn_answered_a_question", notes)
    self.assertEqual(S.get_state(fin)["status"], C.STATUS_WALKING)

  def test_an_explicit_stop_phrase_still_parks_when_the_router_missed_it(self):
    _r, _o, fin, notes = _apply({}, _walking(), "Let's pause this for now - I'd like to pick it up later.")
    self.assertIn("parked:explicit_phrase_fallback", notes)
    self.assertEqual(S.get_state(fin)["status"], C.STATUS_PARKED)

  def test_a_park_keeps_the_gap_and_the_round_history(self):
    fin = _walking()
    S.get_state(fin)  # sanity
    _r, _o, fin2, _n = _apply({"coherence.parked": True}, fin, "I'm done for today.")
    st = S.get_state(fin2)
    self.assertEqual(st["gap_initial"], 904510.27)
    self.assertEqual(st["gap_open"], 904510.27)
    self.assertEqual(st["round"]["key"], "cost_structure")

  def test_a_parked_round_stays_frozen_across_an_identity_change(self):
    """Meriwether: 'Save it for now' re-derived growth, the revenue base
    fell 7.9M -> 5.7M and 41% closed became 0%."""
    src = open(S.__file__, encoding="utf-8").read()
    i = src.find('stale_keys = ["growth_error"')
    self.assertGreater(i, 0)
    block = src[i:i + 1000]
    self.assertIn("_ctl.STATUS_PARKED", block)
    self.assertIn("growth_frozen_during_round", block)


class ARefusalBinds(unittest.TestCase):
  def test_the_sablecreek_turn_a_refused_rent_blocks_the_option_that_moves_it(self):
    """Message 93, both halves in one turn: the floor is recorded and the
    option that would cut the lease is NOT applied, whatever the router
    emitted."""
    _r, _o, fin, notes = _apply(
      {"coherence.assert_floor": "rent", "coherence.option": "costs_gna_rent"}, _walking(),
      "The warehouse is a signed five-year lease, so rent cannot move. Take the overhead down where it can.")
    st = S.get_state(fin)
    self.assertTrue(st["client_floors"]["rent"])
    self.assertIn("client_floor:rent", notes)
    self.assertTrue(any(n.startswith("option_blocked_by_floor:costs_gna_rent:rent") for n in notes), notes)
    self.assertEqual(fin["monthly_rent_expense"], 22000)
    self.assertEqual(fin["other_operating_expense"], 340000)
    self.assertNotIn("round", st, "the round rebuilds without the refused move")

  def test_a_floor_recorded_earlier_still_blocks_a_later_option(self):
    fin = _walking(floors={"rent": True})
    _r, _o, fin2, notes = _apply({"coherence.option": "costs_gna_rent"}, fin, "option one")
    self.assertTrue(any(n.startswith("option_blocked_by_floor") for n in notes), notes)
    self.assertEqual(fin2["monthly_rent_expense"], 22000)

  def test_a_clean_option_still_applies(self):
    opt = {"id": "costs_gna", "label": "Trim overhead", "patch": {"kind": "financials_fields", "fields": [
      {"group": "financials", "field": "other_operating_expense", "value": 52776.0}]}}
    fin = _walking(options=[opt], floors={"rent": True})
    _r, _o, fin2, notes = _apply({"coherence.option": "costs_gna"}, fin, "take the overhead down")
    self.assertFalse(any(n.startswith("option_blocked_by_floor") for n in notes), notes)
    self.assertEqual(fin2["other_operating_expense"], 52776.0)
    self.assertEqual(fin2["monthly_rent_expense"], 22000)

  def test_no_more_volume_binds_the_whole_round(self):
    """Halloran 127: 'No more volume. That is my final answer on volume.'
    was answered with a volume lever, then a price lever."""
    vol = {"id": "volume_mid", "label": "Take on a bit more work",
           "patch": {"kind": "ops_volume", "volumes": []}}
    fin = _walking(options=[vol], key="volume")
    _r, _o, fin2, notes = _apply({"coherence.assert_floor": "volume"}, fin, "No more volume.")
    st = S.get_state(fin2)
    self.assertIn("client_floor:volume", notes)
    self.assertIn("volume", st["rounds_done"])
    self.assertTrue(st["client_floors"]["volume"])
    # a later attempt to pick the volume option is blocked too
    fin3 = dict(fin2); st3 = dict(S.get_state(fin3)); st3["round"] = {"key": "volume", "options": [vol]}
    fin3 = S.put_state(fin3, st3)
    _r, _o, fin4, notes4 = _apply({"coherence.option": "volume_mid"}, fin3, "fine, option 1")
    self.assertTrue(any(n.startswith("option_blocked_by_floor:volume_mid:volume") for n in notes4), notes4)

  def test_no_more_price_changes_binds_pricing(self):
    price = {"id": "pricing_mid", "label": "Middle step", "patch": {"kind": "ops_prices", "prices": []}}
    fin = _walking(options=[price], key="pricing")
    _r, _o, fin2, notes = _apply({"coherence.assert_floor": "prices"}, fin, "No more price changes.")
    self.assertIn("pricing", S.get_state(fin2)["rounds_done"])

  def test_the_lever_write_site_holds_a_floored_field(self):
    src = open(S.__file__, encoding="utf-8").read()
    self.assertIn('notes.append(f"floor_held:{_field}")', src)


class TheReceiptTellsTheTruth(unittest.TestCase):
  def test_nothing_moved_says_so(self):
    self.assertIn("Nothing you told me was moved", S._walk_receipt({}))
    self.assertIn("every number you set is yours", S._walk_receipt(None))

  def test_moved_figures_are_named_in_the_clients_units(self):
    r = S._walk_receipt({"monthly_rent_expense": {"from": 22000.0, "to": 13333.33},
                         "other_opex_absolute": {"from": 4080000.0, "to": 633312.0}})
    self.assertIn("rent", r)
    self.assertIn("a month", r)
    self.assertIn("other operating costs", r)
    self.assertIn("a year", r)
    self.assertNotIn("every number you just set is yours", r)

  def test_the_false_sentence_is_gone_from_the_section(self):
    src = open(S.__file__, encoding="utf-8").read()
    self.assertNotIn("Every number you just set is yours.", src)
    self.assertNotIn('"set is yours."', src)


class TheRouterIsToldTheRules(unittest.TestCase):
  def test_stop_intent_and_refusal_precedence_are_in_the_coherence_rules(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intent_router.py"), encoding="utf-8").read()
    self.assertIn("WRAP UP or FINISH the intake", src)
    self.assertIn("A REFUSAL BINDS", src)
    self.assertIn("never answer a stop with another lever", src)


if __name__ == "__main__":
  unittest.main()
