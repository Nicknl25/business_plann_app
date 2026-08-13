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

PATCHLESS = {"action": "answer_readonly", "assistant_message": "", "patch": None}


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

    def single_line_candidates(self, prefix="6feac758", limit=6):
        """Clean SINGLE-line drafts for the byte floor - PIN FIRST, then
        OLDEST FIRST. Also records WHY in `self.draft_pick`.

        WHY NOT `updated_at DESC` (the shape this replaced, mini round 7).
        That ordering made the golden legs hash WHATEVER DRAFT WAS WRITTEN
        LAST - which on this machine means a fixture draft one of the gate's
        own legs just seeded, or a persona run live in another window. Two
        costs, both fatal to a negative control:
          - the input moved between prove rounds for no app reason. Round 6
            hashed Fernhill `5ce9bba8`; minutes later the same call resolved
            to Sumac `8e84ba9d` and every digest changed. Round-over-round
            digest stability was reading the DB's churn, not the build's.
          - a draft landing BETWEEN the baseline child and the current child
            of ONE prove moves the input under the comparison and fires a
            FALSE DRIFT - the single false alarm this gate cannot afford.
        `created_at ASC` is immune both ways: a new draft always sorts last,
        so the pick changes only if the chosen row is deleted.

        THE PIN IS CURRENTLY DEAD AND SAYS SO. `6feac758` (Sunny Glaze) is
        the draft the frozen run artifacts came from, but it carries TWO
        product lines, so it can never satisfy the single-line filter - the
        old code fell through to the newest draft silently. The miss is now
        named in every evidence line. The real fix is VS's: freeze ONE
        single-line draft's sections beside its run artifacts so the floor
        stops reading this table at all.
        """
        def _lines(ops):
            return sum(len((lob or {}).get("products") or [])
                       for lob in ((ops or {}).get("lob_models") or []))

        def _j(row, key):
            v = row.get(key)
            if isinstance(v, str):
                try:
                    return json.loads(v or "{}")
                except Exception:
                    return {}
            return dict(v or {})

        def _pack(row):
            ops = _j(row, "operating_model_json")
            if _lines(ops) != 1:
                return None
            return {"id": str(row.get("draft_id") or ""), "row": dict(row),
                    "ops": ops,
                    "people": _j(row, "people_json"),
                    "fin": _j(row, "financials_json"),
                    "year1": _j(row, "financials_year1_json"),
                    "marketing": _j(row, "marketing_model_json"),
                    "facts": _j(row, "business_facts_json") or
                             {"business_name": row.get("business_name")}}

        picks, why = [], []
        cur = self.read_conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s "
                "LIMIT 1", (prefix + "%",))
            hit = cur.fetchone()
            if not hit:
                why.append(f"pin {prefix} is not in this DB")
            else:
                packed = _pack(hit)
                if packed:
                    picks.append(packed)
                    why.append(f"PINNED draft {prefix}")
                else:
                    why.append(
                        f"pin {prefix} carries "
                        f"{_lines(_j(hit, 'operating_model_json'))} product "
                        f"lines - ineligible for a SINGLE-line control")
            # Two-step on purpose: the full row carries multi-MB JSON columns,
            # so the ordering scan reads only the ops model.
            cur.execute(
                "SELECT draft_id, operating_model_json FROM "
                "intake_consult_drafts WHERE operating_model_json IS NOT NULL "
                "ORDER BY created_at ASC, draft_id ASC LIMIT 500")
            ids = [str(r["draft_id"]) for r in (cur.fetchall() or [])
                   if _lines(_j(r, "operating_model_json")) == 1]
            for draft_id in ids:
                if len(picks) >= limit:
                    break
                if any(p["id"] == draft_id for p in picks):
                    continue
                cur.execute("SELECT * FROM intake_consult_drafts WHERE "
                            "draft_id = %s LIMIT 1", (draft_id,))
                row = cur.fetchone()
                packed = _pack(row) if row else None
                if packed:
                    picks.append(packed)
        except Exception as exc:
            self.draft_pick = (f"draft lookup failed: {type(exc).__name__}: "
                               f"{exc}"[:200])
            return []
        finally:
            cur.close()
        self.draft_pick = "; ".join(why) if why else ""
        return picks

    draft_pick = ""
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
        """
        picks = self.single_line_candidates()
        if not picks:
            return None, None, None, self.draft_pick
        pick_note, tried, last = self.draft_pick, [], None
        for draft in picks:
            last = draft
            mij, finmo, note = self._frozen_build(
                facts=draft["facts"], ops=draft["ops"], people=draft["people"],
                fin=draft["fin"], year1=draft["year1"],
                marketing=draft["marketing"])
            if mij is None or finmo is None:
                # Refuse and MOVE ON, in a fixed order: a candidate that
                # cannot be hashed honestly is skipped, never hashed anyway,
                # and the skip is reported so the ladder is visible.
                tried.append(f"{draft['id'][:8]} skipped ({note.split(':')[0]})")
                continue
            rows = ((mij.get("sections") or {}).get("revenue") or []
                    if isinstance(mij, dict) else [])
            if len(rows) < 3:
                tried.append(f"{draft['id'][:8]} skipped (only {len(rows)} "
                             f"revenue rows - too thin to pin)")
                continue
            # INPUT IDENTITY, hashed and printed beside the outputs. The
            # ladder above is deterministic, but it runs SEPARATELY in the
            # baseline child and the current child - so if a candidate were
            # ever hashable on one side and not the other, the two sides
            # would silently compare DIFFERENT businesses. Hashing the input
            # makes that case surface as a DRIFT that NAMES single_line_input,
            # instead of an unexplained move in the outputs.
            self.draft_input_sha = hashlib.sha256(json.dumps(
                {k: draft[k] for k in
                 ("facts", "ops", "people", "fin", "year1", "marketing")},
                sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")).hexdigest()
            self.draft_pick = "; ".join(
                [f"draft {draft['id'][:8]}", pick_note] + tried)
            return draft, mij, finmo, f"{note}; {self.draft_pick}"
        self.draft_pick = "; ".join([pick_note] + tried)
        return last, None, None, (
            f"no hashable single-line draft among {len(picks)} candidates - "
            f"{self.draft_pick}")

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
        if builder is None or from_row is None:
            self.grid_gap = "no builder/from_row supplied"
            return {}
        info = draft
        if not info:
            d, mij, finmo, note = self.single_line_payloads()
            if not d or mij is None or finmo is None:
                self.grid_gap = note or "no single-line draft"
                return {}
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
            self.grid_gap = (
                "no frozen run artifacts - payroll_headcount is GPT-authored "
                "during a planning run and cannot be derived offline. Capture "
                "it ONCE: python \"Test Files/_capture_workbook_fixture.py\" "
                "6feac758   (writes replay_gate/_run_artifacts.py; commit it). "
                "Deliberately NOT read live: a moving input makes a golden "
                "master cry wolf.")
            return {}

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
            self.grid_gap = ("the frozen payroll_headcount fixture is empty - "
                             "re-capture from a draft that completed a run; a "
                             "hollow payload hashes stably and proves nothing")
            return {}
        self.artifact_provenance = getattr(_run_artifacts, "PROVENANCE", {})
        try:
            wb = builder(from_row(row))
        except Exception as exc:
            self.grid_gap = (f"{type(exc).__name__}: {exc}"[:300]
                             + " (builder refused the payload)")
            return {}

        # THE SPLITTER. Empty sheetnames means the BUILD produced nothing;
        # populated sheetnames with no formulas means EXTRACTION is wrong.
        # Recording which one it is turns a second blind round into a fact.
        names = list(getattr(wb, "sheetnames", []) or [])
        if not names:
            self.grid_gap = ("the builder returned a Workbook with NO sheets - "
                             "this is a BUILD failure, not an extraction one")
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
            self.grid_gap = (f"the builder produced {len(names)} sheets "
                             f"({', '.join(names[:6])}) but NOT ONE '=' string "
                             f"- sheets built, so this is EXTRACTION, not build")
        return grid

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
