"""mini claim (c): strict by-address compare of one draft built+recalculated on BOTH trees.
Values AND formulas, every sheet. Every diff is classified; anything unclassified is a finding.
Also reads Checks!B2 on each build and the per-quarter balance."""
import sys, openpyxl
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
A, B, TAG = sys.argv[1], sys.argv[2], sys.argv[3]
def isnum(v): return isinstance(v,(int,float)) and not isinstance(v,bool)
def same(a,b):
    if isnum(a) and isnum(b): return abs(float(a)-float(b)) <= max(1e-6, abs(float(a))*1e-9)
    return a == b
def grid(p, data):
    wb = openpyxl.load_workbook(p, data_only=data)
    g = {}
    for n in wb.sheetnames:
        ws = wb[n]
        for r in ws.iter_rows():
            for c in r:
                if c.value is not None: g[(n, c.row, c.column)] = c.value
    return g, wb
va, wba = grid(A, True); vb, wbb = grid(B, True)
fa, _ = grid(A, False); fb, _ = grid(B, False)
def rowlabel(wb, sheet, row):
    ws = wb[sheet]
    return (ws.cell(row,1).value or ws.cell(row,2).value or "")
vdiff = [k for k in set(va)|set(vb) if not same(va.get(k), vb.get(k))]
fdiff = [k for k in set(fa)|set(fb) if not same(fa.get(k), fb.get(k))]
print(f"[{TAG}] cells compared old={len(va)} new={len(vb)}")
print(f"[{TAG}] VALUE diffs={len(vdiff)}   FORMULA diffs={len(fdiff)}")
def classify(ks, src):
    from collections import Counter
    c = Counter()
    for k in ks:
        n, r, col = k
        c[(n, str(rowlabel(wbb, n, r)).strip()[:44])] += 1
    return c
if vdiff:
    for (n, lab), cnt in sorted(classify(vdiff, va).items(), key=lambda x: -x[1]):
        print(f"    VALUE  {n:<22} row='{lab}'  x{cnt}")
if fdiff:
    for (n, lab), cnt in sorted(classify(fdiff, fa).items(), key=lambda x: -x[1]):
        print(f"    FORMULA{n:<22} row='{lab}'  x{cnt}")
for tag, wb in (("old", wba), ("new", wbb)):
    b2 = wb["Checks"].cell(2,2).value if "Checks" in wb.sheetnames else None
    ws = wb["FINMO"]; rows = {}
    for r in range(1, 60):
        v = ws.cell(r,1).value
        if isinstance(v, str) and v.strip() and v.strip() not in rows: rows[v.strip()] = r
    TA, TL = rows.get("Total Assets"), rows.get("Total Liabilities & Equity")
    STD, LTD = rows.get("Short Term Debt"), rows.get("Long Term Debt")
    bad = []
    for c in range(3, 23):
        a, l = ws.cell(TA,c).value, ws.cell(TL,c).value
        if isnum(a) and isnum(l) and abs(a-l) > 1.0: bad.append((c-3, round(a-l)))
    stdv = [ws.cell(STD,c).value for c in range(3,23)]
    print(f"[{TAG}] {tag}: Checks!B2={b2!r}  unbalanced quarters={bad}")
    print(f"[{TAG}] {tag}: STD Q1..Q6 = {[round(x) if isnum(x) else x for x in stdv[1:7]]}")
