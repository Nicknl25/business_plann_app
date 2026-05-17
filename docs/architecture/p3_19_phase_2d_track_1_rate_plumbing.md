# P3.19 Phase 2d — Track 1: Interest Rate Plumbing End-to-End Audit

**Iter:** Phase 9 P3.19 Phase 2d (read-only investigation; no fixes)
**Scope:** Complete factual matrix of every writer/reader/transformer of any interest-rate-shaped value across the app and workbook builder.
**Method:** Exhaustive grep + line-by-line inspection.

---

## Definitions

- **ANNUAL** scale: the value represents an annual rate (e.g. 0.1025 = 10.25%/year).
- **QUARTERLY** scale: the value represents a per-quarter rate (e.g. 0.025625 = 10.25%/4).
- **PER-QUARTER contract**: the value is intended to be applied as `rate × balance` once per quarter to yield correct quarterly interest. Established as the `expenses::Interest Rate` row's contract by P3.19 Phase 2 (commit 758fa9f).

The policy field `derived_driver_policies.debt_interest_rate_policy.annual_rate_decimal` is ANNUAL. The policy field `derived_driver_policies.debt_interest_rate_policy.quarterly_rate_decimal` (added in P3.19 Phase 2) is QUARTERLY. The `expenses::Interest Rate` row holds the QUARTERLY value (post-Phase 2). The FINMO field `debt_interest_rate` holds the QUARTERLY value (mirrors the row).

---

## A. Policy structure shape

`derived_driver_policies.debt_interest_rate_policy` carries (post-Phase 2):

| Key | Scale | Source |
|---|---|---|
| `policy_version` | n/a (string `sba_7a_business_loan_interest_rate_v1`) | finmo_bridge.py:3651 |
| `driver_source` | n/a (string `sba_loan_7a_raw`) | finmo_bridge.py:3652 |
| `lever_id` | n/a (string `expenses::Interest Rate`) | finmo_bridge.py:3653 |
| `annual_rate_decimal` | ANNUAL | finmo_bridge.py:3654 |
| `quarterly_rate_decimal` | QUARTERLY (= annual / 4) | finmo_bridge.py:3655 (added Phase 2) |
| `source_detail` | n/a (nested dict) | finmo_bridge.py:3656 |
| `finmo_formula_unchanged` | n/a (bool) | finmo_bridge.py:3657 |
| `finmo_formula` | n/a (string documenting per-quarter contract) | finmo_bridge.py:3658 |

The `source_detail` nested dict also carries `annual_rate_decimal` (ANNUAL), populated by `_sba_business_loan_interest_rate_and_source` at finmo_bridge.py:1127.

---

## B. WRITERS — every site that writes a rate value

### B1. Writers into `expenses::Interest Rate` row

| File | Line | What | Scale produced | Arithmetic | Contract-consistent? |
|---|---|---|---|---|---|
| python/client_intake_and_finmo/finmo_bridge.py | 3273 | Q0 stub `intake_stub_value = round(intake_interest_rate_stub / 4.0, 6)` | QUARTERLY | `intake_rate / 4` | ✓ |
| python/client_intake_and_finmo/finmo_bridge.py | 3311 | seed-slots Q1-Q20 `values.append(round(interest_rate_baseline / 4.0, 6))` | QUARTERLY | `annual / 4` | ✓ |
| python/client_intake_and_finmo/finmo_bridge.py | 3346 | regular Q1-Q20 `values.append(round(interest_rate_baseline / 4.0, 6))` | QUARTERLY | `annual / 4` | ✓ |
| python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py | 246-254 | exact_updates `exact_value=forecast_interest_rate` for the skipped-no-debt case (writes for Q1-Q20) | QUARTERLY | `forecast_interest_rate` comes from `quarterly_rate_decimal` per the post-Phase 2-followup edit | ✓ |
| python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py | 292-300 | exact_updates per-quarter `exact_value=interest_rate` (= forecast_interest_rate = quarterly_rate_decimal) | QUARTERLY | none | ✓ |
| python/client_intake_and_finmo/numeric_execution.py | (downstream applier of exact_updates above) | Writes the QUARTERLY value into the row via the solver | QUARTERLY | none | ✓ |

