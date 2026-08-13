"""Fix 1 diagnostic: measure Skyward B2 recurrence under current compaction.
3 runs; record mode + Handler C turn latencies. Writes skyward_b2_probe.json."""
import subprocess, sys, os, time, json, re
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT,"python"))
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT,".env"), override=False)
from client_intake_and_finmo.intake_submission import get_mysql_connection
PY=os.path.join(ROOT,".venv","Scripts","python.exe")
RUNNER=os.path.join(ROOT,"Test Files","run_persisted_system_run.py")
SRC="82b485233e51409ba14b1407e4fded99"
def hc_lat(did):
  try:
    c=get_mysql_connection(); cur=c.cursor()
    cur.execute("SELECT trace_json FROM post_intake_handler_traces WHERE draft_id=%s AND handler='gpt_io' ORDER BY seq",(did,))
    out=[]
    for (tj,) in cur.fetchall():
      p=json.loads(tj).get("payload",{}); n=p.get("consultant_name") or ""
      if "payroll_handler_c" in n: out.append({"ms":p.get("elapsed_ms"),"out":(p.get("usage") or {}).get("output_tokens"),"err":bool(p.get("error"))})
    cur.close(); c.close(); return out
  except Exception as e: return [{"err":str(e)[:80]}]
res=[]
for i in range(3):
  env=dict(os.environ); env["BPLAN_TRACE_VERBOSE"]="1"
  t0=time.time()
  try:
    p=subprocess.run([PY,RUNNER,"--draft-id",SRC],capture_output=True,text=True,timeout=600,env=env,cwd=ROOT)
    o=(p.stdout or "")+"\n"+(p.stderr or "")
  except subprocess.TimeoutExpired as e: o=(e.stdout or "")+"\n[HUNG]"
  m=re.search(r"new draft:\s*([0-9a-f]{32})",o); nid=m.group(1) if m else None
  mode="PASS" if "System run duration" in o else ("B2" if ("network_retry_exhausted" in o or "payroll_tool_calling_session_turn_failed" in o) else ("B1" if "stage_ramp_revenue_path_not_applied" in o else ("B3" if "payroll_tool_calling_session_exhausted" in o else "OTHER")))
  res.append({"run":i+1,"draft":nid,"mode":mode,"dur":round(time.time()-t0,1),"hc":hc_lat(nid) if nid else []})
  print("run",i+1,mode,nid,flush=True)
  json.dump(res, open(os.path.join(HERE,"skyward_b2_probe.json"),"w"), indent=2)
print("DONE", [r["mode"] for r in res])
