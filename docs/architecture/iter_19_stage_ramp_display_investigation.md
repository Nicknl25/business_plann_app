# Stage Ramp Contract Display Gap — Investigation Memo

**Iter:** Phase 9 P3.15
**Status:** Read-only investigation. No code changes.
**Trigger:** The Revenue Drivers sheet on recent workbooks (Sunny, NexGen, ExpressLogix) appeared to show only the revenue QoQ growth ramp. Everything else on the stage ramp contract section was blank or zero.

---

## 1. What is displayed today

Inspected the live NexGen workbook from the P3.14 pass:
[`C:/dev/Cilient Plans/NexGen Software Solutions Inc. -- 05-17-2026 10-36-49.xlsx`](file:///C:/dev/Cilient%20Plans/NexGen%20Software%20Solutions%20Inc.%20--%2005-17-2026%2010-36-49.xlsx).

The Revenue Drivers sheet has a "Stage Ramp Contract" section starting at row 16. The rows underneath:

| Row | Label | Values (Q1..Q4 sample) |
|---|---|---|
| 16 | Stage Ramp Contract (section header) | — |
| 17 | Actual Revenue QoQ Growth | (computed formula; non-zero) |
| 18 | Stage Ramp Revenue QoQ Target | **0, 0, 0, 0** |
| 19 | Stage Ramp Revenue QoQ Max | **0, 0, 0, 0** |
| 20 | Stage Ramp Revenue QoQ Spike Max | **0, 0, 0, 0** |
| 21 | Stage Ramp Utilization Cap | **0, 0, 0, 0** |
| 22 | Stage Ramp COGS % Revenue Target | **0, 0, 0, 0** |
| 23 | Stage Ramp COGS % Revenue Max | **0, 0, 0, 0** |
| 24 | Stage Ramp Marketing % Revenue Max | **0, 0, 0, 0** |
| 25 | Stage Ramp R&D % Revenue Max | **0, 0, 0, 0** |
| 26 | Stage Ramp G&A % Revenue Max | **0, 0, 0, 0** |
| 27 | Stage Ramp Lease % Revenue Max | **0, 0, 0, 0** |
| 28 | Stage Ramp Net Income Margin Floor | **0, 0, 0, 0** |

The user's read ("only shows revenue QoQ growth ramp") is accurate: row 17 (Actual Revenue QoQ Growth) is the only non-zero row, and it isn't even sourced from the contract — it's a computed formula off the actual revenue total above. Every contract-sourced row renders as zeros.

---

## 2. What is in the contract today

Pulled NexGen's persisted draft (`d7e58d2e38c344ccb602d1ac7ae5caf3`) `planning_run_json.stage_ramp_contract`:

```python
{
  'business_stage': 'operational',
  'business_stage_source': 'ops.business_stage',
  'contract_version': 'stage_ramp_contract_v2',
  'decision_source': 'stage_ramp_handler_refined',
  'planning_mode': '...',
  'planning_mode_reason': '...',
  'python_proposal_diagnostic': {...},
  'quarter_ramp_grid': [20 rows, see below],
  'r_and_d_applicability': {...},
  'rationale': '...',
  'stage_family': 'operational',
  'utilization_high_watermark': 0.85,
}
```

Each `quarter_ramp_grid[]` row, sampled from Q1:

```python
{
  'q': 1,
  'rev_target': 0.04,
  'rev_max': 0.06,
  'rev_spike': False,
  'rev_spike_max': 0.06,
  'max_util': 0.65,
  'cogs_target': 0.31,
  'cogs_max': 0.49,
  'marketing_max': 0.31,
  'rd_max': 0.3,
  'ga_max': 0.31,
  'lease_max': 0.03,
  'ni_floor': 0,
  'posture': 'near_breakeven',
}
```

The contract carries **substantial** data: 14 per-quarter fields × 20 quarters, plus 7+ root-level metadata fields (stage_family, utilization_high_watermark, rationale, decision_source, business_stage, planning_mode, python_proposal_diagnostic). The values are real and meaningful for NexGen (e.g., `cogs_target: 0.31`, `max_util: 0.65 → 0.85` over the horizon).

---

## 3. The gap — primary cause: key-name mismatch

Renderer at [client_statements_output_excel/schedule_sheets.py:95-104](../../client_statements_output_excel/schedule_sheets.py#L95-L104):

```python
def _stage_ramp_values(data: DraftWorkbookData, field: str) -> List[float]:
  values = [0.0 for _ in range(PERIOD_COUNT)]
  ramp_rows = data.stage_ramp_contract.get("quarter_ramp_grid") if isinstance(data.stage_ramp_contract, dict) else []
  for item in ramp_rows or []:
    if not isinstance(item, dict):
      continue
    quarter_index = int(number(item.get("quarter_index")))   # ← KEY MISMATCH #1
    if 1 <= quarter_index < PERIOD_COUNT:
      values[quarter_index] = number(item.get(field))         # ← KEY MISMATCH #2
  return values
```

Called from [schedule_sheets.py:207-219](../../client_statements_output_excel/schedule_sheets.py#L207-L219):

```python
ramp_definitions = [
  ("Stage Ramp Revenue QoQ Target", "revenue_qoq_target", PERCENT_FORMAT),
  ("Stage Ramp Revenue QoQ Max", "revenue_qoq_max", PERCENT_FORMAT),
  ("Stage Ramp Revenue QoQ Spike Max", "revenue_qoq_spike_max", PERCENT_FORMAT),
  ("Stage Ramp Utilization Cap", "utilization_cap", PERCENT_FORMAT),
  ("Stage Ramp COGS % Revenue Target", "cogs_percent_of_revenue_target", PERCENT_FORMAT),
  ("Stage Ramp COGS % Revenue Max", "cogs_percent_of_revenue_max", PERCENT_FORMAT),
  ("Stage Ramp Marketing % Revenue Max", "marketing_percent_of_revenue_max", PERCENT_FORMAT),
  ("Stage Ramp R&D % Revenue Max", "rd_percent_of_revenue_max", PERCENT_FORMAT),
  ("Stage Ramp G&A % Revenue Max", "g_and_a_percent_of_revenue_max", PERCENT_FORMAT),
  ("Stage Ramp Lease % Revenue Max", "lease_percent_of_revenue_max", PERCENT_FORMAT),
  ("Stage Ramp Net Income Margin Floor", "net_income_margin_floor", PERCENT_FORMAT),
]
```

The renderer looks up **long-form field names** (`revenue_qoq_target`, `utilization_cap`, `cogs_percent_of_revenue_target`, …). The persisted contract carries **short-form aliases** (`rev_target`, `max_util`, `cogs_target`, …). Every `item.get(field)` returns `None`. `number(None)` returns `0.0`. All 11 rows × 20 quarters render as 0.

The mismatch is **exhaustive**:

| Renderer expects | Contract emits |
|---|---|
| `quarter_index` | `q` |
| `revenue_qoq_target` | `rev_target` |
| `revenue_qoq_max` | `rev_max` |
| `revenue_qoq_spike_max` | `rev_spike_max` |
| `utilization_cap` | `max_util` |
| `cogs_percent_of_revenue_target` | `cogs_target` |
| `cogs_percent_of_revenue_max` | `cogs_max` |
| `marketing_percent_of_revenue_max` | `marketing_max` |
| `rd_percent_of_revenue_max` | `rd_max` |
| `g_and_a_percent_of_revenue_max` | `ga_max` |
| `lease_percent_of_revenue_max` | `lease_max` |
| `net_income_margin_floor` | `ni_floor` |

The mapping isn't ambiguous — the validator at [post_intake_contracts/runner.py:709-722](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L709-L722) has an explicit `ramp_field_aliases` dict that documents this exact short→long correspondence. The renderer was written against the long form (the validator's *normalized internal* form), but the contract that gets persisted to `planning_run_json` carries the short form (the GPT-emitted / SQL-contract-row form).

---

## 4. The gap — secondary observation: missing metadata rows

Even if the 11 per-quarter rows render correctly, the section still omits substantial useful information that's in the contract:

| Contract field | What it carries | Currently shown? |
|---|---|---|
| `stage_family` | startup / early / operational | No |
| `utilization_high_watermark` | mature utilization cap (e.g., 0.85) | No |
| `rationale` | GPT/Python text explaining the ramp | No |
| `decision_source` | `python_deterministic_builder` vs `stage_ramp_handler_refined` (handler engagement provenance) | No |
| `business_stage` / `business_stage_source` | operator-reported stage + source | No |
| `planning_mode` / `planning_mode_reason` | growth/turnaround/etc. | No |
| `python_proposal_diagnostic` | when handler engaged: `validator_error_text`, `tool_calls_used`, diagnostic — the audit trail of Stage 5's GPT loop | No |
| Per-row `rev_spike` (bool) | whether revenue spike is allowed that quarter | No |
| Per-row `posture` (string) | `loss_allowed` / `improving_losses` / `near_breakeven` / `positive` | No |

The two per-row fields (`rev_spike`, `posture`) and the root-level metadata are real, validator-checked contract data that has no representation on the sheet.

---

## 5. When did this happen

The renderer block (lines 207-232) was added in commit `0dfe081` ("updated payroll", 2026-05-05). It's the only commit that touched these lines — it has never been corrected. The bug has existed since the renderer was first written.

Cross-check: the SQL contract row declarations in [post_intake_mapping.py](../../python/client_intake_and_finmo/post_intake_mapping.py) for stage_ramp_contract use the short-form `field_name` values (`q`, `rev_target`, `max_util`, etc.) and have done so since they were added pre-iter-19. The persisted contract has always been short-form. The renderer was authored against the validator's internal normalized representation, not against the persisted form.

This means: **every workbook ever generated has had this gap.** The user's recent observation is correct but the cause predates iter 19 and all subsequent work — none of P3.11/P3.12/P3.13/P3.14 caused or worsened it.

---

## 6. Cause categorization

- **Display-only fix needed?** Yes for the primary issue (key-name mismatch).
- **Data-flow fix needed?** No. The data is present in `planning_run_json.stage_ramp_contract` and `data.stage_ramp_contract` correctly returns it. The 4-tier fallback in [data.py:151-165](../../client_statements_output_excel/data.py#L151-L165) is unnecessary for this fix (the top-level path resolves; the fallbacks are belt-and-suspenders).
- **Builder fix needed?** No. The Stage 5 Python builder (`build_python_stage_ramp_contract`) and the GPT path both correctly emit the contract in the SQL contract row's declared field-name form (short). That's intentional and consistent with the validator's parsing.

---

## 7. Recommended fix scope

### Primary fix — rename the lookups

Update `_stage_ramp_values` and `ramp_definitions` to use the actual stored keys. Approximately 12 lines changed in [client_statements_output_excel/schedule_sheets.py](../../client_statements_output_excel/schedule_sheets.py):

```python
# In _stage_ramp_values:
quarter_index = int(number(item.get("q")))   # was "quarter_index"

# In ramp_definitions:
("Stage Ramp Revenue QoQ Target", "rev_target", PERCENT_FORMAT),
("Stage Ramp Revenue QoQ Max", "rev_max", PERCENT_FORMAT),
("Stage Ramp Revenue QoQ Spike Max", "rev_spike_max", PERCENT_FORMAT),
("Stage Ramp Utilization Cap", "max_util", PERCENT_FORMAT),
("Stage Ramp COGS % Revenue Target", "cogs_target", PERCENT_FORMAT),
("Stage Ramp COGS % Revenue Max", "cogs_max", PERCENT_FORMAT),
("Stage Ramp Marketing % Revenue Max", "marketing_max", PERCENT_FORMAT),
("Stage Ramp R&D % Revenue Max", "rd_max", PERCENT_FORMAT),
("Stage Ramp G&A % Revenue Max", "ga_max", PERCENT_FORMAT),
("Stage Ramp Lease % Revenue Max", "lease_max", PERCENT_FORMAT),
("Stage Ramp Net Income Margin Floor", "ni_floor", PERCENT_FORMAT),
```

This alone makes all 11 contract rows populate with their real values. Pure renderer fix — no data layer or builder changes.

### Doctrine alignment

Per doctrine §3 Pattern 1 (Two paths compute same value), the short-form and long-form names are a Mirror Flavor 4 (independent computation + invariant check). The validator already has the `ramp_field_aliases` mapping that ties the two; the renderer should either:

- **Option A (smallest):** use the same short-form keys the contract actually carries (the proposed fix above).
- **Option B (most robust):** import `ramp_field_aliases` from the validator module and use it to translate at the renderer boundary. This keeps the renderer's label-set in long-form (more human-readable for the codebase) but resolves to short-form at lookup time. ~3 extra lines.

Option B is doctrine-cleaner — one canonical aliases mapping shared between the validator and the renderer. Option A is smaller. Both achieve the same workbook output.

### Secondary fix — add the missing metadata rows

Add a small "Stage Ramp Contract Metadata" sub-section before or after the per-quarter rows showing:

- `stage_family`, `business_stage`, `planning_mode`
- `utilization_high_watermark`
- `decision_source` (the handler engagement indicator)
- `rationale` (the GPT/Python text)
- `python_proposal_diagnostic.tool_calls_used` (when handler engaged — audit trail)

And add per-quarter `posture` and `rev_spike` rows under the existing 11.

This is ~30-50 lines. Stand-alone from the primary fix; can be done in the same commit or deferred.

---

## 8. Recommendation summary

| Layer | Fix needed | Lines | Priority |
|---|---|---|---|
| Renderer key-name lookups | Yes — primary cause | ~12 | **High** (fixes the user's observed gap entirely) |
| Renderer metadata-section addition | Optional — secondary observation | ~30-50 | Medium (more comprehensive workbook output) |
| Data flow | No | 0 | n/a |
| Stage ramp builder | No | 0 | n/a |
| Validator | No | 0 | n/a |

**Suggested approach:** ship the primary key-name fix as a small focused commit (Option A or Option B as you prefer). Treat the metadata-section addition as a separate workbook-richness improvement if and when desired — it's worth doing but doesn't block correcting the user's observed gap.

---

## 9. Notes

- The bug predates iter 19. None of the recent iter work (Stage 5 / P3.11 / P3.12 / P3.13 / P3.14) caused or worsened it.
- Every workbook ever produced from this codebase has had the same all-zero stage ramp contract display.
- The contract data itself is correct and meaningfully populated; this is purely a presentation gap.
- The `python_proposal_diagnostic` field, when handler engaged (NexGen and ExpressLogix in the P3.14 runs), carries the audit trail of which handler engaged, how many tool calls it used, and what validator error it was responding to. Adding this to the secondary metadata section would make the handler engagement visible in the workbook for the first time.
