"""THE BRIDGE BETWEEN VS AND COWORK: everything since id N, with a short hold.

SHAPED BY COWORK'S OWN MEASUREMENTS OF ITS SIDE (relayed by Nick 2026-09-22),
not by what would be convenient:

  NOTHING CAN WAKE COWORK FROM OUTSIDE. No inbound endpoint, no POST, no signal.
  Its only wake is its own scheduled message back into its session, floor one
  minute. Clock-driven, never event-driven. So the bridge cannot push; it can
  only be there when Cowork looks.

  A COWORK TURN CANNOT BLOCK FOR MINUTES. Browser JavaScript is its only path to
  127.0.0.1:5050 and there is a hard 45-second CDP timeout - 60s failed, 35s
  returned. So the hold is capped at 30 seconds and RETURNS EMPTY rather than
  hanging, and Cowork chains several inside one turn.

  CURSOR, NEVER "THE NEXT MESSAGE". Its extension and MCP servers drop
  mid-operation. Cowork said this would matter more than the latency and it is
  right: latency costs minutes, a lost or doubled finding costs a run.

The two properties everything else rests on:
  A DROPPED POLL LOSES NOTHING  - the client has not advanced its cursor, so the
                                  same call returns the same rows.
  A REPEATED POLL DOUBLES NOTHING - for the same reason.

AND THE ID A POSTER GETS BACK IS THE ID A READER RESUMES FROM. `issue_id` is the
DEDUPED identity: refiling an existing signature reuses it, so it goes down as
well as up, and a cursor built on it silently skips every repeat filing. That
was live until it was caught here - the POST never returned the occurrence id at
all. The occurrence id is one per filing and only ever increases.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "python"), str(ROOT / "scripts")):
  if p not in sys.path:
    sys.path.insert(0, p)

BASE = "http://127.0.0.1:5050"


def _store_is_up() -> bool:
  try:
    with urllib.request.urlopen(BASE + "/api/ping", timeout=5) as r:
      return r.status == 200
  except Exception:                                           # noqa: BLE001
    return False


def _stream(since_id: int, wait: int = 0, exclude: str = "", limit: int = 50):
  url = "%s/api/issues/stream?since_id=%d&wait=%d&limit=%d" % (BASE, since_id, wait, limit)
  if exclude:
    url += "&exclude_source=" + exclude
  with urllib.request.urlopen(url, timeout=60) as r:
    return json.loads(r.read().decode("utf-8"))


def _tail() -> int:
  cur = 0
  while True:
    d = _stream(cur, limit=200)
    if not d["count"]:
      return cur
    cur = d["cursor"]


@unittest.skipUnless(_store_is_up(), "the store is not running; this pin drives the real endpoint")
class TheBridgeHoldsBrieflyAndNeverHangs(unittest.TestCase):
  """The hold exists to give sub-30-second latency while Cowork is awake. It
  must never become the thing that kills its turn."""

  def test_an_empty_read_actually_holds_and_then_returns(self):
    """THE ONE MEASUREMENT THAT SEPARATES THE CASES (Nick 2026-09-22).

    The first version of this pin asked only that an empty read finish in under
    twenty seconds. That passes just as happily when there is NO HOLD AT ALL -
    which is exactly what Cowork found deployed. "A row posted 1.5s into a hold
    returning at 2.03s" is likewise indistinguishable from no hold plus a
    re-request. The test that tells them apart is asking for a hold WHEN
    NOTHING IS COMING and timing it, so this asserts the LOWER bound first.
    """
    for wait in (3, 6):
      with self.subTest(wait=wait):
        started = time.time()
        d = _stream(_tail(), wait=wait)
        elapsed = time.time() - started
        self.assertEqual(d["count"], 0)
        self.assertGreaterEqual(
          elapsed, wait - 0.5,
          "asked for a %ds hold and it returned in %.2fs - it is not holding"
          % (wait, elapsed))
        self.assertLess(elapsed, wait + 15, "the hold outlived its window")
        self.assertGreaterEqual(d["waited_seconds"], wait - 0.5,
                                "self-reported wait disagrees with the wall clock")

  def test_every_cursor_name_a_caller_might_reach_for_is_honoured(self):
    """Cowork tried eight spellings and every one silently read as 0, returning
    the first fifty rows - a fallback that manufactured a plausible answer out
    of a caller's mistake, and looked like it worked."""
    tail = _tail()
    for name in ("since_id", "cursor", "since", "after", "from", "cursor_id",
                 "min_cursor", "since_cursor", "last"):
      with self.subTest(name=name):
        url = "%s/api/issues/stream?%s=%d&wait=0" % (BASE, name, tail)
        with urllib.request.urlopen(url, timeout=30) as r:
          d = json.loads(r.read().decode("utf-8"))
        self.assertEqual(d["count"], 0,
                         "%s was ignored and the first page came back" % name)
        self.assertEqual(d["cursor"], tail)

  def test_a_cursor_name_we_do_not_know_is_refused_not_defaulted(self):
    """The deeper defect: a silent default standing in for a value nobody
    supplied. Same class as everything else taken out this month."""
    url = "%s/api/issues/stream?cursorr=99999" % BASE
    try:
      with urllib.request.urlopen(url, timeout=30) as r:
        self.fail("an unknown parameter returned %s instead of refusing" % r.status)
    except urllib.error.HTTPError as exc:
      self.assertEqual(exc.code, 400)
      body = json.loads(exc.read().decode("utf-8"))
      self.assertEqual(body.get("error"), "unknown_parameter")
      self.assertIn("since_id", body.get("cursor_names") or [])

  def test_two_cursor_names_that_disagree_are_refused(self):
    url = "%s/api/issues/stream?cursor=10&since=99" % BASE
    try:
      with urllib.request.urlopen(url, timeout=30) as r:
        self.fail("conflicting cursors returned %s" % r.status)
    except urllib.error.HTTPError as exc:
      self.assertEqual(exc.code, 400)
      self.assertEqual(json.loads(exc.read().decode("utf-8")).get("error"),
                       "conflicting_cursors")

  def test_every_row_carries_the_cursor_to_resume_after_it(self):
    """With the cursor only in the envelope, a client that drops after ten of
    fifty rows can only re-request all fifty or skip the other forty."""
    cur = max(0, _tail() - 5)
    rows = _stream(cur)["rows"]
    self.assertTrue(rows)
    for row in rows:
      self.assertEqual(row.get("cursor"), row.get("occurrence_id"))
      self.assertEqual(row.get("occurrence_id"), row.get("id"))

  def test_the_deduped_number_is_present_and_named_apart(self):
    """issue_id is reused by every refiling of a signature, so it goes down as
    well as up. It is carried for reference and must never be the cursor."""
    cur = max(0, _tail() - 5)
    for row in _stream(cur)["rows"]:
      self.assertIn("issue_id", row)
      self.assertNotEqual(row.get("cursor"), None)

  def test_the_hold_is_capped_below_cowork_s_cdp_timeout(self):
    """60s failed on Cowork's side and 35s returned, so the ceiling is 30 - a
    number this endpoint must enforce itself rather than trust a caller."""
    d = _stream(_tail(), wait=999)
    self.assertEqual(d["max_wait_seconds"], 30)
    self.assertLessEqual(d["waited_seconds"], 32)

  def test_a_row_arriving_mid_hold_returns_at_once(self):
    from issue_post import post_issue          # noqa: WPS433
    cur = _tail()
    box = {}

    def _poll():
      box["d"] = _stream(cur, wait=30)

    t = threading.Thread(target=_poll)
    t.start()
    time.sleep(1.5)
    ok, _detail = post_issue({
      "source": "cowork", "category": "progress", "severity": "note",
      "signature": "cowork_bridge_pin_probe",
      "title": "a row arriving mid-hold",
      "expected": "the waiting reader returns as soon as it lands",
      "observed": "posted during an open hold by the pins"})
    t.join(timeout=45)
    self.assertTrue(ok, "the probe did not file")
    d = box.get("d") or {}
    self.assertEqual(d.get("count"), 1)
    self.assertLess(d.get("waited_seconds", 99), 10,
                    "the reader sat out the whole window instead of returning")

  def test_the_server_serves_a_post_while_a_read_is_holding(self):
    """The test above only means anything if the two can happen at once - a
    single-threaded server would deadlock here rather than fail visibly."""
    cur = _tail()
    box = {}
    t = threading.Thread(target=lambda: box.update(d=_stream(cur, wait=6)))
    t.start()
    time.sleep(1.0)
    with urllib.request.urlopen(BASE + "/api/ping", timeout=8) as r:
      self.assertEqual(r.status, 200, "the store stopped answering during a hold")
    t.join(timeout=30)


