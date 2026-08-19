STATUS: awaiting-Nick
TURN: 2/16
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

RESULT:
  AGENT: VS
  VERDICT: needs-ruling
  ERROR-SIGNATURE: R32:formula-only-grid-unpinned-text-surface
  EVIDENCE: replay_gate/VS_NOTES.md, section "mini's TWO BLOCKERS FIXED" -
    the three new paragraphs RECORD CORRECTION, UNDECLARED RIDER NOW DECLARED,
    and OPEN DECISION FOR NICK
  SUMMARY:
    Both record corrections landed, and I fact-checked each against the code
    and the diff rather than transcribing mini's account of mini's own mistake.
    (1) The false mechanism is GONE. prove() never inserted the baseline root:
    the only sys.path.insert in prove.py is probe_baseline()'s and it inserts
    <root>/python; _run_one() sets PYTHONPATH=HOME, so the HOME root was on the
    child path. The property was carried by intake_consult.py line 19's own
    parents[2] plus assert_surface() importing that module before any leg - an
    accident of app code the gate does not own. The note now says so, names the
    line that was carrying it, and records that bind_root() binds <root> ahead
    of PYTHONPATH so it is structural. The conclusion still holds; the reason
    given for it did not.
    (2) The rider is DECLARED. git show 01fd627 confirms build_valuation_sheet
    turned the positional header tuple into an explicit (column, name) list and
    moved "As of" from column 5 to column 12 - E to L, exactly as mini said,
    and it is one static-label change, nothing else rode with it. It is correct
    and stays; the note now says it happened and says why R32 could not see it.
    (3) Surfaced, not built - see the TASK below and the plain-English question
    for Nick.
    Docs only this turn: no app code, no gate code, no fixture. Nothing
    executable changed, so there was nothing to red-proof and nothing
    downstream to break - no canary, no legs, per the declared spot-check.
    DECLARED-vs-ACTUAL: matches. Declared spot-check / docs-only / canary skip
    / legs none, and that is what ran. One divergence worth stating: my first
    handoff_turn_plan.py call emitted an EMPTY plan (a scratchpad path resolved
    to / and the heredoc died); I re-sent the full four-line plan immediately,
    so Nick has one blank plan email followed by the real one.

  FOR NICK, IN PLAIN ENGLISH - one question, nothing is blocked on machinery:
    The gate that guards the workbook checks the FORMULAS on every sheet, and
    it checks them hard. It does not check the WORDS - the column headings, the
    labels, the number formatting. So if a future change silently moved a
    heading to the wrong column or renamed a label on the client's document,
    the gate would pass it. That is not hypothetical: it just happened. One of
    yesterday's fixes also moved the "As of" heading on the Valuation sheet
    four columns over. It was the right move - the heading had been sitting
    over an empty cell while the actual dates went unlabelled - but nothing
    caught it, we only found it by reading the diff by hand.
    The question is whether you want the gate widened to cover the words and
    the formatting too. Upside: a wrong heading or a mangled label can never
    reach a client unnoticed. Cost: every ordinary copy edit - retitling a
    section, changing a label - would then need the gate re-blessed, which is a
    small chore each time and adds noise to the record. Both answers are
    defensible; it is a judgement about how tightly you want a client-facing
    document pinned. Nothing is built either way, and nobody is waiting on you
    to touch anything - just say widen it or leave it and we will do the rest.
    On the numbers: mini re-audited both of yesterday's blockers independently
    and both hold, and mini found no wrong number and no false claim in the
    delivered workbook. Nothing about the Cowork run is blocked on this
    question.

TASK (for mini):
  Queued behind Nick's ruling - do not start it unblocked.
  1. If Nick says WIDEN: the R32 grid gains text/format/position alongside
     formulas. That is gate code and therefore yours. Land it with the
     re-bless in the same commit and declare exactly what the widened grid
     hashes, so the next reader knows what a GOLDEN on R32 does and does not
     promise. If Nick says LEAVE IT: record the ruling in the leg note on R32
     so the formula-only scope is a stated decision rather than an accident,
     and close it.
  2. Either way, independent of the ruling: your bind_root() root-binding is
     the load-bearing fix and it is new code on the gate's own import path. If
     you have not already, satisfy yourself that a --prove pass still resolves
     app modules from the BASELINE tree and not from HOME after the stale-entry
     eviction on re-bind - the failure mode is silent and reports GOLDEN.
  3. No action for me pending. VS_NOTES is corrected on both counts.
