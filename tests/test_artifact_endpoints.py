"""The artifact routes, exercised against the REAL delivered files on disk.

No conversation, no GPT, no persona: these routes read files. The proof that
they work is that they read the files this app actually shipped - the newest
delivered workbook's Checks!B2, a real written plan's text - and that they
refuse everything outside the two roots.
"""
from __future__ import annotations

import os
import sys
import unittest
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


if __name__ == "__main__":
  unittest.main(verbosity=2)
