# P3.40 Contract 4 — SolverOutputContract (Spec)

**Status:** Specification only. No code lands until Nick reviews this doc.
After review, implementation follows the commit sequence in §6 below.

**Boundary covered:** Solver return → API handler. Formerly framed
as "Boundary 6: SOLVER → FINMO_BUILD" per the v2 inventory; the
trace doc's Flag 0 resolution pivoted to Surface B (the
orchestrator's return dict consumed at intake_consult.py:7418+)
because Surface A
(`build_python_finmo_json(model_input_json)` input) is already
typed end-to-end by Contract 1's gates.

**Predecessors:**
- [Contract 1 — FinmoModelInputContract](p3_40_contract_1_finmo_model_input_spec.md) (landed at b7f3584). Composed by Contract 4 for `model_input_json`.
- [Contract 2 — WorkbookPayloadContract](p3_40_contract_2_workbook_payload_spec.md) (landed at a6db38c). Composed by Contract 4 for `finmo_json` (`FinmoOutputContract`), `payroll_headcount` (`PayrollHeadcountContract`), `debt_schedule` (`DebtScheduleContract`).
- [Contract 3 — SolverInputContract](p3_40_contract_3_solver_input_spec.md) (landed at 616166c). Pairs naturally with Contract 4 — the solver's input vs output surfaces.

**Companion trace doc:** [p3_40_contract_4_solver_output_trace.md](p3_40_contract_4_solver_output_trace.md)
(landed at 7492a00; renamed + Flag 0 resolved at 28c2444). All
file:line citations and divergence findings below trace back to
that doc.

**Lessons applied from Contracts 1-3:**
- Trace before spec. The trace caught a major mis-scoping — the
  v2-inventory boundary surface was already typed by Contract 1.
  Flag 0 pivoted to the substantive un-typed surface.
- Match production vocabulary verbatim. Field names + types +
  the `PLAN_CONFIDENCE_*` enumeration lifted from orchestrator.py
  + adaptation_cascade.py.
- Constraints from production reality. int/float/Decimal lesson
  applies to any numeric fields (none today since most fields
  are dicts).
- Don't loosen safety checks. PSL3 keeps the 5 phantom-read
  fields as Optional rather than dropping them.
- `extra="forbid"` only on top-level; `extra="ignore"` on
  sub-contracts and rows.
- Adjustment B is recurring. Trace Div-6 confirms the same
  intake_consult.py:7377 generic catch propagates ContractViolation
  cleanly at this boundary.
- Compose prior contracts; don't redefine.
- Diagnostic-emission invariant matters. Contract 4's
  PhaseCode addition gets its own observability invariant test
  in test_p3_40_diagnostic_emission_invariant.py.

---

## 1. Trace Task Findings

The 8 pre-implementation traces (T1-T8) produced findings folded
directly into this spec's structure. The full enumeration is in
the trace doc; this section consolidates the ones that change
contract design.

### 1.1 Surface B is the substantive un-typed handoff (Flag 0 resolution)

