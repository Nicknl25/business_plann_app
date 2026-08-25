# -*- coding: utf-8 -*-
"""Structural invariants - things that must ALWAYS be true.

Each is fired at the surface where it applies and carries its own broken
baseline, so it is provable the same way a regression leg is.
"""
import copy
import re

from .legs import FAST, LIVE, STRUCTURAL_ABSENCE, Leg
from .surface import OPS, PATCHLESS, PEOPLE, RecordedRouter, near, product_field

# ---------------------------------------------------------------------------
# I01..I06  no turn dead-ends / every correction lands or infers-and-proposes
# One leg per correction type, so RED names the exact type that froze.
# ---------------------------------------------------------------------------
PAYROLL_DOOR = {"action": "edit_patch", "assistant_message": "",
                "patch": {"people.total_team_payroll": 120000}}


def _ops_price(ctx, did, fin_out):
    _f, _p, ops = ctx.sections(did)
    got = product_field(ops, "unit_price")
    return near(got, 610.0), f"stored unit_price = {got!r} (want 610, was 520)"


def _ops_volume(ctx, did, fin_out):
    _f, _p, ops = ctx.sections(did)
    got = product_field(ops, "units_per_period_capacity")
    return near(got, 40.0), f"stored units_per_period_capacity = {got!r} (want 40, was 34)"


def _fin_field(field, want, tol=0.5, extra=None):
    def probe(ctx, did, fin_out):
        fin_db, _p, _o = ctx.sections(did)
        got = fin_db.get(field)
        src = "stored"
        if not near(got, want, tol):
            alt = (fin_out or {}).get(field)
            if near(alt, want, tol):
                got, src = alt, "handler state (DB row not re-synced)"
        ok = near(got, want, tol)
        if ok and extra:
            ok, extra_ev = extra(fin_db, fin_out)
            return ok, f"{src} {field} = {got!r}; {extra_ev}"
        return ok, f"{src} {field} = {got!r} (want {want:,.0f})"
    return probe


def _cogs_dollars(fin_db, fin_out):
    basis = fin_db.get("cogs_basis") or (fin_out or {}).get("cogs_basis")
    return str(basis) == "dollars", f"cogs_basis = {basis!r} (want 'dollars')"


def _no_landing_expected(ctx, did, fin_out):
    return False, "ambiguous input - no landing expected; a proposal is the pass"


CORRECTION_TYPES = [
    ("price", "My unit price is now 610 instead of 520.", PATCHLESS, _ops_price),
    ("payroll", "My total payroll is $120,000.", PAYROLL_DOOR,
     _fin_field("current_payroll", 120000.0, 1.5)),
    ("cogs", "Materials run about $30,000 a year.", PATCHLESS,
     _fin_field("current_cogs", 30000.0, 0.5, extra=_cogs_dollars)),
    ("volume", "I can take on 40 properties now.", PATCHLESS, _ops_volume),
    ("marketing", "Marketing is really $2,400 a year.", PATCHLESS,
     _fin_field("marketing_total_year1", 2400.0)),
    ("AMBIGUOUS/garbage", "Put 777 in there.", PATCHLESS, _no_landing_expected),
]


def _forward_move_runner(message, router, probe):
    def run(ctx):
        turn, fin_out, did = ctx.turn(message, RecordedRouter(router))
        ctx.note_turn(turn)          # verdict.judge sees the turn: dead end,
        return probe(ctx, did, fin_out)   # verbatim repeat, empty, all caught
    return run


# ---------------------------------------------------------------------------
# I07  the stored field matches what the app CLAIMED
# ---------------------------------------------------------------------------
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")


