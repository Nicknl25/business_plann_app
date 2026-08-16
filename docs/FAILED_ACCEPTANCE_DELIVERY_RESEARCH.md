# A plan that FAILED acceptance was delivered — Nine Fathom (draft 6d2823db, run 10a81085)

Status: RESEARCH for Nick's ruling (2026-08-16). NOTHING BUILT. Engine /
acceptance-gate / delivery-path territory — FULL APPARATUS when it
becomes a fix. Supersedes the NI presentation question in
docs/NI_TRAJECTORY_RESEARCH.md (see "Correction" below).

## The five answers

### 1. What is the 17.0, and why no named failure?
- **17.0 = 17 of 18 acceptance checks passed** (`post_intake_run_diagnostics.py:94-112`
  `_acceptance_score`; the gate records exactly 18 checks,
  `post_intake_acceptance/gate.py:932-991`). DB row: `acceptance_passed=0,
  acceptance_score='17.0'`.
- **The failing check has a name: `net_income_trajectory_viable`** —
  persisted in `planning_runs.acceptance_verdict_json.failed_checks`:
  Q11 NI margin **0.0404** vs `min_required_q11_margin_flat` **0.08**,
  `flat_floor_source = executive_margin_band_judgment` (`gate.py:496-517`).
  Ramping shape also failed (Q5→Q11 delta 0.87pp < 2pp).
- **The email cannot print it.** `build_run_email_body`
  (`workbook_email.py:314-325`) reads `payload["realism_checks"]` — the
  REALISM gate's per-metric results (a different subsystem, genuinely all
  clean) — and never reads `acceptance_checks` or `failed_checks`, which
  the payload DOES carry (`post_intake_run_diagnostics.py:253-259, 288`).
  So "FAILED (17.0)" + "Failing realism metrics: (none)" is three
  technically-true lines that never name the failure. Only the workbook
  Diagnostics sheet names it (`diagnostics_sheet.py:157-159`).

