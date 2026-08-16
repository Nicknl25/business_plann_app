"""n1 ONE AUTHORITY LIVE PROOF (Nick 2026-08-16, restructure-path hygiene).

Production call chain exercised (same as the FIX 2b proof): POST
/api/intake-consult/system-run -> post_intake_consult_system_run_handler ->
_run_planning_system_for_draft (grid build CREATES the planning_runs row)
-> verify_run_acceptance (fails on the base Nine Fathom plan) -> restructure
stage -> run_restructure_joint_solve -> RestructureNetDeadError (the test
server strips the synthesized COGS % row) -> inner catch (run_status flip)
-> outer catch (failure surface).

THE QUESTION: which planning_runs row does the restructure path write to?
PRE: acceptance_planning_run_id is EMPTY on this path (result.planning_run_json
carries no planning_run_id) so the gate AND the FIX 2b flip resolve the
draft's LATEST row - a guess. POST: the unified runner stamps the row the
grid build created into result.planning_run_json.planning_run_id and every
write on the path resolves by that id only.

To make the guess OBSERVABLE the clone gets a DECOY planning_runs row
(run_status=completed, started_at/updated_at one day in the future, tagged
DECOY) inserted BEFORE the POST. A latest-run fallback lands on the decoy;
the single authority lands on the real row the run created.

PRE (HEAD build served from a git worktree): decoy carries the failed flip /
verdict, the real row does not.  POST: real row failed + verdict, decoy
untouched, response planning_run_json.planning_run_id == real row.

Preconditions: :5050 served by "Test Files/_rs_deadnet_live_server.py" of
the build under test (ONE listener). Clone left in place (audit artifact).
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
import mysql.connector

load_dotenv("C:/dev/business_plann_app/.env")
BASE = "http://127.0.0.1:5050"
SOURCE = "6d2823db268d483bbb4c8be8c627dc26"
TAG = "rsn1au"
LABEL = (sys.argv[1] if len(sys.argv) > 1 else "RUN").upper()
FAILS: list = []


def check(label, ok, detail=""):
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
  if not ok:
    FAILS.append(label)


def conn():
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True)


def make_clone(c):
  cur = c.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE,))
  src = cur.fetchone()
  cur.close()
  if not src:
    raise SystemExit("source draft missing")
  clone_id = TAG + uuid.uuid4().hex[: 32 - len(TAG)]
  client_id = TAG.upper() + uuid.uuid4().hex[:10].upper()
  row = dict(src)
  row["draft_id"] = clone_id
  row["client_id"] = client_id
  row["business_name"] = f"Nine Fathom Coffee Roasters [N1 AUTHORITY {LABEL} CLONE]"
  for k in ("planning_run_id", "planning_run_status", "planning_failure_reason",
            "repair_guidance_json", "model_input_json", "finmo_json",
            "numeric_solver_feedback_json"):
    if k in row:
      row[k] = None
  cols = list(row.keys())
  cur = c.cursor()
  cur.execute(
    "INSERT INTO intake_consult_drafts (" + ", ".join(cols) + ") VALUES (" + ", ".join(["%s"] * len(cols)) + ")",
    [row[k] for k in cols])
  cur.close()
  return clone_id, client_id


def insert_decoy(c, clone_id, client_id):
  """A COMPLETED planning_runs row dated one day in the FUTURE: any
  latest-run lookup (ORDER BY started_at / updated_at DESC) returns it;
  it is never active (queued/running/paused) so lifecycle start is clean."""
  decoy_id = "decoy" + uuid.uuid4().hex[:27]
  future = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f")
  cur = c.cursor()
  cur.execute(
    "INSERT INTO planning_runs (planning_run_id, draft_id, client_id, run_status, current_stage, "
    "current_stage_status, trigger_type, resume_count, created_at, updated_at, started_at, "
    "completed_at, failure_reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    (decoy_id, clone_id, client_id, "completed", "finalize", "completed", "n1_decoy", 0,
     future, future, future, future, "N1 DECOY ROW - must never be written by the run"))
  cur.close()
  return decoy_id


def main():
  c = conn()
  r = requests.get(f"{BASE}/api/business-types", timeout=10)
  check("backend answers on :5050", r.status_code == 200, f"HTTP {r.status_code}")
  clone_id, client_id = make_clone(c)
  decoy_id = insert_decoy(c, clone_id, client_id)
  print(f"[{LABEL}] clone draft {clone_id} client {client_id} decoy run {decoy_id}")
  t0 = time.time()
  resp = requests.post(f"{BASE}/api/intake-consult/system-run",
                       json={"draft_id": clone_id, "client_id": client_id}, timeout=5400)
  dt = time.time() - t0
  print(f"HTTP {resp.status_code} after {dt:.0f}s")
  body = {}
  try:
    body = resp.json()
  except Exception:
    print("non-JSON body:", resp.text[:300].replace("\n", " "))
  print("body:", json.dumps({k: body.get(k) for k in ("error", "detail", "restructure_net_dead")}, default=str)[:600])
  check("HTTP 500 dead-net failure surface", resp.status_code == 500 and body.get("restructure_net_dead") is True)

  cur = c.cursor(dictionary=True)
  cur.execute("SELECT * FROM planning_runs WHERE draft_id=%s ORDER BY created_at", (clone_id,))
  runs = cur.fetchall()
  non_decoy = [x for x in runs if x["planning_run_id"] != decoy_id]
  decoy = next((x for x in runs if x["planning_run_id"] == decoy_id), None)
  print("planning_runs:", [(x["planning_run_id"][:10], x["run_status"], (x["failure_reason"] or "")[:60],
                            "verdict" if x.get("acceptance_verdict_json") else "no-verdict") for x in runs])
  # The row the GRID BUILD created = the earliest non-decoy row (begin_planning_run
  # runs before anything else). Any LATER non-decoy row is a PHANTOM minted by
  # persist_post_intake_execution_state's OWN latest-run resolution (it accepts the
  # payload's planning_run_id only when that id is the latest active/any row; the
  # future-dated decoy hijacks 'latest any', so it mints a fresh uuid row). That is
  # a SHARED persist outside n1's restructure path - reported as WARN, flagged for
  # triage, never a pass/fail of the single authority under test. Without a decoy
  # the same build lands exactly ONE row (see _rs_deadnet_live_failure_surface).
  real = sorted(non_decoy, key=lambda x: x["started_at"])[:1]
  phantom = sorted(non_decoy, key=lambda x: x["started_at"])[1:]
  check("grid build created the real run row (decoy present)", len(real) == 1 and decoy is not None)
  if phantom:
    print(f"  [WARN] {len(phantom)} phantom row(s) minted by persist_post_intake_execution_state latest-run resolution "
          f"(decoy-induced; shared persist, NOT the restructure path): "
          f"{[(x['planning_run_id'][:10], x['run_status'], x['completed_at']) for x in phantom]}")
  real_row = real[0] if real else {}
  real_id = str(real_row.get("planning_run_id") or "")
  # THE ROW THE RUN WROTE TO
  check("REAL row run_status=failed, failure_reason names ContractViolation",
        real_row.get("run_status") == "failed" and "ContractViolation" in (real_row.get("failure_reason") or ""),
        f"real={real_row.get('run_status')} reason={(real_row.get('failure_reason') or '')[:50]}")
  rv = {}
  try:
    rv = json.loads(real_row.get("acceptance_verdict_json") or "{}")
  except Exception:
    rv = {}
  check("REAL row carries the acceptance verdict (gate resolved THIS row)",
        bool(rv) and rv.get("passed") is False,
        f"verdict.passed={rv.get('passed')} snapshot.run_id={(rv.get('field_snapshot') or {}).get('planning_run_id', '')[:10]}")
  check("verdict.field_snapshot.planning_run_id == REAL row id",
        str((rv.get("field_snapshot") or {}).get("planning_run_id") or "") == real_id)
  # THE DECOY (the latest-run guess) MUST BE UNTOUCHED
  check("DECOY untouched: run_status still completed",
        decoy is not None and decoy.get("run_status") == "completed", f"decoy={decoy and decoy.get('run_status')}")
  check("DECOY untouched: no acceptance verdict stamped on it",
        decoy is not None and not decoy.get("acceptance_verdict_json"))
  check("DECOY untouched: failure_reason still the decoy marker",
        decoy is not None and str(decoy.get("failure_reason") or "").startswith("N1 DECOY"))
  # FAILED diagnostics row keyed by the REAL run
  cur.execute("SELECT planning_run_id, acceptance_passed, diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id=%s ORDER BY created_at DESC", (clone_id,))
  diags = cur.fetchall()
  print("diagnostics rows:", [((d["planning_run_id"] or "")[:10], d["acceptance_passed"]) for d in diags])
  check("FAILED diagnostics row keyed by the REAL run id (never the decoy)",
        bool(diags) and all((d["planning_run_id"] or "") == real_id for d in diags))
  # The response payload names the run (POST only - PRE carries none)
  prj = body.get("planning_run_json") if isinstance(body.get("planning_run_json"), dict) else {}
  print("response planning_run_json.planning_run_id:", (prj.get("planning_run_id") or "")[:10] or "(none)")
  # Draft row mirror
  cur.execute("SELECT planning_run_status, repair_guidance_json FROM intake_consult_drafts WHERE draft_id=%s", (clone_id,))
  d = cur.fetchone()
  rg = (json.loads(d["repair_guidance_json"] or "{}").get("restructure") or {})
  check("repair_guidance dead_net record present", isinstance(rg.get("dead_net"), dict))
  cur.close()
  print()
  print(f"[{LABEL}] clone draft: {clone_id}  real run: {real_id}  decoy: {decoy_id}")
  print(f"[{LABEL}] RESULT:", "ALL GREEN" if not FAILS else f"RED ({len(FAILS)}): {FAILS}")
  return 0 if not FAILS else 1


if __name__ == "__main__":
  sys.exit(main())
