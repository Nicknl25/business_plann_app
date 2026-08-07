# Engine/Finalize-Path Fragility Ledger

**Purpose**: the third proactive sweep (Nick, 2026-08-07) — after the
tripwire over-broad hold, the $5 lease exact-zero check, the marketing
absolute floor, and the ceiling informant-veto all failed real plans with
the SAME shape, this audits the verdict/engine/finalize path for the
remaining unfired members: (a) absolute thresholds that should be
scale-relative/derived, (b) exact-equality or sub-rounding tolerances on
rounded/float-summed money, (c) defaults overriding judgments.
**Status: RESEARCH ARTIFACT — rulings proposed, NOTHING converted; Nick
reviews per-item.** Companion: INTAKE_CONSTANTS_LEDGER (intake, done),
INFORMANT_AUTHORITY_LEDGER (cohort vetoes, done).

---

## 1. CONFIRMED CLEAN — the pattern already applied (no action)

`revenue_driver_formula_tolerance_for = max(0.015, |ref|×1e-8)` (both call
sites); `accounting_equation_tolerance = max($1, scale×1e-8)` (equation,
stored-totals companion, convergence gate — ruling 1a); capital-lease
`term_end_residual_tolerance` (derived from rounding-op count); judged
bands replacing constants across realism/acceptance with declared
fallbacks. These are the reference forms for every conversion below.

## 2. PROPOSED CONVERSIONS — exact-equality / sub-rounding class (b), priority order

| # | Site | Defect | Proposed form |
|---|---|---|---|
| E1 | `fail_fast.py:1566/1568/1570` statement math (`int(round(a)) != int(round(b))`) | exact equality on independently-rounded float sums; :1568 has 4 terms; :1570 is the zero-tolerance stored-totals twin of the check that ALREADY got the hybrid at :1680 | the accounting hybrid: `abs(a-b) > accounting_equation_tolerance(scale)` |
| E2 | `fail_fast.py:1955-1971` FINMO-vs-rebuild | **300 exact-equality money comparisons** (15 fields × 20 quarters); any 0.5-boundary straddle between two float pipelines kills the run | per-field `max($1, |value|×1e-8)` |
| E3 | `balance_sheet_driver_validation.py:604/754/795` | 5-rounding STD chain at tolerance 0; LTD 3-rounding at 1 (bound 1.5); stored-totals A=L+E 3-rounding at 1 | derived per-site: tolerance = roundings×0.5 floor, + relative term for :795 (it IS the accounting form) |
| E4 | `post_intake_debt_schedule/schedule.py:719/721/793/846-851` | exact-equality rollforward + snapshot-vs-FINMO at zero tolerance — the capital-lease file's treatment was never applied to its debt sibling | mirror the capital-lease derived tolerances |
| E5 | `post_intake_capital_lease/schedule.py:582/618/658` | residual members of the fixed file: 3-, 3-, and 6-rounding component sums vs flat 1 (:658 legit drift up to 3.0) | derived: roundings×0.5 (658 → 3) |
| E6 | `finalize_post_intake.py:288-320` revenue bundles | K per-bundle roundings vs flat $1 — a 3+-product business can legitimately exceed what a 1-product business never can (scale-with-COUNT, the lease lesson) | tolerance = K×0.5 + 0.5, derived from bundle count |
| E7 | `sanity_assertion.py:25` + `target_seeking_loop.py:38` + `orchestrator.py:49` | `1e-6` ABSOLUTE applied to dollar-scale metrics = exact equality at $M scale; feeds finalize RuntimeError and cascade triggers; declared three times | one shared hybrid `max(1e-6, |ref|×1e-9)`; single declaration |
| E8 | `finmo_model.py:142` `MAPPING_FORMULA_INT_TOLERANCE = 1` flat | marginal 2-rounding sites at bound exactly 1 | derive per call site (roundings×0.5); low urgency |
| E9 | contract percent bounds (`finmo_model_input_contract.py:322/396/471`, `fail_fast.py:1403` util > 1.0) | hard 1.0 with no epsilon — a quotient landing at 1.0000000000000002 rejects the contract | bound at `1.0 + 1e-9` (float-noise epsilon; NOT a semantic loosening) |
| E10 | `quarter_grid.py:2717-2721` envelope `±1e-6` | one absolute constant across dollars/counts/ratios | hybrid relative form |

## 3. PROPOSED FIXES — coherence class

| # | Site | Defect |
|---|---|---|
| E11 | `DAYS_IN_QUARTER`: 90.0 (`balance_sheet_driver_validation.py:23`) vs actual-calendar (same file :165) vs 91.25 (`evaluate_plan.py:240`) | **the cascade steers WC days toward a value the validator can then reject** — three quarter-length constants in one pipeline; unify on one authority |
| E12 | `evaluate_plan.py:181/183/193/195` hand-copied fallbacks of `gate.py` thresholds | if the gate's threshold ever moves, the cascade steers to the stale copy — import, don't duplicate |
| E13 | `formulas.py:1050` raw 0.02 healthy-floor inside the fixed-cost exception while the same function honors the judged band at :1028 | the judgment is honored for half the rule — consult the judged band in both halves |

## 4. FLAGGED — absolute-threshold class (a), each needs a business ruling

- `_MIN_EDITABLE_LEVERS_DEFAULT = 4` (`joint_feasibility_check.py`): a structurally simple business trips a fixed count. Propose: scale to applicable-lever catalog size, or ruling that 4 is a true floor.
- 365-day stage boundary (`quarter_grid.py:1502` + stage-family mismatch RuntimeError at :898): a hard calendar cliff that can hard-fail a contract authored across the boundary. Propose: derive family once, stamp it, compare stamps.
- `stub_revenue > 3.0 × first_live_revenue` (`fail_fast.py:1069`): deliberate (basis-class errors are 4x/12x/52x) — KEEP, watch for a seasonal-peak false positive.
- `structural_feasibility` 0.95 util / 0.05 buffer / Q12-20 mature window: documented deliberate; the mature-window start is the weakest (a long-build business is judged at quarters it hasn't reached). KEEP, watch-listed.
- `-$250k catastrophic liquidity floor` (`runtime.py:74`): already neutralized (cash-pass owns liquidity; result hardcoded passed) — KEEP as signal-only, note the dead constant.
- Cascade budgets/steps (35 calls, 15% relaxation cap, 3 cycles): recorded user decisions (§14.1/§14.5) — KEEP as declared policy.
- Contract structural minimums (`min_length=1` on debt rows etc.): a debt-free business must still emit a row-shaped section — KEEP (producers emit empty-shaped rows), watch.
- Acceptance-gate constants (coverage 1.5x etc.): ruled in VERDICT_CONSTANTS_LEDGER — unchanged.
- `schedule_sanity.py` docstring/code disagreement (docstring says one-violation-raises; code defaults warn-only): documentation fix.

## 5. Sweep verdict

The engine path is NOT clean: the exact-equality/sub-rounding class (§2)
has ten live members, several on the finalize kill path, and E1-E6 are the
same disease that killed Ironbridge's plan over $5 — dormant only until a
rounding boundary straddles. The clean pattern exists in-codebase (§1) and
every proposal reuses it. Nothing converts until ruled.

*Produced 2026-08-07 alongside the CW-017 ceiling fix.*
