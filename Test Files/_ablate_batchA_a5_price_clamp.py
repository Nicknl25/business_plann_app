"""A5: section.py:655-666 custom-price LOWER clamp (client may not lower
price below current).  Trace with Glaze's real line (donut $2.00, pmax 1.20
bounds): wanted=$1.50 below current.  Clamp expression copied verbatim,
then the real _apply_custom_prices call, then the no-clamp counterfactual
pushed through the next-turn re-eval (evaluate_current) to show downstream."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ablate_batchA_common import load_drafts
import client_intake_and_finmo.intake_coherence.controller as _ctl
from client_intake_and_finmo.intake_coherence.section import _apply_custom_prices
from client_intake_and_finmo.intake_coherence.controller import evaluate_current

d = load_drafts()["Glaze"]
fin, ops = d["fin"], d["ops"]
split = _ctl.ops_line_split(ops, fin)
line = split[0]
pmax = 1.20
wanted = 1.50

# --- verbatim clamp expression (section.py:664-666) with real numbers ---
lo, hi = line["unit_price"], round(line["unit_price"] * pmax, 2)
new_price = min(max(wanted, lo), hi)
clamped = abs(new_price - wanted) > 0.005
print(f"line={line['product']!r} current=${line['unit_price']:.2f} pmax={pmax} "
      f"wanted=${wanted:.2f} -> clamp range [lo=${lo:.2f}, hi=${hi:.2f}] "
      f"new_price=${new_price:.2f} clamped={clamped}")

# --- the real handler on the real draft ---
state = {"bounds": {"existing_lines": [
    {"lob": line["lob"], "product": line["product"], "price_multiplier_max": pmax}]}}
next_ops, next_fin, was_clamped = _apply_custom_prices(
    ops, fin, {"donut": {"unit_price": wanted}}, state)
def _price_of(o):
    for l in o.get("lob_models") or []:
        for p in l.get("products") or []:
            return p.get("unit_price")
print(f"_apply_custom_prices: applied unit_price={_price_of(next_ops)} "
      f"current_revenue {fin.get('current_revenue')} -> {next_fin.get('current_revenue')} "
      f"clamped_flag={was_clamped}")
res = evaluate_current(financials_json=next_fin, ops_json=next_ops,
                       financials_year1_json=d["fy1"], margin_band=d["band"])
print(f"re-eval after clamped apply: gap=${res['gap_quarterly']:,.2f} passed={res['passed']}")

# --- counterfactual: clamp removed (lower bound dropped, hi kept) ---
ratio = wanted / line["unit_price"]
nc_ops = dict(next_ops)
# apply wanted price directly through the same spec applier
from client_intake_and_finmo.intake_coherence.section import _apply_price_spec
nc_ops = _apply_price_spec(ops, [{"lob": line["lob"], "product": line["product"], "unit_price": wanted}])
nc_fin = dict(fin)
nc_fin["current_revenue"] = round(float(fin["current_revenue"]) * ratio, 2)
res2 = evaluate_current(financials_json=nc_fin, ops_json=nc_ops,
                        financials_year1_json=d["fy1"], margin_band=d["band"])
print(f"NO-CLAMP counterfactual: unit_price={_price_of(nc_ops)} current_revenue={nc_fin['current_revenue']}")
print(f"re-eval after no-clamp apply: gap=${res2['gap_quarterly']:,.2f} passed={res2['passed']} "
      f"(gap delta vs clamped: ${res2['gap_quarterly']-res['gap_quarterly']:+,.2f}/q)")
