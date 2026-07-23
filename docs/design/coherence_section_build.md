# Coherence Section — Build Architecture (design only, nothing built)

The coherence section is the interactive consultation loop that ends intake with a plan
that works. It is not a validation gate. Intake guarantees STRUCTURE; the engine authors
SHAPE. Coherence works the structural inequalities at the Q11 mature state and nothing
else.

**Q11 anchoring, confirmed explicitly (load-bearing):** every check reads the mature
state. Early-quarter losses are never evaluated and never flagged. A startup ramping
through Q1–Q8 losses is normal, expected, and the cascade/executive's job to shape —
coherence has no opinion about the ramp, only about whether the destination is a business.
This is what protects the client population we care most about (early-stage founders)
from being told their normal ramp is a problem.

**Funding is out of scope.** No check, no question, no gate touches capital access. The
serviceable-debt ceiling, substitution arithmetic, coverage, and loss-window all stay
where they live today (cash pass / acceptance). Coherence shows at most a transparency
readback of the capital going in and the debt/equity split — reflecting what the client
already told us, informational, never blocking.

**Unit sanity is not a coherence feature.** Basis restatement ("Rent's about $4,000 a
month, got it — so roughly $48K a year") is a general intake conversation principle at
every monetary capture. Coherence assumes bases are already settled.

---

## 0. Hard precondition — the closed-form v2 gate at 7/7 (Phase 0, before any build)

The loop's evaluator is `Test Files/_fcore_backtest.py`'s closed form: five binding
checks at Q11 (GM ≥ judged floor; fixed-cost burden ≤ judged max; EBITDA ≥ 0; EBITDA
margin ≥ judged band low; NI margin ≥ judged floor), each threshold read from the
margin-band judgment with doctrine-constant fallbacks, revenue grown from the stated base
under the 7% QoQ authorable fence.

It backtests today against the 7-business set (Sunny_V3, Glaze, Blueprint, Meridian,
Understory, Harvest Lane, Ironthread) but carries three known fidelity gaps that MUST be
closed and the set re-backtested to 7/7 before build starts:

1. **Engine-derived capacity ceiling.** Replace the flat `current_revenue` base with the
   same authoritative revenue the engine uses (`authoritative_annual_revenue` /
   `capacity_driven_annual_revenue`, structural_feasibility_check.py:88–171), so the
   ceiling is capacity×price×periods×utilization-derived, not snapshot-derived.
2. **Stage payroll.** Replace the flat `/4` payroll with the staged quarter basis the
   engine actually applies (cf. `_payroll_at_quarter` reading
   `payroll_headcount.quarter_totals`) — the flat basis is exactly what a startup's
   hiring ramp violates.
3. **Post-restatement G&A.** `other_opex_absolute` (or ×12 fallback) must match the
   engine's restated G&A, not the raw stated figure — the fcore disagreement probe exists
   because this term drifts.

Plus one hazard found in this research: **basis discipline on the corner.** The Glaze
lever-proof script fed an annual payroll figure where the evaluator consumed quarterly,
producing a −203.75% corner margin; recomputed on the solver's own loaded-cost quarterly
bounds the honest corner is ≈ −13% (still fails the +3% judged floor — verdict unchanged,
magnitude wrong by ~15×). The corner evaluator must run on the solver's own
`_base_levels`/burden-factor basis, never on re-derived units. Acceptance criterion for
Phase 0: all 7 verdicts agree AND the failing runs' gap magnitudes agree with the landed
FINMO rows within tolerance, not just the sign.

## 1. Where the checks run

New coherence controller inside the intake flow (`intake_consult.py` pattern — a section
frame like `financials_controller`/`people_controller`, plus a small pure-arithmetic
module, e.g. `python/client_intake_and_finmo/intake_coherence/evaluator.py` holding the
closed form so the backtest script and the live section import ONE implementation).

- `active_focus` gains a `coherence` stop between `financials` and `done`. The done flag
  can only be set from coherence status ∈ {converged, roadmap_accepted, parked_explicit}.
  That is the completion gate.
- **Monotonic surfacing.** The revenue ceiling is fixed at ops confirm; costs only
  accumulate through the financials stages. So the evaluator runs incrementally at every
  `_sync_financials_consult_persistence_state` pass: the moment the accumulated fixed
  floor exceeds the ceiling, FAIL is stable on that configuration and the section may
  open early ("surface FAIL immediately"). PASS is only surfaced once the last cost stage
  lands ("surface PASS at its firm-up point"). No verdict shown can flip on the same
  configuration.

## 2. The two GPT artifacts — made once, stamped, shared with post-intake

- **Margin-band judgment** (`gpt_author_margin_band_once`, seed-locked, viability-blind):
  coherence triggers the SAME F-core authoring the initial-grid runner performs today
  (initial_grid/runner.py:1120–1187), stamps the validated judgment to
  `model_input_json["solver_input"]["margin_band_judgment"]` keyed by
  `build_operating_model_digest(...)` (mirror.py:444–478). Post-intake finds the stamp
  fresh and consumes it — same artifact, not two calls. Invalidation is identity-level
  only: the compact digest changes (business/lines/market changed), never on knob changes
  (a price or cost edit re-evaluates, it never re-judges).
- **Restructure bounds** (`gpt_author_restructure_bounds_once` +
  `validate_restructure_bounds`): authored only when the closed form FAILS. The bounds
  box IS the lever vocabulary — per-line price/volume multipliers and can_drop, ≤3
  new-line candidates with market caps and margins, payroll/rent floors, COGS/marketing/
  G&A percentage floors, machine-railed. The client never sees a lever outside it.

## 3. Corner-first (silent, before any conversation)

On FAIL, before a word is shown: evaluate the closed form at each lever's NI-favorable
bound — exactly the seed the joint solver already builds (joint_solver.py:313–347: prices
at market ceilings, new lines at market caps, costs at floors, volumes held). Pure Python
on the solver's loaded-cost basis; milliseconds.

- **Corner passes** → guided lever walk. Convergence is structural: the walk explores a
  box whose best corner is known to clear, so the loop cannot dead-end.
- **Corner fails** → skip the walk entirely; open the roadmap conversation. Never grind a
  client through corrections that provably can't sum to viability (Glaze: best corner
  ≈ −$6.3K/quarter EBITDA vs a +$1.5K floor — short ~$7.8K/q at the ceiling).

