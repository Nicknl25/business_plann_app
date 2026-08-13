"""A2: depreciation_quarterly = capex * 0.05 (evaluator.py:384, inline).
Ablate by scaling financials current_capex: x0 == rate 0.0, x1 == 0.05,
x2 == rate 0.10.  Report ni_floor check margin at each point, the per-
dollar-of-capex sensitivity, and the capex level that would flip ni_floor."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ablate_batchA_common import load_drafts, growth_mult_for
from client_intake_and_finmo.intake_coherence.controller import evaluate_current

drafts = load_drafts()
for label, d in drafts.items():
    fin = d["fin"]
    capex = float(fin.get("current_capex") or 0.0)
    gm = growth_mult_for(d)
    print(f"=== {label} (stated current_capex=${capex:,.0f}) ===")
    for growth_tag, g in (("fence", None), ("judged", gm)):
        if g is None and growth_tag == "judged":
            continue
        for mult, rate_equiv in ((0.0, 0.0), (1.0, 0.05), (2.0, 0.10)):
            fin2 = dict(fin)
            fin2["current_capex"] = capex * mult
            res = evaluate_current(
                financials_json=fin2, ops_json=d["ops"],
                financials_year1_json=d["fy1"], margin_band=d["band"],
                growth_to_q11=g,
            )
            c = res["checks"]["ni_floor"]
            margin = c["value"] - c["threshold"]
            print(f"  [{growth_tag} rate-equiv {rate_equiv:.2f}] ni_margin={c['value']:.6f} "
                  f"thr={c['threshold']:.3f} margin={margin:+.6f} ni_floor_pass={c['passed']} "
                  f"verdict={res['passed']} dep_q=${capex*mult*0.05:,.2f}")
        # sensitivity + flip point at this growth
        res0 = evaluate_current(financials_json={**fin, "current_capex": 0.0},
                                ops_json=d["ops"], financials_year1_json=d["fy1"],
                                margin_band=d["band"], growth_to_q11=g)
        rev_q11 = res0["q11"]["revenue"]
        c0 = res0["checks"]["ni_floor"]
        margin0 = c0["value"] - c0["threshold"]
        # d(ni_margin)/d(capex$) = -0.05 / rev_q11
        sens = -0.05 / rev_q11
        flip_capex = margin0 / (0.05 / rev_q11) if rev_q11 > 0 else float("inf")
        print(f"  [{growth_tag}] Q11 rev=${rev_q11:,.2f}; ni_margin moves {sens:.3e}/$capex "
              f"(= ${0.05:,.2f}/q dep per $1 capex).")
        print(f"  [{growth_tag}] capex-at-zero ni margin {margin0:+.6f} -> ni_floor flips at "
              f"capex ~= ${flip_capex:,.0f} (stated is ${capex:,.0f}, {capex/flip_capex*100 if flip_capex>0 else 0:.2f}% of flip level)")
    print()
