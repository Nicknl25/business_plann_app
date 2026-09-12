"""THE CLIENT'S TODAY (Nick 2026-09-12).

"A client finishing an intake after 8pm should not get tomorrow's date on
their plan."

Three clocks used to date a client's plan: the handler's utcnow() (the
intake, its stage inference, its milestone months, every GPT context),
MySQL's server-local created_at (the writing phase's projection window -
the first of the month AFTER intake, so a UTC flip on the last evening of a
month moved Q1 by a quarter), and the app server's date.today() (the
"prepared" date). None was the client's. One module now resolves one date:
the browser's own (sent as client_today), else today in the business's
state, else the server's LOCAL day - never UTC.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo import client_today as CT  # noqa: E402


def _utcnow_calls(path):
  """Line numbers of every ``...utcnow().date()`` CALL in the file - a UTC
  clock used as a DATE. A utcnow() used to stamp a diagnostics record is a
  timestamp, not a client's day, and is not this test's business; the word
  in a docstring saying 'never utcnow' does not count either."""
  import ast
  tree = ast.parse(open(path, encoding="utf-8-sig").read())  # intake_consult.py carries a BOM
  out = []
  for n in ast.walk(tree):
    if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "date"):
      continue
    inner = n.func.value
    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "utcnow":
      out.append(n.lineno)
  return out


class TheBrowserDateWins(unittest.TestCase):
  def test_client_today_in_the_request_is_used_verbatim(self):
    self.assertEqual(
      CT.resolve_client_today({"client_today": "2026-09-11"}, {"address_state": "NY"}),
      date(2026, 9, 11))

  def test_camel_case_and_the_long_name_are_accepted(self):
    self.assertEqual(CT.resolve_client_today({"clientToday": "2026-01-05"}, {}), date(2026, 1, 5))
    self.assertEqual(CT.resolve_client_today({"client_local_date": "2026-01-06"}, {}), date(2026, 1, 6))

  def test_garbage_is_ignored_and_the_next_source_decides(self):
    prev = os.environ.pop("INTAKE_CURRENT_DATE", None)
    try:
      # 03:30 UTC on the 12th is 23:30 on the 11th in Oregon
      now = datetime(2026, 9, 12, 3, 30, tzinfo=timezone.utc)
      self.assertEqual(
        CT.resolve_client_today({"client_today": "yesterday"}, {"address_state": "OR"}, now=now),
        date(2026, 9, 11))
    finally:
      if prev is not None:
        os.environ["INTAKE_CURRENT_DATE"] = prev


class TheStateZoneIsNext(unittest.TestCase):
  def setUp(self):
    self._prev = os.environ.pop("INTAKE_CURRENT_DATE", None)

  def tearDown(self):
    if self._prev is not None:
      os.environ["INTAKE_CURRENT_DATE"] = self._prev

  def test_a_portland_business_at_nine_pm_is_still_today(self):
    """THE RULING, literally: 21:00 in Portland on the 11th is 04:00 UTC
    on the 12th. The old code dated this intake the 12th."""
    now = datetime(2026, 9, 12, 4, 0, tzinfo=timezone.utc)
    self.assertEqual(CT.resolve_client_today({}, {"address_state": "OR"}, now=now), date(2026, 9, 11))
    self.assertEqual(CT.today_for({"address_state": "Oregon"}, now=now), date(2026, 9, 11))

  def test_state_names_and_codes_both_resolve(self):
    self.assertEqual(CT.state_zone("MA"), "America/New_York")
    self.assertEqual(CT.state_zone("massachusetts"), "America/New_York")
    self.assertEqual(CT.state_zone("Hawaii"), "Pacific/Honolulu")
    self.assertIsNone(CT.state_zone(""))
    self.assertIsNone(CT.state_zone("Ontario"))

  def test_every_state_and_dc_has_a_zone(self):
    self.assertEqual(len(CT.US_STATE_TZ), 51)

  def test_a_persisted_intake_date_outranks_the_zone_for_post_intake(self):
    now = datetime(2026, 9, 12, 4, 0, tzinfo=timezone.utc)
    self.assertEqual(
      CT.today_for({"address_state": "NY", "current_date": "2026-09-01"}, now=now),
      date(2026, 9, 1))


class TheLastResortIsServerLocalNeverUtc(unittest.TestCase):
  def test_no_state_no_request_is_the_servers_local_day(self):
    prev = os.environ.pop("INTAKE_CURRENT_DATE", None)
    try:
      self.assertEqual(CT.resolve_client_today({}, {}), datetime.now().date())
      self.assertEqual(CT.today_for({}), datetime.now().date())
    finally:
      if prev is not None:
        os.environ["INTAKE_CURRENT_DATE"] = prev

  def test_the_module_never_calls_utcnow_for_a_date(self):
    self.assertEqual(_utcnow_calls(CT.__file__), [])


class TheCreatedAtStampBecomesTheClientsDate(unittest.TestCase):
  """MySQL stamps created_at with NOW() in the DB server's zone and hands
  it back naive. The projection window must be dated by the CLIENT's
  calendar, so the stamp is placed in the server's zone and converted."""

  def test_a_late_evening_eastern_stamp_stays_on_the_same_day_for_oregon(self):
    # 23:30 server-local (Eastern) on the 11th is 20:30 in Oregon, the 11th
    local = datetime(2026, 9, 11, 23, 30)
    server_tz = local.astimezone().tzinfo
    # only meaningful when this machine is in the Eastern zone the fixture assumes
    if server_tz.utcoffset(local) != timedelta(hours=-4):
      self.skipTest("fixture assumes an EDT server; this machine is %s" % server_tz)
    self.assertEqual(CT.client_date_of(local, "OR"), date(2026, 9, 11))

  def test_an_aware_utc_stamp_converts_directly(self):
    # 02:00 UTC on the 12th = 22:00 Eastern on the 11th
    self.assertEqual(
      CT.client_date_of(datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc), "NY"),
      date(2026, 9, 11))
    # ...and 10:00 Pacific on the 11th for Oregon? 02:00 UTC = 19:00 PDT on the 11th
    self.assertEqual(
      CT.client_date_of(datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc), "OR"),
      date(2026, 9, 11))

  def test_a_bare_date_and_an_iso_string_round_trip(self):
    self.assertEqual(CT.client_date_of(date(2026, 9, 2), "MA"), date(2026, 9, 2))
    self.assertEqual(
      CT.client_date_of("2026-09-12 02:00:00", "NY").__class__, date)
    self.assertIsNone(CT.client_date_of(None, "NY"))


