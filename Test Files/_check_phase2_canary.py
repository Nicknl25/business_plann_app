"""Verify the Recalc-Phase-2 Sunny_V3 canary (draft d3d5aa35): run
complete, engine-read fields coherent, workbook-level P&L sane, and the
coherence state carries no stale phase-2 artifacts. Read-only."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
DRAFT = sys.argv[1] if len(sys.argv) > 1 else "d3d5aa35"

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, financials_json, people_json, "
    "model_input_json, planning_run_json FROM intake_consult_drafts "
    "WHERE draft_id LIKE %s ORDER BY updated_at DESC LIMIT 1",
    (DRAFT + "%",))
r = cur.fetchone()
if not r:
    print(f"NO DRAFT matching {DRAFT}")
    sys.exit(1)
print("draft:", r["draft_id"])
fin = json.loads(r["financials_json"] or "{}")
mi = json.loads(r["model_input_json"] or "{}")
pr = json.loads(r["planning_run_json"] or "{}")

print("run status:", pr.get("status"))

# Engine-read payroll fields all agree (the Recalc invariant).
trio = {k: fin.get(k) for k in
        ("baseline_payroll_year1", "current_payroll", "payroll_total_year1")}
print("payroll trio:", trio)
vals = {v for v in trio.values() if v is not None}
print("payroll trio coherent:", len(vals) <= 1)
print("payroll_adjustment (must be 0/absent):", fin.get("payroll_adjustment"))

# Phase-2 state shape: digest stamped; _lever_writes entries (if any)
# are {from,to} dicts; no stale roadmap latch on a converged draft.
st = fin.get("_coherence") or {}
print("coherence status:", st.get("status"))
print("digest stamped:", bool(st.get("digest_hash")))
lw = st.get("_lever_writes") or {}
print("lever_writes entries:", {k: type(v).__name__ for k, v in lw.items()})

# Workbook-level: landed payroll row vs the intake trio.
rows = (mi.get("sections") or {}).get("expenses") or []
pay_vals = next((row.get("values") for row in rows
                 if isinstance(row, dict) and row.get("label") == "Payroll"), None)
if pay_vals:
    print("workbook payroll Q1x4:", float(pay_vals[0]) * 4,
          " (year-1 sum:", sum(float(v) for v in pay_vals[:4]), ")")
rev_rows = (mi.get("sections") or {}).get("revenue") or []
print("workbook revenue rows:", len(rev_rows))

cur.close()
conn.close()
