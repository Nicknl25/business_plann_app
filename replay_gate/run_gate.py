# -*- coding: utf-8 -*-
"""The replay gate - every KNOWN issue, fast.

    VS ships a fix -> replay gate (seconds) -> GREEN: every known issue is
    clear, spend the Cowork run.  RED: names the fixed bug that regressed
    or the invariant that broke; bounce to VS, no run burned.

Usage (from C:\\dev\\business_plann_app, venv python):

    .venv\\Scripts\\python.exe -m replay_gate.run_gate            # gate the build
    .venv\\Scripts\\python.exe -m replay_gate.run_gate --tier full  # + live-GPT legs
    .venv\\Scripts\\python.exe -m replay_gate.run_gate --prove      # prove every leg
    .venv\\Scripts\\python.exe -m replay_gate.run_gate --list       # the leg list

Exit codes:  0 GREEN   1 RED   2 SETUP FAILED (the gate is wrong, not the build)

HONEST BOUNDARY: this catches KNOWN issues. It cannot catch a bug nobody
has found - there is no scenario and no assertion for one. That is the
Cowork run's job. Gate = known, seconds. Cowork = unknown, thorough.
"""
import argparse
import os
import sys

from . import _bootstrap


def _gate(args):
    _bootstrap.utf8_stdout()
    root = _bootstrap.bind_root(args.root)

    from . import runner
    from .context import GateContext
    from .verdict import Report

    build = _bootstrap.build_id()
    if not args.quiet:
        print(f"BUILD    {build}")

    conn = _bootstrap.gate_connection()
    read_conn = _bootstrap.read_connection()
    ctx = GateContext(conn, read_conn)

    # Mandatory. A suite that enters anywhere other than the surface the
    # bugs live on is not testing them. Exits 2, never a hollow green.
    ctx.assert_surface()

    report = Report(build)
    quarantined = [q for q in (args.quarantine or "").split(",") if q.strip()]
    runner.run_all(ctx, report, tier=args.tier,
                   only=(args.only.split(",") if args.only else None),
                   quarantined=quarantined)
    return report.emit()


def _list(args):
    from . import runner

    legs = runner.all_legs()
    print(f"{'leg':<5} {'kind':<11} {'tier':<5} {'bug':<34} {'issue':<14} "
          f"{'baseline':<9} surface")
    print("-" * 108)
    for l in legs:
        print(f"{l.id:<5} {l.kind:<11} {l.tier:<5} {l.bug[:34]:<34} "
              f"{l.issue[:14]:<14} {l.baseline[:7]:<9} {l.surface}")
    print("-" * 108)
    reg = sum(1 for l in legs if l.kind == "REGRESSION")
    inv = len(legs) - reg
    live = sum(1 for l in legs if l.tier == "live")
    print(f"{len(legs)} legs: {reg} regression pins, {inv} structural invariants "
          f"({live} need the live judge - --tier full)")
    return 0


def _prove(args):
    _bootstrap.utf8_stdout()
    _bootstrap.bind_root(args.root)
    from . import prove as prove_mod
    from . import runner

    legs, skipped = runner.select(
        tier=args.tier, only=(args.only.split(",") if args.only else None))
    print(f"Proving {len(legs)} legs, one at a time, against their own broken baselines.")
    if skipped:
        print(f"({len(skipped)} live-tier legs not proved in this tier: "
              + ", ".join(l.id for l in skipped) + ")")
    _ok, results, quarantine = prove_mod.prove(legs, tier=args.tier, verbose=args.verbose)
    return prove_mod.emit(results, quarantine)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Replay gate - catch every known issue before a Cowork run")
    p.add_argument("--root", default=None,
                   help="repo/worktree whose python/ is the build under test")
    p.add_argument("--tier", default="fast", choices=("fast", "full"),
                   help="fast = recorded doubles only (default); full = + live-GPT legs")
    p.add_argument("--only", default=None,
                   help="comma-separated leg ids or bug names to run")
    p.add_argument("--quarantine", default=None,
                   help="comma-separated leg ids to exclude (unproven legs)")
    p.add_argument("--prove", action="store_true",
                   help="prove each leg: RED on its broken baseline, GREEN on the fix")
    p.add_argument("--list", action="store_true", help="list the legs and exit")
    p.add_argument("--quiet", action="store_true", help="less chrome (used by --prove)")
    p.add_argument("--verbose", action="store_true", help="echo child logs during --prove")
    args = p.parse_args(argv)

    if args.list:
        return _list(args)
    if args.prove:
        return _prove(args)
    return _gate(args)


if __name__ == "__main__":
    sys.exit(main())
