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

---

# FLOW CONTRACT — my written model (added 2026-08-11)

CANONICAL SOURCE: `docs/INTAKE_FLOW_CONTRACT.md` in the app repo. Read it at the
start of every session. This section is NOT a copy — it is only the rules I test
against, so it cannot drift into a competing spec. If it disagrees with the file,
the file wins. If the FILE disagrees with observed code, that is doc drift and I
file it as such.

## The pre-filing gate — run this before every issue

1. Is the field a LATER STAGE than the one active? -> not a bug. Don't file.
2. Is it a PROPOSAL (stages 1-4: revenue, cogs, payroll, marketing)? -> the anchor
   differing from the client's actuals IS the design. File ONLY if: a promised band
   is missing (COGS), acceptance records something other than what was shown, or a
   correction is refused.
3. Is it a DERIVED TWIN (current_payroll, payroll_total_year1, owner_compensation,
   cogs twin family, year1 rollups)? -> a direct write evaporating is BY DESIGN.
   Never file "the write didn't stick" against a derived field. File the DOOR
   instead (see below).
4. Is it on the do-not-refile list? -> don't file.
5. Only then: does it STRAND THE CLIENT or CORRUPT THE BUILT PLAN?

## The one-door payroll law

`current_payroll` is derived from PEOPLE. Correction doors are
`people.total_team_payroll`, `people.rest_of_team_payroll_year1`,
`people.owner_pay_monthly`, `people.remove_role`. So "payroll is uncorrectable"
is the WRONG finding. The right findings, per contract section 4, are:
  - a correction produced no "Recorded:" receipt
  - a figure that landed nowhere was not DISCLOSED
  - prose claimed a write ("I'll use $X") that did not land
  - the same gate/wall message repeated verbatim after a correction
Those four are named "file immediately" in the contract. Use those words.

## Built-plan verification rule (contract section 6)

At run entry the SAME Recalc re-runs and persists before the grid reads anything.
Therefore:
  - stored-vs-workbook difference on a DERIVED field = design, the workbook is truth.
    NEVER file this.
  - stored-vs-workbook difference on a CLIENT-CAPTURED field = bug. File it.
  - a coherent draft rerun must produce a BYTE-EQUAL workbook. A diff is a finding.

## Testable invariants worth probing

  - "acceptance of an option NEVER moves the ceiling" (section 5) -> the CW-024
    price ratchet is a genuine contract violation. Retest and record the ceiling
    at every offer.
  - the two-beat rule: receipt ALWAYS precedes any gate verdict.
  - a mid-walk collapse triggers hold-and-confirm, never an abrupt verdict flip.
  - an empty/contentless turn re-shows the gate's standing message.
  - volunteer clusters (debt 13-16, balance 17-20): naming several siblings in one
    message must land them all; skipped questions there are CORRECT.

## Do-not-refile (contract section 7)

marketing proposal has no band; owner wage cents artifact (38,000.04); headcount in
financials while payroll dollars live in people; people-section rest-of-team
enumeration (CW-025 rank-2, in progress); cogs_basis re-tag after ratio-stamped
acceptance (in progress); baseline_marketing contamination (in progress).

## Language discipline (standing)

"the ack said X" and "the stored field is X" are DIFFERENT SENTENCES. Never write a
storage claim without having read the field. Close non-reproductions in the same pass.

## STANDING COMPREHENSION PROBE (Nick, 2026-08-13)

The persona is a cooperative business owner who is NOT a numbers
person. You should not need an MBA - or even a BA - to use this app.

If the app ever speaks jargon the persona would not understand - an
internal field name, an unexplained unit token ("ratio", "basis"), an
unglossed acronym, a bare decimal where a human framing belongs - that
is a COMPREHENSION FAILURE. File it as an experience issue, even when
the numbers are correct.

The checked property on every run: "would a normal small-business
owner understand this sentence?" A receipt can be perfectly faithful
and completely opaque - faithfulness is checked elsewhere; THIS probe
checks understandability. "COGS" is borderline ("direct costs" is
friendlier); "cogs_per_line_overrides" must never reach a client.
