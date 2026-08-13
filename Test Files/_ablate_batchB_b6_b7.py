"""Batch B — B6 detail (actual_value / mode / tolerance) + B7 stored restructure traces."""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from dotenv import load_dotenv
load_dotenv(os.path.join(HERE, "..", ".env"))
import mysql.connector

DRAFTS = {
    "Peachtree": "f62e846077ef40ca96f37edafb97a6fe",
    "Sunny_A": "29c4a053b9f64ab3aad10fbcf5256674",
}

def j(raw):
    if isinstance(raw, (dict, list)): return raw
    if isinstance(raw, (bytes, bytearray)): raw = raw.decode("utf-8", "ignore")
    if isinstance(raw, str) and raw.strip():
        try: return json.loads(raw)
        except Exception: return {}
    return {}

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)

print("B6 detail: actual_value + planning_mode + tolerance for ebitda_margin / net_income_margin q11 & q20")
for name, did in DRAFTS.items():
    cur.execute("SELECT realism_memo_json FROM intake_consult_drafts WHERE draft_id=%s", (did,))
    memo = j((cur.fetchone() or {}).get("realism_memo_json"))
    results = memo.get("results") or []
    for r in results:
        if not isinstance(r, dict): continue
        mk = str(r.get("metric_key"))
        qi = r.get("quarter_index")
        if mk in ("ebitda_margin", "net_income_margin") and qi in (11, 20):
            print(f"  {name} q{qi} {mk}: actual={r.get('actual_value')} min={r.get('effective_min')} "
                  f"max={r.get('effective_max')} tol_bps={r.get('tolerance_bps')} "
                  f"mode={r.get('planning_mode_active')} src={r.get('band_source')} status={r.get('status')}")
        if mk in ("ebitda_recovery_trend_q5_q11", "gross_margin_supports_ebitda_recovery",
                  "fixed_cost_burden_reduced_or_scaled_by_q11",
                  "ebitda_margin_q20_holds_or_improves_vs_q11") and name == "Peachtree":
            print(f"  {name} TRAJ {mk}: actual={r.get('actual_value')} status={r.get('status')}")

print()
print("B7: search for stored restructure traces (joint_solve) across drafts")
cur.execute("SELECT draft_id, updated_at, planning_runtime_json IS NOT NULL as has_rt FROM intake_consult_drafts ORDER BY updated_at DESC LIMIT 60")
rows = cur.fetchall()
hits = []
for r in rows:
    did = r["draft_id"]
    cur.execute(
        "SELECT draft_id, updated_at, "
        " planning_runtime_json LIKE '%joint_solve%' AS rt_hit, "
        " planning_run_json LIKE '%joint_solve%' AS pj_hit, "
        " planning_runtime_json LIKE '%restructure%' AS rt_restr "
        "FROM intake_consult_drafts WHERE draft_id=%s", (did,))
    x = cur.fetchone()
    if x and (x["rt_hit"] or x["pj_hit"] or x["rt_restr"]):
        hits.append(x)
for x in hits[:15]:
    print("  hit:", x["draft_id"], x["updated_at"], "joint_solve_rt:", x["rt_hit"], "joint_solve_pj:", x["pj_hit"], "restructure_rt:", x["rt_restr"])
print("total hits in latest 60 drafts:", len(hits))
cur.close(); conn.close()
