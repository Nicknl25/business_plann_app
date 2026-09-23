# TURN A — the two unnamed write sites, named

Ashgrove Bindery and Print, draft `bf731ee486254923986eb049688aed29`.
mini, 2026-09-22. Audit only; no app code touched.

Evidence: `replay_gate/_audit_ashgrove/prove_two_sites.py` (re-runnable) and
its saved output `prove_two_sites_output.txt`. Everything below is read from
the STORE — `intake_turn_reader_extracts` (reader `driver_correction_reconcile`,
one row per client turn, written at the reconcile call), `intake_turn_interpretations`
(the live router's patch), `intake_consult_drafts.messages_json` — never from a log.

---

## FIRST, A CORRECTION TO MY OWN LAST AUDIT: the run was NOT on 4f52588d

`_audit_ashgrove_write_path_20260922.md` quotes code "at the version that was
LIVE during the run: 4f52588d". The store says otherwise, and it is decisive:
every reconcile extract of this run carries

    call_site = intake_consult.py:22727 post_intake_consult_handler

22727 is that call's line in **592d2583** (09-18 18:51). In 4f52588d (19:00) it
is 22750; in a04da00b 22760; in 155fe713 22771. The backend was started before
19:00 and was never restarted, so turns 5..19 (19:37–19:41) ran **592d2583**.

What that changes: nothing in the diagnosis, and one claim in the old doc.
The two commits differ only by the 3c provenance block, and I diffed the driver
door region byte-for-byte across them (identical, offset 23 lines). So the 48
proof stands, at `intake_consult.py:17034-17047` in the code that actually ran
rather than 17057-17070. But the old doc's ruling "3c still earns its place"
was about a block (`_units_per_week_derived_from_weeks`) **that was not running
during this run at all** — it arrived 9 minutes after the backend started and 37
minutes before the killing turn. It is a live-tree ruling, not a run finding.

Line numbers in this document are 592d2583 unless marked HEAD.

---

## (1) operating_periods_per_year = 110 — THE OPS CONSULTANT'S OWN SNAPSHOT

**Site: `_apply_model_ops_patch`, `python/api_handlers/intake_consult.py:1334-1348`
(the `ops_json[key] = v` assignment at 1345), fed by `consultant_chat_turn`'s
`patch` at 24880.**

The ops consultant returns a strict-schema object
(`python/client_intake_and_finmo/intake_consultant.py:546-585`) in which
**every product carries `operating_periods_per_year` as a REQUIRED key**. The
model had been told, in its own previous sentence, "10 at once" and "1,100 a
year". It emitted the division. 1,100 / 10 = 110.

The arithmetic is not in our code — that is exactly why the hunt for a code site
came up empty. Elimination, exhaustive over the live tree at 592d2583:

* Every write to `operating_periods_per_year` in `intake_consult.py` is a
  constant or a clear (799 None, 808 None, 818 `= operating_weeks_per_year`
  — absent on this row, 821 `52`, 827 `1`, 833 `12`, 890 None).
* The alias fold (`d[_canon] = _av`, 731) can only carry a figure written to
  `annual_turns_per_year`, and the only writer of that name is ANNUAL_PAIR_HOMED
  (692), which needs a stated CEILING and, when it fires, pops
  `annual_completed_units` and sets `utilization_rate`. The store at the end of
  turn 13 has the actual still present and utilisation null, so it did not fire.
* `_derive_capacity_cells` / `_derive_ops_cells` never write periods at all.
* No other module writes periods onto an ops row (`financials_year1` writes its
  own output object; `capture_receipt` only reads).
* The turn-13 router patch is in the store and contains no periods key.

That leaves one input carrying a periods figure into this draft: the
consultant's snapshot. Replayed through the real door on the real store row, it
reproduces the store **exactly, to the rounding**:

    STORE, turn-11 reconcile:  per=10  periods=None  week=10
    + the snapshot            -> per=10  periods=110  week=21.1538
    STORE, turn-13 reconcile:    per=10  periods=110  week=21.1538

The 21.1538 is the confirmation: 4 dp is `_derive_capacity_cells`'s
`round(_derived_wk, 4)` (10 x 110 / 52), not the normaliser's 6 dp. The week
figure could only be computed after periods=110 was already on the row.

Timing agrees: `run_vitals_gpt_calls` puts `ops_consult_chat_turn` for turn 11
at 19:38:54, i.e. **after** the turn-11 reconcile extract (19:38:50, no 110) and
before turn 13 (19:39:38, 110 present).

## (2) annual_completed_units = 1100 dropped — THE SAME ASSIGNMENT, ONE KEY SHORT

**Site: `_carry_forward_per_line_drivers` via `_CARRIED_PER_LINE_KEYS`,
`python/api_handlers/intake_consult.py:15628-15639`, called from
`_apply_model_ops_patch:1345`.**

The consultant's `lob_models` is assigned wholesale. `_carry_forward_per_line_drivers`
exists precisely to stop that erasing what the client said — it restores the
keys named in `_CARRIED_PER_LINE_KEYS`. That tuple is:

    unit_price, units_per_week_capacity, units_per_period_capacity,
    operating_periods_per_year, utilization_rate,
    avg_units_per_period_year1, avg_units_per_week_year1,
    operating_weeks_per_year, _concurrent_turns_asked, _periods_default_for

`annual_completed_units` is not in it. Nor is `annual_capacity_units`. So a
figure the per-line door had written seven seconds earlier ceased to exist —
key gone, not null. Replayed on the real row:

    STORE, turn-13 reconcile:  annual_completed=1100 on BOTH rows
    + the snapshot            -> annual_completed=None on both
    STORE, turn-15 reconcile:    annual_completed absent on both   (matches)

This is the Vasquez-Lindqvist class the carry-forward was written for
("I reported that write as a success because the log line said 'landed'. It
had, for thirteen seconds."), recurring on the one driver name the list never
picked up.

### THIS ONE IS THE DEAL BREAKER

(1) alone is survivable: 10 x 110 still returns her 1,100, so her volume is
recoverable from the row. It is (2) that makes (1) lethal — with her own figure
erased, the turns slot is the *only* place her 1,100 exists, and the next
routine write to that slot destroys it with nothing left to notice. Turn 17:
48 lands, 10 x 48 = 480, a 56% cut, and the receipt tells her "48 working
weeks" while the store files 48 as the turns.

Triage: a number the client stated, carried wrong into the delivered plan's
revenue, on the guided path. DEAL BREAKER.

### AND IT IS STILL LIVE ON TODAY'S TREE (HEAD 1afb4d48)

`_CARRIED_PER_LINE_KEYS` at HEAD is unchanged — still no `annual_completed_units`.
Proven end to end in the same script, on HEAD code:

    1) the turn-13 router patch through the patch door
       -> her 1,100 lands on both rows (the keeper from fd1107f4)
    2) the SAME turn's consultant snapshot
       -> annual_completed_units gone from both rows again

