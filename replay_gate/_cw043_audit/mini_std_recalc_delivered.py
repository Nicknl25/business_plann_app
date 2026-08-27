"""mini claim (b): recalculate COPIES of uncached delivered workbooks in the STD-clip
class and read the balance at EVERY quarter plus Checks!B2. Originals are never touched."""
import sys, os, shutil, time, openpyxl
import win32com.client as win32
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = r"C:\dev\Cilient Plans"
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
NAMES = sys.argv[2:]
x = win32.gencache.EnsureDispatch("Excel.Application"); x.Visible = False; x.DisplayAlerts = False
for nm in NAMES:
    src = os.path.join(SRC, nm)
    dst = os.path.join(OUT, "copy_" + nm)
    shutil.copy2(src, dst)
    w = x.Workbooks.Open(dst)
    for _ in range(20):
        try: w.Sheets(1).Name; break
        except Exception: time.sleep(1.0)
    x.CalculateFullRebuild(); w.Save(); w.Close(False)
    wb = openpyxl.load_workbook(dst, data_only=True, read_only=True)
    rows = {}
    for r in wb["FINMO"].iter_rows(min_row=1, max_row=60, max_col=23, values_only=True):
        if isinstance(r[0], str) and r[0].strip() and r[0].strip() not in rows: rows[r[0].strip()] = r
    b2 = None
    for r in wb["Checks"].iter_rows(min_row=2, max_row=2, max_col=2, values_only=True): b2 = r[1]
    A = rows["Total Assets"][2:22]; L = rows["Total Liabilities & Equity"][2:22]
    S = rows["Short Term Debt"][2:22]; D = rows["Long Term Debt"][2:22]
    wb.close()
    bad = [(i, round(A[i]-L[i])) for i in range(20)
           if isinstance(A[i],(int,float)) and isinstance(L[i],(int,float)) and abs(A[i]-L[i])>1.0]
    print(f"{nm}\n   Checks!B2={b2!r}  unbalanced quarters(col idx, 0=stub)={bad}")
    if bad:
        for i, d in bad[:6]: print(f"      idx {i}: TA-TL&E={d:,}  STD={S[i]:,.0f} LTD={D[i]:,.0f}")
    sys.stdout.flush()
x.Quit()
