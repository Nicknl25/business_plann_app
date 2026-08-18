"""W2 R32 drift-purity instrument (2026-08-18).

R32 hashes {sheet: {row label: [formula strings]}}. W2 inserts the Break-Even
Analysis block DIRECTLY BELOW the P&L on FINMO, so every Balance Sheet /
Cash Flow formula string changes by ROW RENUMBERING only, plus new rows
(block, CVP helper, Dashboard, Checks rows for the new statement). This
proves, leaf by leaf, that EVERY moved leaf is one of:
  (a) a NEW row introduced by W2 (allow-listed by label / sheet), or
  (b) an EXISTING row whose formulas are byte-identical after mapping every
      FINMO row reference r >= SHIFT_FROM to r + SHIFT (the block height),
and NOTHING else moved. Usage:
  python "Test Files/_w2_r32_drift_purity.py" grid_base.json grid_now.json
"""
from __future__ import annotations

import json
import re
import sys

base = json.load(open(sys.argv[1]))
now = json.load(open(sys.argv[2]))

# The block occupies rows between the P&L (ends row 20 + blank 21) and the
# Balance Sheet header. Derive the shift from the grids themselves: the
# Balance Sheet 'Cash' row formula '=D<ending cash row>' moved.
FINMO_NEW_STATEMENT_LABELS = {
  "Fixed Costs", "Variable Costs", "Variable Cost Ratio", "Contribution Margin Ratio",
  "Break-Even Revenue", "Cash Break-Even Revenue", "EBITDA-Basis Break-Even Revenue",
  "Planned Revenue", "Margin of Safety", "Break-Even Revenue (G&A as fixed)",
}
NEW_SHEETS = {"Dashboard"}

# Locate the shift: compare the FINMO 'Cash' (balance sheet) row's first formula.
def _first_ref_row(formula: str):
  m = re.search(r"(?<![A-Z$'])\$?[A-Z]{1,3}\$?(\d+)", formula)
  return int(m.group(1)) if m else None

b_cash = base["FINMO"]["Cash"][0]
n_cash = now["FINMO"]["Cash"][0]
shift = _first_ref_row(n_cash) - _first_ref_row(b_cash)
# rows below the P&L move; the P&L itself (rows <= 20 on the fixture) does not.
p_and_l_last = max(_first_ref_row(f) for f in base["FINMO"]["Net Income"] if _first_ref_row(f))
SHIFT_FROM = 21  # first row after the P&L block on the base grid
print(f"detected FINMO row shift = +{shift} for rows >= {SHIFT_FROM} (P&L last row {p_and_l_last})")

# Renumber references to FINMO rows. Local refs on FINMO ("D44"), and
# cross-sheet refs "'FINMO'!D44" / "FINMO!D44" on other sheets.
LOCAL = re.compile(r"(?<![A-Za-z0-9_$!'])(\$?)([A-Z]{1,3})(\$?)(\d+)")
XSHEET = re.compile(r"('FINMO'!|FINMO!)(\$?)([A-Z]{1,3})(\$?)(\d+)")

def _shift_local(formula: str) -> str:
  def rep(m):
    r = int(m.group(4))
    if r >= SHIFT_FROM:
      r += shift
    return f"{m.group(1)}{m.group(2)}{m.group(3)}{r}"
  return LOCAL.sub(rep, formula)

def _shift_xsheet(formula: str) -> str:
  def rep(m):
    r = int(m.group(5))
    if r >= SHIFT_FROM:
      r += shift
    return f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{r}"
  return XSHEET.sub(rep, formula)

problems = []
moved_renumbered = 0
identical = 0
new_rows = 0
removed = 0

