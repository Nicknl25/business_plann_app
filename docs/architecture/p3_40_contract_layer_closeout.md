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

Counts across all 10 spec docs §8 sections (post-Cleanup 6
final dispositions):

| Disposition | Count |
|---|---|
| DONE (addressed in Cleanups 1-5 with SHA reference) | 13 |
| ASSESSED + KEPT (investigated; no change warranted per directive's "do NOT force composition / removal" guideline) | 4 |
| DEFERRED (explicit rationale: no current use case / speculative defense-in-depth / depends on architectural fixes / etc.) | 46 |
| NOT PURSUED (5e/f/g/h python-aggregated track skipped per recommendation) | 1 |
| **Total R-residuals across all 10 specs** | **64** |

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
| 6/6 | (this commit) | Documentation closeout | 10 spec docs §8 dispositions + this top-level summary |

---

## 5. Architectural milestone statement

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

R-residual inventory: 13 DONE + 4 ASSESSED-KEPT + 46 DEFERRED
+ 1 NOT PURSUED = 64 total. Every R-residual has an explicit
disposition recorded in its respective spec doc §8.

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
(`key_people_summary`) type as Optional despite schema-
required; legacy fallback chains KEPT pending DB audits
rather than removed pre-emptively.

---

## 6. Verification status

**Cleanup Commit 6 complete. Awaiting web Claude verification
before P3.40 contract layer is declared FULLY COMPLETE.
Cloud Claude audit follows.**

The contract layer is functionally complete and verified at the
test suite level. Final FULLY COMPLETE designation is gated on:
1. Web Claude verification of the 6-commit cleanup pass.
2. Nick's handoff to cloud Claude for final architectural audit.

This doc is the input artifact for both.
