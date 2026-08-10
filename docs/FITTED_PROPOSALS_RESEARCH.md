# FITTED PROPOSALS — research (NO BUILD; Nick rules before design)

Nick's assignment (2026-08-10): intake's proposed anchors must fit the client's
actual size/shape, because the proposal IS the plan for most clients (they
accept it; the client who most needs help is least likely to catch a bad
anchor). Hard line: FITTED PROPOSAL, NEVER JUDGED FINAL — the executive/post-
intake owns the plan; the fitting makes the starting point honest. Pattern:
the demand judge (GPT fits from real data, thin-evidence doctrine). Stub-only,
intake-only, post-intake untouched.

## 1. What intake proposes today, and where each number comes from

| Proposal | Source | Fit verdict |
|---|---|---|
| Revenue anchor (`revenue_intro` default) | the client's OWN ops drivers (price × capacity × utilization) | FITTED by construction |
| Payroll baseline (`current_payroll` default) | the canonical people rollup — the client's own roles/wages/rest-of-team | FITTED by construction (the one-door work) |
| Marketing baseline (`marketing` default) | the REVIVED demand machinery: census-grounded reach + GPT reasoning over stage/modality/capacity | FITTED — already the demand-judge shape, proven live |
| Suggested role wages (startups only) | people consultant `gpt_estimate` from business context; client-stated wages sticky; OPERATING businesses get NO suggested roles at all | Reasonably fitted; proportional by stage by design |
| **COGS baseline (`cogs` default)** | **PRIMARY: `industry_growth_table.industry_cogs_percent` — public-company quarterly-filing cost-of-revenue averaged by NAICS.** FALLBACK (no coverage): GPT materials-only estimate from full business context | **THE MISFIT — see §2** |
| Rent, opex, debt, cash, capex, employees, lease | ASKED, not proposed | no anchor to misfit |

## 2. The one real misfit: the COGS anchor (double mismatch, data-confirmed)

- The primary benchmark is **public-company cost-of-revenue**, which for
  labor-delivered services INCLUDES the service labor. Janitorial (561720)
  averages **88.2%** in the table — verified by query. Intake's basis puts ALL
  labor in payroll and COGS = materials only, so an 88% "COGS" anchor lands on
  a business whose true materials run ~5–10%. This is the exact janitorial
  case: not merely generic-for-size but **basis-mismatched** (labor-in-COGS
  filings vs materials-only intake) stacked on **scale-mismatched**
  (public-company shape vs a solo operator).
- Coverage is thin: **387 distinct NAICS** have data. Uncovered codes (F&F's
  311811, 812910…) already fall to the GPT fallback — whose prompt demands
  materials-only from the full business context. **The fallback is
  better-fitted than the primary.** The damage happens precisely where the
  cohort table HAS data on a labor-heavy service code.
- The labor-basis reconciliation (CW-002 Bluestem: `labor_treatment` echo,
  measured-basis arbitration) fixed the BAND's basis — the judge now judges
  honestly. But it never touched the PROPOSAL: the band can only honestly
  fail a stub whose COGS anchor came from the wrong basis. The stub is the
  damage; an accepting client ships it into post-intake.

## 3. The fix shape (demand-judge pattern, proposal-never-final)

Replace the raw primary with a **FITTED COGS PROPOSAL judge** at the existing
single seam (`_resolve_cogs_baseline_or_raise` → `_compute_cogs_baseline`):

- **Evidence in**: the cohort row AS EVIDENCE, explicitly labeled
  "public-company cost-of-revenue (includes their direct labor)"; NAICS +
  business type; the intake basis rule (all labor lives in payroll here); unit
  economics (price, what a unit physically consumes); scale/staffing shape
  (solo vs staffed, revenue).
- **Judgment out**: a materials-only COGS percent **band** + a basis string
  that must RECONCILE the cohort number ("filings show ~88% cost-of-revenue
  because their crews are in it; this file carries labor in payroll; materials
  for a janitorial operation run ~5–10%") — stamped into the provenance fields
  that already exist (`cogs_basis_naics`, `cogs_basis_rationale`,
  `cogs_basis_years_used`).
- **Thin-evidence doctrine** (non-negotiable, the demand-judge rule): no NAICS
  coverage + thin context → the judge says so and the estimate carries the
  fallback label it already has; a band no tighter than the evidence supports;
  never a confident point it can't defend. NOTE the stakes inversion Nick
  named: better-fitting proposals get accepted MORE — a wrong fitted anchor
  does more damage than an obviously generic one.
- **Proposal, never final** (the two-authority guardrail): the stage ack keeps
  offering it as a proposal the client owns ("typical for a business like
  yours runs X–Y; I'll start at Z — correct me if your materials differ");
  basis-tagged capture already governs corrections; the executive's own
  fitted-band machinery and the band judge stay the only verdict authorities,
  untouched.
- Design detail to settle at build time: a PROPOSED percent should stamp
  `cogs_basis = "ratio"` (a proposal is a ratio-anchor, not a client-stated
  dollar) — the stage applier's touched-set currently tags by whichever twin
  lands last.

**Wages (minor, optional)**: startup suggested-role wages are GPT-estimated
without OEWS grounding; the engine re-grounds wages via OEWS post-intake, so
the stub exposure is small. Could be OEWS-informed intake-side later; low
priority, listed for completeness.

## 4. Is the conversation one-size-fits-all? (Nick's unknown — checked, mostly NO)

Real proportionality already exists, by stage-branching:
- People: an OPERATING business gets no suggested roles at all (one
  rest-of-team total instead); startups get suggested year-1 roles.
- Rent/future-rent questions branch on operating vs pre-launch.
- The marketing estimator reasons from the business's actual stage, modality,
  and capacity (and its live F&F output talks like it knows she's a solo
  mobile groomer).
- Financials stage questions are fixed-text but size-neutral ("what do you pay
  each month…") — nothing talks to a solo operator like an enterprise.

**The misfit is in the NUMBER, not the tone.** One residual worth ruling on:
stage acks state anchors as flat fact ("I'll use direct costs of $X a year") —
a confident sentence around a misfit anchor is the accept-trap. The fitted
proposal plus a range-flavored ack ("typical for a business like yours…")
closes it; no broader conversation-proportionality work appears needed.

## 5. Blast radius — stub-only, intake-only, confirmed

- One authoring seam: `_compute_cogs_baseline` (single call site via
  `_resolve_cogs_baseline_or_raise`, used by the cogs stage default and stage
  message). Plus the cogs stage ack wording.
- The proposal flows into the financials stub exactly as today (same fields,
  richer provenance). Post-intake consumes the stub unchanged; its
  fitted-band/proportional-trajectory machinery is untouched; the engine is
  frozen. No new persistence shape.

## 6. Rulings for Nick

1. Fit the COGS proposal via the demand-judge pattern at the existing seam
   (cohort-as-evidence + basis reconciliation + band + thin doctrine)?
2. Range-flavored ack wording for proposed anchors (the accept-trap softener)?
3. Proposed percent stamps `cogs_basis="ratio"` (proposal ≠ client-stated
   dollars)?
4. Wages: park the OEWS-informed intake fitting as low-priority, or include?
