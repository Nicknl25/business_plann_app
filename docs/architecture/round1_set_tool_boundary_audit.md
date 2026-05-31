# Round-1 set-tool boundary audit (P3.41)

Discovery-only catalog of mismatches at the round-1 amalgamated set-tool
boundary. Triggered by four consecutive NexGen E2E STOPs (iters 6-9)
clustering in the same boundary with three distinct bug shapes. Scope
bounded to round-1 set-tools; round-2+ deferred until reached.

**Status:** DISCOVERY COMPLETE. No code fixes in this commit. Awaiting
Nick's adjudication on the JUDGMENT items before a batch-fix directive
lands the green-lit set with regression tests.

---

## 1. Round-1 set-tool inventory

Three set-tools invoked by [`post_intake_initial_grid/runner.py`](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py):

| # | Set-tool | Tool file | Envelope check | Producer / validator |
|---|---|---|---|---|
| 1 | `set_capex_rd_balance_seed` | [tools/set_capex_rd_balance_seed.py](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_capex_rd_balance_seed.py) | `_check_envelope_violations` (`mc`, `rd`, `bs` arms) | `_derive_maintenance_capex_percent_from_naics`, `_estimate_r_and_d_applicability_with_gpt`, `propose_balance_sheet_contextual_seed_payload` + `_finalize_balance_sheet_seed_with_critique` |
| 2 | `set_stage_ramp_contract` | [tools/set_stage_ramp_contract.py](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_stage_ramp_contract.py) | `_check_envelope_violations` (rev_max + ratio fields + util consistency + ni_floor) | `build_python_stage_ramp_contract` + `_validate_stage_ramp_contract_payload` |
| 3 | `set_payroll_schedule` | [tools/set_payroll_schedule.py](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py) | `_check_envelope_violations` (target_pct + roles + schedule) | `estimate_payroll_headcount_schedule_with_gpt` + `validate_payroll_headcount_contract_payload` |

Out of round-1 scope (verified):
- `set_drivers` ([tools/set_drivers.py](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_drivers.py)) — explicitly NOT round-1 per the comment at [post_intake_initial_grid/runner.py:1243](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1243): `"set_drivers(anchors=None) is by-design 'amalgamated_session_pending'; the cascade authors them via revise_drivers."`

---

## 2. Catalog of findings

### 2.1 RESOLVED (fixed in earlier loop iters; included for completeness)

