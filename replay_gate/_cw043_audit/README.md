# CW-043 audit instruments (mini, 2026-08-24)

Scratchpad-born, committed so the evidence in HANDOFF.md is reproducible.
None of these is a gate leg; they are the instruments behind mini's audit of
0b26ce8 + 022542b (the frozen-capital-lease fix and its R32/R49 re-bless).

- `mini_cw043_harness.py <repo_root> <out_dir> [--tamper-paste] [--no-recalc]`
  BEFORE' (stored Halbrook ecd0e148 payloads through the new sheet code) and
  AFTER (principal row from the REAL bridge on tests/fixtures/cw043_halbrook_inputs.json,
  spliced, engine rebuilt, exported, Excel-recalculated). `--tamper-paste` is the
  literal-guard tamper test.
- `mini_cw043_compare.py <scratch_dir>` three-way compare delivered / BEFORE' / AFTER,
  formulas AND values, plus the recalculated Debt Schedule vs the engine's quarter_rows.
- `mini_draft_export.py <root> <draft_prefix> <out_dir> <tag>` + `mini_draft_compare.py <a> <b>`
  value-identity of one stored draft built under two trees (old baseline 3609fe6 vs HEAD).
  THIS PAIR FOUND THE HARROW (85f5825d) PAYOFF RESIDUE: sched+extra != engine take by
  one ulp at the payoff quarter, closing lands at 5.46e-12 instead of 0, and FINMO
  Interest Coverage / DSCR read ~1e17 where the old build read "-".
- `grid_drift_3609fe6_to_HEAD.txt` the `python -m replay_gate._grid_dump` leaf diff behind
  the 022542b re-bless: 438 changed + 85 added + 0 removed, every one on the Debt Schedule.

Run from the repo root with .venv python; the draft scripts need the DB (.env) and Excel.

## TURN A audit (mini, 2026-08-25) - dc4d4ef + 4037b70
- `mini_turnA_audit.py detect|tamper|sweep` - residue detector + exact by-address compare, the four-family
  formula tamper (Excel-recalculated), and the all-drafts engine sweep.
- `turnA_audit_evidence.txt` - every measurement behind the HANDOFF RESULT, incl. Bellweather 46ae584a
  (untouched by VS) carrying the live class on 0b26ce8 (129 crumbs / 42 blow-ups) and none on HEAD.

## Cash & Equity audit (mini, 2026-08-25, turn 7) - 7deaefa + be4978e vs b4949f3
- `mini_scan_equity.py` - every stored draft's Owner's Capital / Other Equity / Distributions series: where the
  engine steps (652 of 2006 drafts step at Q2+, 951 have Q1 != stub, 140 non-flat Other Equity).
- `mini_ce_audit.py <scratch> <draft>...` - claims (a)(b)(d)(e): exact by-address value compare of both
  recalculated trees, literal-vs-chain positions against the engine's own steps, Distributions literal + r57,
  every reader of the Cash Equity rows on the BUILT grid (old and new), Model Inputs Lease / FINMO lease rows.
- `mini_ce_demo2.py <scratch> draft:col...` - claim (c): type +40,000 into an Owner's Capital quarter on both
  trees, Excel-recalculated; shows the hold on the new build (post-step quarters) and the revert on the old.
- `mini_text_dump.py <rootA> <rootB>` - the R49 text-surface twin of `_grid_dump`: sha + address-keyed diff,
  every touched cell classified (moved-up-one / fell-off / other).
- `cash_equity_audit_evidence.txt` - every measurement behind the HANDOFF RESULT, drafts VS did not use:
  Sunny Glaze b944961a (Q1 != stub), Third Coast a051f479 (10 steps), Cedar Ridge 97a01a49 (Other Equity
  steps to 0), Northwind be1c0b1b (steps Q5-Q7), plus Bellweather 46ae584a per the standing rule.

