import os
import sys
import json
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
    (sys.argv[1],),
)
mi = json.loads(cur.fetchone()["model_input_json"])
from client_intake_and_finmo.finmo_bridge import build_python_finmo_json

try:
    build_python_finmo_json(model_input_json=mi)
    print("BUILD OK")
except Exception:
    traceback.print_exc()
cur.close()
conn.close()
