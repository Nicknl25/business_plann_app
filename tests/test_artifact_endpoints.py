"""The artifact routes, exercised against the REAL delivered files on disk.

No conversation, no GPT, no persona: these routes read files. The proof that
they work is that they read the files this app actually shipped - the newest
delivered workbook's Checks!B2, a real written plan's text - and that they
refuse everything else: paths outside the two roots, non-loopback callers,
unknown parameters, and reads by filename.

Filename reads are refused (Nick 2026-09-13). A filename cannot prove which run
produced a file: the output folders are shared across runs, two workbooks for
one business has already happened, and the workbook strips "&" from the
business name so the two artifacts of one business do not even share one. Every
content read here goes through a recorded delivery, which is the only thing
that ties a file to its run.
"""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

WORKBOOK_DIR = Path(os.getenv("BPA_WORKBOOK_DIR") or r"C:\dev\Cilient Plans")
PLAN_DIR = Path(os.getenv("BPA_PLAN_DIR") or r"C:\dev\Client Written Plans")


def _newest(folder: Path, suffix: str):
  if not folder.is_dir():
    return None
  files = [p for p in folder.rglob("*" + suffix)
           if p.is_file() and not p.name.startswith("~$")]
  return max(files, key=lambda p: p.stat().st_mtime) if files else None


class ArtifactTestBase(unittest.TestCase):
  """One recorded draft carrying the newest real workbook and plan, so every
  content read goes the way Cowork's will."""

  @classmethod
  def setUpClass(cls):
    from api import create_app  # type: ignore
    from client_intake_and_finmo import delivered_artifacts as da  # type: ignore
    from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore

    cls.client = create_app().test_client()
    cls.da = da
    cls.conn = get_mysql_connection()
    cls.draft_id = "test_" + uuid.uuid4().hex[:20]
    cls.wb = _newest(WORKBOOK_DIR, ".xlsx")
    cls.plan = _newest(PLAN_DIR, ".docx")
    if cls.wb is not None:
      da.record(cls.conn, draft_id=cls.draft_id, planning_run_id="run_for_test",
                kind="workbook", path=str(cls.wb))
    if cls.plan is not None:
      da.record(cls.conn, draft_id=cls.draft_id, planning_run_id="run_for_test",
                kind="plan", path=str(cls.plan))

  @classmethod
  def tearDownClass(cls):
    try:
      cur = cls.conn.cursor()
      cur.execute("DELETE FROM " + cls.da.TABLE + " WHERE draft_id LIKE %s", ("test_%",))
      cls.conn.commit()
      cur.close()
    finally:
      try:
        cls.conn.close()
      except Exception:
        pass

  def _wb(self, **params):
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    return self.client.get("/api/artifacts/workbook",
                           query_string=dict({"draft_id": self.draft_id}, **params))

  def _plan(self, **params):
    if self.plan is None:
      self.skipTest("no written plans on disk")
    return self.client.get("/api/artifacts/plan",
                           query_string=dict({"draft_id": self.draft_id}, **params))


class ListingTests(ArtifactTestBase):
  def test_list_returns_both_kinds_newest_first(self):
    body = self.client.get("/api/artifacts?limit=25").get_json()
    self.assertEqual(body["status"], "ok")
    self.assertGreater(body["count"], 0, "no delivered artifacts found on disk")
    rows = body["artifacts"]
    self.assertEqual([r["modified"] for r in rows],
                     sorted((r["modified"] for r in rows), reverse=True),
                     "artifacts are not newest-first")
    self.assertTrue({r["kind"] for r in rows} <= {"workbook", "plan"})

  def test_list_filters_by_business(self):
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    token = self.wb.name.split(" -- ")[0].split()[0].lower()
    rows = self.client.get("/api/artifacts?kind=workbook&business=" + token).get_json()["artifacts"]
    self.assertTrue(rows, "business filter " + token + " matched nothing")
    for r in rows:
      self.assertIn(token, r["name"].lower())

  def test_list_rejects_a_bad_kind(self):
    self.assertEqual(self.client.get("/api/artifacts?kind=secrets").status_code, 400)

  def test_excel_lock_files_are_never_listed(self):
    rows = self.client.get("/api/artifacts?kind=workbook&limit=500").get_json()["artifacts"]
    for r in rows:
      self.assertFalse(r["name"].startswith("~$"), r["name"])

  def test_the_list_answers_by_draft_with_timestamps(self):
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    body = self.client.get("/api/artifacts",
                           query_string={"draft_id": self.draft_id}).get_json()
    self.assertEqual(body["draft_id"], self.draft_id)
    self.assertGreaterEqual(body["count"], 1)
    row = [r for r in body["artifacts"] if r["kind"] == "workbook"][0]
    self.assertEqual(row["planning_run_id"], "run_for_test")
    self.assertTrue(row["delivered_at"], "no timestamp - a fresh build must be "
                                         "distinguishable from a stale file")
    self.assertEqual(row["state"], "intact")

  def test_an_unrecorded_draft_lists_nothing_and_says_why(self):
    body = self.client.get("/api/artifacts",
                           query_string={"draft_id": "nope_" + uuid.uuid4().hex[:8]}).get_json()
    self.assertEqual(body["count"], 0)
    self.assertIn("2026-09-13", body["note"])