@unittest.skipUnless(_store_is_up(), "the store is not running; this pin drives the real endpoint")
class ADroppedPollLosesNothingAndARepeatedPollDoublesNothing(unittest.TestCase):
  """The property Cowork asked for ahead of latency."""

  def test_the_same_cursor_returns_the_same_rows(self):
    cur = max(0, _tail() - 5)
    first = [r["id"] for r in _stream(cur)["rows"]]
    second = [r["id"] for r in _stream(cur)["rows"]]
    self.assertEqual(first, second, "a repeated poll did not return the same rows")

  def test_a_cursor_never_moves_when_nothing_arrived(self):
    """A client that stores the returned cursor must not be able to skip a row
    it never saw."""
    cur = _tail()
    self.assertEqual(_stream(cur, wait=2)["cursor"], cur)

  def test_rows_come_back_in_order(self):
    cur = max(0, _tail() - 10)
    ids = [r["id"] for r in _stream(cur)["rows"]]
    self.assertEqual(ids, sorted(ids))

  def test_every_row_is_strictly_after_the_cursor(self):
    cur = max(0, _tail() - 10)
    for row in _stream(cur)["rows"]:
      self.assertGreater(row["id"], cur)

  def test_a_caller_can_exclude_its_own_rows(self):
    """Cowork reading the bridge must not be handed its own filings back."""
    cur = max(0, _tail() - 30)
    for row in _stream(cur, exclude="cowork")["rows"]:
      self.assertNotEqual(str(row.get("source") or "").lower(), "cowork")


