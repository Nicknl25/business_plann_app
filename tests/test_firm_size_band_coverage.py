"""BDS FIRM SIZE: the lookup, the band vocabulary, and the reason (Nick
2026-09-11).

"A reason must be tested against the claim, not against its own condition
- 'no data' fails when the data exists under another code."

Halvorsen Tide Oyster proved three defects on one line of evidence:

1. LOOKUP. warehouse._bds_size took bds4[0] blind. Census BDS excludes
   crop and animal production, so the primary code 1125 (oyster
   aquaculture) has ZERO firm-size rows, while the same business's second
   code 4244 has ten and was never tried. _bds beside it already looped
   every code - the asymmetry was the defect.

2. VOCABULARY. The renderer's label map still expected the twelve-bucket
   BDS vintage ('d) 20 to 49' ...). The table supplies ten ('d) 20 to 99'
   ...), so only a/b/c matched and labels.get() dropped the rest in
   silence: Oswin plotted 18,562 of 19,014 firms, Pelletier 142,990 of
   151,242, both under a title claiming every U.S. firm in the trade.
   A business of 20+ people could never be highlighted either.

3. REASON. _no_firm_size_slice re-ran the renderer's emptiness guard, so
   "no bds_firm_size slice in the bundle" passed the gate on a bundle
   that CARRIED the slice - {"naics4":"1125", "firms_by_size":{}} - while
   the Competitive Landscape beside it cited 125 Massachusetts
   establishments from the same warehouse.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from writing_phase_v2 import warehouse as WH  # noqa: E402
from writing_phase_v2.completeness import (  # noqa: E402
    FIRM_SIZE_ORDER, FIRM_SIZE_RANGES, audit_absences, firm_size_bands)

RENDER_CHARTS = os.path.join(ROOT, "python", "writing_phase_v2", "render",
                             "render_charts.py")

# EXACTLY the vocabulary SELECT DISTINCT firm_size_bucket FROM
# bds_firm_size returns - ten buckets, verified 2026-09-11. Counts are
# Pelletier's (151,242 firms; the stale map plotted 142,990 of them).
DB_BUCKETS = {
  "a) 1 to 4": 96_331, "b) 5 to 9": 25_419, "c) 10 to 19": 21_240,
  "d) 20 to 99": 6_512, "e) 100 to 499": 1_190, "f) 500 to 999": 210,
  "g) 1000 to 2499": 190, "h) 2500 to 4999": 80, "i) 5000 to 9999": 40,
  "j) 10000+": 30,
}


class _Cur:
  """Rows keyed by trade code, and a record of every code ASKED for -
  the fall-through is only real if the second code is actually queried."""

  def __init__(self, rows_by_code, asked):
    self._rows = rows_by_code
    self._hit = []
    self.asked = asked

  def execute(self, sql, params):
    code = params[0]
    self.asked.append(code)
    self._hit = [{"firm_size_bucket": k, "f": v}
                 for k, v in (self._rows.get(code) or {}).items()]

  def fetchall(self):
    return self._hit


class _Conn:
  def __init__(self, rows_by_code):
    self._rows = rows_by_code
    self.asked = []

  def cursor(self, dictionary=True):
    return _Cur(self._rows, self.asked)


class BdsSizeFallThroughTests(unittest.TestCase):
  def test_falls_through_an_uncovered_primary_code(self):
    """1125 has no BDS coverage; 4244 does. The slice comes back on
    4244 and SAYS so."""
    conn = _Conn({"4244": DB_BUCKETS})
    out = WH._bds_size(conn, ["1125", "4244"])
    self.assertEqual(conn.asked, ["1125", "4244"])
    self.assertEqual(out["naics4_used"], "4244")
    self.assertEqual(out["naics4"], "4244")  # the counts' OWN code
    self.assertEqual(out["naics4_tried"], ["1125", "4244"])
    self.assertEqual(out["firms_by_size"], DB_BUCKETS)
    self.assertEqual(out["year"], 2023)
    self.assertEqual(out["source"], "Census BDS")

  def test_first_code_with_rows_wins_and_stops_the_search(self):
    conn = _Conn({"1125": DB_BUCKETS, "4244": {"a) 1 to 4": 1}})
    out = WH._bds_size(conn, ["1125", "4244"])
    self.assertEqual(conn.asked, ["1125"])
    self.assertEqual(out["naics4_used"], "1125")

  def test_no_code_has_coverage_keeps_the_envelope_and_the_trail(self):
    """Every code tried, none with rows: the envelope still ships, with
    naics4_used None - that is what lets the reason gate tell 'no code
    has coverage' from 'nobody looked'."""
    conn = _Conn({})
    out = WH._bds_size(conn, ["1125", "4244"])
    self.assertEqual(conn.asked, ["1125", "4244"])
    self.assertIsNone(out["naics4_used"])
    self.assertEqual(out["naics4"], "1125")
    self.assertEqual(out["naics4_tried"], ["1125", "4244"])
    self.assertEqual(out["firms_by_size"], {})


