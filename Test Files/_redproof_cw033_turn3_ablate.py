"""CW-033 turn 3 -- per-fix ablations: neuter ONE fix at a time in-process
and confirm the red lands on THAT fix's checks alone (no decorative gates).

  A1 neuter M2 (the write-door stage check): _next_financials_stage -> None
     -> M2a/M2b must go red (mid-interview landing returns), M3/B3 stay green.
  A2 neuter M3 (the cadence reconciler): passthrough value, no ask
     -> M3a-M3f (+M2e's spoken cadence) must go red, M2 boundary stays green.
  A3 neuter M1 (the ack-fallback gate): write-claim regex never matches and
     the figure-ack probe always False -> M1a must go red.
  A4 neuter B3 (the carve-out): carve-out regex never matches and the helper
     returns None -> B3a/B3b/B3c/B3f/B3g must go red, B3d/B3e/B3h stay green.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw033_turn3_ablate.py"
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

_spec = importlib.util.spec_from_file_location(
    "_redproof_cw033_turn3_fixes",
    REPO_ROOT / "Test Files" / "_redproof_cw033_turn3_fixes.py")
fixes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixes)

import api_handlers.intake_consult as ic  # type: ignore

_NEVER = re.compile(r"(?!x)x")


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
    all_ok &= expect("baseline is fully green", baseline, [], ["M", "B3"])

    # A1: neuter the write-door stage check
    _orig = ic._next_financials_stage
    ic._next_financials_stage = lambda *a, **k: None
    try:
        failed = run("A1: M2 door neutered (_next_financials_stage -> None)")
    finally:
        ic._next_financials_stage = _orig
    all_ok &= expect(
        "A1 reds exactly the M2 boundary checks", failed,
        ["M2a", "M2b"], ["M3a", "M3e", "M1a", "B3a", "B3f"])

    # A2: neuter the cadence reconciler
    _orig = ic._reconcile_stated_capacity_cadence
    ic._reconcile_stated_capacity_cadence = (
        lambda **k: {"value": k["value"], "spoken": "", "converted": False})
    try:
        failed = run("A2: M3 reconciler neutered (passthrough)")
    finally:
        ic._reconcile_stated_capacity_cadence = _orig
    all_ok &= expect(
        "A2 reds exactly the M3 conversion checks", failed,
        ["M3a", "M3b", "M3c", "M3e", "M3f", "M2e"],
        ["M2a", "M2b", "M2c", "M1a", "B3a"])

    # A3: neuter the ack-fallback gate
    _orig_re, _orig_fn = ic._WRITE_CLAIM_RE, ic._prose_acks_unwritten_figure
    ic._WRITE_CLAIM_RE = _NEVER
    ic._prose_acks_unwritten_figure = lambda **k: False
    try:
        failed = run("A3: M1 ack gate neutered")
    finally:
        ic._WRITE_CLAIM_RE, ic._prose_acks_unwritten_figure = _orig_re, _orig_fn
    all_ok &= expect(
        "A3 reds exactly the M1 fallback check", failed,
        ["M1a"], ["M1b", "M2a", "M3a", "B3a"])

    # A4: neuter the capex carve-out
    _orig_re, _orig_fn = ic._CAPEX_CARVEOUT_RE, ic._capex_carveout_figure
    ic._CAPEX_CARVEOUT_RE = _NEVER
    ic._capex_carveout_figure = lambda m: None
    try:
        failed = run("A4: B3 carve-out neutered")
    finally:
        ic._CAPEX_CARVEOUT_RE, ic._capex_carveout_figure = _orig_re, _orig_fn
    all_ok &= expect(
        "A4 reds exactly the carve-out checks", failed,
        ["B3a", "B3b", "B3f", "B3g"],
        ["B3d", "B3e", "B3h", "M2a", "M3a", "M1a"])

    print()
    print("RESULT:", "GREEN - every ablation red on its own checks alone"
          if all_ok else "RED - see FAIL lines above")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
