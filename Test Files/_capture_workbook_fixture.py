# -*- coding: utf-8 -*-
"""CAPTURE THE GOLDEN-LEG INPUT, ONCE, AS A COMMITTED FROZEN FIXTURE.

WHY THIS EXISTS. The golden legs (R31 model_input/finmo, R32 workbook formula
grid) are negative controls: identical inputs must produce identical outputs at
both commits. That argument is only worth anything if the INPUT cannot move.
Three things could move it, for three different reasons:

  RUN ARTIFACTS (payroll_headcount, debt_schedule, planning_run_json)
      payroll_headcount is authored by GPT during the planning run
      (gpt_payroll_author.py), so nothing offline can derive it. Frozen since
      round 6.
  THE DRAFT SECTIONS (facts/ops/people/fin/year1/marketing + the raw row)
      came from a LIVE QUERY over intake_consult_drafts at prove time. The
      ladder was deterministic given the table, but the table is not: a prune,
      a restore, or a new draft landing moves the pick. Round 7 caught exactly
      that - the input silently moved between two runs minutes apart.
  THE REFERENCE LOOKUPS (industry baselines, cohort bands, the driver-target
      mapping, the metric registry, realism checks, headcount policy, the GPT
      contract rows, the SBA rate)
      build_python_model_input_json reads all of them out of MySQL on its own
      account - 152 queries across 8 loaders for one build. Found by running
      the no-DB proof, not by reading the code. A migration of any of those
      tables moves every golden digest with no app-code change, which is the
      same defect as the moving draft pick wearing a different hat.

Three ways to feed any of them, and only one is honest:

  live DB read   - breaks determinism. The row can change between the
                   baseline run and the current run of the same prove, and a
                   golden master whose input moves produces a false DRIFT,
                   which is the one false alarm that costs the gate its
                   credibility.
  synthesized    - drifts against the contract. A stub that satisfies today's
                   validator tests the stub, not the workbook, and silently
                   stops matching the real shape.
  FROZEN FIXTURE - capture the real payload once, pin it, hash what is built
                   from it. The input never moves; the OUTPUT is under test.

USAGE (needs DB access; run once, commit the result):

    python "Test Files/_capture_workbook_fixture.py" --input 89e5a622
    python "Test Files/_capture_workbook_fixture.py" --artifacts 6feac758 \
                                                     --input 89e5a622

It writes replay_gate/_run_artifacts.py - a module of literals with provenance
(draft, run, stage, per-payload sha256) for every constant, plus
prime_frozen_lookups(), which serves the recorded reference data in place of
the live tables.

HOW THE LOOKUPS ARE RECORDED. Not by listing tables - by running the real
build once with the DB up and recording every (loader, arguments) -> result
it actually asked for. A loader nobody calls is never frozen, and a NEW loader
introduced by an app change is not silently missed: it has no recorded key, so
the no-DB proof fails loudly instead of quietly reading live data.

WATCH-ITEM, stated out loud rather than buried: once the reference lookups are
frozen, the golden legs can no longer notice a lookup-table migration. That is
correct for a negative control - it asks whether TWO COMMITS agree given
identical inputs, not whether production's reference data is current - but it
means reference-data drift now needs its own instrument if anyone wants one.

ROT GUARD. Re-running this must never silently "refresh" a payload that is
already frozen: refreshing is what turns a frozen fixture back into a moving
input. The run artifacts are RE-EMITTED FROM THE COMMITTED MODULE, not re-read
from the DB, unless --artifacts is passed; and even then a sha256 that differs
from the committed one is a REFUSAL unless --allow-refresh says out loud that
a refresh is intended. Re-capture only when a payload CONTRACT changes.

STORAGE. Every constant is stored as a compact JSON string parsed at import.
Identical bytes of DATA to a pretty-printed repr (this script asserts the
sha256 of the parsed value against the recorded sha before it writes), roughly
a sixth of the file size, and materially faster to import.
"""
import argparse
import copy
import hashlib
import importlib
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv()
import mysql.connector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "replay_gate", "_run_artifacts.py")
for _p in (os.path.join(REPO, "python"), REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The reference loaders the construction path reads out of MySQL. Every entry
# was OBSERVED reaching the database during a real build (see the module
# docstring); none is here on suspicion.
LOOKUP_TARGETS = (
    ("client_intake_and_finmo.post_intake_industry_baseline.lookup",
     "post_intake_industry_baseline_for_naics"),
    ("client_intake_and_finmo.post_intake_industry_baseline.lookup",
     "_load_metric_registry"),
    ("client_intake_and_finmo.post_intake_solver.cohort_band_resolver",
     "_query_cohort_rows"),
    ("client_intake_and_finmo.post_intake_realism.lookup",
     "_load_realism_check_rows"),
    ("client_intake_and_finmo.post_intake_mapping",
     "load_post_intake_driver_target_mapping_rows"),
    ("client_intake_and_finmo.post_intake_mapping",
     "load_post_intake_gpt_contract_rows"),
    ("client_intake_and_finmo.post_intake_headcount.lookup",
     "load_post_intake_headcount_policy_rows"),
    ("client_intake_and_finmo.finmo_bridge",
     "_sba_business_loan_interest_rate_and_source"),
)


def _sha(payload):
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        default=str).encode("utf-8")).hexdigest()


