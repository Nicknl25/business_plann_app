"""Seed-parity guard for the pass-through-sourced Literals in
``finmo_model_input_contract.py`` (P3.41 NexGen E2E iter 2).

The Contract 1 ``ValueKind`` + per-section ``*InputSemantics``
Literals are pass-through-sourced: ``_revenue_input_semantics``
and ``_simple_input_semantics`` at
``python/client_intake_and_finmo/finmo_bridge.py:256-320`` first
consult the mapping table (``_mapping_formula_contract_for_lever``)
and return the lever's ``value_kind`` + ``input_semantics``
VERBATIM if present; only when the mapping table has no row for
the lever do the hardcoded fallback returns fire.

The authoritative producer vocabulary is therefore the UNION of:
  (a) the live ``post_intak_mapping_lookup`` seed (active rows),
      grouped by section via the ``lever_id`` prefix; and
  (b) the finmo_bridge fallback returns at lines 265-320.

This file's tests assert that each affected Literal covers
(a) ∪ (b). When the seed gains a new ``value_kind`` /
``input_semantics`` value or finmo_bridge gains a new fallback
branch, CI fails LOUDLY with a message naming the missing
value(s) instead of letting the contract silently break on a
future E2E run.

The DB-half tests skip cleanly when no MySQL connection is
configured (CI workers without DB credentials, fresh-clone
contributors). The source-parse half always runs.

This guard is the key piece of the P3.41 iter-2 fix -- the
Literal completion itself is mechanical; the parity test is what
makes the contract enforced-in-sync with the seed going forward.
"""

from __future__ import annotations

import os
import re
import sys
import typing
import unittest
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Set


HERE = Path(__file__).resolve().parent
PYTHON_ROOT = HERE.parent / "python"
if str(PYTHON_ROOT) not in sys.path:
  sys.path.insert(0, str(PYTHON_ROOT))


from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  BalanceSheetInputSemantics,
  ExpenseInputSemantics,
  RevenueInputSemantics,
  ScheduleInputSemantics,
  ValueKind,
)


_FINMO_BRIDGE_PATH = PYTHON_ROOT / "client_intake_and_finmo" / "finmo_bridge.py"
_FALLBACK_SCAN_RANGE = (255, 322)  # inclusive line range covering
#                                    _revenue_input_semantics + _simple_input_semantics


def _literal_args(literal_type) -> FrozenSet[str]:
  return frozenset(str(arg) for arg in typing.get_args(literal_type))


def _scan_finmo_bridge_fallbacks() -> Dict[str, Set[str]]:
  """Parse finmo_bridge.py:255-322 for hardcoded {value_kind,
  input_semantics} returns. Returns:
    {
      "value_kind": {...},
      "input_semantics": {...},
    }

  The fallback returns are inside ``_revenue_input_semantics``
  and ``_simple_input_semantics``. We scan literal string
  assignments of the form ``"value_kind": "<value>"`` and
  ``"input_semantics": "<value>"``."""
  text = _FINMO_BRIDGE_PATH.read_text(encoding="utf-8")
  lines = text.splitlines()
  start, end = _FALLBACK_SCAN_RANGE
  region = "\n".join(lines[start - 1 : end])
  vk_pattern = re.compile(r'"value_kind"\s*:\s*"([^"]+)"')
  is_pattern = re.compile(r'"input_semantics"\s*:\s*"([^"]+)"')
  return {
    "value_kind": set(vk_pattern.findall(region)),
    "input_semantics": set(is_pattern.findall(region)),
  }


def _scan_finmo_bridge_fallbacks_by_section() -> Dict[str, Set[str]]:
  """Per-section input_semantics fallback scan. The 4 sections
  map to function branches in finmo_bridge:
    - revenue:       lines 256-270 (separate _revenue_input_semantics)
    - expenses:      lines 282-295 (branch) + line 320 (function-wide
                     catch-all when no label matches)
    - balance_sheet: lines 296-307 (branch) + line 320
    - schedules:     lines 308-320 (branch includes in-branch
                     catch-all at line 319 + function-wide at line 320)
  Returns a per-section set of all input_semantics literal values
  that could be emitted by the fallback path."""
  text = _FINMO_BRIDGE_PATH.read_text(encoding="utf-8")
  lines = text.splitlines()
  is_pattern = re.compile(r'"input_semantics"\s*:\s*"([^"]+)"')
  ranges: Dict[str, list] = {
    "revenue": [(256, 270)],
    "expenses": [(282, 295), (320, 320)],
    "balance_sheet": [(296, 307), (320, 320)],
    "schedules": [(308, 320)],
  }
  out: Dict[str, Set[str]] = {}
  for section, slices in ranges.items():
    found: Set[str] = set()
    for lo, hi in slices:
      region = "\n".join(lines[lo - 1 : hi])
      found.update(is_pattern.findall(region))
    out[section] = found
  return out


def _try_db_connect():
  """Attempt MySQL connection from .env. Returns connection or
  None if not available. Skipping tests on None is the desired
  behavior on workstations / CI without DB credentials."""
  try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
  except Exception:
    pass
  host = os.getenv("MYSQL_HOST")
  user = os.getenv("MYSQL_USER")
  database = os.getenv("MYSQL_DB")
  if not (host and user and database):
    return None
  try:
    import mysql.connector  # type: ignore

    return mysql.connector.connect(
      host=host,
      user=user,
      password=os.getenv("MYSQL_PASSWORD") or "",
      database=database,
      port=int(os.getenv("MYSQL_PORT") or 3306),
    )
  except Exception:
    return None


