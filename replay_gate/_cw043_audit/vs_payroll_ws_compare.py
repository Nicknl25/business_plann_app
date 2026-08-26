"""TEXT-AWARE compare, old (7738cfb: horizontal, per-role wage source) vs new (per-quarter wage source row).
Bridge rows vs old bridge rows INCLUDING strings; every other sheet by address including strings (only the
OLD/NEW name tag excused); Checks by label. Also: bridge column N vs the engine's per-row wage_source label."""
import glob,os,sys,json,openpyxl
sys.path.insert(0,r'C:\dev\business_plann_app')
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
from client_statements_output_excel.schedule_sheets import _wage_source_plain
SC=r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\1b5df2b9-512c-4fc5-bfdd-b10c0712b978\scratchpad'
def isnum(v): return isinstance(v,(int,float)) and not isinstance(v,bool)
def same(a,b):
    if isnum(a) and isnum(b): return abs(float(a)-float(b))<=max(1e-6,abs(float(a))*1e-9)
    return (a or '')==(b or '') if (a is None or b is None or isinstance(a,str) or isinstance(b,str)) else a==b
def tag(v): return isinstance(v,str) and ('OLD ' in v or 'NEW ' in v)
import mysql.connector
from dotenv import load_dotenv; load_dotenv(r'C:\dev\business_plann_app\.env')
c=mysql.connector.connect(host=os.getenv('MYSQL_HOST'),user=os.getenv('MYSQL_USER'),password=os.getenv('MYSQL_PASSWORD'),database=os.getenv('MYSQL_DB'),autocommit=True); cur=c.cursor(dictionary=True)
for d in sys.argv[1:]:
    A=glob.glob(os.path.join(SC,'ws_old','*'+d+'*.xlsx'))[0]; B=glob.glob(os.path.join(SC,'ws_new','*'+d+'*.xlsx'))[0]
    wa,wb=openpyxl.load_workbook(A,data_only=True),openpyxl.load_workbook(B,data_only=True)
    bad={}; tot=0
    for name in wa.sheetnames:
        if name=='Payroll Schedule':
            pa,pb=wa[name],wb[name]
            oh=[r for r in range(1,pa.max_row+1) if pa.cell(r,1).value=='Quarter'][-1]+1; nh=[r for r in range(1,pb.max_row+1) if pb.cell(r,1).value=='Quarter'][-1]+1
            k=0; m=0; mtext=0
            while isnum(pa.cell(oh+k,1).value):
                for col in range(1,15):
                    x,y=pa.cell(oh+k,col).value,pb.cell(nh+k,col).value
                    if not same(x,y):
                        if col==14: mtext+=1
                        else: m+=1
                k+=1
            if m: bad['bridge numeric/other cols']=m
            if mtext: bad['bridge col N (wage source) - EXPECTED where per-quarter label differs']=mtext
            n=sum(1 for r in range(6,23) for cc in range(1,29) if not same(pa.cell(r,cc).value,pb.cell(r,cc).value))
            if n: bad['Payroll summary']=n
            # bridge N vs engine per-row label
            cur.execute("SELECT payroll_headcount FROM intake_consult_drafts WHERE draft_id LIKE %s",(d+'%',))
            rows=[x for x in json.loads(cur.fetchone()['payroll_headcount'])['rows'] if isinstance(x,dict)]
            eng_bad=sum(1 for i,it in enumerate(rows) if (pb.cell(nh+i,14).value or '')!=_wage_source_plain(it.get('wage_source') or it.get('wage_source_code')))
            old_bad=sum(1 for i,it in enumerate(rows) if (pa.cell(oh+i,14).value or '')!=_wage_source_plain(it.get('wage_source') or it.get('wage_source_code')))
            bad['bridge N != engine label: OLD']=old_bad; bad['bridge N != engine label: NEW']=eng_bad
            tot+=k*14; continue
        if name=='Checks':
            la={}; lb={}
            for ws_,dst in ((wa[name],la),(wb[name],lb)):
                for r in range(1,ws_.max_row+1):
                    kk=ws_.cell(r,2).value
                    if isinstance(kk,str) and kk.strip(): dst.setdefault(kk.strip(),[]).append([ws_.cell(r,cc).value for cc in range(1,ws_.max_column+1) if cc!=2])
            n=0
            for kk,rows_ in la.items():
                for i,ra in enumerate(rows_):
                    rb=(lb.get(kk) or [])[i] if i<len(lb.get(kk) or []) else None
                    if rb is None: n+=1; continue
                    n+=sum(1 for x,y in zip(ra,rb) if not same(x,y) and not (tag(x) or tag(y)))
            if n: bad['Checks(by label)']=n
            continue
        ca={(cc.row,cc.column):cc.value for r in wa[name].iter_rows() for cc in r if cc.value is not None}
        cb={(cc.row,cc.column):cc.value for r in wb[name].iter_rows() for cc in r if cc.value is not None}
        dd=[kk for kk in set(ca)|set(cb) if not same(ca.get(kk),cb.get(kk)) and not (tag(ca.get(kk)) or tag(cb.get(kk)))]
        tot+=len(ca)
        if dd: bad[name]=len(dd)
    print(f"  {d}: {tot} cells (text-aware) -> {bad or 'NONE'} | Checks!B2 old={wa['Checks'].cell(2,2).value} new={wb['Checks'].cell(2,2).value}")
cur.close(); c.close()
