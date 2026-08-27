"""mini claim (b), second half: does any DELIVERED workbook in Client Plans carry an
unbalanced quarter? Reads the CACHED values Excel left in each delivered file."""
import sys, glob, os, openpyxl
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FILES = sorted(glob.glob(r"C:\dev\Cilient Plans\*.xlsx"))
C0, C1 = 3, 23
TOL = 1.0
unbal = []; nocache = []; err = []; n = 0
for k, p in enumerate(FILES):
    if k % 100 == 0: print(f"  ...{k}/{len(FILES)}", flush=True)
    try:
        wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
        if "FINMO" not in wb.sheetnames: wb.close(); continue
        ws = wb["FINMO"]
        rows = {}
        for r in ws.iter_rows(min_row=1, max_row=120, max_col=C1, values_only=True):
            lab = r[0]
            if isinstance(lab, str) and lab.strip() and lab.strip() not in rows:
                rows[lab.strip()] = r
        A = rows.get("Total Assets"); L = rows.get("Total Liabilities & Equity")
        S = rows.get("Short Term Debt"); D = rows.get("Long Term Debt")
        b2 = None
        if "Checks" in wb.sheetnames:
            for r in wb["Checks"].iter_rows(min_row=2, max_row=2, max_col=2, values_only=True):
                b2 = r[1]
        wb.close()
        if not (A and L): continue
        n += 1
        a = A[C0-1:C1-1]; l = L[C0-1:C1-1]
        if all(x is None for x in a): nocache.append(os.path.basename(p)); continue
        bad = [(i, a[i]-l[i]) for i in range(len(a))
               if isinstance(a[i], (int, float)) and isinstance(l[i], (int, float)) and abs(a[i]-l[i]) > TOL]
        if bad:
            s = S[C0-1:C1-1] if S else []; d = D[C0-1:C1-1] if D else []
            unbal.append((os.path.basename(p), [(i, round(x)) for i, x in bad][:6], len(bad), b2,
                          [(s[i] if s else None, d[i] if d else None) for i, _ in bad][:3]))
    except Exception as e:
        err.append((os.path.basename(p), repr(e)[:90]))
print(f"\ndelivered workbooks with a FINMO sheet: {n}  (no cached values: {len(nocache)}, unreadable: {len(err)})")
print(f"DELIVERED WORKBOOKS WITH AN UNBALANCED QUARTER (|TA - TL&E| > ${TOL:.0f}): {len(unbal)}")
for u in unbal:
    print(f"  {u[0]}\n     out at {u[2]} quarter(s) (0-based col idx, 0=stub); first: {u[1]}   Checks!B2={u[3]!r}   (STD,LTD) there={u[4]}")
for e in err[:10]: print("  ERR", e)
print("  nocache sample:", nocache[:5])
