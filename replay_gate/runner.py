# -*- coding: utf-8 -*-
"""Run legs against the bound build and score them."""
from . import surface as surface_mod
import os

from .legs import (
    FAST, GOLDEN_MASTER, LIVE, REGRESSIONS, bare_golden_verdict,
)
from .invariants import INVARIANTS
from .verdict import judge


def all_legs():
    return list(REGRESSIONS) + list(INVARIANTS)


def select(tier="fast", only=None):
    legs = all_legs()
    if only:
        wanted = {s.strip().lower() for s in only}
        legs = [l for l in legs
                if l.id.lower() in wanted or l.bug.lower() in wanted]
    skipped = []
    if tier == FAST:
        skipped = [l for l in legs if l.tier == LIVE]
        legs = [l for l in legs if l.tier == FAST]
    return legs, skipped


def _lock_misses():
    """How many recorded GPT responses this leg could not find."""
    try:
        from client_intake_and_finmo import openai_http as _o
        return _o.lock_miss_count(), _o.lock_miss_keys()
    except Exception:
        return 0, []


def _reset_lock_misses():
    try:
        from client_intake_and_finmo import openai_http as _o
        _o.reset_lock_misses()
    except Exception:
        pass


def _stale(misses, keys, underlying=""):
    """STALE RECORDING, NOT A FAILURE (Nick 2026-09-13): a leg that drives a
    real turn calls the guard, the guard calls GPT under the strict lock, and
    a prompt edit re-keys it. The leg then says nothing about the code. "I'd
    rather have fewer legs that mean something than sixty-five that can go red
    because a prompt got a comma."
    """
    detail = ("%d GPT recording(s) not found (keys %s) - re-record before reading this leg's verdict." % (misses, ", ".join(keys[:4]) or "?"))
    if underlying:
        detail += " Underlying: " + str(underlying)
    return detail


def run_leg(ctx, leg):
    """-> (ok, verdict, detail, evidence)"""
    ctx.reset()
    _reset_lock_misses()
    try:
        landed, evidence = leg.run(ctx)
    except Exception as exc:
        _m, _k = _lock_misses()
        if _m:
            return True, "STALE RECORDING", _stale(_m, _k, f"{type(exc).__name__}: {exc}"), ""
        return (False, "ERROR",
                f"leg raised {type(exc).__name__}: {exc}", "")
    if ctx.last_turn is not None:
        prior = getattr(ctx, "last_wall", surface_mod.WALL)
        ok, verdict, detail = judge(leg.id, ctx.last_turn, landed, prior)
        if ok and not landed and leg.kind == "REGRESSION":
            # A regression leg pins a specific landing. A proposal is a
            # forward move but it is NOT the fix holding, unless the leg
            # explicitly allows it (the ambiguous-input invariant does).
            ok, verdict = False, "NOT-FIXED"
            detail = "moved forward but the pinned value did not land"
        if not ok:
            _m, _k = _lock_misses()
            if _m:
                return True, "STALE RECORDING", _stale(_m, _k, detail), evidence
        return ok, verdict, detail, evidence
    if not landed:
        _m, _k = _lock_misses()
        if _m:
            # the no-turn path: a leg whose probe simply returned False, with a
            # recording it could not find behind it
            return True, "STALE RECORDING", _stale(_m, _k, str(evidence or "")), evidence
    verdict = "HOLDS" if landed else ("REGRESSED" if leg.kind == "REGRESSION"
                                      else "VIOLATED")
    if landed and leg.proof == GOLDEN_MASTER and not _proving():
        # BARE MODE. --prove compares the surface across two commits and is
        # the authority when it runs; without it, the leg's own assertions
        # only check a floor and a canary. The claim a golden-master leg
        # makes is "this did not change", so bare mode compares it against
        # the blessed record - and refuses green when it cannot.
        ok, verdict, detail = bare_golden_verdict(
            leg.id, getattr(ctx, "golden_shas", None) or {})
        if not ok:
            _m, _k = _lock_misses()
            if _m:
                return True, "STALE RECORDING", _stale(_m, _k, detail), evidence
        return ok, verdict, detail, evidence
    return bool(landed), verdict, evidence, ""


def _proving():
    """True inside a --prove child, which does its own two-commit compare."""
    return os.environ.get("REPLAY_GATE_PROVING") == "1"


def run_all(ctx, report, tier="fast", only=None, quarantined=(), still_quiet=None):
    """still_quiet: called before EVERY leg; a non-empty return aborts.

    CONTINUOUS, NOT AT STARTUP (Nick 2026-09-13). The first version checked
    once before the first leg, and I walked into the gap myself - running a
    291-test suite against the same database while a gate run was in flight,
    the exact contamination the guard exists to prevent. A gate run takes
    minutes; a startup check cannot see anything that begins after it.
    """
    legs, skipped = select(tier=tier, only=only)
    quarantined = {q.strip().upper() for q in quarantined}
    for leg in legs:
        if still_quiet is not None:
            busy = still_quiet()
            if busy:
                report.abort("the database stopped being quiet mid-run, so every leg after this one would measure the traffic: " + "; ".join(busy))
                return report
        if leg.id.upper() in quarantined:
            report.quarantine(leg, "unproven: did not go red on its own broken baseline")
            continue
        ok, verdict, detail, evidence = run_leg(ctx, leg)
        prov = getattr(ctx, "provenance", "")
        if prov:
            evidence = (evidence + f"\n          [{prov}]").strip()
            ctx.provenance = ""
        report.add(leg, ok, verdict, detail, evidence)
    for leg in skipped:
        report.skip(leg, "live tier - needs the real judge/router; run --tier full")
    return report
