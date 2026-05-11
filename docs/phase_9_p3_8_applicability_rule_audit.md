# Phase 9 P3.8 — Applicability Rule Audit

**Date:** 2026-05-11
**Scope:** Every rule in the codebase that conditions a realism metric's activity (or a lever's applicability) on NAICS, archetype, stage code, or business-type signal. Read-only — no code changes.

This audit answers: "before we touch the Inventory Days skip rule, how many similar rules exist? Is it a one-off or part of a pattern?"

---

## 1. Summary

| Category | Rule count | Where |
|---|---:|---|
| **Realism-gate applicability rules — business-type conditioned** | 3 | `post_intake_realism/validator.py::_applicability_skip` |
| **Realism-gate applicability rules — financial-state conditioned** | 5 | same file (denominator-zero / pretax-nonpositive / debt-zero / distributions-zero) |
| **Balance-sheet seed applicability — NAICS-2 set membership** | 2 levers | `post_intake_balance_sheet/contextual_seed.py` |
| **Balance-sheet seed applicability — token match in business description** | per-lever | same file (`applicability_positive_tokens`) |
| **R&D applicability decision lookup — NAICS-2 set membership** | 23 NAICS-2 entries | `post_intake_mapping.py` |
| **Planning-mode tolerated_issue_codes** | 5 modes × varied codes | same file |
| **active=False rows in the realism config** | 0 | `post_intake_finalize_realism_check_rows()` (none currently) |
| **stage_sensitivity tolerance multipliers** | 36 rows | same. These widen/narrow bands; they do NOT skip metrics. |

Total NAICS / archetype conditional rules that actually disable a metric or lever: **5 in the realism gate + 2 in the seed proposer = 7 conditional rules**. Plus the upstream R&D applicability decision (which inputs into one of the 5 realism rules).

---

## 2. Realism-gate applicability rules

