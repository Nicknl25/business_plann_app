# -*- coding: utf-8 -*-
"""The completed-financials surface, driven through the REAL turn chain.

Entry point is api_handlers.intake_consult._run_financials_turn_and_sync -
the exact function a live financials turn hits, doors and all. There is no
fixture path here on purpose: a fixture would pass on the broken build.
"""
import copy
import hashlib
import inspect
import json
import re
import sys
import uuid


class SignatureUnbridgeable(RuntimeError):
    """The baseline needs an argument the leg cannot honestly supply.

    Raised loudly rather than silently guessing: a fabricated argument would
    make the leg measure the fixture instead of the build.
    """


def call_compat(fn, _supply=None, **kwargs):
    """Call `fn` adapting to ITS OWN signature, not to today's.

    WHY THIS EXISTS. Several legs call a production helper directly. When a
    fix changes that helper's signature, the leg's call raises TypeError on
    the baseline - exit code 1, which prove() used to read as a clean red.
    That is a proof about an API surface, not about behaviour: it says a
    parameter list changed, and says NOTHING about whether the bug behaved.
    Worse, it hides the case where the property being pinned ALREADY HELD at
    the baseline (I10 @ 7b9f481: cogs_fit_band was already there).

    So: drop arguments the target does not accept at this commit, and fill
    arguments it requires but today's caller no longer passes - sourcing them
    from the app's OWN production wiring, never inventing a value. The leg
    then reaches its assertion on both sides and the red is behavioural.

    -> (result, note) where note names every adaptation, so the evidence line
    says out loud that the call shape was bridged.
    """
    params = inspect.signature(fn).parameters
    var_kw = any(p.kind is p.VAR_KEYWORD for p in params.values())
    call, notes = {}, []
    for key, val in kwargs.items():
        if var_kw or key in params:
            call[key] = val
        else:
            notes.append(f"dropped {key} (not a parameter at this commit)")
    for name, p in params.items():
        if name in call or p.default is not p.empty:
            continue
        if p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        supplier = (_supply or {}).get(name)
        if supplier is None:
            raise SignatureUnbridgeable(
                f"{getattr(fn, '__name__', fn)} requires {name!r} at this "
                f"commit and the leg has nothing honest to pass for it")
        value = supplier() if callable(supplier) else supplier
        if value is None:
            raise SignatureUnbridgeable(
                f"{getattr(fn, '__name__', fn)} requires {name!r} and the "
                f"app's own wiring did not yield one")
        call[name] = value
        notes.append(f"supplied {name} from the app's own production wiring")
    return fn(**call), ("; ".join(notes) or "no adaptation needed")

# The structural wall the persona is standing in front of when the
# correction arrives. This is the last_assistant a real turn sees at this
# surface, and it is what a frozen build repeats back verbatim.
WALL = (
    "The profit math clears, but one structural wall still stands: your "
    "team costs are 76% of revenue, and a labor-intensive business like "
    "this one is financed at no more than 70% - a lender won't finance a "
    "plan above that level. The honest way through is revenue (pricing "
    "and volume are the levers we can work right now)."
)

# Sumac Ridge Grounds shape - the business the CW-026 live run froze on.
OPS = {
    "business_naics_6": "561730",
    "business_type": "Commercial grounds maintenance",
    "unit_price": 520.0,
    "units_per_period_capacity": 34.0,
    "operating_periods_per_year": 12.0,
    "utilization_rate": 0.82,
    "lob_models": [{
        "lob_name": "Grounds Care",
        "products": [{
            "product_name": "Property contract",
            "unit_name": "property contract",
            "unit_price": 520.0,
            "unit_cadence": "contract",
            "units_per_period_capacity": 34.0,
            "operating_periods_per_year": 12.0,
            "utilization_rate": 0.82,
        }],
    }],
}

PEOPLE = {
    "people": [
        {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
         "annual_wage": 34000.0},
        {"full_name": "Rosalie Fenn", "role_title": "Crew Lead",
         "annual_wage": 37000.0},
    ],
    "rest_of_team_payroll_year1": 62000.0,
}

BASE_FIN = {
    "current_revenue": 175000.0,
    "cogs_percent_of_revenue": 0.15,
    "cogs_basis": "ratio",
    "current_payroll": 133000.0,
    "current_num_employees": 4,
    "marketing_total_year1": 1200.0,
    "monthly_rent_expense": 340.0,
    "gna_total_year1": 8000.0,
    "capex_total_year1": 0.0,
    "initial_assets": 18000.0,
    "initial_lease": 0.0,
    "total_debt_outstanding": 9000.0,
    "other_monthly_debt_payments": 260.0,
    "annual_interest_payment": 700.0,
    # 2,600 not 2,400: the marketing battery leg states $2,400 and a
    # figure that matches a stored value is read as a restatement. That
    # collision would be a fixture artifact, not app behaviour.
    "annual_principal_payment": 2600.0,
    "cash_on_hand": 6000.0,
    "ar_balance": 9000.0,
    "ap_balance": 1500.0,
    "inventory_balance": 1100.0,
    "cash_strategy": "preserve_cash",
    "funding_preference": "debt",
    "_financials_revenue_intro_done": True,
    "_financials_marketing_stage_done": True,
}

