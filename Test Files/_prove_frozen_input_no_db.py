# -*- coding: utf-8 -*-
"""PROVE the golden-leg input is durable BY CONSTRUCTION, not by assertion.

The claim under test: the golden legs' digests are a function of COMMITTED
BYTES ONLY, so no database change - a prune, a restore, a new draft landing,
a persona run in another window - can move them.

Asserting that is worthless; a comment saying "frozen" is not evidence. So
this reproduces the digests with the DATABASE UNREACHABLE, at the OS boundary:
every outbound socket is poisoned before anything is imported, and
mysql.connector.connect is replaced with a raiser that records its calls. If
any part of the hashing path still reaches for the DB, this script cannot
print a digest - it crashes with DB-UNREACHABLE, which is the point.

    python "Test Files/_prove_frozen_input_no_db.py"

Checks, in order:
  1. ROT GUARD - every frozen payload's sha256 still equals the one recorded
     in PROVENANCE. Catches a hand-edit or a half-written re-capture.
  2. GENUINE, NOT SYNTHESIZED - the frozen row is a real full-width draft row,
     and its stored JSON columns re-parse to exactly the packed sections the
     fixture claims. A trimmed or hand-made fixture fails this.
  3. NO-DB BUILD - model_input / finmo / workbook-formula-grid digests, built
     through the same production constructors the legs use, with the DB down.
  4. DETERMINISM - the whole build repeated; digests must be identical.
  5. CONTINUITY - digests compared against the round-7 goldens, so a human can
     see whether freezing moved the input or preserved it.
"""
import hashlib
import io
import json
import os
import socket
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# The app packages live under <root>/python - the same head-of-path binding
# replay_gate/_bootstrap.bind_root() does, minus its .env load (this proof
# wants NO credentials in the environment at all).
for path in (os.path.join(REPO, "python"), REPO):
    if path not in sys.path:
        sys.path.insert(0, path)

# ---- take the database away, at the OS boundary -------------------------
# Env first: even a lazily-built connection string now points nowhere.
for var in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DB",
            "MYSQL_PORT"):
    os.environ[var] = ""

REACHED = []


class DatabaseUnreachable(RuntimeError):
    pass


_real_connect = socket.socket.connect


def _no_socket(self, address, *a, **k):
    REACHED.append(f"socket.connect{tuple(address)!r}")
    raise DatabaseUnreachable(f"DB-UNREACHABLE: outbound socket to {address!r} "
                              f"is poisoned for this proof")


socket.socket.connect = _no_socket
socket.create_connection = lambda *a, **k: _no_socket(None, a[0] if a else ())

import mysql.connector  # noqa: E402


def _no_mysql(*a, **k):
    REACHED.append("mysql.connector.connect")
    raise DatabaseUnreachable("DB-UNREACHABLE: mysql.connector.connect is "
                              "poisoned for this proof")


mysql.connector.connect = _no_mysql

from replay_gate import _run_artifacts as FX  # noqa: E402
from replay_gate.surface import Surface  # noqa: E402

# ROUND-7 GOLDENS (_prove_20260812_ws1ws2_prove7b_goldens.txt), the last
# digests produced while the input was still a live query.
# RE-BLESSED 2026-08-14: model_input + finmo moved when the ruled opening-PPE
# 5y straight-line depreciation landed (7b26ff6, Nick ratified). Purity proven
# leaf-by-leaf before re-baselining (_mini_cw032_drift_purity_20260814.txt):
# every moved leaf traces to the depreciation schedule and its arithmetic
# descendants. single_line_input and workbook_formulas did not move.
# Pre-depreciation values, for the record:
#   model_input 9650f148a32026aefade9a36aa48c585eebe5968497c6d1847aaf9a42d5cfc76
#   finmo       c21a05c9d30bef1f408886f81596bc659914636bdc923f40fa84272017c8257e
ROUND7 = {
    "single_line_input": "72dfcb81f6f30a2cee54391d6078454717c0ef73fa39ef02fd8e08131538f679",
    "model_input": "1d50e46ab8e653a21c85a9114d6ca49186ab750b3135b831ee60c663af0739ff",
    "finmo": "24e38de4dc9879f8ff2e0400f90d271e5c8db6819944f59bde45a2226c841583",
    "workbook_formulas": "cbd764631e986196d6be8fab9940b029c3818f290a92a392f84da6d22a466cc0",
}

FAILS = []
NOTES = []


def _sha(payload):
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        default=str).encode("utf-8")).hexdigest()


def check(ok, label, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)
    return ok


# ---- 1. rot guard --------------------------------------------------------
print("\n(1) ROT GUARD - frozen payloads still hash to their recorded shas")
P = FX.PROVENANCE
for name, payload, key in (
    ("payroll_headcount", FX.PAYROLL_HEADCOUNT, "payroll_headcount_sha256"),
    ("debt_schedule", FX.DEBT_SCHEDULE, "debt_schedule_sha256"),
    ("planning_run_json", FX.PLANNING_RUN_JSON, "planning_run_json_sha256"),
):
    got, want = _sha(payload), P.get(key, "")
    check(bool(want) and got == want, f"{name} sha256",
          f"{got[:16]} (recorded {want[:16]})")

DRAFT = FX.SINGLE_LINE_DRAFT
SECTIONS = ("facts", "ops", "people", "fin", "year1", "marketing")
input_sha = _sha({k: DRAFT[k] for k in SECTIONS})
check(input_sha == P.get("single_line_input_sha256", ""),
      "single_line_input sha256", f"{input_sha[:16]}")
