"""export a stored draft through <root>'s workbook code, recalc in Excel. usage: <root> <draft_prefix> <out_dir> <tag>"""
import json, os, sys, time
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv
ROOT, PREFIX, OUT, TAG = sys.argv[1], sys.argv[2], Path(sys.argv[3]), sys.argv[4]; OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "python")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(r"C:\dev\business_plann_app\.env")
import client_statements_output_excel.schedule_sheets as ss
assert os.path.abspath(ss.__file__).lower().startswith(os.path.abspath(ROOT).lower()), ss.__file__
from client_statements_output_excel.export_client_workbook import export_workbook_for_row
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True); cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (PREFIX+'%',)); row = dict(cur.fetchone())
cur.execute("SELECT diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id LIKE %s ORDER BY id DESC LIMIT 1", (PREFIX+'%',)); d = cur.fetchone(); cur.close(); c.close()
diag = json.loads(d["diagnostics_json"]) if d else None
mi = json.loads(row["model_input_json"]); sch = mi["sections"]["schedules"]
print(TAG, PREFIX, row["business_name"], "| debt seed", sch.get("debt_opening_balance_seed"), "lease seed", sch.get("lease_opening_balance_seed"), "judged term", ((mi.get("solver_input") or {}).get("cash_judgment") or {}).get("debt_term_quarters"))
row["business_name"] = f"{TAG} {PREFIX}"
p = export_workbook_for_row(row, output_dir=OUT, run_diagnostics=diag)
import win32com.client as win32
x = win32.gencache.EnsureDispatch("Excel.Application"); x.Visible = False; x.DisplayAlerts = False
w = x.Workbooks.Open(str(p))
for _ in range(20):
    try: w.Sheets(1).Name; break
    except Exception: time.sleep(1.5)
x.CalculateFullRebuild(); w.Save(); w.Close(False); x.Quit()
print("built+recalculated:", p)
