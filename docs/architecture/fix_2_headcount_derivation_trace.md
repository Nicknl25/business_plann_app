# Fix #2 — Headcount Derivation: TRACE (pre-spec)

**Status:** TRACE-ONLY. No code changes, no mapping-table edits, no fixes. This is the
trace-before-spec step for Fix #2 (make headcount a DERIVED value instead of a primary
lever). Every claim is grounded in `file:line`. Nick decides the derived binding in the
spec phase; this doc only surfaces the options the system already has the pieces for.

**Scope:** Manager-side deterministic (Python) post-intake logic only. Intake untouched.
Payroll *authoring* is noted as a downstream consumer but its redesign is deferred.

---

## TL;DR — the headcount reality is not what "primary lever" implies

1. **There is no standalone headcount / FTE lever row in the mapping table.** The only
   seeded cost lever is `expenses::Payroll`, and it is `control_owner = "python_derived"`,
   `targeting_allowed = 0`, `diagnostic_only = 1` — i.e. Payroll is *derived*, never
   targeted. ([post_intake_mapping.py:3529-3561](../../python/client_intake_and_finmo/post_intake_mapping.py#L3529-L3561))

2. **Headcount (FTE) is authored, today, by the GPT `payroll_headcount_schedule` contract**
   — the `payroll_headcount_grid` of `starting_fte` / `ending_fte` per OEWS title per
   quarter. ([post_intake_mapping.py:2048-2054](../../python/client_intake_and_finmo/post_intake_mapping.py#L2048-L2054),
   [post_intake_mapping.py:2121-2134](../../python/client_intake_and_finmo/post_intake_mapping.py#L2121-L2134))
   This is the **first entanglement finding**: in the current round-1 code, headcount is a
   *GPT-authored primary input*, not a Python dialed-in lever. The Fix #2 framing
   ("headcount as a primary lever in the Manager-side Python logic") does not match the code
   — Python *consumes* an authored FTE grid; it does not dial FTE itself.

3. **The causal direction today is `headcount → capacity → (revenue sanity check)`.**
   Python derives *supported Capacity* FROM average FTE
   (`supported_capacity = total_average_fte × capacity_units_per_supporting_fte`), and
   revenue is used only as a *sanity bound*, never as a driver of FTE. This is encoded
   explicitly as policy doctrine in `payroll_trend_rules_json`:
   `capacity_primary: True`, `use_revenue_as_sanity_not_driver: True`.
   ([lookup.py:82-88](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L82-L88))
   **Fix #2 inverts this doctrine** — it makes revenue/productivity the driver and headcount
   the output.

4. **The upstream lever for the inversion already exists and is named.** The headcount
   "economic basis" is a real, defaulted DB column: `headcount_economic_basis =
   "capacity_units_per_supporting_fte"`. ([lookup.py:36](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L36),
   [lookup.py:264](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L264))
   The system is architected to make headcount economics swappable through this basis field,
   but only one basis ("capacity-per-FTE") is implemented.

---

## Step 1 — Headcount in the mapping table

### 1a. No standalone headcount/FTE/productivity lever exists

A full scan of the mapping seed (`_ensure_mapping_lookup_table`, the INSERT block at
[post_intake_mapping.py:3462-3561](../../python/client_intake_and_finmo/post_intake_mapping.py#L3462-L3561))
finds **no** lever row whose `value_kind = count`, and **no** lever named headcount, FTE,
productivity, or revenue-per-head. Headcount only appears (a) embedded in the Payroll lever
as its causal source, and (b) as fields of the GPT `payroll_headcount_grid` contract (Step 5).

### 1b. The one cost lever — `expenses::Payroll`

Full seeded tuple, [post_intake_mapping.py:3529-3561](../../python/client_intake_and_finmo/post_intake_mapping.py#L3529-L3561):

| Column | Value |
|---|---|
| `lever_id` | `expenses::Payroll` |
| `driver_category` | `payroll_schedule` |
| `target_driver` | `payroll` |
| `model_input_field` | `model_input_json.sections.expenses[Payroll]` |
| `financial_model_field` | `finmo_json.quarter_rows[*].payroll` |
| `impact_type` | `derived` |
| `control_owner` | **`python_derived`** |
| `value_kind` | `quarter_currency` |
| `input_semantics` | `quarter_currency` |
| `driver_bundle` | `payroll_headcount_schedule` |
| `targeting_allowed` | **`0` (false)** |
| `diagnostic_only` | **`1` (true)** |
| `tolerance_allowed` | `0` |
| `seed_formula_key` | `python_derived_schedule` |
| `finmo_formula_key` | `finmo_python_derived_schedule` |
| `validation_formula_key` | `schedule_marker_validation` |
| `business_applicability_key` | `revenue_positive` |
| `forecast_presence_rule_key` | `schedule_reconciles_when_applicable` |
| `zero_allowed_reason_key` | `payroll_not_applicable` |
| `allow_zero` | `0` |
| `notes` | "Payroll is derived from payroll_headcount_schedule. Directional repair rules live here so GPT sees the causal movement contract through SQL mapping." |

**Answer to the key questions:** Payroll is **not** a targetable primary lever
(`targeting_allowed = 0`) and **is** `diagnostic_only`. There is a single payroll lever (no
per-role rows in the mapping table); per-role/per-title granularity lives in the GPT grid,
not the lever table.

### 1c. The revenue-side levers that headcount feeds

Three pattern levers (`revenue::*::*::Capacity`, `revenue::*::*::Unit Price`,
`revenue::*::*::Utilization`) are seeded from the driver CSV and then UPDATE-patched with
payroll-feasibility issue codes and repair rules at
[post_intake_mapping.py:3563-3593](../../python/client_intake_and_finmo/post_intake_mapping.py#L3563-L3593).
`Capacity` is the lever that receives the headcount-derived supported-capacity value
(Step 3 / Step 4). It is not independently dialed as a free input once payroll runs —
downstream steps "may read but not overwrite it" ([post_intake_mapping.py:1319](../../python/client_intake_and_finmo/post_intake_mapping.py#L1319)).

---

## Step 2 — Where headcount is SET (producer path)

Headcount is **not a dialed-in constant**. It is produced by a GPT-propose → Python-build
chain in the `initial_grid` stage of the post-intake sequence:

| Seq # | Step key | Who acts | Produces |
|---|---|---|---|
| 62 | `load_payroll_oews_title_catalog` | Python | `oews_title_catalog`, `headcount_policy`, `productivity_assumptions` ([post_intake_mapping.py:1253-1262](../../python/client_intake_and_finmo/post_intake_mapping.py#L1253-L1262)) |
| 63 | `estimate_payroll_headcount_schedule_with_gpt` | **GPT** | `payroll_headcount_contract` (the FTE grid + capacity/labor enums) ([post_intake_mapping.py:1268-1289](../../python/client_intake_and_finmo/post_intake_mapping.py#L1268-L1289)) |
| 64 | `assert_payroll_headcount_payload_ready` | Python | **`payroll_headcount`** (validated payload → `intake_consult_drafts.payroll_headcount`) ([post_intake_mapping.py:1295-1304](../../python/client_intake_and_finmo/post_intake_mapping.py#L1295-L1304)) |
| 66 | `apply_payroll_supported_capacity_to_model_input` | Python | `model_input.revenue.Capacity` (derived from FTE) ([post_intake_mapping.py:1306-1320](../../python/client_intake_and_finmo/post_intake_mapping.py#L1306-L1320)) |
| 67 | `apply_payroll_headcount_payload_to_model_input` | Python | `model_input.expenses.Payroll` ([post_intake_mapping.py:1325-1334](../../python/client_intake_and_finmo/post_intake_mapping.py#L1325-L1334)) |

**`seed_formula_key = "python_derived_schedule"` is a marker, not a formula.** It is assigned
automatically whenever `control_owner == "python_derived"`
([post_intake_driver_formulas.py:126-130](../../python/client_intake_and_finmo/post_intake_driver_formulas.py#L126-L130)):

```python
elif owner == "python_derived":
  seed_formula_key = "python_derived_schedule"
  finmo_formula_key = "finmo_python_derived_schedule"
  validation_formula_key = "schedule_marker_validation"
  forecast_presence_rule_key = "schedule_reconciles_when_applicable"
```

It means "the value is computed once into a stored schedule, not re-derived by a runtime
formula." The actual payroll-dollar computation from the FTE grid happens in
`_build_payroll_headcount_payload_from_contract`
([schedule.py ~1900-2010](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py)):
per title, `average_fte = (starting_fte + ending_fte) / 2`,
`quarterly_wage = average_fte × annual_wage / 4`,
`quarterly = wage + wage × payroll_tax_benefits_pct`, summed to a quarter total.

**Conclusion for Step 2:** headcount today is an *independent authored input* (by GPT),
not computed from revenue or capacity. The only computed relationship runs the *other*
direction — capacity is computed from headcount (Step 3).

---

## Step 3 — The current headcount / revenue / productivity relationship (the crux)

### 3a. The productivity concept already exists: `capacity_units_per_supporting_fte`

It is a GPT-selected number in the payroll contract: "how many structural capacity units one
supporting FTE can support per quarter."
([post_intake_mapping.py:2139](../../python/client_intake_and_finmo/post_intake_mapping.py#L2139))
It has **no** active min/max policy columns — `capacity_units_per_supporting_fte_min` / `_max`
(and `capacity_productivity_bounds_json`) are in a DROP COLUMN legacy-removal list with no
replacement ([lookup.py:336-338](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L336-L338);
corrected in the Fix #2 spec — productivity has no current numeric anchor / starting value).
It is the multiplier used to derive capacity from FTE
([schedule.py:2559-2631](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2559-L2631),
formula string `"total_average_fte * capacity_units_per_supporting_fte"` at
[schedule.py:2631](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2631)).
Its prompt explicitly says **"Do not use revenue-per-employee."**

### 3b. The economic basis is a named, swappable field

`headcount_economic_basis` is a DB column, default `"capacity_units_per_supporting_fte"`
([lookup.py:36](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L36),
DDL default [lookup.py:264](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L264),
validated to equal that value at [lookup.py:715](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L715)).
The architecture anticipates more than one basis but implements exactly one. **This is the
natural seam for Fix #2's upstream lever.**

### 3c. The current doctrine is explicitly capacity-primary, revenue-as-sanity

`payroll_trend_rules_json` ([lookup.py:82-88](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L82-L88)):

```python
"payroll_trend_rules_json": {
  "capacity_primary": True,
  "use_revenue_as_sanity_not_driver": True,
  "average_fte_cannot_decline_when_capacity_increases": True,
  "average_fte_cannot_decline_when_utilization_increases": True,
  "payroll_dollars_cannot_decline_when_revenue_increases": True,
},
```

and the policy notes: "Payroll is schedule-driven and capacity-primary… Reasonableness is
checked against GPT's own payroll/revenue sanity target, not universal capacity-per-FTE
bounds." ([lookup.py:92-98](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L92-L98))

### 3d. Revenue is a sanity bound, not a driver

`target_payroll_percent_of_revenue` is a GPT business-judgment target in [0.06, 0.80]
that, per its own prompt, **"does not drive payroll math or force FTE"**
([post_intake_mapping.py:2150-2158](../../python/client_intake_and_finmo/post_intake_mapping.py#L2150-L2158)).
It is range-checked against tier bounds
`payroll_revenue_sanity_bounds_json` ([lookup.py:74-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L79)):

```python
"low":    {"min_pct": 0.06, "max_pct": 0.45},
"medium": {"min_pct": 0.10, "max_pct": 0.55},
"high":   {"min_pct": 0.16, "max_pct": 0.70},
"expert": {"min_pct": 0.18, "max_pct": 0.80},
```

selected by `labor_intensity_class`
([headcount_payroll_revenue_sanity_bounds, lookup.py:836-850](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L836-L850)).
`capacity_labor_model` (labor_driven/hybrid/system_driven/expert_driven) and
`labor_intensity_class` (low/medium/high/expert) are **GPT enums**, not numeric bindings
([lookup.py:40-51](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L40-L51),
[post_intake_mapping.py:2135-2136](../../python/client_intake_and_finmo/post_intake_mapping.py#L2135-L2136)).

### 3e. There IS already a partial revenue→productivity binding — in the repair path

Notably, the feasibility-repair layer **already computes the inverse direction** when
payroll/revenue is out of band: it solves for the
`capacity_units_per_supporting_fte` that would bring payroll into the sanity band
(`safe_capacity_units_per_supporting_fte_target_with_buffer`,
`required_capacity_units_per_supporting_fte_direction`,
[schedule.py:2944-2961](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2944-L2961),
repair constraints at [schedule.py:600-627](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L600-L627)).
The math note states "payroll_supported_revenue scales linearly with
capacity_units_per_supporting_fte when FTE, unit price, and utilization are unchanged"
([schedule.py:2957](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2957)).

**This is the second entanglement finding:** the system *already has the math* to bind
productivity to a revenue target — but only as a corrective nudge to the GPT-authored
productivity input, never as the primary producer of headcount. Fix #2 is largely about
promoting this existing inverse math from "repair hint" to "primary derivation."

---

## Step 4 — Downstream consumers of headcount

| Consumer | Where | How headcount flows in | Impact if headcount becomes derived |
|---|---|---|---|
| **Payroll grid contract** (`payroll_headcount_grid`: `q`, `oews_occ_title`, `starting_fte`, `hires`, `ending_fte`, `payroll_tax_benefits_pct`) | [post_intake_mapping.py:2048-2054](../../python/client_intake_and_finmo/post_intake_mapping.py#L2048-L2054) | GPT authors per title/quarter | If FTE is derived, the grid is *generated*, not authored — the `q1_to_q20_exactly_once` horizon rule (per title) no longer fits |
| **Payroll cost** | `_build_payroll_headcount_payload_from_contract`, [schedule.py ~1946-1982](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py) | `avg_fte × wage/4 + benefits` per quarter | Wage math is reusable; its *input* (FTE) changes source from authored to derived |
| **`expenses::Payroll` → finmo** | `apply_payroll_headcount_payload_to_model_input` → `finmo_python_derived_schedule` ([post_intake_mapping.py:1325-1334](../../python/client_intake_and_finmo/post_intake_mapping.py#L1325-L1334)) | quarter totals written to model_input then FINMO | Unchanged shape; the upstream producer changes |
| **Supported Capacity** | `apply_payroll_supported_capacity_to_model_input` ([post_intake_mapping.py:1306-1320](../../python/client_intake_and_finmo/post_intake_mapping.py#L1306-L1320); [schedule.py:2559-2631](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2559-L2631)) | `capacity = total_avg_fte × productivity` | **Risk of circularity:** if FTE is derived from revenue and capacity is derived from FTE and revenue depends on capacity, the chain closes a loop and must be ordered/iterated carefully |
| **FINMO reconciliation validator** | `assert_finmo_payroll_matches_headcount_schedule` (seq 68, [post_intake_mapping.py:1340-1351](../../python/client_intake_and_finmo/post_intake_mapping.py#L1340-L1351)) | asserts `finmo.payroll[q] == schedule.quarter_totals[q]` | Still valid if the derived schedule is computed *before* FINMO; the assertion compares to whatever schedule exists |
| **Payroll/revenue feasibility** | `payroll_revenue_feasibility_violations` / `assert_payroll_revenue_feasibility` ([schedule.py:2855-2961](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2855-L2961)) | ratio = payroll/revenue vs tier bounds | If headcount is *derived from* the revenue target, this band becomes a **constraint to solve to**, not a post-hoc check — meaning becomes prescriptive |
| **Quarter-grid + solver steps** | seq 70+ require `payroll_headcount` ([post_intake_mapping.py:1388, 1408, 1438, 1463, 1493](../../python/client_intake_and_finmo/post_intake_mapping.py#L1388)) | read FTE schedule as context | Need the derived schedule materialized before they run |

**headcount → payroll dependency (explicitly noted, deferred):** payroll authoring is the
primary consumer (`avg_fte × wage`). Payroll redesign is out of scope, but the Fix #2 spec
must guarantee the derived headcount still hands payroll a per-title, per-quarter FTE shape
(or the payroll cost math must be re-pointed at whatever the new producer emits).

---

## Step 5 — Contract / validator treatment

Headcount is treated as a **required, authored primary input** throughout the contract and
validator layer:

- **Contract field requiredness.** `payroll_headcount_grid` is a required array,
  `min_items=20`, `horizon_rule="q1_to_q20_at_least_once"`
  ([post_intake_mapping.py:2121-2134](../../python/client_intake_and_finmo/post_intake_mapping.py#L2121-L2134)); each grid row's `q`
  carries `horizon_rule="q1_to_q20_exactly_once"`
  ([post_intake_mapping.py:2049](../../python/client_intake_and_finmo/post_intake_mapping.py#L2049)). These rules assume FTE is
  *authored per title per quarter*.
- **`schedule_marker_validation`** is the validation key auto-assigned to `python_derived`
  fields ([post_intake_driver_formulas.py:129](../../python/client_intake_and_finmo/post_intake_driver_formulas.py#L129)). It is a
  marker meaning "the source schedule must be present and reconcile" — enforced by the
  headcount validators below, not a standalone function.
- **`assert_payroll_headcount_payload_ready`** fails fast with "post-intake payroll must
  originate from payroll_headcount_schedule.payroll_headcount_grid" if no schedule is present
  (seq 64, [post_intake_mapping.py:1295-1304](../../python/client_intake_and_finmo/post_intake_mapping.py#L1295-L1304)).
- **`assert_finmo_payroll_matches_headcount_schedule`** reconciles FINMO payroll to the
  schedule quarter-by-quarter (seq 68, [post_intake_mapping.py:1340-1351](../../python/client_intake_and_finmo/post_intake_mapping.py#L1340-L1351)).
- **`payroll_headcount` is a `required_context_key`** in ~13 downstream steps (issue
  detection, capacity derivation, payroll application, quarter-grid build/gen/solve,
  acceptance gates) — e.g. [post_intake_mapping.py:943, 1314, 1329, 1344, 1359, 1388, 1408, 1438, 1463, 1493, 1508, 1737](../../python/client_intake_and_finmo/post_intake_mapping.py#L1314).

**What this means for Fix #2:** nothing in the contract layer needs to *type headcount as
primary* — it is required as a *present, valid schedule*, not as a *dialed input*. As long
as a derived producer materializes `payroll_headcount` (same payload shape) before the
consumers run, the validators continue to hold. The pieces that assume *authoring* are the
two grid `horizon_rule`s (`q1_to_q20_exactly_once` per title, `at_least_once` on the array)
and the GPT contract instructions — those are what change if FTE stops being authored.

---

## KEY SPEC DECISIONS (for Nick)

These are the open choices the Fix #2 spec must settle. The trace surfaces options grounded
in what exists; it does not pick among them.

1. **What is the derived binding for headcount?** The system already implements *one*
   direction (`capacity = avg_fte × capacity_units_per_supporting_fte`) and already has the
   *inverse* math in the repair path. Candidate bindings:
   - **(A) Capacity/productivity-based (smallest change):** keep
     `capacity_units_per_supporting_fte` as the economic basis, but make
     `avg_fte = required_capacity ÷ capacity_units_per_supporting_fte` the *primary*
     producer, where required_capacity comes from the revenue/throughput plan. This promotes
     the existing repair-path inverse ([schedule.py:2944-2961](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2944-L2961))
     to the primary derivation and reuses the named `headcount_economic_basis` seam.
   - **(B) Revenue-per-head-based:** introduce a new economic basis (e.g.
     `revenue_per_fte`) and derive `headcount = revenue ÷ revenue_per_fte`. Note the current
     code *explicitly forbids* revenue-per-employee in the productivity field
     ([post_intake_mapping.py:2139](../../python/client_intake_and_finmo/post_intake_mapping.py#L2139)) — choosing this reverses a
     stated doctrine and needs a new lever + policy bounds.
   - **(C) Productivity-curve-based:** headcount as a non-linear function of revenue/scale
     (economies of scale). No pieces exist for this today; largest build.

2. **What becomes the upstream primary lever in headcount's place?** Options map to (1):
   `capacity_units_per_supporting_fte` (basis A, already a lever with min/max bounds), a new
   `revenue_per_fte` lever (basis B), or a curve (basis C). The `headcount_economic_basis`
   column ([lookup.py:36](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L36)) is the designed switch point.

3. **Invert or keep the `capacity_primary` doctrine?** Today `payroll_trend_rules_json` says
   `capacity_primary: True`, `use_revenue_as_sanity_not_driver: True`
   ([lookup.py:82-88](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L82-L88)). Fix #2 means flipping
   `use_revenue_as_sanity_not_driver` to false (revenue becomes the driver). Decide whether
   the monotonicity rules (FTE-cannot-decline-when-capacity-increases, etc.) survive or are
   replaced.

4. **Who authors what after the inversion?** Currently GPT authors the FTE grid (the
   "Executive" layer Fix #2 considers unbuilt). If headcount becomes Python-derived, decide:
   does GPT still author the OEWS *title mix* + productivity/revenue-per-head judgment while
   Python derives the *FTE numbers*? Or does Python own the whole grid? This determines which
   `payroll_headcount_grid` fields stay GPT-authored vs become Python-generated, and whether
   the `q1_to_q20_exactly_once` horizon rule
   ([post_intake_mapping.py:2049](../../python/client_intake_and_finmo/post_intake_mapping.py#L2049)) is kept, relaxed, or replaced.

5. **How is the capacity→FTE→capacity loop ordered to avoid circularity?** If revenue drives
   FTE, FTE drives supported capacity, and capacity feeds revenue drivers, the spec must
   define the solve order (single pass with a fixed revenue target, or an iterated
   convergence) so `apply_payroll_supported_capacity_to_model_input`
   ([post_intake_mapping.py:1306-1320](../../python/client_intake_and_finmo/post_intake_mapping.py#L1306-L1320)) and the feasibility
   validators remain consistent.

6. **Keep the payroll/revenue sanity band as check or promote to target?** If headcount is
   derived from a revenue binding, `payroll_revenue_sanity_bounds`
   ([lookup.py:74-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L79)) shifts from a post-hoc
   sanity check to a constraint the derivation must satisfy by construction. Decide whether it
   stays as a guardrail or becomes the governing equation.

---

## Hard-rule compliance

Trace only — no code, mapping, or fixes changed. Executive layer, payroll authoring, and
intake untouched. The derived binding is left open (decisions above). Two
"more-entangled-than-expected" findings reported rather than resolved: (i) headcount is
currently *GPT-authored*, not Python-dialed; (ii) the inverse revenue→productivity math
already exists in the repair path but is not the primary producer.
