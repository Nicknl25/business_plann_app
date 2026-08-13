# -*- coding: utf-8 -*-
"""The leg registry - every KNOWN issue, one leg each.

Two kinds of leg live here:

  REGRESSION  one per fixed bug. Replays the scenario that broke and
              asserts the fix still holds. Carries the commit that fixed
              it and the commit where it was still live, so the leg can
              be PROVEN: red on its own broken baseline, green after.

  INVARIANT   one per structural rule that must always hold. Fired at
              the relevant surface. Same proof discipline.

THE RULE FOR ADDING A LEG: it must go RED on `baseline` and GREEN on the
fix. `python -m replay_gate.run_gate --prove` checks exactly that, per
leg, in clean subprocesses. A leg that cannot go red on its own broken
baseline is on a fixture path and is QUARANTINED - excluded from the
gate verdict and named in the report. It is not silently trusted.

HONEST BOUNDARY: this file catches KNOWN issues only. It structurally
cannot catch a bug nobody has found - there is no scenario and no
assertion for one. That is what the full Cowork run is for. Keep the
split: gate = known issues, seconds; Cowork = unknown, thorough.
"""
import copy
import json

from .surface import (
    OPS, PEOPLE, PATCHLESS, RecordedRouter, call_compat, near, product_field,
)

FAST = "fast"      # recorded router doubles / pure functions - no GPT
LIVE = "live"      # needs the real judge or router - slower, costs tokens


BEHAVIOURAL = "behavioural"
# GOLDEN_MASTER: a NEGATIVE CONTROL. Its property is "this output did not
# change", so it is GREEN on both commits by construction and can never
# satisfy red-on-broken. That is not a fixture path - it is a different kind
# of claim, and it needs a different proof: prove() runs it at BOTH commits
# and requires the artifact hash it emits to be IDENTICAL and non-empty on
# each side. A leg carrying this label MUST print "GOLDEN-SHA <hex>" in its
# evidence, and must assert its payload is substantive - a hash over an empty
# dict matches itself perfectly and proves nothing.
GOLDEN_MASTER = "golden-master"
# STRUCTURAL_ABSENCE: this leg's baseline red is an ImportError/AttributeError
# because the capability it pins DID NOT EXIST at that commit - verified by
# grepping the baseline tree, not inferred from the commit message. Such a red
# is honest (the guard genuinely was not there) but it is NOT a demonstration
# of the bug behaving, so it is counted and reported separately. A leg may only
# carry this label with a `proof_note` recording the check that justifies it.
STRUCTURAL_ABSENCE = "structural-absence"


class Leg(object):
    def __init__(self, leg_id, kind, bug, title, fix_commit, baseline,
                 run, tier=FAST, surface="completed-financials", issue="",
                 proof=BEHAVIOURAL, proof_note=""):
        self.id = leg_id
        self.kind = kind              # REGRESSION | INVARIANT
        self.bug = bug                # short_name of the bug this pins
        self.title = title
        self.fix_commit = fix_commit
        self.baseline = baseline      # commit where this bug was still live
        self.run = run                # run(ctx) -> (ok, evidence)
        self.tier = tier
        self.surface = surface
        self.issue = issue
        self.proof = proof            # BEHAVIOURAL | STRUCTURAL_ABSENCE
        self.proof_note = proof_note  # why the label is justified

    def __repr__(self):
        return f"<Leg {self.id} {self.bug}>"


# =========================================================================
# REGRESSION legs
# =========================================================================

def _r_freeze(ctx):
    """CW-026: the completed-financials dead end. The exact Sumac [101]
    text, patchless router - the live failure."""
    msg = ctx.captured(r"unit price is now\s*\$?\s*650",
                       "My unit price is now 650 instead of 520.",
                       draft_hint="2ecc759c")
    turn, fin_out, did = ctx.turn(msg, RecordedRouter(PATCHLESS))
    _f, _p, ops = ctx.sections(did)
    got = product_field(ops, "unit_price")
    ctx.note_turn(turn)
    return near(got, 650.0), f'replayed "{msg}" -> stored unit_price = {got!r} (want 650, was 520)'


def _r_payroll_lands(ctx):
    """The payroll door must land the stated total on the stored field.

    RE-BASELINED (was ff1da19/5b5ffbb, which could never red). This case is
    F3 in the CW-026 red-proof, and that suite's own protocol calls it an
    INVARIANT - "0-green on the pre-fix baseline except the pinned F3/F12
    invariants" - i.e. green on both sides of ff1da19. F3's label says what
    it actually pins: "rank-1 pin", meaning CW-025 rank-1.

    At c3d83a9 the completed-financials branch is an unconditional early
    return, so the router never runs, the people door never executes, and
    the stated total never reaches the stored field. That is the commit
    where "a payroll correction lands" was genuinely false.

    Overlaps R15 by design: R15 pins that the router RAN, this pins that
    the value LANDED. Same bug, two symptoms, both worth catching.
    """
    door = {"action": "edit_patch", "assistant_message": "",
            "patch": {"people.total_team_payroll": 120000}}
    turn, fin_out, did = ctx.turn("My total payroll is $120,000.",
                                  RecordedRouter(door))
    ctx.note_turn(turn)
    fin_db, _p, _o = ctx.sections(did)
    got = fin_db.get("current_payroll")
    src = "stored"
    if not near(got, 120000.0, 1.5):
        got, src = (fin_out or {}).get("current_payroll"), "handler state"
    return near(got, 120000.0, 1.5), (
        f"{src} current_payroll = {got!r} (want 120,000; at c3d83a9 the "
        f"completed-state early return skips the router entirely so the door "
        f"never applies and it stays 133,000)")


def _r_sumac_revert(ctx):
    """The Sumac revert: the correction landed, then came back one turn
    later. The next turn's preamble runs THE RECALC over the PERSISTED
    sections, so replay exactly that: land it, reload from the DB, run
    the canonical sync, assert it survived."""
    door = {"action": "edit_patch", "assistant_message": "",
            "patch": {"people.total_team_payroll": 120000}}
    turn, fin_out, did = ctx.turn("My total payroll is $120,000.",
                                  RecordedRouter(door))
    ctx.note_turn(turn)
    if not near((fin_out or {}).get("current_payroll"), 120000.0, 1.5):
        return False, f"never landed in the first place: {(fin_out or {}).get('current_payroll')!r}"
    fin_db, ppl_db, ops_db = ctx.sections(did)
    fin_next, _y1 = ctx.ic._sync_financials_consult_persistence_state(
        financials_json=fin_db,
        financials_year1_json=ctx.assembled_year1(fin_db, people=ppl_db, ops=ops_db),
        marketing_model_json={},
        people_json=ppl_db,
        ops_json=ops_db,
    )
    got = (fin_next or {}).get("current_payroll")
    return near(got, 120000.0, 1.5), (
        f"after reload + next-turn Recalc: current_payroll = {got!r} "
        f"(want 120,000; the live revert rebuilt 133,000 from the stale roster)")


CEDAR_PEOPLE_PHANTOM = {
    "people": [
        {"full_name": "Owner", "role_title": "Owner / Operator",
         "annual_wage": 60000.0},
        {"full_name": "Crew (4)", "role_title": "Grounds crew (4 people)",
         "annual_wage": 136000.0},
    ],
    "rest_of_team_payroll_year1": 136000.0,
}


def _r_crew_double_count(ctx):
    """A crew-of-N group row cannot persist as a person AND be counted
    again in rest-of-team. The rollup must dedupe."""
    fin = ctx.completed_fin()
    fin_out, _y1 = ctx.ic._sync_financials_consult_persistence_state(
        financials_json=copy.deepcopy(fin),
        financials_year1_json={},
        marketing_model_json={},
        people_json=copy.deepcopy(CEDAR_PEOPLE_PHANTOM),
        ops_json=copy.deepcopy(OPS),
    )
    rollup = (fin_out or {}).get("current_payroll")
    doubled = 60000.0 + 136000.0 + 136000.0     # the phantom sum
    deduped = 60000.0 + 136000.0
    ok = near(rollup, deduped, 1.0) or (rollup is not None and float(rollup) < doubled - 1.0)
    return ok, (f"rollup = {rollup!r}; deduped = {deduped:,.0f}, "
                f"double-counted = {doubled:,.0f} (the group row counted twice)")


def _r_capex_zero(ctx):
    """Prose must not confirm a capex write that never happened.

    REWRITTEN. The old shape could not red for three compounding reasons:

    1. It entered at the completed-financials surface, where 7b9f481 returns
       before route_intent is ever called - the recorded router was never
       invoked, so normalize was never reached.
    2. It asserted on `capex_total_year1`, a field that does not exist
       anywhere in the app (0 hits in python/). The real stage field is
       `current_capex`.
    3. Its message contained "haven't", which trips the zero-token branch of
       the very guard it was aiming at - so even on the FIX the zero would
       land and the leg would have been red on its own fix commit.

    Now RP5's shape: the capex question is PENDING, the client answers about
    something else entirely (payroll), and nothing about capex is stated. The
    bug is that the reply confirms a capex write it never made.
    """
    fin = ctx.completed_fin()
    fin.pop("current_capex", None)
    fin.pop("_financials_stage_confirms", None)
    stage = ctx.ic._next_financials_stage(fin)
    if stage != "current_capex":
        return False, (f"setup: active stage is {stage!r}, need 'current_capex' "
                       f"pending for the false-confirmation shape")
    prose = ("Got it - I will use 0 for current capital spending for now. "
             "We can revisit it once you know the number.")
    turn, fin_out, did = ctx.turn(
        "Before the equipment question - my total annual payroll is 225,000. "
        "Please correct it to 225,000.",
        RecordedRouter({"action": "answer_readonly", "assistant_message": prose,
                        "patch": {"financials.current_capex": 0.0,
                                  "financials.payroll_total_year1": 225000.0}}),
        fin=fin,
        last_assistant="Have you recently made any larger one-time purchases "
                       "for the business, like equipment or vehicles?")
    ctx.note_turn(turn)
    msg = str((turn or {}).get("assistant_message") or "")
    fin_db, _p, _o = ctx.sections(did)
    capex = fin_db.get("current_capex")
    if capex is None:
        capex = (fin_out or {}).get("current_capex")
    zeroed = near(capex, 0.0, 1e-9)
    claims_zero = ("use 0" in msg.lower()) or ("use $0" in msg.lower())
    return (not zeroed) and (not claims_zero), (
        f"stored current_capex = {capex!r} (must not be zeroed by a message "
        f"that never mentions capex); reply claims a zero write = "
        f"{claims_zero} (at 7b9f481 the router's prose ships verbatim and "
        f"confirms a write that never happened)")


def _r_price_ratchet(ctx):
    """Accepting a price cannot raise the ceiling. The durable market
    fact caps it, so the next offer is bounded by the market fact and not
    by a multiplier off the just-accepted price."""
    from client_intake_and_finmo.intake_coherence.controller import _effective_pmax

    # FIXTURE FIXED. The old bounds dict carried only price_ceiling_market_fact,
    # which 7b9f481 ignores entirely - with no price_multiplier_max and no
    # unit_price_at_authoring it fell through to pmax = 1.0 and the assertion
    # passed on BOTH sides. The ratchet only exists when the relative
    # multiplier and the authoring price are present; that is also the only
    # shape section.py ever stamps.
    line = {"unit_price": 109.25}
    bl = {"price_multiplier_max": 1.15,
          "unit_price_at_authoring": 109.25,
          "price_ceiling_market_fact": 109.25}
    pmax = _effective_pmax(line, bl)
    offer = 109.25 * float(pmax)
    ok = offer <= 109.25 + 0.01
    return ok, (f"_effective_pmax -> {pmax!r}; next offer = {offer:,.2f} "
                f"(must stay <= the 109.25 market fact; at 7b9f481 the market "
                f"fact is not consulted and the full relative +15% re-grants "
                f"off the just-accepted price -> 125.64)")


def _r_ask_then_ignore(ctx):
    """A solicitation must have a consumer. The #117 guard covers an
    acceptance whose own words CONTRADICT the proposal - not a
    figure-quoting acceptance, which is a different concern this guard
    never covered on any commit. The topic line comes from stage_name,
    so pass a real one."""
    hold = ctx.ic._acceptance_mismatch_hold(
        stage_name="cogs",
        user_message="I don't spend anything like that today, but fine, use it.")
    clean = ctx.ic._acceptance_mismatch_hold(
        stage_name="cogs", user_message="Yes, that works.")
    ok = bool(hold) and clean is None
    return ok, (f"contradicting acceptance -> hold={hold!r}; "
                f"clean acceptance -> {clean!r} (want a hold, then None)")


def _r_freeze_norouting(ctx):
    """CW-025 rank-1: the OTHER stage of the freeze class. At the
    completed state a correction turn returned BEFORE the router ran -
    zero router calls, and the gate replayed the wall verbatim. R01 pins
    the later dead-end wording; this pins the early return itself.

    The surface assertion already guarantees the completed state, which
    matters here: on c3d83a9 the stage-flow people door worked fine and
    only the no-active-stage path was broken."""
    spy = RecordedRouter({"action": "edit_patch", "assistant_message": "",
                          "patch": {"people.total_team_payroll": 120000}})
    turn, fin_out, did = ctx.turn("My total payroll is $120,000.", spy)
    ctx.note_turn(turn)
    fin_db, _p, _o = ctx.sections(did)
    got = fin_db.get("current_payroll")
    if not near(got, 120000.0, 1.5):
        got = (fin_out or {}).get("current_payroll")
    routed = len(spy.calls) >= 1
    ok = routed and near(got, 120000.0, 1.5)
    return ok, (f"router calls = {len(spy.calls)} (want >= 1 - the early "
                f"return made zero); stored current_payroll = {got!r} "
                f"(want 120,000)")


SUMAC_FRAME = {"stated": 99000.0, "named_sum": 37000.0, "remainder": 62000.0}


def _r_inclusion_references(ctx):
    """Ruling #3: figures inside the app's own frame are REFERENCES, not
    the client's answer. The client confirming "Rosalie's $37,000 is
    inside that $99,000, so $62,000 for the other two" means 62,000 -
    the resolver used to hand back the first figure it saw, 37,000."""
    resolve = ctx.ic._rest_inclusion_resolve
    got = resolve(pending=dict(SUMAC_FRAME),
                  user_message=("Yes, Rosalie's $37,000 is inside that $99,000. "
                                "So $62,000 for the other two is right."))
    fresh = resolve(pending=dict(SUMAC_FRAME),
                    user_message="It's $90,000 for the others.")
    separate = resolve(pending=dict(SUMAC_FRAME),
                       user_message="No, that's separate from her.")
    agree = resolve(pending=dict(SUMAC_FRAME),
                    user_message="Yes, she's included.")
    ok = (near(got, 62000.0) and near(fresh, 90000.0)
          and near(separate, 99000.0) and near(agree, 62000.0))
    return ok, (f"actual Sumac confirmation -> {got!r} (want 62,000, the bug "
                f"returned 37,000); fresh figure -> {fresh!r} (90,000); "
                f"separate -> {separate!r} (99,000); agreement -> {agree!r} (62,000)")


_ECHO_FIN = {
    "current_revenue": 175000.0, "cogs_percent_of_revenue": 0.15,
    "cogs_basis": "ratio", "current_cogs": 26250.0,
    "cogs_total_year1": 26250.0, "_financials_revenue_intro_done": True,
}


