"""KEYSTONE FINAL VERIFICATION - the rebuilt plans vs the corrected
intake, at the ENGINE-READ level (CW-023 permanent standard). The two
real drafts that created the converged-on-one-built-on-another class:

  F&F 50658fff: corrected in room to price $60 / cap 40 -> anchor
    $87,360; owner pay $3,300/mo one-door -> payroll 39,600; stated
    $5,900 cogs dollars-durable.
  Sparrow 4aa25e24: wall caught at 72% in room; team-cost exit ->
    payroll 139,100; converged 69.8%.
"""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)


def load(prefix):
    cur.execute(
        "SELECT draft_id, business_name, planning_run_status, financials_json, "
        "model_input_json FROM intake_consult_drafts WHERE draft_id LIKE %s",
        (prefix + "%",))
    r = cur.fetchone()
    return (r["business_name"], r["planning_run_status"],
            json.loads(r["financials_json"] or "{}"),
            json.loads(r["model_input_json"] or "{}"))


def wb_row(mi, section, label):
    for row in (mi.get("sections") or {}).get(section) or []:
        if isinstance(row, dict) and str(row.get("label")) == label:
            return [float(v) for v in (row.get("values") or [])]
    return None


def wb_q1_revenue(mi):
    """Revenue section rows are the DRIVERS (capacity, price,
    utilization) - Q1 revenue is their product."""
    rows = [[float(v) for v in (r.get("values") or [])]
            for r in ((mi.get("sections") or {}).get("revenue") or [])
            if isinstance(r, dict)]
    if len(rows) < 3 or not all(r for r in rows[:3]):
        return None
    return rows[0][0] * rows[1][0] * rows[2][0]


# ---------------- F&F ----------------
name, run, fin, mi = load("50658fff")
print(f"== {name} (run={run}) ==")
check("F1 run completed", run == "completed")
pay = wb_row(mi, "expenses", "Payroll")
cogs_pct = wb_row(mi, "expenses", "Cost of Goods Sold")
q1_rev = wb_q1_revenue(mi)
trio = fin.get("payroll_total_year1")
print(f"   intake: payroll={trio} cogs={fin.get('current_cogs')} "
      f"({fin.get('cogs_basis')!r}) anchor={fin.get('current_revenue')}")
print(f"   workbook: payroll Q1x4={pay[0]*4 if pay else None} "
      f"cogs_pct Q1={cogs_pct[0] if cogs_pct else None} rev Q1={q1_rev}")
check("F2 workbook payroll Q1 x4 == intake trio (39,600 - her $3,300/mo)",
      pay is not None and abs(pay[0] * 4 - 39600.0) < 1.0)
check("F3 workbook Q1 revenue (cap x price x util) == corrected anchor/4 "
      "(21,840 at $60/40wk; not the corrupted 112/30 shape)",
      q1_rev is not None and abs(q1_rev - 87360.0 / 4.0) < 25.0)
_q1_cogs = (cogs_pct[0] * q1_rev) if (cogs_pct and q1_rev) else None
check("F4 workbook Q1 COGS == her stated dollars "
      f"({_q1_cogs:.0f} vs {5900.0/4:.0f}; NOT the restated {14676.48/4:.0f})"
      if _q1_cogs is not None else "F4 cogs row",
      _q1_cogs is not None and abs(_q1_cogs - 5900.0 / 4.0) < 25.0)

# ---------------- Sparrow ----------------
name, run, fin, mi = load("4aa25e24")
print(f"== {name} (run={run}) ==")
check("S1 run completed (was 3x deterministic wall-kill at 0.72)",
      run == "completed")
pay = wb_row(mi, "expenses", "Payroll")
q1_rev = wb_q1_revenue(mi)
print(f"   intake: payroll={fin.get('payroll_total_year1')} "
      f"anchor={fin.get('current_revenue')}")
print(f"   workbook: payroll Q1x4={pay[0]*4 if pay else None} rev Q1={q1_rev}")
check("S2 workbook payroll Q1 x4 == corrected trio (139,100; not the "
      "pre-exit 143,400)", pay is not None and abs(pay[0] * 4 - 139100.0) < 1.0)
check("S3 workbook payroll share inside the high wall "
      f"({(pay[0]*4)/199294.0:.4f} <= 0.70)" if pay else "S3 payroll row",
      pay is not None and (pay[0] * 4) / 199294.0 <= 0.70 + 1e-6)
check("S4 workbook Q1 revenue (cap x price x util) == stated anchor/4 "
      "(49,824)", q1_rev is not None and abs(q1_rev - 199294.12 / 4.0) < 25.0)

cur.close()
conn.close()
print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
