# P3.31 — Handler field ownership audit

**Status:** Read-only investigation. No code changes.
**Goal:** Identify every (handler, field) pair where a handler can
write a field it does not canonically own. Propose tightening of
each handler's writable lever catalog.

**Headline:** The leak landscape is **narrow and concentrated on
one field**: `expenses::Payroll`. Two writers besides Handler C
can hit it:

- **Leak A** — GPT exhaustion handler's hardcoded
  `GPT_AUTHORED_LEVER_IDS` includes `"expenses::Payroll"`
  ([handler.py:54](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L54)).
- **Leak B** — The deterministic restoration-loop / target-solver
  pre-handler writes whatever lever_id appears in a failing
  realism row's `primary_levers`. Multiple realism rows list
  `expenses::Payroll` ([lookup.py:544,605,1005,1116](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L544))
  → solver writes to it via `apply_exact_lever_updates_to_model_input`.

Every other handler has clean authority on its named domain
(stage_ramp_contract.*, funding levers, payroll_headcount.*).
Recommendation: tighten catalogs in two targeted commits, ~120
LOC total. **No governor needed**; the leak surface is too small
to justify a centralized enforcement layer.

---

## Q1 — Handler writable lever catalogs

### Handler GPT-Exhaustion (Restoration / Site 1)

**Module:** [post_intake_gpt_exhaustion_handler/handler.py](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py)
**Catalog:** Two static tuples at module scope.

```
GPT_AUTHORED_LEVER_IDS  (handler.py:50-59)         # 8 PNL levers
GPT_AUTHORED_WORKING_CAPITAL_LEVER_IDS  (105-111)  # 5 WC levers
```

| # | Lever ID                                                | Catalog | Notes |
| - | ------------------------------------------------------- | ------- | ----- |
| 1 | revenue::Unit Price                                     | PNL     | OWNED |
| 2 | revenue::Capacity                                       | PNL     | OWNED |
| 3 | revenue::Utilization                                    | PNL     | OWNED |
| 4 | **expenses::Payroll**                                   | PNL     | **LEAK — Handler C is canonical** |
| 5 | expenses::Cost of Goods Sold                            | PNL     | OWNED |
| 6 | expenses::Marketing                                     | PNL     | OWNED |
| 7 | expenses::General & Administrative                      | PNL     | OWNED |
| 8 | expenses::Research & Development                        | PNL     | OWNED |
| 9 | balance_sheet::Accounts Receivable Days                 | WC      | OWNED |
| 10 | balance_sheet::Accounts Payable Days                    | WC      | OWNED |
| 11 | balance_sheet::Inventory Days                           | WC      | OWNED |
| 12 | balance_sheet::Deferred Revenue (% of Revenue)          | WC      | OWNED |
| 13 | balance_sheet::Prepaid Expenses (% of Revenue)          | WC      | OWNED |

Doctrine §6 line 332 names this handler's authority as "12 PNL
levers + 5 WC levers". Code reality is 8 PNL + 5 WC = 13. **The
doctrine count is stale.** No functional gap; just doc-drift.

### Funding handler