### B2. Writers into the policy structure

| File | Line | What | Scale produced |
|---|---|---|---|
| python/client_intake_and_finmo/finmo_bridge.py | 3650-3660 | `next_payload["derived_driver_policies"]["debt_interest_rate_policy"] = {...}` | BOTH (annual_rate_decimal ANNUAL + quarterly_rate_decimal QUARTERLY) |
| python/client_intake_and_finmo/finmo_bridge.py | 1116, 1127 | `annual_rate = median_rate_pct / 100.0` and `source["annual_rate_decimal"] = annual_rate` | ANNUAL |
| python/client_intake_and_finmo/finmo_bridge.py | 1132-1138 | intake-fallback policy: `"annual_rate_decimal": round(intake_rate, 6)` from `annual_interest_payment / total_debt_outstanding` | ANNUAL |
| python/client_intake_and_finmo/finmo_bridge.py | 1151-1156 | second intake-fallback (no SBA rows): same | ANNUAL |

### B3. Writers into FINMO `debt_interest_rate` field

| File | Line | What | Scale produced |
|---|---|---|---|
| python/financial_model_engine/finmo_model.py | 654 (`debt_interest_rate=interest_rate`) | The FinmoQuarterResult dataclass field is populated from the local variable `interest_rate = quarter.expenses.interest_rate` (line 460), which reads the Interest Rate row | QUARTERLY (mirrors the row) |
| python/financial_model_engine/finmo_model.py | (Q0 stub) | Q0 has `debt_interest_rate=0.0` hardcoded — Q0 carries no interest computation | QUARTERLY (effectively 0) |

---

## C. READERS — every site that reads a rate value

### C1. Readers of `expenses::Interest Rate` row (via model_input lever_map or expense_rows)

| File | Line | What it does | Scale expected | Arithmetic | Contract-consistent? |
|---|---|---|---|---|---|
| python/financial_model_engine/finmo_model.py | 460 | `interest_rate = quarter.expenses.interest_rate` | QUARTERLY (applied per quarter at line 476-477) | none — applies `((opening+closing)/2) * rate` once per quarter | ✓ |
| python/financial_model_engine/finmo_model.py | 476-477 | `debt_interest_expense_only = ((debt_opening + debt_closing)/2.0) * interest_rate` and `lease_interest_expense = max(0.0, lease_opening) * interest_rate` | QUARTERLY | none | ✓ |
| python/financial_model_engine/finmo_model.py | 70 (`FORMULA_REGISTRY` comment) | Documents the formula as `... * expenses::Interest Rate` | implies QUARTERLY | none | ✓ |
| python/financial_model_engine/model_inputs.py | (`expenses.interest_rate` attribute resolver) | Reads `Interest Rate` row value into the `quarter.expenses.interest_rate` field used by FINMO | QUARTERLY | none | ✓ |
| python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py | 24, 240 | `INTEREST_RATE_LEVER_ID` lookup + `forecast_interest_rate = round(float(interest_rate_policy.get("quarterly_rate_decimal") or 0.0), 6)` | QUARTERLY (from policy.quarterly_rate_decimal) | none | ✓ |
| python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py | 282 | `interest_expense = int(round(((opening_debt + closing_debt)/2.0) * interest_rate))` | QUARTERLY | none — applies once per quarter | ✓ |
| python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py | 367-368 | `interest_rate_series = [round(float(value), 6) for value in (lever_map.get(INTEREST_RATE_LEVER_ID) or [])]` reading from model_input lever map | QUARTERLY | none | ✓ |
| python/client_intake_and_finmo/post_intake_cash/runner.py | 892 | `(lever_map or {}).get("expenses::Interest Rate")` reads the Interest Rate row series for the debt cash support multiplier | QUARTERLY | `1.0 - normalized_rate/2.0` (partial-quarter drag) | ✓ if the formula intends a per-quarter drag |
| python/client_intake_and_finmo/post_intake_cash/runner.py | 4107-4120 | `_solved_lever_value_map(...).get("expenses::Interest Rate")` for the per-quarter mismatch validator | QUARTERLY (compared against `quarterly_rate_decimal` per Phase 2 followup) | none | ✓ |
| python/client_intake_and_finmo/post_intake_cash/common.py | 263 | `(lever_map or {}).get("expenses::Interest Rate")` | QUARTERLY | (further inspection — see Track 3) | ✓ |
| python/client_intake_and_finmo/post_intake_solver/influence_map.py | 58 | Treats `expenses::Interest Rate` as a lever for the solver — no arithmetic | n/a (lever-id only) | none | ✓ |

