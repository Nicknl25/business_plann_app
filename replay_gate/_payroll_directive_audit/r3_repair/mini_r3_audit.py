"""mini's audit of the R3 data repair (2026-09-09, item 2). READ-ONLY: fresh-connection
readback of both live rows, THE RECALC replayed on deep copies for no-move, planning_runs,
and incoming-row provenance against the turn-79 finalize JSON and the GPT response store."""
import copy, json, os, sys, hashlib
ROOT = r"C:\dev\business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
    if p not in sys.path: sys.path.insert(0, p)
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/924bd877-ade8-4dd8-941d-a9a35bdf23fe/scratchpad")
from pd_db import q
from api_handlers.intake_consult import _sync_financials_consult_persistence_state, _merge_people_rows
E = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit")
sha = lambda o: hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:12]
names = lambda ppl: [(p.get("full_name"), p.get("role_title"), p.get("annual_wage"), p.get("wage_source")) for p in (ppl.get("people") or [])]
COLS = ["people_json", "financials_json", "financials_year1_json", "marketing_model_json", "operating_model_json"]
EXPECT = {
  "3201a64c637f47beb9f9583262874351": dict(roster=[('Ottoline Marchetti','Principal Architect and Co-Owner',155000.0,'client_override'),('Rasheed Fennimore','Design Director and Co-Owner',142000,'client_override')], rest=523000, cp=820000.0, oc=12916.67, conflict=None, fold=None, digests={'people_json':'2f1d1d7917d7','financials_json':'b61155021646','financials_year1_json':'a967eba0a690','marketing_model_json':'3efa8542935c','operating_model_json':'9fe715a3974b'}, runs=[('210a4b72','completed')]),
  "3c2224e10ddc4d8e947c73fe5a75b21a": dict(roster=[('Elena Vasquez','Co-Founder and CEO',650000.0,'client_override'),('Rajan Mehta','Co-Founder and CTO',202210.0,'client_override')], rest=51350000, cp=52202210.0, oc=54166.67, conflict=None, fold={'unapplied': 202210.0}, digests={'people_json':'74196dc08f1b','financials_json':'99bdbaefea0a','financials_year1_json':'5cc057331b8d','marketing_model_json':'6aa9ed32c6e1','operating_model_json':'4eb89d511ff0'}, runs=[]),
}
ok_all = True
def check(label, got, exp):
    global ok_all
    good = got == exp
    ok_all &= good
    print(("  OK   " if good else "  FAIL ") + label + ": " + json.dumps(got, default=str) + ("" if good else "  EXPECTED " + json.dumps(exp, default=str)))

