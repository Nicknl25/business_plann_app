# P3.40 Contract Layer — Closeout Summary

**Status:** Final cleanup pass complete. Awaiting web Claude
verification + cloud Claude audit before P3.40 contract layer
is declared FULLY COMPLETE.

This doc summarizes the 7-contract + 3-sub-contract-retrofit
P3.40 contract layer, the 6-commit R-residual cleanup pass,
and the final R-residual inventory.

---

## 1. Final test count

**637 P3.40 contracts suite tests passing** (post-Cleanup 5/6;
unchanged through Cleanup 6 which is documentation-only).

Adjacent build-mirror callsite tests: 18/18 passing (combined
total: 655).

P3.40 suite progression across the cleanup pass:
- Pre-cleanup baseline (post-Contract-5d series): 627
- Post-Cleanup 1/6 (R10/R11 silent-drop closures): 631
- Post-Cleanup 2/6 (R16 alignment + R9 assessed-no-change): 631
- Post-Cleanup 3/6 (legacy fallback assessments + R10/R11
  removal): 626 (-5 from dropped phantom-write test coverage)
- Post-Cleanup 4/6 (Contract 1 R1-R7 dispositions; doc-only): 626
- Post-Cleanup 5/6 (R8/R9/R17/R14 defense-in-depth): 637 (+11
  from new structural-invariant + classmethod test coverage)
- Post-Cleanup 6/6 (documentation closeout; doc-only): 637

---

## 2. 7 contracts + 3 sub-contract retrofits inventory

### Boundary contracts (7)

| # | Contract | Module | Boundary | Status |
|---|---|---|---|---|
| 1 | FinmoModelInputContract | `finmo_model_input_contract.py` | AMALGAMATED_SESSION → MODEL_INPUT | LANDED |
| 2 | WorkbookPayloadContract | `workbook_payload_contract.py` | FINMO_BUILD → WORKBOOK | LANDED |
| 3 | SolverInputContract | `solver_input_contract.py` | MODEL_INPUT → SOLVER | LANDED |
| 4 | SolverOutputContract | `solver_output_contract.py` | SOLVER → FINMO_BUILD | LANDED |
| 5 | IntakeDraftContract | `intake_draft_contract.py` | INTAKE → POST_INTAKE | LANDED |
| 6 | IndustryBaselineResolvedContract (multi-shape) | `industry_baseline_resolved_contract.py` | INDUSTRY_BASELINE | LANDED |
| 7 | AmalgamatedSessionContract (multi-shape) | `amalgamated_session_contract.py` | INDUSTRY_BASELINE → AMALGAMATED_SESSION | LANDED |

### Sub-contract retrofits (3)

| # | Sub-contract | Module | Retrofit Target | Status |
|---|---|---|---|---|
| 5b | OperatingModelJsonContract (4 sub-shapes) | `operating_model_json_contract.py` | `IntakeDraftContract.operating_model_json` | LANDED (fc91083) |
| 5c | TargetMarketJsonContract (4 sub-shapes) | `target_market_json_contract.py` | `IntakeDraftContract.target_market_json` | LANDED (8942527) |
| 5d | PeopleJsonContract (3 sub-shapes) | `people_json_contract.py` | `IntakeDraftContract.people_json` | LANDED (6c71a14) |

§0 value-constraint policy applied uniformly across 5b/c/d:
type STRUCTURE not VALUES; bare types only; no Literal
narrowing for enum vocabularies; no Field(min/max/pattern/
ge/le/gt/lt); no @model_validator content checks; no
@field_validator content checks. Structural cross-field
consistency invariants permitted (added in Cleanup 5 R8/R9).

---

## 3. R-residual total inventory

Counts across all 10 spec docs §8 sections (post-Cleanup 6 +
post-audit disposition updates):

