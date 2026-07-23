"""FLEET PROOF for landing-fidelity #2 + #3.

#3 (bounds as output invariants): re-run the joint solve in-process on
each restructured fleet business (current model_input + its persisted
authored bounds) and assert the emitted directive satisfies the bounds
that authored it: team wages within [min,max], rent target within
[min,max], cost pcts at/above floors. Glaze must still find NOTHING
(no non-viable business starts passing).

#2 (rent directive lands): simulate the runner's facility consumption
glide on a copy of the model_input with the solved rent target, then
fast-build + score: the Lease row must glide stated->target by Q11 and
the design must remain viable (verify-what-you-ship, now including
rent). Read-only DB; all computation on deep copies."""
import copy
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

from client_intake_and_finmo.post_intake_restructure.joint_solver import (
    run_restructure_joint_solve,
)
from client_intake_and_finmo.post_intake_restructure.searcher import (
    candidate_to_directive,
)
from client_intake_and_finmo.post_intake_restructure.fast_evaluator import (
    build_fast_finmo,
    score_viability,
)

CASES = [
    ("Understory", "ea30f6dc", False),
    ("Redux", "17d8793b", False),
    ("Glaze", "195d85e4", False),
]
# NOTE: a synthetic "degraded Redux" case was tried and removed — scaling
# the landed payroll breaks the stated-wages/burden-factor relationship
# (bf rails at 2.0, the loaded floor exceeds the base) and produces
# artifacts, not evidence. The live exercise of the clamps + facility
# landing is a REAL restructure run via the bypass harness with a
# degrading override (see _logs_rent_restructure_canary*.txt).


def degrade(mi):
    out = copy.deepcopy(mi)
    for row in ((out.get("sections") or {}).get("expenses") or []):
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        vals = row.get("values")
        if not isinstance(vals, list):
            continue
        if label == "Lease":
            row["values"] = [19500.0 for _ in vals]
        elif label == "Payroll":
            row["values"] = [round(float(v) * 1.85, 2) for v in vals]
            row.pop("derived_driver", None)
            row.pop("payroll_headcount_schedule", None)
            row["controller_write"] = True
        elif label == "Marketing":
            row["values"] = [0.18 for _ in vals]
        elif label == "General & Administrative":
            row["values"] = [0.15 for _ in vals]
    # a degraded base must not carry the landed schedule authority —
    # the solve treats Payroll as a plain lever
    for store in ("derived_driver_runtime", "derived_driver_policies"):
        if isinstance(out.get(store), dict):
            out[store].pop("expenses::Payroll", None)
    return out

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


