"""mini's payroll-directive audit (2026-09-09): replay the Marchetti roster
through (A) THE RECALC's owner-row uniqueness pass (the door the audit found)
and (B) VS's guarded people.people door. Run from repo root with .venv python.
Reads only; writes nothing to the DB."""
import json, logging, os, sys, io
ROOT = r"C:/dev/business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
    if p not in sys.path: sys.path.insert(0, p)
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/924bd877-ade8-4dd8-941d-a9a35bdf23fe/scratchpad")
from pd_db import q
from api_handlers.intake_consult import (_apply_scoped_patch, _sync_financials_consult_persistence_state, _OWNER_TITLE_RE)
E = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit")
d = "3201a64c637f47beb9f9583262874351"
row = q("SELECT financials_json, operating_model_json, people_json FROM intake_consult_drafts WHERE draft_id=%s", (d,))[0]
fin = json.loads(row["financials_json"]); ops = json.loads(row["operating_model_json"]); ppl_now = json.loads(row["people_json"])
final79 = json.load(open(os.path.join(E, "marchetti_turn79_finalize_people.json")))
both = [dict(p) for p in final79["people"]]
names = lambda ppl: [(p.get("full_name"), p.get("role_title"), p.get("annual_wage")) for p in (ppl.get("people") or [])]

print("=== A. THE RECALC (_sync_financials_consult_persistence_state) on the turn-79 finalize roster (both partners)")
print("owner-regex matches:", [(p["full_name"], bool(_OWNER_TITLE_RE.search(p["role_title"]))) for p in both])
ppl_a = {"people": [dict(p) for p in both], "rest_of_team_payroll_year1": 523000}
fin_a, y1_a = _sync_financials_consult_persistence_state(
    financials_json=json.loads(json.dumps(fin)), financials_year1_json={}, marketing_model_json={}, people_json=ppl_a, ops_json=json.loads(json.dumps(ops)))
print("roster BEFORE:", names({"people": both}))
print("roster AFTER :", names(ppl_a))
print("current_payroll after:", fin_a.get("current_payroll"), "owner_wage_conflict_hold:", fin_a.get("_owner_wage_conflict_hold"))
print("stored Marchetti roster today:", names(ppl_now), "stored current_payroll:", fin.get("current_payroll"))

print("\n=== A2. same pass with Rasheed titled plainly 'Design Director' (what the client SAID at turn 77)")
plain = [dict(p) for p in both]; plain[1]["role_title"] = "Design Director"
ppl_a2 = {"people": plain, "rest_of_team_payroll_year1": 523000}
fin_a2, _ = _sync_financials_consult_persistence_state(financials_json=json.loads(json.dumps(fin)), financials_year1_json={}, marketing_model_json={}, people_json=ppl_a2, ops_json=json.loads(json.dumps(ops)))
print("roster AFTER :", names(ppl_a2), "current_payroll:", fin_a2.get("current_payroll"))

print("\n=== B. VS's guarded door: people.people carrying ONE named person against a two-person roster")
buf = io.StringIO(); h = logging.StreamHandler(buf); h.setLevel(logging.INFO)
lg = logging.getLogger("api_handlers.intake_consult"); lg.addHandler(h); lg.setLevel(logging.INFO)
logging.getLogger().addHandler(h); logging.getLogger().setLevel(logging.INFO)
ppl_b = {"people": [dict(p) for p in both]}
patch = {"people.people": [{"full_name": "Ottoline Marchetti", "role_title": "Principal Architect and Co-Owner", "annual_wage": 155000, "wage_source": "client_override", "relevant_background": None}]}
_bf, _op, _mk, ppl_b2, fin_b, _ff = _apply_scoped_patch(patch, business_facts={}, ops_json={}, market_json={}, people_json=ppl_b, financials_json={}, fulfillment_json={})
print("roster AFTER people.people(Ottoline only):", names(ppl_b2))
print("PEOPLE_PATCH log lines:", [l for l in buf.getvalue().splitlines() if "PEOPLE_PATCH" in l])
print("\n=== B2. explicit remove_role still removes")
_bf, _op, _mk, ppl_b3, fin_b3, _ff = _apply_scoped_patch({"people.remove_role": "Rasheed Fennimore"}, business_facts={}, ops_json={}, market_json={}, people_json=ppl_b2, financials_json={}, fulfillment_json={})
print("roster AFTER remove_role(Rasheed):", names(ppl_b3))
print("\n=== B3. the guarded door's output then meets THE RECALC (the real sequence on a handler turn)")
ppl_b4 = {"people": [dict(p) for p in ppl_b2["people"]], "rest_of_team_payroll_year1": 523000}
fin_b4, _ = _sync_financials_consult_persistence_state(financials_json=json.loads(json.dumps(fin)), financials_year1_json={}, marketing_model_json={}, people_json=ppl_b4, ops_json=json.loads(json.dumps(ops)))
print("roster AFTER guard -> recalc:", names(ppl_b4), "current_payroll:", fin_b4.get("current_payroll"))
