"""Batch B — B7: real stored joint-solve traces vs the judged band."""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from dotenv import load_dotenv
load_dotenv(os.path.join(HERE, "..", ".env"))
import mysql.connector

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)

def j(raw):
    if isinstance(raw, (dict, list)): return raw
    if isinstance(raw, (bytes, bytearray)): raw = raw.decode("utf-8", "ignore")
    if isinstance(raw, str) and raw.strip():
        try: return json.loads(raw)
        except Exception: return {}
    return {}

cur.execute(
    "SELECT draft_id, updated_at FROM intake_consult_drafts "
    "WHERE repair_guidance_json LIKE '%joint_solve%' ORDER BY updated_at DESC LIMIT 4")
hits = cur.fetchall()
for h in hits:
    did = h["draft_id"]
    cur.execute(
        "SELECT repair_guidance_json, model_input_json, operating_model_json "
        "FROM intake_consult_drafts WHERE draft_id=%s", (did,))
    row = cur.fetchone() or {}
    rg = j(row.get("repair_guidance_json"))
    mi = j(row.get("model_input_json"))
    om = j(row.get("operating_model_json"))
    mbj = ((mi.get("solver_input") or {}).get("margin_band_judgment") or {})
    print("=" * 74)
    print("draft", did, h["updated_at"], "| business:", om.get("business_name") or om.get("company_name"))
    print("  judged band: q11", mbj.get("q11"), "q20", mbj.get("q20"), "ni_floor", mbj.get("ni_margin_floor_q11"))
    restr = rg.get("restructure") or {}
    hist = restr.get("history") or []
    for it in hist:
        stage = it.get("stage")
        if not str(stage).startswith("search"):
            continue
        print(f"  {stage}: found={it.get('found')} evals={it.get('evals')}")
        for ln in (it.get("trace") or []):
            s = str(ln)
            if any(k in s for k in ("floor governed", "clamped", "rung", "targets", "joint_solve")):
                print("    trace:", s[:180])
        landed = it.get("landed") or {}
        if isinstance(landed, dict):
            print("    landed:", json.dumps(landed)[:300])
cur.close(); conn.close()
