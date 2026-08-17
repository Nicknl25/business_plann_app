# A-122 — Submit validator rejects a valid single-line model (Tanager Print Works, 87f0fbba) — RESEARCH for Nick's ruling

Status: research, 2026-08-17. NOTHING BUILT. Cited to code, DB, and the
persona log.

## Root cause — NOT a residual empty row; a flat-first validator the flat-cell retirement never converted

**There is no empty row anywhere.** The persisted `operating_model_json`
for 87f0fbba has exactly one LOB / one product with every driver
populated (`unit_name "print job"`, `unit_price 720`,
`units_per_week_capacity 28`, `units_per_period 28`, `unit_cadence
weekly`, `utilization 0.7`, `periods 52`); `GET /api/shared-context`
returns `operating_model` byte-identical to the column; the discovery
latch is a self-contained dict (bindery = `answer: "merged_into:print
job"`, no row, no slot). **bd1a541 behaved correctly.**

The submit validator (`intake_submit_service.py:317-364`) validates
**flat top-level scalars** on the payload — `unit_name`,
`unit_description`, `units_per_week_capacity`, `unit_price` — whenever
`is_multi_lob` is False (`:211-227`: one LOB with one product ⇒ False).
It never iterates `lob_models` rows. And the ops canonical pass
`_derive_ops_cells` (`intake_consult.py:16131-16160`, `_OPS_FLAT_DERIVED_
FIELDS` :16035) **deliberately deletes those exact flat keys whenever
product rows exist** — the UNIVERSAL ENGINE phase 4 "flat driver cells
RETIRED (Nick-cleared)" change, **539fb17, 2026-08-12**. Every reader was
converted to row-first (`_ops_driver_value` :16041, "the flat key
survives only on rowless legacy drafts") — **`intake_submit_service.py`
was missed. It is the last flat-first reader in the system.**

Smoking gun: `unit_description` is NOT in the retired tuple, so the
back-fill sites (`intake_consult.py:967-989`, `:20950-20981`) leave it on
the flat level while the other seven get stripped — exactly the DB
state (flat `unit_description` present, flat `unit_name/price/capacity`
absent). Proof the back-fill ran and the strip won.

## Q1-Q4 answers
1. What submit validates: `payload` = the draft's persisted
   `operating_model_json` top-level keys merged in server-side
   (`financials.py:280-284`) + 9 contact fields from the browser
   (`SubmitStep.tsx:41-52`; the POST body carries NO lob_models/units/
   prices — log line 928 confirms). The banner is Flask's sorted-key
   error dict rendered by `SubmitStep.tsx:74-87` for unmapped keys.
2. Residual empty row: **NONE** — refuted against the persisted model,
   the shared-context object, and the latch.
3. Right source of truth: it reads the right OBJECT (persisted
   operating_model_json) but the wrong SHAPE — flat scalars that the
   engine retired as a second copy of the drivers. The divergence is
   between the submit CONTRACT (flat) and the at-rest SCHEMA (rows).
4. New to bd1a541? **No.** `git show --stat bd1a541` touches no submit /
   financials / shared-context / frontend files. Latent since 539fb17
   (Aug 12); bd1a541 merely made SINGLE-product outcomes reachable on
   discovery drafts (before it, every discovery draft ended
   multi-product ⇒ `is_multi_lob=True` ⇒ the flat checks are skipped).
   Controls: Nine Fathom 6d2823db (3 products, same flat cells absent)
   ⇒ skipped ⇒ submitted fine; **Sumac Ridge clone mn33t5g9 (1 product,
   Aug 14) ⇒ never submitted — a pre-existing casualty 3 days before
   bd1a541.** Fetch & Fluff 50658fff (Aug 10, pre-539fb17, flat cells
   present) submitted fine. Post-539fb17 single-product: 0/2 succeed.

## Persona log
Three `POST /api/financials -> 400` in ~31 ms each (12:32:11, 12:34:49,
12:37:30): `IntakeValidationError` raised at `intake_submit_service.py:
403-404`, caught `financials.py:318`, before any DB write ⇒
`mark_submitted` never runs ⇒ `_start_system_run_in_background` never
fires ⇒ `planning_run_status` stays `pending`, no reference code. Client
stranded on a valid model.

## Triage
DEAL BREAKER (client stranded on the guided path with a correct model;
no plan). Class: every single-line business since Aug 12 (any draft
that ends with one product) — the majority of real businesses. Nine
Fathom/Corvid passed only because discovery had made them multi-line.

## Fix shape (NOT built; VS declares tier — spot-check expected, with
the new VERIFY-FORWARD law's hard case: an end-to-end SUBMIT + BUILD on
a single-product draft)
Make `intake_submit_service.py` ROW-FIRST like the rest of the engine:
resolve `unit_name / unit_description / unit_price /
units_per_week_capacity` through a row-first read (first non-None across
`lob_models[*].products[*]`, falling back to the flat key ONLY for
rowless legacy drafts) before the checks at :319-321 / :347 / :355 — and
feed the same resolved values into `insert_intake_submission` (the
`intake_submissions` columns must carry 720 / 28 / "print job", not just
pass the gate). Do NOT revert 539fb17 (would restore the dual-write
staleness class); do NOT flip `is_multi_lob` True for single rows (would
skip validation entirely). Regression subjects sitting ready: 87f0fbba
(Tanager) and mn33t5g9 (Sumac clone) — submit + build both; plus a
multi-line control (Nine Fathom) and a rowless legacy control
(50658fff) to prove the fallback.