# Thistledown: a TWO-line business - retail materials beside a service line.
# cogs_percent_of_line_revenue on every product is what makes the per-line
# COGS % rows exist; without it the all-or-nothing rule keeps per-line
# INACTIVE and R26 would be measuring a single-blend payload.
MULTI_OPS = {
    "business_naics_6": "441222",
    "business_type": "Bicycle retail and repair",
    "lob_models": [
        {"lob_name": "Retail", "products": [{
            "product_name": "Bicycle", "unit_name": "bicycle",
            "unit_price": 60.0, "unit_cadence": "unit",
            "units_per_period_capacity": 300.0,
            "operating_periods_per_year": 12.0, "utilization_rate": 0.7,
            "cogs_percent_of_line_revenue": 0.52}]},
        {"lob_name": "Workshop", "products": [{
            "product_name": "Service hour", "unit_name": "service hour",
            "unit_price": 85.0, "unit_cadence": "hour",
            "units_per_period_capacity": 120.0,
            "operating_periods_per_year": 12.0, "utilization_rate": 0.6,
            "cogs_percent_of_line_revenue": 0.22}]},
    ],
}
# The blend is the revenue-weighted mean of the two lines - the invariant
# R26 pins. initial_assets pairs with the derived ppe seed.
MULTI_FIN = {
    "current_revenue": 224640.0,
    "cogs_percent_of_revenue": round((12600.0 * 0.52 + 6120.0 * 0.22)
                                     / 18720.0, 6),
    "cogs_basis": "ratio",
    "current_payroll": 90000.0,
    "initial_assets": 40000.0,
    "monthly_rent_expense": 2500.0,
    "marketing_total_year1": 12000.0,
}
MULTI_Y1 = {"company_revenue_total_year1": 224640.0}

# Larkspur: a SECOND SINGLE-LINE business, for the R49 text surface only.
#
# The text pin decides what is "static" by intersecting two builds at the same
# cell address. Thistledown was the obvious second sample and it was the wrong
# one: two revenue lines against CareCompanions' one pushes every block below a
# per-line block onto a different ROW, so 633 cells of real chrome - FINMO's
# whole ratio-analysis block, Calc's cost-structure labels, 459 Checks cells,
# Model Inputs' label column - dropped out for having MOVED, not for being
# per-draft, and went unpinned (mini, 2026-08-19).
#
# So the second sample matches the first's LINE COUNT and differs in everything
# else: name, city, state, NAICS, industry, product, staff, every figure. The
# layout lines up, the identity does not, and the pin covers 2,588 cells
# instead of 1,942 at exactly the same cost - two builds, not three.
ALT_OPS = {
    "business_naics_6": "812113",
    "business_type": "Nail salon",
    "unit_price": 61.0,
    "units_per_period_capacity": 47.0,
    "operating_periods_per_year": 12.0,
    "utilization_rate": 0.74,
    "lob_models": [{
        "lob_name": "Salon Services",
        "products": [{
            "product_name": "Manicure appointment",
            "unit_name": "appointment",
            "unit_price": 61.0,
            "unit_cadence": "appointment",
            "units_per_period_capacity": 47.0,
            "operating_periods_per_year": 12.0,
            "utilization_rate": 0.74,
        }],
    }],
}

ALT_PEOPLE = {
    "people": [
        {"full_name": "Marisol Vega", "role_title": "Owner / Technician",
         "annual_wage": 41000.0},
        {"full_name": "June Okafor", "role_title": "Technician",
         "annual_wage": 33000.0},
    ],
    "rest_of_team_payroll_year1": 22000.0,
}

ALT_FIN = {
    "current_revenue": 209000.0,
    "cogs_percent_of_revenue": 0.21,
    "cogs_basis": "ratio",
    "current_payroll": 96000.0,
    "current_num_employees": 3,
    "marketing_total_year1": 4400.0,
    "monthly_rent_expense": 1900.0,
    "gna_total_year1": 11000.0,
    "capex_total_year1": 0.0,
    "initial_assets": 26000.0,
    "initial_lease": 0.0,
    "total_debt_outstanding": 14000.0,
    "other_monthly_debt_payments": 310.0,
    "annual_interest_payment": 900.0,
    "annual_principal_payment": 3100.0,
    "cash_on_hand": 8000.0,
    "ar_balance": 4000.0,
    "ap_balance": 2200.0,
    "inventory_balance": 3300.0,
    "cash_strategy": "preserve_cash",
    "funding_preference": "debt",
    "_financials_revenue_intro_done": True,
    "_financials_marketing_stage_done": True,
}
ALT_Y1 = {"company_revenue_total_year1": 209000.0}

PATCHLESS = {"action": "answer_readonly", "assistant_message": "", "patch": None}


def text_cells_of(wb):
    """{sheet: {cell address: text}} for ONE workbook - every non-formula string.

    MODULE LEVEL, not a closure, because the R49 negative controls have to be
    able to import it. mini's audit caught the tests reimplementing this and
    proved the point the hard way: all seven passed unchanged before and after
    the production surface was edited, so they were guarding a copy and would
    have kept passing while the real extraction rotted (2026-08-19).
    """
    out = {}
    for ws in getattr(wb, "worksheets", []) or []:
        cells = {}
        for row_cells in ws.iter_rows():
            for cell in row_cells:
                val = cell.value
                if not isinstance(val, str):
                    continue
                val = val.strip()
                # A formula is the OTHER surface. This one line is what keeps
                # R32 and R49 independent, so an edit to a formula never churns
                # the text golden.
                if not val or val.startswith("="):
                    continue
                cells[cell.coordinate] = val
        if cells:
            out[ws.title] = cells
    return out


