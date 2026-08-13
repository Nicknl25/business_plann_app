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
d = "ea30f6dc23784a35a73ac7f4352c2721"  # Understory W2
cur.execute(
    "SELECT planning_context_summary_json, planning_run_json, model_input_json "
    "FROM intake_consult_drafts WHERE draft_id=%s", (d,))
row = cur.fetchone()
pcs = json.loads(row["planning_context_summary_json"]) if row.get("planning_context_summary_json") else {}
pr = json.loads(row["planning_run_json"]) if row.get("planning_run_json") else {}
mi = json.loads(row["model_input_json"]) if row.get("model_input_json") else {}
contract = pcs.get("stage_ramp_contract") or {}
print("contract keys:", list(contract.keys())[:12])
print("rev_qoq_target_max:", contract.get("revenue_qoq_growth_target_max"),
      " spike_max:", contract.get("revenue_qoq_max_spike"),
      " spike_window:", contract.get("revenue_spike_window_quarters"),
      " max_spikes:", contract.get("max_spike_count"))
grid = contract.get("quarter_ramp_grid") or []
for r in grid:
    q = int(r.get("q") or r.get("quarter_index") or 0)
    if 4 <= q <= 8:
        print(f"  Q{q}: rev_target={r.get('rev_target') or r.get('revenue_qoq_target')} "
              f"rev_max={r.get('rev_max') or r.get('revenue_qoq_max')} spike={r.get('rev_spike') or r.get('revenue_qoq_spike_allowed')}")
# Any composite ramp violations recorded anywhere in the run payloads?
blob = json.dumps(pr) + json.dumps(pcs)
print("composite_revenue_ramp violations recorded:", blob.count("composite_revenue_ramp"))
cur.close()
conn.close()
