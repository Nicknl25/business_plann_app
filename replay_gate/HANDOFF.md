STATUS: awaiting-Nick

TURN: 17/16

TASK:
  Audit the CLOSING of the Payroll Schedule with your own instruments; VS's proofs read, not trusted. Commits: 231b0b1 (contract relaxation + funded-only supporting mix + three tidy items), 4f06f6d (+ re-bless 655d5d7: the payroll coherence tie-out scoped to live quarters after the stub fix broke it), 39d21b1 (the SECOND named-FTE scaler converted), 035838a and 655d5d7 re-blesses, prove 18f2306 (64 legs, 0 DRIFT, landed BEFORE this seed). WHAT WAS DONE: (1) a business may be only its named people - post_intake_mapping now honours allow_empty for arrays (stored on every contract row since April, never read) and sets it on payroll_headcount_grid; the producer-side _validate_payroll_title_rows no longer requires a supporting row in every quarter when there are NO rows; the GPT prompt and the remediation vocabulary say an empty grid is legal. (2) the supporting mix takes titles in weight order while each clears ROUND1_SUPPORTING_MIN_REAL_FTE=0.25 and DROPS the rest instead of flooring them at 0.01; fund none and there is no supporting block. (3) three tidy items, each a sheet that asserted something untrue: the Wage source row is written once and thereafter only where the label CHANGES; the "OEWS title" row is not rendered for a named person (variable block geometry); the stub column carries the engine's real stub payroll instead of showing nothing. (4) BOTH named-FTE scalers are exempt: 3560a08 exempted enforce_labor_scaling_on_payload, and 39d21b1 converted _apply_headcount_coherence_to_key_rows (renamed _headcount_coherence_is_recorded_not_applied) which scaled every NON-OWNER named person by (coherent total - owner)/(current non-owner) - the owner carve-out is why the owner alone read 1.0 on affected plans. ANGLES NICK WANTS COVERED, and the first is the point of this audit: (a) IS THERE A THIRD PATH that writes a named person's FTE? Both scalers were found by noticing an odd number in a built file, not by search. Do the search properly - enumerate every writer of starting_fte/ending_fte/hires on a key_person row across python/, including GPT-authored paths (set_payroll_schedule), the cascade, the restructure, the exhaustion handler and the solver, and either PROVE there is no third path or name it. A population sweep of stored payloads is not sufficient on its own: a path that only fires on shapes absent from the population would pass it. (b) the exemptions on drafts VS did not use, ESPECIALLY ones where named payroll exceeds the target - that is where both defects lived (VS used Bluestem 52cf5792, Understory 7042ce1a, Sunny Glaze cc8b7081, Ironwood 1b9b4e45, Halbrook ecd0e148, Bellweather 46ae584a). (c) allow_empty: what else in post_intake_gpt_contract_lookup carries the flag and was never read - VS found only unified_convergence_decision.retry_reason (a string, unaffected: the flag is honoured in the array branch only) - and CHECK THE LIVE TABLE, not the source: the DB row still read allow_empty=0 through four reruns because contract rows are seeded from _DEFAULT_GPT_CONTRACT_ROWS and only refreshed when _ensure_gpt_contract_lookup_table runs; VS ran it and re-verified (empty grid passes min_items AND the horizon rule; a 1-row grid still fails BOTH). Confirm that, and say whether any other code-side contract edit is sitting un-seeded. (d) each tidy item now asserts something TRUE - including the stub column: the engine's stub payroll is the figure Model Inputs and FINMO use, and the summary must show that and not zero, while headcount cells stay empty rather than asserting zero people. (e) TAMPER-TEST the tie-out VS scoped to live quarters (checks_sheet, "Payroll summary totals equal payroll detail by quarter"): break the summary or the detail on a LIVE quarter and confirm it still goes FAIL, so the scoping removed a false failure and not the check. (f) the five delivered workbooks VS showed: every named person 1.0, the only fraction Understory's stated part-timer at 0.84, Checks!B2 OK on all five, no phantom roles. Deal-breaker rule stands. Standing rules: Bellweather in the neighbour set; read Checks!B2 on every neighbour you build.
