"""Probe: what range does the payroll tie-out actually sum, and does breaking a
row INSIDE that range move it? (mini, 2026-08-28, audit of the live-quarter scoping)"""
import json, os, sys, time
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv

ROOT = r"C:\dev\business_plann_app"
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "python"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(os.path.join(ROOT, ".env"))
from client_statements_output_excel.export_client_workbook import export_workbook_for_row

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
PREFIX = sys.argv[2]
TIE_LABEL = "Payroll summary totals equal payroll detail by quarter"

c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                            password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (PREFIX + "%",))
row = dict(cur.fetchone())
cur.execute("SELECT diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id LIKE %s ORDER BY id DESC LIMIT 1", (PREFIX + "%",))
d = cur.fetchone(); cur.close(); c.close()
diag = json.loads(d["diagnostics_json"]) if d else None
row["business_name"] = "MINIPROBE %s" % PREFIX
p = export_workbook_for_row(row, output_dir=OUT, run_diagnostics=diag)

import win32com.client as win32
x = win32.gencache.EnsureDispatch("Excel.Application"); x.Visible = False; x.DisplayAlerts = False
w = x.Workbooks.Open(str(p))
for _ in range(20):
    try:
        w.Sheets(1).Name; break
    except Exception:
        time.sleep(1.5)
x.CalculateFullRebuild()
ps = w.Sheets("Payroll Schedule"); ck = w.Sheets("Checks")

tie_row = None
for r in range(1, 400):
    for cc in (2, 3):
        if str(ck.Cells(r, cc).Value or "").strip() == TIE_LABEL:
            tie_row = r; break
    if tie_row: break
print("tie-out Checks row:", tie_row)
for cc in range(1, 15):
    v = ck.Cells(tie_row, cc).Value
    f = ck.Cells(tie_row, cc).Formula
    if v is not None or (f and f != ""):
        print("   col %2d  value=%r" % (cc, v), " formula=", str(f)[:150])

# Which payroll-sheet rows does that SUMIFS actually range over?
tie_formula = None
for cc in range(1, 15):
    f = str(ck.Cells(tie_row, cc).Formula or "")
    if "SUMIFS" in f:
        tie_formula = f; break
if tie_formula:
    import re
    m = re.search(r"\$G\$(\d+):\$G\$(\d+)", tie_formula)
    print("\nSUMIFS detail range rows:", m.groups() if m else "not parsed")
    print("quarter keys present in formula:", sorted(set(int(z) for z in re.findall(r"\$A\$\d+:\$A\$\d+,(\d+)\)", tie_formula))))
    first, last = (int(m.group(1)), int(m.group(2))) if m else (None, None)
else:
    first = last = None

print("\nrows around the detail range:")
for r in range(max(1, (first or 2) - 3), min((first or 2) + 4, ps.UsedRange.Rows.Count + 1)):
    print("   r%-4d A=%r B=%r M=%r" % (r, ps.Cells(r, 1).Value, ps.Cells(r, 2).Value, ps.Cells(r, 13).Value))
print("   ...")
for r in range(max(1, (last or 2) - 3), min((last or 2) + 4, ps.UsedRange.Rows.Count + 1)):
    print("   r%-4d A=%r B=%r M=%r" % (r, ps.Cells(r, 1).Value, ps.Cells(r, 2).Value, ps.Cells(r, 13).Value))

# find a row INSIDE [first,last] whose A == 5 and break its M
target = None
for r in range(first, last + 1):
    if ps.Cells(r, 1).Value == 5 and isinstance(ps.Cells(r, 13).Value, (int, float)):
        target = r; break
print("\nrow inside the detail range with A==5:", target, " M=", ps.Cells(target, 13).Value if target else None)
if target:
    orig = ps.Cells(target, 13).Formula
    ps.Cells(target, 13).Value = 777777.0
    x.CalculateFullRebuild()
    st = None
    for cc in range(1, 15):
        v = str(ck.Cells(tie_row, cc).Value or "").strip().upper()
        if v in ("OK", "FAIL"): st = v
    print("AFTER breaking DETAIL M%d (inside range, Q5): Checks!B2=%s  tie-out=%s   (expect FAIL)"
          % (target, ck.Cells(2, 2).Value, st))
    ps.Cells(target, 13).Formula = orig
    x.CalculateFullRebuild()
    st2 = None
    for cc in range(1, 15):
        v = str(ck.Cells(tie_row, cc).Value or "").strip().upper()
        if v in ("OK", "FAIL"): st2 = v
    print("RESTORED: Checks!B2=%s  tie-out=%s" % (ck.Cells(2, 2).Value, st2))
w.Close(False); x.Quit()
