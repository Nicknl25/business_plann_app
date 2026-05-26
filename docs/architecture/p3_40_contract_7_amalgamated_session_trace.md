# P3.40 Contract 7 — AmalgamatedSessionContract — Pre-spec trace

**Boundary:** 3 (INDUSTRY_BASELINE → AMALGAMATED_SESSION).
**Status:** pre-spec trace. Holds for review before the spec doc is drafted.
**Companion to:** [p3_40_contract_7_amalgamated_session_spec.md](./p3_40_contract_7_amalgamated_session_spec.md) (not yet written).
**v2 inventory baseline:** [p3_40_pipeline_data_flow_inventory_v2.md §Boundary 3](./p3_40_pipeline_data_flow_inventory_v2.md#boundary-3-industry_baseline--amalgamated_session) (lines 297-383).

**Final contract in the P3.40 sequence.** After Contract 7 lands,
Boundaries 1-7 are end-to-end contract-typed.

Same trace-before-spec discipline as Contracts 1-6.

---

## Headline findings — read these first

1. **The Mirror dataclass IS the boundary surface.** Per v2 §A
   the Mirror at
   [mirror.py:75-86](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L75)
   carries 10 fields (9 data + 1 internal cap). Bug 2 and Bug 3
   fixes added two new write paths (`set_plan_state_section` +
   `set_validation_state`) that refresh `plan_state` +
   `validation_state` during the cascade. Contract 7 types the
   Mirror and its 2 critical sub-shapes (plan_state +
   validation_state-bounded-projection).

2. **Refresh-semantic invariants from Bugs 2 + 3 fixes become
   @model_validators per PSL2.** The Bug 2 fix
   ([mirror.py:163-180](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L163))
   has an **alias-sync** invariant: when section ∈
   {balance_sheet, capex_rd_balance_seed, capex_rd}, all three
   keys in plan_state share the same payload. The Bug 3 fix
   ([mirror.py:106-161](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L106))
   has a **bounded-projection** invariant: failing_check_names
   capped at 12; failing_lever_margins capped at 12; truncation
   flags accompany.

3. **Multi-shape contract per F0 pattern from Contract 6.**
   Single Contract 7 module with sub-contracts for Mirror +
   RecentDecision + PlanState (5 SECTIONS) +
   ValidationStateProjection + LeverMarginEntry.

4. **Composition with Contracts 1 + 2 + 6 expected per PSL1**:
   - `plan_state` sections carry model-input row shapes — likely
     compose pieces of Contract 1 (FinmoModelInputContract).
   - `bands` carries Contract 6's `GetBandsViewContract` per
     SECTION (verified at trace T1 below).
   - `business_facts` reads from Contract 5's intake-side scalar
     fields (R-residual retrofit).

5. **v2 inventory is the post-Bug-fix baseline.** Trace mostly
   CONFIRMS v2's findings with detail additions; no major NEW
   SUBSTANTIVE divergences expected.

---

## T1. Producer-side amalgamation

### T1.1 Mirror construction via `build_mirror`

Single producer: `build_mirror` at
[mirror.py:201-279](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L201).
Signature:

```python
def build_mirror(
  conn=None,
  *,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  plan_state: Optional[Dict[str, Any]] = None,
  sequence_position: Optional[Dict[str, Any]] = None,
  validation_state: Optional[Dict[str, Any]] = None,
  budget: Optional[Dict[str, Any]] = None,
  recent_decisions_cap: int = DEFAULT_RECENT_DECISIONS_CAP,
  load_bands: bool = True,
) -> Mirror:
```

Inputs:
- `business_facts: Optional[Dict]` — passed from upstream caller
  (post_intake_initial_grid runner or similar).
- `plan_state: Optional[Dict]` — initial snapshot per SECTION.
- `sequence_position: Optional[Dict]` — phase tracker.
- `validation_state: Optional[Dict]` — typically empty at build;
  populated later via `set_validation_state`.
- `budget: Optional[Dict]` — call-budget state.

Bands loaded internally:
- `bands_payload[section] = get_bands(conn, draft_id, planning_run_id, section)`
  for each section in `SECTIONS = ("stage_ramp", "drivers",
  "payroll", "capex_rd", "balance_sheet")` per
  [mirror.py:218-225](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L218).
- **`get_bands` returns Contract 6's `GetBandsViewContract`
  shape** per Contract 6 §T1.5. PSL1 composition target.

Constructs the Mirror dataclass and emits a `MIRROR_BUILD_*`
diagnostic.

### T1.2 Mirror refresh path — Bug 2 + Bug 3 fixes

After `build_mirror`, the Mirror state is refreshed by two
callback-driven paths registered in `session_factory`:

- **`apply_to_plan_state_fn` (Bug 2 fix at 851fa28)** wired at
  [session_factory.py:339-340](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L339):
  ```python
  def apply_to_plan_state_fn(section: str, payload: Any) -> None:
    mirror.set_plan_state_section(section, payload)
  ```
  Invoked from `SessionDriver._commit_proposal` at
  [session_driver.py:663-680](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L663)
  after each successful revise_* commit. Emits
  `EventCode.CASCADE_PROPOSAL_APPLIED_TO_MIRROR` per v2 §B.

- **`apply_to_validation_state_fn` (Bug 3 fix at b6968ae)** wired at
  [session_factory.py:346-347](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L346):
  ```python
  def apply_to_validation_state_fn(evaluate_plan_result: Any) -> None:
    mirror.set_validation_state(evaluate_plan_result)
  ```
  Invoked from `SessionDriver._evaluate` at
  [session_driver.py:857-865](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L857)
  after each `_evaluate_plan_fn` returns an EvaluatePlanResult.
  Best-effort try/except around the call (mirror-projection
  failure does not abort the standards-check path).

**The Mirror is mutated in-process** — there is no separate
"amalgamated session payload" emitted at a single point. The
contract types the Mirror's STATE at the point a downstream
consumer reads it.

### T1.3 No SQL persistence of Mirror state

The Mirror is in-memory only. SessionDriver holds a reference;
session_factory wires the callbacks. Nothing is INSERTed to a
SQL table representing the Mirror. The closest persisted
representation: the EvaluatePlanResult's full `to_dict()` lives
on `SessionDriver._last_result` in-process (per
mirror.py:108 docstring) but doesn't reach a persisted column.

---

## T2. Boundary surface — Mirror payload + 4 sub-shapes

Per the multi-shape F0 pattern from Contract 6, Contract 7
types **6 sub-contracts** inside a single module:

| Shape | Source | Field count | Notes |
|---|---|---|---|
| **A — MirrorContract** | `Mirror` dataclass at mirror.py:75-86 | 9 data fields (10 minus `recent_decisions_cap` internal cap) | Top-level boundary shape; the Mirror's serialized form |
| **B — RecentDecisionContract** | `RecentDecision` dataclass at mirror.py:64-72 | 6 fields | Ring-buffer entry |
| **C — PlanStateSectionContract** | `Mirror.plan_state[section]` | section-dependent (opaque Dict for first cut per PSL1) | 5 SECTIONS enumerated; F0 sub-flag on tightening per-section |
| **D — ValidationStateProjectionContract** | `Mirror.set_validation_state` output at mirror.py:106-161 | 11 fields | Bounded-projection (12-cap) per Bug 3 |
| **E — LeverMarginEntryContract** | inner dict in `failing_lever_margins[]` at mirror.py:135-145 | 8 fields | Per Bug 3 bounded projection |
| **F — BandsForSectionContract** | re-import `GetBandsViewContract` from Contract 6 | n/a (composition) | PSL1 — no redefinition |

### T2.1 Shape A — MirrorContract (9 fields)

Per Mirror dataclass at mirror.py:75-86:

| # | Field | Type today | Required? | Tier |
|---|---|---|---|---|
| 1 | `invariants` | `Dict[str, str]` | required (defaults to `_INVARIANTS` constant per build_mirror) | A |
| 2 | `authority` | `str` | required (defaults to `_AUTHORITY` constant) | A |
| 3 | `business_facts` | `Dict[str, Any]` | required (intake-extracted; R-residual retrofit to Contract 5b/c/d) | A |
| 4 | `plan_state` | `Dict[str, Dict]` keyed by SECTION | required (5 SECTIONS, may be empty {}) | A |
| 5 | `sequence_position` | `Dict[str, Any]` | required (phase tracker; opaque) | A |
| 6 | `bands` | `Dict[str, GetBandsViewContract]` keyed by SECTION | required (composes Contract 6) | A |
| 7 | `validation_state` | `Dict[str, Any]` matching Shape D | required (may be empty {} pre-evaluate) | A |
| 8 | `recent_decisions` | `List[RecentDecisionContract]` | required (may be empty []) | A |
| 9 | `budget` | `Dict[str, Any]` | required (opaque) | A |

`recent_decisions_cap` is internal config, not boundary surface
— excluded from Contract 7 per the `to_dict()` precedent at
mirror.py:182-192.

### T2.2 Shape B — RecentDecisionContract (6 fields)

Per RecentDecision dataclass at mirror.py:64-72:

| # | Field | Type | Required? |
|---|---|---|---|
| 1 | `tool_name` | `str` | required |
| 2 | `inputs_summary` | `str` | required |
| 3 | `delta_all_pass` | `Optional[int]` | Optional (delta indicator) |
| 4 | `delta_worst_distance` | `Optional[float]` | Optional |
| 5 | `result_summary` | `str` | required (defaults to `""`) |
| 6 | `at` | `Optional[str]` | Optional (UTC ISO timestamp; set by `record_decision`) |

### T2.3 Shape C — PlanStateSectionContract

5 SECTIONS per `SECTIONS = ("stage_ramp", "drivers", "payroll",
"capex_rd", "balance_sheet")` at evaluation_types.py:39.

Per-section payload shape depends on what each section's
revise_* tool commits. Section payloads carry model_input row
data — likely compose pieces of Contract 1's
FinmoModelInputContract.sections per PSL1. **First cut: type as
opaque `Dict[str, Any]`** with the 5-section Literal at the
envelope level. Section-specific sub-contract typing is
R-residual (per Contract 5b/c/d pattern).

### T2.4 Shape D — ValidationStateProjectionContract (11 fields per Bug 3)

Verbatim from set_validation_state at mirror.py:146-157:

| # | Field | Type | Required? | Notes |
|---|---|---|---|---|
| 1 | `all_pass` | `bool` | required | from EvaluatePlanResult.all_pass |
| 2 | `round_number` | `int` | required | F12-equivalent invariant: `ge=0` |
| 3 | `strictness` | `Literal["mini_finmo", "full_acceptance_gate"]` | required | F8-equivalent Literal pin per evaluation_types.py:110 |
| 4 | `failing_check_count` | `int` | required | derived from checks |
| 5 | `worst_failing_check` | `Optional[str]` | Optional (None when all pass) | |
| 6 | `worst_failing_distance` | `Optional[float]` | Optional | |
| 7 | `failing_check_names` | `List[str]` | required (defaults `[]`) | **Bug 3 cap: len ≤ 12** |
| 8 | `failing_check_names_truncated` | `bool` | required | True when raw count > 12 |
| 9 | `failing_lever_margins` | `List[LeverMarginEntryContract]` | required (defaults `[]`) | **Bug 3 cap: len ≤ 12** |
| 10 | `failing_lever_margins_truncated` | `bool` | required | True when raw count > 12 |
| 11 | `evaluated_at` | `Optional[str]` | Optional (UTC ISO) | from EvaluatePlanResult.evaluated_at |

**Cross-field invariant per PSL2 (the Bug 3 fix IS the contract):**
- `len(failing_check_names) <= 12 AND len(failing_lever_margins) <= 12`.
- `failing_check_names_truncated` MUST be True iff
  `failing_check_count > len(failing_check_names)` (= when raw
  count was capped).
- Same for `failing_lever_margins_truncated`.

### T2.5 Shape E — LeverMarginEntryContract (8 fields per Bug 3)

Inner dict in failing_lever_margins[] per mirror.py:135-145:

| # | Field | Type | Required? |
|---|---|---|---|
| 1 | `lever_id` | `Optional[str]` | Optional |
| 2 | `section` | `Optional[Literal[5 SECTIONS]]` | Optional |
| 3 | `current` | `Optional[float]` | Optional |
| 4 | `band_min` | `Optional[float]` | Optional |
| 5 | `band_max` | `Optional[float]` | Optional |
| 6 | `outside_band` | `bool` | required (filter predicate: only outside_band entries are in this list) |
| 7 | `pinned_min` | `bool` | required (defaults `False`) |
| 8 | `pinned_max` | `bool` | required (defaults `False`) |

**Filter invariant:** every entry in
`validation_state.failing_lever_margins` has
`outside_band == True` — the producer at mirror.py:130-133
explicitly filters: `failing_margins = [m for m in ... if
getattr(m, "outside_band", False)]`.

---

## T3. Consumer-side reads

### T3.1 `responder.render_mirror_for_proposal` (Bug 3 reader)

Per v2 §C: `responder.render_mirror_for_proposal` at
[responder.py:181-309](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L181)
renders mirror state into GPT prompts.

Specifically reads `mirror.validation_state` at responder.py:269+:
- all_pass / failing_check_count / worst_failing_check /
  worst_failing_distance for the header line
- failing_check_names + failing_check_names_truncated for the
  failing-check list
- failing_lever_margins (with pinned_min/max) for the lever
  context table

### T3.2 Amalgamated tools' `_echo_*_bands` helpers

Per Contract 6 §T3.2: every amalgamated tool's `_echo_*_bands`
helper reads `mirror.bands[section]` (which is a
GetBandsViewContract per Contract 6). Direct consumer of
Shape A `bands` field.

### T3.3 `evaluate_plan._margin_distance_from_bands`

Per Contract 6 §T3.2: reads `mirror.bands` via `get_bands`
fallback. Direct consumer of Shape A `bands` field.

### T3.4 Downstream Contract 3 (SolverInput) composition

Contract 3's `SolverInputContract.applied_model_input_json`
(Contract 1) carries the post-cascade FINAL state — which is
derived from `mirror.plan_state` after the full SessionDriver
loop completes. The Mirror itself doesn't flow directly into
SolverInputContract; the orchestrator extracts `model_input_json`
from a downstream post-session step.

**No direct cross-boundary leak.** Contract 7 types the
in-session Mirror state; Contract 3 types the post-session
extracted bundle. They share derived data but distinct surfaces.

### T3.5 Phantom-read pattern

Per v2 §D-2 + D-3:
- `mirror.recent_decisions` — setter `record_decision` is called
  but no production reader consumes it (ring buffer fills with
  no consumer). PHANTOM-WRITE.
- `mirror.sequence_position` and `mirror.budget` — never written
  by production code paths (build_mirror accepts them but no
  active caller passes them). PHANTOM-REQUIRED.

Both are CONFIRMED RESIDUAL per v2 §D. F-flag candidates for the
spec to decide on tightening vs. opaque-Optional.

---

## T4. Composition with prior contracts

### T4.1 Composition with Contract 6 — CONFIRMED at `bands`

`mirror.bands[section]` is loaded via Contract 6's `get_bands`
helper at mirror.py:218-225. Each section's value matches
Contract 6's `GetBandsViewContract` shape exactly.

**PSL1: re-import `GetBandsViewContract` from Contract 6 and
type `MirrorContract.bands` as `Dict[str, GetBandsViewContract]`.**

### T4.2 Composition with Contract 1 — at `plan_state` (per-section R-residual)

`mirror.plan_state[section]` carries model_input section
payloads. These are subsets of Contract 1's
`FinmoModelInputContract.sections.{revenue, expenses,
balance_sheet, schedules}`. Per-section sub-contract typing
deferred to R-residual; first cut types plan_state as
`Dict[<5-section Literal>, Dict[str, Any]]`.

### T4.3 No composition with Contract 5

`mirror.business_facts` reads from intake-side scalar fields
(Contract 5's territory) but Contract 5 itself only types the
8 JSON columns, not the scalar fields per Contract 5 F3 EXCLUDE
disposition. `business_facts` types as opaque `Dict[str, Any]`
here; R-residual retrofit when Contract 5 follow-ups land.

### T4.4 No composition with Contracts 2, 3, 4

- Contract 2 (workbook payload): downstream of solver; doesn't
  flow INTO amalgamated session.
- Contract 3 (solver input): downstream of amalgamated session;
  doesn't compose.
- Contract 4 (solver output): downstream of solver; doesn't
  compose.

---

## T5. Bugs 2-3 fix verification (the contract's invariants)

### T5.1 Bug 2 fix (851fa28) — plan_state refresh

Per v2 §B: `Mirror.set_plan_state_section(section, payload)` at
[mirror.py:163-180](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L163).

Verbatim:
```python
def set_plan_state_section(self, section: str, payload: Any) -> None:
  if not isinstance(self.plan_state, dict):
    self.plan_state = {}
  stored = copy.deepcopy(payload) if payload is not None else {}
  self.plan_state[section] = stored
  if section in ("balance_sheet", "capex_rd_balance_seed", "capex_rd"):
    self.plan_state["balance_sheet"] = stored
    self.plan_state["capex_rd_balance_seed"] = stored
```

**Alias-sync invariant:** when `section ∈ {balance_sheet,
capex_rd_balance_seed, capex_rd}`, ALL THREE keys in plan_state
share the same payload after this call. Per the docstring:
> "Aliases are kept in sync — balance_sheet and
> capex_rd_balance_seed mirror each other (the read-side closure
> at session_factory._build_current_payload_for treats them as
> aliases), so a write to one also writes the other."

Wired at session_factory.py:339-340 (callback) and invoked at
session_driver.py:663-680 (post-commit). Diagnostic emit:
`EventCode.CASCADE_PROPOSAL_APPLIED_TO_MIRROR`.

**Contract 7 @model_validator candidate (PSL2):**
`plan_state_alias_sync` — if any of the 3 alias keys is
present, all 3 must hold the same dict value.

Subtle catch: the third alias key `"capex_rd"` is written to
plan_state when triggered, but the docstring + code only echo
to `balance_sheet` and `capex_rd_balance_seed`. So if section
is `"capex_rd"`, plan_state["capex_rd"] holds the payload AND
plan_state["balance_sheet"] + plan_state["capex_rd_balance_seed"]
hold the same. Three-way mirror.

### T5.2 Bug 3 fix (b6968ae) — set_validation_state bounded projection

Per v2 §B: `Mirror.set_validation_state(evaluate_plan_result)`
at [mirror.py:106-161](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L106).

Caps at `_VALIDATION_STATE_RENDER_CAP = 12` per
mirror.py:34. Filters to failing-only:
- `failing_checks = [c for c in evaluate_plan_result.checks if not c.passed]`
- `failing_margins = [m for m in evaluate_plan_result.lever_margins if getattr(m, "outside_band", False)]`

Wired at session_factory.py:346-347 (callback) and invoked at
session_driver.py:857-865 (post-_evaluate). Best-effort
try/except — observability failure must not abort standards-
check.

**Contract 7 @model_validators (PSL2):**
1. `validation_state_failing_check_names_cap`: `len(failing_check_names) <= 12`
2. `validation_state_failing_lever_margins_cap`: `len(failing_lever_margins) <= 12`
3. `validation_state_truncation_flag_consistency`:
   `failing_check_names_truncated == (failing_check_count > len(failing_check_names))`
4. `validation_state_lever_margins_all_outside_band`:
   every entry in failing_lever_margins has `outside_band == True`
   (filter invariant from mirror.py:130-133).

### T5.3 Refresh callback wiring (NOT a contract invariant)

The callback wiring at session_factory.py:339-340 + :346-347
is structural plumbing — not something the contract can verify
at the data level. It's tested behaviorally (Contracts 1-6
include adapter tests that exercise the producer→consumer
path); Contract 7 adopts the same pattern.

---

## T6. Silent fallback / defensive patterns

### T6.1 best-effort try/except around set_validation_state

session_driver.py:863-870 wraps `_apply_to_validation_state_fn`
in a try/except. On failure, emits
`EVALUATE_PLAN_COMPLETED status=FAILED` with
`validation_state_projection_failed=True` and continues. The
standards-check path proceeds with `_last_result` (full
EvaluatePlanResult on the driver, not the bounded projection on
the mirror).

This is by design — observability must not abort logic. **Not a
contract concern.**

### T6.2 best-effort try/except around set_plan_state_section

session_driver.py at the Bug 2 invocation site has the same
pattern — wraps `_apply_to_plan_state_fn` in try/except,
emits `CASCADE_PROPOSAL_APPLIED_TO_MIRROR status=FAILED` on
failure, continues. Same disposition: observability-only.

### T6.3 `mirror.recent_decisions` ring-buffer-with-no-reader

Per v2 §D-2 / v1 §D-2. `record_decision` appends entries; cap
applies; nothing reads them. PHANTOM-WRITE. F-flag candidate:
mark Optional with default `[]` (matches production) vs. drop
entirely from contract (R-residual cleanup).

### T6.4 `mirror.sequence_position` / `mirror.budget` never written

Per v2 §D-3. Both accepted as kwargs to build_mirror but no
production caller passes them; both default to `{}`. PHANTOM-
REQUIRED. F-flag candidate similar to T6.3.

---

## T7. Producer-side gate feasibility

### T7.1 Single producer (`build_mirror`) — gate-feasible

The Mirror is constructed at a single function: `build_mirror`
at mirror.py:201-279. Producer-side gate would land
immediately before the return statement at mirror.py:259-265
(after the Mirror() dataclass is constructed but before the
return).

**However:** the Mirror's state at `build_mirror` return is
the INITIAL snapshot. The Bug 2 + Bug 3 refresh paths mutate
state in-process during the SessionDriver loop. A
producer-side gate at build_mirror would only validate the
initial state, not the post-refresh state.

### T7.2 Refresh-point gates (Bug 2 + Bug 3 invocation sites)

The Bug 2 + Bug 3 invocation sites at session_driver.py:663-680
and :857-865 are wrapped in best-effort try/except. Adding a
producer-side gate at the refresh point would either:
- Fail-loud on ContractViolation (changes the try/except
  semantic; potentially aborts the standards-check path)
- Be wrapped in the same try/except (silently swallowed —
  loses the contract enforcement value)

**Spec recommendation candidate (per PSL5):** SHIP a
producer-side gate at `build_mirror` return for initial-state
validation. SKIP refresh-point gates (R-residual; refresh-path
contract enforcement would require splitting the
try/except semantic, which is out of scope for Contract 7).

### T7.3 Consumer-side gate placement (per PSL6)

The Mirror is consumed at 3+ sites:
- `responder.render_mirror_for_proposal` at responder.py:181
- Amalgamated tools' `_echo_*_bands` helpers (multiple
  set_* tools)
