# Is the stub clean? / Where do annotations live? — RESEARCH for Nick's ruling (2026-08-17)

NOTHING BUILT. Traced against code, Millgate's persisted model_input /
finmo (draft 2e198cbf, run 3d4e1de9), Kestrelbrook's workbook + run
6055904d, the restructuring log, and Cowork's runlog. Cited.

## PART 2 — IS THE STUB CLEAN?

**Verdict: STUB ADJUSTED — but NOT by any post-intake / executive step.
The contamination is upstream, inside the model_input assembler
(`finmo_bridge._build_model_input_overlay`), where four Q0 cells are
written from derived/policy sources instead of client-stated fields.**

**Every post-intake writer is clean** (index 0 untouched, most with an
explicit comment): target solver `live_idx = 1 + q_idx # skip stub`
(`target_solver.py:519,546`); restoration loop (`:636,761,770`);
orchestrator restoration `range(1, …)` "q0 stub stays at the original
intake-fact value" (`:810, 841-871`); Phase-B price lift `range(2, …)`
(`:3790-3805`); adaptation cascade (no values[] writes); balance-sheet
contextual seed preserves `values[0]` (`contextual_seed.py:247-282`);
headcount schedule reads the stub out and writes it back verbatim
(`schedule.py:3595, 3719`); fitted bands `range(1, …)`
(`band_fitting.py:288, 350`); revenue authoring `range(1, …)`
(`:238-239`); exhaustion handler, funding handler, amalgamated
revise_operating_model (`range(1, …)`), executive protocol ("stub 0
facts cannot be modified", `response_tools.py:166`); restructure
`apply_candidate` `range(2, …)` "Q1 always stays stated reality"
(`searcher.py:303, 379-488`); contract enforces `periods_stub_first_then_
live` with `valid_quarter_indices = [1..20]`
(`finmo_model_input_contract.py:815-826`). Design intent documented in
`docs/phase_9_p3_7_q1_stub_alignment_audit.md` ("System must NOT modify
it"). One latent hazard: `joint_solver.py:156` multiplies the whole
array incl. index 0 — harmless only because synthesized rows are zeroed
at 0/1 (`searcher.py:152`).

**Payroll stub is PURE (Nick's specific question): YES.** Millgate
`values[0] = 41,500 = payroll_total_year1 166,000 / 4` (`finmo_bridge.py:
3585, 3692`) — bare /4, no burden, no roster substitution; the derived
41,026 lands ONLY at Q1+ from the headcount schedule. Balance-sheet Q0 is
all client (cash 62,000 / AR 88,000 / inv 38,000 / AP 54,000 / PPE
260,000 / LTD 120,000 / owner's capital 140,000 = intake verbatim); the
`balance_sheet_contextual_seed` stage seeds Q1+ ratios only.

**Row-by-row stub sources (expenses, `finmo_bridge.py:3682-3811`):**
COGS ← client (`cogs_percent_of_revenue`) ✅; Marketing ← client ✅; R&D
← client ✅; Lease ← client `monthly_rent_expense` ✅; Payroll ← client
✅; Interest Rate ← client `annual_interest / total_debt` /4 ✅;
**G&A ← DERIVED** — `_rescaled_target("sga_percent_of_revenue")` (the
operator-rescaled cohort band from band-fitting) is preferred over the
client seed (`:3591-3593`) and written into `values[0]` (`:3694`);
**Taxes ← DERIVED when intake is silent** — doctrinal cascade envelope →
NAICS band → 0.21 (`:3617-3671, 3706-3716`; comment: "Stub period uses
the same doctrinal effective_tax_rate as live quarters"); **Depreciation
← hard 0** (never assigned; `:3682` fall-through, `:2091/:2137` preserve
the template zero). Revenue drivers: Unit Price ✅ / Utilization ✅
verbatim; **Capacity stub = capacity × back-solve factor** so
cap×price×util = current_revenue/4 (`:3300-3311, 3344-3346`) —
numerically the weekly→quarterly conversion for Millgate (×13) but the
mechanism is a solve against stated revenue, not a stated quarterly
capacity. Retained Earnings Q0 = balancing plug (`:2400`).

**Millgate stub vs client-stated, the misses:**
| row | stub | client-stated | note |
|---|---|---|---|
| G&A | 0.027701 → 5,914/q | 31,200/854,000 = 0.036534 → 7,800/q | **−24% — matches NEITHER the client figure NOR the current fitted target (0.032465) NOR the fitted min (0.027): a superseded band-fit revision frozen in the stub cell** |
| Taxes | 0.182667 | not stated | NAICS band |
| Depreciation | 0 | PPE 260,000 stated → true Q0 depreciation ≠ 0 | hard 0 (the NI-research basis finding) |
Everything else (revenue 213,500, COGS 93,940, payroll 41,500, lease
11,400, marketing 2,000, interest 2,250, all BS balances) = client
verbatim.

**The adjusters, named, and whether the intent is deliberate:**
1. G&A stub ← operator-rescaled cohort band (`:3588-3593`, `:3694`).
   The comment frames the preference as deliberate FOR THE FORECAST
   ("the actual finmo G&A sits at the real level"); it says nothing
   about the stub. **CATEGORY ERROR by Nick's rule** — an executive band
   in the "today" cell — and worse, a STALE one.
2. Taxes stub ← doctrinal tax cascade (`:3706-3716`), explicitly
   deliberate ("same doctrinal rate as live quarters"), but a forecast-
   authority value in a stated-state cell when the client stated no
   rate.
3. Capacity stub ← revenue back-solve (deliberate, benign for weekly
   rows, undocumented as stub policy).
4. Depreciation stub ← hard 0 (engine Q0 P&L is all-zero by design in
   `finmo_model.py:319-390`, but the operating-stub overlay fills every
   OTHER P&L line, so depreciation is inconsistent with its siblings).
5. Retained Earnings Q0 ← plug (standard, documented).

**Two incidental bugs found en route (flag, not fixed):**
- `marketing_ratio_baseline` is assigned ONLY in the `else:` branch at
  `finmo_bridge.py:3561-3566` but read unconditionally at `:3706` →
  `UnboundLocalError` whenever `_rescaled_target("marketing_percent_of_
  revenue")` is non-None. Millgate's persisted fitted_envelope DOES carry
  that target, so a full model_input rebuild after band-fitting on this
  draft would crash — which is also WHY the G&A stub is stale (no
  rebuild since band-fitting).
- `joint_solver.py:156` whole-array multiply (index 0) — latent.

## PART 3 — WHERE DO ANNOTATIONS LIVE?

**Load-bearing correction: the G&A trim was NOT disclosed anywhere.** The
"plain language" Cowork reported was on MILLGATE (not Kestrelbrook), and
it is the generic EBITDA-band tempering sentence emitted at INTAKE CLOSE,
BEFORE the plan build, by `intake_coherence/section.py:1769-1793`
`_converged_suffix()` band-high branch: "…that stress figure actually
sits above the X%-Y% that healthy businesses like yours actually run, so
the full build will temper it back to that level - treat Y% as the honest
ceiling…". It fires on a margin comparison only, is LEVER-BLIND (would
fire identically if the engine had cut payroll or raised price), and
never names G&A, the stated 0.23, or any lever. Cowork's runlog
(cowork_tester/runlog.jsonl:78, CW-038 Millgate, `not_filed.g_and_a_
solver_trim`) stitched that sentence to the internal stamp
`applied_by_target_solver_quarters` and inferred the link. **A weather
forecast, not a disclosure of what happened.**

**Where the Kestrelbrook G&A trim (0.23 → 0.068) actually lives:**
- `post_intake_restructuring_log` id 12316: `cascade_tier V7 Bound
  relaxation`, `reason_code VIABILITY_BOUND_RELAXED` (closed enum,
  `reason_codes.py:27-38` — "audit logs remain queryable by a stable
  vocabulary", NO text field), `original 0.230000 → proposed 0.068065`,
  `applied_by deterministic_floor` — and the sibling row shows the GPT
  reviewer VETOED it (`amalgamated_gpt_vetoed`) and the floor applied it
  anyway; that fact exists nowhere else. **The ONLY surface holding
  stated→landed side by side.**
- `model_input_json` G&A row: only `applied_by_target_solver_quarters`
  (target ebitda_margin, per-quarter applied values). Zero hits for
  relax / annotat / disclos / 0.23-as-original in the 641KB blob.
- Workbook: `Model Inputs` row 33 `General & Administrative | Direct
  model driver | 0.253036 | 0.0648…` — stub and forecast adjacent, no
  label for the 74% drop; source column B names the MECHANISM never the
  authority or the change; `Audit Source` dollars only; `Diagnostics`
  `cascade_exercised_or_documented ✓` says a cascade fired, never what it
  did; **zero cell comments on all 11 sheets** (no comment layer exists);
  full-text scan for relax/trimmed/0.23/23%/stated: no hit.
- `financial_story` (LONGTEXT on drafts AND checkpoints): NULL
  everywhere; its only reader is an issue-code helper. Internal email
  (`workbook_email.py:280`, off-limits, read only): verdict/score/
  handler/realism names — no cascade tier, no lever movement, even
  internally. `repair_guidance_json`: nothing. `planning_run_json.
  post_cascade_completion`: the CASH pass carries real authored English
  (`funding_source_policy.policy_reasons`, e.g. "DEBT SERVICEABILITY
  CEILING: additional debt is capped at $1,353,896…") — the one override
  family with prose — but it is rendered nowhere.

**Can the writing phase read them?** THERE IS NO WRITING PHASE.
`context/system_overview.md:40-42` has three aspirational bullets and no
code pointer; no docx/narrative/plan module in python/, no handler, no
route, no frontend page; the pipeline ends at workbook build → the
internal email. When built off the draft row it gets `model_input_json`
+ `planning_run_json` for free (~17 of 19 stamps, machine keys, no
English) — but NOT `post_intake_restructuring_log`, the only stated→
landed record for the whole cascade, without a new join, and even then
it receives `VIABILITY_BOUND_RELAXED`, not a sentence. Solver logs /
stdout: unreachable. `financial_story` is the obvious column and is
empty.

**Coverage (19 override families):** 17 SILENT (all cascade tiers V1-V8
+ STAGNATION meta, SBA interest replacement [rich structured stamp
`debt_interest_rate_policy`, no words], opening-PPE depreciation, stub-
vs-forecast basis, stage-ramp/judged growth, fitted bands, judged
floors, restructure lines/multipliers, utilization re-expression / the
#343 class); 2 with prose never rendered (cash judgment; R&D
`rationale` — engineer changelog, not client copy); payroll roster
reconstruction PARTIAL (`payroll_provenance.doctrine` is a sentence
explaining the CONCEPT — "intake states WAGES; the Payroll line is
LOADED labor cost" — plus `stated_annual_wages` vs `q1_roster_annual_
wages` and the band; the workbook shows the RESULT rows and `Wage
Source` codes, never "client said 52,000; model used 20,510"). **Zero
overrides carry client-facing prose naming the override.**

**Is there ONE mechanism?** No. ~20 differently-named provenance key
families at different depths (`source`, `wage_source`, `derived_driver`,
`policy_version`, `provenance` ×61, `payroll_provenance` ×1,
`calibration_source`, `driver_source`, `applied_by_target_solver_
quarters` …), each authored by the subsystem that made the move. The
closest thing to a registry — `solver_input.judgment_ledger` (gated by
`_check_judgment_ledger`, Diagnostics `judgment_ledger_complete ✓`) — is
seven booleans + seven source labels: it certifies a judgment WAS
authored, never WHAT it decided, and the cascade is not in it. G&A is
not a one-off disclosure; it is not a disclosure.

**The structural root:** the workbook, model_input, and FINMO all carry
stub (client) and forecast (engine) side by side and never label which
is which (item 13). Label that boundary once and G&A, COGS, interest,
payroll become disclosed together; leave it and every future override
inherits the silence. Combined with Part 2: the stub itself is not
uniformly "client" (G&A/taxes/depreciation cells are derived), so the
labelling must be per-cell-truthful, not a blanket "column C = you".

## For Nick's ruling (nothing built)
S1 Stub purity: make the four Q0 cells client-truthful — G&A ← the
   client's stated figure (`other_opex_absolute` / stated ratio), Taxes
   ← stated rate else an honest "not stated" (not a NAICS band in the
   today cell), Depreciation ← client-basis (or explicitly labelled
   as-stated pre-depreciation — Nick parked A1 vs A2; this is that
   decision surfacing again from the stub side), Capacity stub ← the
   stated quarterly-equivalent, not a revenue back-solve. finmo_bridge =
   workbook builder / golden floor → FULL apparatus when built (goldens
   will move; purity proof per leaf). Plus the two incidental bugs
   (marketing_ratio_baseline UnboundLocalError — real crash risk on any
   rebuild after band-fitting; joint_solver index-0 multiply).
S2 Annotations for the writing phase: there is nothing to consume yet.
   The honest path is (i) label the stub/forecast boundary per cell,
   (ii) mirror `post_intake_restructuring_log` before/afters into the
   draft-reachable artifact (model_input or planning_run_json) with a
   client-plain sentence per reason_code, (iii) render the cash prose
   that already exists, (iv) a single stated→landed registry that every
   override writes to (values, not booleans) — the judgment_ledger shape
   extended with what was decided. This is design work for the writing
   phase, not a fix turn.