| Disposition | Count |
|---|---|
| DONE (addressed in Cleanups 1-5 with SHA reference + P3.41 R-d-bis contract-typing portion) | 14 |
| ASSESSED + KEPT (investigated; no change warranted per directive's "do NOT force composition / removal" guideline) | 4 |
| DEFERRED (explicit rationale: no current use case / speculative defense-in-depth / depends on architectural fixes / intake-remediation workstream / etc.) | 47 |
| NOT PURSUED | 0 |
| **Total R-residuals across all 10 specs** | **65** |

**Post-audit accounting:**
- Original Cleanup-6 totals: 13 + 4 + 46 + 1 = 64.
- Contract 5 R11 (5e/f/g/h skip) reclassified NOT PURSUED → DEFERRED
  per cloud Claude reframing ("requires per-producer trace work"
  rather than "different pattern"). +1 DEFERRED, -1 NOT PURSUED, 0
  net change.
- Contract 5c R-d-bis newly tracked (target_market_summary parallel
  bug surfaced by intake-side research at 8a98e26). +1 DEFERRED,
  +1 total.
- Contract 5d R-d rationale rewritten (reclassified to intake-
  remediation workstream); bucket unchanged.
- Post-audit totals (pre-NexGen-E2E): 13 + 4 + 48 + 0 = 65.
- P3.41 NexGen E2E surfaced that R-d-bis was an actionable SPLIT, not
  a single deferred item: the contract-typing portion was independently
  fixable. R-d-bis CONTRACT-TYPING portion → DONE
  (target_market_summary retyped Optional[str] = None at
  target_market_json_contract.py to mirror Contract 5d
  key_people_summary at people_json_contract.py:294). R-d-bis GATE
  portion remains DEFERRED to intake-remediation workstream. +1 DONE,
  -1 DEFERRED. Post-P3.41 totals: 14 + 4 + 47 + 0 = 65 (R-d-bis still
  counts as one row, now with split-disposition).

### DONE inventory (13)

| Cleanup | Residual | Brief |
|---|---|---|
| 1/6 | Contract 6 R10 | cohort_query SQL persistence + Shape B contract amendment |
| 1/6 | Contract 6 R11 | naics_prefix_used + data_source surfaced in get_bands; Shape C amended |
| 2/6 | Contract 6 R16 | per-field composition assessment; naics_6 pattern dropped for §0 alignment |
| 2/6 | Contract 6 R24 | digit-length validation relocated upstream via R17 |
| 3/6 | Contract 7 R10 | RecentDecision + record_decision dropped (phantom-write removal) |
| 3/6 | Contract 7 R11 | sequence_position + budget dropped (phantom-required removal) |
| 5/6 | Contract 6 R8 | count_matches_bands_length invariant |
| 5/6 | Contract 6 R9 | cascade_payloads + get_bands_views key/value consistency invariants |
| 5/6 | Contract 6 R17 | _naics_6_from_ops length-warning at upstream producer |
| 5/6 | Contract 7 R14 | MirrorContract.from_mirror classmethod adapter |
| (retrofit series) | Contract 5 R8 | 5b OperatingModelJsonContract sub-contract retrofit |
| (retrofit series) | Contract 5 R9 | 5c TargetMarketJsonContract sub-contract retrofit |
| (retrofit series) | Contract 5 R10 | 5d PeopleJsonContract sub-contract retrofit |
| (P3.41) | Contract 5c R-d-bis (CONTRACT-TYPING portion only) | target_market_summary retyped Optional[str] = None to mirror 5d key_people_summary; surfaced by NexGen E2E; GATE portion still deferred to intake-remediation |

### ASSESSED + KEPT inventory (4)

| Cleanup | Residual | Rationale |
|---|---|---|
| 2/6 | Contract 7 R9 | Mirror.business_facts is flat draft-row columns, NOT 5b/c/d JSON content; zero structural overlap |
| 3/6 | Contract 5b R-a | ops_json naics_code/business_naics fallback chain kept for legacy DB support |
| 3/6 | Contract 5d R-b | post_intake_headcount role/name/months_until_hire fallback kept (directive flagged as classic legacy case) |
| 4/6 | Contract 1 R1 | to_model_input_json has test callers; tests block removal per Cleanup 3 precedent |

---

## 4. 6-commit cleanup pass summary

| # | SHA | Title | Scope |
|---|---|---|---|
| 1/6 | e0c06b1 | Contract 6 R10 + R11 silent-drop closures | SQL persistence of cohort_query + get_bands surfaces naics_prefix_used/data_source |
| 2/6 | 05a33ad | Contract 6 R16 + Contract 7 R9 inverse-retrofit assessment | naics_6 pattern alignment + R9 assessed-no-change |
| 3/6 | 0d48fac | Legacy fallback assessments + R10/R11 phantom-write removals | Mirror phantom-writes dropped; fallback chains KEPT for legacy support |
| 4/6 | c196ef0 | Contract 1 R1-R7 dead-code assessments | R1 ASSESSED+KEPT (test callers); R2/R3/R4/R6/R7 DEFERRED |
| 5/6 | d92bfe2 | Cheap defense-in-depth (R8/R9/R17/R14) | Structural cross-field invariants + length-warning at source + classmethod adapter |
| 6/6 | 4d59e3d | Documentation closeout | 10 spec docs §8 dispositions + this top-level summary |
| (post-audit) | (this commit) | Post-audit disposition updates | R-d reclassified to intake-remediation; R-d-bis tracked; R11 reframed per cloud Claude |

---

## 5. Post-audit intake-remediation handoff

Cloud Claude's post-Contract-7 audit (full text in conversation
history) flagged Contract 5d R-d (`key_people_summary` submission
gate) as broken production submission path. Claude Code VS's
intake-side research
([docs/architecture/intake_side_research_post_audit.md](intake_side_research_post_audit.md),
commit 8a98e26) established that:

- The pop machinery is intentional design (commit e57ff49
  single-source-of-truth).
- The bug class includes a parallel for `target_market_summary`
  (now tracked as Contract 5c R-d-bis).