- `evaluate_plan._margin_distance_from_bands` at
  evaluate_plan.py:189

A single consumer-side gate inside `Mirror.to_dict()` (at
mirror.py:182-192) would catch every read that serializes the
Mirror. But many consumers access the Mirror directly via
attribute (not via to_dict). So a single Mirror-level gate is
insufficient.

**Spec recommendation candidate:** per-shape consumer-side
gates at the actual read sites (similar to Contract 6 F15
per-shape pattern):
- Shape A MirrorContract gate inside `to_dict()` (catches
  serializer consumers like the GPT-prompt renderer)
- Shape D ValidationStateProjectionContract gate inside
  `responder.render_mirror_for_proposal` at responder.py:269
  (where the validation_state slice is read)
- Shape A's `bands` is already gated by Contract 6's Shape C
  gate at cohort_bands_table.py:386 (Contract 6 catches it
  upstream)

---

## T8. Divergences from v2 inventory

Taxonomy: NEW SUBSTANTIVE / NEW STRUCTURAL / CONFIRMED RESIDUAL
/ CONFIRMED CLOSED. **v2 was the post-Bug-fix baseline; most
findings CONFIRM rather than DIVERGE.**

### Div-1. Mirror dataclass 9-field shape — CONFIRMED + new detail

v2 §A confirms `Mirror` dataclass shape unchanged. Trace
enumerates all 9 data fields with type-today + Tier
classification (T2.1). NEW STRUCTURAL detail.

