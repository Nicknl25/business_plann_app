# Shared issue database (persona testing)

The Cowork testing app detects issues while driving personas against the live
site and writes them here; this side owns the schema, recurrence/resolution
accounting, and the dashboard. Same MySQL store as the `run_vitals_*` tables,
so every issue joins to its run's backend truth on `draft_id` — one join, no
bridge.

Code: `python/client_intake_and_finmo/issue_registry.py`
Dashboard: `http://127.0.0.1:5050/admin/issues`
Checker: runs automatically after every watched persona run
(`persona_run_vitals_finalize.py`); manual sweeps via
`scripts/issue_resolution_check.py --draft-id <id> | --latest N`.

## Tables

- **`issues`** — the registry, ONE row per unique issue keyed by
  `signature` (UNIQUE). The deliberate UPDATE exception to INSERT-only
  discipline: it holds current state; every state change is mirrored by an
  INSERT-only audit row in `issue_resolution_events`.
- **`issue_occurrences`** — INSERT-only, one row per sighting: draft_id,
  planning_run_id, business/persona, turn_index, section, stage, severity,
  `observed` (what the app did), `expected` (what should have happened),
  evidence_json, source (`cowork` | `auto_check` | `human`).
- **`issue_resolution_events`** — INSERT-only audit: `exercised_clean`,
  `recurred` (implicit via occurrences), `reopened`, `resolved_confirmed`,
  `resolved_observational`, `manual_resolve`.

## Write contract (Cowork)

HTTP (preferred — works while the stack is up, validates loudly):

```
POST http://127.0.0.1:5050/api/issues
{
  "signature":  "flow:financials:asked_twice:future_rent_expected",
  "category":   "flow",              // hard_break | flow | verdict | experience
  "severity":   "major",             // blocker | major | minor | note
  "title":      "future_rent clarifier asked twice",
  "observed":   "The consultant asked about expected future rent, I answered, and two turns later it asked the same thing again.",
  "expected":   "One answer to the rent question is captured and not re-asked.",
  "draft_id":   "<the run's draft_id>",
  "planning_run_id": "<if known>",
  "business_name": "Sunny Glaze Donuts",
  "persona":    "anxious_first_time_baker",
  "turn_index": 14,
  "section":    "financials",
  "resolution_class": "",            // optional override, see below
  "probe":      {"section": "financials"},   // optional, see resolution-sensing
  "evidence":   {"quote": "…verbatim on-screen text…", "at": "2026-07-30T14:02"}
}
```

400 with the exact vocabulary error on any bad category/severity — a typo
must bounce, never mint a phantom taxonomy. Python path: `issue_registry.
report_issue(conn, ...)` (same fields).

Reads: `GET /api/admin/issues?status=&category=&limit=` (also feeds the
dashboard), or SQL directly — Cowork should query `issues` for its agenda
(open/recurring, what to retest) and search existing signatures before
minting a new one.

## Categories

- `hard_break` — error / stall / crash / hold the client can see.
- `flow` — conversation logic: asked twice, loop, dead-end, no path forward.
- `verdict` — wrong outcome class for the business (converged when it should
  have parked, roadmap when it should have converged, …).
- `experience` — confusing question, lever that didn't fit the business,
  tone, plan didn't feel like the business.

Severity: `blocker` (run can't finish / client is stuck), `major` (wrong or
costly outcome), `minor` (friction), `note` (observation worth keeping).

## Signature — the identity of "this same issue" across runs

Stable slug, authored by the reporter, built ONLY from stable coordinates —
never from draft_id, timestamps, or verbatim GPT text (those vary per run).
Convention `<category>:<locus...>`:

- `hard_break:<phase>:<section-or-stage>:<failure-class>` —
  e.g. `hard_break:intake:financials:turn_hold_timeout`,
  `hard_break:post_intake:fitted_band_solve:stall`
- `flow:<section>:<pattern>:<field-or-question>` —
  e.g. `flow:financials:asked_twice:future_rent_expected`
- `verdict:<business-slug>:<expected>-vs-<actual>` —
  e.g. `verdict:sunny_glaze:converged-vs-parked`
- `experience:<section>:<topic-slug>` —
  e.g. `experience:financials:rent_question_confusing`

Recurrence == a new occurrence arriving under an existing signature, so the
slug IS the resolution-sensing key. For `experience` issues Cowork owns the
semantic matching: before minting a new slug, check whether an existing
signature describes the same complaint (phrasing differs, issue doesn't).

## Resolution-sensing — honest about certainty

`resolution_class` on each issue, defaulted by category
(`hard_break`/`verdict`/`flow` → `hard`, `experience` → `soft`; the reporter
may override, e.g. a phrasing-dependent flow issue → `soft`):

- **hard** — deterministically resolvable. When a later run **exercises**
  the issue's path and the failure does not recur, that's an
  `exercised_clean` tick; at `hard_clean_threshold` (default 1) consecutive
  clean exercises → `status=resolved`, `resolution_basis=retested_clean`,
  `resolution_confidence=confirmed`.
- **soft** — GPT phrasing varies run to run; absence is weak evidence. Soft
  issues can ONLY reach `resolution_basis=not_seen_n_runs` with
  `resolution_confidence=observational`, after `soft_runs_threshold`
  (default 5) exercised runs without a recurrence. `confirmed` is
  unreachable for soft issues by construction.

**Exercised** is decided by the issue's `probe` predicate against that run's
vitals — absence without opportunity is never evidence. Probe vocabulary
(all clauses must pass):

| key | meaning |
|---|---|
| `section` / `sections` | run visited the section(s) (`run_vitals_turns`) |
| `call_label_like` | a GPT call matching this label ran (`run_vitals_gpt_calls`) |
| `stage_like` | planning stage reached (`planning_stage_events`) |
| `business_like` | draft's business name matches (verdict issues) |
| `min_turns` | at least N intake turns |
| `require_completed` | planning run completed (default true) |
| `auto_recur` | opt-in machine recurrence: `{"stall": true, "hold": true, "gpt_error_like": "ReadTimeout%"}` — the checker re-reports the issue itself (source `auto_check`) when the signal fires |

No probe → one is derived from the first occurrence (its section; business
for verdict issues). No probe and nothing derivable → the issue is never
"exercised" and must be resolved manually
(`issue_registry.resolve_manually`, basis `manual`).

Any recurrence resets both counters. A recurrence after `resolved` flips to
`status=recurring` and increments `reopened_count` (the dashboard shows
`×N`) — the prior resolution verdict is cleared on the registry row but
preserved in `issue_resolution_events`.

## Lifecycle summary

```
report → open ──(exercised clean × threshold)──→ resolved
  ↑                                                 │
  └──── counters reset ──── new occurrence ─────────┘→ recurring (reopened_count++)
```

`first_seen_at` / `last_seen_at` / `resolved_detected_at` are on the
registry row; `occurrence_count`, `clean_exercise_count` (hard progress),
`runs_since_last_seen` (soft progress) are maintained by the write path and
the checker.
