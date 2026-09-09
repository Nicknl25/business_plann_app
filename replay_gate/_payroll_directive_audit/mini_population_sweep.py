"""mini: population blast radius of the rest-of-team anchor. For every draft
that has a stored payroll payload (latest checkpoint), apply the committed
anchor function to its stored supporting rows: movers must be exactly the
rot>0 drafts with a Q1 supporting pool that differs from the pool; every mover
carries an 'applied' stamp from the function; no rot -> never moves. Read-only."""
import json, os, sys, collections
ROOT = r"C:/dev/business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python")):
    if p not in sys.path: sys.path.insert(0, p)
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/924bd877-ade8-4dd8-941d-a9a35bdf23fe/scratchpad")
from pd_db import q, conn
from client_intake_and_finmo.post_intake_headcount.schedule import _anchor_supporting_rows_to_stated_pool
ids = [r["draft_id"] for r in q("SELECT DISTINCT draft_id FROM planning_run_checkpoints WHERE model_input_json IS NOT NULL")]
print("drafts with a stored checkpoint:", len(ids))
c = conn(); cur = c.cursor(dictionary=True)
tally = collections.Counter(); movers = []; bad = []
for i, d in enumerate(ids):
    cur.execute("SELECT model_input_json FROM planning_run_checkpoints WHERE draft_id=%s AND model_input_json IS NOT NULL ORDER BY created_at DESC LIMIT 1", (d,))
    row = cur.fetchone()
    try: mi = json.loads(row["model_input_json"] or "{}")
    except Exception: tally["unparseable"] += 1; continue
    ph = ((mi.get("derived_driver_runtime") or {}).get("expenses::Payroll") or {}).get("payroll_headcount")
    if not isinstance(ph, dict) or not ph.get("rows"): tally["no_payload"] += 1; continue
    cur.execute("SELECT business_name, people_json FROM intake_consult_drafts WHERE draft_id=%s", (d,))
    dr = cur.fetchone() or {}
    try: ppl = json.loads(dr.get("people_json") or "{}") or {}
    except Exception: ppl = {}
    rot = ppl.get("rest_of_team_payroll_year1")
    try: rotf = float(rot) if rot is not None else None
    except Exception: rotf = None
    sup = [r for r in ph["rows"] if isinstance(r, dict) and str(r.get("staffing_class")) == "supporting_staff"]
    before = json.dumps(sup, sort_keys=True)
    out, anchor = _anchor_supporting_rows_to_stated_pool([json.loads(json.dumps(r)) for r in sup], people_json=ppl)
    moved = json.dumps(out, sort_keys=True) != before
    if rotf is None or rotf <= 0:
        tally["no_pool"] += 1
        if moved or anchor is not None: bad.append((d[:8], "moved/stamped without a pool", anchor))
    else:
        disp = (anchor or {}).get("anchor_disposition")
        tally[f"pool:{disp}"] += 1
        if moved and disp != "applied": bad.append((d[:8], "moved without applied stamp", anchor))
        if disp == "applied" and not moved: bad.append((d[:8], "applied stamp but no move", anchor))
        if moved:
            movers.append((d[:8], dr.get("business_name"), rotf, anchor.get("q1_supporting_pool_before"), anchor.get("q1_supporting_pool_after"), anchor.get("factor")))
cur.close(); c.close()
print("tally:", dict(tally))
print("movers:", len(movers)); [print("  ", m) for m in movers]
print("violations:", bad)
