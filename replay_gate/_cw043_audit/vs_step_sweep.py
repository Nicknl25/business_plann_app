"""Bit-identity sweep: build EVERY stepping draft since 07-13 on the working tree, recalculate in ONE Excel
instance, and compare the recalculated Owner's Capital / Other Equity rows (Cash sheet AND FINMO) to the
engine's authored series with float equality. Old-tree literals == engine exact (mini's (b)), so new == engine
is new == old. Any miss is a STOP."""
import glob,json,os,sys,time,tempfile,shutil
sys.path.insert(0,r'C:\dev\business_plann_app'); sys.path.insert(0,r'C:\dev\business_plann_app\python')
sys.stdout.reconfigure(encoding='utf-8',errors='replace',line_buffering=True)
from dotenv import load_dotenv; load_dotenv(r'C:\dev\business_plann_app\.env')
import mysql.connector, openpyxl
import win32com.client as win32
from client_statements_output_excel.data import draft_data_from_row, values_21
from client_statements_output_excel.export_client_workbook import export_workbook_for_row
IDS=open(sys.argv[1]).read().split(); OUT=sys.argv[2]; os.makedirs(OUT,exist_ok=True)
c=mysql.connector.connect(host=os.getenv('MYSQL_HOST'),user=os.getenv('MYSQL_USER'),password=os.getenv('MYSQL_PASSWORD'),database=os.getenv('MYSQL_DB'),autocommit=True)
cur=c.cursor(dictionary=True)
x=win32.gencache.EnsureDispatch("Excel.Application"); x.Visible=False; x.DisplayAlerts=False
ok=miss=skip=0; misses=[]; t0=time.time()
def frow(ws,lbl):
    for r in range(1,ws.max_row+1):
        if str(ws.cell(r,1).value or '').strip()==lbl: return r
for i,pfx in enumerate(IDS,1):
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s",(pfx+'%',)); row=cur.fetchone()
    if not row: skip+=1; continue
    try:
        d=draft_data_from_row(dict(row)); by={x_.get('label'):values_21(x_.get('values')) for x_ in d.balance_sheet_rows}
        row=dict(row); row['business_name']=f"SWEEP {pfx}"
        p=export_workbook_for_row(row,output_dir=OUT)
    except Exception as e:
        skip+=1; print(f"  skip {pfx}: {type(e).__name__}: {str(e)[:80]}"); continue
    w=x.Workbooks.Open(str(p))
    for _ in range(20):
        try: w.Sheets(1).Name; break
        except Exception: time.sleep(1.0)
    x.CalculateFullRebuild(); w.Save(); w.Close(False)
    v=openpyxl.load_workbook(str(p),data_only=True); cs=v['Cash Equity Schedule']; fi=v['FINMO']
    bad=[]
    for label,r_cash in (("Owner's Capital",7),("Other Equity",8)):
        eng=[float(t or 0.0) for t in by.get(label) or []]
        if len(eng)!=21: continue
        got=[cs.cell(r_cash,3+q).value for q in range(21)]
        rf=frow(fi,label); gotf=[fi.cell(rf,3+q).value for q in range(21)] if rf else [None]*21
        for q in range(21):
            gv=float(got[q] or 0.0); ge=eng[q]
            if gv!=ge: bad.append((label,'cash',q,ge,gv))
            if rf and q>=1 and float(gotf[q] or 0.0)!=ge: bad.append((label,'finmo',q,ge,gotf[q]))
    if bad: miss+=1; misses.append((pfx,bad[:3])); print(f"  MISS {pfx}: {bad[:3]}")
    else: ok+=1
    os.remove(str(p))
    if i%20==0: print(f"  progress {i}/{len(IDS)} ok={ok} miss={miss} skip={skip} {int(time.time()-t0)}s")
x.Quit(); cur.close(); c.close()
print(f"SWEEP DONE: drafts={len(IDS)} ok={ok} miss={miss} skip={skip} in {int(time.time()-t0)}s")
for m in misses: print("  ",m)
