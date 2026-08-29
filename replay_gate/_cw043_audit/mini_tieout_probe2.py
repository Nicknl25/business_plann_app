"""Is the payroll tie-out comparing the summary against the detail, or against
itself? Reads the SUMMARY formulas and the CHECK formula and puts them side by
side, then breaks the detail and reports WHICH checks move. (mini, 2026-08-28)"""
import json, os, re, sys, time
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

c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                            password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (PREFIX + "%",))
row = dict(cur.fetchone())
cur.execute("SELECT diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id LIKE %s ORDER BY id DESC LIMIT 1", (PREFIX + "%",))
d = cur.fetchone(); cur.close(); c.close()
row["business_name"] = "MINIPROBE2 %s" % PREFIX
p = export_workbook_for_row(row, output_dir=OUT, run_diagnostics=(json.loads(d["diagnostics_json"]) if d else None))

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


def frow(label, col=1, limit=400):
    for r in range(1, limit + 1):
        if str(ps.Cells(r, col).Value or "").strip() == label:
            return r
    return None


print("=== SUMMARY formulas (Q5 = col H) vs the CHECK's own SUMIFS ===")
for lab in ("Total Ending FTE", "Total Average FTE", "Total Payroll"):
    r = frow(lab)
    print("  %-18s row %-4s STUB(C)=%r" % (lab, r, ps.Cells(r, 3).Formula))
    print("  %-18s          Q5(H) = %s" % ("", str(ps.Cells(r, 8).Formula)[:120]))

tie_row = None
for r in range(1, 400):
    if str(ck.Cells(r, 2).Value or "").strip() == "Payroll summary totals equal payroll detail by quarter":
        tie_row = r; break
f = str(ck.Cells(tie_row, 5).Formula or "")
q5 = [t for t in re.findall(r"ABS\([^)]*\)[^,]*", f) if ",5)" in t]
print("\n=== the CHECK's Q5 terms ===")
for t in re.findall(r"ABS\('Payroll Schedule'!\w+\d+-SUMIFS\([^)]*\)[^)]*\)", f):
    if ",5)" in t:
        print("  ", t)

# snapshot every check's status, break the detail, and see which ones move
def statuses():
    out = {}
    for r in range(1, 400):
        lab = str(ck.Cells(r, 2).Value or "").strip()
        if not lab:
            continue
        for cc in range(1, 15):
            v = str(ck.Cells(r, cc).Value or "").strip().upper()
            if v in ("OK", "FAIL"):
                out[lab] = v
    return out


before = statuses()
target = None
for r in range(114, 254):
    if ps.Cells(r, 1).Value == 5 and isinstance(ps.Cells(r, 13).Value, (int, float)):
        target = r; break
orig = ps.Cells(target, 13).Formula
print("\n=== breaking DETAIL M%d (Q5 payroll, inside the SUMIFS range) ===" % target)
print("   original formula:", orig)
ps.Cells(target, 13).Value = 777777.0
x.CalculateFullRebuild()
after = statuses()
print("   Checks!B2:", ck.Cells(2, 2).Value)
moved = [(k, before.get(k), v) for k, v in after.items() if before.get(k) != v]
print("   checks that MOVED:")
for k, b, a in moved:
    print("      %-62.62s %s -> %s" % (k, b, a))
if not moved:
    print("      (none)")
print("   payroll tie-out stayed:", after.get("Payroll summary totals equal payroll detail by quarter"))
ps.Cells(target, 13).Formula = orig
x.CalculateFullRebuild()
print("   restored, Checks!B2 =", ck.Cells(2, 2).Value)
w.Close(False); x.Quit()
