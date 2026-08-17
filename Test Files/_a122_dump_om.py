import json, os, sys
from dotenv import load_dotenv
import mysql.connector
load_dotenv()
conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306))
cur = conn.cursor(dictionary=True)
for prefix in sys.argv[1:]:
    cur.execute("SELECT draft_id, client_id, business_name, status, submitted_at, intake_submission_id, planning_run_status, operating_model_json FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
    for r in cur.fetchall():
        om = json.loads(r["operating_model_json"] or "{}")
        print("=== ", r["draft_id"], r["client_id"], r.get("business_name"), "status=", r["status"], "sub=", r["submitted_at"], r["intake_submission_id"], "prs=", r["planning_run_status"])
        flat = {k: om.get(k) for k in ("unit_name","unit_description","unit_price","units_per_week_capacity","units_per_period_capacity")}
        print("flat:", flat)
        for lm in om.get("lob_models") or []:
            for pr in (lm or {}).get("products") or []:
                print("row:", {k: pr.get(k) for k in ("name","product_name","unit_name","unit_description","unit_price","units_per_week_capacity","units_per_period_capacity","unit_cadence")})
