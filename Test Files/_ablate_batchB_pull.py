"""Batch B step 0 — pull real run data for the three drafts, summarize."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import mysql.connector

DRAFTS = {
    "Peachtree": "f62e846077ef40ca96f37edafb97a6fe",
    "Sunny_A": "29c4a053b9f64ab3aad10fbcf5256674",
    "Sunny_B": "a7ae3c0bb8fd42fd9c1e1b1714012e09",
}

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)

cur.execute("SHOW COLUMNS FROM intake_consult_drafts")
draft_cols = [r["Field"] for r in cur.fetchall()]
print("draft cols:", [c for c in draft_cols if "json" in c or "date" in c or "naics" in c])

cur.execute("SHOW COLUMNS FROM planning_runs")
pr_cols = [r["Field"] for r in cur.fetchall()]
print("planning_runs cols:", pr_cols)

def j(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "ignore")
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}

for name, did in DRAFTS.items():
    print("=" * 70)
    print(name, did)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (did,))
    d = cur.fetchone() or {}
    fin = j(d.get("finmo_json"))
    mi = j(d.get("model_input_json"))
    rows = fin.get("quarter_rows") or []
    print("  finmo quarter_rows:", len(rows))
    rev = {int(r.get("quarter_index")): r.get("revenue") for r in rows if isinstance(r, dict)}
    print("  revenue q1..q20:", [round(float(rev.get(q) or 0)) for q in sorted(rev)])
    si = (mi.get("solver_input") or {}) if isinstance(mi, dict) else {}
    mbj = si.get("margin_band_judgment")
    print("  margin_band_judgment:", json.dumps(mbj)[:600] if mbj else None)
    print("  judged_growth:", json.dumps(si.get("judged_growth"))[:300])
    print("  business_start_date:", d.get("business_start_date"), "naics:", d.get("business_naics_6") or mi.get("business_naics_6"))
    # planning run
    cur.execute("SELECT * FROM planning_runs WHERE draft_id=%s ORDER BY started_at DESC LIMIT 3", (did,))
    prs = cur.fetchall()
    for pr in prs:
        av = j(pr.get("acceptance_verdict_json"))
        checks = av.get("checks") or av.get("criteria") or {}
        print("  run", pr.get("planning_run_id"), "stage:", pr.get("current_stage"),
              "mode:", pr.get("planning_mode"), "tier:", pr.get("cascade_landed_tier"),
              "conf:", pr.get("plan_confidence"))
        print("    acceptance keys:", list(av.keys())[:20])
        if isinstance(checks, dict):
            for k, v in checks.items():
                p = v.get("passed") if isinstance(v, dict) else v
                print("     check", k, "->", p)
        vs = av.get("viability_standard")
        if vs:
            print("    viability_standard verdict:", vs.get("verdict"), "tier1:", vs.get("tier1_score"),
                  "thr:", vs.get("pass_refine_threshold"), "gates_all_pass:", (vs.get("gates") or {}).get("all_pass"))
cur.close(); conn.close()
