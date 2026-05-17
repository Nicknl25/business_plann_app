# P3.17 Phase 1 — Accounting Equation Investigation

**Iter:** Phase 9 P3.17 — Accounting equation hard fail-fast + capital lease BS reconciliation investigation
**Scope:** App-layer investigation of accounting equation invariant on the P3.16b lease-injected run.
**Investigated draft:** `5107f559865f45c9adec9f650a6741fb` (runner clone of the modified source draft `e112df06c6914889b1f104f05e97bcc0`; ExpressLogix Shipping Services with `initial_lease=4500.0` monthly → `lease_opening_balance_seed=$54,000`).
**Method:** Loaded persisted `finmo_json` from MySQL; computed per-quarter `total_assets` and `total_liabilities_and_equity` two ways: (a) summing raw component BS rows directly, (b) reading the stored totals. Cross-checked by directly re-running `calculate_finmo_model` against the persisted `model_input_json` to see what FINMO produces independently.

---

## Q1-Q20 result

**No accounting equation violation in Q1 through Q20** at either the component sum or stored totals level. The equation holds to the dollar at every quarter:

```
Q    component_A    stored_A    diff_A | component_L+E  stored_L+E   diff_LE | A-(L+E)comp  A-(L+E)stored
 1     3,849,645    3,849,645    0.00 |    3,849,645    3,849,645    0.00 |        0.00            0.00
 2     3,890,121    3,890,121    0.00 |    3,890,121    3,890,121    0.00 |        0.00            0.00
 3     3,962,479    3,962,479    0.00 |    3,962,479    3,962,479    0.00 |        0.00            0.00
 4     3,994,647    3,994,647    0.00 |    3,994,647    3,994,647    0.00 |        0.00            0.00
 5     4,030,695    4,030,695    0.00 |    4,030,695    4,030,695    0.00 |        0.00            0.00
 6     4,072,668    4,072,668    0.00 |    4,072,668    4,072,668    0.00 |        0.00            0.00
 7     4,115,307    4,115,307    0.00 |    4,115,307    4,115,307    0.00 |        0.00            0.00
 8     4,165,978    4,165,978    0.00 |    4,165,978    4,165,978    0.00 |        0.00            0.00
 9     4,232,221    4,232,221    0.00 |    4,232,221    4,232,221    0.00 |        0.00            0.00
10     4,320,209    4,320,209    0.00 |    4,320,209    4,320,209    0.00 |        0.00            0.00
... (Q11-Q19 same pattern) ...
20     5,298,792    5,298,792    0.00 |    5,298,792    5,298,792    0.00 |        0.00            0.00
```

Components used for A: `cash + accounts_receivable + inventory + prepaid_expenses + ppe + right_of_use_asset`.
Components used for L+E: `(accounts_payable + short_term_debt + deferred_revenue + long_term_debt + capital_lease_obligation) + (owners_capital + retained_earnings + other_equity)`.

The 9 existing capital lease validators correctly cover this scope (`capital_lease_obligation_at_q0`, `capital_lease_asset_at_q0`, amortization, depreciation-linear, interest-at-rate, interest-components-sum, depreciation-components-sum, principal-in-CF-financing, lease-obligation-zero-at-term-end), but they do NOT explicitly check the BS accounting equation row-level. They check the validity of the lease snapshot itself.

## Q0 finding — out of iter scope but real bug

Q0 (the stub period) does have a discrepancy. The iter explicitly checks Q1 through Q20 only, but the Q0 bug is worth recording because it is real and visible in the workbook.

At Q0 with the lease present:

| Field | Stored (in persisted finmo_json) | Direct FINMO recompute | Component sum (from stored rows) |
|---|---:|---:|---:|
| `total_assets` | 1,150,000 | 1,204,000 | 1,204,000 |
| `total_liabilities` | 620,000 | 674,000 | 674,000 |
| `total_equity` | 530,000 | 530,000 | 530,000 |
| `total_liabilities_and_equity` | 1,150,000 | 1,204,000 | 1,204,000 |
| `right_of_use_asset` | 54,000 | 54,000 | — |
| `capital_lease_obligation` | 54,000 | 54,000 | — |
| `retained_earnings` | -1,970,000 | -1,970,000 | — |

