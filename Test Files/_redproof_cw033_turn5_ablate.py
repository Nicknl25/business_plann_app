"""CW-033 turn 5 -- per-fix ablations: neuter ONE fix at a time in-process
and confirm the red lands on THAT fix's checks (no decorative gates).

  AB1 D1b: the mover's turn_written_fields guard dropped -> the clobber
      returns (D1b red), everything else green.
  AB2 D2: the cadence parse ignores the value (old whole-message scan)
      -> D2a/D2e mis-bind again; same-clause cases stay green.
  AB3 D3: the disclosure bypass blinded on the D3 wording alone -> the
      stored-40 figure dies in the restatement filter again (D3a/D3b).
  AB4 D4: monthly_rent_expense removed from the labels map -> bare
      "Got it." returns (D4a red), other scalars untouched.
  AB5 D5: the mover's holds-turn flag forced False -> the completion
      prose ships behind the ask again (D5b red).
  AB6 X2: the cadence reconciler passthrough -> the xsec door re-bases
      raw again (X2a/X2b/X2c red) and the mover conversion dies with it
      (D3b/D5a/D5b red); the cadence-free controls stay green.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw033_turn5_ablate.py"
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

_spec = importlib.util.spec_from_file_location(
    "_redproof_cw033_turn5_fixes",
    REPO_ROOT / "Test Files" / "_redproof_cw033_turn5_fixes.py")
fixes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixes)

import api_handlers.intake_consult as ic  # type: ignore


def run(label):
    results = []

    def check(tag, ok, detail=""):
        results.append((tag, bool(ok)))

    fixes.run_checks(ic, SHAPES, check)
    failed = [t for t, ok in results if not ok]
    print(f"\n=== {label} ===")
    for t in failed:
        print(f"  RED: {t}")
    if not failed:
        print("  (all green)")
    return set(failed)


def expect(label, failed, must_red, must_stay_green):
    ok = True
    for frag in must_red:
        if not any(frag in t for t in failed):
            print(f"  [FAIL] expected RED on '{frag}' but it stayed green")
            ok = False
    for frag in must_stay_green:
        if any(frag in t for t in failed):
            print(f"  [FAIL] '{frag}' went red under an unrelated ablation")
            ok = False
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


def main() -> int:
    global SHAPES
    SHAPES = fixes._load_shapes()
    all_ok = True

    baseline = run("baseline (no ablation)")
    all_ok &= expect("baseline is fully green", baseline, [], ["D", "X2"])

    # AB1: drop the write-set guard
    _orig = ic._apply_forward_move
    def _no_guard(**kw):
        kw.pop("turn_written_fields", None)
        return _orig(**kw)
    ic._apply_forward_move = _no_guard
    try:
        failed = run("AB1: D1b guard dropped (turn_written_fields ignored)")
    finally:
        ic._apply_forward_move = _orig
    all_ok &= expect(
        "AB1 reds exactly the D1b clobber checks", failed,
        ["D1b"], ["D1c", "D1a", "D2a", "D3a", "D4a", "D5a", "X2a"])

    # AB2: cadence parse ignores the value (whole-message scan)
    _orig = ic._stated_capacity_cadence
    ic._stated_capacity_cadence = lambda text, value=None: _orig(text)
    try:
        failed = run("AB2: D2 value-binding dropped (whole-message scan)")
    finally:
        ic._stated_capacity_cadence = _orig
    all_ok &= expect(
        "AB2 reds exactly the clause-binding checks", failed,
        ["D2a", "D2e"], ["D2b", "D2c", "D2d", "D2f", "D3a", "D1b", "X2a"])

    # AB3: blind the disclosure bypass on the D3 wording alone
    _orig = ic._stated_capacity_cadence
    def _blind_d3(text, value=None):
        if "sorry - mowing" in str(text or "").lower():
            return ""
        return _orig(text, value=value)
    ic._stated_capacity_cadence = _blind_d3
    try:
        failed = run("AB3: D3 bypass blinded on the C3 wording")
    finally:
        ic._stated_capacity_cadence = _orig
    all_ok &= expect(
        "AB3 reds exactly the restatement-survival checks", failed,
        ["D3a", "D3b"], ["D3c", "D2a", "D5a", "X2a", "D1b", "D4a"])

    # AB4: un-name the rent stage
    _had = "monthly_rent_expense" in ic._GENERIC_FINANCIALS_FIELD_LABELS
    _saved = ic._GENERIC_FINANCIALS_FIELD_LABELS.pop("monthly_rent_expense", None)
    try:
        failed = run("AB4: D4 rent label removed")
    finally:
        if _had:
            ic._GENERIC_FINANCIALS_FIELD_LABELS["monthly_rent_expense"] = _saved
    all_ok &= expect(
        "AB4 reds exactly the rent-ack check", failed,
        ["D4a"], ["D4b", "D2a", "D1b", "D3a", "D5a"])

    # AB5: force the holds-turn flag False
    _orig = ic._apply_forward_move
    def _no_hold(**kw):
        res = _orig(**kw)
        return (res[0], res[1], res[2], False)
    ic._apply_forward_move = _no_hold
    try:
        failed = run("AB5: D5 holds-turn flag forced False")
    finally:
        ic._apply_forward_move = _orig
    # With the flag forced False the ask is treated as a landing and the
    # turn flows into the completion persist machinery - offline that is
    # a conn=None crash, so the red lands at section granularity: the
    # D5 coverage goes red for exactly the right reason (the ask no
    # longer holds the turn).
    all_ok &= expect(
        "AB5 reds exactly the ask-holds coverage", failed,
        ["_checks_d5"], ["D1b", "D3b", "D2a", "X2a"])

    # AB6: cadence reconciler passthrough
    _orig = ic._reconcile_stated_capacity_cadence
    ic._reconcile_stated_capacity_cadence = (
        lambda **k: {"value": k["value"], "spoken": "", "converted": False})
    try:
        failed = run("AB6: X2 reconciler passthrough (raw re-base returns)")
    finally:
        ic._reconcile_stated_capacity_cadence = _orig
    # Same section-granularity note as AB5: no reconciler -> no ask ->
    # the "Recorded:" copy is a landing -> completion persist crash.
    all_ok &= expect(
        "AB6 reds the conversion checks at BOTH doors", failed,
        ["X2a", "X2b", "X2c", "D3b", "_checks_d5"],
        ["X2d", "X2e", "D2a", "D1b", "D4a", "D3a"])

    print()
    print("ABLATIONS:", "ALL PASS - none decorative" if all_ok else "FAILURES")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
