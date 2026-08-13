"""Why didn't post-intake reuse the coherence band stamp? Compare the
stamped digest hash against a fresh digest built from the draft columns,
then hash each component to find the drifting input. Read-only."""
import hashlib
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")
from client_intake_and_finmo.post_intake_amalgamated.mirror import build_operating_model_digest
from client_intake_and_finmo.intake_coherence.controller import stable_digest_hash

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT operating_model_json, people_json, target_market_json, marketing_model_json, financials_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    ("e3e1cedd7f354006a0b1b1271ed87600",),
)
r = cur.fetchone()


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


ops = _j(r.get("operating_model_json"))
people = _j(r.get("people_json"))
market = _j(r.get("target_market_json"))
marketing = _j(r.get("marketing_model_json"))
fin = _j(r.get("financials_json"))
coh = fin.get("_coherence") or {}

fresh = build_operating_model_digest(ops, people, market, marketing)
fresh_hash = stable_digest_hash(fresh)
print("stamped hash:", coh.get("digest_hash"))
print("fresh hash:  ", fresh_hash)
print("MATCH:", fresh_hash == coh.get("digest_hash"))

# hash each digest slice to localize drift
for key in sorted(set(list(fresh.keys()))):
    part = json.dumps(fresh.get(key), sort_keys=True, default=str)
    print(f"  slice {key}: {hashlib.sha256(part.encode()).hexdigest()[:12]}  len={len(part)}")

# what would the digest be with EMPTY marketing (the gate may have seen a
# different marketing_model than the stored column)?
for label, mk in (("empty marketing", {}), ("stored marketing", marketing)):
    h = stable_digest_hash(build_operating_model_digest(ops, people, market, mk))
    print(f"digest with {label}: {h[:16]}  vs stamped {str(coh.get('digest_hash'))[:16]}")

cur.close()
conn.close()
