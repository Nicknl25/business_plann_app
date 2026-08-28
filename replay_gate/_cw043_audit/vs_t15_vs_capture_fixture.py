"""Capture the named-person payroll fixture from the live drafts table."""
import os, sys, json, gzip, datetime, mysql.connector
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(r"C:\dev\business_plann_app\.env")
OUT = r"C:\dev\business_plann_app\tests\fixtures\payroll_named_person_payloads.json.gz"
QUERY = ("SELECT draft_id, business_name, payroll_headcount, finmo_json "
         "FROM intake_consult_drafts WHERE draft_id LIKE %s")
WANT = {
    "537e824e": "over-budget: a named full-timer and a named part-timer, supporting already at its floor",
    "09d10c39": "supporting absorbs: two named full-timers and a real supporting block",
}
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
drafts = {}
for short, why in WANT.items():
    cur.execute(QUERY, (short + "%",))
    rows = cur.fetchall()
    assert len(rows) == 1, (short, len(rows))
    r = rows[0]
    fj = json.loads(r["finmo_json"])
    drafts[short] = {
        "draft_id": r["draft_id"],
        "business_name": r["business_name"],
        "why": why,
        # verbatim as stored - the test parses it exactly as production does
        "payroll_headcount": r["payroll_headcount"],
        # the only part of finmo_json the orchestrator's anchor reads
        # (orchestrator.py:2987-2996 walks quarter_rows for quarter_index + revenue)
        "finmo_quarter_rows": [
            {"quarter_index": int(x["quarter_index"]), "revenue": x.get("revenue")}
            for x in fj["quarter_rows"] if isinstance(x, dict) and int(x.get("quarter_index") or 0) >= 1
        ],
    }
cur.close(); c.close()
blob = {
    "captured_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "captured_from": "intake_consult_drafts",
    "capture_query": QUERY,
    "drafts": drafts,
}
with gzip.open(OUT, "wt", encoding="utf-8") as fh:
    json.dump(blob, fh, indent=1, sort_keys=True)
print("wrote", OUT, os.path.getsize(OUT), "bytes")
for k, v in drafts.items():
    print("  ", k, v["draft_id"], v["business_name"], len(v["payroll_headcount"]), "chars,",
          len(v["finmo_quarter_rows"]), "quarter rows")
