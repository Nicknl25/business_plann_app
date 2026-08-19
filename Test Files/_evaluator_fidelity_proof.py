"""EVALUATOR FIDELITY PROOF — the hard gate before the restructure search.

For each known draft (by business name, latest draft with a finmo and a
verdict): rebuild the P&L offline with the fast evaluator (the
pipeline's own builder) from the STORED model_input_json, then:
  1. Compare rebuilt quarter rows vs the stored (real-pipeline) finmo
     rows: revenue / EBITDA / net income max diffs.
  2. Score P&L viability with the gate's own check logic and compare
     against the REAL pipeline's persisted acceptance verdict.
  3. Time the evaluation (the search needs this fast).
"""
import json
import os
import sys
import time

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "python"))

# Known drafts: (label, draft_id) — completed runs with real verdicts.
DRAFTS = [
  ("Sunny (viable)", "97ff2c5a8a154e29be2f47a36234fcb3"),
  ("Meridian (viable)", "04292a46ac2f"),
  ("Harvest Lane (viable)", "25fd1ede85d8"),
  ("Ironthread (viable)", "e2291b66d4c9"),
  ("Understory (non-viable)", "3464962b16864c1a942d48c746dc48bb"),
]

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)


def _j(v):
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


from client_intake_and_finmo.post_intake_restructure.fast_evaluator import (
    build_fast_finmo,
    compare_finmo_rows,
    score_viability,
)
from client_intake_and_finmo.post_intake_acceptance.gate import verify_run_acceptance

for name, draft_prefix in DRAFTS:
    cur.execute(
        "SELECT draft_id, business_name, model_input_json, finmo_json, planning_run_json, "
        "planning_runtime_json, operating_model_json, financials_json "
        "FROM intake_consult_drafts WHERE draft_id LIKE %s AND finmo_json IS NOT NULL "
        "ORDER BY updated_at DESC LIMIT 1",
        (draft_prefix + "%",),
    )
    row = cur.fetchone()
    if not row:
        print(f"=== {name}: NO DRAFT FOUND ===")
        continue
    draft_id = row["draft_id"]
    mi = _j(row.get("model_input_json"))
    real_finmo = _j(row.get("finmo_json"))
    runtime = _j(row.get("planning_runtime_json"))
    ops = _j(row.get("operating_model_json"))
    fin = _j(row.get("financials_json"))
    pr = _j(row.get("planning_run_json"))
    planning_mode = str(runtime.get("planning_mode") or "").strip() or None
    naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None

    print(f"=== {name} (draft {draft_id[:12]}, mode={planning_mode}) ===")

    # Real verdict (re-read via the gate itself, same as the pipeline).
    try:
        real_verdict = verify_run_acceptance(
            conn, draft_id=draft_id,
            planning_run_id=str(pr.get("planning_run_id") or "").strip() or None,
        )
        real_passed = bool(real_verdict.get("passed"))
        real_failed = list(real_verdict.get("failed_checks") or [])
    except Exception as exc:
        real_passed, real_failed = None, [f"verdict_error: {exc}"]
    print(f"  REAL pipeline verdict: passed={real_passed} failed={real_failed}")

    # 1. Rebuild fidelity.
    t0 = time.perf_counter()
    try:
        fast_finmo = build_fast_finmo(mi)
    except Exception as exc:
        print(f"  FAST build FAILED: {type(exc).__name__}: {str(exc)[:300]}")
        print()
        continue
    build_ms = (time.perf_counter() - t0) * 1000.0
    diffs = compare_finmo_rows(fast_finmo, real_finmo)
    print(f"  FAST build: {build_ms:.0f} ms; row fidelity vs stored finmo:")
    for field, d in diffs.items():
        print(
            f"    {field:<12} max_abs={d['max_abs_diff']:>12,.2f}  "
            f"max_rel={d['max_rel_diff']*100:>8.4f}%  worst_q={d['worst_quarter']}"
        )

    # 2. Score agreement — on the REBUILT rows (what the search will see).
    t1 = time.perf_counter()
    score = score_viability(
        model_input_json=mi, finmo_json=fast_finmo,
        business_naics_6=naics, ops_json=ops, financials_json=fin,
        planning_mode=planning_mode,
    )
    score_ms = (time.perf_counter() - t1) * 1000.0
    print(f"  FAST score ({score_ms:.0f} ms): viable_pnl={score['viable_pnl']} "
          f"failed_binding={score['failed_binding']}")
    advisories = [
        f"{k}={'PASS' if c['passed'] else 'FAIL'}"
        for k, c in score["checks"].items() if c["advisory"]
    ]
    print(f"  advisory (cash, pre-funding): {advisories}")
    landed = score["landed"]
    print(f"  landed q11: {landed['q11']}")
    agree = (real_passed is not None) and (score["viable_pnl"] == real_passed)
    print(f"  AGREEMENT with real verdict: {'MATCH' if agree else 'MISMATCH'}")
    print()

cur.close()
conn.close()