def _i_ack_matches_stored(ctx):
    """An acknowledgement is not evidence: prose claiming a write cannot
    ship unless the write landed.

    RE-BASELINED AND RESHAPED (was 5b5ffbb/7bcf307, which could never red).
    The write-claim ship gate this pins was shipped BY 7bcf307 - the leg was
    naming its own fix commit as its baseline. 5b5ffbb/7bcf307 is R12's pair,
    copied here by mistake.

    The old fixture could not produce a false claim either: the payroll door
    carries an empty assistant_message and the completed-state branch builds
    its ack FROM the write, so a mismatched claim is unrepresentable there.
    And the >= 1000 payroll-scale filter would have discarded the "$0" claim
    that is the actual symptom.

    Now the red-proof R4 shape: a lease question is pending, the client
    answers about payroll instead, the router returns patchless prose
    claiming a $0 lease write, and nothing lands.
    """
    fin = ctx.completed_fin()
    # The 'initial_lease' STAGE KEY survived CW-041 (ef2d6e7) but its
    # completion field became capital_lease_balance, and completed_fin()
    # fills every stage's completion field - so popping only the old field
    # left the stage complete and the leg dark from ef2d6e7 on (mini,
    # 2026-08-24: GREEN at 7480c5d, 'active stage is None' at HEAD). Both
    # fields are popped: the old one makes the stage pending on the 7bcf307
    # baseline, the new one on any build after CW-041.
    fin.pop("initial_lease", None)
    fin.pop("capital_lease_balance", None)
    fin.pop("_financials_stage_confirms", None)
    stage = ctx.ic._next_financials_stage(fin)
    if stage != "initial_lease":
        return False, (f"setup: active stage is {stage!r}, need 'initial_lease' "
                       f"pending for the false-write-claim shape")
    prose = "Got it - I'll use $0 for monthly lease commitment beyond main rent."
    turn, fin_out, did = ctx.turn(
        "My total annual payroll is $166,000.",
        RecordedRouter({"action": "answer_readonly",
                        "assistant_message": prose, "patch": None}),
        fin=fin,
        last_assistant="What monthly amount should we use for any leased "
                       "equipment, vehicles, servers, or additional space?")
    ctx.note_turn(turn)
    msg = str((turn or {}).get("assistant_message") or "")
    claims_write = "i'll use $0" in msg.lower() or "i will use $0" in msg.lower()
    discloses = "$166,000" in msg
    fin_db, _p, _o = ctx.sections(did)
    # Whichever field the build under test writes for this stage: the legacy
    # monthly payment (initial_lease) or the CW-041 balance still owed
    # (capital_lease_balance). Neither may land silently as $0.
    lease = None
    for _field in ("capital_lease_balance", "initial_lease"):
        lease = fin_db.get(_field)
        if lease is None:
            lease = (fin_out or {}).get(_field)
        if lease is not None:
            break
    silently_written = near(lease, 0.0, 1e-9)
    ok = (not claims_write) and discloses and (not silently_written)
    return ok, (f"reply ships a $0 write-claim = {claims_write} (must be False "
                f"- nothing landed); client's stated $166,000 disclosed = "
                f"{discloses}; stored lease field = {lease!r} (must not have "
                f"been silently written)")


# ---------------------------------------------------------------------------
# I08  owner appears exactly once
# ---------------------------------------------------------------------------
def _i_owner_once(ctx):
    """RE-BASELINED AND RESHAPED (was 000edda/66cc26b, which could never red).

    000edda removed the financials owner door; it contains no dedupe logic at
    all, so it was never the fix for a duplicate row. The duplicate-owner
    family was fixed by 18f5ca5 (owner-row uniqueness in THE RECALC).

    The old fixture also could not create the condition: at 66cc26b the
    completed surface returns before routing, so a patchless turn was a
    no-op and the seeded roster - which has exactly one owner - came back
    unchanged. A duplicate has to be PRESENT in the seeded people_json; the
    turn never manufactures one.

    Distinct from I12 by design: I12 proves the invariant inside the RECALC
    by calling the sync directly. This proves it survives a live production
    turn and the persistence round-trip.
    """
    turn, fin_out, did = ctx.turn(
        "I pay myself $4,000 a month.",
        RecordedRouter({"action": "edit_patch", "assistant_message": "",
                        "patch": {"people.owner_pay_monthly": 4000}}),
        people=copy.deepcopy(SUMAC_DUP_PEOPLE))
    ctx.note_turn(turn)
    _f, ppl, _o = ctx.sections(did)
    rows = [p for p in (ppl.get("people") or [])
            if ctx.ic._OWNER_TITLE_RE.search(str(p.get("role_title") or ""))]
    rollup = (fin_out or {}).get("current_payroll")
    ok = len(rows) == 1
    return ok, (f"{len(rows)} owner row(s) persisted through a live turn: "
                f"{[r.get('role_title') for r in rows]!r} (want exactly 1); "
                f"rollup = {rollup!r} (at ff1da19 both 'Owner / Crew Lead' and "
                f"the bare 'Owner' survive and the rollup carries 141,999.96)")


