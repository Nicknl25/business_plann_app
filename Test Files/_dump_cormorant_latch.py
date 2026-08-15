import json, sys
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(ROOT / "python")); sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))
from intake_submission import get_mysql_connection
conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT draft_id, active_focus, operating_model_json, messages_json FROM intake_consult_drafts WHERE draft_id LIKE 'ec1e22ef%'")
row = cur.fetchone()
ops = json.loads(row["operating_model_json"] or "{}")
print("draft", row["draft_id"], "focus", row["active_focus"])
print("business_type", ops.get("business_type"), "naics", ops.get("business_naics_6"), "stage", ops.get("business_stage"))
print("desc:", ops.get("business_description_summary"))
print("lobs:", json.dumps(ops.get("lob_models"), indent=1)[:3000])
print("latch:", json.dumps(ops.get("stream_discovery"), indent=1))
msgs = json.loads(row["messages_json"] or "[]")
print("n msgs", len(msgs))
for i, m in enumerate(msgs):
    print(i, m.get("role"), (m.get("content") or "")[:110].replace("\n"," "))
