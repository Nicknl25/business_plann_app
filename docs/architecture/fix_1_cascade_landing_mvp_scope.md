# Fix #1 — Cascade Landing: Sunny MVP Scope

**Status:** scope note. **No code.** This maps the adaptation cascade's current state, locates the
GPT-judge seam, traces the exact Python-only failure point, and specs the minimal behavior that
lands Sunny's verdict. Every claim is `file:line`-grounded. This note IS the build plan.

**Companion docs:** [fix_1_viability_standard_spec.md](fix_1_viability_standard_spec.md) (the verdict
STANDARD — already built + wired advisory), [fix_1_executive_load_boundary_scope.md](fix_1_executive_load_boundary_scope.md).

**Goal (restated):** the cascade should **LAND Sunny's verdict** — commit a `cascade_landed_tier` +
`plan_confidence` + the standard's `non_viable` result — **not** solve Sunny into viability, and
**not** die at an unmet target.

---

## 0. ONE-PARAGRAPH ANSWER (task 4 up front)

Landing Sunny's non-viable verdict is **deterministic Python, not GPT judgment.** The viability
STANDARD already computes `non_viable` for Sunny with no GPT and no cohort dependence
(`standard.py:100-101`, gates A/B), and it is already wired **advisory (non-gating)** at the
acceptance gate (`gate.py:790-802`). The cascade itself never crashes — it always lands a committed
in-bounds (floored) plan. The single thing that turns "land a verdict" into "crash" is **downstream
of the cascade**, in the orchestrator's finalize step: when the floored plan doesn't hit the solver's
output targets (which, for a genuinely non-viable business, it never can), `run_finalize_post_intake_validation`
raises `solver_target_residual` (`finalize_post_intake.py:858`), and the orchestrator re-raises it
under `CONVERGENCE_TEST_MODE` (`orchestrator.py:3608-3609`). **The MVP is to reframe that one fatal
assert into a committed low-confidence outcome** — accept the standard's verdict, stamp
`cascade_landed_tier` + `plan_confidence`, finalize successfully. No GPT. GPT judgment (confirm/veto/
choose among restructuring options) is the *full executive* (ii) — it only matters for *salvageable*
plans, and is irrelevant to a business that is non-viable by physics.

---

## 1. CASCADE MACHINERY INVENTORY

Two distinct loops sit in series. **Naming them apart is the whole point.**

### 1A. The amalgamated restructure cascade (`post_intake_amalgamated/protocol/`) — the propose→judge→commit loop

| Module | Role (propose / judge / commit) | State | Evidence |
|---|---|---|---|
| `cascades.py` | **Policy** — 5 per-mode tier tables (V/G/C/B/H), source of truth | LIVE | `CASCADES` index `cascades.py:456-462`; tiers `:119-449` |
| `restructure_proposer.py` | **PROPOSE** — Python authors the move (`propose_for_tier` builds Type-A single / Type-B option lists) | LIVE | called at `session_driver.py:348, 776` |
| `responder.py` | **JUDGE seam** — round-trips GPT through 4 tools (confirm/veto/choose/other) | LIVE (degrades — see §2) | `make_amalgamated_responder` `responder.py:405-566` |
| `response_tools.py` | **JUDGE shapes** — the 4 `ProposalResponse` constructors + in-band validation | LIVE | imported `responder.py:54-60`; parsed `:385-398` |
| `session_driver.py` | **Orchestration** — the §12 state machine; runs propose→judge→commit→floor | LIVE | `run()` `:254-302`, `_walk_cascade` `:306-479`, `_apply_tier` `:483-635` |
| `session_factory.py` | **Wiring** — builds a fully-wired `SessionDriver`; defaults `responder=make_amalgamated_responder` | LIVE | `make_session_driver` `:291-382`; responder default `:316-321` |
| `floor.py` | **COMMIT (deterministic)** — cascade-as-floor walker + §9.2 mode primitives; never consults GPT | LIVE | `floor_for_mode` invoked `session_driver.py:734` |
| `reason_codes.py` | **Audit vocabulary** — closed `ReasonCode`/`AppliedBy`/`StepType` enums | LIVE | enums `reason_codes.py:24-110` |

