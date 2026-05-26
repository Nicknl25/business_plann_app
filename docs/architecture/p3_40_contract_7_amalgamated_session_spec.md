# P3.40 Contract 7 — AmalgamatedSessionContract (Spec)

**Status:** Specification only. No code lands until Nick reviews this doc.
After review, implementation follows the commit sequence in §6 below.

**Boundary covered:** INDUSTRY_BASELINE → AMALGAMATED_SESSION
(Boundary 3 in
[p3_40_pipeline_data_flow_inventory_v2.md](p3_40_pipeline_data_flow_inventory_v2.md)).

**FINAL CONTRACT in the P3.40 sequence.** After Commit 3 lands,
Boundaries 1-7 are end-to-end contract-typed.

**Predecessors:**
- [Contract 6 — IndustryBaselineResolvedContract](p3_40_contract_6_industry_baseline_spec.md)
  (landed end-to-end at c196a09). Contract 7 composes
  `GetBandsViewContract` for `mirror.bands` per F1.
- Contracts 1-5 are upstream/downstream of this boundary but
  don't compose into Contract 7 directly (Contract 1 per-section
  composition deferred to R-residual per F2).

**Companion trace doc:** [p3_40_contract_7_amalgamated_session_trace.md](p3_40_contract_7_amalgamated_session_trace.md)
(landed at 9a353c3, 721 LOC, 15 flags surfaced).

**Lessons applied from Contracts 1-6:**
- Trace before spec. Bugs 2-3 fix invariants verified at
  mirror.py:163-180 + :106-161 before encoding as
  @model_validators (pre-1a re-verification per Contracts 4-6
  precedent).
- Match production vocabulary verbatim. 5 SECTIONS + 2-value
  strictness Literal + 12-cap value + outside_band filter all
  lifted from mirror.py + evaluation_types.py.
- Constraints from production reality. `float` for numeric
  margin fields per Contract 2 1a-fix.
- Don't loosen safety checks. F3 + F4 phantom Optionals match
  production-as-is.
- `extra="forbid"` only on top-level (F13).
- Compose where downstream contracts already type the shape
  (F1 composes Contract 6).
- Multi-shape contracts use one module + multiple sub-contracts
  (F0 pattern from Contract 6).
- Refresh-semantic invariants from Bug fixes become
  @model_validators (F5 + F6 — the Bug 2/3 fixes ARE the
  contract).
- Adjustment B is recurring (F11).
- Diagnostic-emission invariant extends (F12).
- **First dataclass-shaped boundary** — `asdict(mirror)`
  conversion documented explicitly (F14).

---

## 1. Trace Task Findings

The 8 pre-implementation traces (T1-T8) produced findings folded
directly into this spec's structure. Full enumeration is in the
trace doc; this section consolidates the ones that change
contract design.

### 1.1 5 headline findings (trace summary)

1. **The Mirror dataclass IS the boundary surface.** 9 data
   fields (10 minus `recent_decisions_cap` internal) at
   [mirror.py:75-86](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L75).
   Bug 2 + Bug 3 fixes added 2 callback-driven refresh paths
   that mutate Mirror state in-process during the cascade.

2. **Refresh-semantic invariants from Bugs 2-3 become
   @model_validators per PSL2.** Bug 2 fix
   ([mirror.py:163-180](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L163))
   = 3-way alias-sync; Bug 3 fix
   ([mirror.py:106-161](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L106))
   = 4 bounded-projection invariants.

3. **Multi-shape contract per F0/Contract 6 pattern.** 6
   sub-contracts in a single module.

4. **Composition with Contract 6 CONFIRMED** at `mirror.bands`
   (loaded via `get_bands` at mirror.py:218-225). PSL1 re-import.

5. **v2 inventory was the post-Bug-fix baseline.** Trace mostly
   CONFIRMS with detail additions; no major NEW SUBSTANTIVE
   divergences.

### 1.2 8 trace divergences (folded into §7)

Per trace T8: 1 CONFIRMED detail (Mirror 9-field shape), 2 NEW
STRUCTURAL (Bug 2 alias-sync invariant + Bug 3 4-invariant
enumeration), 1 NEW STRUCTURAL detail (plan_state per-section
opaque deferral), 2 CONFIRMED RESIDUAL phantoms (recent_decisions,
sequence_position+budget), 1 CONFIRMED carry-over (Adjustment B).
All fold into F0-F14 flags below.

---

## 2. Top-level Mirror payload + 4 internal sub-shapes

Per the F0/Contract 6 multi-shape pattern, Contract 7 types **6
sub-contracts** in a single module:

| Shape | Source | Field count | Notes |
|---|---|---|---|
| **A — MirrorContract** | `Mirror` dataclass at mirror.py:75-86 | 9 data fields | Top-level boundary surface |
| **B — RecentDecisionContract** | `RecentDecision` dataclass at mirror.py:64-72 | 6 fields | Ring-buffer entry (phantom-write per F3) |
| **C — PlanStateSectionContract** | `Mirror.plan_state[section]` | section-dependent (opaque per F2) | 5 SECTIONS Literal at envelope level |
| **D — ValidationStateProjectionContract** | `Mirror.set_validation_state` output at mirror.py:146-157 | 11 fields | Bug 3 bounded projection |
| **E — LeverMarginEntryContract** | inner dict in `failing_lever_margins[]` at mirror.py:135-145 | 8 fields | Per Bug 3 |
| **F — `GetBandsViewContract`** | re-import from Contract 6 | n/a (composition) | F1 — no redefinition |

### 2.1 Shape A — MirrorContract (9 data fields)

Per Mirror dataclass at mirror.py:75-86. `recent_decisions_cap`
excluded (internal config, not boundary surface — matches the
`to_dict()` precedent at mirror.py:182-192).

