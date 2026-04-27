# System Overview Update 4.25.26

This is a Codex-to-Codex handoff for `C:\dev\business_plann_app`. It is written so a future session can recover the current work without relying on chat history. The user wants the app to remain a conventional driver-based 3-statement model:

`intake -> model_input drivers -> FINMO calculations -> financial outputs -> post-intake convergence/cash pass`

The core rule must not change: Python writes/updates model-input drivers only, FINMO calculates the outputs only, and convergence/cash logic must not mutate financial outputs directly.

## User Intent

The user is moving the app away from legacy fuzzy/proxy mapping and toward a deterministic post-intake system.

Key invariants:

- Mapping is table-driven. The source of truth is `python/client_intake_and_finmo/config/post_intake_driver_target_mapping.csv`.
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

Important files:

- `python/client_intake_and_finmo/config/post_intake_driver_target_mapping.csv`
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

- Some issue records still show `working_capital_payment_model_mismatch` inside convergence state. This should be treated as cash-pass-owned and not as a convergence blocker.
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
- `python/client_intake_and_finmo/config/post_intake_driver_target_mapping.csv`
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

Cash strategy behavior belongs in the cash pass, not convergence. Convergence should build a coherent operating model first; cash pass should then fund or distribute according to the selected strategy. A hard cash viability gate was added: every live quarter must satisfy `ending_cash >= required_cash_buffer`. A run must fail with `cash_pass_failed_unresolved_liquidity` if any live quarter remains below buffer after cash pass. Do not allow cash failures to be tolerated.

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
