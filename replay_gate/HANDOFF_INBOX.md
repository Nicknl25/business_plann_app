# HANDOFF INBOX — plain English only.
# Nick writes what he wants in normal words. The WATCHER seeds the task and
# flips STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.
# Prefix a line with "mini:" to address mini instead of VS.

TURN-TIMEOUT-MINUTES: 240

DURABLE FREEZE of the golden-leg input — Nick's one condition before he calls
per-line COGS closed. Round 7's table is clean and honest, but the golden
input is still DB-DERIVED: it picks a draft by query, so a prune, a restore,
or a new draft landing can move it. A GOLDEN that depends on database state is
not frozen, and blessing it would repeat the mistake just corrected — matching
digests read as construction when they were coincidence.

VS: pin the golden-leg input as a COMMITTED CONSTANT so no database change can
move it.
- Capture the chosen single-line draft's payloads ONCE and commit them as a
  literal frozen fixture, the way the R32 run artifacts were pinned. After
  this the golden legs must build from committed bytes with NO database query
  anywhere in the hashing path.
- PROVE the property, do not assert it: show the digest reproducing with the
  database unreachable, so durable-by-construction is evidence.
- Keep the determinism self-check and rot guard meaningful: the constant must
  be the REAL captured payload, never synthesized or trimmed, and its
  provenance (draft id, run id, checkpoint stage) recorded in the fixture.
- Say plainly in the RESULT that round 8 digests are NOT comparable to rounds
  4-7 (the input changed identity when frozen) — expected, not drift.
- Then run the full prove, post the file, and flip to awaiting-mini asking
  mini to re-audit the freeze: no DB call in the hashing path, fixture matches
  the checkpoint it claims, goldens still earn their rows.
- Commit ONLY the files your task touches. A previous turn swept 408 unrelated
  files into one commit; stage explicit paths, never a bare index-wide add.
Also settle the boundary the last cycle exposed: the R32 artifacts landed in
replay_gate/ (mini's territory) because surface.py imports them relatively,
contradicting the ownership law in both bootstrap prompts. State where frozen
fixtures belong and make the import match, rather than leaving rule and code
disagreeing.
