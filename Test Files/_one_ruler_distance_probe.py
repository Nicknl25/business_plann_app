"""FIX 3 companion: NI distance_to_feasibility PRE (old key set: floor read as 0.0)
vs POST (gate's actual floor key) on every draft whose cascade NI check FAILS."""
import json, importlib, sys
sys.path.insert(0, "C:/dev/business_plann_app/python")
sys.path.insert(0, "C:/dev/business_plann_app/Test Files")
import _one_ruler_cascade_proof as h
ep = importlib.import_module("client_intake_and_finmo.post_intake_amalgamated.evaluate_plan")
from client_intake_and_finmo.post_intake_acceptance import gate
conn = h._conn()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT draft_id, business_name, planning_run_status, model_input_json, finmo_json FROM intake_consult_drafts WHERE finmo_json LIKE '%quarter_rows%' AND model_input_json <> '' ORDER BY updated_at DESC")
rows = cur.fetchall()
print("NI distance PRE (floor unread -> 0.0) vs POST (floor-aware) on every draft where the cascade NI check FAILS:")
n = sign_flips = 0; exec_floor = 0; skipped = 0
for row in rows:
  mi = json.loads(row["model_input_json"] or "{}"); fj = json.loads(row["finmo_json"] or "{}")
  if not fj.get("quarter_rows"): continue
  post = {r.name: r for r in ep._evaluate_in_cascade(finmo_json=fj, model_input_json=mi)[0]}
  ni = post["net_income_trajectory_viable"]
  if ni.passed: continue
  d = ni.detail
  if "q11_ni_margin" not in d:
    skipped += 1; print(f"  {row['draft_id'][:8]} NI fails on {d.get('reason')} (no margins) dist={ni.distance_to_feasibility}"); continue
  q11 = d["q11_ni_margin"]; delta = d["q5_to_q11_delta"]
  pre_dist = min(q11 - 0.0, delta - 0.02)
  n += 1
  if d.get("flat_floor_source") == "executive_margin_band_judgment": exec_floor += 1
  if (pre_dist < 0) != (ni.distance_to_feasibility < 0): sign_flips += 1
  print(f"  {row['draft_id'][:8]} {(row['business_name'] or '')[:26]:<26} run={row['planning_run_status']!s:<9} q11={q11} delta={delta} floor={d.get('min_required_q11_margin_flat')} ({d.get('flat_floor_source')})  PRE dist={pre_dist:+.4f} -> POST dist={ni.distance_to_feasibility:+.4f}")
print(f"failing-NI drafts with margins: {n} (executive floor on {exec_floor}); no-margin reason rows: {skipped}; SIGN FLIPS: {sign_flips}")