| # | Field | Type | Required? | Tier |
|---|---|---|---|---|
| 1 | `invariants` | `Dict[str, str]` | required (defaults to `_INVARIANTS` const) | A |
| 2 | `authority` | `str` | required (defaults to `_AUTHORITY` const) | A |
| 3 | `business_facts` | `Dict[str, Any]` | required (intake-extracted; R-residual retrofit) | A |
| 4 | `plan_state` | `Dict[Literal[5 SECTIONS], Dict[str, Any]]` | required (5 SECTIONS may each be `{}`) | A |
| 5 | `sequence_position` | `Optional[Dict[str, Any]] = None` per F4 | Optional (phantom-required per v2 §D-3) | A |
| 6 | `bands` | `Dict[Literal[5 SECTIONS], GetBandsViewContract]` | required (composes Contract 6 per F1) | A |
| 7 | `validation_state` | `Optional[ValidationStateProjectionContract] = None` | Optional (empty `{}` pre-evaluate; populated by Bug 3 refresh) | A |
| 8 | `recent_decisions` | `Optional[List[RecentDecisionContract]] = None` per F3 | Optional (phantom-write per v2 §D-2) | A |
| 9 | `budget` | `Optional[Dict[str, Any]] = None` per F4 | Optional (phantom-required per v2 §D-3) | A |

### 2.2 Shape B — RecentDecisionContract (6 fields)

Per RecentDecision dataclass at mirror.py:64-72:

| # | Field | Type | Required? |
|---|---|---|---|
| 1 | `tool_name` | `str = Field(min_length=1)` | required |
| 2 | `inputs_summary` | `str` | required |
| 3 | `delta_all_pass` | `Optional[int]` | Optional (-1/0/+1 indicator) |
| 4 | `delta_worst_distance` | `Optional[float]` | Optional |
| 5 | `result_summary` | `str = ""` | required (default empty string) |
| 6 | `at` | `Optional[str]` | Optional (UTC ISO timestamp set by `record_decision`) |

### 2.3 Shape C — PlanStateSectionContract (opaque per F2)

5 SECTIONS per `SECTIONS = ("stage_ramp", "drivers", "payroll",
"capex_rd", "balance_sheet")` at evaluation_types.py:39.

Per-section payload depends on the section's revise_* tool
commit shape. **First cut per F2: type as opaque `Dict[str, Any]`**
with the 5-section Literal at the envelope level. Per-section
sub-contract typing (Contract 1 composition) is R-residual.

### 2.4 Shape D — ValidationStateProjectionContract (11 fields per Bug 3)

Verbatim from set_validation_state at mirror.py:146-157:

| # | Field | Type | Required? | Notes |
|---|---|---|---|---|
| 1 | `all_pass` | `bool` | required | from EvaluatePlanResult.all_pass |
| 2 | `round_number` | `int = Field(ge=0)` | required | |
| 3 | `strictness` | `Literal["mini_finmo", "full_acceptance_gate"]` (F7) | required | per evaluation_types.py:110 |
| 4 | `failing_check_count` | `int = Field(ge=0)` | required | derived from `[c for c in checks if not c.passed]` |
| 5 | `worst_failing_check` | `Optional[str] = None` | Optional | None when all pass |
| 6 | `worst_failing_distance` | `Optional[float] = None` | Optional | |
| 7 | `failing_check_names` | `List[str] = Field(default_factory=list, max_length=12)` (F6 invariant i) | required | **Bug 3 cap: ≤ 12** |
| 8 | `failing_check_names_truncated` | `bool` | required | True iff `failing_check_count > len(failing_check_names)` (F6 invariant iii) |
| 9 | `failing_lever_margins` | `List[LeverMarginEntryContract] = Field(default_factory=list, max_length=12)` (F6 invariant ii) | required | **Bug 3 cap: ≤ 12** |
| 10 | `failing_lever_margins_truncated` | `bool` | required | F6 invariant iii (mirror) |
| 11 | `evaluated_at` | `Optional[str] = None` | Optional | UTC ISO from EvaluatePlanResult.evaluated_at |

### 2.5 Shape E — LeverMarginEntryContract (8 fields per Bug 3)

Inner dict in failing_lever_margins[] per mirror.py:135-145:

| # | Field | Type | Required? |
|---|---|---|---|
| 1 | `lever_id` | `Optional[str] = None` | Optional |
| 2 | `section` | `Optional[Literal[5 SECTIONS]] = None` (F8) | Optional |
| 3 | `current` | `Optional[float] = None` | Optional |
| 4 | `band_min` | `Optional[float] = None` | Optional |
| 5 | `band_max` | `Optional[float] = None` | Optional |
| 6 | `outside_band` | `bool` (F6 invariant iv — every entry MUST be True) | required |
| 7 | `pinned_min` | `bool = False` | required (defaults False) |
| 8 | `pinned_max` | `bool = False` | required |

### 2.6 Shape F — `GetBandsViewContract` (composed from Contract 6 per F1)

Re-imported from Contract 6's
`industry_baseline_resolved_contract.py`. No redefinition. Used
in `MirrorContract.bands: Dict[Literal[5 SECTIONS], GetBandsViewContract]`.

---

## 3. Field-by-field contract spec

### 3.1 6 sub-contracts (per §2.1-2.6)

Already enumerated in §2. Spec module exports:

```python
__all__ = [
  "AMALGAMATED_SESSION_STAGE_LABEL",
  "MirrorContract",
  "RecentDecisionContract",
  "PlanStateSectionContract",   # (alias for Dict[str, Any] -- documentary)
  "ValidationStateProjectionContract",
  "LeverMarginEntryContract",
  # Re-exported from Contract 6 (PSL1 / F1):
  "GetBandsViewContract",
  "GetBandsViewBandContract",
  # Re-exported from Contract 1 (gate callers import ContractViolation from one place):
  "ContractViolation",
]
```

### 3.2 Re-imports from prior contracts

```python
# Contract 6 composition per F1:
from client_intake_and_finmo.post_intake_contracts.industry_baseline_resolved_contract import (
  GetBandsViewContract,
  GetBandsViewBandContract,
)
# Contract 1 ContractViolation re-export only:
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
)
```

ZERO redefinition of `GetBandsViewContract`; same class identity
ensures type-checking parity across Contracts 6 + 7.

### 3.3 Module-level constants

