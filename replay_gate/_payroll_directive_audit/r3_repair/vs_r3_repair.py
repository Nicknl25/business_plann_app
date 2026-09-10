"""R3 DATA REPAIR (VS, 2026-09-09, item 2 of Nick's payroll rulings).
Restores the deleted second co-owner on two LIVE drafts through the guarded
people.people door (_apply_scoped_patch -> _merge_people_rows, PEOPLE_PATCH
trace), runs THE RECALC in-process (a pure function: no :5050 call, no
system run, no writing-phase trigger), and persists ONLY the columns the
handler path would persist. Default = DRY RUN on deep copies. --write persists.
"""
import copy, hashlib, io, json, logging, os, sys, datetime
ROOT = r"C:\dev\business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path: sys.path.insert(0, p)
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/e7c6ea70-948d-44f2-b6f4-4c8aaaadb609/scratchpad")
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))
from pd_db import q, conn as fresh_conn
from api_handlers.intake_consult import _apply_scoped_patch, _sync_financials_consult_persistence_state

WRITE = "--write" in sys.argv
E = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit", "r3_repair")
os.makedirs(E, exist_ok=True)
EVID = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit", "marchetti_turn79_finalize_people.json")


def names(ppl):
  return [(p.get("full_name"), p.get("role_title"), p.get("annual_wage"), p.get("wage_source")) for p in (ppl.get("people") or [])]


def sub(row, biz):
  return {k: (v.replace("{{fact:business.name}}", biz) if isinstance(v, str) else v) for k, v in row.items()}


def rasheed_row():
  d = json.load(open(EVID, encoding="utf-8"))
  r = [p for p in d["people"] if p["full_name"] == "Rasheed Fennimore"][0]
  return sub(r, "Marchetti & Fen")


def rajan_row():
  rows = q("SELECT response_text FROM post_intake_gpt_response_store WHERE input_hash LIKE %s", ("63cc005b20fd%",))
  assert len(rows) == 1
  j = json.loads(rows[0]["response_text"])

  def find(o):
    if isinstance(o, dict):
      if isinstance(o.get("people"), list) and any(isinstance(p, dict) and p.get("full_name") == "Rajan Mehta" for p in o["people"]):
        return [p for p in o["people"] if p.get("full_name") == "Rajan Mehta"][0]
      for v in o.values():
        f = find(v)
        if f: return f
    elif isinstance(o, list):
      for v in o:
        f = find(v)
        if f: return f
    elif isinstance(o, str) and o.lstrip().startswith("{"):
      try: return find(json.loads(o))
      except Exception: return None
    return None
  r = dict(find(j))
  # the wage the client accepted at turn 65 and the source the deleted row carried
  # (the conflict hold {650,000 / 202,210} is raised ONLY when both rows are client_override)
  r["annual_wage"] = 202210.0
  r["wage_source"] = "client_override"
  return sub(r, "Northwind Systems, Inc.")


TARGETS = [
  ("marchetti_3201a64c", "3201a64c637f47beb9f9583262874351", rasheed_row),
  ("northwind_3c2224e1", "3c2224e10ddc4d8e947c73fe5a75b21a", rajan_row),
]
COLS = ["people_json", "financials_json", "financials_year1_json", "marketing_model_json", "operating_model_json"]


def sha(o):
  return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:12]


def state_line(ppl, fin):
  return ("roster=%s rest_of_team_payroll_year1=%s current_payroll=%s payroll_total_year1=%s owner_compensation=%s _owner_wage_conflict_hold=%s _payroll_fold_hold=%s payroll_stated_total_target=%s"
          % (names(ppl), ppl.get("rest_of_team_payroll_year1"), fin.get("current_payroll"), fin.get("payroll_total_year1"),
             fin.get("owner_compensation"), fin.get("_owner_wage_conflict_hold"), fin.get("_payroll_fold_hold"), fin.get("payroll_stated_total_target")))


