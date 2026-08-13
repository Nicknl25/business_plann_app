"""ABLATION EXP-1: GROWTH_FENCE_Q11 (1.07^10) - what job does it do,
what breaks without it. In-memory only; app code untouched.

Three evaluations per real draft, real margin-band judgment attached:
  A) fence basis  (growth_to_q11 = 1.967, production gate-entry tier)
  B) judged basis (the engine's own judged multiple, walk tier)
  C) ABLATED flat (growth_to_q11 = 1.0 - "remove the fence")
"""
import json
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()
import mysql.connector

import client_intake_and_finmo.intake_coherence.controller as ctl
from client_intake_and_finmo.intake_coherence.evaluator import (
    GROWTH_FENCE_Q11, growth_multiple_from_judged,
)

conn = mysql.connector.connect(
    host="localhost", user="root", password="Lovers251979!",
    database="biz_plan_revert", autocommit=True)
cur = conn.cursor()

DRAFTS = {
    "Peachtree security (healthy)": "f62e846077ef40ca96f37edafb97a6fe",
    "Meridian Motorcars (fleet flip case)": "adf1090bf87d446c80ee3b81d10ce273",
    "Doomed Glaze (known-fail case)": "cc8b7081adec47b4b79f33a6231beb26",
}


def summarize(ev):
    if ev is None:
        return "no-basis"
    checks = ev.get("checks") or {}
    fails = [k for k, v in checks.items() if isinstance(v, dict) and v.get("passed") is False]
    return f"passed={ev.get('passed')} failing={fails or 'none'}"


for name, did in DRAFTS.items():
    cur.execute(
        "SELECT operating_model_json, financials_json, financials_year1_json, "
        "model_input_json FROM intake_consult_drafts WHERE draft_id = %s", (did,))
    row = cur.fetchone()
    if not row:
        continue
    ops, fin, fy1, mi = [json.loads(x) if x else {} for x in row]
    si = (mi.get("solver_input") or {})
    band = si.get("margin_band_judgment")
    jg = si.get("judged_growth")
    gm = growth_multiple_from_judged(jg, ops_json=ops)
    print(f"\n== {name}  (judged_multiple={round(gm, 3) if gm else None}, fence={round(GROWTH_FENCE_Q11, 3)})")
    for label, mult in (("A fence ", None), ("B judged", gm), ("C FLAT  ", 1.0)):
        if label.startswith("B") and not gm:
            print("  B judged: no growth stamp on draft")
            continue
        ev = ctl.evaluate_current(
            financials_json=fin, ops_json=ops, financials_year1_json=fy1,
            margin_band=band, growth_to_q11=mult)
        print(f"  {label}: {summarize(ev)}")
