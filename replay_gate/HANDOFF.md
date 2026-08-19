STATUS: awaiting-Nick
TURN: 1/16
TASK:
  audit R49, the new workbook-text-surface leg (b1bfabc), built on Nick's ruling from your As-of finding. Tier declared by VS: instrument only - replay_gate/surface.py + legs.py + one new test; no app code, no engine, no workbook builder, no fixture; new leg + negative controls + baseline bless + fast gate; no canary, no full prove. What to hit hardest: (1) the STATICNESS RULE - static is earned by intersecting two different businesses rather than by an exclusion list; does that actually hold, or is there per-draft text that happens to be identical across both fixtures and is now pinned into a golden master that will go red for the next client (dates are dropped by shape, but check for anything else per-run that survived - draft ids, timestamps, run stamps, NAICS-specific citation text); (2) the reverse risk - is there STRUCTURAL text that legitimately differs between the two fixtures and therefore silently ESCAPED the pin, so the surface is thinner than it looks (per-line labels are meant to drop, but count what else did and say whether the gap matters); (3) the negative controls - do they bite for the right reason, and is the formula-independence control real or tautological; (4) the shared-door refactor of surface.py - R32's digest is unchanged at 8878c405e17d and I proved that, but the refactor moved the payload assembly both legs depend on, so check it the way you check my claims rather than taking it; (5) the leg id collision I hit and fixed (drafted R33, already taken by CW-031 tier 1) - is there anything else in the gate keyed on leg id that a duplicate would have corrupted, and did any earlier duplicate ever ship. Also standing: you have not said GREEN on the two blockers yet - both record corrections you asked for landed in 66ce906, so close that out too if they satisfy you.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.

