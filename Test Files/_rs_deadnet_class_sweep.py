"""DEAD-NET CLASS SWEEP across every completed per-line-COGS draft.

For drafts whose run PASSED acceptance the restructure never fired, so no
executive bounds are persisted. To prove the CLASS (the contract-validity
of synthesized new lines on any per-line-COGS draft), each such draft gets
STRUCTURAL bounds built deterministically from its own rows through the
system's own validate_restructure_bounds (existing lines at their stated
levels, ONE new-line candidate sized at 15% of Q11 revenue with an
authored 0.50 margin, team/facility at base levels). Persisted executive
bounds are used verbatim where they exist (Nine Fathom).

Per draft: PRE (pre-fix searcher: COGS % row stripped) -> prepared model
contract-invalid + joint solve dies; POST (fixed searcher) -> prepared
model CONTRACT VALID + joint solve EVALUATES (evals>0) or raises loud.
"""
import json, sys, time, importlib.util
sys.path.insert(0, "C:/dev/business_plann_app/python")
spec = importlib.util.spec_from_file_location("r", "C:/dev/business_plann_app/Test Files/_rs_deadnet_repro.py")
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

from client_intake_and_finmo.post_intake_restructure import joint_solver as js
from client_intake_and_finmo.post_intake_restructure.joint_solver import RestructureNetDeadError
from client_intake_and_finmo.post_intake_restructure.searcher import _base_levels, _base_line_revenue_series
from client_intake_and_finmo.post_intake_restructure.constraint_author import validate_restructure_bounds
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import ModelInputSections

_real_synth = js.synthesize_new_line_rows
def _prefix_synth(*a, **k):
  return [x for x in _real_synth(*a, **k) if x.get("driver") != "COGS %"]


def structural_bounds(mi):
  rows = mi["sections"]["revenue"]
  by = {}
  for x in rows:
    by.setdefault((x["lob"], x["product"]), {})[x["driver"]] = x["values"]
  lines = []
  for (lob, prod), d in by.items():
    cogs1 = float((d.get("COGS %") or [0, 0.5])[1])
    lines.append({"lob": lob, "product": prod, "price_multiplier_max": 1.10, "volume_multiplier_max": 1.20,
                  "can_drop": False, "gross_margin_pct": round(1 - cogs1, 4), "rationale": "structural"})
  first = next(iter(by.values()))
  price = float(first["Unit Price"][1]) or 10.0
  q11 = sum(s[11] for s in _base_line_revenue_series(mi).values())
  bl = _base_levels(mi)
  raw = {
    "feasible_region_exists": True,
    "reality_constraints": {k: "structural sweep" for k in ("real_market", "real_physics", "still_this_business", "lender_defensible")},
    "existing_lines": lines,
    "new_line_candidates": [{"lob": lines[0]["lob"], "product": "Sweep New Line", "unit_price": round(price, 2),
                             "q11_quarterly_revenue_max": round(0.15 * q11, 2), "gross_margin_pct": 0.50, "rationale": "structural"}],
    "team": {"min_annual_payroll": round(0.8 * float(bl.get("annual_payroll") or 0.0), 2),
             "max_annual_payroll": round(float(bl.get("annual_payroll") or 0.0), 2), "structure_at_min": "structural"},
    "facility": {"min_quarterly_rent": round(0.8 * float(bl.get("quarterly_rent") or 0.0), 2),
                 "max_quarterly_rent": round(float(bl.get("quarterly_rent") or 0.0), 2)},
    "cost_floors": {"cogs_percent_of_revenue_min": 0.10, "marketing_percent_of_revenue_min": 0.01, "g_and_a_percent_of_revenue_min": 0.01},
    "growth": {}, "overall_rationale": "structural sweep bounds",
  }
  return validate_restructure_bounds(bounds=raw, stated_owner_annual_wage=0.0)


def contract_ok(mi, bounds):
  try:
    ModelInputSections.model_validate(js._prepare_restructure_model(mi, bounds)["sections"])
    return True, ""
  except Exception as exc:  # noqa: BLE001
    return False, str(exc)[:160]


def solve(mi, bounds, ops, fin, rt):
  pm = str(rt.get("planning_mode") or "").strip() or None
  naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None
  try:
    res = js.run_restructure_joint_solve(base_model_input=mi, bounds=bounds, business_naics_6=naics, ops_json=ops, financials_json=fin, planning_mode=pm)
    errs = [t for t in res["trace"] if "solve_raised" in t]
    return {"found": res["found"], "evals": res["evals"], "rung_errors": len(errs), "raised": None}
  except RestructureNetDeadError as exc:
    return {"found": False, "evals": 0, "rung_errors": exc.rungs, "raised": "RestructureNetDeadError:" + exc.violation[:90]}


conn = r._conn()
prefixes = sys.argv[1:] or ["6d2823db", "fd3d1b02", "d9b17850", "cw32wb0b", "cw32wb08", "plcogsaa", "plcogsd6", "plcogs43"]
table = []
for p in prefixes:
  row, mi, rt, ops, fin, bounds = r._load(conn, p)
  src = "executive(persisted)" if bounds else "structural"
  if not bounds:
    bounds = structural_bounds(mi)
  n_slots = len({x["revenue_slot_key"] for x in mi["sections"]["revenue"]})
  js.synthesize_new_line_rows = _prefix_synth
  pre_ok, pre_err = contract_ok(mi, bounds)
  pre = solve(mi, bounds, ops, fin, rt)
  js.synthesize_new_line_rows = _real_synth
  post_ok, post_err = contract_ok(mi, bounds)
  t0 = time.perf_counter(); post = solve(mi, bounds, ops, fin, rt); el = time.perf_counter() - t0
  rec = {"draft": row["draft_id"][:8], "name": row["business_name"][:28], "slots": n_slots, "bounds": src,
         "PRE_contract": pre_ok, "PRE_evals": pre["evals"], "PRE_raised": (pre["raised"] or "")[:60],
         "POST_contract": post_ok, "POST_evals": post["evals"], "POST_found": post["found"], "POST_raised": post["raised"], "secs": round(el, 1)}
  table.append(rec)
  print(json.dumps(rec), flush=True)
conn.close()
print("\nCLASS SWEEP SUMMARY")
print(f"{'draft':9}{'business':30}{'slots':6}{'bounds':22}{'PRE ctr':9}{'PRE ev':7}{'PRE dead-net raise':20}{'POST ctr':10}{'POST ev':8}{'POST found':11}")
for t in table:
  print(f"{t['draft']:9}{t['name']:30}{t['slots']:<6}{t['bounds']:22}{str(t['PRE_contract']):9}{t['PRE_evals']:<7}{('YES' if t['PRE_raised'] else 'no'):20}{str(t['POST_contract']):10}{t['POST_evals']:<8}{str(t['POST_found']):11}")
allgood = all(t["POST_contract"] and t["POST_evals"] > 0 and not t["POST_raised"] and not t["PRE_contract"] and t["PRE_evals"] == 0 and t["PRE_raised"] for t in table)
print("CLASS RESTORED:", allgood)