**Critical fact:** the `SessionDriver`'s terminal states are `RESOLVED`, `MODE_FLOOR`,
`STAGNATION_FLOOR_ALL`, `META_HALTED`, `BUDGET_EXHAUSTED_FLOOR` (`session_driver.py:86-91`). **None of
them is `non_viable`.** The doctrine is explicit: floor-state plans are "committed, in-bounds,
viable-in-the-floor's-sense" (`session_driver.py:1080-1082`). The cascade has **no concept of giving
up** — it always claims to have landed a usable plan. Producing a *verdict* (viable vs non-viable) is
not the cascade's job; it is the STANDARD's job, computed later at acceptance.

The cascade is wired into the live run: `runner.py:1865` calls `make_session_driver` (no `responder=`
override → production GPT responder), then `driver_run_with_audit_wrapper` (`runner.py:1880`).

### 1B. The post-cascade completion (`post_intake_solver/orchestrator.py`) — the gate/finalize layer

This runs **after** the cascade has landed a plan. It is **not** a propose/judge/commit loop — it is a
validation + finalize pass. Its three relevant stages:

1. **Realism gate** (`orchestrator.py:2928-2936`) — `validate_industry_realism_bands`.
2. **`solver_target_assertion`** (`orchestrator.py:3071-3123`) — `assert_solver_respected_targets`.
3. **Finalize** (`orchestrator.py:3417-3433`) — `run_finalize_post_intake_validation`.

This layer is where Sunny dies (§3).

---

## 2. THE GPT-JUDGE SEAM

**Where it lives:** the seam is the `SessionDriver._responder` callback (`session_driver.py:159, 175`),
invoked at `_apply_tier` (`session_driver.py:511-514`). The driver **does not call GPT directly** — by
design (`session_driver.py:14`). The production implementation is `make_amalgamated_responder`
(`responder.py:405`), which exposes the four tools as the *only* legal GPT responses
(`responder.py:75-152`, `tool_choice:"required"` `:347`) and parses the tool call into a
`ProposalResponse` (`responder.py:385-398`). Confirm/veto/choose **are built, not stubbed, not raising.**

**What "GPT was pulled" means concretely.** The seam is not deleted — it *degrades*. When
`OPENAI_API_KEY` is unset, the responder returns a **synthetic veto for every proposal**
(`responder.py:468-469`). The consequence cascades deterministically:

- Every Type-A judge point → synthetic veto → `_apply_tier` logs a veto, applies nothing, advances
  (`session_driver.py:520-537`).
- The walk reaches the floor tier (`is_floor`) → `_invoke_floor_for_mode` → deterministic floor
  primitive produces an in-bounds plan (`session_driver.py:339-346`, `floor.py`).
- Terminal state = a floor state, **never** `non_viable`.

So **"runs Python-only" ≡ "responder synthetic-vetoes to the floor."** That is the disconnected-judge
behavior: at each judge point with no GPT, the cascade auto-vetoes and walks to the floor. (Budget-aware
mode auto-*confirms* Type-A instead — `session_driver.py:501-509` — but only after the budget is nearly
spent; the default no-GPT behavior is veto-to-floor.) Either way the cascade lands a floored plan and
hands off to §1B.

---

## 3. THE PYTHON-ONLY FAILURE POINT (where it "dies at an unmet target")

The cascade does **not** die — it floors. The death is in the post-cascade completion (§1B), and the
two prime suspects behave differently than "assert and crash":

**Suspect A — realism gate (`orchestrator.py:2928-2986`): NOT the death.** `validate_industry_realism_bands`
raises `RealismBandViolation` on first hard-fail, but it is **caught locally** (`orchestrator.py:2987`)
and converted to an advisory payload with `halted_on_hard_fail=True` (`:3004-3006`). Execution
continues. Advisory, not fatal.

**Suspect B — `solver_target_assertion` (`orchestrator.py:3071-3123`): the mechanism, via finalize.**
`assert_solver_respected_targets` itself **never raises** — it returns `{status, violations, …}` and is
wrapped in a try/except that downgrades to `checked:False` on any error (`orchestrator.py:3116-3121`).
The kill happens when **finalize re-runs the same assertion**:

1. `run_finalize_post_intake_validation` collects `gate_kind=="hard_fail"` violations into `errors`
   (`finalize_post_intake.py:842-854`).
2. `_raise_if_errors(errors)` raises `RuntimeError("post_intake_finalize_validation_failed: …
   solver_target_residual: <metric>@q<n> produced=… target=[…] residual=…")` (`finalize_post_intake.py:858`,
   helper `:39-44`).
