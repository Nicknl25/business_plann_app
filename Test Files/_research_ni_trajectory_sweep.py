"""RESEARCH (Nick 2026-08-15, Part 2): sweep recent completed real runs for the
Nine Fathom pattern - net income BELOW the stub for most/all forecast quarters
and/or a declining NI margin. Reads the FINAL checkpoint finmo_json.quarter_rows
(row 0 = stub, rows 1..20 = forecast). Read-only."""
import os, json, sys, io, mysql.connector
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv(r"c:\dev\business_plann_app\.env")
c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"),user=os.getenv("MYSQL_USER"),password=os.getenv("MYSQL_PASSWORD"),database=os.getenv("MYSQL_DB"),port=int(os.getenv("MYSQL_PORT") or 3306),autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("""SELECT pr.planning_run_id, pr.draft_id, pr.completed_at, d.business_name
               FROM planning_runs pr JOIN intake_consult_drafts d ON d.draft_id=pr.draft_id
               WHERE pr.run_status='completed' AND pr.completed_at >= '2026-08-01'
               ORDER BY pr.completed_at DESC LIMIT 60""")
runs=cur.fetchall()
print(f"completed runs since 08-01: {len(runs)}")
print(f"{'business':38} {'run':10} {'stubNI':>9} {'stub%':>6} {'Q1NI':>9} {'Q1%':>6} {'Q20NI':>9} {'Q20%':>6} {'belowStub':>9} {'Q1->Q20':>8} {'revQoQ%':>7} {'dep0':>6} {'dep1':>7} {'int1':>6}")
flag=0; seen=set()
for r in runs:
    if r["draft_id"] in seen: continue
    seen.add(r["draft_id"])
    cur.execute("SELECT finmo_json FROM planning_run_checkpoints WHERE planning_run_id=%s AND finmo_json IS NOT NULL ORDER BY created_at DESC LIMIT 1",(r["planning_run_id"],))
    ck=cur.fetchone()
    if not ck: continue
    try: fm=json.loads(ck["finmo_json"]); q=fm.get("quarter_rows") or []
    except Exception: continue
    if len(q)<21: continue
    def f(row,k):
        v=row.get(k); 
        try: return float(v)
        except Exception: return 0.0
    stub,q1,q20=q[0],q[1],q[20]
    sni,s_rev=f(stub,"net_income"),f(stub,"revenue"); n1,r1=f(q1,"net_income"),f(q1,"revenue"); n20,r20=f(q20,"net_income"),f(q20,"revenue")
    below=sum(1 for i in range(1,21) if f(q[i],"net_income")<sni)
    m=lambda n,r:(n/r*100 if r else 0)
    qoq=((r20/r1)**(1/19)-1)*100 if r1>0 and r20>0 else 0
    dep0,dep1=f(stub,"depreciation"),f(q1,"depreciation"); int1=f(q1,"interest_expense") or f(q1,"interest")
    trend="UP" if n20>n1 else "DOWN"
    mark="  <-- NF PATTERN" if (below>=15 and m(n20,r20)<m(sni,s_rev)) else ""
    if mark: flag+=1
    print(f"{(r['business_name'] or '?')[:38]:38} {r['planning_run_id'][:8]:10} {sni:9.0f} {m(sni,s_rev):6.1f} {n1:9.0f} {m(n1,r1):6.1f} {n20:9.0f} {m(n20,r20):6.1f} {below:9d} {trend:>8} {qoq:7.2f} {dep0:6.0f} {dep1:7.0f} {int1:6.0f}{mark}")
print(f"\nNF-PATTERN (NI below stub >=15/20 quarters AND Q20 margin < stub margin): {flag} of {len(seen)} distinct drafts")