### Div-2. Bug 2 alias-sync invariant — NEW STRUCTURAL

v2 §A documented set_plan_state_section but did NOT enumerate
the 3-way alias-sync invariant (balance_sheet /
capex_rd_balance_seed / capex_rd all hold same payload after
write). This is the Bug 2 fix's contract-enforceable
invariant. Trace surfaces it explicitly for PSL2.

### Div-3. Bug 3 four invariants — NEW STRUCTURAL

v2 §A documented set_validation_state's bounded projection but
did NOT enumerate the 4 derivable contract invariants:
1. failing_check_names cap (≤ 12)
2. failing_lever_margins cap (≤ 12)
3. truncation_flag consistency
4. lever_margins all-outside-band filter

Trace surfaces all 4 for PSL2.

### Div-4. plan_state per-section payload shape — RESIDUAL / NEW STRUCTURAL

v2 §A doesn't enumerate per-section payload shapes (5 SECTIONS:
stage_ramp / drivers / payroll / capex_rd / balance_sheet).
Each section's revise_* tool commits a section-specific shape.
**Spec defers to opaque Dict[str, Any] per PSL1 first cut;
per-section typing R-residual.**

### Div-5. recent_decisions phantom-write — CONFIRMED RESIDUAL

v2 §D-2 noted this; trace confirms.

