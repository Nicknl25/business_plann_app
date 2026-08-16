STATUS: awaiting-Nick
TURN: 2/16
TASK:
  RESTRUCTURE-PATH HYGIENE n1 + n4 — Nick's ruling 2026-08-16. Small
  cleanups, NOWHERE NEAR the email/delivery path (that path is OFF-LIMITS
  per the standing fence in your bootstrap - if anything you touch looks
  like email composition, delivery routing, or the failure-email
  attachment, STOP and needs-ruling). Not engine math, not goldens.
  TURN-TIMEOUT-MINUTES: 75
  TURN 1 (VS; declare the tier per fix - both look restructure-path
  SPOT-CHECK; mini audits the call):
   n1 ONE AUTHORITY for the run id on the restructure path:
      acceptance_planning_run_id is empty there, so verify_run_acceptance
      runs with planning_run_id=None and a latest-run fallback (guessing).
      Resolve the run id PROPERLY on that path (FIX 2b already resolves the
      row for the failure surface - use the same resolution as the single
      authority) so no latest-run guessing remains. Red-proof: on the Nine
      Fathom rewind clone the verdict is persisted against the exact run
      row, never a fallback.
   n4 ROW-SHAPE TWO SOURCES OF TRUTH: _prepare_restructure_model flips
      EXISTING per-line COGS % rows to controller_write=True /
      derived_driver=None - not the real per-line row shape. Fix so
      existing per-line COGS rows keep the byte-identical real shape FIX 1
      already uses for synthesized lines (controller_write=False,
      derived_driver=per_line_cogs_source, same lever id / label). Solve
      stays green. Red-proof: prepared model rows for a per-line-COGS draft
      are shape-identical to finmo_bridge's real rows PRE/POST; joint solve
      still finds candidates on the class sweep drafts.
   Floor R31/R32 via --only. Canary skip. Flip to mini.
  TURN 2 (mini, spot-check audit): diff confined to the restructure path;
  zero touches to workbook_email.py / delivery / attachment (grep the
  diff); n1 single authority; n4 shape identity; solve green; floor.
  Green -> stop.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: commit 97189a0; Test Files/_rs_n1_single_authority_proof_20260816_PRE.txt (RED 7/7) + _POST.txt (single authority GREEN, one labeled WARN); Test Files/_rs_deadnet_live_failure_surface_20260816_n1POST.txt (ALL GREEN, ONE row); Test Files/_rs_n4_shape_proof_out.txt (PRE RED / POST GREEN 8/8); Test Files/_gate_only_R31_R32_20260816_n1n4.txt; server logs _logs_deadnet_N1PRE_20260816.txt / _logs_deadnet_N1POST_20260816.txt
  SUMMARY: n1 + n4 LANDED at spot-check, both red-proofed. n1: the unified runner
  stamps the planning_runs row the grid build CREATED into
  result.planning_run_json.planning_run_id (the key the handler already read
  first - it was never populated, so the gate ran planning_run_id=None and read
  the draft's LATEST row); every write on the restructure path (both dead-net
  catches, rerun restamp, rerun verdict) resolves by that id ONLY - the
  get_planning_run(draft_id=) fallbacks + the draft-row re-read are gone. LIVE
  decoy proof (future-dated completed planning_runs row on a Nine Fathom rewind
  clone, HEAD worktree server vs this build): PRE the DECOY took the failed flip
  + verdict + FAILED diagnostics row and the real row stayed completed with no
  verdict; POST the real row carries all three (verdict.field_snapshot.
  planning_run_id == real row), decoy untouched. n4: existing per-line COGS %
  rows are no longer flipped in _prepare_restructure_model - byte-identical to
  the base rows and shape-identical to FIX 1's synthesized row on 8/8 drafts,
  joint solve found=True evals=8 on all 8 (PRE and POST alike). Floor R31/R32
  GREEN, digests identical; ONE :5050 listener (normal backend restarted, pid
  38436); zero email/delivery/attachment lines in the diff.
  DECLARED-vs-ACTUAL: matched. Tier spot-check for both as declared. Two
  disclosures: (a) the n1 proof used a DECOY row (a contrivance to make the
  latest-run guess observable - the FIX 2b PRE proof had already shown the id
  EMPTY on this path, so the fallback WAS the operative resolution); (b) 6d2823db
  (Nine Fathom live draft) is now the POST-RESCUE state (20 rows) so its
  persisted bounds re-add the two new lines and it dead-nets on the revenue
  formula contract under PRE and POST alike - a test-input artifact; the
  pre-rescue clone rsdeadd25e stood in for it in the n4 sweep (disclosed in the
  script). LIVE FINDING for triage (NOT fixed - shared persist, outside the
  restructure path): persist_post_intake_execution_state (intake_consult_draft.py
  ~2793-2807) accepts the payload's planning_run_id only when it equals the
  latest active/any row, else MINTS a fresh uuid row - the decoy exposed it as
  a phantom second row (b5a5ea13, WARN in the POST txt). Without a decoy the
  same build lands exactly ONE row (FIX 2b harness re-run ALL GREEN). Deal-
  breaker test: no wrong number in a delivered plan today; it is a latent
  two-rows-of-truth class - Nick's call whether it earns a neighbor-check turn.
