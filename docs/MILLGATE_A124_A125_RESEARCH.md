# A-124 (interest rate) + A-125 (payroll cross-section) — RESEARCH for Nick's ruling

Status: research, 2026-08-17, from the Millgate Press run (draft 2e198cbf,
run 3d4e1de9, HEAD d26a0e8). NOTHING BUILT. Cited to code, persisted
model_input/finmo, the live SBA table, and the delivered workbook.

## A-124 — INTEREST RATE: by design, genuinely SBA-derived, silent, with one real defect underneath

**Mechanism confirmed (Nick's belief is right):**
`finmo_bridge.py:1126 _sba_business_loan_interest_rate_and_source` — a real
DB lookup on `sba_loan_7a_raw`: match cascade exact NAICS-6 → 5/4/3/2 →
all 7(a) (`:1141-1148`); trailing 5 approval years (`:1155-1163`);
`InitialInterestRate` in (0,50], optional `ProjectState` (`:1170-1172`);
**median** (`:1116-1123`) ÷ 100 (`:1215`). No `0.09` literal anywhere;
the only fallbacks are to the client's stated rate (`:1239`, `:1264`).
Stub keeps the stated rate: `intake_interest_rate_stub =
annual_interest / total_debt = 9,000/120,000 = 0.075` (`:3606-3609`),
written /4 = 0.01875 (`:3704`); Q1..Q20 = SBA 0.09/4 = 0.0225 (`:3734`,
`:3769`). Provenance stamped in model_input
`derived_driver_policies.debt_interest_rate_policy`
(`sba_7a_business_loan_interest_rate_v1`, `driver_source
sba_loan_7a_raw`, `match_basis exact_naics_6`, naics 323111,
`approval_fy 2021-2025`, `sample_count 895`, `median_rate_pct 9.0`).

**9% is genuinely derived, not a flat default:** re-derived live against
the table — NAICS 323111, FY≥2021, n=895, median bucket 9.0000 (mean
8.59, range 1.75–15.5).

**BUT one real defect in the lookup inputs — state never reaches the
resolver.** `source_detail.state = null`: the resolver reads
`financials.state` / `ops.address_state` / `ops.state` (`:1131`), and
Millgate's `financials_json` has no `state` key while
`operating_model_json` carries none of those (the draft's
`address_state = 'Iowa'` lives on the draft row). So a NATIONAL median
was used. Iowa-specific median for 323111 FY≥2021 = **6.0% (n=9)** —
below the client's 7.5%. Two compounding issues: the field isn't
plumbed, and even plumbed it would arrive as 'Iowa' vs `ProjectState =
'IA'`. Also not keyed by loan size or term though `GrossApproval` /
`TermInMonths` exist in the table.

**Arithmetic correction to the finding as filed:** 9,900 ≠ 120,000 × 9%
(= 10,800). The debt schedule AMORTIZES (3,750/q Q1-Q3, 23,729 Q4;
interest = average balance × rate, `:4110`): Σ avg balances 440,010.5 ×
0.0225 = **9,900.24**. Like-for-like at the client's 7.5%: 440,010.5 ×
0.01875 = **8,250**. Pure rate effect = 1,650, not 900. Stub 2,250 × 4 =
9,000 = exactly the client's stated figure.

**Disclosure: SILENT.** Model Inputs row 18 source label "Debt Schedule
output"; Debt Schedule row 12 label "Interest Rate" source "Source rate",
renders 1.9% then 2.3% (quarterly, no annual anywhere); Audit Source has
dollars only; full-text scan for sba / 7(a) / stated rate / median = 0
hits; `financial_story` empty. Already classified in
docs/NI_TRAJECTORY_RESEARCH.md F-A (stub on a stated-interest basis with
no label). `docs/architecture/p3_19_debt_interest_rate_investigation.md:155`
anticipated the confusion ("rename to 'Quarterly Interest Rate'") — never
done.

**Verdict:** SBA mechanism as designed — YES; 9% genuinely derived — YES
(national median, 895 approvals); disclosed — NO. Park the disclosure for
Nick's later revisit as ruled. FLAG (not fixed): the state plumbing gap
is a real defect in the by-design mechanism (national vs Iowa median,
6.0%), and it happens to push the rate up.

## A-125 — PAYROLL: legitimate derivation, NOT a miscount — but the "1.1%" hides a 19% roster substitution

**The two numbers are different quantities.**
- 166,000 = client-stated GROSS wages: people_json Deshawn Vantrease
  (owner/GM) 66,000 + Roselle Kaddour (lead press) 48,000, both
  `client_override`, + `rest_of_team_payroll_year1` 52,000; financials
  `payroll_basis_people_roles` all 12/12 months, `payroll_adjustment 0`,
  owner comp 5,500/mo = the same 66,000 (not additive). Reaches the model
  ONLY as the stub: 41,500/q (`finmo_bridge.py:3691`).
- 164,104 = the engine's LOADED labor cost on a RECONSTRUCTED roster:
  `expenses::Payroll` `controller_write false`, `derived_driver
  headcount_schedule_derived`, values [41,500 stub, 41,026 ×4, 42,256 …];
  FINMO quarter_rows and Audit Source row 13 identical.

**Per-role Q1 (workbook Payroll Schedule):** Lead Press Operator 1.0 FTE
48,000 (client_override) → 14,640/q loaded; Owner/GM 1.0 FTE 66,000
(client_override) → 20,130/q; **Printing Press Operators 0.5 FTE 41,020
(`oews_title_catalog:oews_median`) → 6,255.55/q**. Q1 = 41,025.55.
Hires 0 every quarter, FTE 2.5 flat; 3% wage step at Q5. Neither named
person dropped or mis-summed.

**The engine's own provenance stamp** (`post_intake_headcount/schedule.py:3673-3697`):
doctrine "intake states WAGES; the Payroll line is LOADED labor cost";
`stated_annual_wages 166,000`; `q1_roster_annual_wages 134,510`;
`payroll_taxes_benefits_percent 0.22` (post_intake_headcount_policy_lookup,
rail 0.12-0.35); `q1_landed_annual_loaded 164,104`; `implied_load_factor
1.22`; `roster_vs_stated_ratio 0.8103`; `stated_fact_band [0.70,1.30]`;
`wage_adaptations []`.

**Arithmetic:** 66,000 + 48,000 + 20,510 (0.5 × 41,020) = 134,510 ×
1.22 = 164,102.20 → 41,025.55/q → rounded 41,026 × 4 = **164,104**.
Decomposition vs 166,000: rest-of-team 52,000 → OEWS 0.5 FTE 20,510 =
**−31,490**; +22% burden on 134,510 = **+29,592**; rounding +1.80 →
net −1,896. **Two large offsetting adjustments nearly cancel; the 1.1%
is a coincidence, not noise.**

**Mechanisms:** (1) burden ×1.22 uniform (ledgered HERETIC_LEDGER P1;
noted conflict: coherence gate tests at 1.0× while the engine lands
1.22×); (2) supporting-staff FTE is CAPACITY-derived — 390.17 capacity
units ÷ `capacity_units_per_supporting_fte` 780 = 0.5 FTE — and the
client's `rest_of_team_payroll_year1 = 52,000` is NEVER READ by
post_intake_headcount (zero hits in that package; only intake
capture/routing reads it); (3) OEWS median at `wage_positioning_tier
floor`, multiplier 1.0 (P2); (4) no phasing (Hires 0), rounding ±1.80,
no floor/adaptation engaged; (5) the `stated_fact_band [0.70,1.30]` guard
passed at 0.8103 — working as designed, but permitting a 19% silent
haircut of client-stated headcount spend.

**Authority per design:** the derived schedule (engine-owned,
`controller_write false`, `payroll_headcount_schedule_policy_v1`); the
narrative is the input fact, checked by the ±30% band (P6: "client-
authority enforcement, document the ±30%"; sticky-provenance at
`schedule.py:3661-3672`).

**Verdict:** legitimate derivation artifact — no fix on "the gap".
FLAGS for Nick (product judgment, not bugs): (a) the workbook discloses
the RESULT (per-role rows, wage source, benefits %, tier) but never
states "client said 52,000; model used 20,510" — same disclosure class as
A-124; (b) the client's stated rest-of-team payroll is discarded by
construction in favor of a capacity-derived FTE at OEWS median — the
band [0.70,1.30] is the only lever; if a 19% silent haircut of stated
payroll is out of tolerance, the band (or reading the stated figure as
a floor for supporting staff) is the decision.