Surface A (`build_python_finmo_json(model_input_json)`) is
already typed by Contract 1's consumer-side gate at
[finmo_bridge.py:619-660](../../python/client_intake_and_finmo/finmo_bridge.py#L619)
and producer-side gate at
[runner.py:1809-1822](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1809).
Per trace T1.2, 15 call sites of `build_python_finmo_json`
across 11 files all pass `model_input_json` as the sole data
argument — the closure docstring at
[orchestrator.py:625-630](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L625)
makes this explicit. **No new contract belongs at Surface A.**

Surface B is the orchestrator's 14-key return dict
(`next_result`) consumed by the API handler at
[intake_consult.py:7418+](../../python/api_handlers/intake_consult.py#L7418).
That's what Contract 4 types.

### 1.2 The 14-key `next_result` shape (trace T2)

Stamped across **600+ lines** of orchestrator.py at 14+ distinct
sites. Inherited keys at init from
[orchestrator.py:1701](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1701):
`next_result = copy.deepcopy(inner_result if isinstance(inner_result, dict) else {})`
— the inner runner is Phase-8 bypassed so `inner_result` is
effectively `{"status": "phase_8_inner_runner_bypassed", ...}`.

Per-key stamp sites:

| Key | Stamp site | Type today | Spec target type |
|---|---|---|---|
| `model_input_json` | orchestrator.py:1703 (+ 9 conditional rewrites) | `Dict[str, Any]` | **Contract 1 `FinmoModelInputContract`** (PSL1) |
| `finmo_json` | orchestrator.py:1705 (+ 9 rewrites) | `Dict[str, Any]` | **Contract 2 `FinmoOutputContract`** (PSL1) |
| `target_seeking_diagnostics` | orchestrator.py:1706 | `Dict[str, Any]` | opaque `Dict[str, Any]` |
| `plan_confidence` | orchestrator.py:1707 | `str` | **`Literal[...]`** enumerated (Flag 4 / §4.1) |
| `adaptation_cascade_diagnostics` | orchestrator.py:1709 | `Optional[Dict[str, Any]]` | `Optional[Dict[str, Any]]` opaque |
| `adaptive_policy` | orchestrator.py:1713 | `Dict[str, Any]` | `Dict[str, Any]` opaque |
| `gpt_call_budget_diagnostic` | orchestrator.py:1722 (best-effort) | `Optional[Dict[str, Any]]` | `Optional[Dict[str, Any]]` opaque |
| `handler_trace_diagnostic` | orchestrator.py:1740 (best-effort) | `Optional[Dict[str, Any]]` | `Optional[Dict[str, Any]]` opaque |
| `payroll_headcount` | orchestrator.py:1769 (`setdefault`) | `Optional[Dict[str, Any]]` | **`Optional[Contract 2 PayrollHeadcountContract]`** (PSL1) |
| `solver_target_assertion` | orchestrator.py:3123 | `Dict[str, Any]` | `Dict[str, Any]` opaque |
| `debt_schedule` | orchestrator.py:3144 | `Optional[Dict[str, Any]]` | **`Optional[Contract 2 DebtScheduleContract]`** (PSL1) |
| `capital_lease_schedule` | orchestrator.py:3166 | `Optional[Dict[str, Any]]` | `Optional[Dict[str, Any]]` opaque (Flag 5) |
| `realism_memo_json` | orchestrator.py:3705 | `Dict[str, Any]` | `Dict[str, Any]` opaque |
| `post_cascade_completion` | (via diagnostics dict assignment) | `Dict[str, Any]` | `Dict[str, Any]` opaque |
| `status` (inherited from inner_result) | orchestrator.py:1420-1425 | `str` | `Optional[str]` opaque (Phase-8 bypass artifact) |

### 1.3 The 5 phantom-read fields (trace T3 / Div-5)

The API handler at
[intake_consult.py:7418-7434](../../python/api_handlers/intake_consult.py#L7418)
does 5 defensive `result.get(<key>) if isinstance(...) else {}`
reads. **Every single one is a phantom-read** — the solver
never stamps the key, so the fallback fires on every run today:

| Field | Read at | Solver stamps it? |
|---|---|---|
| `planning_run_json` | intake_consult.py:7418 | NO |
| `numeric_solver_feedback_json` | intake_consult.py:7422 | NO |
| `planning_runtime_json` | intake_consult.py:7426 | NO |
| `planning_context_summary_json` | intake_consult.py:7430 | NO |
| `draft_id` | intake_consult.py:7434 | NO (handler falls back to caller's draft_id) |

PSL2 (Flag 3) elaborates the treatment options.

### 1.4 Eight divergences from v2 inventory (trace T8)

Folded directly into the flag dispositions below. Carrying as a
table for reference:

| Div | Class | Spec impact |
|---|---|---|
| Div-1: v2 Boundary 6 entry is already Contract 1 typed | CONFIRMED CLOSED | Flag 0 — Surface A skipped |
| Div-2: cash strategy uses same model_input surface | CONFIRMED RESIDUAL | No Contract 4 impact |
| Div-3: WC slot phantoms | CONFIRMED CLOSED by Fix 4 | No Contract 4 impact |
| Div-4: 14-key next_result shape | NEW STRUCTURAL | §2 + §3 |
| Div-5: 5 API-handler phantom-reads | NEW STRUCTURAL | Flag 3 (PSL2) |
| Div-6: Adjustment B carry-over | CONFIRMED | §5 + §6 Commit 3 test |
| Div-7: `_build_finmo_callable` captures-but-unused | NEW STRUCTURAL (documentary only) | No Contract 4 impact |
| Div-8: inner_runner_kwargs phantoms | CONFIRMED CLOSED by Contract 3 | No Contract 4 impact |

---

## 2. Top-level production payload — 15-field roster

Tier legend:
- **A. Typed via composition with prior contracts.** Re-import; do not redefine. Same pattern as Contract 3.
- **B. Literal enumeration.** Closed-set string; pinned via `Literal[...]`.
- **C. Diagnostic blob.** Opaque `Dict[str, Any]` for first cut; structurally tightening defers to R-residuals.
- **D. Phantom-read.** Per PSL2 (Flag 3): typed as Optional + present in contract so the handler's reads are documented at type level.
- **E. Inherited from inner_result.** Phase-8 bypass artifact (status string).

| # | Field | Tier | Contract type | Notes |
|---|---|---|---|---|
| 1 | `model_input_json` | A | `FinmoModelInputContract` (Contract 1) | Final solver-mutated state; same Contract 1 shape post-mutation. |
| 2 | `finmo_json` | A | `FinmoOutputContract` (Contract 2) | TC2-equivalent: producer is `build_python_finmo_json`, same as Contract 2 types. |
| 3 | `payroll_headcount` | A | `Optional[PayrollHeadcountContract]` (Contract 2) | Optional because `setdefault` only fires when `payroll_headcount` truthy at line 1769. |
| 4 | `debt_schedule` | A | `Optional[DebtScheduleContract]` (Contract 2) | Optional because post-cash-pass stamp at orchestrator.py:3144 lives inside a conditional. |
| 5 | `plan_confidence` | B | `Literal[...]` (11 members; see §4.1) | Closed set across PLAN_CONFIDENCE_* constants + 3 ad-hoc strings. |
| 6 | `target_seeking_diagnostics` | C | `Dict[str, Any]` | Per-iter solver diagnostics. Always stamped. |
| 7 | `adaptation_cascade_diagnostics` | C | `Optional[Dict[str, Any]]` | Only stamped when cascade fires. |
| 8 | `adaptive_policy` | C | `Dict[str, Any]` | `AdaptivePolicy.to_dict()`. Always stamped. |
| 9 | `gpt_call_budget_diagnostic` | C | `Optional[Dict[str, Any]]` | Best-effort write at orchestrator.py:1722. |
| 10 | `handler_trace_diagnostic` | C | `Optional[Dict[str, Any]]` | Best-effort write at orchestrator.py:1740. |
| 11 | `solver_target_assertion` | C | `Optional[Dict[str, Any]]` | Stamped inside `_run_post_cascade_completion`. |
| 12 | `capital_lease_schedule` | C | `Optional[Dict[str, Any]]` | Flag 5: opaque for first cut. |
| 13 | `realism_memo_json` | C | `Optional[Dict[str, Any]]` | Stamped inside `_run_post_cascade_completion`. |
| 14 | `post_cascade_completion` | C | `Optional[Dict[str, Any]]` | Trace dict from post-cascade tail. |
| 15 | `status` | E | `Optional[str]` | Inherited from inner_result (Phase-8 bypass: `"phase_8_inner_runner_bypassed"`). |
| **+ phantom-reads (Flag 3)** | D | `Optional[Dict[str, Any]] = None` | `planning_run_json`, `numeric_solver_feedback_json`, `planning_runtime_json`, `planning_context_summary_json`. (`draft_id` handled separately as `Optional[str]`.) |

**Total typed fields: 15 + 5 phantom-read (per PSL2 (a)) = 20.**

### 2.1 Why phantom-read fields are typed instead of dropped

Per PSL2 / Flag 3 disposition (a): the API handler currently
calls `result.get(<key>)` on these five fields. The
`.get(<key>)` returns `None` because the solver never stamps them
→ `isinstance(None, dict)` is `False` → fallback to `{}`. With
the contract, these fields type as `Optional[Dict[str, Any]] = None`
which documents the silent-empty path as an explicit Optional
rather than ad-hoc defensive code. The contract surface tells
future readers "these CAN be present but aren't guaranteed."

Alternative (b) — drop from contract entirely + remove the
handler reads as dead code — is the cleaner long-run answer
but requires auditing the handler's actual downstream
dependencies. Deferred to R-residual per PSL2 reasoning ("don't
drop a check until you've confirmed the dropping is safe").

---

## 3. Field-by-field contract spec

### 3.1 Top-level `SolverOutputContract`

```python
class SolverOutputContract(BaseModel):
  """The 20-field dict that
  ``run_target_seeking_orchestrated_system_run`` returns to its
  caller (intake_consult API handler at
  intake_consult.py:7276+).

  Composition: Contract 1 for model_input_json; Contract 2 for
  finmo_json / payroll_headcount / debt_schedule. The other 12+
  fields are opaque diagnostic blobs or a Literal-typed
  plan_confidence + a Phase-8-bypass status string.

  Per spec Flag 6 (PSL4): extra='forbid' on top-level; composed
  sub-contracts use their own extra policy.
  """

  # Tier A -- composition with Contracts 1 + 2
  model_input_json: FinmoModelInputContract
  finmo_json: FinmoOutputContract
  payroll_headcount: Optional[PayrollHeadcountContract] = None
  debt_schedule: Optional[DebtScheduleContract] = None

  # Tier B -- Literal-pinned closed set (§4.1)
  plan_confidence: Literal[
    "high_no_adaptation",
    "medium_gpt_band_relaxation",
    "medium_cohort_fallback",
    "low_target_tolerance_widened",
    "low_supplementary_levers_used",
    "low_planning_mode_shifted",
    "low_stage_family_widened",
    "generic_fallback_no_calibration",
    "restoration_after_cascade_exhausted",
    "restoration_with_documented_adjustments",
    "terminal_cause_7",
  ]

  # Tier C -- diagnostic blobs (opaque first cut)
  target_seeking_diagnostics: Dict[str, Any]
  adaptation_cascade_diagnostics: Optional[Dict[str, Any]] = None
  adaptive_policy: Dict[str, Any]
  gpt_call_budget_diagnostic: Optional[Dict[str, Any]] = None
  handler_trace_diagnostic: Optional[Dict[str, Any]] = None
  solver_target_assertion: Optional[Dict[str, Any]] = None
  capital_lease_schedule: Optional[Dict[str, Any]] = None
  realism_memo_json: Optional[Dict[str, Any]] = None
  post_cascade_completion: Optional[Dict[str, Any]] = None

  # Tier E -- Phase-8 bypass artifact
  status: Optional[str] = None

  # Tier D -- phantom-read fields (PSL2 (a), Flag 3)
  planning_run_json: Optional[Dict[str, Any]] = None
  numeric_solver_feedback_json: Optional[Dict[str, Any]] = None
  planning_runtime_json: Optional[Dict[str, Any]] = None
  planning_context_summary_json: Optional[Dict[str, Any]] = None
  draft_id: Optional[str] = None

  model_config = ConfigDict(extra="forbid")  # PSL4
```

### 3.2 Re-imports from prior contracts (PSL1)

```python
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
  FinmoModelInputContract,
)
from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (
  FinmoOutputContract,
  PayrollHeadcountContract,
  DebtScheduleContract,
)
```

No new typing of `FinmoOutputContract` / `PayrollHeadcountContract`
/ `DebtScheduleContract` — Contract 4 reuses Contract 2's
definitions verbatim. Same module identity prevents drift
between the workbook-side typing and the solver-output-side
typing.

### 3.3 No new sub-contracts

Contract 3 introduced one new sub-contract
(`BusinessFactsForSolverContract`). Contract 4 introduces ZERO —
every field either composes a prior contract, is opaque, is a
Literal string, or is a primitive. The 12+ diagnostic-blob
fields would each warrant their own typed sub-contract IF a
downstream consumer structure-reads them, but per trace T3 the
handler's `result.get()` reads are all phantom-reads — no
consumer needs structured access. Spec defers diagnostic-blob
typing to R-residuals.

---

## 4. Cross-field invariants

Per PSL5 — at minimum, `plan_confidence` Literal pinning. Other
invariants enumerated below; spec §1c tests pin all halves.

### 4.1 `plan_confidence` Literal enumeration (PSL5)

The canonical set lives at
[adaptation_cascade.py:52-59](../../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L52)
as 8 PLAN_CONFIDENCE_* constants:

```python
PLAN_CONFIDENCE_HIGH_NO_ADAPTATION = "high_no_adaptation"
PLAN_CONFIDENCE_GPT_BAND_RELAXATION = "medium_gpt_band_relaxation"
PLAN_CONFIDENCE_COHORT_FALLBACK = "medium_cohort_fallback"
PLAN_CONFIDENCE_TARGET_TOLERANCE_WIDENED = "low_target_tolerance_widened"
PLAN_CONFIDENCE_SUPPLEMENTARY_LEVERS = "low_supplementary_levers_used"
PLAN_CONFIDENCE_PLANNING_MODE_SHIFTED = "low_planning_mode_shifted"
PLAN_CONFIDENCE_STAGE_FAMILY_WIDENED = "low_stage_family_widened"
PLAN_CONFIDENCE_GENERIC_FALLBACK = "generic_fallback_no_calibration"
```

Plus 3 ad-hoc string-literal assignments:
- `"restoration_after_cascade_exhausted"` at adaptation_cascade.py:909
- `"restoration_with_documented_adjustments"` at adaptation_cascade.py:936
- `"terminal_cause_7"` at orchestrator.py:1690

Plus the orchestrator's init at orchestrator.py:1597
(`plan_confidence: str = "high_no_adaptation"`) which uses the
same literal as `PLAN_CONFIDENCE_HIGH_NO_ADAPTATION`.

**Total: 11 distinct values.** Spec contract Literal lists all 11
verbatim. Sub-flag candidate (Flag 4(b)): the 3 ad-hoc strings
should be promoted to PLAN_CONFIDENCE_* constants for symmetry —
defer to R-residual cleanup; not blocking Contract 4.

Enforced declaratively by the `Literal[...]` field declaration;
no separate `@model_validator` needed. Test pairs typo-rejection
+ all 11 accepted-spellings per the Contract 1 / Contract 3
typo-lock pattern.

### 4.2 Composition-inherited invariants (PSL1)

Inherited from Contract 1 + Contract 2 via composition:
- `model_input_json.contract_version == "finmo_model_input_v3"`
- `finmo_json.contract_version == "finmo_output_v1"`
- `debt_schedule.contract_version == "post_intake_debt_amortization_schedule_v1"`
- `payroll_headcount.capacity_labor_model in {...}` (closed set per Contract 2)
- `finmo_json.periods` length == 21
- `payroll_headcount.rows` covers all horizon quarters

No new validators needed; composition does the work.

### 4.3 Cross-field invariant — `plan_confidence` vs `adaptation_cascade_diagnostics` agreement

Candidate invariant (PSL5 sub-flag): if
`adaptation_cascade_diagnostics is not None`, then
`plan_confidence` must NOT be `"high_no_adaptation"` (which
means the cascade DID NOT fire).

Conversely if `adaptation_cascade_diagnostics is None`,
`plan_confidence` MUST be either `"high_no_adaptation"` or
`"terminal_cause_7"` (terminal cause skips cascade).

This is a real invariant — verified by grep of orchestrator.py
assignment paths:
- Line 1707 always stamps `plan_confidence`.
- Line 1709 conditionally stamps `adaptation_cascade_diagnostics` ONLY
  inside `if cascade_diagnostics is not None:`.
- Cascade re-assigns `plan_confidence` per line 1645 only when it
  fires.

Sub-flag 4(c): add as `@model_validator(mode="after")` OR skip.
Spec recommends **(a) add** — surfaces drift between the two
fields if a future code path stamps one without the other.

### 4.4 Cross-field invariant — phantom-read field consistency (Flag 3 sub-invariant)

Per PSL2 (a), phantom-read fields type as
`Optional[Dict[str, Any]] = None`. No cross-field validator
needed because the spec accepts ALL combinations (all-None is
valid; the API handler defends against absence).

If Flag 3 picks (c) elevate-to-required, then a cross-field
invariant would enforce non-emptiness. NOT recommended for first
cut.

---

## 5. Boundary enforcement

### 5.1 Producer-side gate — SKIP per PSL3

Per trace T7 the 14 stamp sites scattered across 600 lines of
orchestrator.py make a single producer-side gate infeasible. The
two return sites in the orchestrator (line 1768 + the
post-cascade tail return) are mutation paths within a single
function — adding a gate at each return is redundant with a
single consumer-side gate immediately downstream.

The 4 composed fields (`model_input_json`, `finmo_json`,
`payroll_headcount`, `debt_schedule`) ARE producer-gated upstream:
- `model_input_json` via Contract 1's runner.py:1809-1822 gate
  (validated before bundle return → flows through orchestrator
  mutations → final form lands in `next_result`).
- `finmo_json` via Contract 1's finmo_bridge.py:619 consumer-side
  gate (every `build_python_finmo_json` call validates input;
  output is `FinmoOutputContract` shape by construction).
- `payroll_headcount` via Contract 2's typing (PayrollHeadcountContract
  is already validated wherever payroll updates land).
- `debt_schedule` via the post-cash-pass builder
  (`build_debt_schedule_snapshot`) which emits the documented
  Contract 2 shape.

The 10 diagnostic/Literal/status fields don't have upstream
producer-side gates because they don't have shape contracts at
their production sites — they're emitted ad-hoc.

**Spec recommends (a) consumer-side gate only.** Producer-side
gates per stamp site would be 10 separate places — same R8-defer
reasoning Contract 2 applied.

### 5.2 Consumer-side gate

**Location:** the FIRST executable line of
`_run_planning_system_for_draft_unified` at
[intake_consult.py:7039+](../../python/api_handlers/intake_consult.py#L7039)
— immediately after the orchestrator return, before the
acceptance gate at intake_consult.py:7455.

Two candidate placement sites:
- (a) intake_consult.py:7276 (after `result =
  _run_planning_system_for_draft(...)`, before
  `verify_run_acceptance`). Single site; catches every return
  path of the orchestrator including both return statements.
- (b) Inside `_run_planning_system_for_draft_unified` at the
  end (after `_run_unified_post_grid_system_run` returns,
  before the dict-return at intake_consult.py:7103). One layer
  deeper; same effect.

Spec recommends **(a) intake_consult.py:7276** because:
- It's the LAST layer before the acceptance gate runs.
- Co-located with the acceptance-gate exception handling so the
  ContractViolation propagation path is one decision per
  function.
- Mirrors Contract 3's pattern (consumer-side gate at
  orchestrator.py:1028 as the first executable line of the
  orchestrator body).

```python
# python/api_handlers/intake_consult.py:7276+

    try:
      result = _run_planning_system_for_draft(
        conn=conn, draft_id=draft_id, lifecycle_mode=lifecycle_mode,
        planning_run_id=planning_run_id or None,
      )
    except ... as exc:
      ...

    # P3.40 Contract 4 Commit 3 -- consumer-side boundary gate.
    # Validates the 20-field solver output dict before any
    # acceptance-gate processing or workbook-export trigger.
    # On invalid shape raises ContractViolation, which propagates
    # through the next-level `except Exception as exc:` catch at
    # intake_consult.py:7377 (Div-6) as a structured 500 with
    # str(exc) carrying SOLVER_OUTPUT_STAGE_LABEL + field path.
    from client_intake_and_finmo.post_intake_contracts.enforcement import (
      SIDE_CONSUMER,
      validate_solver_output_at_boundary,
    )
    validate_solver_output_at_boundary(
      result, side=SIDE_CONSUMER,
    )
```

### 5.3 Enforcement helper

Added to existing `enforcement.py` alongside Contracts 1-3
helpers:

```python
SOLVER_OUTPUT_STAGE_LABEL = "SOLVER→API_HANDLER"

def validate_solver_output_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = SOLVER_OUTPUT_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> SolverOutputContract:
  ...
```

Mirrors Contract 1/2/3 helpers verbatim. Reuses
`_extract_first_error` + `_safe_emit` private helpers.

### 5.4 Adjustment B verification (Div-6 confirmed)

Per trace Div-6 the API handler at
[intake_consult.py:7377](../../python/api_handlers/intake_consult.py#L7377)
catches `except Exception as exc:` (skips the line-7298 RuntimeError
branch because `ContractViolation` is `Exception` subclass, not
`RuntimeError`). Returns HTTP 500 with `detail=str(exc)`, logs
via `app.logger.exception`, persists via
`_persist_failed_system_run_snapshot`, dispatches failure email.

`str(ContractViolation)` carries `SOLVER→API_HANDLER` +
`field path` + `expected vs actual` — informative for the
operator, not a fallback stack trace.

§6 Commit 3 includes a test mirroring Contract 3's
`ApiCatchPatternEndToEndTest` end-to-end pattern.

### 5.5 PhaseCode / EventCode / FailFastCode additions

New entries (lockstep with the lock-count tests per the
Contract 2 diagnostic-stack restoration pattern):

- `PhaseCode.SOLVER_OUTPUT_CONTRACT`
- `EventCode.SOLVER_OUTPUT_CONTRACT_VALIDATED`
- `EventCode.SOLVER_OUTPUT_CONTRACT_VIOLATION`
- `FailFastCode.FAIL_SOLVER_OUTPUT_CONTRACT_VIOLATION = "fail_solver_output_contract_violation"`

Lock-count tests to update:
- `test_phase_9_p3_33_phase3_step9a_phase_codes.py`: rename
  `test_phase_code_has_sixteen_phases` → `_seventeen_phases`
  (or refactor to a constant-driven assertion if preferred);
  comment updated to list all 4 contract phases (MODEL_INPUT,
  WORKBOOK_PAYLOAD, SOLVER_INPUT, SOLVER_OUTPUT).
- `_safe_emit` partition + `raise_fail_fast` failed_event
  mapping updated to include the new phase.

### 5.6 Diagnostic-emission invariant test (per directive)

Per the directive's lesson + Contract 2 restoration pattern:
the Commit 3 test set extends
`tests/test_p3_40_diagnostic_emission_invariant.py` with one
new test class:

- `ContractFourEmitsSolverOutputPhaseCodeTest` (1 test): feed
  a deliberate Contract 4 violation through
  `validate_solver_output_at_boundary` with a capturing emitter;
  assert the captured event carries
  `PhaseCode.SOLVER_OUTPUT_CONTRACT`.

Plus an addition to
`PhaseCodesDoNotCrossContaminateTest`:
- `test_contract_4_violation_does_not_emit_under_model_input_contract` (1 test)
- (cross-contamination check covering the new contract).

Total invariant-file additions: 2 new tests, bringing the
file's count from 5 → 7.

---

## 6. Implementation sequence

After Nick green-lights this spec, implementation follows:

### Commit 1a — Contract module

File: `python/client_intake_and_finmo/post_intake_contracts/solver_output_contract.py`

- Top-level `SolverOutputContract` (20 typed fields per §3.1).
- Re-imports from Contracts 1 + 2 (no redefinition of
  `FinmoModelInputContract` / `FinmoOutputContract` /
  `PayrollHeadcountContract` / `DebtScheduleContract`).
- 1 cross-field invariant per §4.3
  (`plan_confidence_matches_cascade_presence`).
- Module docstring covering boundary + composition + Flag 0
  resolution context.
- NO new sub-contracts (per §3.3 — diagnostic-blob typing
  defers to R-residuals).

Expected LOC: 250-350 (mostly docstrings). Single file artifact.
Well under 700 cap.

### Commit 1b — Fixtures + sub-contract tests

`tests/_p3_40_contract_4_fixtures.py` + `tests/test_p3_40_contract_4_subcontracts.py`

Imports Contract 1 + 2 fixtures
(`valid_top_level` as `valid_model_input_json_dict`,
`valid_finmo_output_dict`, `valid_payroll_headcount_dict`,
`valid_debt_schedule_dict`). Adds:

- `valid_solver_output_dict(include_optionals=True)`

Tests:
- `plan_confidence` Literal: 11 valid spellings accepted, 1 typo
  rejected (test_typo_accepted + test_correct_spelling_rejected
  per Contract 1/3 typo-lock pattern) (12 tests).
- Tier-D phantom-read fields: each of 5 fields accepted absent
  (default `None`) and accepted with a dict (10 tests).
- Tier-C optional diagnostic fields: each accepted absent + with
  a dict (~6 tests, representative subset).

Target: 25-30 tests.

### Commit 1c — Top-level + cross-field + Adjustment B tests

`tests/test_p3_40_contract_4_solver_output.py`

5 test classes mirroring Contract 3 §1c:

- `SolverOutputContractTopLevelTest`: required-field rejection +
  `extra="forbid"` on top-level + all optional fields can be
  absent (~8-10 tests).
- `CompositionWithContract1Test`: `model_input_json` typed as
  `FinmoModelInputContract`; Contract 1 invariant violation
  (revenue empty) propagates (2 tests).
- `CompositionWithContract2Test`: `finmo_json` typed as
  `FinmoOutputContract`; `payroll_headcount` typed as
  `PayrollHeadcountContract`; `debt_schedule` typed as
  `DebtScheduleContract`; Contract 2 invariant violations
  propagate (3-4 tests).
- `CrossFieldInvariantTest`: invariant 4.3
  (`plan_confidence_matches_cascade_presence`). Both halves of
  each pair (4 tests).
- `ApiBoundaryContractViolationTest`: Adjustment B verification
  per Contract 3 pattern: ContractViolation message uses
  `SOLVER_OUTPUT_STAGE_LABEL`; structured attributes accessible;
  survives generic Exception catch at intake_consult.py:7377;
  source_payload not dumped into str (4 tests).

Target: 21-25 tests.

### Commit 2 — Adapter (classmethod, no dataclass per F1-equivalent)

Per PSL1 + the Contract 3 pattern. Adapter not strictly needed
since the orchestrator return IS already a dict (no dataclass
to bridge to/from). Spec sub-flag (Flag 6 sub-flag): does
Contract 4 need an adapter at all?

- (a) Skip Commit 2. The contract module ships
  `SolverOutputContract.model_validate(result)` directly; no
  intermediate adapter helper needed. Mirrors Contract 2's
  pattern where the dataclass already existed; here there's
  no dataclass, so the adapter equivalent is just
  `model_validate`.
- (b) Add `from_orchestrator_result(result: Dict[str, Any]) -> SolverOutputContract`
  classmethod as a thin wrapper for symmetry with Contract 3.

Spec recommends **(a) skip Commit 2.** No new abstraction; the
enforcement helper `validate_solver_output_at_boundary(result,
side=...)` already wraps `model_validate` with the
ContractViolation translation.

If approved, Commit 2 is SKIPPED and the sequence is 1a → 1b → 1c → 3.

### Commit 3 — Consumer-side gate + enforcement helper + diagnostic codes + invariant test + Adjustment B test

THREE wirings in one commit (mirroring Contract 3 Commit 3):

1. **Enforcement helper** added to `enforcement.py`
   (`validate_solver_output_at_boundary`, `SOLVER_OUTPUT_STAGE_LABEL`
   new, `SIDE_PRODUCER` / `SIDE_CONSUMER` reused).
2. **Consumer-side gate** at intake_consult.py:7276 (after
   `_run_planning_system_for_draft` returns, before
   `verify_run_acceptance`).
3. **PhaseCode / EventCode / FailFastCode** additions per §5.5.
   Lockstep update of `test_phase_9_p3_33_phase3_step9a_phase_codes.py`
   (count 16 → 17).
4. **Diagnostic-emission invariant test** addition to
   `test_p3_40_diagnostic_emission_invariant.py` (per §5.6).

Tests in `tests/test_p3_40_contract_4_consumer_gate.py`:
- Valid solver-output passes the gate (1 test).
- Missing each of 4 representative required fields →
  ContractViolation (4 tests).
- Bad sub-payload → field path points into violation (2 tests).
- Adjustment B end-to-end: 3 tests mirroring Contract 3.

Target: 10-12 tests.

---

## 7. Open flags for Nick's review

8 decisions numbered with spec recommendations matching the
PSL pre-stated leans.

### Flag 0 — Surface choice — RESOLVED at trace amendment

Resolved (a) Pivot to Surface B. See trace amendment commit
28c2444. Carried here for reference; no action.

### Flag 1 — Composition with prior contracts (PSL1)

**(Recommended) (a) Compose Contracts 1 + 2 for the 4 typed
fields.** Re-import; do not redefine.

**(b) Re-define one or more sub-contract shapes.** Risks type
drift between workbook-side and solver-output-side typings.
Recommend against.

### Flag 2 — Adapter (Commit 2)

**(Recommended) (a) Skip Commit 2 — no adapter.** The
orchestrator return is already a dict; `model_validate` + the
enforcement helper handle the bridge with no intermediate
abstraction.

**(b) Add `from_orchestrator_result(...)` classmethod for
symmetry.** Adds a thin wrapper with no behavior. Recommend
against.

### Flag 3 — Phantom-read fields treatment (PSL2)

**(Recommended) (a) Add to contract as
`Optional[Dict[str, Any]] = None` (and `Optional[str] = None`
for `draft_id`).** Documents the silent-empty path as a known
shape. Least disruptive.

**(b) Drop from contract entirely + remove handler reads.**
Cleaner long-run but requires verifying no downstream consumer
depends on them. Defer to R-residual audit.

**(c) Elevate to required.** Forces solver to start stamping
them; shifts work upstream. Recommend against — phantom-reads
are real today and elevation could break the API handler in
ways not yet inventoried.

### Flag 4 — `plan_confidence` Literal (PSL5)

**(a) Literal of all 11 values** (8 constants + 3 ad-hoc
strings). Recommended.

**Sub-flag 4(b):** also promote the 3 ad-hoc strings
(`"restoration_after_cascade_exhausted"`,
`"restoration_with_documented_adjustments"`,
`"terminal_cause_7"`) to PLAN_CONFIDENCE_* constants in
adaptation_cascade.py / orchestrator.py. Recommend **defer** to
R-residual cleanup; not blocking Contract 4. Constants vs
literal strings is a code-hygiene concern, not a contract-shape
concern.

**Sub-flag 4(c):** add the cross-field invariant 4.3
(`plan_confidence_matches_cascade_presence` —
`adaptation_cascade_diagnostics` presence ↔ `plan_confidence`
not `"high_no_adaptation"`). Recommend **add** — cheap; surfaces
drift between two fields that today are co-stamped manually.

### Flag 5 — `capital_lease_schedule` typing

**(Recommended) (a) Opaque `Optional[Dict[str, Any]]` for
first cut.** Limited downstream consumer; not used by the API
handler in trace T3.

**(b) Define `CapitalLeaseScheduleContract` sub-contract** for
symmetry with debt_schedule. Adds scope; defer to R-residual.

### Flag 6 — `extra` policy (PSL4)

**(Recommended) (a) `extra="forbid"` on top-level
SolverOutputContract; composed sub-contracts use their own
extra policy (Contract 1 forbids; Contract 2 ignores on row
types).** Established pattern.

**(b) `extra="ignore"` everywhere.** Loosens drift detection.
Recommend against.

### Flag 7 — Producer-side gate (PSL3)

**(Recommended) (a) Skip producer-side gate.** Per §5.1 the
14 stamp sites scattered across 600 lines of orchestrator.py
make a single producer-side gate infeasible; the 4 composed
fields are upstream-gated via Contract 1/2 producer-side gates.

**(b) Add per-return-site producer gates at the two
`return next_result` sites in orchestrator.py.** Defense-in-depth
but mostly redundant with the consumer-side gate.

### Flag 8 — Adjustment B verification (PSL6)

**(Recommended) (a) Re-use Contract 3's verification pattern
verbatim.** intake_consult.py:7377 generic Exception catch
handles ContractViolation as a structured 500 with `str(exc)`
carrying the stage tag. Test class mirrors Contract 3's
`ApiCatchPatternEndToEndTest`.

**(b) Add a new verification helper.** Adds scope for no
benefit. Recommend against.

---

## 8. Known residual cleanups (out of scope for Contract 4)

- **R8.** Diagnostic-blob typing: structurally type
  `target_seeking_diagnostics`, `adaptation_cascade_diagnostics`,
  `adaptive_policy`, `gpt_call_budget_diagnostic`,
  `handler_trace_diagnostic`, `solver_target_assertion`,
  `realism_memo_json`, `post_cascade_completion`. Per §3.3 these
  are opaque first cut; structurally typing them pulls
  diagnostic-domain scope into Contract 4.

- **R9.** Phantom-read audit + drop (PSL2 (b)). Verify no
  downstream consumer depends on `planning_run_json`,
  `numeric_solver_feedback_json`, `planning_runtime_json`,
  `planning_context_summary_json`, `draft_id` at the API
  handler, then drop both the contract fields AND the handler
  reads as dead code.

- **R10.** Promote `"restoration_after_cascade_exhausted"`,
  `"restoration_with_documented_adjustments"`, `"terminal_cause_7"`
  to PLAN_CONFIDENCE_* constants (per Flag 4 sub-flag (b)).
  Code-hygiene cleanup; not blocking.

- **R11.** `CapitalLeaseScheduleContract` typed sub-contract
  (per Flag 5 (b)). Symmetric with debt_schedule.

- **R12.** Inner-runner Phase-8 bypass cleanup — the `status:
  "phase_8_inner_runner_bypassed"` field inherited from
  `inner_result` is a known leftover from the Phase 8 bypass
  per Contract 3 Div-1. When Phase 8 cleanup lands, the
  `status` field comes out of the contract.

- **R13.** Per-stamp-site producer gates (Flag 7 (b)). If
  defense-in-depth becomes valuable, add gates at each return
  site in orchestrator.py.

---

## 9. Workflow

Same as Contracts 1, 2, and 3: trace doc + spec doc each ship as
single commits, held for Nick review. After spec approval, the
3- or 4-commit implementation series (1a → 1b → 1c → [3]) lands
per §6 with push + email per commit.

Per-commit LOC cap: 700. If a natural unit exceeds the cap
single-artifact ships are acceptable with a note matching prior
precedent.

If during Commit 1a (the contract module) I find anything else
that diverges from production, I'll flag back the same way
Contracts 1, 2, 3 did — no silent adjustment.

After Commit 3 lands and the full P3.40 contracts suite goes
green, Contract 4 is end-to-end. The next direction (Contract 5
intake-domain contracts deferred from Contract 3 Flag 4, or
another upstream contract) comes from Nick.
