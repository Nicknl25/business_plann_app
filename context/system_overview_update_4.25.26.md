# System Overview Update 4.25.26

This is a Codex-to-Codex handoff for `C:\dev\business_plann_app`. It is written so a future session can recover the current work without relying on chat history. The user wants the app to remain a conventional driver-based 3-statement model:

`intake -> model_input drivers -> FINMO calculations -> financial outputs -> post-intake convergence/cash pass`

The core rule must not change: Python writes/updates model-input drivers only, FINMO calculates the outputs only, and convergence/cash logic must not mutate financial outputs directly.

## User Intent

The user is moving the app away from legacy fuzzy/proxy mapping and toward a deterministic post-intake system.

Key invariants:

- Mapping is SQL-table-driven. The source of truth is the MySQL table `post_intak_mapping_lookup`, loaded through `python/client_intake_and_finmo/post_intake_mapping.py`.
- Solver/convergence should use table-backed driver-to-target relationships, not hardcoded proxy mappings.
- GPT owns business decisions and numeric targets. Python defines the valid solution space, validates contracts, applies model-input driver updates, and runs deterministic FINMO calculations.
- Python must not complete, infer, top up, proxy, broaden, or rewrite GPT-owned decision content after GPT returns.
- Capex is derived by default in the model-input/derived-driver layer. It is not a convergence issue target and should not be repaired directly by solver.
- Cash-related issue detection belongs in the cash pass, not convergence.
- Runtime speed is a correctness concern. A convergence cycle should not exceed 3 minutes. If it does, treat time as a failure to diagnose, not as something to tolerate.
- Backend restarts should be autonomous through `context/ensure_5050_backend.ps1`; do not ask the user to restart Flask.

## Intake Flow

The intake flow collects and confirms business facts before post-intake starts.

High-level stages:

1. Business facts, operations, market, people, and financials are collected/confirmed.
2. The app builds canonical JSON sections such as `operating_model_json`, `marketing_model_json`, `people_json`, and `financials_json`.
3. The quarter grid/model input layer produces `model_input_json`.
4. FINMO is run from `model_input_json` to produce `finmo_json`.
5. Post-intake convergence starts from persisted intake state, not from ad hoc in-memory assumptions.

Important persisted table:

- `intake_consult_drafts`

Useful fields:

- `draft_id`
- `model_input_json`
- `finmo_json`
- `planning_convergence_json`
- `numeric_solver_feedback_json`
- `planning_stage`
- `planning_status`
- `planning_failure_reason`
- `planning_remaining_issue_count`
- `planning_resolved_issue_count`
- `planning_tolerated_issue_count`

## Model Input And FINMO Contract

The app operates like a 3-statement model.

- Revenue, expenses, balance sheet rows, and schedules are model-input drivers.
- FINMO calculates financial statements from those drivers.
- Post-intake may update model-input drivers.
- Post-intake must not patch FINMO output rows directly.

The user repeatedly confirmed this relationship:

`lever -> driver/model_input -> FINMO -> financial outputs`

This is fundamental and must never be redesigned away.

## Mapping System

The new mapping goal is simple:

`lever_id -> target driver / financial model field`

The mapping table is intended to remove old fuzzy behavior:

- No proxy mapping.
- No broad candidate leakage.
- No issue-dependent target switching.
- No derived metric targets such as EBITDA, net income, margins, liquidity ratios, current assets, total assets, or total liabilities.
- Valid targets should be model/FINMO rows that can be moved through direct model-input drivers.

Important mapping components:

- SQL table `post_intak_mapping_lookup`
- `python/client_intake_and_finmo/post_intake_mapping.py`
- `context/post_intake_driver_based_mapping_table_2026-04-22.csv`
- `context/post_intake_driver_based_mapping_table_2026-04-22.md`
- `context/post_intake_driver_based_mapping_formula_grounded_2026-04-22.csv`
- `context/post_intake_driver_based_mapping_formula_grounded_2026-04-22.md`

Recent mapping cleanup intent:

- Keep deterministic lookup-driven mapping.
- Keep issue context and quarter targeting for execution.
- Do not collapse all execution into pure lookup; only mapping itself should be pure lookup.
- Remove/deactivate legacy mapping paths that deviate from the mapping table.

## Capex And Depreciation

The user was concerned that old capex behavior caused capex to grow continuously with capacity. We moved toward a deterministic derived-driver rule.

Current design intent:

- Capex belongs in the model-input/derived-driver layer only.
- Capex is derived by default unless explicit capex values are present.
- Capex is not a convergence target.
- Depreciation remains a FINMO-input percentage; FINMO formulas stay unchanged.
- Final capex used for the quarter drives derived depreciation percent.
- Do not use Alpha tables for capex/depreciation; that experiment was reverted/abandoned.

Conceptual capex model:

- Maintenance capex can increase over time.
- Expansion capex should occur only on structural capacity step changes.
- Capacity remains a real revenue driver; the revenue formula itself does not change.
- The point is to prevent capex from being directly repaired or constantly reshaped by convergence.

Recent code cleanup:

- `capex_footprint_mismatch` was removed from active issue detection/actionability.
- `capex_footprint_mismatch` was removed from convergence issue registry and remaining-horizon paths.
- Capex language was removed from convergence/reality prompts where it made capex look like an actionable repair target.

Verification command used:

```powershell
rg -n "capex_footprint_mismatch|align_asset_intensity" python/api_handlers/intake_consult.py python/client_intake_and_finmo/numeric_execution.py python/client_intake_and_finmo/realism_memo.py python/client_intake_and_finmo/prompts -S
```

