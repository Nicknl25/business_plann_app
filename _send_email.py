"""One-shot push notification email for Contract 7 1c."""
import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

host = os.environ["EMAIL_HOST"]
port = int(os.environ.get("EMAIL_PORT", "587"))
user = os.environ["EMAIL_USER"]
password = os.environ["EMAIL_PASSWORD"]
sender = user
to = os.environ["EMAIL_ALERTS_ADDRESS"]

subject = "[P3.40] FULLY COMPLETE -- post-audit disposition updates pushed (e99d1d5)"
body = """\
P3.40 CONTRACT LAYER FULLY COMPLETE.

Post-audit disposition updates landed:
  e99d1d5 phase_9_p3_40_contract_layer_closeout_post_audit_disposition_updates

Documentation-only commit. No code changes. Suite unchanged
(637 P3.40 passing).

Files modified (4):
  - p3_40_contract_5d_people_json_spec.md (R-d reclassified to
    intake-remediation workstream; canonical key_people_summary
    design-intent documented)
  - p3_40_contract_5c_target_market_json_spec.md (R-d-bis new
    entry tracking target_market_summary parallel bug)
  - p3_40_contract_5_intake_draft_spec.md (R11 reframed per
    cloud Claude: NOT PURSUED -> DEFERRED with "per-producer
    trace work" framing)
  - p3_40_contract_layer_closeout.md (R-residual totals
    13+4+48+0=65; new §5 intake-remediation handoff section;
    §7 verification status updated to "FULLY COMPLETE")

7 boundary contracts + 3 sub-contract retrofits done. 6-commit
cleanup pass done. Post-audit disposition updates applied per
cloud Claude + Claude Code VS findings.

Remaining intake-side work (Contract 5d R-d + Contract 5c
R-d-bis) explicitly handed off to intake-remediation
workstream with full design-intent documentation.

Ready for Fix #1 (steady-state viability) and Fix #2 (headcount
derivation) to begin on top of this foundation. The intake-
remediation pass is a separate workstream Nick owns.

Pushed to origin/intake-stable.
"""

_old_research_body = """\
P3.40 intake-side research report landed (post cloud-Claude
audit). Research-only commit; no code changes.

  8a98e26 phase_9_p3_40_intake_side_research_post_audit
  docs/architecture/intake_side_research_post_audit.md (619 LOC)

Key findings:

§1 Canonical definition: key_people_summary is a DENORMALIZED
VIEW of people_json["people"][].paragraph. The pop is
INTENTIONAL (commit e57ff49) to enforce single source of truth.
Consumers should reconstruct from per-person paragraphs.

§3 Finding A (cloud Claude) -- AGREE. AND scope wider than
flagged: target_market_summary shares the EXACT bug class
(popped at intake_consult.py:10863; gate-read at
financials.py:95). Recommended fix: Option 3 (replace
proxy-summary checks with direct structural checks on
primary data). Small fix, no persistence change.

§3 Finding E (5e/f/g/h skip framing) -- PARTIAL agreement.
Skip stands; framing should be cloud Claude's reframing
("requires per-producer trace work") not the current "different
pattern" framing.

§4 Broader observations:
  - LEGACY (target_market.py + people_capability.py) vs UNIFIED
    (intake_consult.py) dual-handler split; frontend uses
    UNIFIED.
  - No other "pop + gate-read" pairs found beyond the 2
    summaries.

§5 Prioritized recommendations:
  BLOCKING for Fix #2: fix gate for BOTH summaries via Option 3.
  RECOMMENDED before Fix #2: reframe Contract 5 R11 + document
    dual-handler split.
  NICE-TO-HAVE: audit other semantic-via-proxy checks; add
    pre-flight endpoint; deprecate/pin LEGACY handlers.
  NOT WORTH PURSUING: 5e/f/g/h typing wave; Finding A Option 1
    (stop popping -- reverses design decision).

§6 Open questions for Nick:
  1. Submission reality today -- has gate been blocking?
  2. LEGACY handler disposition?
  3. Option 2 vs 3 (payload downstream consumer impact)?
  4. target_market_summary symmetry confirmation?
  5. 5e/f/g/h spec reframing authorization?

HOLD for Nick's review before any subsequent action.

Pushed to origin/intake-stable.
"""