**Module:** [post_intake_funding_handler/handler.py](../../python/client_intake_and_finmo/post_intake_funding_handler/handler.py)
**Catalog:** [handler.py:267-273](../../python/client_intake_and_finmo/post_intake_funding_handler/handler.py#L267-L273)

```
FUNDING_LEVER_AUTHORITY = (
  "schedules::Debt Issuance (New Borrowing)",
  "schedules::Debt Repayment (Scheduled)",
  "balance_sheet::Owner's Capital",
  "balance_sheet::Other Equity",
  "balance_sheet::Distributions",
)
```

Validator-enforced membership at [handler.py:189-192](../../python/client_intake_and_finmo/post_intake_funding_handler/handler.py#L189-L192).
All 5 levers are funding-side; no operating-side overlap.
**No leaks.**

### Stage-ramp handler

**Module:** [post_intake_stage_ramp_handler/handler.py](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py)
**Catalog:** `STAGE_RAMP_FIELD_AUTHORITY` at [handler.py:204-221](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L204-L221).

16 fields, all of form `stage_ramp_contract.<x>`:
- stage_family
- utilization_high_watermark
- quarter_ramp_grid[].{rev_target, rev_max, rev_spike,
  rev_spike_max, max_util, cogs_target, cogs_max, marketing_max,
  rd_max, ga_max, lease_max, ni_floor, posture}
- rationale

Authority is scoped to the contract JSON; no model_input writes.
**No leaks.**

### Handler C — Payroll headcount schedule

**Module:** [post_intake_headcount/schedule.py](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py)
**Entry point:** `estimate_payroll_headcount_schedule_with_gpt`
([schedule.py:2180](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2180))
**Pattern:** GPT-as-authoring-source (doctrine §6 GPT-as-authoring-source table).

**Direct authority:** writes `payroll_headcount.{rows,
quarter_totals, assumptions}` (the dedicated SQL column).

**Apply chain authority:**
`apply_payroll_headcount_payload_to_model_input` at
[schedule.py:2809-2895](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2809-L2895)
propagates `payroll_headcount.quarter_totals[q].payroll` into
`model_input.sections.expenses["Payroll"].values[q+1]` and stamps
the row with `controller_write = False` +
`derived_driver = "payroll_headcount"`
([schedule.py:2896-2897](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2896-L2897)).

`PAYROLL_HEADCOUNT_LEVER_ID = "expenses::Payroll"` at
[schedule.py:44](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L44)
— the bridge identifier. The
`controller_write = False` flag is the **structural signal** that
this row is a derived view, not an independently writable lever.

**No leaks** from Handler C itself.

### Cash strategy proposer (Python-first deterministic)

**Module:** [post_intake_cash/runner.py](../../python/client_intake_and_finmo/post_intake_cash/runner.py)
**Catalog:** `_CASH_STRATEGY_ALLOWED_LEVER_IDS` at
[runner.py:53-64](../../python/client_intake_and_finmo/post_intake_cash/runner.py#L53-L64)
— resolved from SQL `post_intake_driver_target_lever_ids_for_cash_roles`
for roles `{distribution, debt_paydown, debt_raise, equity_raise,
owner_equity_raise, external_equity_raise}`.

Catalog overlaps fully with FUNDING_LEVER_AUTHORITY by design:
the cash strategy proposer is the Python-first deterministic; the
funding handler is the GPT handler-on-failure for the same lever
set. Doctrine §1 pattern. **SHARED authority is intentional and
correctly scoped.**

### Restoration loop / target-solver

**Module:** [post_intake_target_solver/restoration_loop.py](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py)
+ [post_intake_target_solver/target_solver.py](../../python/client_intake_and_finmo/post_intake_target_solver/target_solver.py)
**Catalog:** dynamic. For each target metric (ebitda_margin,
current_assets_minus_cash, current_liabilities_to_revenue), the
solver pulls `primary_levers` from the realism config row
([restoration_loop.py:649-651](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L649-L651)) and writes each via the joint-fit
algebra.

**Hard exclusion:** `_CASH_PASS_OWNED_LEVER_IDS` at
[target_solver.py:66-73](../../python/client_intake_and_finmo/post_intake_target_solver/target_solver.py#L66-L73):

```
_CASH_PASS_OWNED_LEVER_IDS = frozenset({
  "balance_sheet::Owner's Capital",
  "balance_sheet::Other Equity",
  "balance_sheet::Distributions",
  "balance_sheet::Short Term Debt (% of LTD)",
  "schedules::Debt Issuance (New Borrowing)",
  "schedules::Debt Repayment (Scheduled)",
})
```

— never written by the solver
([target_solver.py:367](../../python/client_intake_and_finmo/post_intake_target_solver/target_solver.py#L367),
[665-672](../../python/client_intake_and_finmo/post_intake_target_solver/target_solver.py#L665-L672)).

**Other lever IDs** are written based on whatever the realism
config primary_levers list contains. The realism config lists
`expenses::Payroll` in multiple primary_levers entries
([lookup.py:544,605,1005,1116](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L544);
secondary_levers at 1033,1077). **LEAK B**: the solver can write
to expenses::Payroll, bypassing Handler C's authority.

### Convergence runner (GPT-as-authoring-source)

**Module:** [post_intake_convergence/runtime.py](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py)
+ [post_intake_convergence/runner.py](../../python/client_intake_and_finmo/post_intake_convergence/runner.py)
**Catalog:** none — the convergence runner accepts whatever
levers GPT proposes within `controller_write_levers` (the
model_input field that's filtered by
`_extract_controller_lever_catalog` to **exclude expenses::Payroll**
at [post_intake_contracts/runner.py:5498,5509](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L5498)).

This means the convergence runner is already structurally fenced
from Payroll via the catalog-extraction filter. **No leak.**

### Path engine (writer-of-record for handler exhaustion output)

**Module:** [post_intake_adaptive_planning/path_engine.py](../../python/client_intake_and_finmo/post_intake_adaptive_planning/path_engine.py)
**Catalog:** none — iterates `model_input.sections[*]` rows and
emits an `exact_update` for every lever with a writable shape
([path_engine.py:700-770](../../python/client_intake_and_finmo/post_intake_adaptive_planning/path_engine.py#L700-L770)).

It writes whatever the handler set in `model_input.sections`.
Path engine is the **mechanical apply pass**, not an author. If
the GPT exhaustion handler stamps the Payroll row, path engine
writes it. **Inherits Leak A** from the handler's catalog.

### Numeric solver (numeric_solver.py)

**Module:** [client_intake_and_finmo/numeric_solver.py](../../python/client_intake_and_finmo/numeric_solver.py)
**Catalog:** `allowed_levers` parameter at
[numeric_solver.py:321](../../python/client_intake_and_finmo/numeric_solver.py#L321)
— caller supplies the lever list.

The numeric solver is a deterministic optimizer invoked from
multiple sites; each caller defines its own `allowed_levers`.
Audit punts to the callers (convergence runner + restoration
loop + inner_joint_fit_adapter). No standalone catalog.

---

## Q2 — Canonical ownership per field group

| Field group | Canonical owner | Other writers (today) | Status |
| ----------- | --------------- | ---------------------- | ------ |
| `payroll_headcount.*` (rows + qts + assumptions) | Handler C | None | OK |
| `model_input.expenses["Payroll"].values` | Handler C (derived via apply chain) | GPT exhaustion handler (Leak A); restoration target-solver (Leak B) | **LEAK** |
| `model_input.sections.revenue.*` (Unit Price / Capacity / Utilization rows) | GPT exhaustion handler (handler-on-failure for ratios/path); also intake-time author for initial values | restoration target-solver writes via primary_levers | OK (handler-on-failure pattern) |
| `model_input.expenses["Cost of Goods Sold"|"Marketing"|"G&A"|"R&D"]` | GPT exhaustion handler | restoration target-solver | OK (handler-on-failure pattern) |
| `model_input.expenses["Lease"]` | intake input (no handler-on-failure) | none | OK |
| `model_input.expenses["Depreciation"]` / `["Interest Rate"]` / `["Interest Expense"]` | intake input + Debt/CapEx schedule re-derivation | none | OK |
| `model_input.balance_sheet["Accounts Receivable Days"|"Inventory Days"|"Accounts Payable Days"|"Prepaid Expenses (%)"|"Deferred Revenue (%)"]` | GPT exhaustion handler (WC scope) | restoration target-solver | OK (handler-on-failure pattern) |
| `model_input.balance_sheet["Owner's Capital"|"Other Equity"|"Distributions"]` | Funding handler | Cash strategy proposer (Python-first) | OK (Python-first + handler-on-failure pattern; both intentional) |
| `model_input.balance_sheet["Short Term Debt (% of LTD)"]` | Cash strategy proposer | Funding handler | OK (same pattern) |
| `model_input.schedules["Debt Issuance"|"Debt Repayment"]` | Funding handler | Cash strategy proposer | OK |
| `stage_ramp_contract.*` (all fields) | Stage-ramp handler | none | OK |
| `cash_strategy_mode` (planning_run state) | Funding handler / cash strategy | none | OK |

**Conclusion:** Only `expenses::Payroll` has unauthorized
writers. Every other field is either single-writer or has
intentional Python-first/handler-on-failure shared authority.

---

## Q3 — Cross-ownership leak matrix

| (handler, field) | Classification | Recommendation |
| ---------------- | -------------- | -------------- |
| **GPT exhaustion handler → `expenses::Payroll`** | **LEAK A** | Remove from `GPT_AUTHORED_LEVER_IDS` ([handler.py:54](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L54)). Route payroll repair to Handler C via P3.26-style feasibility-failure mechanism. |
| **Restoration target-solver → `expenses::Payroll`** | **LEAK B** | Add `expenses::Payroll` to the solver's exclusion set (mirror `_CASH_PASS_OWNED_LEVER_IDS` shape). Drop from `primary_levers` in realism config rows that target payroll-driven metrics (or annotate as "handler-routed only", e.g. gate_kind="route_to_handler_c"). |
| GPT exhaustion handler → revenue::*, expenses::COGS/Marketing/G&A/R&D, balance_sheet::AR/AP/Inventory Days, Deferred Rev/Prepaid % | OWNED | n/a |
| Funding handler → schedules::Debt Issuance/Repayment, balance_sheet::Owner's Capital/Other Equity/Distributions | OWNED | n/a |
| Cash strategy proposer → same as funding handler | SHARED (Python-first pattern; funding handler is the handler-on-failure for same set) | Keep; documented in doctrine §1. |
| Stage-ramp handler → stage_ramp_contract.* | OWNED | n/a |
| Restoration target-solver → revenue::*, other expense ratios, balance_sheet WC days/% | SHARED (handler-on-failure pattern; restoration is Python-first, exhaustion handler is handler-on-failure for same set when restoration exhausts) | Keep. |
| Path engine → any lever the handler stamps | INHERITS from upstream handler | Inherits Leak A; closing A closes this surface. |
| Convergence runner → whatever GPT proposes within `controller_write_levers` | OWNED (filtered by `_extract_controller_lever_catalog` to exclude Payroll) | Already fenced. |

**Two leaks total**, both on the same field (`expenses::Payroll`),
both rooted in handler/solver authority that bypasses Handler C.

---

## Q4 — Routing mechanism audit

### Current routing pattern (P3.26 Commit 2)

When the payroll feasibility validator fails
(`payroll_revenue_economic_feasibility_failed` /
`payroll_stage_profitability_feasibility_failed`), the orchestrator
catches the FailFastError and routes back to Handler C via
[feasibility_repair.py:107](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L107)
`route_payroll_feasibility_to_handler_c`. The failure context
becomes Handler C's `previous_contract_failure` seed. Handler C
re-authors payroll, the apply chain propagates back to model_input
+ FINMO, and the validator reruns.

This is the **canonical routing pattern**: validator failure →
fail-fast → orchestrator catches → handler re-author with
failure-context seed → apply chain → re-validate.

### Gaps relative to the leak landscape

- **Leak A (GPT exhaustion handler writing Payroll directly):**
  the handler is invoked when restoration exhausts. Its
  `GPT_AUTHORED_LEVER_IDS` includes Payroll, so when GPT proposes
  payroll anchors the path engine writes them — no routing through
  Handler C happens. **No existing mechanism prevents this.**
  Closing the leak requires removing Payroll from the catalog +
  ensuring that when restoration determines payroll-related
  metrics are failing, the orchestrator routes to Handler C
  *instead of* invoking the exhaustion handler with Payroll
  authority. The P3.26 Commit 2 mechanism is already the right
  shape; it just needs to be invoked *before* the exhaustion
  handler runs when payroll is the bottleneck.

- **Leak B (restoration target-solver writing Payroll):** the
  solver runs deterministically before any handler. If a realism
  primary_lever list says `expenses::Payroll`, the solver writes
  it. **No routing mechanism exists for this case** — the solver
  is not designed to escalate; it just clamps drivers to bounds
  and reports BOUND_PINNED. The fix is to exclude payroll from
  the solver's lever set (move to `_CASH_PASS_OWNED_LEVER_IDS`
  analog) so the solver leaves payroll alone; Handler C's
  intake-time output stands until a feasibility-repair route
  fires.

### Routing-mechanism completeness check

The P3.26 Commit 2 pattern is **already the canonical routing
shape**. Two more "trigger → route" wirings needed:

1. Restoration loop: when `failing_metrics` contains any metric
   whose primary_levers include `expenses::Payroll`, route to
   Handler C via `route_payroll_feasibility_to_handler_c` instead
   of letting the solver tune Payroll directly. This becomes the
   restoration-time analog of the post-grid feasibility route.
2. GPT exhaustion handler: same shape. If the handler's authored
   anchors include any payroll-touching value, route to Handler C
   first; the exhaustion handler operates only on its 12 truly-
   owned levers.

Both are doable with the existing routing primitive; no new
mechanism needed.

---

## Q5 — Remediation sequence + LOC estimates

| Fix | LOC | Risk | Sequence |
| --- | --- | ---- | -------- |
| **(F1) Remove `expenses::Payroll` from `GPT_AUTHORED_LEVER_IDS`** at [handler.py:54](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L54). Also remove from `_DRIVER_KEY_TO_LEVER_ID` ([handler.py:66](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L66)) and the mirroring set in restoration_loop.py:152 (`_GPT_AUTHORED_PNL_LEVER_IDS`). | ~10 | Low | **1st** |
| **(F2) Mirror tests + the prompt template** that lists "payroll_dollars_per_quarter" so GPT no longer proposes it. Search and remove from `prompts.py` + tool-schema. | ~30 | Low | **1st** (same commit as F1) |
| **(F3) Add `expenses::Payroll` to the restoration target-solver exclusion frozenset** (mirror of `_CASH_PASS_OWNED_LEVER_IDS` shape; possibly create `_HANDLER_C_OWNED_LEVER_IDS = frozenset({"expenses::Payroll"})` and union with cash-pass set). | ~20 | Low | **2nd** |
| **(F4) Annotate realism primary_levers entries** that list `expenses::Payroll` to use a new `gate_kind="route_to_handler_c"` flag (or remove and rely on solver exclusion in F3 alone). | ~30 | Low | **2nd** (same commit as F3) |
| **(F5) Wire restoration-loop exhaustion to route_payroll_feasibility_to_handler_c** when failing_metrics list includes a metric whose primary_levers include payroll. Mirror P3.26 Commit 2's Site A wiring. | ~50 | Med | **3rd** (next commit, if F1+F3 leave residual cases) |
| **(F6) Doctrine §6 line 332 update**: change "12 PNL levers" to "8 PNL levers" to match code reality (or document why doctrine count differs). | ~2 | None | **Trivial, any time** |

**Total estimated scope: ~140 LOC** across 2-3 commits.

### Sequencing rationale

1. **F1 + F2 first** (~40 LOC, single commit). Closes Leak A.
   This is the active vector from P3.25 CareFirst. After this
   commit, no GPT-author path can write Payroll directly. Tests
   verify the catalog no longer includes Payroll and the prompt
   no longer mentions `payroll_dollars_per_quarter`.
2. **F3 + F4 second** (~50 LOC, single commit). Closes Leak B.
   Restoration solver no longer tunes Payroll directly. Realism
   rows that previously had Payroll in primary_levers are either
   annotated route_to_handler_c or rely on the solver exclusion
   doing the same.
3. **F5 third (conditional)** (~50 LOC, single commit). Only
   needed if F1-F4 leave a class of cases where payroll feasibility
   fails but no existing route triggers Handler C. The P3.26
   Commit 2 Site A route already covers post-grid feasibility
   failures; F5 adds a restoration-exhaustion-time route. Worth
   running F1-F4 first and observing the sweep before deciding.

### Recommendation: NO governor

The leak landscape is two writers on one field. A centralized
governor (catalog-enforcement layer that intercepts every
model_input write and checks authority) would be **disproportionate**
to the surface area. Per-handler catalog tightening + targeted
exclusion frozenset is the cleaner shape.

If a future audit surfaces 5+ leak fields across 3+ handlers, the
governor case grows; today, two leaks on one field do not
justify it.

---

## Quick reference — what changes per fix

**F1 (Leak A closure):**
```
# handler.py:50
GPT_AUTHORED_LEVER_IDS: Tuple[str, ...] = (
   "revenue::Unit Price",
   "revenue::Capacity",
   "revenue::Utilization",
-  "expenses::Payroll",      # REMOVED — Handler C is canonical
   "expenses::Cost of Goods Sold",
   ...
)

# handler.py:66
_DRIVER_KEY_TO_LEVER_ID = {
   ...
-  "payroll_dollars_per_quarter": "expenses::Payroll",  # REMOVED
   "cogs_percent_of_revenue": "expenses::Cost of Goods Sold",
   ...
}
```

Mirror at [restoration_loop.py:152](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L152).

**F3 (Leak B closure):**
```
# target_solver.py:66
_CASH_PASS_OWNED_LEVER_IDS = frozenset({...})
+ _HANDLER_C_OWNED_LEVER_IDS = frozenset({"expenses::Payroll"})
+ _ALL_HANDLER_OWNED_LEVER_IDS = (
+   _CASH_PASS_OWNED_LEVER_IDS | _HANDLER_C_OWNED_LEVER_IDS
+ )
```

Update [target_solver.py:367](../../python/client_intake_and_finmo/post_intake_target_solver/target_solver.py#L367)
and [665-672](../../python/client_intake_and_finmo/post_intake_target_solver/target_solver.py#L665-L672)
to use `_ALL_HANDLER_OWNED_LEVER_IDS`.

---

User direction required for sequencing F1-F5.
