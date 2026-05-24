"""Phase 9 P3.33 Phase 3 step 4b — ``post_intake_restructuring_log`` writer.

Hermetic tests for ``protocol.restructuring_log_table``. Exercises the
writer against an in-memory fake DB cursor so no MySQL is required.

Confirms:

  - ``ensure_restructuring_log_table`` emits ``CREATE TABLE IF NOT EXISTS``
    idempotently against the expected table name (spec §10.1).
  - ``log_restructure`` round-trips a confirmed Type-A row (spec §10.4 —
    every column matches the dataclass field).
  - Veto rows with ``applied_value != None`` are rejected (the invariant
    that no state changed on a veto).
  - Mismatched ``(failure_mode, reason_code)`` pairs are rejected at write
    time via the closed-enum partition.
  - Required identifying fields raise ``ValueError`` early.
  - String enum inputs are coerced; unknown reason codes raise.
  - Floor and META rows route via the correct step_type / applied_by.
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class _FakeCursor:
  def __init__(self, store):
    self._store = store
    self._dictionary = False
    self.lastrowid = None

  def execute(self, sql, params=None):
    sql_lower = sql.strip().lower()
    self._store["calls"].append((sql, params))
    if sql_lower.startswith("create table"):
      self._store["create_table_sql"] = sql
      return
    if sql_lower.startswith("insert"):
      self._store["rows"].append(params)
      self._store["next_id"] += 1
      self.lastrowid = self._store["next_id"]
      return
    if sql_lower.startswith("select"):
      self._store["last_select"] = (sql, params)
      return

  def fetchall(self):
    return list(self._store.get("rows", []))

  def close(self):
    return None


class _FakeConn:
  def __init__(self):
    self._store = {
      "calls": [], "rows": [], "next_id": 0, "committed": 0,
    }

  def cursor(self, dictionary=False):
    cur = _FakeCursor(self._store)
    cur._dictionary = bool(dictionary)
    return cur

  def commit(self):
    self._store["committed"] += 1


class _WriterBase(unittest.TestCase):
  def setUp(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      AppliedBy, ReasonCode, StepType,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.restructuring_log_table import (  # noqa: E501
      RestructureLogEntry, log_restructure, ensure_restructuring_log_table,
      RESTRUCTURING_LOG_TABLE_NAME,
    )
    self.FailureMode = FailureMode
    self.ReasonCode = ReasonCode
    self.AppliedBy = AppliedBy
    self.StepType = StepType
    self.RestructureLogEntry = RestructureLogEntry
    self.log_restructure = log_restructure
    self.ensure = ensure_restructuring_log_table
    self.table_name = RESTRUCTURING_LOG_TABLE_NAME
    self.conn = _FakeConn()

  def _good_entry(self):
    return self.RestructureLogEntry(
      draft_id="draft_abc",
      planning_run_id="run_001",
      failure_mode=self.FailureMode.VIABILITY_INVARIANT,
      cascade_tier="V1",
      cascade_tier_name="Cost-ratio tuning",
      reason_code=self.ReasonCode.VIABILITY_COST_RATIO_TUNED,
      section="drivers",
      field="expenses::Cost of Goods Sold",
      quarter_index=None,
      original_value=0.72,
      proposed_value=0.65,
      applied_value=0.65,
      step_type=self.StepType.TYPE_A,
      applied_by=self.AppliedBy.AMALGAMATED_GPT_CONFIRMED,
      evaluate_plan_round=2,
      worst_check_before="ebitda_positive_by_q11",
      worst_distance_before=-0.04,
      worst_check_after="ebitda_positive_by_q11",
      worst_distance_after=0.01,
    )


class EnsureTableTest(_WriterBase):
  def test_emits_create_table_if_not_exists(self) -> None:
    self.ensure(self.conn)
    self.assertIn("create_table_sql", self.conn._store)
    sql = self.conn._store["create_table_sql"]
    self.assertIn("CREATE TABLE IF NOT EXISTS", sql)
    self.assertIn(self.table_name, sql)
    self.assertEqual(self.table_name, "post_intake_restructuring_log")

  def test_idempotent_second_call(self) -> None:
    self.ensure(self.conn)
    self.ensure(self.conn)
    # Both calls hit the cursor; CREATE TABLE IF NOT EXISTS is idempotent.
    create_calls = [
      c for c in self.conn._store["calls"]
      if c[0].strip().lower().startswith("create table")
    ]
    self.assertEqual(len(create_calls), 2)

  def test_no_op_on_none_conn(self) -> None:
    # Defensive — should not raise.
    self.ensure(None)


class ConfirmedTypeARowTest(_WriterBase):
  def test_row_columns_match_spec(self) -> None:
    row_id = self.log_restructure(self.conn, self._good_entry())
    self.assertEqual(row_id, 1)
    rows = self.conn._store["rows"]
    self.assertEqual(len(rows), 1)
    p = rows[0]
    # Spec §10.1 column order is:
    # (draft_id, planning_run_id, failure_mode, cascade_tier,
    #  cascade_tier_name, reason_code, section, field, quarter_index,
    #  original_value, proposed_value, applied_value, step_type,
    #  applied_by, veto_reason, evaluate_plan_round,
    #  worst_check_before, worst_distance_before,
    #  worst_check_after, worst_distance_after)
    self.assertEqual(p[0], "draft_abc")
    self.assertEqual(p[1], "run_001")
    self.assertEqual(p[2], "viability_invariant")
    self.assertEqual(p[3], "V1")
    self.assertEqual(p[4], "Cost-ratio tuning")
    self.assertEqual(p[5], "VIABILITY_COST_RATIO_TUNED")
    self.assertEqual(p[6], "drivers")
    self.assertEqual(p[7], "expenses::Cost of Goods Sold")
    self.assertIsNone(p[8])
    self.assertEqual(p[9],  Decimal("0.72"))
    self.assertEqual(p[10], Decimal("0.65"))
    self.assertEqual(p[11], Decimal("0.65"))
    self.assertEqual(p[12], "A")
    self.assertEqual(p[13], "amalgamated_gpt_confirmed")
    self.assertIsNone(p[14])
    self.assertEqual(p[15], 2)
    self.assertEqual(p[16], "ebitda_positive_by_q11")
    self.assertEqual(p[17], Decimal("-0.04"))
    self.assertEqual(p[18], "ebitda_positive_by_q11")
    self.assertEqual(p[19], Decimal("0.01"))

  def test_ensure_table_runs_before_insert_by_default(self) -> None:
    self.log_restructure(self.conn, self._good_entry())
    sql_calls = [c[0].strip().lower() for c in self.conn._store["calls"]]
    # CREATE then INSERT.
    self.assertTrue(any(s.startswith("create table") for s in sql_calls))
    self.assertTrue(any(s.startswith("insert") for s in sql_calls))
    create_idx = next(i for i, s in enumerate(sql_calls) if s.startswith("create table"))
    insert_idx = next(i for i, s in enumerate(sql_calls) if s.startswith("insert"))
    self.assertLess(create_idx, insert_idx)

  def test_ensure_table_false_skips_ddl(self) -> None:
    self.log_restructure(self.conn, self._good_entry(), ensure_table=False)
    sql_calls = [c[0].strip().lower() for c in self.conn._store["calls"]]
    self.assertFalse(any(s.startswith("create table") for s in sql_calls))
    self.assertTrue(any(s.startswith("insert") for s in sql_calls))


class VetoRowTest(_WriterBase):
  def test_veto_with_applied_value_is_rejected(self) -> None:
    entry = self._good_entry()
    entry.applied_by = self.AppliedBy.AMALGAMATED_GPT_VETOED
    entry.veto_reason = "premium positioning; cohort target inapplicable"
    # applied_value still set -> writer must reject.
    with self.assertRaises(ValueError) as ctx:
      self.log_restructure(self.conn, entry)
    self.assertIn("veto rows must not carry", str(ctx.exception))

  def test_veto_with_none_applied_value_accepted_and_logs_reason(self) -> None:
    entry = self._good_entry()
    entry.applied_by = self.AppliedBy.AMALGAMATED_GPT_VETOED
    entry.applied_value = None
    entry.veto_reason = "premium positioning; cohort target inapplicable"
    row_id = self.log_restructure(self.conn, entry)
    self.assertEqual(row_id, 1)
    p = self.conn._store["rows"][0]
    self.assertIsNone(p[11])  # applied_value
    self.assertEqual(p[13], "amalgamated_gpt_vetoed")
    self.assertIn("premium positioning", p[14])

  def test_veto_reason_truncated_to_512(self) -> None:
    entry = self._good_entry()
    entry.applied_by = self.AppliedBy.AMALGAMATED_GPT_VETOED
    entry.applied_value = None
    entry.veto_reason = "x" * 1000
    row_id = self.log_restructure(self.conn, entry)
    self.assertEqual(row_id, 1)
    p = self.conn._store["rows"][0]
    self.assertEqual(len(p[14]), 512)


class ValidationFailuresTest(_WriterBase):
  def test_mismatched_mode_and_reason_code_rejected(self) -> None:
    entry = self._good_entry()
    entry.failure_mode = self.FailureMode.GROWTH_INVARIANT  # mismatch
    with self.assertRaises(ValueError) as ctx:
      self.log_restructure(self.conn, entry)
    self.assertIn("not valid for", str(ctx.exception))

  def test_missing_draft_id_raises(self) -> None:
    entry = self._good_entry()
    entry.draft_id = ""
    with self.assertRaises(ValueError):
      self.log_restructure(self.conn, entry)

  def test_missing_planning_run_id_raises(self) -> None:
    entry = self._good_entry()
    entry.planning_run_id = ""
    with self.assertRaises(ValueError):
      self.log_restructure(self.conn, entry)

  def test_missing_section_raises(self) -> None:
    entry = self._good_entry()
    entry.section = ""
    with self.assertRaises(ValueError):
      self.log_restructure(self.conn, entry)

  def test_unknown_reason_code_raises(self) -> None:
    with self.assertRaises(Exception):
      self.log_restructure(
        self.conn,
        draft_id="d", planning_run_id="r",
        failure_mode=self.FailureMode.VIABILITY_INVARIANT,
        cascade_tier="V1", cascade_tier_name="x",
        reason_code="NOT_A_REAL_CODE",
        section="drivers",
        step_type=self.StepType.TYPE_A,
        applied_by=self.AppliedBy.AMALGAMATED_GPT_CONFIRMED,
        evaluate_plan_round=1,
      )

  def test_passing_both_entry_and_kwargs_raises(self) -> None:
    with self.assertRaises(ValueError):
      self.log_restructure(self.conn, self._good_entry(), section="drivers")

  def test_no_args_raises(self) -> None:
    with self.assertRaises(ValueError):
      self.log_restructure(self.conn)


class StringEnumCoercionTest(_WriterBase):
  def test_string_inputs_coerced_via_kwargs(self) -> None:
    # Caller passed string values rather than enums — writer must coerce.
    row_id = self.log_restructure(
      self.conn,
      draft_id="draft_abc",
      planning_run_id="run_001",
      failure_mode="viability_invariant",
      cascade_tier="V1",
      cascade_tier_name="Cost-ratio tuning",
      reason_code="VIABILITY_COST_RATIO_TUNED",
      section="drivers",
      step_type="A",
      applied_by="amalgamated_gpt_confirmed",
      evaluate_plan_round=1,
      field="expenses::Cost of Goods Sold",
      original_value=0.72, proposed_value=0.65, applied_value=0.65,
    )
    self.assertEqual(row_id, 1)
    p = self.conn._store["rows"][0]
    self.assertEqual(p[2], "viability_invariant")
    self.assertEqual(p[5], "VIABILITY_COST_RATIO_TUNED")
    self.assertEqual(p[12], "A")
    self.assertEqual(p[13], "amalgamated_gpt_confirmed")


class FloorAndMetaRowsTest(_WriterBase):
  def test_floor_row_uses_floor_step_type(self) -> None:
    entry = self._good_entry()
    entry.cascade_tier = "V8"
    entry.cascade_tier_name = "Floor"
    entry.reason_code = self.ReasonCode.VIABILITY_FLOOR_APPLIED
    entry.step_type = self.StepType.FLOOR
    entry.applied_by = self.AppliedBy.DETERMINISTIC_FLOOR
    row_id = self.log_restructure(self.conn, entry)
    self.assertEqual(row_id, 1)
    p = self.conn._store["rows"][0]
    self.assertEqual(p[12], "floor")
    self.assertEqual(p[13], "deterministic_floor")

  def test_floor_primitive_row(self) -> None:
    entry = self._good_entry()
    entry.cascade_tier = "V8"
    entry.cascade_tier_name = "Floor primitive (apply_viability_floor)"
    entry.reason_code = self.ReasonCode.VIABILITY_FLOOR_PRIMITIVE
    entry.step_type = self.StepType.FLOOR
    entry.applied_by = self.AppliedBy.FLOOR_PRIMITIVE
    row_id = self.log_restructure(self.conn, entry)
    self.assertEqual(row_id, 1)

  def test_meta_escalation_row(self) -> None:
    row_id = self.log_restructure(
      self.conn,
      draft_id="draft_abc", planning_run_id="run_001",
      failure_mode=self.FailureMode.META_INVARIANT,
      cascade_tier="--",
      cascade_tier_name="meta_halt",
      reason_code=self.ReasonCode.META_ESCALATED,
      section="protocol",
      step_type=self.StepType.META,
      applied_by=self.AppliedBy.META_ESCALATION,
      evaluate_plan_round=4,
    )
    self.assertEqual(row_id, 1)
    p = self.conn._store["rows"][0]
    self.assertEqual(p[2], "meta_invariant")
    self.assertEqual(p[5], "META_ESCALATED")
    self.assertEqual(p[12], "meta")
    self.assertEqual(p[13], "meta_escalation")

  def test_budget_exhausted_row(self) -> None:
    row_id = self.log_restructure(
      self.conn,
      draft_id="draft_abc", planning_run_id="run_001",
      failure_mode=self.FailureMode.META_INVARIANT,
      cascade_tier="--",
      cascade_tier_name="budget_exhausted_floor_all",
      reason_code=self.ReasonCode.BUDGET_EXHAUSTED_FLOOR,
      section="protocol",
      step_type=self.StepType.META,
      applied_by=self.AppliedBy.META_ESCALATION,
      evaluate_plan_round=10,
    )
    self.assertEqual(row_id, 1)


class FetchHelperTest(_WriterBase):
  def test_fetch_returns_inserted_rows(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.restructuring_log_table import (  # noqa: E501
      fetch_restructuring_log,
    )
    self.log_restructure(self.conn, self._good_entry())
    self.log_restructure(self.conn, self._good_entry())
    rows = fetch_restructuring_log(
      self.conn, draft_id="draft_abc", planning_run_id="run_001"
    )
    self.assertEqual(len(rows), 2)

  def test_fetch_with_no_conn_returns_empty(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.restructuring_log_table import (  # noqa: E501
      fetch_restructuring_log,
    )
    rows = fetch_restructuring_log(
      None, draft_id="draft_abc", planning_run_id="run_001"
    )
    self.assertEqual(rows, [])


if __name__ == "__main__":
  unittest.main()