def _r_cogs_echo_guard(ctx):
    """Ruling #4: the basis flips to dollars only when the figure is in
    the CLIENT's message. An anchor the app itself put on screen and the
    router echoed back is not a client statement.

    Both halves in one leg: the echo must NOT flip (Q3), and a genuine
    client-stated dollar figure MUST still flip (Q4) - otherwise the fix
    could 'pass' by never flipping at all."""
    norm = ctx.ic._normalize_financials_router_patch
    echoed = norm(
        patch={"financials.current_cogs": 26250.0},
        active_stage="",
        financials_json=copy.deepcopy(_ECHO_FIN),
        financials_year1_json={"company_revenue_total_year1": 175000.0},
        last_assistant=("For direct costs - a business like yours typically "
                        "runs about 12%-18% of revenue. I'd start at 15%, "
                        "which works out to around $26,250."),
        user_message="That sounds reasonable, let's go with 15%.",
    )
    held = str((echoed or _ECHO_FIN).get("cogs_basis"))
    stated = norm(
        patch={"financials.current_cogs": 30000.0},
        active_stage="",
        financials_json=copy.deepcopy(_ECHO_FIN),
        financials_year1_json={"company_revenue_total_year1": 175000.0},
        last_assistant="",
        user_message="Materials actually run about $30,000 a year.",
    )
    flipped = str((stated or {}).get("cogs_basis"))
    amount = (stated or {}).get("current_cogs")
    ok = held == "ratio" and flipped == "dollars" and near(amount, 30000.0)
    return ok, (f"echoed anchor -> cogs_basis {held!r} (want 'ratio'); "
                f"client-stated -> {flipped!r} @ {amount!r} (want 'dollars' @ 30,000)")


def _r_cogs_basis_stamp(ctx):
    """CW-024 #112: an EXPLICIT cogs_basis in the patch outranks the
    touched-twin inference through the PRODUCTION normalize path."""
    fin = ctx.completed_fin()
    applied = ctx.ic._normalize_financials_router_patch(
        patch={"cogs_percent_of_revenue": 0.055,
               "cogs_total_year1": 21120.0,
               "cogs_basis": "ratio"},
        active_stage="",
        financials_json=fin,
        financials_year1_json=ctx.assembled_year1(fin),
        last_assistant="",
        user_message="",
    )
    got = (applied or {}).get("cogs_basis")
    return str(got) == "ratio", (
        f"normalized patch cogs_basis = {got!r} (want 'ratio'; the bug "
        f"filtered the field and the twin inference re-tagged 'dollars')")


def _r_owner_one_door(ctx):
    """Owner pay lives in PEOPLE, period. The financials door is gone -
    not deprecated, gone: no stage, no spec field, no router schema."""
    ic = ctx.ic
    order = tuple(getattr(ic, "_FINANCIALS_STAGE_ORDER", ()))
    in_order = "owner_compensation" in order
    in_specs = False
    for st in order:
        spec = ic._financials_stage_spec(st) or {}
        fields = set(spec.get("patch_targets") or ()) | set(spec.get("completion_fields") or ())
        if "owner_compensation" in fields:
            in_specs = True
            break
    import client_intake_and_finmo.intent_router as router_mod
    import inspect
    try:
        src = inspect.getsource(router_mod)
    except Exception:
        src = ""
    # The precise schema fragment, not the bare word: a comment or a
    # read-only mirror mentioning owner_compensation is not the door.
    in_schema = '"owner_compensation": {"type": "number"}' in src
    ok = not in_order and not in_specs and not in_schema
    return ok, (f"owner_compensation in stage order={in_order}, in a stage "
                f"spec={in_specs}, in router patch schema={in_schema} "
                f"(all must be False - the door is gone, not deprecated)")


def _r_role_wage_rollup(ctx):
    """CW-023: a role-wage correction recomputes THE ROLLUP. Never a
    hand-patch that leaves the engine-read fields stale."""
    people = copy.deepcopy(PEOPLE)
    fin = ctx.completed_fin()
    # ops_json arrived with the fix; at 000edda the writer has no such
    # parameter. Passing it raised TypeError and the leg never reached the
    # rollup assertion - a crash-red that said "signature changed", not
    # "the rollup was stale". call_compat drops it there so the stale-twin
    # behaviour is what the red actually shows.
    fin2, adapt = call_compat(
        ctx.ic._apply_owner_pay_statement,
        monthly=4000.0, people_json=people, financials_json=fin,
        ops_json=copy.deepcopy(OPS))
    owner = next((p for p in (people.get("people") or [])
                  if ctx.ic._OWNER_TITLE_RE.search(str(p.get("role_title") or ""))), {})
    wage = owner.get("annual_wage")
    fields = {k: (fin2 or {}).get(k) for k in
              ("current_payroll", "payroll_total_year1", "baseline_payroll_year1")}
    present = {k: v for k, v in fields.items() if v is not None}
    expected = 48000.0 + 37000.0 + float(PEOPLE["rest_of_team_payroll_year1"])
    consistent = bool(present) and all(near(v, expected, 1.0) for v in present.values())
    return near(wage, 48000.0, 1.0) and consistent, (
        f"owner annual_wage = {wage!r} (want 48,000); rollup fields = {present!r} "
        f"(all must equal {expected:,.0f} - the bug left them stale) [{adapt}]")


def _r_cedar_double_correction(ctx):
    """The door is a TARGET. The delta is computed AFTER roster dedupe,
    so a stated total persists exactly instead of being subtracted twice."""
    door = {"action": "edit_patch", "assistant_message": "",
            "patch": {"people.total_team_payroll": 225000}}
    turn, fin_out, did = ctx.turn(
        "My total payroll is $225,000.", RecordedRouter(door),
        people=copy.deepcopy(CEDAR_PEOPLE_PHANTOM))
    ctx.note_turn(turn)
    fin_db, _p, _o = ctx.sections(did)
    got = fin_db.get("current_payroll")
    if got is None:
        got = (fin_out or {}).get("current_payroll")
    return near(got, 225000.0, 1.0), (
        f"stored current_payroll = {got!r} (want exactly 225,000; the "
        f"pre-dedupe delta subtracted twice and landed 89k)")


def _r_rest_inclusion(ctx):
    """CW-025 rank-2: a rest-of-team figure that plausibly CONTAINS an
    already-named wage cannot record silently."""
    hold = ctx.ic._rest_inclusion_check(
        patch={"people.rest_of_team_payroll_year1": 128000},
        people_json={"people": [
            {"full_name": "Tanya Brill", "role_title": "Cleaner",
             "annual_wage": 35000.0}]},
        user_message="The cleaners come to $128,000 a year all together.",
        messages=[{"role": "user",
                   "content": "They're $31,000 each, so that's $93,000 for them."}],
    )
    clean = ctx.ic._rest_inclusion_check(
        patch={"people.rest_of_team_payroll_year1": 62000},
        people_json=copy.deepcopy(PEOPLE),
        user_message="The rest of the crew is $62,000.",
        messages=[],
    )
    ok = bool(hold) and clean is None
    return ok, (f"inclusion-ambiguous answer -> hold={'raised' if hold else 'NONE'}; "
                f"clean capture -> {clean!r} (want a hold, then None)")


# --- CW-027 -------------------------------------------------------------
# The Wren Hollow shapes, verbatim from the live run.
WREN_PROPOSAL = (
    "I'll start with direct costs of $99,840 a year (32% of revenue) - "
    "correct me if your actual materials cost differs.\n\nFor marketing, "
    "a reasonable starting point is about 9% of revenue, which works out "
    "to around $28,080 a year.\n\nDoes that broadly match what it will "
    "take to attract and convert customers, or should we adjust it?"
)
MSG_67 = ("I spend about $4,800 a year on Google ads and that's it. "
          "Nowhere near $28,000.")
MSG_97 = ("I'd keep most of them. Maybe I lose one in ten - the price "
          "shoppers who were only calling me because I was cheapest. "
          "Call it 90% staying.")

WREN_OPS = {
    "business_naics_6": "811412",
    "lob_models": [{"lob_name": "Appliance Repair", "products": [{
        "product_name": "completed service job", "unit_price": 189.0,
        "unit_cadence": "weekly", "units_per_week_capacity": 55.0,
        "utilization_rate": 0.78}]}],
}
WREN_PEOPLE = {
    "people": [
        {"full_name": "Tobias Reyes", "role_title": "Owner / Lead Technician",
         "annual_wage": 46000.0, "wage_source": "client_override"},
        {"full_name": "Junie Delacroix", "role_title": "Lead Technician",
         "annual_wage": 52000.0, "wage_source": "client_override"},
    ],
    "rest_of_team_payroll_year1": 132000.0,
}
_WREN_ROUTER = {"action": "edit_patch",
                "assistant_message": "Got it - $4,800 a year.",
                "patch": {"financials.marketing_total_year1": 4800}}


def _wren_marketing_fin(ctx):
    return ctx.ic._ensure_financials_stage_defaults({
        "current_revenue": 312000.0,
        "cogs_percent_of_revenue": 0.32,
        "cogs_basis": "dollars",
        "current_cogs": 99840.0,
        "cogs_total_year1": 99840.0,
        "current_payroll": 230000.0,
        "_financials_revenue_intro_done": True,
    })


def _r_rejected_figure_reference(ctx):
    """CW-027 #1 (blocker #130): a figure in rejection/negation context,
    or one echoing the app's own last message, is a REFERENCE. It cannot
    be captured as a value.

    This leg fires at the MARKETING stage, not the completed state - it
    asserts that locally, because entering anywhere else would not be
    replaying the shape that broke.

    Both halves, per VS's W1 + W2: the negated figure cannot land, AND
    the filter does not eat a real correction. Without the second half a
    build that simply captured nothing would look fixed."""
    fin = _wren_marketing_fin(ctx)
    stage = ctx.ic._next_financials_stage(fin)
    if stage != "marketing":
        return False, (f"setup: active stage is {stage!r}, need 'marketing' - "
                       f"this leg replays the marketing-stage shape")

    turn, fin_out, did = ctx.turn(
        MSG_67, RecordedRouter(_WREN_ROUTER), fin=fin,
        people=copy.deepcopy(WREN_PEOPLE), ops=copy.deepcopy(WREN_OPS),
        last_assistant=WREN_PROPOSAL,
        year1={"company_revenue_total_year1": 312000.0},
        business_name="Wren Hollow Appliance Repair")
    ctx.note_turn(turn)
    msg = str((turn or {}).get("assistant_message") or "")
    cogs = fin_out.get("current_cogs")
    mkt = fin_out.get("marketing_total_year1")
    cogs_ok = near(cogs, 99840.0)
    mkt_ok = near(mkt, 4800.0)
    no_capture = "$28,000" not in msg
    fin_db, _p, _o = ctx.sections(did)

    # W2 invariant: a bundled STATEMENT figure still moves forward.
    _t2, fin2, _d2 = ctx.turn(
        "About $4,800 a year on ads. And my total payroll is really "
        "$210,000 by the way.",
        RecordedRouter(_WREN_ROUTER), fin=_wren_marketing_fin(ctx),
        people=copy.deepcopy(WREN_PEOPLE), ops=copy.deepcopy(WREN_OPS),
        last_assistant=WREN_PROPOSAL,
        year1={"company_revenue_total_year1": 312000.0},
        business_name="Wren Hollow Appliance Repair")
    statement_ok = near(fin2.get("current_payroll"), 210000.0, 1.5)

    ok = cogs_ok and mkt_ok and no_capture and statement_ok
    return ok, (
        f"marketing = {mkt!r} (want 4,800); current_cogs = {cogs!r} "
        f"(want 99,840 untouched - the bug inferred 28,000); "
        f"reply free of a $28,000 capture = {no_capture}; "
        f"W2 bundled statement -> current_payroll "
        f"{fin2.get('current_payroll')!r} (want 210,000); "
        f"DB financials_json.current_cogs = {fin_db.get('current_cogs')!r}")


def _r_retention_consumed(ctx):
    """CW-027 #2 (#131): the retention answer is consumed regardless of
    focus. Assert the stored state actually MOVED - utilization
    0.78 -> 0.702 and revenue scaled - not that the app acknowledged it.

    Paired with W4: a bare figure with no keep/stay/retain context is
    not a retention answer, so the consumer cannot become a figure
    magnet."""
    from client_intake_and_finmo.intake_coherence import section as sec

    fin = {"current_revenue": 421200.0, "cogs_percent_of_revenue": 0.32,
           "cogs_basis": "dollars", "current_cogs": 134784.0,
           "cogs_total_year1": 134784.0}
    st = dict(sec.get_state(fin))
    st["retention_pending"] = {
        "prices": [{"product": "completed service job", "to": 189.0}],
        "retained_used": 1.0,
    }
    fin = sec.put_state(fin, st)
    ops = copy.deepcopy(WREN_OPS)

    ans = ctx.ic._parse_retention_answer(MSG_97)
    if ans is None:
        return False, ("the verbatim [97] answer did not parse as a retention "
                       "answer (parser returned None) - the frame would sit "
                       "unconsumed into the build")
    fin2, ops2, applied = sec.apply_retention_answer(fin, ops, ans)
    st2 = sec.get_state(fin2)
    util = product_field(ops2, "utilization_rate")
    rev = fin2.get("current_revenue")
    cleared = st2.get("retention_pending") is None

    bare_rev = ctx.ic._parse_retention_answer("Revenue is about $190,000.")
    bare_price = ctx.ic._parse_retention_answer("Change my price to $650.")
    w4_ok = bare_rev is None and bare_price is None

    ok = (bool(applied) and cleared and near(util, 0.702, 0.002)
          and near(rev, 379080.0, 2.0) and w4_ok)
    return ok, (
        f"applied = {applied!r}; stored utilization = {util!r} "
        f"(want 0.702, was 0.78); revenue = {rev!r} (want 379,080 from "
        f"421,200); frame cleared = {cleared}; W4 bare figures parsed as "
        f"retention = {(bare_rev, bare_price)!r} (want (None, None))")


# --- CW-028 -------------------------------------------------------------
# Alder & Vine Home Goods: the retail/goods persona whose run stuck at the
# reconciliation hold. Fixtures and assertions lifted from VS's
# _redproof_cw028.py (X1-X9), which is 0/9 on af791ec and 9/9 on the fix.
#
# NOTE ON ALDER_OPS: units_per_period_capacity is deliberately STALE (2.0)
# against a weekly capacity of 185. R20 exists to prove the canonical pass
# heals that. Any leg that must NOT start from a corrupt twin overrides it
# to 185 first - see _r_sibling_attribution's count-of-persons form, where
# a pre-stored 2 would make the old code vacuously green.
ALDER_OPS = {
    "business_naics_6": "449129",
    "lob_models": [{"lob_name": "Retail", "products": [{
        "product_name": "In-store sales transaction", "unit_price": 68.0,
        "unit_cadence": "weekly", "units_per_week_capacity": 185.0,
        "units_per_period_capacity": 2.0,
        "operating_periods_per_year": 52.0, "utilization_rate": 0.8}]}],
}
ALDER_PEOPLE = {
    "people": [
        {"full_name": "Marisol Okafor", "role_title": "Owner & Buyer",
         "annual_wage": 62000.0, "wage_source": "client_override"},
        {"full_name": "Priya Raghunathan", "role_title": "Store Manager",
         "annual_wage": 46000.0, "wage_source": "client_override"},
    ],
    "rest_of_team_payroll_year1": 19000.0,
}
_ALDER_BASE_FIN = {
    "current_revenue": 530000.0, "cogs_percent_of_revenue": 0.48,
    "cogs_basis": "ratio", "current_cogs": 254400.0,
    "cogs_total_year1": 254400.0, "current_payroll": 127000.0,
    "current_num_employees": 3, "marketing_total_year1": 6000.0,
    "monthly_rent_expense": 3900.0, "gna_total_year1": 21000.0,
    "capex_total_year1": 0.0, "initial_assets": 45000.0,
    "initial_lease": 0.0, "total_debt_outstanding": 32000.0,
    "other_monthly_debt_payments": 780.0,
    "annual_interest_payment": 2600.0,
    "annual_principal_payment": 6760.0, "cash_on_hand": 28000.0,
    "ar_balance": 2000.0, "ap_balance": 15000.0,
    "inventory_balance": 96000.0, "cash_strategy": "preserve_cash",
    "funding_preference": "debt",
    "_financials_revenue_intro_done": True,
    "_financials_marketing_stage_done": True,
}
ALDER_YEAR1 = {"company_revenue_total_year1": 530000.0}


