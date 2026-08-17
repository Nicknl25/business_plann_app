STATUS: awaiting-VS
TURN: 0/16
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
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
