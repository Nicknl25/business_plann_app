"""The artifact routes, exercised against the REAL delivered files on disk.

No conversation, no GPT, no persona: these routes read files. The proof that
they work is that they read the files this app actually shipped - the newest
delivered workbook's Checks!B2, a real written plan's text - and that they
refuse everything outside the two roots.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

WORKBOOK_DIR = Path(os.getenv("BPA_WORKBOOK_DIR") or r"C:\dev\Cilient Plans")
PLAN_DIR = Path(os.getenv("BPA_PLAN_DIR") or r"C:\dev\Client Written Plans")


def _newest(folder: Path, suffix: str) -> Path | None:
  if not folder.is_dir():
    return None
  files = [p for p in folder.rglob(f"*{suffix}") if p.is_file() and not p.name.startswith("~$")]
  return max(files, key=lambda p: p.stat().st_mtime) if files else None


class ArtifactEndpointTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    from api import create_app  # type: ignore

    cls.app = create_app()
    cls.client = cls.app.test_client()

  # ---------------------------------------------------------------- list

  def test_list_returns_both_kinds_newest_first(self):
    res = self.client.get("/api/artifacts?limit=25")
    self.assertEqual(res.status_code, 200, res.data[:300])
    body = res.get_json()
    self.assertEqual(body["status"], "ok")
    self.assertGreater(body["count"], 0, "no delivered artifacts found on disk")
    rows = body["artifacts"]
    self.assertTrue(rows, "empty artifact page")
    self.assertEqual(
      [r["modified"] for r in rows],
      sorted((r["modified"] for r in rows), reverse=True),
      "artifacts are not newest-first",
    )
    self.assertTrue({r["kind"] for r in rows} <= {"workbook", "plan"})

  def test_list_filters_by_business(self):
    wb = _newest(WORKBOOK_DIR, ".xlsx")
    if wb is None:
      self.skipTest("no workbooks on disk")
    token = wb.name.split(" -- ")[0].split()[0].lower()
    res = self.client.get(f"/api/artifacts?kind=workbook&business={token}")
    self.assertEqual(res.status_code, 200)
    rows = res.get_json()["artifacts"]
    self.assertTrue(rows, f"business filter {token!r} matched nothing")
    for r in rows:
      self.assertIn(token, r["name"].lower())

  def test_list_rejects_a_bad_kind(self):
    res = self.client.get("/api/artifacts?kind=secrets")
    self.assertEqual(res.status_code, 400)

  def test_excel_lock_files_are_never_listed(self):
    res = self.client.get("/api/artifacts?kind=workbook&limit=500")
    for r in res.get_json()["artifacts"]:
      self.assertFalse(r["name"].startswith("~$"), r["name"])

  # ------------------------------------------------------------ workbook

  def test_workbook_sheet_names(self):
    wb = _newest(WORKBOOK_DIR, ".xlsx")
    if wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get("/api/artifacts/workbook", query_string={"file": wb.name})
    self.assertEqual(res.status_code, 200, res.data[:300])
    body = res.get_json()
    self.assertEqual(body["file"], wb.name)
    self.assertIn("Checks", body["sheets"], f"delivered workbook has no Checks sheet: {body['sheets']}")

  def test_checks_b2_is_one_get(self):
    """The single cell every Cowork run is asked to report."""
    wb = _newest(WORKBOOK_DIR, ".xlsx")
    if wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get(
      "/api/artifacts/workbook",
      query_string={"file": wb.name, "sheet": "Checks", "cell": "B2"},
    )
    self.assertEqual(res.status_code, 200, res.data[:300])
    body = res.get_json()
    self.assertEqual(body["sheet"], "Checks")
    self.assertEqual(body["cell"], "B2")
    self.assertEqual(body["values"], "cached")
    self.assertIn("value", body)
    self.assertIsNotNone(body["value"], "Checks!B2 read back empty - cached values are missing (A-136 class)")

  def test_formulas_mode_reads_the_formula_not_the_value(self):
    """A-136: a workbook can carry perfect formulas and no cached values, and
    every reader without a spreadsheet engine then sees blanks. The route has
    to be able to tell the two apart."""
    wb = _newest(WORKBOOK_DIR, ".xlsx")
    if wb is None:
      self.skipTest("no workbooks on disk")
    q = {"file": wb.name, "sheet": "Checks", "cell": "B2"}
    cached = self.client.get("/api/artifacts/workbook", query_string=q).get_json()
    formula = self.client.get("/api/artifacts/workbook", query_string={**q, "formulas": "1"}).get_json()
    self.assertEqual(cached["values"], "cached")
    self.assertEqual(formula["values"], "formulas")

  def test_workbook_range_reads_a_block(self):
    wb = _newest(WORKBOOK_DIR, ".xlsx")
    if wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get(
      "/api/artifacts/workbook",
      query_string={"file": wb.name, "sheet": "Checks", "cells": "A1:B6"},
    )
    self.assertEqual(res.status_code, 200, res.data[:300])
    rows = res.get_json()["rows"]
    self.assertEqual(len(rows), 6)
    self.assertEqual(len(rows[0]), 2)

  def test_unknown_sheet_is_404_and_names_the_sheets(self):
    wb = _newest(WORKBOOK_DIR, ".xlsx")
    if wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get(
      "/api/artifacts/workbook", query_string={"file": wb.name, "sheet": "NotASheet"}
    )
    self.assertEqual(res.status_code, 404)
    self.assertIn("sheets", res.get_json())

  # ---------------------------------------------------------------- plan

  def test_plan_text_comes_back_readable(self):
    plan = _newest(PLAN_DIR, ".docx")
    if plan is None:
      self.skipTest("no written plans on disk")
    res = self.client.get("/api/artifacts/plan", query_string={"file": plan.name})
    self.assertEqual(res.status_code, 200, res.data[:300])
    body = res.get_json()
    self.assertEqual(body["format"], "docx")
    self.assertGreater(body["chars"], 500, "written plan came back suspiciously short")
    self.assertIn("text", body)

  def test_plan_respects_max_chars(self):
    plan = _newest(PLAN_DIR, ".docx")
    if plan is None:
      self.skipTest("no written plans on disk")
    res = self.client.get("/api/artifacts/plan", query_string={"file": plan.name, "max_chars": 400})
    body = res.get_json()
    self.assertLessEqual(body["chars"], 400)
    self.assertTrue(body.get("truncated"))

  # ------------------------------------------------------------ refusals

  def test_traversal_out_of_the_root_is_refused(self):
    for rel in (r"..\..\.env", "../../.env", r"..\business_plann_app\.env", "../../../Windows/win.ini"):
      res = self.client.get("/api/artifacts/plan", query_string={"file": rel})
      self.assertEqual(res.status_code, 404, f"{rel!r} was not refused: {res.data[:200]}")

  def test_absolute_path_outside_the_root_is_refused(self):
    res = self.client.get("/api/artifacts/plan", query_string={"file": str(ROOT / ".env")})
    self.assertEqual(res.status_code, 404, res.data[:200])

  def test_a_workbook_cannot_be_read_through_the_plan_route(self):
    wb = _newest(WORKBOOK_DIR, ".xlsx")
    if wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get("/api/artifacts/plan", query_string={"file": wb.name})
    self.assertEqual(res.status_code, 404)

  def test_missing_file_argument_is_400(self):
    self.assertEqual(self.client.get("/api/artifacts/workbook").status_code, 400)
    self.assertEqual(self.client.get("/api/artifacts/plan").status_code, 400)

  def test_non_loopback_is_forbidden(self):
    """These routes read the operator's disk. Nothing that arrived over a
    network interface gets an answer."""
    for addr in ("10.0.0.5", "192.168.1.22", "203.0.113.7"):
      for path in ("/api/artifacts", "/api/artifacts/workbook", "/api/artifacts/plan"):
        res = self.client.get(path, environ_overrides={"REMOTE_ADDR": addr})
        self.assertEqual(res.status_code, 403, f"{path} answered {addr}")

  def test_routes_are_read_only(self):
    """No write verb is bound on any artifact route."""
    for path in ("/api/artifacts", "/api/artifacts/workbook", "/api/artifacts/plan"):
      for verb in ("post", "put", "delete", "patch"):
        res = getattr(self.client, verb)(path)
        self.assertEqual(res.status_code, 405, f"{verb.upper()} {path} was accepted")


class BothHalvesAndDiscoveryTests(unittest.TestCase):
  """Cowork's spec, and the defect underneath it: asking for the formula with
  `values=formula` - a parameter this API never had - silently returned the
  cached value, so a wrong call and a right call gave the same shape of
  answer."""

  @classmethod
  def setUpClass(cls):
    from api import create_app  # type: ignore

    cls.client = create_app().test_client()
    cls.wb = _newest(WORKBOOK_DIR, ".xlsx")

  def test_a_cell_returns_formula_and_cached_together(self):
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get("/api/artifacts/workbook",
                          query_string={"file": self.wb.name, "sheet": "Checks", "cell": "B2"})
    self.assertEqual(res.status_code, 200, res.data[:300])
    body = res.get_json()
    for key in ("formula", "cached", "has_formula", "has_cached_value"):
      self.assertIn(key, body, f"{key} missing - the standing question needs both halves")

  def test_a_healthy_workbook_shows_a_formula_with_a_cached_value(self):
    """The whole point of the LibreOffice recalculation work: a formula WITH a
    cached value, not a formula with nothing."""
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    body = self.client.get(
      "/api/artifacts/workbook",
      query_string={"file": self.wb.name, "sheet": "Checks", "cell": "B2"}).get_json()
    self.assertTrue(body["has_formula"], f"Checks!B2 carries no formula: {body.get('formula')!r}")
    self.assertTrue(body["has_cached_value"],
                    "formula with no cached value - A-136: every reader without a "
                    "spreadsheet engine sees a blank")
    self.assertNotIn("warning", body)

  def test_both_halves_agree_whichever_mode_is_asked_for(self):
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    q = {"file": self.wb.name, "sheet": "Checks", "cell": "B2"}
    a = self.client.get("/api/artifacts/workbook", query_string=q).get_json()
    b = self.client.get("/api/artifacts/workbook", query_string={**q, "formulas": "1"}).get_json()
    self.assertEqual(a["formula"], b["formula"])
    self.assertEqual(a["cached"], b["cached"])

  def test_an_unknown_parameter_is_refused_not_ignored(self):
    """The actual Cowork bug. `values=formula` must not quietly become the
    default."""
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get(
      "/api/artifacts/workbook",
      query_string={"file": self.wb.name, "sheet": "Checks", "cell": "B2", "values": "formula"})
    self.assertEqual(res.status_code, 400, res.data[:300])
    body = res.get_json()
    self.assertIn("values", body["detail"])
    self.assertIn("formulas", body["known_parameters"])
    self.assertIn("help", body["discovery"])

  def test_unknown_parameters_are_refused_on_every_route(self):
    for path in ("/api/artifacts", "/api/artifacts/plan"):
      res = self.client.get(path, query_string={"nonsense": "1"})
      self.assertEqual(res.status_code, 400, f"{path} ignored an unknown parameter")

  def test_discovery_names_every_route_in_one_call(self):
    res = self.client.get("/api/artifacts/help")
    self.assertEqual(res.status_code, 200)
    body = res.get_json()
    routes = {r["route"] for r in body["routes"]}
    self.assertEqual(routes, {"GET /api/artifacts",
                              "GET /api/artifacts/workbook",
                              "GET /api/artifacts/plan"})
    for r in body["routes"]:
      self.assertTrue(r.get("params") and r.get("example"), r["route"])
    self.assertIn("workbook", body["folders"])

  def test_discovery_is_loopback_only_too(self):
    res = self.client.get("/api/artifacts/help", environ_overrides={"REMOTE_ADDR": "10.0.0.5"})
    self.assertEqual(res.status_code, 403)


class DraftKeyedReadTests(unittest.TestCase):
  """Reading by filename cannot prove provenance. The folders are shared across
  runs, two workbooks for one business have already happened, and the workbook
  and the plan do not even spell the business the same way - the workbook
  strips '&', so 'Sorrel & Dunne Cold Brew' ships as 'Sorrel Dunne Cold Brew'.
  Only the delivery record ties a file to the run that made it."""

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
    if cls.wb is not None:
      da.record(cls.conn, draft_id=cls.draft_id, planning_run_id="run_for_test",
                kind="workbook", path=str(cls.wb))

  @classmethod
  def tearDownClass(cls):
    try:
      cur = cls.conn.cursor()
      cur.execute(f"DELETE FROM {cls.da.TABLE} WHERE draft_id=%s", (cls.draft_id,))
      cls.conn.commit()
      cur.close()
    finally:
      try:
        cls.conn.close()
      except Exception:
        pass

  def test_the_list_answers_by_draft_with_timestamps(self):
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    body = self.client.get("/api/artifacts", query_string={"draft_id": self.draft_id}).get_json()
    self.assertEqual(body["draft_id"], self.draft_id)
    self.assertGreaterEqual(body["count"], 1)
    row = body["artifacts"][0]
    self.assertEqual(row["kind"], "workbook")
    self.assertEqual(row["planning_run_id"], "run_for_test")
    self.assertTrue(row["delivered_at"], "no timestamp - a fresh build must be "
                                         "distinguishable from a stale file")
    self.assertEqual(row["state"], "intact")

  def test_a_cell_can_be_read_by_draft_id(self):
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    body = self.client.get("/api/artifacts/workbook", query_string={
      "draft_id": self.draft_id, "sheet": "Checks", "cell": "B2"}).get_json()
    self.assertEqual(body["cell"], "B2")
    self.assertIn("formula", body)
    self.assertEqual(body["provenance"]["draft_id"], self.draft_id)
    self.assertEqual(body["provenance"]["state"], "intact")

  def test_reading_by_filename_says_provenance_is_unproven(self):
    """It still works - but it must not look like the same answer."""
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    body = self.client.get("/api/artifacts/workbook", query_string={
      "file": self.wb.name, "sheet": "Checks", "cell": "B2"}).get_json()
    self.assertEqual(body["provenance"]["state"], "unkeyed")

  def test_draft_id_and_file_together_are_refused(self):
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    res = self.client.get("/api/artifacts/workbook", query_string={
      "draft_id": self.draft_id, "file": self.wb.name, "sheet": "Checks", "cell": "B2"})
    self.assertEqual(res.status_code, 400, "two sources that can disagree must not both be accepted")

  def test_an_unrecorded_draft_says_so_rather_than_guessing(self):
    res = self.client.get("/api/artifacts/workbook", query_string={
      "draft_id": "no_such_draft_" + uuid.uuid4().hex[:8], "sheet": "Checks", "cell": "B2"})
    self.assertEqual(res.status_code, 404)
    body = res.get_json()
    self.assertIn("no workbook recorded", body["detail"])
    self.assertIn("2026-09-13", body["note"], "it must say records start from the change forward")

  def test_a_replaced_file_is_flagged_on_the_read(self):
    """The record's whole point: a path overwritten by a later run must not
    read back as if it were the recorded delivery."""
    if self.wb is None:
      self.skipTest("no workbooks on disk")
    stale = "test_" + uuid.uuid4().hex[:20]
    self.da.record(self.conn, draft_id=stale, kind="workbook", path=str(self.wb))
    cur = self.conn.cursor()
    cur.execute(f"UPDATE {self.da.TABLE} SET sha256=%s WHERE draft_id=%s",
                ("0" * 64, stale))
    self.conn.commit(); cur.close()
    try:
      body = self.client.get("/api/artifacts/workbook", query_string={
        "draft_id": stale, "sheet": "Checks", "cell": "B2"}).get_json()
      self.assertEqual(body["provenance"]["state"], "replaced")
      self.assertIn("no longer matches", body["provenance"]["warning"])
    finally:
      cur = self.conn.cursor()
      cur.execute(f"DELETE FROM {self.da.TABLE} WHERE draft_id=%s", (stale,))
      self.conn.commit(); cur.close()

  def test_discovery_names_draft_id_as_preferred(self):
    body = self.client.get("/api/artifacts/help").get_json()
    for route in body["routes"]:
      self.assertIn("draft_id", route["params"], f"{route['route']} does not offer draft_id")
    joined = json.dumps(body)
    self.assertIn("PREFERRED", joined)


if __name__ == "__main__":
  unittest.main(verbosity=2)