def _alder_fin(ctx, missing=None, extra=None):
    """Completed-financials fin, then pop `missing` so a NAMED stage is
    active. Legs that replay a mid-stage capture need the stage the live
    run was actually in, not the completed surface."""
    fin = ctx.ic._ensure_financials_stage_defaults(copy.deepcopy(_ALDER_BASE_FIN))
    for st in list(getattr(ctx.ic, "_FINANCIALS_STAGE_ORDER", ())):
        spec = ctx.ic._financials_stage_spec(st)
        for f in (spec.get("completion_fields") or ()):
            if fin.get(f) is None:
                fin[f] = 1.0
    for k in (missing or []):
        fin.pop(k, None)
        fin.pop("_financials_stage_confirms", None)
    for k, v in (extra or {}).items():
        fin[k] = v
    return fin


def _alder_turn(ctx, message, router, fin, ops=None, last=""):
    return ctx.turn(
        message, RecordedRouter(router), fin=fin,
        people=copy.deepcopy(ALDER_PEOPLE),
        ops=copy.deepcopy(ops or ALDER_OPS),
        last_assistant=last, year1=copy.deepcopy(ALDER_YEAR1),
        business_name="Alder & Vine Home Goods")


def _r_capacity_twin(ctx):
    """CW-028 #1 (X1): under a weekly cadence the period twin DERIVES from
    the weekly value at the canonical pass. Two capacity fields can never
    disagree - which is what let the reconciliation hold read 2 while every
    receipt reported 185."""
    ops = copy.deepcopy(ALDER_OPS)          # period twin stale at 2
    before = ops["lob_models"][0]["products"][0]["units_per_period_capacity"]
    ctx.ic._sync_financials_consult_persistence_state(
        financials_json=_alder_fin(ctx), financials_year1_json={},
        marketing_model_json={}, people_json=copy.deepcopy(ALDER_PEOPLE),
        ops_json=ops)
    prod = ops["lob_models"][0]["products"][0]
    after = prod.get("units_per_period_capacity")
    week = prod.get("units_per_week_capacity")
    return near(after, 185.0), (
        f"period twin {before!r} -> {after!r} against weekly {week!r} "
        f"(weekly cadence: the twins must agree; the stale 2 is the loop's trigger)")


def _r_reconciliation_hold_consumes(ctx):
    """CW-028 #2 (X2): the anchor-vs-ops hold can never re-issue verbatim.
    In the live run the identical hold fired four times while the client
    answered it every time and the stored driver never moved."""
    from client_intake_and_finmo.intake_coherence import section as sec

    ops = copy.deepcopy(ALDER_OPS)          # stale twin kept: ceiling ~7,072
    fin = {"current_revenue": 530000.0, "_financials_revenue_intro_done": True}
    answer = "Capacity is 185 per week."
    t1, fin1, _x = sec.gate_and_turn(
        ops_json=ops, people_json={}, market_json={}, marketing_model_json={},
        financials_json=fin, financials_year1_json={}, user_text=answer)
    m1 = str((t1 or {}).get("assistant_message") or "")
    if "doesn't add up" not in m1:
        return False, ("setup: the reconciliation hold did not fire on the "
                       f"first pass - got {m1[:120]!r}")
    t2, _fin2, _y = sec.gate_and_turn(
        ops_json=ops, people_json={}, market_json={}, marketing_model_json={},
        financials_json=dict(fin1), financials_year1_json={}, user_text=answer)
    m2 = str((t2 or {}).get("assistant_message") or "")
    differs = m2 != m1
    exposes = ("computing from" in m2) and ("$68.00" in m2)
    return differs and exposes, (
        f"second hold differs from the first = {differs}; exposes its stored "
        f"operands = {exposes} (the repeat must show what it is computing "
        f"from, never re-issue the same text)")


def _r_sibling_attribution(ctx):
    """CW-028 #3 (X3/X4/X5) + the positive invariant (X6) + the repair
    receipt (X9, folded here per VS since it shares this baseline).

    The reference-vs-statement law's self-attribution forms: a figure the
    client's own words already attribute to one line cannot be re-captured
    onto a sibling. Three forms, each the verbatim live message.

    The positive companion is not optional - without it a build that
    captured nothing at all would pass this leg."""
    ic = ctx.ic
    fails = []

    # --- X3 ratio-twin: the verbatim [55]. The landed 48% must not
    # re-capture as a $48 unit price.
    fin = _alder_fin(ctx, missing=["current_cogs"])
    stage = ic._next_financials_stage(fin)
    if stage != "cogs":
        return False, f"setup(ratio-twin): active stage is {stage!r}, need 'cogs'"
    turn, _fo, _d = _alder_turn(
        ctx,
        "It's a bit higher than that - what we pay for the goods themselves "
        "runs about 48% of the sale price. So call it $254,000 a year.",
        {"action": "edit_patch", "assistant_message": "",
         "patch": {"financials.cogs_percent_of_revenue": 0.48,
                   "financials.cogs_total_year1": 254400.0,
                   "financials.current_cogs": 254400.0}},
        fin,
        last=("For direct costs - a business like yours typically runs about "
              "42%-50% of revenue. I'd start at 46%, which works out to "
              "around $243,800."))
    m = str((turn or {}).get("assistant_message") or "")
    if "unit price" in m.lower() or "$48" in m:
        fails.append("ratio-twin: 48% re-captured as unit price")

    # --- X4 arithmetic-of-landed: the verbatim [81]. The client's own
    # $9,360 total must not capture as marketing.
    fin = _alder_fin(ctx, missing=["annual_principal_payment"])
    stage = ic._next_financials_stage(fin)
    if stage != "annual_principal_payment":
        return False, (f"setup(arithmetic): active stage is {stage!r}, "
                       f"need 'annual_principal_payment'")
    turn, fin_out, _d = _alder_turn(
        ctx,
        "The payments come to $9,360 a year, so if $2,600 is interest the "
        "principal part is about $6,760.",
        {"action": "edit_patch", "assistant_message": "",
         "patch": {"financials.annual_principal_payment": 6760}},
        fin,
        last="What is your best estimate of the annual principal you expect to repay?")
    m = str((turn or {}).get("assistant_message") or "")
    mkt = (fin_out or {}).get("marketing_total_year1")
    if not near(mkt, 6000.0) or "9,360" in m:
        fails.append(f"arithmetic: marketing = {mkt!r} (want 6,000 untouched)")

    # --- X5 count-of-persons: the verbatim [85]. A people-count must not
    # capture as capacity.
    #
    # THE FIXTURE TRAP: the stored period capacity is forced CLEAN (185)
    # first. At [85] in the live run the capacity was clean and the
    # mis-capture CREATED the 2. Leaving ALDER_OPS' stale 2 in place here
    # would let the old code skip the write as a restatement and go
    # vacuously green - the same fixture-bug class that made R05/R09 lie
    # green on the stub earlier.
    fin = _alder_fin(ctx, missing=["ar_balance"])
    stage = ic._next_financials_stage(fin)
    if stage != "ar_balance":
        return False, f"setup(count): active stage is {stage!r}, need 'ar_balance'"
    clean_ops = copy.deepcopy(ALDER_OPS)
    clean_ops["lob_models"][0]["products"][0]["units_per_period_capacity"] = 185.0
    turn, fin_out, _d = _alder_turn(
        ctx,
        "Hardly anything - people pay at the counter. The two designers "
        "have accounts and might owe us $2,000 between them at any time.",
        {"action": "edit_patch", "assistant_message": "",
         "patch": {"financials.ar_balance": 2000}},
        fin, ops=clean_ops,
        last="About how much do customers currently owe you for completed work?")
    m = str((turn or {}).get("assistant_message") or "")
    ar = (fin_out or {}).get("ar_balance")
    if "capacity" in m.lower() or not near(ar, 2000.0):
        fails.append(f"count-of-persons: ar = {ar!r}, capacity named in ack = "
                     f"{'capacity' in m.lower()}")

    # --- X6 POSITIVE invariant: real capacity statements STILL capture.
    for msg in ("I can take on 40 properties now.", "I do about 40 jobs a week."):
        turn, _fo, _d = _alder_turn(
            ctx, msg, PATCHLESS, _alder_fin(ctx),
            last="The wall: pricing and volume are the levers we can work.")
        m = str((turn or {}).get("assistant_message") or "")
        if "capacity" not in m.lower() or "40" not in m:
            fails.append(f"POSITIVE miss on {msg!r} - a real capacity "
                         f"statement stopped capturing")

    # --- X9 repair receipt: an extra applied non-stage field is named.
    fin = _alder_fin(ctx, missing=["cash_on_hand"])
    stage = ic._next_financials_stage(fin)
    if stage != "cash_on_hand":
        return False, f"setup(receipt): active stage is {stage!r}, need 'cash_on_hand'"
    turn, _fo, _d = _alder_turn(
        ctx, "Cash is $28,000. And put marketing back to $5,200 a year.",
        {"action": "edit_patch", "assistant_message": "",
         "patch": {"financials.cash_on_hand": 28000,
                   "financials.marketing_total_year1": 5200}},
        fin, last="About how much cash does the business have on hand?")
    m = str((turn or {}).get("assistant_message") or "")
    if "Also recorded" not in m or "5,200" not in m:
        fails.append("repair receipt: the extra applied field was not named "
                     "(a silent fix is invisible to the client)")

    return not fails, ("all five forms clear" if not fails
                       else "FAILED: " + "; ".join(fails))


def _r_compound_word_numbers(ctx):
    """CW-028 #4 (X7): 'one hundred and eighty-five' is 185, not the 85
    fragment. In the live run the leading 'one hundred and' was dropped and
    the app recorded capacity 85."""
    text = "My weekly capacity is one hundred and eighty-five checkouts."
    figs = list(ctx.ic._message_figures(text) or [])
    parsed_ok = any(near(f, 185.0) for f in figs) and not any(near(f, 85.0) for f in figs)

    # FIXTURE UPDATED for the universal engine (phase 4).
    #
    # This leg used to inherit ALDER_OPS, which stores week=185 beside
    # period=2. The engine makes that shape UNREPRESENTABLE - a weekly
    # cadence derives period := week at every pass - and with the stamp's
    # deeper placed-check, restating a value the row already holds is
    # correctly a no-op with nothing to land. The leg was asserting the
    # pre-engine world and would have reddened on a correct build.
    #
    # week/period = 100 keeps the leg's real target intact: the spoken
    # "one hundred and eighty-five" is now a GENUINE correction rather
    # than a restatement, so the word-number parse AND the attribution
    # are both still under test. The parse assert is unchanged.
    # Mirrors VS's same update to X7 in _redproof_cw028.py.
    ops = copy.deepcopy(ALDER_OPS)
    _prod = ops["lob_models"][0]["products"][0]
    _prod["units_per_week_capacity"] = 100.0
    _prod["units_per_period_capacity"] = 100.0

    turn, _fo, _d = _alder_turn(
        ctx, text, PATCHLESS, _alder_fin(ctx), ops=ops,
        last="Which is right - the revenue figure or one of the drivers?")
    m = str((turn or {}).get("assistant_message") or "")
    attributed_ok = ("185" in m) and ("capacity 85" not in m)
    return parsed_ok and attributed_ok, (
        f"_message_figures -> {figs!r} (want 185 present, 85 absent); "
        f"ack attributes 185 and never 'capacity 85' = {attributed_ok} "
        f"(fixture holds week/period=100 so 185 is a genuine correction, "
        f"not a restatement of an engine-unrepresentable row)")


def _r_owner_not_enumerated(ctx):
    """CW-028 #5 (X8): the rest-of-team question never names an
    owner-titled row alongside 'yourself'. Copy-only by design - the live
    rollup was correct - but it is a standing invitation to the CW-024
    double-count, so it is pinned."""
    q = str(ctx.ic._build_rest_of_team_payroll_question(
        "", people_json=copy.deepcopy(ALDER_PEOPLE)) or "")
    owner_named = "Marisol" in q
    staff_named = "Priya Raghunathan" in q
    return (not owner_named) and staff_named, (
        f"owner named as a third party = {owner_named} (must be False); "
        f"non-owner staff still enumerated = {staff_named} (must be True); "
        f"question: {q[:160]!r}")


# --- UNIVERSAL ENGINE (phases 1-4) --------------------------------------
# Fernhill Advisory: contract cadence, per=45 beside week=80. Mirrors
# _redproof_phase1_capacity.py (P1-P8), 0/8 on 909f66f -> 8/8 on the engine.
#
# ROUTING NOTE - why these do not call _derive_capacity_cells directly:
# that function does not exist at 909f66f, so a leg calling it would red
# with an AttributeError. That is a STRUCTURAL red, not a behavioural one,
# and structural reds are the false-proof class this gate exists to kill.
# The derivation is reached through _derive_ops_cells from the canonical
# sync, and _sync_financials_consult_persistence_state exists at BOTH
# commits - so these legs drive the sync and assert the derived cells.
FERN_OPS = {
    "business_naics_6": "541611",
    "lob_models": [{"lob_name": "Consulting", "products": [{
        "product_name": "unit", "unit_name": "consulting day",
        "unit_price": 2400.0, "unit_cadence": "contract",
        "units_per_week_capacity": 80.0,
        "units_per_period_capacity": 45.0,
        "operating_periods_per_year": 12.0,
        "utilization_rate": 0.65}]}],
}
FERN_PEOPLE = {
    "people": [
        {"full_name": "Odette Marchetti", "role_title": "Owner / Principal",
         "annual_wage": 180000.0, "wage_source": "client_override"},
        {"full_name": "Bram Sikorski", "role_title": "Senior Consultant",
         "annual_wage": 145000.0, "wage_source": "client_override"},
    ],
    "rest_of_team_payroll_year1": 296000.0,
}
FERN_YEAR1 = {"company_revenue_total_year1": 1497000.0}
FERN_WALL = (
    "Before I run the final checks, one thing doesn't add up: your stated "
    "annual revenue ($1,497,000) is more than your operation can physically "
    "produce even flat-out - at your stated capacity and prices, 100% "
    "utilization tops out around $1,296,000 a year."
)
_FERN_BASE_FIN = {
    "current_revenue": 1497000.0, "cogs_percent_of_revenue": 0.02,
    "cogs_basis": "ratio", "current_cogs": 29940.0,
    "cogs_total_year1": 29940.0, "current_payroll": 621000.0,
    "current_num_employees": 5, "marketing_total_year1": 24000.0,
    "monthly_rent_expense": 4100.0, "gna_total_year1": 60000.0,
    "capex_total_year1": 0.0, "initial_assets": 40000.0,
    "initial_lease": 0.0, "total_debt_outstanding": 0.0,
    "other_monthly_debt_payments": 0.0, "annual_interest_payment": 0.0,
    "annual_principal_payment": 0.0, "cash_on_hand": 90000.0,
    "ar_balance": 120000.0, "ap_balance": 30000.0,
    "inventory_balance": 0.0, "cash_strategy": "preserve_cash",
    "funding_preference": "debt",
    "_financials_revenue_intro_done": True,
    "_financials_marketing_stage_done": True,
}


def _fern_fin(ctx, missing=None):
    fin = ctx.ic._ensure_financials_stage_defaults(copy.deepcopy(_FERN_BASE_FIN))
    for st in list(getattr(ctx.ic, "_FINANCIALS_STAGE_ORDER", ())):
        spec = ctx.ic._financials_stage_spec(st)
        for f in (spec.get("completion_fields") or ()):
            if fin.get(f) is None:
                fin[f] = 1.0
    for k in (missing or []):
        fin.pop(k, None)
        fin.pop("_financials_stage_confirms", None)
    return fin


def _fern_turn(ctx, message, router, fin, ops, last="", **kw):
    return ctx.turn(message, RecordedRouter(router), fin=fin,
                    people=copy.deepcopy(FERN_PEOPLE), ops=ops,
                    last_assistant=last, year1=copy.deepcopy(FERN_YEAR1),
                    business_name="Fernhill Advisory", **kw)


def _canonical_pass(ctx, ops):
    """Drive the derivation the way the app does - through the canonical
    sync, which exists at both commits. Mutates ops in place."""
    ctx.ic._sync_financials_consult_persistence_state(
        financials_json=_fern_fin(ctx), financials_year1_json={},
        marketing_model_json={}, people_json=copy.deepcopy(FERN_PEOPLE),
        ops_json=ops)
    return ops