The single chokepoint is `_applicability_skip()` in [post_intake_realism/validator.py:120-260](python/client_intake_and_finmo/post_intake_realism/validator.py#L120-L260). It returns a non-empty reason string when a check should be skipped (status flips to `"skipped"`). All eight active rules:

### 2.1 Business-type conditioned (NAICS-2 set membership)

#### 2.1.1 `inventory_when_business_has_inventory`

| Field | Value |
|---|---|
| **Metric affected** | `inventory_days` |
| **Condition** | Skip when `business_naics_6[:2]` ∉ `{"31", "32", "33", "42", "44", "45", "72"}` (Manufacturing 31-33, Wholesale Trade 42, Retail Trade 44-45, Accommodation/Food Service 72) |
| **What's skipped** | Entire metric — `status="skipped"`, no band check, no hard-fail-able path |
| **Skip reason emitted** | `"skip_inventory_not_applicable_naics2_{naics_2}"` |
| **gate_kind** | `skip` (from realism config) |
| **Reasoning** | Service-only NAICS-2 sectors (Information 51, Professional Services 54, Health Care 62, Finance 52, Transportation 48/49, etc.) carry no meaningful physical inventory. The cohort tables nonetheless populate Inventory Days values for NAICS 51 because the L3=511 cohort includes legacy publishers (book/periodical/sound recording) with physical inventory. Skip prevents a false hard-fail; downside is that nothing flags the cohort-derived Inventory Days at 35 days for a SaaS firm. |
| **File** | [validator.py:173-178](python/client_intake_and_finmo/post_intake_realism/validator.py#L173-L178) |

#### 2.1.2 `deferred_revenue_when_business_has_recurring`

| Field | Value |
|---|---|
| **Metric affected** | `deferred_revenue_percent_of_revenue` |
| **Condition** | Skip when `business_naics_6[:2]` ∉ `{"51", "52", "53", "54", "62"}` (Information / Finance / Real Estate / Professional Services / Health Care) |
| **What's skipped** | Entire metric — `status="skipped"` |
| **Skip reason emitted** | `"skip_deferred_revenue_not_applicable_naics2_{naics_2}"` |
| **gate_kind** | `skip` |
| **Reasoning** | The included NAICS-2 sectors are those where annual contracts / membership / retainer / capitation revenue produces material deferred-revenue balances. Other sectors (manufacturing, retail, food service) typically settle revenue at point-of-sale and don't carry deferred revenue. |
| **File** | [validator.py:212-220](python/client_intake_and_finmo/post_intake_realism/validator.py#L212-L220) |

#### 2.1.3 `r_and_d_when_applicable`

| Field | Value |
|---|---|
| **Metric affected** | `r_and_d_percent_of_revenue` |
| **Condition** | Skip when R&D dollars are zero across all 20 quarters AND `business_naics_6[:2]` ∉ `{"51", "54"}` (Information / Professional Scientific Technical). For NAICS-2 in {51, 54}, the skip is *suppressed* — zero R&D is treated as a model defect and lets the band check fire. |
| **What's skipped** | Entire metric (status=skipped) for non-{51,54} sectors with zero R&D. For {51, 54} with zero R&D, the band check runs and may hard-fail. |
| **Skip reason emitted** | `"skip_r_and_d_not_applicable_to_business"` |
| **gate_kind** | `skip` |
| **Reasoning** | Documented inline as Phase 9 audit fix #9 — the silent skip was masking "we forgot to schedule any R&D" for software / research businesses. Per the comment: "Zero R&D in those sectors is itself a model defect — let the band check fire so the mismatch surfaces as an actionable out-of-band result." |
| **File** | [validator.py:179-211](python/client_intake_and_finmo/post_intake_realism/validator.py#L179-L211) |

### 2.2 Financial-state conditioned (no NAICS / archetype dependency)

These skip based on the FINMO state (revenue=0, opex=0, debt=0, etc.) rather than business type. Listed for completeness; not the audit's primary concern.

| Rule key | Metrics affected | Trigger condition |
|---|---|---|
| `skip_when_revenue_zero` | `ar_days_dso` (skip), `current_assets_minus_cash` (hard_fail), `current_liabilities_to_revenue` (hard_fail), `ebitda_margin` (hard_fail) | revenue ≤ 0 at the evaluated quarter |
| `skip_when_operating_expense_zero` | `ap_days_dpo` | opex (or COGS+marketing+G&A fallback) ≤ 0 |
| `skip_when_pretax_income_nonpositive` | `effective_tax_rate` (both skip + hard_fail rows) | pretax income summed over the row's quarter scope ≤ 0 |
| `skip_when_debt_zero` | `debt_to_assets`, `debt_to_equity` | short_term + long_term debt ≤ 1e-6 |
| `skip_when_distributions_zero` | (defined but not currently bound to any active row) | distributions/owner_distributions horizon- or year-scoped ≤ 1e-6 |

These rules are universal across NAICS — they reflect math-impossibility (zero denominator) or doctrine (don't measure tax-rate on a loss).

### 2.3 Rows with empty `applicability_rule_key`

Metrics with no rule key (24 active rows) — these run unconditionally for every business. Examples: `cogs_percent_of_revenue`, `gross_margin_percent`, `marketing_percent_of_revenue`, `sga_percent_of_revenue`, `payroll_percent_of_revenue`, `quick_ratio`, the 6 universal viability trajectory metrics, etc. No business-type conditioning.

---

## 3. Balance-sheet seed applicability (lever-side, not metric-side)

In `post_intake_balance_sheet/contextual_seed.py`, the contextual seed has its own applicability gate at the LEVER level. This determines whether the seed writes a non-zero value into Q1..Q20 for that lever; the realism metric for that lever is separately governed by Section 2.

The map at [contextual_seed.py:298-304](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L298-L304):

```python
_LEVER_APPLICABILITY_NAICS_2: Dict[str, Optional[set]] = {
  "balance_sheet::Accounts Receivable Days": None,             # universal
  "balance_sheet::Accounts Payable Days": None,                # universal
  "balance_sheet::Inventory Days": {"31","32","33","42","44","45","72"},
  "balance_sheet::Prepaid Expenses (% of Revenue)": None,      # universal
  "balance_sheet::Deferred Revenue (% of Revenue)": {"51","52","53","54","62"},
}
```

### 3.1 Inventory Days seed applicability

| Field | Value |
|---|---|
| **Lever** | `balance_sheet::Inventory Days` |
| **Applicable NAICS-2 set** | `{31, 32, 33, 42, 44, 45, 72}` — same as the realism rule's set |
| **What happens when not applicable** | Seed proposer sets `applicable=False`, `seed_value=0.0`. When applied, the seed PRESERVES existing values in Q1..Q20 (does not flat-stamp). Whatever the upstream cohort-baseline initializer put there stays. |
| **File** | [contextual_seed.py:301](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L301) + [contextual_seed.py:403-416](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L403-L416) |

### 3.2 Deferred Revenue seed applicability

| Field | Value |
|---|---|
| **Lever** | `balance_sheet::Deferred Revenue (% of Revenue)` |
| **Applicable NAICS-2 set** | `{51, 52, 53, 54, 62}` — same as the realism rule's set |
| **What happens when not applicable** | Same pattern. |
| **File** | [contextual_seed.py:303](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L303) |

**Architectural symmetry note:** the realism gate's NAICS-2 sets and the seed proposer's NAICS-2 sets are identical pairs. The realism gate trusts the seed proposer's applicability decision (or vice versa — they were designed together). Editing one without the other risks divergent semantics (e.g., a lever seeded with zero but the realism gate still expects an in-band value, or seeded with a positive value the realism gate hard-fails).

### 3.3 Token-match applicability (description signals, not NAICS)

The seed proposer ALSO defines per-lever `applicability_positive_tokens` and `applicability_negative_tokens` that operate on the business description string. Example from the [seed config](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py):

```python
{
  "lever_id": "balance_sheet::Deferred Revenue (% of Revenue)",
  "business_applicability_key": "deferred_revenue_business",
  "applicability_positive_tokens": ["subscription", "membership", "retainer",
    "deposit", "prepaid", "advance payment", "upfront", "annual contract"],
  "applicability_negative_tokens": [],
  ...
}
```

Effect: a business in a sector NOT in the NAICS-2 applicable set can still have the lever activated if the description matches a positive token. This is the path by which a "membership program at a retail superstore" would still get deferred revenue. The token list is per-lever and configured via the mapping table.

**Implication for any future architectural change to inventory_days:** the NAICS-2-only test is one layer. If you remove the inventory-days NAICS-2 skip, the token layer should still allow opt-in via description.

---

## 4. R&D applicability decision lookup

Separate from the realism rule — this is the upstream decision that determines whether R&D shows up in the model_input at all.

[post_intake_mapping.py:5389-5417](python/client_intake_and_finmo/post_intake_mapping.py#L5389-L5417) defines `_DEFAULT_R_AND_D_APPLICABILITY_ROWS` for 23 NAICS-2 codes, with three values:

- **`required`** (2 NAICS-2): `{51, 54}` — Information, Professional Services
- **`not_applicable`** (10 NAICS-2): `{22, 44, 45, 48, 49, 53, 55, 56, 61, 71, 72, 81}` — Utilities, Retail, Transportation, Warehousing, Real Estate, Mgmt of Companies, Admin Support, Education, Arts/Entertainment, Accommodation/Food, Other Services
- **`optional`** (10 NAICS-2): `{11, 21, 23, 31, 32, 33, 42, 52, 62}` — Agriculture, Mining, Construction, Manufacturing, Wholesale, Finance, Health Care — GPT decides per-business

The decision feeds `r_and_d_enabled` on the model_input, which the FINMO bridge reads via `_normalized_r_and_d_applicability_policy`. When `r_and_d_enabled=False`, the bridge forces R&D row's live values to zero and disables the controller-write lever. The realism rule (Section 2.1.3) reacts to this by computing horizon-wide-zero → skip (except for {51, 54} which never zero out).

---

## 5. Planning-mode `tolerated_issue_codes`

Not a NAICS / archetype rule — it's a planning_mode rule that allows specific issue codes to escape hard-fail status. Listed for completeness because it's a form of "tolerate metric failure conditional on business state."

Source: [post_intake_mapping.py:4990-5103](python/client_intake_and_finmo/post_intake_mapping.py#L4990-L5103) defines 5 planning modes:

| Planning mode | Tolerated issue codes | Effect |
|---|---|---|
| `growth` (the unnamed default) | `[]` | none |
| `turnaround` | `["mature_loss_state", "early_revenue_under_run_rate"]` | Allows EBITDA / NI / operating margin / GM hard-fails when the metric matches the issue code |
| `normalize` | `[]` | none |
| `growth_investment` | `["mature_loss_state"]` | Allows EBITDA / NI / operating margin hard-fails |
| `preservation` | `[]` | none |

Mapping from metric → issue code at [validator.py:327-332](python/client_intake_and_finmo/post_intake_realism/validator.py#L327-L332):
```python
_REALISM_METRIC_BELOW_BAND_TO_ISSUE_CODE = {
  "ebitda_margin": "mature_loss_state",
  "net_income_margin": "mature_loss_state",
  "operating_margin_percent": "mature_loss_state",
  "gross_margin_percent": "early_revenue_under_run_rate",
}
```

Effect: a `turnaround` business can hard-fail EBITDA margin and the violation is downgraded to `out_of_band_warn` (the gate does not raise). Universal across NAICS — same code list per mode.

---

## 6. Things that are NOT applicability rules

For clarity, these were inspected and ruled out:

- **`active=False` rows**: zero in the current realism config. There's no row that is disabled outright.
- **`stage_sensitivity` map** (every realism row): widens / narrows tolerance bands by stage profile (startup / early / operational / mature). Does NOT skip metrics — every metric runs at every stage; the band edges shift.
- **Cohort cascade resolver**: walks NAICS levels to find a band; does not filter metrics by NAICS.
- **`post_intake_industry_baseline/lookup.py`**: provides band values; no metric-skip logic.
- **`cohort_band_resolver.py`**: assembles cohort bands; no metric-skip logic.

---

## 7. Implication for the Inventory Days finding

The inventory_days skip is **part of a small pattern**, not a one-off:

| Metric / Lever | Skip rule | NAICS-2 set | Identical seed-side rule? |
|---|---|---|---|
| `inventory_days` | `inventory_when_business_has_inventory` | `{31,32,33,42,44,45,72}` | YES — [contextual_seed.py:301](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L301) |
| `deferred_revenue_percent_of_revenue` | `deferred_revenue_when_business_has_recurring` | `{51,52,53,54,62}` | YES — [contextual_seed.py:303](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L303) |
| `r_and_d_percent_of_revenue` | `r_and_d_when_applicable` | suppressed-skip for `{51,54}` | upstream decision lookup at 23 NAICS-2 entries |

If the user removes the inventory_days skip (so a service business with cohort-derived 35 days of inventory triggers a hard-fail), the analogous changes to consider:
- the seed-side applicability for the SAME lever (to stop the seed from preserving non-zero cohort values for non-applicable sectors)
- whether the same treatment should apply to deferred_revenue_percent_of_revenue (which has identical structure)

Three actions to think through, not one. None of the remaining 5 financial-state rules (Section 2.2) are business-type conditional; they're math-impossibility skips and don't need parallel treatment.

---

## 8. Pointers

- **Realism-gate single chokepoint**: `_applicability_skip()` at [validator.py:120](python/client_intake_and_finmo/post_intake_realism/validator.py#L120). Every applicability decision routes through here.
- **Seed-side applicability**: `_LEVER_APPLICABILITY_NAICS_2` at [contextual_seed.py:298](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L298) + `_proposer_applicability_for_lever()` at [contextual_seed.py:403](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L403).
- **R&D applicability decision**: `_assert_r_and_d_applicability_policy_applied()` and the NAICS-2 lookup at [post_intake_mapping.py:5389](python/client_intake_and_finmo/post_intake_mapping.py#L5389).
- **Planning-mode tolerance**: `tolerated_issue_codes` per mode at [post_intake_mapping.py:4990](python/client_intake_and_finmo/post_intake_mapping.py#L4990) + metric→issue mapping at [validator.py:327](python/client_intake_and_finmo/post_intake_realism/validator.py#L327).
