"""THE SINGLE-LINE BYTE-IDENTITY FLOOR (Nick-ruled, non-negotiable; the
regression floor for the WS1(b) per-line-COGS change at c77094a).

WHAT THIS PROVES: rerunning a clean SINGLE-LINE draft through the live
production system-run produces byte-identical model_input_json and
finmo_json across code versions. Five of six businesses are
single-line; they must not move a byte.

EXACTLY WHAT IS HASHED (mini: match this boundary, not another):
  - The FINAL checkpoint of the LATEST planning run for the draft:
    the most recent `planning_run_checkpoints` row (created_at DESC)
    WHERE finmo_json IS NOT NULL - in a clean run that is the
    post_intake_finalize_validation_completed checkpoint.
  - MODEL_INPUT_SHA = sha256 of the canonical JSON serialization
    (json.dumps(parsed, sort_keys=True, separators=(",", ":"))) of
    that checkpoint's model_input_json column - i.e. the PERSISTED
    production payload (build_python_model_input_json ->
    apply_derived_driver_policies_to_model_input -> solver
    applications), NOT FinancialModelInputs.to_model_input_json()
    round-tripped through the dataclass.
  - FINMO_SHA = the same canonicalization of that checkpoint's
    finmo_json column (the build_python_finmo_json output).
  - The WORKBOOK IS NOT HASHED here: .xlsx bytes are not
    deterministic (zip metadata / timestamps). The workbook surface
    is covered structurally (see _ws1b_multiline_e2e-style checks:
    single-line = exactly one "Cost of Goods Sold" P&L row with the
    legacy formula shape; multi-line = one "Cost of Goods Sold - "
    row per line + total =SUM over them). A deterministic workbook
    hash, if wanted as a gate leg, should hash the FORMULA GRID
    (sheet -> row label -> formula strings), never the file bytes.

PROTOCOL (the c77094a proof, reproducible):
  1. On the OLD code: restart :5050, run
       python "Test Files/_prove_single_line_byte_floor.py" 6feac758 OLD
  2. On the NEW code: restart :5050, run the same with label NEW.
  3. The two FINMO_SHA lines and the two MODEL_INPUT_SHA lines must
     match exactly. c77094a golden values (draft 6feac758):
       FINMO_SHA       9549d3a950080b8773601df38093fe4951e597c98410b70d6db82093cc425152
       MODEL_INPUT_SHA d7cc76831a1b1caaa8c5995d0d35508193b387324b9921e34511c69120205373

The rerun POST never passes planning_run_id (the run names the NEW
run - recovery-design law). Requires ONE live :5050 listener.
"""
import hashlib
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests
from dotenv import load_dotenv

load_dotenv()
import mysql.connector

BASE = os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050")
prefix = sys.argv[1] if len(sys.argv) > 1 else "6feac758"
label = sys.argv[2] if len(sys.argv) > 2 else "run"

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, client_id FROM intake_consult_drafts WHERE draft_id LIKE %s",
    (prefix + "%",))
row = cur.fetchone()
if not row:
    print(f"[{label}] NO DRAFT matching {prefix}")
    sys.exit(1)
draft_id, client_id = row["draft_id"], row["client_id"]
print(f"[{label}] system run for {draft_id}")
resp = requests.post(f"{BASE}/api/intake-consult/system-run", json={
    "draft_id": draft_id, "client_id": client_id,
}, timeout=1800)
print(f"[{label}] HTTP {resp.status_code}")

cur.execute(
    "SELECT planning_run_id FROM planning_runs WHERE draft_id=%s "
    "ORDER BY created_at DESC LIMIT 1", (draft_id,))
run_id = (cur.fetchone() or {}).get("planning_run_id")
cur.execute(
    "SELECT stage, finmo_json, model_input_json FROM planning_run_checkpoints "
    "WHERE planning_run_id=%s AND finmo_json IS NOT NULL "
    "ORDER BY created_at DESC LIMIT 1", (run_id,))
ck = cur.fetchone() or {}


def _sha(raw):
    if raw is None:
        return "ABSENT"
    canonical = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


print(f"[{label}] run {str(run_id)[:14]} stage={ck.get('stage')}")
print(f"[{label}] FINMO_SHA {_sha(ck.get('finmo_json'))}")
print(f"[{label}] MODEL_INPUT_SHA {_sha(ck.get('model_input_json'))}")
cur.execute(
    "SELECT planning_run_status FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,))
print(f"[{label}] status {cur.fetchone()}")