def _u_capacity_derivation(ctx):
    """P1+P2+P8: capacity is canonical-per-cadence at every canonical pass.
    Divergence between the twins is unrepresentable.

    The weekly case is the POSITIVE companion - it already held from
    8bfbbb6, so it is green on both sides. Without it a build that derived
    nothing at all could pass the non-weekly asserts by coincidence."""
    fails = []

    ops_w = {"lob_models": [{"products": [{
        "unit_cadence": "weekly", "units_per_week_capacity": 185.0,
        "units_per_period_capacity": 2.0, "operating_periods_per_year": 52.0}]}]}
    _canonical_pass(ctx, ops_w)
    w_per = product_field(ops_w, "units_per_period_capacity")
    if not near(w_per, 185.0, 0.01):
        fails.append(f"weekly per:=week gave {w_per!r}, want 185")

    ops_c = copy.deepcopy(FERN_OPS)
    _canonical_pass(ctx, ops_c)
    c_wk = product_field(ops_c, "units_per_week_capacity")
    want_wk = 45.0 * 12.0 / 52.0
    if not near(c_wk, want_wk, 0.01):
        fails.append(f"contract week derived {c_wk!r}, want {want_wk:.4f} "
                     f"(per*periods/52); at 909f66f it stays the stale 80")

    ops_a = {"lob_models": [{"products": [{
        "unit_cadence": "contract", "units_per_week_capacity": 12.0,
        "operating_periods_per_year": 12.0}]}]}
    _canonical_pass(ctx, ops_a)
    a_per = product_field(ops_a, "units_per_period_capacity")
    if not near(a_per, 52.0, 0.01):
        fails.append(f"adopt-once gave {a_per!r}, want 52 (a mirror-only "
                     f"legacy row must gain its canonical cell)")

    ops_m = {"lob_models": [{"products": [
        {"unit_cadence": "weekly", "units_per_week_capacity": 30.0,
         "units_per_period_capacity": 4.0, "operating_periods_per_year": 52.0},
        {"unit_cadence": "contract", "units_per_period_capacity": 10.0,
         "units_per_week_capacity": 99.0, "operating_periods_per_year": 12.0},
    ]}]}
    _canonical_pass(ctx, ops_m)
    rows = ops_m["lob_models"][0]["products"]
    if not near(rows[0].get("units_per_period_capacity"), 30.0, 0.01):
        fails.append(f"multi-product row 1 per = "
                     f"{rows[0].get('units_per_period_capacity')!r}, want 30")
    if not near(rows[1].get("units_per_week_capacity"), 10.0 * 12.0 / 52.0, 0.01):
        fails.append(f"multi-product row 2 week = "
                     f"{rows[1].get('units_per_week_capacity')!r}, want "
                     f"{10.0 * 12.0 / 52.0:.4f} - derivation must cover EVERY row")

    return not fails, ("all four derivation forms hold (weekly, contract, "
                       "adopt-once, multi-product)" if not fails
                       else "FAILED: " + "; ".join(fails))


def _u_fernhill_round_trip(ctx):
    """P3 - THE PERSISTENCE PROPERTY. write -> survive -> read back correct.

    This is the leg that matters most: a correction that receipts but does
    not survive to SQL is indistinguishable, to the client, from one that
    was never made. Three receipted corrections died on this seam.

    THE VACUOUS-GREEN TRAP, and how this leg defeats it: the landing is
    only real if it MUTATED THROUGH the ops object the handler was handed.
    So the leg passes its own object by reference (share_ops), and after
    the turn re-persists THAT SAME OBJECT the way the handler's caller
    does. Without that second persist the leg would read back the row the
    turn function itself wrote and pass on old code - green, and worthless.
    """
    fin = _fern_fin(ctx)
    stage = ctx.ic._next_financials_stage(fin)
    if stage is not None:
        return False, f"setup: active stage is {stage!r}, need the completed state"

    ops = copy.deepcopy(FERN_OPS)
    turn, fin_out, did = _fern_turn(
        ctx, "Capacity, 80.", PATCHLESS, fin, ops, last=FERN_WALL,
        share_ops=True, seed_ops=True)
    ctx.note_turn(turn)
    msg = str((turn or {}).get("assistant_message") or "")
    if "capacity" not in msg.lower() or "80" not in msg:
        return False, f"no landing receipt at all: {msg[:140]!r}"

    # THE LIVE SEAM: persist the harness's OWN reference, as the caller does.
    ctx.persist_ops(did, ops)

    _f, _p, db_ops = ctx.sections(did)
    per = product_field(db_ops, "units_per_period_capacity")
    if not near(per, 80.0, 1e-6):
        return False, (f"SQL read-back: units_per_period_capacity = {per!r}, "
                       f"want 80 - the landing did NOT survive the persist "
                       f"(the receipt said it landed; the database disagrees)")

    from client_intake_and_finmo.intake_coherence import section as sec
    t2, _fin3, _x = sec.gate_and_turn(
        ops_json=db_ops, people_json=copy.deepcopy(FERN_PEOPLE), market_json={},
        marketing_model_json={}, financials_json=dict(fin_out),
        financials_year1_json={}, user_text="")
    m2 = str((t2 or {}).get("assistant_message") or "")
    cleared = "doesn't add up" not in m2
    return cleared, (f"receipt landed, SQL read-back period = {per!r} (survived), "
                     f"and the next turn's conflict check cleared = {cleared} "
                     f"(if it re-fires, the corrected value never reached the gate)")


def _u_product_pattern_total(ctx):
    """P4: '4 people x 20 days = 80 ... that is the capacity number' lands
    the TOTAL, never one of the factors."""
    fin = _fern_fin(ctx)
    turn, _fo, did = _fern_turn(
        ctx,
        "My four billable people can each deliver about 20 billable days in "
        "a month, so the team can put out about 80 billable days a month. "
        "That is the capacity number.",
        PATCHLESS, fin, copy.deepcopy(FERN_OPS),
        last="Which of those stored numbers is wrong?", seed_ops=True)
    ctx.note_turn(turn)
    msg = str((turn or {}).get("assistant_message") or "")
    ok = ("80" in msg) and ("capacity 20" not in msg.lower())
    return ok, (f"ack must attribute the stated total 80 and never the "
                f"per-person factor 20 - contains '80' = {'80' in msg}, "
                f"contains 'capacity 20' = {'capacity 20' in msg.lower()}")


def _u_noop_never_receipts(ctx):
    """P5, REFIXTURED to the live door-echo shape (VS_NOTES U04 diagnosis).

    WHY THE FIRST FIXTURE WAS VACUOUS: it aimed at the capacity door, and
    on 909f66f the SMALL-FIGURE RESTATEMENT SKIP - which predates the mover
    - already suppressed capacity echoes before any receipt could fire. Old
    code was correctly silent there, so the leg could not go red. Silence
    for the wrong reason is not a proof.

    WHERE THE BUG ACTUALLY LIVED: the DOOR path. Fernhill [86] shipped
    "Recorded: total team payroll $621,000" against a row that already held
    621,000. The door receipted echoes even on current code; 9d2c41c
    extends the no-op rule to it (rider #4), so the baseline is 13fae7c -
    the last commit before that extension.

    TWO HALVES, and the second is what keeps the first honest:

      NEGATIVE (the pin) - a door patch restating the stored value ships no
        receipt, and leaves the stored field alone. RED at 13fae7c.

      POSITIVE (the liveness companion) - the SAME door with a genuine new
        value still lands it and still says so. Green on both commits by
        design. Without it, a build where the door never ran at all, or one
        that stopped acknowledging writes entirely, would sail through the
        negative half for a reason that has nothing to do with no-ops. This
        leg's whole claim is a DIFFERENCE between two door writes, so it
        has to drive both.
    """
    fin = _fern_fin(ctx)
    held = float(fin.get("current_payroll") or 0.0)
    if not near(held, 621000.0, 1.0):
        return False, (f"setup: the fixture holds current_payroll = {held!r}; "
                       f"an echo write needs the row to ALREADY hold 621,000")
    fails = []

    echo = {"action": "edit_patch", "assistant_message": "",
            "patch": {"people.total_team_payroll": 621000}}
    turn, fin_out, did = _fern_turn(
        ctx, "Total team payroll is $621,000.", echo, fin,
        copy.deepcopy(FERN_OPS),
        last="Which of those stored numbers is wrong?", seed_ops=True)
    msg = str((turn or {}).get("assistant_message") or "")
    fin_db, _p, _o = ctx.sections(did)
    after = fin_db.get("current_payroll")
    if after is None:
        after = (fin_out or {}).get("current_payroll")

    if not msg.strip():
        fails.append("the echo turn produced no assistant message at all - "
                     "silence by crash is not silence by rule")
    if "recorded" in msg.lower():
        fails.append(f"the echo RECEIPTED - ack: {msg[:140]!r}; the row already "
                     f"held 621,000, so nothing changed and nothing was recorded")
    if not near(after, 621000.0, 1.0):
        fails.append(f"the echo moved the stored field to {after!r} - a no-op "
                     f"must leave 621,000 exactly where it was")

    real = {"action": "edit_patch", "assistant_message": "",
            "patch": {"people.total_team_payroll": 655000}}
    turn2, fin_out2, did2 = _fern_turn(
        ctx, "Total team payroll is $655,000.", real, _fern_fin(ctx),
        copy.deepcopy(FERN_OPS),
        last="Which of those stored numbers is wrong?", seed_ops=True)
    msg2 = str((turn2 or {}).get("assistant_message") or "")
    fin_db2, _p2, _o2 = ctx.sections(did2)
    moved = fin_db2.get("current_payroll")
    if moved is None:
        moved = (fin_out2 or {}).get("current_payroll")
    if not near(moved, 655000.0, 1.0):
        fails.append(f"LIVENESS: a GENUINE door write left the stored field at "
                     f"{moved!r}, want 655,000 - the door is not running here, "
                     f"so the silence above proves nothing about no-ops")
    elif "655" not in msg2:
        fails.append(f"LIVENESS: a genuine door write landed but never said so "
                     f"- ack: {msg2[:140]!r}. A build that stopped acknowledging "
                     f"every write would pass the no-op half for free")

    return not fails, (
        "door echo (row already holds 621,000): silent, stored field untouched; "
        "a genuine write to 655,000 still lands and still acknowledges - the "
        "door is live and the no-op rule is what is doing the work"
        if not fails else "; ".join(fails))


def _u_pin_escalation(ctx):
    """P6: the operand message cannot repeat verbatim either. R21 pinned
    that hold #2 differs from #1; this pins that #3 differs again and
    escalates to offering the direct set, so a client who cannot answer the
    question still has a way out."""
    from client_intake_and_finmo.intake_coherence import section as sec

    ops = copy.deepcopy(FERN_OPS)
    fin = {"current_revenue": 1497000.0, "_financials_revenue_intro_done": True}
    msgs = []
    for _ in range(3):
        t, fin, _x = sec.gate_and_turn(
            ops_json=ops, people_json={}, market_json={},
            marketing_model_json={}, financials_json=dict(fin),
            financials_year1_json={}, user_text="hm.")
        msgs.append(str((t or {}).get("assistant_message") or ""))
    if "doesn't add up" not in msgs[0]:
        return False, f"setup: the hold did not fire on the first pass: {msgs[0][:120]!r}"
    distinct = len(set(msgs)) == 3
    escalated = "name the stored number" in msgs[2].lower()
    return distinct and escalated, (
        f"three holds produced {len(set(msgs))} distinct messages (want 3); "
        f"the third escalates to the direct set = {escalated} (at 909f66f the "
        f"operand message repeats verbatim from the second onward)")


# ---- GOAL ANCHOR (conversational-state audit #1, shipped 13fae7c) -------
#
# The 12-month goal question was the one genuinely dead-ended solicitation:
# every client answered it with their real ambition and the roadmap never
# consumed a word of it. VS's red-proof (_redproof_goal_anchor.py) is G1
# capture / G2 payload+copy / G3 end-to-end, 1/3 on 539fb17 -> 3/3.
#
# This leg deliberately does NOT mirror G2's direct call
# `roadmap_payload(client_goal=...)`. That kwarg does not exist at 539fb17,
# so the call would raise TypeError - a STRUCTURAL red, which proves only
# that a signature changed. The same property is reachable behaviourally
# through the real caller: walk the coherence gate to the roadmap with the
# milestone present, and again with it absent. On 539fb17 the walk runs
# fine and the copy simply never anchors. That is a behavioural red.
GOAL_ANSWER = ("I'd like to be full at 60 visits a week and actually pay "
               "myself properly. Right now I take what's left and some "
               "months that isn't much.")
GOAL_MILESTONE = {
    "description": "be full at 60 visits a week and actually pay myself properly",
    "timing": "Within the next 12 months",
}
GOAL_OPS = {
    "business_type": "Commercial cleaning services",
    "business_naics_6": "561720",
    "business_description_summary": (
        "Commercial office cleaning under recurring monthly contracts "
        "with night crews."),
    "lob_models": [{"lob_name": "Cleaning", "products": [{
        "product_name": "Monthly office contract", "unit_price": 1200.0,
        "units_per_period_capacity": 22.0,
        "operating_periods_per_year": 12.0, "utilization_rate": 0.8}]}],
}
GOAL_FIN = {
    "current_revenue": 253440.0, "baseline_payroll_year1": 260000.0,
    "current_payroll": 260000.0, "payroll_total_year1": 260000.0,
    "other_opex_absolute": 55000.0, "marketing_total_year1": 12000.0,
    "cogs_percent_of_revenue": 0.07, "monthly_rent_expense": 2500.0,
}


def _goal_walking_state(sec, fin, ops):
    """The stamped walking state one turn short of the corner collapse -
    lifted from the red-proof so the leg enters the same doorway."""
    state = {
        "margin_band_judgment": {
            "q11": {"low": 0.12, "high": 0.22},
            "gross_margin_floor_q11": 0.30,
            "fixed_cost_burden_max_q11": 0.90,
            "ni_margin_floor_q11": 0.02,
            "labor_intensity_class": "high",
            "labor_treatment": "all_labor_in_payroll_line",
        },
        "judged_growth": {"qoq_start": 0.05, "qoq_end": 0.02, "source": "test",
                          "year1_annual_growth": 0.2,
                          "mature_annual_growth": 0.08},
        "demand_response": {"evidence_level": "thin", "withheld": True,
                            "price_response": None, "marketing_response": None,
                            "volume_headroom": None, "notes": []},
        "essentials_response": {"evidence_level": "thin", "withheld": True,
                                "lines": {}, "notes": []},
        "status": "walking",
        "gap_open": 9000.0, "gap_initial": 12000.0,
        "round": {"key": "cost_structure"}, "rounds_done": [],
        "_lever_writes": {"marketing_total_year1": {"from": 23850.0,
                                                    "to": 12000.0}},
        "bounds": {
            "feasible_region_exists": True,
            "existing_lines": [{
                "lob": "Cleaning", "product": "Monthly office contract",
                "unit_price": 1200.0, "annual_units": 211.2,
                "price_multiplier_max": 1.01, "volume_multiplier_max": 1.01,
                "utilization_rate": 0.8}],
            "team": {"min_annual_payroll": 250000.0},
            "cogs_percent_of_revenue_min": 0.07,
            "marketing_floor_annual": 12000.0,
            "rent_monthly_min": 2500.0,
            "other_opex_annual_min": 55000.0,
        },
    }
    digest, _ = sec._compute_band_identity_digest(
        state, ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=fin)
    state["digest_hash"] = digest
    return state


