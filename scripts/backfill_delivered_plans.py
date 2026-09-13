"""Backfill the delivery record for written plans that shipped before it existed.

Filename reads are refused now (Nick 2026-09-13: "refused once draft_id keying
lands, not labelled" - a caveat on something that works will be ignored, and
Cowork's playbook keeps the path it already has). That is only affordable if
the plans already on disk can be keyed, and they can:

  C:\\dev\\Client Written Plans\\_v2_runs\\<slug>__<8 hex>\\<plan>.docx

where the 8 hex is the planning_run_id prefix (verified on 7 folders), and
planning_runs maps run -> draft. So plan -> run -> draft is DERIVED, not
guessed: every row this writes is backed by a run id carried in the path the
writer itself chose.

Workbooks are NOT recoverable this way. `Business Name -- MM-DD-YYYY
HH-MM-SS.xlsx` carries no run id and no draft id, and neither does anything
inside the file (Audit Source, Model Inputs and Cover all checked). This script
does not guess at them, and says how many it left alone.

Read-only against the run folders; the only writes are delivered_artifacts rows.
Idempotent: a path already recorded is skipped.

    python scripts/backfill_delivered_plans.py            # report only
    python scripts/backfill_delivered_plans.py --write    # write the rows
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

try:
  from dotenv import load_dotenv  # type: ignore

  load_dotenv(str(ROOT / ".env"), override=False)
except Exception:
  pass

PLANS_DIR = Path(os.getenv("BPA_PLAN_DIR") or r"C:\dev\Client Written Plans")
RUNS_DIR = PLANS_DIR / "_v2_runs"
WORKBOOK_DIR = Path(os.getenv("BPA_WORKBOOK_DIR") or r"C:\dev\Cilient Plans")

#: <slug>__<8 hex> - the run folder the writer creates per delivered plan.
_RUN_FOLDER = re.compile(r"^(?P<slug>.+)__(?P<run8>[0-9a-f]{8})$")


def _conn():
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore

  return get_mysql_connection()


def _draft_for_run_prefix(conn, run8: str):
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT planning_run_id, draft_id FROM planning_runs WHERE planning_run_id LIKE %s",
      (run8 + "%",))
    rows = cur.fetchall()
  finally:
    cur.close()
  if len(rows) != 1:
    return (None, None, f"{len(rows)} runs match {run8} - ambiguous, skipped")
  return (rows[0]["planning_run_id"], rows[0]["draft_id"], None)


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--write", action="store_true", help="write the rows (default: report only)")
  args = ap.parse_args()

  from client_intake_and_finmo import delivered_artifacts as da  # type: ignore

  conn = _conn()
  written = skipped = already = ambiguous = 0
  try:
    cur = conn.cursor()
    cur.execute(f"SELECT path FROM {da.TABLE}")
    recorded = {str(r[0]) for r in cur.fetchall()}
    cur.close()

    if not RUNS_DIR.is_dir():
      print(f"no run folders at {RUNS_DIR}")
      return 1

    for folder in sorted(RUNS_DIR.iterdir()):
      if not folder.is_dir():
        continue
      match = _RUN_FOLDER.match(folder.name)
      if not match:
        skipped += 1
        print(f"  SKIP  {folder.name}: no run id in the folder name")
        continue
      run_id, draft_id, problem = _draft_for_run_prefix(conn, match.group("run8"))
      if problem:
        ambiguous += 1
        print(f"  SKIP  {folder.name}: {problem}")
        continue
      for plan in sorted(folder.glob("*.docx")):
        if "FAILED DRAFT" in plan.name:
          continue   # never shipped; not a delivery
        shipped = PLANS_DIR / plan.name
        target = shipped if shipped.is_file() else plan
        if str(target) in recorded:
          already += 1
          continue
        print(f"  PLAN  {draft_id[:12]} run={run_id[:12]} {target.name}")
        if args.write:
          da.record(conn, draft_id=draft_id, planning_run_id=run_id,
                    kind="plan", path=str(target))
          written += 1
        report = Path(str(plan) + ".render_report.json")
        if report.is_file() and str(report) not in recorded:
          print(f"  RPT   {draft_id[:12]} {report.name}")
          if args.write:
            da.record(conn, draft_id=draft_id, planning_run_id=run_id,
                      kind="render_report", path=str(report))
            written += 1
  finally:
    try:
      conn.close()
    except Exception:
      pass

  workbooks = len([p for p in WORKBOOK_DIR.rglob("*.xlsx")
                   if p.is_file() and not p.name.startswith("~$")])
  print()
  print(f"rows {'written' if args.write else 'that WOULD be written'}: {written}")
  print(f"already recorded: {already}   folders with no run id: {skipped}   ambiguous: {ambiguous}")
  print(f"workbooks left unkeyed: {workbooks} - a workbook filename carries no run id "
        f"and neither does the file; these are not guessable and are not guessed at")
  if not args.write:
    print("\n(report only - pass --write to record these)")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
