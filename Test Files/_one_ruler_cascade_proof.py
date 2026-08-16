"""ONE RULER proof (FIX 3): the in-loop cascade's net_income_trajectory_viable
must read the SAME floor the final acceptance gate reads.

For every draft with a persisted model_input_json + finmo_json:
  PRE  = _evaluate_in_cascade(finmo_json=fj)                       (finmo-only)
  POST = _evaluate_in_cascade(finmo_json=fj, model_input_json=mi)  (the fix)
  GATE = gate._check_net_income_trajectory_viable(fj, mi)          (the ruler)
Neighbor-check: every NON-NI check in the cascade result must be identical
PRE vs POST (passed + detail). ONE-RULER assertion: POST NI detail ==
GATE NI detail (same floor value + same floor source). Flips: any draft
where PRE.passed != POST.passed is enumerated with its floor + margins for
adjudication.

Same-input comparison by construction: both readings use the draft's own
persisted finmo_json (what the gate itself judges), so a floor difference
is the ONLY possible source of disagreement.

Run pre-fix for the RED baseline (POST is unavailable -> the harness
reports the PRE-vs-GATE mismatch), post-fix for GREEN.
"""
import json, os, sys, inspect, traceback
from dotenv import load_dotenv
import mysql.connector
load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

import importlib
ep = importlib.import_module("client_intake_and_finmo.post_intake_amalgamated.evaluate_plan")
from client_intake_and_finmo.post_intake_acceptance import gate

def _conn():
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306))

def _load(conn, only):
  cur = conn.cursor(dictionary=True)
  if only:
    q = ("SELECT draft_id, business_name, planning_run_status, model_input_json, finmo_json "
         "FROM intake_consult_drafts WHERE " + " OR ".join(["draft_id LIKE %s"] * len(only)))
    cur.execute(q, tuple(p + "%" for p in only))
  else:
    cur.execute(
      "SELECT draft_id, business_name, planning_run_status, model_input_json, finmo_json "
      "FROM intake_consult_drafts WHERE finmo_json IS NOT NULL AND finmo_json <> '' "
      "AND model_input_json IS NOT NULL AND model_input_json <> '' "
      "AND finmo_json LIKE '%quarter_rows%' ORDER BY updated_at DESC")
  rows = cur.fetchall(); cur.close()
  return rows

def _by_name(results):
  out = {}
  for r in results:
    out[r.name] = {"passed": bool(r.passed), "detail": r.detail,
                   "distance": r.distance_to_feasibility, "units": r.distance_units}
  return out

