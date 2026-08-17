STATUS: awaiting-VS
TURN: 0/16
TASK:
  FIX A-124 STATE PLUMBING — Nick's ruling 2026-08-17 (research:
  docs/MILLGATE_A124_A125_RESEARCH.md, A-124 section). The SBA 7(a)
  interest-rate lookup (_sba_business_loan_interest_rate_and_source,
  finmo_bridge.py ~:1126-1264) is DESIGNED to key on NAICS + STATE, but
  state never reaches the resolver: it reads financials.state /
  ops.address_state / ops.state (~:1131) and none of those are populated
  - the draft's state lives on intake_consult_drafts.address_state
  ('Iowa') - so source_detail.state=null and a NATIONAL median (9.0%,
  n=895) was used where the Iowa median for NAICS 323111 is 6.0% (n=9).
  Even if plumbed, 'Iowa' would not match ProjectState='IA' (2-letter).
  This is a confirmed defect inside a by-design mechanism. Deal breaker
  named: the forecast interest expense (a delivered number) is computed
  from the wrong cohort - the state-keyed rate the design specifies is
  silently replaced by the national one. EMAIL / DELIVERY PATH OFF-LIMITS.
  TURN-TIMEOUT-MINUTES: 90
  TURN 1 (VS): plumb the state through so the resolver uses the
  state-keyed SBA rate as designed:
   - source the state from the ONE authority the app already holds
     (intake_consult_drafts.address_state / business_address parse - the
     same field the rest of the app trusts) into whatever the resolver
     reads (financials.state or ops.address_state - pick the existing
     read, do not add a third); normalize to the 2-letter code the SBA
     table uses (ProjectState) via an existing state-name->code helper if
     one exists, else a minimal, complete US-state map (this is a
     deterministic lookup, not a heuristic).
   - Do NOT change the cascade, the median, the window, or the stub
     (stub stays the client's stated rate). If the state cohort is THIN
     (the resolver already has a sample_count concept - keep whatever
     thin-guard the design already applies; do NOT invent a new
     threshold; if none exists, note it in the RESULT for Nick and use
     the state cohort as designed).
   - Provenance stamp must show state=<code> and the state-keyed
     sample_count / median (source_detail).
   DECLARE THE TIER (this touches finmo_bridge - the workbook builder /
   engine seam; VERIFY FORWARD in one line: it changes the forecast
   interest rate for every draft with a state -> the delivered Interest
   line moves; if the state-keyed value differs the golden floor legs
   R31/R32 (Sunny_V3, whose state cohort may differ from national) WILL
   move - a legitimate re-baseline, ruled here as EXPECTED if and only if
   the ONLY moved leaves are the interest rate row + its arithmetic
   descendants; prove PURITY leaf-by-leaf (the R31 drift protocol) before
   re-blessing, and state the old vs new rate + cohort n). Expect
   NEIGHBOR-CHECK at least; FULL apparatus if the goldens move (they
   probably do). Red-proof: Millgate 2e198cbf rewound/replayed model_input
   stamps state='IA', Iowa cohort n=9, median 6.0 -> quarterly 0.015;
   stub unchanged 0.01875; Y1 interest = Σ avg balances × 0.015; a draft
   with NO state resolves exactly as today (national). Flip to mini.
  TURN 2 (mini): audit at the tier VS declared; verify the state source is
  the single authority (no third read), the code normalization is
  complete, provenance carries state + cohort n, the no-state path is
  byte-identical to before, and if goldens moved: purity proven
  (interest row + descendants ONLY) before re-bless; ONE :5050 listener;
  declared-vs-actual. Green -> stop.
  (re-armed after the Cowork-tester dirty-tree fault; tree clean now)
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
