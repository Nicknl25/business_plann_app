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


def _r_workbook_text_surface(ctx):
    """R49 - the STATIC TEXT of the workbook, the surface R32 cannot see.

    R32 hashes FORMULAS. Labels, headers, section titles and static source
    text are not formulas, so a label that MOVES, changes wording, or arrives
    garbled is invisible to it. That is not hypothetical: 01fd627 moved the
    Valuation "As of" header from column E to column L and the re-blessed
    formula golden could not have noticed either way (mini, 2026-08-19). On a
    document a client pays for, a misplaced or mojibake label is a real defect.

    Deliberately a SEPARATE leg rather than a widening of R32 (Nick's ruling,
    2026-08-19): the two surfaces change for different reasons and on different
    schedules. Folding text into the formula grid would mean every wording
    tweak re-blesses the math golden, and a golden that churns for cosmetics is
    one nobody reads before blessing.

    Keyed by cell ADDRESS, because MOVING is the failure mode that started it.
    """
    from client_statements_output_excel import data as wbdata
    from client_statements_output_excel import workbook_builder

    surface = ctx.workbook_text_surface(
        builder=workbook_builder.build_client_financial_model_workbook,
        from_row=wbdata.draft_data_from_row)
    if not surface:
        return False, (f"SETUP: no text surface - "
                       f"{getattr(ctx, 'text_gap', '') or 'the builder rendered nothing'}")
    cells = sum(len(v) for v in surface.values())
    # FLOOR. A near-empty surface hashes stably and proves nothing; the real
    # workbook carries ~1,900 static strings across 15 sheets, so anything
    # under a few hundred means extraction broke rather than the sheets
    # emptying out.
    if cells < 400 or len(surface) < 10:
        return False, (f"only {cells} static text cells across {len(surface)} "
                       f"sheets - too thin to pin; a hollow surface hashes "
                       f"stably and proves nothing")
    blob = json.dumps(surface, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    print(f"GOLDEN-SHA single_line_input {ctx.draft_input_sha}")
    print(f"GOLDEN-SHA workbook_text {digest}")

    # A NAMED CANARY, not just a hash. The hash tells you something moved; this
    # says the specific cell whose silent move created this leg is still where
    # it belongs, so a red leg comes with one concrete thing to look at.
    as_of = [(sheet, addr) for sheet, cells_ in surface.items()
             for addr, text in cells_.items() if text.strip().lower() == "as of"]
    if not as_of:
        return False, ("the Valuation 'As of' header is not in the static text "
                       "surface at all - it is the cell this leg exists for")

    kept, seen = getattr(ctx, "text_coverage", (cells, cells))
    return True, (f"{cells} static text cells across {len(surface)} sheets, "
                  f"keyed by address; static EARNED by intersecting two "
                  f"different businesses built at two different WALL CLOCKS, "
                  f"so the client name, city, per-line labels and the build "
                  f"date are absent by construction; the 'As of' header is at "
                  f"{as_of[0][0]}!{as_of[0][1]}; COVERAGE {kept}/{seen} of the "
                  f"first workbook's text - the {seen - kept} unpinned are the "
                  f"per-draft text that SHOULD escape (client name and city, "
                  f"product and line names, the draft id, and the Valuation "
                  f"reference block's citations and as-of dates, which are live "
                  f"data built differently in the second sample on purpose); "
                  f"text sha {digest[:12]}")


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


def _r_transport_keys_never_persist(ctx):
    """R37 - a transport key is consumed at its door, never stored.

    THE BUG (CW-031 round 7 -> 8, fix 1). cogs_per_line_overrides and
    cogs_shared_structure_groups are pseudo-fields: the client's statement
    in flight, in the CLIENT'S OWN units, on its way to rows that store
    something else. The correction path consumed them and then persisted
    them verbatim into financials_json anyway - measured 12 of 12 live
    turns, one array carrying a 48 and a 0.19 under one field name. That
    is round 7's wrong-unit defect preserved in the ARTIFACT instead of
    in the sentence, waiting for the first reader that just takes the
    number. R36 pins the sentence half; this pins the storage half.

    Positive control: the rows must actually be written (the door still
    works), so a patch path that stopped consuming the keys entirely
    fails this leg as loudly as one that stores them.
    """
    ops = {"lob_models": [{"lob_name": "Garden", "products": [
        {"product_name": "Plant sale", "unit_price": 38,
         "units_per_period_capacity": 420},
        {"product_name": "Install project", "unit_price": 4200,
         "units_per_period_capacity": 2},
    ]}]}
    patch = {
        "financials.cogs_per_line_overrides": [
            {"line_name": "Plant sale", "cogs_percent": 48,
             "cogs_percent_unit": "percent"},
            {"line_name": "Install project", "cogs_percent": 0.19,
             "cogs_percent_unit": "ratio"},
        ],
        "financials.cogs_shared_structure_groups": [
            ["Plant sale", "Install project"]],
    }
    _bf, ops_out, _mk, _pp, fin_out, _ff = ctx.ic._apply_scoped_patch(
        patch,
        business_facts={}, ops_json=ops, market_json={}, people_json={},
        financials_json={"cogs_percent_of_revenue": 0.47},
        fulfillment_json={})

    rows = [p for lob in ops_out.get("lob_models") or []
            for p in lob.get("products") or []]
    rates = {p.get("product_name"): p.get("cogs_percent_of_line_revenue")
             for p in rows}

    fails = []
    # Positive control first: the door must have written the rows.
    if any(v is None for v in rates.values()):
        fails.append(f"the door did not write the rows: {rates!r} - a leg "
                     "green because nothing was consumed proves nothing")
    # THE RULE: neither transport key, bare or dotted, reaches the artifact.
    for key in ("cogs_per_line_overrides", "cogs_shared_structure_groups",
                "financials.cogs_per_line_overrides",
                "financials.cogs_shared_structure_groups"):
        if fin_out.get(key) is not None:
            fails.append(f"transport key {key!r} STORED in financials_json: "
                         f"{fin_out.get(key)!r}")

    return not fails, (
        f"rows {rates!r}; stored transport keys: "
        f"{[k for k in fin_out if 'cogs_per_line' in k or 'shared_structure' in k]!r}"
        + ("; FAILED: " + "; ".join(fails) if fails else ""))


class _OpsOnlyCursor(object):
    """A cursor stub for issue-registry assertions that only ever read
    operating_model_json for one draft (_load_ops_model's exact surface).
    Keeps gate legs out of the drafts table entirely: the assertion under
    test is pure given its ops JSON, and a leg must not write rows to
    prove a rule about writes."""

    def __init__(self, ops_json):
        import json as _json
        self._payload = _json.dumps(ops_json)

    def execute(self, *_a, **_k):
        return None

    def fetchone(self):
        return (self._payload,)


def _r_inference_never_stored(ctx):
    """R38 - an inference is never stored as structure; the net ASKS.

    THE BUG (CW-031 round 8 -> 9, fix 1). Round 8's value-equality net
    stored an inferred all-lines group whenever a write left every line
    on one rate. The round-8 audit killed it three ways at once: it
    CLOBBERED a client-declared partial group and restamped every basis
    as inferred (the app overwriting what the client declared), an echo
    of one existing rate minted a collapse nobody declared, and the
    artifact assertion then PASSED the result - a false PASS inside the
    gate this class exists to close. Ruled under Nick's corollary 2 +
    silence-never-agreement: uniform post-write rates at N>=3 put a
    QUESTION in the receipt; only the client's own declaration stores a
    group. THE RULE: AN INFERENCE NEVER OVERWRITES A DECLARED STAMP -
    and an inference is never authority at the gate either.

    Four teeth, each red on the round-8 baseline for its own reason:
    the mint, the clobber, the echo, and the gate's declared-only rule.
    Positive controls: the rates themselves still land, and a declared
    all-lines group still PASSES the assertion - a door that stopped
    writing or a gate that fails everything cannot satisfy this leg.
    """
    from client_intake_and_finmo import issue_registry as ir  # type: ignore

    door = ctx.ic._apply_per_line_cogs_patch_keys
    say = ctx.ic._build_per_line_cogs_receipt_text

    def _rows(**named):
        products = []
        for name, (rate, group, basis) in named.items():
            row = {"product_name": name.replace("_", " "), "unit_price": 100.0,
                   "units_per_period_capacity": 10.0,
                   "operating_periods_per_year": 12.0}
            if rate is not None:
                row["cogs_percent_of_line_revenue"] = rate
            if group:
                row["cogs_cost_structure_group"] = group
                row["cogs_cost_structure_group_basis"] = basis
            products.append(row)
        return {"lob_models": [{"lob_name": "Main", "products": products}]}

    fails, seen = [], []

    # S1 THE MINT: this write CREATES uniformity at N=4 -> ask, never store.
    ops = _rows(plant=(0.55, None, None), hard=(0.55, None, None),
                install=(None, None, None), design=(None, None, None))
    receipt = door({"financials.cogs_per_line_overrides": [
        {"line_name": "install", "cogs_percent": 55, "cogs_percent_unit": "percent"},
        {"line_name": "design", "cogs_percent": 55, "cogs_percent_unit": "percent"},
    ]}, ops_json=ops)
    rows = ops["lob_models"][0]["products"]
    stored = [(r["product_name"], r.get("cogs_cost_structure_group"),
               r.get("cogs_cost_structure_group_basis"))
              for r in rows if r.get("cogs_cost_structure_group")]
    seen.append(f"mint: stored={stored!r}, ask={receipt.get('uniform_rate_ask')!r}")
    if stored:
        fails.append(f"uniform write STORED a group nobody declared: {stored!r}")
    if not receipt.get("uniform_rate_ask"):
        fails.append("uniform write raised no ask in the receipt")
    elif "one shared cost structure" not in say(receipt):
        fails.append("the ask is in the receipt but not in the sentence")
    if any(r.get("cogs_percent_of_line_revenue") != 0.55 for r in rows):
        fails.append("positive control: the rates themselves did not land")

    # S2 THE CLOBBER: a client-DECLARED partial group survives a coinciding
    # write byte-identical.
    label = "shared:hard+plant"
    ops = _rows(plant=(0.55, label, "declared"), hard=(0.55, label, "declared"),
                install=(None, None, None), design=(None, None, None))
    door({"financials.cogs_per_line_overrides": [
        {"line_name": "install", "cogs_percent": 55, "cogs_percent_unit": "percent"},
        {"line_name": "design", "cogs_percent": 55, "cogs_percent_unit": "percent"},
    ]}, ops_json=ops)
    rows = ops["lob_models"][0]["products"]
    declared = [(r["product_name"], r.get("cogs_cost_structure_group"),
                 r.get("cogs_cost_structure_group_basis")) for r in rows[:2]]
    newcomers = [(r["product_name"], r.get("cogs_cost_structure_group"))
                 for r in rows[2:] if r.get("cogs_cost_structure_group")]
    seen.append(f"clobber: declared={declared!r}, newcomers={newcomers!r}")
    if declared != [("plant", label, "declared"), ("hard", label, "declared")]:
        fails.append(f"a coinciding write TOUCHED the declared stamp: {declared!r}")
    if newcomers:
        fails.append(f"the net grouped rows the client never grouped: {newcomers!r}")

    # S3 THE ECHO: restating one rate of an already-uniform state neither
    # stores nor re-asks.
    ops = _rows(plant=(0.55, None, None), hard=(0.55, None, None),
                install=(0.55, None, None), design=(0.55, None, None))
    receipt = door({"financials.cogs_per_line_overrides": [
        {"line_name": "hard", "cogs_percent": 55, "cogs_percent_unit": "percent"},
    ]}, ops_json=ops)
    rows = ops["lob_models"][0]["products"]
    echo_stored = [r["product_name"] for r in rows if r.get("cogs_cost_structure_group")]
    seen.append(f"echo: stored={echo_stored!r}, ask={receipt.get('uniform_rate_ask')!r}")
    if echo_stored:
        fails.append(f"an echo of an already-uniform state minted a group: {echo_stored!r}")
    if receipt.get("uniform_rate_ask"):
        fails.append("an echo of an already-uniform state re-raised the ask")

    # S4 THE GATE: an inferred-basis group is not authority; a declared one is.
    inferred_ops = _rows(
        a=(0.55, "shared:a+b+c", "inferred from identical stated rates"),
        b=(0.55, "shared:a+b+c", "inferred from identical stated rates"),
        c=(0.55, "shared:a+b+c", "inferred from identical stated rates"))
    verdict = ir._assert_ops_per_line_cogs(_OpsOnlyCursor(inferred_ops), "r38", {})
    seen.append(f"gate(inferred)={verdict.get('verdict')!r}")
    if verdict.get("verdict") != "fail":
        fails.append(f"an INFERRED all-lines group passed the gate: {verdict!r}")
    declared_ops = _rows(a=(0.55, "shared:a+b+c", "declared"),
                         b=(0.55, "shared:a+b+c", "declared"),
                         c=(0.55, "shared:a+b+c", "declared"))
    verdict = ir._assert_ops_per_line_cogs(_OpsOnlyCursor(declared_ops), "r38", {})
    seen.append(f"gate(declared)={verdict.get('verdict')!r}")
    if verdict.get("verdict") != "pass":
        fails.append("positive control: a DECLARED all-lines group must pass "
                     f"the gate, got {verdict!r}")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_separation_clears_group(ctx):
    """R39 - separation clears the group, and the stale label retires.

    THE BUG (CW-031 round 8 -> 9, fix 2). "Keep design consults separate"
    got "Got it - we'll keep design consults separate" while the row STILL
    carried the all-lines label: the group field had two writers and ZERO
    removers, so an authority the client could not revoke was not an
    authority the client held. Words != state, this batch's founding law,
    in the artifact. Round 9 built the remover (cogs_separate_lines,
    consumed never stored) and the group-coherence pass: a label encodes
    its own membership, and rows wearing a label whose carrying set no
    longer matches it are cleared too, BY NAME, in the receipt.

    Teeth: the named row's group AND basis clear; the abandoned member's
    stale label retires and is named; a regroup that leaves a member out
    retires that member's label. Positive control: a DISJOINT declared
    group survives the separation byte-identical - a pass that clears
    everything fails this leg as loudly as one that clears nothing.
    """
    import copy as _copy

    door = ctx.ic._apply_per_line_cogs_patch_keys
    say = ctx.ic._build_per_line_cogs_receipt_text

    g1, g2 = "shared:hard+plant", "shared:design+install"
    ops = {"lob_models": [{"lob_name": "Main", "products": [
        {"product_name": "plant", "cogs_percent_of_line_revenue": 0.52,
         "cogs_cost_structure_group": g1, "cogs_cost_structure_group_basis": "declared",
         "unit_price": 100.0, "units_per_period_capacity": 10.0},
        {"product_name": "hard", "cogs_percent_of_line_revenue": 0.52,
         "cogs_cost_structure_group": g1, "cogs_cost_structure_group_basis": "declared",
         "unit_price": 80.0, "units_per_period_capacity": 12.0},
        {"product_name": "install", "cogs_percent_of_line_revenue": 0.20,
         "cogs_cost_structure_group": g2, "cogs_cost_structure_group_basis": "declared",
         "unit_price": 4200.0, "units_per_period_capacity": 2.0},
        {"product_name": "design", "cogs_percent_of_line_revenue": 0.20,
         "cogs_cost_structure_group": g2, "cogs_cost_structure_group_basis": "declared",
         "unit_price": 950.0, "units_per_period_capacity": 4.0},
    ]}]}
    other_before = _copy.deepcopy(ops["lob_models"][0]["products"][2:])

    receipt = door({"financials.cogs_separate_lines": ["plant"]}, ops_json=ops)
    text = say(receipt)
    rows = ops["lob_models"][0]["products"]
    fails, seen = [], []
    seen.append(f"separated={receipt.get('separated')!r}, "
                f"ungrouped={receipt.get('ungrouped')!r}")
    if rows[0].get("cogs_cost_structure_group") is not None \
       or rows[0].get("cogs_cost_structure_group_basis") is not None:
        fails.append(f"the separated row still carries "
                     f"{rows[0].get('cogs_cost_structure_group')!r} / "
                     f"{rows[0].get('cogs_cost_structure_group_basis')!r}")
    if not receipt.get("separated"):
        fails.append("the separation left no receipt entry - the door did not "
                     "consume the key")
    if rows[1].get("cogs_cost_structure_group") is not None:
        fails.append("the abandoned member still wears a label whose "
                     "membership is gone")
    if "hard" not in " ".join(str(u) for u in (receipt.get("ungrouped") or [])):
        fails.append(f"the retired row is not NAMED in the receipt "
                     f"(ungrouped={receipt.get('ungrouped')!r})")
    elif "no longer covers" not in text:
        fails.append("the retirement is recorded but never spoken")
    if rows[2:] != other_before:
        fails.append(f"THE DISJOINT GROUP CHANGED: {other_before!r} -> {rows[2:]!r}")

    # A regroup that leaves a member out retires that member's stale label.
    g_all = "shared:alpha+beta+gamma"
    ops2 = {"lob_models": [{"lob_name": "Main", "products": [
        {"product_name": "alpha", "cogs_percent_of_line_revenue": 0.30,
         "cogs_cost_structure_group": g_all, "cogs_cost_structure_group_basis": "declared",
         "unit_price": 50.0, "units_per_period_capacity": 20.0},
        {"product_name": "beta", "cogs_percent_of_line_revenue": 0.30,
         "cogs_cost_structure_group": g_all, "cogs_cost_structure_group_basis": "declared",
         "unit_price": 60.0, "units_per_period_capacity": 15.0},
        {"product_name": "gamma", "cogs_percent_of_line_revenue": 0.30,
         "cogs_cost_structure_group": g_all, "cogs_cost_structure_group_basis": "declared",
         "unit_price": 70.0, "units_per_period_capacity": 10.0},
        {"product_name": "delta", "cogs_percent_of_line_revenue": 0.10,
         "unit_price": 90.0, "units_per_period_capacity": 5.0},
    ]}]}
    receipt2 = door({"financials.cogs_shared_structure_groups": [["alpha", "beta"]]},
                    ops_json=ops2)
    rows2 = ops2["lob_models"][0]["products"]
    seen.append(f"regroup: gamma={rows2[2].get('cogs_cost_structure_group')!r}, "
                f"ungrouped={receipt2.get('ungrouped')!r}")
    if rows2[2].get("cogs_cost_structure_group") is not None:
        fails.append("the member the regroup left out still wears the old "
                     f"label {rows2[2].get('cogs_cost_structure_group')!r}")
    if not (rows2[0].get("cogs_cost_structure_group")
            and rows2[0].get("cogs_cost_structure_group")
            == rows2[1].get("cogs_cost_structure_group")):
        fails.append("positive control: the regroup itself did not land")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_membership_is_data(ctx):
    """R40 - group membership is data beside the label, not a label parse.

    THE BUG (CW-031 round 9 -> 10, fix 1). The group label encoded its own
    membership ("shared:" + "+".join(names)) and the coherence pass parsed
    it back with split('+'); product names legitimately contain '+' (7 real
    drafts: 'Business Plan + Financial Model', 'IV services (visits +
    memberships)'), so declaring a group containing such a line stored it
    and RETIRED it in the same call - the client's declaration evaporated
    with a receipt that said both "sharing one rate" and "no longer covers"
    in one breath. Round 10 stores the normalized member list beside the
    label (cogs_cost_structure_group_members); the pass compares stored
    membership to the carrying set directly and the label is display only.

    Teeth: the '+'-named declared group SURVIVES its own declaring call,
    and the member list is STORED AS DATA beside the label on every member
    row. Positive controls: a genuine separation still retires the
    abandoned survivor by name (a pass that never retires fails as loudly
    as one that retires everything), and an AGREEING mixed group (one row
    carrying the list, one legacy label-only row whose name the list
    covers) survives untouched - the legacy fallback must not false-retire
    a members-carrying group. Proven live 2026-08-13: 'Hard goods +
    Sundries' declared through the real router landed with members
    ['hard goods + sundries', 'plant sale'], basis declared, and survived
    (_mini_cw031_r10_live_20260813.txt W1/W2).
    """
    door = ctx.ic._apply_per_line_cogs_patch_keys

    plus_name = "Design + Build"
    ops = {"lob_models": [{"lob_name": "Main", "products": [
        {"product_name": plus_name, "cogs_percent_of_line_revenue": 0.30,
         "unit_price": 100.0, "units_per_period_capacity": 10.0},
        {"product_name": "Plant sale", "cogs_percent_of_line_revenue": 0.30,
         "unit_price": 80.0, "units_per_period_capacity": 12.0},
        {"product_name": "Hard goods", "cogs_percent_of_line_revenue": 0.60,
         "unit_price": 60.0, "units_per_period_capacity": 15.0},
    ]}]}
    rows = ops["lob_models"][0]["products"]
    receipt = door(
        {"financials.cogs_shared_structure_groups": [[plus_name, "Plant sale"]]},
        ops_json=ops)

    fails, seen = [], []
    seen.append(f"declare: groups={[r.get('cogs_cost_structure_group') for r in rows]!r}, "
                f"ungrouped={receipt.get('ungrouped')!r}")
    if not (rows[0].get("cogs_cost_structure_group")
            and rows[0].get("cogs_cost_structure_group")
            == rows[1].get("cogs_cost_structure_group")):
        fails.append("the '+'-named declared group did not survive its own "
                     "declaring call (the round-9 split('+') trap)")
    for r in rows[:2]:
        members = r.get("cogs_cost_structure_group_members")
        if not (isinstance(members, list)
                and sorted(str(m).strip().lower() for m in members)
                == sorted([plus_name.lower(), "plant sale"])):
            fails.append(f"membership is not stored as data beside the label "
                         f"on {r.get('product_name')!r} "
                         f"(members={members!r})")
            break
    if rows[2].get("cogs_cost_structure_group") is not None:
        fails.append("a line outside the declaration was grouped")

    # Positive control 1: a genuine separation still retires the survivor.
    if not fails:
        receipt2 = door({"financials.cogs_separate_lines": ["Plant sale"]},
                        ops_json=ops)
        seen.append(f"separation: groups={[r.get('cogs_cost_structure_group') for r in rows]!r}, "
                    f"ungrouped={receipt2.get('ungrouped')!r}")
        if any(r.get("cogs_cost_structure_group") for r in rows):
            fails.append("a real separation left a group standing - the pass "
                         "lost its teeth")
        if any(r.get("cogs_cost_structure_group_members") for r in rows):
            fails.append("a cleared row still carries a stored member list")
        if plus_name.lower() not in " ".join(
                str(u).lower() for u in (receipt2.get("ungrouped") or [])):
            fails.append(f"the retired '+'-named survivor is not named "
                         f"(ungrouped={receipt2.get('ungrouped')!r})")

    # Positive control 2: an AGREEING mixed group (one row with the stored
    # list, one legacy label-only row the list covers) must survive.
    ops3 = {"lob_models": [{"lob_name": "Main", "products": [
        {"product_name": "Plum", "cogs_percent_of_line_revenue": 0.30,
         "cogs_cost_structure_group": "shared:pear+plum",
         "cogs_cost_structure_group_basis": "declared",
         "cogs_cost_structure_group_members": ["pear", "plum"],
         "unit_price": 50.0, "units_per_period_capacity": 20.0},
        {"product_name": "Pear", "cogs_percent_of_line_revenue": 0.30,
         "cogs_cost_structure_group": "shared:pear+plum",
         "cogs_cost_structure_group_basis": "declared",
         "unit_price": 55.0, "units_per_period_capacity": 18.0},
    ]}]}
    rows3 = ops3["lob_models"][0]["products"]
    door({"financials.cogs_per_line": [
        {"line_name": "Plum", "cogs_percent": 0.31, "unit": "ratio"}]},
        ops_json=ops3)
    seen.append(f"agreeing-mixed: groups={[r.get('cogs_cost_structure_group') for r in rows3]!r}")
    if not (rows3[0].get("cogs_cost_structure_group")
            and rows3[1].get("cogs_cost_structure_group")):
        fails.append("an AGREEING mixed group (stored list + legacy row the "
                     "list covers) was false-retired")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_match_never_lies(ctx):
    """R41 - a match never names an ambiguous field, a near-miss never
    claims a match.

    THE BUG (CW-031 round 10, mini's D1/D2 -> round 11 fixes 1-2). The
    match-on-file sentence named the FIRST leaf whose value matched, so a
    client who restated their annual interest payment (9,800) was told
    "monthly rent expense is $9,800" - a field claim the client never made,
    on a collision 92.7% of real drafts carry. And the 0.5% tolerance let a
    swallowed near-miss CORRECTION (1,548,000 vs stored 1,553,000) be
    spoken as a confirmation, keeping the client on the old number.

    Teeth: (D1) a value stored under two distinct leaf names matches with
    leaf None and the sentence speaks the bare value with no field claim;
    (D2) a 0.32% near-miss never claims a match. Positive controls: a
    unique-name figure still names its field (a law that never names fails
    as loudly as one that always does), and exact + float-dust restatements
    still match (a tolerance of zero fails as loudly as one of 0.5%).
    Proven live 2026-08-13 (_mini_cw031_r11_live_b_20260813.txt): B1
    ambiguous spoke '$9,800 on file' bare, B2 matched real stored dust
    729909.9999999995 against a stated 729,910, B3 unique kept its name.
    """
    figures_on_file = ctx.ic._figures_all_on_file
    spoken = ctx.ic._spoken_on_file_match

    state = {"financials": {"monthly_rent_expense": 9800.0,
                            "annual_interest_payment": 9800.0,
                            "current_revenue": 1553000.0}}
    fails, seen = [], []

    m = figures_on_file(state, [9800.0])
    sent = spoken(*m[0]) if m else "(no match)"
    seen.append(f"ambiguous 9800 -> m={m!r} spoken={sent!r}")
    if not m:
        fails.append("an on-file ambiguous value no longer matches at all")
    elif m[0][0] is not None:
        fails.append(f"an ambiguous value named a field: {m[0][0]!r} "
                     "(rent==interest - the client never said it)")
    elif " is " in sent or "9,800" not in sent:
        fails.append(f"the bare-value sentence is wrong: {sent!r}")

    m2 = figures_on_file(state, [1548000.0])
    seen.append(f"near-miss 1,548,000 vs 1,553,000 -> m={m2!r}")
    if m2:
        fails.append("a 0.32% correction was claimed as a match - the "
                     "swallowed-correction register is back")

    # Positive control 1: the unique name still names its field.
    m3 = figures_on_file(state, [1553000.0])
    sent3 = spoken(*m3[0]) if m3 else "(no match)"
    seen.append(f"unique -> {sent3!r}")
    if not (m3 and m3[0][0] == "current_revenue"
            and "current revenue" in sent3 and "1,553,000" in sent3):
        fails.append("a unique-name match lost its field name - the law "
                     "must not be satisfied by never naming")

    # Positive control 2: exact and float-dust restatements still match.
    m4 = figures_on_file(state, [1552999.999999999])
    seen.append(f"dust -> match={bool(m4)}")
    if not m4:
        fails.append("a float-dust restatement no longer matches - the "
                     "tolerance died instead of narrowing")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_identity_is_member_set(ctx):
    """R42 - group identity is the stored member set, not the label string.

    THE BUG (CW-031 round 10, mini's D3 -> round 11 fix 3). The coherence
    pass grouped carrying rows BY LABEL, so two healthy groups whose
    '+'-joined labels collide ('A+B','C' vs 'A','B+C' -> both
    'shared:a+b+c') read as ONE incoherent claim and BOTH retired -
    declaring the second killed the first and itself in the same call. And
    a stale label-only legacy row (renamed after grouping) dragged a fresh
    members-carrying declaration down with it.

    Teeth: (a) the label collision yields two coherent partitions and BOTH
    survive with their member lists intact; (b) the stale legacy twin
    retires ALONE while the fresh declaration survives. Positive control:
    a one-row group wearing a two-member claim still retires (a pass that
    never retires fails as loudly as one that retires everything).

    KNOWN LIMIT, closed in round 12: the pure-legacy tier's order
    dependence (round-11 audit T1b) and the duplicate-name attach (T2)
    were fixed at e8d1f3b and are pinned by R43, which baselines at
    b0607e0 where this leg is green - the two legs partition the class
    between them.
    """
    door = ctx.ic._apply_per_line_cogs_patch_keys

    def mkops(names_rates):
        return {"lob_models": [{"lob_name": "Main", "products": [
            {"product_name": n, "cogs_percent_of_line_revenue": r,
             "unit_price": 100.0, "units_per_period_capacity": 10.0,
             "operating_periods_per_year": 12.0}
            for n, r in names_rates]}]}

    fails, seen = [], []

    # Tooth (a): the '+'-label collision - both groups must survive.
    o1 = mkops([("A+B", 0.30), ("C", 0.30), ("A", 0.50), ("B+C", 0.50)])
    rows1 = o1["lob_models"][0]["products"]
    door({"financials.cogs_shared_structure_groups": [["A+B", "C"]]},
         ops_json=o1)
    r1 = door({"financials.cogs_shared_structure_groups": [["A", "B+C"]]},
              ops_json=o1)
    labels1 = [r.get("cogs_cost_structure_group") for r in rows1]
    members1 = [r.get("cogs_cost_structure_group_members") for r in rows1]
    seen.append(f"collision: labels={labels1!r} "
                f"ungrouped={r1.get('ungrouped')!r}")
    if not all(labels1) or r1.get("ungrouped"):
        fails.append("a label collision retired a healthy group - identity "
                     "is being read from the label again")
    elif not (members1[0] and sorted(members1[0]) == ["a+b", "c"]
              and members1[2] and sorted(members1[2]) == ["a", "b+c"]):
        fails.append(f"the surviving partitions lost their member lists: "
                     f"{members1!r}")

    # Tooth (b): a stale legacy twin retires ALONE.
    o2 = mkops([("Alpha", 0.40), ("Beta", 0.40), ("Gamma", 0.20)])
    ra, rb, rg = o2["lob_models"][0]["products"]
    rg["cogs_cost_structure_group"] = "shared:alpha+beta"
    rg["cogs_cost_structure_group_basis"] = "declared"
    r2 = door({"financials.cogs_shared_structure_groups": [["Alpha", "Beta"]]},
              ops_json=o2)
    seen.append(f"stale twin: a={ra.get('cogs_cost_structure_group')!r} "
                f"g={rg.get('cogs_cost_structure_group')!r} "
                f"ungrouped={r2.get('ungrouped')!r}")
    if not (ra.get("cogs_cost_structure_group")
            and rb.get("cogs_cost_structure_group")):
        fails.append("a stale label-only twin dragged the fresh declaration "
                     "down with it")
    if rg.get("cogs_cost_structure_group"):
        fails.append("the stale twin kept a group it never earned")
    if "Main / Gamma" not in (r2.get("ungrouped") or []):
        fails.append(f"the stale twin's retire is not named "
                     f"(ungrouped={r2.get('ungrouped')!r})")

    # Positive control: a failing claim still retires (the O4b shape).
    o3 = mkops([("P1", 0.30), ("P2", 0.30), ("P3", 0.30), ("P4", 0.10)])
    rows3 = o3["lob_models"][0]["products"]
    door({"financials.cogs_shared_structure_groups": [["P1", "P2"]]},
         ops_json=o3)
    r3 = door({"financials.cogs_shared_structure_groups": [["P2", "P3", "P4"]]},
              ops_json=o3)
    seen.append(f"overlap: p1={rows3[0].get('cogs_cost_structure_group')!r} "
                f"ungrouped={r3.get('ungrouped')!r}")
    if rows3[0].get("cogs_cost_structure_group") \
            or "Main / P1" not in (r3.get("ungrouped") or []):
        fails.append("a one-row group wearing a two-member claim survived - "
                     "the pass lost its teeth")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_legacy_tier_is_law(ctx):
    """R43 - the legacy tier is a law, not an accident of order.

    THE BUG (CW-031 round-11 audit T1b/T2 -> round 12 fix, e8d1f3b). The
    parse-fallback partition for pure-legacy rows (label, no member list)
    was created by whichever legacy row iterated FIRST (`elif not _parts`),
    and that row JOINED it even when its own name was off-claim: same rows,
    stale-last retired alone, stale-FIRST poisoned the partition and
    retired everything. And a stale label-only twin under a DUPLICATE
    product name attached to a fresh members-carrying partition and kept a
    group it never earned, because the coherence test compares name SETS
    and the duplicate disappeared in the dedup.

    THE LAW: the parse partition is derived from the LABEL, once, before
    any row is looked at; rows join any partition by one rule (name in
    key), and never one that already carries their name.

    Teeth: (a) stale legacy row FIRST in document order still retires
    ALONE - the coherent remainder survives; (b) the duplicate-name twin
    goes stale instead of keeping the unearned group. Positive controls:
    stale-LAST retires alone (a retire-everything pass fails) and the
    agreeing mixed attach still lands (an over-eager guard fails).
    """
    door = ctx.ic._apply_per_line_cogs_patch_keys

    def _p(n, r):
        return {"product_name": n, "cogs_percent_of_line_revenue": r,
                "unit_price": 100.0, "units_per_period_capacity": 10.0,
                "operating_periods_per_year": 12.0}

    def legacy(row, label):
        row["cogs_cost_structure_group"] = label
        row["cogs_cost_structure_group_basis"] = "declared"

    trigger = {"financials.cogs_shared_structure_groups": [["C", "D"]]}
    fails, seen = [], []

    # Tooth (a): stale legacy row FIRST - must retire alone.
    o1 = {"lob_models": [{"lob_name": "Main", "products": [
        _p("Zed", 0.20), _p("A", 0.30), _p("B", 0.30),
        _p("C", 0.10), _p("D", 0.10)]}]}
    rz, ra, rb = o1["lob_models"][0]["products"][:3]
    for r in (rz, ra, rb):
        legacy(r, "shared:a+b")  # Zed renamed after grouping: off-claim
    r1 = door(trigger, ops_json=o1)
    seen.append(f"stale-first: ungrouped={r1.get('ungrouped')!r}")
    if not (ra.get("cogs_cost_structure_group")
            and rb.get("cogs_cost_structure_group")):
        fails.append("a stale-FIRST legacy row poisoned the parse partition "
                     "- the coherent remainder retired with it")
    if rz.get("cogs_cost_structure_group"):
        fails.append("the off-claim legacy row kept its label")

    # Tooth (b): duplicate-name twin in another LOB stays stale.
    o2 = {"lob_models": [
        {"lob_name": "Main", "products": [_p("Alpha", 0.40), _p("Beta", 0.40)]},
        {"lob_name": "Side", "products": [_p("Alpha", 0.55), _p("C", 0.10),
                                          _p("D", 0.10)]},
    ]}
    ma, mb = o2["lob_models"][0]["products"]
    sa = o2["lob_models"][1]["products"][0]
    for r in (ma, mb):
        legacy(r, "shared:alpha+beta")
        r["cogs_cost_structure_group_members"] = ["alpha", "beta"]
    legacy(sa, "shared:alpha+beta")  # stale label-only twin, duplicate name
    r2 = door(trigger, ops_json=o2)
    seen.append(f"dup twin: side={sa.get('cogs_cost_structure_group')!r} "
                f"ungrouped={r2.get('ungrouped')!r}")
    if sa.get("cogs_cost_structure_group"):
        fails.append("a duplicate-name legacy twin kept a group it never "
                     "earned - the name-set dedup is hiding it again")
    if not (ma.get("cogs_cost_structure_group")
            and mb.get("cogs_cost_structure_group")):
        fails.append("the fresh members-carrying declaration retired with "
                     "the twin")

    # Positive control 1: stale legacy row LAST still retires alone.
    o3 = {"lob_models": [{"lob_name": "Main", "products": [
        _p("A", 0.30), _p("B", 0.30), _p("Zed", 0.20),
        _p("C", 0.10), _p("D", 0.10)]}]}
    ra3, rb3, rz3 = o3["lob_models"][0]["products"][:3]
    for r in (ra3, rb3, rz3):
        legacy(r, "shared:a+b")
    r3 = door(trigger, ops_json=o3)
    seen.append(f"stale-last: ungrouped={r3.get('ungrouped')!r}")
    if not (ra3.get("cogs_cost_structure_group")
            and rb3.get("cogs_cost_structure_group")
            and not rz3.get("cogs_cost_structure_group")):
        fails.append("the stale-LAST shape broke - the pass retires "
                     "everything or nothing")

    # Positive control 2: the agreeing mixed attach still lands.
    o4 = {"lob_models": [{"lob_name": "Main", "products": [
        _p("Alpha", 0.40), _p("Beta", 0.40), _p("C", 0.10), _p("D", 0.10)]}]}
    ra4, rb4 = o4["lob_models"][0]["products"][:2]
    legacy(ra4, "shared:alpha+beta")
    ra4["cogs_cost_structure_group_members"] = ["alpha", "beta"]
    legacy(rb4, "shared:alpha+beta")  # label-only, on-claim, no twin
    r4 = door(trigger, ops_json=o4)
    seen.append(f"mixed attach: ungrouped={r4.get('ungrouped')!r}")
    if not (ra4.get("cogs_cost_structure_group")
            and rb4.get("cogs_cost_structure_group")
            and not r4.get("ungrouped")):
        fails.append("a legitimate legacy attach was refused - the "
                     "duplicate guard is over-eager")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _weekly_install_ops(price=2400.0):
    """A Thornfield-shaped single weekly install row (CW-033's live shapes,
    reduced to one product so no line resolution is in play)."""
    return {
        "business_naics_6": "561730",
        "lob_models": [{
            "lob_name": "Landscaping",
            "products": [{
                "product_name": "Install job",
                "unit_name": "install job",
                "unit_price": price,
                "unit_cadence": "weekly",
                "units_per_week_capacity": 5.0,
                "units_per_period_capacity": 5.0,
                "operating_periods_per_year": 52,
                "utilization_rate": 0.66,
            }],
        }],
    }


def _r_reply_never_acks_unlanded(ctx):
    """R44 - the ack fallback never out-claims the receipt.

    THE BUG (CW-033 M1, mini's A4b live). On a redirect turn that wrote
    NOTHING, the reply shipped "Got it -- I'll update the hard goods
    checkout ticket price to 99" - the router's free prose, surviving as
    the stage acknowledgment fallback. F1(b) at this ship gate: prose that
    claims a write, or acknowledges a figure the client stated this turn,
    may never ship from a branch whose receipt carries nothing.

    Pins the fallback gate directly (the other three M1 layers - the
    redirect-consumed reference filter, the phantom-note filter, and the
    Also-recorded change filter - are inline in the stage flow and covered
    by the committed turn-3 red-proof plus the live A-series probes).
    Positive control: benign prose without a claim still ships, so a gate
    that silences everything fails as loudly as one that gates nothing.
    """
    ic = ctx.ic
    fails, seen = [], []

    def _ack(prose, user_message):
        res, note = call_compat(
            ic._build_financials_stage_acknowledgement_first,
            router_text=prose, stage_name="monthly_rent_expense",
            financials_json={}, user_message=user_message,
        )
        return str(res or ""), note

    # The A4b shape: a write-claim on a turn whose stage wrote nothing.
    ack, note = _ack(
        "Got it - I'll update the hard goods checkout ticket price to 99.",
        "One more thing - bump the hard goods ticket price to 99 instead of 95.",
    )
    seen.append(f"write-claim -> {ack[:60]!r}{note or ''}")
    if "99" in ack or "update the hard goods" in ack.lower():
        fails.append("router prose claiming an unmade write SHIPPED as the ack")

    # The figure half: receipt-claiming without a change verb.
    ack, note = _ack(
        "Thanks for sharing that - your ticket price of 99 is noted.",
        "The ticket price is 99.",
    )
    seen.append(f"figure-ack -> {ack[:60]!r}")
    if "99" in ack:
        fails.append("prose acknowledging a figure no receipt carries SHIPPED")

    # Positive control: benign prose still ships.
    ack, note = _ack(
        "Thanks - noted, and one thought on positioning.", "hello there")
    seen.append(f"benign -> {ack[:60]!r}")
    if "positioning" not in ack:
        fails.append("benign prose without a claim was silenced - the gate "
                     "is over-eager")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_midinterview_ops_never_lands(ctx):
    """R45 - mid-interview ops landings are impossible regardless of wording.

    THE BUG (CW-033 M2, mini's D1 live). The redirect DETECTOR required
    the literal words capacity/price/utilization, but the forward-move
    lander understood "7 jobs a week" - a keywordless correction landed an
    ops lever MID-INTERVIEW with a "Recorded:" receipt and no redirect,
    re-opening the off-path landing Nick retracted (A-113) through the
    back door. The fix puts the boundary AT THE WRITE DOOR:
    _apply_forward_move's ops branch refuses with the honest redirect
    whenever a financials stage is active, whatever wording carried the
    move there. This leg pins the DOOR (the choke point), not the
    detector - deleting _strip_suppressed_ops_move must not reopen it.

    Driven through the real wrapper (detect included) with a recorded
    router, so the whole reachable chain is the thing pinned. Positive
    control: the same correction at the WALL still lands 7/7, so a door
    that refuses everywhere fails as loudly as one that refuses nowhere.
    """
    fails, seen = [], []
    fin_mid = ctx.completed_fin()
    fin_mid.pop("monthly_rent_expense", None)

    # T1: the keywordless capacity correction, rent stage active.
    turn, _fin, did = ctx.turn(
        "Hang on - the install crew can do 7 jobs a week now, not 5.",
        RecordedRouter(PATCHLESS), fin=fin_mid, ops=_weekly_install_ops(),
        seed_ops=True)
    ctx.note_turn(turn)
    _f, _p, ops_db = ctx.sections(did)
    wk = product_field(ops_db, "units_per_week_capacity")
    msg = str((turn or {}).get("assistant_message") or "").lower()
    seen.append(f"mid-interview capacity -> stored wk={wk!r}")
    if not near(wk, 5.0):
        fails.append(f"a keywordless capacity correction moved the row "
                     f"mid-interview (stored {wk!r}, want 5 untouched)")
    if "recorded:" in msg:
        fails.append("the mid-interview reply claimed a receipt")
    if "haven't changed any operations" not in msg:
        fails.append("the honest refusal/redirect was not spoken")

    # T2: a volunteered FIRST-CAPTURE (null-price row) mid-interview.
    turn, _fin, did = ctx.turn(
        "By the way - we charge 650 per install job.",
        RecordedRouter(PATCHLESS), fin=copy.deepcopy(fin_mid),
        ops=_weekly_install_ops(price=None), seed_ops=True)
    ctx.note_turn(turn)
    _f, _p, ops_db = ctx.sections(did)
    price = product_field(ops_db, "unit_price")
    msg = str((turn or {}).get("assistant_message") or "").lower()
    seen.append(f"mid-interview first-capture -> stored price={price!r}")
    if price is not None:
        fails.append(f"a volunteered price first-capture LANDED "
                     f"mid-interview ({price!r})")
    if "recorded:" in msg:
        fails.append("the first-capture reply claimed a receipt")

    # Positive control: the same capacity correction at the WALL lands.
    turn, _fin, did = ctx.turn(
        "Hang on - the install crew can do 7 jobs a week now, not 5.",
        RecordedRouter(PATCHLESS), fin=ctx.completed_fin(),
        ops=_weekly_install_ops(), seed_ops=True)
    ctx.note_turn(turn)
    _f, _p, ops_db = ctx.sections(did)
    wk = product_field(ops_db, "units_per_week_capacity")
    seen.append(f"wall control -> stored wk={wk!r}")
    if not near(wk, 7.0):
        fails.append(f"the WALL landing broke (stored {wk!r}, want 7) - "
                     "the door refuses everywhere")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_stated_cadence_never_rebased(ctx):
    """R46 - a stated cadence is never silently re-based.

    THE BUG (CW-033 M3, mini's D3 live on Sumac). "Capacity should be 40
    a week, not 34" on a contract row (12 operating periods/yr) wrote
    period=40 - the model then held 9.23 a week - and the receipt
    ("Recorded: capacity 40") hid the misread. The stated cadence is PART
    of the stated number: matching cadence lands as today, a differing
    one CONVERTS into the canonical cell (40/wk -> 173.33/period), an
    ambiguous one ASKS, and the receipt always speaks the client's own
    cadence.

    Driven through the real wrapper at the wall on the Sumac-shaped
    contract row and a weekly install row. Positive control: a matching
    cadence still lands identity (7 a week -> 7), so a reconciler that
    converts everything fails as loudly as none at all.

    KNOWN LIMITS, deliberately not pinned here (open fix shapes handed to
    VS in the turn-4 audit): the cadence parse is message-scoped, so an
    unrelated cadence word ("We invoice monthly") can mis-bind; and the
    disclosure's stored-value reference filter lacks the cadence bypass,
    so a cadence-differing restatement of the stored NUMBER dead-ends.
    Pinning today's exact scope would pin those bugs (the round-8
    lesson); this leg pins only the re-base law itself.
    """
    fails, seen = [], []

    # T1: the D3 shape - differing cadence CONVERTS, receipt speaks it.
    turn, _fin, did = ctx.turn(
        "Our mowing route capacity should be 40 a week, not 34.",
        RecordedRouter(PATCHLESS), fin=ctx.completed_fin(),
        ops=copy.deepcopy(OPS), seed_ops=True)
    ctx.note_turn(turn)
    _f, _p, ops_db = ctx.sections(did)
    per = product_field(ops_db, "units_per_period_capacity")
    msg = str((turn or {}).get("assistant_message") or "")
    seen.append(f"40-a-week on contract row -> stored period={per!r}")
    if not (per is not None and near(per, 40.0 * 52.0 / 12.0, 0.01)):
        fails.append(f"the stated week cadence was re-based to the row "
                     f"(stored period {per!r}, want 173.33)")
    if "40 a week" not in msg.lower():
        fails.append("the receipt does not speak the client's own cadence")

    # T2: mixed cadences in one message ASK; nothing moves.
    turn, _fin, did = ctx.turn(
        "Mowing capacity should be 40 a week - call it about 170 a month.",
        RecordedRouter(PATCHLESS), fin=ctx.completed_fin(),
        ops=copy.deepcopy(OPS), seed_ops=True)
    ctx.note_turn(turn)
    _f, _p, ops_db = ctx.sections(did)
    per = product_field(ops_db, "units_per_period_capacity")
    msg = str((turn or {}).get("assistant_message") or "")
    seen.append(f"mixed cadences -> stored period={per!r}")
    if not near(per, 34.0):
        fails.append(f"an ambiguous cadence WROTE (stored {per!r}, want 34)")
    if "Quick check on that capacity change" not in msg:
        fails.append("the ambiguous cadence did not ask")

    # T3: a weekly row told a monthly figure converts (26/mo -> 6/wk).
    turn, _fin, did = ctx.turn(
        "Actually the install crew can handle 26 jobs a month.",
        RecordedRouter(PATCHLESS), fin=ctx.completed_fin(),
        ops=_weekly_install_ops(), seed_ops=True)
    ctx.note_turn(turn)
    _f, _p, ops_db = ctx.sections(did)
    wk = product_field(ops_db, "units_per_week_capacity")
    msg = str((turn or {}).get("assistant_message") or "")
    seen.append(f"26-a-month on weekly row -> stored wk={wk!r}")
    if not (wk is not None and near(wk, 6.0, 0.01)):
        fails.append(f"a monthly figure on a weekly row did not convert "
                     f"(stored {wk!r}, want 6.0)")
    if "26 a month" not in msg.lower():
        fails.append("the conversion receipt does not speak '26 a month'")

    # Positive control: matching cadence still lands identity.
    turn, _fin, did = ctx.turn(
        "Hang on - the install crew can do 7 jobs a week now, not 5.",
        RecordedRouter(PATCHLESS), fin=ctx.completed_fin(),
        ops=_weekly_install_ops(), seed_ops=True)
    ctx.note_turn(turn)
    _f, _p, ops_db = ctx.sections(did)
    wk = product_field(ops_db, "units_per_week_capacity")
    seen.append(f"matching cadence -> stored wk={wk!r}")
    if not near(wk, 7.0):
        fails.append(f"a matching cadence no longer lands (stored {wk!r}, "
                     "want 7)")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_carveout_survives_the_no(ctx):
    """R47 - a carve-out purchase survives the no.

    THE BUG (CW-033 B3, confirmed live by the turn-3 audit then fixed).
    "No, none of it was bought this year - but we did spend 15,000 on a
    mower" is a solicited answer to the capex question carrying BOTH a
    real exclusion (the 380k asset base) and a real purchase (the
    mower). _capex_answer_expresses_none read the negative lead and
    forced 0 - the mower's 15,000 died on a solicited answer. The
    carve-out figure IS the capex; the excluded base still cannot land.

    Positive controls: the plain explicit-no still expresses none
    (A-115b intact) and the "No wait" correction lookahead still never
    matches, so a classifier that stopped recognising refusals fails as
    loudly as one that swallows carve-outs.
    """
    ic = ctx.ic
    fails, seen = [], []
    both = ("None of it this year, we've got about 380,000 sitting there - "
            "but we did spend 15,000 on a mower.")
    plain = ("Not really, no. Over the years we've built up about 380,000 "
             "worth of trucks and greenhouse equipment, but none of that "
             "was bought this year.")
    correction = "No wait, it was 380,000."

    got = ic._capex_answer_expresses_none(both)
    seen.append(f"but-we-did -> expresses_none={got!r}")
    if got:
        fails.append("the but-we-did answer was read as a none-answer - "
                     "the mower's 15,000 dies into a forced 0")
    got = ic._capex_answer_expresses_none(plain)
    seen.append(f"plain no -> {got!r}")
    if not got:
        fails.append("the plain explicit-no stopped expressing none "
                     "(A-115b broken)")
    got = ic._capex_answer_expresses_none(correction)
    seen.append(f"no-wait -> {got!r}")
    if got:
        fails.append("the 'No wait' correction matched none - the "
                     "lookahead is broken")

    carve = getattr(ic, "_capex_carveout_figure", None)
    if carve is None:
        fails.append("the carve-out extractor is absent - the excluded "
                     "380,000 has no scoping rule")
    else:
        got = carve(both)
        seen.append(f"carve-out figure -> {got!r}")
        if got != 15000.0:
            fails.append(f"the carve-out figure is {got!r}, want the "
                         "mower's 15,000 (never the excluded 380,000)")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


def _r_discovery_removed_never_resurrected(ctx):
    """R48 - a removed discovery line never comes back; the wrap gate sees
    what is persisted.

    THE BUG (Corvid Press e3af1f24, fixed bd1a541 - Nick's Option A ruling
    2026-08-17). Discovery kept its own per-candidate yes/no reader and
    carry_stream_discovery rebuilt "confirmed" from answer=="yes" alone: a
    line the client said to DROP ("you'd be double-counting") was re-
    appended from the stale yes-latch on every ops turn and again at
    finalize - a null-driver row the wrap gate (a fresh finalize snapshot
    that never carried it) never saw, so the wrap fired and the phantom
    killed the run at the boundary.

    Three teeth, all offline, no GPT, no DB:
      (1) ORDINARY TURN: the shared reader's snapshot omits a latched
          discovery row -> carry_stream_discovery must NOT re-append it
          (the client's removal stands). Red at b8f2697 (row resurrected).
      (2) FINALIZE SEAM: a yes-latch whose row is gone from the shared
          model mints NOTHING (never from the latch); a null-driver
          before-row is never restored. Red at b8f2697 (fresh null row).
      (3) GATE == PERSISTED: align_gate_rows_with_persisted forces a
          persisted null-driver discovery row INTO the gate snapshot and
          strips a discovery row the persisted model lacks. Absent at
          b8f2697 (named gap, secondary to the behavioural reds).
    Positive controls: a discovery row present in both keeps its stamp; a
    FILLED before-row lost by the finalize re-derivation is carried
    forward from that row (the legitimate job carry-forward keeps).
    """
    import copy as _copy

    from client_intake_and_finmo.intake_coherence import gpt_stream_discovery as sd

    fails, seen = [], []
    ORIGIN = getattr(sd, "STREAM_DISCOVERY_ORIGIN", "discovery_confirmed")

    def _row(name, price=None, cap=None, origin=None):
        return {"product_name": name, "unit_name": None, "unit_cadence": None,
                "units_per_week_capacity": cap, "units_per_period_capacity": None,
                "utilization_rate": None, "unit_price": price, "origin": origin}

    def _names(ops):
        return [str(p.get("product_name")) for lob in (ops.get("lob_models") or [])
                for p in (lob.get("products") or [])]

    def _latch(answer):
        return {"asked": True, "candidates": [
            {"label": "Digital printing services", "answer": answer},
            {"label": "Copying and duplicating services", "answer": "no"}]}

    def _has_digital(ops):
        return any("digital" in n.lower() for n in _names(ops))

    def _find(ops, label):
        # local finder: the baseline module has no _find_row helper
        for lob in (ops.get("lob_models") or []):
            for p in (lob.get("products") or []):
                if str(p.get("product_name") or "").strip().lower() == label.lower():
                    return p
        return None

    real = [{"lob_name": "Commercial print", "products": [_row("Standard commercial print job", 690, 30)]},
            {"lob_name": "Wide-format", "products": [_row("Wide-format job", 420, 9)]}]

    def _with_digital(price=None, cap=None):
        return _copy.deepcopy(real) + [
            {"lob_name": "Digital printing services",
             "products": [_row("Digital printing services", price, cap, origin=ORIGIN)]}]

    # (1) ordinary turn - the shared reading dropped the discovery row.
    for legacy in ("yes", "added"):
        before = {"lob_models": _with_digital(), "stream_discovery": _latch(legacy)}
        after = {"lob_models": _copy.deepcopy(real), "stream_discovery": _latch(legacy)}
        out = sd.carry_stream_discovery(_copy.deepcopy(before), after)
        seen.append("turn/%s: rows=%r" % (legacy, _names(out)))
        if _has_digital(out):
            fails.append("ordinary-turn carry re-appended the removed discovery row "
                         "(latch answer %r) - the client's drop is undone" % legacy)

    # (2) finalize seam - never minted from the latch, never a null-driver restore.
    try:
        before_null = {"lob_models": _with_digital(), "stream_discovery": _latch("yes")}
        out = sd.carry_stream_discovery(_copy.deepcopy(before_null),
                                        {"lob_models": _copy.deepcopy(real)}, restore_dropped=True)
        seen.append("finalize/null-before: rows=%r" % _names(out))
        if _has_digital(out):
            fails.append("finalize carry restored a NULL-driver discovery row "
                         "(a phantom reaches the boundary)")
        no_row = {"lob_models": _copy.deepcopy(real), "stream_discovery": _latch("yes")}
        out = sd.carry_stream_discovery(_copy.deepcopy(no_row),
                                        {"lob_models": _copy.deepcopy(real)}, restore_dropped=True)
        seen.append("finalize/yes-latch-no-row: rows=%r" % _names(out))
        if _has_digital(out):
            fails.append("finalize carry minted a discovery row from the yes-latch alone")
        # positive control: a FILLED before-row lost by the re-derivation is carried.
        before_filled = {"lob_models": _with_digital(300, 12), "stream_discovery": _latch("added")}
        out = sd.carry_stream_discovery(_copy.deepcopy(before_filled),
                                        {"lob_models": _copy.deepcopy(real)}, restore_dropped=True)
        got = _find(out, "Digital printing services")
        seen.append("finalize/filled-before: restored price=%r" % (got and got.get("unit_price"),))
        if got is None or got.get("unit_price") != 300 or got.get("origin") != ORIGIN:
            fails.append("finalize carry no longer carries a FILLED discovery row the "
                         "re-derivation lost (positive control broken)")
    except TypeError as exc:
        fails.append("carry_stream_discovery has no finalize seam (restore_dropped): %s" % exc)

    # positive control: present in both -> kept and stamped.
    both = {"lob_models": _with_digital(300, 12), "stream_discovery": _latch("added")}
    out = sd.carry_stream_discovery(_copy.deepcopy(both), _copy.deepcopy(both))
    got = _find(out, "Digital printing services")
    if got is None or got.get("origin") != ORIGIN:
        fails.append("a discovery row present in both snapshots lost its stamp / row")

    # (3) gate == persisted.
    align = getattr(sd, "align_gate_rows_with_persisted", None)
    if align is None:
        fails.append("align_gate_rows_with_persisted is absent - the wrap gate can "
                     "judge a snapshot the persisted state disagrees with")
    else:
        persisted = {"lob_models": _with_digital(), "stream_discovery": _latch("added")}
        out = align(persisted, {"lob_models": _copy.deepcopy(real)})
        got = _find(out, "Digital printing services")
        seen.append("gate+persisted-null-row: gate row price=%r" % (got and got.get("unit_price"),))
        if got is None or got.get("unit_price") is not None:
            fails.append("the gate snapshot does not carry the persisted null-driver "
                         "discovery row - the wrap can fire past a phantom")
        persisted2 = {"lob_models": _copy.deepcopy(real), "stream_discovery": _latch("removed")}
        out = align(persisted2, {"lob_models": _with_digital()})
        seen.append("gate-phantom/persisted-removed: rows=%r" % _names(out))
        if _find(out, "Digital printing services") is not None:
            fails.append("a discovery row the persisted model lacks survived in the "
                         "gate snapshot (a re-derivation resurrected it)")

    return not fails, (
        "; ".join(seen) + ("; FAILED: " + "; ".join(fails) if fails else ""))


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
        "c77094a", "b7586ca", _r_workbook_formula_grid, issue="WS1b floor",
        surface="workbook formula grid", proof=GOLDEN_MASTER,
        proof_note=("RE-BLESSED 2026-08-21 (baseline 01fd627 -> b7586ca, VS, Nick's "
                    "schedule-sheet cleanup). 283 leaves identical, 13 changed, "
                    "every one declared: the ELEVEN Stage Ramp Contract rows are "
                    "REMOVED (R_RAMP_01 - nothing consumed them, proven across "
                    "formulas, defined names, data validation, conditional "
                    "formatting, chart series and hyperlinks on both fixtures); "
                    "Actual Revenue QoQ Growth keeps its 26 cells but moves up "
                    "into the live driver section so its own AVERAGE references "
                    "follow; and Checks Formula Error Scan narrows from C7:W28 "
                    "to C7:W16 because the sheet is shorter. ZERO unexplained. "
                    "R31 did NOT move (finmo c36bef7c5bdb, model_input "
                    "1d50e46ab8e6) - no engine touched. Delivered values "
                    "recalculated in Excel and identical: FINMO Marketing "
                    "2,250.00, Net Income 17,021.92, Checks OK. Hiding the stub "
                    "COLUMN moves neither digest - visibility is not a cell value. "
                    "PREVIOUS: RE-BLESSED 2026-08-19d (baseline 54c1843 -> 01fd627, VS, mini's "
                    "two client-facing blockers). The grid moves by ELEVEN leaves "
                    "out of 298 and every one is declared: 5 annual cells on "
                    "Beginning Cash (=SUM(D46:G46) -> =D46, the year START) and 5 "
                    "on Ending Cash (=SUM(D61:G61) -> =G61, the year END), because "
                    "those two rows are BALANCES living on the cash-flow statement "
                    "and were being added up like flows - the sheet printed Y1 cash "
                    "of 391,730 on the cash-flow statement and 127,623 on the "
                    "balance sheet two blocks above; and the Valuation bridge rows, "
                    "where net debt moved from the end of year 5 to the valuation "
                    "date (FINMO!W84 -> FINMO!C84) on the headline row and all five "
                    "sensitivity rows, plus the two label renames that go with it. "
                    "287 leaves identical. "
                    "INSTRUMENT CORRECTION recorded with this re-bless: the ad-hoc "
                    "grid dump used for the previous purity proofs resolved "
                    "client_statements_output_excel from the HOME repo whichever "
                    "tree it was pointed at, so it compared HEAD to HEAD and would "
                    "report '0 changed' whatever had moved. THE GATE'S RESULT "
                    "WAS UNAFFECTED and mini re-proved it end to end (R32 at "
                    "5c9a8b9 -> 7 sheets, 4,185 formulas, sha cbd76463; at HEAD "
                    "-> 10 sheets, 7,779 formulas, sha 8878c405), but NOT for the "
                    "reason VS recorded: prove() does NOT put the baseline root on "
                    "sys.path. bind_root() bound <root>/python only, and the "
                    "workbook package lives at the repo ROOT, so the baseline was "
                    "resolving through python/api_handlers/intake_consult.py's own "
                    "parents[2] insert, which assert_surface() happens to trigger "
                    "before any leg. mini bound the ROOT in bind_root() so the "
                    "property is structural, not an accident of app-side code the "
                    "gate does not own. Re-verified under mini's own dump: the "
                    "01fd627 move is 25 sensitivity cells + 10 annual cash cells "
                    "changed and 2 labels renamed (7,777 shared leaves, 35 changed) "
                    "- VS's '11 of 298' counts ROWS, not formula cells; same move, "
                    "different unit. NOT captured by this leg, because the grid "
                    "hashes FORMULAS only: 01fd627 also moved the Valuation input "
                    "table's 'As of' header from column E to column L (a static "
                    "string) - correct, undeclared, and invisible here. "
                    "PREVIOUS: RE-BLESSED 2026-08-19c (baseline a474c3b -> 54c1843, VS, X5: the "
                    "Valuation sheet is NEW, so the grid gains one sheet key and "
                    "nothing else moves - the annual-class fix that preceded it is "
                    "already in the baseline. "
                    "PREVIOUS: RE-BLESSED 2026-08-19b (baseline 500907d -> a474c3b, VS, the "
                    "ANNUAL-COLUMN DEFECT CLASS fix: annual aggregation now routes "
                    "by row semantics, so rate rows are AVERAGEd and Opening "
                    "balances take the year START. Grid change fully accounted "
                    "- 220 rows identical, 44 changed, every one in a declared "
                    "category (30 annual-mode, 8 Calc NA(), 6 ratio formulas), "
                    "ZERO unexplained; and the MODEL is untouched (4,362 "
                    "quarterly cells compared, the only 21 that moved are ROIC, "
                    "which was computed pre-tax and is now correct). "
                    "PREVIOUS: RE-BLESSED 2026-08-19 (baseline 96133a7 -> 500907d, VS, "
                    "Nick's restructure ruling: FINMO reads IS -> BS -> CF -> "
                    "BREAK-EVEN -> RATIOS, the CVP helper data moved to the "
                    "hidden Calc engine, and the Dashboard was rebuilt on that "
                    "engine with a macro-free period selector). ONE re-bless "
                    "bundling the whole restructure. Purity proven leaf-by-leaf "
                    "BEFORE re-baselining (Test Files/_x2_restructure_purity.py "
                    "on the grids at adafc07 vs now): 109 leaves identical, 51 "
                    "pure renumberings on FINMO/Checks, 35 new ratio labels, 1 "
                    "new sheet (Calc), Dashboard declared rebuilt, and the five "
                    "CVP helper rows proven to have ARRIVED on Calc rather than "
                    "vanished. The NUMBERS were held separately: 5,342 numeric "
                    "cells identical by (sheet, row label, column) via "
                    "Test Files/_x1_numbers_identical.py compare-labeled, and "
                    "the selector was driven in real Excel "
                    "(Test Files/_x4_toggle_live_proof.py, 17 live checks). "
                    "PREVIOUS RE-BLESS 2026-08-18 (baseline 725b374 -> 96133a7, VS, W2 "
                    "break-even below the P&L + Dashboard; ONE planned re-bless "
                    "bundled for A+B+C per docs/WRITING_PHASE_RESEARCH_2.md R5): "
                    "the Break-Even Analysis block is inserted DIRECTLY BELOW "
                    "the Income Statement on FINMO, so every Balance Sheet / "
                    "Cash Flow formula string moved by ROW RENUMBERING (+13) "
                    "and the grid gained the block rows, the CVP helper rows, "
                    "the Dashboard sheet and the Checks rows for the new "
                    "statement. Purity proven leaf-by-leaf BEFORE re-baselining "
                    "(Test Files/_w2_r32_drift_purity.py on the grids at "
                    "5c9a8b9 vs W2: 108 rows identical, 42 rows pure row-shift, "
                    "99 new W2 rows, 0 removed, 0 impure; three tampered-grid "
                    "negative controls all caught; record in "
                    "_w2_break_even_workbook_proof_20260818.txt). "
                    "RE-POINTED 2026-08-17 (baseline 9d2c41c -> 725b374, mini): "
                    "the A-124 SBA rate resolver changed the replay KEY of "
                    "_sba_business_loan_interest_rate_and_source and the "
                    "fixture (VS's _run_artifacts.py) was re-recorded for the "
                    "new key only, so every pre-A-124 baseline dies "
                    "FrozenLookupMiss (UNEARNED, no hash) - the grid digest "
                    "itself never moved (cbd76463 before and after A-124 and "
                    "after the G&A stub split 6b6f400: the CareCompanions "
                    "fixture states no current_revenue, so the stub takes the "
                    "unchanged forecast-basis fallback). "
                    "The surface neither VS SHA covers - finmo_sheet.py moved "
                    "45 lines in c77094a. Hashes sheet -> row label -> formula "
                    "strings, sorted; NOT the .xlsx bytes, which are "
                    "non-deterministic (zip metadata/timestamps) and would "
                    "false-DRIFT every run. NOTE: this needs "
                    "client_statements_output_excel/ in the baseline tree - "
                    "prove.BASELINE_PATHS was widened for exactly this, since "
                    "otherwise the module resolves from the HOME repo and the "
                    "'baseline' hash is computed with CURRENT workbook code.")),
    Leg("R49", "INVARIANT", "workbook-text-surface",
        "NEGATIVE CONTROL: the workbook's static text does not move or change",
        "01fd627", "ef62181", _r_workbook_text_surface, issue="X5 rider class",
        surface="workbook static text", proof=GOLDEN_MASTER,
        proof_note=("RE-BLESSED 2026-08-21b (baseline b7586ca -> ef62181, VS): ONE cell, "
                    "Audit Source!A47, from the Depreciatoin typo fix. R32 did NOT "
                    "move - no formula changed. "
                    "PREVIOUS: RE-BLESSED 2026-08-21 (baseline 2757e22 -> b7586ca, VS, Nick's "
                    "schedule-sheet cleanup). 2,550 cells identical; 24 gone, 1 new, "
                    "3 changed in place, all on Revenue Drivers and Checks and all "
                    "declared: the 11 Stage Ramp row labels, their 11 GPT-selected "
                    "stage ramp contract details, the section header, and the QoQ "
                    "label OLD address are gone; the QoQ label reappears at its new "
                    "address; the two Checks range strings and the section-header "
                    "position change in place. ZERO unexplained. "
                    "PREVIOUS: RE-BLESSED 2026-08-20 (baseline 66ce906 -> 2757e22, VS, "
                    "R-MKTG-03 phase 2 + A-129). 70862e7bdfad, 2,575 -> 2,577 "
                    "cells. The drift is ENTIRELY on Cover and is a pure "
                    "one-row shift: the contents index gained a Valuation line "
                    "at position 19 (A-129 - the sheet was built and never "
                    "indexed, so a client had no route to it), and every row "
                    "below moved down one. Leaf-by-leaf: 5 added, 3 removed, 20 "
                    "changed, and every changed cell is a label that MOVED "
                    "rather than changed - zero content differs. "
                    "The Marketing Schedule tab does NOT appear in this digest, "
                    "and that is the honest position rather than an oversight: "
                    "the frozen fixture carries no marketing_schedule_json, so "
                    "the builder correctly does not create the sheet. THE NEW "
                    "TAB IS THEREFORE UNPINNED BY BOTH GOLDENS. Closing that "
                    "needs a marketing payload in the fixture, which re-keys the "
                    "R31/R32 baselines - a separate declared change, not "
                    "something to slip into this re-bless. "
                    "R32 and R31 did NOT move: no engine, and no formula change "
                    "to any pre-existing sheet. "
                    "PREVIOUS: RE-BLESSED 2026-08-19d (VS, mini's green-with-follow-ups): "
                    "91d4fa285c75 -> 4d5d81484fd8, 2,572 -> 2,575 cells. The three "
                    "cells are the em-dash placeholders a constant with NO as-of "
                    "date prints: _patch_reference_constants had been stamping a "
                    "date on every row including those, so real chrome differed "
                    "between the builds and dropped out for a reason that was not "
                    "true of it (mini's nit). It now shifts only fields that "
                    "actually carry a value. "
                    "ALSO CLOSED, and it was mini's finding (3), RED-PROVEN: the "
                    "tests reimplemented the INTERSECTION inline - the same "
                    "guarding-a-copy class caught in the extraction a turn earlier, "
                    "moved one layer up - and that copy had ALREADY drifted, "
                    "carrying no date filter, so the staticness tests asserted "
                    "against a surface the leg does not pin. Deleting the whole "
                    "intersection from production left all 8 passing. The rule is "
                    "now surface.static_intersection at module level, imported by "
                    "the tests with the leg's own _DATE_TEXT; mini's exact tamper "
                    "(delete the intersection AND the filter) now fails 2 tests, "
                    "and a new test asserts the date filter is applied at all. "
                    "mini's finding (5) is documented rather than fixed: build 2 "
                    "cannot prime the frozen lookups (the recorded keys belong to "
                    "the other business) and makes ~4,292 live reference-table "
                    "calls. Exposure MEASURED at zero pinned cells twice over, so "
                    "it is a dependency and not a leak - written down in "
                    "alt_single_line_payload because its failure mode is quiet. "
                    "mini's finding (4), the multi-line gap, is CLOSED AS "
                    "WON'T-FIX with a number and it corrects the framing in this "
                    "note's previous entry: a third build cannot buy it, because "
                    "the pin is an INTERSECTION and a multi-line third member only "
                    "SHRINKS it back toward 1,942. The honest price is a second "
                    "multi-line PAIR and a UNION - four builds, 5.8s -> 11.6s - and "
                    "it buys TWO genuinely new static labels. If ever wanted it is "
                    "its own leg (R50), never a dilution of R49. "
                    "PREVIOUS: RE-BLESSED 2026-08-19c (VS, Nick's WIDEN ruling): the second "
                    "sample now matches the first's LINE COUNT. mini measured the "
                    "gap and it was the bigger half of the leg - 674 of 2,608 "
                    "cells escaped and only 41 were genuinely per-draft; the rest "
                    "were ROW-SHIFT drops, because the multi-line second sample "
                    "pushed everything below a per-line block onto a different "
                    "address. FINMO's whole ratio-analysis block, Calc's "
                    "cost-structure labels, Model Inputs' label column, W2's "
                    "break-even headers and 459 Checks cells were unpinned for "
                    "having MOVED rather than for being per-draft - the exact "
                    "class the leg exists to catch. "
                    "Nick asked for the cheapest fix and specifically NOT a third "
                    "sample. The answer was not to ADD a build but to CHANGE the "
                    "second one: Larkspur Nail Studio, one revenue line like the "
                    "first, different name, city, state, NAICS, industry, product, "
                    "staff and every figure. Layout aligns, identity does not. "
                    "MEASURED: 1,942 -> 2,572 cells pinned, all nine sections Nick "
                    "named now covered, at the SAME cost of two builds (2.9s each). "
                    "SECOND LEAK FOUND AND CLOSED WHILE MEASURING, and it was live "
                    "before this change: the Valuation reference block prints each "
                    "constant's citation, source and as-of date - live data Nick's "
                    "loader refreshes - and both builds read the same table, so "
                    "'BizBuySell Insight Report, Q2 2026' and '20-year CAGR 1.98% "
                    "(through 2026-04-01)' were pinned into the golden. A correct "
                    "data refresh would have turned R49 red. The date regex could "
                    "not catch it because 'Q2 2026' is not a date - the same trap "
                    "the wall clock set, in a shape the list did not know. Fixed "
                    "the way mini fixed the clock: the second build reads DIFFERENT "
                    "reference data (_patch_reference_constants, found-not-listed, "
                    "patching nothing is a SETUP gap), so those cells fall out by "
                    "construction while the headers above them stay pinned. "
                    "Verified: zero hits for CareCompanions / Larkspur / Raleigh / "
                    "Asheville / the draft id / 2026 / 1996 / Q2 2026 / CAGR / "
                    "BizBuySell / Damodaran, and the digest is byte-identical with "
                    "the wall clock moved to 2027-01-30. "
                    "mini's finding (3) also closed: the extraction is now "
                    "surface.text_cells_of at module level and the tests IMPORT it "
                    "instead of reimplementing it - proven by deleting the formula "
                    "filter from the real extraction, which now fails 2 tests where "
                    "before all 7 passed through a production edit. The tautological "
                    "independence control was replaced by one asserting the filter's "
                    "EFFECT (no pinned cell is a formula, over 1,000 formulas "
                    "actually turned away). New digest 91d4fa285c75; R32 unchanged "
                    "at 8878c405e17d. "
                    "PREVIOUS: BLESSED 2026-08-19 at 66ce906 (VS, on Nick's ruling). The "
                    "surface R32 cannot see: R32 hashes FORMULAS, so labels, "
                    "headers, section titles and static source text are outside "
                    "it entirely. 01fd627 moved the Valuation 'As of' header "
                    "from column E to column L inside a RE-BLESSED commit and no "
                    "golden master could have noticed - mini caught it by "
                    "reading the diff, which is exactly the kind of catch that "
                    "should not depend on someone reading a diff. On a document "
                    "a client pays for, a misplaced or mojibake label is a real "
                    "defect. "
                    "SEPARATE FROM R32 BY RULING, not by accident: the two "
                    "surfaces change for different reasons, so folding text into "
                    "the formula grid would re-bless the math golden on every "
                    "wording tweak, and a golden that churns for cosmetics is one "
                    "nobody reads before blessing. Each re-blesses on its own "
                    "terms. "
                    "KEYED BY CELL ADDRESS because MOVING is the failure mode "
                    "that created the leg; a label-keyed hash would have called "
                    "the As-of move identical. "
                    "WHAT COUNTS AS STATIC IS EARNED, NOT DECLARED: the workbook "
                    "is built for TWO DIFFERENT BUSINESSES (the frozen "
                    "single-line fixture and the multi-line one, different name "
                    "and city) and only text identical at the same address in "
                    "both is pinned - so the client's name, its city, per-line "
                    "revenue labels and every per-draft value drop out by "
                    "construction rather than by a hand-written exclusion list "
                    "somebody has to remember to maintain. Live as-of dates, "
                    "which refresh from FRED and Damodaran, are dropped by shape "
                    "on top of that: pinning them would turn a correct data "
                    "refresh into a red leg and teach everyone to bless without "
                    "reading. "
                    "RE-BLESSED 2026-08-19 at HEAD (mini's audit of the first "
                    "bless). The first bless was CLOCK-DEPENDENT: 'Cover'!C12 "
                    "renders %d %B %Y and the drop-by-shape regex only knew the "
                    "month-first form, so '19 August 2026' - today's wall clock, "
                    "identical in both builds because both ran in the same "
                    "second - was pinned into the golden. Proven, not argued: "
                    "with the clock moved to 2026-08-20 the digest went "
                    "6d1e65edbfe9 -> bd37bb3ced66 with nothing wrong in the "
                    "build, so R49 would have gone red the next morning and "
                    "taught exactly the bless-without-reading habit the ruling "
                    "was written to prevent. The bless-time check that missed it "
                    "was TAUTOLOGICAL: it re-applied the same regex the surface "
                    "had already filtered by, so it could never fail. "
                    "The fix earns time-staticness the same way it earns "
                    "identity-staticness - the second business is built AT A "
                    "DIFFERENT WALL CLOCK (1996-03-07), so anything derived from "
                    "today differs between the builds and drops out by "
                    "construction; the widened regex is now only a second line "
                    "of defence. The clock scan FINDS its targets in the "
                    "workbook package rather than naming one module, and "
                    "patching nothing is a SETUP gap, never a pass. Verified "
                    "after the fix: digest 4157868b6f89 identical at two "
                    "different wall clocks, 1,934 cells over 15 sheets, and none "
                    "of CareCompanions / Raleigh / Thistledown / Burlington - "
                    "the gate fixture's REAL identity, which the first bless "
                    "never probed - present anywhere. "
                    "KNOWN COVERAGE GAP, stated in the evidence line rather "
                    "than implied away: 1,934 of the first workbook's 2,608 text "
                    "cells are pinned. The 674 unpinned are mostly ROW-SHIFT "
                    "drops - the second business has two revenue lines to the "
                    "first's one, so FINMO's ratio-analysis labels, Calc's "
                    "cost-structure labels and ~44% of Checks sit at different "
                    "addresses and escape. Widening that is a scope decision "
                    "for Nick, not a silent re-bless. "
                    "R32's digest is UNCHANGED at 8878c405e17d across both the "
                    "shared-door refactor and this fix.")),
    Leg("R31", "INVARIANT", "single-line-unchanged",
        "NEGATIVE CONTROL: a single-line draft's persisted payloads do not move",
        "c77094a", "ef62181", _r_single_line_unchanged, issue="WS1b floor",
        surface="persisted model_input_json + finmo_json", proof=GOLDEN_MASTER,
        proof_note=("RE-BLESSED 2026-08-21 (baseline 5c9a8b9 -> ef62181, VS): ONE emitted "
                    "label typo corrected, Depreciatoin -> Depreciation. Purity "
                    "proven leaf-by-leaf: 3,472 leaves in finmo_json, exactly ONE "
                    "different - /cash_flow[2]/label. No VALUE moved anywhere. "
                    "Nothing matched on the misspelling, so this is a display fix. "
                    "PREVIOUS: RE-BLESSED 2026-08-19 (baseline 725b374 -> 5c9a8b9, VS): W1 "
                    "added finmo_json['break_even'], so the finmo digest moved by "
                    "EXACTLY that key and nothing else - proven by stripping it: "
                    "finmo-minus-break_even hashes to 24e38de4dc98, the pre-W1 "
                    "baseline digest, byte for byte (Test Files/_w1_r31_diff, "
                    "re-verified at HEAD on 2026-08-19). model_input is untouched "
                    "at 1d50e46ab8e6. The leg had been QUARANTINED out of the gate "
                    "verdict since W1; re-pointing restores it before production "
                    "use. mini still owes the independent audit of the W1-X5 stack. "
                    "PREVIOUS: RE-POINTED 2026-08-17 (baseline 5716ba4 -> 725b374, mini): "
                    "NOT a re-bless - the digests did not move (model_input "
                    "1d50e46a / finmo 24e38de4 before A-124, after A-124, and "
                    "after the G&A stub split 6b6f400). The A-124 SBA rate "
                    "resolver changed the replay KEY of _sba_business_loan_"
                    "interest_rate_and_source and the fixture was re-recorded "
                    "for the new key only, so pre-A-124 baselines die "
                    "FrozenLookupMiss (UNEARNED, no hash) instead of hashing. "
                    "KNOWN BLIND SPOT: the CareCompanions fixture states no "
                    "current_revenue, so the G&A STUB (stated/stated since "
                    "6b6f400) takes the forecast-basis fallback here - this "
                    "floor does not exercise the stub denominator; the "
                    "red-proof Test Files/_redproof_ga_stub_denominator.py "
                    "(Millgate) does. "
                    "RE-BLESSED 2026-08-14 (baseline 9d2c41c -> 5716ba4): the "
                    "ruled opening-PPE 5y straight-line depreciation (7b26ff6, "
                    "Nick ratified) legitimately moved every business with "
                    "opening assets, incl. this fixture (ppe=15,000). Purity "
                    "proven leaf-by-leaf before re-baselining - EVERY moved "
                    "leaf traces to the depreciation schedule and its "
                    "arithmetic descendants, zero others "
                    "(_mini_cw032_drift_purity_20260814.txt, instrument "
                    "Test Files/_mini_cw032_drift_purity.py). "
                    "Five of six businesses are single-line. This leg cannot "
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
        surface="consultant patch schema",
        proof_note=("PROMOTED 2026-08-14: the prove harness reported the "
                    "baseline red is BEHAVIOURAL (the leg reds at 9d2c41c on "
                    "its own assertion, not on an import crash), so the "
                    "STRUCTURAL_ABSENCE label was dropped per its own note. "
                    "Original absence rationale, kept for the record: "
                    "line_split_confidence = 0 and split_rationale = 0 "
                    "occurrences at 9d2c41c - the schema fields did not "
                    "exist there.")),
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
    Leg("R37", "REGRESSION", "transport-keys-never-persist",
        "a transport key is consumed at its door, never stored",
        "858987b", "53daa0b", _r_transport_keys_never_persist,
        issue="CW-031 round 8 fix 1", surface="scoped correction path",
        proof_note=("Baseline red is BEHAVIOURAL: at 53daa0b the correction "
                    "path persisted both keys verbatim (measured 12/12 on "
                    "live turns in the round-7 audit) while the door still "
                    "wrote the rows, so the leg reds on the stored key with "
                    "its positive control green. Its positive control is the "
                    "written rows, so a path that stopped consuming the keys "
                    "fails as loudly as one that stores them.")),
    Leg("R38", "REGRESSION", "inference-never-stored-as-structure",
        "an inference is never stored as structure; the net asks",
        "56717dd", "858987b", _r_inference_never_stored,
        issue="CW-031 round 9 fix 1",
        surface="per-line COGS write door + issue registry",
        proof_note=("Four teeth, each red at 858987b for its own reason: the "
                    "round-8 net minted an inferred all-lines group on the "
                    "uniform write, clobbered the declared partial stamp, "
                    "minted on an echo, and the gate passed the inferred "
                    "result. Positive controls: the rates still land and a "
                    "DECLARED all-lines group still passes the gate, so a "
                    "door that stopped writing or a gate that fails "
                    "everything cannot satisfy this leg.")),
    Leg("R39", "REGRESSION", "separation-clears-the-group",
        "separation clears the group and retires the stale label by name",
        "56717dd", "858987b", _r_separation_clears_group,
        issue="CW-031 round 9 fix 2",
        surface="per-line COGS write door",
        proof_note=("At 858987b cogs_separate_lines is not consumed and no "
                    "coherence pass exists, so the separated row keeps its "
                    "group and the abandoned member keeps the stale label - "
                    "red behaviourally, no crash. Positive control: a "
                    "DISJOINT declared group must survive byte-identical, so "
                    "a pass that clears everything fails as loudly as one "
                    "that clears nothing.")),
    Leg("R40", "REGRESSION", "membership-is-data",
        "group membership is stored data beside the label, not a label parse",
        "1cb145d", "5dcbca4", _r_membership_is_data,
        issue="CW-031 round 10 fix 1",
        surface="per-line COGS write door + group coherence pass",
        proof_note=("At 5dcbca4 (round-9 code) the coherence pass rebuilt "
                    "membership by splitting the label on '+', so a group "
                    "containing a '+'-named product retired itself in the "
                    "declaring call and no member list was stored - red "
                    "behaviourally on both teeth. Positive controls: a real "
                    "separation still retires the survivor by name and an "
                    "agreeing mixed (list + legacy label-only) group "
                    "survives, so a pass that retires everything or one "
                    "that never retires both fail.")),
    Leg("R41", "REGRESSION", "match-never-lies",
        "a match never names an ambiguous field, a near-miss never claims a match",
        "b0607e0", "55f0ae0", _r_match_never_lies,
        issue="CW-031 round 11 fixes 1-2",
        surface="no-write match-on-file sentence",
        proof_note=("At 55f0ae0 (round-10 code) the scan named the FIRST "
                    "matching leaf (walk order put rent before interest) and "
                    "the 0.5% tolerance matched a 0.32% correction - red "
                    "behaviourally on both teeth. Positive controls: a "
                    "unique-name figure still names its field and float-dust "
                    "still matches, so never-naming and a dead tolerance "
                    "both fail.")),
    Leg("R42", "REGRESSION", "identity-is-the-member-set",
        "group identity is the stored member set, not the label string",
        "b0607e0", "55f0ae0", _r_identity_is_member_set,
        issue="CW-031 round 11 fix 3",
        surface="per-line COGS write door + group coherence pass",
        proof_note=("At 55f0ae0 the coherence pass held one claim per label: "
                    "the 'shared:a+b+c' collision read as one incoherent "
                    "claim and retired all four rows (the second declaration "
                    "killed the first AND itself), and the agreeing member "
                    "sets under a stale twin's label retired the fresh "
                    "declaration with the twin - red behaviourally on both "
                    "teeth. Positive control: the O4b overlap retire still "
                    "fires, so a pass that never retires fails too.")),
    Leg("R43", "REGRESSION", "legacy-tier-is-a-law",
        "the legacy tier is a law, not an accident of order",
        "e8d1f3b", "b0607e0", _r_legacy_tier_is_law,
        issue="CW-031 round 12",
        surface="per-line COGS write door + group coherence pass",
        proof_note=("At b0607e0 (round-11 final) the parse-fallback "
                    "partition was minted by whichever legacy row iterated "
                    "first (`elif not _parts`) and that row joined it even "
                    "off-claim, so the stale-FIRST ordering retired the "
                    "coherent remainder; and the duplicate-name twin "
                    "attached to the fresh members partition because the "
                    "name-set dedup hid it - red behaviourally on both "
                    "teeth. Positive controls: stale-LAST retires alone and "
                    "the agreeing mixed attach lands, both green at "
                    "baseline, so retire-everything and an over-eager "
                    "guard fail too.")),
    Leg("R44", "REGRESSION", "reply-never-acks-unlanded-ops-figure",
        "the ack fallback never out-claims the receipt",
        "02effe1", "6d38c54", _r_reply_never_acks_unlanded,
        issue="CW-033 M1", surface="financials stage ack ship gate",
        proof_note=("At 6d38c54 the fallback shipped the router's free "
                    "prose ungated (and took no user_message - call_compat "
                    "bridges the signature), so the A4b write-claim and the "
                    "figure-ack both shipped - red behaviourally. Positive "
                    "control: benign prose still ships, so a gate that "
                    "silences everything fails too. The other three M1 "
                    "layers are inline in the stage flow; the committed "
                    "turn-3 red-proof and the live A-series cover them.")),
    Leg("R45", "REGRESSION", "midinterview-ops-landing-impossible",
        "mid-interview ops landings are impossible regardless of wording",
        "02effe1", "6d38c54", _r_midinterview_ops_never_lands,
        issue="CW-033 M2", surface="forward-move ops write door",
        proof_note=("At 6d38c54 the keywordless '7 jobs a week' wording "
                    "slipped past the redirect detector and the door landed "
                    "it mid-interview with a 'Recorded:' receipt - red "
                    "behaviourally through the real wrapper, detect "
                    "included. Pins the DOOR: the boundary must hold with "
                    "the detector deleted. Positive control: the WALL "
                    "landing still works, green at both commits.")),
    Leg("R46", "REGRESSION", "stated-cadence-never-rebased",
        "a stated cadence is never silently re-based",
        "02effe1", "6d38c54", _r_stated_cadence_never_rebased,
        issue="CW-033 M3", surface="forward-move ops write door",
        proof_note=("At 6d38c54 '40 a week' on the 12-period contract row "
                    "stored period=40 (9.23/wk), the mixed-cadence message "
                    "wrote instead of asking, and 26-a-month landed raw on "
                    "the weekly row - red behaviourally on three teeth. "
                    "Positive control: a matching cadence still lands "
                    "identity at both commits. Deliberately does NOT pin "
                    "the message-scoped cadence parse or the disclosure "
                    "filter (open fix shapes in the turn-4 audit) - "
                    "pinning today's scope would pin those bugs.")),
    Leg("R47", "REGRESSION", "carveout-figure-survives-the-no",
        "a carve-out purchase survives the no",
        "02effe1", "6d38c54", _r_carveout_survives_the_no,
        issue="CW-033 B3", surface="capex answer classifier",
        proof_note=("At 6d38c54 _capex_answer_expresses_none read the "
                    "but-we-did answer as a none-answer (True) - red "
                    "behaviourally on the classifier tooth; the absent "
                    "extractor line is secondary evidence, not the red. "
                    "Positive controls: the plain explicit-no and the "
                    "'No wait' lookahead hold at both commits.")),
    Leg("R48", "REGRESSION", "discovery-removed-never-resurrected",
        "a removed discovery line never comes back; the wrap gate sees the persisted rows",
        "bd1a541", "b8f2697", _r_discovery_removed_never_resurrected,
        issue="Corvid e3af1f24", surface="stream discovery carry-forward + wrap gate",
        proof_note=("At b8f2697 carry_stream_discovery rebuilt 'confirmed' from "
                    "answer=='yes' and re-appended the row the shared reading "
                    "omitted (ordinary turn) and minted a fresh null row at the "
                    "finalize seam - red behaviourally on teeth (1)+(2); the "
                    "absent align_gate_rows_with_persisted is the named gap "
                    "for tooth (3), secondary. Positive controls: present-in-"
                    "both keeps its stamp; a FILLED before-row lost at "
                    "finalize is carried from that row.")),
    Leg("R13", "REGRESSION", "fitted-cogs-covered",
        "covered NAICS proposes materials-only with a band",
        "eb7529b", "613a19a", _r_fitted_cogs_covered, tier=LIVE),
    Leg("R14", "REGRESSION", "fitted-cogs-fallback",
        "uncovered NAICS still yields a fitted band (no dead estimator)",
        "582cef7", "7b9f481", _r_fitted_cogs_fallback, tier=LIVE),
]
