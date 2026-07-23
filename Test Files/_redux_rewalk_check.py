"""Would the two-tier rule have prevented the Redux false convergence?
Load the walk draft's POST-WALK configuration, stamp the run's own
judged growth, and evaluate both tiers. Fence-pass + judged-fail means:
the walk would have KEPT GOING instead of promising. Read-only."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")
from client_intake_and_finmo.intake_coherence.controller import evaluate_current
from client_intake_and_finmo.intake_coherence.evaluator import growth_multiple_from_judged

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT financials_json, operating_model_json, financials_year1_json, model_input_json "
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
ops = _j(r.get("operating_model_json"))
y1 = _j(r.get("financials_year1_json"))
mi = _j(r.get("model_input_json"))
band = (fin.get("_coherence") or {}).get("margin_band_judgment")
judged = (mi.get("solver_input") or {}).get("judged_growth")

mult = growth_multiple_from_judged(judged, ops_json=ops)
print(f"judged_growth: {judged}")
print(f"proposer-called Q1->Q11 multiple: x{mult:.4f}" if mult else "no judged multiple")

for label, growth in (("FENCE (what shipped yesterday)", None), ("JUDGED (two-tier walk standard)", mult)):
    ev = evaluate_current(
        financials_json=fin, ops_json=ops, financials_year1_json=y1,
        margin_band=band, growth_to_q11=growth,
    )
    q11 = ev.get("q11") or {}
    print(f"\n{label}:")
    print(f"  Q11 rev ${q11.get('revenue', 0):,.0f}/q  EBITDA ${q11.get('ebitda', 0):,.0f} "
          f"({q11.get('ebitda_margin', 0)*100:.1f}%)  passed={ev.get('passed')}  "
          f"failed={ev.get('failed')}  gap ${ev.get('gap_quarterly') or 0:,.0f}/q")

print("\nVERDICT: fence-pass + judged-fail means the walk would have continued "
      "instead of converging - the promise would not have been made on that config.")
cur.close()
conn.close()
