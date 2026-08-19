# -*- coding: utf-8 -*-
"""Leaf-level workbook-grid dump and diff - the instrument behind an R32 re-bless.

WHY THIS IS COMMITTED (mini, 2026-08-19). The ad-hoc dump used for the earlier
re-blesses put only <root>/python on sys.path and let cwd supply the repo-root
package. client_statements_output_excel/ lives at the ROOT, so it resolved from
the HOME repo whichever tree the dump was aimed at: it compared HEAD to HEAD and
would have reported "0 changed" whatever had moved. A one-off script that lies
this way costs a whole re-bless, so the instrument lives in the gate now and
ASSERTS ITS OWN PROVENANCE before it hashes anything.

  python -m replay_gate._grid_dump <root> [<other root>]

One root  -> sha + sheet inventory for that tree.
Two roots -> the same, plus a leaf-by-leaf diff (sheet, row label, column index).
"""
import hashlib
import json
import os
import subprocess
import sys

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _grid_for(root):
    """Build the grid under <root>'s OWN workbook code, in a clean subprocess.

    A subprocess per root is not caution, it is correctness: the two trees ship
    the same module names, so one process cannot hold both.
    """
    p = subprocess.run(
        [sys.executable, "-m", "replay_gate._grid_dump", "--child", root],
        cwd=HOME, capture_output=True, text=True)
    marker = "@@GRID@@"
    if p.returncode != 0 or marker not in (p.stdout or ""):
        tail = ((p.stderr or p.stdout or "").strip().splitlines() or ["no output"])[-1]
        raise SystemExit(f"dump failed for {root}: {tail[:300]}")
    return json.loads(p.stdout.split(marker, 1)[1])


def _child(root):
    root = os.path.abspath(root)
    from . import _bootstrap  # noqa: F401  (imported for HOME_REPO/.env only)

    _bootstrap.bind_root(root)
    import client_statements_output_excel as pkg

    # THE PROVENANCE ASSERTION. Everything else here is bookkeeping; this line
    # is the reason the file exists.
    got = os.path.abspath(os.path.dirname(pkg.__file__))
    want = os.path.abspath(os.path.join(root, "client_statements_output_excel"))
    if os.path.normcase(got) != os.path.normcase(want):
        raise SystemExit(
            f"PROVENANCE FAIL: workbook package resolved from {got}, not {want}. "
            f"This dump would compare a tree against itself.")

    from client_statements_output_excel import data as wbdata
    from client_statements_output_excel import workbook_builder
    from .context import GateContext

    ctx = GateContext(None, None)  # the grid path is frozen fixtures, no DB
    grid = ctx.workbook_formula_grid(
        builder=workbook_builder.build_client_financial_model_workbook,
        from_row=wbdata.draft_data_from_row)
    if not grid:
        raise SystemExit(f"no grid: {getattr(ctx, 'grid_gap', '') or 'unknown gap'}")
    sys.stdout.write("@@GRID@@" + json.dumps(grid, sort_keys=True, default=str))
    return 0


def _leaves(grid):
    return {f"{sheet}\t{label}\t{i}": f
            for sheet, rows in grid.items()
            for label, formulas in rows.items()
            for i, f in enumerate(formulas)}


def _report(root, grid):
    blob = json.dumps(grid, sort_keys=True, separators=(",", ":"), default=str)
    sha = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    leaves = _leaves(grid)
    print(f"ROOT   {root}")
    print(f"SHA    {sha}")
    print(f"GRID   {len(grid)} sheets, {len(leaves)} formula cells - {sorted(grid)}")
    return leaves


def main(argv):
    if len(argv) >= 2 and argv[0] == "--child":
        return _child(argv[1])
    if not argv:
        print(__doc__)
        return 2
    roots = argv[:2]
    sides = [(r, _report(r, _grid_for(r))) for r in roots]
    if len(sides) < 2:
        return 0
    (a_root, a), (b_root, b) = sides
    gone = sorted(set(a) - set(b))
    new = sorted(set(b) - set(a))
    moved = [k for k in sorted(set(a) & set(b)) if a[k] != b[k]]
    print(f"\nDIFF   {len(set(a) & set(b))} shared cells, {len(moved)} CHANGED, "
          f"{len(gone)} only in {os.path.basename(a_root)}, "
          f"{len(new)} only in {os.path.basename(b_root)}")
    # NOT A COMPLETE PICTURE, AND SAYING SO IS THE POINT: the grid carries
    # FORMULAS. A moved static label, a header written to a different column, a
    # number format - none of it is here, and none of it moves this sha.
    print("       (formulas only - static labels and formats are invisible here)")
    for k in gone:
        print(f"  -    {k}\t{a[k][:110]}")
    for k in new:
        print(f"  +    {k}\t{b[k][:110]}")
    for k in moved:
        print(f"  *    {k}\n         was {a[k][:110]}\n         now {b[k][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
