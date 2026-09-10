"""mini turn 19 - independent replay of the verbatim a9db48dd people-stage
patches through the REAL doors at HEAD, plus the same replay through a
NO-FOLD copy of intake_consult (the two turn-18 fold branches disabled) to
show what the healed-row fill-only fold is responsible for.
"""
import copy, importlib.util, io, json, logging, os, sys
ROOT = r"C:\dev\business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))
import api_handlers  # noqa
from api_handlers import intake_consult as IC
from client_intake_and_finmo.post_intake_contracts.people_json_contract import PeopleJsonContract, PersonContract
from pydantic import ValidationError

EVID = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit")
VERBATIM = json.load(open(os.path.join(EVID, "r9_people_canonicalize", "verbatim_turn_intent_rows.json"), encoding="utf-8"))
STORED = json.load(open(os.path.join(EVID, "r8_final_acceptance", "people_json_a9db48dd.json"), encoding="utf-8"))


def contract_errors(rows):
  env = copy.deepcopy(STORED)
  env["people"] = copy.deepcopy(rows)
  try:
    PeopleJsonContract.model_validate(env)
    return 0
  except ValidationError as e:
    return len(e.errors())


def capture(fn):
  buf = io.StringIO()
  h = logging.StreamHandler(buf)
  h.setFormatter(logging.Formatter("%(message)s"))
  lg = logging.getLogger("api_handlers.intake_consult")
  old = lg.level
  lg.addHandler(h); lg.setLevel(logging.INFO)
  try:
    out = fn()
  finally:
    lg.removeHandler(h); lg.setLevel(old)
  return out, [ln for ln in buf.getvalue().splitlines() if "PEOPLE_PATCH" in ln]


def replay(M, label):
  v = VERBATIM
  t45, t47, t51 = (copy.deepcopy(v[k]["patch"]) for k in ("turn45", "turn47", "turn51"))
  steps, traces = [], []

  def door(patch, ppl, fin):
    (_bf, _ops, _mk, np_, nf, _ff), lines = capture(lambda: M._apply_scoped_patch(
      copy.deepcopy(patch), business_facts={}, ops_json={}, market_json={},
      people_json=ppl, financials_json=fin, fulfillment_json={}))
    traces.extend(lines)
    return np_, nf

  ppl, fin = door(t45, {}, {}); steps.append(("t45", len(ppl["people"])))
  ppl, fin = door(t47, ppl, fin); steps.append(("t47", len(ppl["people"])))
  model_rows = []
  for r in t51["people.people"]:
    if "full_name" in r:
      m = dict(r); m["annual_wage"] = None; m.pop("wage_source", None); model_rows.append(m)
  (roster, _rep), lines = capture(lambda: M._merge_model_roster(ppl, model_rows, site="people_finalize_done_adding"))
  traces.extend(lines)
  ppl = dict(ppl); ppl["people"] = roster; steps.append(("finalize", len(roster)))
  fin, _y1 = M._sync_financials_consult_persistence_state(
    financials_json=fin, financials_year1_json={}, marketing_model_json={}, people_json=ppl, ops_json={})
  steps.append(("recalc", len(ppl["people"])))
  ppl, fin = door(t51, ppl, fin); steps.append(("t51", len(ppl["people"])))
  rows = ppl["people"]
  print(f"[{label}] steps={steps}")
  print(f"[{label}] PeopleJsonContract errors={contract_errors(rows)} on {len(rows)} rows")
  per_row = 0
  for r in rows:
    try:
      PersonContract.model_validate(r)
    except ValidationError as e:
      per_row += len(e.errors())
  print(f"[{label}] PersonContract per-row errors={per_row}")
  for r in rows:
    print(f"[{label}]   {r.get('full_name')!r} | {r.get('role_title')!r} | wage={r.get('annual_wage')!r} src={r.get('wage_source')!r} exp={r.get('experience_years')!r} rawkeys={[k for k in ('name','title','annual_pay','years_experience','education_credentials') if k in r]}")
  print(f"[{label}] owner_compensation={fin.get('owner_compensation')!r} current_payroll={fin.get('current_payroll')!r}")
  for ln in traces:
    print(f"[{label}] TRACE {ln[:230]}")
  return steps, rows


print("=== HEAD (real module) ===")
steps_head, rows_head = replay(IC, "HEAD")

# ---- NO-FOLD copy: disable the two turn-18 fold branches only ----
src_path = os.path.join(ROOT, "python", "api_handlers", "intake_consult.py")
src = open(src_path, encoding="utf-8").read()
a = 'if ident[0] == "name" and ident in standing_by_ident:'
b = 'if ident[0] == "name" and ident in out_by_ident:'
assert src.count(a) == 1 and src.count(b) == 1, (src.count(a), src.count(b))
nofold_src = src.replace(a, "if False:  # mini19 no-fold").replace(b, "if False:  # mini19 no-fold")
nf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ic_nofold.py")
open(nf_path, "w", encoding="utf-8").write(nofold_src)
spec = importlib.util.spec_from_file_location("api_handlers.intake_consult_nofold", nf_path)
NF = importlib.util.module_from_spec(spec)
sys.modules["api_handlers.intake_consult_nofold"] = NF
spec.loader.exec_module(NF)
print("=== NO-FOLD copy (both fold branches disabled, everything else HEAD) ===")
steps_nf, rows_nf = replay(NF, "NOFOLD")

# ---- stored 12-row roster heals on the next write ----
merged, rep = IC._merge_people_rows(copy.deepcopy(STORED["people"]), [])
print(f"stored a9db48dd 12-row roster through the helper on an empty write -> {len(merged)} rows, healed={rep['healed']}, dropped={rep['dropped']}, errors={contract_errors(merged)}")
merged_nf, rep_nf = NF._merge_people_rows(copy.deepcopy(STORED["people"]), [])
print(f"  same through NO-FOLD -> {len(merged_nf)} rows, errors={contract_errors(merged_nf)}")

# ---- trace shape for canonical rows: byte-identical to the item-5 format ----
existing = [{"full_name": "Ottoline Marchetti", "role_title": "Owner", "annual_wage": 155000.0, "wage_source": "client_override"}]
incoming = [{"full_name": "Ottoline Marchetti", "role_title": "Owner", "annual_wage": None}]
(m, r), lines = capture(lambda: IC._merge_model_roster(existing, incoming, site="people_finalize_review"))
old_fmt = "PEOPLE_PATCH site=%s incoming=%d restored=%s field_kept=%s" % ("people_finalize_review", r.get("incoming", 0), r.get("restored"), r.get("field_kept"))
print("trace canonical-rows line :", lines)
print("item-5 format rendered    :", [old_fmt])
print("byte-identical:", lines == [old_fmt])