RESULT:
  AGENT: mini
  VERDICT: needs-ruling
  ERROR-SIGNATURE: part_time_hours_adapted:derived-fraction-on-named-person
  EVIDENCE: replay_gate/_cw043_audit/mini_payroll_close_findings.md (full write-up); mini_named_fte_population_sweep.txt (1,078 drafts); mini_exemption_probe.py; mini_payroll_close_audit.py --tamper; mini_tieout_probe2.py; mini_stored_vs_rebuilt.py
  SUMMARY:
    The close holds. All six angles measured on artifacts, not on VS's claims.
    (a) THERE IS A THIRD PATH and I have named it: the part-time hours adaptation,
    schedule.py L1657-1662, which sets a named person's FTE = FTE x (wage / OEWS
    floor). Source enumeration proves the writer universe is five sites in ONE file
    (every other file that mentions the keys only reads them); the 1,078-draft
    rebuild agrees - 995 fractional named rows across 194 drafts, and EVERY one
    carries wage_source=client_override|part_time_hours_adapted, zero from any
    other cause. Both scalers are silent.
    (b) The exemption HOLDS with a real control: 400 drafts, forced scale-down and
    scale-up, both call shapes - 0 named FTEs moved, while SUPPORTING FTEs moved on
    398/400. 11 named-heavy drafts VS did not use all rebuild at exactly 1.0.
    (c) LIVE table confirmed: payroll_headcount_grid id 10372 carries allow_empty=1,
    updated 20:01:22 today; retry_reason is the only other carrier and is a string.
    All 108 code-side contract rows diffed against the live table: nothing un-seeded.
    (d) Stub Total Payroll equals Model Inputs AND FINMO to the cent on 8 drafts
    (Halbrook 149,750 as claimed); stub headcount cells are empty, not zero.
    (e) The scoping removed a false failure and NOT the check: stub tamper -> tie-out
    stays OK, summary tamper at Q1/Q5/Q20 -> FAIL every time.
    (f) Five workbooks confirmed: Checks!B2 OK on all five, all named people 1.0,
    Understory's stated part-timer the only fraction, no phantom roles. Bellweather
    FAILs on the pre-existing marketing row only, as VS said.
    THREE THINGS FOR NICK, none a deal breaker, none auto-buildable:
    1. The part-time fraction is DERIVED, not stated - all 995 rows have a stated
       $25,000 wage and the FTE is wage/floor. "Part-time Packer 1" reads 0.88, a
       number the client never said. And that block has NO owner guard; the
       docstring's "an owner is never floored" rests on upstream client_override.
    2. ALREADY-DELIVERED workbooks still carry the old numbers. The exporter renders
       the STORED payload and does not re-run the producer; VS's five read 1.0
       because VS re-authored them today 19:15-19:36. Bellweather (stored 08-17)
       still renders 1.07->1.28 and Stillpoint (07-30) 1.00->1.07 - both rebuild at
       1.0 through today's code. Backfill or not is Nick's call.
    3. The tie-out preserved by the scoping is near-vacuous on live quarters, and
       this is PRE-EXISTING, not a regression: the summary cell IS the check's
       expected value (H17 = SUMIFS(...) vs ABS(H17 - SUMIFS(...)), same expression
       both sides), so a detail-side drift moves both sides together and cannot fail
       it - measured. Detail corruption is still caught, by "Payroll detail wage and
       tax math". The check's own note overstates what it detects. Strengthening it
       is NEW BEHAVIOR -> Nick decides.
    GATE FINDING (mine): the goldens cannot see this class. R31's frozen draft
    89e5a622 has payroll_headcount NULL; R32/R49's frozen draft 6feac758 has
    headcount_coherence applies=false. So 39d21b1's "R31/R32/R49/R50 unchanged" is
    true but is not evidence, and the prove's 0 DRIFT is not coverage of it. The
    frozen fixture still carries a 0.20-FTE phantom supporting role and a named
    person at 0.27 - the pre-fix shape, re-blessed into the baseline.
    PROCESS FINDING: VS's declared turn-16 plan named ONE change and the turn
    shipped three. 4f06f6d is a legitimate follow-on the live rerun surfaced.
    39d21b1 is not - a semantic re-scope of a shared payroll path, in no part of the
    declared TASK/LOADING/VERIFY. Under split-by-blast-radius it travels alone.
    No canary log exists for 08-28; the five live re-authored drafts are stronger
    evidence, so I close that as satisfied in substance.
    DECLARED-vs-ACTUAL (mine): declared neighbor-check, ran neighbor-check. Declared
    Bellweather plus drafts VS did not use - built Bellweather, EZ Drive 573df641,
    Stillpoint 4fca544b and read Checks!B2 on every one. Declared canary skip - none
    run. Declared the single-line floor - gate.bat --only R31,R32,R49 is 3/3 GREEN,
    R32's live digest a7d2ebcd7f89 matching legs.py and the closed prove. I went
    BEYOND the declared plan in one place: I added the 1,078-draft population
    rebuild, because the source enumeration alone could not tell me how much of the
    population the third path touches.

TASK (for VS, when Nick rules):
  NOTHING TO BUILD YET. Three rulings are owed and two of the three items are NEW
  BEHAVIOR, which is never auto-built. Do not start any of this before Nick speaks.

  Held for ruling 1 (the derived part-time fraction). If Nick rules that a named
  part-timer's FTE must come from intake rather than from wage/floor, that is a
  semantic change to the producer on a shared payroll path - it travels ALONE, full
  blast radius, with a red-proof on a draft that carries a stated part-timer
  (Understory 7042ce1a, Bridgeburn 0be7d198) and a live rerun. If Nick rules the
  derived fraction stays, the only contained piece is an explicit owner guard in the
  L1657 block so the docstring's claim is enforced rather than assumed - that one is
  spot-check and can ride with other cheap work.

  Held for ruling 2 (already-delivered plans). If Nick wants a backfill, it is a
  data migration over stored payroll_headcount payloads, not an app-code change, and
  it needs its own turn with a dry-run count first. NAMED DEAL BREAKER it would
  prevent: a client whose plan is rebuilt or re-delivered reads 1.28 of a named
  employee - a number no one chose and the client cannot act on.

  Held for ruling 3 (the near-vacuous tie-out). Strengthening it means comparing the
  summary against something that is NOT the summary's own formula - that is a new
  check, i.e. NEW BEHAVIOR. Nick decides whether it is worth building at all, given
  that "Payroll detail wage and tax math" already catches detail corruption.

  MINE, not VS's (replay_gate is my territory, recorded here so it is not lost): the
  golden fixtures cannot red on this class, and 6feac758's frozen artifacts still
  carry the pre-fix shape (a 0.20-FTE phantom supporting role, a named person at
  0.27). Re-freezing a fixture touches the golden baseline - full apparatus - so I
  am not doing it inside an audit turn. I will propose it as its own turn.

  WONT-FIX, closed here with reasons: the funded-title filter is a single pass over
  renormalised weights rather than the iterative "take in weight order while each
  clears 0.25" the comment describes - it only ever drops MORE titles, every kept
  title still clears the threshold, so no wrong number reaches a plan. The
  `number(_stub_payroll) or 0` fallback would write a false zero if the "Payroll"
  expense row were ever absent - I found no draft where it is; untested, not broken.
