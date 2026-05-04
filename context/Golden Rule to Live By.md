# Golden Rule to Live By

This file is a hard invariant for post-intake work.

When working on post-intake, treat this as the architecture rule that everything else must obey.

## The Architecture Goal

Python owns deterministic structure through lookup tables.

GPT owns judgment and decisions inside those table-backed contracts.

FINMO calculates only from model inputs.

So anything predictable should not live as scattered code or prompt prose. It should live in lookup tables and be accessed through lookup functions.

This includes:

- mapping
- process sequence
- contracts
- context payloads
- numeric format rules
- cash policy
- headcount policy
- issue ownership
- driver bundles
- horizons
- any repeatable validation or normalization rules

The deeper goal is consistency: there should be one source of truth for each deterministic concept.

If code conflicts with the tables, the code is legacy and should be converted or deleted.

If a table is missing metadata needed to make behavior deterministic, add columns or rows to the table instead of hardcoding around it.

Where necessary and practical, do not put deterministic behavior inline in phase runners.

Use named functions that call lookup tables. Inline code should be thin orchestration, simple glue, or execution of a table-selected formula/function. If a phase runner starts owning business rules, schedule rules, contract rules, mapping rules, validation rules, or sequence rules directly, that logic should be moved behind a table-backed function or deleted.

`intake_consult.py` should be intake/API orchestration only.

Post-intake behavior belongs in post-intake folders with functions that route through the lookup tables wherever appropriate.

## Working Rule

If something is consistent, structural, repeatable, or contract-like, it belongs in a lookup table or a table-backed function.

If something requires business judgment, GPT decides it, but only inside a table-defined schema, context, and contract.

## Distinct Jobs

The controller runs the play.

The controller's job is orchestration:

- run the correct post-intake sequence
- call the correct phase modules
- enforce process order, cycle limits, time limits, and progress checks
- persist state and diagnostics
- route failures to the correct fail-fast path

The controller must not invent values, choose mappings, repair financial logic, or act as a hidden decision-maker.

Python draws the field and enforces the rules.

Python's job is deterministic structure:

- read lookup tables
- build prompts, schemas, context packets, contracts, and sequence rules from lookup tables
- validate GPT payloads against table-backed contracts
- normalize only where the contract explicitly allows lossless formatting normalization
- compute deterministic derived drivers
- apply accepted GPT decisions to `model_input_json`
- run FINMO
- detect issues using table-backed issue/driver/target definitions
- fail fast when required metadata is missing or a contract is incomplete

Python must not complete, infer, broaden, proxy, top up, rewrite, or silently repair GPT-owned decision content.

GPT makes the business decisions inside the marked lanes.

GPT's job is judgment:

- choose realistic values inside Python/table-defined bounds
- decide ramp shape, headcount shape, R&D applicability, maintenance capex percentage, and repair values when asked by a contract
- reason about business type, stage, planning mode, and strategy
- fill the exact table-backed contract it is given

GPT must not define structure, invent fields, choose unsupported targets, bypass lookup tables, or freeform outside the contract.

FINMO calculates the scoreboard from model inputs.

FINMO's job is calculation only:

- consume model-input drivers
- calculate financial outputs
- preserve the 3-statement model relationship

FINMO should not receive patched output rows from post-intake. Post-intake changes drivers; FINMO calculates outputs.

## Mapping Formula Authority

The mapping table must own driver formula intent, not inline bridge assumptions.

`post_intak_mapping_lookup` is not only a lever-to-target table. It is also the source of truth for:

- which source fields seed a model-input driver
- which named formula key Python may use to seed that driver
- which named FINMO formula relationship should result
- which validation formula must pass after FINMO rebuild
- when the row is required
- whether zero is allowed

Formula notes are not authority. Human notes can explain the formula, but machine behavior must use explicit columns such as:

- `seed_source_paths_json`
- `seed_formula_key`
- `finmo_formula_key`
- `validation_formula_key`
- `required_when_key`
- `allow_zero`
- `formula_status`

Python may only execute approved formula keys from the deterministic formula registry. SQL selects the key; Python executes the known implementation. If SQL names an unknown formula key, the app must fail fast before the run proceeds.

Before each run, including production runs, runtime table integrity must validate the mapping formula contract.

After each FINMO rebuild/final run state, post-intake fail-fast must validate mapped model-input rows against the mapping table formula contract. For example, if a row is `percent_of_revenue`, the FINMO field must equal revenue times that mapped model-input ratio. If the mapping row says zero is not allowed when revenue is positive, zero must fail immediately.

