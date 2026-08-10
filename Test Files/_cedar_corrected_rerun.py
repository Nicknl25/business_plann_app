# -*- coding: utf-8 -*-
"""CW-024 follow-through (Nick): re-run the EXACT Cedar Ridge shape
(draft 7deeafb2) with the payroll corrected through the new door and
report what verdict the room now reaches - does the 'your plan fails'
wall disappear once the phantom is gone, and if not, which HONEST wall
replaces it?

Chain: real draft rows from SQL -> people door (total_team_payroll
225,000) -> THE RECALC -> evaluator basis -> the payroll wall math the
gate itself uses (payroll share vs class ceiling) + fence eval.
Read-only against the DB; nothing is written back.
"""
import copy
import io
import json
import os
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv("C:/dev/business_plann_app/.env")
import mysql.connector

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST", "localhost"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB", "biz_plan_revert"),
    autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, business_name, financials_json, people_json, "
    "operating_model_json FROM intake_consult_drafts "
    "WHERE draft_id LIKE '7deeafb2%'"
)
row = cur.fetchone()
cur.close()
conn.close()
if not row:
    print("draft 7deeafb2 not found")
    sys.exit(1)


def _j(v):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if v else {}
    except Exception:
        return {}


fin0 = _j(row["financials_json"])
people0 = _j(row["people_json"])
ops0 = _j(row["operating_model_json"])
print(f"draft: {row['draft_id']}  business: {row['business_name']}")
print(f"stored current_payroll: {fin0.get('current_payroll')}")
print(f"stored current_revenue: {fin0.get('current_revenue')}")
print(f"people rows: {[(p.get('role_title'), p.get('annual_wage')) for p in (people0.get('people') or [])]}")
print(f"rest_of_team: {people0.get('rest_of_team_payroll_year1')}")

from api_handlers.intake_consult import (  # noqa: E402
    _apply_scoped_patch, _sync_financials_consult_persistence_state,
)
from client_intake_and_finmo.intake_coherence.evaluator import (  # noqa: E402
    basis_from_intake,
)
from client_intake_and_finmo.intake_coherence import controller as _ctl  # noqa: E402

# The client's correction, through the door, then the RECALC.
_b, _o, _m, people1, fin1, _f = _apply_scoped_patch(
    {"people.total_team_payroll": 225000.0},
    business_facts={}, ops_json=copy.deepcopy(ops0), market_json={},
    people_json=copy.deepcopy(people0), financials_json=copy.deepcopy(fin0),
    fulfillment_json={},
)
fin2, _y1 = _sync_financials_consult_persistence_state(
    financials_json=fin1, financials_year1_json={},
    people_json=people1, ops_json=copy.deepcopy(ops0),
)
pay = float(fin2.get("current_payroll") or 0.0)
rev = float(fin2.get("current_revenue") or 0.0)
print(f"\nAFTER door+RECALC: current_payroll={pay:,.0f}  revenue={rev:,.0f}")
print(f"payroll share of revenue: {pay / rev:.1%}" if rev else "no revenue")

# The payroll wall the gate applies (class ceiling from the stored
# judged class, mirroring the gate's own arithmetic).
state = (fin2.get("_coherence") or {}) if isinstance(fin2.get("_coherence"), dict) else {}
walls = state.get("walls") or {}
print(f"\nstored coherence status: {state.get('status')}")
print(f"stored walls: {json.dumps(walls)[:400]}")

basis = basis_from_intake(financials_json=fin2, ops_json=ops0,
                          financials_year1_json={})
if basis is not None:
    print(f"\nevaluator basis: q1_rev/qtr={basis.q1_revenue_quarterly:,.0f} "
          f"payroll/qtr={basis.payroll_quarterly:,.0f} "
          f"cogs_pct={basis.cogs_pct:.1%}")
    # Fence-tier structural eval with the stored band thresholds if any.
    mb = state.get("margin_band") or {}
    print(f"stored margin band stamp: {json.dumps(mb)[:300]}")