def _obj(raw):
    if raw is None:
        return {}
    if isinstance(raw, (str, bytes)):
        try:
            return json.loads(raw or "{}")
        except Exception:
            return {}
    return dict(raw)


def _lines(ops):
    return sum(len((lob or {}).get("products") or [])
               for lob in ((ops or {}).get("lob_models") or []))


def _lit(payload):
    """A compact JSON string literal, parsed back at import time."""
    return "_json.loads(" + repr(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str)) + ")"


ap = argparse.ArgumentParser()
ap.add_argument("--artifacts", default="",
                help="draft prefix to re-read the RUN ARTIFACTS from; omit to "
                     "re-emit the already-frozen ones verbatim")
ap.add_argument("--input", default="",
                help="draft prefix to freeze as the SINGLE-LINE golden input")
ap.add_argument("--allow-refresh", action="store_true",
                help="permit a re-read whose sha256 differs from the frozen "
                     "one - this is a MOVING-INPUT event, say why in the "
                     "commit message")
args = ap.parse_args()

# ---- the already-frozen half -------------------------------------------
frozen = None
try:
    from replay_gate import _run_artifacts as frozen
except Exception as exc:  # first-ever capture
    print(f"no committed fixture to re-emit ({type(exc).__name__}); "
          f"--artifacts is required")

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)


def _capture_artifacts(prefix):
    cur.execute(
        "SELECT draft_id, payroll_headcount, debt_schedule FROM "
        "intake_consult_drafts WHERE draft_id LIKE %s LIMIT 1", (prefix + "%",))
    row = cur.fetchone()
    if not row:
        print(f"NO DRAFT matching {prefix}")
        sys.exit(1)
    draft_id = row["draft_id"]
    cur.execute(
        "SELECT planning_run_id FROM planning_runs WHERE draft_id=%s "
        "ORDER BY created_at DESC LIMIT 1", (draft_id,))
    run_id = (cur.fetchone() or {}).get("planning_run_id")
    stage, planning_run_json = "", {}
    if run_id:
        cur.execute(
            "SELECT stage, planning_run_json FROM planning_run_checkpoints "
            "WHERE planning_run_id=%s AND finmo_json IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1", (run_id,))
        ck = cur.fetchone() or {}
        stage = str(ck.get("stage") or "")
        planning_run_json = _obj(ck.get("planning_run_json"))
    payroll = _obj(row.get("payroll_headcount"))
    debt = _obj(row.get("debt_schedule"))
    # REFUSE TO PIN AN EMPTY ARTIFACT. A fixture of {} satisfies nothing and
    # would let R32 hash a workbook built from a hollow payload - stable, and
    # meaningless. Better to fail here and pick a draft that has actually run.
    problems = []
    if not payroll:
        problems.append("payroll_headcount is empty - this draft has not been "
                        "through a planning run, so GPT never authored it")
    if not debt:
        problems.append("debt_schedule is empty")
    if problems:
        print(f"REFUSING to write a hollow fixture for {draft_id}:")
        for p in problems:
            print("  - " + p)
        sys.exit(2)
    return {"draft_id": draft_id, "planning_run_id": str(run_id), "stage": stage,
            "payroll": payroll, "debt": debt, "run_json": planning_run_json}


if args.artifacts:
    art = _capture_artifacts(args.artifacts)
    if frozen is not None and not args.allow_refresh:
        # THE ROT GUARD, teeth first. A re-read that produces different bytes
        # is a moving input, which is precisely the failure this whole fixture
        # exists to remove - so it stops here rather than sliding through.
        moved = [name for name, new, old in (
            ("payroll_headcount", art["payroll"], frozen.PAYROLL_HEADCOUNT),
            ("debt_schedule", art["debt"], frozen.DEBT_SCHEDULE),
            ("planning_run_json", art["run_json"], frozen.PLANNING_RUN_JSON),
        ) if _sha(new) != _sha(old)]
        if moved:
            print("REFUSING to refresh a frozen payload: " + ", ".join(moved)
                  + "\nThe DB now holds different bytes than the committed "
                    "fixture. Re-freezing moves the golden input and every "
                    "digest with it. Pass --allow-refresh only if a payload "
                    "CONTRACT changed, and say so in the commit message.")
            sys.exit(3)