check(_sha(FX.LOOKUP_REPLAY) == P.get("lookup_replay_sha256", ""),
      "lookup_replay sha256",
      f"{_sha(FX.LOOKUP_REPLAY)[:16]} ({P.get('lookup_replay_loaders')} "
      f"loaders, {P.get('lookup_replay_keys')} keys)")

# ---- 2. genuine, not synthesized ----------------------------------------
print("\n(2) GENUINE CAPTURE - a real draft row, sections agreeing with it")
row = DRAFT.get("row") or {}
check(len(row) >= 60, "the frozen row is a full-width draft row",
      f"{len(row)} columns")
check(str(row.get("draft_id") or "") == DRAFT.get("id"),
      "row.draft_id matches the packed id", str(DRAFT.get("id"))[:8])
check(len(str(row.get("messages_json") or "")) > 1000,
      "the row carries its real transcript (not trimmed)",
      f"{len(str(row.get('messages_json') or '')):,} bytes")


def _parse(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


for sect, col in (("ops", "operating_model_json"), ("people", "people_json"),
                  ("fin", "financials_json"),
                  ("year1", "financials_year1_json"),
                  ("marketing", "marketing_model_json")):
    check(_sha(_parse(row.get(col))) == _sha(DRAFT[sect]),
          f"{sect} == the row's own {col}")

lines = sum(len((lob or {}).get("products") or [])
            for lob in (DRAFT["ops"].get("lob_models") or []))
check(lines == 1, "the frozen business is SINGLE-line", f"{lines} product line")

# ---- 3. the no-DB build --------------------------------------------------
print("\n(3) NO-DB BUILD - digests from committed bytes, database unreachable")


def build():
    """The gate's own construction path, fed the frozen input.

    Surface is instantiated WITHOUT connections on purpose: if any step of the
    hashing path needed one, this is where it would raise instead of quietly
    reading a table.
    """
    from client_statements_output_excel import data as wbdata
    from client_statements_output_excel import workbook_builder

    # The reference tables the builder reads on its own account. Priming them
    # is part of the freeze, not a workaround: without it
    # build_python_model_input_json SELECTs industry baselines, cohort bands,
    # the driver-target mapping and five more, and the digest goes back to
    # being a function of database state.
    patched, restore = FX.prime_frozen_lookups()
    if not patched:
        raise RuntimeError("primed ZERO lookup bindings - the frozen "
                           "reference data is not in the path")

    ctx = Surface.__new__(Surface)   # no conn, no read_conn, no DB handle
    ctx.conn = None
    ctx.read_conn = None
    try:
        mij, finmo, note = ctx._frozen_build(
            facts=DRAFT["facts"], ops=DRAFT["ops"], people=DRAFT["people"],
            fin=DRAFT["fin"], year1=DRAFT["year1"],
            marketing=DRAFT["marketing"])
        if mij is None or finmo is None:
            raise RuntimeError(f"frozen build refused: {note}")
        grid = ctx.workbook_formula_grid(
            builder=workbook_builder.build_client_financial_model_workbook,
            from_row=wbdata.draft_data_from_row,
            draft={"draft": DRAFT, "mij": mij, "finmo": finmo})
    finally:
        # The patch is process-wide; leaving it installed would make any
        # later build in this process ask the frozen loaders questions
        # nobody recorded. Restoring here also proves restore() works.
        restore()
    if not grid:
        raise RuntimeError(f"no formula grid: {getattr(ctx, 'grid_gap', '')}")
    cells = sum(len(v) for rows in grid.values() for v in rows.values())
    return {"model_input": _sha(mij), "finmo": _sha(finmo),
            "workbook_formulas": _sha(grid)}, cells, len(grid), note


try:
    first, cells, sheets, note = build()
except DatabaseUnreachable as exc:
    print(f"  FAIL  the hashing path REACHED FOR THE DATABASE: {exc}")
    print(f"        call site(s): {REACHED}")
    sys.exit(1)

for name, digest in first.items():
    print(f"  SHA   {name:18s} {digest}")
print(f"  built {cells:,} formulas across {sheets} sheets")
print(f"  {note}")
check(cells > 1000, "the grid is substantial (not a stub)", f"{cells:,} formulas")
check(not REACHED, "ZERO database calls in the hashing path",
      "no socket opened, mysql.connector.connect never called"
      if not REACHED else str(REACHED))

# ---- 4. determinism ------------------------------------------------------
print("\n(4) DETERMINISM - the same committed bytes built twice")
second, _, _, _ = build()
check(first == second, "all three digests reproduce exactly")

# ---- 5. continuity against round 7 --------------------------------------
print("\n(5) CONTINUITY - frozen digests vs the last live-query round (7)")
moved = []
for name, digest in [("single_line_input", input_sha)] + sorted(first.items()):
    same = digest == ROUND7.get(name)
    print(f"  {'SAME ':5s} {name:18s} {digest[:16]}"
          if same else
          f"  MOVED {name:18s} {digest[:16]} (round 7: {ROUND7.get(name, '')[:16]})")
    if not same:
        moved.append(name)
if moved:
    NOTES.append(f"digests moved when frozen: {', '.join(moved)} - expected if "
                 f"the freeze picked a different draft than the live ladder")
else:
    NOTES.append("the freeze preserved the input EXACTLY: every digest carries "
                 "forward from round 7. Rounds 4-6 are still NOT comparable - "
                 "mini's round-7 pick-ordering fix moved them, and freezing "
                 "did not move them back")

print("\n" + "=" * 70)
for n in NOTES:
    print("NOTE: " + n)
if FAILS:
    print(f"FAILED {len(FAILS)}: " + "; ".join(FAILS))
    sys.exit(1)
print("PROVEN: the golden-leg input is durable by construction - every digest "
      "above was produced with the database unreachable.")
