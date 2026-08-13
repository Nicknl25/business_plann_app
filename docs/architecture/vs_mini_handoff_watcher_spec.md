# VS <-> mini Handoff Watcher — SPEC (v1)

STATUS: APPROVED by Nick 2026-08-12, with the §9 rulings and one
addition below. Build follows §8 rollout.

## §0.1 THE INTERFACE CONSTRAINT (Nick, 2026-08-12, non-negotiable)

**Nick's only interface is PLAIN LANGUAGE IN, PING OUT.** He says what
he wants in normal words; he reads the ping when the loop stops. He
NEVER edits HANDOFF.md, never flips a STATUS, never touches config,
scripts, or any machinery. Every mechanical action — seeding the task,
flipping status, re-arming, un-pausing, git — belongs to VS or the
watcher. A design that makes him toggle a STATUS line has only moved
his fiddling from copy-paste to status-editing; that is a design bug,
not a workflow.

**Rule for every future change:** if ANY step in the flow requires Nick
to touch HANDOFF/STATUS/config/scripts directly, that step is a bug
and gets closed.

### Gap audit against the constraint (all closed in this build)

| # | Gap (v1 design assumed "Nick edits the file")        | Closure |
|---|-------------------------------------------------------|---------|
| 1 | `awaiting-Nick` idled until Nick flipped STATUS (the "only Nick re-arms" comment) | **INBOX** (`replay_gate/HANDOFF_INBOX.md`): a plain-English line is read by the watcher, which seeds the TASK, resets TURN, flips STATUS, clears the inbox, commits and pushes. Consumed exactly once. Nick may also just say it in chat and VS does the same — shape 1 and shape 2 both live. |
| 2 | §2 transition table said "NICK-ONLY, by editing the file" | Rewritten: **Nick's WORDS** drive the transition; the watcher (inbox) or VS (chat) performs it. |
| 3 | PAUSE required Nick to create/delete a sentinel file | An inbox instruction **lifts PAUSE automatically** (his words are the un-pause) and VS sets/clears the sentinel on his say-so. A stale line cannot resume a paused loop later — the inbox is cleared in the same commit that consumes it. |
| 4 | §9.2 "cap tunable in config" implied Nick editing JSON | Config is VS-owned; Nick asks for a different ceiling in words. |
| 5 | Stop pings said what happened but not how to continue | Every ping now appends: *say what you want in plain English; VS or the watcher does every mechanical step.* |
| 6 | Agent binary was assumed on PATH (`claude`) — a missing CLI would have made Nick fix machinery | `resolve_agent_binary`: explicit config → PATH → newest VS Code extension native binary. Self-healing across extension updates. |

## §9 RULINGS (Nick, 2026-08-12)

1. **DRIFT force-stops, HARDER than green.** DRIFT means a
   previously-passing business moved — the loudest alarm in the
   gate, never auto-continue past it. Priority ping (URGENT
   subject); green's ping stays "success, confirm".
2. **Cap: default 8, as CONFIG** (replay_gate/handoff_config.json),
   tunable without a code change.
3. **Timeouts catch HANGS, not SLOWNESS.** 90 min is too tight for a
   prove+canary turn. Generous global default (180 min) + an
   optional per-task `TURN-TIMEOUT-MINUTES:` line in the TASK block
   for known-long turns. A false timeout killing a valid prove is
   worse than waiting out a hang — err generous.
4. **Push IMMEDIATELY after every commit** — the ff-only launch
   precondition (HEAD==origin) depends on origin being current.
   Never batch. Applies to agent turns and watcher STATUS writes.

