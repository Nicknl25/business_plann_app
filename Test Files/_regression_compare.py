"""Regression comparison: for each business, the LATEST draft vs the
PRIOR reference draft — verdict, restructure_present, and a canonical
hash of the finmo quarter rows (numeric business content only)."""
import hashlib
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

# (label, business_name, prior reference draft prefix, expect_restructure)
CASES = [
    ("Harvest Lane", "Harvest Lane Market, LLC", "25fd1ede85d8", False),
    ("Ironthread", "Ironthread Apparel Co.", "e2291b66d4c9", False),
    ("Meridian", "Meridian Motorcars, LLC", "04292a46ac2f", False),
    # Reference = the 11:57 four-line growing restructure (prune reverted).
    ("Understory", "Understory Mushroom Co.", "4c73db1f48cc", True),
]

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)


def _j(v):
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def canonical_rows_hash(finmo_json):
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
    payload = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


from client_intake_and_finmo.post_intake_acceptance.gate import verify_run_acceptance

for label, name, prior_prefix, expect_restructure in CASES:
    cur.execute(
        "SELECT draft_id, finmo_json, model_input_json, repair_guidance_json, planning_run_json, updated_at "
        "FROM intake_consult_drafts WHERE business_name=%s ORDER BY updated_at DESC LIMIT 1",
        (name,),
    )
    new = cur.fetchone()
    cur.execute(
        "SELECT draft_id, finmo_json FROM intake_consult_drafts WHERE draft_id LIKE %s",
        (prior_prefix + "%",),
    )
    old = cur.fetchone()
    if not new or not old:
        print(f"{label}: MISSING DRAFT (new={bool(new)}, old={bool(old)})")
        continue
    if str(new["draft_id"]).startswith(prior_prefix):
        print(f"{label}: no NEW run found (latest is the prior reference)")
        continue
    pr = _j(new.get("planning_run_json"))
    v = verify_run_acceptance(
        conn, draft_id=new["draft_id"],
        planning_run_id=str(pr.get("planning_run_id") or "").strip() or None,
    )
    rg = _j(new.get("repair_guidance_json"))
    restructure = (rg or {}).get("restructure") or {}
    restructure_present = bool(restructure)
    h_new = canonical_rows_hash(_j(new.get("finmo_json")))
    h_old = canonical_rows_hash(_j(old.get("finmo_json")))
    print(f"{label} (new draft {str(new['draft_id'])[:12]} vs prior {prior_prefix}):")
    print(f"  passed: {v.get('passed')}  failed: {v.get('failed_checks')}")
    print(f"  restructure_present: {restructure_present}"
          + (f"  final_passed: {restructure.get('final_passed')}" if restructure_present else ""))
    print(f"  finmo rows hash: new={h_new} old={h_old}  BYTE-IDENTICAL={h_new == h_old}")
    if expect_restructure:
        mi = _j(new.get("model_input_json"))
        lines = sorted({
            f"{r.get('lob')} / {r.get('product')}"
            for r in ((mi.get("sections") or {}).get("revenue") or [])
            if isinstance(r, dict) and r.get("driver") == "Unit Price"
        })
        fmn = _j(new.get("finmo_json"))
        rows_n = {int(float(r.get("quarter_index"))): r for r in fmn.get("quarter_rows") or [] if isinstance(r, dict)}
        revs = [round(float((rows_n.get(q) or {}).get("revenue") or 0)) for q in range(1, 21)]
        flat = sum(1 for i in range(1, 20) if revs[i] == revs[i - 1])
        print(f"  revenue lines shipped ({len(lines)}): {lines}")
        print(f"  revenue Q1={revs[0]:,} Q11={revs[10]:,} Q20={revs[19]:,}  flat quarter-pairs={flat}")
cur.close()
conn.close()
