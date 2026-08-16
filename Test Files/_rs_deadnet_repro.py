"""DEAD RESTRUCTURE NET red-proof + sweep (Nick 08-16 ruling).

Offline: replays run_restructure_joint_solve on a draft's PERSISTED
model_input + the executive bounds persisted in repair_guidance_json
(no GPT call). Prints found / evals / per-rung trace, whether every
rung died on an identical exception, and (POST) whether the synthesized
new-line rows carry a contract-valid COGS % row.

Usage: python "Test Files/_rs_deadnet_repro.py" <draft_prefix> [<draft_prefix> ...]
       python "Test Files/_rs_deadnet_repro.py" --sweep   (all completed per-line-COGS drafts with persisted bounds)
"""
import json
import os
import sys
import time
import traceback

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")


def _conn():
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
  )


def _load(conn, prefix):
  cur = conn.cursor(dictionary=True)
  cur.execute(
    "SELECT draft_id, business_name, model_input_json, planning_runtime_json, "
    "operating_model_json, financials_json, repair_guidance_json "
    "FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
  row = cur.fetchone()
  cur.close()
  if not row:
    raise SystemExit(f"no draft {prefix}")
  j = lambda k: json.loads(row[k]) if row.get(k) else {}
  g = j("repair_guidance_json")
  hist = (g.get("restructure") or {}).get("history") or []
  bounds = next((it.get("bounds") for it in hist if it.get("stage") == "bounds" and it.get("bounds")), None)
  return row, j("model_input_json"), j("planning_runtime_json"), j("operating_model_json"), j("financials_json"), bounds


def _per_line_cogs(mi):
  rows = ((mi.get("sections") or {}).get("revenue") or [])
  slots = {}
  for r in rows:
    if isinstance(r, dict):
      slots.setdefault(r.get("revenue_slot_key"), set()).add(r.get("driver"))
  return {k: ("COGS %" in v) for k, v in slots.items()}


def run_one(conn, prefix):
  row, mi, runtime, ops, fin, bounds = _load(conn, prefix)
  did = row["draft_id"]
  print(f"=== {did[:8]} {row['business_name']}")
  plc = _per_line_cogs(mi)
  print(f"  base slots: {len(plc)} per-line COGS on {sum(plc.values())} slot(s)")
  if not bounds:
    print("  NO persisted bounds (restructure never authored bounds on this draft) - skipping solve")
    return {"draft": did, "skipped": "no_bounds"}
  print(f"  bounds: feasible={bounds.get('feasible_region_exists')} new_line_candidates={len(bounds.get('new_line_candidates') or [])}")
  from client_intake_and_finmo.post_intake_restructure.joint_solver import run_restructure_joint_solve
  from client_intake_and_finmo.post_intake_restructure import joint_solver as _js
  from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import ModelInputSections
  # POST-only structural check: the prepared model must validate against
  # the contract (the synthesized new lines must be born contract-valid).
  prepared = _js._prepare_restructure_model(mi, bounds)
  new_rows = [r for r in prepared["sections"]["revenue"] if r not in mi["sections"]["revenue"]]
  cogs_new = [r for r in new_rows if r.get("driver") == "COGS %"]
  print(f"  prepared: +{len(new_rows)} synthesized rows, {len(cogs_new)} COGS % rows among them")
  for r in cogs_new:
    print(f"    COGS row slot={r.get('revenue_slot_key')} lever={r.get('lever_id')} cw={r.get('controller_write')} dd={r.get('derived_driver')} sem={r.get('input_semantics')} v[1..3]={r.get('values')[1:4]}")
  try:
    ModelInputSections.model_validate(prepared["sections"])
    print("  prepared model: CONTRACT VALID")
    contract_ok = True
  except Exception as exc:
    print(f"  prepared model: CONTRACT INVALID -> {type(exc).__name__}: {str(exc)[:200]}")
    contract_ok = False
  planning_mode = str(runtime.get("planning_mode") or "").strip() or None
  naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None
  t0 = time.perf_counter()
  raised = None
  result = None
  try:
    result = run_restructure_joint_solve(
      base_model_input=mi, bounds=bounds, business_naics_6=naics,
      ops_json=ops, financials_json=fin, planning_mode=planning_mode)
  except Exception as exc:  # noqa: BLE001
    raised = exc
  el = time.perf_counter() - t0
  if raised is not None:
    print(f"  SOLVE RAISED {type(raised).__name__} after {el:.1f}s: {str(raised)[:300]}")
    return {"draft": did, "raised": type(raised).__name__, "detail": str(raised)[:300], "contract_ok": contract_ok}
  print(f"  found={result['found']} evals={result['evals']} in {el:.1f}s")
  for line in result["trace"]:
    print("    ", str(line)[:220])
  rung_errs = [str(t) for t in result["trace"] if "solve_raised" in str(t)]
  identical = len(rung_errs) >= 1 and len(set(e.split(":", 1)[1] for e in rung_errs)) == 1
  print(f"  rung errors: {len(rung_errs)} identical={identical}")
  sc = result.get("score") or {}
  print(f"  score: viable={sc.get('viable_pnl')} failed={sc.get('failed_binding')}")
  return {"draft": did, "found": result["found"], "evals": result["evals"], "rung_errors": len(rung_errs), "identical": identical, "contract_ok": contract_ok}


def main():
  conn = _conn()
  args = sys.argv[1:]
  if args and args[0] == "--sweep":
    cur = conn.cursor(dictionary=True)
    cur.execute(
      "SELECT draft_id, business_name FROM intake_consult_drafts "
      "WHERE repair_guidance_json LIKE '%new_line_candidates%' "
      "AND model_input_json LIKE '%per_line_cogs_source%' ORDER BY updated_at DESC")
    args = [r["draft_id"] for r in cur.fetchall()]
    cur.close()
    print(f"SWEEP: {len(args)} drafts with per-line COGS + persisted restructure bounds")
  out = []
  for p in args:
    try:
      out.append(run_one(conn, p))
    except Exception:
      traceback.print_exc()
  print("\nSUMMARY")
  for o in out:
    print(" ", json.dumps(o))
  conn.close()


if __name__ == "__main__":
  main()
