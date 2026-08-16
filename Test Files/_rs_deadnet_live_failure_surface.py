"""FIX 2b LIVE PROOF - the dead restructure net reaches the FAILURE SURFACE.

Production call chain exercised: POST /api/intake-consult/system-run ->
post_intake_consult_system_run_handler -> _run_planning_system_for_draft
-> verify_run_acceptance (FAILS on the base 3-line Nine Fathom plan) ->
restructure stage -> run_restructure_joint_solve -> (net dead: the test
server strips the synthesized COGS % row = the pre-FIX-1 shape) ->
RestructureNetDeadError -> inner catch (repair_guidance dead_net record,
planning_runs failed) -> outer except (FIX 2b: failed snapshot + FAILED
diagnostics row + failure email + HTTP 500 JSON).

PRE (build before FIX 2b): outer except is a bare re-raise -> Flask
default 500 (HTML), NO FAILED diagnostics row, NO failure email.
POST: all artifacts below present.

Preconditions: :5050 is served by "Test Files/_rs_deadnet_live_server.py"
(ONE listener). The clone is a rewind of Nine Fathom 6d2823db (planning
columns + repair_guidance + model_input cleared) so the base plan is
rebuilt from the 3 intake lines and fails acceptance exactly like run
f44ff3f1 did. Clone is left in place (audit artifact); business_name is
tagged so it can never be mistaken for the client.

  set PYTHONIOENCODING=utf-8
  .venv\\Scripts\\python.exe "Test Files\\_rs_deadnet_live_failure_surface.py"
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

import requests
from dotenv import load_dotenv
import mysql.connector

load_dotenv("C:/dev/business_plann_app/.env")
BASE = "http://127.0.0.1:5050"
SOURCE = "6d2823db268d483bbb4c8be8c627dc26"
TAG = "rsdead"
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
  row["business_name"] = "Nine Fathom Coffee Roasters [DEADNET PROOF CLONE]"
  # planning_run_json is KEPT (the DB trigger consistency_completion_guard
  # requires it on a completed row); the system run overwrites it. The
  # planning_runs table has no row for the clone, so lifecycle start is clean.
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


def main():
  c = conn()
  r = requests.get(f"{BASE}/api/business-types", timeout=10)
  check("backend answers on :5050", r.status_code == 200, f"HTTP {r.status_code}")
  clone_id, client_id = make_clone(c)
  print(f"clone draft {clone_id} client {client_id}")
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
  print("body:", json.dumps({k: body.get(k) for k in ("error", "detail", "restructure_net_dead", "failure_email")}, default=str)[:900])

  # 1. HTTP 500 with the structured JSON body (not Flask's default HTML)
  check("HTTP 500", resp.status_code == 500)
  check("JSON body error=system_run_failed + restructure_net_dead flag",
        body.get("error") == "system_run_failed" and body.get("restructure_net_dead") is True)
  check("detail names the violation", "ContractViolation" in str(body.get("detail") or ""), str(body.get("detail") or "")[:120])
  fe = body.get("failure_email") or {}
  check("failure email SENT (body.failure_email.sent)", fe.get("sent") is True, json.dumps(fe, default=str)[:300])

  cur = c.cursor(dictionary=True)
  # 2. planning_runs failed + failure_reason names the violation
  cur.execute("SELECT * FROM planning_runs WHERE draft_id=%s ORDER BY created_at DESC", (clone_id,))
  runs = cur.fetchall()
  print("planning_runs:", [(x["planning_run_id"][:8], x["run_status"], (x["failure_reason"] or "")[:80]) for x in runs])
  check("exactly one planning_run, run_status=failed", len(runs) == 1 and runs[0]["run_status"] == "failed")
  check("planning_runs.failure_reason names ContractViolation", bool(runs) and "ContractViolation" in (runs[0]["failure_reason"] or ""))
  # 3. FAILED diagnostics row
  cur.execute("SELECT planning_run_id, acceptance_passed, acceptance_score, diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id=%s ORDER BY created_at DESC", (clone_id,))
  diags = cur.fetchall()
  labels = []
  for d in diags:
    dj = json.loads(d["diagnostics_json"] or "{}")
    labels.append(((d["planning_run_id"] or "")[:8], d["acceptance_passed"], dj.get("acceptance_score_label"), dj.get("failure_exception_class"), (dj.get("failure_detail") or "")[:60]))
  print("diagnostics rows:", labels)
  check("FAILED diagnostics row present (label FAILED, class RestructureNetDeadError)",
        any(l[2] == "FAILED" and l[3] == "RestructureNetDeadError" for l in labels))
  check("NO passed diagnostics row", not any(l[1] in (1, True) for l in labels))
  # 4. draft row: repair_guidance dead_net record, planning_run_json failed
  cur.execute("SELECT planning_run_status, planning_failure_reason, repair_guidance_json, planning_run_json FROM intake_consult_drafts WHERE draft_id=%s", (clone_id,))
  d = cur.fetchone()
  rg = (json.loads(d["repair_guidance_json"] or "{}").get("restructure") or {})
  print("draft: planning_run_status", d["planning_run_status"], "| failure", (d["planning_failure_reason"] or "")[:80])
  print("repair_guidance.restructure: dead_net", json.dumps(rg.get("dead_net"), default=str)[:200], "| final_passed", rg.get("final_passed"), "| active_directive", rg.get("active_directive"))
  hist = rg.get("history") or []
  print("  history stages:", [(h.get("stage"), h.get("found"), h.get("evals"), h.get("dead_net")) for h in hist])
  check("repair_guidance dead_net record (violation named, rungs>0)",
        isinstance(rg.get("dead_net"), dict) and "ContractViolation" in str(rg["dead_net"].get("violation")) and int(rg["dead_net"].get("rungs") or 0) > 0)
  check("repair_guidance final_passed False, active_directive None", rg.get("final_passed") is False and rg.get("active_directive") is None)
  check("search stage evals=0 dead_net=True", any(h.get("dead_net") is True and h.get("evals") == 0 for h in hist))
  pr = json.loads(d["planning_run_json"] or "{}")
  check("draft planning_run_status=failed", d["planning_run_status"] == "failed", f"planning_run_json.run_status={pr.get('run_status')}")
  # 5. NO workbook delivered, NO passed email
  cur.execute("SELECT COUNT(*) AS n FROM workbook_deliveries WHERE draft_id=%s", (clone_id,))
  n_wb = cur.fetchone()["n"]
  check("NO workbook delivery record", n_wb == 0, f"workbook_deliveries rows={n_wb}")
  if runs and "client_workbook_path" in runs[0]:
    check("NO client_workbook_path on the run", not any((x.get("client_workbook_path") or "") for x in runs))
  cur.close()
  print()
  print("clone draft:", clone_id)
  print("RESULT:", "ALL GREEN" if not FAILS else f"RED ({len(FAILS)}): {FAILS}")
  return 0 if not FAILS else 1


if __name__ == "__main__":
  sys.exit(main())
