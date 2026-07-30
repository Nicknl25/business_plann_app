# Persona-run backend observability

How to run the backend so a browser-driven persona run (Claude Cowork as the client)
is fully observable from the backend side, live.

## Startup

One command for the whole stack (what Cowork's control app should invoke):

```powershell
powershell -File scripts\start_persona_stack.ps1   # backend :5050 + frontend :5173
```

Client entry URL (open in a FRESH browser tab/window per run):
`http://localhost:5173/business-plan-form`. Draft identity (draft_id/client_id)
lives in **sessionStorage**, so a new tab = a new draft + a server-generated
client_id (no collision with the drafts table's `uniq_client_id`); reusing a
tab RESUMES the prior draft. Give each run a distinct business name — nothing
enforces uniqueness, but it is the human-readable key for matching a run to
its OneDrive transcript afterwards.

Backend half only:

```powershell
powershell -File scripts\start_persona_backend.ps1          # default port 5050
```

What it does:

- Starts the Flask app on `:5050` with **`BPLAN_TRACE_VERBOSE=1`**, so every
  `post_intake_handler_traces` row carries the verbatim GPT request/response —
  not just telemetry.
- Redirects stdout+stderr to one file: `_logs_persona_<stamp>.txt`. All log lines
  are timestamped (`api._configure_logging`).
- Pins `frontend/.env.local` to `VITE_API_BASE_URL=http://127.0.0.1:5050` — without
  this the frontend silently calls the `:5000` default. Start the frontend
  separately: `cd frontend; npm run dev`.

Stale-server rule still applies: restart after **every** app-code edit, or the run
exercises old code. One Sunny_V3 canary before any batch.

## Log markers

- `REQ <method> <path> -> <status> <ms> draft=<id>` — one line per `/api` request
  (`api.py` after_request). The request rhythm of the browser session.
- `TURN_BEGIN draft=<id> turn=<n> starting=<bool> focus=<active_focus> msg_chars=<n>` —
  one line per consult turn at entry (`intake_consult.py`, consult handler). Joins a
  log moment to "the Nth thing the persona was asked."

## Live watcher

```powershell
.venv\Scripts\python.exe scripts\run_live_e2e_monitor.py --watch-only --stall-seconds 300
```

`--watch-only` watches an externally-driven run instead of spawning a runner: it
detects the newest draft created after start (or `--draft-id`), prints JSON events
on every state change (`draft_detected`, `state_change`, `planning_run_detected`,
`planning_run_change`), and exits on:

| condition | event | exit code |
|---|---|---|
| planning run completed | `run_terminal` | 0 (then the usual 2/3/4 draft checks) |
| planning run failed / stopped | `run_terminal` | 7 |
| active run silent > `--stall-seconds` | `stall_detected` | 6 |
| `--max-wait-seconds` exceeded | `max_wait_exceeded` | 8 |

Stall = an active (non-paused) planning run whose freshest signal (run heartbeat,
run update, draft update) is older than the threshold. The intake conversation
before the system run is human-paced, so no planning run ⇒ no stall check.

Run it in the background from a Claude session and the exit re-invokes the
session at the moment of stall/failure — that is the "wake me when it breaks"
mechanism for persona runs.

## Auto-sensing session watcher

```powershell
.venv\Scripts\python.exe scripts\persona_session_watch.py
```

No prompt needed: it waits until backend (:5050) AND frontend (:5173)
both accept connections, announces `STACK UP`, then loops the watch-only
monitor over each new draft — compact one-line events for draft
detection, intake progress, stage transitions, stalls, and terminal
states, plus a tail of the newest `_logs_persona_*.txt` for `TURN_BEGIN`
/ `TURN_HOLD` / tracebacks. Claude arms this as a persistent background
monitor at the start of a persona session; each line wakes the session.

Notes: one draft watched at a time (serial runs by design); an abandoned
intake recycles after `--recycle-seconds` (default 1h); verbatim GPT I/O
and the log markers exist only when the backend was started via
`start_persona_backend.ps1`. When each watch ends the watcher runs
`persona_run_vitals_finalize.py` automatically and emits a one-line
`RUN VITALS:` summary (and the summary row lands in `run_vitals_runs`).

## Run-vitals database log

Every persona run leaves a queryable vitals record — four INSERT-only tables
written live by the app plus a summary row written by the watcher when a
watch ends (`python/client_intake_and_finmo/run_vitals.py`; capture is
best-effort by contract and never blocks a turn or a GPT call):

- **`run_vitals_turns`** — one row per intake consult turn: draft/client id,
  turn_index, section at entry + section after (section transitions = where
  consecutive rows differ), turn latency_ms, HTTP status, message/reply sizes,
  per-turn GPT rollup (calls, elapsed, tokens in/out, lock replays, retries),
  hold flag, error, and `call_labels_json` (the per-call breakdown). Armed at
  TURN_BEGIN (`intake_consult.py`), flushed by the `/api/intake-consult`
  after_request hook in `api.py`.
- **`run_vitals_gpt_calls`** — one row per GPT HTTP call process-wide, hooked
  at `openai_http.post_openai_with_retries` (the layer every GPT call flows
  through): phase (`intake` — attributed to draft/turn/section — or
  `post_intake` — attributed via the active trace run — or `unattributed`),
  model, schema/call label, status, attempts (>1 = retried), elapsed_ms,
  tokens, response-lock replay flag, error. `decision_source` for post-intake
  calls lives in `post_intake_handler_traces` (join on draft_id + time).
- **`run_vitals_events`** — catch-all event stream: app-sourced `turn_hold`,
  watcher-sourced `watch_end_*` (with stall count + transcript link).
- **`run_vitals_runs`** — one summary row per watched run, INSERTed by
  `scripts/persona_run_vitals_finalize.py` (invoked automatically by the
  session watcher when a watch ends): exit reason, run/draft status, planning
  stage, coherence status (converged/parked/roadmap/walking), turn + GPT
  aggregates, holds/errors/stalls, run duration, and the best-effort OneDrive
  transcript path. INSERT-only: a re-finalized run adds a newer row.

Example queries:

```sql
-- slowest sections by average turn latency
SELECT section, COUNT(*) turns, AVG(latency_ms) avg_ms
FROM run_vitals_turns GROUP BY section ORDER BY avg_ms DESC;

-- runs that hit holds or errors
SELECT draft_id, business_name, holds, errors, stalls, exit_reason
FROM run_vitals_runs WHERE holds > 0 OR errors > 0 OR stalls > 0;
```

Caveat: the turn accumulator is process-global (serial persona runs by
design); two simultaneous consult turns on one server would cross-attribute
GPT calls — same doctrine as the one-server-per-run rule below.

## Ground truth for persona runs

No pre-written persona spec — a real client doesn't hand over an answer
key, and pre-writing one biases what gets flagged. After a run,
reconstruct ground truth from the full transcript in:

`C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\Test Runs`

and adjudicate subjective reports ("that lever didn't fit my business")
against the transcript + the run's backend artifacts (trace rows,
judgment ledger, bounds).

## Concurrency

One server process per concurrent run. The run pipeline keeps process-global
state (trace context, GPT budget counter, OpenAI deadline); two simultaneous
system runs on one server clobber each other. Serial persona runs on :5050, or
one port per run (the historical `_logs_5050/5051/5058` pattern).
