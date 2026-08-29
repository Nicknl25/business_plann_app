"""Read the BUILT workbook's Payroll Schedule: every named person's Ending FTE
across Q1..Q20, every supporting title's, the stub cells, and Checks!B2.

Pulls the used range in ONE COM call (cell-by-cell reads get rejected by a busy
Excel), so it is fast enough to sweep neighbours. (mini, 2026-08-28)

usage: python mini_named_fte_read.py <out_dir> <prefix> [prefix...]
"""
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
PREFIXES = sys.argv[2:]
TIE = "Payroll summary totals equal payroll detail by quarter"


def _grid(ws):
    """whole used range as a 0-indexed list of rows (1 COM call)"""
    v = ws.UsedRange.Value
    if v is None:
        return []
    return [list(r) for r in v]


def _txt(v):
    return str(v).strip() if v is not None else ""


def run(prefix, xl):
    c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                                password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), autocommit=True)
    cur = c.cursor(dictionary=True)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
    row = cur.fetchone()
    if row is None:
        cur.close(); c.close(); print("  %s: NO DRAFT" % prefix, flush=True); return
    row = dict(row); name = row.get("business_name")
    cur.execute("SELECT diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id LIKE %s ORDER BY id DESC LIMIT 1", (prefix + "%",))
    d = cur.fetchone(); cur.close(); c.close()
    row["business_name"] = "MINIAUD %s" % prefix
    p = export_workbook_for_row(row, output_dir=OUT, run_diagnostics=(json.loads(d["diagnostics_json"]) if d else None))
    w = xl.Workbooks.Open(str(p))
    for _ in range(20):
        try:
            w.Sheets(1).Name; break
        except Exception:
            time.sleep(1.5)
    xl.CalculateFullRebuild()
    try:
        ps = _grid(w.Sheets("Payroll Schedule"))
        ck = _grid(w.Sheets("Checks"))
        mi = _grid(w.Sheets("Model Inputs"))
        fn = _grid(w.Sheets("FINMO"))
        b2 = ck[1][1] if len(ck) > 1 and len(ck[1]) > 1 else None
        tie = None
        for r in ck:
            if len(r) > 2 and _txt(r[1]) == TIE:
                tie = next((_txt(x).upper() for x in r if _txt(x).upper() in ("OK", "FAIL")), None)
                break

        def summary_stub(label):
            for r in ps:
                if _txt(r[0]) == label:
                    return r[2]
            return "<<no row>>"

        def stub_of(grid, label):
            for r in grid:
                if _txt(r[0]) == label:
                    return r[2]
            return None

        stub_pay, stub_fte, stub_avg = summary_stub("Total Payroll"), summary_stub("Total Ending FTE"), summary_stub("Total Average FTE")
        mi_pay, fn_pay = stub_of(mi, "Payroll"), stub_of(fn, "Payroll")
        agree = (isinstance(stub_pay, float) and isinstance(mi_pay, float)
                 and abs(stub_pay - mi_pay) < 0.01 and isinstance(fn_pay, float) and abs(stub_pay - fn_pay) < 0.01)
        print("  %-8s | %-26.26s | B2=%-4s tie=%-4s | STUB pay sheet=%s MI=%s FINMO=%s %s | stub FTE=%r avg=%r"
              % (prefix, str(name), b2, tie, stub_pay, mi_pay, fn_pay,
                 "AGREE" if agree else "*** MISMATCH ***", stub_fte, stub_avg), flush=True)

        # role blocks: a header row is (col A = title/person, col B = class label)
        named, support = [], []
        for i, r in enumerate(ps):
            cls = _txt(r[1]).lower()
            if cls not in ("named person", "supporting staff", "key_person", "supporting_staff"):
                continue
            title = _txt(r[0])
            if not title:
                continue
            ef = None
            for j in range(i + 1, min(i + 16, len(ps))):
                if _txt(ps[j][0]) == "Ending FTE":
                    vals = [round(v, 4) for v in ps[j][3:23] if isinstance(v, (int, float))]
                    u = sorted(set(vals))
                    ef = u[0] if len(u) == 1 else u
                    break
            if ef is None:
                continue
            (named if cls in ("named person", "key_person") else support).append((title, ef))
        for t, ef in named:
            ok = isinstance(ef, float) and abs(ef - 1.0) < 1e-6
            print("        NAMED      %-36.36s ending FTE = %-22s %s" % (t, ef, "" if ok else "<<< NOT 1.0"), flush=True)
        for t, ef in support:
            lo = ef if isinstance(ef, float) else (min(ef) if ef else None)
            print("        supporting %-36.36s ending FTE = %-22s %s"
                  % (t, ef, "<<< PHANTOM (<0.25)" if isinstance(lo, float) and 0 < lo < 0.25 else ""), flush=True)
        if not support:
            print("        (no supporting block - the business is its named people)", flush=True)
    finally:
        w.Close(False)


import win32com.client as win32
xl = win32.gencache.EnsureDispatch("Excel.Application")
xl.Visible = False; xl.DisplayAlerts = False
print("=== BUILD + RECALC + READ THE ARTIFACT ===", flush=True)
for pfx in PREFIXES:
    for attempt in range(3):
        try:
            run(pfx, xl); break
        except Exception as e:
            if attempt == 2:
                import traceback
                print("  %s: ERROR %s: %s" % (pfx, type(e).__name__, e), flush=True)
                traceback.print_exc()
            else:
                time.sleep(4)
try:
    xl.Quit()
except Exception:
    pass