# ---------------------------------------------------------------------------
# I09  no double-counted people
# ---------------------------------------------------------------------------
def _i_no_double_count(ctx):
    """The rollup can never reach the naive sum of every roster row plus
    rest-of-team. Hitting it means someone was counted twice.

    The naive ceiling MUST be computed from a snapshot taken BEFORE the
    sync. `_sync_financials_consult_persistence_state` mutates the people
    dict in place - removing the group row IS the dedupe working - so
    measuring the ceiling afterwards collapses it onto the rollup and the
    assertion can never pass on a correct build."""
    from .legs import CEDAR_PEOPLE_PHANTOM

    before = copy.deepcopy(CEDAR_PEOPLE_PHANTOM)
    people = copy.deepcopy(CEDAR_PEOPLE_PHANTOM)
    fin_out, _y1 = ctx.ic._sync_financials_consult_persistence_state(
        financials_json=copy.deepcopy(ctx.completed_fin()),
        financials_year1_json={},
        marketing_model_json={},
        people_json=people,
        ops_json=copy.deepcopy(OPS),
    )
    rollup = float((fin_out or {}).get("current_payroll") or 0.0)
    named = sum(float(p.get("annual_wage") or 0.0)
                for p in (before.get("people") or []))
    rest = float(before.get("rest_of_team_payroll_year1") or 0.0)
    ceiling = named + rest
    ok = rollup < ceiling - 1.0
    return ok, (f"rollup = {rollup:,.2f}; naive pre-sync ceiling = "
                f"{ceiling:,.2f} (named {named:,.0f} + rest {rest:,.0f}); "
                f"hitting the ceiling means the group row was counted twice")


# ---------------------------------------------------------------------------
# I12  the owner appears exactly once, and a wage conflict is never
#      resolved silently
# ---------------------------------------------------------------------------
SUMAC_DUP_PEOPLE = {
    "people": [
        {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
         "annual_wage": 34000.0, "wage_source": "client_override",
         "relevant_background": "ten years of commercial grounds"},
        {"full_name": "", "role_title": "Owner",
         "annual_wage": 33999.96, "wage_source": "client_override"},
        {"full_name": "Rosalie Fenn", "role_title": "Crew Lead",
         "annual_wage": 37000.0, "wage_source": "client_override"},
    ],
    "rest_of_team_payroll_year1": 37000.0,
}


