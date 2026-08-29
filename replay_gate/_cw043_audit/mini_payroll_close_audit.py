"""mini's OWN audit of the payroll close (2026-08-28).

Builds drafts through the PRODUCTION exporter, recalculates in Excel, and reads
the ARTIFACT - never the source - for:
  (d) the stub Total Payroll cell equals the engine's payroll figure that Model
      Inputs / FINMO use, and the stub headcount cells are EMPTY (not 0).
  (e) TAMPER: the live-quarter-scoped payroll tie-out still FAILS when a LIVE
      quarter's summary or detail is broken, and does NOT fail on the stub -
      the scoping removed a false failure, not the check.
  (f) every named person at 1.0 (or a stated part-time fraction), Checks!B2,
      and no phantom supporting roles.

usage: python mini_payroll_close_audit.py <out_dir> <draft_prefix> [more...]
       python mini_payroll_close_audit.py <out_dir> --tamper <draft_prefix>
"""
import json, os, sys, time
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv

ROOT = r"C:\dev\business_plann_app"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(os.path.join(ROOT, ".env"))
from client_statements_output_excel.export_client_workbook import export_workbook_for_row
import client_statements_output_excel.schedule_sheets as ss
print("code under test:", ss.__file__, flush=True)

args = list(sys.argv[1:])
TAMPER = "--tamper" in args
if TAMPER:
    args.remove("--tamper")
OUT = Path(args[0]); OUT.mkdir(parents=True, exist_ok=True)
PREFIXES = args[1:]

TIE_LABEL = "Payroll summary totals equal payroll detail by quarter"


def _conn():
    return mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                                   password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
                                   autocommit=True)


def _row(prefix):
    c = _conn(); cur = c.cursor(dictionary=True)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
    row = cur.fetchone()
    if row is None:
        cur.close(); c.close(); return None, None
    row = dict(row)
    cur.execute("SELECT diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id LIKE %s "
                "ORDER BY id DESC LIMIT 1", (prefix + "%",))
    d = cur.fetchone(); cur.close(); c.close()
    return row, (json.loads(d["diagnostics_json"]) if d else None)


_XL = None


def _excel():
    global _XL
    if _XL is None:
        import win32com.client as win32
        _XL = win32.gencache.EnsureDispatch("Excel.Application")
        _XL.Visible = False; _XL.DisplayAlerts = False
    return _XL


def _open_recalc(path):
    x = _excel(); w = x.Workbooks.Open(str(path))
    for _ in range(20):
        try:
            w.Sheets(1).Name; break
        except Exception:
            time.sleep(1.5)
    x.CalculateFullRebuild()
    return w


def _find_row(ws, label, col=1, limit=400):
    for r in range(1, limit + 1):
        if str(ws.Cells(r, col).Value or "").strip() == label:
            return r
    return None


def _check_status(w):
    """Checks!B2 plus the payroll tie-out row status."""
    ck = w.Sheets("Checks")
    b2 = ck.Cells(2, 2).Value
    tie = None
    for r in range(1, 400):
        for c in (2, 3):
            if str(ck.Cells(r, c).Value or "").strip() == TIE_LABEL:
                for cc in range(1, 15):
                    v = str(ck.Cells(r, cc).Value or "").strip().upper()
                    if v in ("OK", "FAIL"):
                        tie = (r, cc, v)
                return b2, tie
    return b2, tie


def _block_ending_fte(ps, header_row):
    for r in range(header_row + 1, header_row + 15):
        if str(ps.Cells(r, 1).Value or "").strip() == "Ending FTE":
            vals = [ps.Cells(r, c).Value for c in range(4, 24)]
            vals = [round(v, 4) for v in vals if isinstance(v, (int, float))]
            u = sorted(set(vals))
            return u[0] if len(u) == 1 else u
    return None


def _labeled_stub(ws, label, limit=400):
    for r in range(1, limit + 1):
        if str(ws.Cells(r, 1).Value or "").strip() == label:
            return ws.Cells(r, 3).Value
    return None


