"""Verify the canary draft: coherence stamp vs post-intake margin band
(same artifact?), acceptance state, coherence state. Read-only."""
import json
import os

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_status, active_focus, financials_json, model_input_json, planning_run_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    ("17d8793b08b547d59b152aeb15237979",),
)
r = cur.fetchone()


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


fin = _j(r.get("financials_json"))
mi = _j(r.get("model_input_json"))
pr = _j(r.get("planning_run_json"))
coh = fin.get("_coherence") or {}
stamp = coh.get("margin_band_judgment") or {}
mi_band = ((mi.get("solver_input") or {}).get("margin_band_judgment")) or {}

print("draft_status:", r.get("draft_status"), "| active_focus:", r.get("active_focus"))
print("coherence status:", coh.get("status"))
print("coherence band q11:", stamp.get("q11"))
print("model_input band q11:", mi_band.get("q11"))
print("SAME ARTIFACT:", json.dumps(stamp, sort_keys=True) == json.dumps(mi_band, sort_keys=True))
print("digest_hash stamped:", bool(coh.get("digest_hash")))
print("eval passed:", (coh.get("eval") or {}).get("passed"),
      "| q11 margin:", ((coh.get("eval") or {}).get("q11") or {}).get("ebitda_margin"))
print("planning_run status:", pr.get("status"), "| acceptance:",
      pr.get("acceptance_passed") if "acceptance_passed" in pr else "(key absent)")
print("planning_run keys:", sorted(pr.keys())[:20])
cur.close()
conn.close()