class BandVocabularyTests(unittest.TestCase):
  def test_every_database_bucket_maps_and_no_firm_is_dropped(self):
    agg, unknown = firm_size_bands(DB_BUCKETS)
    self.assertEqual(unknown, [])
    self.assertEqual(sum(agg.values()), sum(DB_BUCKETS.values()))
    self.assertEqual(sorted(agg), sorted(set(FIRM_SIZE_ORDER)))
    # the bands the stale map lost outright
    self.assertEqual(agg["20–99"], 6_512)
    self.assertEqual(agg["100–499"], 1_190)
    self.assertEqual(agg["1,000+"], 190 + 80 + 40 + 30)

  def test_an_unknown_bucket_comes_back_instead_of_vanishing(self):
    agg, unknown = firm_size_bands({"a) 1 to 4": 10, "z) 20 to 49": 5})
    self.assertEqual(unknown, ["z) 20 to 49"])
    self.assertEqual(agg, {"1–4": 10})

  def test_the_ranges_tile_the_bands_without_a_gap(self):
    self.assertEqual(len(FIRM_SIZE_ORDER), len(FIRM_SIZE_RANGES))
    self.assertEqual(FIRM_SIZE_RANGES[0][0], 1)
    for (lo, hi), (nxt, _) in zip(FIRM_SIZE_RANGES, FIRM_SIZE_RANGES[1:]):
      self.assertEqual(nxt, hi + 1)

  def test_a_forty_person_business_finds_its_band(self):
    """Forced to None by the old 20-49/50-99 ranges against buckets that
    no longer exist - every 20+ business lost its highlight."""
    mine = next(b for b, (lo, hi) in zip(FIRM_SIZE_ORDER, FIRM_SIZE_RANGES)
                if lo <= 40 <= hi)
    self.assertEqual(mine, "20–99")


