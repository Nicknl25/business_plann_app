import sys, time, openpyxl, win32com.client as win32
p = sys.argv[1]
x = win32.gencache.EnsureDispatch("Excel.Application"); x.Visible=False; x.DisplayAlerts=False
wb = x.Workbooks.Open(p)
for _ in range(20):
    try: wb.Sheets(1).Name; break
    except Exception: time.sleep(1.5)
x.CalculateFullRebuild(); wb.Save(); wb.Close(False); x.Quit()
w = openpyxl.load_workbook(p, data_only=True)
ck = w["Checks"]; fin = w["FINMO"]
print("Checks!B2 =", repr(ck["B2"].value))
for r in (7,8,9,10):
    print(f"  Checks r{r}: {ck.cell(r,2).value!r} -> {ck.cell(r,9).value!r}")
def row(lbl):
    for r in range(1, fin.max_row+1):
        if str(fin.cell(r,1).value or "").strip()==lbl: return r
    raise SystemExit(f"no row {lbl}")
ta, tle, std, ltd = row("Total Assets"), row("Total Liabilities & Equity"), row("Short Term Debt"), row("Long Term Debt")
print(" quarter | assets-L&E")
for q in range(1,21):
    a = float(fin.cell(ta,3+q).value or 0); l = float(fin.cell(tle,3+q).value or 0)
    if abs(a-l) > 1.0: print(f"   Q{q}: OUT BY {a-l:,.0f}   STD={float(fin.cell(std,3+q).value or 0):,.0f} LTD={float(fin.cell(ltd,3+q).value or 0):,.0f}")
print("done")