The stored Q0 has `total_assets = 1,150,000` and `total_liabilities_and_equity = 1,150,000`. They balance only because both sides dropped the $54,000 lease equally. The stored totals do not actually reflect the displayed row values (`right_of_use_asset = 54,000` on the asset side, `capital_lease_obligation = 54,000` on the liability side both flow through to the component sum at $1,204,000 but the stored totals are $1,150,000).

## Root cause of Q0 drift

`_build_balance_sheet_intake_stub_metrics()` at [finmo_bridge.py:2140](python/client_intake_and_finmo/finmo_bridge.py#L2140) computes a Q0 stub independently of FINMO and is unaware of the capital lease. Lines 2168 and 2177:

```python
total_assets = round(current_assets + ppe + accumulated_depreciation, 6)  # no ROU
...
total_liabilities = round(current_liabilities + long_term_debt, 6)  # no lease
```

`_apply_operating_stub_to_quarter_rows()` at [finmo_bridge.py:2210](python/client_intake_and_finmo/finmo_bridge.py#L2210) then `.update()`s the FINMO-produced Q0 row with these stub-metric values, overwriting the correct `total_assets` and `total_liabilities` that FINMO had computed.

The per-quarter FINMO loop (Q1+) is unaffected by this overwrite because `stub_index` only matches `quarter_index == 0`. That is why Q1-Q20 are consistent.

The overwrite landed in finmo_bridge well before P3.16 (it predates the capital lease integration). P3.16 added ROU asset and capital lease obligation to FINMO's Q0 stub correctly, but the downstream `_apply_operating_stub_to_quarter_rows` then strips them from the totals.

There is also a secondary issue in that same stub helper: `total_assets = current_assets + ppe + accumulated_depreciation` adds the accumulated depreciation to total assets. Since `accumulated_depreciation_opening_seed` is stored as a negative number, this functions as a subtraction — but it is a contra-asset that should already be reflected inside PPE, not a separate asset line. For ExpressLogix the seed is 0 so it has no effect here. This is mentioned for completeness; it is not in scope for P3.17 to repair.

## Drift origin classification

- **Not capital lease integration itself** — `calculate_finmo_model` produces a balanced Q0 stub when called directly.
- **Not PP&E or depreciation** — they are correctly carried through.
- **Not retained earnings** — RE is computed by FINMO based on the with-ROU total, and the stored RE matches the direct recompute (`-1,970,000`).
- **Yes from a pre-P3.16 stub-overwrite layer** — `_apply_operating_stub_to_quarter_rows` in `finmo_bridge.py` rewrites Q0 BS totals using a helper that has not been updated to include capital lease components.

This is doctrine Pattern 1 (two paths compute the same value, drift at the boundary): `calculate_finmo_model` is the canonical Q0 BS computation, but `_build_balance_sheet_intake_stub_metrics` is a parallel implementation that doesn't include lease lines. Mirror Flavor 1 (direct reference) is the right fix: stop computing a parallel Q0 stub and let the FINMO output stand.

## Iter-scope conclusion

- **Phase 2 (new fail-fast for Q1-Q20):** still warranted. The check passes today for the lease-injected ExpressLogix run, but having it in place is doctrine-aligned protection against future regressions. Q0 is not in the iter's check scope.
- **Phase 3 (root-cause fix):** the Q1-Q20 equation already holds, so Phase 3 is technically a no-op for the iter's scope. However, the Q0 drift is a real bug surfaced by this investigation. Recommendation: fix it in Phase 3 as the doctrine Pattern 1 mirror collapse, since the fix is small (delete the BS-related fields from the stub overwrite path and let FINMO's Q0 BS values stand).
- **Phase 4 (rerun with fail-fast active):** expected to pass clean. The fail-fast checks Q1-Q20 only; Q0 is correctly excluded.

## Existing validator coverage gap

The 9 capital lease validators cover the lease snapshot's internal consistency (opening/closing/principal/interest/ROU/depreciation per quarter). They do NOT cover the accounting equation invariant at any quarter. The new fail-fast in Phase 2 is the right place for that check — it lives one layer up from the lease-specific validators and verifies that the full BS the FINMO+lease produces is internally coherent.
