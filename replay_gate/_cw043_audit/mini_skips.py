"""re-derive the skips on <root> without Excel. usage: <root> ids..."""
import os, sys, json, mysql.connector, tempfile
ROOT = sys.argv[1]; IDS = sys.argv[2:]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "python")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv(r"C:\dev\business_plann_app\.env")
import client_statements_output_excel.schedule_sheets as ss
assert os.path.abspath(ss.__file__).lower().startswith(os.path.abspath(ROOT).lower()), ss.__file__
from client_statements_output_excel.export_client_workbook import export_workbook_for_row
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True); out = tempfile.mkdtemp(); ok = fail = 0
for pfx in IDS:
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (pfx+'%',)); row = cur.fetchone()
    if not row: print("  NOROW", pfx); fail += 1; continue
    row = dict(row); row["business_name"] = "SKIPCHK " + pfx
    try: export_workbook_for_row(row, output_dir=out); ok += 1; print("  EXPORTED", pfx)
    except Exception as e: fail += 1; print(f"  FAIL {pfx}: {type(e).__name__}: {str(e)[:70]}")
print(f"SKIPS on {os.path.basename(ROOT) or ROOT}: exported={ok} failed={fail} of {len(IDS)}")
