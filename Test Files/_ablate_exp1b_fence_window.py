"""EXP-1b: the fence's load-bearing window, measured on a real business.

Take Peachtree's REAL intake shape and scale payroll (the dominant fixed
cost) by k. For each k, evaluate at the fence (1.967), the judged
multiple (1.348), and FLAT (1.0). The k-ranges where the verdicts
diverge ARE the fence's job, quantified: businesses in that window
gate-pass only because the evaluation runs at the authorable ceiling.
"""
import copy
import json
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()
import mysql.connector

import client_intake_and_finmo.intake_coherence.controller as ctl

conn = mysql.connector.connect(
    host="localhost", user="root", password="Lovers251979!",
    database="biz_plan_revert", autocommit=True)
cur = conn.cursor()
cur.execute(
    "SELECT operating_model_json, financials_json, financials_year1_json, "
    "model_input_json FROM intake_consult_drafts WHERE draft_id = "
    "'f62e846077ef40ca96f37edafb97a6fe'")
ops, fin0, fy1, mi = [json.loads(x) if x else {} for x in cur.fetchone()]
band = (mi.get("solver_input") or {}).get("margin_band_judgment")

print("payroll_x | fence(1.967) judged(1.348) flat(1.0)")
flips = {}
for k in [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.2, 2.5]:
    fin = copy.deepcopy(fin0)
    for f in ("baseline_payroll_year1", "payroll_total_year1", "current_payroll"):
        if fin.get(f) is not None:
            fin[f] = float(fin[f]) * k
    row = []
    for mult in (None, 1.348, 1.0):
        ev = ctl.evaluate_current(
            financials_json=fin, ops_json=ops, financials_year1_json=fy1,
            margin_band=band, growth_to_q11=mult)
        row.append("PASS" if (ev or {}).get("passed") else "FAIL")
    print(f"  {k:4.1f}    |  {row[0]}        {row[1]}          {row[2]}")
