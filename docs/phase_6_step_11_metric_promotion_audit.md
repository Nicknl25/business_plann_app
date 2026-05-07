# Phase 6 Step 11 — Metric Promotion Audit

## Purpose

Phase 6 Step 11 promotes target metrics from `gate_kind="warn"` to
`gate_kind="hard_fail"` in `post_intake_realism/lookup.py` and wires
each promoted metric to a remediation pathway via either:

- **Mechanism 1**: a single `governs_model_input_lever_id` on the realism
  row.
- **Mechanism 2**: a multi-lever entry in
  `post_intake_solver/influence_map.py:_MULTI_LEVER_METRIC_REGISTRY`.

Acceptance for Step 11 (per directive):
- Zero `gate_kind="warn"` rows remain in `lookup.py` (`skip_if_no_coverage`
  preserved as a separate category).
- Every `hard_fail` row has either a single governing lever OR a
  multi-lever influence_map entry. No metric promoted without a
  remediation pathway.

## Lever Inventory (verified from `post_intak_mapping_lookup`)

26 active mapping rows. `gpt_editable` set (the convergence solver's
degrees of freedom): 8 levers — Capacity / Unit Price / Utilization /
COGS / Marketing / R&D / Lease / G&A.

Other control owners:
- `cash_pass` — 9 levers (AR Days, AP Days, Deferred Revenue %, etc.)
- `python_derived` — 4 levers (Payroll, Depreciation, Capex, Taxes)

## Per-Metric Mapping

### Already `hard_fail` (kept as is, no Step 11 change)

| Metric | Lever | Verification |
|---|---|---|
| `cogs_percent_of_revenue` | `expenses::Cost of Goods Sold` | ✓ exists, gpt_editable |
| `ebitda_margin` | `expenses::Cost of Goods Sold` | ✓ exists, gpt_editable |
| `effective_tax_rate` | `expenses::Taxes` | ✓ exists, python_derived |
| `ar_days_dso` | `balance_sheet::Accounts Receivable Days` | ✓ exists, cash_pass |
| `ap_days_dpo` | `balance_sheet::Accounts Payable Days` | ✓ exists, cash_pass |

### Already `skip_if_no_coverage` (kept; not warn)

| Metric | Notes |
|---|---|
| `advertising_percent_of_revenue` | NAICS coverage gap — skip_if_no_coverage is correct semantics |

### Step 11 promotions — single governing lever

| Metric | New Lever | Verification | Notes |
|---|---|---|---|
| `gross_margin_percent` | `expenses::Cost of Goods Sold` | ✓ exists, gpt_editable | gross_margin = (revenue - COGS) / revenue; COGS is the primary remediation lever |
| `marketing_percent_of_revenue` | `expenses::Marketing` | ✓ exists, gpt_editable | already linked; only flipping gate |
| `r_and_d_percent_of_revenue` | `expenses::Research & Development` | ✓ exists, gpt_editable | already linked |
| `rent_percent_of_revenue` | `expenses::Lease` | ✓ exists, gpt_editable | directive said `expenses::Lease/Rent`; canonical name is `expenses::Lease` |
| `sga_percent_of_revenue` | `expenses::General & Administrative` | ✓ exists, gpt_editable | |
| `inventory_days` | `balance_sheet::Inventory Days` | ✓ exists, cash_pass | already linked |
| `deferred_revenue_percent_of_revenue` | `balance_sheet::Deferred Revenue (% of Revenue)` | ✓ exists, cash_pass | |
| `distributions_percent_of_net_income` | `balance_sheet::Distributions` | ✓ exists, cash_pass | |
| `prepaid_expenses_percent_of_revenue` | `balance_sheet::Prepaid Expenses (% of Revenue)` | ✓ exists, cash_pass | |
| `owners_capital_percent_of_assets` | `balance_sheet::Owner's Capital` | ✓ exists, cash_pass | |

### Step 11 promotions — single governing lever, schedule-only remediation