```python
AMALGAMATED_SESSION_STAGE_LABEL = "INDUSTRY_BASELINE->AMALGAMATED_SESSION"

# Per evaluation_types.py:39 -- the 5 SECTIONS Mirror tracks.
SUPPORTED_SECTIONS = ("stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet")

# Per evaluation_types.py:110 -- the 2-value strictness vocabulary.
SUPPORTED_STRICTNESS_VALUES = ("mini_finmo", "full_acceptance_gate")

# Per mirror.py:34 -- Bug 3 bounded-projection cap. Numeric constant
# the F6 invariants reference; lifted from production verbatim.
VALIDATION_STATE_RENDER_CAP = 12

# Per Bug 2 fix at mirror.py:163-180 -- the 3-way alias triplet.
# When plan_state contains any of these section keys, all 3 must
# hold the same payload (F5 invariant).
PLAN_STATE_ALIAS_TRIPLET = ("balance_sheet", "capex_rd_balance_seed", "capex_rd")
```

### 3.4 Zero new sub-contracts for plan_state per F2

Per F2: plan_state types as
`Dict[Literal[5 SECTIONS], Dict[str, Any]]` first cut. Per-section
typing (Contract 1 composition) is R-residual. Aliased section
keys (`capex_rd_balance_seed`) accepted as extra keys via
top-level alias-sync invariant — see §4.1.

---

## 4. Cross-field invariants

### 4.1 F5 — Bug 2 plan_state alias-sync invariant

```python
class MirrorContract(BaseModel):
  ...
  @model_validator(mode="after")
  def plan_state_alias_sync(self) -> "MirrorContract":
    """F5 / Bug 2 fix invariant (mirror.py:163-180).

    When plan_state contains ANY of the 3 alias keys
    (balance_sheet, capex_rd_balance_seed, capex_rd), ALL three
    must hold the same payload after a set_plan_state_section
    call -- this is the structural invariant the Bug 2 fix
    established. Future regression of the alias-sync surfaces
    as ContractViolation.

    Sub-condition: if NONE of the 3 alias keys is present, no
    constraint (pre-first-commit state).
    """
    alias_keys = PLAN_STATE_ALIAS_TRIPLET  # 3-tuple
    present_aliases = {k: self.plan_state.get(k) for k in alias_keys if k in self.plan_state}
    if not present_aliases:
      return self  # no aliases yet; pre-commit state
    # All present aliases must hold the same payload.
    values = list(present_aliases.values())
    first = values[0]
    for k, v in present_aliases.items():
      if v != first:
        raise ValueError(
          f"plan_state alias-sync violated: keys {list(present_aliases.keys())} "
          f"hold differing payloads. Bug 2 fix requires balance_sheet / "
          f"capex_rd_balance_seed / capex_rd all carry the same payload after "
          f"set_plan_state_section commits (mirror.py:163-180)."
        )
    return self
```

### 4.2 F6 — Bug 3 four bounded-projection invariants

Encoded as @model_validators on `ValidationStateProjectionContract`:

```python
class ValidationStateProjectionContract(BaseModel):
  ...

  @model_validator(mode="after")
  def failing_check_names_cap(self) -> "ValidationStateProjectionContract":
    """F6 invariant (i) -- Bug 3 cap. Per
    _VALIDATION_STATE_RENDER_CAP=12 at mirror.py:34, failing_check_names
    is bounded at 12. The Field(max_length=12) declaration enforces
    this at field-level; this validator is documentary."""
    if len(self.failing_check_names) > VALIDATION_STATE_RENDER_CAP:
      raise ValueError(
        f"failing_check_names exceeds Bug 3 cap of {VALIDATION_STATE_RENDER_CAP}; "
        f"got {len(self.failing_check_names)} (mirror.py:34, :128)"
      )
    return self

  @model_validator(mode="after")
  def failing_lever_margins_cap(self) -> "ValidationStateProjectionContract":
    """F6 invariant (ii) -- mirror of (i) for lever margins."""
    if len(self.failing_lever_margins) > VALIDATION_STATE_RENDER_CAP:
      raise ValueError(
        f"failing_lever_margins exceeds Bug 3 cap of "
        f"{VALIDATION_STATE_RENDER_CAP}; got {len(self.failing_lever_margins)}"
      )
    return self

  @model_validator(mode="after")
  def truncation_flag_consistency(self) -> "ValidationStateProjectionContract":
    """F6 invariant (iii) -- truncation flag MUST be True iff
    raw count was capped. Catches drift between the projection
    and the truncated-list outputs.

    NOTE: we can't directly recover the raw counts from the
    capped projection (those are upstream EvaluatePlanResult
    state). The invariant we CAN enforce: if the list is at-or-
    above cap AND truncated_flag is False, that's a definitive
    violation (truncation must have occurred). If the list is
    below cap, truncated_flag could legitimately be either True
    (extreme edge case where exactly cap entries were failing
    but the cap+1 entry was also failing) or False (normal
    case). So we enforce one half:

      truncated_flag must be True if list length >= cap.

    The full bidirectional invariant requires upstream context;
    this half catches the common-case regression.
    """
    if len(self.failing_check_names) >= VALIDATION_STATE_RENDER_CAP and not self.failing_check_names_truncated:
      raise ValueError(
        f"failing_check_names_truncated must be True when "
        f"failing_check_names length is at-or-above cap "
        f"({VALIDATION_STATE_RENDER_CAP})"
      )
    if len(self.failing_lever_margins) >= VALIDATION_STATE_RENDER_CAP and not self.failing_lever_margins_truncated:
      raise ValueError(
        f"failing_lever_margins_truncated must be True when "
        f"failing_lever_margins length is at-or-above cap "
        f"({VALIDATION_STATE_RENDER_CAP})"
      )
    return self

  @model_validator(mode="after")
  def lever_margins_all_outside_band(self) -> "ValidationStateProjectionContract":
    """F6 invariant (iv) -- per the producer filter at
    mirror.py:130-133, every entry in failing_lever_margins has
    outside_band=True. The producer filters explicitly:

      failing_margins = [m for m in evaluate_plan_result.lever_margins
                         if getattr(m, "outside_band", False)]

    So at the contract layer, an entry with outside_band=False
    is a producer-side bug (e.g., a future refactor that skipped
    the filter). Surface as ContractViolation."""
    for i, entry in enumerate(self.failing_lever_margins):
      if not entry.outside_band:
        raise ValueError(
          f"failing_lever_margins[{i}].outside_band must be True "
          f"(producer filter at mirror.py:130-133 should exclude "
          f"in-band entries); got outside_band=False for "
          f"lever_id={entry.lever_id!r}"
        )
    return self
```