Expected result after cleanup: no matches in active files.

## Issue Detection

The user wants issue detection to remain useful and realistic, but not over-perfect or disconnected from the mapping table.

Keep:

- Accounting integrity issues.
- Structural plausibility issues that map to direct drivers.
- Cost structure issues when they target mapped direct rows such as `cogs`, `marketing`, `lease_rent`, or `g_and_a`.
- Revenue/capacity/pricing/utilization issues when they map to direct revenue drivers.

Move to cash pass:

- Cash/liquidity/working-capital-payment issues that cannot be judged until cash pass behavior is applied.

Remove/retire:

- Profitability cash shape issue.
- Retired memo-only issue items.
- PPE ratio checks when they duplicate derived capex/PPE behavior.
- Capex footprint mismatch as an active convergence issue.
- Escalation legacy flow and associated friction paths. The user explicitly said escalation is obsolete and should be deleted, not hidden.

Known current friction:

- Current issue detection uses the SQL-backed taxonomy: `capacity_support_mismatch`, `cost_structure_mismatch`, `p_and_l_flatline`, `working_capital_mismatch`, `liquidity_failure`, `funding_structure_mismatch`, `accounting_integrity_failure`, and `structural_impossibility`. Working-capital issues are cash-pass-owned and should not be treated as convergence blockers.
- Some closure metrics still reference ratios such as `current_ratio`. These are not mapping-table targets and should not be convergence targets.

## Unified Convergence

Unified convergence is the post-intake loop that attempts to resolve non-cash structural issues by letting GPT choose a plan inside Python-defined constraints.

Core flow:

1. Build convergence context from current model input, FINMO, mapping table, issue state, and retry memory.
2. Build deterministic numeric guidance and issue repair packets.
3. GPT returns a structured convergence decision.
4. Python validates the decision contract.
5. Python translates GPT-authored `lever_adjustments` into solver controls.
6. Numeric solver searches only within GPT/Python-approved driver space.
7. Exact updates are applied to `model_input_json`.
8. FINMO recalculates outputs.
9. Verification and issue-state scoring decide whether to accept, retry, tolerate, or fail.

Important files:

- `python/api_handlers/intake_consult.py`
- `python/client_intake_and_finmo/numeric_execution.py`
- `python/client_intake_and_finmo/numeric_solver.py`
- `python/client_intake_and_finmo/quarter_grid.py`
- `python/client_intake_and_finmo/prompts/unified_convergence/reviewer.md`

Recent convergence cleanup:

- `_autofill_unified_lever_adjustments_from_guidance` is disabled and must not generate adjustments.
- `_augment_solver_quarter_target_metrics` should remain normalization-only.
- Post-GPT compensation/scaffold/backfill behavior should be deleted or converted to fail-fast validation.
- Active issue packets should be authoritative for active lever scope. The lever-band scaffold may provide diagnostics/context but must not broaden the active schema when issue packets exist.
- Planner contract now validates lever bounds so ratio/percent drivers cannot emit values outside deterministic scaffold bands.

Important prompt contract:

- Every selected lever must have an explicit `lever_adjustment`.
- Every `lever_adjustment` must include `mapped_repair_targets`.
- Every mapped metric must appear in `primary_target_metric_names`.
- Every primary metric must appear in every targeted quarter row.
- Every targeted quarter must be explicitly present.
- Python will not fill missing mappings, metrics, targets, or lever adjustments.
- Incomplete output should fail.

## Numeric Solver

The numeric solver should not make business decisions. It only fits GPT-defined quarter targets using GPT-approved model-input levers.

Important file:

- `python/client_intake_and_finmo/numeric_solver.py`

Recent solver stabilization:

- `TARGET_METRIC_KEYS` now comes from the post-intake mapping table via `post_intake_driver_target_metric_ids()`.
- Direct one-lever / one-target cases now have a deterministic one-dimensional estimate path.
- This is meant to stop direct mapped targets, such as COGS, from sticking on the GPT anchor when a direct algebraic estimate can close the target.
- The local reproduction showed this works for COGS:
  - Failed live clone: `9709cb773fd3453688761a81901d27bf`
  - Live persisted update stayed at `expenses::Cost of Goods Sold` Q1 `0.32`.
  - Local run of the same saved model/plan returned `0.38820861678004537` and closed the target.

Current unresolved stabilization problem:

- Despite backend runtime probe confirming it loaded the updated `numeric_solver.py`, live E2E persisted results still sometimes show the solver returning the GPT anchor/no-op value.
- Probe confirms:
  - `numeric_solver_module_path = c:\dev\business_plann_app\python\client_intake_and_finmo\numeric_solver.py`
  - `numeric_solver_direct_seed_probe = true`
  - `numeric_solver_direct_estimate_code_probe = true`
- This means the next session should investigate execution path or payload differences, not assume the file is stale.

Fresh failing E2E clones from tonight:

- `fa63518ad2f9493a8ed40688cd646ff9`
- `bf8152f100844dab96fca181c89f8df3`
- `5a7da3983f6340ffbe7630c642ca7c84`
- `9709cb773fd3453688761a81901d27bf`

Most recent source draft:

- `2ce63dfaa4014af88fe5836ba80cee82`

Most recent failure pattern:

- `planning_failure_reason = no_meaningful_progress`
- `current_cycle = 4`
- `target_metric_names = ["cogs"]`
- `targeted_quarters = [1]`
- `allowed_lever_ids = ["expenses::Cost of Goods Sold"]`
- Live result persisted applied update `0.32`, while local reproduction using same saved model/plan produced `0.38820861678004537` and target fit passed.

## Cash Pass