def main():
  only = [a for a in sys.argv[1:] if not a.startswith("--")]
  conn = _conn()
  rows = _load(conn, only)
  post_supported = "model_input_json" in inspect.signature(ep._evaluate_in_cascade).parameters
  print(f"ONE RULER PROOF - {len(rows)} drafts ; cascade accepts model_input_json = {post_supported}")
  flips, mismatch_one_ruler, neighbor_diffs, errors = [], [], [], []
  agree_pre = 0; total = 0
  for row in rows:
    did = row["draft_id"]; name = (row.get("business_name") or "")[:28]
    try:
      mi = json.loads(row["model_input_json"] or "{}"); fj = json.loads(row["finmo_json"] or "{}")
    except Exception as e:
      errors.append((did, f"json:{e}")); continue
    if not isinstance(fj, dict) or not fj.get("quarter_rows"):
      continue
    total += 1
    try:
      pre = _by_name(ep._evaluate_in_cascade(finmo_json=fj)[0])
      post = _by_name(ep._evaluate_in_cascade(finmo_json=fj, model_input_json=mi)[0]) if post_supported else None
      g_pass, g_det = gate._check_net_income_trajectory_viable(fj, mi)
    except Exception as e:
      errors.append((did, f"{type(e).__name__}:{str(e)[:120]}")); traceback.print_exc(); continue
    pre_ni = pre.get("net_income_trajectory_viable") or {}
    pre_src = (pre_ni.get("detail") or {}).get("flat_floor_source")
    pre_floor = (pre_ni.get("detail") or {}).get("min_required_q11_margin_flat")
    g_src = g_det.get("flat_floor_source"); g_floor = g_det.get("min_required_q11_margin_flat")
    q11 = g_det.get("q11_ni_margin"); delta = g_det.get("q5_to_q11_delta")
    line = (f"{did[:8]} {name:<28} run={str(row.get('planning_run_status')):<9} q11={q11!s:<8} d={delta!s:<8} "
            f"PRE cascade={pre_ni.get('passed')!s:<5} floor={pre_floor} ({pre_src}) | GATE={g_pass!s:<5} floor={g_floor} ({g_src})")
    if post is not None:
      post_ni = post.get("net_income_trajectory_viable") or {}
      p_src = (post_ni.get("detail") or {}).get("flat_floor_source")
      p_floor = (post_ni.get("detail") or {}).get("min_required_q11_margin_flat")
      line += f" | POST cascade={post_ni.get('passed')!s:<5} floor={p_floor} ({p_src}) dist={post_ni.get('distance')}"
      # ONE RULER: POST cascade NI == gate NI (passed + full detail)
      if not (post_ni.get("passed") == bool(g_pass) and post_ni.get("detail") == g_det):
        mismatch_one_ruler.append((did, post_ni, g_pass, g_det))
        line += "  ONE-RULER-MISMATCH"
      # NEIGHBORS: every non-NI check identical PRE vs POST
      for k in sorted(set(pre) | set(post)):
        if k == "net_income_trajectory_viable":
          continue
        if pre.get(k) != post.get(k):
          neighbor_diffs.append((did, k, pre.get(k), post.get(k)))
          line += f"  NEIGHBOR-DIFF:{k}"
      if pre_ni.get("passed") != post_ni.get("passed"):
        flips.append((did, name, pre_ni.get("passed"), post_ni.get("passed"), q11, delta, p_floor, p_src, row.get("planning_run_status")))
        line += "  FLIP"
    else:
      if pre_ni.get("passed") == bool(g_pass) and pre_ni.get("detail") == g_det:
        agree_pre += 1
      else:
        mismatch_one_ruler.append((did, pre_ni, g_pass, g_det))
        line += "  PRE!=GATE (two rulers)"
    print(line)
  print()
  print(f"drafts evaluated: {total}")
  if post_supported:
    print(f"NEIGHBOR-CHECK: {'GREEN - every non-NI cascade check identical PRE vs POST' if not neighbor_diffs else 'RED'} ({len(neighbor_diffs)} diffs)")
    for d in neighbor_diffs: print("  ", d)
    print(f"ONE-RULER: {'GREEN - POST cascade NI == gate NI on every draft' if not mismatch_one_ruler else 'RED'} ({len(mismatch_one_ruler)} mismatches)")
    for d in mismatch_one_ruler[:10]: print("  ", d[0][:8], d[1].get("passed"), (d[1].get("detail") or {}).get("flat_floor_source"), "gate", d[2], d[3].get("flat_floor_source"))
    print(f"FLIPS (PRE cascade verdict != POST cascade verdict): {len(flips)}")
    for f in flips:
      print(f"   {f[0][:8]} {f[1]:<28} run={f[8]} PRE={f[2]} -> POST={f[3]}  q11={f[4]} delta={f[5]} floor={f[6]} ({f[7]})")
  else:
    print(f"PRE baseline: cascade NI == gate NI on {agree_pre}/{total}; TWO-RULER mismatches: {len(mismatch_one_ruler)} (RED - the bug)")
    for d in mismatch_one_ruler: print("  ", d[0][:8], "cascade", d[1].get("passed"), (d[1].get("detail") or {}).get("flat_floor_source"), "| gate", d[2], d[3].get("flat_floor_source"), d[3].get("min_required_q11_margin_flat"))
  if errors:
    print("ERRORS:", errors)
  ok = post_supported and not neighbor_diffs and not mismatch_one_ruler and not errors
  print("VERDICT:", "GREEN" if ok else ("RED (pre-fix baseline)" if not post_supported else "RED"))
  return 0 if ok else 1

if __name__ == "__main__":
  sys.exit(main())