elif frozen is not None:
    art = {"draft_id": frozen.PROVENANCE.get("draft_id", ""),
           "planning_run_id": frozen.PROVENANCE.get("planning_run_id", ""),
           "stage": frozen.PROVENANCE.get("stage", ""),
           "payroll": frozen.PAYROLL_HEADCOUNT, "debt": frozen.DEBT_SCHEDULE,
           "run_json": frozen.PLANNING_RUN_JSON}
    print("re-emitting the frozen run artifacts verbatim (no DB read)")
else:
    print("nothing to re-emit and no --artifacts given")
    sys.exit(1)

# ---- the single-line golden input --------------------------------------
single = None
if args.input:
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s "
                "LIMIT 1", (args.input + "%",))
    row = cur.fetchone()
    if not row:
        print(f"NO DRAFT matching {args.input}")
        sys.exit(1)
    ops = _obj(row.get("operating_model_json"))
    n = _lines(ops)
    if n != 1:
        # The golden legs are a SINGLE-line control. A pin that cannot satisfy
        # the filter is what silently turned round 7's floor into a live query
        # in the first place - refuse loudly instead of falling through.
        print(f"REFUSING: draft {row['draft_id']} carries {n} product lines - "
              f"the golden legs are a SINGLE-line negative control")
        sys.exit(2)
    # PACKED EXACTLY AS replay_gate/surface.py _pack() packs it, so the frozen
    # constant IS what the live ladder produced - not a re-shaping of it.
    single = {
        "id": str(row.get("draft_id") or ""),
        "row": dict(row),
        "ops": ops,
        "people": _obj(row.get("people_json")),
        "fin": _obj(row.get("financials_json")),
        "year1": _obj(row.get("financials_year1_json")),
        "marketing": _obj(row.get("marketing_model_json")),
        "facts": _obj(row.get("business_facts_json")) or
                 {"business_name": row.get("business_name")},
    }
    thin = [k for k in ("ops", "people", "fin", "year1") if not single[k]]
    if thin:
        print(f"REFUSING to freeze a hollow input for {single['id']}: "
              f"empty {', '.join(thin)} - a hash over a stub matches itself "
              f"and proves nothing")
        sys.exit(2)
elif frozen is not None and getattr(frozen, "SINGLE_LINE_DRAFT", None):
    single = frozen.SINGLE_LINE_DRAFT
    print("re-emitting the frozen single-line input verbatim (no DB read)")
else:
    print("no --input given and none frozen yet - the golden legs would keep "
          "querying the DB")
    sys.exit(1)

# THE INPUT DIGEST the golden legs print as GOLDEN-SHA single_line_input.
# Recorded here so a human can compare the fixture against a prove output
# without running anything.
input_sha = _sha({k: single[k] for k in
                  ("facts", "ops", "people", "fin", "year1", "marketing")})

# ---- record the reference lookups by RUNNING the real build -------------
RECORD = {}


def _key(a, k):
    return json.dumps([a, k], sort_keys=True, separators=(",", ":"), default=str)


def _tag(value):
    """Preserve the container type JSON would flatten (only tuples, today)."""
    if isinstance(value, tuple):
        return {"__tuple__": [_tag(v) for v in value]}
    return value


def _install_recorders():
    installed = 0
    for modname, fname in LOOKUP_TARGETS:
        mod = importlib.import_module(modname)
        orig = getattr(mod, fname)
        full = f"{modname}.{fname}"

        def make(orig=orig, full=full):
            def rec(*a, **k):
                out = orig(*a, **k)
                RECORD.setdefault(full, {})[_key(a, k)] = _tag(copy.deepcopy(out))
                return out
            return rec

        rec = make()
        # Patch EVERY binding, not just the defining module: a caller that did
        # `from x import y` at module level holds its own reference, and
        # missing one would leave a live query in a path we just declared
        # frozen.
        for m in list(sys.modules.values()):
            try:
                if m is not None and getattr(m, fname, None) is orig:
                    setattr(m, fname, rec)
                    installed += 1
            except Exception:
                pass
    return installed