def audit(prefix):
    row, diag = _row(prefix)
    if row is None:
        print("  %s: NO DRAFT" % prefix, flush=True); return None
    name = row.get("business_name")
    row = dict(row); row["business_name"] = "MINIAUD %s" % prefix
    p = export_workbook_for_row(row, output_dir=OUT, run_diagnostics=diag)
    w = _open_recalc(p)
    ps = w.Sheets("Payroll Schedule")
    b2, tie = _check_status(w)
    tp = _find_row(ps, "Total Payroll")
    tf = _find_row(ps, "Total Ending FTE")
    ta = _find_row(ps, "Total Average FTE")
    stub_pay = ps.Cells(tp, 3).Value if tp else None
    stub_fte = ps.Cells(tf, 3).Value if tf else None
    stub_avg = ps.Cells(ta, 3).Value if ta else None
    mi_pay = _labeled_stub(w.Sheets("Model Inputs"), "Payroll")
    fin_pay = _labeled_stub(w.Sheets("FINMO"), "Payroll")
    named, support = [], []
    last = ps.UsedRange.Rows.Count
    for r in range(1, last + 1):
        cls = str(ps.Cells(r, 2).Value or "").strip().lower()
        if cls == "key_person":
            named.append((str(ps.Cells(r, 1).Value or "").strip(), _block_ending_fte(ps, r)))
        elif cls == "supporting_staff":
            support.append((str(ps.Cells(r, 1).Value or "").strip(), _block_ending_fte(ps, r)))
    print("  %s | %-26.26s | Checks!B2=%s | tie=%s | STUB payroll sheet=%s MI=%s FINMO=%s | stub FTE=%r avgFTE=%r"
          % (prefix, str(name), b2, (tie[2] if tie else "?"), stub_pay, mi_pay, fin_pay, stub_fte, stub_avg), flush=True)
    for person, ef in named:
        flag = "" if (isinstance(ef, float) and abs(ef - 1.0) < 1e-6) else "   <-- NOT 1.0"
        print("        named      : %-34.34s endingFTE=%s%s" % (person, ef, flag), flush=True)
    for title, ef in support:
        lo = ef if isinstance(ef, float) else (min(ef) if ef else None)
        flag = "   <-- PHANTOM (<0.25)" if isinstance(lo, float) and 0 < lo < 0.25 else ""
        print("        supporting : %-34.34s endingFTE=%s%s" % (title, ef, flag), flush=True)
    return p, w


def tamper(prefix):
    row, diag = _row(prefix)
    row = dict(row); row["business_name"] = "MINITAMP %s" % prefix
    p = export_workbook_for_row(row, output_dir=OUT, run_diagnostics=diag)
    w = _open_recalc(p); x = _excel()
    ps = w.Sheets("Payroll Schedule")
    tp = _find_row(ps, "Total Payroll")
    b2, tie = _check_status(w)
    print("BASELINE                              -> Checks!B2=%s  tie-out=%s   (Total Payroll row %s)"
          % (b2, (tie[2] if tie else "?"), tp), flush=True)

    # CONTROL: break the STUB column. The scoping says the tie-out must NOT
    # fail here - that is exactly the false failure it removed.
    orig_stub = ps.Cells(tp, 3).Value
    ps.Cells(tp, 3).Value = float(orig_stub or 0) + 99999.0
    x.CalculateFullRebuild()
    b2s, ties = _check_status(w)
    print("TAMPER STUB     C%-3d += 99999        -> Checks!B2=%s  tie-out=%s   (expect tie-out OK - scoped off the stub)"
          % (tp, b2s, (ties[2] if ties else "?")), flush=True)
    ps.Cells(tp, 3).Value = orig_stub
    x.CalculateFullRebuild()

    # THE TAMPER THAT MATTERS: break a LIVE quarter's SUMMARY.
    for qcol, qlab in ((4, "Q1"), (8, "Q5"), (23, "Q20")):
        orig = ps.Cells(tp, qcol).Formula
        ps.Cells(tp, qcol).Value = 424242.0
        x.CalculateFullRebuild()
        b2t, tiet = _check_status(w)
        print("TAMPER SUMMARY  %-3s col %-2d := 424242 -> Checks!B2=%s  tie-out=%s   (expect FAIL)"
              % (qlab, qcol, b2t, (tiet[2] if tiet else "?")), flush=True)
        ps.Cells(tp, qcol).Formula = orig
        x.CalculateFullRebuild()

    # ...and break the DETAIL side on a live quarter (hidden bridge, payroll col M).
    dfirst = None
    last = ps.UsedRange.Rows.Count
    for r in range(1, last + 1):
        if isinstance(ps.Cells(r, 1).Value, (int, float)) and str(ps.Cells(r, 2).Value or "").strip():
            dfirst = r; break
    if dfirst:
        for rr in range(dfirst, min(dfirst + 600, last + 1)):
            if ps.Cells(rr, 1).Value == 5:
                origd = ps.Cells(rr, 13).Formula
                ps.Cells(rr, 13).Value = 777777.0
                x.CalculateFullRebuild()
                b2d, tied = _check_status(w)
                print("TAMPER DETAIL   M%-4d := 777777      -> Checks!B2=%s  tie-out=%s   (expect FAIL)"
                      % (rr, b2d, (tied[2] if tied else "?")), flush=True)
                ps.Cells(rr, 13).Formula = origd
                x.CalculateFullRebuild()
                break
    b2f, tief = _check_status(w)
    print("FINAL RESTORED                        -> Checks!B2=%s  tie-out=%s" % (b2f, (tief[2] if tief else "?")), flush=True)
    w.Close(False)


if TAMPER:
    tamper(PREFIXES[0])
    try:
        _excel().Quit()
    except Exception:
        pass
    sys.exit(0)

print("=== BUILD + RECALC + READ THE ARTIFACT ===", flush=True)
built = []
for pfx in PREFIXES:
    try:
        r = audit(pfx)
        if r:
            built.append(r)
    except Exception as e:
        import traceback
        print("  %s: ERROR %s: %s" % (pfx, type(e).__name__, e), flush=True)
        traceback.print_exc()
for _p, _w in built:
    try:
        _w.Close(False)
    except Exception:
        pass
try:
    _excel().Quit()
except Exception:
    pass
