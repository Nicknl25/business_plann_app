"""n4 ONE ROW SHAPE red-proof (Nick 2026-08-16, restructure-path hygiene).

PRE = the HEAD joint_solver (git show HEAD:... captured beside this file as
_rs_n4_joint_solver_PRE.py): _prepare_restructure_model flips EXISTING
per-line COGS % rows to controller_write=True / derived_driver=None (not the
real row shape).
POST = the working-tree joint_solver: existing COGS % rows are byte-identical
to the base draft rows (finmo_bridge's real shape) and shape-identical to the
COGS % row FIX 1 synthesizes for a new line; the joint solve still evaluates
and finds candidates on the class-sweep drafts.
"""
import copy, json, sys, time, importlib.util
sys.path.insert(0, "C:/dev/business_plann_app/python")
HERE = "C:/dev/business_plann_app/Test Files/"


def _mod(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  m = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(m)
  return m


r = _mod("r", HERE + "_rs_deadnet_repro.py")
PRE = _mod("js_pre", HERE + "_rs_n4_joint_solver_PRE.py")
from client_intake_and_finmo.post_intake_restructure import joint_solver as POST
from client_intake_and_finmo.post_intake_restructure.joint_solver import RestructureNetDeadError
from client_intake_and_finmo.post_intake_restructure.searcher import _base_levels, _base_line_revenue_series
from client_intake_and_finmo.post_intake_restructure.constraint_author import validate_restructure_bounds
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import ModelInputSections

SHAPE_KEYS = ("driver", "controller_write", "derived_driver", "value_kind", "input_semantics",
              "payroll_supported_capacity", "capacity_shaping")


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


def cogs_rows(mi):
  return [x for x in mi["sections"]["revenue"] if isinstance(x, dict) and str(x.get("driver") or "").strip() == "COGS %"]


def key(x):
  return f"{x.get('lob')}/{x.get('product')}"


def solve(mod, mi, bounds, ops, fin, rt):
  pm = str(rt.get("planning_mode") or "").strip() or None
  naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None
  try:
    res = mod.run_restructure_joint_solve(base_model_input=mi, bounds=bounds, business_naics_6=naics,
                                          ops_json=ops, financials_json=fin, planning_mode=pm)
    return {"found": res["found"], "evals": res["evals"], "raised": None}
  except Exception as exc:  # noqa: BLE001 - PRE raises its own module's RestructureNetDeadError class
    return {"found": False, "evals": 0, "raised": type(exc).__name__ + ":" + str(getattr(exc, "violation", exc))[:90]}


conn = r._conn()
# 6d2823db (Nine Fathom live draft) is now the POST-RESCUE state (20 rows: the two new lines are
# real rows) so its persisted bounds re-add them and BOTH PRE and POST dead-net on the revenue
# formula contract - a test-input artifact, not a code fact. The pre-rescue clone rsdeadd25e
# (12 rows, same persisted executive bounds) stands in for it.
prefixes = sys.argv[1:] or ["rsdeadd25e", "fd3d1b02", "d9b17850", "cw32wb0b", "cw32wb08", "plcogsaa", "plcogsd6", "plcogs43"]
table = []
for p in prefixes:
  row, mi, rt, ops, fin, bounds = r._load(conn, p)
  src = "executive(persisted)" if bounds else "structural"
  if not bounds:
    bounds = structural_bounds(mi)
  base_cogs = {key(x): x for x in cogs_rows(mi)}
  pre_m = PRE._prepare_restructure_model(copy.deepcopy(mi), bounds)
  post_m = POST._prepare_restructure_model(copy.deepcopy(mi), bounds)
  pre_cogs = {key(x): x for x in cogs_rows(pre_m)}
  post_cogs = {key(x): x for x in cogs_rows(post_m)}
  # PRE: existing rows flipped (controller_write True / derived None) => differ from base
  pre_flipped = sum(1 for k, x in base_cogs.items()
                    if json.dumps(pre_cogs.get(k), sort_keys=True) != json.dumps(x, sort_keys=True))
  pre_cw_true = sum(1 for k in base_cogs
                    if pre_cogs.get(k, {}).get("controller_write") is True and pre_cogs.get(k, {}).get("derived_driver") is None)
  # POST: existing rows byte-identical to base
  post_identical = all(json.dumps(post_cogs.get(k), sort_keys=True) == json.dumps(x, sort_keys=True)
                       for k, x in base_cogs.items())
  # POST: synthesized new-line COGS row shape == existing rows' shape (real finmo_bridge shape)
  new_keys = [k for k in post_cogs if k not in base_cogs]
  shapes_existing = {tuple((s, post_cogs[k].get(s)) for s in SHAPE_KEYS) for k in base_cogs}
  shapes_new = {tuple((s, post_cogs[k].get(s)) for s in SHAPE_KEYS) for k in new_keys}
  one_shape = len(shapes_existing) == 1 and shapes_new <= shapes_existing
  shape = dict(next(iter(shapes_existing))) if shapes_existing else {}
  lever_ok = all(str(post_cogs[k].get("lever_id") or "") ==
                 f"revenue::{post_cogs[k].get('lob')}::{post_cogs[k].get('product')}::COGS %" for k in post_cogs)
  try:
    ModelInputSections.model_validate(post_m["sections"])
    post_contract = True
  except Exception:  # noqa: BLE001
    post_contract = False
  t0 = time.perf_counter()
  post = solve(POST, mi, bounds, ops, fin, rt)
  el = time.perf_counter() - t0
  pre = solve(PRE, mi, bounds, ops, fin, rt)
  rec = {"draft": row["draft_id"][:8], "name": row["business_name"][:26], "bounds": src, "cogs_rows": len(base_cogs),
         "PRE_flipped": pre_flipped, "PRE_cw_true_derived_none": pre_cw_true,
         "POST_identical_to_base": post_identical, "POST_one_shape": one_shape,
         "POST_shape": {"controller_write": shape.get("controller_write"), "derived_driver": shape.get("derived_driver")},
         "POST_lever_ids_ok": lever_ok, "POST_contract": post_contract, "new_cogs_rows": len(new_keys),
         "POST_found": post["found"], "POST_evals": post["evals"], "POST_raised": post["raised"],
         "PRE_found": pre["found"], "PRE_evals": pre["evals"], "secs": round(el, 1)}
  table.append(rec)
  print(json.dumps(rec), flush=True)
conn.close()
print("\nN4 SHAPE PROOF SUMMARY")
print(f"{'draft':9}{'business':28}{'rows':5}{'PRE flipped':12}{'POST ident':11}{'one shape':10}"
      f"{'cw/derived':52}{'lever':7}{'ctr':6}{'found':7}{'evals':7}{'PRE found':10}")
for t in table:
  print(f"{t['draft']:9}{t['name']:28}{t['cogs_rows']:<5}{t['PRE_flipped']:<12}{str(t['POST_identical_to_base']):11}"
        f"{str(t['POST_one_shape']):10}{str(t['POST_shape']):52}{str(t['POST_lever_ids_ok']):7}{str(t['POST_contract']):6}"
        f"{str(t['POST_found']):7}{t['POST_evals']:<7}{str(t['PRE_found']):10}")
red = all(t["PRE_flipped"] == t["cogs_rows"] > 0 and t["PRE_cw_true_derived_none"] == t["cogs_rows"] for t in table)
green = all(t["POST_identical_to_base"] and t["POST_one_shape"] and t["POST_lever_ids_ok"] and t["POST_contract"]
            and t["POST_shape"] == {"controller_write": False, "derived_driver": "per_line_cogs_source"}
            and t["POST_evals"] > 0 and not t["POST_raised"] for t in table)
print("PRE RED (existing COGS % rows flipped on every draft):", red)
print("POST GREEN (byte-identical to base, one shape, solve evaluates):", green)
print("SOLVE found PRE->POST:", [(t["draft"], t["PRE_found"], t["POST_found"]) for t in table])