3. The orchestrator catches it (`orchestrator.py:3480`), routes payroll-feasibility failures to repair,
   and for everything else **re-raises iff `convergence_test_mode_enabled()`** (`orchestrator.py:3608-3609`).
   In production mode it is swallowed into an advisory `finalize_validation.status="failed"` trace
   (`orchestrator.py:3610-3620`).

**Precise death for Sunny:** `finalize_post_intake.py:858` `_raise_if_errors([... "solver_target_residual" ...])`,
propagated by `orchestrator.py:3608-3609` under `CONVERGENCE_TEST_MODE` (flag def:
`fail_fast/common.py:106-107`). This is exactly the "solver_target_assertion at finalize" the task
suspected. A non-viable plan trips it because the floored plan cannot hit the solver's output targets —
and finalize treats "didn't hit target" as a hard error rather than "this business can't get there."

**Note on the earlier crash:** before reaching finalize, Sunny historically hard-failed at the
payroll/revenue feasibility assert. Recent Fix #1 commits demoted that to advisory/non-gating
(`f5afb51`, `886074f`), which is what now lets execution reach the finalize assert. The finalize
solver_target_residual hard-fail is the **next** (and currently terminal) Python-only death.

---

## 4. THE KEY QUESTION — deterministic cascade behavior vs genuine GPT judgment

**Separate the two cleanly:**

### (i) Sunny MVP — "commit a verdict (incl. non-viable) instead of crashing" → **deterministic Python. NO GPT.**

Everything the verdict needs already exists and is GPT-free:

- The **standard** computes `non_viable` deterministically — gate failure ⇒ `VERDICT_NON_VIABLE`
  (`post_intake_viability/standard.py:100-101`); the verdict enum exists (`standard.py:36-38`); the
  pipeline adapter never raises (`adapter.py:120-149`). For Sunny it returns `non_viable` and is covered
  by a direct test (`Test Files/test_fix_1_viability_standard.py:542-577`).
- It is already **wired advisory, non-gating** at acceptance (`gate.py:790-802`); `verdict["passed"]`
  is computed from the gate's own checks, not from the standard (`gate.py:764`).
- `cascade_landed_tier` and `plan_confidence` are **real persisted columns** written by
  `persist_cascade_resolution` (`intake_consult_draft.py:~3095`, UPDATE at `:3147`), derived from
  `cascade_diagnostics.tier_landed` or the `_PLAN_CONFIDENCE_TO_TIER` lookup.

The *only* missing behavior is in §1B: **don't let "solver didn't hit its targets" be fatal when the
business is non-viable by physics.** That is a deterministic decision — "targets provably unreachable ⇒
accept the standard's verdict and land it at low confidence" — requiring **zero** GPT.

### (ii) Full executive (later) — "drive a salvageable plan toward viable" → **genuine GPT judgment.**

This is the responder's confirm/veto/choose role: among Type-B options (pricing `V3/G3`, payroll
restructure `V6`, target compression `G5/C4`) and Type-A vetoes, GPT picks the lever that best fits
*this specific* business to push a *borderline* plan over the gates. This is real judgment because the
choice is business-contextual, not formulaic. **It is irrelevant to Sunny:** no lever choice makes a
physically non-viable business pass gates A/B, so the MVP must not wait on it.

**The trap (per hard rules):** do **not** fake (ii) inside (i). The MVP must not invent a heuristic that
"decides" viability — the standard already decides it deterministically. The MVP only changes *what
happens to that decision* (land it vs crash). Naming: committing the standard's verdict = **Python's**
deterministic move; choosing restructuring options to chase viability = **GPT's** judgment, deferred.

---

## 5. MVP SPEC — the minimal behavior that lands Sunny's verdict

**Scope:** change §1B only (the orchestrator finalize handling) + ensure the landing fields are stamped.
**Do not** modify the `SessionDriver` (it correctly floors), the responder, or the standard.

1. **Reframe the finalize solver-target hard-fail as a landed outcome when the plan is non-viable.**
   At the `orchestrator.py:3480-3620` finalize except-handler, when the failure is a
   `solver_target_residual` (targets unreachable) — corroborated by the realism gate's
   `halted_on_hard_fail` payload (`orchestrator.py:3004-3006`) and/or the standard's `non_viable`
   verdict — treat it as **"cascade landed at floor, plan non-viable, low confidence"** instead of
   re-raising. This is the one behavioral change. Keep the hard-fail for *genuine* solver bugs (a plan
   the standard says *should* be viable but the solver mishandled) — distinguish "unreachable physics"
   from "solver defect."