### C2. Readers of `debt_interest_rate_policy` policy

| File | Line | What | Scale expected | Arithmetic |
|---|---|---|---|---|
| python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py | 150-182 (`sba_forecast_interest_rate_policy`) | Reads `annual_rate_decimal`; computes `quarterly_rate_decimal = annual_rate / 4.0` and emits both | ANNUAL→QUARTERLY | `/4.0` |
| python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py | 240 (`forecast_interest_rate = quarterly_rate_decimal`) | Reads policy's QUARTERLY scaled value | QUARTERLY | none |
| python/client_intake_and_finmo/post_intake_cash/runner.py | 4076-4106 | Reads `debt_rate_policy.get("quarterly_rate_decimal")`, fallback to `annual_value / 4.0` | QUARTERLY | `/4.0` fallback only | ✓ |
| python/client_intake_and_finmo/post_intake_cash/runner.py | 822 | Wrapper `_cash_strategy_sba_forecast_interest_rate_policy()` calls the debt_schedule policy helper | QUARTERLY (via the helper's output) | none | ✓ |

### C3. Readers of FINMO `debt_interest_rate` field

| File | Line | What | Scale expected | Arithmetic | Contract-consistent? |
|---|---|---|---|---|---|
| python/client_intake_and_finmo/post_intake_realism/schedule_sanity.py | 367 | `rate = _safe_float(row.get("debt_interest_rate"))` | QUARTERLY | line 377 multiplies by 4.0 to annualize for SBA band comparison | ✓ |
| python/client_intake_and_finmo/post_intake_capital_lease/schedule.py | 109-114 (`_interest_rate_from_finmo`) | Reads `debt_interest_rate` from first non-zero Q1+ FINMO row | QUARTERLY (used in snapshot construction) | none | ✓ |
| python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py | 380-382 | `interest_rate = round(float(row.get("debt_interest_rate") ...) or interest_rate_series[q-1], 6)` for build_debt_schedule_snapshot | QUARTERLY | none | ✓ |
| python/client_intake_and_finmo/post_intake_acceptance/gate.py | 386 | `_quarter_field(rows, q, "interest", "debt_interest_expense")` — note this reads `interest` (combined P&L total) first, falls back to `debt_interest_expense`; neither is the RATE field, so n/a for this audit | n/a | n/a | n/a |
| python/client_intake_and_finmo/post_intake_realism/formulas.py | (description comment) | References `debt_interest_expense` for derivation key — no arithmetic on rate field directly | n/a | n/a | n/a |

### C4. Readers of `intake_interest_rate_stub` (the intake-implied rate)

| File | Line | What | Scale expected |
|---|---|---|---|
| python/client_intake_and_finmo/finmo_bridge.py | 3175-3178 | `intake_interest_rate_stub = _ratio(annual_interest_payment, total_debt_outstanding)` | ANNUAL |
| python/client_intake_and_finmo/finmo_bridge.py | 3273 | Used at the Q0 stub write site (now divided by 4 per Phase 2) | converted to QUARTERLY |
| python/client_intake_and_finmo/finmo_bridge.py | 2104 | `interest_rate = float(expense_stub_by_label.get("Interest Rate") or 0.0)` — reads the Q0 stub value (POST-Phase 2 this is QUARTERLY) | QUARTERLY |

### C5. Capital lease readers/writers

| File | Line | What | Scale | Notes |
|---|---|---|---|---|
| python/client_intake_and_finmo/post_intake_capital_lease/schedule.py | 109-114 | `_interest_rate_from_finmo` reads from FINMO `debt_interest_rate` (Q1 first non-zero) | QUARTERLY | post-Phase 2 ✓ |
| python/client_intake_and_finmo/post_intake_capital_lease/schedule.py | 156-169 (`build_capital_lease_schedule`) | Per-quarter `interest_payment = float(round(quarter_opening * rate, 6))` | QUARTERLY (rate × opening once per quarter) | ✓ |
| python/client_intake_and_finmo/post_intake_capital_lease/schedule.py | 248-259 (snapshot row) | Emits `"interest_rate": round(float(rate), 6)` carrying the QUARTERLY rate forward | QUARTERLY | ✓ |
| python/client_intake_and_finmo/post_intake_capital_lease/schedule.py | 372-378 (validator) | `expected_interest = int(round(opening * rate))` validation | QUARTERLY | ✓ |

### C6. Workbook readers/writers of the Interest Rate row

| File | Line | What | Pattern | Scale | Notes |
|---|---|---|---|---|---|
| client_statements_output_excel/schedule_sheets.py | 440 | `rate_values = values_21((expense_by_label.get("Interest Rate") or {}).get("values"))` — reads Model Inputs Interest Rate row | reader | QUARTERLY post-Phase 2 | ✓ |
| client_statements_output_excel/schedule_sheets.py | 435, 453 | `interest_rate = ctx.schedule_row(DEBT_SHEET, "Interest Rate")` row, then `ws.cell(interest_rate, col, value=rate_values[idx])` writes the rate value into the cell | writer | QUARTERLY value written into the cell | ✓ |
| client_statements_output_excel/schedule_sheets.py | 454 | Debt Interest Expense formula `f"=(({local_ref(debt_opening, col)}+{local_ref(closing_debt, col)})/2)*{local_ref(interest_rate, col)}"` — **uses Excel cell reference** `local_ref(interest_rate, col)` pointing at the row written above | writer (formula) | QUARTERLY (via cell ref) | ✓ CELL-REFERENCE pattern — picks up changes to the Interest Rate cell in Excel |
| client_statements_output_excel/schedule_sheets.py | 491 | `interest_rate_values_lease = values_21((expense_by_label.get("Interest Rate") or {}).get("values"))` — reads same Interest Rate row values into a Python list | reader | QUARTERLY post-Phase 2 | ✓ |
| client_statements_output_excel/schedule_sheets.py | 519-520 | `rate_cell_value = interest_rate_values_lease[idx]` then formula `f"={local_ref(lease_open, col)}*{rate_cell_value}"` — **interpolates the Python list value directly into the formula string as a literal** | writer (formula) | QUARTERLY at build time | ⚠ HARDCODED-LITERAL pattern (see mismatches) |
| client_statements_output_excel/finmo_sheet.py | 178 (P&L Interest formula) | `={_mi(ctx, 'is::Interest Expense', col)}+{_mi(ctx, 'cash::Lease Interest Expense', col)}` — cell refs to Model Inputs cells | writer | mirrors the underlying Debt Schedule and capital lease rows (QUARTERLY scale) | ✓ |
| client_statements_output_excel/model_inputs_sheet.py | 226-232 | Writes `cash::` links for Debt Closing/Opening, Lease Closing/Opening, Lease Interest Expense, Lease Asset Depreciation as cell-reference formulas to the corresponding Debt Schedule / CapEx rows | writer | mirrors source rows | ✓ |
| client_statements_output_excel/checks_sheet.py | (existing checks) | No direct rate computation in checks sheet | n/a | n/a | n/a |

### C7. Other rate-shaped fields discovered

| Term | Where | Notes |
|---|---|---|
| `annual_interest_payment` | financials_json intake field; consumed only at finmo_bridge.py:3175-3178 to compute `intake_interest_rate_stub` | ANNUAL DOLLAR amount, NOT a rate. Out of scope for rate audit. |
| `interest_rate_baseline` | finmo_bridge.py local variable (3179, 3301, 3334) | ANNUAL — the SBA policy rate before Phase 2 conversion at the row write site. |
| `interest_rate_source` | finmo_bridge.py local + policy field | metadata dict; carries `annual_rate_decimal` |
| `intake_interest_rate_stub` | finmo_bridge.py:3175 local | ANNUAL ratio |
| `_RATIO_TOL_HIGH/MEDIUM/LOW` | post_intake_realism/schedule_sanity.py | tolerance values, not rates |
| `continuous_rate`, `daily_rate`, `monthly_rate` | NOT FOUND in any code search | no other scale fields present |

---

## D. MISMATCHES FOUND

### D1. Workbook lease interest formula — hardcoded literal pattern (⚠ but build-time-correct)

- **Location:** client_statements_output_excel/schedule_sheets.py line 519-520
- **Code:**
  ```python
  rate_cell_value = interest_rate_values_lease[idx] if idx < len(interest_rate_values_lease) else 0
  ws.cell(lease_interest, col, value=0 if idx == 0 else f"={local_ref(lease_open, col)}*{rate_cell_value}")
  ```
- **Behavior:** Python interpolates the rate value (`interest_rate_values_lease[idx]`, sourced from the model_input Interest Rate row) into the formula STRING as a literal. The resulting Excel formula is e.g. `=D18*0.025625` (post-Phase 2) or `=D18*0.1025` (pre-Phase 2).
- **Numerical correctness post-Phase 2:** The literal IS the per-quarter rate at build time because line 491 reads the (now-quarterly) Interest Rate row. So the workbook NUMERIC value is correct.
- **Mismatch with the debt formula pattern:** the debt Interest Expense formula at line 454 uses `local_ref(interest_rate, col)` — a true Excel cell reference. If a user edits the Interest Rate cell in Excel, the debt formula recomputes; the lease formula does not.
- **Doctrine pattern:** Pattern 1 (two paths compute the same conceptual quantity differently) — debt interest uses cell reference, lease interest uses literal. Mirror Flavor 1 would consolidate them into the same cell-reference pattern.
- **Scope:** workbook-builder only, two lines.

### D2. Workbook lease asset depreciation — hardcoded literal (⚠ but build-time-correct)

- **Location:** client_statements_output_excel/schedule_sheets.py lines 506-510 and 523
- **Code:**
  ```python
  lease_seed_value = number(schedules.get("lease_opening_balance_seed")) or 0
  per_quarter_dep_formula = f"({lease_seed_value if lease_seed_value else 0}/20)"
  ...
  ws.cell(lease_dep, col, value=0 if idx == 0 else f"=MIN({per_quarter_dep_formula},{local_ref(rou_open, col)})")
  ```
- **Behavior:** Python interpolates the lease seed value (e.g. 54000) into the formula string. Resulting Excel: `=MIN((54000/20),D24)`.
- **Numerical correctness post-Phase 2:** The literal IS the per-iter lease balance (P3.16 design — depreciate seed/20 over 20 quarters). So the workbook NUMERIC value is correct.
- **Mismatch with cell-reference pattern:** if a user edits the Lease Opening Balance cell in Excel, the depreciation formula does not update.
- **Doctrine pattern:** Pattern 1 again (same conceptual quantity, two paths) — could reference the cell `C18` (Lease Opening Balance Q0) instead of the Python literal.
- **Scope:** workbook-builder only, three lines.

### D3. Q0 stub Interest Rate value at finmo_bridge.py:3273 reads `intake_interest_rate_stub` not `interest_rate_baseline`

- **Location:** finmo_bridge.py:3273 (Q0 path)
- **Code:** `intake_stub_value = round(intake_interest_rate_stub / 4.0, 6)` where `intake_interest_rate_stub = annual_interest_payment / total_debt_outstanding` (the implied intake rate).
- **Behavior:** Q0 stub Interest Rate cell shows the intake-implied annual rate / 4 (e.g. 0.0125 for ExpressLogix's $25K/$500K = 5% / 4 = 1.25% per quarter).
- **Q1-Q20** Interest Rate cells show the SBA-policy rate / 4 (e.g. 0.025625 for the 10.25% SBA rate).
- **Mismatch?** No — this is intentional per the comment "stub Q0 remains intake history". Q0 reflects the intake input, Q1-Q20 reflects the SBA-backed forecast. Both are now correctly per-quarter.
- **Note:** the intake-fallback policy code at finmo_bridge.py:1132-1138 and 1151-1156 stores `annual_rate_decimal` ONLY (no `quarterly_rate_decimal` field is added in those fallback paths). If SBA lookup fails AND those fallbacks fire, the policy will carry annual but not quarterly. The downstream `sba_forecast_interest_rate_policy` at debt_schedule/schedule.py:150-182 would then compute `quarterly_rate_decimal = annual / 4` on the fly. So functionally these fallbacks still work, but the policy structure is asymmetric depending on which path populated it.

### D4. No app-layer reader expects ANNUAL from the Interest Rate row

All readers of `expenses::Interest Rate` row (lever_map, expense_rows, or via the `interest_rate` field in FINMO) apply the rate once per quarter without any /4 or *4 scaling at the read site. They are consistent with the QUARTERLY contract.

The only sites that DO scale are:
- `_check_debt_rate_realism` at schedule_sanity.py:377 — multiplies by 4 to ANNUALIZE for SBA band comparison. Expects QUARTERLY. ✓
- `sba_forecast_interest_rate_policy` at debt_schedule/schedule.py:150-182 — divides ANNUAL by 4 to derive QUARTERLY. Source-of-truth conversion. ✓
- `_cash_strategy_debt_cash_support_multiplier` at cash/runner.py:884-904 — divides QUARTERLY rate by 2 inside the multiplier formula `1.0 - normalized_rate/2`. The intent here is partial-quarter drag (cash effect of new borrowing within the same quarter is dampened by half-quarter average), not unit conversion. Worth a separate Track 3 audit of intent.

---

## E. Summary table of conformance

| Site class | Count | All consistent with PER-QUARTER contract? |
|---|---|---|
| Policy structure writers | 4 sites | ✓ (annual_rate_decimal annual; quarterly_rate_decimal quarterly; intake-fallback paths don't add quarterly_rate_decimal but downstream re-derives) |
| `expenses::Interest Rate` row writers | 5 sites | ✓ (all `/4` post-Phase 2 + Phase 2 follow-up) |
| FINMO `debt_interest_rate` field | 2 writers, 4 readers | ✓ (mirrors row) |
| Capital lease | 1 reader, 1 writer chain | ✓ |
| Cash pass policy reader | 1 site | ✓ |
| Cash pass debt support multiplier | 1 site | ✓ (separate intent check pending in Track 3) |
| Realism rate check | 1 site | ✓ |
| Workbook formula writers — cell-ref pattern | debt interest line 454, BS line 224, FINMO P&L line 178 | ✓ |
| Workbook formula writers — hardcoded-literal pattern | lease interest line 520, lease asset depreciation lines 506+510+523 | ⚠ numerically correct at build time; not Excel-cell-editable. Pattern 1 anti-pattern relative to the debt-interest path. |

---

## F. Conclusions

**The app-layer plumbing is consistent with the per-quarter contract.** Every writer of `expenses::Interest Rate` row produces QUARTERLY; every reader expects QUARTERLY. The realism check and cash-policy compare correctly. The policy structure carries both ANNUAL (`annual_rate_decimal`, for documentation) and QUARTERLY (`quarterly_rate_decimal`, for enforcement) explicitly.

**Two workbook formulas use hardcoded-literal interpolation** instead of Excel cell references: the capital lease interest formula (line 520) and the lease asset depreciation formula (lines 506+510+523). Both produce numerically correct values at build time post-Phase 2, but they break the "edit-in-Excel" affordance the debt-interest formula provides. They are a Pattern 1 anti-pattern.

**No silent annual-vs-quarterly mismatch is visible in any reader.** If the cash buffer violation in the lease-bearing ExpressLogix run originates from a rate-scale mismatch, the mismatch is not in this layer. Track 3 (cash pass machinery) and Track 4 (cash buffer violation root cause) will investigate further.

**One asymmetry note:** the intake-fallback policy paths at finmo_bridge.py:1132 and :1151 store `annual_rate_decimal` only. The structure is rebuilt with both fields at finmo_bridge.py:3650-3660, but if any path skips that rebuild, downstream readers using `quarterly_rate_decimal` directly would get None (the fallback at runner.py:4099 handles this; debt_schedule/schedule.py:240 reads quarterly_rate_decimal directly without fallback — would compute 0 if missing). Not a bug today, but a brittleness.

No fixes proposed in this memo per iter directive.
