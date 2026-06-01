# P3.32 K13 — Fix 4 (H4↔H2 revenue reconciliation) + Fix 3 (H2 viability floor) design note

**Grounding (finalize validator `assert_stage_ramp_revenue_path_applied`):**
for each Q2..Q20 the committed live-forecast revenue QoQ growth (2dp)
must be **≤ rev_max** (always) and **≥ rev_target** (only when the model
has NO payroll-supported capacity; with Handler C payroll present the
target floor is subordinate — only the max ceiling binds). B1 =
committed revenue growth violates this band; dominant cause is growth
**above rev_max**.

## Fix 4 — what the reconciler computes
After H2 commits drivers and FINMO is rebuilt, read committed live
revenue `rev[1..20]`. For q in 2..20, compute `g = round(rev[q]/rev[q-1],2)`:
- if `g > rev_max[q]`: revenue grew too fast → scale `rev[q]` down to
  `rev[q-1]*(1+rev_max[q])` by reducing that quarter's **utilization_rate**
  (the direct, bounded [0,max_util] revenue lever; capacity is
  payroll-supported and price is intake-anchored, so utilization is the
  free knob). Cascade: later quarters recompute off the adjusted level.
- if `g < rev_target[q]` AND no payroll-supported capacity: scale up to
  target (raise utilization toward max_util). With payroll capacity
  present this branch is skipped (validator subordinates target).
Rebuild FINMO; re-check; bounded iterations (≤ a few passes — each pass
is monotone toward the band). Operates within driver bounds only.

## Priority rule when H4 ramp and H2 driver-reality conflict
**H4 ramp is the authority.** It is the validator's reference and is now
deterministically valid (Fix 2). H2 drivers yield the revenue *level*
but must respect the ramp's growth *band*; the reconciler adjusts H2
(utilization) DOWN to the ramp, never raises the ramp. The ramp is
adjusted only in the degenerate case where respecting it makes viability
unreachable — but §10.2 forbids an infeasibility escape, so instead we
respect the ramp and hand the reconciled revenue to the Fix 3 floor to
find the best in-bounds cost configuration. No NAICS branch.

## Fix 3 — what the H2 viability floor computes (given reconciled revenue)
If no H2 probe reached `all_pass`, the floor takes the reconciled revenue
trajectory as fixed and sets the **cost ratios** to achieve viability:
start each cost ratio at its contract target (cogs→cogs_target,
marketing/sga/rd at low end), build anchors, run `mini_finmo`; if
`ebitda_positive_by_q11` / `ni_floor` still fail, step the cost ratios
DOWN toward their mins (within cogs_max etc.) until `all_pass` or bounds
are exhausted. Commit the verified-viable anchors instead of GPT's
non-viable best-effort. **Lock-on-viability:** once a probe (GPT or
floor) is `all_pass`, it is the commit; later worse probes never
override it (the session already keeps most-recent-all_pass; the floor
extends this to "if none, synthesize one").

## Worked example — Sunny Glaze Donuts (bakery turnaround)
- H4 ramp (Fix-2-valid): rev_max ≈ 0.06/q; payroll capacity present →
  target subordinate, so the 0.06 ceiling binds.
- Pre-fix: payroll-capacity-driven revenue grew >6% in some quarter →
  finalize B1 (`stage_ramp_revenue_path_not_applied`).
- **Fix 4:** for each quarter where `g_2dp > 0.06`, drop that quarter's
  utilization so `rev[q] = rev[q-1]*1.06`; rebuild → revenue path now
  inside the band → B1 cleared.
- **Fix 3:** on the reconciled revenue, set cogs ≈ 0.55 (≤ cogs_max),
  marketing/sga/rd at low end; `mini_finmo` confirms Q11 EBITDA ≈ +6.9%
  (matches the observed best probe) and ni_floor satisfied → `all_pass`.
  Commit the floor. Run lands: revenue-path band + viability both pass.

**Compose order:** Fix 4 runs first (reconcile revenue to the ramp), then
Fix 3 (viability floor on the reconciled revenue). Both are Pattern-2
deterministic, both commit only validator-confirmed output (§10.6).
