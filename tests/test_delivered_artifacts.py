"""The delivery record: every file we hand a client is traceable to its run.

No conversation, no GPT. A file on disk, a row in the table, and the two
delivery sites proven to call the recorder.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))

try:
  from dotenv import load_dotenv  # type: ignore

  load_dotenv(str(ROOT / ".env"), override=False)
except Exception:
  pass


def _conn():
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore

  return get_mysql_connection()


class DeliveryRecordTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    from client_intake_and_finmo import delivered_artifacts as da  # type: ignore

    cls.da = da
    cls.conn = _conn()
    cls.draft_id = "test_" + uuid.uuid4().hex[:20]
    cls.tmp = tempfile.mkdtemp(prefix="delivered_artifacts_test_")

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

  def _file(self, name: str, content: bytes) -> str:
    path = os.path.join(self.tmp, name)
    with open(path, "wb") as fh:
      fh.write(content)
    return path

  def test_a_delivery_is_recorded_with_its_size_and_hash(self):
    path = self._file("plan.docx", b"x" * 4096)
    row_id = self.da.record(self.conn, draft_id=self.draft_id,
                            planning_run_id="run_abc", kind="plan", path=path)
    self.assertIsNotNone(row_id, "the delivery was not recorded")
    row = self.da.latest(self.conn, self.draft_id, kind="plan")
    self.assertIsNotNone(row)
    self.assertEqual(row["bytes"], 4096)
    self.assertEqual(row["planning_run_id"], "run_abc")
    self.assertEqual(row["name"], "plan.docx")
    self.assertEqual(len(row["sha256"]), 64)

  def test_both_artifacts_for_one_draft_come_back_newest_first(self):
    """Cowork's list question: both artifacts for a draft, with timestamps, so
    a fresh build is distinguishable from a stale file."""
    self.da.record(self.conn, draft_id=self.draft_id, planning_run_id="run_abc",
                   kind="workbook", path=self._file("book.xlsx", b"w" * 128))
    rows = self.da.for_draft(self.conn, self.draft_id)
    self.assertGreaterEqual(len(rows), 2)
    kinds = {r["kind"] for r in rows}
    self.assertIn("workbook", kinds)
    self.assertIn("plan", kinds)
    stamps = [r["delivered_at"] for r in rows]
    self.assertEqual(stamps, sorted(stamps, reverse=True), "not newest-first")

  def test_a_replaced_file_is_detected_by_its_hash(self):
    """Two workbooks for the same business is the case that started this. A
    path can be overwritten; the hash is what catches it."""
    path = self._file("replaceme.xlsx", b"first")
    self.da.record(self.conn, draft_id=self.draft_id, kind="workbook", path=path)
    row = self.da.latest(self.conn, self.draft_id, kind="workbook")
    self.assertEqual(self.da.verify(row)["state"], "intact")
    with open(path, "wb") as fh:
      fh.write(b"second, from a later run")
    self.assertEqual(self.da.verify(row)["state"], "replaced")

  def test_a_missing_file_is_reported_missing(self):
    path = self._file("gone.docx", b"here for now")
    self.da.record(self.conn, draft_id=self.draft_id, kind="plan", path=path)
    row = [r for r in self.da.for_draft(self.conn, self.draft_id, kind="plan")
           if r["name"] == "gone.docx"][0]
    os.remove(path)
    self.assertEqual(self.da.verify(row)["state"], "missing")

  def test_an_unattributable_delivery_is_refused(self):
    """A file with no draft id is exactly the thing this table exists to stop;
    it is refused and logged rather than written as an orphan row."""
    path = self._file("orphan.xlsx", b"x")
    self.assertIsNone(self.da.record(self.conn, draft_id="", kind="workbook", path=path))

  def test_a_bad_kind_is_refused(self):
    path = self._file("odd.txt", b"x")
    self.assertIsNone(self.da.record(self.conn, draft_id=self.draft_id,
                                     kind="screenshot", path=path))

  def test_recording_never_raises_on_a_missing_file(self):
    """Bookkeeping must not undo a delivery that already happened."""
    self.da.record(self.conn, draft_id=self.draft_id, kind="plan",
                   path=os.path.join(self.tmp, "never_written.docx"))


class DeliverySitesCallTheRecorderTests(unittest.TestCase):
  """Source-level: both sites that put a file in front of a client record it."""

  def test_the_workbook_export_records_its_delivery(self):
    src = (ROOT / "client_statements_output_excel" / "export_client_workbook.py").read_text(encoding="utf-8")
    self.assertIn("_record_delivery(", src)
    self.assertIn('kind="workbook"', src)

  def test_the_workbook_export_records_only_a_real_delivery(self):
    """An export into a scratch output_dir (the audit harnesses) is not a
    delivery and must leave no row."""
    src = (ROOT / "client_statements_output_excel" / "export_client_workbook.py").read_text(encoding="utf-8")
    self.assertIn("Path(target_dir).resolve() != Path(DEFAULT_OUTPUT_DIR).resolve()", src)

  def test_the_plan_ship_records_the_plan_and_the_render_report(self):
    src = (ROOT / "scripts" / "writing_phase_v2_run.py").read_text(encoding="utf-8")
    self.assertIn("_record_plan_delivery(", src)
    self.assertIn('kind="plan"', src)
    self.assertIn('kind="render_report"', src)

  def test_the_plan_is_recorded_only_after_every_gate_passed(self):
    """The 09-11 rule: a plan enters the ship folder only on a clean run. The
    record must sit with the ship, not before it."""
    src = (ROOT / "scripts" / "writing_phase_v2_run.py").read_text(encoding="utf-8")
    ship = src.index("_ship_to_plans(rendered_to)")
    record = src.index("_record_plan_delivery(", ship)
    between = src[ship:record]
    self.assertNotIn("if passed", between,
                     "the record must be inside the same passed branch as the ship")


if __name__ == "__main__":
  unittest.main(verbosity=2)
