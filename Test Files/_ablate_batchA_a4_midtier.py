"""A4: controller.py:235 mid-tier price = 1.0 + (pmax-1)*0.5, recommended=True.
Product-behavior doc on a real draft (Glaze, the only walking-FAIL draft).
No real authored bounds exist on any of the three drafts, so bounds carry
Glaze's real line with a representative pmax=1.20.  Consumers traced:
  - section._round_question (renders numbered options; the recommended one
    gets ' - this is the one I'd suggest')
  - intent_router.py:1801 (brief agreement 'yes/do that' maps to the option
    marked recommended)
  - the picked option's patch (ops_prices + current_revenue anchor).
Then simulate mid-tier removal by monkeypatching the level tuple loop via a
wrapper that filters options — show the resulting options-list shape."""
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ablate_batchA_common import load_drafts
from client_intake_and_finmo.intake_coherence.evaluator import (
    basis_from_intake, thresholds_from_margin_band, GROWTH_FENCE_Q11,
)
import client_intake_and_finmo.intake_coherence.controller as _ctl
from client_intake_and_finmo.intake_coherence.section import _round_question

d = load_drafts()["Glaze"]
fin, ops, fy1 = d["fin"], d["ops"], d["fy1"]
basis = basis_from_intake(financials_json=fin, ops_json=ops,
                          financials_year1_json=fy1, growth_to_q11=GROWTH_FENCE_Q11)
th = thresholds_from_margin_band(d["band"])
split = _ctl.ops_line_split(ops, fin)
bounds = {"existing_lines": [
    {"lob": s["lob"], "product": s["product"], "price_multiplier_max": 1.20}
    for s in split]}

rnd = _ctl._pricing_round(basis, th, bounds, split)
print("=== pricing round WITH mid tier (production behavior) ===")
for o in rnd["options"]:
    print(f"  id={o['id']} recommended={o['recommended']} prices={o['prices']} "
          f"closes={o['closes_display']} patch.current_revenue={o['patch']['current_revenue']}")
print("\nrendered question:\n " + _round_question(rnd, "$60,758"))

# --- ablation: remove the mid tier (filter to the max level only) ---
print("\n=== pricing round WITHOUT mid tier (ablated) ===")
ablated = dict(rnd)
ablated["options"] = [o for o in rnd["options"] if o["id"] != "pricing_mid"]
ablated["best_closure_quarterly"] = max(o["closes_quarterly"] for o in ablated["options"])
for o in ablated["options"]:
    print(f"  id={o['id']} recommended={o['recommended']} prices={o['prices']} closes={o['closes_display']}")
print("any option recommended:", any(o["recommended"] for o in ablated["options"]))
print("\nrendered question (ablated):\n " + _round_question(ablated, "$60,758"))
