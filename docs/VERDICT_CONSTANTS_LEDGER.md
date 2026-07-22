# Verdict-Path Constants Ledger

**Purpose**: the durable artifact of the fragility-class workstream (2026-07,
commits `42af1b6` → `b7511cc`). Every constant that remains in or near the
verdict path is listed here with its classification and its stated reason.
Next time someone finds a constant in the verdict path, "is this rot or is
this deliberate?" has a written answer.

**The governing principle** (established by the workstream): a verdict
threshold must be a **true invariant**, a **scale-relative ratio**, or an
**executive judgment with the constant as judgment-absent fallback**.
Absolute margin points and absolute margin deltas are never verdict
thresholds. The executive margin-band judgment (locked, viability-blind,
railed, one call per run) is the carrier for business-grounded floors.

---

## 1. Converted to executive judgment (constants now fallback-only)

| Constant | Location | Judged replacement | Commit |
|---|---|---|---|
| `_GROSS_MARGIN_RECOVERY_FLOOR = 0.20` | realism/formulas.py | `gross_margin_floor_q11` (margin-band judgment) | `42af1b6` |
| `_FIXED_COST_BURDEN_INDUSTRY_MAX = 0.65` | realism/formulas.py | `fixed_cost_burden_max_q11` | `42af1b6` |
| Q20-holds 1pp absolute buffer | realism/formulas.py | subordinate to judged Q20 band low | `630b2d2` |
| Recovery-trend 2pp exception floor | realism/formulas.py | judged Q11 band low | `630b2d2` |
| Restructure solve: floors without ceiling | restructure/joint_solver.py | judged band target clamp + band-high moderation | `630b2d2` |
| `_NI_Q11_HEALTHY_FLAT_MARGIN_FLOOR = 0.02` | acceptance/gate.py | `ni_margin_floor_q11` (`flat_floor_source` in every verdict) | `b7511cc` |

The fallback constants above are DELIBERATE as fallbacks only: a missing or
failed judgment lands on the pre-workstream behavior. No business may ever
end up with no floor at all.

## 2. Deliberate constants — permanently, with reasons

| Constant | Location | Class | Reason it is NOT judged |
|---|---|---|---|
| `cash >= 0` (never-negative, loss-window-funded, cash-legitimate) | gate.py, formulas.py | true invariant | insolvency is not a business-relative concept |
| `current_assets > 0` | gate.py | true invariant | balance-sheet coherence |
| `ebitda_positive_by_q11 >= 0` | formulas.py | sign invariant | the universal Q11-positive doctrine; a sign, not a level |
| `_COVERAGE_FLOOR = 1.5` | gate.py | **the lender's seat** | DSCR floors express the LENDER's margin of safety, not the business's character. A judged coverage floor would let the executive negotiate the lender's side of the table — the one seat it must never sit in. (SBA min 1.15x; 1.25–1.5x conventional.) |
| `_INTEREST_REVENUE_RATIO_THRESHOLD_DEFAULT = 0.05` | gate.py | judgment-absent fallback | active only when no cash judgment exists (near-dead in practice) |
| Revenue-flatness `CV >= 0.02 OR delta >= 0.05` | gate.py | scale-relative | already ratio-shaped |
| Balance-sheet growth `<= 5x quarterly opex` | gate.py | scale-relative | ratio-shaped |
| `_MIN_DELTA_Q5_TO_Q11 = 0.02` (NI ramping disjunct) | gate.py | ramping-shape guard | untouched by Wave 2 deliberately; the flat disjunct is the judged one. Revisit only with evidence of a real business harmed. |

## 3. Parked open members — the class closed with TWO of these

| Item | State | Trigger to resume |
|---|---|---|
| **Debt-ceiling substitution** (debt stops at what the judged band services at 1.5x; owner equity funds the remainder, surfaced never silent; equity SIZE is the client's business, never a fail condition) | Built, compiled, **stashed** (`stash@{0}`), unvalidated — its motivating evidence (Meridian's coverage crisis) was an artifact of the G&A x12 harness bug | A genuinely debt-heavy business appearing in the fleet on honest data |
| **7% growth fantasy fence** (`_DEFAULT_QOQ_MAX = 0.07`, deterministic_revenue_proposer.py) — rails the growth judgment ONE-WAY: the executive may tighten the curve, never widen it | Deliberate for now; the safe direction on the axis where hockey sticks are the canonical lender red flag. Known limit: a genuine hypergrowth tiny-base business would surface it as a false negative | A real business on honest data whose market-grounded growth judgment exceeds the fence — then it gets the judged treatment against a real condition |

## 4. Scoping truth: the stage-ramp contract caps are AUTHORING SCAFFOLDING

Established by Wave-3 forensics (2026-07-22): the stage-ramp contract's
`rev_max` caps (and its `composite_revenue_ramp_is_binding` claim) bind the
**quarter-grid writer's proposed values only**. The FINAL landed trajectory
is routinely above those caps with zero violations recorded — including on
non-restructure plans (Meridian +20% Q2 and +10.4% Q5 vs a 5% cap; Sunny
+5.6% vs 5.0%) and on restructure plans (Understory +21.7% at Q6 vs 5%,
authored by the reviewer-approved directive). Later writers (cascade levers,
restructure consumption, capacity shaping, cash-pass effects) move revenue
after that gate.

**This is the coherent architecture, not a bug to "fix" by re-enforcement**:
the final trajectory's verdict authority is the acceptance/realism layer —
now judged and subordinated per this ledger — and it evaluated and passed
those trajectories. Re-enforcing the contract caps against final
trajectories would fail every currently-passing fleet business (the
hard-stop condition), which itself demonstrates the caps are scaffolding.
The contract's "binding" language overstates its scope; treat its caps as
constraints on the grid-authoring step, and the gate layer as the verdict.
The original "Q6 cliff" fragility (structural steps hard-failing plans) is
empirically absent on the clean fleet for this reason.

## 5. Standing watches

- **Band drift**: judged bands move when the judgment prompt evolves
  (re-rolls) — logged per wave, not chased. Same-prompt same-input
  determinism holds (locked calls). No verdict has ever flipped on drift.
- **Harness identity**: the bypass runs production's own finalize
  normalization (`89d43a1`). The harness converges to the app, never the
  reverse. Any new intake-side derivation must flow through
  `_sync_financials_consult_persistence_state` (or the harness inherits it
  automatically by calling it).
