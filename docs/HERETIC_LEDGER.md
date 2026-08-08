# HERETIC LEDGER — CW-021

**The test (Nick's ruling, 2026-08-08):** for every hardcoded value that makes a JUDGMENT
ABOUT THE BUSINESS — what's an honest COGS, margin, cost ratio, growth rate, floor,
ceiling — ask ONE question: *does the executive already own this judgment?*
- YES → the constant is a redundant second authority (a **heretic**). Delete it, or demote
  it to the executive's judgment-absent fallback. The executive is the authority; the
  constant is at most a backstop when no judgment exists.
- NO → keep it ONLY with a written reason, and the reason must be (a) a **true invariant**
  (cash ≥ 0, A = L + E — a real boundary, not a business-relative guess) or (b) a
  deliberate **non-business seat** the executive must never occupy (the lender's 1.5×
  coverage margin is THE example).

**The owners (executive judgments that exist today):** `margin_band_judgment`
(q11/q20 EBITDA band, gross_margin_floor_q11, fixed_cost_burden_max_q11,
ni_margin_floor_q11), `judged_growth` (qoq_start/qoq_end), `fitted_bands` +
`fitted_envelope_per_q` (per-quarter cost targets/walls), `cash_judgment`
(buffer/ceiling months, surplus_priority, funding_access), `wc_judgment` (AR/AP/inventory
days, prepaid/deferred pct), `headcount_coherence`, lever-ceilings judgment,
owner-draw judgment. Plus the CLIENT (stated facts — never adjustable, the standing ruling).

**Precedent:** the basis-blind-floors fix (ac5276b) is the template for H-YIELD — the
registry cogs floor now yields to the manager wall / labor-converted band, provenance-gated,
and the negative control (garbage-low without provenance still floored) is proven both
directions.

**Proposed ruling classes:**
| class | meaning |
|---|---|
| **H-KILL** | heretic, delete (dead code or purely redundant with an always-present owner) |
| **H-DEMOTE** | heretic co-authority → becomes judgment-absent fallback (owner governs when present, explicit precedence in code) |
| **H-YIELD** | garbage-data floor/ceiling that stays, but yields to the owner when one covers the seat (the ac5276b pattern) |
| **ORPHAN** | business judgment with NO owner — needs a seat extension (design) or an explicit declared-universal entry; Nick rules |
| **KEEP-INV** | true invariant |
| **KEEP-LS** | lender seat |
| **KEEP-RAIL** | deliberate rail bounding the executive itself (self-consistency clamp on judgment authoring) |
| **DUP** | consolidation-only: same number as N literals → one shared named constant (orthogonal to class; no behavior change) |

Status of every row: **PROPOSED — nothing deleted or changed yet.** Build starts only on
per-item approval.

---

## Family 1 — GROWTH

| id | location | value | judgment / owner | current mode | proposed ruling + reason |
|---|---|---|---|---|---|
| G1 | `intake_coherence/evaluator.py:55` + `section.py:1000-1004` | `GROWTH_FENCE_Q11 = 1.07**10` | Q1→Q11 growth ceiling; owner `judged_growth` | **CO-AUTHORITY** — a first-attempt PASS is declared on the hardcoded fence even when a judged multiple exists (judged consulted only on WALKING or after a fence fail) | **H-DEMOTE**: when a judged growth stamp exists, the judged multiple IS the fence for pass and fail alike; 1.07^10 only when no stamp. (The 7%/q rail itself stays — see G2.) |
| G2 | `deterministic_revenue_proposer.py:43`, `revenue_critique.py:441`, clamps at `initial_grid/runner.py:1627-1691`, `gpt_growth_judgment.py:23-26` | `0.07`/qtr | the growth physics rail; binds judged rates | CO-AUTHORITY by design | **KEEP-RAIL** — CW-017 ruled it "the deliberate one-way rail." Q6-cliff work stays queued. **DUP**: two literals → one shared constant. |
| G3 | `post_intake_contracts/runner.py:2258` | `_JUDGED_REV_MAX_HEADROOM_QOQ = 0.03` | rev_max = judged peak + 3pp; fires only WHEN judgment exists | CO-AUTHORITY | **KEEP w/ written derivation, flagged**: documented as matching Phase B ceiling walls' max per-quarter revenue addition — it is the adaptation mechanism's own capacity, not a business guess. If Nick prefers, fold into the growth judgment prompt instead. |
| G4 | `runner.py:1671-75, 2112-17` | stage qoq fallbacks `{0.18/0.10/0.04}`, `*1.5` max, `0.05` default | owner `judged_growth` | FALLBACK (clean precedence proven) | **KEEP as declared judgment-absent fallback** (already demoted); ledger'd. |
| G5 | `runner.py:2117` | `qoq_spike_max = qoq_max * 1.3` | spike allowance | **DEAD** — assigned, never read (grid writes `rev_max`) | **H-KILL** (dead local). |
| G6 | `runner.py:772-773` | rev fields validator bounds `0.0 / 2.5` | 250%/qtr ceiling; registry rows carry no range | CO-AUTHORITY (vacuous width) | Note-only: effectively unbounded; declare registry ranges for rev fields or leave — no live harm. |
| G7 | `acceptance/gate.py:35-36` | flatness `CV ≥ 0.02`, `Q10/Q1 ≥ 0.05` | "a real plan grows"; owner `judged_growth` — never consulted | CO-AUTHORITY | **H-DEMOTE**: derive the flatness bar from the judged path when present (a judged near-flat mature plan must not fail its own judgment); constants only when no stamp. |
| G8 | `revenue_critique.py:40-41` | critique factor `0.90–1.10` | how far GPT critique may bend the judged path | CO-AUTHORITY | **KEEP-RAIL** (bounds the critic, not the business). |
| G9 | `post_intake_mapping.py:2893-2911` (stage policy F3/F4) | startup Q1-Q4 revenue fractions `{0.25,0.40,0.60,0.80}`, early `{0.55,0.70,0.85}` | early-ramp shape; owner `judged_growth` (partially) | CO-AUTHORITY (flows to quarter-grid context regardless of judged path) | **ORPHAN, declared**: docstring already declares them hand-calibrated. Propose: keep declared, add advisory when a judged path disagrees materially; seat-extension candidate for the growth judgment (queue). |

## Family 2 — COST-RATIO FLOORS/CEILINGS

| id | location | value | judgment / owner | current mode | proposed ruling |
|---|---|---|---|---|---|
| C1 | registry `post_intake_mapping.py:1954,1980` | `cogs_target [0.05,0.9]`, `cogs_max [0.2,0.97]` | honest cogs range; owners margin band + walls | lo: **H-YIELD shipped (ac5276b)**; hi: co-authority | lo: done. hi 0.97: **KEEP** (3% min gross margin, documented derivation vs trucking 0.963). |
| C2 | registry `:1988-2012` | `marketing_max 0.40`, `rd_max 0.50`, `ga_max 0.60`, `lease_max 0.50` | max honest ratios; owner walls | CO-AUTHORITY (hi never yields) | **KEEP hi as garbage-high protection** + add advisory-on-conflict when a manager wall exceeds one (wall above these is itself suspect; record, don't clip silently). |
| C3 | registry `:2024-25` | `ni_floor [-0.25, 0.15]` | the **0.15 cap CAPS THE JUDGMENT** — a judged mature floor above 15% cannot be expressed | CO-AUTHORITY over the owner | **H-YIELD (hi side)**: the cap yields UP to a judged ni floor when one exists; -0.25 lo stays as garbage protection with the same yield rule down. |
| C4 | `post_intake_contracts/runner.py:1903` sane-floor | `max(max_value, default_max)` | resolved cohort ceiling never tighter than default; owners walls/margin band | CO-AUTHORITY widener (converts every C5 default into an always-on floor) | **H-YIELD**: already yields on labor-converted (ac5276b). Extend: yield when a manager wall covers the metric (the wall proves the tight value is real). Raw-cohort-no-owner path keeps the guard (its original mismatched-segment purpose). |
| C5 | `runner.py:2125-2159` | builder defaults cogs `0.45/0.65`, mkt `0.08/0.18`, ga `0.12/0.25`, lease `0.05/0.12`, rd `0.04/0.10` | honest ratios; owners walls (via `_mgr_*`) | FALLBACK (clean) except via C4 | **KEEP as judgment-absent fallback**, contingent on C4's yield. Note: **lease has no `_mgr_max` call** — the wall never covers lease (seat gap, flag). |
| C6 | `quarter_grid.py:1244-1267` | cogs `[0.20,0.85]`, mkt `[0.01,0.35]`, rd `[0,0.35]`, ga `[0,0.40]`, other `[0,0.60]` + `max(min_value, maturity_cap)` | per-cell corridors; owner walls — **quarter_grid reads NO owner at all** | CO-AUTHORITY (the Peachtree disease one layer deeper: a fitted 0.11 wall raised back to 0.20) | **H-YIELD, priority**: corridors yield to the stage-ramp contract values (which are now owner-governed) — the contract IS quarter_grid's owner-visible surface. Verified not binding on the deterministic landing (Peachtree shipped 7.0-7.7% cogs) but live on the GPT grid path. |
| C7 | `quarter_grid.py:1269` | marketing floor `min(0.02, cap*0.25)` | every business spends ≥2% marketing | CO-AUTHORITY on top of wall | **H-DEMOTE**: wall/contract governs; floor only when no owner. |
| C8 | `band_fitting.py:51,557,566-568,897` | `±10%` search corridor, `±20%` Q1-vs-stated, `[0,0.95]` clamp, `0.1` half-width | corridor construction around the manager path | CO-AUTHORITY (these BUILD the envelope) | **KEEP-RAIL** (they construct the owner's envelope; the fitted path itself is judged) — flag the `0.10` half-width as a candidate for the band-author prompt. |
| C9 | `runner.py:1858` | `max = target*1.2` when band max missing | partial-coverage headroom | FALLBACK | KEEP (declared). |

## Family 3 — MARGIN / VIABILITY

| id | location | value | owner | mode | proposed ruling |
|---|---|---|---|---|---|
| M1 | `realism/formulas.py:957,997,837` | GM floor `0.20`, burden max `0.65`, healthy-flat `0.02` | margin band (explicit precedence) | FALLBACK (clean) | **KEEP as fallback** — already the model citizen; ledger'd. |
| M2 | `formulas.py:838` | retention fraction `0.5` | none (deliberately relative) | CO-AUTHORITY | KEEP-declared (documented as relative-by-design). |
| M3 | `adaptive_planning/industry_profile.py:34-51` | shadow copies: buffer months `1.5/×{1.5,1.0,0.7}/floor 0.5`, burden `0.65`, GM floor `0.20`, interest `0.09`, term `84mo` | margin band + cash judgment — **module reads neither** | DUPLICATE AUTHORITY (dormant external callers for cash fn) | **H-KILL the duplicate authority**: delete or reroute through the judgment-aware seams; per the remove-don't-route-around rule, delete the dead `cash_buffer_months_for_strategy` if truly uncalled. |
| M4 | `gpt_exhaustion_handler/mini_finmo.py:390-391,44` | healthy-flat `0.02`, retention `0.5`, Q20 tolerance `0.01` — **third copy, zero judgment wiring** | margin band | CO-AUTHORITY | **H-DEMOTE + DUP**: share formulas.py's judgment-aware helpers. |
| M5 | `restructure/joint_solver.py:49-52` | `_TARGET_LADDER` ni `0.03/0.07`, ebitda `0.06/0.11` | margin band — **ignored entirely** | CO-AUTHORITY | **H-DEMOTE**: the restructure solves to the judged band (floor = judged ni floor / band low); ladder only when no judgment. |
| M6 | `post_intake_mapping.py:4806-4930` planning-mode floor table | 36+ stage×window EBITDA floors | margin band; validator applies `max(judged, policy)` | CO-AUTHORITY (either may bind) | **RULING NEEDED**: policy floors are the planning-mode CONTRACT (turnaround tolerates losses, etc.) — arguably a deliberate policy seat, not a heretic. Propose: keep as policy seat, but when the judged floor is BELOW policy, record an advisory instead of silently binding (mirrors CW-017 ownership). Nick decides. |
| M7 | `runner.py:1786,1796` | startup/early ni: `-0.10` Q1-Q4, `+0.05` Q11→Q20 escalator | ni floor judgment | SOLE/CO-AUTHORITY (non-operational branch) | **H-DEMOTE**: derive from policy row + judged floor like the operational branch; hardcodes only when both absent. |
| M8 | `acceptance/gate.py:411` | ramp delta `0.02` Q5→Q11 | margin band (owns flat arm only) | CO-AUTHORITY | **H-DEMOTE**: judged floor derives the ramp bar when present. |
| M9 | `quarter_grid.py:356,428` | `ebitda > 0.30` ⇒ "overstated", route to normalize | margin band rails allow 0.55 | CO-AUTHORITY, in tension with the band's own rails | **H-DEMOTE**: consult the judged band before presuming a lie; 0.30 only when no judgment. |
| M10 | `viability/` package (`policy.py`, `gates.py:30-33`, `stage.py:41-46`) | PASS_REFINE `0.55`, health targets `0.25/0.50`, distress relax `0.15`, stage weights, breakeven deadline Q10+4+2, age bands 12/36/84mo | none — an entire second verdict layer | ORPHAN-SYSTEM | **ORPHAN, design-tier**: queue "viability consumes judged bands where they exist" as its own pass; do NOT patch constants piecemeal. |
| M11 | `solver/orchestrator.py:3363` | coverage `< 1.5` engages adaptation | lender seat (mirror) | CO-AUTHORITY | **KEEP-LS** + DUP (see L1). |
| M12 | `formulas.py:809` | lease amortizes ≥5% by Q20 | none | CO-AUTHORITY | ORPHAN-minor: keep-declared. |
| M13 | `acceptance/gate.py:419` | balance-sheet items ≤ `5.0×` quarterly opex | wc_judgment owns the drivers — not consulted | CO-AUTHORITY | **H-DEMOTE**: derive the ceiling from judged days when present. |

## Family 4 — UTILIZATION / CAPACITY / PRICE

| id | location | value | owner | proposed ruling |
|---|---|---|---|---|
| U1 | five sites: `deterministic_revenue_proposer.py:48`, `contracts/runner.py:1688`, `quarter_grid.py:1211/1213/1292`, `finmo_bridge.py:1108`, `headcount/lookup.py:633` | mature utilization `0.85` (+`0.84`×2, `0.95`×2, snap-back `0.70`) | **none — no utilization owner exists anywhere** | **ORPHAN + DUP, two steps**: (1) consolidate the pentad into one named constant set (no behavior change); (2) queue the design question "does utilization deserve a judgment seat?" — today it is the largest unowned judgment surface in the engine. |
| U2 | `contracts/runner.py:1679-83, 2041` | Q1 utilization `{0.25/0.45/0.65}`, 10-quarter ramp | none | ORPHAN: same seat as U1; consolidate + queue. |
| U3 | `gpt_lever_ceilings.py:45-50` | rails price `1.20`, capacity `1.50`, util `0.84`, payroll floor `0.50` | lever-ceilings judgment (which may only TIGHTEN) | **KEEP-RAIL** (documented one-way design). |
| U4 | `feasibility_restoration.py:70` | price cap `2.0×` | inconsistent with U3's 1.20 | **DUP/fix**: consolidate to the rail (1.20) unless the restoration cascade has a ruled reason for 2.0 — flag. |
| U5 | `quarter_grid.py:1216,1226-27,1236-40,1188,1276-82` | capacity growth `1.05/1.03`, Q1 corridor `±10%`, price drift `±2%/q`, generic `2×`, capital flows `4×/$1M` | judged growth / cash judgment not consulted | **H-YIELD family**: thread the stage-ramp contract (owner-governed) into the grid ranges — same repair as C6; capital-flow caps consult cash_judgment. |
| U6 | `structural_feasibility_check.py:39`, `feasibility_restoration.py:66` | `0.95` feasibility utilization | none | ORPHAN → U1 consolidation. |

## Family 5 — PAYROLL

| id | location | value | owner | proposed ruling |
|---|---|---|---|---|
| P1 | `headcount/lookup.py:66-68/643-645` + 3 inline `or 0.22` + coherence clamp `[1.0,2.0]` | burden `×1.22` universal ("fleet-verified at exactly ×1.22 on every business") | none | **ORPHAN, seat-extension candidate**: give the burden % to the payroll author GPT within the existing [0.12,0.35] rail (statutory floor documented). **BUG-adjacent conflict**: `intake_coherence/controller.py:551` tests coherence at burden `1.0×` while the engine lands `1.22×` — the gate is systematically optimistic on payroll-heavy businesses. Propose immediate H-DEMOTE of the coherence 1.0: pass the landed burden factor in. |
| P2 | `lookup.py:52-57` | wage positioning multipliers `1.0→2.5×` | none | **ORPHAN, biggest wage heresy**: unowned multipliers on top of OEWS. Propose: fold tier selection + magnitude into the wage-author/OEWS seam (Spec-2 adjacent), or declare with documented basis. Nick rules. |
| P3 | `lookup.py:634` | wage inflation `3%/yr` universal | none | ORPHAN: keep-declared (macro assumption, documented) or seat to payroll author. |
| P4 | `lookup.py:69` + 3 inline `or 25000` | min annual wage `$25,000` flat | none | ORPHAN + DUP: consolidate; keep-declared as national wage-floor backstop w/ basis note. |
| P5 | `lookup.py:72-79` vs `gpt_margin_band_judgment.py:69` | payroll % bands `0.06-0.80` vs burden rail `(0.30,0.90)` | headcount_coherence + margin band — **two seats, different numbers** | **H-DEMOTE/reconcile**: one authority for payroll-share sanity; the other becomes advisory. |
| P6 | `schedule.py:3695` | stated_fact_band `[0.70,1.30]` | client (stated wages) | KEEP-declared: protects client-stated payroll from reconstruction drift — client-authority enforcement, document the ±30%. |
| P7 | `lookup.py:642,652-53`, `schedule.py:655/670,1644` | benchmark ratio `0.75`, tolerances `0.03/0.20`, repair targets `±10%`, min FTE `0.05` | none | ORPHAN-minor: keep-declared, consolidate. |

## Family 6 — CASH / DEBT

| id | location | value | owner | proposed ruling |
|---|---|---|---|---|
| K1 | `post_intake_mapping.py:58-155` cash policy rows + `validation_envelope.py:146-150` + `debt_schedule/schedule.py:347-356` | floor/ceiling months per strategy (1.0→3.0) — **`min(judged, policy, balanced)` binds the crash gate and revolver paydown even when cash_judgment fired** | cash_judgment | **H-DEMOTE, priority**: judged buffer governs when present (policy may not pull the paydown floor below it, nor raise the crash floor above it); policy matrix only when no judgment. |
| K2 | same rows | surplus split weights (9 pairs) vs binary `surplus_priority` | cash_judgment (seat too narrow) + CLIENT strategy choice | **KEEP as client-preference mapping** (the strategy is the client's stated choice; weights are product design mapping it) — flag: extend `surplus_priority` to a fraction if Nick wants the executive owning the split. |
| K3 | `mapping` + `debt_schedule/schedule.py:118-123` | D/E cuts `0.50 / 1.00 / 999` selecting the policy row | none | **KEEP-LS-adjacent** (leverage classification is lender-vocabulary) + DUP: consolidate the duplicated literals. |
| K4 | `cash/runner.py:75,2313-15` + `or 1.0` copies | buffer `1.0mo` default + trace hardcodes disagreeing with enforcement | cash_judgment | FALLBACK: keep, DUP-consolidate; fix the trace to echo the enforced values (honesty of the emitted trace). |
| K5 | `cash/runner.py:1422-24`, `gate.py:418` | funding-access fallbacks (gaps ≥5, rate ≥3%, ratio ≥0.55; interest ≤5% rev) | cash_judgment (clean short-circuit proven) | **KEEP as fallback** (model citizens; ledger'd). |
| K6 | `cash/common.py:261` | debt-share enum `(0.70,0.50,0.30)` | client preference | KEEP (enumeration of client choice). |

## Family 7 — WORKING CAPITAL & DATA-TRUST

| id | location | value | proposed ruling |
|---|---|---|---|
| W1 | `finmo_bridge.py:3686-3717` | — | **CLEAN, exemplary**: fails loud (`*_no_coverage`) rather than substituting day defaults. |
| W2 | `industry_baseline/lookup.py:275-76` | generic WC defaults (0.15/0.225/0.30 etc.) | KEEP as last-rung cascade fallback (fires only when the full walk is empty). |
| W3 | `lookup.py:662-700` sector gates | inventory/deferred/R&D applicability by NAICS-2, default OFF | **H-DEMOTE**: a judged `wc_judgment.deferred_pct`/inventory_days must not be silently zeroed by a sector table — judgment wins, table advises (or asks). |
| W4 | `cohort_band_resolver.py:136-150` | revenue-window ladder, ≥2 firms, staleness ladder, tier Ns | KEEP: data-admissibility structure (which cohort is trustworthy), not business judgment; ledger'd. |
| W5 | realism tolerance tiers (`lookup.py:341-399`, `schedule_sanity.py:27-33`) | stage sensitivity ×, bps tiers | KEEP-declared (confidence-scaled tolerance system) + DUP: consolidate the duplicated ratio tiers. |

## Family 8 — INTAKE CAPTURE HEURISTICS (different genus: no executive exists at capture time)

`intake_consult.py` guard constants: derivability tolerance `0.005` (empirically tuned, documented), structure-fix `pre_gap>0.08` + (i2) `post_gap≤0.01` (documented fingerprint, replay-calibrated), basis fingerprint `±15%`, silent-absorb `0.87–1.15`, under-read asymmetry `0.5–0.87` silent, scope probe `≥1.5` / dominance `0.6`, marketing share `0.5%/1%`, 3× divergence ask, percent-window `>50%` implausible, capacity triplet `≤2%` family, near-price `±50%`, stream neighborhood `≤40%`, residual `1000/2000` cutoffs at 6264.

**Proposed ruling for the family: KEEP as declared capture heuristics** — they decide how to
READ the client, not what the business should be; no owner can exist before intake completes.
Ledger them with their empirical basis notes. **Four flagged for individual review:**
- `4876/4878` asymmetry: 2× over-read asks, 2× under-read stays silent — propose symmetric ask.
- `6213` `≤0.40` neighborhood — widest silent-steering tolerance in the driver path.
- `6123` `±50%` near-price band.
- `6264` residual absolute cutoffs (1000/2000) — inconsistent with Ledger 1b/1c's own conversion; convert same way.
- labor_basis `adj_max < 0.02` demote threshold (mine): propose re-derivation as `_MATERIALS_FLOOR + 2 grid units (0.01 + 2×0.005)` so the number is grid-derived, not chosen.

## Family 9 — COHERENCE VERDICT LAYER

| id | location | value | proposed ruling |
|---|---|---|---|
| V1 | `evaluator.py:475`, `controller.py:457,594`, `section.py:728` | assumed `50%` gross margin for unauthored new lines — reaches the roadmap-vs-walk decision AND is PRINTED to the client ("at 50% margin") | **H-KILL the fabrication**: require an authored margin (re-ask or bounds author) or render "margin not yet specified"; never print an invented number. The corner test uses conservative-direction handling instead of a favorable default. |
| V2 | `evaluator.py:384` | depreciation `= capex × 5%/q` (20%/yr) | ORPHAN: derive from the actual asset schedule the engine carries, or declare with basis; feeds the ni_floor verdict today, undocumented. |
| V3 | `controller.py:235,239` | "meet the market" = judged headroom `× 0.5`, marked `recommended` | product-design choice (the app endorses a price): flag for Nick — consultant Stage A adjacent, not a mechanical fix. |
| V4 | `section.py:655-666` | custom price clamped to `lo = current price` — client may never LOWER a price | **H-review, client-authority**: the client's own price is theirs; propose allowing decrease with an honest consequence re-eval (or an explicit ruled reason to keep the floor). |
| V5 | `evaluator.py:65-68` fallback four (GM 0.20 / burden 0.65 / NI 0.02 / band-low 0.0) | FALLBACK with documented reachability (judge-omitted fields) | KEEP as fallback; note `gpt_margin_band_judgment.py:505-509` drops a judged gm_floor below band low → the constant governs — flag precedence for review. |
| V6 | `evaluator.py:330` `min(2.0, cogs)`; `481` burden clamp `[1,2]` | ORPHAN-minor: keep-declared; the burden clamp resolves under P1's fix. |
| V7 | `section.py:1099` `$0.50` visible-progress epsilon | effectively a no-op epsilon — KEEP (note only). |

## Family 10 — LENDER SEAT (canonical keeps + one consolidation)

| id | location | value | proposed ruling |
|---|---|---|---|
| L1 | `acceptance/gate.py:564`, `cash/runner.py:1299`, `orchestrator.py:3363`, `evaluator.py:60` | coverage `1.5×` (4 sites, prose-synced) | **KEEP-LS + DUP**: ONE shared named constant (`LENDER_COVERAGE_FLOOR`); delete the dead evaluator export if unused. |
| L2 | `evaluator.py:58-59` | SBA rate `10.5%`, quarterly factor `0.0405` | KEEP-LS; `QUARTERLY_DEBT_SERVICE_FACTOR` has **no consumer** → H-KILL the dead constant. |
| L3 | K3's D/E cuts | `0.50/1.00` | KEEP-LS-adjacent + DUP (see K3). |

## Family 11 — TRUE INVARIANTS (kept, listed)

cash ≥ 0 (`gate.py:511`); current assets > 0; trailing/cumulative EBITDA ≥ 0 *levels* (`viability/gates.py:95,124`); A = L + E (`balance_sheet_driver_validation.py:777-809`, $-tolerance float-noise-only per the constants ledger); horizon/lockstep/days-in-quarter invariants (`workbook_payload_contract.py`); wage > 0, burden ∈ [0,1] domains; `_FINALIZE_HORIZON = 20` structural.

## Family 12 — RAILS ON THE EXECUTIVE (kept, three flagged)

`gpt_margin_band_judgment.py:60-70` (band rails), `gpt_cash_judgment.py:66-71`, `gpt_wc_judgment.py:57-63`, `gpt_owner_draw_judgment.py:43-46`, `gpt_headcount_coherence.py:44-49` (≤60% cut), growth clamp [0, 7%]. **KEEP-RAIL** as self-consistency clamps on judgment authoring. **Flagged for review:** (a) `q11_low` upper rail 0.35 / `q11_high_max` 0.55 cap what the executive may believe about a genuinely high-margin business — and sit in direct tension with M9's 0.30 "presumed lie"; (b) registry `ni_floor ≤ 0.15` (C3) caps the judged floor; (c) `gpt_margin_band_judgment.py:505-509` dropping a judged gm_floor below band low (V5).

---

## Structural repairs (cross-family, the three patterns that mint heretics)

1. **`max(hardcode, resolved)` outranking patterns** — `runner.py:1903` (C4) and `quarter_grid.py:1267` (C6): the two sites where a constant structurally outranks a resolved/judged value. Both get the H-YIELD treatment.
2. **quarter_grid judgment-blindness** — zero references to any owner; every corridor operates blind. Repair: the stage-ramp contract (already owner-governed post-ac5276b) becomes the grid's authority surface.
3. **Literal duplication drift** — 0.85×5 (+0.84×2, 0.95×2), 1.5×4, 0.22×4, $25k×4, 1.0mo×4, healthy-flat trio, burden/GM duplicate pairs, price 1.2-vs-2.0. Consolidation pass (DUP) is behavior-neutral and prevents the next drift bug regardless of other rulings.
