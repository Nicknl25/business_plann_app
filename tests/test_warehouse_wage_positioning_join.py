"""The OEWS area join and the wage-positioning row builder (Nick's
rulings 2026-09-10, universal-class fixes).

1. AREA JOIN: oews_state_wages.area_title carries FULL state names;
   _metro_area's fallback returned the draft's abbreviation ('IL'), so
   the join matched zero rows for EVERY multi-metro state - which is
   essentially every state. wage_positioning AND oews_may2023 came back
   empty, silently. The complete USPS table now translates both ways.

2. P90 CAP: BLS reports no p90 for top-earning occupations (Illinois:
   43 of 780 rows - dentists, executives). Requiring p90 dropped
   exactly the best-paid roles; the bar top now falls back to p75,
   stamped top_percentile so the renderer captions what it drew.

3. STAMP HEALING: rosters authored while the matcher was broken carry
   mis-stamps (a Lead hygienist as 11-1021). _wage_rows_from_roster now
   re-derives every key person through the author's own exported
   matcher; a fresh match wins, the stored stamp is only the fallback.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from writing_phase_v2 import warehouse as WH  # noqa: E402


class StateAreaTitleTests(unittest.TestCase):
  def test_abbr_becomes_full_name(self):
    self.assertEqual(WH._state_area_title("IL"), "Illinois")
    self.assertEqual(WH._state_area_title("mi"), "Michigan")

  def test_full_name_passes_through(self):
    self.assertEqual(WH._state_area_title("Illinois"), "Illinois")

  def test_abbr_both_directions(self):
    self.assertEqual(WH._state_abbr("Illinois"), "IL")
    self.assertEqual(WH._state_abbr("IL"), "IL")
    self.assertEqual(WH._state_abbr("District of Columbia"), "DC")


class _Cur:
  def __init__(self, rows_by_key):
    self._rows = rows_by_key

  def execute(self, sql, params):
    self._hit = self._rows.get(params)

  def fetchone(self):
    return self._hit


class _Conn:
  def __init__(self, rows_by_key):
    self._rows = rows_by_key

  def cursor(self, dictionary=True):
    return _Cur(self._rows)


class WagePositioningRowTests(unittest.TestCase):
  def test_p90_cap_falls_back_to_p75(self):
    conn = _Conn({("29-1021", "Illinois"): {
      "occ_title": "Dentists, General", "area_title": "Illinois",
      "a_pct10": 82960.0, "a_pct25": 130840.0, "a_median": 180420.0,
      "a_pct75": 229320.0, "a_pct90": None}})
    out = WH._wage_positioning(conn, [{"soc": "29-1021",
                                       "client_wage": 180000,
                                       "client_label": "Dr. H"}], "Illinois")
    self.assertEqual(len(out), 1)
    self.assertEqual(out[0]["top"], 229320.0)
    self.assertEqual(out[0]["top_percentile"], 75)

  def test_no_spine_at_all_still_omits(self):
    conn = _Conn({("29-1021", "Illinois"): {
      "occ_title": "Dentists, General", "area_title": "Illinois",
      "a_pct10": 82960.0, "a_pct25": None, "a_median": 180420.0,
      "a_pct75": None, "a_pct90": None}})
    out = WH._wage_positioning(conn, [{"soc": "29-1021", "client_wage": 1,
                                       "client_label": "x"}], "Illinois")
    self.assertEqual(out, [])


class StampHealingTests(unittest.TestCase):
  DRAFT = {
    "payroll_headcount": json.dumps({"rows": [
      {"quarter_index": 1, "person_name": "Emily Carter",
       "staffing_class": "key_person", "base_annual_wage": 70000,
       "wage_source": "client_override", "oews_occ_code": "11-1021"}]}),
    "people_json": json.dumps({"people": [
      {"full_name": "Emily Carter", "role_title": "Lead hygienist"}]}),
    "operating_model_json": "{}",
  }

  def test_fresh_match_overrides_a_legacy_mis_stamp(self):
    with mock.patch("client_intake_and_finmo.post_intake_headcount."
                    "schedule.match_occupation_for_person",
                    return_value={"matched_occ_code": "29-1292",
                                  "matched_occ_title": "Dental Hygienists",
                                  "match_basis": "t"}):
      rows = WH._wage_rows_from_roster(self.DRAFT)
    self.assertEqual(rows[0]["soc"], "29-1292")

  def test_stored_stamp_survives_when_matcher_returns_nothing(self):
    with mock.patch("client_intake_and_finmo.post_intake_headcount."
                    "schedule.match_occupation_for_person",
                    return_value=None):
      rows = WH._wage_rows_from_roster(self.DRAFT)
    self.assertEqual(rows[0]["soc"], "11-1021")


if __name__ == "__main__":
  unittest.main()
