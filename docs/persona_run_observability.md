# Persona-run backend observability

How to run the backend so a browser-driven persona run (Claude Cowork as the client)
is fully observable from the backend side, live.

## Startup

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

## Concurrency

One server process per concurrent run. The run pipeline keeps process-global
state (trace context, GPT budget counter, OpenAI deadline); two simultaneous
system runs on one server clobber each other. Serial persona runs on :5050, or
one port per run (the historical `_logs_5050/5051/5058` pattern).
