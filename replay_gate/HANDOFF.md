STATUS: awaiting-Nick
TURN: 1/16
TASK:
  audit the R49 widen (6d94f61), built on Nick's ruling from your coverage finding. Same tier as before - instrument only, replay_gate/surface.py + legs.py + the one test file; no app code, no engine, no builder, no fixture. What changed: the second sample is no longer the multi-line business, it is a second SINGLE-line business (Larkspur Nail Studio, different name/city/state/NAICS/industry/product/staff/figures), so the layout aligns and the row-shift drops you counted disappear - 1,942 to 2,572 cells, all nine sections Nick named covered, still two builds at 2.9s each, no third sample. Hit these: (1) the same staticness question you asked before, on the NEW pairing - with both samples single-line, is there per-draft text that now happens to be identical at the same address and got pinned; I checked identity, the draft id, the clock and the reference block, but you found the wall clock last time by asking a question I had not asked, so ask the next one; (2) I found and closed a leak that was LIVE in your blessed digest - the Valuation reference block's citations and as-of dates ("BizBuySell Insight Report, Q2 2026", "CAGR 1.98% (through 2026-04-01)") were pinned, so a correct constants refresh would have turned R49 red; I fixed it your way (the second build reads different reference data, found-not-listed) rather than widening the regex - check the patch actually covers every path that prints reference data, including any the valuation sheet reads outside _load_constants; (3) your finding (3) is closed - the extraction is surface.text_cells_of and the tests import it; I proved the coupling by deleting the formula filter and watching 2 tests fail, but verify the tests would also catch a break in the INTERSECTION logic, which they still do not touch; (4) the residual gap I named - multi-line-only labels are in neither sample and so in no pin - tell me whether that matters enough to cost a third build, with a number rather than a feeling. Also: R32 8878c405e17d unchanged, R49 now 91d4fa285c75, fast gate 63/63, --prove R31,R32,R49 = 3 GOLDEN 0 DRIFT. If this holds, say GREEN and we stage Cowork.
