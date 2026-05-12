# Phase 9 P3.10 — Critical Operations Audit

**Scope:** Read-only audit. NO code changes. Document only.
**Goal:** Enumerate every critical operation in the post-intake pipeline, document each one's current failure semantics, and map the gap between (a) the existing fail-fast file (`python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py`) and (b) the operations the user wants fail-fast for under `CONVERGENCE_TEST_MODE=true`.

A "critical operation" is defined as: any step where a failure should make the run unusable, not just degraded — i.e. continuing past the failure produces a misleading verdict (the Sunny 13/16 pattern) or a workbook that materially misrepresents the business's plan.

---

## 1. Existing fail-fast file inventory

[python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py) — 1867 lines — defines 16 public assertion functions, controlled by:

- `CONVERGENCE_TEST_MODE` env var (default false in [common.py:49](python/client_intake_and_finmo/fail_fast/common.py#L49))
- `FAIL_FAST_ENABLED` env var (default true)
- Per-phase env var `POST_INTAKE_FAIL_FAST_ENABLED` (default true)
- Per-flag-group `Set[str]` constants that gate which flags raise

### 1.1 Assertion functions defined

| Function | Stage applied | Trigger |
|---|---|---|
| `assert_stage_ramp_revenue_path_applied` | finalize stage | Actual revenue trajectory violates stage_ramp_contract |
| `assert_quarter_grid_stage_ramp_bridge_applied` | finalize | Quarter-grid composite revenue ramp violations |
| `assert_stage_ramp_expense_path_applied` | finalize | Cost/expense ratios exceed maturity bands |
| `assert_stage_ramp_profitability_path_applied` | finalize | Stage profitability feasibility |
| `assert_marketing_presence_applied` | finalize | Marketing missing or zero |
| `assert_post_intake_business_shape_applied` | finalize | Bundles 4 stage_ramp + marketing asserts |
| `assert_post_intake_horizon_integrity` | both | model_input/finmo horizon length mismatch |
| `assert_post_intake_mapping_formula_contract_integrity` | both | mapping_formula contract rows malformed |
| `assert_post_intake_mapping_formula_application_integrity` | finalize | Mapping formulas not applied / mismatch |
| `assert_post_intake_model_input_rows_integrity` | both | model_input row schema violations |
| `assert_post_intake_revenue_driver_integrity` | both | Revenue driver bundle / formula mismatch |
| `assert_post_intake_finmo_statement_integrity` | finalize | finmo statement math invalid |
| `assert_post_intake_schedule_markers_integrity` | both | Headcount/debt schedule markers missing |
| `assert_post_intake_rebuilt_finmo_matches_model_input` | finalize | Rebuilt FINMO drifts from model_input |
| `assert_post_intake_cash_buffer_integrity` | finalize (optional) | Cash buffer violation |
| `assert_post_intake_global_invariants` | finalize | Umbrella that calls all of the above |

### 1.2 Call sites of the existing fail-fast

Coverage is **structurally narrow** — concentrated at two pipeline boundaries (initialize and finalize), with nothing in between.

| File | Site | What's checked |
|---|---|---|
| [post_intake_runtime_validation/initialize_post_intake.py:134](python/client_intake_and_finmo/post_intake_runtime_validation/initialize_post_intake.py#L134) | `run_initialize_post_intake_validation` | Lookup tables, contract schemas, sequence rows, formula rows, draft SQL, BS driver sample |
| [post_intake_runtime_validation/finalize_post_intake.py:397](python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L397) | `run_finalize_post_intake_validation` | Calls `assert_post_intake_global_invariants` + 4 schedule-level asserts |
| [post_intake_convergence/runner.py:861](python/client_intake_and_finmo/post_intake_convergence/runner.py#L861) | (legacy convergence runner) | Calls global invariants pre-finalize |
| [post_intake_initial_grid/runner.py:304](python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L304) | Initial grid | Calls global invariants at end of grid build |
| [post_intake_cash/runner.py](python/client_intake_and_finmo/post_intake_cash/runner.py) line 41 | Cash runner | Imports only the `CASH_STRATEGY_TEST_MODE_FAIL_FLAGS` set (string constants), NOT the assert functions |
| [post_intake_headcount/schedule.py](python/client_intake_and_finmo/post_intake_headcount/schedule.py) | Headcount writer | Calls `post_intake_fail_fast_raise` for headcount-specific flags |
| [post_intake_debt_schedule/schedule.py](python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py) | Debt schedule | Calls fail_fast for debt-specific flags |

### 1.3 Coverage shape

The existing fail-fast is **state-checking, not operation-gating**: it verifies the resulting state (model_input + FINMO + schedules + math) at finalize time. It does NOT check whether the operations between initialize and finalize ran successfully. So if an operation silently fails AND happens to leave model_input in a consistent shape (e.g., un-restored after EXHAUSTED handoff failure), every finalize assert will pass while the plan itself is broken. **This is exactly the Sunny 13/16 pattern.**

What fail-fast does NOT cover (gap pattern):
- Pipeline orchestrators' outer `try/except Exception` blocks
- Mid-pipeline operations that return status dicts on failure
- GPT call sites (which "never raise" by chokepoint contract)
- Handler-side write-failure paths that silently skip drivers
- Pre-flight feasibility checks that fail-open on missing inputs
- Realism-gate formula errors that downgrade to `status="skipped"`
- Cash strategy validation failures that quietly revert state
- Post-run side effects (diagnostic SQL, workbook, email)

---

## 2. Pipeline order — where each critical operation lives

Per [post_intake_solver/orchestrator.py:1338-2200](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1338) (`_run_post_cascade_completion`) and the surrounding orchestration:

```
[initialize phase]
  run_initialize_post_intake_validation                    [F.F. covered]
  Operating model construction (intake consultants)
  Intake context building
  Balance sheet contextual seed (Tier A intake / Tier B cohort)
  Headcount schedule build                                 [F.F. covered piecewise]
  Debt schedule build                                      [F.F. covered piecewise]
  Initial grid quarter-grid build                          [F.F. covered (global invariants at end)]

[post-cascade body — orchestrator._run_post_cascade_completion]
  1.   Target-seeking solver pass                          [GAP]
  1.5  unit_price drift / quarter-grid rebuild
  1.55 Post-cascade path stamp pass                       [GAP]
  1.6  Composite revenue trajectory check vs stage_ramp_contract  [GAP — silent return]
  1.7  Target-driven restoration loop                      [GAP]
         └─ forecast classifier (P3.7) scope decision      [GAP — silent default]
  1.8  GPT exhaustion handler (when restoration EXHAUSTED) [GAP — Sunny pattern]
         ├─ pre-session FINMO build
         ├─ tool-calling session
         │    ├─ call_gpt_responses_api_turn (chokepoint)
         │    ├─ compute_trajectory_from_anchors (mini-FINMO)
         │    ├─ verified candidate tracking
         │    └─ budget extension / hard cap
         ├─ writer (driver anchors -> model_input)
         ├─ post-commit FINMO rebuild
         └─ compute_metrics_to_mute
  2.   Cash strategy pass                                  [GAP — runs even after handler failure]
  3.   Realism gate                                        [GAP — formula errors → skip]
  3.5  Realism verification proposer                       [GAP]
  4.   Finalize validation                                 [F.F. covered]
       └─ global_invariants (16 asserts)
  5.   Persist                                             [GAP]

[post-run side effects — intake_consult.py:7240-7445]
  Diagnostic payload assembly                              [GAP]
  Diagnostic SQL persistence                               [GAP — log-and-continue]
  Workbook generation                                      [GAP partial — sheet builders raise, diagnostics sheet swallows]
  Workbook auto-email                                      [GAP — by design "never raises"]
```

---

## 3. Per-operation audit

Format per row: **failure modes → current handling → fail-fast coverage → gap severity**.
"Coverage = no" means no import from `client_intake_and_finmo.fail_fast.post_intake_fail_fast` and no equivalent local raise on that failure path.

### 3.1 Initialize phase

| # | Operation | Location | Failure modes | Handling | Coverage | Gap |
|---|---|---|---|---|---|---|
| 1 | `run_initialize_post_intake_validation` | [initialize_post_intake.py:134](python/client_intake_and_finmo/post_intake_runtime_validation/initialize_post_intake.py#L134) | Lookup tables / contracts / sequence rows / draft SQL fetch missing or malformed | **Raises** (accumulate-then-raise pattern, `_raise_if_errors`) | yes | none |
| 2 | Operating model construction (intake_consultant, financials_consultant, etc.) | `python/client_intake_and_finmo/*_consultant.py` | GPT consultant call failure, malformed parse, schema mismatch | Status dict via `call_gpt_with_schema_or_fallback` ([_gpt_critic_io.py:179](python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py#L179)) — "Python proposer floor" path. Never raises. | no | **moderate** — Python floor exists, but malformed floors propagate downstream silently |
| 3 | Intake context building (`build_minimal_convergence_context`, draft state hydration) | [orchestrator.py:68](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L68), [post_intake_state/runner.py](python/client_intake_and_finmo/post_intake_state/runner.py) | Missing draft fields, malformed intake snapshot | Defaults to `{}` / None on missing; coercion errors swallowed by `_safe_float` | no | **moderate** — silent coercion masks corrupt intake state |
| 4 | Balance sheet contextual seed — `apply_balance_sheet_contextual_seed_to_model_input` (Tier A) | [contextual_seed.py:202](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L202) | Missing sections dict, missing model row for lever_id | **Raises RuntimeError** on missing sections/row | no (but local raise) | minor — one swallowed `except Exception` at line 238 for malformed solver-tag keys |
| 5 | Balance sheet seed proposer (Tier A → Tier B fallback) — `_proposer_naics_seed` | [contextual_seed.py:370](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L370) | Resolver exception, no NAICS coverage, missing target/min/max | Bare `except Exception: return None` (line 383-384) — **silent fallback to mapping-band midpoint** (line 507) | no | **high** — resolver outages indistinguishable from legitimate no-coverage; whole BS seed silently degraded |
| 6 | Headcount schedule build / write | [post_intake_headcount/schedule.py](python/client_intake_and_finmo/post_intake_headcount/schedule.py) | Wage policy missing, OEWS naics empty, capacity grid incomplete, finmo mismatch | Calls `post_intake_fail_fast_raise` for ~60 named flags (see `PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS`) | yes | none |
| 7 | Debt schedule build | [post_intake_debt_schedule/schedule.py](python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py) | SBA rate missing, debt-schedule rows missing, interest-rate mismatch | Calls `post_intake_fail_fast_raise` + `assert_debt_schedule_payload_ready` + `assert_finmo_matches_debt_schedule` | yes | none |
| 8 | Initial grid quarter-grid build | [post_intake_initial_grid/runner.py:304](python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L304) | Quarter-grid math failure, formula mismatch, missing rows | Calls `assert_post_intake_global_invariants` at end | yes | none |

### 3.2 Post-cascade body — solver

| # | Operation | Location | Failure modes | Handling | Coverage | Gap |
|---|---|---|---|---|---|---|
| 9 | Target-seeking solver — `run_target_seeking_solver` | [target_seeking_loop.py:189](python/client_intake_and_finmo/post_intake_solver/target_seeking_loop.py#L189) | Pinned driver, no candidate levers, inner joint-fit raises | Returns status dict (`converged` / `no_candidate_levers` / `stuck_pinned` / `max_iterations_reached`). `except Exception` at line 325 → status `"inner_joint_fit_raised"`, outer loop continues to `max_iterations_reached`. | no | **high** — inner crash masquerades as "max iterations"; orchestrator sees a "completed" run |
| 10 | Target solver — `solve_for_target` | [target_solver.py:622](python/client_intake_and_finmo/post_intake_target_solver/target_solver.py#L622) | Cash-pass lever in driver list (raises), ramp length mismatch (raises), no bounds for driver, sensitivity None | Mixed — raises on contract violations, **silently skips** on missing bounds (line 665, 673); `_compute_metric_per_q` at line 545: `except Exception: v=None → 0.0`. **NaN/divide-by-zero silently becomes "zero metric"** which keeps solver iterating against phantom residual. | no | **high** — silent 0.0 substitution makes the solver chase a problem that isn't real |
| 11 | Adaptation cascade — `run_adaptation_cascade` | [adaptation_cascade.py:356](python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L356) | Tier 4 import failure (line 261), Tier 7 envelope build (line 679), Tier 7 inner runner (line 698), restoration TypeError/Exception (lines 773-806) | **Heavily swallowed**. Line 698-702: Tier 7 inner-runner exception sets `residuals=[]`, which then trips `if not residuals:` → declares Tier 7 a clean landing. **A code exception masquerades as a successful generic fallback plan.** Phase 9 corrective directive removed terminal "raise CascadeAndRestorationExhausted" entirely; cascade always lands. | no | **high** — exception literally becomes "success" |
| 12 | Pre-solver feasibility cascade — `run_pre_solver_feasibility_cascade` | [adaptation_cascade.py:927](python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L927) | All tiers fail to restore feasibility | "Never raises" by design (docstring). Tier exhaustion silently returns still-infeasible payload with `tier_landed=None`. Fallback to phase_3_calibrated is recorded in diagnostic but **not logged in app logs**. | no | **moderate** — observable in diagnostic, invisible in real-time |
| 13 | Pre-flight structural feasibility — `verify_structural_feasibility` | [structural_feasibility_check.py:328](python/client_intake_and_finmo/post_intake_solver/structural_feasibility_check.py#L328) | Missing ops/financials/payroll, periods_per_year wrong, no payroll schedule | **Fail-open**: returns `feasible=True` with `insufficient_inputs` diagnostic when data missing (lines 399, 470). Capacity-source priority chain silently degrades source quality. | no — only via dedicated fail-fast flag `structural_feasibility_check_failed` if violation detected | **high** — fail-open on missing inputs hides upstream corruption |
| 14 | Joint feasibility check — `verify_joint_feasibility` | [joint_feasibility_check.py:86](python/client_intake_and_finmo/post_intake_solver/joint_feasibility_check.py#L86) | Missing envelope/targets payload, collapsed lever bands, metric target excludes lever range | Returns `FeasibilityResult(feasible=False, ...)` — never raises. Silently skips metrics without `governs_lever` (line 137). | no — only via `joint_feasibility_check_failed` flag once violation detected | **moderate** — fail-open via None defaults; partial coverage when caller checks `min_editable_levers` |

### 3.3 Post-cascade body — restoration + handler

| # | Operation | Location | Failure modes | Handling | Coverage | Gap |
|---|---|---|---|---|---|---|
| 15 | Composite revenue trajectory check vs `stage_ramp_contract` | [orchestrator.py:1548-1574](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1548) | Validator import/exec failure | `except Exception` swallows to `completion_trace` entry; continues | no | **moderate** — drift check skipped silently |
| 16 | Target-driven restoration loop — `run_restoration_loop` | [restoration_loop.py:858](python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L858) | No driver bounds, CashPassLeverViolation, FINMO build failure during viability eval, band resolver failure, max outer passes | Mixed — returns `RestorationStatus.{LANDED, ITERATING_STILL, FAILED, EXHAUSTED}` enum. When `bounds_by_target` empty for ALL targets, loop iterates 5 passes producing zero work → `ITERATING_STILL` (no raise). `_evaluate_viability` swallows formula errors at line 238 → False → routes to EXHAUSTED. **Error becomes business verdict.** | no | **high** — solver-side silent degradation produces wrong EXHAUSTED routing |
| 17 | Forecast classifier (P3.7 scope) — `_classify_forecast_exhaustion` | [restoration_loop.py:745](python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L745) | Validator import failure, validator raises, missing primary_levers, realism rows missing | `except Exception: return (None, [])` at lines 782, 794; realism rows lookup `except Exception: rows = []` at 807 | no | **high** — classifier failure on EXHAUSTED path silently defaults to `HandlerScope.PNL_PATH` (line 1135); on LANDED path silently skips handoff entirely. The classifier's correctness IS the run's correctness. |
| 18 | Band resolver — `_resolve_band_for_target` / `_driver_bounds_for_target` | [restoration_loop.py:451, 564](python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L451) | NAICS baseline service outage, band None on all axes | Swallowed — `except Exception: payload = None` at 469, 631 → silently strips levers from driver list → restoration runs with zero authority | no | **high** — baseline outage indistinguishable from "no targetable levers" |
| 19 | GPT exhaustion handler — pre-session FINMO build | [handler.py:644-656](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L644) | `build_finmo(model_input)` raises | Returns `HandlerResult(status=FAILED_PRECONDITION)` — status enum, not exception | no | **high** — Sunny pattern |
| 20 | GPT exhaustion handler — `tool_calling_session` import | [handler.py:661-684](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L661) | Module missing / import error | Returns `HandlerResult(status=FAILED_PRECONDITION)` | no | **high** |
| 21 | GPT tool-calling session — `run_tool_calling_session` | [tool_calling_session.py:431](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L431) | GPT turn HTTP/timeout/budget exhaustion, JSON parse error on tool args, unknown tool name, hard cap with no all_pass | Status enum (`verified` / `best_effort_no_all_pass` / `failed_precondition`). [Line 535-539](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L535) silent `break` on `decision_source != "python_proposer_plus_gpt_critic"` — the Sunny pattern. JSON-parse error on tool args (line 572-580) fed back to GPT as tool error; session continues. | no | **high** — Sunny pattern; both first-turn network failure AND mid-loop arg-parse failures swallowed |
| 22 | OpenAI Responses API chokepoint — `call_gpt_responses_api_turn` | [_gpt_critic_io.py:366](python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py#L366) | Network failure, timeout, HTTP ≥400, invalid JSON, budget exhausted | "Never raises" by docstring contract (line 205-208). Every failure returns `decision_source="python_proposer_only_*"` | no — by design | **deliberate** for Phase-3 critics where Python has a floor; **broken** for handler where there is no Python floor |
| 23 | Mini-FINMO probe — `compute_trajectory_from_anchors` | [mini_finmo.py:187](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L187) | Bad operating_context, writer raises, build_finmo raises, FINMO returns empty quarter_rows | Three explicit `except Exception` blocks (lines 232, 251, 259) → `{"error":..., "viability_checks":{"all_pass":False}}` | no | **high** — error masquerades as a "failing" probe; GPT iterates against phantom; writer/FINMO crashes invisible |
| 24 | Handler P&L writer — `_write_gpt_authored_per_quarter_values` | [handler.py:378](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L378) | Missing anchor, non-numeric anchor, no rows for lever, labor-driven capacity | Silently records `skipped_no_anchor` / `skipped_non_numeric_anchor` / `skipped_no_rows` / `skipped_payroll_supported_capacity` in `per_driver_summary`. `except Exception` line 447 → skip. **ANY/ALL drivers can skip silently; function returns "success."** | no | **high** — caller never inspects status; an entire commit can be a no-op |
| 25 | Handler WC writer — `_write_gpt_authored_working_capital_values` | [handler.py:303](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L303) | Missing WC value, non-numeric, no rows for lever | Same silent skip pattern as #24 | no | **high** |
| 26 | Compute metrics to mute — `compute_metrics_to_mute` | [handler.py:539](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L539) | Realism lookup import/load failure | `except Exception: rows = []` (line 581) → minimal mute set `["ebitda_margin"]` | no | **moderate** — under-muting causes spurious realism failures attributed to GPT-authored drivers |
| 27 | Post-commit FINMO rebuild | [tool_calling_session.py:765-778](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L765) | build_finmo raises after commit | `except Exception` → `HandlerResult(FAILED_PRECONDITION, reason="finmo_rebuild_failed_after_commit")` | no | **high** |
| 28 | Orchestrator outer try/except around handler | [orchestrator.py:1710-1714](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1710) | ANY exception escaping handler | `completion_trace["gpt_exhaustion_handler"] = {"status": "failed", ...}` then continues to cash pass | no | **critical** — even if Task 3 makes handler raise, this catch would still swallow it |
| 29 | Orchestrator outer try/except around restoration loop | [orchestrator.py:1715-1719](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1715) | ANY exception from restoration block | Same pattern | no | **critical** |

### 3.4 Post-cascade body — cash, realism, acceptance

| # | Operation | Location | Failure modes | Handling | Coverage | Gap |
|---|---|---|---|---|---|---|
| 30 | Cash strategy pass — `run_mode_based_cash_strategy` | [orchestrator_invocation.py:149](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L149) | build_context / GPT review / plan / apply / validation / final-FINMO-rebuild exceptions | Wraps every step in `except Exception` → `_failure_result(...)` with `status="failed"` (lines 245, 273, 306, 321, 364). Final FINMO rebuild silently `pass` (line 396-400) | no — `CASH_STRATEGY_TEST_MODE_FAIL_FLAGS` exists but only some flags are written into result, not raised | **high** — cash pass routinely "fails" without halting; caller barely inspects `keep_changes` |
| 31 | Cash GPT review — `_run_cash_strategy_review_openai` | [cash/runner.py:1996](python/client_intake_and_finmo/post_intake_cash/runner.py#L1996) | Proposer invalid contract, OPENAI key missing, HTTP ≥400, parse fail, amended-invalid | Returns proposal_only_response / python_proposer_with_critic_fallback. **Every failure silent**; only `decision_source` distinguishes; caller does not inspect for failure | no | **high** — analogous to Sunny pattern but in cash strategy |
| 32 | Cash translation — `_build_cash_strategy_second_pass_plan` | [cash/runner.py:2310](python/client_intake_and_finmo/post_intake_cash/runner.py#L2310) | review_status != "completed", translation produces no contract | Returns dict with `translation_fail_flags`; never raises | no | **moderate** — flags only consumed in test mode |
| 33 | Cash apply — `_apply_cash_strategy_exact_updates` | [cash/runner.py:3290](python/client_intake_and_finmo/post_intake_cash/runner.py#L3290) | numeric_execution import, plan not "ready", exact_updates empty, solver failure | Status dict (`skipped_*` variants); appends `cash_translation_failed` to fail_flags | no | **moderate** — "skipped" vs "applied nothing" indistinguishable |
| 34 | Cash validation — `_validate_cash_strategy_post_pass` | [cash/runner.py:3766](python/client_intake_and_finmo/post_intake_cash/runner.py#L3766) | Debt-schedule minimum-plan failure, SBA rate missing, debt rows missing, interest mismatch | Status dict; accumulates failures into `cash_contract_failures[]`. Caller reverts via `keep_changes=False` at [orchestrator_invocation.py:383-385](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L383) | no | **moderate** — revert is the only signal; nothing raises |
| 35 | Realism gate — `validate_industry_realism_bands` | [validator.py:423](python/client_intake_and_finmo/post_intake_realism/validator.py#L423) | Trajectory formula exception, NAICS resolver exception, no coverage, missing tolerance, per-metric formula exception, band min/max missing | Every formula exception → `RealismCheckResult(status="skipped", reason="formula_error:...")`. NAICS resolver exception → silent `naics_band=None`. Phase 9 Phase D: **no `RealismBandViolation` raised** — only accumulates into `hard_fail_violations[]`. | no | **high** — formula crashes downgrade to "skip"; acceptance gate then declares the unscored metrics "passed" (skipped count > 0) |
| 36 | Realism mute consumption (`_muted_realism_metrics` read) | [validator.py:488-494, 524, 574, 967](python/client_intake_and_finmo/post_intake_realism/validator.py#L488) | None — read-side of the mute mechanism | Reads `model_input_json._muted_realism_metrics`; muted metrics' hard_fails become `status="muted_gpt_post_exhaustion"` | no | **moderate** — over-muting can hide real failures; under-muting is the more common bug (compute_metrics_to_mute silent-fallback issue, #26) |
| 37 | Realism verification proposer — `propose_realism_verification_payload` | [verification_proposer.py:149](python/client_intake_and_finmo/post_intake_realism/verification_proposer.py#L149) | Empty issue_packets, applied_updates with no quarter_index | Empty packets → synthesized `no_open_issues` `all_resolved` verdict — never raises | no | **low** — observable as missing real issues only via downstream check |
| 38 | Acceptance gate — `verify_run_acceptance` (16 checks) | [acceptance/gate.py:660](python/client_intake_and_finmo/post_intake_acceptance/gate.py#L660) | Missing draft_id (raises), missing finmo/realism_memo, persistence error | Only draft_id empty raises (line 675); every individual `_check_*` returns `(False, detail_dict)`. Persistence error swallowed into `verdict["persistence_error"]` (line 762). **Gate itself never raises** — depends on API handler to convert `verdict.passed=False` to HTTP 500. | partial — 16 named checks ARE de-facto fail-fast for the assembled plan | **moderate** — gate logic OK, but it's downstream of all the silent failures, so it scores symptoms not causes |

### 3.5 Finalize + Persist

| # | Operation | Location | Failure modes | Handling | Coverage | Gap |
|---|---|---|---|---|---|---|
| 39 | `run_finalize_post_intake_validation` | [finalize_post_intake.py:397](python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L397) | 15 `except Exception` sites all accumulate into `errors[]`; final `_raise_if_errors` raises if any | **Raises** | yes | none |
| 40 | Orchestrator outer try/except around finalize | [orchestrator.py:1953-1959](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1953) | Any finalize exception | `completion_trace["finalize_validation"] = {"status": "failed_downgraded_to_warning", ...}`. **`failed_downgraded_to_warning` is literally in the code** — the orchestrator currently turns a finalize-failure into a warning. | no | **critical** — Sunny's persisted state shows this exact pattern at line 114751: `"finalize_validation":{"status":"failed_downgraded_to_warning",...}`. Finalize fail-fast is being undone at the orchestrator level. |
| 41 | Persist post-intake state | [orchestrator.py:2007-2067](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2007) | SQL UPDATE failure | `except Exception as exc` swallows; persistence error recorded but run continues | no | **moderate** |

### 3.6 Post-run side effects (intake_consult.py)

| # | Operation | Location | Failure modes | Handling | Coverage | Gap |
|---|---|---|---|---|---|---|
| 42 | Diagnostic payload assembly — `build_run_diagnostics_payload` | [post_intake_run_diagnostics.py:162](python/client_intake_and_finmo/post_intake_run_diagnostics.py#L162) | Missing draft_row / planning_run_json / realism_memo, bad casts | Defaults to None / {} per field; never raises | no | **low** — appropriate (it's a report), but missing canonical fields only `logger.warning`'d at [intake_consult.py:7357](python/api_handlers/intake_consult.py#L7357) |
| 43 | Diagnostic SQL persistence — `persist_run_diagnostics` | [post_intake_run_diagnostics.py:284](python/client_intake_and_finmo/post_intake_run_diagnostics.py#L284) | Missing draft_id/planning_run_id (returns False), commit error swallowed (line 338) | Mixed — DB exec errors propagate to caller; caller swallows at [intake_consult.py:7375](python/api_handlers/intake_consult.py#L7375) with `logger.warning` only | no | **moderate** — broken diagnostics table renders stale data into workbook Diagnostics sheet silently |
| 44 | Workbook generation — `build_client_financial_model_workbook` | `client_statements_output_excel/workbook_builder.py:30` | Missing JSON blobs (`validate_draft_data` raises), sheet builder failure | Sheet builders raise (correct); Diagnostics sheet swallows (`except Exception: pass` at line 54); `excel_utils` named-range registration swallows | partial | **low** — single explicit swallow site at workbook_builder.py:54 (diagnostics sheet) |
| 45 | Workbook orchestrator — `export_workbook_for_draft_id` | `client_statements_output_excel/export_client_workbook.py:107` | Diagnostics fetch (swallowed line 73/77), conn cleanup (swallowed line 132) | Real workbook save raises naturally; caller [intake_consult.py:7406](python/api_handlers/intake_consult.py#L7406) catches into `workbook_export_error`, logs, **does not abort response** | no | **moderate** — failed workbook does not block API success response |
| 46 | Auto-email — `send_workbook_alert` | [workbook_email.py:51](python/client_intake_and_finmo/workbook_email.py#L51) | Missing env vars, attachment unreadable, port parse, SMTP failure | "Never raises" by design — returns status dict. Outer `except Exception` at [intake_consult.py:7437](python/api_handlers/intake_consult.py#L7437) belt-and-suspenders | no | **low** — appropriate for email; misconfiguration only visible in logs |

---

## 4. Cross-cutting silent-degradation patterns

The audit surfaces five recurring patterns. Task 3's overhaul needs to address each.

### 4.1 The status-enum-instead-of-exception pattern
Operations return a `Result` object or dict whose `status` field encodes failure:
- `HandlerStatus.FAILED_PRECONDITION` (handler)
- `ToolCallSessionResult.status = "failed_precondition"` (tool-calling session)
- `RestorationStatus.{FAILED, EXHAUSTED, ITERATING_STILL}` (restoration loop)
- `SolverStatus.{BOUND_PINNED, MAX_INNER_ITERATIONS_REACHED}` (target solver)
- `target_seeking_loop` status dict (`stuck_pinned`, `max_iterations_reached`, `inner_joint_fit_raised`)
- `CashStrategyResult.status="failed"` (cash strategy)

Under test mode each of these should raise rather than return.

### 4.2 The `decision_source` Phase-3-critic pattern
GPT call chokepoint deliberately "never raises"; returns `decision_source="python_proposer_only_*"`. Callers that DO have a Python floor are fine. Callers that DO NOT (the exhaustion handler is the canonical case; cash GPT review is the second) need the chokepoint failure converted to a raise at the *call site*, not at the chokepoint.

### 4.3 The `except Exception: continue/None/0.0` swallow
- `target_solver._compute_metric_per_q` (line 545): formula crash → 0.0 metric → solver chases phantom
- `restoration_loop._evaluate_viability` (line 238): formula crash → False → routes to EXHAUSTED
- `restoration_loop._classify_forecast_exhaustion` (lines 782, 794): classifier crash → `(None, [])` → default PNL scope
- `restoration_loop._resolve_band_for_target` (line 469): NAICS outage → strip lever silently
- `adaptation_cascade._cascade_resolver._resolve` (line 309): NAICS outage → None → silent retention
- `adaptation_cascade.run_adaptation_cascade` line 698-702: **Tier 7 exception → residuals=[] → declared a clean landing**
- `mini_finmo` lines 251, 259: writer/build_finmo crash → all_pass=False → GPT iterates against phantom
- `handler._write_gpt_authored_per_quarter_values` line 447: any drivers can skip silently and writer returns "success"
- `handler.compute_metrics_to_mute` line 581: realism lookup crash → minimal mute set

These are the **deepest** kind of silent failure — the function returns a "normal-looking" value and the caller has no way to distinguish corruption from legitimate input.

### 4.4 The orchestrator outer `except Exception` pattern
Six orchestrator wrappers ([orchestrator.py:1448, 1530, 1569, 1710, 1715, 1788, 1864, 1953, 1989, 2067](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1448)) catch any escaping exception, record into `completion_trace[block_name] = {"status": "failed", "error": ...}`, and **fall through to the next block**. The single most consequential one is the finalize wrapper at line 1953 which produces the documented status `"failed_downgraded_to_warning"` (Sunny line 114751). Under test mode these wrappers should be removed or scoped to whitelisted exception types.

### 4.5 The fail-open pre-flight pattern
`verify_structural_feasibility` and `verify_joint_feasibility` both default to `feasible=True` (or `feasible=False` with no raise) on missing inputs. Pre-flights only catch problems they CAN see — they never escalate "I couldn't see the input" to a real failure.

---

## 5. Coverage gap summary

| Severity | Count | Examples |
|---|---|---|
| Critical (overhaul required) | 6 | Orchestrator outer `try/except` x4 (lines 1710, 1715, 1953); Tier 7 cascade `residuals=[]` masquerade; finalize `failed_downgraded_to_warning` |
| High (must convert to fail-fast under test mode) | 16 | Handler precondition x3 sites (#19/20/27); tool-calling session silent break (#21); mini-FINMO error-as-result (#23); writer silent-skip x2 (#24/25); restoration loop status enums (#16/17/18); target solver 0.0-substitution (#10); inner_joint_fit_raised swallow (#9); pre-solver feasibility cascade silent fallback (#12); structural-feasibility fail-open (#13); cash GPT review silent fallback (#31); realism formula-error skip (#35); orchestrator finalize wrapper (#40) |
| Moderate | 9 | BS seed cohort fallback (#5); composite revenue check skipped (#15); joint feasibility fail-open (#14); cash translation flags (#32); cash apply skipped (#33); cash validation revert-only (#34); mute consumption (#36); operating model construction (#2); intake context coercion (#3) |
| Low / by design | 5 | Workbook email (#46); workbook diagnostics sheet swallow (#44); chokepoint "never raises" (#22 — correct for Phase-3 critics); verification proposer (#37); diagnostic payload (#42) |

**Total critical operations identified: 46.** Of these:
- **6 are currently fail-fast covered** (initialize validation, finalize validation, headcount, debt schedule, initial grid via global invariants).
- **5 are appropriately soft-degraded** (email, diagnostics, chokepoint design).
- **35 are silently degraded and within scope for Task 3.**

---

## 6. Task 3 scoping recommendations

The user asked the audit to surface gaps, not prescribe fixes. The following are scoping observations only — Task 3 design is to be authored under user review.

1. **Test-mode entry point.** The existing `convergence_test_mode_enabled()` already gates every fail-fast in the file via `CONVERGENCE_TEST_MODE=true`. Task 3 should reuse this — every new assert must short-circuit to a no-op when the env var is false.
2. **Universal-app discipline.** None of the failure modes in this audit are NAICS- or archetype-specific. All proposed asserts apply identically to every business.
3. **SQL discipline.** Item 41 (Persist) and item 43 (diagnostic SQL) are the only ones that touch SQL. Per the user's directive both should remain ADD-only.
4. **Phase order for fail-fast additions.** A reasonable order (not prescribed):
   - **First commit:** Wrap the GPT exhaustion handler — items 19/20/21/23/24/25/27 + orchestrator catch at 1710. This is the directly-observed Sunny pattern.
   - **Second commit:** Tighten the restoration loop and target solver silent-substitution paths — items 9/10/16/17/18.
   - **Third commit:** Adaptation cascade Tier 7 masquerade + pre-flight fail-open — items 11/12/13.
   - **Fourth commit:** Realism gate formula-error skip + cash strategy GPT review — items 31/35.
   - **Fifth commit:** Remove orchestrator outer `except Exception` wrappers under test mode — items 28/29/40, plus the four other wrappers at lines 1448, 1569, 1788, 1864.
5. **Diagnostic structure.** Every new `post_intake_fail_fast_raise(...)` call should carry the same shape the existing 16 asserts use: `code`, `stage`, `details` dict with concrete actual-vs-expected. The Sunny diagnosis (Task 1 doc, section 7) gives the format target — operator-readable in one line.
6. **Three deferred questions from the Sunny diagnosis:**
   - Should network failures retry before fail-fast? (Currently retries cover HTTP status; not connection errors.)
   - Should the `_GPT_CALL_BUDGET_PER_RUN` account for failed calls?
   - Should Phase-3 consultant Python-floor existence be re-verified per consultant before promoting their chokepoint to fail-fast? (Out of scope for handler-side overhaul.)

These three remain deferred to user direction at Task 3 kickoff.

---

## 7. What is NOT in scope

- NAICS / archetype / business-type branching in any new fail-fast (universal-app discipline).
- Production-mode behaviour changes. The user's directive explicitly scopes fail-fast to `CONVERGENCE_TEST_MODE=true`.
- SQL DELETE / DROP — diagnostic table ADD-only.
- The chokepoint `call_gpt_responses_api_turn` itself — its "never raises" design is correct for Phase-3 critics; the overhaul happens at the *callers* that lack a Python floor (handler, cash GPT review).
- Workbook email's "never raises" design — appropriate for SMTP and acknowledged in the user's intake_consult.py wrapper.

---

*Audit complete. Awaiting user review of Task 1 (diagnosis) + Task 2 (this audit) before Task 3 (overhaul) is authorized.*
