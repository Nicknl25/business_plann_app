"""`writing_phase_rule_lookup` — the rules as DB rows (2026-08-30).

WHY THE RULES LIVE IN A TABLE AS WELL AS IN CODE. Each row carries BOTH the
instruction GPT is given (`prompt_instruction`) AND the enforcement that holds
it (`check_name`, `failure_code`, `enforcement`). They are the same row, so
they cannot drift apart. A rule written into a prompt string and checked by
separate code drifts the first time someone edits one and not the other; this
is the shape post_intake_gpt_contract_lookup has used for the payroll contract
since it was built (157 rows, `prompt_required_instruction` beside
`validation_kind`/`min_items`/`failure_code`).

THE LESSON THAT SHAPES THE VERIFY STEP. That payroll contract row sat INERT
through four live reruns on 2026-08-28: the DB said `allow_empty=0` while the
code said `allow_empty=True`, because `_ensure_gpt_contract_lookup_table()` had
never run. Seeding is therefore not enough - `verify_rule_lookup_live()` reads
the table back and reports disagreement, and the writing phase refuses to run
against a table that disagrees with rules.py.

Nothing here generates a document. It creates a table, seeds it from the single
door, and reads it back.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

from . import rules as R

TABLE_NAME = "writing_phase_rule_lookup"

_READY = False
_LOCK = threading.Lock()


def ensure_rule_lookup_table(conn) -> None:
  """Create the table if absent. Idempotent, and cheap after the first call."""
  global _READY
  if _READY:
    return
  with _LOCK:
    if _READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          rule_set_version VARCHAR(64) NOT NULL,
          rule_id VARCHAR(8) NOT NULL,
          title VARCHAR(128) NOT NULL,
          enforcement VARCHAR(16) NOT NULL,
          check_name VARCHAR(128) NULL,
          failure_code VARCHAR(128) NULL,
          mechanism TEXT NOT NULL,
          cannot_enforce TEXT NULL,
          prompt_instruction TEXT NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uq_rule (rule_set_version, rule_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
      )
      conn.commit()
      _READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def seed_rule_lookup(conn) -> int:
  """Push rules.py into the table. rules.py is the source of truth; the table
  is its serving copy, never the other way round."""
  ensure_rule_lookup_table(conn)
  cur = conn.cursor()
  written = 0
  try:
    for rule in R.WRITING_RULES:
      cur.execute(
        f"""
        INSERT INTO {TABLE_NAME}
          (rule_set_version, rule_id, title, enforcement, check_name,
           failure_code, mechanism, cannot_enforce, prompt_instruction, active)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
        ON DUPLICATE KEY UPDATE
          title=VALUES(title), enforcement=VALUES(enforcement),
          check_name=VALUES(check_name), failure_code=VALUES(failure_code),
          mechanism=VALUES(mechanism), cannot_enforce=VALUES(cannot_enforce),
          prompt_instruction=VALUES(prompt_instruction), active=1
        """,
        (R.RULE_SET_VERSION, rule["id"], rule["title"], rule["enforcement"],
         rule.get("check"), rule.get("failure_code"), rule["mechanism"],
         rule.get("cannot_enforce"), rule["prompt_instruction"]),
      )
      written += 1
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return written


def read_rule_lookup(conn) -> List[Dict[str, Any]]:
  ensure_rule_lookup_table(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""SELECT rule_id, title, enforcement, check_name, failure_code,
                 mechanism, cannot_enforce, prompt_instruction
          FROM {TABLE_NAME}
          WHERE rule_set_version=%s AND active=1
          ORDER BY rule_id""",
      (R.RULE_SET_VERSION,),
    )
    return list(cur.fetchall())
  finally:
    try:
      cur.close()
    except Exception:
      pass


def verify_rule_lookup_live(conn) -> Tuple[bool, List[str]]:
  """Read the table back and compare it field by field with rules.py.

  This exists because of 2026-08-28: a contract row can be seeded in code and
  still be wrong in the database, and four live runs went by before anyone
  read the row. The writing phase must call this and REFUSE TO RUN on
  disagreement - a mismatch is not a warning, it means the instruction GPT
  receives is not the rule being enforced.
  """
  problems: List[str] = []
  try:
    rows = {r["rule_id"]: r for r in read_rule_lookup(conn)}
  except Exception as exc:
    # The CoInitialize shape: could not verify is NOT verified.
    return False, ["rule lookup could not be read: %s" % str(exc)[:160]]

  for rule in R.WRITING_RULES:
    rid = rule["id"]
    row = rows.get(rid)
    if row is None:
      problems.append("%s missing from the table (seeder has not run)" % rid)
      continue
    for code_key, db_key in (("title", "title"), ("enforcement", "enforcement"),
                             ("check", "check_name"), ("failure_code", "failure_code"),
                             ("mechanism", "mechanism"),
                             ("prompt_instruction", "prompt_instruction")):
      want, got = rule.get(code_key), row.get(db_key)
      if (want or None) != (got or None):
        problems.append("%s.%s differs: code=%r db=%r"
                        % (rid, db_key, str(want)[:60], str(got)[:60]))
  for extra in sorted(set(rows) - {r["id"] for r in R.WRITING_RULES}):
    problems.append("%s present in the table but not in rules.py" % extra)
  return (not problems), problems