class TheHandlerAndTheGateAreWired(unittest.TestCase):
  def test_the_handler_resolves_today_through_the_module(self):
    src = open(os.path.join(ROOT, "python", "api_handlers", "intake_consult.py"), encoding="utf-8").read()
    self.assertIn("current_date = _resolve_client_today(payload, business_facts)", src)
    self.assertNotIn("current_date = datetime.utcnow().date()", src)

  def test_no_dating_module_calls_utcnow_any_more(self):
    """The whole footprint: the handler, the post-intake runner, the
    quarter grid, adaptive policy and the writing bundle. A utcnow CALL
    anywhere in them is a client dated by London."""
    for rel in ("python/api_handlers/intake_consult.py",
                "python/client_intake_and_finmo/post_intake_contracts/runner.py",
                "python/client_intake_and_finmo/quarter_grid.py",
                "python/client_intake_and_finmo/post_intake_adaptive_planning/policy.py",
                "python/writing_phase_v2/bundle.py",
                "python/client_intake_and_finmo/client_today.py"):
      self.assertEqual(_utcnow_calls(os.path.join(ROOT, rel)), [], rel)

  def test_post_intake_and_the_bundle_read_the_module(self):
    for rel, needle in (
      ("python/client_intake_and_finmo/post_intake_contracts/runner.py", "today_for(facts)"),
      ("python/client_intake_and_finmo/quarter_grid.py", "today_for(facts)"),
      ("python/writing_phase_v2/bundle.py", "client_date_of(draft.get(\"created_at\")"),
      ("python/writing_phase_v2/bundle.py", "today_for(draft)"),
    ):
      src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
      self.assertIn(needle, src, rel)
    for rel in ("python/client_intake_and_finmo/post_intake_contracts/runner.py",
                "python/client_intake_and_finmo/quarter_grid.py"):
      src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
      self.assertNotIn("today = datetime.utcnow().date()", src, rel)

  def test_the_browser_sends_its_date_and_the_gate_sends_the_recording_date(self):
    fe = open(os.path.join(ROOT, "frontend", "src", "intake_form", "steps", "UnifiedConsultStep.tsx"), encoding="utf-8").read()
    self.assertIn("client_today: localIsoDate()", fe)
    self.assertIn("function localIsoDate()", fe)
    gate = open(os.path.join(ROOT, "scripts", "intake_persona_gate.py"), encoding="utf-8").read()
    self.assertIn('"client_today": str(getattr(PS, "RECORDED_ON", "") or "")', gate)


if __name__ == "__main__":
  unittest.main()