### Div-6. sequence_position / budget phantom-required — CONFIRMED RESIDUAL

v2 §D-3 noted both; trace confirms.

### Div-7. Composition with Contract 6 at `bands` — CONFIRMED

v2 confirmed bands loaded via `get_bands`; Contract 6's typing
applies. PSL1 re-imports `GetBandsViewContract`.

### Div-8. Adjustment B carry-over — CONFIRMED

Same intake_consult.py:7377 generic Exception catch propagates
ContractViolation. The Mirror is constructed inside
`prepare_initial_grid_for_draft` (or later post-intake steps);
ContractViolation from Contract 7's gates lands in the same
generic catch as Contracts 5 + 6.

---

## Open questions / flags for the spec doc

Numbered for the spec doc's §7. Same format as Contracts 1-6.
Expected count: 12-16 flags.

### F0 — Single module with multi-sub-contracts

**(Recommended) (a) Single Contract 7 module with 6
sub-contracts inside** per Contract 6 F0 pattern (PSL9).

### F1 — Composition with Contract 6 `GetBandsViewContract` for bands

**(Recommended) (a) YES.** Re-import. PSL1.

### F2 — Composition with Contract 1 for plan_state sections

**(Recommended) (a) DEFER to R-residual.** First cut: type
plan_state as `Dict[Literal[5 SECTIONS], Dict[str, Any]]`.
Per-section typing as Contract 1 sub-shape composition is
follow-up scope per Contract 5b/c/d pattern.

