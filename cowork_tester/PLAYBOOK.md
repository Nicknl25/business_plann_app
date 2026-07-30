# Cowork Persona Testing App — Playbook

This folder is the durable home of the Cowork-side persona testing app. Any
Claude Cowork session that is asked to "run persona tests" should read this
file first and follow it. The operator is Ignatius; he gives short commands,
never long instructions.

## What this app is

Claude drives persona-driven intakes against the live business-plan app as a
REAL founder would, decides what's worth testing, files issues to the shared
issue database, and keeps a coverage/agenda picture so testing accumulates
instead of repeating. Claude-in-VS watches the backend; Cowork owns the
client-experience side. Both write to the same MySQL store.

## Fixed facts (do not rediscover)

- Stack up: `powershell -File C:\dev\business_plann_app\scripts\start_persona_stack.ps1`
  → prints `STACK READY`. Idempotent-ish; restart backend after app-code edits.
- Client entry: `http://localhost:5173/business-plan-form` — FRESH TAB PER RUN
  (draft identity is in sessionStorage; reused tab = resumed old draft).
- SERIAL ONLY. One run at a time, ever. Batches are strictly sequential.
- Distinct human-readable business name per run (it's the join key to the
  OneDrive transcript).
- Issue write contract: `POST http://127.0.0.1:5050/api/issues` — full contract
  in `docs/issue_database.md` (read it every session). Categories exactly:
  hard_break | flow | verdict | experience. Severities: blocker | major |
  minor | note. Signatures from STABLE coordinates only. For `experience`
  issues, check existing open signatures (GET /api/admin/issues) before
  minting a slug — semantic dedup is Cowork's job.
- Reads for planning: `GET http://127.0.0.1:5050/api/admin/issues?status=&category=&limit=`.
- Resolution-sensing is automatic backend-side. Cowork's duty is only honest
  occurrences on exercised paths.
- VS monitors runs automatically. Do not coordinate; just run.

## Operator command grammar (short by design)

- `run P3 "law firm, two revenue streams, since 2019"` — one run, chosen persona.
- `... focus: bad monthly/annual answers` — optional; steers BOTH persona
  behavior and what Claude watches for.
- `run yours` / `batch 5` — Claude picks persona+business from the agenda.
- `agenda` — show ranked recommendations with reasoning.
- `issues` — glance at open issues.
- Anything ambiguous: Claude makes the sensible call and says what it assumed.

## Per-run procedure (Claude)

1. **Invent ground truth.** From the operator's one-liner (or own agenda),
   invent the founder's full knowledge: prices, volumes, costs, staffing,
   history — plausible for the business type. Apply the persona's distortion
   (planted basis mixes, wrong figures, defended positions). Write the
   ground-truth block into the runlog entry BEFORE driving the run.
2. **Fresh tab** → `http://localhost:5173/business-plan-form`. Confirm it's a
   new draft (empty form, new conversation).
3. **Drive the intake in character.** Real-founder discipline: know what this
   persona knows, guess what they'd guess, push back where they'd push back.
   Never break character to help the app. Answer at human length, not essay
   length. Through the full coherence walk to completion (converged / parked /
   roadmap — whatever it honestly reaches).
4. **Mid-run issues: keep going.** Log observations as they happen (notes in
   the run record with turn numbers). Only a hard break — app unresponsive,
   dead session — stops a run.
5. **File issues** after (or during, for clear-cut ones) via POST /api/issues,
   from a tab on the 127.0.0.1:5050 origin (admin dashboard tab) to avoid
   CORS surprises. Honest observed vs expected, verbatim on-screen quotes in
   evidence. Dedup experience signatures against existing open ones first.
6. **Finalize runlog entry** (`runlog.jsonl`): outcome, verdict class, issues
   filed (signatures), observations, draft business name, what this run
   covered. Update `coverage.json` and, if warranted, `agenda.json`.
7. **Refresh the operator console artifact** with new open-issue snapshot,
   coverage, recent runs.

## Batch procedure (Part B, after operator's go)

- Build/refresh agenda from: coverage gaps (business types × friction
  conditions), open issues needing retest (prioritize recently-touched
  areas — check `last_seen_at` and what VS/Ignatius say they fixed), and
  suspected-weak paths.
- Run serially. Between runs, re-read open issues + the last run's outcome and
  choose the next run accordingly (a new failure may be worth an immediate
  targeted follow-up).
- STOP the batch on: a blocker-severity hard break, the same hard_break
  signature twice in a row, or the stack going unreachable. Ten dead personas
  teach nothing.
- End of batch: consolidated report — runs, verdicts, new issues, recurrences,
  clean exercises, coverage delta, next recommendations.

## Retest discipline

Retesting = running a persona/business that EXERCISES an open issue's path
(its probe: section, business type, condition), then filing honestly — either
a new occurrence (recurred) or nothing (the backend counts the clean
exercise). Prefer The Straight Shooter for hard-issue retests unless the
issue is friction-dependent; then re-create the original friction.

## State files (this folder)

- `personas.json` — persona library (extensible; console renders from it).
- `runlog.jsonl` — one JSON object per run. Schema: run_id (CW-###), ts,
  persona, business_name, business_brief, focus, ground_truth {facts,
  planted_errors[]}, outcome {completed, verdict_class, turns, notes},
  issues_filed [signatures], observations [], coverage_tags [].
- `coverage.json` — business types × friction conditions exercised, with run
  refs; the gap list drives the agenda.
- `agenda.json` — current ranked recommendations {rank, persona, business,
  reason, kind: gap|retest|followup, status: proposed|approved|done}.
- `console.html` — source of the operator console artifact.

## Session boot checklist

1. Read this file, `docs/issue_database.md`, `docs/persona_run_observability.md`.
2. Stack check: GET :5050/api/business-types and :5173 via the browser; if
   down, start via the stack script (computer-use terminal) and wait for
   STACK READY.
3. Contract check (first session of the day): POST an intentionally invalid
   category to /api/issues and confirm a 400 — proves reachability and
   validation without polluting the registry.
4. GET open issues; reconcile with runlog/coverage; refresh agenda.
5. Report status to operator in a few lines; await command or `run yours`.