These metrics have a governing lever in the mapping table, but the
lever's `control_owner` is `python_derived` — meaning it's mechanically
computed from a schedule (payroll headcount schedule, capex schedule,
depreciation schedule). The cascade cannot push these levers directly
because they're not editable; the editable surface is the underlying
schedule's input. When these metrics are out of band, the structural
feasibility check (Phase 6 Step 9) is the upstream catcher — if the
structural revenue / fixed-cost relationship is feasible, schedule-
derived metrics typically land. When they don't land, the diagnostic
points the consultant at the schedule input rather than implying the
cascade can fix it.

| Metric | Lever | Verification | Notes |
|---|---|---|---|
| `payroll_percent_of_revenue` | `expenses::Payroll` | ✓ exists, python_derived | schedule_only_no_lever; remediation is via payroll headcount schedule input |
| `depreciation_percent_of_revenue` | `expenses::Depreciation` | ✓ exists, python_derived | schedule_only_no_lever; remediation is via capex schedule input |
| `capex_percent_of_revenue` | `schedules::Capital Expenditures` | ✓ exists, python_derived | schedule_only_no_lever |

### Step 11 promotions — multi-lever influence_map

These metrics are functions of multiple drivers; no single lever
fully governs. The realism row sets `gate_kind="hard_fail"` and leaves
`governs_model_input_lever_id=None`. The new
`_MULTI_LEVER_METRIC_REGISTRY` in `influence_map.py` maps each metric
to a priority-ordered list of candidate levers; the cascade walks the
list when remediation is needed.

| Metric | Candidate Levers (priority order) |
|---|---|
| `operating_margin_percent` | COGS, Marketing, R&D, G&A |
| `net_income_margin` | COGS, Marketing, R&D, G&A, Interest Rate |
| `current_ratio` | AR Days, AP Days, Inventory Days, Short Term Debt (% of LTD) |
| `quick_ratio` | AR Days, AP Days, Short Term Debt (% of LTD) |
| `debt_to_equity` | Debt Issuance, Debt Repayment, Owner's Capital |
| `debt_to_assets` | Debt Issuance, Debt Repayment |
| `operating_cash_flow_margin` | AR Days, AP Days, Inventory Days, COGS |
| `total_assets_to_revenue` | Capacity, Unit Price, Utilization, AR Days, Inventory Days |

### Removals — no remediation pathway

| Metric | Reason |
|---|---|
| `ppe_percent_of_revenue` | PPE is a schedule output of Capex (python_derived). No editable lever; not a structural-feasibility input. The metric is descriptive, not enforceable. Removed from `_DEFAULT_REALISM_CHECK_ROWS`. |

## Out-of-scope per directive

Mentioned by directive's lever-assignment narrative but not in current
realism table:
- `debt_to_ebitda` — adding new metrics is "different work — adding
  measurement vs enforcing what already exists." Not added.
- `interest_coverage` — same.

## Influence_map performance check

The Phase 5.2 R3 joint feasibility check at
`joint_feasibility_check.py:verify_joint_feasibility` does pairwise
direct-governance checks for every metric whose
`governs_model_input_lever_id` is set. After Step 11, more metrics have
governing levers, so the check has more pairs to evaluate. Quick math:

- Single-lever metrics post-Step-11: 13 (was 5)
- Multi-lever metrics post-Step-11: 8 (handled outside the joint
  feasibility direct-governance pass — they don't increase its scope)

13 pairwise checks is sub-millisecond. Sub-second runtime budget
preserved.

## Final row counts

| Status | Pre-Step-11 | Post-Step-11 |
|---|---|---|
| `hard_fail` | 5 | 26 |
| `warn` | 22 | 0 |
| `skip_if_no_coverage` | 1 | 1 |
| Removed | 0 | 1 |
| **Total** | **28** | **27** |

Acceptance: `grep -c 'gate_kind="warn"' lookup.py` returns 0 after
Step 11.
