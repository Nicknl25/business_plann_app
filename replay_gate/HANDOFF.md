STATUS: awaiting-Nick
TURN: 2/16
TASK:
  FIX THE G&A STUB DENOMINATOR — Nick's ruling 2026-08-17. Research w/
  citations: docs/STUB_CELLS_WHY_RESEARCH.md §1 (read it first). DEAL
  BREAKER: the client's own CURRENT overhead is rendered 24% wrong in the
  delivered plan, ABOVE EBITDA, and the app's own coherence gate
  contradicts it on the same draft.
  THE BUG: the G&A STUB (finmo_bridge.py ~:3714, values[0]) = the
  client's real stated dollars (other_opex_absolute - Millgate 31,200/yr
  from the dedicated intake question) divided by the WRONG denominator -
  the SHARED revenue_total_year1, which since 513778e is the CAPACITY-
  CEILING revenue (capacity x price x periods x 0.95 = 1,126,320 for
  Millgate), not the client's stated current_revenue (854,000). Stub =
  0.027701 ($23,657/yr) instead of the client's real 0.036534
  ($31,200/yr). The coherence gate (intake_coherence/evaluator.py:20-29
  BASIS DOCTRINE: G&A pct = other_opex_absolute / stated current_revenue)
  runs 0.036534 on the SAME draft. STRUCTURAL ROOT: every other ratio row
  has a stub/forecast split (cogs_ratio_baseline / cogs_ratio_forecast
  ~:3431/:3541 -> stub :3704 / live :3768; marketing baseline/forecast
  :3706/:3777; taxes_percent / tax_rate_forecast); G&A ALONE has NO
  _forecast twin - g_and_a_ratio_baseline is read at BOTH the stub
  (~:3714) AND the live/forecast (~:3785), so a forecast-basis
  denominator leaks into the today cell. EMAIL / DELIVERY PATH OFF-LIMITS.
  TURN-TIMEOUT-MINUTES: 180
  TURN 1 (VS) - TWO PARTS, fix the number AND the class:
   1. G&A STUB denominator = the client's STATED current_revenue (the same
      basis the coherence gate uses): stub ratio = other_opex_absolute /
      stated current_revenue (Millgate -> 0.036534). The stub is client
      truth: client dollars over client revenue, never the capacity
      ceiling. (Keep the mapping-table seed path's numerator; only the
      denominator for the STUB changes. Rowless/edge cases: if stated
      revenue is missing/0 fall back to whatever the row does today for
      the stub and SAY SO in the RESULT - do not invent a new fallback.)
   2. ADD THE MISSING g_and_a_ratio_forecast TWIN: the FORECAST (Q1-Q20)
      keeps its CURRENT capacity/band basis EXACTLY (read from the same
      variable/derivation it reads today, just under its own name); the
      stub keeps the client-stated basis - mirroring the split every
      other ratio row has. Stub and forecast no longer share a variable,
      so a forecast-aimed denominator change can NEVER again land in the
      today cell. FIX THE CLASS.
   CONSTRAINTS: do NOT change forecast G&A behaviour (prove Q1-Q20 G&A
   byte-identical before/after); do NOT touch revenue_total_year1's OTHER
   consumers (COGS fallback, cohort bucketing - 513778e's retarget stays);
   the dead _rescaled_ga branch and the latent marketing_ratio_baseline
   UnboundLocalError are NOT this fix - note them, leave them; the other
   three stub cells (taxes, depreciation, capacity) are RULED FINE - do
   not touch them. G&A ONLY.
   TIER: DECLARE it (VERIFY FORWARD in one line: this changes a
   workbook-builder money cell (Model Inputs G&A stub -> FINMO Q0 G&A ->
   EBITDA/NI/RE plug/taxes at Q0) so the golden floor R31/R32 WILL move ->
   expect FULL APPARATUS: Sunny_V3 canary + full prove + golden re-bless
   under the R31 DRIFT-PURITY PROTOCOL - the G&A stub cell and its
   arithmetic descendants (Q0 G&A dollars, Q0 EBITDA, Q0 pre-tax/taxes/NI,
   the Q0 retained-earnings plug, anything downstream of the stub G&A) are
   the ONLY leaves that may move; prove leaf-by-leaf that every moved leaf
   traces to the stub-denominator change and NOTHING else hides in the
   drift; the negative control still fails; forecast columns Q1-Q20 for
   G&A byte-identical). Re-bless only after purity is proven; state old
   vs new stub ratio + dollars.
   RED-PROOF on Millgate 2e198cbf: PRE stub 0.027701 (wrong) -> POST
   0.036534 = 31,200/854,000 = the coherence gate's own value on the same
   draft; forecast Q1-Q20 G&A unchanged. VERIFY-FORWARD END-TO-END: a
   draft with stated G&A SUBMITS and BUILDS on the fixed backend (ONE
   :5050 listener) and the built workbook's Model Inputs G&A stub cell =
   stated dollars / stated revenue, FINMO Q0 G&A = the stated quarterly
   dollars (Millgate 7,800). Flip to mini.
  TURN 2 (mini, audit at the tier VS declared): diff confined to the G&A
  stub denominator + the new _forecast twin (grep: g_and_a_ratio_baseline
  no longer read at the live site; forecast twin reads the prior basis);
  forecast Q1-Q20 byte-identical PRE/POST on Millgate + one multi-line
  draft; DRIFT PURITY: independently diff old vs new golden payloads
  leaf-by-leaf and confirm every moved leaf is the G&A stub cell or its
  descendants - anything else = NOT green, do not re-bless; negative
  control red; e2e submit+build ran and the workbook stub cell matches
  stated/stated; other three stub cells untouched; zero email lines;
  ONE :5050 listener; declared-vs-actual. Green -> stop -> Nick.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: R31:UNEARNED-baseline-FrozenLookupMiss
  EVIDENCE: commit 6b6f400 (python/client_intake_and_finmo/finmo_bridge.py ~:3604-3660 stub/forecast split, :3825 live site reads g_and_a_ratio_forecast); Test Files/_redproof_ga_stub_denominator.py -> _redproof_ga_stub_denominator_PREFIX.txt (RED 4 on the stashed pre-fix tree: stub 0.027701, Q0 G&A 5,914.16) / _POSTFIX.txt (GREEN 10); Test Files/_gastub_leaf_purity_millgate_20260817.txt (PURE); Test Files/_gate_R31_R32_PREFIX_shas.txt vs _POSTFIX_shas.txt (identical digests); Test Files/_prove_20260817_gastub.txt (full prove); _canary_gastub_sunnyv3_20260817.txt (Sunny_V3 + stored-payload check); _e2e_gastub_millgate_rerun_20260817.txt (Millgate REAL rerun + workbook cells old vs new); Test Files/_gastub_tripwire_check.py (wrap-gate producer contract PROCEED); C:/dev/Cilient Plans/Millgate Press -- 08-17-2026 20-03-01.xlsx
  SUMMARY: BOTH PARTS BUILT. (1) STUB denominator = STATED current_revenue: g_and_a_ratio_baseline (the stub var) = _table_seed_ratio_for_lever(G&A, annual_revenue=stated_annual_revenue) - same mapping-row numerator (other_opex_absolute), same coerce ladder, only the divisor changed; the anchor is the existing stated_annual_revenue the capacity stub already scales to. Millgate PRE 0.027701 -> POST 0.036534 = 31,200/854,000 = the coherence gate's basis_from_intake gna_pct 0.036534 on the same draft; FINMO Q0 G&A 5,914.16 -> 7,800.01 (Q0 EBITDA 58,745.77 -> 56,859.92, taxes 10,319.91 -> 9,975.43, NI 46,175.86 -> 44,634.49). No-stated-revenue fallback = the forecast value (what the row did before the split; nothing invented) - the golden fixture (CareCompanions, no current_revenue) takes exactly this path, so R31/R32 digests are BYTE-IDENTICAL PRE vs POST (model_input 1d50e46a / finmo 24e38de4 / workbook_formulas cbd76463): the golden floor did NOT move, no re-bless needed - the task's prediction that it WILL move was wrong for this fixture. (2) CLASS: NEW g_and_a_ratio_forecast carries the unchanged prior derivation (dead _rescaled_ga branch -> table seed over revenue_total_year1 -> _coerce_ratio_units) and the LIVE site :3825 reads ONLY the twin; grep: g_and_a_ratio_baseline is now read at the stub site alone. Forecast Q1-Q20 G&A byte-identical PRE/POST (red-proof + delivered workbooks: Q1 7,581.430389 both). LEAF PURITY on Millgate through the production builder: model_input 15,249 leaves -> 1 changed (the G&A stub cell); finmo 2,824 leaves -> 10 changed, ALL Q0: quarter_rows[0].{g_and_a, general_and_administrative, ebitda, taxes, net_income} + their pl[]/cash_flow[] mirrors at values[0]; 0 added/removed; the Q0 RE plug/BS did NOT move (Q0 balance sheet is the intake snapshot). Not touched, as ruled: taxes/depreciation/capacity stubs (asserted untouched), revenue_total_year1's other consumers, dead _rescaled_ga branch (still dead, now on the forecast twin only - noted), latent marketing_ratio_baseline UnboundLocalError (untouched, still latent), zero email/delivery lines. FULL APPARATUS as declared: backend restarted ONCE after the edit (listener pid 29652 @19:51:15 > edit @19:49:50, ONE :5050 listener); Sunny_V3 canary system_run_complete 384s, 0 Traceback/ERROR lines in _logs_persona_20260817_195114.txt, stored stub 0.02849 = 8,000/280,800, workbook Model Inputs C21 0.02849, Q0 G&A 1,999.998 = stated 2,000; then Millgate 2e198cbf REAL rerun (system-run POST, no planning_run_id) on the same listener: completed, workbook Model Inputs C17 0.036534, FINMO Q0 G&A 7,800.009 (Audit Source), Q1+ G&A identical to the pre-fix workbook (only Interest differs old-vs-new = A-124 Iowa rate 0.015/q, not this fix); wrap-gate producer tripwire on Millgate -> PROCEED. Full prove --tier full: 66 legs, 59 behavioural + 5 structural-absence, 0 DRIFT, 0 other failures; R31/R32 UNEARNED - the BASELINE side (5716ba4/9d2c41c) raises FrozenLookupMiss because the fixture was re-recorded for the A-124 replay key only (725b374), so pre-A-124 baselines cannot replay - PRE-EXISTING and gate-side (identical UNEARNED on the stashed pre-fix tree: _prove_R31_PREFIX_tree_20260817.txt); mini's to re-point. Legacy pytest test_module1_substitution_wiring: 6 failed / 3 passed both PRE and POST (pre-existing). Phantom draft 5622879a appeared after the .env.local rewrite at restart (the known vite-reload phantom), untouched. DECLARED-vs-ACTUAL: TASK matches; BLAST-RADIUS full as declared; LOADING as declared plus intake_consult._completion_model_input_tripwire (for the wrap-gate check) and run_intake_bypass/_keystone_rerun (runners); VERIFY: full apparatus ran (canary + full prove + red-proof + e2e submit-path check + real rerun to workbook); ONE divergence: no golden re-bless because the goldens did not move (fixture fallback path) - purity was proven on Millgate instead. VERDICT progress not green: the prove table carries the pre-existing R31/R32 UNEARNED pair.
TASK (to mini, TURN 2 audit at FULL tier as declared):
  1. Diff confined: git show 6b6f400 -- python/ = finmo_bridge.py only; grep g_and_a_ratio_baseline (stub site :3753 + its assignment) / g_and_a_ratio_forecast (:3825 live site + assignment); the forecast twin's derivation is byte-for-byte the prior g_and_a_ratio_baseline derivation.
  2. Re-run Test Files/_redproof_ga_stub_denominator.py --compare Test Files/_ga_stub_prefix_capture.json (GREEN 10) and independently on a throwaway worktree at 6b6f400^ (RED 4: stub 0.027701).
  3. Purity: re-run Test Files/_gastub_leaf_purity.py --dump on 6b6f400^ and HEAD, --diff -> PURE, 11 leaves, all G&A stub / Q0 P&L descendants; ALSO one multi-line draft of your choice: forecast Q1-Q20 G&A byte-identical PRE/POST.
  4. Goldens: --only R31,R32 digests unchanged (1d50e46a / 24e38de4 / cbd76463) - no re-bless needed; confirm the fixture has no current_revenue so the fallback path is what kept them.
  5. e2e: _e2e_gastub_millgate_rerun_20260817.txt + the 20-03-01 workbook (C17 0.036534, Q0 G&A 7,800.01); canary file; ONE :5050 listener; zero email lines in the diff; other three stub cells untouched (POSTFIX.txt lines).
  6. GATE-SIDE RESIDUAL (yours, replay_gate/*): R31/R32 --prove are UNEARNED on the baseline side since 725b374 (fixture carries only the new SBA replay key; baselines 5716ba4/9d2c41c ask with the old key -> FrozenLookupMiss). Re-point both baselines to 725b374 (or record both keys) so the golden legs earn again - the digests themselves have not moved.
  7. Declared-vs-actual: plan at _handoff/logs (TURN PLAN [VS] 2026-08-17 ~19:45) vs this RESULT. Green -> Nick.
RESULT:
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_mini_gastub_audit_20260817.txt (my independent runs); replay_gate/legs.py R31/R32 baselines -> 725b374 (this commit); commit 6b6f400 (VS's fix); C:/dev/Cilient Plans/Millgate Press -- 08-17-2026 20-03-01.xlsx
  SUMMARY: AUDIT AT FULL TIER (as VS declared) - GREEN. (1) Diff confined: 6b6f400 touches ONE app file, finmo_bridge.py :3603-3661 (stub/forecast split) + :3823 (live site reads g_and_a_ratio_forecast); grep: g_and_a_ratio_baseline read at the stub site :3751 only; the forecast twin's derivation is the prior derivation verbatim (rescaled -> table seed over revenue_total_year1 -> _coerce_ratio_units); zero email/smtp/attach lines. (2) Red-proof re-run myself: HEAD GREEN 10; the SAME script on a throwaway worktree at 6b6f400^ RED 4 for the right reason (stub 0.027701, Q0 G&A 5,914.16). (3) Purity independent dumps PRE vs HEAD: model_input 1 leaf (the G&A stub cell 0.027701->0.036534), finmo 10 leaves all Q0 G&A/EBITDA/taxes/NI + pl/cash_flow mirrors, arithmetic checks (dG&A 1,885.85 = dEBITDA; dtaxes = 0.182667 x that; dNI = the rest); NEGATIVE CONTROL: a mutated dump (forecast leaf + taxes stub) -> IMPURE 2 OTHER, the classifier is not vacuous. Multi-line Alderfen 158f6816 (4 lines): stub 0.187094 -> 0.097405 = 146,400/1,503,000 = the coherence gate's value, Q0 G&A 70,300.57 -> 36,599.93 (the client's stated quarterly overhead), Q1-Q20 G&A byte-identical, other three stubs untouched - the CLASS fix holds on multi-line. (4) Goldens: fixture has no current_revenue (nor other_opex_absolute) -> fallback path -> digests unchanged (1d50e46a/24e38de4/cbd76463), no re-bless; VS's 'goldens will move' prediction was wrong for this fixture and VS said so honestly. GATE RESIDUAL DONE (mine): R31/R32 baselines re-pointed 5716ba4/9d2c41c -> 725b374 in legs.py with the reason + a KNOWN-BLIND-SPOT note (this floor cannot exercise the stub denominator; the Millgate red-proof does) - --prove --only R31,R32: both GOLDEN (SAME/GREEN, 0 UNEARNED); --list 66 legs; fast gate on the current build 62/62 clear. With VS's full prove (59 behavioural + 5 structural-absence + 0 DRIFT) the only non-clean rows were these two, now earned -> table clean. (5) e2e: opened the 20-03-01 Millgate workbook myself - Model Inputs C17 0.036534, Audit Source Q0 G&A 7,800.009, Q1 7,581.43 == pre-fix; Sunny_V3 canary system_run_complete, stored stub 0.02849 = 8,000/280,800 MATCH; ONE :5050 listener (pid 29652); Q1+ taxes/NI old-vs-new differ only through the A-124 interest change (Q1 G&A identical). VERIFY-FORWARD: not a model-flow change (a value in an existing cell, ratio in [0,1]); the consequence chain stub -> FINMO Q0 P&L -> workbook was checked at the level it would fail (real system run to workbook + wrap-gate tripwire PROCEED); no unverified plausible consequence. DECLARED-vs-ACTUAL (VS, plan 19:44:03): matches; the one divergence (no re-bless because nothing moved; purity proven on Millgate instead) was declared in the RESULT; 'RE plug moves' predicted, did not (Q0 BS is the intake snapshot) - stated honestly. Mixed-bundle check: G&A only, no bundle. MINE declared-vs-actual: TASK/BLAST/LOADING/VERIFY as declared (canary skipped as declared - VS's canary audited, I changed no app code; legs R31+R32 re-earned; extra: fast gate 62/62 after my legs.py edit).
  WONT-FIX / OBSERVATIONS (no work queued): (a) Q0 NI moves but the Q0 RE/BS plug does not - the Q0 balance sheet is the intake snapshot by design, pre-existing, not this fix, no client-facing wrong number introduced. (b) Alderfen's FORECAST G&A basis (0.187094, ~2x the client's stated 0.097405) - the forecast basis is exactly what Nick's ruling kept unchanged; informational only; whether that 0.187 is the 'dead' _rescaled_ga branch or the table seed over capacity revenue was NOT resolved this turn (VS's 'still dead' claim is unverified either way, harmless to delivered numbers). (c) The golden floor (CareCompanions) is structurally blind to the stub denominator (no stated revenue) - recorded in the R31 proof_note; a stated-revenue single-line fixture would close that blind spot - a gate improvement (mine), not a VS task, queued in MINI_NOTES-terms only if Nick wants the floor to see the stub. (d) legacy pytest test_module1_substitution_wiring 6 failed / 3 passed PRE and POST - pre-existing, not this fix.
TASK (to VS): none - G&A stub denominator class CLOSED GREEN. Nick: the delivered plan's Q0 G&A now equals the client's stated overhead (Millgate 7,800/q = 31,200/854,000 of Q0 revenue), the forecast is untouched, the gate is clean (66 legs, R31/R32 earning again). Next fix turn only on a new deal-breaker.

