# Where the Executive's Load Begins on Sunny's Path (scope only, no code)

**Frame.** Post-intake was built for two cooperating roles. **Python** authors mechanical
state moves. The **executive** (GPT Lineage-B: in-loop confirm/veto/choose during the
adaptation cascade) makes the judgment calls that steer a plan toward viability. The
executive is currently disconnected, so the cascade of boundary failures on Sunny's path is
mostly the **missing horse's load**, not dead weight. The viability **standard** (goalposts)
is already built + verified.

**Goal of this note:** trace the ordered contract boundaries from where Sunny is now
(MODEL_INPUT→SOLVER) to acceptance, classify each PLUMBING / EXECUTIVE LOAD / DEAD with
evidence, and state **the line** where mechanical Python work ends and executive load begins.

**Discriminating test per boundary:** *"Would this still need satisfying if BOTH horses were
hitched?"* Yes + Python can do it → PLUMBING. Yes + needs judgment → EXECUTIVE LOAD. No → DEAD.
When unsure between EXECUTIVE LOAD and DEAD, default to EXECUTIVE LOAD (reversible).

---

## Ordered boundary chain (where Sunny is → acceptance)

Pipeline spine: `run_target_seeking_orchestrated_system_run`
([orchestrator.py:1028](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1028))
→ deterministic adaptive policy → target-seeking solver + **adaptation cascade** →
`_run_post_cascade_completion` (cash → realism → finalize) → acceptance.