**ADDITION — PAUSE brake (Nick's manual emergency brake):** before
every launch decision the watcher checks (a) a sentinel file
`replay_gate/HANDOFF_PAUSE` (committed — pushable from anywhere; the
watcher fetches each poll so a remote push pauses it) and (b)
`STATUS: paused`. If either is set, the watcher stops cleanly at the
turn boundary (never mid-turn kill) and idles until the sentinel is
removed / STATUS re-armed. The stopped-* states are the automatic
brakes; PAUSE is the manual one.

## 0. Problem and non-goals

Every fix -> run -> audit -> re-fixture turn currently routes through
Nick copy-pasting between VS (builds/runs) and mini (audits/owns the
gate). The mechanical churn — kwargs rungs, re-fixtures, re-runs —
needs no judgment. The rulings and the green-blessing do.

NON-GOALS (explicitly out of scope):
- The watcher NEVER merges the agents. VS and mini remain separate
  headless sessions with separate prompts; mini audits VS's work in a
  fresh context every time. The independence that caught every
  false-proof this campaign (the uncommitted floor script, the
  vacuous workbook leg, the R26 wrong-way assertion) is the property
  being preserved, not an implementation detail.
- The watcher makes NO judgment calls. It is a clock and a router:
  it reads one status line, launches one agent, watches for the
  flip, and stops on the conditions in §4. It never interprets
  results beyond the structured fields agents write for it.
- No autonomous green-trusting. Green ALWAYS stops for Nick (§4.2).

## 1. The mailbox — `replay_gate/HANDOFF.md`

One committed file, three parts, fixed grammar. It lives in
`replay_gate/` beside VS_NOTES.md (same channel the agents already
share); VS_NOTES stays the long-form diagnosis channel, HANDOFF.md is
the machine-read turn state.

```
STATUS: awaiting-mini
TURN: 3/8
TASK:
  <one task block, written by whoever flipped STATUS — what the
   next agent must do, in imperative sentences. Replaced each turn.>
RESULT:
  AGENT: mini
  VERDICT: progress | green | blocked | needs-ruling
  ERROR-SIGNATURE: capex_depreciation_maintenance_rate_invalid
  EVIDENCE: _prove_20260812_ws1ws2_prove5.txt R32 block
  SUMMARY: <2-6 lines, human-readable>
```

Field rules:
- `STATUS:` is line 1, exactly one of the §2 values. The watcher
  reads ONLY this line to decide action; everything else is for the
  agents and Nick.
- `TURN: n/CAP` is watcher-owned (§4.4). Agents never edit it.
- `TASK:` is written by the agent that flips STATUS (it addresses
  the NEXT agent) or by Nick when he re-arms after a stop.
- `RESULT:` is appended by the finishing agent before it flips.
  `VERDICT` and `ERROR-SIGNATURE` are machine-read (§4.2, §4.3):
  - `green` — a clean table / passing floor / clean canary. The
    watcher stops for Nick. An agent must never write `green` for
    partial progress.
  - `progress` — moved forward, more mechanical work remains.
  - `blocked` — cannot proceed without the other agent.
  - `needs-ruling` — a design decision surfaced; goes to Nick.
  - `ERROR-SIGNATURE` — the stable identifier of the current
    blocker: the contract/exception token (e.g.
    `forecast_starting_ppe_must_equal_authoritative_balance_sheet`),
    or the failing leg id + failure token (`R32:no-formula-grid`).
    NOT prose, no paths, no numbers. `none` when VERDICT=green.
    This is what makes same-error-twice detectable (§4.3): the
    kwargs ladder produced a DIFFERENT signature every round —
    converging; the same signature twice means stuck.

## 2. The state machine

Values (STATUS line):

| value          | meaning                                   | watcher action        |
|----------------|-------------------------------------------|-----------------------|
| awaiting-VS    | VS's turn (build/fix/run/post)            | launch VS headless    |
| awaiting-mini  | mini's turn (audit/re-fixture/gate edit)  | launch mini headless  |
| awaiting-Nick  | ruling needed, green to bless, or stopped | STOP + ping (§5)      |
| stopped-stuck  | same-error-twice tripped                  | STOP + ping           |
| stopped-cap    | iteration cap tripped                     | STOP + ping           |
| stopped-fault  | watcher/process fault (§6)                | STOP + ping           |

Transitions:
- `awaiting-VS -> awaiting-mini` — flipped by VS as its final act.
- `awaiting-mini -> awaiting-VS` — flipped by mini as its final act.
- `any -> awaiting-Nick` — flipped by an agent (VERDICT green or
  needs-ruling), or by the WATCHER when it observes VERDICT=green on
  any flip (belt over the agent's own discipline: even if an agent
  writes green but flips to the other agent, the watcher overrides
  to awaiting-Nick — green never self-continues).
- `any -> stopped-stuck / stopped-cap / stopped-fault` — watcher-only.
- `awaiting-Nick / stopped-* -> awaiting-VS | awaiting-mini` —
  driven by NICK'S WORDS, performed by the machinery (§0.1): the
  watcher consumes a plain-English line from
  `replay_gate/HANDOFF_INBOX.md` (seeds TASK, resets TURN, flips
  STATUS, clears the inbox, commits+pushes), or VS performs the
  same flip when Nick says it in chat. Nick never edits the file.

Only agents and Nick flip between awaiting-VS/awaiting-mini. Only
the watcher writes stopped-*. Only Nick leaves awaiting-Nick.

## 3. Serialization — how one status line prevents collisions

The rule the whole design hangs on: **exactly one live agent, ever,
and a turn is not over until its commit lands.**

1. Both agents run in THIS repo, same working tree, strictly
   sequentially. There is no concurrent-commit case to reconcile
   because the watcher never has two children alive: it holds ONE
   child process slot, guarded by a local pidfile
   (`_handoff/watcher.pid` + `_handoff/agent.pid`, gitignored).
2. An agent's turn contract (baked into its bootstrap prompt):
   read HANDOFF.md -> do ONLY the TASK block -> commit all work ->
   write RESULT + flip STATUS -> **the STATUS flip is part of the
   FINAL commit** -> push. The flip and the work are therefore
   atomic in history: seeing the flip in git means the work that
   justified it is already in.
3. The watcher's launch precondition, ALL required:
   a. no agent.pid alive,
   b. `git status --porcelain` clean for tracked files (untracked
      scratch is fine),
   c. local HEAD == origin (fetch + compare; if origin is ahead,
      pull --ff-only first; if diverged -> stopped-fault + ping,
      never merge on its own),
   d. STATUS is awaiting-VS or awaiting-mini.
   Only then does it spawn the agent. "Never launch mini until VS's
   commit lands and is pulled" is precondition (c); "never launch a
   second VS" is (a) + the single child slot.
4. Push failure at the end of an agent turn: the flip exists locally
   but not on origin. The watcher treats LOCAL HEAD as truth for
   sequencing (same tree), retries the push itself up to 3 times,
   and if origin still won't take it -> stopped-fault + ping. It
   never launches the next agent with an unpushed flip (offsite
   evidence per-turn is part of the protocol, same as the
   push-per-phase law).
5. Nick edits HANDOFF.md whenever he wants; the watcher re-reads
   STATUS immediately before every launch decision, so a manual
   edit between polls always wins.

## 4. Stop conditions — the section that matters

The campaign's lesson, encoded: green needs a skeptical human.

1. **awaiting-Nick** (ruling): any agent writes VERDICT=needs-ruling
   and flips to awaiting-Nick. Watcher stops + pings. No timeout —
   it stays stopped until Nick re-arms.
2. **GREEN — ALWAYS stops.** Two layers:
   - Agents must flip to awaiting-Nick themselves when the result is
     a clean table / passing floor / clean canary.
   - The watcher independently parses VERDICT on every flip; if
     `green`, it forces awaiting-Nick REGARDLESS of where the agent
     pointed, then pings. Green lied four times this campaign
     (crash-reds read as proofs, vacuous workbook leg, uncommitted
     floor, R26 wrong-way) — a clean table is a stop signal, never a
     continue signal. The watcher has no code path that launches an
     agent after a green.
3. **SAME ERROR TWICE**: the watcher keeps the previous
   ERROR-SIGNATURE per direction (VS-turn signatures and mini-turn
   signatures tracked separately — the same rung legitimately
   appears once on each side). If a new RESULT carries the same
   signature as that agent's previous RESULT -> stopped-stuck +
   ping. Signature `none`/missing never matches (absence is not
   evidence of stuck; a missing signature on VERDICT!=green is
   itself a spec violation the ping mentions).
4. **ITERATION CAP**: TURN increments at every watcher launch.
   Default CAP=8 round-trips (16 agent turns), configurable in the
   file. At cap -> stopped-cap + ping. A runaway cannot churn all
   night: the cap bounds it even if every turn "makes progress".

Additional watcher-fault stops (§6) exist but are process hygiene,
not judgment: agent timeout, dirty tree, diverged history.

## 5. The ping

Reuse the existing SMTP path (.env EMAIL_* -> EMAIL_ALERTS_ADDRESS —
the same mechanism as the per-push emails). Every stop sends one
email: subject `HANDOFF STOPPED: <status>`, body = the full RESULT
block + last 3 turn summaries + the file's git ref. Optional
Windows toast (PowerShell BurntToast or msg.exe) as a second channel;
email is the required one. No email on normal flips — only stops.

## 6. The doorbell — watcher process mechanics

Modeled on the processes that already run unattended on this machine
(run_supervisor.py, persona_session_watch.py — poll loops as
scheduled tasks; no git hooks, they can't wake a dead process).

- `scripts/handoff_watch.py`, single instance enforced by
  `_handoff/watcher.pid` (stale-pid detection: pid dead -> reclaim).
- Poll loop, 60s: fetch origin -> reconcile (§3.3c) -> read STATUS
  -> act.
- Launch = headless Claude Code:
  `claude -p @replay_gate/HANDOFF_PROMPT_VS.md` (and _MINI), cwd =
  repo root, stdout/stderr -> `_handoff/logs/<ts>-<agent>.txt`
  (gitignored). The bootstrap prompts are COMMITTED files: they
  state the turn contract (§3.2), the agent's identity and
  boundaries (VS never edits replay_gate legs; mini never edits app
  code — the existing ownership law, restated where the agents will
  actually read it), and the VERDICT/ERROR-SIGNATURE grammar.
  Permission mode, model, and effort flags for each agent are
  Nick's call at review time (they are cost/scope knobs, not
  architecture).
- Per-turn timeout: 90 min default. On expiry: kill the child,
  STATUS -> stopped-fault, ping with the log tail. (The supervisor's
  reap instinct, applied here.)
- The watcher never writes anything except: TURN increments, the
  stopped-* statuses, the forced awaiting-Nick on green, and pidfile
  bookkeeping. It commits those STATUS writes with a fixed message
  prefix `[handoff-watcher]` so history shows which flips were
  machine-made.

## 7. Failure modes considered

| failure                          | behavior                                        |
|----------------------------------|-------------------------------------------------|
| watcher dies mid-turn            | agent finishes + flips; on watcher restart, stale watcher.pid reclaimed, loop resumes from STATUS |
| agent dies mid-turn (no flip)    | timeout reap -> stopped-fault + ping; tree may be dirty — Nick inspects, never auto-reset |
| agent commits but push fails     | watcher retries push x3 -> stopped-fault + ping (§3.4) |
| both-agents-alive (bug)          | unreachable by construction (one child slot); if agent.pid exists at launch time -> no launch |
| history diverged from origin     | stopped-fault + ping; watcher never merges/rebases |
| HANDOFF.md malformed             | stopped-fault + ping with the parse error; watcher never guesses |
| green mislabeled as progress     | not machine-catchable — mitigated by mini's audit turn (a false "progress" gets audited next turn) and the cap |

## 8. Rollout — supervised before trusted

1. Nick reviews THIS SPEC (stop conditions + §3 hardest).
2. Build `scripts/handoff_watch.py` + the two bootstrap prompts +
   HANDOFF.md skeleton.
3. Mini audits the WATCHER ITSELF as code: does it stop on green
   (feed it a fabricated green flip)? detect same-signature-twice?
   refuse to launch on dirty tree / diverged history / live pid?
   force awaiting-Nick over an agent's wrong flip? Each is a
   testable behavior; mini writes the harness.
4. SUPERVISED CYCLES: run the loop on a real mechanical task (the
   R32 pinned-payload turn is the natural candidate) with Nick
   watching, for at least 2-3 full VS->mini->VS cycles including one
   real stop-on-green. Only after those cycles behave does it run
   unattended.

## 9. Open questions for Nick (answer at review)

- CAP default 8 round-trips — right ceiling?
- Should DRIFT (a negative control moving) force awaiting-Nick like
  green does, or stay a normal mechanical bounce to VS? (VS lean:
  force-stop — DRIFT is the alarm the golden layer exists to raise,
  and it has never fired legitimately yet.)
- Per-turn timeout 90 min — long runs (full-tier prove ~20-40 min +
  audit) fit, but a Sunny canary + prove in one turn might not.
  Split such turns, or raise to 150?
- Watcher's own STATUS commits push immediately (offsite trail per
  flip) or batch at stop?