2. **Stamp the landing.** Ensure `cascade_landed_tier` (the floor tier the cascade terminated at, from
   the `amalgamated_session_result.termination_state` / `cascade_diagnostics.tier_landed`) and
   `plan_confidence` (low, for a floored/non-viable landing) are persisted via the existing
   `persist_cascade_resolution` path (`intake_consult_draft.py:3147`). Confirm at build time that these
   are populated on a floor-landed run (not only on a clean RESOLVED run).

3. **Thread the verdict through.** The standard's `non_viable` result is already attached advisory at
   acceptance (`gate.py:795`). MVP verifies the full run *reaches* acceptance (no upstream crash) so the
   verdict is committed in `acceptance_verdict_json`. The acceptance gate already completes normally on a
   non-viable advisory verdict — no change needed there.

**Acceptance criterion for the MVP:** a Sunny run under `CONVERGENCE_TEST_MODE=true` finishes without
raising, with `cascade_landed_tier` + `plan_confidence` set and the acceptance verdict carrying
`viability_standard.verdict == "non_viable"`.

---

## 6. TEST HARNESS (task 5) — exercise the cascade decoupled from the producer plumbing

Mirror how the standard was verified directly (`Test Files/test_fix_1_viability_standard.py` feeds
Sunny's real finmo straight into `evaluate_viability`). For the cascade, the seams are already
injectable:

- **Driver-level (hermetic, no GPT, no DB):** `make_session_driver(conn=None, draft_id, planning_run_id,
  mirror=Mirror(business_facts=…, plan_state=…), responder=<fake>)` — the factory accepts an injected
  responder and a `conn=None` (pattern proven in `test_phase_9_p3_33_phase3_step8a_session_factory.py:59-77`).
  A `fake_responder = lambda **_: ProposalResponse(kind="veto", reason=…)` reproduces the **Python-only
  (no-GPT) path** without an API key; injecting `kind="confirm"` exercises the apply path. Feed a
  synthetic **contract-valid `SolverInputContract` bundle** (`post_intake_contracts/solver_input_contract.py`)
  as the `model_input_json` / `plan_state`, plus **Sunny's real finmo** as `finmo_json`, and a
  `build_finmo` stub. Run via `driver_run_with_audit_wrapper` and assert the terminal state is a floor
  state (the cascade lands, never `non_viable`).

- **Completion-level (where the death is):** drive `post_intake_solver/orchestrator._run_post_cascade_completion`
  (or `run_finalize_post_intake_validation` directly) with the floored Sunny `final_model_input_json` +
  `final_finmo_json` and `CONVERGENCE_TEST_MODE=true`, and assert it currently raises
  `solver_target_residual` (the failure to fix), then — post-MVP — assert it lands the verdict instead.

This decouples cleanly: the producer plumbing (intake → set_* authoring) is replaced by a synthetic
contract-valid bundle + Sunny's finmo, exactly as the standard's harness bypassed intake.

---

## 7. EVIDENCE INDEX (file:line)

- Cascade tier tables: `post_intake_amalgamated/protocol/cascades.py:119-462`
- Propose: `restructure_proposer.py:propose_for_tier` (called `session_driver.py:348, 776`)
- Judge seam + synthetic veto: `responder.py:405-566`, no-key veto `:468-469`; tools `:75-152`
- Judge dispatch / commit: `session_driver.py:483-635`, floor branch `:339-346`
- Terminal states (no `non_viable`): `session_driver.py:86-91`; floor doctrine `:1080-1082`
- Wiring (responder default): `session_factory.py:316-321`; live call `runner.py:1865, 1880`
- Realism gate (caught, advisory): `orchestrator.py:2928-2936`, catch `:2987-3006`
- solver_target_assertion (no raise): `orchestrator.py:3071-3123`
- Finalize raise: `finalize_post_intake.py:842-858`; re-raise under test mode `orchestrator.py:3608-3609`
- Flag: `fail_fast/common.py:106-107` (`CONVERGENCE_TEST_MODE`)
- Standard verdict (`non_viable`): `post_intake_viability/standard.py:36-38, 100-101`; adapter `adapter.py:120-149`
- Advisory wiring at acceptance: `post_intake_acceptance/gate.py:790-802`, passed `:764`
- Landing fields: `intake_consult_draft.py:~3095, 3147` (`cascade_landed_tier`, `plan_confidence`)
- Harness pattern: `test_phase_9_p3_33_phase3_step8a_session_factory.py:59-77`; standard harness
  `Test Files/test_fix_1_viability_standard.py:542-577`
