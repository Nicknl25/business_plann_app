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
