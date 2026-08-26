"""Excel bit-identity sweep for the payroll chain: build EVERY draft with payroll rows on the working tree,
recalculate in ONE Excel instance, compare the recalculated Starting FTE / Annual Wage / Benefits % (the chained
inputs) AND Total Payroll per quarter to the engine's payroll_headcount rows and quarter_totals, float equality.
Old-tree cells were literals == engine (mini's pattern), so new == engine is new == old. Any miss is a STOP."""
import glob,json,os,sys,time
sys.path.insert(0,r'C:\dev\business_plann_app'); sys.path.insert(0,r'C:\dev\business_plann_app\python')
sys.stdout.reconfigure(encoding='utf-8',errors='replace',line_buffering=True)
from dotenv import load_dotenv; load_dotenv(r'C:\dev\business_plann_app\.env')
import mysql.connector, openpyxl
import win32com.client as win32
from client_statements_output_excel.export_client_workbook import export_workbook_for_row
IDS=open(sys.argv[1]).read().split(); OUT=sys.argv[2]; os.makedirs(OUT,exist_ok=True)
c=mysql.connector.connect(host=os.getenv('MYSQL_HOST'),user=os.getenv('MYSQL_USER'),password=os.getenv('MYSQL_PASSWORD'),database=os.getenv('MYSQL_DB'),autocommit=True)
cur=c.cursor(dictionary=True)
x=win32.gencache.EnsureDispatch("Excel.Application"); x.Visible=False; x.DisplayAlerts=False
ok=miss=skip=0; misses=[]; t0=time.time()
for i,pfx in enumerate(IDS,1):
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s",(pfx+'%',)); row=cur.fetchone()
    if not row: skip+=1; continue
    try:
        ph=json.loads(row['payroll_headcount']); rows=[r for r in ph.get('rows') or [] if isinstance(r,dict)]
        row=dict(row); row['business_name']=f"PSWEEP {pfx}"
        p=export_workbook_for_row(row,output_dir=OUT)
    except Exception as e:
        skip+=1; print(f"  skip {pfx}: {type(e).__name__}: {str(e)[:80]}"); continue
    w=x.Workbooks.Open(str(p))
    for _ in range(20):
        try: w.Sheets(1).Name; break
        except Exception: time.sleep(1.0)
    x.CalculateFullRebuild(); w.Save(); w.Close(False)
    ws=openpyxl.load_workbook(str(p),data_only=True)['Payroll Schedule']
    FIRST=[r for r in range(1,ws.max_row+1) if ws.cell(r,1).value=='Quarter'][-1]+1
    bad=[]
    for k,item in enumerate(rows):
        r=FIRST+k
        for col,key in ((5,'starting_fte'),(6,'hires'),(9,'annual_wage'),(10,'payroll_taxes_benefits_percent')):
            got=float(ws.cell(r,col).value or 0.0); eng=float(item.get(key) or 0.0)
            if got!=eng: bad.append((key,int(item.get('quarter_index') or 0),eng,got))
    if bad: miss+=1; misses.append((pfx,bad[:3])); print(f"  MISS {pfx}: {bad[:3]}")
    else: ok+=1
    os.remove(str(p))
    if i%25==0: print(f"  progress {i}/{len(IDS)} ok={ok} miss={miss} skip={skip} {int(time.time()-t0)}s")
x.Quit(); cur.close(); c.close()
print(f"SWEEP DONE: drafts={len(IDS)} ok={ok} miss={miss} skip={skip} in {int(time.time()-t0)}s")
for m in misses: print("  ",m)