### F3 — recent_decisions phantom-write disposition (Div-5)

**(Recommended) (a) Optional[List[RecentDecisionContract]] = []
typing.** Matches production reality (setter exists; no
reader). R-residual cleanup to drop the setter + field.

### F4 — sequence_position + budget phantom-required disposition (Div-6)

**(Recommended) (a) Optional[Dict[str, Any]] = {} typing.**
Matches production: no caller passes them; default empty
dict. R-residual cleanup to drop the build_mirror kwargs.

### F5 — plan_state alias-sync invariant (T5.1 / Div-2)

**(Recommended) (a) ADD @model_validator on MirrorContract.**
The Bug 2 fix's 3-way alias-sync (balance_sheet /
capex_rd_balance_seed / capex_rd) becomes a contract invariant.
Surfaces regressions if a future refactor breaks the alias-sync.

### F6 — validation_state 4 invariants from Bug 3 (T5.2 / Div-3)

**(Recommended) (a) ADD all 4 @model_validators on
ValidationStateProjectionContract:**
- failing_check_names cap (≤ 12)
- failing_lever_margins cap (≤ 12)
- truncation_flag consistency
- lever_margins all-outside-band filter

### F7 — strictness Literal pinning

**(Recommended) (a) Literal["mini_finmo", "full_acceptance_gate"]**
per evaluation_types.py:110 docstring. Production vocabulary.

