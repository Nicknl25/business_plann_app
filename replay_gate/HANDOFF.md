STATUS: awaiting-Nick
TURN: 2/16
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
TASK (to mini):
  AUDIT A-124 TURN 1 at the tier VS declared (NEIGHBOR-CHECK; goldens did NOT
  move so no FULL apparatus). Verify:
   1. Single authority, no third read: finmo_bridge._sba_business_loan_interest_rate_and_source
      now takes business_facts (kw) and reads facts.address_state FIRST, then the
      pre-existing (never-populated) financials.state / ops.address_state / ops.state,
      normalized through the EXISTING people_roles._normalize_state_abbrev with
      address_raw=None (field only, no address-token heuristic). The one call site
      (_build_model_input_overlay ~:3627) passes business_facts=business_facts, the
      same dict the runner (post_intake_initial_grid/runner.py ~:296) and the tripwire
      (intake_consult.py ~:6543) already pack from intake_consult_drafts.address_state.
   2. Code normalization complete: _STATE_ABBREV = 50 states + DC; 2-letter passes
      through; unknown text -> None -> national (same as before). Territories (PR/VI/GU)
      only as 2-letter codes - flag if that matters.
   3. Provenance: source_detail.state='IA', sample_count=9, median_rate_pct=6.0 on the
      Millgate replay (Test Files/_redproof_a124_state_plumbing_20260817_green.txt).
   4. No-state path byte-identical: the red-proof asserts the 2-positional-arg call ==
      the address_state=None build (state=None, n=895, 9.0), AND the golden floor
      R31/R32 digests are byte-identical to 08-16 (model_input 1d50e46ab8e6.., finmo
      24e38de4dc98.., workbook cbd764631e98..) - Test Files/_gate_only_R31_R32_20260817_a124.txt.
   5. Fixture re-record legitimacy: replay_gate/_run_artifacts.py was regenerated by
      Test Files/_capture_workbook_fixture.py WITHOUT --allow-refresh (artifacts +
      single-line input re-emitted verbatim); the ONLY diff is the SBA replay KEY
      (new business_facts kwarg) - every recorded VALUE identical, verified by diff
      before commit (SBA value identical because the frozen facts carry no state).
      Test Files/_prove_frozen_input_no_db.py PROVEN post-recapture.
   6. Neighbors (Test Files/_a124_neighbor_check_20260817.txt): debt-schedule policy
      reader returns 0.06/0.015; cash-pass contract (row Q1..Q20 == policy quarterly,
      sba-backed) holds; realism debt-rate check = skipped (generic-tier band, tolerance
      None -> skipped irrespective of rate; warn-only anyway); offline workbook from the
      persisted Millgate row + replayed mij shows Debt Schedule Interest Rate cells
      0.01875 (stub) then 0.015 (Test Files/_a124_millgate_replay_workbook.xlsx).
   7. ONE :5050 listener (pid 7288, log _logs_persona_20260817_180113.txt); declared-vs-actual.
  Flags for Nick (not built, per task): (a) the resolver has NO thin-cohort guard - the
  only guard is no-rows -> drop state; Iowa n=9 is used as designed; (b) the frozen
  golden facts carry ONLY business_name (business_facts_json fallback shape) whereas
  production packs address_state - the goldens therefore do not exercise the state
  path (a fixture-shape decision, not a defect); (c) live confirm: the next system-run
  of any draft with a stated state will stamp source_detail.state in model_input -
  the offline replay ran the exact production builder with the runner's exact
  business_facts packing, but no new planning run was spent this turn.
  Green -> stop (awaiting-Nick).
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_redproof_a124_state_plumbing.py (+ _20260817_green.txt); Test Files/_gate_only_R31_R32_20260817_a124.txt; Test Files/_a124_neighbor_check_20260817.txt; Test Files/_a124_millgate_replay_workbook.xlsx; replay_gate/_run_artifacts.py (re-record)
  SUMMARY: A-124 state plumbing SHIPPED. Resolver reads business_facts.address_state
  (the one draft-row authority the runner/tripwire already pack), normalized via the
  existing people_roles._normalize_state_abbrev to the 2-letter ProjectState; cascade /
  median / window / stub untouched. Red-proof: pre-fix tree RED (state=None, n=895,
  9.0, q 0.0225) -> fixed tree GREEN (state=IA, n=9, median 6.0, q 0.015; stub 0.01875;
  Y1 interest on persisted balances 440,010.5 x 0.015 = 6,600.16 vs 9,900.24 old).
  No-state path byte-identical; golden floor R31/R32 GREEN, digests byte-identical
  (goldens did NOT move -> neighbor-check stands, no canary). Fixture re-recorded for
  the new replay key only (values identical, no-DB freeze PROVEN). Backend restarted,
  ONE :5050 listener. DECLARED-vs-ACTUAL: matches - neighbor-check with the named
  neighbors (1)-(6), canary skipped as declared (goldens unmoved), one extra: realism
  check reported skipped (generic tier) rather than in_band; no scope beyond the TASK.
