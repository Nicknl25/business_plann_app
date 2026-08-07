# Informant-Authority Ledger — who may veto whom

**Purpose**: the completeness sweep Nick ordered after CW-017's Vanguard
failure (2026-08-07): the cohort ceiling vetoed the manager's judged COGS
wall — the same "informant cannot veto the owner" principle Wave 2
(1b47199) established for floors, never applied to ceilings. Confirmed an
**unfired member, not a regression** (Wave 2's diff touches only the floor
branch and wrote the ceiling retention into its own docstring; the manager
wall was already feeding grid ceilings since 4c3a2cf, Jul-10). This ledger
lists EVERY location where cohort/informant data can veto, clamp, or
override an executive-judged, manager-fitted, or client-stated value — so
the class closes completely, not one member per burned run.

**The precedence doctrine** (from the existing demotions and Nick's
rulings): judged/managerial authority owns its seat; the cohort informs,
records disagreement, and recalibrates — it vetoes only where NO judgment
exists (raw-cohort fallback: the informant is then the only authority).
Client-stated facts are never silently discarded (THE RULING).

---

## 1. FIXED THIS SWEEP

**Stage-ramp CEILING veto** (`set_stage_ramp_contract.py`) — when the
manager's fitted per-quarter wall covers the field and the contract value
sits within it, a cohort ceiling breach demotes to
`stage_ramp_ceiling_above_cohort_band_advisory` (recorded, persisted, never
rejecting). Veto RETAINED on raw-cohort fallback and for values above the
manager's own wall (proven by negative controls). Both directions now
apply the 2dp grid-rounding tolerance (`_GRID_ROUNDING_TOLERANCE = 0.005`,
derived: half the authoring grid unit) — the Vanguard Q8-Q10 "breaches"
were the author's own round() and are suppressed for every authority.

## 2. ALREADY DEMOTED (the healthy precedent — unchanged)

Stage-ramp floors (Wave 2); realism WC checks muted under wc_judgment;
gross-margin proxy muted under margin-band judgment; cohort viability grade
wired advisory; business-shape conformance advisory ("references GROUND,
they don't GATE"); schedule sanity warn-only v3; payroll economic
feasibility advisory; cash-buffer verdict-not-crash; restructure fast-eval
advisory metrics; judged floors/ceilings replacing constants throughout
realism/acceptance (the direction-reversed set). Full citation list in the
sweep record.

## 3. CONVERTED — all three ruled by Nick (2026-08-07: "demote all three") and shipped

| Member | Fix (each with red→green + BOTH negative controls) |
|---|---|
| **Driver-anchor band veto** (`set_drivers.py`) | anchors within the manager's fitted per-quarter [min, max] wall demote to `driver_anchor_*_advisory` (both directions), recorded via runtime trace; raw-cohort fallback (no walls) KEEPS the veto, and an anchor above the manager's own wall vetoes. RED: 3 vetoes on manager-covered anchors pre-fix. |
| **Judged-growth qoq cap** (`contracts/runner.py`) | judged path governs `rev_target`/`rev_max` (peak + 0.03 headroom); the cohort's disagreement is a recorded advisory. RED: judged 12%/qtr was silently HALVED to the 6% cohort default. The 7% mechanical rail downstream is untouched (the deliberate one-way fence). NEG: with no judged stamp, cohort/default governs unchanged. |
| **Degenerate-anchor client-fact discard** (`band_fitting.py`) | low-side pre-arbitration posture is now `kept_union_span_fact_preserved` — the client's stated level anchors the target and stays inside the search range; ceiling keeps raw-cohort reach. With NO arbitration verdict the fact stays `credible: True` (an informant outage cannot delete a fact); an EXPLICIT executive "cohort" verdict retains removal power (the owner's seat). RED: `kept_raw_cohort_band` (fact erased) pre-fix. High-side behavior unchanged. |

## 4. RETAINED WITH REASON

- **Cohort-bands ABSENCE kills the run** (populator/mirror fail-fasts): plumbing integrity, not value authority — without bands the informant layer is broken, and that IS a machinery bug. KEEP.
- **Acceptance-gate cohort-provenance requirement** (`gate.py:636-667`): proves the informant layer ran; a run with no cohort provenance is a wiring failure. KEEP (note: it gates on presence, never on values).
- **Registry economic-envelope clamp** (`robust_bound_stage_ramp_contract`): canonical physics bounds (cogs ≤ 0.97 = 3% minimum gross margin), deliberately principled; clamps impossible values from ANY author including the manager. KEEP.
- **WC judgment rails / margin-band rails / manager-forecast fact-snap**: python-default rails over judgments are the deliberate railed-judgment design (judgments are railed, facts win, kill-guard) — the seat architecture itself. KEEP.
- **NAICS WC-days seeding over intake-implied days** (`contextual_seed.py`, `finmo_bridge.py:3686`): documented deliberate ("intake-is-noise-by-design" for these derived rows), counterweighted by wc_judgment at apply time. KEEP, watch.
- **Band-relaxation cascade tiers**: the mechanism by which a binding band is honestly widened under supervision — the pressure valve, not the disease. KEEP.

## 5. Cross-cutting: three precedence ladders disagree

Search/shaping layer: manager beats cohort. Authoring-tool layer: cohort
beat the executive (now fixed for ramp floors+ceilings; `set_drivers`
proposed). Verdict layer: cohort edges hard except the muted metrics.
Section 3 is the work-list that makes all three ladders agree.

*Produced by the CW-017 sweep (2026-08-07). Companions:
VERDICT_CONSTANTS_LEDGER.md, INTAKE_CONSTANTS_LEDGER.md,
ENGINE_FRAGILITY_LEDGER.md.*
