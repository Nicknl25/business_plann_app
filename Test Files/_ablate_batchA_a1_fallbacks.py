"""A1: evaluator fallback thresholds — real judged band vs margin_band=None.
Runs evaluate_current on each real draft at fence growth and at the judged
multiple, both with the real band and with band=None (pure fallbacks).
Also ablates the fallback constants themselves to prove which are live."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ablate_batchA_common import load_drafts, growth_mult_for

import client_intake_and_finmo.intake_coherence.evaluator as EV
from client_intake_and_finmo.intake_coherence.controller import evaluate_current


def show(tag, res):
    if res is None:
        print(f"  {tag}: eval=None (no revenue basis)")
        return
    th = res["thresholds"]
    checks = res["checks"]
    line = " ".join(
        f"{k}={'P' if c['passed'] else 'F'}({c['value']:.4f}/{c['threshold']:.4f})"
        for k, c in checks.items()
    )
    print(f"  {tag}: passed={res['passed']} gap=${res['gap_quarterly']:,.2f} judged={th['judged']}")
    print(f"    thresholds: gm={th['gm_floor']} burden={th['burden_max']} band_low={th['band_low']} ni={th['ni_floor']}")
    print(f"    checks: {line}")


drafts = load_drafts()
for label, d in drafts.items():
    print(f"=== {label} ===")
    gm = growth_mult_for(d)
    for growth_tag, g in (("fence", None), (f"judged x{gm:.4f}" if gm else "judged N/A", gm)):
        if growth_tag.endswith("N/A"):
            continue
        for band_tag, band in (("real band", d["band"]), ("band=None", None)):
            res = evaluate_current(
                financials_json=d["fin"], ops_json=d["ops"],
                financials_year1_json=d["fy1"], margin_band=band,
                growth_to_q11=g,
            )
            show(f"[growth={growth_tag} | {band_tag}]", res)
    print()

# --- fallback-constant ablation: which fallback is actually consulted on
# each draft's REAL band?  Set each fallback to a poison value and see if
# the thresholds/verdict move (they can only move if the fallback is read).
print("=== fallback-constant reachability on REAL bands (poison test) ===")
POISON = {"FALLBACK_GM_FLOOR": 0.99, "FALLBACK_BURDEN_MAX": 0.0,
          "FALLBACK_NI_FLOOR": 0.99, "FALLBACK_BAND_LOW": 0.99}
for label, d in drafts.items():
    base = evaluate_current(financials_json=d["fin"], ops_json=d["ops"],
                            financials_year1_json=d["fy1"], margin_band=d["band"])
    for name, poison in POISON.items():
        saved = getattr(EV, name)
        setattr(EV, name, poison)
        try:
            res = evaluate_current(financials_json=d["fin"], ops_json=d["ops"],
                                   financials_year1_json=d["fy1"], margin_band=d["band"])
        finally:
            setattr(EV, name, saved)
        moved = (res["thresholds"] != base["thresholds"])
        flip = (res["passed"] != base["passed"])
        print(f"  {label}: poison {name} -> thresholds_moved={moved} verdict_flip={flip}"
              + (f" ({base['passed']}->{res['passed']})" if flip else ""))