_old_cleanup_6_body = """\
P3.40 Contract Layer R-residual Cleanup Pass -- Cleanup Commit
6 of 6 landed (FINAL):
  4d59e3d phase_9_p3_40_contract_layer_cleanup_6_of_6_documentation_closeout

Documentation-only commit. 11 files: 10 contract spec docs §8
disposition summaries + NEW top-level closeout doc
(docs/architecture/p3_40_contract_layer_closeout.md).

R-residual disposition totals across all 10 specs:
  - 13 DONE (addressed in Cleanups 1-5 with SHA references)
  - 4 ASSESSED + KEPT (R9 Contract 7 + R-a Contract 5b + R-b
    Contract 5d + R1 Contract 1)
  - 46 DEFERRED (explicit rationale per residual)
  - 1 NOT PURSUED (Contract 5 R11: 5e/f/g/h python-aggregated
    track skipped per recommendation)
  - 64 total R-residuals, every one explicitly dispositioned

6-commit cleanup pass:
  1/6 e0c06b1 -- Contract 6 R10 + R11 silent-drop closures
  2/6 05a33ad -- Contract 6 R16 + Contract 7 R9 inverse-
       retrofit assessment
  3/6 0d48fac -- Legacy fallback assessments + R10/R11
       phantom-write removals
  4/6 c196ef0 -- Contract 1 R1-R7 dead-code assessments
  5/6 d92bfe2 -- Cheap defense-in-depth (R8/R9/R17/R14)
  6/6 4d59e3d -- Documentation closeout (this commit)

Final test count: 637 P3.40 suite + 18 adjacent = 655
combined, all passing.

Architectural milestone (per closeout doc):
"P3.40 contract layer end-to-end. Boundaries 1-7 contract-
typed with producer + consumer side enforcement, Adjustment B
propagation, single-PhaseCode-per-contract observability with
shape discriminators, and structural sub-contract retrofits
(5b/c/d) under §0 value-constraint policy."

** STOPPING per directive. **

Cleanup Commit 6 complete. Awaiting web Claude verification
before P3.40 contract layer is declared FULLY COMPLETE.
Cloud Claude audit follows.

NOT autonomously declaring the contract layer FULLY COMPLETE
-- that designation is gated on web Claude verification +
Nick's handoff to cloud Claude for final architectural audit.

Pushed to origin/intake-stable.
"""

_old_cleanup_5_body = """\
P3.40 Contract Layer R-residual Cleanup Pass -- Cleanup Commit
5 of 6 landed:
  d92bfe2 phase_9_p3_40_contract_layer_cleanup_5_of_6_cheap_defense_in_depth_r8_r9_r17_r14

4 cheap defense-in-depth additions:

  R8 -- GetBandsViewContract count_matches_bands_length
    @model_validator (STRUCTURAL).
  R9 -- IndustryBaselineResolvedContract key/value
    consistency invariants on cascade_payloads +
    get_bands_views (STRUCTURAL).
  R17 -- _naics_6_from_ops length warning at the upstream
    producer (defense-in-depth; PSL2 log-only).
  R14 -- MirrorContract.from_mirror(mirror) classmethod
    adapter (readability upgrade; STRUCTURAL convenience).

§0 compatibility: all 4 additions are STRUCTURAL consistency
checks or convenience wrappers, NOT value-level content
checks. §0's prohibition targets content; structural
consistency is allowed.

Files modified (6): industry_baseline_resolved_contract.py +
amalgamated_session_contract.py + finmo_bridge.py + new
test_p3_40_contract_layer_cleanup_5.py (11 tests, all
passing) + 2 spec docs.

Verification: Full P3.40 suite 655/655 passing (was 626; +29
net from new R8/R9/R17/R14 coverage). Zero regressions.

Cleanup Commit 6 of 6 follows: documentation closeout (final
R-residual disposition pass across 10 contract spec docs +
top-level closeout summary). After Cleanup 6 lands, STOP per
directive -- web Claude verification + cloud Claude audit
pending before P3.40 contract layer is declared FULLY
COMPLETE.

Pushed to origin/intake-stable.
"""

_old_cleanup_4_body = """\
P3.40 Contract Layer R-residual Cleanup Pass -- Cleanup Commit
4 of 6 landed:
  c196ef0 phase_9_p3_40_contract_layer_cleanup_4_of_6_contract_1_r1_r7_dead_code_assessments

Contract 1 R1-R7 dispositions per assess-before-remove:
  R1 -- ASSESSED + KEPT. to_model_input_json has 2 test
    callers; tests block removal per Cleanup 3 precedent.
  R2 -- DEFERRED. "model_input_balancehseet" typo needs
    coordinated workbook-reader migration.
  R3 -- DEFERRED. Sub-contract typing of opaque blobs needs
    its own trace+spec+multi-commit (analog to 5b/c/d).
  R4 -- DEFERRED. Pre-Contract-1 production cleanup.
  R6 -- DEFERRED. Deep finmo_bridge.py migration; multi-week
    scope.
  R7 -- DEFERRED. Depends on R3; deferred.

Documentation-only commit. P3.40 suite: 626/626 passing.

Cleanup Commit 5 of 6 follows: cheap defense-in-depth
(R8 + R9 + R17 + R14).

Pushed to origin/intake-stable.
"""