def _query_seed_vocab(conn, column: str) -> Set[str]:
  cur = conn.cursor()
  try:
    cur.execute(
      f"SELECT DISTINCT {column} FROM post_intak_mapping_lookup "
      f"WHERE mapping_status = 'active'"
    )
    return {str(row[0]).strip().lower() for row in cur.fetchall() if row[0]}
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _query_seed_vocab_by_section(conn, column: str) -> Dict[str, Set[str]]:
  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      SELECT SUBSTRING_INDEX(lever_id, '::', 1) AS section,
             {column}
      FROM post_intak_mapping_lookup
      WHERE mapping_status = 'active'
      """
    )
    out: Dict[str, Set[str]] = {}
    for section, value in cur.fetchall():
      if not section or not value:
        continue
      out.setdefault(str(section).strip().lower(), set()).add(
        str(value).strip().lower()
      )
    return out
  finally:
    try:
      cur.close()
    except Exception:
      pass


class ValueKindLiteralSeedParityTest(unittest.TestCase):
  """Assert the ``ValueKind`` Literal covers seed ∪ fallback."""

  def test_fallback_vocabulary_subset_of_literal(self) -> None:
    """Source-parse half: every finmo_bridge fallback ``value_kind``
    must be in the Literal. Runs without DB."""
    fallback = _scan_finmo_bridge_fallbacks()["value_kind"]
    literal_vocab = _literal_args(ValueKind)
    missing = fallback - literal_vocab
    self.assertFalse(
      missing,
      f"finmo_bridge emits value_kinds not covered by the "
      f"ValueKind Literal: {sorted(missing)}. Add them to "
      f"finmo_model_input_contract.py:ValueKind.",
    )

  def test_seed_vocabulary_subset_of_literal(self) -> None:
    """DB-half: every distinct ``value_kind`` in
    ``post_intak_mapping_lookup`` (active rows) must be in the
    Literal. Skipped cleanly if no DB."""
    conn = _try_db_connect()
    if conn is None:
      self.skipTest("MySQL not configured -- skipping live seed parity")
    try:
      seed = _query_seed_vocab(conn, "value_kind")
    finally:
      try:
        conn.close()
      except Exception:
        pass
    literal_vocab = _literal_args(ValueKind)
    missing = seed - literal_vocab
    self.assertFalse(
      missing,
      f"post_intak_mapping_lookup seeds value_kinds not covered "
      f"by the ValueKind Literal: {sorted(missing)}. Add them to "
      f"finmo_model_input_contract.py:ValueKind.",
    )


class InputSemanticsLiteralSeedParityTest(unittest.TestCase):
  """Assert each per-section ``*InputSemantics`` Literal covers
  its section's seed ∪ fallback."""

  _SECTION_LITERALS = {
    "revenue": RevenueInputSemantics,
    "expenses": ExpenseInputSemantics,
    "balance_sheet": BalanceSheetInputSemantics,
    "schedules": ScheduleInputSemantics,
  }

  def test_fallback_vocabulary_subset_of_per_section_literals(self) -> None:
    """Source-parse half: per-section fallback returns must be in
    each section's Literal."""
    fallback_by_section = _scan_finmo_bridge_fallbacks_by_section()
    for section, literal in self._SECTION_LITERALS.items():
      fallback = fallback_by_section.get(section, set())
      literal_vocab = _literal_args(literal)
      missing = fallback - literal_vocab
      self.assertFalse(
        missing,
        f"finmo_bridge {section} fallback emits input_semantics "
        f"not covered by the section Literal: {sorted(missing)}. "
        f"Add them to finmo_model_input_contract.py:"
        f"{literal.__name__ if hasattr(literal, '__name__') else section}"
        f"InputSemantics.",
      )

  def test_seed_vocabulary_subset_of_per_section_literals(self) -> None:
    """DB-half: per-section seed vocabulary must be in each
    section's Literal. Skipped cleanly if no DB."""
    conn = _try_db_connect()
    if conn is None:
      self.skipTest("MySQL not configured -- skipping live seed parity")
    try:
      seed_by_section = _query_seed_vocab_by_section(conn, "input_semantics")
    finally:
      try:
        conn.close()
      except Exception:
        pass
    for section, literal in self._SECTION_LITERALS.items():
      seed = seed_by_section.get(section, set())
      literal_vocab = _literal_args(literal)
      missing = seed - literal_vocab
      self.assertFalse(
        missing,
        f"post_intak_mapping_lookup {section} rows seed "
        f"input_semantics not covered by the section Literal: "
        f"{sorted(missing)}. Add them to "
        f"finmo_model_input_contract.py:{section}InputSemantics.",
      )


class LiteralCompositionDocumentaryTest(unittest.TestCase):
  """Pin the current member counts so accidental over-narrowing
  (someone deleting a value from the Literal) is caught even
  before E2E fires."""

  def test_value_kind_has_at_least_seed_plus_fallback_count(self) -> None:
    # 5 seed + 1 fallback-only ('direct_number') = 6 minimum.
    self.assertGreaterEqual(
      len(_literal_args(ValueKind)), 6,
      "ValueKind Literal must cover at least the 5 seed values "
      "+ direct_number fallback = 6 minimum.",
    )

  def test_each_input_semantics_literal_has_at_least_one_member(self) -> None:
    for literal in (
      RevenueInputSemantics,
      ExpenseInputSemantics,
      BalanceSheetInputSemantics,
      ScheduleInputSemantics,
    ):
      self.assertGreater(
        len(_literal_args(literal)), 0,
        f"{literal!r} must be non-empty.",
      )


if __name__ == "__main__":
  unittest.main()