## 4. The loop — deterministic Python drives, GPT phrases

State machine per round (all state in a `_coherence_state` frame persisted in the draft,
same underscore-key discipline as `_financials_revenue_intro_done`):

1. **Evaluate** (Python): closed form on current stated config → pass/fail + the gap in
   dollars per mature quarter: `gap = judged_floor(rev) − ebitda_q11` when positive.
2. **Select** (Python): one binding constraint at a time. Rank lever groups by
   dollar-gap-closure at their bounds (evaluate each group at its favorable bound, hold
   others); present the largest first. A founder shown one problem hears a shape, not a
   verdict.
3. **Present** (GPT phrasing only): the narrator turn is authored from a structured
   payload — constraint, the client's own numbers, 2–3 options each inside judged bounds,
   each option's computed gap effect. GPT phrases; it never invents a figure. Same
   naturalization pattern as existing consult turns.
4. **Client answers** → the EXISTING intent router with a `coherence_controller` frame
   (`current_question`, `patch_targets` = the lever fields in play) — the proven
   people_controller/financials_controller pattern, intent-interpreted, no phrase
   coaching, deterministic re-ask backstop with an app-authored marker.
5. **Apply** → the EXISTING scoped edit path. Price/cost levers patch their real intake
   fields; a new revenue line goes through the existing ops multi-LOB structure edit. No
   parallel write path — that rule exists because the harness divergence happened.
   (Riskiest integration point: new-line adds touch `operating_model_json`; they must
   flow through the same ops edit + re-sync machinery, which also refreshes the digest —
   and an identity-level digest change correctly re-judges the band.)
6. **Recompute** → sync runs, closed form re-evaluates, gap moves. Acknowledge movement
   in dollars ("that closes about 40% of the gap — $15,900 a quarter"). Repaint, next
   constraint or converge.

**Convergence:** all five checks pass on the stated configuration at its firm-up point.
Because Phase 0 proved the closed form faithful to the engine's verdict, a converged
intake hands post-intake a structure it will not reject — restructure demotes to safety
net for genuine engine-side drift (band-fit surprises), no longer the primary rescue.

## 5. The three honest exits

- **Converged:** transparency readback (including the informational funding line),
  intake completes, plan authored and emailed as today.
- **Client-parked:** the client declines to move any lever now. We do not ship a plan
  that says they fail and we do not bully. The draft stays open with the gap and the
  lever menu persisted; completion is explicitly deferred with a resume path. Register:
  "let's get this working first — pick it up whenever you're ready," never "error."
- **Roadmap (corner failed):** no plan is shipped. The conversation inverts from
  "adjust inputs" to "what would have to become true": each unsatisfiable constraint
  becomes a milestone stated in the client's own numbers (e.g. Glaze: a volume ceiling
  that moves — wholesale/standing accounts; payroll staged to revenue, not to the 5-role
  plan; a second high-margin channel proven, not assumed). Deliverable is the roadmap
  document; the draft's numbers persist so the same evaluation reruns when a milestone
  lands. This is honest by construction: it is the persisted `final_passed=False` truth,
  said in business terms while the client is still in the room.

## 6. Build phases (each ends with commit+push+email; Sunny_V3 canary after app changes)

- **Phase 0** — evaluator extraction + the three fidelity fixes + corner basis
  discipline; re-backtest 7/7 with magnitude agreement. HARD GATE.
- **Phase 1** — shadow mode: coherence evaluates + logs on every fleet intake, zero UI.
  Compare shadow verdicts against post-intake outcomes across the fleet.
- **Phase 2** — read-only reveal: mature-quarter P&L + gap hero surfaced at the
  coherence stop, no levers yet (keep-or-park only). Emotional register verified.
- **Phase 3** — the lever walk: bounds authoring on fail, corner-first, rounds through
  the router/edit path, convergence gating live.
- **Phase 4** — roadmap branch + parked exit + funding readback + restructure demotion.

## 7. Mockup

`docs/design/coherence_loop_mockup.html` — standalone, real numbers:

- **Understory Mushroom Co.** (draft 3464962b…, bounds 5dd5a321…): stated Q11 loses
  $36,188/q (−41.1%); judged band Q11 low +4%/high +14%; gap ≈ $39,700/q. The mockup's
  live arithmetic reproduces the real joint-solver landing exactly (prices ×1.2734/
  ×1.3906, CSA $21,094/q @65% GM, workshops $9,375/q @80% GM, payroll $37,992/q, rent
  $15,984/q, marketing 7.9%, G&A 12.31% → Q11 revenue $144,730, EBITDA +14.8%,
  moderated at the judged ceiling).
- **Sunny Glaze Donuts** (draft cc8b7081…, `final_passed=False`): the corner-fail →
  roadmap branch, computed on the bounds basis (best corner ≈ $48.7K/q revenue vs
  ≈ $55.0K/q costs at every believable limit).
