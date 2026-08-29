# mini's audit of the payroll close — 2026-08-28

Commits audited: `231b0b1`, `4f06f6d`, `39d21b1`, re-blesses `035838a` / `655d5d7`,
prove `18f2306`. Everything below was measured on artifacts, not read off VS's claims.

---

## (a) IS THERE A THIRD PATH that writes a named person's FTE? — YES. Named.

Two independent methods, and they agree.

**By source enumeration** (the method the task asked for; a population sweep alone
could not answer it). Every assignment to `starting_fte` / `ending_fte` / `hires`
across `python/` and `client_statements_output_excel/`. Nine files mention the keys;
eight are read-only — `workbook_payload_contract.py` (a pydantic field),
`payroll_validator_translator.py` (an error string), `post_intake_mapping.py`
(contract metadata), `schedule_sanity.py` (reads), `initialize_post_intake.py`
(a field list), `gpt_payroll_author.py` (a JSON schema), `lookup.py` (a zeroed
quarter-total seed), `set_payroll_schedule.py` (reads). No `.update()`,
`setdefault()` or `pop()` idiom touches them anywhere.

**Every writer lives in `post_intake_headcount/schedule.py`**, at five sites:

| # | site | what it does to a key_person row |
|---|---|---|
| 1 | `_normalize_mechanical_fte_continuity` L488–505 | continuity only — can only RAISE |
| 2 | `_validate_payroll_title_rows` continuity block L1587–1602 | continuity only — can only RAISE |
| 3 | **`_validate_payroll_title_rows` part-time hours adaptation L1657–1662** | **THE THIRD WRITER — scales FTE DOWN** |
| 4 | `enforce_labor_scaling_on_payload` L2404 | key_person rows `continue`d out — exempt (3560a08) |
| 5 | `_enforce_forward_fte_continuity` L3473 | continuity only — can only RAISE |

plus `_headcount_coherence_is_recorded_not_applied`, which I confirmed is now a
literal pass-through (`return rows`).

**Site 3 is the third path.** When a row's `annual_wage` is under its wage floor
and the title text contains "part-time"/"part time", it sets
`FTE = FTE x (annual_wage / row_floor)`, clamped to `[0.05, 1.0]`. It reaches named
people: the same block explicitly branches on `staffing_class == "key_person"` for
the floor lookup (L1634). This is the mechanism that produces Understory's 0.84.

**By population sweep** (1,078 drafts rebuilt through the real producer —
`replay_gate/_cw043_audit/mini_named_fte_population_sweep.txt`): 995 named-person
rows land off 1.0, across 194 drafts. **Every single one carries
`wage_source = client_override|part_time_hours_adapted`. Zero from any other cause.**
The two methods close on the same answer: both scalers are silent, and the
part-time adaptation is the only remaining writer that moves a named person.

### Two things about site 3 that need Nick

1. **The fraction is DERIVED, not stated.** All 995 rows have a client-stated wage
   of $25,000; the FTE is wage ÷ OEWS floor. Nick's rule is "1.0, or the stated
   fraction of a real part-timer". The part-time-ness is stated (it is in the
   title); the *number* is the engine's inference of hours from dollars. Bridgeburn's
   "Part-time Packer 1" reads 0.88 — a figure the client never said.
2. **There is no owner guard in that block.** The docstring says "An owner is never
   floored at all", but that rests on upstream `client_override`, not on a check
   here. An owner titled "Owner (part-time)" with a stated wage under the state
   min p10 would be scaled. I found no such draft in the population — untested,
   not broken.

---

## (b) The exemption on drafts VS did not use — HOLDS, with a real control

`replay_gate/_cw043_audit/mini_exemption_probe.py`. The **real**
`enforce_labor_scaling_on_payload` driven over 400 drafts, both call shapes
(round-1 up-only and Phase B `allow_scale_down=True`), with an anchor that forces
a scale-DOWN (target 35%) and a scale-UP (240%):

```
named FTEs MOVED by a forced SCALE-DOWN: 0
named FTEs MOVED by a forced SCALE-UP  : 0

CONTROL — did the scaler actually fire?
   SUPPORTING FTEs moved on the scale-DOWN: 100 / 400
   SUPPORTING FTEs moved on the scale-UP  : 398 / 400
   drafts with no supporting block at all :   4
```

The control matters: without it the green is vacuous. The scaler fired on
398 of 400 drafts and moved the supporting block every time, and not one named
person moved in either direction.

13 drafts are **named-heavy** (named payroll ≥ the whole authored payroll) — the
shape both defects lived on. 11 of them VS did not use. All 11 rebuild every named
person at exactly 1.0.

---

## (c) allow_empty — the LIVE table confirmed, and nothing else is un-seeded

Read from the live DB, not the source. Exactly **two** rows carry `allow_empty=1`:

- `payroll_headcount_grid` — id 10372, `contract_name=payroll_headcount_schedule`,
  `contract_status=active`, `min_items=20`, `max_items=400`,
  **`updated_at = 2026-08-28 20:01:22`** — VS's reseed landed.
- `retry_reason` — a string, `validation_kind=schema_only`. The flag is read only
  inside the array branch (guarded by `len(value)==0` for min_items and `if not value`
  for the horizon rule), so a string is unaffected. VS's claim holds.

A third `payroll_headcount_grid` row exists (id 7518, `allow_empty=0`) but it is
`contract_status='retired'` under the retired `stage_ramp_contract` — not live.

**Un-seeded edits: none.** I diffed all 108 code-side `_DEFAULT_GPT_CONTRACT_ROWS`
against the live table across 17 semantic fields: 0 rows missing, 0 real
divergences. (14 apparent ones were my comparator failing to JSON-encode enum
lists — `['low','medium']` vs `'["low","medium"]'` — not divergences.)

---

## (d) Each tidy item asserts something TRUE — confirmed on recalculated artifacts

Built through the production exporter and recalculated in Excel. The stub
`Total Payroll` on the Payroll Schedule equals **both** Model Inputs and FINMO,
to the cent, on every draft tested:

| draft | sheet | Model Inputs | FINMO |
|---|---|---|---|
| Bluestem 52cf5792 | 81,750 | 81,750 | 81,750 |
| Understory 7042ce1a | 32,500 | 32,500 | 32,500 |
| Sunny Glaze cc8b7081 | 45,830.625 | 45,830.625 | 45,830.625 |
| Ironwood 1b9b4e45 | 98,500 | 98,500 | 98,500 |
| Halbrook ecd0e148 | 149,750 | 149,750 | 149,750 |
| EZ Drive 573df641 | 95,250 | 95,250 | 95,250 |
| Stillpoint 4fca544b | 18,500 | 18,500 | 18,500 |
| Bellweather 46ae584a | 56,500 | 56,500 | 56,500 |

Halbrook's 149,750 is the figure the commit message names. Stub `Total Ending FTE`
and `Total Average FTE` are **empty** (None), not 0, on all eight — headcount does
not assert zero people.

One residual, untested rather than broken: `formula = number(_stub_payroll) or 0`
writes a hard `0` if the "Payroll" expense row is ever absent — which would restore
the exact false claim the fix removed. I found no draft where it is absent.

---

## (e) TAMPER TEST — the scoping removed a false failure and NOT the check

Bluestem, Excel-recalculated after each poke
(`replay_gate/_cw043_audit/mini_payroll_close_audit.py --tamper`):

```
BASELINE                          -> Checks!B2=OK    tie-out=OK
TAMPER STUB    C17 += 99999       -> Checks!B2=OK    tie-out=OK     <- the false failure is gone
TAMPER SUMMARY Q1  := 424242      -> Checks!B2=FAIL  tie-out=FAIL
TAMPER SUMMARY Q5  := 424242      -> Checks!B2=FAIL  tie-out=FAIL
TAMPER SUMMARY Q20 := 424242      -> Checks!B2=FAIL  tie-out=FAIL
TAMPER DETAIL  M142 := 777777     -> Checks!B2=FAIL  tie-out=OK
FINAL RESTORED                    -> Checks!B2=OK    tie-out=OK
```

The check is **alive on the first, a middle, and the last live quarter**, and dead
on the stub. That is exactly what the scoping claimed. Confirmed.

### But the check it preserved was already near-vacuous — and that is PRE-EXISTING

The detail-side tamper is the interesting one. Read off the artifact:

```
summary cell        H17 = SUMIFS($M$114:$M$253,$A$114:$A$253,5)
the check's Q5 term ABS(H17 - SUMIFS($M$114:$M$253,$A$114:$A$253,5))
```

The summary cell **is** the check's expected value — the same expression on both
sides, for all three terms (G/H/M) in every live quarter. So on live quarters the
check evaluates `ABS(X-X)=0` by construction: it can only ever catch a hand-edit
of the summary cell, never a drift in the detail. Breaking a detail cell inside
the SUMIFS range moves both sides together and the tie-out stays OK.

**This is not a regression.** Live-quarter summary cells were `SUMIFS` before this
change too. The stub column was the one place the two sides were genuinely
different expressions (a literal against a SUMIFS over a detail with no stub rows)
— and they differed because of a units mismatch, which is precisely why scoping it
off was right.

The workbook is **not** blind to detail corruption: breaking M142 drove
Checks!B2 to FAIL via **"Payroll detail wage and tax math"**.

Triage: no wrong number reaches a client, so not a deal breaker. But the check's
own note — *"If this fails, payroll summary is no longer tied to detail FTE/payroll
rows"* — overstates what it can detect. Strengthening it is NEW BEHAVIOR and is
Nick's decision, never auto-built.

