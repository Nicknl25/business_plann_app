"""Shared issue database for autonomous persona testing.

The Cowork testing app (persona driver) DETECTS issues and writes them here;
this side owns the schema, the recurrence/resolution accounting, and the
dashboard. Lives in the same MySQL store as the run_vitals_* tables so an
issue joins to its run's backend truth natively (same draft_id, one join).

Three tables
------------
- ``issues`` — the registry: ONE row per unique issue, keyed by
  ``signature``. This table is the deliberate UPDATE exception to the
  project's INSERT-only discipline: it is a REGISTRY (current state of a
  known issue), not a log. Every state change it undergoes is mirrored by an
  INSERT-only audit row in ``issue_resolution_events``, so history is never
  lost to an UPDATE.
- ``issue_occurrences`` — INSERT-only: one row per sighting of an issue on a
  specific run (draft_id + turn/section + what-happened/what-should-have).
- ``issue_resolution_events`` — INSERT-only audit of the resolution-sensing:
  exercised-clean ticks, recurrences, reopens, and the resolution verdicts.

Signature (the crux of resolution-sensing)
------------------------------------------
``signature`` is the stable identity of "this same issue" across runs.
Authored by the reporter (Cowork), following the documented convention
(docs/issue_database.md): ``<category>:<locus...>`` built ONLY from stable
coordinates — section, stage, field/question id, failure class, business
slug. NEVER from run-minted tokens (draft_id, timestamps) or verbatim GPT
text (varies run to run). The registry upserts on it; recurrence == a new
occurrence arriving under an existing signature.

Resolution-sensing honesty (resolution_class)
---------------------------------------------
- ``hard`` (default for hard_break / verdict / flow): deterministically
  resolvable. When a later run EXERCISES the issue's path (probe_json
  predicate against that run's vitals) and the failure does not recur, that
  is an exercised-clean tick; at ``hard_clean_threshold`` consecutive clean
  exercises the issue is resolved with resolution_confidence='confirmed'.
- ``soft`` (default for experience): NOT deterministically resolvable — GPT
  phrasing varies run to run, so absence is weak evidence. Soft issues can
  only ever reach resolution_basis='not_seen_n_runs' with
  resolution_confidence='observational', after ``soft_runs_threshold``
  exercised runs without a recurrence. The schema forbids 'confirmed' on a
  soft issue by construction (only the hard path writes it).

Any recurrence resets both counters; a recurrence after resolution flips the
issue to status='recurring' and increments reopened_count.

Write contract style: report_issue() FAILS LOUDLY on a bad category /
severity / status vocabulary — a typo in the write path must surface
immediately, not create a phantom taxonomy.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


ISSUES_TABLE = "issues"
OCCURRENCES_TABLE = "issue_occurrences"
RESOLUTION_EVENTS_TABLE = "issue_resolution_events"

CATEGORIES = ("hard_break", "flow", "verdict", "experience")
SEVERITIES = ("blocker", "major", "minor", "note")
STATUSES = ("open", "resolved", "recurring")
RESOLUTION_CLASSES = ("hard", "soft")
RESOLUTION_BASES = ("retested_clean", "not_seen_n_runs", "manual")
RESOLUTION_CONFIDENCES = ("confirmed", "observational")

# Category -> default resolution class. flow defaults to hard (loops /
# dead-ends are routing logic, deterministically re-testable); the reporter
# may override to soft for phrasing-dependent flow issues.
DEFAULT_RESOLUTION_CLASS = {
  "hard_break": "hard",
  "verdict": "hard",
  "flow": "hard",
  "experience": "soft",
}

DEFAULT_HARD_CLEAN_THRESHOLD = 1
DEFAULT_SOFT_RUNS_THRESHOLD = 5

_CREATE_ISSUES_SQL = f"""
CREATE TABLE IF NOT EXISTS {ISSUES_TABLE} (
  issue_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  signature VARCHAR(191) NOT NULL,
  category VARCHAR(24) NOT NULL,
  resolution_class VARCHAR(8) NOT NULL,
  severity VARCHAR(12) NOT NULL,
  title VARCHAR(255) NOT NULL DEFAULT '',
  status VARCHAR(16) NOT NULL DEFAULT 'open',
  first_seen_at DATETIME(6) NOT NULL,
  last_seen_at DATETIME(6) NOT NULL,
  occurrence_count INT NOT NULL DEFAULT 1,
  reopened_count INT NOT NULL DEFAULT 0,
  clean_exercise_count INT NOT NULL DEFAULT 0,
  runs_since_last_seen INT NOT NULL DEFAULT 0,
  resolved_detected_at DATETIME(6) NULL,
  resolution_basis VARCHAR(32) NULL,
  resolution_confidence VARCHAR(16) NULL,
  probe_json LONGTEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uniq_signature (signature),
  KEY ix_issues_status (status),
  KEY ix_issues_category (category),
  KEY ix_issues_last_seen (last_seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_OCCURRENCES_SQL = f"""
CREATE TABLE IF NOT EXISTS {OCCURRENCES_TABLE} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  issue_id BIGINT UNSIGNED NOT NULL,
  signature VARCHAR(191) NOT NULL,
  draft_id VARCHAR(64) NOT NULL DEFAULT '',
  planning_run_id VARCHAR(64) NOT NULL DEFAULT '',
  business_name VARCHAR(255) NULL,
  persona VARCHAR(64) NOT NULL DEFAULT '',
  turn_index INT NULL,
  section VARCHAR(32) NOT NULL DEFAULT '',
  stage VARCHAR(64) NOT NULL DEFAULT '',
  severity VARCHAR(12) NOT NULL DEFAULT '',
  observed LONGTEXT NULL,
  expected LONGTEXT NULL,
  evidence_json LONGTEXT NULL,
  source VARCHAR(16) NOT NULL DEFAULT 'cowork',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_occ_issue (issue_id, created_at),
  KEY ix_occ_signature (signature),
  KEY ix_occ_draft (draft_id),
  KEY ix_occ_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_RESOLUTION_EVENTS_SQL = f"""
CREATE TABLE IF NOT EXISTS {RESOLUTION_EVENTS_TABLE} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  issue_id BIGINT UNSIGNED NOT NULL,
  signature VARCHAR(191) NOT NULL,
  draft_id VARCHAR(64) NOT NULL DEFAULT '',
  event_type VARCHAR(32) NOT NULL,
  detail_json LONGTEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_res_issue (issue_id, created_at),
  KEY ix_res_type (event_type),
  KEY ix_res_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_tables_ready = False


def ensure_tables(conn) -> None:
  global _tables_ready
  if _tables_ready:
    return
  cur = conn.cursor()
  try:
    cur.execute(_CREATE_ISSUES_SQL)
    cur.execute(_CREATE_OCCURRENCES_SQL)
    cur.execute(_CREATE_RESOLUTION_EVENTS_SQL)
    conn.commit()
    _tables_ready = True
  finally:
    cur.close()


def _require(value: str, allowed: tuple, field: str) -> str:
  v = str(value or "").strip()
  if v not in allowed:
    raise ValueError(f"{field} must be one of {allowed}, got {value!r}")
  return v


def _json_or_none(value: Any) -> Optional[str]:
  if value is None:
    return None
  if isinstance(value, str):
    return value
  return json.dumps(value, ensure_ascii=False, default=str)


def _insert_resolution_event(
  cur, *, issue_id: int, signature: str, draft_id: str,
  event_type: str, detail: Any = None,
) -> None:
  cur.execute(
    f"""
    INSERT INTO {RESOLUTION_EVENTS_TABLE}
      (issue_id, signature, draft_id, event_type, detail_json)
    VALUES (%s, %s, %s, %s, %s)
    """,
    (issue_id, signature, draft_id, event_type, _json_or_none(detail)),
  )


def _fetch_issue(cur, signature: str) -> Optional[Dict[str, Any]]:
  cur.execute(
    f"SELECT * FROM {ISSUES_TABLE} WHERE signature = %s", (signature,)
  )
  row = cur.fetchone()
  if row is None:
    return None
  cols = [d[0] for d in cur.description]
  return dict(zip(cols, row))


# ----------------------------------------------------------------------------
# Write path (Cowork's contract; also used by the HTTP endpoint).
# ----------------------------------------------------------------------------

def report_issue(
  conn,
  *,
  signature: str,
  category: str,
  severity: str,
  observed: str,
  expected: str,
  draft_id: str = "",
  planning_run_id: str = "",
  business_name: str = "",
  persona: str = "",
  turn_index: Optional[int] = None,
  section: str = "",
  stage: str = "",
  title: str = "",
  resolution_class: str = "",
  probe: Any = None,
  evidence: Any = None,
  source: str = "cowork",
) -> Dict[str, Any]:
  """Report one sighting of an issue. Upserts the registry row keyed by
  ``signature`` and INSERTs the occurrence. Returns the resulting registry
  state plus flags (is_new, reopened).

  Vocabulary violations raise — the write contract fails loudly.
  """
  signature = str(signature or "").strip()
  if not signature or len(signature) > 191:
    raise ValueError("signature is required (non-empty, <=191 chars)")
  category = _require(category, CATEGORIES, "category")
  severity = _require(severity, SEVERITIES, "severity")
  rclass = str(resolution_class or "").strip() or DEFAULT_RESOLUTION_CLASS[category]
  rclass = _require(rclass, RESOLUTION_CLASSES, "resolution_class")
  observed = str(observed or "").strip()
  expected = str(expected or "").strip()
  if not observed or not expected:
    raise ValueError("observed and expected are both required (what the app "
                     "did vs what should have happened)")

  ensure_tables(conn)
  cur = conn.cursor()
  try:
    existing = _fetch_issue(cur, signature)
    is_new = existing is None
    reopened = False
    if is_new:
      cur.execute(
        f"""
        INSERT INTO {ISSUES_TABLE}
          (signature, category, resolution_class, severity, title, status,
           first_seen_at, last_seen_at, occurrence_count, probe_json)
        VALUES (%s, %s, %s, %s, %s, 'open', NOW(6), NOW(6), 1, %s)
        """,
        (signature, category, rclass, severity,
         str(title or "")[:255], _json_or_none(probe)),
      )
      issue_id = cur.lastrowid
    else:
      issue_id = int(existing["issue_id"])
      reopened = str(existing["status"]) == "resolved"
      next_status = "recurring" if reopened else str(existing["status"])
      # A sighting resets BOTH resolution counters and (on a resolved issue)
      # clears the resolution verdict — the audit rows keep the history.
      cur.execute(
        f"""
        UPDATE {ISSUES_TABLE}
        SET status = %s,
            last_seen_at = NOW(6),
            occurrence_count = occurrence_count + 1,
            reopened_count = reopened_count + %s,
            clean_exercise_count = 0,
            runs_since_last_seen = 0,
            severity = %s,
            resolved_detected_at = IF(%s, NULL, resolved_detected_at),
            resolution_basis = IF(%s, NULL, resolution_basis),
            resolution_confidence = IF(%s, NULL, resolution_confidence),
            probe_json = COALESCE(%s, probe_json)
        WHERE issue_id = %s
        """,
        (next_status, 1 if reopened else 0, severity,
         reopened, reopened, reopened, _json_or_none(probe), issue_id),
      )
      if reopened:
        _insert_resolution_event(
          cur, issue_id=issue_id, signature=signature, draft_id=draft_id,
          event_type="reopened",
          detail={"previous_basis": existing.get("resolution_basis"),
                  "previous_confidence": existing.get("resolution_confidence")},
        )

    cur.execute(
      f"""
      INSERT INTO {OCCURRENCES_TABLE}
        (issue_id, signature, draft_id, planning_run_id, business_name,
         persona, turn_index, section, stage, severity, observed, expected,
         evidence_json, source)
      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
      """,
      (issue_id, signature, str(draft_id or ""), str(planning_run_id or ""),
       str(business_name or "")[:255] or None, str(persona or "")[:64],
       int(turn_index) if turn_index is not None else None,
       str(section or "")[:32], str(stage or "")[:64], severity,
       observed, expected, _json_or_none(evidence), str(source or "cowork")[:16]),
    )
    conn.commit()
  finally:
    cur.close()
  state = get_issue(conn, signature=signature)
  state["is_new"] = is_new
  state["reopened"] = reopened
  return state


def get_issue(conn, *, signature: str) -> Dict[str, Any]:
  ensure_tables(conn)
  cur = conn.cursor()
  try:
    row = _fetch_issue(cur, signature)
  finally:
    cur.close()
  if row is None:
    raise KeyError(f"no issue with signature {signature!r}")
  return row


def resolve_manually(conn, *, signature: str, note: str = "") -> Dict[str, Any]:
  """Human override: mark resolved with basis 'manual'. Confidence follows
  the class honesty rule (hard -> confirmed, soft -> observational)."""
  ensure_tables(conn)
  cur = conn.cursor()
  try:
    issue = _fetch_issue(cur, signature)
    if issue is None:
      raise KeyError(f"no issue with signature {signature!r}")
    confidence = "confirmed" if issue["resolution_class"] == "hard" else "observational"
    cur.execute(
      f"""
      UPDATE {ISSUES_TABLE}
      SET status='resolved', resolved_detected_at=NOW(6),
          resolution_basis='manual', resolution_confidence=%s
      WHERE issue_id=%s
      """,
      (confidence, issue["issue_id"]),
    )
    _insert_resolution_event(
      cur, issue_id=int(issue["issue_id"]), signature=signature, draft_id="",
      event_type="manual_resolve", detail={"note": note},
    )
    conn.commit()
  finally:
    cur.close()
  return get_issue(conn, signature=signature)


# ----------------------------------------------------------------------------
# Resolution sensing (run after each completed persona run).
# ----------------------------------------------------------------------------

def _probe_from_issue(cur, issue: Dict[str, Any]) -> Dict[str, Any]:
  """The issue's probe predicate; when absent, derive a minimal one from its
  FIRST occurrence (section; business for verdict issues) so older issues
  still get honest exercised-detection instead of none."""
  raw = issue.get("probe_json")
  if raw:
    try:
      parsed = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
      if isinstance(parsed, dict) and parsed:
        return parsed
    except Exception:
      pass
  cur.execute(
    f"""
    SELECT section, business_name FROM {OCCURRENCES_TABLE}
    WHERE issue_id = %s ORDER BY id ASC LIMIT 1
    """,
    (issue["issue_id"],),
  )
  row = cur.fetchone()
  derived: Dict[str, Any] = {}
  if row:
    section, business = row[0], row[1]
    if section:
      derived["section"] = str(section)
    if str(issue.get("category")) == "verdict" and business:
      derived["business_like"] = f"%{str(business)[:80]}%"
  return derived


def _run_exercised(cur, draft_id: str, probe: Dict[str, Any]) -> Dict[str, Any]:
  """Did this run exercise the issue's path? Evaluates the small documented
  predicate vocabulary against the run's vitals + planning rows. Every
  clause must pass. Empty probe -> not exercised (never guess)."""
  if not probe:
    return {"exercised": False, "reason": "no probe and none derivable"}
  checks: List[str] = []

  if probe.get("require_completed", True):
    cur.execute(
      """
      SELECT run_status FROM planning_runs
      WHERE draft_id = %s ORDER BY started_at DESC LIMIT 1
      """,
      (draft_id,),
    )
    row = cur.fetchone()
    status = str(row[0]) if row else ""
    if status != "completed":
      return {"exercised": False,
              "reason": f"run not completed (status={status or 'none'})"}
    checks.append("run_completed")

  sections = probe.get("sections") or (
    [probe["section"]] if probe.get("section") else []
  )
  if sections:
    placeholders = ", ".join(["%s"] * len(sections))
    cur.execute(
      f"""
      SELECT COUNT(*) FROM run_vitals_turns
      WHERE draft_id = %s AND (section IN ({placeholders})
                               OR section_after IN ({placeholders}))
      """,
      (draft_id, *sections, *sections),
    )
    if int(cur.fetchone()[0] or 0) == 0:
      return {"exercised": False, "reason": f"sections {sections} not visited"}
    checks.append(f"sections={sections}")

  if probe.get("call_label_like"):
    cur.execute(
      """
      SELECT COUNT(*) FROM run_vitals_gpt_calls
      WHERE draft_id = %s AND call_label LIKE %s
      """,
      (draft_id, str(probe["call_label_like"])),
    )
    if int(cur.fetchone()[0] or 0) == 0:
      return {"exercised": False,
              "reason": f"no gpt call matching {probe['call_label_like']!r}"}
    checks.append("call_label")

  if probe.get("stage_like"):
    cur.execute(
      """
      SELECT COUNT(*) FROM planning_stage_events
      WHERE draft_id = %s AND stage LIKE %s
      """,
      (draft_id, str(probe["stage_like"])),
    )
    if int(cur.fetchone()[0] or 0) == 0:
      return {"exercised": False,
              "reason": f"stage {probe['stage_like']!r} not reached"}
    checks.append("stage")

  if probe.get("business_like"):
    cur.execute(
      "SELECT business_name FROM intake_consult_drafts WHERE draft_id = %s",
      (draft_id,),
    )
    row = cur.fetchone()
    name = str(row[0] or "") if row else ""
    like = str(probe["business_like"]).replace("%", "").lower()
    if like and like not in name.lower():
      return {"exercised": False,
              "reason": f"business {name!r} does not match {probe['business_like']!r}"}
    checks.append("business")

  if probe.get("min_turns"):
    cur.execute(
      "SELECT COUNT(*) FROM run_vitals_turns WHERE draft_id = %s",
      (draft_id,),
    )
    if int(cur.fetchone()[0] or 0) < int(probe["min_turns"]):
      return {"exercised": False, "reason": "fewer turns than min_turns"}
    checks.append("min_turns")

  return {"exercised": True, "reason": "; ".join(checks) or "probe empty-pass"}


def _auto_recurrence(cur, draft_id: str, probe: Dict[str, Any]) -> Optional[str]:
  """Hard signals the checker can detect WITHOUT a Cowork report, when the
  probe opts in: stalls, holds, matching GPT errors on this run."""
  auto = probe.get("auto_recur") or {}
  if not isinstance(auto, dict) or not auto:
    return None
  if auto.get("stall"):
    cur.execute(
      """
      SELECT COUNT(*) FROM run_vitals_events
      WHERE draft_id = %s AND event_type LIKE 'watch_end_stall%%'
      """,
      (draft_id,),
    )
    if int(cur.fetchone()[0] or 0) > 0:
      return "stall event on this run"
  if auto.get("hold"):
    cur.execute(
      """
      SELECT COUNT(*) FROM run_vitals_events
      WHERE draft_id = %s AND event_type = 'turn_hold'
      """,
      (draft_id,),
    )
    if int(cur.fetchone()[0] or 0) > 0:
      return "turn_hold event on this run"
  if auto.get("gpt_error_like"):
    cur.execute(
      """
      SELECT COUNT(*) FROM run_vitals_gpt_calls
      WHERE draft_id = %s AND error LIKE %s
      """,
      (draft_id, str(auto["gpt_error_like"])),
    )
    if int(cur.fetchone()[0] or 0) > 0:
      return f"gpt error matching {auto['gpt_error_like']!r}"
  return None


def evaluate_run_for_resolution(
  conn,
  *,
  draft_id: str,
  hard_clean_threshold: int = DEFAULT_HARD_CLEAN_THRESHOLD,
  soft_runs_threshold: int = DEFAULT_SOFT_RUNS_THRESHOLD,
) -> Dict[str, Any]:
  """Evaluate every open/recurring issue against one finished run.

  Per issue: if it was reported again on THIS run (or an opted-in hard
  signal auto-recurred), counters were/are reset. Otherwise, if the run
  exercised the issue's path, tick the clean counters and resolve when the
  class-appropriate threshold is met — 'confirmed' only ever for hard
  issues, 'observational' for soft. Not-exercised runs change nothing
  (absence without opportunity is not evidence).
  """
  draft_id = str(draft_id or "").strip()
  if not draft_id:
    raise ValueError("draft_id is required")
  ensure_tables(conn)
  summary = {
    "draft_id": draft_id, "evaluated": 0, "recurred": 0,
    "exercised_clean": 0, "not_exercised": 0,
    "resolved_confirmed": [], "resolved_observational": [],
  }
  cur = conn.cursor()
  try:
    cur.execute(
      f"SELECT * FROM {ISSUES_TABLE} WHERE status IN ('open', 'recurring')"
    )
    cols = [d[0] for d in cur.description]
    issues = [dict(zip(cols, r)) for r in cur.fetchall()]
    for issue in issues:
      summary["evaluated"] += 1
      issue_id = int(issue["issue_id"])
      signature = str(issue["signature"])

      cur.execute(
        f"""
        SELECT COUNT(*) FROM {OCCURRENCES_TABLE}
        WHERE issue_id = %s AND draft_id = %s
        """,
        (issue_id, draft_id),
      )
      reported_this_run = int(cur.fetchone()[0] or 0) > 0

      probe = _probe_from_issue(cur, issue)
      auto_reason = None if reported_this_run else _auto_recurrence(cur, draft_id, probe)

      if reported_this_run or auto_reason:
        summary["recurred"] += 1
        if auto_reason:
          # Auto-detected recurrence: record the occurrence + reset, exactly
          # as a reported sighting would (source marks it machine-found).
          report_issue(
            conn,
            signature=signature,
            category=str(issue["category"]),
            severity=str(issue["severity"]),
            observed=f"auto-detected recurrence: {auto_reason}",
            expected="no recurrence of this signature on an exercised run",
            draft_id=draft_id,
            source="auto_check",
          )
        continue

      verdict = _run_exercised(cur, draft_id, probe)
      if not verdict["exercised"]:
        summary["not_exercised"] += 1
        continue

      summary["exercised_clean"] += 1
      clean = int(issue["clean_exercise_count"] or 0) + 1
      quiet = int(issue["runs_since_last_seen"] or 0) + 1
      rclass = str(issue["resolution_class"])
      resolve_now = (
        clean >= hard_clean_threshold if rclass == "hard"
        else quiet >= soft_runs_threshold
      )
      if resolve_now:
        basis = "retested_clean" if rclass == "hard" else "not_seen_n_runs"
        confidence = "confirmed" if rclass == "hard" else "observational"
        cur.execute(
          f"""
          UPDATE {ISSUES_TABLE}
          SET clean_exercise_count=%s, runs_since_last_seen=%s,
              status='resolved', resolved_detected_at=NOW(6),
              resolution_basis=%s, resolution_confidence=%s
          WHERE issue_id=%s
          """,
          (clean, quiet, basis, confidence, issue_id),
        )
        event = ("resolved_confirmed" if rclass == "hard"
                 else "resolved_observational")
        _insert_resolution_event(
          cur, issue_id=issue_id, signature=signature, draft_id=draft_id,
          event_type=event,
          detail={"basis": basis, "confidence": confidence,
                  "clean_exercise_count": clean, "runs_since_last_seen": quiet,
                  "exercised_via": verdict["reason"]},
        )
        summary[f"resolved_{confidence}"].append(signature)
      else:
        cur.execute(
          f"""
          UPDATE {ISSUES_TABLE}
          SET clean_exercise_count=%s, runs_since_last_seen=%s
          WHERE issue_id=%s
          """,
          (clean, quiet, issue_id),
        )
        _insert_resolution_event(
          cur, issue_id=issue_id, signature=signature, draft_id=draft_id,
          event_type="exercised_clean",
          detail={"clean_exercise_count": clean, "runs_since_last_seen": quiet,
                  "exercised_via": verdict["reason"]},
        )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return summary


# ----------------------------------------------------------------------------
# Read helpers (dashboard / Cowork agenda queries).
# ----------------------------------------------------------------------------

def list_issues(
  conn,
  *,
  status: str = "",
  category: str = "",
  limit: int = 200,
) -> List[Dict[str, Any]]:
  ensure_tables(conn)
  where: List[str] = []
  params: List[Any] = []
  if status:
    where.append("status = %s")
    params.append(_require(status, STATUSES, "status"))
  if category:
    where.append("category = %s")
    params.append(_require(category, CATEGORIES, "category"))
  sql = f"SELECT * FROM {ISSUES_TABLE}"
  if where:
    sql += " WHERE " + " AND ".join(where)
  sql += " ORDER BY last_seen_at DESC LIMIT %s"
  params.append(min(500, max(1, int(limit))))
  cur = conn.cursor()
  try:
    cur.execute(sql, tuple(params))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
  finally:
    cur.close()


def recent_occurrences(conn, *, limit: int = 100) -> List[Dict[str, Any]]:
  ensure_tables(conn)
  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      SELECT o.id, o.signature, o.draft_id, o.planning_run_id,
             o.business_name, o.persona, o.turn_index, o.section, o.stage,
             o.severity, LEFT(o.observed, 400) AS observed,
             LEFT(o.expected, 400) AS expected, o.source, o.created_at,
             i.category, i.status
      FROM {OCCURRENCES_TABLE} o
      JOIN {ISSUES_TABLE} i ON i.issue_id = o.issue_id
      ORDER BY o.id DESC LIMIT %s
      """,
      (min(500, max(1, int(limit))),),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
  finally:
    cur.close()