So `ANNUAL_COMPLETIONS_HOMED` and the contradiction hold added in fd1107f4 /
1ba47652 (`intake_consult.py:892+`) both read `annual_completed_units` off the
row, and from the turn after she says it there is nothing there to read. The
hold cannot fire. **The keeper is not kept.** Turn C's routing change
(1afb4d48) happens to save Ashgrove specifically — the bare 48 is now refused
as row-ambiguous on this two-row model — but a single-line business, or the
same answer once a row is named, still walks the whole path.

## (3) "1,100 short-run print jobs a year" — a true receipt of a false write

Not a receipt invention, and not site (2). The store shows the figure really was
written to the print row: the turn-13 ROUTER patch itself named both lines —

    {"ops.product_overrides": {"Book binding & repair job": {"annual_completed_units": 1100},
                               "Short-run print job":       {"annual_completed_units": 1100}}}

and `_apply_ops_product_overrides` (`intake_consult.py:3446`, called at 16889)
landed it on both, logging `OPS_PER_LINE_DRIVERS landed=[...both lines...]`. The
turn-14 message then read the write back truthfully. The invention is one step
earlier, in the router: she answered a question about one line and the patch
answered for two. Then the same consultant snapshot erased both seven seconds
later, so the false figure reached her ear and never reached the plan.

Writer to fix: the router's per-line patch when the client named no line —
the row-identity question VS is already inside for Turn C. Same door, one turn
apart; it is not a second erasure site.

## Worth VS's eye, from the same store

* **Turn 10's question and its declared field disagree.** `messages_json[10]`
  carries `asked_field: "operating_periods_per_year"` while the sentence asks
  "about how many individual binding/repair jobs do you actually complete...
  across the year" — that is `annual_completed_units`, which was already an
  askable field at 592d2583. Turn 16 does it again (weeks, since fixed by
  a04da00b adding `operating_weeks_per_year` to ASKABLE_OPS_FIELDS). The turn-10
  mislabel is a prompt/model behaviour, not a code branch — surfaced, not queued.
* **On HEAD, the turn-13 patch door now holds her week figure**: replaying that
  turn logs `IMPLAUSIBLE_WRITE_HELD field=units_per_week_capacity value=10.0
  cadence=contract`. That is the new guard asking about the 10/week the app
  itself derived at turn 9. Observation for VS, not a finding.
* **On HEAD the keeper did not home the turns** in my replay: after the patch
  door, `annual_completed_units=1100` sat beside `units_per_period_capacity=10`
  with `operating_periods_per_year=None`; `ANNUAL_COMPLETIONS_HOMED` runs inside
  `_normalize_ops_capacity_compat`, which that path did not reach. Worth VS
  confirming the keeper's own site actually runs on the per-line door.

## Process findings

* **The HANDOFF TASK cites the wrong commit for the approved guard.** It says
  "the write-time bounds guard is approved and shipped (be2574a4)". be2574a4 is
  a `scripts/store_tick.py` watcher change; the guard and the keeper shipped in
  fd1107f4 (21:23) and 1ba47652 (21:33). An evidence pointer a human opens and
  finds nothing in.
* **VS's declared-vs-actual could not be audited from the watcher log**: there
  has been no `TURN PLAN [VS]` line since 2026-09-10 — VS's turns today run
  outside the watcher, so the plan never reaches the log Nick reads. Audited
  against the HANDOFF TASK text and the commits instead.
* **Forward-verification gap on fd1107f4 / 1ba47652** (the finding above):
  the keeper was proven to WRITE and never proven to SURVIVE the turn it is
  written in. The standing law is already on the wall for exactly this —
  "prove stored as well as used" — and the Vasquez-Lindqvist comment in the
  same file names the door that eats it.
