import json
import os

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
# Non-restructure fleet members: does the landed trajectory respect the contract rev_max?
for label, d in (
    ("Sunny W2 (no restructure)", "ee7cd6b20cc142429e576214b5cf199c"),
    ("Blueprint W2 (no restructure)", "49181987acf24de4adf0f5e8b79e5bff"),
    ("Meridian clean (no restructure)", "0f8e1e1c5d8d414cb17e2c51f5860382"),
):
    cur.execute(
        "SELECT planning_context_summary_json, finmo_json FROM intake_consult_drafts WHERE draft_id=%s",
        (d,),
    )
    row = cur.fetchone()
    pcs = json.loads(row["planning_context_summary_json"]) if row.get("planning_context_summary_json") else {}
    fm = json.loads(row["finmo_json"])
    grid = ((pcs.get("stage_ramp_contract") or {}).get("quarter_ramp_grid")) or []
    rev_max_by_q = {}
    for r in grid:
        q = int(r.get("q") or r.get("quarter_index") or 0)
        v = r.get("rev_max") if r.get("rev_max") is not None else r.get("revenue_qoq_max")
        if q and v is not None:
            rev_max_by_q[q] = float(v)
    rows = {int(float(r.get("quarter_index"))): r for r in fm.get("quarter_rows") or [] if isinstance(r, dict)}
    worst = None
    for q in range(2, 21):
        prev = float((rows.get(q - 1) or {}).get("revenue") or 0)
        curr = float((rows.get(q) or {}).get("revenue") or 0)
        if prev <= 0:
            continue
        qoq = curr / prev - 1
        cap = rev_max_by_q.get(q)
        if cap is not None and qoq > cap + 0.005:
            worst = (q, round(qoq * 100, 1), round(cap * 100, 1))
    print(f"{label}: worst landed-over-contract breach = {worst if worst else 'NONE (choked properly)'}")
cur.close()
conn.close()
