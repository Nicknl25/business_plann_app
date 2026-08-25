"""compare two recalculated workbooks: values by address everywhere except Debt Schedule, which is compared by ROW LABEL (bridge) + mapped table columns."""
import sys, openpyxl
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
A, B = sys.argv[1], sys.argv[2]
wa, wb = openpyxl.load_workbook(A, data_only=True), openpyxl.load_workbook(B, data_only=True)
def isnum(v): return isinstance(v,(int,float)) and not isinstance(v,bool)
def same(a,b):
    if isnum(a) and isnum(b): return abs(float(a)-float(b)) <= max(1e-6, abs(float(a))*1e-9)
    return a == b
tot=0; ncells=0
for name in wa.sheetnames:
    if name == "Debt Schedule": continue
    ca = {(c.row,c.column):c.value for r in wa[name].iter_rows() for c in r if c.value is not None}
    cb = {(c.row,c.column):c.value for r in wb[name].iter_rows() for c in r if c.value is not None}
    d = [k for k in set(ca)|set(cb) if not same(ca.get(k),cb.get(k)) and not (isinstance(ca.get(k),str) and isinstance(cb.get(k),str))]
    ncells += len(ca); tot += len(d)
    if d: print(f"  {name}: {len(d)} value diffs e.g. {[(k, ca.get(k), cb.get(k)) for k in sorted(d)[:3]]}")
OLD = dict(d_open=2,d_new=3,d_rate=4,d_pay=5,d_int=6,d_prin=7,d_close=8,l_open=9,l_add=10,l_rate=11,l_term=12,l_pay=13,l_int=14,l_prin=15,l_close=16,t_pay=17,t_int=18,t_close=19)
NEW = dict(d_open=2,d_new=3,d_rate=4,d_pay=10,d_int=9,d_prin=8,d_close=11,l_open=12,l_add=13,l_rate=14,l_term=15,l_pay=20,l_int=19,l_prin=18,l_close=21,t_pay=22,t_int=23,t_close=24)
da, db = wa["Debt Schedule"], wb["Debt Schedule"]
bad=[(k,r,da.cell(r,OLD[k]).value,db.cell(r,NEW[k]).value) for k in OLD for r in range(7,28) if not same(da.cell(r,OLD[k]).value or 0, db.cell(r,NEW[k]).value or 0)]
def bridge(ws):
    return {ws.cell(r,1).value.strip():[ws.cell(r,c).value for c in range(3,24)] for r in range(28, ws.max_row+1) if isinstance(ws.cell(r,1).value,str) and ws.cell(r,1).value.strip()}
ba, bb = bridge(da), bridge(db)
bbad = sum(1 for k in ba for x,y in zip(ba[k], bb.get(k,[None]*21)) if not same(x or 0, y or 0))
print(f"  off-Debt cells compared={ncells} diffs={tot} | Debt table mapped diffs={len(bad)} {bad[:3]} | bridge labels {len(ba)}/{len(bb)} diffs={bbad}")
print("  new-code debt Term/Sched/Extra Q1..Q3:", [[db.cell(r,c).value for c in (5,6,7)] for r in (8,9,10)])
