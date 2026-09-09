"""mini: anchor arithmetic with my own rebuild on the stored payroll payloads
(latest checkpoint's derived_driver_runtime['expenses::Payroll']['payroll_headcount']).
For each draft: Q1 supporting pool from the stored rows, the anchor applied to
the stored supporting rows by the committed function, invariants, named-row
exemption, and the provenance stamp on the stored payload. Read-only."""
import json, os, sys
ROOT = r"C:/dev/business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python")):
    if p not in sys.path: sys.path.insert(0, p)
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/924bd877-ade8-4dd8-941d-a9a35bdf23fe/scratchpad")
from pd_db import q
from client_intake_and_finmo.post_intake_headcount.schedule import _anchor_supporting_rows_to_stated_pool
E = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit")
DRAFTS = ["3201a64c","176d4279","bb793dbb","c8a6b6b5","b4929a89","65e3c466","482b870f","1b7eeb63"]
def payload_for(draft_id):
    c = q("SELECT checkpoint_id, stage, created_at, model_input_json FROM planning_run_checkpoints WHERE draft_id=%s AND model_input_json IS NOT NULL ORDER BY created_at DESC LIMIT 1", (draft_id,))
    if not c: return None, None
    mi = json.loads(c[0]["model_input_json"] or "{}")
    ph = ((mi.get("derived_driver_runtime") or {}).get("expenses::Payroll") or {}).get("payroll_headcount")
    return ph, c[0]
def q1_pool(rows, cls="supporting_staff"):
    return sum(float(r.get("ending_fte") or 0) * float(r.get("annual_wage") or 0) for r in rows if int(r.get("quarter_index") or 0) == 1 and str(r.get("staffing_class")) == cls)
sig = {}
for pre in DRAFTS:
    d = q("SELECT draft_id, business_name, people_json FROM intake_consult_drafts WHERE draft_id LIKE %s", (pre+"%",))[0]
    ppl = json.loads(d["people_json"] or "{}"); rot = ppl.get("rest_of_team_payroll_year1")
    ph, ck = payload_for(d["draft_id"])
    if not ph: print(pre, d["business_name"], "NO PAYLOAD"); continue
    json.dump(ph, open(os.path.join(E, f"payload_{pre}.json"), "w"), indent=1)
    rows = [r for r in (ph.get("rows") or []) if isinstance(r, dict)]
    sup = [r for r in rows if str(r.get("staffing_class")) == "supporting_staff"]
    named = [r for r in rows if str(r.get("staffing_class")) == "key_person"]
    q1s = q1_pool(rows); q1n = q1_pool(rows, "key_person")
    print(f"\n== {pre} {d['business_name']} ckpt={ck['stage']} @ {str(ck['created_at'])[:19]} rot={rot}")
    print(f"   rows={len(rows)} supporting={len(sup)} named={len(named)} Q1 supporting pool={q1s:,.0f} Q1 named pool={q1n:,.0f} stored stamp={ph.get('rest_of_team_anchor')} labor_scaling={'labor_scaling_trace' in ph or 'labor_scaling' in json.dumps(ph)[:0]}")
    print(f"   stored keys: {[k for k in ph.keys() if 'anchor' in k or 'scal' in k or 'decision' in k]}")
    q1_fte = {r.get('oews_occ_title'): (r.get('starting_fte'), r.get('hires'), r.get('ending_fte'), r.get('annual_wage')) for r in sup if int(r.get('quarter_index') or 0)==1}
    print(f"   Q1 supporting rows: {q1_fte}")
    print(f"   named Q1 rows: {[(r.get('full_name') or r.get('oews_occ_title'), r.get('ending_fte'), r.get('annual_wage')) for r in named if int(r.get('quarter_index') or 0)==1]}")
    # my rebuild: the committed anchor on the stored supporting rows
    before = json.dumps(sup, sort_keys=True)
    out, anchor = _anchor_supporting_rows_to_stated_pool([json.loads(json.dumps(r)) for r in sup], people_json=ppl)
    after_pool = q1_pool(out)
    moved = json.dumps(out, sort_keys=True) != before
    print(f"   ANCHOR on stored supporting rows -> {anchor}; Q1 pool after={after_pool:,.0f}; rows moved={moved}")
    if anchor and anchor.get("applied"):
        bad = [r for r in out if abs(float(r['starting_fte']) + float(r['hires']) - float(r['ending_fte'])) > 1e-9]
        # forward continuity: ending_fte(q) == starting_fte(q+1) per title
        cont_bad = []
        by_title = {}
        for r in out: by_title.setdefault(r.get('oews_occ_title'), {})[int(r['quarter_index'])] = r
        for t, qs in by_title.items():
            for qi in sorted(qs):
                if qi+1 in qs and abs(float(qs[qi]['ending_fte']) - float(qs[qi+1]['starting_fte'])) > 1e-9: cont_bad.append((t, qi, qs[qi]['ending_fte'], qs[qi+1]['starting_fte']))
        print(f"   invariants: start+hires=end violations={len(bad)}; forward continuity violations={len(cont_bad)} {cont_bad[:3]}")
        print(f"   factor={anchor.get('factor')} Q1 FTE before={sum(float(r['ending_fte']) for r in sup if int(r['quarter_index'])==1):.2f} after={sum(float(r['ending_fte']) for r in out if int(r['quarter_index'])==1):.2f}; named rows untouched by construction (fn receives supporting rows only) -> named Q1 pool stays {q1n:,.0f}")
    sig[pre] = json.dumps({k: v for k, v in ph.items() if k not in ('draft_id','client_id')}, sort_keys=True)
print("\n== Sunny payload byte-compare (post-anchor canary 1b7eeb63 vs pre-anchor bb793dbb / 176d4279; 482b870f differs by design - the door-smoke edits):")
for a, b in (("1b7eeb63","bb793dbb"), ("1b7eeb63","176d4279"), ("bb793dbb","176d4279")):
    if a in sig and b in sig: print(f"   {a} == {b}: {sig[a] == sig[b]}")
