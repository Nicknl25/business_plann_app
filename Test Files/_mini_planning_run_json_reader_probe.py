"""Does the WORKBOOK BUILDER read planning_run_json? (VS's owed question)

VS wants to drop PLANNING_RUN_JSON from the R32 fixture -- 2.8 MB of 2.9 MB --
if nothing reads it. Reading the source says it IS read; this proves it by
A/B on the frozen fixture itself: build the R32 formula grid twice, once with
the fixture as committed and once with PLANNING_RUN_JSON emptied, and compare.

If the grids are identical, the payload is dead weight and the re-freeze is
safe. If they differ (or one of them refuses to build), dropping it changes
the golden output and the re-freeze would silently move the master.

  .venv\\Scripts\\python.exe "Test Files\\_mini_planning_run_json_reader_probe.py"
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


def digest(grid) -> str:
  return hashlib.sha256(
    json.dumps(grid, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT))
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

  from replay_gate import _bootstrap  # type: ignore
  _bootstrap.bind_root("")
  from replay_gate.context import GateContext  # type: ignore
  from replay_gate import _run_artifacts as fx  # type: ignore

  conn = _bootstrap.gate_connection()
  read_conn = _bootstrap.read_connection()

  print("fixture PLANNING_RUN_JSON: "
        f"{len(json.dumps(fx.PLANNING_RUN_JSON)):,} bytes, "
        f"{len(fx.PLANNING_RUN_JSON)} top-level keys")

  def build(label):
    from client_statements_output_excel import data as wbdata  # type: ignore
    from client_statements_output_excel import workbook_builder  # type: ignore
    s = GateContext(conn, read_conn)
    grid = s.workbook_formula_grid(
      builder=workbook_builder.build_client_financial_model_workbook,
      from_row=wbdata.draft_data_from_row)
    gap = getattr(s, "grid_gap", None)
    if not grid:
      print(f"  {label}: NO GRID - gap: {gap}")
      return None, gap
    sheets = {k: sum(len(v) for v in rows.values()) for k, rows in grid.items()}
    print(f"  {label}: {sum(sheets.values())} formulas over {len(grid)} sheets "
          f"digest={digest(grid)[:16]}")
    return grid, sheets

  print("\nA - fixture as committed")
  grid_a, sheets_a = build("as-committed")

  print("\nB - PLANNING_RUN_JSON emptied (what the re-freeze would do)")
  saved = fx.PLANNING_RUN_JSON
  fx.PLANNING_RUN_JSON = {}
  try:
    grid_b, sheets_b = build("planning_run_json dropped")
  finally:
    fx.PLANNING_RUN_JSON = saved

  print("\n== VERDICT ==")
  if grid_a is None or grid_b is None:
    print("  one side refused to build - dropping it is NOT safe")
    return 0
  if digest(grid_a) == digest(grid_b):
    print("  IDENTICAL grids: the workbook builder does not read it "
          "(for this payload) - the re-freeze is safe for R32")
    return 0
  print("  GRIDS DIFFER: the builder READS planning_run_json. Dropping it "
        "would move the golden master.")
  for sheet in sorted(set(sheets_a) | set(sheets_b)):
    a, b = sheets_a.get(sheet, 0), sheets_b.get(sheet, 0)
    if a != b:
      print(f"    {sheet}: {a} formulas with it, {b} without ({b - a:+d})")
  for sheet in sorted(set(grid_a) & set(grid_b)):
    only_a = set(grid_a[sheet]) - set(grid_b[sheet])
    only_b = set(grid_b[sheet]) - set(grid_a[sheet])
    if only_a or only_b:
      print(f"    {sheet}: rows only WITH it: {sorted(only_a)[:6]}")
      if only_b:
        print(f"    {sheet}: rows only WITHOUT it: {sorted(only_b)[:6]}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
