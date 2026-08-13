STATUS: awaiting-VS
TURN: 1/16
TASK:
  (ARMED by VS on Nick's plain-English go — supervised cycle 1 per spec
  SS8.4. Nick never edits this file; VS or the watcher performs every
  mechanical step.)

  TURN-TIMEOUT-MINUTES: 240

  VS: capture the R32 workbook fixture from a COMPLETED draft
  (6feac758; use plcogs43 if that draft is incomplete). The gap R32
  named is payroll_headcount — a GPT-authored run artifact the
  offline builder cannot derive (gpt_payroll_author.py writes it
  during the run; the policy applier only consumes it). Capture the
  payload ONCE from a real final checkpoint (the same
  planning_run_checkpoints row the committed floor script reads),
  commit it as Test Files/_run_artifacts.py so mini can import it as
  a FROZEN CONSTANT — a pinned copy, never a live DB read at prove
  time (the digest must stay a pure function of frozen inputs and the
  determinism self-check must keep its meaning), and never a
  synthesized minimal payload. Then run:
    python -m replay_gate.run_gate --prove --tier full --verbose > _prove_<date>.txt 2>&1
  Post the file, write the RESULT block, flip to awaiting-mini.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: docs/architecture/vs_mini_handoff_watcher_spec.md
  SUMMARY: Mailbox initialized and staged with the first supervised
  task. Watcher built (c4f861c) and self-review-fixed. Blocked on
  mini's audit of the watcher itself (VS_NOTES, 9 behaviors) before
  any live cycle.
