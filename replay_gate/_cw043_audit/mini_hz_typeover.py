"""mini (b): a client's type-over in a ROLE BLOCK carries right with bumps/hires on top and reaches the summary,
the FINMO Payroll row and the Checks THROUGH the hidden bridge. Excel-evaluated on a NEW-tree build of an untouched draft.
usage: <new xlsx> <scratch_dir>"""
import sys, os, shutil, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import win32com.client as win32
SRC, SC = sys.argv[1], sys.argv[2]
PSC = 3; PERIOD = ["Starting FTE", "Hires", "Ending FTE", "Average FTE", "Annual Wage", "Benefits %", "Wage Cost", "Taxes & Benefits", "Total Payroll"]
x = win32.gencache.EnsureDispatch("Excel.Application"); x.Visible = False; x.DisplayAlerts = False


def open_copy(tag):
    p = os.path.join(SC, f"typeover_{tag}.xlsx"); shutil.copy(SRC, p)
    w = x.Workbooks.Open(p)
    for _ in range(20):
        try:
            w.Sheets(1).Name; break
        except Exception:
            time.sleep(1.0)
    return w


def colA(ws, n=600):
    return [ws.Cells(r, 1).Value for r in range(1, n + 1)]


def blocks_of(ws):
    a = colA(ws); out = []; r = 1
    while r < len(a):
        if a[r - 1] == "OEWS title" and a[r] == "Wage source":
            b = {"header": r - 1, "oews": r, "source": r + 1}
            for n, lab in enumerate(PERIOD):
                assert a[r + 1 + n] == lab, (r, lab, a[r + 1 + n]); b[lab] = r + 2 + n
            out.append(b); r += 2 + len(PERIOD)
        else:
            r += 1
    return out


def rowvals(ws, r):
    return [float(ws.Cells(r, PSC + q).Value or 0) for q in range(1, 21)]


def label_row(ws, label, first=True, n=600):
    rows = [i + 1 for i, v in enumerate(colA(ws, n)) if isinstance(v, str) and v.strip() == label]
    return rows[0] if first else rows[-1]


def snapshot(w, b):
    ps = w.Sheets("Payroll Schedule"); fin = w.Sheets("FINMO"); ck = w.Sheets("Checks")
    s = {lab: rowvals(ps, b[lab]) for lab in PERIOD}
    s["summary Total Payroll"] = rowvals(ps, label_row(ps, "Total Payroll"))
    s["summary Total Ending FTE"] = rowvals(ps, label_row(ps, "Total Ending FTE"))
    frow = next(r for r in range(1, 200) if isinstance(fin.Cells(r, 1).Value, str) and fin.Cells(r, 1).Value.strip() == "Payroll")
    s["FINMO Payroll"] = rowvals(fin, frow)
    s["Checks!B2"] = ck.Cells(2, 2).Value
    s["payroll checks"] = [(ck.Cells(r, 2).Value, ck.Cells(r, 9).Value) for r in range(7, 230) if isinstance(ck.Cells(r, 2).Value, str) and "payroll" in ck.Cells(r, 2).Value.lower() and ck.Cells(r, 3).Value == "Payroll Schedule"]
    s["non-OK"] = [ck.Cells(r, 2).Value for r in range(7, 230) if ck.Cells(r, 9).Value not in (None, "OK", "")]
    return s


def close(v, e, tol=1e-6):
    return abs(v - e) <= tol * max(1.0, abs(e))


def demo(tag, label, q, delta_fn, expect):
    w = open_copy(tag); ps = w.Sheets("Payroll Schedule"); blocks = blocks_of(ps); b = blocks[1]
    before = snapshot(w, b); col = PSC + q
    old = float(ps.Cells(b[label], col).Value or 0); new = delta_fn(old)
    ps.Cells(b[label], col).Value = new
    x.CalculateFullRebuild(); after = snapshot(w, b)
    print(f"\n== {tag}: block[1] {ps.Cells(b['header'],1).Value!r} {label} q{q}: {old} -> {new}")
    ok = True
    for qq in range(1, 21):
        exp = expect(qq, before, q, new - old)
        for key, e in exp.items():
            got = after[key][qq - 1] - before[key][qq - 1]
            if not close(got, e):
                ok = False; print(f"   MISS {key} q{qq}: delta {got} expected {e}")
    dp = [round(after["Total Payroll"][i] - before["Total Payroll"][i], 4) for i in range(20)]
    ds = [round(after["summary Total Payroll"][i] - before["summary Total Payroll"][i], 4) for i in range(20)]
    df = [round(after["FINMO Payroll"][i] - before["FINMO Payroll"][i], 4) for i in range(20)]
    print(f"   block Total Payroll delta by q: {dp}")
    print(f"   summary Total Payroll delta == block delta: {dp == ds}; FINMO Payroll delta == block delta: {dp == df} {df if dp != df else ''}")
    print(f"   Checks!B2 before/after: {before['Checks!B2']}/{after['Checks!B2']}; non-OK rows unchanged: {before['non-OK'] == after['non-OK']}; payroll checks after: {sorted(set(s for _, s in after['payroll checks']))} (n={len(after['payroll checks'])})")
    print(f"   every expected delta held (Starting/Ending/Average/Annual Wage/Total Payroll/summary/FINMO, all 20 quarters): {ok}")
    w.Close(False)
    return ok


def exp_fte(qq, before, q, d):
    # a Starting FTE type-over at q: Starting +d at q (typed) and every later quarter (ROUND(prev Ending)), Ending +d, Average +d
    if qq < q:
        return {"Starting FTE": 0, "Ending FTE": 0, "Average FTE": 0, "Total Payroll": 0, "summary Total Payroll": 0, "FINMO Payroll": 0}
    wage = before["Annual Wage"][qq - 1]; ben = before["Benefits %"][qq - 1]
    dpay = d * wage / 4 * (1 + ben)
    return {"Starting FTE": d, "Ending FTE": d, "Average FTE": d, "Total Payroll": dpay, "summary Total Payroll": dpay, "FINMO Payroll": dpay, "summary Total Ending FTE": d}


def exp_wage(qq, before, q, d):
    if qq < q:
        return {"Annual Wage": 0, "Total Payroll": 0}
    avg = before["Average FTE"][qq - 1]; ben = before["Benefits %"][qq - 1]
    dpay = avg * d / 4 * (1 + ben)
    return {"Annual Wage": d, "Starting FTE": 0, "Total Payroll": dpay, "summary Total Payroll": dpay, "FINMO Payroll": dpay}


def exp_hires(qq, before, q, d):
    if qq < q:
        return {"Starting FTE": 0, "Ending FTE": 0}
    davg = d / 2 if qq == q else d
    wage = before["Annual Wage"][qq - 1]; ben = before["Benefits %"][qq - 1]
    dpay = davg * wage / 4 * (1 + ben)
    return {"Starting FTE": 0 if qq == q else d, "Ending FTE": d, "Average FTE": davg, "Total Payroll": dpay, "summary Total Payroll": dpay, "FINMO Payroll": dpay}


r1 = demo("fte", "Starting FTE", 3, lambda v: v + 1.0, exp_fte)
r2 = demo("wage", "Annual Wage", 5, lambda v: v + 1000.0, exp_wage)
r3 = demo("hires", "Hires", 2, lambda v: v + 2.0, exp_hires)
x.Quit()
print("\nTYPE-OVER VERDICT:", "ALL HELD" if r1 and r2 and r3 else "MISSES ABOVE")