Cash pass should own cash, liquidity, and working-capital-payment issue handling.

The user believes cash strategy interpretation may be wrong if convergence creates large cash buildup while debt is not paid down. The cash pass should be reviewed next after convergence stabilizes.

Current user intent:

- Move cash-related issue checks out of convergence.
- Do not delete cash checks entirely.
- Cash pass should evaluate and fix cash after convergence.
- Strategies such as debt paydown, reinvestment, maintain cushion, and funding should be interpreted during cash pass, not only convergence.

Important files:

- `python/api_handlers/intake_consult.py`
- `python/client_intake_and_finmo/prompts/cash_strategy_review/reviewer.md`

## Backend And E2E Workflow

The user does not want to manually restart the backend.

Use:

```powershell
powershell -ExecutionPolicy Bypass -File context\ensure_5050_backend.ps1 -ForceRestart -StartupTimeoutSeconds 90
```

The helper:

- Checks port 5050.
- Stops the listening process when forced or stale.
- Starts `tmp_run_api_5050_single.py`.
- Probes `/api/runtime-probe`.
- Returns JSON with listener PIDs, runtime probe payload, listener start time, and latest source write time.

Current runtime probe includes:

- `runtime_probe_version`
- `convergence_test_mode`
- `pre_solver_fail_fast_enabled`
- `non_productive_cycle_limit`
- `numeric_solver_module_path`
- `numeric_solver_direct_seed_probe`
- `numeric_solver_direct_estimate_code_probe`

Run E2E with:

```powershell
.\.venv\Scripts\python.exe "Test Files\run_persisted_system_run.py" --draft-id 2ce63dfaa4014af88fe5836ba80cee82 --base-url http://127.0.0.1:5050
```

If the runner times out or fails, inspect SQL immediately. Do not guess from terminal output alone.

Useful SQL diagnostic pattern:

```powershell
@'
import json, os
from pathlib import Path
try:
 from dotenv import load_dotenv; load_dotenv(Path('.env'), override=False)
except Exception: pass
import mysql.connector
DRAFT='<clone_id>'
conn=mysql.connector.connect(
 host=os.getenv('MYSQL_HOST') or '127.0.0.1',
 user=os.getenv('MYSQL_USER'),
 password=os.getenv('MYSQL_PASSWORD') or '',
 database=os.getenv('MYSQL_DB'),
 port=int(os.getenv('MYSQL_PORT') or 3306),
)
cur=conn.cursor(dictionary=True)
cur.execute('SELECT planning_convergence_json, numeric_solver_feedback_json, planning_failure_reason, planning_stage, planning_status, model_input_json, finmo_json FROM intake_consult_drafts WHERE draft_id=%s LIMIT 1', (DRAFT,))
row=cur.fetchone() or {}
conv=json.loads(row.get('planning_convergence_json') or '{}')
print(row.get('planning_stage'), row.get('planning_status'), row.get('planning_failure_reason'))
print({k: conv.get(k) for k in ['status','failure_reason','current_cycle','solver_invoked','solver_execution_state','remaining_issue_count','resolved_issue_count','tolerated_issue_count','targeted_quarters','target_metric_names','quarters_with_target_misses']})
for key in ['terminal_failure_context','numeric_feedback','alignment_debug_summary','alignment_issue_debug']:
 print('\\nKEY', key)
 print(json.dumps(conv.get(key), indent=2)[:30000])
cur.close()
conn.close()
'@ | .\.venv\Scripts\python.exe -
```

## Current Stop Point

We stopped for the night after adding runtime solver fingerprints and the direct single-metric estimate path.

Latest backend before stopping:

- Port: `5050`
- Listener PID from last restart: `32868`
- Runtime probe showed the new solver probes as `true`.

Do not continue E2E until the next session unless the user asks. If continuing:

1. Run `context\ensure_5050_backend.ps1` with `-ForceRestart`.
2. Verify runtime probe has `numeric_solver_direct_estimate_code_probe=true`.
3. Rerun the E2E for source draft `2ce63dfaa4014af88fe5836ba80cee82`.
4. If it fails, inspect the persisted clone row first.
5. Focus on why live execution persists GPT anchor/no-op updates when local `solve_review_plan()` on the same saved payload returns a direct-fit update.

## Files Most Likely Relevant Tomorrow

- `python/api_handlers/intake_consult.py`
- `python/client_intake_and_finmo/numeric_solver.py`
- `python/client_intake_and_finmo/numeric_execution.py`
- `python/client_intake_and_finmo/quarter_grid.py`
- `python/client_intake_and_finmo/finmo_bridge.py`
- `python/client_intake_and_finmo/post_intake_mapping.py`
- SQL table `post_intak_mapping_lookup`
- `context/ensure_5050_backend.ps1`
- `context/system_overview_update_4.25.26.md`

## Warnings For Next Session

- Do not reintroduce Python compensation logic.
- Do not make capex a convergence target again.
- Do not treat ratios or aggregate output metrics as solver targets unless they are explicitly in the mapping table and genuinely driver-controllable.
- Do not ask the user to restart backend.
- Do not rely on old `best_path`, escalation, or fuzzy mapping behavior.
- Do not use broad scaffold fallback to expand active lever scope.
- Fix classes of bugs, not one surfaced run.

## Update 2026-04-26: Cash, Ramp, Balance Sheet Base, And Current Instability

This section is a handoff for the next Codex session. The system is not stable yet.

### Cash Strategy Update

The cash strategy design was changed from four strategies to three. The user wants `reinvest` removed because it is too broad and unbounded unless it is tied to a specific growth investment model. The remaining strategies should be:

- `maintain_cushion`
- `debt_paydown`
- `shareholder_return`

Cash strategy behavior belongs in the cash pass, not convergence. Convergence should build a coherent operating model first; cash pass should then fund or distribute according to the selected strategy. A hard cash viability gate was added: every live quarter must satisfy `ending_cash >= required_cash_buffer`. A run must fail with `liquidity_failure` if any live quarter remains below buffer after cash pass. Do not allow cash failures to be tolerated.

The cash system has been moving toward a debt-schedule style implementation similar to the depreciation schedule: debt issuance, repayment, interest, and cash-buffer funding should be visible and deterministic, then translated into existing model input / FINMO-compatible rows. Interest rates should come from the non-Alpha SQL loan-rate table when available. The user wants cash to be robust and strategy-driven, not random hard cash buildup.

### GPT Stage Ramp Update

The ramp is now intentionally split into two GPT phases:

- Ramp GPT runs once before convergence.
- Convergence GPT runs after that and must obey the ramp contract.

Ramp GPT creates a `stage_ramp_contract` from business type, business stage, planning mode, scale, and model context. It returns stage-family fields such as:

- `revenue_qoq_growth_target_min`
- `revenue_qoq_growth_target_max`
- `revenue_qoq_default`
- `revenue_qoq_max_spike`
- `fte_qoq_max`
- `fte_qoq_max_spike`
- `utilization_high_watermark`
- `max_spike_count`

Python validates this contract fail-fast, stores it in the business-world contract, and passes it into convergence. Convergence GPT must not change or negotiate this ramp. It is a wall between ramp selection and convergence. Revenue still uses the original formula: `sum(Capacity * Unit Price * Utilization)` across products. Payroll remains Python-derived from revenue plus OEWS/FTE grounding. FINMO formulas do not change.

New fail-fast added on 2026-04-26: `_estimate_stage_ramp_contract_with_gpt()` now has a hard GPT time limit. Default is `45s`, configurable via `STAGE_RAMP_GPT_TIMEOUT_SECONDS`, clamped to `15s..90s`. If ramp GPT hangs, the run fails before convergence with `stage_ramp_contract_timeout`.

### Balance Sheet / Intake Base Forecast Update

Stub 0 remains historical intake fact only. It should stay in `model_input_json` and `finmo_json` as the client-reported intake column, but forecast periods should not mutate stub 0.

The latest design direction from the user is: balance sheet intake is more authoritative than derived P&L intake because balance-sheet inputs are asked more directly. Forecast drivers should be consistent with the authoritative starting balance sheet rather than upsizing the balance sheet to match an inflated P&L. If P&L implies a business larger than the balance sheet supports, P&L should be scaled down or phased over time. Balance sheet should not be automatically upsized to match P&L.

Separately, starting PPE has recently been handled through GPT-generated Q1 forecast starting PPE with a hallucination guardrail: positive integer, annual revenue positive, and `starting_ppe <= 10 * annual_revenue`. This was intended to replace blindly using unrealistic stub PPE as the live forecast base. This area is still philosophically unsettled because the user later leaned toward treating balance-sheet intake as authoritative. Future Codex must be careful not to silently mix these two approaches.

### Current Problems / Instability

The system is significantly unstable right now. Do not claim it is stable from code changes alone. The most recent stress work used controlled completed-intake scenarios, including:

- ClearPaw Veterinary Urgent Care: passed in an earlier run.
- BlueRidge Climate Works: passed in an earlier run.
- IronLeaf Specialty Packaging: still failing.

IronLeaf exposed several class bugs:

- The convergence issue envelope sometimes demanded a revenue target that violated the newly selected ramp contract. Example: mature-loss repair wanted Q1 revenue to jump from roughly `$1.5M` to over `$6M`, while ramp GPT correctly capped operational-stage spikes around `10%`.
- The issue detector then blamed payroll because payroll is revenue-derived. Root cause was not payroll; it was an impossible revenue target envelope.
- A patch capped business-model coherence revenue floors by the stage-ramp feasible move, but the loop still tends to hammer revenue-only repairs when mature losses also require direct cost actions.
- Business-model coherence is currently too revenue-centric. When the revenue floor is ramp-capped and cannot solve mature losses, direct mapped cost targets like `cogs`, `marketing`, `research_and_development`, `lease_rent`, and `g_and_a` need to become part of the active target surface instead of repeatedly targeting revenue only.
- Retry correction grid was added so rejected lever values, for example utilization `1.00` outside `[0.40, 0.84]`, are surfaced back to GPT as explicit correction rows. Verify this actually appears in prompts and changes behavior.
- Progress detection was adjusted so direct table-backed target movement can count as progress even when old driver-path direction metadata is missing.
- Focus lever limits were widened from 6 to 12 because three revenue products require the full 9-lever bundle: Capacity, Unit Price, Utilization for each product. The prior cap caused false missing-product failures.

Important current principle: the ramp contract is a hard world constraint. Convergence issue packets must be built inside that world. If Python asks convergence GPT for targets outside the ramp, that is a Python issue-envelope bug, not a GPT failure.

### Next Session Directive

If continuing stabilization, do not start by redesigning everything. Start with the IronLeaf failure class:

1. Use `context\ensure_5050_backend.ps1 -ForceRestart -Port 5050 -StartupTimeoutSeconds 90`.
2. Rerun the controlled packaging scenario `tmp_stage_scenario_operational_packaging.json`.
3. Inspect the persisted clone row before changing code.
4. Fix the business-model coherence issue packet so it does not target revenue-only when the stage-ramp cap makes revenue insufficient.
5. Keep all mapping table rules intact: direct drivers only, table-backed targets only, no proxy or fuzzy mapping.
6. Do not change payroll derivation, revenue formula, FINMO formulas, or the driver-only/model-input boundary.