def dict_diff(a, b, path=""):
  out = []
  keys = sorted(set(a) | set(b), key=str) if isinstance(a, dict) and isinstance(b, dict) else []
  for k in keys:
    if k not in a: out.append("  + %s%s = %s" % (path, k, json.dumps(b[k], default=str)[:160]))
    elif k not in b: out.append("  - %s%s (was %s)" % (path, k, json.dumps(a[k], default=str)[:160]))
    elif a[k] != b[k]:
      if isinstance(a[k], dict) and isinstance(b[k], dict): out += dict_diff(a[k], b[k], path + k + ".")
      else: out.append("  ~ %s%s: %s -> %s" % (path, k, json.dumps(a[k], default=str)[:120], json.dumps(b[k], default=str)[:120]))
  return out


log = []


def P(*a):
  s = " ".join(str(x) for x in a); print(s); log.append(s)


P("R3 DATA REPAIR", "WRITE" if WRITE else "DRY-RUN", datetime.datetime.now().isoformat(timespec="seconds"))
for tag, draft_id, rowfn in TARGETS:
  P("\n==================", tag, draft_id)
  runs_before = q("SELECT planning_run_id, run_status, created_at FROM planning_runs WHERE draft_id=%s ORDER BY created_at DESC", (draft_id,))
  P("planning_runs BEFORE:", [(r["planning_run_id"][:8], r["run_status"], str(r["created_at"])[:19]) for r in runs_before])
  row = q("SELECT " + ", ".join(COLS) + ", updated_at, business_name FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))[0]
  before = {c: json.loads(row[c] or "{}") for c in COLS}
  P("updated_at BEFORE:", row["updated_at"], "| column digests BEFORE:", {c: sha(before[c]) for c in COLS})
  P("BEFORE:", state_line(before["people_json"], before["financials_json"]))
  P("BEFORE people.people rows verbatim:")
  for p in before["people_json"].get("people") or []: P("   ", json.dumps(p, ensure_ascii=False))

  ppl = copy.deepcopy(before["people_json"]); fin = copy.deepcopy(before["financials_json"])
  y1 = copy.deepcopy(before["financials_year1_json"]); mkt = copy.deepcopy(before["marketing_model_json"]); ops = copy.deepcopy(before["operating_model_json"])
  incoming = rowfn()
  P("incoming row (guarded door people.people=[row]):", json.dumps(incoming, ensure_ascii=False))

  buf = io.StringIO(); h = logging.StreamHandler(buf); h.setLevel(logging.INFO); h.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
  lg = logging.getLogger("api_handlers.intake_consult"); lg.addHandler(h); lg.setLevel(logging.INFO)
  root = logging.getLogger(); root.addHandler(h); root.setLevel(logging.INFO)
  # (i) DOOR PROOF, in memory only: the single restored row through the guard -
  # the guard RESTORES the standing owner row and leaves the PEOPLE_PATCH trace.
  _bf, _op, _mk, ppl_proof, _fp, _ff = _apply_scoped_patch(
    {"people.people": [incoming]}, business_facts={}, ops_json={}, market_json={},
    people_json=copy.deepcopy(ppl), financials_json=copy.deepcopy(fin), fulfillment_json={})
  P("door proof (single row, NOT persisted) roster:", names(ppl_proof))
  # (ii) THE PERSISTED WRITE: the full roster in its ORIGINAL order (the
  # standing rows first, the restored partner where the finalize had them)
  # through the same guarded door. The owner_compensation mirror follows the
  # FIRST roster row (R4, order-dependent, item 7 fixes the meaning) - the
  # faithful repair restores the order the deletion took away, so the mirror
  # does not move this turn.
  full = [dict(r) for r in (ppl.get("people") or []) if isinstance(r, dict)] + [incoming]
  from api_handlers.intake_consult import _merge_people_rows
  _merged_preview, guard_report = _merge_people_rows(ppl.get("people"), [dict(r) for r in full])
  P("guard report for the persisted write (verbatim _merge_people_rows report):", json.dumps(guard_report, ensure_ascii=False))
  _bf, _op, _mk, ppl2, fin2, _ff = _apply_scoped_patch(
    {"people.people": full}, business_facts={}, ops_json={}, market_json={},
    people_json=ppl, financials_json=fin, fulfillment_json={})
  P("after guarded door (full roster, original order):", names(ppl2))
  fin3, y1b = _sync_financials_consult_persistence_state(
    financials_json=fin2, financials_year1_json=y1, marketing_model_json=mkt, people_json=ppl2, ops_json=ops)
  lg.removeHandler(h); root.removeHandler(h)
  trace = [l for l in buf.getvalue().splitlines() if "PEOPLE_PATCH" in l or "OWNER_ROW" in l or "PAYROLL" in l or "REST_OF_TEAM" in l]
  P("trace lines (door proof + persisted write + recalc):")
  if trace:
    for l in trace: P("   ", l)
  else:
    P("    (none)")
  P("AFTER recalc (in memory):", state_line(ppl2, fin3))
  # (iii) the stale conflict hold: THE RECALC only ever WRITES this key (a
  # second owner-titled row with a different override wage); with both
  # partners standing as two humans it is not re-raised, and nothing but the
  # client's answer at the gate pops it - so the repair pops it here.
  if "_owner_wage_conflict_hold" in fin3:
    P("clearing stale _owner_wage_conflict_hold:", fin3.pop("_owner_wage_conflict_hold"))
  else:
    P("_owner_wage_conflict_hold: not present, nothing to clear")
  P("AFTER hold clear (in memory):", state_line(ppl2, fin3))
  after = {"people_json": ppl2, "financials_json": fin3, "financials_year1_json": y1b, "marketing_model_json": mkt, "operating_model_json": ops}
  for c in COLS:
    d = dict_diff(before[c], after[c])
    P("diff %s: %s" % (c, "UNCHANGED" if not d else "%d change(s)" % len(d)))
    for l in d: P(l)
  changed = [c for c in COLS if before[c] != after[c]]
  P("columns that would be written:", changed)
  if WRITE:
    c = fresh_conn(); cur = c.cursor()
    sets = ", ".join("%s=%%s" % col for col in changed)
    cur.execute("UPDATE intake_consult_drafts SET " + sets + " WHERE draft_id=%s", tuple(json.dumps(after[col], ensure_ascii=False) for col in changed) + (draft_id,))
    P("UPDATE rowcount:", cur.rowcount, "columns:", changed); c.commit(); cur.close(); c.close()
    rb = q("SELECT " + ", ".join(COLS) + ", updated_at FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))[0]
    readback = {col: json.loads(rb[col] or "{}") for col in COLS}
    P("updated_at AFTER:", rb["updated_at"], "| column digests AFTER (fresh connection):", {col: sha(readback[col]) for col in COLS})
    P("AFTER (fresh-connection readback):", state_line(readback["people_json"], readback["financials_json"]))
    P("AFTER people.people rows verbatim:")
    for p in readback["people_json"].get("people") or []: P("   ", json.dumps(p, ensure_ascii=False))
    P("readback == in-memory after:", all(readback[col] == after[col] for col in COLS))
    with open(os.path.join(E, tag + "_BEFORE_touched_columns.json"), "w", encoding="utf-8") as f: json.dump(before, f, indent=1, ensure_ascii=False)
    with open(os.path.join(E, tag + "_AFTER_touched_columns.json"), "w", encoding="utf-8") as f: json.dump(readback, f, indent=1, ensure_ascii=False)
  runs_after = q("SELECT planning_run_id, run_status, created_at FROM planning_runs WHERE draft_id=%s ORDER BY created_at DESC", (draft_id,))
  P("planning_runs AFTER:", [(r["planning_run_id"][:8], r["run_status"], str(r["created_at"])[:19]) for r in runs_after], "| no new run:", len(runs_after) == len(runs_before))

with open(os.path.join(E, "r3_repair_%s.txt" % ("WRITE" if WRITE else "DRYRUN")), "w", encoding="utf-8") as f: f.write("\n".join(log) + "\n")
