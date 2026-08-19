import json
import os

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute("SELECT financials_year1_json FROM intake_consult_drafts WHERE draft_id LIKE 'ea30f6dc%'")
r = cur.fetchone()
y1 = json.loads(r["financials_year1_json"] or "{}")


def walk(d, p="", depth=0):
    if depth > 3:
        return
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                print(f"{p}{k}: {type(v).__name__}" + (f" n={len(v)}" if isinstance(v, list) else ""))
                walk(v if isinstance(v, dict) else (v[0] if v else {}), p + "  ", depth + 1)
            else:
                print(f"{p}{k} = {json.dumps(v)[:110]}")
    elif isinstance(d, list) and d:
        walk(d[0], p + "  ", depth + 1)


walk(y1)
cur.close()
conn.close()