This rule exists to prevent bugs where a bridge function silently interprets an intake value differently than the mapping table intended.

## Required Schedule Invariant

Some model-input lines are deterministic schedule outputs. Those schedules are not optional guidance.

These schedules must be built, applied to model input, reflected in FINMO, and persisted where applicable:

- payroll schedule
- debt schedule
- depreciation schedule

If a required schedule is missing, skipped, contradicted by model input, contradicted by FINMO, or bypassed by legacy logic, the run must fail fast at the boundary where the mismatch is detected.

The schedule is the source for the model-input driver values. The model-input driver values feed FINMO. FINMO calculates outputs.

Do not let GPT or legacy convergence code directly rewrite schedule-owned model-input rows outside the schedule process.

Client-facing Excel workbooks must preserve the same direction:

- source schedule tabs contain the editable operating mechanics
- `Model Inputs` links to those schedule tabs
- `FINMO` links to `Model Inputs` and in-sheet statement rows
- `Checks` validates workbook formula/coherence integrity and labels broken line items
- persisted-output reconciliation is informational when a user edits assumptions; it must show baseline movement without treating a valid scenario edit as a hard model failure

The workbook is a delivery artifact generated from the completed run. It does not replace runtime initialize/finalize validation. Runtime gates protect the run before spend and before completion; workbook checks protect the client-facing model after export.

Debt schedule detail:

- Debt must be handled through the SQL-backed cash policy and debt schedule process.
- The debt schedule method is `amortizing_remaining_balance`.
- The debt schedule subsystem lives in `python/client_intake_and_finmo/post_intake_debt_schedule/`.
- Cash pass calls the debt schedule subsystem; cash pass does not own debt amortization math.
- New borrowing layers into the schedule in the quarter it occurs. The schedule then calculates available principal, required amortizing principal, extra principal paydown, closing principal, interest, debt service, and current-portion short-term debt across Q1-Q20.
- Outstanding principal balance must decline quarter by quarter whenever debt exists and no new borrowing occurs.
- Interest must be derived from the SBA-backed forecast interest rate policy and remaining debt balance.
- Model input and FINMO do not change shape: Python writes the existing Interest Rate, Debt Issuance, Debt Repayment, and Short Term Debt driver rows; FINMO calculates from those drivers.
- If debt schedule policy, interest-rate policy, current-portion short-term debt, minimum principal, or declining-principal behavior is missing or contradicted, fail fast.

## Fail-Fast Ownership

Fail-fast behavior must be centralized by app phase.

The canonical fail-fast package is `python/client_intake_and_finmo/fail_fast/`.

It has three phase-owned areas:

- `intake_fail_fast`
- `post_intake_fail_fast`
- `writtenplan_fail_fast`

Post-intake fail-fast flags, switches, and named failure helpers belong in `post_intake_fail_fast`, not scattered through foundation files or phase runners.

Fail-fast is controlled by the existing `CONVERGENCE_TEST_MODE` environment toggle.

If `CONVERGENCE_TEST_MODE` is not true, fail-fast helpers must not raise.

Phase-specific switches can only further disable fail-fast while `CONVERGENCE_TEST_MODE` is true:

- `POST_INTAKE_FAIL_FAST_ENABLED=false`
- `INTAKE_FAIL_FAST_ENABLED=false`
- `WRITTENPLAN_FAIL_FAST_ENABLED=false`
- `FAIL_FAST_ENABLED=false`

Disabling fail-fast is a runtime/operator choice. It must not cause Python to silently invent values, complete GPT decisions, bypass mapping tables, or mutate FINMO outputs.

## Current Reality Check

We are past concept and the structural architecture is now close to fully manifested.

Infrastructure is mostly there:

- tables exist
- lookup functions exist
- post-intake has been split out of `intake_consult.py`
- cash, headcount, contracts, context, mapping, prompts, issue detection, and sequence are moving through table-backed structure

Enforcement now exists, but operational proof is still incomplete:

- Golden Rule checks validate table availability and alignment
- retired issue-code literals are guarded against
- issue detector sets are checked against SQL issue mappings
- cash issue emission is gated through SQL-owned cash-pass issue codes
- prompt/schema/context generation is table-backed for post-intake GPT contracts

Stability proof is not fully there yet:

- we have not run enough clean E2Es after the latest separation to say the app consistently obeys the table-first architecture

Current estimate:

- structurally: near 100 percent for the intended table-backed skeleton
- operationally proven: still not fully proven until repeated E2Es pass after the latest cleanup

