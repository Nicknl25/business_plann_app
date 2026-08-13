"""Which prior Meridian drafts were PLAIN runs vs funding-preference
override proofs? Compare today's run against the right reference."""
import hashlib
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
cur.execute(
    "SELECT draft_id, updated_at, financials_json, finmo_json FROM intake_consult_drafts "
    "WHERE business_name=%s ORDER BY updated_at",
    ("Meridian Motorcars, LLC",),
)


def rows_hash(finmo_json):
    rows = []
    for r in (finmo_json or {}).get("quarter_rows") or []:
        if not isinstance(r, dict):
            continue
        clean = {
            k: (round(float(v), 6) if isinstance(v, (int, float)) else v)
            for k, v in sorted(r.items())
            if not isinstance(v, str) or k in ("quarter_label",)
        }
        rows.append(clean)
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()[:16]


for r in cur.fetchall():
    fin = json.loads(r["financials_json"]) if isinstance(r["financials_json"], str) else (r["financials_json"] or {})
    fm = json.loads(r["finmo_json"]) if isinstance(r["finmo_json"], str) and r["finmo_json"] else {}
    pref = fin.get("funding_preference")
    split = fin.get("funding_split_debt_share")
    print(f"{r['updated_at']} {r['draft_id'][:12]} pref={pref!r} split={split!r} "
          f"hash={rows_hash(fm) if fm else '(no finmo)'}")
cur.close()
conn.close()
