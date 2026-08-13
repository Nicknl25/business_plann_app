"""A3: the 50% gross-margin default for UNAUTHORED new lines.
Entry points: evaluator.favorable_corner_basis:475 (corner math),
controller._new_lines_round:457 (lever closure math), controller:594 +
section:728 (client-facing wording '...at 50% margin').
No monkeypatch possible (inline literal) — compare missing-field (default
path) vs the field explicitly set to 0.5 / 0.25 / 0.0 on Glaze's real basis.
Sweep the candidate cap to find the window where the default ALONE decides
roadmap-vs-walk."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ablate_batchA_common import load_drafts
from client_intake_and_finmo.intake_coherence.evaluator import (
    basis_from_intake, thresholds_from_margin_band, favorable_corner_basis,
    evaluate_structural, GROWTH_FENCE_Q11,
)
import client_intake_and_finmo.intake_coherence.controller as _ctl

d = load_drafts()["Glaze"]
fin, ops, fy1, band = d["fin"], d["ops"], d["fy1"], d["band"]

split = _ctl.ops_line_split(ops, fin)
print("Glaze ops_line_split:", split)

basis = basis_from_intake(financials_json=fin, ops_json=ops,
                          financials_year1_json=fy1, growth_to_q11=GROWTH_FENCE_Q11)
th = thresholds_from_margin_band(band)
print(f"stated eval gap (fence): {evaluate_structural(basis, th)['gap_quarterly']}")

# Real-shaped bounds (shape taken from the code's own reads): existing
# lines with modest believable price/volume headroom, judged cost floors
# at stated levels (no cost cuts — isolates the new-line term), one new
# line candidate.
def bounds_with(nl):
    return {
        "existing_lines": [
            {"lob": s["lob"], "product": s["product"],
             "price_multiplier_max": 1.15, "volume_multiplier_max": 1.25}
            for s in split
        ],
        "team": {}, "facility": {}, "cost_floors": {},
        "new_line_candidates": [nl] if nl else [],
    }

def corner_pass(nl):
    return _ctl.corner_check(basis=basis, thresholds=th, bounds=bounds_with(nl),
                             ops_json=ops, financials_json=fin)

# 1) prove missing == 0.5 default
CAP = 30000.0
nl_missing = {"lob": "Bakery", "product": "wholesale accounts",
              "unit_price": 30.0, "q11_quarterly_revenue_max": CAP}
nl_half = dict(nl_missing, gross_margin_pct=0.5)
a, b = corner_pass(nl_missing), corner_pass(nl_half)
print(f"\nmissing gm field -> corner passed={a['passed']} gap={a['gap_quarterly']} q11_ebitda={a['q11'].get('ebitda')}")
print(f"gm=0.5 explicit  -> corner passed={b['passed']} gap={b['gap_quarterly']} q11_ebitda={b['q11'].get('ebitda')}")
print("identical:", a == b)

# 2) sweep cap x gm: where does roadmap-vs-walk flip?
print("\ncap sweep (corner verdict; walk=PASS, roadmap=FAIL):")
print(f"{'cap/q':>10} | gm missing(0.5) | gm=0.25 | gm=0.0")
flip_rows = []
for cap in (25000, 50000, 75000, 100000, 125000, 150000, 175000, 200000, 250000, 300000):
    verdicts = []
    for gmv in (None, 0.25, 0.0):
        nl = {"lob": "Bakery", "product": "wholesale accounts",
              "unit_price": 30.0, "q11_quarterly_revenue_max": float(cap)}
        if gmv is not None:
            nl["gross_margin_pct"] = gmv
        r = corner_pass(nl)
        verdicts.append("WALK" if r["passed"] else f"ROADMAP(gap ${r['gap_quarterly']:,.0f})")
    print(f"{cap:>10,} | {verdicts[0]:>22} | {verdicts[1]:>22} | {verdicts[2]:>22}")

# 3) lever closure math (_new_lines_round) at each gm, fixed cap
print("\n_new_lines_round closes_quarterly at cap=$100,000/q:")
for gmv in (None, 0.5, 0.25, 0.0):
    nl = {"lob": "Bakery", "product": "wholesale accounts",
          "unit_price": 30.0, "q11_quarterly_revenue_max": 100000.0}
    if gmv is not None:
        nl["gross_margin_pct"] = gmv
    rnd = _ctl._new_lines_round(basis, th, bounds_with(nl))
    o = rnd["options"][0]
    print(f"  gm={'missing' if gmv is None else gmv}: closes_quarterly=${o['closes_quarterly']:,.2f} "
          f"display gm_pct={o['gross_margin_pct']}")