def _i_owner_row_uniqueness(ctx):
    """Three shapes, one rule: after the sync there is exactly ONE owner
    row. The duplicate merges, a benchmark row loses to a client
    override, and two DIFFERENT overrides raise a hold rather than a
    silent pick."""
    def _sync(people):
        fin, _y1 = ctx.ic._sync_financials_consult_persistence_state(
            financials_json={"current_revenue": 175000.0,
                             "_financials_revenue_intro_done": True},
            financials_year1_json={},
            marketing_model_json={},
            people_json=people,
            ops_json=copy.deepcopy(OPS),
        )
        return fin, people

    def _owners(people):
        return [p for p in (people.get("people") or [])
                if ctx.ic._OWNER_TITLE_RE.search(str(p.get("role_title") or ""))]

    dup = copy.deepcopy(SUMAC_DUP_PEOPLE)
    fin_dup, dup = _sync(dup)
    dup_owners = _owners(dup)
    rollup = float((fin_dup or {}).get("current_payroll") or 0.0)
    dup_ok = (len(dup_owners) == 1 and near(rollup, 108000.0, 1.5)
              and str(dup_owners[0].get("full_name")) == "Delia Rennick")

    bench = {"people": [
        {"full_name": "Delia Rennick", "role_title": "Owner and Crew Lead",
         "annual_wage": 63960.0, "wage_source": "oews_pct75",
         "relevant_background": "ten years"},
        {"full_name": "", "role_title": "Owner",
         "annual_wage": 34000.0, "wage_source": "client_override"},
    ], "rest_of_team_payroll_year1": 0.0}
    _fb, bench = _sync(bench)
    brows = bench.get("people") or []
    bench_ok = (len(brows) == 1
                and str(brows[0].get("full_name")) == "Delia Rennick"
                and near(brows[0].get("annual_wage"), 34000.0)
                and str(brows[0].get("wage_source")) == "client_override")

    conflict = {"people": [
        {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
         "annual_wage": 34000.0, "wage_source": "client_override",
         "relevant_background": "ten years"},
        {"full_name": "", "role_title": "Owner",
         "annual_wage": 52000.0, "wage_source": "client_override"},
    ], "rest_of_team_payroll_year1": 0.0}
    fin_c, conflict = _sync(conflict)
    crows = conflict.get("people") or []
    hold = (fin_c or {}).get("_owner_wage_conflict_hold")
    conflict_ok = (len(crows) == 1 and isinstance(hold, dict)
                   and near(hold.get("kept"), 34000.0)
                   and near(hold.get("other"), 52000.0))

    ok = dup_ok and bench_ok and conflict_ok
    return ok, (f"duplicate -> {len(dup_owners)} owner row(s), rollup "
                f"{rollup:,.2f} (want 1 row @ 108,000, was 141,999.96); "
                f"benchmark vs override -> {len(brows)} row(s) @ "
                f"{(brows[0].get('annual_wage') if brows else None)!r} "
                f"(want 1 @ 34,000); two overrides -> {len(crows)} row(s), "
                f"hold={hold!r} (want 1 row + a hold, never a silent pick)")


# ---------------------------------------------------------------------------
# I13  the offered owner draw actually clears the wall
# ---------------------------------------------------------------------------
def _i_owner_draw_clears(ctx):
    """The draw offered must be the one that ACTUALLY clears: the wall's
    payroll_to_clear minus what the rest of the team costs. And when
    that leaves nothing, the exit is not offered at all - an unreachable
    exit is worse than no exit."""
    from client_intake_and_finmo.intake_coherence.section import _owner_draw_exit_tail

    tail = _owner_draw_exit_tail(
        {"kind": "owner_dominated", "owner_annual": 100000.0,
         "staffed_annual": 30000.0, "phasable_annual": 0.0},
        {"payroll_to_clear": 122500.0, "revenue_to_clear": 190000.0},
    )
    # (122,500 - 30,000) / 12 = 7,708/mo. The broken shape divided the
    # whole payroll_to_clear and offered 10,208 - a draw that clears
    # nothing once the staffed team is paid.
    honest = ("$7,708" in tail and "$10,208" not in tail
              and "rest of the team paid as-is" in tail)

    zero_tail = _owner_draw_exit_tail(
        {"kind": "owner_dominated", "owner_annual": 60000.0,
         "staffed_annual": 130000.0, "phasable_annual": 0.0},
        {"payroll_to_clear": 122500.0, "revenue_to_clear": 271000.0},
    )
    zero_ok = ("draw at or below" not in zero_tail and "$271,000" in zero_tail
               and "revenue is the honest way through" in zero_tail)

    ok = honest and zero_ok
    return ok, (f"owner-dominated wall -> offers the clearing draw: {honest} "
                f"(want $7,708, not $10,208); staffed already above the "
                f"ceiling -> no draw exit offered, revenue named: {zero_ok}")