### B5 — MODEL_INPUT→SOLVER · `SolverInputContract.business_facts.fact_template`  → **PLUMBING**
- Where: validated at [orchestrator.py:1072](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1072); contract at [solver_input_contract.py:146-166](../../python/client_intake_and_finmo/post_intake_contracts/solver_input_contract.py#L146-L166) (`fact_template: Dict[str, Any]` **required**, [:164](../../python/client_intake_and_finmo/post_intake_contracts/solver_input_contract.py#L164)).
- Producer today: business_facts is assembled as a **flat** intake dict (name/address/start_date/…) at [intake_consult.py:7171-7183](../../python/api_handlers/intake_consult.py#L7171-L7183) and passed through `prepare_initial_grid_for_draft` ([runner.py:1968-1991](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1968-L1991)) — **no `fact_template` key is ever set**. No GPT/LLM call populates it anywhere in the live pipeline.
- Consumer today: every read is **defensive** and bottoms out in one field — `fact_template.get("business_stage")` with a fallback chain to `business_facts.business_stage` → `ops_json.business_stage` ([adaptive_planning/policy.py:355-362](../../python/client_intake_and_finmo/post_intake_adaptive_planning/policy.py#L355-L362); orchestrator reads [orchestrator.py:1216-1218](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1216-L1218), [:1634-1636](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1634-L1636); finmo_bridge [:3189-3191](../../python/client_intake_and_finmo/finmo_bridge.py#L3189-L3191)). The contract itself notes the shape was *"deliberately deferred… to Contract 5"* ([solver_input_contract.py:157-161](../../python/client_intake_and_finmo/post_intake_contracts/solver_input_contract.py#L157-L161)).
- **Test:** both horses hitched → still needed? Yes. Needs judgment? **No.** The one field consumed (`business_stage`) is now **age-derived by Python** (the locked decision in [planning_mode_and_stage_derivation.md](planning_mode_and_stage_derivation.md) §3; the viability standard derives stage from `business_age_months`), and `fact_templates.py` is a **prompt-rendering** engine for facts shown *to* GPT, not facts GPT produces. No executive populates it.
- **Disposition: FIX as plumbing** — Python wraps the already-captured intake facts into `fact_template` (stage from age), OR the contract field is relaxed to optional to match the defensive reads. Python both makes and consumes this shape.
- *Prime-suspect caveat (addressed):* this was flagged as likely EXECUTIVE LOAD ("the shape GPT populated"). The evidence says otherwise — no GPT producer exists, reads are defensive, and the only judgment it could carry (lifecycle stage) is already Python-owned via age-derivation. **Reversible flag:** if Nick later decides lifecycle stage should be an *executive* judgment rather than age-derived, `fact_template.business_stage` becomes EXECUTIVE LOAD — but that contradicts the locked age-derivation, so today it is PLUMBING.

### (between B5 and B6) — Adaptive policy → **PLUMBING**; **the adaptation cascade → EXECUTIVE LOAD** ← THE LINE
- `compute_adaptive_policy` is *"computed deterministically from intake + FINMO snapshot + industry profile"* ([orchestrator.py:1186-1199](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1186-L1199)) → **PLUMBING**.
- The **target-seeking solver** is a deterministic optimizer (Python). But when it / the realism gate can't land the plan in-band, the **adaptation cascade** is where confirm/veto/choose happens — landing a `cascade_landed_tier`, setting `plan_confidence`, choosing which adaptations steer toward the viability bands. **This is the executive's job and the missing horse.** → **EXECUTIVE LOAD.**

### B6 — SOLVER_OUTPUT · `SolverOutputContract` (approved_targets, envelope, finmo) → **EXECUTIVE LOAD** (downstream of the line)
- Where: [intake_consult.py:7296](../../python/api_handlers/intake_consult.py#L7296). The payload (approved targets / landed envelope) is the **output of the executive-driven cascade**; satisfying it requires the cascade to have landed. The contract check is mechanical; the *content* is executive-produced.

### 7a — Realism gate · `validate_industry_realism_bands` → **EXECUTIVE LOAD** (these are the goalposts)
- Where: [orchestrator.py:2928-2936](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2928-L2936). This IS the standard (per-metric bands → `realism_memo_json`). The gate is built; **clearing it (no hard_fail) is what the executive steers toward**. Passing requires the driver, not more plumbing.

### 7b — Finalize validation · `run_finalize_post_intake_validation` → **MIXED**
- Where: [orchestrator.py:3421-3480](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L3421-L3480).
- `solver_target_assertion` (targets met) → **EXECUTIVE LOAD** (requires the cascade landed targets). Global invariants / balance-sheet finalize / statement integrity → **PLUMBING** (mechanical; largely already passing — the alias-sync fix was one of these).

### B8 — Acceptance gate · `verify_run_acceptance` → **EXECUTIVE LOAD** (where the standard's verdict surfaces)
- Where: [gate.py verify_run_acceptance](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L660) (called [intake_consult.py:7440](../../python/api_handlers/intake_consult.py#L7440)). Of its checks, the executive-gated ones are: `cascade_landed_tier` not null, `plan_confidence` not null, `realism_gate_no_hard_fail`, `solver_target_assertion_*` — **all executive/cascade outputs.** The structural ones (revenue-not-flat, finalize-stage-reached) are plumbing. This is also where the viability standard's advisory verdict is now attached.

### B9 — Workbook export · `export_workbook_for_draft_id` → **PLUMBING** (downstream of acceptance)
- Where: [intake_consult.py:7663-7717](../../python/api_handlers/intake_consult.py#L7663-L7717). Mechanical serialization of the landed plan; runs after acceptance.

**DEAD:** none of B5→acceptance is *provably* dead under the chosen Lineage-B architecture, so
nothing here is tagged DEAD (the rule requires explicit proof; `fact_templates.py` rendering is
still live for the executive's prompts, not a Lineage-A remnant). The fact_template *contract
field* is over-strict, not dead — Python should satisfy or relax it (PLUMBING).

---

## THE LINE

> **Mechanical Python work ends at the solver-input bundle (B5) + the deterministic adaptive
> policy. The executive's load begins at the adaptation cascade** — the in-loop judge that,
> when the deterministic solver/realism can't land the plan in-band, decides which adaptations
> to make and **lands a `cascade_landed_tier`, sets `plan_confidence`, and meets the
> solver/realism targets**. Everything from SOLVER_OUTPUT (B6) through acceptance (B8) is gated
> on that executive-produced state; those boundaries fail today because the horse pulling them
> is unhitched, not because they are wrong.

**What this means for the build:**
1. **One last plumbing fix before the line:** B5 `fact_template` — Python populates it from the
   already-captured intake facts (stage from age) or the contract field is relaxed to match the
   defensive reads. (Plus any remaining mechanical finalize invariants as they surface.)
2. **Everything past the line is the executive's job-spec:** reconnect the Lineage-B in-loop
   judge to the adaptation cascade so it can land a tier + confidence and steer toward the
   (already-built, already-verified) viability standard. For a structurally non-viable case like
   Sunny, the executive's correct landing is a low-confidence / non-viable verdict — which the
   standard already computes; the cascade just needs the executive to *commit* it rather than the
   pipeline dying at an unmet target.

**Build trigger:** the line above is the executive's job-spec. The next build is reconnecting the
executive to the cascade — not forcing Python solo past B6+ (which would mean tearing out the
executive's harness or faking its judgment, both forbidden).