## Remaining Work

The remaining work is not to invent the architecture. The architecture is clear.

The remaining work is enforcement:

- audit every post-intake phase and confirm it gets sequence, context, contract, mapping, cash, and headcount rules through lookup functions
- delete or convert anything that still defines those rules locally
- make fail-fast errors prove when a table is missing required metadata
- run E2Es and fix only root causes where legacy code conflicts with the table system

The big win is that we now know what correct means.

The next step is to make it impossible for post-intake to operate outside the lookup-table structure.

## Enforcement Added

The app now has structural Golden Rule enforcement in `python/client_intake_and_finmo/post_intake_foundation/`.

The enforcement layer validates these lookup authorities before post-intake starts and before convergence runs:

- `post_intak_mapping_lookup`
- `post_intake_cash_policy_lookup`
- `post_intake_gpt_contract_lookup`
- `post_intake_gpt_context_lookup`
- `post_intake_headcount_policy_lookup`
- `post_intake_process_sequence_lookup`

Runtime dependency binding from `intake_consult.py` is intentionally table-safe. Post-intake modules may receive shared helper functions from the API handler, but uppercase deterministic authority values such as horizons, mapping constants, prompt paths, cash levers, and contract constants are not allowed to overwrite post-intake module/table authority.

The structural guard fails fast if:

- required lookup rows are missing
- required contracts or prompt-context rows are missing
- forecast horizons do not resolve to the contract-backed Q1-Q20 horizon
- process sequence steps do not declare required lookup tables and horizon rules
- issue codes are not backed by mapping-table levers/targets where required
- post-intake prompt files do not reference SQL table authority
- `intake_consult.py` reintroduces forbidden post-intake authority constants

This does not prove operational E2E stability by itself. It proves the structure now has a fail-fast wall around the table-first architecture so later E2E failures should expose real remaining code paths or data gaps instead of silently bypassing the lookup tables.

## Table-Rendered Prompt Concept

Prompts should become a rendering of table data, not another source of truth.

The practical rule is:

- contracts define fields, types, required status, normalization, allowed aliases, horizon rules, lookup sources, and validation rules
- context lookup defines which runtime facts are allowed into the prompt
- prompt text should render those contract/context rows into a readable instruction block
- static prompt prose should stay minimal and only describe the thinking task

That means prompt structure should be:

- static role/task instruction
- generated contract spec from `post_intake_gpt_contract_lookup`
- generated context spec from `post_intake_gpt_context_lookup`
- small task instruction that says to produce a valid payload and not add or omit fields

GPT still decides values, tradeoffs, and realistic shape inside the contract.

Tables control structure, allowed fields, formats, horizons, and validation.

This prevents drift:

- prompt says X
- schema expects X
- validator checks X
- normalizer applies X

All of those should come from the same table-backed contract path wherever possible.

Do not over-automate natural-language reasoning. The goal is not to generate every sentence from SQL. The goal is to generate deterministic contract/context structure from SQL, while keeping business judgment instructions concise and static.

## Production Runtime Validation Gates

Post-intake must have formal initialize and finalize gates. These are production gates, not test-only helpers.

Runtime validation gates are operational gates, not golden snapshot audits. Runtime initialize/finalize validation must validate only the operational lookup tables and runtime payloads needed to run or submit the plan:

- `post_intak_mapping_lookup`
- `post_intake_cash_policy_lookup`
- `post_intake_gpt_contract_lookup`
- `post_intake_gpt_context_lookup`
- `post_intake_headcount_policy_lookup`
- `post_intake_process_sequence_lookup`

Runtime initialize/finalize validation must explicitly exclude `post_intake_lookup_table_snapshot` and static source-code scans. Snapshot comparison belongs to preflight, deploy, or admin audit only. It must not block or govern a normal client run unless the operator deliberately runs the Golden preflight.

The initialize gate runs after the planning run starts and before post-intake spends OpenAI/runtime cycles:

- validates lookup tables and lookup functions are callable
- validates process sequence rows are active and table-backed
- validates GPT contracts, context contracts, horizons, cash policy, mapping rows, formula metadata, and headcount policy
- validates the payroll schedule contract shape before GPT is called: exact OEWS title/FTE fields must be active and legacy role-family/category/title fields must be absent
- treats nonpositive key-person wages as invalid input, not usable client overrides; payroll must resolve them from the NAICS OEWS title universe before the payroll GPT call when the person is OEWS-resolvable, or fail fast with the unresolved person, NAICS, candidate count, and required action
- treats `starting_fte` and `hires` as mechanical continuity fields derived from GPT's selected ending FTE when necessary; Python may normalize those mechanics, but it must not invent OEWS titles, wages, or capacity assumptions
- treats GPT's payroll/revenue target as a sanity anchor inside the table-backed labor-intensity bounds, not an exact landing point that overrides capacity-driven FTE
- reads phase timeouts and max attempts from `post_intake_process_sequence_lookup`; payroll must honor a 180-second total cycle budget and must change process shape instead of extending time when GPT cannot complete the full schedule mechanically
- takes a balance-sheet driver initialization sample from `sql.post_intak_mapping_lookup` formula metadata and the intake record
- identifies balance-sheet forecast obligations that intake omitted, especially formula-backed AR, AP, prepaid expenses, inventory when applicable, deferred revenue when applicable, and debt only when debt policy or existing debt makes it applicable
- validates the sample itself has required mapped rows, formula keys, applicability keys, presence rules, and source-of-truth metadata
- writes `post_intake_initialize_validation_running` and `post_intake_initialize_validation_completed` into `planning_stage`

The finalize gate runs after convergence and cash pass, but before completion:

- validates final `model_input_json` and `finmo_json`
- validates payroll, debt, and depreciation schedule usage
- validates cash phase trace and cash buffer integrity
- validates mapping formula application from SQL lookup rows
- validates the full Q1-Q20 forecast horizon and blocks Q21/partial-horizon leaks
- validates live-quarter model-input rows are numeric and complete
- validates live-quarter FINMO rows have required P&L, balance sheet, and cash-flow fields
- validates revenue reconciles to the three model-input drivers: Capacity x Unit Price x Utilization
- validates payroll reconciles from the persisted headcount schedule into model input and FINMO
- validates the debt schedule reconciles to FINMO issuance, repayment, closing debt, interest, and interest-rate requirements
- validates table-backed balance-sheet drivers reconcile to FINMO formulas and are not left zero merely because stub/intake omitted them
- writes `post_intake_finalize_validation_running` and `post_intake_finalize_validation_completed` into `planning_stage`

These gates must be wired through `post_intake_process_sequence_lookup` and the post-intake runtime validation folder. If the gates fail, the run must not complete. They are the production proof that the table-backed machine is present before the run and still obeyed after the run.

### Balance Sheet Driver Sample Rule

The balance sheet sets the tone for the P&L and forecast world. Stub `Q0` is an intake fact, but missing stub rows do not mean the forecast can ignore those line items.

Initialization must sample every mapped balance-sheet driver from `post_intak_mapping_lookup`:

- read `business_applicability_key`, `forecast_presence_rule_key`, `zero_allowed_reason_key`, `validation_formula_key`, and FINMO formula metadata from the mapping table
- inspect intake/stub data and business context
- compute a formula sample base where applicable, such as revenue for AR/prepaids, operating expense base for AP, COGS for inventory, and debt policy/existing debt for short-term debt
- record whether the forecast driver is required even when intake seed values are missing or zero

Examples:

- AR cannot disappear just because `ar_balance` was missing at intake when live revenue exists.
- AP cannot disappear just because `ap_balance` was missing at intake when operating expense activity exists.
- Prepaid expenses cannot disappear just because intake omitted them when revenue exists.
- Inventory is required when inventory business context or inventory seed says it applies.
- Deferred revenue is required when the business model has subscriptions, deposits, retainers, memberships, upfront payments, or similar deferred-revenue behavior.
- Debt is not forced. Debt is governed by cash strategy, cash policy, debt schedule policy, and existing debt.

Finalize must prove every applicable sampled driver actually appears in model input and reconciles to FINMO. A row existing with twenty zeroes is not enough when the table says the formula base makes it applicable.

## Golden Baseline Snapshot Rule

The active golden baseline is now the pushed commit that carries the exact OEWS-title payroll system and the client FINMO Excel workbook exporter.

Commit `f949316` remains the historical payroll/debt/depreciation baseline, but it is no longer the active baseline for the current system generation.

The app must preserve that behavior unless we intentionally change the baseline:

- Active baseline commit: the git commit created for the payroll roles logic and FINMO output Excel model update
- Historical golden tag: `post-intake-golden-payroll-debt-depr-tables`
- Historical golden run doc: `context/post_intake_golden_baseline_f949316.md`
- Golden SQL baseline table: `post_intake_lookup_table_snapshot`
- Active baseline name: `post_intake_golden_current_payroll_roles_excel_model`

The snapshot table freezes the semantic contents of the critical lookup tables:

- `post_intak_mapping_lookup`
- `post_intake_cash_policy_lookup`
- `post_intake_gpt_contract_lookup`
- `post_intake_gpt_context_lookup`
- `post_intake_headcount_policy_lookup`
- `post_intake_process_sequence_lookup`

Future fixes must not silently drift away from these tables.

The snapshot table is the audit baseline, not a production runtime dependency. `post_intake_lookup_table_snapshot` is checked by `scripts/post_intake_golden_preflight.py` and by deploy/admin review. It is intentionally excluded from runtime initialize/finalize gates so a normal client run validates the live operational machine instead of comparing itself to a stored audit snapshot.

For the current active baseline, `post_intake_lookup_table_snapshot` should be associated with the most recent successful run that produced the payroll roles logic and FINMO Excel workbook output. Refreshing that snapshot is an intentional admin/deploy action, not a runtime side effect.

If an E2E failure appears after the golden baseline:

1. Run `scripts/post_intake_golden_preflight.py`.
2. If a lookup snapshot mismatch appears, decide whether the table change is intentional.
3. If intentional, update the table and refresh the baseline snapshot deliberately.
4. If not intentional, revert or fix the drift.
5. Never patch around the snapshot by bypassing table-backed logic.

Payroll, debt, and depreciation schedules are now part of the standard:

- Payroll must come from the `payroll_headcount_schedule` contract and headcount schedule application.
- Payroll is capacity-primary, not revenue-primary. The correct direction is `capacity -> FTE -> payroll`, while `capacity x utilization x price -> revenue`. Revenue may be used as sanity context, but never as the primary FTE driver.
- Payroll uses exact OEWS titles, not role families, role categories, role titles, aliases, or abstract staffing buckets.
- Python determines the business NAICS and builds the full `oews_state_wages` title universe for that NAICS, with state-specific rows preferred and a national fallback where appropriate.
- GPT owns business judgment inside the SQL-backed payroll contract: capacity labor model, labor intensity class, wage positioning tier and multiplier, positive business-specific capacity units per supporting FTE, exact OEWS titles to staff, FTE timing by quarter, and the payroll/revenue sanity target.
- GPT must select each supporting-staff `oews_occ_title` exactly from the Python-built OEWS title catalog and must return Q1-Q20 FTE rows with `starting_fte`, `hires`, `ending_fte`, and payroll tax/benefits percent. GPT must not provide wages.
- Python owns deterministic payroll arithmetic through `post_intake_headcount_policy_lookup`: exact OEWS wage resolution, key-person injection from intake, wage positioning, annual wage inflation, taxes/benefits, quarter totals, capacity/utilization FTE guardrails, model-input application, persisted payroll schedule, and FINMO reconciliation.
- Payroll/revenue is an end sanity check only. GPT must provide `target_payroll_percent_of_revenue` inside the payroll contract, and Python must validate that target and the final model/FINMO payroll percent of revenue against policy table labor-intensity sanity bounds. The target is an anchor, not an exact-match blocker. This does not drive FTE; it catches incoherent payroll.
- The old universal revenue-per-employee payroll cap/floor, default wage fallback, role-family schedule, and fake universal capacity-per-FTE reasonableness bounds are legacy. If any reappears as active payroll logic, delete it or convert it to the exact OEWS-title, capacity-primary, table-backed system.
- Debt must come from the cash debt schedule policy and persist into `intake_consult_drafts.debt_schedule`.
- Depreciation must come from the deterministic capex/depreciation schedule.
- If any schedule is missing, bypassed, or contradicted, fail fast.

Balance-sheet contextual seeding is also part of the standard:

- `post_intak_mapping_lookup` supplies candidate drivers, applicability keys, value semantics, and min/max bounds. It must not supply universal numeric fallback seed values for live forecast drivers.
- GPT supplies the business-context-specific seed decision through the SQL-backed `balance_sheet_contextual_seed` contract before stage ramp and convergence.
- Python validates that GPT returned every mapping-backed candidate exactly once, checks min/max bounds from the mapping table, applies applicable seeds into model_input Q1-Q20, and fails fast if any applicable seed is missing or invalid.
- AR, AP, inventory, prepaid expenses, and deferred revenue cannot remain zero merely because intake omitted them when business context and formula bases make them applicable.
- This is not a validation bypass. It is producer-side table-backed initialization/derived-driver behavior, and finalize validation must still prove FINMO reconciles to the resulting model-input driver values.

This baseline exists so future Codex sessions know what "working correctly" means before touching new failures.