# ---------------------------------------------------------------------------
# I10  COGS proposals are materials-only, with a band
# ---------------------------------------------------------------------------
def _i_cogs_materials_band(ctx):
    """RE-FIXTURED off a crash-red. The old call used today's signature and
    died on TypeError at 7b9f481; that exit code was scored PROVEN. Reading
    the baseline source showed cogs_fit_band already present there (4
    occurrences, the covered path returning the judged materials band), so
    the crash was very likely hiding a GREEN-on-its-own-baseline.

    Bridged, this leg now asks the question at both commits. It also checks
    the COHORT relationship, which is the part that actually distinguishes
    materials-only from cost-of-revenue: the cohort figure must be visible
    AND the proposal must sit far below it. A build that proposed the ~87%
    cohort as the client's materials anchor passes a naive band check if the
    band travels with it; it cannot pass this one."""
    ops = copy.deepcopy(OPS)
    ops["business_naics_6"] = "561720"
    baseline, adapt = ctx.cogs_baseline(ops, 384000.0)
    pct = float(baseline.get("baseline_cogs_percent") or 0.0)
    band = baseline.get("cogs_fit_band")
    cohort = baseline.get("cogs_fit_cohort_cost_of_revenue")
    banded = isinstance(band, (list, tuple)) and len(band) == 2 \
        and band[0] < band[1] and band[0] <= pct <= band[1] and band[1] <= 0.30
    # A labour-heavy cohort runs ~85-90% cost-of-revenue. Materials-only for
    # the same business is single digits. If the proposal is anywhere near the
    # cohort, it is the misfit this invariant exists to forbid.
    not_cohort = pct <= 0.20 and (cohort is None or pct < float(cohort) * 0.5)
    return banded and not_cohort, (
        f"pct = {pct:.4f} within band {band!r} (top <= 0.30) = {banded}; cohort "
        f"cost-of-revenue = {cohort!r} and the proposal must sit far below it "
        f"= {not_cohort} [{adapt}]")


# ---------------------------------------------------------------------------
# I11  the judged price ceiling cannot ratchet on acceptance
# ---------------------------------------------------------------------------
def _i_ceiling_no_ratchet(ctx):
    from client_intake_and_finmo.intake_coherence.controller import _effective_pmax

    # FIXTURE FIXED - same defect R06 had. A bounds dict carrying only
    # price_ceiling_market_fact makes every round return pmax = 1.0 on BOTH
    # commits, so the loop was vacuous. The ratchet requires the relative
    # multiplier and the authoring price, which is also the only shape the
    # app ever stamps.
    fact = 109.25
    offers = []
    price = fact
    for _ in range(3):                       # accept, re-offer, accept again
        pmax = float(_effective_pmax(
            {"unit_price": price},
            {"price_multiplier_max": 1.15,
             "unit_price_at_authoring": fact,
             "price_ceiling_market_fact": fact}))
        price = price * pmax
        offers.append(round(price, 2))
    ok = all(o <= fact + 0.01 for o in offers)
    return ok, (f"three accept/re-offer rounds -> {offers!r}; the market fact "
                f"is {fact} and no round may exceed it (at 7b9f481 round one "
                f"walks the client to 125.64 - acceptance raises the ceiling)")


# ---------------------------------------------------------------------------
INVARIANTS = []