class RecordedRouter(object):
    """A recorded router double: deterministic, no GPT, no tokens.

    This stands in for the LLM call only. Everything downstream of it -
    the doors, attribution, normalize, forward-move, THE RECALC, the
    persistence sync - is the real production chain. The live router is
    available behind --live-router for the legs that need to prove
    attribution end to end.
    """

    def __init__(self, ret=None):
        self.ret = ret or PATCHLESS
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return copy.deepcopy(self.ret)


class Surface(object):
    def __init__(self, conn, read_conn):
        self.conn = conn
        self.read_conn = read_conn
        import api_handlers.intake_consult as ic

        self.ic = ic

    # ---- the mandatory surface assertion -------------------------------
    def completed_fin(self):
        ic = self.ic
        fin = ic._ensure_financials_stage_defaults(copy.deepcopy(BASE_FIN))
        for st in list(getattr(ic, "_FINANCIALS_STAGE_ORDER", ())):
            spec = ic._financials_stage_spec(st)
            for f in (spec.get("completion_fields") or ()):
                if fin.get(f) is None:
                    fin[f] = 1.0
        return fin

    def assert_surface(self):
        """MANDATORY. A suite that enters anywhere other than the
        completed-financials surface is not testing the surface that
        breaks. Raises SystemExit(2) rather than reporting RED, because a
        wrong entry state is a broken gate, not a broken build."""
        fin = self.completed_fin()
        active = self.ic._next_financials_stage(fin)
        print(f"SURFACE  completed-financials  (active stage = {active!r})")
        if active is not None:
            print("SETUP FAILED: not at the completed-financials surface - "
                  "_next_financials_stage(fin) must be None. Refusing to run; "
                  "a green here would be meaningless.")
            raise SystemExit(2)
        return fin

    # ---- draft seeding + readback --------------------------------------
    def fresh_draft(self, fin=None, people=None, ops=None):
        from client_intake_and_finmo.intake_consult_draft import (
            create_draft, append_messages,
        )

        d = create_draft(self.conn, client_id=f"rgate{uuid.uuid4().hex[:8]}")
        draft_id = str(d.get("draft_id") or d.get("id") or "").strip()
        kw = {}
        if ops is not None:
            # Seed the ops section too, so a later SQL read-back is a real
            # round-trip rather than reading a row that was never written.
            kw["operating_model_json"] = copy.deepcopy(ops)
        append_messages(
            self.conn, draft_id=draft_id, new_messages=[],
            people_json=copy.deepcopy(people or PEOPLE),
            financials_json=fin or self.completed_fin(),
            active_focus="financials", **kw
        )
        return draft_id

    def persist_ops(self, draft_id, ops):
        """Persist an ops object as the HANDLER's caller would.

        This is the live seam: after the turn function returns, the handler
        persists sections from its OWN references. If a landing rebound a
        copy instead of mutating through, this carries the stale object and
        the correction evaporates. Legs replaying that seam must pass the
        very object they handed to the turn - see Surface.turn(share_ops).
        """
        from client_intake_and_finmo.intake_consult_draft import append_messages

        append_messages(self.conn, draft_id=draft_id, new_messages=[],
                        operating_model_json=ops)

    def sections(self, draft_id):
        """Stored fields, read back from the DB on a fresh autocommit
        connection. Never assert on the ack text - assert here."""
        from client_intake_and_finmo.intake_consult_draft import get_draft

        row = get_draft(self.read_conn, draft_id=draft_id) or {}

        def _j(key):
            v = row.get(key)
            if isinstance(v, str):
                try:
                    return json.loads(v or "{}")
                except Exception:
                    return {}
            return dict(v or {})

        return _j("financials_json"), _j("people_json"), _j("operating_model_json")

    def cogs_baseline(self, ops, revenue, people=None):
        """Resolve a COGS baseline through whatever call shape THIS build
        wants. -> (baseline, note)

        The estimator is pulled from the app's own `_financials_baseline_
        estimators()` - the exact callable the production caller passed at
        commits that required it - so the band the leg judges is the band the
        app would have produced, not one the harness manufactured.
        """
        ic = self.ic

        def _estimator():
            getter = getattr(ic, "_financials_baseline_estimators", None)
            if getter is None:
                return None
            try:
                return (getter() or (None,))[0]
            except Exception:
                return None

        return call_compat(
            ic._resolve_cogs_baseline_or_raise,
            _supply={"estimate_cogs_percent_from_context": _estimator},
            conn=self.conn, ops_json=ops,
            shared_context={"operating_model": ops,
                            "people_capability": copy.deepcopy(people or PEOPLE)},
            financials_year1_json={"company_revenue_total_year1": float(revenue)},
        )

    draft_source = ""
    draft_input_sha = ""

    # A golden digest must be a function of its INPUTS ONLY. The construction
    # path reaches for the wall clock in four places:
    #   finmo_bridge._forecast_anchor_date_iso()      <- datetime.now(), ALWAYS
    #   finmo_bridge:2909  start_dt = datetime.utcnow()          (fallback)
    #   model_inputs:60/62 datetime.utcnow()                     (fallback)
    #   model_inputs:987   start_date or utcnow().date()         (fallback)
    # The first fires on every build; the other three only when a date is
    # missing. So: freeze the anchor, and then PROVE the fallbacks stayed
    # asleep by asserting the payload's own start_date is the frozen value.
    #
    # Freezing an input is the correct fix. Loosening the comparison - a
    # tolerance, an ignored field - would trade a false DRIFT for the ability
    # to miss a REAL one, and DRIFT is only worth top billing if it is always
    # real.
    FROZEN_ANCHOR = "2026-01-01"

    def _frozen_build(self, *, facts, ops, people, fin, year1, marketing):
        """(mij, finmo, note) from FROZEN INPUTS ONLY, or (None, None, why).

        The one construction path both golden legs and the per-line invariant
        share, so a payload fix lands once. Freezes the wall clock, proves the
        fallbacks stayed asleep, and self-checks determinism.

        THE PPE PAIR. forecast_starting_ppe is NOT a free constant: the engine
        enforces forecast_starting_ppe_must_equal_authoritative_balance_sheet,
        so the seed and the client's initial_assets are two halves of ONE
        consistent state. 0.0 with no assets is consistent; 40,000 with 40,000
        is consistent; mixing them is a payload that could never come out of
        production. The seed is therefore DERIVED from the financials rather
        than pinned - still a pure function of the frozen inputs, because the
        financials themselves are frozen.
        """
        import hashlib as _hashlib
        import json as _json

        from client_intake_and_finmo import finmo_bridge

        original = getattr(finmo_bridge, "_forecast_anchor_date_iso", None)
        if original is None:
            return None, None, ("ANCHOR-UNFROZEN: finmo_bridge."
                                "_forecast_anchor_date_iso is gone, so the "
                                "digest would depend on the current date - "
                                "refusing to hash")

        facts = dict(facts or {})
        facts.setdefault("business_name", "Frozen Fixture")
        facts["start_date"] = str(facts.get("start_date") or "2020-01-01")
        raw_assets = (fin or {}).get("initial_assets")
        ppe = float(raw_assets) if raw_assets not in (None, "") else 0.0

        def _build():
            return finmo_bridge.apply_derived_driver_policies_to_model_input(
                finmo_bridge.build_python_model_input_json(
                    business_facts=facts,
                    ops_json=copy.deepcopy(ops),
                    people_json=copy.deepcopy(people or {}),
                    financials_json=copy.deepcopy(fin or {}),
                    financials_year1_json=copy.deepcopy(year1 or {}),
                    marketing_model_json=copy.deepcopy(marketing or {}),
                    forecast_starting_ppe=ppe,
                    maintenance_rate=0.05,
                ))

        def _digest(payload):
            return _hashlib.sha256(_json.dumps(
                payload, sort_keys=True, separators=(",", ":"),
                default=str).encode("utf-8")).hexdigest()

        finmo_bridge._forecast_anchor_date_iso = (
            lambda *a, **k: self.FROZEN_ANCHOR)
        try:
            mij = _build()
            # DETERMINISM SELF-CHECK: build twice, compare. Catches any
            # non-input dependency that varies WITHIN a run - a uuid, a
            # random, an id()-ordered dict - without enumerating them.
            if _digest(mij) != _digest(_build()):
                return None, None, (
                    "NONDETERMINISTIC: two builds from identical frozen inputs "
                    "produced different payloads - something in the "
                    "construction path is not a function of its inputs, and a "
                    "golden digest over it would eventually cry wolf")
            finmo = finmo_bridge.build_python_finmo_json(model_input_json=mij)
        finally:
            finmo_bridge._forecast_anchor_date_iso = original

        stamped = str((mij or {}).get("start_date") or "")
        if stamped != self.FROZEN_ANCHOR:
            return None, None, (
                f"ANCHOR-LEAK: payload start_date is {stamped!r}, not the "
                f"frozen {self.FROZEN_ANCHOR!r} - a wall-clock fallback fired "
                f"and the digest is no longer a function of its inputs")

        return mij, finmo, (
            f"frozen inputs: anchor={self.FROZEN_ANCHOR}, "
            f"start_date={facts['start_date']}, ppe={ppe:,.1f} "
            f"(= initial_assets, the pair the engine enforces), "
            f"maintenance_rate=0.05; build repeated -> identical digest")

    def single_line_payloads(self):
        """(draft, model_input_json, finmo_json, note) for the byte floor.

        Kwargs shape lifted VERBATIM from the committed reference,
        Test Files/_ws1b_intake_smoke.py (T7/T9) - the payload VS proved
        passes producer- AND consumer-side contract validation, signature
        identical at 9d2c41c.

        WHY THE CONSTANTS ARE FIXED: these feed GOLDEN-MASTER legs, which ask
        "given identical input, does construction produce identical output at
        both commits" - not "does production derive the right rate". Both
        sides get the same values, so what is under test is construction
        determinism. FOR A BEHAVIOURAL LEG THIS WOULD BE WRONG and the
        derived values would be required. Do not derive these back.

        Shared by R31 and R32 so each proves ALONE - legs run one at a time
        under --only, so R32 cannot rely on R31 having populated anything.

        THE INPUT IS COMMITTED BYTES, NOT A QUERY (round 9). This used to
        pick a draft off `intake_consult_drafts` by a pin/oldest-first
        ladder. Every ordering fix made the pick more stable without making
        it FROZEN: a prune, a restore, or a delete of the chosen row still
        moved the golden input, and a golden master over a moving input
        produces DRIFT that names nothing. The ladder is deleted rather than
        kept as a fallback - a fallback to the live table is exactly the
        silent path back to DB-derived digests, and dead code invites a
        future re-point onto it.

        BOTH HALVES OF THE INPUT ARE FROZEN. The draft is one half;
        `build_python_model_input_json` reads eight reference-table loaders
        on its own account, which is the other. `prime_frozen_lookups()`
        must wrap the build or the digest is still a function of database
        state. It patches process-wide, so restore() goes in a `finally`:
        under --prove each leg is its own subprocess, but in battery mode
        R26's multi-line payload shares this process and would ask those
        loaders questions nobody recorded.

        A MISS IS AN HONEST SETUP, NEVER A LIVE READ. If a build asks a
        reference table something the capture never recorded - most likely
        on the BASELINE side, whose app code is older - FrozenLookupMiss
        fires. That is reported as a gap and the leg goes UNEARNED. Falling
        back to a live query would restore the exact defect this removed,
        and would do it invisibly.
        """
        from . import _run_artifacts as fx

        draft = copy.deepcopy(fx.SINGLE_LINE_DRAFT)
        source = (f"FROZEN draft {str(draft.get('id') or '')[:8]} "
                  f"({(draft.get('facts') or {}).get('business_name') or '?'})"
                  f" - committed fixture, no DB query in this path")
        patched, restore = fx.prime_frozen_lookups()
        if not patched:
            self.draft_source = "frozen lookups not primed"
            return None, None, None, (
                "SETUP: prime_frozen_lookups() patched ZERO bindings, so the "
                "reference tables would be read LIVE and the digest would "
                "stop being a function of committed bytes - refusing to "
                "hash. The app package is probably not importable at this "
                "root, or the loaders were renamed")
        try:
            mij, finmo, note = self._frozen_build(
                facts=draft["facts"], ops=draft["ops"], people=draft["people"],
                fin=draft["fin"], year1=draft["year1"],
                marketing=draft["marketing"])
        except fx.FrozenLookupMiss as exc:
            self.draft_source = source
            return None, None, None, (
                f"SETUP: FrozenLookupMiss - this build asked a reference "
                f"table something the fixture never recorded, so the digest "
                f"could not be a function of committed bytes. Reported, NOT "
                f"routed around with a live read: {exc}"[:400])
        finally:
            restore()
        if mij is None or finmo is None:
            # ANCHOR-UNFROZEN / ANCHOR-LEAK / NONDETERMINISTIC. Refused, not
            # hashed: a digest that is not a pure function of its inputs
            # would pass for months and then fire a false DRIFT.
            self.draft_source = source
            return None, None, None, f"{note}; {source}"
        rows = ((mij.get("sections") or {}).get("revenue") or []
                if isinstance(mij, dict) else [])
        if len(rows) < 3:
            self.draft_source = source
            return draft, None, None, (
                f"only {len(rows)} revenue rows from the frozen input - too "
                f"thin to pin; a hash over a stub matches itself and proves "
                f"nothing; {source}")
        # INPUT IDENTITY, hashed and printed beside the outputs. Recipe
        # UNCHANGED from the live-query era on purpose: it is what makes
        # round 8 and round 9 comparable at all, and it is the digest the
        # fixture's own PROVENANCE records.
        self.draft_input_sha = hashlib.sha256(json.dumps(
            {k: draft[k] for k in
             ("facts", "ops", "people", "fin", "year1", "marketing")},
            sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")).hexdigest()
        self.draft_source = source
        return draft, mij, finmo, f"{note}; {source}"

    def multi_line_payload(self):
        """(model_input_json, finmo_json, note) for a TWO-LINE business.

        R26's payload used to be a hand-written model_input_json, so it sat
        outside the shared construction path and every payload fix missed it.
        It now goes through the same production builder with the same frozen
        inputs - and the ops carry cogs_percent_of_line_revenue on EVERY
        product row, because that is what makes the per-line rows exist at
        all: the invariant leg has nothing to measure without them.
        """
        return self._frozen_build(
            facts={"business_name": "Thistledown Cycles"},
            ops=copy.deepcopy(MULTI_OPS), people={},
            fin=copy.deepcopy(MULTI_FIN), year1=copy.deepcopy(MULTI_Y1),
            marketing={})

    @staticmethod
    def _patch_clock(when):
        """Build AS IF today were `when`. -> (restore, gap).

        FOUND, NOT LISTED. A hardcoded "patch cover_sheet.date" would be a
        promise that somebody notices the next wall-clock read added to the
        builder; instead every module of the workbook package is scanned for
        one and each match is patched. Finding NONE is a gap, not a pass -
        the builder has read the clock since it was written, so zero matches
        means the scan broke and the second business would silently be built
        at the same clock as the first, which is precisely the hole this
        closes (mini, 2026-08-19: 'Cover'!C12 carried today's date straight
        into the blessed golden, so R49 would have gone red the next day).
        """
        import datetime as _dt
        import pkgutil

        class _Frozen(_dt.date):
            @classmethod
            def today(cls):
                return when

        class _FrozenDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime(when.year, when.month, when.day)

            @classmethod
            def utcnow(cls):
                return _dt.datetime(when.year, when.month, when.day)

        try:
            import client_statements_output_excel as pkg
        except ImportError as exc:
            return None, f"cannot patch the clock: {exc}"
        undo, patched = [], []
        for mod in list(sys.modules.values()):
            name = getattr(mod, "__name__", "") or ""
            if not name.startswith(pkg.__name__):
                continue
            src = ""
            try:
                src = inspect.getsource(mod)
            except Exception:
                pass
            _d = getattr(mod, "date", None)
            if ("date.today()" in src and isinstance(_d, type)
                    and issubclass(_d, _dt.date)):
                undo.append((mod, "date", mod.date))
                mod.date = _Frozen
                patched.append(f"{name}.date")
            _dtm = getattr(mod, "datetime", None)
            if (("datetime.now()" in src or "datetime.utcnow()" in src)
                    and isinstance(_dtm, type)
                    and issubclass(_dtm, _dt.datetime)):
                undo.append((mod, "datetime", mod.datetime))
                mod.datetime = _FrozenDT
                patched.append(f"{name}.datetime")
        if not patched:
            for mod, attr, old in undo:
                setattr(mod, attr, old)
            return None, ("the clock scan patched NOTHING in "
                          f"{pkg.__name__} - the builder has always read the "
                          "wall clock somewhere, so zero matches means the "
                          "scan is broken and the two businesses would be "
                          "built at the SAME clock, which is how a build date "
                          "gets pinned into a golden master")

        def restore():
            for mod, attr, old in undo:
                setattr(mod, attr, old)

        return restore, ""

    def _build_workbook(self, builder, from_row, info=None, clock=None):
        """(workbook, gap) for ONE business, through the production builder.

        Extracted so the formula grid (R32) and the text surface (R49) enter
        the builder by the SAME door. Two copies of this assembly would drift
        apart, and the first symptom would be two goldens disagreeing about
        what the workbook is.

        `clock` builds this workbook AS IF it were that date. It exists for
        the text surface, which earns staticness by DIFFERING: the second
        business is built at a different wall clock so that any text derived
        from today's date differs between the two builds and drops out of the
        intersection, the same way the client's name does. R32 never passes
        it, so the formula grid's door is unchanged.
        """
        if builder is None or from_row is None:
            return None, "no builder/from_row supplied"
        if not info:
            d, mij, finmo, note = self.single_line_payloads()
            if not d or mij is None or finmo is None:
                return None, (note or "no single-line draft")
            info = {"draft": d, "mij": mij, "finmo": finmo}

        # THE RUN ARTIFACTS. payroll_headcount is GPT-authored during the
        # planning run (gpt_payroll_author.py) - nothing offline derives it,
        # and the boundary gate validates it against a 15-field contract.
        # Three ways to supply it, one honest:
        #   live DB read   -> the row can move between the baseline run and
        #                     the current run of the SAME prove, so the golden
        #                     input moves and DRIFT fires for nothing;
        #   synthesized    -> a stub tests the stub, and drifts against the
        #                     contract without anyone noticing;
        #   FROZEN FIXTURE -> the real artifact, captured once and pinned, so
        #                     the input never moves and the OUTPUT is what is
        #                     under test.
        try:
            from . import _run_artifacts
        except ImportError:
            return None, (
                "no frozen run artifacts - payroll_headcount is GPT-authored "
                "during a planning run and cannot be derived offline. Capture "
                "it ONCE: python \"Test Files/_capture_workbook_fixture.py\" "
                "6feac758   (writes replay_gate/_run_artifacts.py; commit it). "
                "Deliberately NOT read live: a moving input makes a golden "
                "master cry wolf.")

        src = dict((info.get("draft") or {}).get("row") or {})
        row = {"draft_id": (info.get("draft") or {}).get("id")}
        row.update(src)
        row["model_input_json"] = info.get("mij")
        row["finmo_json"] = info.get("finmo")
        row["payroll_headcount"] = copy.deepcopy(
            _run_artifacts.PAYROLL_HEADCOUNT)
        row["debt_schedule"] = copy.deepcopy(_run_artifacts.DEBT_SCHEDULE)
        row["planning_run_json"] = copy.deepcopy(
            _run_artifacts.PLANNING_RUN_JSON)
        if not row["payroll_headcount"]:
            return None, ("the frozen payroll_headcount fixture is empty - "
                          "re-capture from a draft that completed a run; a "
                          "hollow payload hashes stably and proves nothing")
        self.artifact_provenance = getattr(_run_artifacts, "PROVENANCE", {})
        restore_clock = None
        if clock is not None:
            restore_clock, gap = self._patch_clock(clock)
            if gap:
                # NEVER build both businesses at the same clock silently: the
                # whole point is that wall-clock text differs and drops out.
                return None, gap
        try:
            wb = builder(from_row(row))
        except Exception as exc:
            return None, (f"{type(exc).__name__}: {exc}"[:300]
                          + " (builder refused the payload)")
        finally:
            if restore_clock:
                restore_clock()
        names = list(getattr(wb, "sheetnames", []) or [])
        if not names:
            return None, ("the builder returned a Workbook with NO sheets - "
                          "this is a BUILD failure, not an extraction one")
        return wb, ""

    def workbook_formula_grid(self, builder=None, from_row=None, draft=None):
        """{sheet: {row label: [formula strings]}} from the in-memory BUILDER.

        Deterministic, unlike the exporter's .xlsx bytes (zip metadata and
        timestamps), which would false-DRIFT on every run.

        NOTE ON data_only: it is NOT in play here. build_client_financial_
        model_workbook never saves or reloads - it returns a live openpyxl
        Workbook, so the "=..." strings are still strings. The first attempt
        produced nothing for a duller reason: the builder opens with a
        CONSUMER-SIDE boundary gate over all five JSON payloads, and a bare
        `except Exception: return {}` swallowed the ContractViolation whole.
        The gap is now recorded and reported, because a leg that cannot say
        WHY it produced nothing is a leg that wastes a whole prove cycle.
        """
        self.grid_gap = ""
        wb, gap = self._build_workbook(builder, from_row, draft)
        if gap:
            self.grid_gap = gap
            return {}

        grid = {}
        for ws in getattr(wb, "worksheets", []) or []:
            rows = {}
            for row_cells in ws.iter_rows():
                label = None
                formulas = []
                for cell in row_cells:
                    val = cell.value
                    if isinstance(val, str) and val.startswith("="):
                        formulas.append(val)
                    elif label is None and isinstance(val, str) and val.strip():
                        label = val.strip()
                if formulas:
                    key = label or f"row{row_cells[0].row}"
                    rows.setdefault(key, []).extend(formulas)
            if rows:
                grid[ws.title] = rows
        if not grid:
            names = list(getattr(wb, "sheetnames", []) or [])
            self.grid_gap = (f"the builder produced {len(names)} sheets "
                             f"({', '.join(names[:6])}) but NOT ONE '=' string "
                             f"- sheets built, so this is EXTRACTION, not build")
        return grid

    #: Text that IS a date is never pinned. The valuation inputs carry live
    #: as-of dates that refresh from FRED and Damodaran; pinning them would
    #: turn a correct data refresh into a red leg, which teaches everyone to
    #: re-bless without reading. Nick's ruling, 2026-08-19.
    #: BOTH ORDERS of the spelled-out form. The day-first one is not
    #: hypothetical: the Cover sheet renders "%d %B %Y", so "19 August 2026"
    #: slipped past the month-first pattern and was blessed into the golden
    #: at 66ce906 - a leg that would have gone red the following morning with
    #: nothing wrong with the build (mini, 2026-08-19). The regex is now the
    #: SECOND line of defence, not the first: the two businesses are built at
    #: different wall clocks, so anything derived from today differs and drops
    #: out by construction, the way an exclusion list can never be trusted to.
    _DATE_TEXT = re.compile(
        r"\d{4}-\d{2}-\d{2}"
        r"|\d{1,2}/\d{1,2}/\d{2,4}"
        r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}"
        r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
        r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}")

    #: The second business is built AS IF it were this date. Far from any
    #: plausible today in day, month AND year, so a build-date stamp cannot
    #: collide at any granularity - not the day, not "August 2026", not
    #: "2026". Fixed rather than today-plus-an-offset because a golden master
    #: over a moving input is the thing this leg exists to prevent.
    _SECOND_CLOCK = (1996, 3, 7)

    def alt_single_line_payload(self):
        """(model_input_json, finmo_json, note) for the SECOND single-line
        business. Same shape as the first, same number of revenue lines,
        nothing else in common."""
        return self._frozen_build(
            facts={"business_name": "Larkspur Nail Studio"},
            ops=copy.deepcopy(ALT_OPS), people=copy.deepcopy(ALT_PEOPLE),
            fin=copy.deepcopy(ALT_FIN), year1=copy.deepcopy(ALT_Y1),
            marketing={})

    @staticmethod
    def _patch_reference_constants():
        """Build the second workbook against DIFFERENT reference data.
        -> (restore, gap).

        The Valuation input table prints, for every constant, its citation, its
        source and its as-of date - live data from valuation_reference_constants
        that Nick's loader refreshes on demand. Both builds read the same table,
        so those strings were identical and got pinned into the golden: "Q2 2026",
        "20-year CAGR 1.98% (through 2026-04-01)". A correct data refresh would
        then turn R49 red, which is the bless-without-reading habit the leg was
        written to prevent - the same trap the wall clock set, in a form the
        date regex does not catch because "Q2 2026" is not a date.

        Reference data is CONTENT, not chrome. So it earns its exclusion the way
        identity and the clock do: the second build gets different values for it
        and the cells fall out of the intersection by themselves. The headers
        above them ("As of", "Basis", "Source") are chrome and stay pinned.

        FOUND, NOT LISTED - patching nothing is a gap, never a pass.
        """
        try:
            from client_statements_output_excel import valuation_sheet as _vs
        except ImportError as exc:
            return None, f"cannot patch the reference constants: {exc}"
        real = getattr(_vs, "_load_constants", None)
        if real is None:
            return None, ("valuation_sheet has no _load_constants to patch - the "
                          "reference-data exclusion would silently stop working")

        def _shifted(naics):
            out = {}
            for key, row in (real(naics) or {}).items():
                row = dict(row)
                # Values are left alone: they feed FORMULAS, not text, and
                # moving them would change the math surface R32 owns.
                row["citation"] = f"[second-sample citation for {key}]"
                row["as_of"] = "1996-03-07"
                row["source"] = "[second-sample source]"
                out[key] = row
            return out

        _vs._load_constants = _shifted
        return (lambda: setattr(_vs, "_load_constants", real)), ""

    def workbook_text_surface(self, builder=None, from_row=None):
        """{sheet: {cell address: text}} of the workbook's STATIC text.

        The surface R32 cannot see. R32 hashes FORMULAS, so a label that moves,
        changes wording, or arrives garbled is invisible to it - which is how
        the Valuation "As of" header moved from column E to column L inside a
        re-blessed commit without any golden master noticing (mini, 2026-08-19).
        On a document a client pays for, a misplaced or mojibake label is a real
        defect, so it gets its own pin.

        KEYED BY CELL ADDRESS, not by row label, because MOVING is the failure
        mode that started this. A label-keyed hash would have called the As-of
        move identical.

        WHAT COUNTS AS STATIC IS EARNED, NOT DECLARED. A hand-written exclusion
        list is a promise that someone will remember to maintain it; instead the
        workbook is built for TWO DIFFERENT BUSINESSES and only text identical
        in both, at the same address, is pinned. The client's name, its city,
        the per-line revenue labels, every per-draft value - all drop out by
        construction, because they differ. What survives is the chrome: section
        titles, statement labels, column headers, static source and citation
        text. Live dates are dropped by shape on top of that.
        """
        self.text_gap = ""
        first, gap = self._build_workbook(builder, from_row)
        if gap:
            self.text_gap = gap
            return {}
        alt = self.alt_single_line_payload()
        mij, finmo = alt[0], alt[1]
        if mij is None or finmo is None:
            self.text_gap = ("no second single-line payload - the static/dynamic "
                             "split needs two businesses")
            return {}
        restore_refs, gap = self._patch_reference_constants()
        if gap:
            self.text_gap = gap
            return {}
        # A DELIBERATELY DIFFERENT BUSINESS: different name, different city,
        # different number of revenue lines. The same fixture on both sides
        # would make every per-draft string look static and would pin the
        # client's own name into a golden master.
        # ...AND AT A DIFFERENT WALL CLOCK. Same principle as the different
        # name: text that comes from today's date differs between the two
        # builds and drops out, instead of relying on a regex to recognise
        # every date format the workbook might ever render.
        import datetime as _dt
        try:
            second, gap = self._build_workbook(builder, from_row, {
                "draft": {"id": "text-surface-probe",
                          "row": {"business_name": "Larkspur Nail Studio",
                                  "address_city": "Asheville",
                                  "address_state": "NC"}},
                "mij": mij, "finmo": finmo},
                clock=_dt.date(*self._SECOND_CLOCK))
        finally:
            restore_refs()
        if gap:
            self.text_gap = f"second business would not build: {gap}"
            return {}

        a, b = text_cells_of(first), text_cells_of(second)
        surface = {}
        for sheet in sorted(set(a) & set(b)):
            keep = {addr: txt for addr, txt in a[sheet].items()
                    if b[sheet].get(addr) == txt and not self._DATE_TEXT.search(txt)}
            if keep:
                surface[sheet] = keep
        if not surface:
            self.text_gap = ("no text survived the two-business intersection - "
                             "either the builds differ everywhere (wrong fixture) "
                             "or extraction is broken")
        # WHAT THIS PIN DOES NOT COVER, COUNTED AND SAID OUT LOUD. The two
        # samples now share a line count, so the row-shift drops are gone and
        # what escapes is per-draft text that SHOULD escape: the client's name
        # and city, its product and line names, the draft id, and the Valuation
        # reference block's citations and as-of dates. The residual gap is real
        # but narrow - labels that exist ONLY in a multi-line layout are in no
        # sample and so in no pin (mini, 2026-08-19; widened on Nick's ruling).
        kept = sum(len(v) for v in surface.values())
        self.text_coverage = (kept, sum(len(v) for v in a.values()))
        return surface

    def assembled_year1(self, fin, people=None, ops=None):
        """The handler assembles year1 from live shared context every turn.
        A minimal stub would make THE RECALC's rescale refuse (nothing
        rescalable) and mask real behaviour."""
        from client_intake_and_finmo.financials_year1 import (
            assemble_financials_year1,
        )

        shared = {
            "operating_model": copy.deepcopy(ops or OPS),
            "people_capability": copy.deepcopy(people or PEOPLE),
            "financials": copy.deepcopy(fin),
        }
        return assemble_financials_year1(shared, None) or {}

    # ---- one real turn --------------------------------------------------
    def turn(self, message, router, fin=None, people=None, ops=None,
             last_assistant=None, year1=None, business_name=None,
             share_ops=False, seed_ops=False):
        """One real turn.

        last_assistant defaults to the structural WALL, but a leg may
        override it: some guards key on what the APP itself last put on
        screen (an echoed proposal anchor is a reference, not a client
        statement), so replaying those needs the real prior message.
        The forward-move judgment compares against whatever was used
        here, via self.last_wall."""
        fin = fin or self.completed_fin()
        prior = last_assistant if last_assistant is not None else WALL
        self.last_wall = prior
        draft_id = self.fresh_draft(fin=fin, people=people,
                                    ops=(ops if seed_ops else None))
        # share_ops passes the CALLER's ops object into shared_context by
        # reference instead of deep-copying it, so the handler mutates the
        # very object the leg holds. That is what makes a persistence
        # round-trip testable: the leg can then re-persist its own reference
        # exactly as the handler's caller does.
        shared_ops = (ops if (share_ops and ops is not None)
                      else copy.deepcopy(ops or OPS))
        self.last_shared_ops = shared_ops
        shared = {
            "people_capability": copy.deepcopy(people or PEOPLE),
            "operating_model": shared_ops,
            "marketing": {},
        }
        turn, fin_out = self.ic._run_financials_turn_and_sync(
            route_intent=router,
            conn=self.conn,
            intake_context={"draft_id": draft_id},
            conversation_messages=[{"role": "assistant", "content": prior}],
            business_facts={"name": business_name or "Sumac Ridge Grounds"},
            shared_context=shared,
            last_assistant=prior,
            user_message=message,
            financials_json=fin,
            financials_year1_json=(year1 if year1 is not None
                                   else self.assembled_year1(fin, people=people, ops=ops)),
        )
        return turn, fin_out, draft_id

    last_wall = WALL


# ---- stored-field probes ------------------------------------------------
def product_field(ops_json, field):
    prod = ((ops_json.get("lob_models") or [{}])[0].get("products") or [{}])[0]
    val = prod.get(field)
    if val is None:
        val = ops_json.get(field)
    return val


def near(val, target, tol=0.5):
    try:
        return abs(float(val) - float(target)) < tol
    except (TypeError, ValueError):
        return False