---

## (f) The five delivered workbooks — confirmed, plus three neighbours

Built and recalculated (`mini_named_fte_read.py`):

| draft | Checks!B2 | tie-out | named people | supporting |
|---|---|---|---|---|
| Bluestem 52cf5792 | **OK** | OK | 7, all 1.0 | none |
| Understory 7042ce1a | **OK** | OK | 3 at 1.0 + "Market & Sales Lead (part-time)" 0.84→0.94 | none |
| Sunny Glaze cc8b7081 | **OK** | OK | 2, all 1.0 (incl. the Lead Baker that read 0.11) | none |
| Ironwood 1b9b4e45 | **OK** | OK | 5, all 1.0 | none |
| Halbrook ecd0e148 | **OK** | OK | 3, all 1.0 | none |
| EZ Drive 573df641 | FAIL* | OK | 8, all 1.0 | none |
| Stillpoint 4fca544b | FAIL* | OK | 2 at 1.00→1.07 (stale payload) | none |
| **Bellweather 46ae584a** | FAIL* | OK | 2 at 1.07→1.28 (stale payload) | none |

\* the only failing row on all three is **"Marketing Schedule could not be built"** —
the pre-existing stale-marketing row, exactly as VS said. No payroll check fails
on any of the eight. No phantom roles anywhere.

---

## THE ONE THING THAT NEEDS NICK: already-delivered workbooks still carry the old numbers

The exporter renders `intake_consult_drafts.payroll_headcount` **as stored** — it
does not re-run the payroll producer. VS's five workbooks read 1.0 because VS
**re-authored those five payloads** on 2026-08-28 between 19:15 and 19:36.

| draft | payload stored | renders | rebuilds through today's producer |
|---|---|---|---|
| Bellweather 46ae584a | 2026-08-17 | 1.07 → 1.28 | **1.0** |
| Stillpoint 4fca544b | 2026-07-30 | 1.00 → 1.07 | **1.0** |

So the fix is right — both rebuild at exactly 1.0 — but any draft whose payload
predates it will reproduce the old number if it is ever rebuilt or re-delivered.
Whether to backfill the stored payloads is Nick's call.

---

## GATE FINDING (mine, not VS's): the goldens cannot see this class

- `R31` runs on frozen draft **89e5a622** (CareCompanions), whose `payroll_headcount`
  is **NULL** — no payroll payload at all.
- `R32`/`R49` grid the workbook built from frozen draft **6feac758** (Sunny Glaze),
  whose `solver_input.headcount_coherence` reads **`applies: false,
  right_size_factor: 1.0`** — the coherence scaler was **inert** on it.

So `39d21b1`'s "R31/R32/R49/R50 unchanged" is *true* but carries no evidence about
the scaler conversion, and the prove's 0 DRIFT should not be read as coverage of it.
R32 is a formula grid and R49 is static text; a changed FTE **value** cannot move
either.

Worse, the frozen fixture still carries **"Food Service Managers" at 0.20 FTE** — a
phantom supporting role below the new `ROUND1_SUPPORTING_MIN_REAL_FTE = 0.25` — and
**Alex Rivera at 0.27–0.31**. The re-blesses at `035838a`/`655d5d7` froze the
pre-fix shape, because fixture run-artifacts are frozen data and are not
re-authored. The gate's payroll surface is now pinned to a shape the product no
longer produces, and no golden leg can red on a regression that reintroduces
phantom roles or fractional named people.

Not a deal breaker (no client plan involved) — a gate-coverage gap, in my territory.

---

## PROCESS FINDING: declared-vs-actual on VS's turn 16

VS's declared plan (`_handoff/logs/watcher.log`, 2026-08-28 16:49:01) named **one**
change — the contract row, the mix, and the payroll sheet; "system-touching,
canary owed". The turn shipped **three** commits.

- `4f06f6d` (Checks tie-out scoping) is a legitimate follow-on: the live rerun of
  the declared work surfaced it and VS documented it fully.
- `39d21b1` is not. Converting `_apply_headcount_coherence_to_key_rows` is a
  **semantic change to a shared payroll path every plan flows through**, and it
  appears nowhere in the declared TASK, LOADING, or VERIFY. Under
  split-by-blast-radius a semantic re-scope of a shared path travels alone.

Naming it, not queuing it.

On the declared canary: there is no canary log for 2026-08-28. What exists instead
is five drafts re-authored through the live producer at 19:15–19:36 — stronger
evidence than a canary. Closing that as satisfied in substance.

---

## Gate floor

`replay_gate\gate.bat --only R31,R32,R49` → **3/3 GREEN**. R32's live digest
`a7d2ebcd7f89` matches both `legs.py` and the closed prove artifact — the re-bless
is self-consistent.
