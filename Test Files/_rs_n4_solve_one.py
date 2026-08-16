import sys, json, importlib.util
sys.path.insert(0, "C:/dev/business_plann_app/python")
HERE = "C:/dev/business_plann_app/Test Files/"
which, prefix = sys.argv[1], sys.argv[2]
def _mod(name, path):
  spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
r = _mod("r", HERE + "_rs_deadnet_repro.py")
if which == "PRE":
  mod = _mod("js_pre", HERE + "_rs_n4_joint_solver_PRE.py")
else:
  from client_intake_and_finmo.post_intake_restructure import joint_solver as mod
proof = _mod("proof_helpers", HERE + "_rs_n4_shape_proof.py") if False else None
from client_intake_and_finmo.post_intake_restructure.searcher import _base_levels, _base_line_revenue_series
from client_intake_and_finmo.post_intake_restructure.constraint_author import validate_restructure_bounds
conn = r._conn()
row, mi, rt, ops, fin, bounds = r._load(conn, prefix)
conn.close()
if not bounds:
  # same structural bounds as the class sweep
  spec = importlib.util.spec_from_file_location("sw", HERE + "_rs_deadnet_class_sweep.py")
  src = open(HERE + "_rs_deadnet_class_sweep.py", encoding="utf-8").read().split("conn = r._conn()")[0]
  ns = {}
  exec(compile(src, "sweep_defs", "exec"), ns)
  bounds = ns["structural_bounds"](mi)
pm = str(rt.get("planning_mode") or "").strip() or None
naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None
try:
  res = mod.run_restructure_joint_solve(base_model_input=mi, bounds=bounds, business_naics_6=naics, ops_json=ops, financials_json=fin, planning_mode=pm)
  out = {"which": which, "draft": prefix, "found": res["found"], "evals": res["evals"], "raised": None}
except Exception as exc:  # noqa: BLE001
  out = {"which": which, "draft": prefix, "found": False, "evals": 0, "raised": type(exc).__name__ + ": " + str(exc)[:200]}
print("RESULT " + json.dumps(out))
