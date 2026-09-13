"""A failed build is recorded, including one that died before the run existed.

Sorrel & Dunne 691a4763 is the case: the run threw inside
prepare_initial_grid_for_draft, before begin_planning_run made a row, so the
draft's planning_* columns kept saying "pending"; and the `status="failed"`
the snapshot did write was overwritten two minutes later when the client
carried on talking. No conversation is needed to prove any of this - a row, a
draft, and the handler's own source.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

try:
  from dotenv import load_dotenv  # type: ignore

  load_dotenv(str(ROOT / ".env"), override=False)
except Exception:
  pass


def _conn():
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore

  return get_mysql_connection()


class FailureRecordTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    from client_intake_and_finmo import system_run_failures as srf  # type: ignore

    cls.srf = srf
    cls.conn = _conn()
    cls.draft_id = "test_" + uuid.uuid4().hex[:20]

  @classmethod
  def tearDownClass(cls):
    try:
      cur = cls.conn.cursor()
      cur.execute(f"DELETE FROM {cls.srf.TABLE} WHERE draft_id=%s", (cls.draft_id,))
      cls.conn.commit()
      cur.close()
    finally:
      try:
        cls.conn.close()
      except Exception:
        pass

  def test_a_failure_before_the_run_row_exists_is_recorded(self):
    """The gap this closes: no planning_run_id, and it still lands."""
    row_id = self.srf.record(
      self.conn, draft_id=self.draft_id,
      detail="balance_sheet_stub_continuity_failed: Other Equity 610000 empty in live quarters",
      stage="prepare_initial_grid_for_draft", run_existed=False)
    self.assertIsNotNone(row_id)
    row = self.srf.latest(self.conn, self.draft_id)
    self.assertEqual(row["run_existed"], 0)
    self.assertIsNone(row["planning_run_id"])
    self.assertIn("stub_continuity", row["detail"])
    self.assertEqual(row["stage"], "prepare_initial_grid_for_draft")

  def test_a_failure_with_a_run_row_records_the_run(self):
    self.srf.record(self.conn, draft_id=self.draft_id,
                    detail="revenue_driver_formula_contract_failed: 13 quarters",
                    planning_run_id="59870b997aa04b49bb053db36bbef0c8",
                    stage="quarter_grid_ready", run_existed=True)
    row = self.srf.latest(self.conn, self.draft_id)
    self.assertEqual(row["run_existed"], 1)
    self.assertEqual(row["planning_run_id"], "59870b997aa04b49bb053db36bbef0c8")

  def test_the_history_is_append_only_and_newest_first(self):
    """Both of Sorrel's deaths are still readable, in order. A draft column
    would hold only the last one - and not even that, once the client talks."""
    rows = self.srf.for_draft(self.conn, self.draft_id)
    self.assertGreaterEqual(len(rows), 2)
    stamps = [r["occurred_at"] for r in rows]
    self.assertEqual(stamps, sorted(stamps, reverse=True))
    details = " ".join(str(r["detail"]) for r in rows)
    self.assertIn("stub_continuity", details)
    self.assertIn("revenue_driver_formula_contract_failed", details)

  def test_an_unattributable_failure_is_refused(self):
    self.assertIsNone(self.srf.record(self.conn, draft_id="", detail="boom"))

  def test_recording_never_raises(self):
    """The request is already failing; its error belongs to the caller."""
    self.srf.record(self.conn, draft_id=self.draft_id, detail="x" * 200000)


class TheHandlerRecordsOnEveryFailurePathTests(unittest.TestCase):
  """Source-level, because the alternative is driving a real failed build."""

  @classmethod
  def setUpClass(cls):
    cls.src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(
      encoding="utf-8-sig")

  def test_both_failure_branches_record(self):
    self.assertEqual(self.src.count("_record_system_run_failure("), 3,
                     "expected the definition plus a call in each of the two "
                     "failure branches")

  def test_the_columns_are_stamped_only_when_no_run_row_exists(self):
    """With a run row, clear_planning_run_action owns those columns; writing
    them twice from two places is how they drift apart."""
    start = self.src.index("def _record_system_run_failure(")
    body = self.src[start:self.src.index("\ndef ", start + 10)]
    self.assertIn("if run_row:", body)
    self.assertIn("return   # clear_planning_run_action owns the columns", body)
    self.assertIn("planning_status='failed'", body)
    self.assertIn("planning_run_status='failed'", body)
    self.assertIn("planning_failure_reason=%s", body)

  def test_the_append_only_row_is_written_before_the_columns(self):
    """The row is the durable record; the columns are a view a later turn may
    legitimately overwrite. If the row write were second, a failure in it
    would leave only the overwritable half."""
    start = self.src.index("def _record_system_run_failure(")
    body = self.src[start:self.src.index("\ndef ", start + 10)]
    self.assertLess(body.index("_srf.record("), body.index("UPDATE intake_consult_drafts"))


if __name__ == "__main__":
  unittest.main(verbosity=2)
