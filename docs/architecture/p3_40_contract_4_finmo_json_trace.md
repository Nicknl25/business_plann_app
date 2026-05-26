# P3.40 Contract 4 — FinmoJsonContract — Pre-spec trace

**Boundary:** 6 (SOLVER → FINMO_BUILD).
**Status:** pre-spec trace. Holds for review before the spec doc is drafted.
**Companion to:** [p3_40_contract_4_finmo_json_spec.md](./p3_40_contract_4_finmo_json_spec.md) (not yet written).
**v2 inventory baseline:** [p3_40_pipeline_data_flow_inventory_v2.md §Boundary 6](./p3_40_pipeline_data_flow_inventory_v2.md#boundary-6-solver--finmo_build) (lines 530-575).

This document captures the trace-before-spec work for Contract 4.
Same discipline as Contracts 1, 2, and 3: enumerate the actual
producer + consumer call paths from production code, surface
divergences from the v2 inventory and the directive's framing,
and call out anything that would change the shape of the contract
before the spec is written.

---

## Headline finding — read this first

**The v2-inventory-defined "Boundary 6" surface
(`build_python_finmo_json(model_input_json: Dict[str, Any])`) is
already typed end-to-end by Contract 1's
`FinmoModelInputContract`.** Both the consumer-side gate (at
finmo_bridge.py:619 entry) and the producer-side gate (at the
amalgamated-session bundle return at runner.py:1809-1822) live
inside Contract 1's enforcement surface today.

The directive's framing — "Contract 4 types the handoff between
the solver's return dict and the finmo_bridge's build path" —
describes TWO distinct boundaries that v2 conflates:

| Surface | What flows | Producer | Consumer | Already typed? |
|---|---|---|---|---|
| **A.** `build_python_finmo_json` input | single `model_input_json` arg | many (initial-grid runner, orchestrator closures, cash strategy, numeric solver, headcount, fail-fast) | the function body | **YES — Contract 1's FinmoModelInputContract.** Producer + consumer gates already wired. |
| **B.** orchestrator return value | 14-key `next_result` dict | `run_target_seeking_orchestrated_system_run` at orchestrator.py:1028+ | API handler at intake_consult.py:7103 → 7418+ (acceptance gate + persist + workbook trigger) | **NO.** Not yet typed. |

Naive Contract 4 (boundary 6 per v2 inventory) is a one-liner: it
already exists. The spec doc's headline Flag is whether
**Contract 4 should pivot to type Surface B (the orchestrator
return)** instead, since that's the substantive un-typed handoff
the directive's framing alludes to and where the un-checked
shape drift currently lives.

§T1 through §T8 below trace both surfaces. §T8 frames the
choice for the spec.

---

## T1. Consumer entry

### T1.1 `build_python_finmo_json` is the FINMO build entry (Surface A)

Signature, verbatim from
[finmo_bridge.py:619-625](../../python/client_intake_and_finmo/finmo_bridge.py#L619):

```python
def build_python_finmo_json(
  *,
  model_input_json: Dict[str, Any],
  finmo_path: Optional[str] = None,
  emit_diagnostic_fn: Optional[Any] = None,
) -> Dict[str, Any]:
```

One data parameter (`model_input_json`) + one configuration
path (`finmo_path`) + one observability handle (`emit_diagnostic_fn`).

**Contract 1's consumer-side gate already lives at the entry of
this function**
([finmo_bridge.py:626-660](../../python/client_intake_and_finmo/finmo_bridge.py#L626)):

```python
validate_model_input_at_boundary(
  model_input_json if isinstance(model_input_json, dict) else {},
  side=SIDE_CONSUMER,
  emit_diagnostic_fn=emit_diagnostic_fn,
)
```

This is the Boundary 6 consumer-side gate per v2 inventory. It's
already producing diagnostic events under
`PhaseCode.MODEL_INPUT_CONTRACT` (verified by the Commit 2 / 3
diagnostic-stack restoration work).

### T1.2 Call sites of `build_python_finmo_json` (Surface A producers)

Counted via grep across `python/`: **15 call sites** in 11 files.
All pass `model_input_json` as the sole data argument:

| File:line | Caller | Notes |
|---|---|---|
| [finmo_bridge.py:3853](../../python/client_intake_and_finmo/finmo_bridge.py#L3853) | internal re-build inside finmo_bridge | self-call |
| [numeric_solver.py:690](../../python/client_intake_and_finmo/numeric_solver.py#L690) | numeric solver rebuild | |
| [numeric_execution.py:874](../../python/client_intake_and_finmo/numeric_execution.py#L874) | numeric execution rebuild | |
| [fail_fast.py:1826](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1826) | post-intake fail-fast rebuild | |
| [post_intake_cash/runner.py:3134](../../python/client_intake_and_finmo/post_intake_cash/runner.py#L3134) | cash-pass rebuild | |
| [post_intake_cash_strategy/orchestrator_invocation.py:444](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L444), [579](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L579), [625](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L625) | cash-strategy 3 sites | |
| [post_intake_headcount/schedule.py:2068](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2068) | headcount projection rebuild | |
| [post_intake_headcount/feasibility_repair.py:98](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L98) | feasibility repair rebuild | |
| [post_intake_initial_grid/runner.py:815, 855, 1289, 1360](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L815) | initial-grid 4 sites | |
| [post_intake_solver/orchestrator.py:639, 2127, 2222, 2417, 2864](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L639) | orchestrator 5 sites | including `_build_finmo_callable` closure at 639 (the inner-loop FINMO rebuild) |

Every call site passes `model_input_json=…` as the sole data
argument. The `_build_finmo_callable` closure at
[orchestrator.py:620-641](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L620)
captures `business_facts`, `ops_json`, `people_json`,
`financials_json`, `financials_year1_json`, `fulfillment_json`,
`marketing_model_json` for "potential future use" but **the closure
body explicitly does not pass them to `build_python_finmo_json`**:

> `# The auxiliary kwargs (business_facts, ops_json, etc.) aren't
>  part of build_python_finmo_json's signature — they're already
>  stamped onto model_input_json by the time _build_model_input_overlay
>  runs. The closure-captured args are kept here only for potential
>  future use ...; today they are intentionally unused.`

This is decisive: the surface IS `model_input_json` and nothing
else. Producer-side enrichment (`set_capex_rd_balance_seed`,
`set_balance_sheet_contextual_seed`, derived-driver policy
application) all stamp ONTO `model_input_json` before the build
call. No side-channel data crosses the boundary.

### T1.3 The directive's "solver return dict" alludes to a different boundary (Surface B)

The directive specifies: "Contract 4 types the handoff between
the **solver's return dict** and the finmo_bridge's build path."

The solver does NOT pass its return dict to `build_python_finmo_json`.
The solver:
- INTERNALLY calls `build_python_finmo_json` many times during
  the iteration (Surface A producer sites above).
- RETURNS a 14-key dict (`next_result`) to its caller
  (intake_consult API handler), NOT to finmo_bridge.

So "solver return dict → finmo_bridge build" isn't a real handoff.
The actual two boundaries are:
- (A) `build_python_finmo_json` input — already Contract 1.
- (B) `run_target_seeking_orchestrated_system_run` return value
  — consumed by the API handler at intake_consult.py:7418+.

**The honest read: the directive's intent is Surface B, even
though its naming ("FinmoJsonContract") and v2-inventory
references suggest Surface A.** Spec doc §1 Flag 0 lands this
choice with Nick. The rest of this trace fully documents Surface
B so the spec has the data either way.

---

## T2. Solver return-dict shape (Surface B) — what gets stamped

Tracing `next_result` from initialization to return across
orchestrator.py (cited by line number).

### T2.1 Initialization

[orchestrator.py:1701](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1701):

```python
next_result = copy.deepcopy(inner_result if isinstance(inner_result, dict) else {})
```

`next_result` inherits from `inner_result` — the post-inner-runner
output. Per Contract 3 Div-1, the inner runner is Phase-8-bypassed:
its return is the hardcoded passthrough dict at
[orchestrator.py:1420-1425](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1420)
with status `"phase_8_inner_runner_bypassed"`. So `inner_result` is
effectively `{"status": "phase_8_inner_runner_bypassed", ...}` at
init, and the rest of `next_result`'s keys come from explicit
orchestrator stamps below.

### T2.2 Orchestrator stamp sites

All `next_result["<key>"] = ...` writes in orchestrator.py
(grepped + de-duped):

| Key | Line | Producer | Type today |
|---|---|---|---|
| `model_input_json` | 1703 | final solver state | `Dict[str, Any]` — **Contract 1 shape (`FinmoModelInputContract`)** |
| `finmo_json` | 1705 | last `build_python_finmo_json` result | `Dict[str, Any]` — **Contract 2 shape (`FinmoOutputContract`)** |
| `target_seeking_diagnostics` | 1706 | per-iter solver diagnostics | `Dict[str, Any]` opaque |
| `plan_confidence` | 1707 | `"high_no_adaptation"` / `"high_with_adaptation"` / etc. | `str` (enumerable; T4 to confirm closed set) |
| `adaptation_cascade_diagnostics` | 1709 | cascade-tier outcome dict | `Optional[Dict[str, Any]]` opaque |
| `adaptive_policy` | 1713 | `AdaptivePolicy.to_dict()` | `Dict[str, Any]` opaque (already a typed AdaptivePolicy upstream; dict round-trip here) |
| `gpt_call_budget_diagnostic` | 1722 | GPT call counter | `Dict[str, Any]` opaque, best-effort (wrapped in try/except) |
| `handler_trace_diagnostic` | 1740 | handler-trace buffer dump | `Dict[str, Any]` opaque, best-effort |
| `payroll_headcount` | 1769 (`setdefault`) | echoed input + cascade restoration updates | `Optional[Dict[str, Any]]` — **Contract 2 shape (`PayrollHeadcountContract`)** |
| `solver_target_assertion` | 3123 | finalize-validation assertion | `Dict[str, Any]` opaque |
| `debt_schedule` | 3144 | post-cash-pass debt schedule build | `Dict[str, Any]` — **Contract 2 shape (`DebtScheduleContract`)** |
| `capital_lease_schedule` | 3166 | post-cash-pass lease schedule build | `Dict[str, Any]` opaque (no existing contract) |
| `realism_memo_json` | 3705 | realism-gate evaluation output | `Dict[str, Any]` opaque |
| `post_cascade_completion` | 3xxx (via diagnostics dict) | trace dict | `Dict[str, Any]` opaque |

**Plus** whatever `inner_result` carried at init, which today is
only `{"status": "phase_8_inner_runner_bypassed", ...}` (T7
discusses whether the contract should accept or forbid inherited
keys).

### T2.3 Stamp-site dispersion

The 14+ stamp sites are spread across **600+ lines** of
orchestrator.py (1703 through 3705). Most sites are inside
conditional branches:
- The `model_input_json` / `finmo_json` pair is rewritten at AT
  LEAST 10 different sites in orchestrator.py (per Contract 3
  §T6 — grep shows lines 1665, 1933, 2008, 2095, 2218, 2284,
  2470, 2630, 2831 in addition to the 1703 / 1705 base case).
  Each path lands the right shape; the issue is structural
  dispersion, not value drift.
- `solver_target_assertion`, `debt_schedule`, `capital_lease_schedule`,
  `realism_memo_json`, `post_cascade_completion` are all stamped
  inside `_run_post_cascade_completion` (orchestrator.py:1788+),
  not in `run_target_seeking_orchestrated_system_run` directly.

**Producer-side gate implication:** placing a single
"validate-the-return-dict" gate at the orchestrator entry's
`return next_result` would not work — there are TWO candidate
return statements (line 1768 and line 1773, the second after the
post-cascade tail). And the dict is mutated extensively across the
function body. The gate would need to land at EACH return site —
2 sites — OR be restructured as a "validate before return" wrapper
around the whole function. §T7 elaborates.

---

## T3. Consumer-side: what intake_consult reads from the solver return

Consumer is the API handler at
[intake_consult.py:7261+](../../python/api_handlers/intake_consult.py#L7261).
After `result = _run_planning_system_for_draft(...)` at line
7276, the handler reads from `result`:

| Field | Line | Read shape | Producer status |
|---|---|---|---|
| `result.get("planning_run_json")` | 7418 | isinstance(dict) else `{}` | **PHANTOM-READ — solver never stamps this.** Always falls back to `{}`. |
| `result.get("numeric_solver_feedback_json")` | 7422 | isinstance(dict) else `{}` | **PHANTOM-READ — solver never stamps this.** Always falls back to `{}`. |
| `result.get("planning_runtime_json")` | 7426 | isinstance(dict) else `{}` | **PHANTOM-READ — solver never stamps this.** Always falls back to `{}`. |
| `result.get("planning_context_summary_json")` | 7430 | isinstance(dict) else `{}` | **PHANTOM-READ — solver never stamps this.** Always falls back to `{}`. |
| `result.get("draft_id")` | 7434 | `str(...)` else fallback to caller's `draft_id` | **PHANTOM-READ — solver never stamps `draft_id`.** Falls back. |

**Every single key the API handler reads from `result` is a
phantom-read.** The actual values come from elsewhere (DB row, or
the persist-layer's snapshot that orchestrator.py:3xxx wrote
INTO the database). The API handler's defensive `.get()` chain
just provides fallback-to-empty-dict on every read.

This is the same pattern Contract 2 §T3 found at the workbook
boundary, but inverted: at Contract 4 it's the CONSUMER doing
phantom-reads, not the producer doing phantom-writes. The values
the consumer needs are in the DB; the producer's return dict is
ALSO sent over the wire as the JSON response body but the post-
acceptance block reads from `result` defensively in case the
solver's return dict has different data.

Then the acceptance gate at line 7455 calls
`verify_run_acceptance(conn, draft_id=..., planning_run_id=...)`
which queries the DB directly. So even the acceptance verdict
doesn't structure-read `result`.

**What DOES `result` flow into?** Per the orchestrator return
contract: it's serialized as the JSON HTTP response body. The
client (UI / external caller) reads it. The API handler also
forwards keys like `draft_id` for downstream log lines.

### T3.1 What the orchestrator's INTERNAL persist site reads from the bundle

Separately from the API handler's read of `result`, the orchestrator's
internal `_persist_unified_convergence_state` call at
[orchestrator.py:3609](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L3609)
takes structured values from local vars (NOT from `result`):
`final_model_input_json`, `final_finmo_json`,
`controller_resolution_state`, `resolution_summary`, etc. These
DON'T cross any Boundary 6 surface — they're internal to the
solver function.

---

## T4. Composition with prior contracts

For each key in `next_result` (Surface B):

| Key | Composes with | Notes |
|---|---|---|
| `model_input_json` | **Contract 1 — `FinmoModelInputContract`** | Final mutated state. Round-trips through `_apply_restoration_to_model_input`, `_stamp_solver_inputs`, every iteration's lever updates. Type at this boundary should be FinmoModelInputContract; Contract 1's contract_version Literal still applies. |
| `finmo_json` | **Contract 2 — `FinmoOutputContract`** | Result of the last `build_python_finmo_json` call. Already typed by Contract 2 at finmo_bridge's OUTPUT (workbook boundary); same shape applies here. |
| `payroll_headcount` | **Contract 2 — `PayrollHeadcountContract`** (Optional) | Echoed input + cascade restoration updates. Same Contract 2 shape. |
| `debt_schedule` | **Contract 2 — `DebtScheduleContract`** | Built by `build_debt_schedule_snapshot` at post-cash-pass site. Same Contract 2 shape (`post_intake_debt_amortization_schedule_v1`). |
| `capital_lease_schedule` | NO existing contract | Built similarly to debt_schedule but no Contract 2 type. Spec choice: type opaque or define a new typed sub-contract. |
| `target_seeking_diagnostics`, `adaptation_cascade_diagnostics`, `adaptive_policy`, `gpt_call_budget_diagnostic`, `handler_trace_diagnostic`, `solver_target_assertion`, `realism_memo_json`, `post_cascade_completion` | NO existing contract | All diagnostic dumps. Type as opaque `Dict[str, Any]` for first cut. |
| `plan_confidence` | Closed-set string | Per orchestrator.py:1558 the init is `"high_no_adaptation"`; reassigned by `run_adaptation_cascade` to other values. Spec to enumerate via Literal[...] (TC-equivalent for Contract 4). |

**Re-imports for the contract module would mirror Contract 3's
pattern:** import `FinmoModelInputContract`, `FinmoOutputContract`,
`PayrollHeadcountContract`, `DebtScheduleContract` from their
defining modules. No redefinition. Same `ContractViolation`
re-export.

---

## T5. Silent fallback / defensive patterns

### T5.1 At the consumer-side (intake_consult.py:7418-7434)

Every `result.get(<key>)` read uses the pattern:

```python
key = (
  result.get("<key>")
  if isinstance(result.get("<key>"), dict)
  else {}
)
```

Five sites, all defensive fall-back to `{}`. None catch errors;
they silently produce empty dicts on absent / wrong-type keys.

A Contract-4-typed `result` would let the API handler write
`contract.<key>` directly, eliminating these fallbacks. But per
T3, the keys it reads ARE phantom-reads, so the fallbacks fire
on every run today and produce `{}` anyway. Tightening here would
either:
- Surface the phantom-read as a contract violation (if those
  keys become required) — risky, breaks the "always returns 500"
  path
- Type each as `Optional[Dict[str, Any]]` — preserves current
  behavior but moves the fallback from runtime to type-level

### T5.2 Inside finmo_bridge (Surface A)

At [finmo_bridge.py:626-660](../../python/client_intake_and_finmo/finmo_bridge.py#L626)
the consumer-side gate uses Contract 1; no defensive `or {}`
patterns survive at the function entry. Per-row defensive patterns
inside the helpers called below remain (R6 from Contract 1).

### T5.3 At producer sites of Surface B

Orchestrator stamps `next_result["<key>"] = <value>` directly in
most cases. A few sites use `setdefault` (line 1769:
`next_result.setdefault("payroll_headcount", payroll_headcount)`).
The `setdefault` pattern is intentional — preserves an
upstream-assigned value if present. With a contract, the field
typing would still allow this since the final value is what gets
validated.

---

## T6. Mutation between solver return and finmo_bridge entry

### T6.1 Surface A (build_python_finmo_json input)

NONE. The consumer-side gate at finmo_bridge.py:626-660 validates
on entry; everything past that point is internal. The producer
side does plenty of mutation (cascade restoration, lever updates,
seed application) but ALL of it happens BEFORE the
`build_python_finmo_json(model_input_json=…)` call — meaning the
producer-side gate (if added at the call site) would validate
the mutated final form.

Today there's no single producer-side gate at Surface A — each of
the 15 call sites would need its own. Per the 15-call-site count,
this is the same situation as Contract 2 (5 writers → R8 defer).
**Spec Flag candidate: per-call-site producer gates at Surface A
not feasible.** Contract 1's existing producer-side gate at
runner.py:1809-1822 covers exactly ONE of the 15 sites (the
initial-grid bundle return); the other 14 fire without an
upstream Contract 1 producer check.

### T6.2 Surface B (orchestrator return)

EXTENSIVE mutation inside the orchestrator function body. The
14+ stamp sites span 600 lines. After the final `return
next_result` statement, no mutation happens — intake_consult just
forwards `result` through `_run_planning_system_for_draft_unified`
back to the API endpoint.

**Spec implication:** a Contract-4 gate at Surface B could land
at one of three points:
1. Immediately before each `return next_result` (2 sites) —
   redundant but localized.
2. Inside `_run_planning_system_for_draft_unified` after the
   orchestrator call returns — single site, catches both
   orchestrator return paths.
3. At the API handler immediately after `result =
   _run_planning_system_for_draft(...)` — single site, also catches
   both returns. Same site that runs the acceptance gate.

§T7 ranks these.

---

## T7. Producer-side gate feasibility

### T7.1 Surface A

**Infeasible without consolidation.** 15 call sites across 11
files. Each would need its own gate, OR `build_python_finmo_json`
would need a new "trusted entry" wrapper that callers use instead.

Contract 1 already has a "single producer-side gate at
runner.py:1809-1822 + consumer-side gate at finmo_bridge.py:626".
The 14 other call sites of `build_python_finmo_json` are inside
the solver loop or post-cash-pass and don't have producer-side
contract gates — they are CONSUMED by the same Contract 1
consumer-side gate at finmo_bridge.py:626, so each is implicitly
checked at the consumer end. The Contract 4-equivalent "every
producer site gates separately" would be redundant.

**Spec recommendation:** at Surface A, the existing Contract 1
producer + consumer gates ARE the Contract 4 enforcement. No
new gate is needed if Surface A is the chosen boundary. The
spec doc would close Contract 4 (Surface A) as "fulfilled by
Contract 1" and move on.

### T7.2 Surface B

**Feasible.** Two producer return sites in the orchestrator
(line 1768 + line 1773 region) plus one consumer site at
intake_consult.py:7276 (after `_run_planning_system_for_draft`).
Cleanest is the consumer-side gate at intake_consult, validating
`result` once before the acceptance gate runs. The two return
sites in the orchestrator are mutation paths within a single
function — adding a gate at each return is redundant with a
single consumer-side gate immediately downstream.

**Spec recommendation:** single consumer-side gate at
intake_consult.py:7276 (after `_run_planning_system_for_draft`
returns, before the acceptance gate at line 7455). Producer-side
gate is OPTIONAL — could land at the two return sites in
orchestrator.py for defense-in-depth, but the consumer-side
gate alone catches every regression today.

---

## T8. Divergences from v2 inventory

### Div-1. v2 says Boundary 6 entry is `build_python_finmo_json` — CONFIRMED but ALREADY CONTRACT-1-TYPED

v2 line 535 names the entry. T1.1 confirms the signature and
confirms the consumer-side gate already lives there per Contract 1
Commit 4. This is a CONFIRMED-CLOSED divergence: v2 documents the
entry; what v2 doesn't note is that Contract 1 already fulfills
the contract-typing at this entry.

**Classification: CONFIRMED CLOSED.** The headline finding above
makes the spec choice between (a) closing Contract 4 (Surface A)
as already-done or (b) pivoting Contract 4 to Surface B.

### Div-2. v2 says "Cash strategy invocation rides on the same model_input" — CONFIRMED

v2 line 533 ("Cash strategy invocation rides on the same model_input")
is correct. Cash strategy at
[post_intake_cash_strategy/orchestrator_invocation.py:442-444](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L442)
calls `build_python_finmo_json(model_input_json=...)` with just
the model_input arg. Same surface as every other caller.

**Classification: CONFIRMED RESIDUAL** (residual = not addressed
by any fix, still applies).

### Div-3. v2 D phantoms (`slot["working_capital"]["dso"]` etc.) — CONFIRMED CLOSED by Fix 4

v2 §D notes the slot-level WC phantoms are CLOSED by Fix 4
(b40c25a). Verified — finmo_bridge.py no longer constructs slots
with `working_capital` sub-dicts; the row-level path is the
single source of truth. **Classification: CONFIRMED CLOSED.**

### Div-4. v2 doesn't enumerate the solver return-dict shape — NEW STRUCTURAL

v2 covers Boundary 6 as the build_python_finmo_json input only.
It does NOT document the solver return-dict (Surface B). The
14+ keys enumerated in §T2.2 above are new structural information
this trace surfaces. Per the directive's framing intent
("solver's return dict"), this is the substantive un-typed
surface Contract 4 likely targets.

**Classification: NEW STRUCTURAL.** The spec doc's primary
contribution is typing Surface B if Nick picks that direction.

### Div-5. The 5 API-handler phantom-reads at intake_consult.py:7418-7434 — NEW STRUCTURAL

v2 doesn't note that the API handler does 5 defensive
`result.get(<key>)` reads where every single key is a phantom
(solver never stamps any of them). Surface B contract would let
us decide whether to (a) type those keys as Optional opaque (move
the phantom from runtime to type), (b) drop them from the
contract entirely (admit they're phantom and remove the
defensive reads in a follow-up cleanup), or (c) elevate them to
required (forcing the persist-layer to actually stamp them on
the return dict).

**Classification: NEW STRUCTURAL.**

### Div-6. Adjustment B verification at Surface B target — CONFIRMED carry-over

The same `except RuntimeError` (intake_consult.py:7298) and
`except Exception` (line 7377) catch sequence that protects
Contract 3's solver entry also wraps the orchestrator return
through `_run_planning_system_for_draft`. A ContractViolation
raised at a Surface B consumer-side gate would propagate through
the `except Exception` branch as a structured 500 with
`detail=str(exc)` carrying the stage tag — same pattern verified
for Contracts 1, 2, 3.

**Classification: CONFIRMED carry-over.** Spec doc Adjustment B
section can re-use the Contract 3 Div-8 conclusion verbatim;
spec doc test class mirrors Contract 3's `ApiCatchPatternEndToEndTest`.

### Div-7. `_build_finmo_callable` closure captures-but-doesn't-use 7 params — NEW STRUCTURAL

Per T1.2 the closure at orchestrator.py:620-641 captures
business_facts, ops_json, people_json, financials_json,
financials_year1_json, fulfillment_json, marketing_model_json but
the closure body uses none of them. The closure docstring
explicitly flags this as "intentionally unused" with potential
future use. NOT a Contract 4 concern (it's an internal solver
shape), but worth noting since it appears at first glance to
mean Surface A takes more than just `model_input_json`.

**Classification: NEW STRUCTURAL** (documentary only).

### Div-8. `_inner_runner_kwargs` phantom-fields — CONFIRMED CLOSED by Contract 3

Contract 3 trace Div-1 documented the inner_runner_kwargs
phantom-field pattern. No new finding here; carried for cross-
contract reference. **Classification: CONFIRMED CLOSED.**

---

## Open questions / flags for the spec doc

Numbered for the spec doc's §7 to expand each into a
recommendation + alternatives + Nick's pick. Same format
Contract 3 used.

### Flag 0 (NEW — the headline flag) — Which boundary does Contract 4 type?

**(Recommended) (a) Pivot to Surface B.** Type the orchestrator
return-dict (`run_target_seeking_orchestrated_system_run`'s
`next_result`). Land a consumer-side gate at intake_consult.py:7276.
This is the substantive un-typed handoff the directive's
framing alluded to. Surface A is already Contract 1's
responsibility per Div-1.

**(b) Close Contract 4 (Surface A) as already-done.** Mark
Boundary 6 fulfilled by Contract 1 + Contract 2 (Contract 1
types the input, Contract 2 types the output). Skip Contract 4
entirely; move directly to Contract 5 (intake-domain contracts
deferred from Contract 3 Flag 4).

**(c) Cover both surfaces.** Two contracts: (1) Surface A
closure note (one paragraph in the spec doc concluding Contract 1
already handles it); (2) Surface B typed contract. This is
documentation overhead vs (a) with no structural difference.

Recommend (a). The directive's body explicitly listed solver-
output keys for Contract 4 to type, which makes sense only as
Surface B. Surface A as a separate "fulfilled by Contract 1"
note can ship as one paragraph in the spec doc.

### Flag 1 — `plan_confidence` Literal enumeration

The string is used as a closed set throughout. Trace bottoms out
at `"high_no_adaptation"` init + reassignment by
`run_adaptation_cascade` to other values (likely
`"high_with_adaptation"`, `"medium_…"`, `"low_…"`). Spec doc
should grep adaptation_cascade.py for the closed set and pin
via `Literal[...]` per the Contract 3 TC1 / planning_mode
pattern.

**Spec recommends (a) Literal[...] with full enumerated set.**

### Flag 2 — `capital_lease_schedule` typing

No existing contract types it. Options:
- (a) Define a typed sub-contract (`CapitalLeaseScheduleContract`).
  Cost: one more sub-contract; aligns with the Contract 2 pattern
  for debt_schedule.
- (b) Type as opaque `Dict[str, Any]`. Cost: silent shape drift,
  but capital_lease_schedule has fewer consumers today (verify in
  spec).

Spec doc recommends (a) IF the consumer surface is wider than
one read site, else (b). Trace to confirm before spec.

### Flag 3 — Phantom-read fields treatment (Div-5)

`planning_run_json`, `numeric_solver_feedback_json`,
`planning_runtime_json`, `planning_context_summary_json`,
`draft_id` are all read by the API handler but never written by
the solver. Three options:

- (a) Type each as Optional in the contract (preserves current
  behavior; moves phantom from runtime to type).
- (b) Drop from the contract entirely (admits they're phantom;
  follow-up commit removes the defensive reads at intake_consult.py:
  7418-7434).
- (c) Elevate to required (forces solver to start stamping them;
  shifts work upstream).

Recommend (b) per the "don't loosen safety checks" rule applied
inversely — if the field isn't written, don't pretend it might be.
But (a) is the conservative choice.

### Flag 4 — Producer-side gate feasibility (Surface B)

Per T7.2 — single consumer-side gate at intake_consult.py:7276
catches every Surface B regression. Producer-side gates at the
two orchestrator return sites are defense-in-depth.

- (a) Ship ONLY the consumer-side gate at intake_consult.py:7276.
  Aligns with Contract 2's R8 defer reasoning (multiple producer
  sites; producer-side gates are R-residuals).
- (b) Ship producer-side gates at both orchestrator return sites
  PLUS the consumer-side gate. Aligns with Contract 3's
  ship-both pattern.

Recommend (a). The orchestrator's two return sites are 5 lines
apart (1768 and the post-cascade tail) and any mutation between
them would land in the same function — defense-in-depth here is
low value compared to Contract 3 where producer + consumer were
in different modules.

### Flag 5 — Composition reach

For each Surface B field:
- `model_input_json` → Contract 1 ✓ — no decision needed.
- `finmo_json` → Contract 2 ✓ — no decision needed.
- `payroll_headcount` → Contract 2 ✓ — no decision needed.
- `debt_schedule` → Contract 2 ✓ — no decision needed.
- All other fields → new opaque types OR specific typed
  sub-contracts.

Recommend opaque first cut for diagnostic fields
(target_seeking_diagnostics, adaptation_cascade_diagnostics,
gpt_call_budget_diagnostic, handler_trace_diagnostic,
solver_target_assertion, realism_memo_json,
post_cascade_completion). These are diagnostic blobs that
queries / dashboards read; structurally typing them would pull
diagnostic-domain scope into Contract 4. **Spec defers to R-residuals.**

### Flag 6 — `extra` policy

Per Contracts 1-3: `extra="forbid"` on top-level; `extra="ignore"`
on sub-contracts. Established pattern; no decision needed unless
the spec finds a reason to deviate.

### Flag 7 — Cross-field invariants

Candidates:
- `model_input_json.contract_version == "finmo_model_input_v3"`
  (already enforced by Contract 1 composition; no new validator).
- `finmo_json.contract_version == "finmo_output_v1"` (Contract 2).
- `debt_schedule.contract_version == "post_intake_debt_amortization_schedule_v1"`
  (Contract 2).
- `payroll_headcount.capacity_labor_model in {...}` (Contract 2).
- New: if `adaptation_cascade_diagnostics` is present, then
  `plan_confidence` should be in `{"high_with_adaptation",
  "medium_with_adaptation", ...}` (not `"high_no_adaptation"`).
  Spec to verify by tracing the assignment paths in
  adaptation_cascade.py.

### Flag 8 — Adjustment B verification path

Per Div-6 — re-use Contract 3's pattern verbatim. The
intake_consult.py:7377 generic catch handles ContractViolation
as a structured 500 with `str(exc)` carrying the stage tag. Spec
doc test class mirrors Contract 3's `ApiCatchPatternEndToEndTest`.
No new decision needed.

---

## Lessons baked in for Contract 4 spec drafting

- **Trace before spec saved a wasted Commit.** Without this
  trace, Contract 4 might have shipped a duplicate
  `validate_finmo_input_at_boundary` helper redundant with
  Contract 1. Headline finding catches this.
- **Match production vocabulary verbatim.** All 14 next_result
  keys + 5 phantom-read keys lifted directly from
  orchestrator.py + intake_consult.py source.
- **Don't loosen safety checks.** Flag 3 (phantom-read treatment)
  defaults to NOT promoting phantom fields to required.
- **Compose, don't redefine.** Flag 5 recommends Contract 1 +
  Contract 2 composition for the 4 model_input / finmo_json /
  debt_schedule / payroll_headcount fields.
- **Adjustment B end-to-end is a recurring lesson.** Div-6
  carries Contract 3's verification pattern verbatim; spec doc
  test class follows the same shape.
- **Diagnostic-emission invariant matters.** Per the directive,
  Contract 4's PhaseCode addition gets its own observability
  invariant test in test_p3_40_diagnostic_emission_invariant.py
  (extends the Contract 2 restoration pattern). The invariant
  test catches a future re-silencing of the new contract's
  emits.
