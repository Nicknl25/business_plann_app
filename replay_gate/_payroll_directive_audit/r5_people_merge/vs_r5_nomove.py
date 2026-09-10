"""Item 5 (R1 + hold-retire rider) NO-MOVE proof (VS, 2026-09-09).
Runs THE RECALC (_sync_financials_consult_persistence_state, a pure function:
no :5050 call, no system run, no writing-phase trigger) on DEEP COPIES of the
stored rows of the payroll-directive draft set and digests the resulting
financials_json / people_json. Run once BEFORE the edit (--label before) and
once AFTER (--label after); compare.py diffs the two. Also runs the census of
_owner_wage_conflict_hold carriers on deep copies and counts how many holds
WOULD retire under the current build. Writes NOTHING to the DB.
"""
import copy, hashlib, json, os, sys, datetime
ROOT = r"C:\dev\business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path: sys.path.insert(0, p)
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/413697dc-c7da-4fee-9cab-61d0ae6edcaf/scratchpad")
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))
from pd_db import q
from api_handlers.intake_consult import _sync_financials_consult_persistence_state, _OWNER_TITLE_RE

LABEL = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else "before"
E = os.path.dirname(os.path.abspath(__file__))
SET = {
  "176d4279": "canary (Sunny, AUDIT_SUMMARY)", "1b7eeb63": "canary (Sunny post-anchor)",
  "482b870f": "canary door smoke", "65e3c466": "Ardenwald Cold Storage",
  "b4929a89": "Sunny Glaze Donuts 09-08", "bb793dbb": "canary (Sunny pre-anchor)",
  "c8a6b6b5": "Sunny Glaze Donuts (stalled replay)",
  "3201a64c": "LIVE Marchetti & Fen", "3c2224e1": "LIVE Northwind Systems",
}

def dig(o):
  return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]

def names(ppl):
  return [(p.get("full_name"), p.get("role_title"), p.get("annual_wage"), p.get("wage_source")) for p in (ppl.get("people") or []) if isinstance(p, dict)]

def load(prefix):
  rows = q("SELECT draft_id, business_name, people_json, financials_json, financials_year1_json, marketing_model_json, operating_model_json FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
  return rows

def recalc(row):
  fin = json.loads(row["financials_json"] or "{}") or {}
  ppl = json.loads(row["people_json"] or "{}") or {}
  y1 = json.loads(row["financials_year1_json"] or "{}") or {}
  mk = json.loads(row["marketing_model_json"] or "{}") or {}
  ops = json.loads(row["operating_model_json"] or "{}") or {}
  fin_c, ppl_c, y1_c, mk_c, ops_c = (copy.deepcopy(x) for x in (fin, ppl, y1, mk, ops))
  fin_out, y1_out = _sync_financials_consult_persistence_state(
    financials_json=fin_c, financials_year1_json=y1_c, marketing_model_json=mk_c,
    people_json=ppl_c, ops_json=ops_c)
  return fin, ppl, fin_out, ppl_c, y1_out

out = {"label": LABEL, "at": datetime.datetime.now().isoformat(timespec="seconds"), "drafts": {}, "census": {}}
lines = [f"=== item 5 NO-MOVE proof, label={LABEL} at {out['at']}"]
for prefix, why in SET.items():
  rows = load(prefix)
  if len(rows) != 1:
    lines.append(f"{prefix} {why}: {len(rows)} rows in DB - SKIPPED")
    out["drafts"][prefix] = {"rows": len(rows)}
    continue
  r = rows[0]
  fin, ppl, fin_out, ppl_out, y1_out = recalc(r)
  rec = {
    "draft_id": r["draft_id"], "business": r["business_name"],
    "stored_fin": dig(fin), "stored_ppl": dig(ppl),
    "recalc_fin": dig(fin_out), "recalc_ppl": dig(ppl_out), "recalc_y1": dig(y1_out),
    "current_payroll": fin_out.get("current_payroll"),
    "rest": ppl_out.get("rest_of_team_payroll_year1"),
    "owner_compensation": fin_out.get("owner_compensation"),
    "hold_stored": fin.get("_owner_wage_conflict_hold"),
    "hold_after": fin_out.get("_owner_wage_conflict_hold"),
    "fold_hold_after": fin_out.get("_payroll_fold_hold"),
    "roster_after": names(ppl_out),
  }
  out["drafts"][prefix] = rec
  lines.append(f"{prefix} {r['business_name']!s:32} stored fin={rec['stored_fin']} ppl={rec['stored_ppl']} | recalc fin={rec['recalc_fin']} ppl={rec['recalc_ppl']} y1={rec['recalc_y1']} payroll={rec['current_payroll']} rest={rec['rest']} owner_comp={rec['owner_compensation']} hold={rec['hold_stored']}->{rec['hold_after']}")
  lines.append(f"         roster: {rec['roster_after']}")

# census of stale-hold carriers, on deep copies
lines.append("")
lines.append("=== census: _owner_wage_conflict_hold carriers, THE RECALC replayed on deep copies (nothing written)")
rows = q("SELECT draft_id, business_name, created_at, people_json, financials_json, financials_year1_json, marketing_model_json, operating_model_json FROM intake_consult_drafts")
carriers, would_retire, kept, errors, two_named = [], [], [], [], 0
for r in rows:
  try: fin = json.loads(r["financials_json"] or "{}") or {}
  except Exception: continue
  if not isinstance(fin.get("_owner_wage_conflict_hold"), dict):
    continue
  carriers.append(r["draft_id"][:8])
  try:
    _f, ppl, fin_out, ppl_out, _y = recalc(r)
  except Exception as ex:
    errors.append((r["draft_id"][:8], repr(ex)[:80])); continue
  owners = [p for p in (ppl_out.get("people") or []) if isinstance(p, dict) and _OWNER_TITLE_RE.search(str(p.get("role_title") or ""))]
  named = {" ".join(str(p.get("full_name") or "").lower().split()) for p in owners if str(p.get("full_name") or "").strip()}
  if len(named) >= 2: two_named += 1
  if isinstance(fin_out.get("_owner_wage_conflict_hold"), dict):
    kept.append((r["draft_id"][:8], r["business_name"], fin_out["_owner_wage_conflict_hold"], [(p.get("full_name"), p.get("role_title"), p.get("annual_wage")) for p in owners]))
  else:
    would_retire.append((r["draft_id"][:8], r["business_name"], fin["_owner_wage_conflict_hold"], [(p.get("full_name"), p.get("role_title"), p.get("annual_wage")) for p in owners]))
out["census"] = {"carriers": len(carriers), "would_retire": len(would_retire), "kept": len(kept), "errors": errors,
                 "two_named_owner_humans_among_carriers": two_named,
                 "would_retire_list": would_retire, "kept_list": kept}
lines.append(f"carriers={len(carriers)} would_retire={len(would_retire)} kept={len(kept)} errors={len(errors)} carriers_with_two_named_owner_humans={two_named}")
for x in kept[:200]: lines.append(f"  KEPT   {x}")
for x in would_retire[:200]: lines.append(f"  RETIRE {x}")
for x in errors: lines.append(f"  ERROR  {x}")
txt = "\n".join(lines)
print(txt)
open(os.path.join(E, f"nomove_{LABEL}.txt"), "w", encoding="utf-8").write(txt + "\n")
json.dump(out, open(os.path.join(E, f"nomove_{LABEL}.json"), "w", encoding="utf-8"), indent=1, default=str)