### F8 — section Literal pinning (5 SECTIONS)

**(Recommended) (a) Literal["stage_ramp", "drivers", "payroll",
"capex_rd", "balance_sheet"]** per evaluation_types.py:39.
Used in MirrorContract.plan_state keys + MirrorContract.bands
keys + LeverMarginEntryContract.section field.

### F9 — Producer-side gate feasibility (T7.1)

**(Recommended) (a) SHIP at `build_mirror` return for initial-
state validation.** SKIP refresh-point gates (R-residual;
refresh paths are best-effort observability, not gate-friendly).

### F10 — Consumer-side gate placement (T7.3)

**(Recommended) (a) Per-shape gates:** Shape A inside
`Mirror.to_dict()` (catches serializer consumers); Shape D
inside `responder.render_mirror_for_proposal` (where
validation_state slice is read). Shape A's `bands` field is
already gated upstream by Contract 6's Shape C gate at
cohort_bands_table.py:386 (no double-gate needed).

### F11 — Adjustment B carry-over (Div-8)

**(Recommended) (a) Re-use Contracts 3-6 pattern verbatim.**
intake_consult.py:7377 generic Exception catch.

### F12 — Diagnostic-emission invariant test (PSL8)

**(Recommended) (a) Single PhaseCode `AMALGAMATED_SESSION_CONTRACT`
covering all 6 shapes** per Contract 6 F16 pattern.
`diagnostic_data['shape']` distinguishes A/B/C/D/E/F for
queryability. Lockstep PhaseCode count 19 → 20.

