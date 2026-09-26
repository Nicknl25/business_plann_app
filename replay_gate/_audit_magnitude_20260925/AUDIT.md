# mini audit, e2c8290b + 2d8e74d8 (2026-09-25)

Tier: NEIGHBOR-CHECK. `_normalize_word_numbers`/`_message_figures` is shared code with 35 call sites, so the neighbors are the parser's own consumers, checked against 4,460 real client messages.

## (1a) The router emitted 620000: CONFIRMED from the store
post_intake_gpt_response_store `53f9a8b240b5` (2026-09-25 17:56:49):
`{"field":"people.rest_of_team_payroll_year1","value_json":"620000"}`. On the next turn (`71a32ae58f50`, 17:56:56) it emitted 620000 again, plus total_team_payroll 855000.
Instrument note: the draft_id stamp on these rows is NULL. They were matched on content. cff222e9 has 0 rows in intake_turn_interpretations and 0 in intake_guard_actions.
The final stored people.rest_of_team_payroll_year1 on cff222e9 is **280.0**, not 620.

## (1b) The sites that wrote the wrong numbers: TWO, both proven by calling the real functions
1. **620 comes from `_rest_inclusion_resolve` (intake_consult.py:4194).** Her turn-84 answer was "No, the six hundred and twenty thousand is just for the nine fabricators...". The old parser returned [620, 620000]. The reference filter removed 620000 because it equals the frame's `stated`, so the fragment 620 was the only "fresh" figure left, and `figs[0]` returned it. Old code returns 620.0; HEAD returns 620000.0.
2. **400, 130, 340 and 280 come from the unlanded-figure backstop.** The chain is `_stamp_unlanded_figures_note` (:16225) -> `_unlanded_figures_disclosure` (:11752) -> `_infer_figure_landing` (:10983, nearest stored value by log distance) -> `_apply_forward_move` (:11190). The router landed 400000 in investment, and the fragment 400 had no home. The nearest stored value was rest-of-team at 620, so the forward-move wrote it there: "It looks like you mean rest-of-team payroll - I've set it to $400" (transcript turn 117, and turn 123 for $130).

Is this hardcoding? No. It is a second reader: code re-parses her sentence and writes its own reading over the router's.

## (1c) The new normalizer emits wrong figures the old one never did: DEFECT
The tokenizer keeps "." inside word tokens (`[^a-z0-9.]+`), so a scale word that ends a sentence ("hundred.", "thousand.") is not recognised as a scale word:

| said (real client sentence from the corpus) | old | NEW |
|---|---|---|
| About five hundred. | 500 | **5** |
| About two hundred. / About seven hundred. | 200 / 700 | **2 / 7** |
| Six thousand eight hundred. | 800, 6 | **6008** |
| Thirty-eight thousand four hundred. | 400, 38 | **38004** |
| Twelve thousand eight hundred. | 800, 12 | **12008** |
| Three million eight hundred thousand. | 800, 800000, 3 | **3,000,800,000** |
| About one million one hundred and eighty thousand. | 180, 180000, 1 | **1,000,180,000** |
| About three point eight million. | 3, 8 | 3, 8 (headline case NOT fixed with a period) |
| About twenty thousand. / About nine thousand. | 20 / 9 | 20 / 9 (NOT fixed) |

Other new wrong figures: "between five and six thousand a month" gives **11000** ("and" joins two units), and "half a million" gives **1,000,000**.
36 real client messages end a spoken amount in punctuation (sentence_final_real_messages.txt).
PROVEN to reach the writer: `_stamp_unlanded_figures_note` on "Three million eight hundred thousand." with the router's 3800000 patched puts **3,000,800,000** into `_unlanded_note`. `_infer_figure_landing` then proposes it as current_revenue. `_figure_stated_in_message(500, "About five hundred.")` was True and is now False.

## (1d) Pin shape: SHAPED LIKE VERIFICATION
None of the 26 SPOKEN_AMOUNTS rows ends in punctuation, but real clients speak in sentences. The pin also passes on a parser that sends "About five hundred." to 5.
The red-proof claim (3 of 5) reproduces and fails for the right reason.

## (2) Rulings a/b/c
- (a) CONFIRMED. The three sites match f1e37211 (fdab2efc has 3 "READ THE NUMBER" markers and HEAD has 3). In the ops leaf, the `_conv` corrections above the `continue` still run.
  In the stage guard, the stage-default-zero drop is now unreachable. f1e37211 did the same, so it is inside the ruling.
  Revert-diff site ~1304 is the ops leaf (restored). Site ~1603 is NOT this class: it is the NO REVENUE ECHO (09-14). The revert re-added `current_revenue = company_revenue_total_year1` in `_sync_financials_consult_persistence_state`, and that is still missing. It is a different ruling, so it is flagged for Nick, not fixed.