- The proper fix is Option 3 (replace proxy-summary gate checks
  with structural checks on primary data).
- The fix requires intake-domain context and belongs to a
  separate intake-remediation workstream, not contract-layer
  cleanup.

Both residuals (Contract 5d R-d + Contract 5c R-d-bis) GATE
portions are reclassified from contract-layer cleanup to
intake-remediation workstream. Fix #1 and Fix #2 do not depend
on either gate-portion being fixed.

**Post-P3.41 update (R-d-bis split):** the NexGen E2E run on
2026-05-30 exposed an actionable contract-typing asymmetry:
Contract 5d had typed `key_people_summary` as `Optional[str] =
None` from the start, but Contract 5c left
`target_market_summary` as required `str`. The contract-typing
portion of R-d-bis was therefore independently fixable without
touching intake. That fix landed in P3.41 (target_market_summary
retyped to mirror 5d). What remains is:

- Contract 5d R-d → GATE portion only (financials.py:164 +
  intake_submit_service.py gate-reads on key_people_summary).
  Contract-typing was already correct in 5d.
- Contract 5c R-d-bis → GATE portion only (financials.py:95 +
  intake_submit_service.py gate-reads on target_market_summary).
  Contract-typing now fixed in P3.41.

Both gate portions need the same Option 3 fix (replace proxy-
summary check with structural check on primary data).

This handoff note exists so the intake-remediation pass starts
with explicit awareness of:

- The 2 parallel summary-field GATE issues that need Option 3
  treatment (contract-typing now symmetric across 5c + 5d).
- The design intent that must be preserved during the fix
  (single-source-of-truth via pop).
- The dual-handler split (LEGACY `target_market.py` +
  `people_capability.py` vs UNIFIED `intake_consult.py`)
  documented in §4 of the research doc.
- The frontend's use of the UNIFIED handler per the research.
- The `_SKIP_INTAKE_REMEDIATION_GATES` flag (default True)
  introduced in P3.41 commit 6a03377 — MUST be set False
  before any production submission path runs once Option 3
  lands.

---

## 6. Architectural milestone statement

**P3.40 contract layer end-to-end.**

Boundaries 1-7 contract-typed with:
- **Producer + consumer side enforcement** at every contract's
  gate sites
- **Adjustment B propagation**: ContractViolation surfaces as
  structured 500 through `intake_consult.py:7377` generic
  Exception catch (subclass of Exception, not RuntimeError —
  bypasses the line-7298 RuntimeError branch)
- **Single-PhaseCode-per-contract observability** with
  `diagnostic_data['shape']` discriminators for multi-shape
  contracts (Contracts 6 + 7)
- **Structural sub-contract retrofits** (5b/5c/5d) under §0
  value-constraint policy: type JSON SHAPE only, no VALUE-level
  content constraints

R-residual inventory (post-P3.41): 14 DONE + 4 ASSESSED-KEPT +
47 DEFERRED + 0 NOT PURSUED = 65 total. Every R-residual has an
explicit disposition recorded in its respective spec doc §8.
The 2 intake-side residuals (Contract 5d R-d + Contract 5c
R-d-bis) GATE portions are formally handed off to the intake-
remediation workstream per §5 above; R-d-bis contract-typing
portion landed in P3.41.

§0 policy held across 5b/5c/5d retrofits + R8/R9 structural
cross-field invariants in Cleanup 5: no Literal narrowing for
any enum vocabulary, no Field constraints (min/max/pattern/
ge/le/gt/lt), no @model_validator content checks, no
@field_validator content checks. Structural cross-field
consistency (length matching, key/value identity) permitted —
not value-level content.

PSL2 production-reality-wins applied across all retrofits:
nullable-required schema fields type as `Optional[X] = None`
for legacy-draft safety; production-popped fields
(`key_people_summary` since Contract 5d landing;
`target_market_summary` since P3.41 R-d-bis fix) type as
Optional despite schema-required; legacy fallback chains KEPT
pending DB audits rather than removed pre-emptively.

---

## 7. Verification status

**P3.40 contract layer FULLY COMPLETE.**

7 boundary contracts + 3 sub-contract retrofits done. 6-commit
cleanup pass done. Post-audit disposition updates applied per
cloud Claude + Claude Code VS findings. P3.41 NexGen E2E
surfaced + resolved the R-d-bis contract-typing asymmetry
(target_market_summary now mirrors key_people_summary as
Optional[str] = None at the contract layer).

Remaining intake-side work (Contract 5d R-d GATE + Contract 5c
R-d-bis GATE) explicitly handed off to intake-remediation
workstream with full design-intent documentation in §5 above
and in
[intake_side_research_post_audit.md](intake_side_research_post_audit.md).

Ready for Fix #1 (steady-state viability) and Fix #2 (headcount
derivation) to begin on top of this foundation.

Test suite: 637 P3.40 + 18 adjacent = 655 combined, all passing.

This doc is the input artifact for both.