## Update 2026-04-29: SQL Table Infrastructure, Contract Lookup, Cash Policy Work, And Current Cash Instability

This section supersedes stale notes above where they conflict. The latest architecture direction is table-driven post-intake infrastructure with three SQL lookup tables. Future Codex should start from these tables and their lookup functions before changing prompt, schema, validation, mapping, or cash behavior.

### Current Non-Negotiable Architecture

The user wants one semantic post-intake architecture:

1. `model_input_json` for Q1-Q20 is the only mutable planning state.
2. FINMO is derived from `model_input_json`.
3. Issue detection reads `model_input_json + finmo_json`.
4. Repair contracts are full 20-quarter contracts, not 4-quarter partial horizons.
5. GPT fills only the Python-defined contract/grid.
6. Python applies only model-input driver updates.
7. FINMO recalculates.
8. Progress is compared from old state to new state.
9. Cash pass runs after convergence and owns liquidity, working capital, funding, distributions, and debt/capital structure behavior.

Do not resurrect legacy partial-horizon convergence, best-path, escalation, fuzzy mapping, ratio/proxy targets, or hidden Python completion paths.

Hard runtime limits are part of correctness:

- A convergence cycle must not exceed 180 seconds total.
- Max convergence cycles must stay 10 unless the user explicitly approves a change.
- Meaningful progress is required between cycles.
- Do not increase timeouts or cycle counts to make a run pass.
- Use `context\ensure_5050_backend.ps1` to manage port 5050. Do not ask the user to restart the backend.

### SQL Source-Of-Truth Tables

There are now three SQL tables that should be treated as infrastructure, not optional helpers.

#### `post_intak_mapping_lookup`

Purpose: single source of truth for post-intake mapping.

What it owns:

- `lever_id`
- direct target driver / FINMO field
- issue code association
- phase ownership such as convergence or cash pass
- mapping status
- cash strategy role metadata where relevant

Rules:

- Mapping must be lookup-driven from this SQL table.
- Do not hardcode separate mapping authority in prompts, issue detectors, solver, or cash pass.
- If an issue cannot tie to mapped direct drivers, delete or redesign the issue. Do not target ratios, aggregate outputs, or proxy metrics directly.
- The table maps drivers/lever ids to direct model-input/FINMO target rows. It does not change FINMO formulas.

Primary lookup file:

- `python/client_intake_and_finmo/post_intake_mapping.py`

Important functions:

- `post_intake_mapping_lookup()`
- `post_intake_driver_target_mapping_by_lever()`
- `post_intake_driver_target_mapping_entry(lever_id)`
- `post_intake_driver_target_metric_for_lever(lever_id)`
- `post_intake_driver_target_metric_ids(...)`
- `post_intake_driver_target_mapping_rows_for_issue(issue_code, phase=...)`
- `post_intake_issue_mapping_contract(issue_code, phase=...)`
- `post_intake_lever_ids_for_cash_roles(...)`
- `post_intake_compact_mapping_lookup_for_levers(...)`
- `post_intake_driver_target_mapping_errors(...)`

Current consumers include:

- convergence issue packets
- convergence prompt mapping context
- solver target metric validation
- model-input repair cell validation
- cash funding/repayment/distribution lever selection
- runtime probes and preflight checks

#### `post_intake_cash_policy_lookup`

Purpose: single source of truth for cash strategy deployment policy.

Current canonical strategies:

- `preserve_cash`
- `balanced`
- `shareholder_return`

Do not bring `reinvest` back as a cash strategy. If old intake text says reinvest/growth/expansion, current canonicalization maps that to `balanced`.

What the table owns:

- cash strategy
- debt-position band
- debt-to-equity min/max band
- cash floor months
- cash ceiling months
- distribution weight
- debt paydown weight
- retain weight
- whether surplus above ceiling must be deployed
- policy status

Important functions:

- `post_intake_cash_policy_lookup()`
- `post_intake_cash_policy_for(strategy, debt_to_equity=...)`
- `post_intake_cash_policy_rows(cash_strategy=...)`
- `post_intake_cash_policy_errors()`

Important behavior:

- Cash buffer/floor and ceiling come from this table.
- Surplus deployment weights come from this table.
- Cash pass should deploy excess cash above the strategy ceiling through mapped levers, not let cash hoard indefinitely.
- Funding sources must still be strategy-aware and mapping-table-backed.
- Short-term debt current portion should be reflected in cash pass/debt behavior.

Recent active code changes in this area:

- `_canonical_cash_strategy_value()` now gives explicit labels priority, so text such as `Balanced. Extra cash should preserve liquidity...` is not accidentally classified as `preserve_cash`.
- `quarter_grid._cash_strategy_context()` has the same explicit-label-priority fix.
- `_cash_strategy_violation_envelope()` now attempts sequential and future-aware surplus deployment so a quarter does not distribute cash that is needed to keep a later quarter above buffer.
- `_normalize_cash_strategy_review_decision_from_funding_plan()` now derives required funding adjustments and deterministic surplus deployment adjustments from the cash envelope and SQL cash policy.
- `_apply_cash_policy_surplus_cleanup()` was added to deploy residual surplus above the strategy ceiling after FINMO recalculation.

Warning: this cash cleanup path is exactly where the current instability remains. Do not assume it is correct yet.

#### `post_intake_gpt_contract_lookup`

Purpose: single source of truth for GPT contract fields, schema, prompt field specs, normalization rules, and validation rules.