def _goal_walk(sec, ops):
    """Drive the real gate to the roadmap. -> (status, message, setup_note)"""
    fin = dict(GOAL_FIN)
    fin["_coherence"] = _goal_walking_state(sec, fin, ops)
    _t1, fin1, _x = sec.gate_and_turn(
        ops_json=ops, people_json={}, market_json={}, marketing_model_json={},
        financials_json=fin, financials_year1_json={},
        user_text="ok, what's next?")
    st1 = (fin1 or {}).get("_coherence") or {}
    if not st1.get("corner_collapse_hold"):
        return None, "", (f"the walk never reached the corner collapse "
                          f"(status = {st1.get('status')!r}) - the fixture no "
                          f"longer enters the roadmap doorway, so this run "
                          f"says nothing about the goal anchor")
    t2, fin2, _y = sec.gate_and_turn(
        ops_json=ops, people_json={}, market_json={}, marketing_model_json={},
        financials_json=dict(fin1), financials_year1_json={},
        user_text="those figures are all correct, that's really my payroll")
    st2 = (fin2 or {}).get("_coherence") or {}
    return (st2.get("status"), str((t2 or {}).get("assistant_message") or ""),
            "")


def _r_goal_anchor(ctx):
    """The roadmap builds toward the client's OWN stated 12-month goal.

    Three parts, one claim:

      CAPTURE (companion, green on both commits) - the deterministic
        fallback still extracts the goal from the live Brightline phrasing.
        The capture pipeline is load-bearing for the anchor and predates
        it; pinning it here means a future change that guts the capture
        turns this leg red instead of quietly emptying the roadmap.

      ANCHOR (the pin) - with the milestone captured on ops, the rendered
        roadmap names the client's goal in their own words. RED at 539fb17,
        where the walk completes and the copy simply never mentions it.

      RESTRAINT (the pin's other half) - with NO milestone, the copy is
        untouched: no anchor line at all. A build that always emitted the
        sentence would pass the ANCHOR half while saying something the
        client never said.
    """
    from client_intake_and_finmo.intake_coherence import section as sec

    fails = []

    cap = getattr(ctx.ic, "_fallback_ops_pending_milestone_from_text", None)
    if cap is None:
        fails.append("the capture fallback _fallback_ops_pending_milestone_"
                     "from_text is gone - the anchor has nothing to anchor to")
    else:
        m = cap(GOAL_ANSWER) or {}
        desc = str((m or {}).get("description") or "")
        timing = str((m or {}).get("timing") or "").strip()
        if "60 visits" not in desc or not timing:
            fails.append(f"CAPTURE: the live goal answer extracted to "
                         f"description={desc[:80]!r} timing={timing!r} - want "
                         f"the client's own '60 visits' and a timing")

    ops = copy.deepcopy(GOAL_OPS)
    ops["milestones"] = [copy.deepcopy(GOAL_MILESTONE)]
    status, msg, note = _goal_walk(sec, ops)
    if note:
        return False, "SETUP: " + note
    if status != "roadmap":
        return False, (f"SETUP: the walk ended at status {status!r}, not "
                       f"'roadmap' - the leg never reached the copy it judges")
    if "You told me your goal" not in msg:
        fails.append(f"ANCHOR: the roadmap never names the client's goal - "
                     f"msg: {msg[:200]!r} (at 539fb17 the paths are framed as "
                     f"distance with nothing to be distant FROM)")
    elif "60 visits" not in msg:
        fails.append(f"ANCHOR: the roadmap anchors, but not to the client's "
                     f"own words - '60 visits' is absent from: {msg[:200]!r}")

    bare = copy.deepcopy(GOAL_OPS)
    bare.pop("milestones", None)
    status_b, msg_b, note_b = _goal_walk(sec, bare)
    if note_b:
        fails.append("RESTRAINT: " + note_b)
    elif "You told me your goal" in msg_b:
        fails.append(f"RESTRAINT: with no goal captured the copy still claims "
                     f"the client stated one - msg: {msg_b[:200]!r}")

    return not fails, (
        "capture holds, the roadmap names the client's own goal ('60 visits'), "
        "and with no goal captured the copy stays untouched"
        if not fails else "; ".join(fails))


# ---- the COGS legs, re-fixtured off their crash-reds ---------------------
#
# All three used to call _resolve_cogs_baseline_or_raise with TODAY's
# signature. The fix (dead-estimator deletion) removed a REQUIRED keyword, so
# on every pre-fix baseline the call raised
#     TypeError: missing 1 required keyword-only argument:
#                'estimate_cogs_percent_from_context'
# and the leg died before resolving anything. prove() scored that exit code 1
# as a clean red for months. It is not one: it proves a parameter list moved.
#
# ctx.cogs_baseline() bridges the call shape with the app's own estimator, so
# each leg now reaches its assertion at BOTH commits and the red is whatever
# the resolver actually returned. Verified against baseline source first:
#   613a19a  cogs_fit_band = 0 occurrences  -> R13's property genuinely absent
#   7b9f481  cogs_fit_band = 4 occurrences  -> the covered path ALREADY had a
#            materials-only band, which is why I10's crash-red was suspected
#            of hiding a green-on-its-own-baseline. I10 now carries an
#            assertion that discriminates on the covered path, and if it still
#            comes back GREEN at 7b9f481 the honest answer is a different
#            baseline - see the note on its registry row.
def _r_fitted_cogs_covered(ctx):
    """Fitted COGS on a COVERED NAICS proposes MATERIALS-ONLY with a
    band - never the ~88% cohort cost-of-revenue."""
    ops = copy.deepcopy(OPS)
    ops["business_naics_6"] = "561720"
    ops["business_type"] = "Commercial janitorial services"
    baseline, adapt = ctx.cogs_baseline(ops, 384000.0)
    pct = float(baseline.get("baseline_cogs_percent") or 0.0)
    band = baseline.get("cogs_fit_band")
    cohort = baseline.get("cogs_fit_cohort_cost_of_revenue")
    ok = (0.005 <= pct <= 0.20) and isinstance(band, (list, tuple)) and len(band) == 2 \
        and band[0] < band[1] <= 0.30
    return ok, (f"proposed cogs pct = {pct:.4f}, band = {band!r}, cohort "
                f"cost-of-revenue seen = {cohort!r} (materials-only, not the "
                f"cohort; at 613a19a there is no band at all) [{adapt}]")


def _r_fitted_cogs_fallback(ctx):
    """Fitted COGS on an UNCOVERED NAICS still yields a band - the dead
    estimator must not come back.

    This is the leg the signature change is really about: at 7b9f481 an
    uncovered NAICS falls past the fit judge into the plain estimator, which
    returns a bare percent and NO band. Bridged, that is a behavioural red -
    band is None - instead of a TypeError."""
    ops = copy.deepcopy(OPS)
    ops["business_naics_6"] = "999999"
    baseline, adapt = ctx.cogs_baseline(ops, 175000.0)
    pct = float(baseline.get("baseline_cogs_percent") or 0.0)
    band = baseline.get("cogs_fit_band")
    ok = 0.0 < pct < 1.0 and isinstance(band, (list, tuple)) and len(band) == 2 \
        and band[0] < band[1]
    return ok, (f"uncovered NAICS -> pct = {pct:.4f}, band = {band!r} "
                f"(a band is required; the dead estimator returns a bare "
                f"percent with band=None) [{adapt}]")


# =========================================================================
# WS1/WS2 - per-line COGS, the confidence gate, the retention stamp
# =========================================================================
#
# THE SHAPE OF THE MODEL INPUT. Revenue lives in sections.revenue as one row
# per (slot, driver): Capacity, Unit Price, Utilization, and - new in
# c77094a, multi-line drafts only - COGS %. Line revenue at period i is
# Capacity[i] * Unit Price[i] * Utilization[i]. The blend is the single
# expenses row "Cost of Goods Sold". Both facts are read off the raw JSON by
# _reconcile_per_line_cogs_rows, so the legs below compute Sigma the same way
# the app does, from the same rows, with no private helper in between.
import hashlib
import re

_VALS = [0.0] * 21


def _row(lob, product, driver, value, periods=21):
    return {"lob": lob, "product": product,
            "revenue_slot_key": f"{lob}::{product}",
            "driver": driver, "values": [value] * periods}


def _exp_row(label, value, periods=21):
    return {"section": "expenses", "label": label, "values": [value] * periods}


# Sunny-shape: ONE line, no COGS % row anywhere. This is five of six real
# businesses and it must not move a byte.
SINGLE_LINE_MIJ = {
    "start_date": "2026-01-01",
    "business_name": "Sunny Lane Services",
    "sections": {
        "revenue": [
            _row("Services", "Standard visit", "Capacity", 240.0),
            _row("Services", "Standard visit", "Unit Price", 95.0),
            _row("Services", "Standard visit", "Utilization", 0.8),
        ],
        "expenses": [
            _exp_row("Cost of Goods Sold", 0.18),
            _exp_row("Payroll", 42000.0),
        ],
    },
}

# Thistledown-shape: TWO lines, retail materials-heavy beside a service line.
# Blend is authored as the revenue-weighted mean of the two, which is the
# invariant R26 pins.
_T_RETAIL_REV = 300.0 * 60.0 * 0.7      # 12,600
_T_SERVICE_REV = 120.0 * 85.0 * 0.6     #  6,120
_T_BLEND = round((_T_RETAIL_REV * 0.52 + _T_SERVICE_REV * 0.22)
                 / (_T_RETAIL_REV + _T_SERVICE_REV), 6)

TWO_LINE_MIJ = {
    "start_date": "2026-01-01",
    "business_name": "Thistledown Cycles",
    "sections": {
        "revenue": [
            _row("Retail", "Bicycle", "Capacity", 300.0),
            _row("Retail", "Bicycle", "Unit Price", 60.0),
            _row("Retail", "Bicycle", "Utilization", 0.7),
            _row("Retail", "Bicycle", "COGS %", 0.52),
            _row("Workshop", "Service hour", "Capacity", 120.0),
            _row("Workshop", "Service hour", "Unit Price", 85.0),
            _row("Workshop", "Service hour", "Utilization", 0.6),
            _row("Workshop", "Service hour", "COGS %", 0.22),
        ],
        "expenses": [
            _exp_row("Cost of Goods Sold", _T_BLEND),
            _exp_row("Payroll", 42000.0),
        ],
    },
}


