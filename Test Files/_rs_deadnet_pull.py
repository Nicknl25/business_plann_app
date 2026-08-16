"""Pull the persisted restructure guidance for a draft (dead-net red-proof support)."""
import os, sys, json
from dotenv import load_dotenv
import mysql.connector
load_dotenv()
prefix = sys.argv[1]
conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
  password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306))
cur = conn.cursor(dictionary=True)
cur.execute("SELECT draft_id, business_name, repair_guidance_json FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
for row in cur.fetchall():
  print(row["draft_id"], row["business_name"])
  rg = json.loads(row["repair_guidance_json"] or "{}")
  rs = rg.get("restructure") or {}
  print(" final_passed", rs.get("final_passed"), "keys", list(rs.keys()))
  for h in rs.get("history") or []:
    print("  stage", h.get("stage"), "found", h.get("found"), "evals", h.get("evals"), "feasible", h.get("feasible_region_exists"))
    for t in (h.get("trace") or []):
      print("     ", str(t)[:260])
cur.close(); conn.close()
