# Item 6 / R2 - every rest-of-team anchor DOWN-SCALE is logged loudly (VS, 2026-09-09 night)

Nick: "authoring above the stated total means the model invented people;
scaling down to their number is correct." The down-scale in
python/client_intake_and_finmo/post_intake_headcount/schedule.py
`_anchor_supporting_rows_to_stated_pool` STAYS exactly as it was
(factor = rot / q1_pool, uniform FTE scaling across every quarter, hires
re-derived, rest_of_team_anchor stamp). This turn ADDS one distinct log line
when factor < 1, emitted right after the existing `REST_OF_TEAM_ANCHOR
applied` line:

    REST_OF_TEAM_ANCHOR_DOWNSCALE stated_pool=<rot> authored_pool=<q1_pool> factor=<f> gap_dollars=<q1_pool - rot>

Not emitted at factor >= 1 (up-scale) or inside the 0.5% no-op band (the
already_anchored early return precedes it, so a factor of 0.996 is silent).
Log only: no stamp key, no row, no number moves. Diff = schedule_r6.diff (13
additions, nothing removed).

## Pins (tests/test_rest_of_team_anchor.py, 6 -> 11)

- test_downscale_logs_the_gap_line_with_four_figures: stated 100,000 against
  the Marchetti-shaped authored Q1 pool 189,801.60 -> exactly one DOWNSCALE
  line carrying stated_pool=100000.00 authored_pool=189801.60 factor=0.5269
  gap_dollars=89801.60; the applied line still rides beside it.
- test_downscale_schedule_and_stamp_are_byte_equal_to_the_record: the rows +
  stamp digest equals 34ff11069a09e312, RECORDED AT ebc8c77 BEFORE the edit
  by r6_downscale_digest.py (downscale_digest_before.json); the explicit
  expected FTE shape is asserted too; the stamp carries no gap key.
- test_upscale_does_not_log_the_downscale_line (523,000, factor 2.7555,
  digest 248670d1f002e283 recorded before the edit).
- test_noop_band_does_not_log_the_downscale_line (0.996 x pool:
  already_anchored, no line at all, rows untouched).
- test_downscale_just_outside_the_band_logs_it (0.99 x pool: factor=0.9900,
  gap 1,898.02).

RED-PROOF at HEAD ebc8c77 (redproof_r6_at_HEAD_ebc8c77.txt, run BEFORE the
edit): 2 failed / 9 passed - the two down-scale pins fail on `0 != 1` with
only the applied line in the captured log; the byte-equal, up-scale and
band pins pass at HEAD, which is the point (they pin that nothing else moves).
After the edit: 11/11.

## Byte-equal proof (downscale_compare.txt)

r6_downscale_digest.py --label before (at ebc8c77, untouched tree) vs
--label after (edited tree): five cases (down-scale 100,000; up-scale
523,000; both band edges; down-scale just outside the band) - rows + stamp
digest IDENTICAL on every case; the only difference is the new log line on
the two down-scale cases:

    REST_OF_TEAM_ANCHOR_DOWNSCALE stated_pool=100000.00 authored_pool=189801.60 factor=0.5269 gap_dollars=89801.60
    REST_OF_TEAM_ANCHOR_DOWNSCALE stated_pool=187903.58 authored_pool=189801.60 factor=0.9900 gap_dollars=1898.02

Floors and restart: see R5B_RIDER_FIX.md (same turn: 74 pins, gate
R31,R32 GREEN, ONE :5050 listener 24564, freeze FROZEN). Verify-forward:
the line has no reader (log only); the schedule rows and stamp that
everything downstream consumes are digest-identical, so nothing downstream
can differ.

Where Nick reads it: the backend log (_logs_persona_*.txt) of any system
run whose author over-built - grep REST_OF_TEAM_ANCHOR_DOWNSCALE. Marchetti
3201a64c's shape (523,000 stated vs ~190K authored) is an UP-scale and stays
silent by design; the line fires only when the author invented people.
