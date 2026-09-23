# Write-path audit — Ashgrove Bindery bf731ee486254923986eb049688aed29
mini, 2026-09-22. Audit only; no app code touched.

Everything below is read from the STORE (MySQL), never from a log:
`intake_turn_interpretations` (the LIVE router's patch per turn),
`intake_turn_reader_extracts` (reader='driver_correction_reconcile' —
the ops object at the end of each turn), `intake_consult_drafts`
(final `operating_model_json`, via /debug/state), and
`post_intake_gpt_response_store` (the shadow one-reader's claims).

Code quoted at the version that was LIVE during the run: 4f52588d
(2026-09-18 19:00:13), i.e. BEFORE a04da00b (20:09) and 155fe713 (20:26).
Offline replays import that exact blob.

>>> CORRECTED 2026-09-22 (Turn A, _audit_ashgrove_two_sites_20260922.md):
>>> the run was NOT on 4f52588d. The store's own call_site says
>>> intake_consult.py:22727, which is 592d2583 (18:51) - 4f52588d has that
>>> call at 22750. The backend predates 19:00 and was never restarted. The
>>> doors quoted below are byte-identical across the two commits (offset 23
>>> lines), so the diagnoses stand; the "3c earns its place" ruling in (4) is
>>> a LIVE-TREE ruling, not a run finding - that block was not running.

---

## The turn-by-turn store record

| turn | her words | LIVE router patch (`intake_turn_interpretations.patch_json`) | row 1 at end of turn |
|---|---|---|---|
| 9 | "About ten." | `{"ops.product_overrides": {"Book binding & repair job": {"concurrent_capacity_units": 10}}}` | period=10, week=10, periods=null |
| 11 | "About eleven hundred." | `{"ops.annual_completed_units": 1100}` **(bare)** | unchanged; held in `_unrouted_driver_writes` |
| 13 | "Neither. That's how many I actually finish in a year." | `{"ops.product_overrides": {"Book binding & repair job": {"annual_completed_units": 1100}, "Short-run print job": {"annual_completed_units": 1100}}}` | **periods=110, week=21.1538**, annual_completed_units=1100 |
| 15 | "A hundred and ten dollars." | `{"ops.product_overrides": {"Book binding & repair job": {"unit_price": 110}}}` | periods=110, week=21.1538, **annual_completed_units GONE** |
| 17 | "Forty-eight. We close the last two weeks of December." | `{"ops.operating_periods_per_year": 48}` **(bare)** | **periods=48**, week reverted to 21.1538 |
| 19 | "In person…" | `{"ops.shipping_method": …}` | periods=48, **week=9.2308** |

Final stored `operating_model_json`: `operating_periods_per_year: 48`,
`units_per_period_capacity: 10`, `units_per_week_capacity: 9.2308`,
`unit_price: 110`. No `annual_completed_units` anywhere, no
`operating_weeks_per_year` anywhere.

**The router read her correctly both times.** The shadow one-reader
(`post_intake_gpt_response_store`, 19:38:50 and 19:40:54) emitted
`subject: ops.throughput, kind: actual, value: 1100, per: year` and
`subject: ops.operating_weeks, kind: actual, value: 48, per: year`. The
live router named the fields `annual_completed_units` and (at turn 13)
the per-line `annual_completed_units`. The mislabel is downstream of the
reader, not in it.

---

## (1) Who wrote 110, and who replaced it with 48

**48 — PROVEN, reproduced offline through the real door.**
`_apply_scoped_patch` → the row-less driver branch,
`python/api_handlers/intake_consult.py:17057-17070` (run-time blob),
log token `OPS_DRIVER_WRITE_ROUTED_BY_THE_QUESTION`. A bare driver key on
a multi-line model is normally refused and recorded as an open ask; it
lands anyway when **the app's own previous assistant message contains
exactly one row's product name**. Reproduced on the real two-row model:

    recent_assistant = ""                  -> 48 refused, open ask, periods stays 110
    recent_assistant = the real turn-16 text -> row1 periods=48, week=9.2308

Turn 16's text contains the literal string "book binding & repair job";
turn 10's text does not. Same door, same draft, same two rows, opposite
outcomes — decided by whether our own sentence happened to spell the row
name. That single line is why her 48 landed in the TURNS slot and why her
1,100 (turn 11, same bare shape) did not land at all.

**110 — NOT PROVEN. Narrowed, and VS's hypothesis is NOT confirmed.**
VS believed 110 = 1100/10 via `turns = ceiling / concurrent`. That
derivation is `_normalize_ops_capacity_compat`'s ANNUAL_PAIR_HOMED block
(run-time lines 678-704) and it **cannot** have fired here: it requires
`annual_capacity_units` (a CEILING), which the store shows was never
emitted; and when it does fire it pops `annual_completed_units` and sets
`utilization_rate` — at end of turn 13 the store has
`annual_completed_units: 1100` still present and `utilization_rate: null`.

Replaying the exact stored turn-11 ops object plus the exact turn-13
patch through the real `_apply_scoped_patch` yields
`operating_periods_per_year: None`. So 110 is written by a site AFTER the
patch door inside turn 13. The whole run-time tree has only three readers
of a row's `annual_completed_units` (intake_consult 679/697, and two
allowlists), none of which produce it. **Writer not yet named.**

Corroboration for the arithmetic, with a built-in control: the same 1,100
went to BOTH rows at turn 13; only row 1 (which had
`units_per_period_capacity: 10`) got `periods: 110`; row 2, with no
capacity, got no periods. That is consistent with `periods = annual /
period-capacity` and with nothing else — but consistency is not the
function name, so it is reported as open.

## (2) Her stated 1,100 is in no field — CONFIRMED

Confirmed against the final store: `annual_completed_units` is absent
from every row, from every LOB and from the business level; no field
holds 1100. (`unit_price: 110` is her price, a different number.)

The writer that SHOULD have stored it is
`_apply_ops_product_overrides` (run-time `intake_consult.py:3447`),
reached from `_apply_scoped_patch`'s `product_overrides` branch. It DID
store it at turn 13 — the store shows 1100 on both rows at the end of
that turn, and my replay reproduces that write. It was then lost between
the end of turn 13 and the end of turn 15. Not by ANNUAL_PAIR_HOMED (see
above: no ceiling, no utilisation). **The site that drops it is not yet
named** — same open thread as 110.

At turn 11 it never landed at all: the router emitted it bare, there were
two rows, and turn 10's message did not contain a row name, so it was
held as an open ask (`_unrouted_driver_writes`) — visible in the store at
turn 11 and cleared at turn 13.

**The receipt lied.** Turn 14 told her: "we'll treat 1,100 as the number
of individual binding/repair books you actually finish in a typical
year", and turn 14 also told her she finishes "1,100 book binding &
repair jobs **and 1,100 short-run print jobs** each year" — a figure she
never gave for the print line. Neither survived to the store.

Turn 12 is worth naming separately. The app DID stop to disambiguate:
"So that I record it the right way round - is 1,100 how many working
weeks or months a year you run, or the most you could finish in a year?"
That question comes from the unresolved-figure readback,
`intake_consult.py:16319`, whose options are
`cands = [question_field] + others[:1]`. The router's `unresolved` record
(store, turn 11) listed FOUR candidates —
`[operating_periods_per_year, annual_capacity_units,
annual_completed_units, units_per_period_capacity]` — and `others[:1]`
truncated to one, so the true answer, `annual_completed_units`, was
dropped from the list of things she was offered. She answered "Neither.
That's how many I actually finish in a year." and named it in plain
words anyway.

## (3) Does the per-row engine overwrite a figure the client stated? — YES

`_derive_capacity_cells`, `python/api_handlers/intake_consult.py:20228-20238`
(current working tree; same shape at run time). On any non-weekly
cadence the period cell is canonical and `units_per_week_capacity` is
recomputed as `_per * _periods / _wy` and written whenever it disagrees
by more than 0.05%. There is **no provenance check** — nothing asks
whether the week figure came from the client.

Proved on a real row through the real door (live working-tree code),
a row carrying her stated 17/week beside period=10, periods=119:

    cadence=contract   her 17/wk -> 22.8846     period=10
    cadence=monthly    her 17/wk -> 22.8846     period=10
    cadence=weekly     her 17/wk -> 17          period=17.0

Her seventeen does not survive on contract or monthly. Only on weekly,
where the week cell is the canonical one, does it stand (and there the
period twin is overwritten instead).

This is the sharper form of the same question as (4): the sibling site,
"3c", explicitly refuses to touch a stated value — *"A value we derived
is ours to recompute; a value SHE stated is never touched, which is why
only the derived one carries this mark."* Two sites, one law, and only
one of them obeys it.

## (4) What recomputed 21.1538 into 9.2308 — settled

**VS was right that it was not 3c, and wrong that nothing recomputed.
Cowork's observation is correct.**

The producer is `_derive_capacity_cells` (via `_derive_ops_cells`),
called at `intake_consult.py:17069` immediately after the routed landing
in (1). The rounding is the fingerprint and it is decisive:

* `_derive_capacity_cells` writes `round(_derived_wk, 4)` — **4 dp**
* `_normalize_ops_capacity_compat` (3c and the plain conversion beside
  it) writes `round(_pv * _p / _weeks, 6)` — **6 dp**
* stored: `21.1538` and `9.2308`. `1100/52 = 21.153846…`,
  `480/52 = 9.230769…`. Both are 4 dp.

Reproduced end to end: feeding the real turn-15 ops object and the real
turn-16 assistant text into `_apply_scoped_patch` with the bare 48
produces `periods=48, week=9.2308` — the store's value, exactly, offline.

Note what the 9.2308 also proves: `10 x 48 / 52`. Her stated 48 weeks
were used as the TURNS and the divisor was still the literal 52. That is
the second-conversion defect a04da00b/155fe713 were written for; this run
predates both, and I have not verified those commits end to end here.

**Ruling on 3c: it still earns its place, and it is the site that is
RIGHT.** It is not redundant with `_derive_capacity_cells` — it carries
the provenance mark (`_units_per_week_derived_from_weeks`) and recomputes
only a value the app itself derived. `_derive_capacity_cells` recomputes
unconditionally, so on contract and monthly rows it will overwrite the
stated figure 3c was built to protect, and it runs on the same rows. The
defect is not "3c is redundant"; it is that the unguarded site can undo
the guarded one.

---

## Process findings

* **VS's working tree carries uncommitted app-code changes** —
  `python/api_handlers/intake_consult.py` (+148) and
  `python/client_intake_and_finmo/intake_coherence/section.py` (+95) — a
  2026-09-22 write-time bounds guard (`_FIELD_BOUNDS`,
  `_implausible_for_field`, `_hold_an_implausible_write`,
  `implausible_write_hold_question`) that adds a NEW client-facing
  question. The live :5050 backend is serving it. Under TRIAGE-BEFORE-FIX
  that is the X2 class — new behaviour, Nick's call, not auto-built.
* **A provenance claim inside that uncommitted guard is false.** Its
  docstring says *"This fired exactly once in the whole investigation and
  it is the only time the app caught a mislabel itself: Ashgrove Bindery
  bf731ee4 turn 12."* Turn 12 was produced by the unresolved-figure
  readback at `intake_consult.py:16319`, not by the guard being
  generalised: the guard it replaces read
  `{"monthly": 12.0, "weekly": 53.0}.get(cadence)`, this row's cadence is
  `contract`, so it returned None and the branch could not run. The one
  success being cited as the reason to generalise is not this guard's.
