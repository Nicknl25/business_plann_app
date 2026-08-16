"""FIX 3: exercise the PRODUCTION closure session_factory._build_evaluate_plan_fn
(the exact object the session driver calls each round) offline on a real
draft: live_mi seeded from the draft's model_input, finmo rebuilt by the real
build_python_finmo_json (parity assertion runs). Proves live_mi threads
through evaluate_plan(in_cascade=True) -> _evaluate_in_cascade -> the gate NI
check, and the in-loop NI verdict now equals the gate's on the same finmo."""
import copy, json, sys, types
sys.path.insert(0, "C:/dev/business_plann_app/python")
sys.path.insert(0, "C:/dev/business_plann_app/Test Files")
import _one_ruler_cascade_proof as h
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_factory import _build_evaluate_plan_fn
from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import SECTIONS
from client_intake_and_finmo.finmo_bridge import build_python_finmo_json
from client_intake_and_finmo.post_intake_acceptance import gate
from client_intake_and_finmo.post_intake_sequence import post_intake_sequence_step_scope

conn = h._conn()
for prefix in (sys.argv[1:] or ["rsdeadd25e", "6d2823db", "fd3d1b02"]):
  row = h._load(conn, [prefix])[0]
  mi = json.loads(row["model_input_json"]); did = row["draft_id"]
  # the runner passes applied_model_input_json (already carrying margin_band_judgment) as the seed
  with post_intake_sequence_step_scope(step_key='amalgamated_in_cascade_evaluate', phase='post_intake_target_seeking', executor_function='amalgamated_in_cascade_evaluate'):
    entry_finmo = build_python_finmo_json(model_input_json=copy.deepcopy(mi))
  ref = {"mi": copy.deepcopy(mi)}
  mirror = types.SimpleNamespace(plan_state={s: {} for s in SECTIONS})
  fn = _build_evaluate_plan_fn(conn=conn, draft_id=did, planning_run_id="", mirror=mirror,
                               operating_context={}, finmo_json=entry_finmo,
                               live_model_input_ref=ref, build_finmo=build_python_finmo_json,
                               business_naics_6="")
  res = fn(round_number=1)
  ni = next(c for c in res.checks if c.name == "net_income_trajectory_viable")
  g_pass, g_det = gate._check_net_income_trajectory_viable(entry_finmo, mi)
  same = (bool(ni.passed) == bool(g_pass) and ni.detail == g_det)
  print(f"{did[:8]} {row['business_name'][:24]:<24} in-loop NI passed={ni.passed} floor={ni.detail.get('min_required_q11_margin_flat')} src={ni.detail.get('flat_floor_source')} dist={ni.distance_to_feasibility} | gate passed={g_pass} floor={g_det.get('min_required_q11_margin_flat')} src={g_det.get('flat_floor_source')} | ONE RULER {'GREEN' if same else 'RED'} | checks={len(res.checks)} strictness={getattr(res,'strictness',None)}")
