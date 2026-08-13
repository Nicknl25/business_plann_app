# HANDOFF INBOX — plain English only. The WATCHER seeds the task and flips
# STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.

mini: TURN-TIMEOUT-MINUTES: 240

FINISH THE ROUND-9 TURN. Your last turn did the work — you re-pointed the
golden legs at the frozen fixture and deleted the draft ladder (c292e5f) —
but you launched the prove and then ENDED YOUR TURN while it was still
running. Your session's children die with it, so the prove produced a 0-byte
file and the watcher faulted on "exited without flipping STATUS". That
0-byte artifact has been deleted.

Do this now:
- Re-run the full prove IN THE FOREGROUND and WAIT for it to finish. Never
  end a turn with a job in flight; if it would outlast your turn, return
  VERDICT: blocked and ask for a longer TURN-TIMEOUT-MINUTES instead.
    python -m replay_gate.run_gate --prove --tier full --verbose > _prove_<date>.txt 2>&1
- Audit the durable freeze VS delivered in round 8, sceptically: that no DB
  call remains anywhere in the hashing path (VS poisoned the socket layer and
  mysql.connector and reports all four digests reproducing twice — verify
  that yourself rather than taking it), that the frozen constants are the
  REAL captured payloads with their provenance recorded, and that VS's second
  find is properly frozen too — build_python_model_input_json was reading 8
  reference tables live, 152 queries per build, now recorded as 74 keys with
  FrozenLookupMiss on anything unrecorded. Confirm a miss actually raises.
- Confirm or refute VS's claim that round 7 -> 8 digests are IDENTICAL because
  the freeze captured exactly the draft the ladder already resolved to.
- Then write the RESULT block and flip STATUS as your final act, in the same
  commit. Stage explicit paths only — never a bare index-wide add.