def _render(warehouse):
  """Run the real renderer over a minimal bundle and hand back the
  figures report. Other figures fail inside their own guards - the
  isolation contract - and competitor_size_bands is the one under test."""
  bundle = {
    "model": {
      "annual": [{"year": 2027 + i, "revenue": 1e6, "ebitda": 2e5,
                  "net_income": 1e5} for i in range(5)],
      "payroll": {"quarter_totals": [{"quarter_index": 1,
                                      "ending_fte": 40.0}]}},
    "derived": {},
    "record": {"financials": {"current_num_employees": 40}},
    "warehouse": warehouse,
  }
  with tempfile.TemporaryDirectory() as tmp:
    bp = os.path.join(tmp, "bundle.json")
    with open(bp, "w", encoding="utf-8") as fh:
      json.dump(bundle, fh)
    charts = os.path.join(tmp, "charts")
    r = subprocess.run([sys.executable, "-X", "utf8", RENDER_CHARTS,
                        bp, charts], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    with open(os.path.join(charts, "figures_report.json"),
              encoding="utf-8") as fh:
      return json.load(fh)["competitor_size_bands"]


class RendererNeverDropsFirmsTests(unittest.TestCase):
  def test_the_whole_database_vocabulary_builds(self):
    row = _render({"bds_firm_size_2023": {
      "naics4": "4244", "naics4_used": "4244",
      "naics4_tried": ["1125", "4244"], "year": 2023,
      "source": "Census BDS", "firms_by_size": DB_BUCKETS}})
    self.assertTrue(row["built"], row.get("reason"))

  def test_an_unknown_bucket_makes_the_figure_ABSENT(self):
    """A key the vocabulary does not cover is a contract break, not a
    rounding detail: no chart beats a chart that omits firms."""
    buckets = dict(DB_BUCKETS)
    buckets["z) 20 to 49"] = 452
    row = _render({"bds_firm_size_2023": {
      "naics4": "4244", "naics4_used": "4244", "year": 2023,
      "source": "Census BDS", "firms_by_size": buckets}})
    self.assertFalse(row["built"])
    self.assertTrue(row["reason"].startswith(
      "BDS firm-size bucket not in the label map"), row["reason"])
    self.assertIn("z) 20 to 49", row["reason"])

  def test_present_but_empty_is_not_reported_as_a_missing_slice(self):
    row = _render({"bds_firm_size_2023": {
      "naics4": "1125", "naics4_used": None,
      "naics4_tried": ["1125", "4244"], "year": 2023,
      "source": "Census BDS", "firms_by_size": {}}})
    self.assertFalse(row["built"])
    self.assertTrue(row["reason"].startswith(
      "BDS firm-size buckets empty"), row["reason"])
    self.assertIn("4244", row["reason"])

  def test_a_truly_missing_slice_still_says_so(self):
    row = _render({})
    self.assertFalse(row["built"])
    self.assertEqual(row["reason"], "no bds_firm_size slice in the bundle")


# The Halvorsen bundle: the envelope IS there, its buckets are empty, and
# the business's OTHER trade code carries BDS rows (bds_2023 holds
# firm-size shares only when bds_firm_size returned rows for that code).
HALVORSEN = {
  "record": {}, "model": {},
  "warehouse": {
    "bds_firm_size_2023": {"naics4": "1125", "naics4_used": None,
                           "naics4_tried": ["1125"], "year": 2023,
                           "source": "Census BDS", "firms_by_size": {}},
    "bds_2023": {"4244": {"year": 2023, "firms": 10_440.0,
                          "estabs_history": [[2023, 12_000]],
                          "share_firms_under_5": 0.62,
                          "share_firms_under_10": 0.78}},
  },
}

NO_COVERAGE_ANYWHERE = {
  "record": {}, "model": {},
  "warehouse": {
    "bds_firm_size_2023": {"naics4": "1125", "naics4_used": None,
                           "naics4_tried": ["1125", "4244"], "year": 2023,
                           "source": "Census BDS", "firms_by_size": {}},
    "bds_2023": {"1125": {"year": 2023, "firms": 900.0,
                          "estabs_history": [[2023, 1_000]]}},
  },
}


def _absent(reason):
  return {"competitor_size_bands": {"id": "competitor_size_bands",
                                    "kind": "figure", "placed": False,
                                    "reason": reason}}


class ReasonTestsTheClaimTests(unittest.TestCase):
  def test_missing_slice_reason_is_FALSE_when_the_envelope_is_there(self):
    out = audit_absences(_absent("no bds_firm_size slice in the bundle"),
                         bundle=HALVORSEN)
    self.assertEqual(len(out), 1)
    self.assertIn("DOES carry bds_firm_size_2023", out[0])
    self.assertIn("1125", out[0])

  def test_missing_slice_reason_holds_when_it_really_is_absent(self):
    out = audit_absences(_absent("no bds_firm_size slice in the bundle"),
                         bundle={"record": {}, "model": {},
                                 "warehouse": {"bds_2023": {}}})
    self.assertEqual(out, [])

  def test_empty_reason_is_FALSE_when_another_trade_code_has_data(self):
    """The claim is about BDS COVERAGE, not about the one bucket dict the
    renderer read: 4244's firm-size shares prove the rows exist."""
    out = audit_absences(
      _absent("BDS firm-size buckets empty for every trade code tried: "
              "1125"), bundle=HALVORSEN)
    self.assertEqual(len(out), 1)
    self.assertIn("4244", out[0])
    self.assertIn("HAS rows", out[0])

  def test_empty_reason_is_FALSE_on_a_bundle_stored_before_naics4_tried(self):
    """The bundles already in the database carry no naics4_tried - the
    exact Halvorsen envelope. The validator falls back to naics4 as the
    only code tried, and 4244 still convicts the reason."""
    b = json.loads(json.dumps(HALVORSEN))
    del b["warehouse"]["bds_firm_size_2023"]["naics4_tried"]
    del b["warehouse"]["bds_firm_size_2023"]["naics4_used"]
    out = audit_absences(
      _absent("BDS firm-size buckets empty for the trade code"), bundle=b)
    self.assertEqual(len(out), 1)
    self.assertIn("4244", out[0])

  def test_empty_reason_is_FALSE_when_a_code_was_never_asked_for(self):
    b = json.loads(json.dumps(HALVORSEN))
    del b["warehouse"]["bds_2023"]["4244"]["share_firms_under_5"]
    del b["warehouse"]["bds_2023"]["4244"]["share_firms_under_10"]
    out = audit_absences(
      _absent("BDS firm-size buckets empty for every trade code tried: "
              "1125"), bundle=b)
    self.assertEqual(len(out), 1)
    self.assertIn("never asked for", out[0])
    self.assertIn("4244", out[0])

  def test_empty_reason_holds_when_no_code_has_coverage(self):
    out = audit_absences(
      _absent("BDS firm-size buckets empty for every trade code tried: "
              "1125, 4244"), bundle=NO_COVERAGE_ANYWHERE)
    self.assertEqual(out, [])

  def test_empty_reason_is_FALSE_when_buckets_carry_counts(self):
    b = json.loads(json.dumps(NO_COVERAGE_ANYWHERE))
    b["warehouse"]["bds_firm_size_2023"]["firms_by_size"] = DB_BUCKETS
    out = audit_absences(
      _absent("BDS firm-size buckets empty for the trade code"), bundle=b)
    self.assertEqual(len(out), 1)
    self.assertIn("buckets carry counts", out[0])

  def test_unknown_bucket_reason_is_FALSE_when_every_key_maps(self):
    b = json.loads(json.dumps(NO_COVERAGE_ANYWHERE))
    b["warehouse"]["bds_firm_size_2023"]["firms_by_size"] = DB_BUCKETS
    out = audit_absences(
      _absent("BDS firm-size bucket not in the label map: d) 20 to 99"),
      bundle=b)
    self.assertEqual(len(out), 1)
    self.assertIn("maps to a band", out[0])

  def test_unknown_bucket_reason_holds_on_a_key_nothing_covers(self):
    b = json.loads(json.dumps(NO_COVERAGE_ANYWHERE))
    b["warehouse"]["bds_firm_size_2023"]["firms_by_size"] = {
      "a) 1 to 4": 10, "z) 20 to 49": 452}
    out = audit_absences(
      _absent("BDS firm-size bucket not in the label map: z) 20 to 49"),
      bundle=b)
    self.assertEqual(out, [])


if __name__ == "__main__":
  unittest.main()
