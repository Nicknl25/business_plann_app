import os, json, mysql.connector
from dotenv import load_dotenv
load_dotenv("C:/dev/business_plann_app/.env")
c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True)
cur = c.cursor(dictionary=True)
for tag, d in [("PRE","rsn1au667fdc90de234a2d8faad8cbc8"),("POST","rsn1au0dcd915fefbf4fc8ba527762a9")]:
  cur.execute("SELECT planning_run_id, run_status, created_at, LEFT(failure_reason,60) fr, acceptance_verdict_json FROM planning_runs WHERE draft_id=%s ORDER BY created_at", (d,))
  print(f"== {tag} {d}")
  for r in cur.fetchall():
    v = r.get("acceptance_verdict_json")
    snap = None; passed=None
    if v:
      try:
        vj = json.loads(v) if isinstance(v,str) else v
        passed = vj.get("passed"); snap = (vj.get("field_snapshot") or {}).get("planning_run_id")
      except Exception as e: snap=f"ERR {e}"
    print(f"  {r['planning_run_id'][:12]} status={r['run_status']} created={r['created_at']} fr={r['fr']!r} verdict.passed={passed} snap.run_id={str(snap)[:12] if snap else snap}")
  cur.execute("SELECT planning_run_id, acceptance_passed FROM post_intake_run_diagnostics WHERE draft_id=%s", (d,))
  print("  diagnostics:", [(x['planning_run_id'][:12], x['acceptance_passed']) for x in cur.fetchall()])
