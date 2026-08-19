import json
import os
import sys
import traceback

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT model_input_json FROM intake_consult_drafts WHERE draft_id=%s",
    ("3464962b16864c1a942d48c746dc48bb",),
)
mi = json.loads(cur.fetchone()["model_input_json"])
cur.close()
conn.close()

from client_intake_and_finmo.post_intake_restructure.searcher import apply_candidate
from client_intake_and_finmo.post_intake_restructure.fast_evaluator import build_fast_finmo

cand = {
    "new_lines": [
        {
            "lob": "Value-Added", "product": "Dried Mushroom Products",
            "unit_price": 14.0, "gross_margin_pct": 0.55,
            "q11_quarterly_revenue": 20000.0,
        }
    ]
}
mi2 = apply_candidate(mi, cand)
try:
    build_fast_finmo(mi2)
    print("BUILD OK")
except Exception:
    traceback.print_exc()
