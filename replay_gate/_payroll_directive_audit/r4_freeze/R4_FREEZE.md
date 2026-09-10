# Item 4 FREEZE REAL - the writing-phase trigger switch (VS, 2026-09-09)

Nick: make the freeze real, not a request. Deal breaker prevented: a plan
generated off a draft Nick ordered frozen (Turn A's proof run shipped a
FAILED DRAFT docx + outcome email into the live client folders DURING a
declared freeze).

## What shipped
- python/writing_phase_v2/trigger_switch.py - read_state()/set_state()/one_line().
  State = ONE gitignored JSON file _runtime/writing_phase_trigger.json, read at
  CALL time (no import cache). Absent file = ON (default). trigger=off = FROZEN.
  Unreadable/unknown file = FROZEN (fail-closed; the deal breaker is a plan
  shipping during a freeze, never a plan delayed).
- scripts/writing_phase_freeze.py {on|off|status} [--note] [--by] - one line out,
  exit 0 = ON, 3 = FROZEN. Nick never touches it; the loop flips it.
- python/api_handlers/intake_consult.py - the trigger tail lifted verbatim into
  the module-level _auto_trigger_writing_phase(app, diagnostic_payload,
  result_draft_id) at line 15136 (constant _WP_LOG_ROOT at 15133), called from the ONE
  site in the system-run success tail at line 16567. Branch order: switch FIRST
  -> FROZEN warning + return; then acceptance -> NOT triggered (unchanged
  wording); then the detached Popen (same argv, same creationflags, same
  auto_run.log append). One hygiene line added: the parent's copy of the
  auto_run.log handle is closed after Popen (the child holds its own duplicate)
  - the offline pin's temp-dir cleanup exposed that :5050 kept one open handle
  per triggered run.
- .gitignore: /_runtime/
- tests/test_writing_phase_freeze_switch.py - 10 pins (see pins_freeze_switch.txt).

## Coverage rider: no second trigger site
Every .py/.ps1/.bat/.cmd/.xml under python/, scripts/, Test Files/, tests/ that
names writing_phase_v2_run: the runner itself, intake_consult.py (docstring +
the one Popen), and the new pin file (which asserts exactly this). Every caller
of POST /api/intake-consult/system-run reaches the same tail: live intake
completion, Test Files/run_intake_bypass.py (the canary), scripts/run_supervisor.py
:411 (the BusinessPlanApp-Supervisor rerun ladder). writing_phase_v2_diff.py
imports the bundle module only; it launches nothing.

## Proof on the real path (canary, flag OFF)
- :5050 restarted via start_persona_backend.ps1 - stale 32428 killed, listener
  PID 33576 started 22:12:41, ONE listener (re-verified after the run); edit
  mtimes 22:08:33 (trigger_switch.py) and 22:12:08 (intake_consult.py) precede it.
- flag set OFF 22:12:45 (flag_set_off.txt).
- Sunny_V3 bypass canary: system_run_complete, draft 280a55e1c945444dae99df945d74a409,
  run 82516d631cbf4f058689a58e9102dfa1, POST /system-run -> 200 in 422,312 ms
  (_canary_sunnyv3_freeze_20260909.txt). ACCEPTANCE PASSED this run - so with
  the switch ON the writing phase WOULD have fired; the switch is what stopped it.
- Backend log _logs_persona_20260909_221241.txt line 1487 (backend_log_freeze_lines.txt):
  22:20:10.496 workbook delivered to OneDrive -> 22:20:12.728 WARNING Writing
  phase FROZEN for draft 280a55e1... (run 82516d63..., business Sunny Glaze
  Donuts): trigger switch is OFF (set 2026-09-09 22:12:45 by VS note: ...) -
  runner NOT launched, acceptance_passed=True ignored; workbook delivery
  unaffected -> 22:20:12.746 REQ ... -> 200. Exactly one FROZEN line in the log.
- Client Written Plans: 201 files before and after, byte-identical listing
  (cwp_before.txt == cwp_after.txt, sizes + mtimes); sunny_glaze_donuts/auto_run.log
  sha256 813bcf83... before and after; no writing_phase_v2_run process exists.
- Delivered as today: C:\dev\Cilient Plans\Sunny Glaze Donuts -- 09-09-2026 22-20-05.xlsx
  (Checks!B2 = OK, checks_b2.txt) + the OneDrive Financial Models copy (log
  22:20:10). ONE Sunny workbook this time, not two - acceptance passed, so no
  RESTRUCTURE ATTEMPT file was produced.
- Side effects to list (the ladder's normal output, left in place): canary draft
  280a55e1 (client HRPPOFH90600247657) + run 82516d63; _check_api shadow draft
  579c90f332214fc4855cbb166045fa5b (client RAVYKNF69934555682, business None,
  22:13:10); the 22-20-05 workbook in both folders; persona watcher run_vitals
  rows for 280a55e1 (two STALL events at the 300 s threshold during quarter-grid,
  run_s=411, observability only).

## Floors
- pins_freeze_switch.txt: 10 passed. pins_bare_mode.txt: 17 passed.
- _gate_only_R31_R32_20260909_r4_freeze.txt: GREEN 2/2.

## Flag at end of turn (LEFT OFF per item 6)
writing-phase trigger: FROZEN (off since 2026-09-09 22:12:45 by VS - Nick directive freeze on Marchetti/Northwind, item 4 FREEZE REAL; lifted only by item 8 through this switch; system runs still deliver workbooks, no plan is written)
status rc=3 (3 = FROZEN)