### 2. The restoration loop — LIVE, runs on EVERY run; the label is hardcoded
- `run_restoration_loop` (`post_intake_target_solver/restoration_loop.py:1335`)
  is called unconditionally in the orchestrator's completion tail
  (`post_intake_solver/orchestrator.py:2397-2445`, step "1.7 Phase 9 P3
  target-driven restoration loop"), after the cascade and before cash
  pass / realism / finalize. Not legacy. It has no relationship to the
  acceptance verdict.
- **"Handler: not fired (restoration loop landed)" is a hardcoded
  else-branch string** (`workbook_email.py:302-312`) meaning only "the
  `gpt_exhaustion_handler` key is absent from post_cascade_completion".
  It does not read the loop's status; a loop that failed or threw would
  print the same words.
- Things Nick may be conflating: the `feasibility_restoration` cascade
  tier (`adaptation_cascade.py:37-47`), and — the one that matters —
  the RESTRUCTURE stage (`post_intake_restructure/`, see 3c).

### 3. Why nothing caught it — the gate is an ANNOTATION and the safety net is DEAD
- **The GPT exhaustion handler** fires only on `RestorationStatus.EXHAUSTED`
  from the restoration loop (realism targets) — `handler.py:4-5`,
  `orchestrator.py:2475-2482`. It has no knowledge of the acceptance
  verdict; correctly did not fire (0 handler traces).
- **The acceptance gate runs AFTER completion and blocks nothing.**
  Ordering in `post_intake_consult_system_run_handler`
  (`intake_consult.py:14462+`): (1) orchestrator runs the whole pipeline
  and its own finalize persist stamps `run_status='completed'` /
  `completed_at` **17:44:34.877** (`intake_consult_draft.py:2684-2697,
  2856`); (2) THEN `verify_run_acceptance` at `intake_consult.py:14686`
  persists the verdict at **17:44:36** (`gate.py:795-813`); (3) restructure
  block `if not passed` (`:14720`); (4) diagnostics; (5) workbook export
  "**regardless of acceptance verdict**" (comment `:15326`, code
  `:15328-15337`); (6) copy to delivery dir; (7) email `:15483/:15492`;
  (8) failed verdict → `app.logger.warning` only (`:15517-15522`); (9)
  HTTP 200. Explicit at `:15510-15516`: "a non-passing acceptance verdict
  no longer 500s the run. The verdict is the OUTPUT." — landed in
  `a4c01fd` (2026-06-10) "gates flow, they don't crash".
  **Stale header comment** at `intake_consult.py:14671-14678` still
  claims a failed verdict short-circuits export and returns 500 — false
  since 06-10 (matches obsolete docs/phase_9_workbook_delivery_diagnosis.md).
- **The RESTRUCTURE stage — the one thing that should have rescued the
  plan — DID FIRE and DIED SILENTLY.** `repair_guidance_json` for the
  draft (written by `_rs_persist_guidance`, `intake_consult.py:15133-15141`):
  `restructure.final_passed=False`; history: bounds stage
  `feasible_region_exists=True` (executive authored 3 line ceilings + 2
  new-line candidates); search_1 `found=False, evals=0`; trace:
  "ni floor governed by executive judgment: 0.08", then on EVERY rung:
  `ContractViolation: AMALGAMATED_SESSION→MODEL_INPUT: field 'sections'
  ... per-line COGS is all-or-nothing: slots ['lob_3_product_1',
  'lob_4_product_1'] lack the ...`.
  ROOT: the restructure searcher synthesizes new revenue lines with ONLY
  the driver triple Unit Price / Capacity / Utilization
  (`post_intake_restructure/searcher.py:59-118, 301-306`) and never emits a
  `COGS %` row; the contract validator's all-or-nothing per-line-COGS
  rule (`post_intake_contracts/finmo_model_input_contract.py:676-695`,
  from WS1 `c77094a` 2026-08-12) then rejects every solve on any draft
  that carries per-line COGS. No candidate → attempt-workbook skipped
  (`:15079-15080` guard) → `_rs_swapped=False` → the email says nothing
  about a restructure. `_rs_loader_trace.log`: last restructure artifact
  2026-07-31; Nine Fathom shows `directive_active=False` only.
- **Two floors for one check**: the in-loop cascade evaluates
  `net_income_trajectory_viable` with finmo only (`evaluate_plan.py:763`
  `fn(fj)`, no model_input) → the 2pp default → PASSES, so the cascade
  sees nothing to fix; the final gate gets model_input → the executive
  8% → FAILS. The cascade can never close a gap the gate measures with a
  different ruler.

### 4. Reconciled with the NI research — the research was WRONG on the verdict
docs/NI_TRAJECTORY_RESEARCH.md said Nine Fathom "passes on flat-healthy
(4.04% ≥ 2%)". That read the CODE DEFAULT (2pp) and the in-loop
behaviour, not the persisted verdict. The persisted verdict applied the
executive floor 0.08 → FAILED. Both the artifact analysed (the delivered
finmo) and the trajectory numbers stand; the pass/fail claim does not.
The "escape hatch" concern inverts: on this run the gate was STRICTER
than the doctrine constant, correctly failed the plan, and the failure
was then delivered anyway. The presentation question (stub basis) is
real but secondary; the primary defect is delivery-of-a-failed-plan +
a dead restructure net.

### 5. Is this new? — the failure MODE is old; the DEAD NET is new
- All-time: **254 of 845 completed runs shipped with passed=false (30%)**,
  203 of them failing `net_income_trajectory_viable`; earliest
  2026-05-08 (Sunny Glaze). Non-gating since 06-10; silent email since
  05-12. So "delivered though failed" is not new in kind.
- Since 08-01: **107 passed / 1 failed — Nine Fathom is the only one**,
  and the first failed-acceptance delivery since 07-31. The recent
  baseline was 100% pass, which is why it reads as a regression.
- **What changed since the deal-breaker batch: nothing in the gate,
  email, handler, loop, or completion writer** (last touches 08-08 /
  05-12 / 07-10 / 07-12 / 08-04). What DID change:
  (a) `c77094a` (08-12, WS1 per-line COGS) added the all-or-nothing
      contract rule, and `e26af21` (08-14) made per-line COGS common —
      neither touched `post_intake_restructure/` → **the restructure net
      is dead on every per-line-COGS draft** (the actual regression);
  (b) `7b26ff6` (08-14) opening-PPE depreciation lowers NI below EBITDA
      → lower Q11 NI margin;
  (c) `4cf365f` (08-15, A3 stated-capacity wall) caps the coherence
      growth multiple → lower Q11 revenue → lower Q11 NI margin;
  (d) the floor became the executive's 8% on 07-22 (`b7511cc`, Wave 2);
      under the pre-07-22 2pp constant this run would have PASSED.
  So (b)+(c) moved the number down while (d) had already moved the bar
  up, and (a) removed the rescue.

## Findings for Nick's ruling (nothing built)

R1 **DELIVERY OF A FAILED PLAN.** Today acceptance is an annotation
    (ruled 06-10 "gates flow, they don't crash"). Options: keep
    annotation but make it LOUD (email names failed_checks; workbook
    banner; run status distinct from a passing completion; operator
    ping) — vs re-arm the gate to withhold delivery on fail and route
    to the human inbox (delivery is human-mediated by prior ruling).
    Nick's call; the fallback-class law ("no plan ships on substituted
    judgment") suggests a failed verdict should at least never reach a
    client unflagged.
R2 **THE DEAD RESTRUCTURE NET — a real regression from WS1.** Fix shape:
    the searcher's synthesized new lines must carry a `COGS %` row (or a
    declared blend) so they satisfy the all-or-nothing rule; plus a
    fail-loud when the restructure raises the same ContractViolation on
    every rung (an `evals=0` search should never be silent). Engine
    territory → full apparatus.
R3 **ONE RULER.** The in-loop cascade must evaluate
    `net_income_trajectory_viable` with the same executive floor the
    final gate uses (pass model_input into `_evaluate_in_cascade`), or
    the cascade will keep blessing plans the gate fails.
R4 **THE EMAIL LIES BY OMISSION.** Print `acceptance_checks` failures
    (not just realism), and replace the hardcoded "restoration loop
    landed" with the loop's actual status. Presentation, spot-check.
R5 **Stale header comment** at `intake_consult.py:14671-14678` (claims
    500-on-fail) — delete or correct. Cosmetic.
R6 The NI research's stub-basis finding stands as a SECONDARY
    presentation item; its pass/fail claim is retracted (correction note
    added to that doc).

Sequence suggestion (Nick rules): R2 first (the net), R3 with it (same
engine surface, one full-apparatus turn), R1 as a policy ruling, R4/R5
as a cheap spot-check turn.
