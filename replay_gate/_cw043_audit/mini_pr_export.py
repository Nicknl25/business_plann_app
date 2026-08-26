"""mini: export stored drafts through <root>'s workbook code, recalc all in ONE Excel instance, read Checks!B2.
usage: <root> <out_dir> <tag> <draft_prefix>..."""
import json, os, sys, time
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv
ROOT, OUT, TAG = sys.argv[1], Path(sys.argv[2]), sys.argv[3]; IDS = sys.argv[4:]; OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "python")); sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
load_dotenv(r"C:\dev\business_plann_app\.env")
import client_statements_output_excel.schedule_sheets as ss
assert os.path.abspath(ss.__file__).lower().startswith(os.path.abspath(ROOT).lower()), ss.__file__
print("PROVENANCE", ss.__file__)
from client_statements_output_excel.export_client_workbook import export_workbook_for_row
import openpyxl
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
import win32com.client as win32
x = win32.gencache.EnsureDispatch("Excel.Application"); x.Visible = False; x.DisplayAlerts = False
for pfx in IDS:
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (pfx+'%',)); row = dict(cur.fetchone())
    cur.execute("SELECT diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id LIKE %s ORDER BY id DESC LIMIT 1", (pfx+'%',)); d = cur.fetchone()
    diag = json.loads(d["diagnostics_json"]) if d else None
    name = row["business_name"]; row["business_name"] = f"{TAG} {pfx}"
    t0 = time.time()
    try:
        p = export_workbook_for_row(row, output_dir=OUT, run_diagnostics=diag)
    except Exception as e:
        print(f"EXPORT-FAIL {TAG} {pfx} {name}: {type(e).__name__}: {str(e)[:120]}"); continue
    w = x.Workbooks.Open(str(p))
    for _ in range(20):
        try: w.Sheets(1).Name; break
        except Exception: time.sleep(1.0)
    x.CalculateFullRebuild(); w.Save(); w.Close(False)
    b2 = openpyxl.load_workbook(str(p), data_only=True)["Checks"]["B2"].value
    print(f"BUILT {TAG} {pfx} {name!r} Checks!B2={b2!r} {int(time.time()-t0)}s -> {p}")
x.Quit(); cur.close(); c.close()