class WorkbookReadTests(ArtifactTestBase):
  def test_sheet_names(self):
    body = self._wb().get_json()
    self.assertIn("Checks", body["sheets"], "no Checks sheet: " + str(body["sheets"]))

  def test_checks_b2_is_one_get(self):
    """The single cell every Cowork run is asked to report."""
    body = self._wb(sheet="Checks", cell="B2").get_json()
    self.assertEqual(body["cell"], "B2")
    self.assertIsNotNone(body["value"],
                         "Checks!B2 read back empty - cached values missing (A-136)")

  def test_a_cell_returns_formula_and_cached_together(self):
    body = self._wb(sheet="Checks", cell="B2").get_json()
    for key in ("formula", "cached", "has_formula", "has_cached_value"):
      self.assertIn(key, body, key + " missing - the standing question needs both halves")

  def test_a_healthy_workbook_shows_a_formula_with_a_cached_value(self):
    """The whole point of the LibreOffice recalculation work: a formula WITH a
    cached value, not a formula with nothing."""
    body = self._wb(sheet="Checks", cell="B2").get_json()
    self.assertTrue(body["has_formula"], "no formula: " + repr(body.get("formula")))
    self.assertTrue(body["has_cached_value"],
                    "formula with no cached value - A-136: every reader without "
                    "a spreadsheet engine sees a blank")
    self.assertNotIn("warning", body)

  def test_both_halves_agree_whichever_mode_is_asked_for(self):
    a = self._wb(sheet="Checks", cell="B2").get_json()
    b = self._wb(sheet="Checks", cell="B2", formulas="1").get_json()
    self.assertEqual(a["formula"], b["formula"])
    self.assertEqual(a["cached"], b["cached"])

  def test_a_range_reads_a_block(self):
    rows = self._wb(sheet="Checks", cells="A1:B6").get_json()["rows"]
    self.assertEqual(len(rows), 6)
    self.assertEqual(len(rows[0]), 2)

  def test_unknown_sheet_is_404_and_names_the_sheets(self):
    res = self._wb(sheet="NotASheet")
    self.assertEqual(res.status_code, 404)
    self.assertIn("sheets", res.get_json())

  def test_the_read_carries_provenance(self):
    prov = self._wb(sheet="Checks", cell="B2").get_json()["provenance"]
    self.assertEqual(prov["draft_id"], self.draft_id)
    self.assertEqual(prov["state"], "intact")


class PlanReadTests(ArtifactTestBase):
  def test_plan_text_comes_back_readable(self):
    body = self._plan().get_json()
    self.assertEqual(body["format"], "docx")
    self.assertGreater(body["chars"], 500, "plan came back suspiciously short")

  def test_plan_respects_max_chars(self):
    body = self._plan(max_chars=400).get_json()
    self.assertLessEqual(body["chars"], 400)
    self.assertTrue(body.get("truncated"))

  def test_the_render_report_comes_with_the_plan(self):
    """'How many figures, did they place' is a question the plan's own text
    cannot answer."""
    body = self._plan(max_chars=800).get_json()
    self.assertIn("render_report", body)
    report = body["render_report"]
    if report.get("available"):
      self.assertEqual(report["attempted"], report["placed"] + report["absent"])
      for item in report["absent_items"]:
        self.assertIn("id", item)
        self.assertIn("reason", item)

  def test_the_render_report_can_be_turned_off(self):
    self.assertNotIn("render_report", self._plan(render_report="0").get_json())


