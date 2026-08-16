STATUS: awaiting-VS
TURN: 0/16
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
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