| ID | Set-tool / site | Shape | SHA |
|---|---|---|---|
| R1 (iter 6) | FINMO_SYNC postcondition guard at [post_intake_initial_grid/runner.py:778](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L778) | Name-mismatch — required cols `{period, op_income, cash_end}` never emitted by producer; renamed to `{quarter_index, ebitda, ending_cash}` | `7262a25` |
| R2 (iter 7 Bug 1) | `set_capex_rd_balance_seed._maintenance_capex` caller at [tools/set_capex_rd_balance_seed.py:235-249](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_capex_rd_balance_seed.py#L235-L249) | Python defect — TypeError from `**builder_inputs` spread into a narrower callee. Fixed to explicit kwargs matching the R&D sibling. | `8d93950` |
| R3 (iter 7 Bug 2) | `_slim_balance_sheet_seed_proposal_for_contract` at [post_intake_contracts/runner.py:1502](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1502) | Python defect — NameError on undefined `_BALANCE_SHEET_SEED_CONTRACT_ROW_FIELDS`. Fixed by deriving the whitelist from the contract schema via new `_balance_sheet_seed_contract_row_fields()` helper. | `8d93950` |
| R4 (iter 8) | `_check_envelope_violations` mc arm at [tools/set_capex_rd_balance_seed.py:51-66](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_capex_rd_balance_seed.py#L51-L66) | Unit-mismatch — read percent-form `maintenance_capex_percent` against [0,1] ratio bound. Fixed to read `maintenance_rate` (the ratio canonical field). | `d904ce0` |

### 2.2 JUDGMENT (Nick adjudicates — multiple valid resolution shapes)

#### F-J1 (iter 9 known) — stage_ramp operational branch ignores `q11_to_q20_min_net_income_margin_floor` policy

- **Set-tool:** `set_stage_ramp_contract`
- **Producer site:** [`_stage_family_ni_floors` at post_intake_contracts/runner.py:1688-1695](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1688-L1695):
  ```python
  if str(stage_family).lower() == "operational":
      base = [0.0] * 4 + [0.02] * 16     # ← hardcoded 0.02; doesn't consult q11_min
      if bool(validator_rules.get("operational_requires_nonnegative_from_q1")):
          base = [max(0.0, v) for v in base]
      return base
  # (the non-operational glide branch at :1707-1710 DOES use q11_min directly)
  ```
- **Validator site:** [post_intake_contracts/runner.py:892-898](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L892-L898):
  ```python
  q11_min_floor = _safe_float(validator_rules.get("q11_to_q20_min_net_income_margin_floor"))
  if q11_min_floor is None: q11_min_floor = 0.0
  if quarter_index >= 11 and margin_floor < float(q11_min_floor):
      errors.append(...)
  ```
- **Policy source:** [post_intake_mapping.py:2956-2964](../../python/client_intake_and_finmo/post_intake_mapping.py#L2956-L2964) — SQL row may set q11_q20 floor higher than 0.02 (comment cites `0.07 for operational+rebalance`). NexGen lands on 0.05 → 10 violations Q11..Q20.
- **SHAPE:** Producer / validator-policy mismatch (the iter-9 shape).
- **UNIVERSALITY:** Every operational business whose policy resolves `q11_to_q20_min > 0.02` trips it. NexGen (b2b SaaS, operational, q11_min=0.05) is the first to reach it.
- **REACHABILITY:** Hit on NexGen. Likely hits any operational profile with a non-default q11 floor.
- **OPTIONS for Nick (no recommendation):**
  - (a) **Lift only:** change line 1692 to `base = [0.0] * 4 + [max(0.02, q11_min)] * 16`. Preserves 0.02 as the operational baseline minimum; lifts when policy is stricter. Smallest blast radius.
  - (b) **Use q11_min directly:** change line 1692 to `base = [0.0] * 4 + [q11_min] * 16`. The validator's policy becomes the single source of truth for operational; the 0.02 baseline becomes whatever the policy says.
  - (c) **Unify with glide:** drop the operational hardcoded base; route through the glide branch with operational-appropriate q1_min. Cleanest conceptually; biggest change; needs to confirm q10_min + operational starting values reproduce the Q1..Q4 = 0.0 baseline.
  - (d) **Policy is wrong:** if 0.05 is too strict for operational businesses, fix the policy SQL table (not the producer). The comment at mapping.py:2957 explicitly contemplates higher floors for operational, suggesting the policy is intentional — but Nick owns that domain call.
- **TRADEOFFS:** (a) preserves the historical 0.02 floor as a soft minimum the policy can never weaken; (b) makes the policy fully authoritative — operational businesses with q11_min=0.01 in a future policy would drop below 0.02; (c) eliminates the operational/glide producer asymmetry that caused this bug class; (d) avoids touching the producer entirely but means re-validating every operational policy floor.

### 2.3 CLEAN (unambiguous; ready for batch-fix when Nick green-lights)

#### F-C1 — stage_ramp envelope check reads `util_max`/`util_floor` but producer emits `max_util` (no `util_floor` at all)

- **Set-tool:** `set_stage_ramp_contract`
- **Envelope site:** [`_check_envelope_violations` at tools/set_stage_ramp_contract.py:40-43, :90, :107-112](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_stage_ramp_contract.py#L40-L43):
  ```python
  _RATIO_FIELDS_STAGE_RAMP = (
    "cogs_max", "marketing_max", "rd_max", "ga_max",
    "util_max", "util_floor",        # ← producer never emits these names
  )
  ...
  um = row.get("util_max"); uf = row.get("util_floor")
  if _is_finite_number(um) and _is_finite_number(uf) and float(um) < float(uf):
      violations.append({"code": "envelope_violation_util_max_below_floor", ...})
  ```
- **Producer site:** [`build_python_stage_ramp_contract` at post_intake_contracts/runner.py:2017](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2017): emits `"max_util": utilization_curve[q - 1]`. No `util_floor` is emitted anywhere in the producer or anywhere else in the stage_ramp emission shape.
- **Validator alias confirms:** [post_intake_contracts/runner.py:716](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L716) maps GPT `utilization_cap` → producer `max_util`. No `util_max` or `util_floor` alias exists.
- **SHAPE:** Name-mismatch — same shape as iter 6 (dead guard) but in an envelope check rather than a postcondition guard.
- **UNIVERSALITY:** Universal — every stage_ramp emission is silently NOT having its utilization checked. The ratio-bound check at line 101-105 (which would catch `max_util > 1.0` or negative) is also dead because the loop reads `_RATIO_FIELDS_STAGE_RAMP[idx]` = `util_max`, not the actual `max_util`. The `util_max >= util_floor` consistency invariant is also dead.
- **REACHABILITY:** Doesn't fire as a violation (dead check); but it doesn't PROTECT either. If a future producer change emitted a malformed `max_util` (negative or > 1.0), the envelope would silently miss it.
- **RECOMMENDED FIX (unambiguous):**
  - Replace `"util_max"` with `"max_util"` in `_RATIO_FIELDS_STAGE_RAMP`.
  - Remove `"util_floor"` from the same tuple (no producer emits it).
  - Remove the dead `util_max >= util_floor` consistency check at :107-112 (the comparison field doesn't exist). If a util-floor concept is desired in the future, that's a separate producer change first.
- **CLASSIFICATION:** CLEAN.

#### F-C2 — payroll envelope check has 3 dead subblocks (roles / wages / schedule)

- **Set-tool:** `set_payroll_schedule`
- **Envelope site:** [`_check_envelope_violations` at tools/set_payroll_schedule.py:34-91](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L34-L91)
- **Producer side:** Payroll producer emits `payroll_headcount_grid` with per-row keys `q`/`quarter_index`, `starting_fte`, `ending_fte`, `hires`, `payroll_tax_benefits_pct`, `staffing_class`, `oews_occ_title`, `position_title`, `person_name`, plus `target_payroll_percent_of_revenue` at the top level. Verified at [post_intake_headcount/schedule.py:364-403](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L364) and [:1895](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1895).
- **Envelope check coverage vs producer reality:**
  - `target_payroll_percent_of_revenue` (line 42-55) — **LIVE.** Producer emits, envelope checks [0, 1] ratio. Match.
  - `roles` / `role_specs` per-role `headcount`/`fte_count`/`wage_per_employee`/`wage` (line 57-77) — **DEAD.** `grep -rnE "\"roles\":|'roles':|\"role_specs\":|\"headcount\":|\"wage_per_employee\":|\"fte_count\":"` across `python/client_intake_and_finmo/` returns ZERO matches. No producer emits any of these keys. The whole role/wage block is silently skipped on every real payload.
  - `schedule` / `quarter_schedule` per-row `total`/`total_headcount`/`total_payroll_dollars` (line 79-90) — **DEAD.** Same grep result. No producer emits these top-level keys with this row shape. The schedule block is silently skipped.
- **SHAPE:** Name-mismatch — same shape as iter 6 / F-C1, but covering 2 entire subblocks. The envelope check looks like a structural sanity net but only the `target_pct` arm actually fires.
- **UNIVERSALITY:** Universal — every payroll contract has these checks skipped. A future producer emitting a negative `headcount` or a `total < 0` would NOT be caught here (it might be caught by the canonical validator at `validate_payroll_headcount_contract_payload`, but the envelope's stated purpose is the structural sanity net BEFORE the validator).
- **REACHABILITY:** Doesn't fire as a violation; doesn't protect either.
- **RECOMMENDED FIX (your call on extent — flagging the options instead of one definitive answer, since this trends toward JUDGMENT):**
  - (i) **Minimum — delete dead code.** Remove the `roles`/`schedule` subblocks (and the `_is_finite_number` helper if it ends up unreferenced). Honest: the check covers what the producer actually emits.
  - (ii) **Rename to the live field set.** Replace the role/wage check with a check against the actual producer fields (per-row `starting_fte`/`ending_fte`/`hires` non-negative + finite). Requires picking which sanity invariants to enforce (likely: all three are non-negative finite; possibly `ending_fte == starting_fte + hires` consistency). This is closer to the envelope's stated intent ("catch malformations") but trends toward judgment because the right invariants need design.
  - (iii) **Defer — keep dead code as documentation of intent.** Lowest risk; doesn't add value either.
  - I lean toward (i) as the CLEAN minimum (delete dead code that gives a false sense of coverage); (ii) is a value-add but trends toward JUDGMENT because it requires picking invariants. Treating (i) as CLEAN and (ii) as a follow-up improvement is the cleanest split.

### 2.4 CLEAN sub-checks (verified clean; no fix needed)

| Set-tool | Sub-check | File:line | Verdict |
|---|---|---|---|
| capex_rd | balance_sheet_seed `seed_value >= 0` envelope | [set_capex_rd_balance_seed.py:67-90](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_capex_rd_balance_seed.py#L67-L90) | Producer at [contextual_seed.py:476/489/507](../../python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L476) emits non-negative seed_value for all unit types; `>= 0` is a universal non-negative-magnitude floor. Match. |
| capex_rd | R&D `rd_payload` envelope by-design absent | param accepted at [set_capex_rd_balance_seed.py:42-46](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_capex_rd_balance_seed.py#L42-L46) | R&D producer at [post_intake_contracts/runner.py:1416-1426](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1416-L1426) emits `{contract_version, decision_source, r_and_d_enabled (bool), rationale}`. Zero numeric fields. By-design pass-through. |
| capex_rd | maintenance_rate producer range vs consumer range | producer at [post_intake_contracts/runner.py:1069-1131](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1069-L1131) clamps to `[_MAINTENANCE_RATE_MIN=0.02, _MAINTENANCE_RATE_MAX=0.15]`; consumer at [finmo_bridge.py:1266](../../python/client_intake_and_finmo/finmo_bridge.py#L1266) requires `0.02 <= rate <= 0.15`. Exact match. |
| stage_ramp | `rev_max` envelope (finiteness + non-negative + monotonic) | [set_stage_ramp_contract.py:65-88](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_stage_ramp_contract.py#L65-L88) | Producer at [post_intake_contracts/runner.py:2014](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2014) emits `rev_max`. Match. |
| stage_ramp | `cogs_max`/`marketing_max`/`rd_max`/`ga_max` ratio-bound envelope | [set_stage_ramp_contract.py:40-43, :90-105](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_stage_ramp_contract.py#L40-L43) | Producer at [post_intake_contracts/runner.py:2019-2022](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2019-L2022) emits all four. All ratios, [0, 1] bound matches. |
| stage_ramp | `ni_floor` finiteness envelope | [set_stage_ramp_contract.py:114-119](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_stage_ramp_contract.py#L114-L119) | Producer at [post_intake_contracts/runner.py:2024](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2024) emits `ni_floor`. Match. |
| stage_ramp | validator field-alias normalization (`q` → `quarter_index`, etc.) | [post_intake_contracts/runner.py:711-848](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L711-L848) | The alias map at :711-723 correctly translates every producer-side field name into the GPT-side names that the business-rule checks at :854-911 read from. No name-mismatch in this normalization layer. |
| payroll | `target_payroll_percent_of_revenue` [0, 1] envelope | [set_payroll_schedule.py:42-55](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L42-L55) | Producer at [post_intake_headcount/schedule.py:1895](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1895) emits a ratio via `_safe_ratio`. Match. |

### 2.5 REACHABILITY-FLAG (real mismatch but branch may not execute)

None. Every finding is either resolved, clean, or genuine judgment.

---

## 3. Summary count

| Category | Count |
|---|---|
| RESOLVED (no action) | 4 |
| JUDGMENT (Nick adjudicates) | 1 (F-J1: iter 9 operational floor) |
| CLEAN (unambiguous batch-fix candidates) | 2 (F-C1 stage_ramp util naming; F-C2 payroll dead subblocks) |
| REACHABILITY-FLAG | 0 |
| CLEAN sub-checks confirmed (no fix) | 7 sub-checks across all 3 set-tools |
| Total findings catalogued | 7 (4 resolved + 1 judgment + 2 clean-ready) |

---

## 4. Notes for the batch-fix follow-up

- The 2 CLEAN findings (F-C1, F-C2) are pure name-corrections in envelope checks — same fix shape as iter 6 (FINMO guard names). Single commit, regression tests asserting the corrected field names + assertions that producer emissions still pass.
- F-J1 needs Nick's call between (a)/(b)/(c)/(d) before any fix; the producer/validator-policy mismatch shape (iter 9) is the trickiest because it can hide a real domain choice about what the operational floor should be.
- The iter-8 ESCALATION flag is now resolved at the envelope-check level: 3 sibling envelope functions audited; 2 found dead/partial (F-C1 stage_ramp + F-C2 payroll); the capex one was already fixed in iters 7-8.
- Coverage limit: this audit covered envelope-check + producer/validator at the round-1 set-tool boundary. It did NOT audit the canonical validators in `post_intake_headcount/schedule.py` (payroll) or other deeper validators. Those are out of the round-1 set-tool boundary scope per the directive.