### 4.3 No other cross-field invariants for first cut

Other invariant candidates (R-residual cleanup R8-R9):
- `business_facts` vs intake-side scalar agreement — needs
  Contract 5b/c/d sub-contracts before it can be cross-checked.
- `plan_state[section]` vs `bands[section]` agreement on
  lever_id sets — would require per-section typing (R-residual
  per F2).

---

## 5. Boundary enforcement

### 5.1 Producer-side gate — F9 SHIP at `build_mirror` return only

**Location:** immediately before the return statement at
[mirror.py:259+](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L259)
(after the Mirror dataclass is constructed but before the
return). Lazy import + emit-skip per Contracts 3-6 consumer-
gate pattern.

```python
# mirror.py:259+ (after building the Mirror dataclass)
from client_intake_and_finmo.post_intake_contracts.enforcement import (
  SIDE_PRODUCER as _AS_SIDE_PRODUCER,
  validate_amalgamated_session_at_boundary,
)
validate_amalgamated_session_at_boundary(
  asdict(mirror),  # F14 -- dataclass-to-dict conversion
  side=_AS_SIDE_PRODUCER,
)
```

**Refresh-point gates SKIPPED.** Gating
`set_plan_state_section` / `set_validation_state` refresh
callbacks would either:
- Fail-loud on ContractViolation (changes the
  best-effort try/except semantic at session_driver.py:663-680
  + :857-865; potentially aborts the standards-check path on
  observability work).
- Be wrapped in the same try/except (silently swallowed —
  loses the contract enforcement value).

Per F9 (a): the @model_validators on Bug 2/3 invariants fire
at consumer-side reads (when the gate runs at `to_dict()` or
`responder.render_mirror_for_proposal`), so structural
violations still surface; just not at every refresh tick.

### 5.2 Consumer-side gate placement — F10 per-shape

**3 consumer-side gate sites:**

#### 5.2.1 Shape A (MirrorContract) gate inside `Mirror.to_dict()`

The to_dict() at mirror.py:182-192 is the canonical Mirror
serialization point. Consumers that serialize the Mirror (GPT
prompt renderer, audit dumps) go through this method. Gate
fires at every serialization; catches any in-process mutation
that violated invariants.

```python
# mirror.py:182-192 (modify to_dict to validate before returning)
def to_dict(self) -> Dict[str, Any]:
  payload = {
    "invariants": dict(self.invariants),
    "authority": self.authority,
    "business_facts": copy.deepcopy(self.business_facts),
    "plan_state": copy.deepcopy(self.plan_state),
    "sequence_position": copy.deepcopy(self.sequence_position),
    "bands": copy.deepcopy(self.bands),
    "validation_state": copy.deepcopy(self.validation_state),
    "recent_decisions": [d.to_dict() for d in self.recent_decisions],
    "budget": copy.deepcopy(self.budget),
  }
  # P3.40 Contract 7 Commit 3 -- Shape A consumer-side gate.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (
    SIDE_CONSUMER as _AS_SIDE_CONSUMER,
    validate_amalgamated_session_at_boundary,
  )
  validate_amalgamated_session_at_boundary(
    payload, side=_AS_SIDE_CONSUMER,
  )
  return payload
```

#### 5.2.2 Shape D (ValidationStateProjectionContract) gate inside `responder.render_mirror_for_proposal`

At
[responder.py:269](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L269)
where the validation_state slice is read for GPT rendering.
Gate validates the bounded projection right before rendering.

```python
# responder.py:269 (before reading vs)
vs = getattr(mirror, "validation_state", None) or {}
# P3.40 Contract 7 Commit 3 -- Shape D consumer-side gate.
# Only validate when vs is non-empty (validation_state is {} pre-evaluate).
if vs:
  from client_intake_and_finmo.post_intake_contracts.enforcement import (
    SIDE_CONSUMER as _AS_SIDE_CONSUMER,
    validate_amalgamated_validation_state_at_boundary,
  )
  validate_amalgamated_validation_state_at_boundary(
    vs, side=_AS_SIDE_CONSUMER,
  )
```

#### 5.2.3 Shape A `bands` already gated upstream by Contract 6

Per Contract 6 §5.2.3, Shape C gate at cohort_bands_table.py:386
inside `get_bands` validates the GetBandsView shape. Contract 7's
Shape A composes Contract 6's typed shape — re-gating at the
Mirror-read time would be redundant. **No additional `bands` gate
needed.**

### 5.3 Enforcement helpers

Per F0 + F12: single PhaseCode across all shapes;
`diagnostic_data['shape']` field distinguishes A/B/C/D/E.
**2 enforcement helpers** (Mirror full + Validation projection
slice):

```python
# enforcement.py additions
AMALGAMATED_SESSION_STAGE_LABEL = "INDUSTRY_BASELINE->AMALGAMATED_SESSION"

def validate_amalgamated_session_at_boundary(
  payload: Dict[str, Any], *, side: str,
  stage: str = AMALGAMATED_SESSION_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> MirrorContract:
  """Shape A (full Mirror) validation. Includes F5 alias-sync
  invariant via the MirrorContract @model_validator."""
  ...

def validate_amalgamated_validation_state_at_boundary(
  payload: Dict[str, Any], *, side: str,
  stage: str = AMALGAMATED_SESSION_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> ValidationStateProjectionContract:
  """Shape D (validation_state slice) validation. Includes F6
  four bounded-projection invariants. Used at
  responder.py:269+ where consumers read the projection
  directly without serializing the full Mirror."""
  ...
```

Both helpers share `AMALGAMATED_SESSION_STAGE_LABEL` +
`PhaseCode.AMALGAMATED_SESSION_CONTRACT`;
`diagnostic_data['shape']` = 'mirror' / 'validation_state' to
distinguish.

### 5.4 F14 — Dataclass-to-dict conversion at gate sites