print(f"recording reference lookups through {_install_recorders()} binding(s)")

from replay_gate.surface import Surface  # noqa: E402
from client_statements_output_excel import data as wbdata  # noqa: E402
from client_statements_output_excel import workbook_builder  # noqa: E402

_ctx = Surface.__new__(Surface)
_ctx.conn = None
_ctx.read_conn = None
_mij, _finmo, _note = _ctx._frozen_build(
    facts=single["facts"], ops=single["ops"], people=single["people"],
    fin=single["fin"], year1=single["year1"], marketing=single["marketing"])
if _mij is None or _finmo is None:
    print(f"REFUSING: the frozen build did not complete, so the lookup "
          f"recording is incomplete: {_note}")
    sys.exit(2)
_grid = _ctx.workbook_formula_grid(
    builder=workbook_builder.build_client_financial_model_workbook,
    from_row=wbdata.draft_data_from_row,
    draft={"draft": single, "mij": _mij, "finmo": _finmo})
if not _grid:
    print(f"REFUSING: no formula grid, so the workbook half of the path was "
          f"never exercised: {getattr(_ctx, 'grid_gap', '')}")
    sys.exit(2)

if not RECORD:
    print("REFUSING: not one reference lookup was recorded - the recorders "
          "did not reach the build, and a fixture that freezes nothing would "
          "pass this script and fail the no-DB proof")
    sys.exit(2)
lookup_keys = sum(len(v) for v in RECORD.values())

body_header = f'''# -*- coding: utf-8 -*-
"""FROZEN GOLDEN-LEG INPUT - captured once, never refreshed.

Generated by Test Files/_capture_workbook_fixture.py. Every constant here is
a REAL persisted payload, captured once and committed, so the golden legs
(R31 model_input/finmo, R32 workbook formula grid) build from COMMITTED BYTES
with no database query anywhere in the hashing path.

Three groups, frozen for three different reasons:

  RUN ARTIFACTS - payroll_headcount is GPT-authored during the planning run
  (gpt_payroll_author.py) and cannot be derived offline; debt_schedule and
  planning_run_json come off the same completed run.

  SINGLE_LINE_DRAFT - the golden legs' input business. This used to be picked
  by a live query over intake_consult_drafts, which made every digest a
  function of DATABASE STATE: a prune, a restore, or a new draft landing moved
  the input, and a golden master over a moving input produces false DRIFT. It
  is the packed shape surface.py's _pack() produced, captured verbatim.

  LOOKUP_REPLAY - the reference tables build_python_model_input_json reads on
  its own account (industry baselines, cohort bands, the driver-target
  mapping, the metric registry, realism checks, headcount policy, GPT contract
  rows, the SBA rate): 8 loaders, recorded as (arguments -> result) by running
  the real build once with the DB up. Call prime_frozen_lookups() BEFORE
  building or those tables are read live and the digest stops being a function
  of committed bytes.

DO NOT "refresh" this file to pick up newer data. Refreshing turns a frozen
fixture back into a moving input. The generator refuses a silent refresh; it
takes --allow-refresh, and that flag means the digests are expected to move.
Re-capture ONLY when a payload contract changes.

OWNERSHIP: this is generated DATA plus the shim that serves it - VS-owned,
mini-consumed, zero gate logic. It lives beside the gate because replay_gate
is the package that imports it and "Test Files" is not an importable name.

  RUN ARTIFACTS
    draft            {art["draft_id"]}
    planning run     {art["planning_run_id"]}
    checkpoint stage {art["stage"] or "(none)"}
    payroll_headcount sha256  {_sha(art["payroll"])}
    debt_schedule     sha256  {_sha(art["debt"])}
    planning_run_json sha256  {_sha(art["run_json"])}

  SINGLE-LINE INPUT
    draft            {single["id"]}
    business         {str((single["row"] or {}).get("business_name") or "")}
    product lines    {_lines(single["ops"])}
    section digest   {input_sha}
    (= GOLDEN-SHA single_line_input, the identity the golden legs print)

  REFERENCE LOOKUPS
    loaders          {len(RECORD)}
    recorded keys    {lookup_keys}
    sha256           {_sha(RECORD)}
"""
import copy as _copy
import importlib as _importlib
import json as _json
import sys as _sys

PROVENANCE = {{
    "draft_id": {art["draft_id"]!r},
    "planning_run_id": {art["planning_run_id"]!r},
    "stage": {art["stage"]!r},
    "payroll_headcount_sha256": {_sha(art["payroll"])!r},
    "debt_schedule_sha256": {_sha(art["debt"])!r},
    "planning_run_json_sha256": {_sha(art["run_json"])!r},
    "single_line_draft_id": {single["id"]!r},
    "single_line_input_sha256": {input_sha!r},
    "lookup_replay_loaders": {len(RECORD)!r},
    "lookup_replay_keys": {lookup_keys!r},
    "lookup_replay_sha256": {_sha(RECORD)!r},
}}

PAYROLL_HEADCOUNT = {_lit(art["payroll"])}

DEBT_SCHEDULE = {_lit(art["debt"])}

PLANNING_RUN_JSON = {_lit(art["run_json"])}

# The packed single-line draft: id / row / ops / people / fin / year1 /
# marketing / facts, exactly the dict shape surface.py's _pack() returned.
SINGLE_LINE_DRAFT = {_lit(single)}

# {{"module.function": {{"<canonical args>": <recorded result>}}}}
LOOKUP_REPLAY = {_lit(RECORD)}

LOOKUP_TARGETS = {LOOKUP_TARGETS!r}
'''

