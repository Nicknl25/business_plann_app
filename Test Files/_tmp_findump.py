import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute("SELECT financials_json FROM intake_consult_drafts WHERE draft_id=%s", (sys.argv[1],))
fin = json.loads(cur.fetchone()["financials_json"])
for k in ("other_operating_expense", "other_opex_absolute", "current_cogs", "cogs_total_year1",
          "cogs_percent_of_revenue", "current_payroll", "payroll_total_year1",
          "_financials_revenue_intro_done", "_financials_marketing_stage_done",
          "other_monthly_debt_payments", "annual_interest_payment"):
    print(f"  {k} = {fin.get(k)}")
cur.close()
conn.close()
