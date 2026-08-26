"""Old (vertical) vs new (horizontal + bridge): every sheet by address except Payroll Schedule, where the old
detail rows (27..) are compared value-for-value to the new BRIDGE rows in the same engine order, the summary and
assumption rows by address; Checks by label. Values only (formulas differ by design)."""
import glob,os,sys,openpyxl
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
SC=r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\1b5df2b9-512c-4fc5-bfdd-b10c0712b978\scratchpad'
def isnum(v): return isinstance(v,(int,float)) and not isinstance(v,bool)
def same(a,b):
    if isnum(a) and isnum(b): return abs(float(a)-float(b))<=max(1e-6,abs(float(a))*1e-9)
    return a==b
def bylabel(ws,lc): 
    out={}
    for r in range(1,ws.max_row+1):
        k=ws.cell(r,lc).value
        if isinstance(k,str) and k.strip(): out.setdefault(k.strip(),[]).append([ws.cell(r,c).value for c in range(1,ws.max_column+1) if c!=lc])
    return out
for d in sys.argv[1:]:
    A=glob.glob(os.path.join(SC,'hz_old','*'+d+'*.xlsx'))[0]; B=glob.glob(os.path.join(SC,'hz_new','*'+d+'*.xlsx'))[0]
    wa,wb=openpyxl.load_workbook(A,data_only=True),openpyxl.load_workbook(B,data_only=True)
    bad={}; tot=0
    for name in wa.sheetnames:
        if name=='Payroll Schedule':
            pa,pb=wa[name],wb[name]
            # summary + assumptions by address rows 6..22
            n=sum(1 for r in range(6,23) for c in range(1,29) if not same(pa.cell(r,c).value,pb.cell(r,c).value) and not (isinstance(pa.cell(r,c).value,str) and isinstance(pb.cell(r,c).value,str)))
            if n: bad['Payroll summary']=n
            # old detail rows vs new bridge rows
            oh=[r for r in range(1,pa.max_row+1) if pa.cell(r,1).value=='Quarter'][0]+1
            nh=[r for r in range(1,pb.max_row+1) if pb.cell(r,1).value=='Quarter'][0]+1
            k=0; m=0
            while isnum(pa.cell(oh+k,1).value):
                for c in range(1,15):
                    x,y=pa.cell(oh+k,c).value,pb.cell(nh+k,c).value
                    if not same(x,y) and not (isinstance(x,str) and isinstance(y,str)): m+=1
                k+=1
            rows_new=sum(1 for r in range(nh,pb.max_row+1) if isnum(pb.cell(r,1).value))
            if m or rows_new!=k: bad['Payroll detail/bridge']=(m,k,rows_new)
            tot+=k*14
            continue
        if name=='Checks':
            la,lb=bylabel(wa[name],2),bylabel(wb[name],2); n=0
            for key,rows in la.items():
                for i,ra in enumerate(rows):
                    rb=(lb.get(key) or [None]*(i+1))[i] if i<len(lb.get(key) or []) else None
                    if rb is None: n+=1; continue
                    n+=sum(1 for x,y in zip(ra,rb) if not same(x,y) and not (isinstance(x,str) and isinstance(y,str)))
            if n: bad['Checks(by label)']=n
            continue
        ca={(c.row,c.column):c.value for r in wa[name].iter_rows() for c in r if c.value is not None}
        cb={(c.row,c.column):c.value for r in wb[name].iter_rows() for c in r if c.value is not None}
        dd=[k for k in set(ca)|set(cb) if not same(ca.get(k),cb.get(k)) and not (isinstance(ca.get(k),str) and isinstance(cb.get(k),str))]
        tot+=len(ca)
        if dd: bad[name]=len(dd)
    print(f"  {d}: {tot} cells -> value diffs: {bad or 'NONE'} | Checks!B2 old={wa['Checks'].cell(2,2).value} new={wb['Checks'].cell(2,2).value}")