# Per-type (fix, baseline, issue) overrides.
#
# The payroll type is NOT a CW-026 regression. The payroll door is F3 in the
# CW-026 red-proof, and that suite's protocol names F3 an INVARIANT - green on
# both sides of ff1da19. Its label, "rank-1 pin", says what it actually pins:
# CW-025 rank-1, where the completed-state early return meant the router never
# ran and the door never applied.
FORWARD_MOVE_PAIRS = {
    "payroll": ("7bcf307", "c3d83a9", "CW-025 rank-1"),
}

for _i, (_name, _msg, _router, _probe) in enumerate(CORRECTION_TYPES, start=1):
    _fix, _base, _issue = FORWARD_MOVE_PAIRS.get(
        _name, ("ff1da19", "5b5ffbb", "CW-026"))
    INVARIANTS.append(Leg(
        f"I{_i:02d}", "INVARIANT", f"forward-move:{_name}",
        f"a {_name} correction lands or infers-and-proposes - never dead-ends",
        _fix, _base,
        _forward_move_runner(_msg, _router, _probe), issue=_issue))

INVARIANTS += [
    Leg("I07", "INVARIANT", "ack-matches-stored",
        "prose claiming a write cannot ship unless the write landed",
        "7bcf307", "c3d83a9", _i_ack_matches_stored, issue="CW-025 rank-1",
        surface="financials stage: initial_lease (capital_lease_balance since CW-041)"),
    Leg("I08", "INVARIANT", "owner-appears-once",
        "exactly one owner row survives a live turn and the persistence round-trip",
        "18f5ca5", "ff1da19", _i_owner_once, issue="CW-026 #1"),
    Leg("I09", "INVARIANT", "no-double-counted-people",
        "the payroll rollup never double-counts a person",
        "582cef7", "7b9f481", _i_no_double_count, issue="CW-024 #108"),
    Leg("I12", "INVARIANT", "owner-row-uniqueness",
        "exactly one owner row; a wage conflict holds instead of picking silently",
        "18f5ca5", "ff1da19", _i_owner_row_uniqueness, issue="CW-026 #1"),
    Leg("I13", "INVARIANT", "owner-draw-clears",
        "the offered draw actually clears the wall; an unreachable exit is not offered",
        "18f5ca5", "ff1da19", _i_owner_draw_clears, issue="CW-026 #2",
        surface="coherence section", proof=STRUCTURAL_ABSENCE,
        proof_note=("_owner_draw_exit_tail = 0 occurrences under python/ at "
                    "ff1da19 - the exit-tail builder did not exist, so the "
                    "ImportError is the absence itself. Promote by driving the "
                    "wall through the coherence section and asserting the "
                    "offered draw clears it.")),
    Leg("I10", "INVARIANT", "cogs-materials-only-band",
        "COGS proposals are materials-only and carry a band",
        "eb7529b", "613a19a", _i_cogs_materials_band, tier=LIVE,
        proof_note=(
            "RE-BASELINED 2026-08-12, and this is the whole point of the "
            "four-outcome harness. The leg used to sit at 582cef7/7b9f481 and "
            "died there on a TypeError, which the old prove() scored PROVEN. "
            "Bridged by call_compat it reached its assertion and came back "
            "GREEN on 7b9f481 - the informative result: the baseline was wrong, "
            "not the app. cogs_fit_band first appears at eb7529b (the fitted "
            "COGS proposal) and is 0 occurrences at 613a19a immediately before "
            "it, so 7b9f481 POSTDATES the ship and the invariant genuinely held "
            "there. Relocated to eb7529b/613a19a - R13's pair, by construction: "
            "R13 is the regression pin on that ship, this is the invariant. "
            "Expect the red in R13's shape - no band at all on the raw cohort "
            "figure. If this ever crashes again instead of asserting, the fix "
            "is the call shape, never restoring the crash-red.")),
    Leg("I11", "INVARIANT", "price-ceiling-no-ratchet",
        "the judged price ceiling cannot ratchet on acceptance",
        "582cef7", "7b9f481", _i_ceiling_no_ratchet, issue="CW-024",
        surface="coherence controller"),
]