### F13 — extra policy (PSL4)

**(Recommended) (a) `extra="forbid"` on top-level
MirrorContract; `extra="ignore"` on all sub-contracts.**

### F14 — Adapter (Commit 2) — SKIP per Contract 4-6 precedent

The Mirror IS already a dataclass — but unlike Contract 2's
DraftWorkbookData where the dataclass was the boundary
artifact, here the dataclass is INTERNAL to the
post_intake_amalgamated package and is mutated in-process.
A from_mirror_dataclass() classmethod on MirrorContract would
just wrap `dataclasses.asdict()` — trivial bridge. Skip per
Contract 4-6 precedent.

---

## Lessons baked in for Contract 7 spec drafting

- **Trace before spec.** The Bug 2 alias-sync (Div-2) + Bug 3
  bounded-projection invariants (Div-3) would have been costly
  assumption errors in the spec without verification at
  mirror.py:163-180 + :106-161. The exact 12-cap value + the
  3-way alias-sync set are production-verified before the
  spec lands.
- **Match production vocabulary verbatim.** SECTIONS tuple
  (5 names) + strictness Literal (2 values) + Bug 3 11-field
  projection + Bug 3 8-field margin entry all lifted from
  source.
- **Constraints from production reality.**
  `_VALIDATION_STATE_RENDER_CAP = 12` becomes a numeric
  invariant; `outside_band == True` filter becomes a
  per-entry invariant; alias-sync becomes a 3-way invariant.
- **Don't loosen safety checks.** F3 + F4 phantoms typed as
  Optional matches production-as-is without inventing required
  semantics.
- **`extra="forbid"` only on top-level.** F13.
- **Compose where downstream contracts already type the shape.**
  F1 composes Contract 6's `GetBandsViewContract` for
  Mirror.bands per PSL1.
- **Multi-shape contracts use one module + multiple sub-contracts.**
  F0 = Contract 6 pattern (PSL9). 6 sub-contracts here vs.
  Contract 6's 6 sub-contracts.
- **Refresh-semantic invariants from Bug fixes become
  @model_validators.** F5 + F6 encode the Bug 2 + Bug 3 fixes
  at the contract level (PSL2).
- **Diagnostic-emission invariant matters.** F12 extends the
  established pattern from Contract 2 restoration through
  Contracts 3-6 to Contract 7 — every contract gets its own
  PhaseCode + observability test.
