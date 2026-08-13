# HANDOFF INBOX — plain English only.
# Nick writes what he wants in normal words (e.g. "go", "run the R32 cycle",
# "re-run the prove and have mini audit it"). The WATCHER seeds the task and
# flips STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.
# Prefix a line with "mini:" to address mini instead of VS.

TURN-TIMEOUT-MINUTES: 240

DURABLE FREEZE of the golden-leg input — Nick's condition for calling
per-line COGS closed. Round 7's table is clean and honest, but mini
flagged that the golden input is still DB-DERIVED: it picks a draft by
query (pin-then-oldest), so a DB prune, a restore, or a new draft
landing can move it. A GOLDEN that depends on database state is not
frozen, and blessing it as complete would repeat the exact mistake we
just corrected (matching digests read as construction when they were
coincidence).

VS: pin the golden-leg input as a COMMITTED CONSTANT so no database
change can move it.
- Capture the chosen single-line draft's payloads ONCE and commit them
  as a literal frozen fixture, the same way the R32 run artifacts were
  pinned. After this, the golden legs must build from committed bytes
  with NO database query in the hashing path at all.
- Prove the property, do not assert it: the digest must be reproducible
  with the database unreachable. Demonstrate that (point the DB config
  at nothing, or otherwise make a query impossible) and show the same
  digest, so "durable by construction" is evidence, not a claim.
- Keep the determinism self-check and the rot guard meaningful: the
  frozen constant must still be the REAL captured payload, never a
  synthesized or trimmed one, and its provenance (draft id, run id,
  checkpoint stage) must be recorded in the fixture itself.
- Note honestly in the RESULT that round 8's digests are again NOT
  comparable to rounds 4-7 (the input changed identity when it was
  frozen) — that is expected, not drift.
- Then run: python -m replay_gate.run_gate --prove --tier full --verbose
  > _prove_<date>.txt 2>&1, post the file, and flip to awaiting-mini
  asking mini to re-audit the freeze: that the hashing path contains no
  DB call, that the fixture matches the real checkpoint it claims, and
  that the goldens still earn their rows.
Boundary note from cycle 1 to settle in this turn: the R32 artifacts
landed in replay_gate/ (mini's territory) because surface.py imports
them relatively, which contradicts the ownership law in both bootstrap
prompts. Say plainly where frozen fixtures belong and make the import
match, rather than leaving the rule and the code disagreeing.