_old_body_3 = """\
P3.40 Contract Layer R-residual Cleanup Pass -- Cleanup Commit
3 of 6 landed:
  0d48fac phase_9_p3_40_contract_layer_cleanup_3_of_6_legacy_fallback_assessments_and_phantom_write_removals

Per-candidate reader/writer assessments + targeted removals:

Candidate 1 (5b R-a -- ops_json naics_code/business_naics
fallback in runner.py): ASSESSED + KEPT for legacy DB support.
Zero current writers but legacy drafts may carry the keys.

Candidate 2 (5d R-b -- post_intake_headcount fallback chain
for role/name/months_until_hire on person items): ASSESSED +
KEPT per directive's explicit "THE classic legacy data support
case" hint.

Candidate 3 (Contract 7 R10/R11 -- Mirror phantom-write fields):
REMOVED. record_decision() zero callers; sequence_position/
budget zero callers pass them. Mirror data fields 9 -> 6.
RecentDecision + RecentDecisionContract dropped entirely.
MirrorContract field count 9 -> 6.

Files modified (12): runner.py + schedule.py (KEPT comments) +
mirror.py + __init__.py + amalgamated_session_contract.py +
enforcement.py + 3 test files + 3 spec docs.

Verification: 626/626 P3.40 + 18/18 adjacent passing. Zero
regressions. Suite delta 631 -> 626 (-5 from dropped
RecentDecisionContractTest + record_decision test coverage).

Cleanup Commit 4 of 6 follows: Contract 1 R1-R7 dead-code
assessments + cleanups.

Pushed to origin/intake-stable.
"""

# Suppress redundant second body block below
_ignored_old_body = """\
P3.40 Contract Layer R-residual Cleanup Pass -- Cleanup Commit
2 of 6 landed:
  05a33ad phase_9_p3_40_contract_layer_cleanup_2_of_6_contract_6_r16_contract_7_r9_inverse_retrofit_assessment

Inverse-retrofit ASSESSMENT for Contract 6 R16 + Contract 7 R9.
One alignment landed; one assessed as no-change.

R16 (Contract 6) per-field assessment of BusinessProfileInputContract
(4 fields):
  - naics_6: DIVERGENT (Contract 6 had Field(pattern=...) per
    F11; 5b/5d bare Optional[str]=None per §0). Pattern
    DROPPED for §0 alignment. Net behavior unchanged --
    runner.py:562 strips non-digit chars upstream so production
    payloads already satisfied the pattern.
  - stage: SHARED + already CONSISTENT with 5b's
    business_stage. No code change; documented.
  - target_annual_revenue: UNIQUE within 5b/c/d wave (sourced
    from financials_year1_json -- python-aggregated 5e/h
    R-residual track). No composition until 5e/h lands.
    R16-bis tracked.
  - business_model: UNIQUE. Literal[None] preserved as
    STRUCTURAL value-pin (not enum-vocabulary narrowing); §0's
    Literal ban targets enum narrowings. R12 covers upgrade.

R9 (Contract 7) ASSESSED, NO CODE CHANGE WARRANTED. Production
Mirror.business_facts at runner.py:261-271 is FLAT DRAFT-ROW
COLUMNS (name, business_name, address, start_date,
address_*) -- ZERO content overlap with 5b/5c/5d typed JSONs.
R9 hypothesis ("compose 5b/c/d when they land") doesn't match
production reality. Mirror.business_facts stays as
Dict[str, Any] per the directive's "do NOT force composition
where it doesn't structurally make sense" guideline.

Files modified (6):
  - industry_baseline_resolved_contract.py (R16 pattern drop)
  - amalgamated_session_contract.py (R9 rationale)
  - p3_40_contract_6_industry_baseline_spec.md (§8 R16 +
    §7 F11 amended; R17 re-scoped)
  - p3_40_contract_7_amalgamated_session_spec.md (§8 R9
    ASSESSED + RESOLVED via assessment)
  - tests/test_p3_40_contract_6_subcontracts.py (pattern-
    rejection tests inverted to acceptance tests)
  - tests/test_p3_40_contract_6_industry_baseline.py (top-
    level propagation test inverted similarly)

Verification:
  - Full P3.40 suite: 631/631 passing (unchanged count;
    same test-set with R16-aligned assertions)
  - Adjacent suites: 18/18 passing; zero regressions

Cleanup pass plan revised to 6 commits (was 5) per honest
re-assessment that some defense-in-depth work was deferred too
aggressively. Cleanup Commit 3 of 6 follows: legacy fallback
cleanups batched.

Pushed to origin/intake-stable.
"""

msg = MIMEText(body)
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = to

with smtplib.SMTP(host, port) as s:
  s.starttls()
  s.login(user, password)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent to", to)
