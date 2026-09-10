# Item 5b - the owner-wage hold carries its human; the recalc retires only an UNSTAMPED hold (VS, 2026-09-09 night)

Deal breaker (mini's turn-10 finding, mini_r5_twopass.py case A): a GENUINE
same-human owner-pay conflict raised on a two-owner roster was retired by the
NEXT turn's preamble recalc (intake_consult.py ~17541, which runs before every
_coherence_gate call and therefore before section.py's popper 2203-2206 could
ask). The gate never asked; the kept figure stood - a silent pick, the class
CW-026 ruling #1 forbids, and a regression against 0fcb703.

Root: the hold carried no provenance ({kept, other} only). Once the pass has
merged the duplicate away, the roster looks the same for a genuine hold and for
the legacy stale one (raised by the old per-title-regex pass while it deleted a
second human), so roster shape cannot tell them apart. The stamp can.

## The fix (python/api_handlers/intake_consult.py, diff = intake_consult_r5b.diff, 22 additions / 3 replaced lines)

1. The raise loop iterates `_own_groups.items()` so it knows the group's
   normalized full name, and the hold it stores is
   `{"kept": ..., "other": ..., "human": <that name>}`. For the bare-row
   group with no named owner the stamp is the group key `__unnamed_owner__`
   (still a stamp: raised by THIS per-human pass).
2. The retire block adds one condition: `"human" not in _stored_hold`. Only
   an UNSTAMPED hold retires, and only when this pass raised none and the
   roster carries two or more distinct named owner humans (as shipped in
   19f69ef). A stamped hold is never retired by the recalc; only section.py's
   popper consumes it.
3. The retire log line now reads `OWNER_WAGE_HOLD_RETIRED unstamped hold=...`.

section.py UNTOUCHED (read 2199-2210): the popper does
`financials_json.get("_owner_wage_conflict_hold")`, checks `other > 0`, pops
the WHOLE key, and formats `kept` / `other` into the question. It never reads
any other key, so the `human` stamp is inert there. Pinned structurally
(test_section_popper_reads_kept_and_other_only).

## Pins (tests/test_people_stage_merge_and_hold_retire.py, 17 -> 22)

- test_genuine_two_owner_conflict_survives_the_next_preamble_recalc (the
  two-pass case A): pass 1 raises, pass 2 keeps the same hold, no RETIRED
  line, roster order kept, every other financials key equal between passes.
- test_raise_stamps_the_hold_with_the_grouped_human.
- test_stamped_hold_is_never_retired_by_the_recalc (a stamped hold stored on
  a two-owner roster with no raise this pass: kept, nothing else moves).
- test_unstamped_legacy_hold_still_retires_and_says_so (Marchetti after R3:
  one RETIRED line, carries `unstamped`).
- test_section_popper_reads_kept_and_other_only (structural).
- The existing raise pin (test_genuine_same_human_conflict_raises_and_keeps_the_hold)
  now asserts the stamped shape - the ONLY existing pin touched; the
  stale-retire, Sumac-kept and no-hold pins are unchanged.

RED-PROOF at HEAD 19f69ef/ebc8c77 (redproof_5b_at_HEAD_19f69ef.txt, run
BEFORE the edit): 5 failed / 17 passed. The two-pass pin fails on
`None != {'kept': 155000.0, 'other': 120000.0} : the genuine hold was retired
before the gate asked` - the deal breaker verbatim; the three stamp pins fail
on the missing `human` key; the legacy pin fails on the missing `unstamped`
word. The popper structural pin passes at HEAD (section.py was never wrong).
After the edit: 22/22.

## Proofs on the edited tree

- vs_r5_nomove.py --label before5b (at HEAD, before the edit) vs
  --label after5b: nomove_compare_5b.txt = ALL 9 DRAFTS IDENTICAL
  (AUDIT_SUMMARY set 176d4279, 1b7eeb63, 482b870f, 65e3c466, b4929a89,
  bb793dbb, c8a6b6b5 + live Marchetti 3201a64c 820,000 + Northwind 3c2224e1
  52,202,210); census both runs carriers=102 would_retire=0 kept=102
  carriers_with_two_named_owner_humans=0 (every legacy carrier is unstamped
  AND one-owner Sumac, so the narrower rule changes nothing today).
- mini_r5_twopass_after5b.txt (mini's own instrument): A kept for the gate
  (hold {155000/120000, human ottoline marchetti} on both passes, no retire
  line), B kept (Sumac, stamped delia rennick), C retired (unstamped legacy
  hold on the repaired two-human roster, RETIRED unstamped line).
- Floors: people-stage 22 + anchor 11 + freeze 10 + bare 17 + people-guard 14
  = 74 passed; gate --only R31,R32 GREEN 2/2
  (_gate_only_R31_R32_20260909_r5b_r6.txt).
- :5050 restarted after the edit (stale 34240 killed, launcher 25784, ONE
  listener 24564 at 23:41:06); freeze readback FROZEN exit 3; no system run,
  no writing-phase trigger, nothing written to any live row.

## Verify-forward

Readers of the hold: the raise (writes it), the retire block (reads the stamp),
section.py's popper (kept/other only - inert), and the census instruments
(key presence only - unchanged counts). The stored financials_json of a
draft that raises a hold from now on carries one extra string key inside the
underscore transport dict; nothing renders underscore keys, and the golden
draft carries no hold (gate GREEN). Nothing downstream of the recalc changes
for any draft that carries no hold (no-move on nine drafts).