TASK:
  mini, TURN 2 (spot-check audit of 97189a0):
   1. diff confined to the restructure path + the unified runner stamp:
      `git show 97189a0 -- python/` - two files; grep the diff for
      email|attach|deliver -> zero lines (I did: NO matches). Tier call:
      the stamp is additive on an opaque dict (SolverOutputContract top level
      is extra=forbid, planning_run_json is Dict[str,Any]); the id resolution
      lives inside the NON-VIABLE-only restructure block; n4 is one `continue`
      in _prepare_restructure_model. Say if you disagree that this is
      spot-check.
   2. n1 single authority: read _rs_n1_single_authority_proof_20260816_PRE.txt
      vs _POST.txt - decoy vs real row; then read the planning_runs rows for
      the two clones yourself (rsn1au667f… PRE: real e3276f9e completed/no
      verdict, decoy failed+verdict; rsn1au0dcd… POST: real 225ca67e
      failed+verdict, decoy completed/no verdict). Confirm no
      get_planning_run(draft_id=) remains inside the restructure block
      (grep intake_consult.py 14700-15300).
   3. n4 shape identity: run `python "Test Files/_rs_n4_shape_proof.py"`
      (8 drafts, ~3 min) - PRE RED / POST GREEN; note the 6d2823db
      post-rescue disclosure.
   4. Floor R31/R32 via --only, ONE :5050 listener.
   5. Carry the persist_post_intake_execution_state phantom-row finding to
      Nick's triage list (needs-ruling: n9). Green -> awaiting-Nick.
RESULT:
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_mini_gate_only_R31_R32_20260816_turn2.txt (2/2 clear, digests grid cbd764631e98 / model_input 1d50e46ab8e6 / finmo 24e38de4dc98 == VS); Test Files/_mini_n1_rows_audit.py + _mini_n1_rows_audit_20260816.txt (independent DB read of the PRE/POST clone rows); n4 proof re-run this session (Test Files/_rs_n4_shape_proof.py, PRE RED 8/8 flipped -> POST GREEN 8/8 identical/one-shape/found=True evals=8); git show 97189a0 -- python/
  SUMMARY: SPOT-CHECK AUDIT of 97189a0 - CLEAN. (1) Diff: two python files only
  (intake_consult.py 66 lines, joint_solver.py 17 lines); grep email|attach|deliver
  over the CODE diff = ZERO hits (the only match is the commit-message text itself);
  no touch to workbook_email.py / delivery / attachment. n1 = additive stamp of the
  grid-build-created run id into result.planning_run_json.planning_run_id + id-only
  resolution in the restructure block (both dead-net catches, restamp, rerun verdict);
  the two get_planning_run(draft_id=) fallbacks and the draft-row re-read are GONE
  (grep of 14600-15400: the only draft_id= lookup left is the pre-existing OUTER
  generic-exception catch at 14627, not the restructure path). n4 = one `continue`.
  (2) n1 rows read independently from the DB: PRE clone rsn1au667f real e3276f9e
  completed/no-verdict, decoy failed+verdict+diagnostics; POST clone rsn1au0dcd real
  225ca67e failed + verdict (field_snapshot.planning_run_id == 225ca67e) + diagnostics
  keyed by it, decoy completed/untouched. gate.py resolves an explicit id first
  (_planning_run_row) - so the stamped id is honoured. (3) n4 re-run here: identical
  table to VS's; the PRE fixture _rs_n4_joint_solver_PRE.py is byte-identical to
  97189a0^ joint_solver.py (real pre-fix source, not a mock); 6d2823db post-rescue
  disclosure present in the script (rsdeadd25e stands in). (4) Floor R31/R32 --only
  GREEN 2/2, digests identical to VS's; ONE :5050 listener (pid 38436).
  TIER CALL: spot-check accepted for both, with ONE NOTE for the record - VS's plan
  said the n1 stamp fires "inside the restructure block only"; in fact the STAMP
  itself (14341-14355) rides EVERY unified run and changes the acceptance gate's
  input on the normal path from planning_run_id=None (latest-row fallback) to the
  explicit created row. Behaviour on the guided path is identical BY CONSTRUCTION
  (one row per run => created == latest; VS's FIX 2b re-run landed exactly ONE row)
  and the floor does not traverse the gate, so this is a wording imprecision in the
  radius statement, not a false tier - but the next live GREEN run is the organic
  confirmation of the stamp on a passing path (watch item, no turn owed).
  DECLARED-vs-ACTUAL (VS): matched on files loaded/touched and verify steps; one
  disclosed method deviation - n1 red-proof used a future-dated DECOY row instead of
  the planned "stripped-COGS test server" observation; disclosed, and the decoy is
  the only way to make a latest-row guess observable. Not a finding.
  DECLARED-vs-ACTUAL (mini): matched - diff+grep, PRE/POST txts, DB rows, restructure
  block grep, n4 re-run foreground, R31/R32 --only foreground, listener count; canary
  skipped as declared; legs R31+R32 (2).
  TRIAGE: n1/n4 named deal breakers (verdict against a guessed row = false claim on
  which run failed; two COGS-row shapes in one solve = wrong per-line COGS for the
  class) - both hold; both CLOSED GREEN.
  NEEDS-RULING (n9, Nick): persist_post_intake_execution_state
  (intake_consult_draft.py ~2793-2807) accepts the payload's planning_run_id only
  when it equals the latest active/any row, else MINTS a fresh uuid row - decoy proof
  showed a phantom second row b5a5ea13 (status=failed, no verdict). Deal-breaker
  test TODAY: NO - guided path lands exactly one row (rerun's own row is the latest
  active); the phantom needs a foreign newer row (decoy / concurrent double-submit).
  Latent two-rows-of-truth class in SHARED persist (initial-grid + state runners
  flow through it) => neighbor-check radius if built. Nick's call: queue a
  neighbor-check turn (make persist honour the payload's id when it names an
  existing row for this draft, mint only when absent) or WONT-FIX until a real
  concurrent-run case appears.
TASK:
  VS: nothing queued from this audit. STATUS awaiting-Nick - Nick rules on n9
  (neighbor-check turn vs WONT-FIX) in plain English; the watcher seeds the next
  TASK from his reply. Off-limits fence unchanged: no email/delivery/attachment work.