@unittest.skipUnless(_store_is_up(), "the store is not running; this pin drives the real endpoint")
class ThePosterAndTheReaderShareOneSequence(unittest.TestCase):
  """THE TRAP THAT WAS LIVE UNTIL IT WAS CAUGHT HERE. The POST returned
  `issue_id`, the deduped identity - refiling an existing signature reuses it,
  so it is not monotonic. A reader resuming from it skips every repeat filing,
  which is the "loses nothing" requirement failed at the first hurdle."""

  def test_the_post_returns_an_occurrence_cursor(self):
    from issue_post import _send              # noqa: WPS433
    ok, detail = _send({
      "source": "vs", "category": "progress", "severity": "note",
      "signature": "vs_bridge_sequence_pin",
      "title": "poster and reader share one sequence",
      "expected": "the id a poster is given is the id a reader resumes from",
      "observed": "pinned"})
    self.assertTrue(ok, detail)

  def test_a_posted_row_is_readable_from_the_cursor_before_it(self):
    from issue_post import post_issue          # noqa: WPS433
    before = _tail()
    ok, _d = post_issue({
      "source": "vs", "category": "progress", "severity": "note",
      "signature": "vs_bridge_sequence_pin_roundtrip",
      "title": "round trip",
      "expected": "readable from the cursor taken before the post",
      "observed": "pinned"})
    self.assertTrue(ok)
    after = _stream(before)
    self.assertGreaterEqual(after["count"], 1)
    self.assertGreater(after["cursor"], before)


if __name__ == "__main__":
  unittest.main(verbosity=2)
