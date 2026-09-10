"""mini's item-5 audit instrument (2026-09-09): the retire rider across TWO
recalc passes. Pass 1 is the turn that raises the hold (the per-human
owner-row pass merges a same-human duplicate and stores {kept, other}).
Pass 2 is the NEXT turn's preamble recalc (intake_consult.py:17541), which
runs before every _coherence_gate call in the handler - i.e. before the
section.py popper (2203-2206) can ask the client. Offline, pure function,
writes nothing. Run from the repo root with the .venv python."""
import copy, io, logging, os, sys

ROOT = r"C:/dev/business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)
from api_handlers import intake_consult as IC  # noqa: E402

buf = io.StringIO()
h = logging.StreamHandler(buf)
h.setLevel(logging.INFO)
lg = logging.getLogger("api_handlers.intake_consult")
lg.addHandler(h)
lg.setLevel(logging.INFO)


def recalc(fin, ppl):
  fin = copy.deepcopy(fin)
  ppl = copy.deepcopy(ppl)
  out, _ = IC._sync_financials_consult_persistence_state(
    financials_json=fin, financials_year1_json={}, marketing_model_json={},
    people_json=ppl, ops_json={})
  return out, ppl


def lines():
  out = [l for l in buf.getvalue().splitlines() if "RETIRED" in l]
  buf.truncate(0)
  buf.seek(0)
  return out


TWO_OWNERS_WITH_DUP = {"people": [
  {"full_name": "Ottoline Marchetti", "role_title": "Principal Architect and Co-Owner",
   "annual_wage": 155000, "wage_source": "client_override"},
  {"full_name": "Rasheed Fennimore", "role_title": "Design Director and Co-Owner",
   "annual_wage": 142000, "wage_source": "client_override"},
  {"full_name": "ottoline marchetti", "role_title": "Owner",
   "annual_wage": 120000, "wage_source": "client_override"},
]}
ONE_OWNER_WITH_DUP = {"people": [
  {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
   "annual_wage": 48000, "wage_source": "client_override"},
  {"full_name": "delia rennick", "role_title": "Owner",
   "annual_wage": 33999.96, "wage_source": "client_override"},
]}

print("=== A. TWO named owners + a same-human duplicate (GENUINE conflict, Ottoline 155,000 vs 120,000)")
o1, p1 = recalc({}, TWO_OWNERS_WITH_DUP)
print(" pass 1 (raise turn)      hold:", o1.get("_owner_wage_conflict_hold"),
      "roster:", [(p["full_name"], p["annual_wage"]) for p in p1["people"]], "retire lines:", lines())
o2, p2 = recalc(o1, p1)
print(" pass 2 (next preamble)   hold:", o2.get("_owner_wage_conflict_hold"), "retire lines:", lines())
print(" VERDICT A:", "SILENT PICK - the genuine hold is retired before the gate asks"
      if o2.get("_owner_wage_conflict_hold") is None else "kept for the gate")

print("=== B. ONE owner + a same-human duplicate (the Sumac shape)")
s1, q1 = recalc({}, ONE_OWNER_WITH_DUP)
s2, q2 = recalc(s1, q1)
print(" pass 1 hold:", s1.get("_owner_wage_conflict_hold"), "pass 2 hold:", s2.get("_owner_wage_conflict_hold"),
      "retire lines:", lines())

print("=== C. legacy STALE hold (raised by the old per-title pass while deleting a second human) on the repaired two-human roster")
stale = {"_owner_wage_conflict_hold": {"kept": 155000.0, "other": 142000.0}, "current_payroll": 678000.0}
c1, r1 = recalc(stale, {"people": TWO_OWNERS_WITH_DUP["people"][:2]})
print(" pass 1 hold:", c1.get("_owner_wage_conflict_hold"), "current_payroll:", c1.get("current_payroll"), "retire lines:", lines())
