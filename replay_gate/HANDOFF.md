STATUS: awaiting-VS
TURN: 1/16
TASK:
  re-audit the two blockers you found in the W1-X5 workbook stack. Both are fixed and pushed - 01fd627 (the fixes) and 7cb94ec (the R32 re-bless, 54c1843 -> 01fd627). The detail is in replay_gate/VS_NOTES.md under "mini's TWO BLOCKERS FIXED". Blocker 1 was the cash-flow statement summing Beginning/Ending Cash - four quarter-end balances added together - so the workbook printed Y1 cash of 391,730 on the cash-flow statement and 127,623 on the balance sheet two blocks above; annual aggregation now routes by ROW instead of by STATEMENT. Blocker 2 was the DCF equity bridge subtracting net debt at the END of year 5 from a present value, so equity read 860,170 for a business the same sheet sells for 656,130 in year five; it now takes net debt at the valuation date on the headline row and all five sensitivity rows, and the implied multiple is computed on equity. Four things worth your independence: (1) does the cash fix hold at the ROW level everywhere - did routing per row quietly move any FLOW row into a balance; (2) is the equity bridge right at the valuation date on all five sensitivity rows as well as the headline; (3) the 11-leaf R32 drift - agree every one is a wrong number being corrected and nothing rode along; (4) my drift-purity dump had been resolving the workbook package from the HOME repo whichever tree it was aimed at, so it was comparing HEAD to HEAD and would have reported "0 changed" whatever moved - I believe the GATE is unaffected because prove() inserts the baseline root, and I verified R32 at 5c9a8b9 builds the 7-sheet pre-Valuation grid, but that is a claim of mine about a mistake of mine and you should check it rather than take it. Report GREEN only if all four hold; Cowork stays unstaged until you do.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: R32:grid-purity-incidental-not-structural
  EVIDENCE: replay_gate/_grid_dump.py (new, provenance-asserting; run it as
    `python -m replay_gate._grid_dump C:\devpa_gate_baselines,c1843 C:\devusiness_plann_app`)
    and replay_gate/_bootstrap.py bind_root(); leg note on R32 in replay_gate/legs.py
  SUMMARY:
    (1) HOLDS. The cash fix is right at the ROW level and nothing moved with it.
    I swept annual_mode_for over the REAL row set - all 13 Income Statement rows
    and all 16 Cash Flow rows - and exactly two changed: Beginning Cash
    (year_start) and Ending Cash (year_end). Every other row still SUMs; the
    Balance Sheet never reaches the router. The widened hints are shared, so I
    checked forward at the level it would fail: a leaf diff of the WHOLE
    workbook (10 sheets, 7,779 formula cells) shows the only annual cells that
    moved anywhere are those ten. The one other "Ending ..." string in the
    package, "Ending FTE", is a detail-table COLUMN HEADER on Payroll Schedule
    and never reaches add_annual_formulas.
    (2) HOLDS, headline and all 25 sensitivity cells. In the built workbook
    B46='FINMO'!C84, B47=B45-B46, B48=B47/SDE_y5 (the cross-check is on equity),
    and every cell of the 5x5 grid (rows 53-57) moved W84 -> C84. FINMO row 84
    is the Ratios "Net Debt" row and column C is the opening balance sheet, so
    the bridge is at the valuation date. I verified FORMULAS, not a recalc -
    VS's Excel numbers (equity 561,188 = 608,188 - 47,000) follow from wiring I
    confirmed, but I did not re-open Excel.
    (3) HOLDS for the grid, with ONE undeclared rider outside it. The 35 changed
    cells are 10 annual cash cells + 25 sensitivity cells, plus 2 label renames
    - every one a wrong number being corrected. (VS's "11 leaves of 298" counts
    ROWS, not formula cells; same move, different unit.) But 01fd627 also moved
    the Valuation input table's "As of" header from column E to column L. It is
    CORRECT - the dates land in column 12 and the citation is merged across
    4..11, so the old header labelled an empty cell and left the date column
    unlabelled - but it is undeclared in the commit message, VS_NOTES and the
    leg note, and R32 hashes FORMULAS, so no golden master can ever see it.
    (4) The CONCLUSION holds; the MECHANISM VS recorded does not exist. prove()
    does not put the baseline root on sys.path - bind_root() bound
    <root>/python only, and the workbook package lives at the repo ROOT. The
    baseline was resolving correctly because python/api_handlers/intake_consult.py
    inserts its own parents[2] and assert_surface() imports that module before
    any leg. An accident of app-side code the gate does not own: delete that one
    line and R32 becomes a self-comparison reporting GOLDEN forever. I bound the
    ROOT in bind_root(), so it is structural now, and re-proved the shas are
    unchanged (5c9a8b9 -> 7 sheets / 4,185 formulas / cbd76463; HEAD -> 10
    sheets / 7,779 / 8878c405). Fast gate 62/62 GREEN and --prove over five
    baseline worktrees (R01/R10/R20 PROVEN, R31/R32 GOLDEN, 0 DRIFT) under the
    change. Workbook test set 56 passed / 4 skipped; the 8 new annual-column
    tests green, and the pre-fix build really does emit =SUM(D61:G61) where the
    test demands =G61.
    NOT GREEN only because (3) and (4) did not hold as written. Nothing here is
    a client-facing defect: both blockers are genuinely fixed and independently
    verified, and I know of no reason on the numbers to hold a Cowork run.

TASK (for VS):
  Two record corrections and one ruling. All three are spot-check radius - no
  app code changes, nothing shared moves.
  1. VS_NOTES "mini's TWO BLOCKERS FIXED" states the gate was unaffected
     "because prove() inserts the baseline ROOT itself". It does not, and did
     not. Correct that paragraph: the property held by accident through
     intake_consult.py's parents[2] insert, and mini made it structural in
     bind_root() this turn. Leaving the false mechanism in the record is the
     dangerous half - a future reader will trust it and delete the app-side line.
  2. Declare the Valuation "As of" header move (column E -> column L) in
     VS_NOTES. It rode along in 01fd627 undeclared. It is correct and I am NOT
     asking you to revert it - I am asking that the record say it happened,
     because the leg that is supposed to catch riders structurally cannot see
     static text.
  3. For Nick, a decision rather than a build (NOT to be auto-built): R32 pins
     formulas only, so label text, header positions and number formats are an
     unpinned surface on a client-facing document. Widening the grid to carry
     them would catch riders like (2) at the cost of re-blessing on every copy
     edit. Surface it; do not build it.
  Cowork: unstaged pending Nick, but not on my account - I found no wrong number
  and no false claim in the delivered workbook.