**The Mirror is the FIRST DATACLASS-SHAPED boundary in the
P3.40 series.** Contracts 1-6 were dict-shaped at the boundary;
Pydantic's `model_validate` consumed dicts directly.

For Contract 7, gate sites convert via `dataclasses.asdict()`:
- At the producer-side gate (mirror.py:259+): `asdict(mirror)`
  serializes the dataclass to a dict that Pydantic validates.
- At the Shape A consumer gate inside `to_dict()`: the method
  already builds the dict; the gate validates that dict.
- At the Shape D consumer gate inside responder.py:269: the
  validation_state field is already a dict (it's typed
  `Dict[str, Any]` on the Mirror dataclass and populated by
  `set_validation_state` writing dict literals); no conversion
  needed.

**`asdict()` handles the nested RecentDecision dataclass
automatically** (recursive conversion is built into
`dataclasses.asdict`). No special-case adapter needed.

If during 1a implementation the conversion proves more complex
(e.g., a future refactor adds a Mirror field that holds a
non-dataclass object asdict can't serialize), add an explicit
`MirrorContract.from_mirror(mirror: Mirror) -> MirrorContract`
classmethod and treat that as Commit 2 work. **For first cut:
asdict suffices.**

### 5.5 Adjustment B verification (F11 — confirmed)

Per trace Div-8: same intake_consult.py:7377 generic
`except Exception as exc:` catch handles ContractViolation per
Contracts 3-6 pattern. The Mirror is constructed inside
`prepare_initial_grid_for_draft` (or post-intake amalgamated
steps); ContractViolations from Contract 7's gates propagate
through the same chain.

### 5.6 PhaseCode / EventCode / FailFastCode additions (F12)

**One PhaseCode for Contract 7** (one boundary, one phase per
F12):

- `PhaseCode.AMALGAMATED_SESSION_CONTRACT`
- `EventCode.AMALGAMATED_SESSION_CONTRACT_VALIDATED`
- `EventCode.AMALGAMATED_SESSION_CONTRACT_VIOLATION`
- `FailFastCode.FAIL_AMALGAMATED_SESSION_CONTRACT_VIOLATION = "fail_amalgamated_session_contract_violation"`

Lockstep test updates:
- `test_phase_9_p3_33_phase3_step9a_phase_codes.py`: rename
  `test_phase_code_has_nineteen_phases` → `_twenty_phases`;
  count 19 → 20.

### 5.7 Diagnostic-emission invariant test (F12)

- `ContractSevenEmitsAmalgamatedSessionPhaseCodeTest` (1 new in
  `tests/test_p3_40_diagnostic_emission_invariant.py`).
- `PhaseCodesDoNotCrossContaminateTest` extension: 1 new test
  confirming Contract 7 violations route to
  `AMALGAMATED_SESSION_CONTRACT` exclusively (not Contracts 1-6
  phase codes).

Invariant-file count: 11 → 13.

---

## 6. Implementation sequence

After Nick green-lights this spec, implementation follows.

### Commit 1a — Contract module

File: `python/client_intake_and_finmo/post_intake_contracts/amalgamated_session_contract.py`

- 5 new sub-contracts per §2: MirrorContract,
  RecentDecisionContract, ValidationStateProjectionContract,
  LeverMarginEntryContract.
  - PlanStateSectionContract NOT a sub-contract per F2 (typed
    as `Dict[str, Any]` inside MirrorContract.plan_state).
- Re-imports from Contract 6 (GetBandsViewContract per F1) +
  Contract 1 (ContractViolation re-export).
- 4 module constants (AMALGAMATED_SESSION_STAGE_LABEL,
  SUPPORTED_SECTIONS, SUPPORTED_STRICTNESS_VALUES,
  VALIDATION_STATE_RENDER_CAP, PLAN_STATE_ALIAS_TRIPLET).
- 1 cross-field invariant on MirrorContract (F5 alias-sync).
- 4 cross-field invariants on ValidationStateProjectionContract
  (F6 i-iv).
- `extra="forbid"` top-level (F13); `extra="ignore"` on all
  sub-contracts.
- Module docstring covers:
  - 6-sub-contract design rationale (F0)
  - F1 Contract 6 composition for bands
  - F2 plan_state per-section opaque first cut + R-residual
  - F5/F6 invariant rationale tracing to Bug 2/3 fixes
  - F14 dataclass-to-dict conversion via asdict
  - 11 R-residuals (R8-R18)

Expected LOC: 500-700 — similar to Contract 6 at 552. Within
700-LOC cap.

**Pre-step:** re-verify field counts + Literal values + Bug 2
alias triplet + Bug 3 cap value at writer sites before defining
sub-contracts (per Contracts 4-6 pre-1a re-verification
discipline).

### Commit 1b — Fixtures + sub-contract tests

`tests/_p3_40_contract_7_fixtures.py` +
`tests/test_p3_40_contract_7_subcontracts.py`

Fixtures:
- `valid_recent_decision_dict(tool_name=...)`
- `valid_lever_margin_entry_dict(lever_id=...)`
- `valid_validation_state_projection_dict(failing_count=0)`
- `valid_plan_state_section_dict(section=...)` — opaque dict
- `valid_mirror_dict(include_validation_state=True, ...)`
  — top-level with Contract 6 fixture re-uses for bands

Test classes (~7 per spec):
- `RecentDecisionContractTest` (~3): valid; missing tool_name
  rejected; Optional defaults.
- `ValidationStateProjectionContractTest` (~10):
  - valid full payload
  - F6 (i) failing_check_names > 12 rejected
  - F6 (ii) failing_lever_margins > 12 rejected
  - F6 (iii) truncation flag consistency — len >= 12 + not-True rejected
  - F6 (iv) outside_band=False rejected
  - F7 strictness Literal typo rejected; both spellings accepted
  - Optional fields default to None
- `LeverMarginEntryContractTest` (~4): valid; outside_band=True
  required; section Literal (F8) typo rejected; pinned_min/max
  defaults False.
- `MirrorContractTest` (~6):
  - valid full payload
  - F5 alias-sync invariant fires (3-way mismatch)
  - F5 alias-sync OK when only 1 alias key present
  - F5 alias-sync OK when none present (pre-commit state)
  - F4 sequence_position + budget Optional absent
  - F3 recent_decisions Optional absent
- `VocabularyConstantsTest` (~5): pins
  AMALGAMATED_SESSION_STAGE_LABEL,
  SUPPORTED_SECTIONS, SUPPORTED_STRICTNESS_VALUES,
  VALIDATION_STATE_RENDER_CAP, PLAN_STATE_ALIAS_TRIPLET
  matches Literals.
- `ExtraPolicyTest` (~3): F13 extra='ignore' on sub-contracts
  (Mirror, Validation, LeverMargin).

Expected total: 30-35 tests.

### Commit 1c — Top-level + cross-field + Adjustment B tests

`tests/test_p3_40_contract_7_amalgamated_session.py`

5 test classes:
- `MirrorContractTopLevelTest` (~5): full payload + extra='forbid' +
  required-field rejection.
- `CompositionWithContract6Test` (~3): bands field typed as
  Dict[Literal[5 SECTIONS], GetBandsViewContract]; Contract 6
  invariant violations (F12 monotonicity inside band) propagate
  through Contract 7.
- `CompositionInternalTest` (~4): validation_state + lever_margins
  + plan_state sub-contract violations propagate through
  MirrorContract.
- `CrossFieldInvariantTest` (~5): F5 alias-sync; F6 (i-iv) all
  4 invariants firing through top-level construction.
- `ApiBoundaryContractViolationTest` (~4): Adjustment B per
  Contracts 3-6 pattern.

Expected total: 20-25 tests.

### Commit 2 — SKIP per F14 / Contracts 4-6 precedent

No standalone adapter module. F14 disposition: `asdict(mirror)`
suffices for the dataclass-to-dict conversion at gate sites.
If 1a implementation discovers a complication, add explicit
classmethod and treat as Commit 2. **For first cut: skip.**

Implementation sequence: **1a → 1b → 1c → 3** (4 commits).

### Commit 3 — Gates + helpers + diagnostic codes + invariant test

ONE commit covering all gates per F9/F10 + 2 helpers per §5.3 +
codes + invariant test.

Files modified:
- `python/client_intake_and_finmo/post_intake_diagnostics/phase_codes.py`
  (add `PhaseCode.AMALGAMATED_SESSION_CONTRACT` +
  `EventCode.AMALGAMATED_SESSION_CONTRACT_VALIDATED` +
  `EventCode.AMALGAMATED_SESSION_CONTRACT_VIOLATION` + partition
  entry).
- `python/client_intake_and_finmo/post_intake_diagnostics/fail_fast_codes.py`
  (add `FailFastCode.FAIL_AMALGAMATED_SESSION_CONTRACT_VIOLATION`
  + partition + raise_fail_fast mapping).
- `tests/test_phase_9_p3_33_phase3_step9a_phase_codes.py`
  (rename `_nineteen_phases` → `_twenty_phases`; count 19 → 20).
- `python/client_intake_and_finmo/post_intake_contracts/enforcement.py`
  (add 2 helpers: `validate_amalgamated_session_at_boundary`,
  `validate_amalgamated_validation_state_at_boundary`; re-export
  `AMALGAMATED_SESSION_STAGE_LABEL`; `__all__` updated).
- `python/client_intake_and_finmo/post_intake_amalgamated/mirror.py`
  (producer-side gate at build_mirror return per F9; consumer-side
  gate inside to_dict per F10/§5.2.1).
- `python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py`
  (consumer-side Shape D gate at responder.py:269 per §5.2.2).
- `tests/test_p3_40_diagnostic_emission_invariant.py`
  (ContractSevenEmitsAmalgamatedSessionPhaseCodeTest +
  PhaseCodesDoNotCrossContaminateTest extension).
- `tests/test_p3_40_contract_7_consumer_gate.py` (NEW).

Tests in `tests/test_p3_40_contract_7_consumer_gate.py`:
- `MirrorProducerGateTest` (~3): valid Mirror through producer
  gate; F5 alias-sync violation rejected; both side strings
  accepted.
- `MirrorConsumerGateTest` (~3): valid Mirror through consumer
  helper; bad sub-payloads (broken F5 + F6) rejected.
- `ValidationStateConsumerGateTest` (~4): valid projection;
  F6 (i)/(ii) cap violations; F6 (iv) outside_band filter
  violation.
- `ApiCatchPatternEndToEndTest` (~3): Adjustment B mirror of
  Contracts 3-6.
- `DiagnosticEmitBestEffortTest` (~2): both helpers succeed
  when emit_diagnostic_fn raises.

Expected total: 15-18 tests in consumer_gate file + 2 in
invariant file = ~17-20 new tests.

---

## 7. Open flags for Nick's review

15 numbered flags (F0-F14) with spec recommendations matching
the PSL pre-stated leans.

### F0 — Single module + multi-sub-contracts

**(Recommended) (a) Single Contract 7 module with 6
sub-contracts inside.** Same F0 pattern as Contract 6. Don't
fragment.

**(b) 6 separate modules.** Rejected — fragments the boundary;
breaks the single-import discipline established by Contracts
1-6.

### F1 — Compose Contract 6 GetBandsViewContract for mirror.bands

**(Recommended) (a) Re-import from
industry_baseline_resolved_contract.py.** Confirmed by trace
T4 via get_bands at mirror.py:218-225. No redefinition.

**(b) Type as opaque `Dict[Literal[5 SECTIONS], Dict[str, Any]]`.**
Rejected — drops the Contract 6 typed sub-shape; loses upstream
gate's enforcement value.

### F2 — Defer Contract 1 per-section composition

**(Recommended) (a) DEFER to R-residual.** First cut: type
plan_state as `Dict[Literal[5 SECTIONS], Dict[str, Any]]`. The
per-section payload is a post-revise snapshot, not 1:1 with
Contract 1's full shape; warrants its own sub-contract work
when a downstream consumer warrants it.

**(b) Type each section as a Contract 1 sub-shape composition
in Commit 1a.** Rejected for scope — would push Commit 1a past
700-LOC cap; tighter coupling between Contracts 1 and 7
without immediate enforcement value.

### F3 — recent_decisions phantom-write disposition

**(Recommended) (a) `Optional[List[RecentDecisionContract]] = None`.**
Matches production reality per v2 §D-2 (setter exists; no
reader). Future R-residual to drop the setter + field if
confirmed truly dead.

**(b) Required `List[...] = Field(default_factory=list)`.**
Rejected — would force every Mirror serialization to carry an
empty list, which is fine but doesn't match the "phantom-write"
honesty of Optional.

### F4 — sequence_position + budget phantom-required disposition

**(Recommended) (a) `Optional[Dict[str, Any]] = None`** for
both. Matches production per v2 §D-3 (no caller passes either).
R-residual cleanup to drop the build_mirror kwargs.

**(b) Required `Dict[str, Any] = Field(default_factory=dict)`.**
Rejected — same reasoning as F3.

### F5 — Bug 2 alias-sync @model_validator on MirrorContract

**(Recommended) (a) ADD `plan_state_alias_sync` validator** per
§4.1. The Bug 2 fix at mirror.py:163-180 IS the contract; the
validator surfaces alias-sync regressions as ContractViolation.

Pre-condition handling per §4.1: if NONE of the 3 alias keys is
present (pre-commit Mirror state), no constraint; if ANY are
present, all-present-keys must hold the same payload.

**(b) Skip.** Rejected — defeats the purpose of typing Bug 2's
fix.

### F6 — Bug 3 four @model_validators on ValidationStateProjectionContract

**(Recommended) (a) ADD all 4** per §4.2:
- (i) failing_check_names cap at 12
- (ii) failing_lever_margins cap at 12
- (iii) truncation flag consistency
- (iv) outside_band filter

Each surfaces a producer-side regression. The cap value 12
lifts from `_VALIDATION_STATE_RENDER_CAP` at mirror.py:34.

**(b) Encode caps as `Field(max_length=12)` only.** Field-level
caps cover (i) and (ii). The cross-field invariants (iii) and
(iv) require `@model_validator` because they reference multiple
fields / per-entry attributes. Rejected — partial coverage
loses iii + iv.

### F7 — strictness Literal pinning

**(Recommended) (a) Literal["mini_finmo", "full_acceptance_gate"]**
per evaluation_types.py:110.

### F8 — section Literal pinning (5 SECTIONS)

**(Recommended) (a) Literal["stage_ramp", "drivers", "payroll",
"capex_rd", "balance_sheet"]** per evaluation_types.py:39.
Used in MirrorContract.plan_state keys + MirrorContract.bands
keys + LeverMarginEntryContract.section field.

### F9 — Producer-side gate at build_mirror return only

**(Recommended) (a) SHIP at build_mirror return.** Refresh-
point gates SKIPPED — gating best-effort observability writes
would change the try/except semantic in undesirable ways. The
@model_validators on Bug 2/3 invariants fire at consumer-side
reads (via to_dict + Shape D helper), so structural violations
still surface; just not at every refresh tick.

**(b) Add refresh-point gates inside set_plan_state_section +
set_validation_state.** Rejected — would either abort the
cascade on observability failures or be swallowed (losing
enforcement).

### F10 — Per-shape consumer-side gates

**(Recommended) (a) 2 gates per §5.2:** Shape A inside
Mirror.to_dict() + Shape D inside
responder.render_mirror_for_proposal at responder.py:269.
Shape A's `bands` field is already gated upstream by Contract
6's Shape C gate.

**(b) Single gate inside to_dict() only.** Rejected — many
consumers read validation_state directly (responder.py:269)
without serializing the full Mirror; would miss those reads.

### F11 — Adjustment B carry-over

**(Recommended) (a) Re-use Contracts 3-6 pattern verbatim.**
intake_consult.py:7377 generic Exception catch propagates
ContractViolation as structured 500 with str(exc) carrying
`AMALGAMATED_SESSION_STAGE_LABEL`. Test class mirrors Contracts
3-6 `ApiCatchPatternEndToEndTest`.

### F12 — Diagnostic-emission invariant test + PhaseCode

**(Recommended) (a) SINGLE PhaseCode `AMALGAMATED_SESSION_CONTRACT`**
covering both helpers; `diagnostic_data['shape']` = 'mirror' /
'validation_state' distinguishes. Lockstep PhaseCode count
19 → 20.

### F13 — extra policy

**(Recommended) (a) `extra="forbid"` on top-level
MirrorContract; `extra="ignore"` on all sub-contracts**
(RecentDecisionContract, ValidationStateProjectionContract,
LeverMarginEntryContract).

### F14 — Skip Commit 2 adapter + asdict conversion pattern

**(Recommended) (a) SKIP Commit 2.** Use `dataclasses.asdict()`
at gate sites for the dataclass-to-dict conversion. Implementation
sequence: 1a → 1b → 1c → 3 (4 commits, no Commit 2).

**The Mirror is the FIRST DATACLASS-SHAPED boundary** in the
P3.40 series — explicitly document the asdict() conversion in
§5.4 + the Commit 1a module docstring. If 1a implementation
discovers a complication (e.g., a future Mirror field holds a
non-dataclass object asdict can't serialize), add explicit
`MirrorContract.from_mirror(mirror)` classmethod and treat as
Commit 2 work. **For first cut: asdict suffices.**

**(b) Ship explicit `MirrorContract.from_mirror(mirror)` adapter
in Commit 2.** Rejected for first cut — premature given
`dataclasses.asdict()` handles the conversion (incl. nested
RecentDecision) automatically. R-residual upgrade path.

---

## 8. Known residual cleanups (out of scope for Contract 7)

- **R8.** Per-section `PlanStateSectionContract` typing (F2
  deferral). Each of the 5 SECTIONS has a section-specific
  revise_* tool that commits a specific payload shape. Typing
  these as Contract 1 sub-shape compositions warrants its own
  trace+spec work per section. R-residual when a downstream
  consumer warrants the tightening.

- **R9.** ~~`business_facts` typing — currently opaque
  `Dict[str, Any]`. Once Contract 5b/c/d sub-contracts land,
  inverse retrofit so `MirrorContract.business_facts` composes
  those.~~ **ASSESSED in P3.40 Contract Layer Cleanup Commit
  2; NO CODE CHANGE WARRANTED.** Production
  Mirror.business_facts is built at runner.py:261-271 from
  FLAT DRAFT-ROW COLUMNS (`name`, `business_name`, `address`,
  `start_date`, `address_street/city/state/zip/country`) and
  forwarded verbatim to `build_mirror(...,
  business_facts=amalgamated_business_facts, ...)` at
  runner.py:1825-1830. The dict contains ZERO content from
  the 5b/5c/5d typed JSONs (operating_model_json /
  target_market_json / people_json). The R9 hypothesis
  ("compose 5b/c/d when they land") doesn't match production
  reality — the field is genuinely heterogeneous draft-column
  data, not intake-JSON content. `MirrorContract.business_
  facts` stays as `Dict[str, Any]`; the alternative (typing
  as a sub-shape composing 5b/c/d) would type fields
  production doesn't populate. Contract 5's consumer-side
  gate at runner.py:189 provides the structural assurance
  for the 3 typed sub-contracts; that enforcement doesn't
  transitively apply to Mirror.business_facts because the
  two surfaces are disjoint. R9 status: ASSESSED + RESOLVED
  via assessment (no code change is the correct outcome
  per the directive's "do NOT force composition where it
  doesn't structurally make sense" guideline).

- **R10.** ~~Drop `mirror.recent_decisions` setter + field. Per
  v2 §D-2: phantom-write.~~ **RESOLVED in P3.40 Contract Layer
  Cleanup Commit 3/6.** Reader/writer audit confirmed
  `record_decision()` has ZERO production callers and
  `recent_decisions` had only serialization (Mirror.to_dict)
  + telemetry (enforcement.py:885 length count) + 1 test
  reader. No GPT/responder consumer. Removed: RecentDecision
  dataclass, Mirror.recent_decisions field,
  Mirror.record_decision() method, DEFAULT_RECENT_DECISIONS_CAP
  constant, Mirror.recent_decisions_cap config field,
  RecentDecisionContract class, the recent_decisions field on
  MirrorContract, the recent_decisions_count diagnostic line
  in enforcement.py, the RecentDecisionContract export,
  valid_recent_decision_dict fixture builder, and
  RecentDecisionContractTest test class. Mirror.to_dict()
  output no longer carries the "recent_decisions" key.

- **R11.** ~~Drop `mirror.sequence_position` + `mirror.budget`
  fields. Per v2 §D-3: phantom-required.~~ **RESOLVED in
  P3.40 Contract Layer Cleanup Commit 3/6.** Reader/writer
  audit confirmed ZERO callers pass either to build_mirror;
  both always defaulted to empty dict; only "reader" was
  Mirror.to_dict() serialization with no downstream consumer.
  Removed: both fields from Mirror dataclass, both kwargs
  from build_mirror() signature, both keys from Mirror.to_dict
  output, both fields from MirrorContract, and the
  corresponding normalization shims in mirror.py producer-side
  and consumer-side gates.

- **R12.** F6 invariant (iii) full bidirectional check —
  currently §4.2 only enforces one half (truncated flag must
  be True when list ≥ cap). The full bidirectional check
  requires upstream EvaluatePlanResult context. Worth adding
  when consumers carry the upstream context.

- **R13.** Refresh-point gates (F9 SKIPPED). If a future
  diagnostic shows refresh-time violations matter, add gates
  inside set_plan_state_section / set_validation_state with
  fail-loud semantics (would require restructuring the
  surrounding try/except).

- **R14.** `MirrorContract.from_mirror(mirror)` explicit adapter
  classmethod (F14 (b) deferred). Add if `dataclasses.asdict()`
  conversion proves insufficient for a future Mirror field.

- **R15.** `evaluate_plan._margin_distance_from_bands` per v1
  §E-2 — `mirror.bands` loaded once but evaluate_plan re-fetches.
  Architectural cleanup; not directly Contract 7 scope but
  surfaces the inconsistency.

- **R16.** Operating-model levers no revise_* tool per v2 §E-3.
  Architectural gap; not Contract 7 scope.

- **R17.** WC scalar patch shape formalization in
  `CascadeLever.direction` per v2 §E-4. Partial (docstring
  exists); formal type tightening pending.

- **R18.** End-to-end AmalgamatedSessionContract round-trip
  test — exercises Mirror construction through refresh through
  serialization. Useful for full-pipeline regression detection
  but expensive to set up; R-residual.

---

## 9. Workflow

Same as Contracts 1-6: trace doc + spec doc each ship as
single commits, held for Nick review. After spec approval, the
4-commit implementation series (1a → 1b → 1c → 3) lands per §6
with push + email per commit. Per-commit LOC cap: 700.

**Pre-1a re-verification per Contracts 4-6 discipline.** Before
Commit 1a lands, re-grep `_VALIDATION_STATE_RENDER_CAP` at
mirror.py:34, the alias triplet at mirror.py:175-180, the
SECTIONS tuple at evaluation_types.py:39, and the strictness
docstring at evaluation_types.py:110 to confirm spec values
match production verbatim. Same discipline Contract 4 + 5 + 6
applied; same discipline catches drift.

If during Commit 1a I find anything else that diverges from
production, I'll flag back the same way Contracts 1-6 did —
no silent adjustment.

After Commit 3 lands and the full P3.40 contracts suite goes
green, **Contract 7 is end-to-end and the entire 7-boundary
P3.40 contract layer is in place.**

Expected full-suite total after Commit 3:
477 (today) + ~32 (1b) + ~22 (1c) + ~19 (3) = ~550 passed.

Next directions (post-Contract-7):
- Contract 5b/5c/5d (OpenAI-schema sub-contract follow-ups
  per Contract 5 F0 sub-flag c DEFER).
- R-residual sub-contract typing waves (R8-R18 above + similar
  R-residuals on Contracts 1-6).
- Architectural fixes deferred during the contract-typing wave
  (headcount derivation Fix #2 + steady-state viability Fix #1
  per the original P3.40 directive).
