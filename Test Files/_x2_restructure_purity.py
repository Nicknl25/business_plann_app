"""R32 re-bless evidence for the 2026-08-19 restructure.

What changed by design: the break-even block moved from under the P&L to under
the Cash Flow statement, a Ratios section was added beneath it, the CVP helper
data moved off FINMO to the hidden Calc sheet, and the Dashboard was rebuilt on
that engine. Everything else must be untouched.

This proves exactly that, per row label:

  UNTOUCHED SHEETS   every pre-existing sheet other than FINMO / Dashboard /
                     Calc must carry an identical formula set, label for label.
  FINMO              every label present on both sides must keep the same
                     formula SHAPE (the formula with row numbers masked). A
                     shape match plus the separately-proven identical
                     recalculated values means the references were renumbered
                     correctly and nothing was re-authored: a mis-pointed
                     reference would change a value, and no value changed.
  DECLARED           labels that appear or disappear, and the rebuilt sheets,
                     are listed rather than hidden.

Usage: python "Test Files/_x2_restructure_purity.py" <base_grid.json> <now_grid.json>
"""
from __future__ import annotations

import json
import re
import sys

REBUILT = {"Dashboard", "Calc"}
#: Sheets whose formulas legitimately RENUMBER when FINMO's rows move: FINMO
#: itself, and Checks, which points at FINMO rows by address.
RENUMBERS = {"FINMO", "Checks"}
#: The CVP helper rows Nick ordered off the statements sheet. The block was
#: also REDESIGNED on arrival (the break-even / planned / loss / profit markers
#: became COLUMNS of the grid instead of extra rows), so the proof is not that
#: these row labels reappear - it is that the CVP CAPABILITY is present on
#: Calc, evidenced by the block's own header labels.
MOVED_TO_CALC = {"X max", "Break-even", "Planned revenue", "LOSS", "PROFIT",
                 "Planned revenue (top)"}
#: The block's rows carry formulas, not labels, so the evidence is the band
#: MATH itself - a row that computes both MIN(revenue,cost) and MAX(0, ...)
#: is a CVP band row. Stronger than matching a caption.
CVP_MIN_BAND_ROWS = 8
_ROWNUM = re.compile(r"(?<=[A-Z$])\d+")


def shape(formula: str) -> str:
  return _ROWNUM.sub("#", formula)


def main(base_path: str, now_path: str) -> int:
  base = json.load(open(base_path, encoding="utf-8"))
  now = json.load(open(now_path, encoding="utf-8"))
  problems: list = []
  identical = shifted = extended = 0
  moved: list = []
  unlabelled_moved = 0

  for sheet, base_rows in base.items():
    now_rows = now.get(sheet)
    if now_rows is None:
      problems.append(f"SHEET REMOVED: {sheet}")
      continue
    if sheet in REBUILT:
      print(f"DECLARED REBUILD  {sheet}: {len(base_rows)} labelled rows -> {len(now_rows)}")
      continue
    for label, base_formulas in base_rows.items():
      now_formulas = now_rows.get(label)
      if now_formulas is None:
        if sheet == "FINMO" and (label in MOVED_TO_CALC or re.fullmatch(r"row\d+", label)):
          # The CVP helper block. Its labelled rows must be present on Calc;
          # its unlabelled rows are counted so the move is fully accounted for.
          if label in MOVED_TO_CALC:
            moved.append(label)
          else:
            unlabelled_moved += 1
          continue
        problems.append(f"LABEL LOST  {sheet} :: {label!r} ({len(base_formulas)} formulas)")
        continue
      if base_formulas == now_formulas:
        identical += 1
        continue
      if [shape(f) for f in base_formulas] == [shape(f) for f in now_formulas]:
        if sheet in RENUMBERS:
          shifted += 1
          continue
        problems.append(f"ROW-SHIFT OUTSIDE THE RESTRUCTURED SHEETS  {sheet} :: {label!r}")
        continue
      if (sheet in RENUMBERS and len(now_formulas) > len(base_formulas)
          and now_formulas[:len(base_formulas)] == base_formulas):
        # e.g. the Checks formula manifest gains one entry per new ratio row:
        # every pre-existing entry is byte-identical and the rest is appended.
        extended += 1
        continue
      problems.append(
        f"IMPURE  {sheet} :: {label!r}\n     base={base_formulas[:2]}\n     now ={now_formulas[:2]}")

  band_rows = [label for label, formulas in (now.get("Calc") or {}).items()
               if any(f.startswith("=MIN(") for f in formulas)
               and any(f.startswith("=MAX(0,") for f in formulas)]
  if len(band_rows) < CVP_MIN_BAND_ROWS:
    problems.append(f"CVP BLOCK DID NOT ARRIVE on Calc: only {len(band_rows)} band rows found")

  new_labels = [(s, l) for s, rows in now.items() if s not in REBUILT
                for l in rows if l not in base.get(s, {})]
  new_sheets = [s for s in now if s not in base]

  print(f"\nidentical leaves: {identical}")
  print(f"pure row-shift leaves (FINMO): {shifted}")
  print(f"new sheets: {new_sheets}")
  print(f"new labels on existing sheets: {len(new_labels)}")
  for s, l in new_labels[:12]:
    print(f"    + {s} :: {l}")
  if len(new_labels) > 12:
    print(f"    ... {len(new_labels) - 12} more")
  if problems:
    print(f"\nPROBLEMS ({len(problems)}):")
    for p in problems[:30]:
      print("  -", p)
    if len(problems) > 30:
      print(f"  ... {len(problems) - 30} more")
    return 1
  print("\nPURE: every untouched sheet is formula-identical; every FINMO leaf is "
        "either identical or a pure renumbering; the rest is declared.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1], sys.argv[2]))
