import json, os, sys
from dotenv import load_dotenv
import mysql.connector
load_dotenv()
conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306))
cur = conn.cursor(dictionary=True)
cur.execute("SELECT draft_id, business_name, financials_json, model_input_json FROM intake_consult_drafts WHERE business_name LIKE %s ORDER BY updated_at DESC LIMIT 1", ("Understory%",))
r = cur.fetchone()
fin = json.loads(r["financials_json"]) if r["financials_json"] else {}
mi = json.loads(r["model_input_json"]) if r["model_input_json"] else {}
print("DRAFT", r["draft_id"][:12], r["business_name"])
for k in sorted(fin.keys()):
    v = fin[k]
    if isinstance(v, (int, float, str)) and str(v)[:60]:
        print(f"  fin.{k} = {str(v)[:70]}")
mb = ((mi.get("solver_input") or {}).get("margin_band_judgment") or {})
print("MB KEYS:", json.dumps(mb, indent=1)[:900])
