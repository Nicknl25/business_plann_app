"""Probe: what judgments/bounds do the three real drafts actually carry."""
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ablate_batchA_common import load_drafts, growth_mult_for

drafts = load_drafts()
for label, d in drafts.items():
    if d is None:
        print(f"=== {label}: NOT FOUND ===")
        continue
    band = d["band"] or {}
    print(f"=== {label} ({d['business_name']}) ===")
    print("  band keys:", sorted(band.keys()) if band else "ABSENT")
    print("  band values: gm_floor=%r burden_max=%r ni_floor=%r q11=%r" % (
        band.get("gross_margin_floor_q11"), band.get("fixed_cost_burden_max_q11"),
        band.get("ni_margin_floor_q11"), band.get("q11")))
    print("  judged_growth:", json.dumps(d["judged_growth"]))
    try:
        print("  growth_mult (engine proposer):", growth_mult_for(d))
    except Exception as e:
        print("  growth_mult ERROR:", e)
    st = d["coherence_state"]
    print("  _coherence keys:", sorted(st.keys()))
    b = st.get("bounds") or {}
    print("  bounds keys:", sorted(b.keys()))
    print("  new_line_candidates:", json.dumps(b.get("new_line_candidates")))
    print("  existing_lines:", json.dumps(b.get("existing_lines")))
    print("  fin current_capex=%r total_debt=%r current_revenue=%r" % (
        d["fin"].get("current_capex"), d["fin"].get("total_debt_outstanding"),
        d["fin"].get("current_revenue")))
    print()