The goal is a database-defined contract engine:

- prompts generated from the table
- OpenAI schemas generated from the table
- validators read from the table
- normalizers read from the table
- formatting/rounding rules read from the table

Important functions:

- `post_intake_gpt_contract_lookup()`
- `post_intake_gpt_contract_rows(contract_name=..., grid_name=...)`
- `post_intake_gpt_contract_fields_for_grid(contract_name, grid_name)`
- `post_intake_gpt_contract_field_for_path(contract_name, field_path)`
- `post_intake_gpt_contract_required_field_names(contract_name, grid_name)`
- `post_intake_gpt_contract_alias_to_field_name(contract_name, grid_name)`
- `post_intake_gpt_contract_summary(contract_name)`
- `post_intake_gpt_contract_errors()`
- `post_intake_gpt_contract_openai_schema(contract_name)`
- `post_intake_gpt_contract_prompt_field_spec(contract_name)`
- `post_intake_gpt_contract_normalize_payload(contract_name, payload)`
- `post_intake_gpt_contract_payload_errors(contract_name, payload)`

Contracts currently represented include:

- `unified_convergence_decision`
- `cash_strategy_review`
- `unified_convergence_verification`

Rules:

- No post-intake GPT contract should bypass this table if it can be represented there.
- Strict OpenAI schema failures should be fixed at the contract table/schema-generation level, not field-by-field in random call sites.
- Currency should be normalized/validated as integer dollars.
- Ratios/percentages should be normalized/validated using the contract table precision rules.
- Python may normalize formatting, aliases, and numeric representation where the value is semantically the same. Python must not invent business decisions.

### Prompt And GPT Contract Direction

Use grid-style structured contracts wherever GPT is asked for planning data. The user does not want freeform GPT planning for convergence, ramp, cash pass, or other deterministic contract work.

Current desired pattern:

- Python builds a full grid/contract.
- GPT fills required cells only.
- Python validates every required field.
- Python normalizes harmless formatting.
- Python rejects missing, unmapped, out-of-bounds, or structurally invalid outputs.

R&D toggle is now selected before convergence. If R&D is off, R&D should not be included in the forecast contract rather than being removed after GPT already used it.

Ramp GPT runs before convergence and should produce a 20-quarter, stage-aware ramp. There should be no fallback ramp. If GPT does not provide a valid ramp, fail fast. Ramp is a world constraint for convergence, not a suggestion.

Planning mode, business stage, and ramp must facilitate each other. Established/operational companies should not be forced into startup-style loss ramps unless the actual intake economics require it.

### Issue Detection Current Target Set

The old broad issue set was intentionally replaced. The active conceptual issue set should be:

- `capacity_support_mismatch` in convergence
- `cost_structure_mismatch` in convergence
- `p_and_l_flatline` in convergence
- `working_capital_mismatch` in cash pass
- `liquidity_failure` in cash pass as a hard gate
- `funding_structure_mismatch` in cash pass
- `accounting_integrity_failure` as a hard gate
- `structural_impossibility` as a hard gate

Rules:

- `business_model_coherence` should not be active as a broad standalone issue unless it has been explicitly redesigned. The user wanted it removed because it was too broad and duplicated other checks.
- Capex/PPE ratio checks should remain out of active convergence because capex is derived and PPE is driven through capex/depreciation mechanics.
- Pricing-positioning mismatch, old profitability cash shape, escalation, memo/retired issue items, and legacy mapping-driven targets should stay deleted.
- Flatline detection should not flag lines that are legitimately flat for stretches, such as lease/rent or price. It should catch unfinished/copy-forward output, not legitimate stable drivers.
- Working capital is cash-pass-owned.

### Model Mechanics That Must Not Be Broken

Revenue:

- Revenue remains `sum(Capacity * Unit Price * Utilization)` across up to three products.
- Fail fast if revenue does not equal the three-driver formula.
- Do not target revenue directly as a mapped repair lever; target direct drivers from the mapping table.

Payroll:

- Do not change payroll derivation.
- Payroll uses the existing OEWS/FTE grounding logic.
- Payroll should not be manually rewritten as a generic cost plug.

Capex/depreciation:

- Capex remains derived in the model-input/derived-driver layer.
- Capacity, utilization, and capex interact through structural capacity step changes plus maintenance capex.
- Depreciation uses the depreciation schedule approach so expansion capex does not cause a one-quarter depreciation spike and then disappear.
- FINMO formulas must not be changed.

Stub 0:

- Stub 0 remains historical intake fact.
- Stub 0 should be visible in P&L and balance sheet for user review.
- Stub 0 is not a forecast period and should not be mutated by post-intake convergence.

Balance sheet base:

- The current design leans toward treating intake balance sheet as the authoritative starting state.
- Forecast P&L should be coherent inside that starting balance-sheet reality.
- Do not silently upsize the balance sheet just to make inflated P&L plausible.

### Current Cash Instability Stop Point

The latest work was testing cash strategies after adding the SQL cash policy table and contract lookup table. The `shareholder_return` test passed, but `balanced` remains unstable.

Known passing cash test:

- Source scenario: large profitable software business.
- Passing draft: `64443436e4e149a98501f20e1a0100b8`.
- Strategy: `shareholder_return`.
- Result: `cash_pass_completed`, `completed`, `remaining issues = 0`.
- Runtime was about 138 seconds.
- Distributions were applied heavily, debt issuance and debt repayment were zero because the business did not need funding/debt changes.

Known failing balanced test:

- Source scenario: `tmp_stage_scenario_operational_packaging.json`.
- Source draft seeded for balanced testing: `0f4761bbfa7c4b24b182306ebf763599`.
- Latest failed clone: `0e6ce99c648c4eaa8e9082b8b977f581`.
- Strategy: `balanced`.
- Failure: `liquidity_failure`.
- Failure detail: Q20 ending cash was below required buffer.
- Observed values from the last failed run: Q20 ending cash around `804,947`, required buffer around `865,932`.
- The envelope also had deterministic hard-rule behavior that tried to force Q20 distributions to zero, which suggests the hard-rule/update timing may be wrong: the validation may be seeing a raw cash violation that should have been corrected before final validation, or cleanup may be distributing too much earlier and leaving Q20 short.

Most likely next investigation:

1. Inspect draft `0e6ce99c648c4eaa8e9082b8b977f581`.
2. Look specifically at `planning_convergence_json.cash_validation_envelope.quarter_envelopes[20]`.
3. Compare raw `ending_cash`, `ending_cash_after_hard_rules`, `residual_funding_gap`, `distribution_current_value`, `hard_rule_actions`, and actual applied updates.
4. Determine whether deterministic hard-rule updates are only being reported in the envelope instead of applied before final validation.
5. Fix the class so final validation only sees a model state after deterministic cash hard rules and cleanup have actually been applied.

Do not fix this by increasing cycle count or timeout. Do not hide the violation. Cash viability remains a hard gate.

### E2E And Backend Procedure

Use this backend helper every time:

```powershell
.\context\ensure_5050_backend.ps1
```

The user approved this workflow and does not want to be asked to restart or babysit Flask. If code changes are not taking effect, assume backend is stale and refresh it through the helper.

Probe expectations:

- `mapping_source` should be `sql.post_intak_mapping_lookup`.
- `active_quarter_limit` should be `20`.
- `cycle_timeout_seconds` should be `180.0`.
- `max_cycles` should be `10`.
- cash issue codes should include `funding_structure_mismatch`, `liquidity_failure`, and `working_capital_mismatch`.

Useful run command:

```powershell
.\.venv\Scripts\python.exe "Test Files\run_persisted_system_run.py" --draft-id <draft_id> --base-url http://127.0.0.1:5050 --seed <unique_seed>
```

Useful seeding command pattern:

```powershell
.\.venv\Scripts\python.exe "Test Files\seed_completed_intake_from_scenario.py" "<scenario description>" --scenario-file <scenario.json> --set bootstrap.business_start_date="<date>" --set financials.cash_strategy="<strategy sentence>" --base-url http://127.0.0.1:5050 --seed <seed> --run-system-run
```

### OpenAI / External Instability

Recent tests also hit external API instability:

- Stage ramp GPT timed out under the hard timeout.
- Cash strategy review GPT timed out under the hard timeout.
- Some runner attempts had connection resets immediately after backend restart.

Do not confuse these with business-model failures. If OpenAI is not reachable or times out, record the exact timeout and retry only within user-approved limits. Do not loosen timeouts to hide it.

### Files To Inspect First In A New Thread

- `python/client_intake_and_finmo/post_intake_mapping.py`
- `python/api_handlers/intake_consult.py`
- `python/client_intake_and_finmo/quarter_grid.py`
- `python/client_intake_and_finmo/numeric_execution.py`
- `python/client_intake_and_finmo/numeric_solver.py`
- `python/client_intake_and_finmo/finmo_bridge.py`
- `python/financial_model_engine/finmo_model.py`
- `python/client_intake_and_finmo/prompts/unified_convergence/reviewer.md`
- `python/client_intake_and_finmo/prompts/cash_strategy_review/reviewer.md`
- `context/ensure_5050_backend.ps1`
- SQL tables `post_intak_mapping_lookup`, `post_intake_cash_policy_lookup`, `post_intake_gpt_contract_lookup`, and `intake_consult_drafts`

### Current Working Tree Note At Time Of This Update

At this checkpoint, current code changes include:

- explicit-label-first cash strategy canonicalization in `intake_consult.py`
- matching cash strategy canonicalization in `quarter_grid.py`
- sequential/future-aware cash surplus envelope logic
- deterministic SQL cash policy surplus deployment from `quarter_funding_plan` and cash envelopes
- residual cash policy cleanup after cash-pass FINMO recalculation

These changes have compile-level validation but the balanced cash strategy has not passed yet. Treat this commit as a checkpoint for recovery and continued stabilization, not as proof the cash system is finished.

## Update 2026-04-30: Current Difficulties After Latest Save Point

This section records the latest known difficulties after commit `8cf4d87` (`save current post intake work`). It is intentionally blunt so a future Codex session does not misread partial progress as stability.

### Latest Commit State

- Branch: `intake-stable`
- Latest pushed checkpoint: `8cf4d87`
- Commit message: `save current post intake work`
- The commit saved the current app work but did not prove the system is stable.
- Many temp/debug files remain untracked and were intentionally not committed.

### Payroll Is Currently A Known Broken Class

The most important discovered issue is payroll. Do not treat payroll as solved.

Observed bad row:

- Draft: `57319005e7ad4e26b6197f28724e6732`
- Business: `ApexCloud Workflow Systems`
- Problem: FINMO payroll was around `$30` to `$53` per quarter while revenue was around `$11M` to `$17M`.

Concrete root causes found:

- `financials_json.payroll_total_year1` was `118.0`.
- `financials_json.current_num_employees` was also `118.0`.
- The input phrase was effectively “Use 118 employees,” but the system let that value become both employee count and annual payroll dollars.
- Stub payroll became `29.5`, which is `118 / 4`.
- Payroll derivation then used this bad stub together with the GPT payroll growth grid and backed into an absurd `effective_revenue_per_employee` around `$25B`.
- That produced near-zero implied FTE and tiny payroll.

