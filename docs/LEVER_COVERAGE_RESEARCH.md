# LEVER COVERAGE RESEARCH — three gaps, wall-cause → honest-lever (NO BUILD)

Nick's directive (2026-08-09): research the full lever picture — a lever must be
HONEST (never recommend harm from arithmetic, the cut-insurance disease) and must
respect what the executive/engine owns. Map wall/problem → honest lever for every
gap; flag where the honest answer is "surface it, point at the real fix, don't
offer a cut." Rulings pending; nothing built.

Companion state: the live-truth architecture is CLOSED (turn-anchored + rerun-
anchored, run-entry Recalc ac2022e); keystone 8/8 on the real F&F and Sparrow
drafts. This document is the next slate.

## Levers the walk offers today (for reference)

| Lever | Round | Bound by |
|---|---|---|
| Price (per line) | pricing round (mid/max + custom, clamped) | judged ceiling, dollar-absolute (`unit_price_at_authoring`) |
| Volume (per line, utilization-first) | volume round | judged `volume_multiplier_max`, units-absolute (`annual_units_at_authoring`) |
| New lines | new-lines round (offer-only → ops conversation) | judged caps + authored margins |
| COGS / marketing / G&A / rent / team-dollars | costs round | judged floors, deep-cut guard, client floors |
| Any stated fact | correction path (re-judges per Phase 2) | derivability + consent rails |

---

## GAP 1 — PAYROLL (doctrine ruling needed; top priority)

### Code facts

1. **The payroll-share wall block offers NO structured options.** Its priced
   exits (revenue ≥ X / team ≤ Y) land only if the client volunteers a
   correction (Sparrow's did — free-form, not an offer).
2. **The costs-round payroll move is an aggregate delta**; the fold materializes
   it as rest-of-team absorption first, then a PROPORTIONAL WAGE CUT across all
   non-owner staff (owner untouched by ruling). For a staffed business this is
   the machine proposing real people's pay cuts from arithmetic — the
   cut-insurance shape.
3. **Owner-only teams: the accepted move silently NO-OPS.** rest=0 and no
   non-owner wages → the fold has nothing to absorb into; `payroll_adjustment`
   retires to 0 and the cut evaporates after being acked
   (intake_consult.py `_sync_financials_consult_persistence_state`, fold branch).
   F&F-shaped drafts have a placebo lever.
4. **Hire timing already exists canonically**:
   `inferred_roles[].months_until_hire` (0–12) prorates year-1 payroll in
   `_compute_payroll_baseline`; the engine consumes it as fact (roles inform).
   It applies only to PLANNED roles — the data model itself cannot phase an
   existing person. Representable today; offered by nothing.
5. **Owner draw**: the one-door (`people.owner_pay_monthly`) exists and works,
   client-initiated only. The walk never offers it; the wall does not route
   owner-dominated cases to it.

### Wall-cause → honest-lever map

| Cause of the payroll-share trip | Honest lever | Today |
|---|---|---|
| Owner-dominated payroll (solo / owner is most of the number) | OWNER-DRAW option, priced ("your pay to $X/mo clears it"), one-door mechanics, explicitly the owner's own choice | door exists, never offered; machine move no-ops |
| Planned-but-unmade hires in the roster | HIRE TIMING — move `months_until_hire`, prorates year-1, cuts no one | representable, not offered |
| Existing real staff IS the payroll | NO cut offer. Surface the tension; point at price/volume; client-volunteered team changes respected via correction, never proposed | today's proportional-scale offer is the dishonest case |
| Revenue denominator wrong | correction; anchor-vs-ops holds cover it | shipped, proven |

### Doctrine options (Nick rules)

- **A. CAUSE-SPLIT (recommended, matches Nick's instinct):** the round reads the
  payroll basis rows (owner share, planned-role timing, staffed rest) and offers
  ONLY the honest lever for the actual cause; the proportional-scale fold is
  never OFFERED (kept only as materializer for client-volunteered aggregate
  statements).
- **B. Status quo + fix the no-op bug:** rejected by the principle; listed for
  completeness.
- **C. Informant-only:** no payroll offers at all — wall + revenue levers + free
  correction.

**Sub-ruling needed either way:** a STAFFED client volunteers "cut the team to
$X" (Sparrow's exact move). Today the fold lands it as unnamed per-person pay
cuts. Honest alternatives: ask HOW before landing ("fewer hours, a role change,
a departure?"), or land on rest-of-team only and hold if it would touch named
people.

---

## GAP 2 — OPEX / RENT / MARKETING (rounds exist; honesty audit per line)

- **Marketing — real reducible lever; KEEP; one caveat.** Usually genuinely
  discretionary, floored by a judged minimum. Caveat: with the demand machinery
  dormant, a marketing cut books as PURE SAVINGS — no modeled revenue
  consequence. Blind spot of exactly the distrusted shape; revisit the moment
  demand wakes.
- **G&A/opex — already honest (CW-022 #5).** Deep cuts (>50% of a stated line)
  never recommended, ask-what's-inside-first, client owns the line, judged
  floors. Keep as-is.
- **Rent — NEEDS THE LEASE GATE.** Rent is a commitment, not a dial. The move
  today offers "the space from X to Y/quarter" WITHOUT consulting lease status,
  though lease facts are captured (`initial_lease` stage, term fields); the
  client can only assert the floor AFTER being offered a cut on a signed lease —
  backwards. Honest shape: lease truth gates the offer — committed lease →
  surface-only ("your rent is fixed through the term; the movable levers are…");
  month-to-month/expiring → legitimate offer.

## GAP 3 — CAPEX (finding: no honest lever exists to build)

Intake captures only HISTORICAL capex (`current_capex`, `initial_assets`).
Forward capex is engine-authored (NAICS-derived maintenance %); its cash
consequences belong to the funding pass (Phase 6 ruling: funding out of scope).
Therefore: maintenance capex must never be a lever (cutting what keeps the
equipment running is the cut-insurance disease by definition); growth capex is
not client-stated, so there is nothing to defer. A defer/phase-capex lever would
first require NEW intake capture (planned purchases + timing) — a scope
decision, not a lever gap. **Recommendation: no capex lever; revisit only if
planned-capex capture is added deliberately.**

---

## Rulings on the desk

1. Gap 1 doctrine: A / B / C + the volunteered-aggregate-cut sub-question.
2. Rent lease-gate.
3. Marketing demand-coupling caveat: accept as known, or queue.
4. Capex leave-out.
5. The two STUCK Precision Aesthetics forked drafts (4de1d55c, 6d36e540) —
   at-rest flat-vs-product forks don't self-heal; client corrections ignored by
   all readers until restated.
6. (From the trajectory question) whether consuming the already-authored Q20
   band as a second evaluation point joins this slate.