ok_all = True
for label, prefix, use_degraded in CASES:
    cur.execute(
        "SELECT draft_id, operating_model_json, financials_json, model_input_json, "
        "repair_guidance_json, planning_runtime_json FROM intake_consult_drafts "
        "WHERE draft_id LIKE %s ORDER BY updated_at DESC LIMIT 1", (prefix + "%",))
    r = cur.fetchone()
    ops = _j(r.get("operating_model_json"))
    fin = _j(r.get("financials_json"))
    mi = _j(r.get("model_input_json"))
    rg = _j(r.get("repair_guidance_json"))
    rest = rg.get("restructure") or {}
    bounds = None
    for h in rest.get("history") or []:
        if isinstance(h, dict) and h.get("stage") == "bounds" and isinstance(h.get("bounds"), dict):
            bounds = h["bounds"]
            break
    if not bounds:
        print(f"{label}: no persisted bounds — skipped")
        continue
    planning_mode = str(_j(r.get("planning_runtime_json")).get("planning_mode") or "") or None
    naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None
    if use_degraded:
        mi = degrade(mi)
        pre = score_viability(
            model_input_json=copy.deepcopy(mi),
            finmo_json=build_fast_finmo(copy.deepcopy(mi)),
            business_naics_6=naics, ops_json=ops, financials_json=fin,
            planning_mode=planning_mode,
        )
        print(f"  [degraded base viable={pre.get('viable_pnl')} failed={pre.get('failed_binding')}]")
        if pre.get("viable_pnl"):
            print("  DEGRADATION INSUFFICIENT - case vacuous")
            ok_all = False

    result = run_restructure_joint_solve(
        base_model_input=copy.deepcopy(mi),
        bounds=copy.deepcopy(bounds),
        business_naics_6=naics,
        ops_json=ops,
        financials_json=fin,
        planning_mode=planning_mode,
    )
    found = bool(result.get("found"))
    print(f"=== {label} ({r['draft_id'][:10]}): solve found={found} ===")

    if label == "Glaze":
        ok = not found
        ok_all = ok_all and ok
        print(f"  expected found=False (doomed stays doomed): {'OK' if ok else 'VIOLATED'}")
        continue

    if not found:
        # current model_input is the already-rescued landed state — the
        # solve may find it needs nothing; treat a no-candidate result
        # on a viable base as acceptable only if the base scores viable.
        base_score = score_viability(
            model_input_json=copy.deepcopy(mi),
            finmo_json=build_fast_finmo(copy.deepcopy(mi)),
            business_naics_6=naics, ops_json=ops, financials_json=fin,
            planning_mode=planning_mode,
        )
        ok = bool(base_score.get("viable_pnl"))
        ok_all = ok_all and ok
        print(f"  no candidate; base already viable: {ok}")
        continue

    candidate = result.get("candidate") or {}
    directive = candidate_to_directive(
        candidate=candidate,
        bounds=bounds,
        base_levels=result.get("base_levels") or {},
        base_model_input=mi,
        line_margins=result.get("line_margins") or None,
        payroll_burden_factor=float(result.get("payroll_burden_factor") or 1.0),
    ) if not isinstance(result.get("directive"), dict) else result["directive"]

    team_b = bounds.get("team") or {}
    fac_b = bounds.get("facility") or {}
    floors = bounds.get("cost_floors") or {}
    t = (directive.get("team") or {}).get("annual_payroll")
    rent = (directive.get("facility") or {}).get("quarterly_rent_target")
    cs = directive.get("cost_structure") or {}
    checks = {
        "team>=floor": t is None or float(t) >= float(team_b.get("min_annual_payroll") or 0) - 0.01,
        "team<=max": t is None or not team_b.get("max_annual_payroll")
                     or float(t) <= float(team_b["max_annual_payroll"]) + 0.01,
        "rent in bounds": rent is None or (
            float(rent) >= float(fac_b.get("min_quarterly_rent") or 0) - 0.01
            and (not fac_b.get("max_quarterly_rent") or float(rent) <= float(fac_b["max_quarterly_rent"]) + 0.01)),
        "mkt>=floor": cs.get("marketing_percent_of_revenue") is None
                      or float(cs["marketing_percent_of_revenue"]) >= float(floors.get("marketing_percent_of_revenue_min") or 0) - 1e-9,
        "gna>=floor": cs.get("g_and_a_percent_of_revenue") is None
                      or float(cs["g_and_a_percent_of_revenue"]) >= float(floors.get("g_and_a_percent_of_revenue_min") or 0) - 1e-9,
    }
    print(f"  directive: team {t}  rent {rent}  clamps {directive.get('invariant_clamps')}")
    for name, passed in checks.items():
        print(f"    {name}: {'OK' if passed else 'VIOLATED'}")
    ok = all(checks.values())

    # #2: land the rent via the runner's glide semantics and re-verify.
    if rent is not None and float(rent) > 0:
        mi2 = copy.deepcopy(mi)
        for row in ((mi2.get("sections") or {}).get("expenses") or []):
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Lease":
                vals = row.get("values")
                if isinstance(vals, list) and len(vals) >= 3:
                    q1 = float(vals[1])
                    for q in range(2, min(21, len(vals))):
                        frac = min(1.0, (q - 1) / 10.0)
                        vals[q] = round(q1 + (float(rent) - q1) * frac, 2)
        lease_vals = next((row.get("values") for row in ((mi2.get("sections") or {}).get("expenses") or [])
                           if isinstance(row, dict) and row.get("label") == "Lease"), [])
        glide_ok = abs(float(lease_vals[11]) - float(rent)) <= 0.01 and abs(float(lease_vals[1]) - float(mi["sections"]["expenses"][[i for i, rr in enumerate(mi["sections"]["expenses"]) if rr.get("label") == "Lease"][0]]["values"][1])) <= 0.01
        score2 = score_viability(
            model_input_json=mi2, finmo_json=build_fast_finmo(copy.deepcopy(mi2)),
            business_naics_6=naics, ops_json=ops, financials_json=fin,
            planning_mode=planning_mode,
        )
        print(f"  rent landed: Q1 {lease_vals[1]}  Q11 {lease_vals[11]}  glide {'OK' if glide_ok else 'FAIL'}  "
              f"viable with rent landed: {score2.get('viable_pnl')} failed={score2.get('failed_binding')}")
        ok = ok and glide_ok and bool(score2.get("viable_pnl"))
    ok_all = ok_all and ok

print()
print("FLEET PROOF:", "PASS" if ok_all else "FAIL")
cur.close()
conn.close()