RESULT:
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_redproof_a124_state_plumbing.py (re-run by mini: GREEN on HEAD; RED (5 failing: Q1..Q20 0.0225, state=None n=895) on a throwaway worktree at 725b374^ with the same script - red for the RIGHT reason); replay_gate --only R31,R32 re-run by mini @ 79a4011: 2/2 clear, digests model_input 1d50e46ab8e6 / finmo 24e38de4dc98 / workbook cbd764631e98 byte-identical to 08-16; Test Files/_prove_frozen_input_no_db.py PROVEN; git show 725b374 (finmo_bridge.py +22/-3, _run_artifacts.py); _handoff/logs/watcher.log:16654-16657 (VS TURN PLAN)
  SUMMARY: A-124 audited at NEIGHBOR-CHECK (VS's tier call honest: an INPUT to the resolver
  changed, not the cascade/median/window/stub/engine math; goldens unmoved). (1) Single
  authority: resolver reads business_facts.address_state first (kw), then the three
  pre-existing never-populated reads; ONE call site (_build_model_input_overlay) passes
  business_facts; production chain confirmed: post_intake_initial_grid/runner.py:296-306
  packs draft.address_state -> sync_planning_state_to_finmo -> build_python_model_input_json
  -> overlay -> resolver (tripwire intake_consult.py:6543 same). No third read added.
  (2) Normalization: _STATE_ABBREV = 51 entries (50+DC), 51 distinct codes; 'Iowa'/'iowa'/
  ' IA '->'IA'; 'Puerto Rico'/'Washington DC'/'Foo'/''/None -> None -> national; 2-letter
  passthrough accepts ANY 2 alpha chars ('PR','XX') -> resolver's own no-rows fallback -> national.
  (3) Provenance on Millgate replay: state='IA', n=9, median 6.0, q 0.015, stub 0.01875 - reproduced.
  (4) No-state path: 2-positional call == address_state=None build (state=None, n=895, 9.0);
  R31/R32 byte-identical. (5) Fixture re-record legitimate: mini diffed old vs new
  _run_artifacts.py by module - 8 replayed fns, the ONLY key that changed is the SBA
  resolver's (new business_facts kwarg {business_name,start_date}), ALL values identical
  incl. the SBA value (0.1, n=2750, state=null); PROVENANCE differs only in the lookup sha.
  (6) Neighbors: VS's _a124_neighbor_check_20260817.txt read (policy reader 0.06/0.015,
  cash contract row==policy, realism skipped generic-tier, workbook Interest Rate row
  0.01875 then 0.015). (7) ONE :5050 listener pid 7288. VS DECLARED-vs-ACTUAL: matches
  (plan lines 16654-16657 = neighbor-check, neighbors (1)-(6), canary skip; actual RESULT
  identical, no scope creep). MINI DECLARED-vs-ACTUAL: matches (re-ran red-proof both
  sides, R31/R32 --only, state-map count, fixture values-only diff; canary skipped).
  Tree note: 79a4011 (docs/STUB_PURITY_AND_ANNOTATIONS_RESEARCH.md, docs-only) landed
  between VS's commit and this audit - not app code, does not affect the verdict.
  TRIAGE of the residuals: (a) NO thin-cohort guard exists (VS correct) - Iowa n=9 used
  as designed; new behavior = Nick's decision, not built (needs-ruling flag only).
  (b) PRE-EXISTING provenance imprecision now reachable: when the state cohort has ZERO
  rows for a match_basis the resolver falls back to national for that basis but stamps
  source_detail.state=<code> anyway (finmo_bridge.py ~1240) - internal model_input
  provenance only (never printed in the workbook: only 'Source rate' label), no delivered
  number/claim affected -> WONT-FIX under triage; noted for Nick. (c) Goldens do not
  exercise the state path (frozen facts carry only business_name/start_date) - a pinned
  leg for the state-keyed rate would need a fixture that carries address_state, which
  re-baselines the goldens -> Nick's call, not auto-built. (d) Live confirm: the next
  system-run of any draft with a stated state stamps source_detail.state - same standing
  next step as A-122 (Cowork run). GREEN -> stop.
TASK (to VS, when Nick re-arms - NOT a fix turn):
  Nothing to build for A-124. Open decisions for Nick (plain English, no machinery):
  1. Should thin state cohorts (Iowa n=9) be trusted as-is, or should the state rate need a
     minimum sample before it replaces national? Today: no minimum, by design.
  2. Should the golden fixture carry a state so the gate pins the state-keyed rate? That
     moves the golden digests (a legitimate re-baseline turn with the R31 purity protocol).
  3. Next Cowork/system run of any draft with a state = live confirm of A-124
     (source_detail.state stamped in model_input).
