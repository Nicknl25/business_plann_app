"""A3 NEIGHBOR SWEEP: every behavior that flows through basis_from_intake,
evaluated on the most recent real drafts carrying a margin-band stamp -
gate tiers (fence / judged / flat), refresh_eval_stamps, corner_check
(where stored bounds exist), and the anchor-hold ceiling arithmetic.
Emits one JSON line per draft; run PRE-fix and POST-fix, diff the files.
usage: python _neighbor_sweep_a3_capacity_wall.py <out.jsonl> [N]
"""
import copy, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
import mysql.connector
from client_intake_and_finmo.intake_coherence import controller as _ctl
from client_intake_and_finmo.intake_coherence import section as sec
from client_intake_and_finmo.intake_coherence.evaluator import (
  GROWTH_FENCE_Q11, growth_multiple_from_judged, basis_from_intake, thresholds_from_margin_band,
)

out_path = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 40
conn = mysql.connector.connect(
  host=os.environ["MYSQL_HOST"], user=os.environ["MYSQL_USER"],
  password=os.environ["MYSQL_PASSWORD"], database=os.environ["MYSQL_DB"])
cur = conn.cursor(dictionary=True)
cur.execute(
  "SELECT draft_id, financials_json, operating_model_json, financials_year1_json, updated_at "
  "FROM intake_consult_drafts WHERE financials_json LIKE '%margin_band_judgment%' "
  "ORDER BY updated_at DESC LIMIT %s", (N,))
rows = cur.fetchall()
n = 0
with open(out_path, "w", encoding="utf-8") as fh:
  for row in rows:
    try:
      fin = json.loads(row["financials_json"] or "{}")
      ops = json.loads(row["operating_model_json"] or "{}")
      fy1 = json.loads(row["financials_year1_json"] or "{}")
    except Exception:
      continue
    state = fin.get("_coherence") or {}
    band = state.get("margin_band_judgment")
    if not band:
      continue
    rec = {"draft": row["draft_id"][:8], "name": (fin.get("business_name") or "")[:30]}
    def _ev(g):
      r = _ctl.evaluate_current(financials_json=fin, ops_json=ops, financials_year1_json=fy1, margin_band=band, growth_to_q11=g)
      if r is None:
        return None
      return {"passed": r["passed"], "failed": r["failed"], "gap": r["gap_quarterly"], "q11_rev": r["q11"]["revenue"],
              "growth": r.get("growth")}
    jm = growth_multiple_from_judged(state.get("judged_growth"), ops_json=ops)
    rec["fence"] = _ev(None)
    rec["judged"] = _ev(jm) if jm else None
    rec["flat"] = _ev(1.0)
    imp, ceil = sec._ops_implied_and_ceiling(ops)
    rec["anchor_hold"] = {"implied": round(imp, 2), "ceiling": round(ceil, 2)}
    # refresh_eval_stamps on a copy (production per-turn stamp)
    try:
      out = sec.refresh_eval_stamps(copy.deepcopy(fin), ops_json=ops, financials_year1_json=fy1)
      ev = (out.get("_coherence") or {}).get("eval") or {}
      rec["refresh"] = {"passed": ev.get("passed"), "gap": ev.get("gap_quarterly"), "growth": ev.get("growth")}
    except Exception as e:
      rec["refresh"] = f"ERR {type(e).__name__}"
    bounds = state.get("bounds")
    if isinstance(bounds, dict) and bounds:
      try:
        cb = basis_from_intake(financials_json=fin, ops_json=ops, financials_year1_json=fy1, growth_to_q11=GROWTH_FENCE_Q11)
        corner = _ctl.corner_check(basis=cb, thresholds=thresholds_from_margin_band(band), bounds=bounds, ops_json=ops, financials_json=fin)
        rec["corner"] = {"passed": corner.get("passed"), "gap": corner.get("gap_quarterly")}
      except Exception as e:
        rec["corner"] = f"ERR {type(e).__name__}"
    fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    n += 1
print(f"wrote {n} drafts -> {out_path}")