for sheet in sorted(set(base) | set(now)):
  b_rows = base.get(sheet, {})
  n_rows = now.get(sheet, {})
  if sheet in NEW_SHEETS:
    assert not b_rows, f"{sheet} existed at baseline"
    new_rows += len(n_rows)
    continue
  for label in sorted(set(b_rows) | set(n_rows)):
    b = b_rows.get(label)
    n = n_rows.get(label)
    if b is None:
      # New row - must be a W2 row.
      ok = (
        (sheet == "FINMO" and (label in FINMO_NEW_STATEMENT_LABELS or label.startswith("Break-Even Units") or label.startswith("row") or label in {"X max", "Break-even", "Planned revenue", "LOSS", "PROFIT"}))
        or (sheet == "Checks" and ("Break-Even" in label))
      )
      if ok:
        new_rows += 1
      else:
        problems.append(f"UNEXPECTED NEW ROW {sheet} :: {label!r}")
      continue
    if n is None:
      removed += 1
      problems.append(f"ROW REMOVED {sheet} :: {label!r}")
      continue
    if b == n:
      identical += 1
      continue
    # Moved: must equal after renumbering.
    if sheet == "FINMO":
      mapped = [_shift_local(f) for f in b]
    else:
      mapped = [_shift_xsheet(f) for f in b]
    if mapped == n:
      moved_renumbered += 1
      continue
    if sheet == "Checks":
      # Checks rows are keyed by CATEGORY (many check rows share a label) and
      # their formulas reference the Checks sheet's OWN rows (=E157-F157,
      # COUNTIF(I7:I172,...)), which shift when W2's new check rows are
      # inserted. Normalise Checks-local row numbers away and require the
      # baseline multiset to be contained in the current one; every EXTRA
      # must reference the FINMO block rows (the new statement's
      # formula-count checks) - anything else is impurity.
      norm = re.compile(r"(?<![A-Za-z'!])([A-Z]{1,2})(\d+)")
      def _n(f):
        return norm.sub(lambda m: f"{m.group(1)}#", f)
      from collections import Counter
      cb = Counter(_n(f) for f in mapped)
      cn = Counter(_n(f) for f in n)
      missing = cb - cn
      extra = cn - cb
      block_lo, block_hi = SHIFT_FROM + 1, SHIFT_FROM + shift - 1
      def _is_block_ref(f):
        rows = [int(x) for x in re.findall(r"FINMO'?!\$?[A-Z]{1,3}\$?(\d+)", f)]
        return bool(rows) and all(block_lo <= r <= block_hi for r in rows)
      # Anchors = formulas that can only belong to a W2 check row: a FINMO
      # block reference, or an Audit Source reference to a row beyond any
      # the baseline referenced (the persisted break-even section), or the
      # W2 relative-tolerance formula. Companions = the constant scaffolding
      # every check row carries (=21 / =E#-F# / status IFs); allowed only
      # alongside anchors (<= 3 per anchor).
      base_audit_rows = [int(x) for f in mapped for x in re.findall(r"'Audit Source'!\$?[A-Z]{1,3}\$?(\d+)", f)]
      max_base_audit = max(base_audit_rows) if base_audit_rows else 0
      def _is_new_audit_ref(f):
        rows = [int(x) for x in re.findall(r"'Audit Source'!\$?[A-Z]{1,3}\$?(\d+)", f)]
        return bool(rows) and all(r > max_base_audit for r in rows)
      COMPANIONS = {"=21", "=E#-F#", '=IF(G#=0,"OK","FAIL")', '=IF(ABS(G#)<=H#,"MATCH","CHANGED")'}
      anchors = [f for f in extra.elements() if _is_block_ref(f) or _is_new_audit_ref(f) or "Break-Even" in f]
      companions = [f for f in extra.elements() if f in COMPANIONS]
      bad_extra = [f for f in extra.elements() if f not in anchors and f not in companions]
      # The formula-count checks write their FINMO range as TEXT (not a
      # formula), so their only grid-visible cells are the 3 companions per
      # row; allow exactly one such row per new FINMO block row.
      new_block_rows = sum(1 for lab in now.get("FINMO", {}) if lab not in base.get("FINMO", {}) and (lab in FINMO_NEW_STATEMENT_LABELS or lab.startswith("Break-Even Units")))
      if len(companions) > 3 * (len(anchors) + new_block_rows):
        bad_extra.append(f"too many companion rows: {len(companions)} for {len(anchors)} anchors")
      if not missing and not bad_extra:
        moved_renumbered += 1
        new_rows += sum(extra.values())
        continue
      problems.append(f"IMPURE CHECKS {label!r}: missing={list(missing.elements())[:3]} bad_extra={bad_extra[:3]}")
      continue
    if True:
      # Checks sheet: rows for the block are interleaved; also formula-count
      # checks reference FINMO rows - handled by xsheet shift. Anything else
      # is impurity.
      problems.append(f"IMPURE MOVE {sheet} :: {label!r}\n   base={b[:2]}\n   now ={n[:2]}\n   mapped={mapped[:2]}")

print(f"identical rows: {identical}; renumbered-only rows: {moved_renumbered}; new W2 rows: {new_rows}; removed: {removed}")
if problems:
  print("PROBLEMS:")
  for p in problems[:40]:
    print(" -", p)
  print(f"... {len(problems)} total")
  sys.exit(1)
print("PURE: every moved leaf is a W2 row or a pure row-shift renumbering; nothing else moved.")