- (b) CONFIRMED in the delivered plan. Merrifield's bundle v1/v2 has debt_schedule[0] quarterly 0.016129 and annual 0.064516, and derived model_loan_annual_rate is 0.064516. 20,000/310,000 = 6.4516%. plan_final reads "Interest rate on term debt | 6.45% annually | Rate on existing workshop borrowing". QA findings: [].
  No other reader of the bundle rate exists. render_plan_v2.js and render_charts.py read only amounts. schedule.py:720 and workbook_payload_contract.py:376 read the schedule rows, not the bundle.
  Changing the bundle key's meaning is writing-side only, so it is inside the ruling.
- (c) CONFIRMED with one process finding. VS's "6/6 red on pre-fix code" is an ARTIFACT: all 6 fail with `AttributeError: bundle has no _debt_row`, including the three (c) tests.
  Reverting only qa.py gives 2 of 3 (c) tests red for the right reason. The third is a non-regression, so it is green on both versions, as it should be.
  `margins_above_band_every_year` keeps its `yearly and` guard, so an empty year list never fires it.
  WONT-FIX: its text says "every projection year" but now lists judged years only. This is an operator-only string.
  WONT-FIX: fewer than 3 annual rows leaves the band silent. The model is always 20 quarters.
- ruling-a pin: 3 of 4 red for the right reason, confirmed.

## (3) Architecture ruling: _message_figures as a second reader
35 call sites in 22 functions, by what a wrong reading can do:
- **WRITES A NUMBER** (the parser's reading becomes a stored value). These are the ones the router-interprets-once rule forbids:
  - `_rest_inclusion_resolve` :4194 (PROVEN: the 620)
  - `_stamp_unlanded_figures_note` :16225 + `_unlanded_figures_disclosure` :11810-11942 -> forward-move (PROVEN: 400/130/340/280)
  - `_apply_cross_section_driver_correction` :7554/7631/7680
  - `_reconcile_driver_correction` :8352
  - `_capacity_effective_volume_correction` :7363
  - the ops lever guard's conversions :7835-7836
- **SELECTS among the router's own values** (router value wins, parser breaks ties): :21023 capacity twin; :20884/:20912 restated-confirmation.
- **GATE / COPY ONLY** (a wrong reading changes a question or a receipt, not a stored number): :4152, :4222, :6732, :8076/:8087, :9222/:9249/:9253, :9642, :12531, :12878, :21971.
- **DEAD** (early return): :7270-7271, :7989.

Can they use the router's value instead? YES for the two proven writers. The router already sends what they need:
- In the resolving turn, the router's patch carries rest_of_team=620000.
- For an unplaced figure, the router emits `unresolved_figures` with `value_json` AND `client_words`, which is exactly the "figure with no home" the backstop re-derives. Keir turns 17:57:11 and 17:58:39 both carry `{"value_json":"620000","client_words":...}`.

Sizing:
- phase 1, the two proven writers: small to medium, about 2 functions plus the disclosure path.
- phase 2, the driver-correction pair: large, cross-section, and they need the router to emit the lever.
- The gates can stay. They do not write.

Phase 1 changes Nick-ruled behaviour (CW-024 #109 backstop, CW-025/026 inclusion resolve), so it is **NEEDS-RULING, not auto-built**.

## (4) System-run auto-start: VS's premise is WRONG. Nothing was removed.
The auto-start is live at HEAD: `python/api_handlers/financials.py:9` `_start_system_run_in_background`, fired at :341 from `post_financials_handler` (POST /api/financials). The UI calls that endpoint from `frontend/src/intake_form/steps/SubmitStep.tsx:62`, and the Submit button unlocks when the intake completes.
The 12-September revert touched only the four intake files; financials.py was last changed in dcfa2e27.
Merrifield 4381f427 has submitted_at NULL and intake_submission_id NULL. **Nobody pressed Submit.** The run was started by `scripts/run_business_end_to_end.py`, which posts /session, /intake-consult and then /system-run directly (lines 163-200). It never calls /api/financials, so the harness skips the client's real trigger. Restoring means changing the HARNESS to submit through /api/financials, not changing the app.