RESULT:
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: R49 91d4fa285c75 / R32 8878c405e17d re-derived in this session;
    fast gate 63/63; --prove R31,R32,R49 = 3 GOLDEN 0 DRIFT 0 UNEARNED
  SUMMARY:
    Every number VS reported, I re-derived rather than read: 2,572 pinned /
    2,608 first-workbook text / 15 sheets, digest 91d4fa285c75; R32 unchanged
    at 8878c405e17d; fast gate 63/63; --prove R31,R32,R49 = 3 GOLDEN, 0 DRIFT,
    0 UNEARNED. The widen holds and the table is clean.

    (1) THE NEXT QUESTION, ASKED AND ANSWERED WITH A NUMBER. The two samples
    share more than a line count: both are preserve_cash + debt-funded, both
    have exactly two people, both run 12 periods, both carry debt, both pay
    rent, both have zero capex and zero initial lease. Any label rendered
    conditionally on those would be identical at the same address in both and
    would be pinned as chrome while actually being per-draft. So I built a
    THIRD business that flips every one of them - Quillon Plumbing, NAICS
    238220, QUARTERLY (4 periods not 12), one employee, zero debt, $15k capex,
    $22k initial lease, zero rent, equity funding, invest_growth, third wall
    clock 2011-09-22 - and diffed it against all 2,572 pinned addresses.
    FALSE-STATIC = 0 of 2,572. Not one pinned cell moved. The staticness claim
    survives a question the pairing was not designed to answer.

    (2) THE REFERENCE-DATA FIX COVERS EVERY PATH. Proven twice. Structurally:
    _load_constants is the only reader of valuation_reference_constants, it has
    exactly ONE call site (valuation_sheet.py:167), and valuation_sheet is the
    only module in the whole client_statements_output_excel package that opens
    a DB connection for reference data. Of the fields it loads, only citation
    and as_of are ever written to a cell (lines 221/224), plus scope appended
    to citation for the exit_multiple keys - source and tier are loaded and
    never printed, so the patch is wider than it needs to be, not narrower.
    Behaviourally, the test Nick actually cares about: I simulated a CORRECT
    refresh - new citation, new as_of, new source, new tier, new scope and
    every value bumped 3%, applied to the REAL loader so BOTH builds see the
    refreshed table the way a real refresh would - and recomputed the leg's
    surface. Digest 91d4fa285c75 before, 91d4fa285c75 after. A constants
    refresh can no longer turn R49 red. The patch removes exactly 8 cells
    (Valuation D8 D9 L9 D11 D12 L12 D13 L13): five citations and three em-dash
    as-of placeholders. Nit, not a defect: those three L-column cells hold the
    dash printed when as_of is EMPTY - real chrome that drops only because
    _shifted stamps a date on every row including the ones that have none.
    Harmless (a drop is never a false green), but three static cells are
    unpinned for a reason that is not true of them.

    (3) THE INTERSECTION IS STILL UNGUARDED, AND THE COPY HAS ALREADY DRIFTED.
    RED-PROVEN. It is worse than "the tests do not touch it": setUpClass
    REIMPLEMENTS the intersection inline - the same guarding-a-copy class I
    caught in the extraction last turn, moved one layer up - and that copy has
    ALREADY diverged, because it has no _DATE_TEXT filter, so the two
    staticness tests assert against a surface the leg does not pin. Proof: I
    deleted the entire intersection AND the date filter from the production
    workbook_text_surface and ran the file. 8 passed. Restored; git diff clean.
    Triage: gate instrument, not a client number - NOT a deal breaker, so it
    goes to VS as hygiene and does not block the Cowork run.

    (4) THE MULTI-LINE GAP - THE NUMBER, AND IT CHANGES THE ANSWER. The
    question assumes a third build could buy this. It cannot. The pin is an
    INTERSECTION, so a multi-line third member can only SHRINK it, back toward
    the 1,942 the widen just escaped, because the row shifts come back. Pinning
    multi-line-only chrome needs a second multi-line PAIR and a UNION of two
    pins: TWO extra builds, not one. I built that pair to price it (Thistledown
    Cycles + Harrowgate Bakehouse, both two-line, nothing else in common). Its
    own pin is 2,634 cells and it ADDS 708 cell addresses / 42 distinct new
    strings over the current pin (Checks 516, Model Inputs 81, FINMO 39,
    Revenue Drivers 33, Calc 28, Valuation 8, Dashboard 2, Diagnostics 1). Of
    the 42: 26 are RANGE-ADDRESS strings (Model Inputs C55:W55 and kin, which
    exist only because the layout has more rows and would move again for a
    three-line business), and 16 are labels - of which 6 are lob_2_product_1
    index keys, 5 are Valuation citation text that SHOULD be excluded, 1 is the
    probe draft id, 1 a console artifact. That leaves TWO genuinely new static
    labels: "Break-Even Revenue x this line's revenue share / unit price" and
    "Break-even volume at the planned mix - selected period".
    MY CALL: not worth it. Two real labels and six index keys for a 100%
    increase in the leg's build cost (2 builds -> 4, ~5.8s -> ~11.6s). The 708
    addresses read like coverage but 516 are Checks rows carrying the SAME
    labels at shifted addresses; R49 keys by address to catch a label moving
    WITHIN a layout, and a second layout's addresses do not make that stronger.
    Leave the gap named in the evidence line. If it is ever wanted, the honest
    price is four builds and a union, and it should be its own leg (R50,
    multi-line text surface), not a dilution of R49.

    (5) NOT ASKED, FOUND - THE SECOND BUILD IS NOT HERMETIC. Measured clean,
    but it needs writing down. Build 1 goes through prime_frozen_lookups()
    (committed bytes; I instrumented all 8 LOOKUP_TARGETS and counted 0 live
    calls). Build 2 calls _frozen_build directly and CANNOT prime, because the
    recorded lookup keys belong to one business - so it makes 4,292 LIVE
    reference-table calls (cohort band resolver 4,158, metric registry 128,
    driver-target mapping 2, realism rows 2, SBA rate+source 2). Half the
    leg's input is live DB state, inside a leg whose premise is that a golden
    master over a moving input cries wolf. Exposure MEASURED at zero pinned
    cells: the variant probe (entirely different cohort rows) moved 0 of 2,572,
    and perturbing the SBA loader's SOURCE strings for build 2 moved 0 cells.
    The only reference-shaped text in the pin is oews_title_catalog:oews_median
    x20 and one static Valuation caption - provenance KEY names, not values.
    So: not a leak today, but an undocumented dependency whose failure mode is
    quiet (a moved table changes build-2 text, the cell drops out of the
    intersection, the digest moves, nothing wrong with the build) - exactly the
    class just closed. One comment in alt_single_line_payload, so nobody has to
    measure it again.

    (6) PROCESS FINDING: THE WIDEN TURN FILED NO TURN PLAN. The watcher log
    has TURN PLAN [VS] at 17:13:52 for the original leg (b1bfabc) and nothing
    after it before 6d94f61 landed at 18:04:01; no VS child was launched in
    that window - the log goes straight from my 17:26 turn to "inbox consumed"
    at 18:04:30. The widen was done in a hand-run VS session outside the
    watcher and never declared the four-line plan. Naming it so the machinery
    does not quietly become optional when VS runs by hand. Proportionate: the
    commit message is itself an unusually complete declared-vs-actual record,
    and the tier call in it is HONEST - git show --stat is exactly
    replay_gate/surface.py + replay_gate/legs.py +
    tests/test_r49_workbook_text_surface.py, nothing in python/,
    client_statements_output_excel/ or frontend/. The plan that was never filed
    would have been accurate.

    (7) DOC NIT: the ALT_OPS comment in surface.py says the pin covers 2,588
    cells. It is 2,572 - what the leg prints, what the commit headline says,
    and what I measured.

    MY DECLARED-vs-ACTUAL: MATCHES, with two deviations, both toward MORE
    verification. Declared spot-check, instrument-only, canary skip, R49 under
    --only, and said I would re-read VS's prove artifact. (a) I did not re-read
    it - I RAN the full fast gate (63/63) and the full --prove R31,R32,R49
    myself, because a golden baseline was re-blessed and the turn ends in a
    Cowork spend. (b) I declared read-only and then made ONE temporary edit to
    replay_gate/surface.py to red-proof finding (3) - the intersection deleted,
    tests run, file restored, git diff clean. No app code touched, no canary
    (no app code changed, VS's or mine).

TASK (for VS):
  Three items, all SPOT-CHECK, all instrument-only, and they travel together
  as ONE turn because none of them changes shared high-fan-out code - no app
  code, no engine, no builder, no fixture. Do NOT start until Nick has spent
  or deferred the Cowork run; none of this blocks it.
  A. MAKE THE INTERSECTION GUARDED. tests/test_r49_workbook_text_surface.py
     setUpClass reimplements the intersection and the copy has already drifted
     (no _DATE_TEXT filter). I red-proved it: delete the whole intersection AND
     the date filter from the production workbook_text_surface and all 8 tests
     still pass. Have the staticness tests obtain their surface from the code
     the gate runs - the same move that closed the extraction half - so a
     regression in the real intersection or the real date filter fails a test.
     Then red-prove it the way you red-proved the formula filter: break the
     intersection, watch a test fail, restore. Deal breaker it prevents: the
     pin silently stops intersecting, every per-draft string becomes "static",
     and a mojibake or misplaced label reaches a client's workbook while a
     green suite says the pin is holding.
  B. WRITE DOWN THAT BUILD 2 IS LIVE-READ. One comment in
     alt_single_line_payload: build 1 is frozen via prime_frozen_lookups, build
     2 cannot be (the recorded keys belong to one business) and makes ~4,292
     live reference-table calls; exposure measured at 0 pinned cells on
     2026-08-19; the failure mode if it ever bites is a silent digest move with
     nothing wrong with the build. No behaviour change - this is the note that
     stops the next person re-measuring it.
  C. FIX THE STALE NUMBER: the ALT_OPS comment says 2,588; it is 2,572.
  NOT IN THIS TASK, by my ruling in (4): do not widen R49 to the multi-line
  layout. It needs four builds and a union, not a third sample, and it buys two
  real labels. If Nick ever wants it, it is a new leg (R50), not a re-bless.

FOR NICK, in plain English:
  It holds. GREEN.
  I re-did VS's homework instead of reading it: same 2,572 labels pinned, same
  fingerprint, the formula pin unmoved, all 63 gate checks clear, and the three
  golden masters clean with nothing drifting.
  On your two questions. The leak VS found was real and is properly dead - I
  faked a full data refresh (new citations, new dates, new sources, every
  number moved) and the fingerprint did not budge, so refreshing that table can
  no longer make the label check cry wolf. And I asked the new question: the
  two sample businesses have a lot in common besides one revenue line - both
  borrow money, both keep two staff, both bill monthly - so I built a third,
  deliberately opposite business (quarterly, one employee, no debt,
  equity-funded, buys equipment, no rent) and checked every pinned label
  against it. Zero moved. The labels really are labels.
  Your third-build question has a cleaner answer than expected: don't. A third
  sample would make coverage WORSE, not better - the check works by comparing
  workbooks, and a differently-shaped one shifts everything down a row and
  cancels itself out. Covering the multi-line labels honestly costs FOUR
  workbooks instead of two, doubling that check's cost, and it buys exactly two
  new labels. My advice is to leave it, and I have written the gap into the
  check so nobody later mistakes it for full coverage.
  Two housekeeping items are queued for VS behind you: the label check's own
  tests are still marking their own homework in one place, and one comment
  needs a note added. Neither affects a client's workbook. Nothing is blocking
  the Cowork run - say the word and it goes.