def _mij_sha(mij):
    """A stable hash of the SERIALIZED model input - sorted keys, fixed
    separators, so the digest is over content and never over dict order."""
    blob = json.dumps(mij, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _sections(mij):
    return (mij.get("sections") or {}) if isinstance(mij, dict) else {}


def _slot_rows(mij):
    """-> {slot: {driver: row}} straight off the JSON."""
    out = {}
    for row in _sections(mij).get("revenue") or []:
        if not isinstance(row, dict):
            continue
        slot = (str(row.get("revenue_slot_key") or "").strip()
                or f"{row.get('lob')}::{row.get('product')}")
        out.setdefault(slot, {})[str(row.get("driver") or "").strip()] = row
    return out


def _at(row, i):
    vals = (row or {}).get("values") or []
    try:
        return max(0.0, float(vals[i] or 0.0))
    except (IndexError, TypeError, ValueError):
        return 0.0


def _blend_row(mij):
    for row in _sections(mij).get("expenses") or []:
        if isinstance(row, dict) and str(row.get("label") or "").strip() == "Cost of Goods Sold":
            return row
    return None


def _sigma_and_blend(mij, i):
    """-> (sigma_cogs, total_revenue, blend_pct) at period i, computed off
    the raw rows exactly as _reconcile_per_line_cogs_rows does."""
    sigma = total = 0.0
    for _slot, drivers in _slot_rows(mij).items():
        line_rev = (_at(drivers.get("Capacity"), i)
                    * _at(drivers.get("Unit Price"), i)
                    * _at(drivers.get("Utilization"), i))
        total += line_rev
        sigma += line_rev * _at(drivers.get("COGS %"), i)
    return sigma, total, _at(_blend_row(mij), i)


def _engine_cogs(ctx, mij, i):
    """The quarter's modelled COGS, read the way THIS build models it.

    per_line_cogs_amount() is new in c77094a; where it is absent the engine
    has no per-line notion at all and COGS is revenue x the blend - the exact
    legacy formula. Reading it through getattr keeps the baseline run
    BEHAVIOURAL: the leg observes what the old engine computes instead of
    dying on the attribute."""
    from financial_model_engine.model_inputs import FinancialModelInputs

    book = FinancialModelInputs.from_model_input_json(copy.deepcopy(mij))
    q = book.quarter(i + 1)
    per_line = getattr(q, "per_line_cogs_amount", None)
    if callable(per_line):
        amount = per_line()
        if amount is not None:
            return float(amount), "per-line sum"
    return float(q.revenue) * float(getattr(q.expenses, "cogs_percent", 0.0) or 0.0), \
        "revenue x blend (legacy single-blend path)"


def _r_per_line_sigma(ctx):
    """R26 - THE ONE-LEVER LAW. The blend IS the lines, and the blend LEADS.

    The first fixture moved a single line's percent and expected COGS to
    follow. It didn't - the engine snapped the line back to the blend. That
    was the app being RIGHT: lines FOLLOW the blended lever, they never lead
    it. The assertion was fighting the law instead of pinning it.

    The payload also used to be a hand-written model_input_json, which is why
    it sat outside the shared construction path and missed every payload fix
    landed for R31/R32. It now goes through ctx.multi_line_payload() - the
    same production builder, the same frozen inputs, the same consistent
    ppe/initial_assets pair - with ops carrying cogs_percent_of_line_revenue
    on every product, which is what makes the per-line rows exist at all.

      IDENTITY - after the door, Sigma(line_rev x line_pct) == total x blend
        at every period. The invariant proper.

      CASCADE (the discriminator) - move the blend x1.25 and run the door
        again: every line percent scales by the SAME multiplier and Sigma
        tracks the new blend. On a single-blend build the door leaves the
        line rows untouched, so Sigma keeps its OLD value while the blend has
        moved - two numbers that no longer agree. Behavioural, and no crash,
        because the door is present at both commits.
    """
    from client_intake_and_finmo import finmo_bridge

    mij, _finmo, note = ctx.multi_line_payload()
    if mij is None:
        return False, f"SETUP: {note}"

    rows = _slot_rows(mij)
    cogs_rows = [d for d in rows.values() if d.get("COGS %")]
    if len(cogs_rows) < 2:
        return False, (
            f"SETUP: the builder emitted {len(cogs_rows)} COGS % rows for a "
            f"two-line business (want 2) - per-line is INACTIVE, so there is "
            f"no Sigma to check. {note}")

    fails = []
    for i in (0, 5, 20):
        sigma, total, blend = _sigma_and_blend(mij, i)
        if total <= 0:
            continue
        want = total * blend
        if abs(sigma - want) > max(0.005 * max(sigma, want), 1e-9):
            fails.append(f"period {i}: Sigma(line_rev x line_pct) = {sigma:,.2f} "
                         f"but total x blend = {want:,.2f} (>0.5% apart)")

    before = {slot: _at(d.get("COGS %"), 0) for slot, d in rows.items()
              if d.get("COGS %")}
    moved = copy.deepcopy(mij)
    blend_row = _blend_row(moved)
    if blend_row is None:
        return False, "SETUP: no 'Cost of Goods Sold' expense row to move"
    target = round(_at(blend_row, 0) * 1.25, 6)
    blend_row["values"] = [target] * len(blend_row["values"])
    moved = finmo_bridge.apply_derived_driver_policies_to_model_input(moved)

    after = {slot: _at(d.get("COGS %"), 0) for slot, d in _slot_rows(moved).items()
             if d.get("COGS %")}
    ratios = {slot: (after[slot] / before[slot])
              for slot in before if before[slot] > 0 and slot in after}
    if len(ratios) < 2:
        fails.append(f"lost the lines through the door: {before!r} -> {after!r}")
    else:
        spread = max(ratios.values()) - min(ratios.values())
        if spread > 1e-9:
            fails.append(f"CASCADE: the lines scaled by DIFFERENT multipliers "
                         f"{ratios!r} (spread {spread:.2e}) - one lever means "
                         f"one multiplier")
        if abs(min(ratios.values()) - 1.25) > 1e-6:
            fails.append(f"CASCADE: the blend moved x1.25 but the lines moved "
                         f"x{min(ratios.values()):.6f} - on a single-blend "
                         f"build the door never touches the line rows, so the "
                         f"lines and the blend stop agreeing")
    sigma2, total2, blend2 = _sigma_and_blend(moved, 0)
    if abs(sigma2 - total2 * blend2) > max(0.005 * sigma2, 1e-9):
        fails.append(f"after the lever move Sigma = {sigma2:,.2f} but total x "
                     f"blend = {total2 * blend2:,.2f} - the blend diverged "
                     f"from the lines it is supposed to summarise")

    return not fails, (
        f"{len(cogs_rows)} per-line COGS rows; Sigma == total x blend at "
        f"periods 0/5/20; the blend x1.25 cascaded to every line by one "
        f"multiplier {sorted(set(round(v, 9) for v in (ratios or {}).values()))!r} "
        f"and Sigma tracked to {sigma2:,.2f}. {note}"
        if not fails else "; ".join(fails))


def _r_single_line_unchanged(ctx):
    """R31 - THE NEGATIVE CONTROL, on the boundary VS actually proved.

    Five of six businesses are single-line. Per-line COGS must not move them.
    VS's SHAs hash the PERSISTED planning_run_checkpoints columns, so this
    rebuilds those payloads through the production constructors - all present
    at BOTH commits, so each digest is computed by the tree under test:

        build_python_model_input_json(...)
          -> apply_derived_driver_policies_to_model_input(...)
          -> canonical json.dumps(sort_keys, (",",":")) -> sha256
        build_python_finmo_json(model_input_json=...)  -> same

    HONEST LIMIT: VS's script hashes the checkpoint AFTER the solver, via a
    live :5050 run. The gate has no server, so this covers build + derived
    policies and NOT the solver stage. The two instruments are
    complementary; neither replaces the other.
    """
    import json as _json

    # THE CONTRACT LADDER, ended in one move. The validator rejected
    # forecast_starting_ppe_missing, then capex_depreciation_maintenance_rate_
    # invalid - each run surfacing the next missing kwarg, each time honestly
    # UNEARNED (identical crash both sides, so nothing was measured, and the
    # harness said so rather than lying PROVEN). single_line_payloads() now
    # carries the WHOLE proven payload from the committed reference, so the
    # shape is complete by construction instead of by subtraction from the
    # last error.
    draft, mij, finmo, ppe_src = ctx.single_line_payloads()
    if not draft:
        # The input is a committed fixture now, so "no draft" no longer means
        # an empty table - it means the fixture would not serve, and the note
        # names which way (unimportable app package, renamed loader).
        return False, f"SETUP: {ppe_src}"
    if mij is None or finmo is None:
        # ANCHOR-UNFROZEN / ANCHOR-LEAK / NONDETERMINISTIC. Deliberately NOT
        # hashed: a digest that is not a pure function of its inputs would
        # pass for months and then produce a top-billed false DRIFT, which is
        # the one false alarm that costs the gate its credibility.
        return False, f"SETUP: {ppe_src}"
    lines = sum(len((lob or {}).get("products") or [])
                for lob in (draft["ops"].get("lob_models") or []))
    if lines != 1:
        return False, (f"SETUP: draft {draft['id'][:8]} carries {lines} product "
                       f"lines - this control is only meaningful on a "
                       f"single-line business")

    def _canon(payload):
        blob = _json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    fails = []
    rows = _sections(mij).get("revenue") or []
    drivers = {str(r.get("driver") or "").strip() for r in rows if isinstance(r, dict)}
    if "COGS %" in drivers:
        fails.append("a COGS % row was emitted for a SINGLE-line draft - the "
                     "all-or-nothing guard let a one-line business into the "
                     "per-line path")
    if _blend_row(mij) is None:
        fails.append("the legacy single 'Cost of Goods Sold' row is gone - the "
                     "one-COGS-row layout must be preserved exactly")
    if len(rows) < 3:
        fails.append(f"only {len(rows)} revenue rows - too thin to be hashing "
                     f"anything meaningful")
    if not isinstance(finmo, dict) or len(finmo) < 3:
        fails.append(f"the finmo payload is {type(finmo).__name__} with "
                     f"{len(finmo or {})} keys - a hash over a stub matches "
                     f"itself and proves nothing")

    mi_sha, fin_sha = _canon(mij), _canon(finmo)
    # The INPUT goes on the wire too. Both sides pick their draft by the same
    # deterministic ladder, but they pick it in separate processes - so this
    # is what turns "the two sides hashed different businesses" from an
    # unexplained output move into a DRIFT that names single_line_input.
    print(f"GOLDEN-SHA single_line_input {ctx.draft_input_sha}")
    print(f"GOLDEN-SHA model_input {mi_sha}")
    print(f"GOLDEN-SHA finmo {fin_sha}")
    return not fails, (
        f"single-line draft {draft['id'][:8]}: {len(rows)} revenue rows, zero "
        f"COGS % rows, legacy blend row intact; {ppe_src}; "
        f"model_input={mi_sha[:12]} finmo={fin_sha[:12]} (build + derived "
        f"policies; the SOLVER stage is NOT reproduced here - VS's live-run "
        f"script covers that)" if not fails else "; ".join(fails))


def _r_workbook_formula_grid(ctx):
    """R32 - the WORKBOOK formula grid, the surface neither VS SHA covers.

    finmo_sheet.py moved 45 lines in c77094a and neither MODEL_INPUT_SHA nor
    FINMO_SHA looks at it. Hashing .xlsx bytes would false-DRIFT every run
    (zip metadata, timestamps), so this hashes the FORMULA GRID - sheet ->
    row label -> formula strings, sorted.

    RE-POINTED after the first real run: the entry point is the in-memory
    BUILDER, workbook_builder.build_client_financial_model_workbook over a
    DraftWorkbookData from data.draft_data_from_row - not the disk exporter.
    The builder's grid is deterministic; the exporter's bytes are not.
    """
    from client_statements_output_excel import data as wbdata
    from client_statements_output_excel import workbook_builder

    grid = ctx.workbook_formula_grid(
        builder=workbook_builder.build_client_financial_model_workbook,
        from_row=wbdata.draft_data_from_row)
    if not grid:
        # Never hashed on a gap. The splitter in workbook_formula_grid says
        # whether the BUILD or the EXTRACTION failed, and that string is the
        # whole point - a leg that cannot name its own gap costs a full
        # prove cycle to diagnose.
        return False, (f"SETUP: no formula grid - "
                       f"{getattr(ctx, 'grid_gap', '') or 'the builder rendered nothing'}")
    cells = sum(len(v) for rows in grid.values() for v in rows.values())
    if cells < 20:
        return False, (f"only {cells} formulas across {len(grid)} sheets - too "
                       f"thin to pin; a near-empty grid hashes stably and "
                       f"proves nothing")
    blob = json.dumps(grid, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    # Same reason as R31: the model-input side of this workbook comes from a
    # draft chosen at runtime, so its identity is hashed beside the output.
    print(f"GOLDEN-SHA single_line_input {ctx.draft_input_sha}")
    print(f"GOLDEN-SHA workbook_formulas {digest}")

    # SCOPED TO FINMO (round 7). The label 'Cost of Goods Sold' legitimately
    # appears on THREE sheets, and counting it across the whole grid made the
    # leg red on a correct build:
    #   [Model Inputs] row 12 - the DRIVER row, =SUM(D12:G12) per year;
    #   [FINMO]        row  9 - the P&L row, the one under test;
    #   [Audit Source] row  8 - a label with no formulas, never in the grid.
    # The P&L sheet is where the per-line work would show, so that is where
    # the single-line shape is pinned.
    finmo_rows = grid.get("FINMO") or {}
    if not finmo_rows:
        return False, (f"SETUP: no FINMO sheet in the grid - the P&L sheet is "
                       f"where the COGS row lives; sheets built: "
                       f"{sorted(grid)!r}")
    cogs_rows = {lbl: f for lbl, f in finmo_rows.items()
                 if "cost of goods sold" in str(lbl).lower()}
    per_line = {lbl for lbl in cogs_rows if " - " in str(lbl)}
    period_rx = re.compile(r"^=[A-Z]+\d+\*'Model Inputs'!\$?[A-Z]+\$?(\d+)$")

    fails = []
    if per_line:
        fails.append(f"per-line COGS rows on a SINGLE-line workbook: "
                     f"{sorted(per_line)!r} - the all-or-nothing guard let a "
                     f"one-line business into the per-line layout")
    if len(cogs_rows) != 1:
        fails.append(f"FINMO carries {len(cogs_rows)} 'Cost of Goods Sold' "
                     f"rows {sorted(cogs_rows)!r} - a single-line workbook "
                     f"keeps exactly ONE")
    driver_rows, periods, rollups = set(), 0, 0
    if len(cogs_rows) == 1:
        formulas = list(cogs_rows.values())[0]
        odd = []
        for f in formulas:
            m = period_rx.match(f)
            if m:
                periods += 1
                driver_rows.add(m.group(1))
            elif f.startswith("=SUM("):
                rollups += 1
            else:
                odd.append(f)
        if odd:
            fails.append(f"{len(odd)} COGS formulas are neither the legacy "
                         f"=<revenue cell>*'Model Inputs'!<cell> shape nor an "
                         f"annual =SUM rollup: {odd[:3]!r}")
        if periods < 8:
            fails.append(f"only {periods} per-period COGS formulas - too thin "
                         f"to be pinning a real forecast grid")
        if len(driver_rows) > 1:
            fails.append(f"the COGS row is driven by {len(driver_rows)} "
                         f"different Model Inputs rows {sorted(driver_rows)!r} "
                         f"- single-line COGS reads ONE blend driver")
    prov = getattr(ctx, "artifact_provenance", {}) or {}
    return not fails, (
        f"{cells} formulas across {len(grid)} sheets; FINMO carries exactly "
        f"one 'Cost of Goods Sold' row - {periods} per-period cells of the "
        f"legacy =<revenue cell>*'Model Inputs'!<row "
        f"{sorted(driver_rows)[0] if driver_rows else '?'}> shape plus "
        f"{rollups} annual =SUM rollups, zero per-line rows; grid sha "
        f"{digest[:12]}; run artifacts frozen from draft "
        f"{str(prov.get('draft_id') or '?')[:8]} stage "
        f"{prov.get('stage') or '?'}; model inputs from "
        f"{getattr(ctx, 'draft_source', '') or 'an unnamed draft'}"
        if not fails else "; ".join(fails))


def _r_per_line_proposal(ctx):
    """R28 (Thistledown #138) - a two-line business gets TWO proposals.

    Same call at both commits. At 9d2c41c it comes back with one blended
    percent and no cogs_per_line key at all - the retail line and the
    workshop line are quoted the same materials cost, which is the misfit
    the client sees."""
    ops = copy.deepcopy(OPS)
    ops["business_naics_6"] = "441222"
    ops["business_type"] = "Bicycle retail and repair"
    ops["lob_models"] = [
        {"lob_name": "Retail", "products": [{
            "product_name": "Bicycle", "unit_name": "bicycle",
            "unit_price": 60.0, "unit_cadence": "unit",
            "units_per_period_capacity": 300.0,
            "operating_periods_per_year": 12.0, "utilization_rate": 0.7}]},
        {"lob_name": "Workshop", "products": [{
            "product_name": "Service hour", "unit_name": "service hour",
            "unit_price": 85.0, "unit_cadence": "hour",
            "units_per_period_capacity": 120.0,
            "operating_periods_per_year": 12.0, "utilization_rate": 0.6}]},
    ]
    baseline, adapt = ctx.cogs_baseline(ops, 224640.0)
    per_line = baseline.get("cogs_per_line")
    if not isinstance(per_line, list) or len(per_line) < 2:
        return False, (
            f"cogs_per_line = {per_line!r} - a two-line business got a single "
            f"blended proposal ({baseline.get('baseline_cogs_percent')!r}); the "
            f"retail line and the service line are quoted the same materials "
            f"cost [{adapt}]")
    pcts = {str(item.get("line_name") or item.get("product_name") or ""):
            float(item.get("cogs_percent") or 0.0) for item in per_line}
    retail = next((v for k, v in pcts.items() if "bicycle" in k.lower()
                   or "retail" in k.lower()), None)
    service = next((v for k, v in pcts.items() if "service" in k.lower()
                    or "workshop" in k.lower()), None)
    if retail is None or service is None:
        return False, f"per-line proposals did not name both lines: {pcts!r}"
    return retail > service, (
        f"two lines, two percents: {pcts!r} - retail materials ({retail:.4f}) "
        f"must exceed service ({service:.4f}); blend "
        f"{baseline.get('baseline_cogs_percent')!r} [{adapt}]")


def _r_price_stamps_retention(ctx):
    """R30 (WS2) - a price change stamps the retention frame.

    Pinned at the FORWARD-MOVE door, a module-level function at both commits.
    The edit_patch door's stamp lives inside post_intake_consult_handler and
    is not reachable from this surface - see the registry note.

    Negative half: a NON-price move through the same door must NOT stamp, or
    the frame becomes noise and every turn asks about retention.
    """
    from client_intake_and_finmo.intake_coherence import section as sec

    def _fire(key, value, message):
        fin = ctx.completed_fin()
        ops = copy.deepcopy(OPS)
        shared = {"operating_model": ops,
                  "people_capability": copy.deepcopy(PEOPLE)}
        out, _adapt = call_compat(
            ctx.ic._apply_forward_move,
            move={"key": key, "value": value, "label": "that line"},
            stage_shared_context=shared,
            next_financials=fin,
            financials_year1_json=ctx.assembled_year1(fin, ops=ops),
            conn=ctx.conn,
            intake_context={"draft_id": ctx.fresh_draft(fin=fin, ops=ops,
                                                        people=PEOPLE)},
            user_message=message,
            last_assistant="Which of those stored numbers is wrong?")
        next_fin = out[0] if isinstance(out, tuple) else out
        return (sec.get_state(next_fin or {}) or {}).get("retention_pending")

    fails = []
    priced = _fire("ops.unit_price", 650.0, "My unit price is now 650.")
    if not isinstance(priced, dict):
        fails.append(
            f"a price change through the forward-move door left "
            f"retention_pending = {priced!r} - no frame, so a client who "
            f"volunteers 'I'd keep 85%' has nothing to consume it and "
            f"utilization never moves")
    else:
        used = priced.get("retained_used")
        if not near(used, 1.0, 1e-9):
            fails.append(f"the frame stamped retained_used = {used!r}, want 1.0 "
                         f"- the consumer scales FROM this, so a wrong anchor "
                         f"silently rescales the whole plan")
        if not (priced.get("prices") or []):
            fails.append("the frame carries no prices - the question cannot "
                         "name what changed")

    other = _fire("financials.marketing_total_year1", 2400.0,
                  "Marketing is really $2,400 a year.")
    if isinstance(other, dict):
        fails.append("a NON-price move stamped the retention frame too - every "
                     "turn would end by asking about customer retention")

    return not fails, (
        f"price move -> frame stamped {priced!r}; non-price move -> {other!r} "
        f"(must be None)" if not fails else "; ".join(fails))


def _r_per_line_lockstep(ctx):
    """R27 - the blend is the ONE COGS lever; when it moves, every line
    percent scales by the SAME multiplier and Sigma tracks the new blend.

    Declared STRUCTURAL-ABSENCE: both the reconcile and the scaler are new
    in c77094a, so this asserts a property that has no baseline seam. It
    guards the current build; it does not prove the broken side.
    """
    mij = copy.deepcopy(TWO_LINE_MIJ)
    before = {slot: _at(d.get("COGS %"), 0) for slot, d in _slot_rows(mij).items()}
    blend = _blend_row(mij)
    target = round(_at(blend, 0) * 1.25, 6)
    blend["values"] = [target] * len(blend["values"])

    from client_intake_and_finmo import finmo_bridge

    finmo_bridge._reconcile_per_line_cogs_rows(mij)

    after = {slot: _at(d.get("COGS %"), 0) for slot, d in _slot_rows(mij).items()}
    ratios = {slot: (after[slot] / before[slot]) for slot in before if before[slot]}
    if len(ratios) < 2:
        return False, f"fixture lost its lines: before={before!r} after={after!r}"
    spread = max(ratios.values()) - min(ratios.values())
    sigma, total, new_blend = _sigma_and_blend(mij, 0)
    tracks = abs(sigma - total * new_blend) <= max(0.005 * sigma, 1e-9)
    ok = spread <= 1e-12 and tracks and near(new_blend, target, 1e-9)
    return ok, (f"blend {target:.6f}: line ratios {ratios!r} (spread "
                f"{spread:.2e}, must be one multiplier); Sigma {sigma:,.2f} "
                f"tracks total x blend {total * new_blend:,.2f} = {tracks}")


def _r_line_split_confidence(ctx):
    """R29 (WS1a) - the consultant turn carries the split judgment.

    RE-POINTED after the first real run. The probe read
    api_handlers.intake_consult, which names the field once in a key list and
    carries no enum at all - so it found a stray token and reported a
    capability missing that is fully present. The vocabulary lives in
    client_intake_and_finmo.intake_consultant: the chat-turn schema and the
    finalize schema both carry the full enum, and the gate prompt spells out
    the rule.

    Declared STRUCTURAL-ABSENCE: 0 occurrences in intake_consultant at
    9d2c41c, so there is no baseline behaviour to observe. It guards the
    current build - drop a value from the enum and this turns red.
    """
    import inspect

    from client_intake_and_finmo import intake_consultant as ic2

    src = inspect.getsource(ic2)
    turn = getattr(ic2, "consultant_chat_turn", None)
    try:
        turn_src = inspect.getsource(turn) if turn is not None else ""
    except (OSError, TypeError):
        turn_src = ""
    WANT = ("confident_single", "confident_multi", "unsure")

    fails = []
    if "line_split_confidence" not in src:
        fails.append("line_split_confidence is absent from intake_consultant - "
                     "the chat turn cannot report a split judgment at all")
    if "split_rationale" not in src:
        fails.append("split_rationale is absent - a confidence with no stated "
                     "reason is not reviewable")
    missing = [w for w in WANT if w not in src]
    if missing:
        fails.append(f"the confidence vocabulary is incomplete: {missing!r} "
                     f"missing from the schema enum")
    scope = turn_src or src
    scoped = "line_split_confidence" in scope
    if not scoped:
        fails.append("the field exists in the module but not in the chat-turn "
                     "scope - a judgment that only lands at finalize cannot "
                     "steer the conversation while it is happening")

    return not fails, (
        f"intake_consultant carries line_split_confidence + split_rationale "
        f"and the full enum {WANT!r}; present in the chat-turn scope = "
        f"{scoped}" if not fails else "; ".join(fails))



# =========================================================================
# The ISSUE REGISTRY's own gate (CW-031 tier 1). Nick does not trust a
# registry that reports resolutions it did not verify; these two legs are
# what stops that reverting quietly.
#
# The registry evaluates every open issue against one finished run, so a leg
# that drives it touches SHARED state. Both legs therefore (a) seed their own
# synthetic issues under a reserved prefix and delete them again, and (b)
# snapshot and restore every mutable column of every OTHER issue plus the two
# append-only tables' high-water marks. Measured on the shipped build: an
# evaluation of this draft touches nothing but the synthetics. The baseline
# build has no artifact gate and reaches the resolve path more often, which is
# exactly why the restore is not optional.
# =========================================================================

_REG_DRAFT = "1070c6a560a04f3d971019a3787180bf"   # Ravenwood: a real completed run
_REG_SEED = "replay_gate_leg:financials:"
_REG_MUTABLE = ("status", "occurrence_count", "reopened_count",
                "clean_exercise_count", "runs_since_last_seen",
                "resolved_detected_at", "resolution_basis",
                "resolution_confidence", "probe_json", "last_seen_at")


def _reg_columns(cur):
    """The mutable columns THIS commit's schema actually has."""
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'issues'")
    have = {str(r[0]) for r in (cur.fetchall() or [])}
    return [c for c in _REG_MUTABLE if c in have]


def _reg_snapshot(conn):
    cur = conn.cursor()
    cols = _reg_columns(cur)
    cur.execute(f"SELECT issue_id, {', '.join(cols)} FROM issues")
    rows = cur.fetchall()
    cur.execute("SELECT COALESCE(MAX(id), 0) FROM issue_occurrences")
    max_occ = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COALESCE(MAX(id), 0) FROM issue_resolution_events")
    max_evt = int(cur.fetchone()[0] or 0)
    cur.close()
    return {"cols": cols, "rows": rows, "occ": max_occ, "evt": max_evt}


def _reg_restore(conn, snap, signatures):
    cur = conn.cursor()
    for sig in signatures:
        cur.execute("SELECT issue_id FROM issues WHERE signature = %s", (sig,))
        row = cur.fetchone()
        if row:
            issue_id = int(row[0])
            cur.execute("DELETE FROM issue_occurrences WHERE issue_id = %s", (issue_id,))
            cur.execute("DELETE FROM issue_resolution_events WHERE issue_id = %s",
                        (issue_id,))
            cur.execute("DELETE FROM issues WHERE issue_id = %s", (issue_id,))
    cur.execute("DELETE FROM issue_occurrences WHERE id > %s", (snap["occ"],))
    cur.execute("DELETE FROM issue_resolution_events WHERE id > %s", (snap["evt"],))
    sets = ", ".join(f"{c} = %s" for c in snap["cols"])
    for row in snap["rows"]:
        cur.execute(f"UPDATE issues SET {sets} WHERE issue_id = %s",
                    (*row[1:], row[0]))
    conn.commit()
    cur.close()


def _reg_seed(reg, conn, signature, probe):
    """One synthetic HARD issue, one quiet run away from resolving either way.

    resolution_class is stated rather than derived from the category map, so
    the leg measures the resolution RULE and not that map's contents.
    """
    reg.report_issue(
        conn, signature=signature, category="flow", severity="major",
        resolution_class="hard",
        observed="synthetic issue seeded by replay_gate",
        expected="deleted before this leg returns",
        draft_id="replay-gate-seed", probe=probe, source="probe",
    )
    cur = conn.cursor()
    cur.execute(
        "UPDATE issues SET runs_since_last_seen = 4, clean_exercise_count = 0, "
        "occurrence_count = 1 WHERE signature = %s", (signature,))
    conn.commit()
    cur.close()


def _reg_state(reg, conn, signature):
    issue = reg.get_issue(conn, signature=signature)
    return {
        "status": str(issue["status"]),
        "confidence": issue["resolution_confidence"],
        "basis": issue["resolution_basis"],
        "quiet": int(issue["runs_since_last_seen"] or 0),
        "clean": int(issue["clean_exercise_count"] or 0),
    }


def _r_confirmed_needs_artifact(ctx):
    """R33 - 'confirmed' requires a READ artifact that HELD.

    THE BUG (CW-031 tier 1, the meta-fix). Zero of 129 detectors verified an
    artifact. The probe vocabulary only ever asked whether a run WALKED the
    path, so 'resolved confirmed' meant opportunity plus silence - and #138
    was minted confirmed on the very run that disproves it.

    Two synthetic issues, identical but for the thing under test, both driven
    through the production evaluator against a real completed run:

      OPPORTUNITY-ONLY  a hard issue whose probe says only "the run visited
                        financials". It may resolve - but never 'confirmed'.
      ARTIFACT-BACKED   the same, plus an assertion that reads a persisted
                        artifact which HOLDS on this draft. This one MUST
                        reach 'confirmed', or the leg would be satisfied by a
                        registry that simply stopped confirming anything.
    """
    from client_intake_and_finmo import issue_registry as reg  # type: ignore

    opportunity = _REG_SEED + "opportunity_only_hard_issue_must_not_confirm"
    backed = _REG_SEED + "artifact_backed_hard_issue_must_confirm"
    conn = ctx.conn
    snap = _reg_snapshot(conn)
    try:
        _reg_restore(conn, snap, (opportunity, backed))   # any leftovers first
        _reg_seed(reg, conn, opportunity, {"section": "financials"})
        _reg_seed(reg, conn, backed, {
            "section": "financials",
            "artifact": [{"kind": "ops_field_non_null",
                          "path": "products[].product_name"}],
        })
        reg.evaluate_run_for_resolution(conn, draft_id=_REG_DRAFT)
        weak = _reg_state(reg, conn, opportunity)
        strong = _reg_state(reg, conn, backed)
    finally:
        _reg_restore(conn, snap, (opportunity, backed))

    fails = []
    if weak["confidence"] == "confirmed":
        fails.append("an opportunity-only hard issue reached 'confirmed' on "
                     f"opportunity and silence alone (basis={weak['basis']!r})")
    if strong["confidence"] != "confirmed":
        fails.append("an artifact-backed hard issue did NOT reach 'confirmed' "
                     f"(status={strong['status']!r}, basis={strong['basis']!r}) "
                     "- 'confirmed' has to stay earnable")
    return not fails, (
        f"opportunity-only -> {weak['status']}/{weak['confidence']}; "
        f"artifact-backed -> {strong['status']}/{strong['confidence']} "
        f"(basis {strong['basis']!r})"
        + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_metadata_probe_never_ticks(ctx):
    """R34 - a probe that states no retest condition never ticks.

    Ten of the 129 probes were metadata only - a note, a pin, no condition to
    test. Auto-sensing counted every completed run as a clean exercise for
    them, so they resolved on ANY run that finished. The guard reads the probe
    and refuses: no stated condition, no opportunity, no credit.
    """
    from client_intake_and_finmo import issue_registry as reg  # type: ignore

    signature = _REG_SEED + "metadata_only_probe_must_not_tick"
    conn = ctx.conn
    snap = _reg_snapshot(conn)
    try:
        _reg_restore(conn, snap, (signature,))
        _reg_seed(reg, conn, signature,
                  {"note": "seeded by replay_gate", "regression_pin": True})
        before = _reg_state(reg, conn, signature)
        reg.evaluate_run_for_resolution(conn, draft_id=_REG_DRAFT)
        after = _reg_state(reg, conn, signature)
    finally:
        _reg_restore(conn, snap, (signature,))

    fails = []
    if after["status"] != "open":
        fails.append(f"status moved {before['status']!r} -> {after['status']!r} "
                     "on a probe that states no retest condition")
    if after["quiet"] != before["quiet"] or after["clean"] != before["clean"]:
        fails.append(f"counters ticked (quiet {before['quiet']}->{after['quiet']}, "
                     f"clean {before['clean']}->{after['clean']}) on a run that "
                     "cannot have exercised anything")
    return not fails, (
        f"metadata-only probe after a completed run: status={after['status']}, "
        f"quiet={after['quiet']} (was {before['quiet']}), "
        f"clean={after['clean']} (was {before['clean']})"
        + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_cogs_unit_declared(ctx):
    """R35 - the per-line COGS unit is DECLARED, never inferred from size.

    THE BUG (CW-031 round 7 item 1). The door divided by 100 only when the
    figure exceeded 1.0, so a client whose design line runs 1% got a line
    costing 100% of its own revenue and "half a point" became 50%. Every
    artifact assertion passes that number - it is non-null, it is distinct,
    and the workbook is internally consistent about it - so nothing
    downstream can catch it. No threshold separates the readings either:
    0.71 and 71 are both real client inputs, and so are 1 and 0.5.

    Pinned here because a unit contract is exactly the kind of rule that
    rots silently: it costs nothing to "simplify" back into a clamp, and
    the failure is a plausible number rather than a crash. The leg carries
    its own positive control - the large-percent and ratio readings, which
    the clamp got RIGHT - so it cannot be satisfied by a door that simply
    stopped writing.
    """
    door = ctx.ic._apply_per_line_cogs_patch_keys
    say = ctx.ic._build_per_line_cogs_receipt_text

    def _ops():
        return {"lob_models": [{"lob_name": "Garden", "products": [
            {"product_name": "Design consult", "unit_price": 950,
             "units_per_period_capacity": 4, "utilization_rate": 0.55,
             "operating_periods_per_year": 52},
            {"product_name": "Plant sale", "unit_price": 38,
             "units_per_period_capacity": 420, "utilization_rate": 0.62,
             "operating_periods_per_year": 52},
        ]}]}

    def _write(item):
        ops = _ops()
        receipt = door({"financials.cogs_per_line_overrides": [
            dict(item, line_name="Design consult")]}, ops_json=ops)
        row = ops["lob_models"][0]["products"][0]
        return row.get("cogs_percent_of_line_revenue"), receipt, say(receipt)

    fails, seen = [], {}
    # THE READINGS THE CLAMP GOT BACKWARDS, and the two it got right.
    for label, item, want in (
        ("1 percent", {"cogs_percent": 1, "cogs_percent_unit": "percent"}, 0.01),
        ("half a point", {"cogs_percent": 0.5, "cogs_percent_unit": "percent"}, 0.005),
        ("71 percent", {"cogs_percent": 71, "cogs_percent_unit": "percent"}, 0.71),
        ("ratio 0.71", {"cogs_percent": 0.71, "cogs_percent_unit": "ratio"}, 0.71),
    ):
        got, _receipt, _text = _write(item)
        seen[label] = got
        if got != want:
            fails.append(f"{label} stored {got!r}, client meant {want!r}")

    # NO UNIT: refuse and ASK. A silent write here is the whole defect.
    got, receipt, text = _write({"cogs_percent": 1})
    seen["no unit"] = got
    if got is not None:
        fails.append(f"a bare figure with no declared unit was WRITTEN as {got!r} "
                     "instead of refused")
    if not (receipt.get("unit_unclear") and "percent or a fraction" in text):
        fails.append("a refused figure produced no question for the client "
                     f"(unit_unclear={receipt.get('unit_unclear')!r})")

    # A UNIT THAT CANNOT DESCRIBE ITS OWN FIGURE is incoherent, not a hint.
    got, _receipt, _text = _write({"cogs_percent": 71, "cogs_percent_unit": "ratio"})
    seen["ratio of 71"] = got
    if got is not None:
        fails.append(f"a 'ratio' of 71 was rescaled and written as {got!r} "
                     "instead of refused")

    return not fails, (
        "; ".join(f"{k} -> {v!r}" for k, v in seen.items())
        + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_transport_figure_never_speaks(ctx):
    """R36 - a transport figure never speaks for the write.

    THE BUG (CW-031 round 7 item 1b). cogs_percent is the door's TRANSPORT
    key - the client's figure in the CLIENT'S unit, on its way to being
    converted. The acknowledgment renderer walks the write-set, so it
    rendered that raw figure beside the converted one: row 0.005 spoken as
    "COGS to 50.0%", row 0.01 spoken as "$1". Latent while 71 and 0.71
    agreed to the eye; the unit contract made them stop agreeing.

    The rule this pins is the durable half: the renderer may never speak a
    figure in the client's unit as if it were the write. It holds whatever
    else changes upstream - if the transport keys are later consumed at the
    door and never reach a receipt at all, filtering them here still costs
    nothing and this leg still passes.
    """
    from client_intake_and_finmo.capture_receipt import receipt_summary  # type: ignore

    # "half a point": the client said 0.5 (percent), the row holds 0.005.
    receipt = {
        "written": [
            ("financials.cogs_per_line_overrides[0].cogs_percent", None, 0.5),
            ("ops.lob_models[0].products[0].cogs_percent_of_line_revenue", None, 0.005),
        ],
        "dropped": [], "clarify": None,
        "periods_by_prefix": {}, "names_by_prefix": {},
    }
    said = receipt_summary(receipt)

    fails = []
    if "50.0%" in said:
        fails.append("the receipt spoke the client's raw 0.5 as '50.0%' while "
                     "the row holds 0.005 - the transport figure spoke for the write")
    if "0.5%" not in said:
        fails.append(f"the WRITTEN rate is missing from the receipt: {said!r} "
                     "- filtering must not silence the write itself")

    # The same shape as a money-hinted leaf: "cogs" dollars a bare percent.
    dollared = receipt_summary({
        "written": [
            ("financials.cogs_per_line_overrides[0].cogs_percent", None, 1.0),
            ("ops.lob_models[0].products[0].cogs_percent_of_line_revenue", None, 0.01),
        ],
        "dropped": [], "clarify": None,
        "periods_by_prefix": {}, "names_by_prefix": {},
    })
    if "$1" in dollared:
        fails.append("the receipt dollared the client's raw 1 ('$1') for a rate "
                     f"stored as 0.01: {dollared!r}")

    return not fails, (
        f"half-a-point receipt: {said!r}; one-percent receipt: {dollared!r}"
        + ("; FAILED: " + "; ".join(fails) if fails else ""))


REGRESSIONS = [
    Leg("R01", "REGRESSION", "completed-financials-freeze",
        "the completed-financials dead end (the freeze)",
        "ff1da19", "5b5ffbb", _r_freeze, issue="CW-026"),
    Leg("R02", "REGRESSION", "payroll-correction-lands",
        "a stated total payroll lands on the stored field",
        "7bcf307", "c3d83a9", _r_payroll_lands, issue="CW-025 rank-1"),
    Leg("R03", "REGRESSION", "sumac-revert",
        "the correction survives reload + the next turn's Recalc",
        "ff1da19", "5b5ffbb", _r_sumac_revert, issue="CW-026"),
    Leg("R04", "REGRESSION", "crew-double-count",
        "a crew group row is deduped, not counted twice",
        "582cef7", "7b9f481", _r_crew_double_count, issue="CW-024 #108"),
    Leg("R05", "REGRESSION", "capex-zero",
        "prose cannot zero capex",
        "582cef7", "7b9f481", _r_capex_zero, issue="CW-024 #115",
        surface="financials stage: current_capex"),
    Leg("R06", "REGRESSION", "price-ratchet",
        "accepting a price cannot raise the judged ceiling",
        "582cef7", "7b9f481", _r_price_ratchet, issue="CW-024",
        surface="coherence controller"),
    Leg("R07", "REGRESSION", "ask-then-ignore",
        "a solicitation has a consumer; mismatched acceptance holds",
        "582cef7", "7b9f481", _r_ask_then_ignore, issue="CW-024 #117",
        proof=STRUCTURAL_ABSENCE,
        proof_note=("_acceptance_mismatch_hold = 0 occurrences anywhere under "
                    "python/ at 7b9f481 - the guard did not exist, so no "
                    "behavioural red was available through it. Its green side "
                    "IS behavioural. Promote to BEHAVIOURAL by driving the "
                    "contradictory acceptance through the turn chain and "
                    "asserting the value recorded, the way R01/I01-I06 do.")),
    Leg("R08", "REGRESSION", "cogs-basis-ratio-stamp",
        "an explicit cogs_basis survives the production apply path",
        "be7dbb6", "eb7529b", _r_cogs_basis_stamp, issue="CW-024 #112"),
    Leg("R09", "REGRESSION", "owner-comp-one-door",
        "owner pay lives in PEOPLE only - the financials door is gone",
        "000edda", "66cc26b", _r_owner_one_door, issue="CW-022 #8"),
    Leg("R10", "REGRESSION", "role-wage-rollup-recompute",
        "a role-wage correction recomputes the rollup, never hand-patches",
        "28e9fce", "000edda", _r_role_wage_rollup, issue="CW-023"),
    Leg("R11", "REGRESSION", "cedar-double-correction",
        "the door is a TARGET; the delta is computed post-dedupe",
        "51e2d79", "582cef7", _r_cedar_double_correction),
    Leg("R12", "REGRESSION", "rest-inclusion-tripwire",
        "a rest-of-team figure that may contain a named wage cannot record silently",
        "5b5ffbb", "7bcf307", _r_rest_inclusion, issue="CW-025 rank-2",
        proof=STRUCTURAL_ABSENCE,
        proof_note=("_rest_inclusion_check = 0 occurrences under python/ at "
                    "7bcf307 - the tripwire did not exist. Promote by driving "
                    "the rest-of-team figure through the turn and asserting it "
                    "recorded silently.")),
    Leg("R15", "REGRESSION", "completed-financials-no-routing",
        "a correction turn cannot return before the router runs",
        "7bcf307", "c3d83a9", _r_freeze_norouting, issue="CW-025 rank-1"),
    Leg("R16", "REGRESSION", "inclusion-resolver-references",
        "frame figures are references; the fresh figure wins",
        "18f5ca5", "ff1da19", _r_inclusion_references, issue="CW-026 #3"),
    Leg("R17", "REGRESSION", "cogs-echo-guard",
        "the basis flips only on a figure in the client's own message",
        "18f5ca5", "ff1da19", _r_cogs_echo_guard, issue="CW-026 #4"),
    Leg("R18", "REGRESSION", "rejected-figure-reference",
        "a rejected or echoed figure is a reference and cannot be captured",
        "af791ec", "18f5ca5", _r_rejected_figure_reference,
        issue="CW-027 #130", surface="marketing stage"),
    Leg("R19", "REGRESSION", "retention-consumed",
        "the retention answer is consumed at any surface and moves utilization",
        "af791ec", "18f5ca5", _r_retention_consumed,
        issue="CW-027 #131", surface="coherence section",
        proof=STRUCTURAL_ABSENCE,
        proof_note=(
            "SETTLED ON SOURCE, not on the grep alone. At 18f5ca5 the frame "
            "DOES exist (retention_pending is written at section.py:2082 with "
            "prices + retained_used) and a consumer DOES exist - but only "
            "INLINE inside the coherence round-resolution path, keyed on a "
            "router patch 'coherence.retention_answer' (section.py:1115-1160). "
            "What is entirely absent is the link from the client's PROSE to "
            "that value: _parse_retention_answer = 0 occurrences, and "
            "apply_retention_answer = 0 (af791ec extracted the inline consumer "
            "into a callable AND added the parser AND wired it at any "
            "surface). So there is no behavioural red available: a leg aimed "
            "at the consumer would go GREEN on 18f5ca5 (the consumer worked - "
            "that was never the bug), and the bug's actual behaviour - a "
            "retention answer arriving at the done-focus surface and moving "
            "nothing - is only exercised inside post_intake_consult_handler, "
            "which the gate does not drive (its surface is "
            "_run_financials_turn_and_sync). PROMOTION PATH: if the "
            "deterministic resolve is ever lifted out of the HTTP handler into "
            "the turn chain, re-fixture to drive MSG_97 through ctx.turn with "
            "the frame stamped and assert stored utilization 0.78 -> 0.702."),),
    Leg("R20", "REGRESSION", "capacity-twin-invariant",
        "the period capacity twin derives from weekly - they cannot diverge",
        "8bfbbb6", "af791ec", _r_capacity_twin, issue="CW-028 #1"),
    Leg("R21", "REGRESSION", "reconciliation-hold-consumes",
        "the reconciliation hold moves the driver and never re-issues verbatim",
        "8bfbbb6", "af791ec", _r_reconciliation_hold_consumes,
        issue="CW-028 #2", surface="reconciliation"),
    Leg("R22", "REGRESSION", "sibling-attribution",
        "a figure already attributed by the client cannot capture on a sibling",
        "8bfbbb6", "af791ec", _r_sibling_attribution, issue="CW-028 #3",
        surface="named financials stages"),
    Leg("R23", "REGRESSION", "compound-word-numbers",
        "'one hundred and eighty-five' is 185, never the 85 fragment",
        "8bfbbb6", "af791ec", _r_compound_word_numbers, issue="CW-028 #4"),
    Leg("R24", "REGRESSION", "owner-not-enumerated",
        "the rest-of-team question never names the owner alongside 'yourself'",
        "8bfbbb6", "af791ec", _r_owner_not_enumerated, issue="CW-028 #5"),
    Leg("U01", "REGRESSION", "capacity-derivation-invariant",
        "capacity is canonical-per-cadence at every pass; twins cannot diverge",
        "539fb17", "909f66f", _u_capacity_derivation, issue="ENGINE p1",
        surface="canonical sync"),
    Leg("U02", "REGRESSION", "fernhill-round-trip",
        "PERSISTENCE: a landing survives the caller's persist and reads back from SQL",
        "539fb17", "909f66f", _u_fernhill_round_trip, issue="ENGINE p1",
        surface="completed-financials + SQL round-trip"),
    Leg("U03", "REGRESSION", "product-pattern-total",
        "'4 x 20 = 80' lands the stated total, never a factor",
        "539fb17", "909f66f", _u_product_pattern_total, issue="ENGINE p1"),
    Leg("U04", "REGRESSION", "no-op-never-receipts",
        "a door echo never says Recorded:; a real door write still does",
        "9d2c41c", "13fae7c", _u_noop_never_receipts, issue="ENGINE p5",
        surface="completed-financials / people door"),
    Leg("U05", "REGRESSION", "pin-escalation",
        "three holds, three distinct messages, the third offers the direct set",
        "539fb17", "909f66f", _u_pin_escalation, issue="ENGINE p1",
        surface="reconciliation"),
    Leg("R25", "REGRESSION", "goal-anchor-roadmap",
        "the roadmap builds toward the client's own stated 12-month goal",
        "13fae7c", "539fb17", _r_goal_anchor, issue="conv-state #1",
        surface="coherence roadmap"),
    Leg("R26", "INVARIANT", "per-line-cogs-sigma",
        "the blend IS the lines: Sigma(line_rev x line_pct) == total x blend",
        "c77094a", "9d2c41c", _r_per_line_sigma, issue="WS1b",
        surface="model_input_json / engine"),
    Leg("R32", "INVARIANT", "workbook-formula-grid",
        "NEGATIVE CONTROL: the workbook formula grid does not move",
        "c77094a", "9d2c41c", _r_workbook_formula_grid, issue="WS1b floor",
        surface="workbook formula grid", proof=GOLDEN_MASTER,
        proof_note=("The surface neither VS SHA covers - finmo_sheet.py moved "
                    "45 lines in c77094a. Hashes sheet -> row label -> formula "
                    "strings, sorted; NOT the .xlsx bytes, which are "
                    "non-deterministic (zip metadata/timestamps) and would "
                    "false-DRIFT every run. NOTE: this needs "
                    "client_statements_output_excel/ in the baseline tree - "
                    "prove.BASELINE_PATHS was widened for exactly this, since "
                    "otherwise the module resolves from the HOME repo and the "
                    "'baseline' hash is computed with CURRENT workbook code.")),
    Leg("R31", "INVARIANT", "single-line-unchanged",
        "NEGATIVE CONTROL: a single-line draft's persisted payloads do not move",
        "c77094a", "9d2c41c", _r_single_line_unchanged, issue="WS1b floor",
        surface="persisted model_input_json + finmo_json", proof=GOLDEN_MASTER,
        proof_note=("Five of six businesses are single-line. This leg cannot "
                    "go red-on-broken - its whole claim is that nothing "
                    "changed - so it is proved by hash equality ACROSS the two "
                    "commits. RE-BOUNDED after VS answered: both his SHAs hash "
                    "the PERSISTED planning_run_checkpoints columns, so this "
                    "rebuilds those payloads through build_python_model_input_"
                    "json -> apply_derived_driver_policies_to_model_input and "
                    "build_python_finmo_json (all present at both commits) "
                    "rather than the dataclass round-trip the first version "
                    "used - a single-line production run never executes that "
                    "serializer, so it could have GOLDEN-passed while the real "
                    "payload drifted. LIMIT: the SOLVER stage runs inside the "
                    "live system run and is NOT reproduced here; VS's "
                    "Test Files/_prove_single_line_byte_floor.py covers the "
                    "post-solver checkpoint and remains the fuller instrument.")),
    Leg("R28", "REGRESSION", "per-line-cogs-proposal",
        "a two-line business gets one proposal per line, not one blend",
        "c77094a", "9d2c41c", _r_per_line_proposal, issue="WS1b #138",
        tier=LIVE, surface="cogs baseline"),
    Leg("R30", "REGRESSION", "price-change-stamps-retention",
        "a price change stamps the retention frame; a non-price move does not",
        "c77094a", "9d2c41c", _r_price_stamps_retention, issue="WS2",
        surface="forward-move door",
        proof_note=("HALF-PINNED, deliberately. The forward-move door is a "
                    "module-level function and is driven here. The edit_patch "
                    "door's stamp (_changed_product_prices after "
                    "_reconcile_driver_correction) lives INSIDE "
                    "post_intake_consult_handler at line ~15441 and is not "
                    "reachable from this surface - the same handler-resident "
                    "problem as R19. WS2 found that door by probing; nothing "
                    "in the gate guards it yet. Promote when the stamp is "
                    "lifted into the turn chain.")),
    Leg("R27", "INVARIANT", "per-line-cogs-lockstep",
        "the blend is the ONE lever; writing it scales every line in lockstep",
        "c77094a", "9d2c41c", _r_per_line_lockstep, issue="WS1b",
        surface="model_input_json", proof=STRUCTURAL_ABSENCE,
        proof_note=("_reconcile_per_line_cogs_rows = 0 occurrences and "
                    "lockstep_scale_per_line_cogs = 0 at 9d2c41c - both the "
                    "write path and the scaler are new in c77094a, so there "
                    "is no baseline seam to observe. A leg aimed at the "
                    "existing blend write would go GREEN on 9d2c41c (writing "
                    "the blend worked fine; it just had no lines to scale) - "
                    "the fixture-path trap. Promote when lockstep becomes "
                    "observable through a driven turn.")),
    Leg("R29", "INVARIANT", "line-split-confidence-gate",
        "the chat turn carries line_split_confidence and a split rationale",
        "c77094a", "9d2c41c", _r_line_split_confidence, issue="WS1a",
        surface="consultant patch schema", proof=STRUCTURAL_ABSENCE,
        proof_note=("line_split_confidence = 0 and split_rationale = 0 "
                    "occurrences at 9d2c41c - the schema fields do not exist, "
                    "so there is no baseline behaviour to observe. VS_NOTES "
                    "states structural absence for this leg independently. "
                    "Promote if the gate ever drives a live consultant turn.")),
    Leg("R33", "REGRESSION", "confirmed-needs-a-read-artifact",
        "'confirmed' requires an artifact that was read and HELD",
        "4dc2c33", "2f5940b", _r_confirmed_needs_artifact, issue="CW-031 tier 1",
        surface="issue registry",
        proof_note=("Carries its own positive control: the artifact-backed "
                    "issue MUST reach 'confirmed' in the same pass, so the "
                    "leg cannot be satisfied by a registry that stopped "
                    "confirming anything. Seeds and deletes its own synthetic "
                    "issues and restores every other issue's mutable columns "
                    "and both append-only tables' high-water marks.")),
    Leg("R34", "REGRESSION", "metadata-probe-never-ticks",
        "a probe stating no retest condition earns no clean-run credit",
        "4dc2c33", "2f5940b", _r_metadata_probe_never_ticks, issue="CW-031 tier 1",
        surface="issue registry"),
    Leg("R35", "REGRESSION", "cogs-unit-declared-not-inferred",
        "a per-line direct-cost figure converts by its DECLARED unit",
        "53daa0b", "a38a584", _r_cogs_unit_declared, issue="CW-031 round 7 item 1",
        surface="per-line COGS write door",
        proof_note=("Carries its own positive control: 71 percent and ratio "
                    "0.71 - the two readings the old clamp got RIGHT - must "
                    "still land, so a door that stopped writing fails this leg "
                    "as loudly as a door that guesses.")),
    Leg("R36", "REGRESSION", "transport-figure-never-speaks",
        "the client's raw figure never speaks for the converted write",
        "53daa0b", "a38a584", _r_transport_figure_never_speaks,
        issue="CW-031 round 7 item 1b", surface="capture receipt",
        proof_note=("Asserts on receipt_summary directly rather than through a "
                    "live turn, so it pins the RULE (a figure in the client's "
                    "unit is never spoken as the write) rather than one route "
                    "to it. Its positive control is the written rate, which "
                    "must still appear.")),
    Leg("R13", "REGRESSION", "fitted-cogs-covered",
        "covered NAICS proposes materials-only with a band",
        "eb7529b", "613a19a", _r_fitted_cogs_covered, tier=LIVE),
    Leg("R14", "REGRESSION", "fitted-cogs-fallback",
        "uncovered NAICS still yields a fitted band (no dead estimator)",
        "582cef7", "7b9f481", _r_fitted_cogs_fallback, tier=LIVE),
]
