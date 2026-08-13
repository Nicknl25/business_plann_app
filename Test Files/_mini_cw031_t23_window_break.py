"""CW-031 mini audit, tiers 2/3 -- ITEM 3b: can the run-window fallback be made
to award a workbook to the WRONG draft?

VS's rule: a candidate file goes to the draft whose OWN run stamp is NEAREST
across every draft sharing the business name, inside 300s; among the files a
draft legitimately owns, the LATEST export wins ("a draft can run more than
once"). VS had no real two-runs-in-five-minutes case and asked for one.

This drives the PRODUCTION resolve_workbook_for_draft. Only the DB rows are
stubbed (a cursor that answers the three queries it makes); the filenames are
real files on disk with real embedded stamps, and every decision is the
shipped function's own.

THE CASE THAT BREAKS IT: draft A runs first but builds SLOWLY; draft B runs
before A's file lands, and builds fast. A's file is then nearer B's run stamp
than its own, so "nearest run" awards A's workbook to B -- and because B's own
file is EARLIER, "latest export wins" makes B prefer A's file over its own.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_t23_window_break.py"
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BUSINESS = "Larkspur Repeat Runs"
T0 = datetime(2026, 8, 13, 9, 0, 0)

FAILURES: list = []


def check(label: str, ok: bool, detail: str) -> None:
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
  if not ok:
    FAILURES.append(label)


class StubCursor:
  """Answers exactly the three queries resolve_workbook_for_draft makes."""

  def __init__(self, drafts, run_stamps):
    self.drafts = drafts              # {draft_id: business_name}
    self.run_stamps = run_stamps      # {draft_id: [datetime, ...]}
    self._result = []

  def execute(self, sql, params=()):
    text = " ".join(str(sql).split()).lower()
    if text.startswith("select 1 from workbook_deliveries"):
      raise RuntimeError("no delivery record table in this scenario")
    if "select workbook_filename" in text:
      raise RuntimeError("no delivery record table in this scenario")
    if "select business_name from intake_consult_drafts" in text:
      self._result = [(self.drafts.get(str(params[0])) or "",)]
      return
    if "select draft_id from intake_consult_drafts" in text:
      self._result = [(d,) for d, name in self.drafts.items() if name == params[0]]
      return
    if "from post_intake_run_diagnostics" in text:
      wanted = {str(p) for p in params}
      self._result = [(d, s) for d, stamps in self.run_stamps.items()
                      if d in wanted for s in stamps]
      return
    raise AssertionError(f"unexpected query: {text[:90]}")

  def fetchall(self):
    out, self._result = self._result, []
    return out

  def fetchone(self):
    out = self._result[0] if self._result else None
    self._result = []
    return out


def touch(directory: str, stamp: datetime) -> str:
  name = f"{BUSINESS} -- {stamp:%m-%d-%Y %H-%M-%S}.xlsx"
  path = os.path.join(directory, name)
  with open(path, "wb") as handle:
    handle.write(b"")
  return name


def scenario(wdr, title, *, a_run, a_file, b_run, b_file, expect):
  print(f"\n{title}")
  with tempfile.TemporaryDirectory() as tmp:
    name_a = touch(tmp, a_file)
    name_b = touch(tmp, b_file)
    print(f"  draft A run {a_run:%H:%M:%S}  ->  its workbook stamped {a_file:%H:%M:%S}"
          f"  ({(a_file - a_run).total_seconds():+.0f}s, {name_a[-12:-5]})")
    print(f"  draft B run {b_run:%H:%M:%S}  ->  its workbook stamped {b_file:%H:%M:%S}"
          f"  ({(b_file - b_run).total_seconds():+.0f}s, {name_b[-12:-5]})")
    cur = StubCursor(
      drafts={"draftAAAA": BUSINESS, "draftBBBB": BUSINESS},
      run_stamps={"draftAAAA": [a_run], "draftBBBB": [b_run]},
    )
    got = {}
    for draft in ("draftAAAA", "draftBBBB"):
      res = wdr.resolve_workbook_for_draft(cur, draft, delivery_dir=tmp,
                                           business_name=BUSINESS)
      path = res.get("path")
      got[draft] = os.path.basename(path) if path else None
      print(f"    {draft}: basis={res['basis']:<12} -> "
            f"{(got[draft] or 'NOT ATTRIBUTED')}")
    truth = {"draftAAAA": name_a, "draftBBBB": name_b}
    wrong = {d: (got[d], truth[d]) for d in got
             if got[d] is not None and got[d] != truth[d]}
    if wrong:
      for draft, (awarded, owned) in wrong.items():
        print(f"    !! {draft} was awarded {awarded}, but its OWN workbook is {owned}")
    check(expect["label"], (not wrong) if expect["clean"] else bool(wrong),
          expect["detail"] if (not wrong) == expect["clean"]
          else f"got {got}")
    return wrong


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from client_intake_and_finmo import workbook_delivery_record as wdr  # type: ignore

  print("=" * 78)
  print("TWO RUNS OF ONE BUSINESS NAME, MINUTES APART -- three shapes")
  print("=" * 78)

  scenario(
    wdr,
    "SHAPE 1 (the ordinary repeat run): both builds fast, runs 150s apart.",
    a_run=T0, a_file=T0 + timedelta(seconds=20),
    b_run=T0 + timedelta(seconds=150), b_file=T0 + timedelta(seconds=170),
    expect={"clean": True, "label": "each draft gets its own workbook",
            "detail": "nearest-run does the disambiguation it claims"},
  )

  scenario(
    wdr,
    "SHAPE 2 (A builds slowly, B runs while A is still building): A's file lands\n"
    "         nearer B's run than its own, and B's own file is EARLIER.",
    a_run=T0, a_file=T0 + timedelta(seconds=200),
    b_run=T0 + timedelta(seconds=150), b_file=T0 + timedelta(seconds=160),
    expect={"clean": True, "label": "no draft is awarded another draft's workbook",
            "detail": "both refuse or both bind correctly"},
  )

  scenario(
    wdr,
    "SHAPE 3 (the same, tightened): A slow at +140s, B runs at +100s and builds\n"
    "         in 10s. A's file is 40s from B's run and 140s from A's own.",
    a_run=T0, a_file=T0 + timedelta(seconds=140),
    b_run=T0 + timedelta(seconds=100), b_file=T0 + timedelta(seconds=110),
    expect={"clean": True, "label": "no draft is awarded another draft's workbook",
            "detail": "both refuse or both bind correctly"},
  )

  print()
  print("=" * 78)
  if FAILURES:
    print(f"BREAK FOUND - {len(FAILURES)} shape(s) mis-award: {FAILURES}")
    return 1
  print("NO BREAK - the window fallback never awarded a file to the wrong draft.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
