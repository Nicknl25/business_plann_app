# -*- coding: utf-8 -*-
"""Run legs against the bound build and score them."""
from . import surface as surface_mod
from .legs import FAST, LIVE, REGRESSIONS
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


def run_leg(ctx, leg):
    """-> (ok, verdict, detail, evidence)"""
    ctx.reset()
    try:
        landed, evidence = leg.run(ctx)
    except Exception as exc:
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
        return ok, verdict, detail, evidence
    verdict = "HOLDS" if landed else ("REGRESSED" if leg.kind == "REGRESSION"
                                      else "VIOLATED")
    return bool(landed), verdict, evidence, ""


def run_all(ctx, report, tier="fast", only=None, quarantined=()):
    legs, skipped = select(tier=tier, only=only)
    quarantined = {q.strip().upper() for q in quarantined}
    for leg in legs:
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