# The replay machinery is a STATIC block, kept out of the f-string so its
# braces are not doubled and it reads the way it will run.
body_machinery = '''

class FrozenLookupMiss(RuntimeError):
    """A frozen lookup was called with arguments nobody recorded.

    Deliberately fatal rather than a fall-through to the live table. A silent
    fall-through is exactly the failure this fixture exists to remove: the
    digest would go back to depending on database state, and nothing would
    say so. If this fires, the app asked a reference table something new -
    re-capture the fixture and expect the digests to move.
    """


def _replay_key(args, kwargs):
    return _json.dumps([args, kwargs], sort_keys=True, separators=(",", ":"),
                       default=str)


def _untag(value):
    if isinstance(value, dict) and set(value) == {"__tuple__"}:
        return tuple(_untag(v) for v in value["__tuple__"])
    return value


def prime_frozen_lookups():
    """Serve the recorded reference data instead of the live lookup tables.

    Patches every binding of every recorded loader - the defining module and
    any module that imported the name - because one missed binding leaves a
    live query in a path this fixture claims is frozen.

    -> the number of bindings patched (0 means the app package is not
    importable, which the caller should treat as a failure, not a no-op).
    """
    patched = 0
    for modname, fname in LOOKUP_TARGETS:
        recorded = LOOKUP_REPLAY.get(f"{modname}.{fname}")
        if recorded is None:
            continue
        try:
            mod = _importlib.import_module(modname)
        except Exception:
            continue
        original = getattr(mod, fname, None)
        if original is None:
            continue

        def make(recorded=recorded, fname=fname):
            def replay(*a, **k):
                key = _replay_key(a, k)
                if key not in recorded:
                    raise FrozenLookupMiss(
                        f"{fname} was called with arguments that are not in "
                        f"the frozen fixture. The build is asking a reference "
                        f"table something it did not ask when the fixture was "
                        f"captured, so the digest can no longer be a function "
                        f"of committed bytes. Re-capture with Test Files/"
                        f"_capture_workbook_fixture.py and expect the goldens "
                        f"to move.")
                return _untag(_copy.deepcopy(recorded[key]))
            return replay

        replay = make()
        for m in list(_sys.modules.values()):
            try:
                if m is not None and getattr(m, fname, None) is original:
                    setattr(m, fname, replay)
                    patched += 1
            except Exception:
                pass
    return patched
'''

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(body_header + body_machinery)

print(f"wrote {OUT}  ({os.path.getsize(OUT):,} bytes)")
print(f"  run artifacts   draft {art['draft_id'][:8]} run "
      f"{art['planning_run_id'][:14]} stage {art['stage']}")
for label, payload in (("payroll_headcount", art["payroll"]),
                       ("debt_schedule", art["debt"]),
                       ("planning_run_json", art["run_json"])):
    print(f"    {label:18s} {len(json.dumps(payload, default=str)):>9,} bytes "
          f"sha {_sha(payload)[:16]}")
print(f"  single-line input draft {single['id'][:8]} "
      f"({_lines(single['ops'])} product line) sha {input_sha[:16]}")
print(f"  reference lookups {len(RECORD)} loaders, {lookup_keys} keys, "
      f"sha {_sha(RECORD)[:16]}")
for full, entries in sorted(RECORD.items()):
    print(f"    {full.split('.')[-1]:44s} {len(entries):>4} keys")
print("commit it, then prove the freeze with "
      "Test Files/_prove_frozen_input_no_db.py")