## Cash & Equity option (B) audit (mini, 2026-08-25, turn 9) - 6cd654e + 628b7ee vs 7deaefa
- `mini_ce_B_population.py` - claim (h) my way: the EXACT emitted chain (stub literal; =prev; =ROUND(prev +/- |delta|,6) with
  Excel half-away rounding) evaluated in Python on every stored draft vs the engine series; also lists negative / Other Equity
  steppers for the sample pick, e-notation deltas, and off-6dp-grid values (2,006 drafts, 1,054 stepping, 0 misses, 0 off-grid).
- `mini_ce_B_audit.py <scratch> <draft>...` - claims (a)(b)(d)(e)(f): exact by-address value AND formula compare of both
  recalculated trees, the ROUND/=prev/stub shape parsed off the BUILT grid against the engine's own deltas, Distributions,
  the A2/B7/B8 wording, and the repointed Lease tie-out row + FINMO-vs-Audit-Source equality.
- `mini_ce_B_demo.py <scratch> demo draft:label:col:amount...` - claim (c) to Q20 on both trees (row delta, Total L&E delta,
  A=L+E, Checks!B2); `... tamper draft...` - claim (f): Model Inputs Lease literal +1,234.56, tie-out row + B2 read back.
- `mini_ce_B_enotation_probe.py` - Excel parses the 44 e-notation deltas (`+1.00000761449337e-06`) the emitter can write.
- `cash_equity_B_audit_evidence.txt` - every measurement behind the HANDOFF RESULT, drafts VS did not use: Cedar Ridge
  97a01a49 (Other Equity -7.39M to 0 at Q5), Orion 76915a55 (six negative steps Q15-Q20), Cedarhill 767dc360 (15 steps),
  plus Bellweather 46ae584a and Third Coast a051f479 (the task's demo draft); Halbrook only for the B2 OK->FAIL tamper.

## HORIZONTAL Payroll Schedule audit (mini, 2026-08-25) - 785c3bc + e5161d5 + b82788a
- `mini_hz_audit.py <scratch> <draft>...` - (a)-(e): old (730cb98) vs new (HEAD) recalculated builds; every sheet by address,
  Checks by label, old detail rows vs the hidden bridge value-for-value, block formula shapes, bridge own-block refs, SUMIFS /
  formula-count keying, amber census. FOUND F1: the per-role Wage Source header collapses the per-quarter owner-draw-deferred label.
- `mini_hz_typeover.py <new xlsx> <scratch>` - (b): Excel type-overs (FTE / wage / hires) in a block, delta traced to the summary
  and FINMO through the bridge.
- `mini_hz_mutate.py <HEAD worktree> <scratch> <bluestem xlsx>` - (g): five builder tampers under the committed test (T2 = the
  gap), the 13-role locator run, and a role-missing-a-quarter build on the real tree.
- `payroll_hz_audit_evidence.txt` + `payroll_hz_*_raw.txt` - every measurement behind the HANDOFF RESULT.

## Wage source PERIOD ROW + per-column bridge pin audit (mini, 2026-08-25, turn 12) - b35b4e8 + 5283f0c + 4730608 (F1), 236ac8b (F3)
- `mini_ws_audit.py <scratch> <draft>...` - (a)-(e) TEXT-AWARE: old (785c3bc) vs new (HEAD) recalculated builds; every sheet by
  address values AND formulas strings included; every Payroll Schedule diff classified (old col-B source cell gone / per-quarter
  cells added / bridge column N) with 0 unclassified; bridge N and the visible Wage source row vs the engine per-row label; block
  shapes; bridge own-block refs incl. N at its quarter column; SUMIFS / formula-count keying; amber census (2/role + 1/engine row).
- `mini_ws_mutate.py <HEAD worktree>` - (g): T2 + five T3 tampers anchored on the new column-14 line, run under the committed
  tests in a scratch worktree; reports which test goes RED for each.
- `payroll_ws_audit_evidence.txt` + `payroll_ws_*_raw.txt` - every measurement behind the HANDOFF RESULT, on the WHOLE
  owner-draw-deferral class VS did not use (06f9fcd9, 270e7b3a, 411adb55, 8d6beff7, b2500419, f8bc1b50, 7a489693, 8f395db0,
  aa58c32b) plus Bellweather 46ae584a. GREEN; D1 = VS declared a population run it did not make (closed by this audit).
