"""FIX 2 red-proof: RestructureNetDeadError fires ONLY on the dead-net
shape (every rung raised the identical exception, evals=0); honest
exhaustion and mixed errors stay quiet. Uses Nine Fathom 6d2823db's
persisted model + bounds; the dead-net shape is re-created by stripping
the COGS % row from the synthesized lines (the pre-fix searcher)."""
import sys, importlib.util
sys.path.insert(0, "C:/dev/business_plann_app/python")
spec = importlib.util.spec_from_file_location("r", "C:/dev/business_plann_app/Test Files/_rs_deadnet_repro.py")
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
# Draft prefix: default the original Nine Fathom; pass a fresh (unmutated)
# clone with persisted bounds instead once 6d2823db holds the rescued plan
# (case E replays the persisted candidates - on the mutated draft they
# collide with lob_3/lob_4 and raise). FIX 2b: the dead-net live-proof
# clones (rsdead...) carry the 3-line base + persisted bounds.
_prefix = sys.argv[1] if len(sys.argv) > 1 else "6d2823db"
conn = r._conn(); row, mi, rt, ops, fin, bounds = r._load(conn, _prefix); conn.close()
print("draft:", row["draft_id"], row["business_name"])

from client_intake_and_finmo.post_intake_restructure import joint_solver as js
from client_intake_and_finmo.post_intake_restructure.joint_solver import RestructureNetDeadError
import client_intake_and_finmo.numeric_solver as ns

_real_synth = js.synthesize_new_line_rows
def _prefix_synth(*a, **k):
  return [x for x in _real_synth(*a, **k) if x.get("driver") != "COGS %"]

def _run():
  return js.run_restructure_joint_solve(base_model_input=mi, bounds=bounds, business_naics_6=None,
                                        ops_json=ops, financials_json=fin, planning_mode=None)

# A. DEAD NET (pre-fix searcher shape): must RAISE, naming the violation.
js.synthesize_new_line_rows = _prefix_synth
try:
  res = _run()
  print("A DEAD NET: NO RAISE  <-- RED", res.get("evals"), res.get("trace")[-3:])
  ok_a = False
except RestructureNetDeadError as exc:
  ok_a = "ContractViolation" in exc.violation and "all-or-nothing" in exc.violation and exc.rungs == 2
  print("A DEAD NET: RAISED", type(exc).__name__, "| rungs", exc.rungs, "| ok", ok_a)
  print("   msg:", str(exc)[:200])
  print("   to_dict keys:", sorted(exc.to_dict().keys()))
finally:
  js.synthesize_new_line_rows = _real_synth

# B. HONEST EXHAUSTION: solver runs, returns no updates on every rung -> quiet, evals=0, found=False.
_real_solve = ns.solve_review_plan
ns.solve_review_plan = lambda **k: {"execution_state": "no_solution", "exact_updates": []}
try:
  res = _run()
  ok_b = res["found"] is False and res["evals"] == 0
  print("B EXHAUSTION: quiet found", res["found"], "evals", res["evals"], "| ok", ok_b, "| tail", res["trace"][-1])
except RestructureNetDeadError as exc:
  ok_b = False; print("B EXHAUSTION: RAISED  <-- RED", exc)
finally:
  ns.solve_review_plan = _real_solve

# C. MIXED ERRORS: rung1 raises X, rung2 raises Y -> quiet (not the identical-signature shape), trace notes it.
_calls = {"n": 0}
def _mixed(**k):
  _calls["n"] += 1
  raise (ValueError("alpha") if _calls["n"] == 1 else KeyError("beta"))
ns.solve_review_plan = _mixed
try:
  res = _run()
  ok_c = res["found"] is False and res["evals"] == 0 and any("dead_search_mixed" in t for t in res["trace"])
  print("C MIXED: quiet | ok", ok_c, "| tail", res["trace"][-1])
except RestructureNetDeadError as exc:
  ok_c = False; print("C MIXED: RAISED  <-- RED", exc)
finally:
  ns.solve_review_plan = _real_solve

# D. IDENTICAL NON-CONTRACT ERROR on every rung -> raise (the class, not the instance).
ns.solve_review_plan = lambda **k: (_ for _ in ()).throw(ZeroDivisionError("solver blew up"))
try:
  res = _run(); ok_d = False; print("D IDENTICAL OTHER: NO RAISE  <-- RED")
except RestructureNetDeadError as exc:
  ok_d = "ZeroDivisionError" in exc.violation; print("D IDENTICAL OTHER: RAISED | ok", ok_d)
finally:
  ns.solve_review_plan = _real_solve

# E. FIXED searcher, real solver: evaluates (evals>0), no raise.
res = _run()
ok_e = res["evals"] > 0
print("E FIXED NET: found", res["found"], "evals", res["evals"], "| ok", ok_e)
print("ALL GREEN" if all([ok_a, ok_b, ok_c, ok_d, ok_e]) else "RED")