RESULT:
  AGENT: mini
  VERDICT: needs-ruling
  ERROR-SIGNATURE: R49:wall-clock-build-date-pinned-into-golden
  EVIDENCE: replay_gate/surface.py (_patch_clock, _SECOND_CLOCK, widened
    _DATE_TEXT, text_coverage) and replay_gate/legs.py R49 proof_note;
    re-blessed digest 4157868b6f89, proven identical at two wall clocks.
    Gate: 63/63 fast GREEN; --prove --only R49 -> 1 GOLDEN, 0 DRIFT,
    0 UNEARNED; R32 independently re-derived at 8878c405e17d.
  SUMMARY:
    (1) STATICNESS - ONE REAL LEAK, FOUND AND FIXED. No identity leaked
    (CareCompanions / Raleigh / Thistledown / Burlington / the draft id / any
    NAICS code: zero hits), but 'Cover'!C12 carried TODAY'S WALL CLOCK,
    "19 August 2026", straight into the blessed golden. cover_sheet renders
    %d %B %Y and the drop-by-shape regex only knew the month-FIRST form. Both
    builds ran in the same second, so it looked static. Proven, not argued:
    move the clock to 2026-08-20 and the blessed digest went 6d1e65edbfe9 ->
    bd37bb3ced66 with nothing wrong in the build. R49 would have gone RED this
    morning and taught precisely the bless-without-reading habit the ruling was
    written to prevent. Root cause of the miss: the bless-time check "zero
    date-shaped cells" was TAUTOLOGICAL - it re-applied the same regex the
    surface had already filtered by, so it could never fail.
    FIXED IN MY OWN FILES (replay_gate is mine): the second business is now
    built AT A DIFFERENT WALL CLOCK (1996-03-07), so build-date text differs
    and drops out BY CONSTRUCTION - staticness over time earned the same way
    it is earned over identity. The regex is now only a second line of
    defence (widened to the day-first and month-year forms anyway). The clock
    scan FINDS its targets in the workbook package instead of naming a module,
    and patching NOTHING is a SETUP gap, never a pass. Re-blessed:
    4157868b6f89, 1,934 cells / 15 sheets, byte-identical at two clocks.
    (2) REVERSE RISK - REAL, AND BIGGER THAN THE EVIDENCE LINE SAID.
    1,934 of the first workbook's 2,608 text cells are pinned; 674 escape, and
    only 41 of those are genuinely per-draft. The rest are ROW-SHIFT drops: the
    second business has two revenue lines to the first's one, so everything
    below a per-line block sits at a different ADDRESS. Unpinned as a result:
    FINMO's whole ratio-analysis block (Liquidity, Current/Quick Ratio, Working
    Capital, Leverage, Total/Net Debt), Calc's cost-structure labels, Model
    Inputs' label column below row 11, W2's break-even headers, and 459 of
    1,054 Checks cells. The gap MATTERS: a label moving in any of those
    sections is invisible to R49, which is the exact class it exists for.
    Valuation itself is well covered (110 cells, 8 escapes) and 'As of' is
    pinned at L5, so the founding defect IS caught. The leg now REPORTS
    coverage kept/seen in its evidence line instead of implying fullness.
    Widening it is a scope decision -> Nick, below.
    (3) NEGATIVE CONTROLS - they bite, but they guard a COPY. All four
    injections (move / reword / mojibake / delete) assert the right property
    and would catch the As-of move. But the test reimplements the extraction
    (_text_cells) instead of calling Surface.workbook_text_surface, so it
    tests nothing the gate actually runs. Demonstrated, not asserted: all 7
    tests passed BEFORE and AFTER I changed the production surface. The
    formula-independence control IS tautological - it appends "+0" to five
    formulas, which keeps them "="-prefixed, and the extractor's one line
    startswith("=") guarantees the answer. It proves that filter exists,
    not that the surfaces are independent. Not a blocker; queued to VS below.
    (4) SHARED DOOR - VERIFIED, NOT TAKEN. I re-derived R32 myself:
    8878c405e17d3a68..., unchanged across VS's refactor AND across my clock
    change (clock is optional and R32 never passes it). Full fast gate
    63/63 GREEN after my edit - the honest neighbour sweep for a shared door.
    (5) LEG ID - CLEAN. runner.select() matches on l.id.lower(), so a
    duplicate id makes --only R33 run BOTH legs; prove's _run_one then
    reads that combined exit code as the leg's own, which means a leg could be
    declared PROVEN on the other leg's red. Real corruption vector, correctly
    fixed. I checked every commit that ever touched legs.py back to the 37-leg
    era: ZERO duplicates ever shipped. 54 ids today, all unique.
    (6) THE TWO RECORD CORRECTIONS - GREEN, CLOSED. Verified against source,
    not against VS's account. prove.py's only sys.path.insert is
    probe_baseline's and it inserts <root>/python (line 113); _run_one sets
    PYTHONPATH=HOME (line 204); intake_consult.py line 19 computes its own
    parents[2]; bind_root() inserts <root> then <root>/python at the HEAD of
    sys.path, ahead of PYTHONPATH - so the property is now structural, and
    VS's correction is accurate on every point. And git show 01fd627 shows
    the header tuple becoming an explicit list with (12, "As of") - the E->L
    move, exactly one static-label change, nothing riding along.
    VS DECLARED-vs-ACTUAL: MATCHES. Declared instrument-only / surface.py +
    legs.py + one test / no app code, engine, builder or fixture - and the
    diff is exactly those three files. The tier call was HONEST: VS named the
    shared door itself and proved R32 unchanged rather than hiding it under
    "instrument only". One incomplete verification, which is the finding:
    VS declared the surface "EARNED not asserted", but the date exclusion was
    a hand-written shape list - the one asserted thing in the design - and the
    forward question it invited ("does this surface depend on the wall clock?")
    was never asked. An unverified plausible consequence, and it was live.
    MY DECLARED-vs-ACTUAL: MATCHES, with one deliberate escalation. Declared
    spot-check + named neighbour R32, canary skip, legs R49 + R32. Ran all of
    that, plus - because I re-blessed a golden in a shared door - the full
    63-leg fast gate and --prove --only R49. More verification than declared,
    never less. No canary (no app code changed, mine or VS's).

TASK (for VS):
  Two items, split by radius, and NEITHER is mine to build:
  A. SPOT-CHECK, own turn: make the R49 negative controls guard the CODE THE
     GATE RUNS. tests/test_r49_workbook_text_surface.py reimplements the
     extraction, so it passed unchanged through a real defect in the
     production surface. Point the four injection controls at
     Surface.workbook_text_surface (or at a single extractor imported from
     replay_gate.surface) so a regression in the real filter fails a test.
     Replace the formula-independence control with one that cannot pass by
     construction: perturb formulas through the BUILDER (change an input so
     the emitted formulas differ) and assert the TEXT digest holds. Deal
     breaker it prevents: a mojibake or misplaced label reaching a client's
     workbook while a green test suite says the pin is holding.
  B. DO NOT BUILD until Nick rules (see below): widening R49's coverage past
     the row-shift gap. It changes what the golden covers, so it is his call,
     not a silent re-bless.

FOR NICK, in plain English:
  The label pin VS built was one day from crying wolf - it had accidentally
  photographed the cover page's "19 August 2026" and would have gone red this
  morning with nothing wrong. That is fixed: the two sample workbooks are now
  built on two different dates, so anything that comes from today's date
  cancels out and can never be pinned again. The pin is re-blessed and the
  whole gate is green.
  One question is yours. The pin covers 1,934 of the cover-to-checks labels,
  but about 674 slip through - not because they change per client, but
  because the two sample businesses have a different NUMBER of revenue lines,
  so every block underneath sits one or two rows lower in one of them and the
  comparison misses. That leaves the ratio labels, the cost-structure labels
  and most of the Checks tab unwatched. Closing it means adding a third
  sample business with the SAME number of lines as the first - more coverage,
  one more workbook built every time the gate runs, and a slower gate. Say
  "widen the label pin" and I will do it; say "leave it" and I will write the
  gap into the leg so nobody mistakes it for full coverage later.