for draft_id, X in EXPECT.items():
    print("\n=== " + draft_id)
    r = q("SELECT " + ", ".join(COLS) + ", updated_at, business_name, status FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))[0]
    cols = {c: json.loads(r[c] or "{}") for c in COLS}
    ppl, fin = cols["people_json"], cols["financials_json"]
    print("  business:", r["business_name"], "| status:", r["status"], "| updated_at:", r["updated_at"])
    check("roster", names(ppl), X["roster"])
    check("rest_of_team_payroll_year1", ppl.get("rest_of_team_payroll_year1"), X["rest"])
    check("current_payroll", fin.get("current_payroll"), X["cp"])
    check("payroll_total_year1", fin.get("payroll_total_year1"), X["cp"])
    check("baseline_payroll_year1", fin.get("baseline_payroll_year1"), X["cp"])
    check("owner_compensation", fin.get("owner_compensation"), X["oc"])
    check("_owner_wage_conflict_hold", fin.get("_owner_wage_conflict_hold"), X["conflict"])
    check("_payroll_fold_hold", fin.get("_payroll_fold_hold"), X["fold"])
    check("payroll_stated_total_target", fin.get("payroll_stated_total_target"), None)
    check("column digests (vs the AFTER digests in r3_repair_WRITE.txt)", {c: sha(cols[c]) for c in COLS}, X["digests"])
    after_file = os.path.join(E, "r3_repair", ("marchetti_3201a64c" if draft_id.startswith("3201") else "northwind_3c2224e1") + "_AFTER_touched_columns.json")
    committed = json.load(open(after_file, encoding="utf-8"))
    check("committed AFTER json == live row (5 cols)", all(committed[c] == cols[c] for c in COLS), True)
    runs = q("SELECT planning_run_id, run_status, created_at FROM planning_runs WHERE draft_id=%s ORDER BY created_at DESC", (draft_id,))
    check("planning_runs", [(x["planning_run_id"][:8], x["run_status"]) for x in runs], X["runs"])
    for x in runs: print("     run", x["planning_run_id"], x["run_status"], x["created_at"])
    fin2, y1b = _sync_financials_consult_persistence_state(
        financials_json=copy.deepcopy(fin), financials_year1_json=copy.deepcopy(cols["financials_year1_json"]),
        marketing_model_json=copy.deepcopy(cols["marketing_model_json"]), people_json=copy.deepcopy(ppl), ops_json=copy.deepcopy(cols["operating_model_json"]))
    check("recalc replay: current_payroll", fin2.get("current_payroll"), X["cp"])
    check("recalc replay: _owner_wage_conflict_hold not re-raised", fin2.get("_owner_wage_conflict_hold"), None)
    check("recalc replay: _payroll_fold_hold", fin2.get("_payroll_fold_hold"), X["fold"])
    check("recalc replay: owner_compensation", fin2.get("owner_compensation"), X["oc"])
    check("recalc replay: financials_json byte-identical", sha(fin2), sha(fin))
    if sha(fin2) != sha(fin):
        for k in sorted(set(fin) | set(fin2)):
            if fin.get(k) != fin2.get(k): print("     moved:", k, json.dumps(fin.get(k), default=str)[:100], "->", json.dumps(fin2.get(k), default=str)[:100])
    check("recalc replay: financials_year1 identical", sha(y1b), sha(cols["financials_year1_json"]))
    merged, rep = _merge_people_rows(ppl.get("people"), [dict(p) for p in ppl.get("people")])
    check("door idempotent on full roster (order kept)", names({"people": merged}), X["roster"])
    print("     guard report:", json.dumps(rep))

print("\n=== PROVENANCE")
live_m = json.loads(q("SELECT people_json FROM intake_consult_drafts WHERE draft_id=%s", ("3201a64c637f47beb9f9583262874351",))[0]["people_json"])
f79 = json.load(open(os.path.join(E, "marchetti_turn79_finalize_people.json"), encoding="utf-8"))
sub = lambda row, biz: {k: (v.replace("{{fact:business.name}}", biz) if isinstance(v, str) else v) for k, v in row.items()}
ras79 = sub([p for p in f79["people"] if p["full_name"] == "Rasheed Fennimore"][0], "Marchetti & Fen")
ras_live = [p for p in live_m["people"] if p["full_name"] == "Rasheed Fennimore"][0]
check("Rasheed live row == turn-79 finalize row (rendered)", ras_live, ras79)
ott79 = sub([p for p in f79["people"] if p["full_name"] == "Ottoline Marchetti"][0], "Marchetti & Fen")
ott_live = [p for p in live_m["people"] if p["full_name"] == "Ottoline Marchetti"][0]
print("  Ottoline live vs turn-79 finalize: identical =", ott_live == ott79, "| differing keys:", [k for k in set(ott79)|set(ott_live) if ott79.get(k) != ott_live.get(k)])
print("  turn-79 finalize order:", [p["full_name"] for p in f79["people"]], "| live order:", [p["full_name"] for p in live_m["people"]])

rows = q("SELECT input_hash, created_at, response_text FROM post_intake_gpt_response_store WHERE input_hash LIKE %s", ("63cc005b20fd%",))
print("  gpt response store 63cc005b20fd: rows =", len(rows), "| created_at =", rows[0]["created_at"] if rows else None)
def find_people(o):
    if isinstance(o, dict):
        if isinstance(o.get("people"), list) and any(isinstance(p, dict) and p.get("full_name") == "Rajan Mehta" for p in o["people"]): return o["people"]
        for v in o.values():
            f = find_people(v)
            if f: return f
    elif isinstance(o, list):
        for v in o:
            f = find_people(v)
            if f: return f
    elif isinstance(o, str) and o.lstrip().startswith("{"):
        try: return find_people(json.loads(o))
        except Exception: return None
    return None
store_people = find_people(json.loads(rows[0]["response_text"]))
print("  store finalize roster:", [(p.get("full_name"), p.get("role_title"), p.get("annual_wage"), p.get("wage_source")) for p in store_people])
live_n = json.loads(q("SELECT people_json FROM intake_consult_drafts WHERE draft_id=%s", ("3c2224e10ddc4d8e947c73fe5a75b21a",))[0]["people_json"])
el_store = sub([p for p in store_people if p["full_name"] == "Elena Vasquez"][0], "Northwind Systems, Inc.")
el_live = [p for p in live_n["people"] if p["full_name"] == "Elena Vasquez"][0]
print("  Elena live vs store: identical =", el_live == el_store, "| differing keys:", [k for k in set(el_store)|set(el_live) if el_store.get(k) != el_live.get(k)])
raj_store = sub([p for p in store_people if p["full_name"] == "Rajan Mehta"][0], "Northwind Systems, Inc.")
raj_live = [p for p in live_n["people"] if p["full_name"] == "Rajan Mehta"][0]
diffk = sorted(k for k in set(raj_store)|set(raj_live) if raj_store.get(k) != raj_live.get(k))
print("  Rajan live vs store: differing keys:", diffk, "| store values:", {k: raj_store.get(k) for k in diffk}, "| live values:", {k: raj_live.get(k) for k in diffk})
check("Rajan: only annual_wage + wage_source differ from the store row", diffk, ["annual_wage", "wage_source"])
msgs = json.loads(q("SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s", ("3c2224e10ddc4d8e947c73fe5a75b21a",))[0]["messages_json"] or "[]")
hits = [(i, m.get("role"), (m.get("content") or "")[:400].replace("\n", " ")) for i, m in enumerate(msgs) if "202,210" in (m.get("content") or "") or "202210" in (m.get("content") or "")]
print("  messages mentioning 202,210:", len(hits))
for h in hits[:8]: print("    ", h)
hits2 = [(i, m.get("role"), (m.get("content") or "")[:400].replace("\n", " ")) for i, m in enumerate(msgs) if "51.35" in (m.get("content") or "")]
print("  messages mentioning 51.35:", len(hits2))
for h in hits2[:4]: print("    ", h)
print("\nALL CHECKS PASS:", ok_all)