class RefusalTests(ArtifactTestBase):
  def test_reading_by_filename_is_refused_not_labelled(self):
    """A caveat on something that still works gets ignored, and a playbook
    keeps the path it already has."""
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get("/api/artifacts/workbook",
                          query_string={"file": self.wb.name, "sheet": "Checks", "cell": "B2"})
    self.assertEqual(res.status_code, 400, "a filename read still returned content")
    body = res.get_json()
    self.assertIn("draft_id", body["detail"])
    self.assertIn("how", body)
    self.assertIn("2026-09-13", body["note"], "it must say which files have no record")

  def test_reading_a_plan_by_filename_is_refused_too(self):
    if self.plan is None:
      self.skipTest("no written plans on disk")
    res = self.client.get("/api/artifacts/plan", query_string={"file": self.plan.name})
    self.assertEqual(res.status_code, 400)

  def test_draft_id_and_file_together_are_refused(self):
    res = self._wb(file="anything.xlsx", sheet="Checks", cell="B2")
    self.assertEqual(res.status_code, 400,
                     "two sources that can disagree must not both be accepted")

  def test_an_unrecorded_draft_says_so_rather_than_guessing(self):
    res = self.client.get("/api/artifacts/workbook", query_string={
      "draft_id": "no_such_" + uuid.uuid4().hex[:8], "sheet": "Checks", "cell": "B2"})
    self.assertEqual(res.status_code, 404)
    self.assertIn("no workbook recorded", res.get_json()["detail"])

  def test_a_replaced_file_is_flagged_on_the_read(self):
    """The record's whole point: a path overwritten by a later run must not
    read back as if it were the recorded delivery."""
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    stale = "test_" + uuid.uuid4().hex[:20]
    self.da.record(self.conn, draft_id=stale, kind="workbook", path=str(self.wb))
    cur = self.conn.cursor()
    cur.execute("UPDATE " + self.da.TABLE + " SET sha256=%s WHERE draft_id=%s",
                ("0" * 64, stale))
    self.conn.commit()
    cur.close()
    prov = self.client.get("/api/artifacts/workbook", query_string={
      "draft_id": stale, "sheet": "Checks", "cell": "B2"}).get_json()["provenance"]
    self.assertEqual(prov["state"], "replaced")
    self.assertIn("no longer matches", prov["warning"])

  def test_a_recorded_path_outside_the_root_is_refused(self):
    """The record is data; a row pointing outside the artifact folders must
    still not read that file."""
    stale = "test_" + uuid.uuid4().hex[:20]
    self.da.record(self.conn, draft_id=stale, kind="workbook", path=str(ROOT / ".env"))
    res = self.client.get("/api/artifacts/workbook", query_string={
      "draft_id": stale, "sheet": "Checks", "cell": "B2"})
    self.assertEqual(res.status_code, 404, "a recorded path escaped the root")

  def test_an_unknown_parameter_is_refused_not_ignored(self):
    """Cowork asked for the formula with `values=formula` - a parameter this
    API has never had - and the old code silently returned cached."""
    res = self._wb(sheet="Checks", cell="B2", values="formula")
    self.assertEqual(res.status_code, 400)
    body = res.get_json()
    self.assertIn("values", body["detail"])
    self.assertIn("formulas", body["known_parameters"])
    self.assertIn("help", body["discovery"])

  def test_unknown_parameters_are_refused_on_every_route(self):
    for path in ("/api/artifacts", "/api/artifacts/plan"):
      self.assertEqual(self.client.get(path, query_string={"nonsense": "1"}).status_code, 400,
                       path + " ignored an unknown parameter")

  def test_non_loopback_is_forbidden(self):
    for addr in ("10.0.0.5", "192.168.1.22", "203.0.113.7"):
      for path in ("/api/artifacts", "/api/artifacts/workbook",
                   "/api/artifacts/plan", "/api/artifacts/help"):
        res = self.client.get(path, environ_overrides={"REMOTE_ADDR": addr})
        self.assertEqual(res.status_code, 403, path + " answered " + addr)

  def test_routes_are_read_only(self):
    for path in ("/api/artifacts", "/api/artifacts/workbook",
                 "/api/artifacts/plan", "/api/artifacts/help"):
      for verb in ("post", "put", "delete", "patch"):
        self.assertEqual(getattr(self.client, verb)(path).status_code, 405,
                         verb.upper() + " " + path + " was accepted")


class DiscoveryTests(ArtifactTestBase):
  def test_discovery_names_every_route_in_one_call(self):
    body = self.client.get("/api/artifacts/help").get_json()
    routes = {r["route"] for r in body["routes"]}
    self.assertEqual(routes, {"GET /api/artifacts",
                              "GET /api/artifacts/workbook",
                              "GET /api/artifacts/plan"})
    for r in body["routes"]:
      self.assertTrue(r.get("params") and r.get("example"), r["route"])
    self.assertIn("workbook", body["folders"])

  def test_discovery_says_filename_reads_are_not_supported(self):
    body = self.client.get("/api/artifacts/help").get_json()
    for route in body["routes"]:
      if route["route"] == "GET /api/artifacts":
        continue   # the listing still finds files by name; it reads no content
      self.assertIn("draft_id", route["params"])
      self.assertIn("NOT SUPPORTED", route["params"].get("file", ""),
                    route["route"] + " still advertises reading by filename")

  def test_discovery_is_loopback_only_too(self):
    res = self.client.get("/api/artifacts/help", environ_overrides={"REMOTE_ADDR": "10.0.0.5"})
    self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
  unittest.main(verbosity=2)
