"""What did the realism gate actually see for ebitda_margin on the
final restructured Understory run? Value vs band vs status, verbatim."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
draft_id = sys.argv[1] if len(sys.argv) > 1 else "2c60f62fc636430eac3388d32933ea88"
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT realism_memo_json FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
)
row = cur.fetchone() or {}
memo = row.get("realism_memo_json")
memo = json.loads(memo) if isinstance(memo, str) and memo.strip() else (memo or {})
results = memo.get("results") or []
print(f"realism memo rows: {len(results)}")
for r in results:
    if not isinstance(r, dict):
        continue
    mk = str(r.get("metric_key") or "")
    if "ebitda" in mk.lower() or "margin" in mk.lower():
        print(json.dumps({
            "metric_key": mk,
            "status": r.get("status"),
            "actual_value": r.get("actual_value"),
            "band_min": r.get("band_min") or r.get("effective_min") or r.get("min_allowed"),
            "band_max": r.get("band_max") or r.get("effective_max") or r.get("max_allowed"),
            "band_source": r.get("band_source"),
            "quarter_index": r.get("quarter_index"),
            "detail": {k: r.get(k) for k in ("violation_reason", "note", "tolerance_bps") if r.get(k) is not None},
        }, sort_keys=True))
# Also every non-pass row, whatever the metric:
print("\nnon-pass rows:")
for r in results:
    if isinstance(r, dict) and "pass" not in str(r.get("status") or "").lower():
        print(" ", r.get("metric_key"), "->", r.get("status"),
              "actual:", r.get("actual_value"),
              "band:", r.get("band_min") or r.get("effective_min"), "-",
              r.get("band_max") or r.get("effective_max"))
cur.close()
conn.close()