There was also a second-layer payroll issue:

- The derived payroll fallback currently uses `DEFAULT_REVENUE_PER_EMPLOYEE = 650000`.
- The wage source for that row was `oews_all_occupations_mean:000001`, not a software-specific role/staffing model.
- The resulting recomputed payroll around 10.3% of revenue is not proven correct; it is just `67140 / 650000`.
- The current 5%-50% payroll ratio band is a sanity band, not a real payroll model.

Important: the last code change stopped GPT payroll growth from overriding the OEWS/FTE formula, but that only fixes the tiny-payroll mechanical bug. It does not solve the deeper payroll architecture problem.

Payroll still needs a true class fix:

- Intake parsing must separate headcount from payroll dollars.
- “Use 118 employees” must only populate `current_num_employees`, not `payroll_total_year1`.
- Payroll should be derived from actual FTE/headcount times wage when headcount exists.
- OEWS should use role/business context where possible, not silently fall back to generic `000001 All Occupations`.
- If realistic role/FTE/wage basis is unavailable, fail fast or request a structured staffing grid before convergence.
- GPT may decide staffing structure, but Python must calculate payroll deterministically.

The correct target architecture for payroll is:

```text
intake headcount / GPT staffing grid -> OEWS wages -> FTE x wage payroll -> model_input -> FINMO
```

Not:

```text
revenue / generic revenue-per-employee -> fake FTE -> payroll
```

And not:

```text
bad Q0 payroll x GPT growth percent
```

### Contract Table / Horizon Instability

The SQL GPT contract lookup table exists and is being used, but horizon instability still surfaced.

Recent failure:

- Draft: `ac69417a85394506bc0e11b507c0a50d`
- Error: `failed_table_horizon_contract`
- Detail: `targets_by_quarter` had `row_count=20` but was missing unique Q2, Q3, Q4, Q6, Q7, Q8, Q10, Q11, Q13, Q14, Q15, Q17, Q18, Q19.

Interpretation:

- The contract requires exactly one row for each Q1-Q20.
- The response apparently had 20 rows but duplicate or malformed quarter identifiers.
- This should be treated as a contract-normalization/strict-schema/horizon class bug, not a business-model failure.

Do not weaken the 20Q rule. The architecture still requires full Q1-Q20 contracts.

### Mapping Metadata Ownership Was Corrected

The old behavior requiring GPT to copy `mapped_repair_targets` was removed from the active contract surface.

Current intended behavior:

- GPT chooses levers/cells/values/rationale.
- Python derives issue/target mapping from SQL `post_intak_mapping_lookup`.
- Python must fail fast if a selected lever is not valid for the active issue.
- GPT should not be required to copy deterministic mapping metadata.

This is aligned with the user’s authority boundary:

- GPT makes decisions.
- Python owns deterministic structure, mapping, validation, and application.

### Retry Path Was Partially Cleaned Up

A legacy retry issue was found:

- Initial planner prompt was compacted through the context lookup.
- Retry prompt still used the old heavy/raw full contract scaffold.
- That could reintroduce confusing or oversized contract surfaces after an initial failure.

Current code now compacts the retry contract before sending it back to GPT and adds a retry-payload budget fail-fast.

This was compile-checked and one ApexCloud run passed before the payroll/horizon issues were investigated, but it should still be treated as recent and under-tested.

### OpenAI / Runtime Instability Remains Real

Recent E2E attempt:

- Scenario: `tmp_cash_sweep_scenario_balanced_commercial_landscaping.json`
- Business: `IronOak Commercial Grounds`
- Draft: `e7e2eb42a4bd4ff1a287abe71a0e61ec`
- Failure: OpenAI read timeout in `_run_unified_convergence_openai`.
- Detail included `model=gpt-5.1`, `timeout_seconds=120`, and active cycle deadline remaining around `56s`.

This is external/request instability or payload/time pressure. Do not confuse it with a financial-model failure. Also do not increase the 180-second cycle limit or 10-cycle limit without explicit user permission.

### Current Backend Procedure Still Stands

Always use:

```powershell
.\context\ensure_5050_backend.ps1
```

If code changes need to take effect, use:

```powershell
.\context\ensure_5050_backend.ps1 -ForceRestart
```

The user does not want to be asked to restart the backend. Use the helper.

### Immediate Next Technical Priorities

1. Fix payroll as a class bug, not as a single-run patch.
2. Add fail-fast detection that rejects payroll if employee count is accidentally stored as payroll dollars.
3. Decide and implement the correct staffing/FTE source of truth for payroll.
4. Keep payroll out of GPT freeform dollars; use GPT only for structured staffing decisions if needed.
5. Fix the full-horizon `targets_by_quarter` duplicate/malformed-quarter issue without weakening the Q1-Q20 contract.
6. Continue using SQL lookup tables as authorities: mapping, cash policy, GPT contract, GPT context.
7. Do not increase cycle timeout or cycle count without user approval.

### Do Not Do

- Do not claim payroll is fixed because one mechanical tiny-payroll bug was patched.
- Do not let `payroll_total_year1=118` survive as if it were dollars.
- Do not reintroduce generic fallback behavior that silently creates plausible-looking but unsupported payroll.
- Do not make FINMO formulas do payroll logic. Payroll belongs in model input / derived driver layer.
- Do not make Python choose business staffing decisions that should belong to GPT or intake.
- Do not let GPT output payroll dollars directly as the final authority.
- Do not weaken the full 20-quarter convergence contract.
