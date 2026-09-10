"""mini's audit of the R3b cleanup (2026-09-09, item 3). READ-ONLY, fresh connection.
(a) zero rows for every deleted key across every table carrying draft_id / planning_run_id
    (derived from information_schema here, not from VS's list) + checkpoint 158c4962;
    then a TEXT-COLUMN scan of EVERY table (varchar/char/text/json) for the deleted ids,
    the run id, the checkpoint ids, '17-55-55' and the FAILED DRAFT docx name;
(b) live guards on my own digests vs my R3 audit (mini_r3_audit.txt) + run/checkpoints/
    delivery 61/bundle/issue 571/STAY drafts + the shadow-one-second-before claim;
(c) residual zero-turn census for today; client_id vs0f49e2fe673343c99f anywhere."""
import os, sys, json, hashlib, time, re
ROOT = r"C:\dev\business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
    if p not in sys.path: sys.path.insert(0, p)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))
from intake_submission import get_mysql_connection
E = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit", "r3b_cleanup")
SNAP = os.path.join(ROOT, "_r3b_cleanup_snapshots")
c = get_mysql_connection()
try: c.autocommit = True
except Exception: pass
def q(sql, args=()):
    cur = c.cursor(dictionary=True); cur.execute(sql, args); rows = cur.fetchall(); cur.close(); return rows
sha12 = lambda o: hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:12]
OK = [0, 0]
def check(label, good, detail=""):
    OK[0 if good else 1] += 1
    print(("  OK   " if good else "  FAIL ") + label + ("  " + str(detail) if detail != "" else ""))

db = q("SELECT DATABASE() d")[0]["d"]
print("mini R3b audit", time.strftime("%Y-%m-%dT%H:%M:%S"), "db=" + db)
txt = open(os.path.join(E, "deleted_paths_and_rows.txt"), encoding="utf-8").read()
ids = re.findall(r"^([0-9a-f]{32})", txt.split("DRAFT IDS DELETED")[1], re.M)
SCRATCH_RUN = re.search(r"run ([0-9a-f]{32})", txt).group(1)
check("22 draft ids parsed from deleted_paths_and_rows.txt", len(ids) == 22, len(ids))
ck = json.load(open(os.path.join(SNAP, "db", "scratch_b9b1be21__planning_run_checkpoints.json"), encoding="utf-8"))
ck_ids = [str(r.get("checkpoint_id")) for r in ck]
CK158 = [x for x in ck_ids if x.startswith("158c4962")]
check("checkpoint 158c4962 present in snapshot (7 checkpoint ids)", len(ck) == 7 and len(CK158) == 1, ck_ids)

# ---- (a) keyed sweep, my own table list ----
cols = q("SELECT TABLE_NAME t, COLUMN_NAME c, DATA_TYPE d FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s", (db,))
by = {}
for r in cols: by.setdefault(r["t"], {})[r["c"]] = r["d"]
swept = sorted(t for t, cs in by.items() if "draft_id" in cs or "planning_run_id" in cs)
print("\n(a) KEYED SWEEP - tables carrying draft_id or planning_run_id:", len(swept))
vs_list = "intake_consult_drafts, intake_financials_drafts, intake_people_capability_drafts, intake_sim_runs, intake_target_market_drafts, issue_occurrences, issue_resolution_events, planning_run_checkpoints, planning_runs, planning_stage_events, post_intake_cohort_bands, post_intake_fitted_bands, post_intake_handler_traces, post_intake_restructuring_log, post_intake_run_diagnostics, run_vitals_events, run_vitals_gpt_calls, run_vitals_runs, run_vitals_turns, supervisor_actions, workbook_deliveries, writing_phase_brief_log, writing_phase_bundle, writing_phase_fact_misses, writing_phase_leaf_orphans, writing_phase_section_corpus".split(", ")
check("my sweep list == VS's 26-table list", swept == sorted(vs_list), sorted(set(swept) ^ set(vs_list)))
resid = 0
for t in swept:
    parts, args = [], []
    if "draft_id" in by[t]: parts.append("draft_id IN (%s)" % ",".join(["%s"] * len(ids))); args += ids
    if "planning_run_id" in by[t]: parts.append("planning_run_id=%s"); args.append(SCRATCH_RUN)
    n = q(f"SELECT COUNT(*) n FROM `{t}` WHERE " + " OR ".join(parts), args)[0]["n"]
    if n: print("   RESIDUAL", t, n)
    resid += n
check("residual keyed rows for 22 drafts + run across %d tables" % len(swept), resid == 0, resid)
n = q("SELECT COUNT(*) n FROM planning_run_checkpoints WHERE checkpoint_id IN (%s)" % ",".join(["%s"] * len(ck_ids)), ck_ids)[0]["n"]
check("planning_run_checkpoints rows for the 7 snapshot checkpoint ids (incl 158c4962)", n == 0, n)
cres = 0
for t, cs in sorted(by.items()):
    if "client_id" in cs:
        n = q(f"SELECT COUNT(*) n FROM `{t}` WHERE client_id=%s", ("vs0f49e2fe673343c99f",))[0]["n"]
        if n: print("   client_id vs0f49e2fe673343c99f residual in", t, n); cres += n
check("client_id vs0f49e2fe673343c99f residual across every client_id table", cres == 0, cres)

# ---- (a2) text-column scan of every APP table (JSON/text columns) ----
# Scope: app tables (the sweep tables + any table whose name says intake/planning/post_intake/
# run_vitals/writing_phase/workbook/issue/supervisor/persona/gpt), NOT the bulk reference data
# (sec_edgar_facts, cbp_*, oews_*, sba_*...) which is loaded from government files and can never
# name a draft. Every deleted id was minted today (13:03 or later), so a row that was neither
# created nor updated today cannot name one: the giant tables (checkpoints 11 GB, drafts 7 GB,
# stage_events 4.5 GB) are read on their today-slice via created_at/updated_at; small tables
# are scanned whole. ONE query per table with every token OR-ed (one pass, not 32).
print("\n(a2) TEXT-COLUMN SCAN of app tables for the deleted ids / run / checkpoints / '17-55-55' / FAILED DRAFT docx")
TEXT = {"varchar", "char", "text", "tinytext", "mediumtext", "longtext", "json"}
tokens = ids + [SCRATCH_RUN] + ck_ids + ["17-55-55", "FAILED DRAFT (CLAUDE v2)"]
APP = re.compile(r"intake|planning|post_intake|run_vitals|writing_phase|workbook|issue|supervisor|persona|gpt|cowork|handoff|delivery|email", re.I)
app_tables = sorted(t for t in by if t in swept or APP.search(t))
print("   app tables in scope:", len(app_tables), "-", ", ".join(app_tables))
hits = []
t0 = time.time(); scanned = 0
for t in app_tables:
    cs = by[t]
    tcols = [cn for cn, d in cs.items() if d in TEXT]
    if not tcols: continue
    try:
        nrows = q(f"SELECT COUNT(*) n FROM `{t}`")[0]["n"]
    except Exception as exc:
        print("   SKIP", t, exc); continue
    if not nrows: continue
    scanned += 1
    likes = " OR ".join(f"`{cn}` LIKE %s" for cn in tcols for _ in tokens)
    args = ["%" + tok + "%" for cn in tcols for tok in tokens]
    slice_cols = [cn for cn in ("created_at", "updated_at", "started_at", "ts", "timestamp") if cn in cs]
    where = "(" + likes + ")"
    if nrows > 2000 and slice_cols:
        where = "(" + " OR ".join(f"`{cn}` >= '2026-09-09 00:00:00'" for cn in slice_cols) + ") AND " + where
        scope = "today-slice on " + "/".join(slice_cols)
    else:
        scope = "whole table"
    t1 = time.time()
    n = q(f"SELECT COUNT(*) n FROM `{t}` WHERE " + where, args)[0]["n"]
    print("   %-40s rows=%-8d %-40s hits=%d  (%.1fs)" % (t, nrows, scope, n, time.time() - t1))
    if n:
        pk = [cn for cn in cs if cn in ("id", "draft_id", "planning_run_id", "input_hash", "issue_id", "created_at", "event_type", "run_id")]
        sel = ", ".join("`" + p + "`" for p in pk) if pk else "*"
        rows = q(f"SELECT {sel} FROM `{t}` WHERE " + where, args)[:8]
        for r in rows:
            # name the token(s) the row carries
            full = q(f"SELECT * FROM `{t}` WHERE " + where + (" AND `id`=%s" if "id" in cs and "id" in r else ""), args + ([r["id"]] if "id" in cs and "id" in r else []))[:1]
            blob = json.dumps(full, default=str) if full else ""
            toks = [tok for tok in tokens if tok in blob]
            hits.append((t, r, toks))
            print("      HIT", {k: (str(v)[:48]) for k, v in r.items()}, "tokens:", [x[:12] for x in toks])
print("   scanned %d non-empty app tables in %.1fs" % (scanned, time.time() - t0))
check("no app table (JSON/text columns included) still names a deleted id / run / checkpoint / scratch file", not hits, len(hits))

# ---- (b) live guards ----
print("\n(b) LIVE GUARDS (my digests, R3-audit basis)")
COLS = ["people_json", "financials_json", "financials_year1_json", "marketing_model_json", "operating_model_json"]
EXP = {"3201a64c637f47beb9f9583262874351": {'people_json':'2f1d1d7917d7','financials_json':'b61155021646','financials_year1_json':'a967eba0a690','marketing_model_json':'3efa8542935c','operating_model_json':'9fe715a3974b'},
       "3c2224e10ddc4d8e947c73fe5a75b21a": {'people_json':'74196dc08f1b','financials_json':'99bdbaefea0a','financials_year1_json':'5cc057331b8d','marketing_model_json':'6aa9ed32c6e1','operating_model_json':'4eb89d511ff0'}}
for did, exp in EXP.items():
    r = q("SELECT " + ", ".join(COLS) + ", updated_at, status, business_name, planning_run_id FROM intake_consult_drafts WHERE draft_id=%s", (did,))
    check(f"{did[:8]} row present", len(r) == 1)
    r = r[0]
    got = {cn: sha12(json.loads(r[cn] or "{}")) for cn in COLS}
    check(f"{did[:8]} 5-column digests == my R3 audit", got == exp, got if got != exp else str(r["business_name"]) + " updated_at=" + str(r["updated_at"]))
    fin = json.loads(r["financials_json"] or "{}"); ppl = json.loads(r["people_json"] or "{}")
    print("      roster:", [(p.get("full_name"), p.get("annual_wage")) for p in ppl.get("people") or []], "current_payroll:", fin.get("current_payroll"), "rest:", ppl.get("rest_of_team_payroll_year1"), "conflict_hold:", fin.get("_owner_wage_conflict_hold"), "fold_hold:", fin.get("_payroll_fold_hold"), "planning_run_id:", r["planning_run_id"])
LIVE_DRAFT = "3201a64c637f47beb9f9583262874351"; LIVE_RUN = "210a4b7209024b05b4397269a452dae7"
runs = q("SELECT planning_run_id, run_status, created_at, completed_at FROM planning_runs WHERE draft_id=%s ORDER BY created_at", (LIVE_DRAFT,))
check("Marchetti planning_runs = [210a4b72 completed] only", [(x["planning_run_id"][:8], x["run_status"]) for x in runs] == [("210a4b72", "completed")], runs)
ckl = q("SELECT COUNT(*) n, MIN(created_at) a, MAX(created_at) b FROM planning_run_checkpoints WHERE planning_run_id=%s", (LIVE_RUN,))[0]
check("run 210a4b72 checkpoints present", ckl["n"] > 0, ckl)
nw = q("SELECT planning_run_id, run_status FROM planning_runs WHERE draft_id=%s", ("3c2224e10ddc4d8e947c73fe5a75b21a",))
check("Northwind planning_runs none", nw == [], nw)
wd = q("SELECT id, draft_id, planning_run_id, delivered_at FROM workbook_deliveries WHERE draft_id=%s ORDER BY id", (LIVE_DRAFT,))
check("workbook_deliveries for 3201a64c = row 61 only", [x["id"] for x in wd] == [61], wd)
wd64 = q("SELECT COUNT(*) n FROM workbook_deliveries WHERE id=64")[0]["n"]
check("workbook_deliveries row 64 gone", wd64 == 0, wd64)
wb = q("SELECT draft_id, planning_run_id, bundle_version, LENGTH(bundle_json) lb, LENGTH(v1_json) lv1, created_at FROM writing_phase_bundle WHERE planning_run_id=%s", (LIVE_RUN,))
check("writing_phase_bundle live row: 1 row, bundle_version 2, v1_json present", len(wb) == 1 and str(wb[0]["bundle_version"]) == "2" and (wb[0]["lv1"] or 0) > 0 and (wb[0]["lb"] or 0) > 0, wb)
wbn = q("SELECT COUNT(*) n FROM writing_phase_bundle WHERE draft_id LIKE %s", ("b9b1be21%",))[0]["n"]
check("writing_phase_bundle scratch row gone", wbn == 0, wbn)
io = q("SELECT id, issue_id, draft_id, created_at FROM issue_occurrences WHERE issue_id=571 ORDER BY id")
check("issue 571 occurrences 710/711 still present on fc61585d", [x["id"] for x in io] == [710, 711] and all(str(x["draft_id"]).startswith("fc61585d") for x in io), io)
if "issues" in by:
    icols = [cn for cn in ("issue_id", "status", "severity", "signature", "title", "occurrence_count", "resolved_detected_at") if cn in by["issues"]]
    print("      issue 571:", q("SELECT " + ", ".join(icols) + " FROM issues WHERE issue_id=571"))
stay = ["fc61585d", "8da24f38", "583c6fa5", "bb793dbb", "176d4279", "482b870f", "1b7eeb63", "aa3ee853", "f2ed3d01"]
srows = q("SELECT draft_id, client_id, created_at, JSON_LENGTH(messages_json) m, planning_run_id FROM intake_consult_drafts WHERE " + " OR ".join(["draft_id LIKE %s"] * len(stay)), [s + "%" for s in stay])
check("9 STAY drafts present", len(srows) == 9, len(srows))
for x in sorted(srows, key=lambda r: r["created_at"]): print("      STAY", x["draft_id"][:8], x["client_id"], x["created_at"], "msgs=", x["m"], "run=", (x["planning_run_id"] or "")[:8])
shadow = json.load(open(os.path.join(SNAP, "db", "zero_turn_bypass_check_api_probe__intake_consult_drafts.json"), encoding="utf-8"))
one_sec = True
for s in shadow:
    nxt = q("SELECT draft_id, client_id, created_at FROM intake_consult_drafts WHERE created_at >= %s AND draft_id<>%s ORDER BY created_at LIMIT 1", (s["created_at"], s["draft_id"]))
    print("      shadow", s["draft_id"][:8], s["client_id"], s["created_at"], "msgs=", (len(json.loads(s["messages_json"])) if s.get("messages_json") else 0), "-> next draft", nxt[0]["draft_id"][:8] if nxt else None, nxt[0]["client_id"] if nxt else None, str(nxt[0]["created_at"]) if nxt else None)
    one_sec &= bool(nxt) and nxt[0]["draft_id"][:8] in ("bb793dbb", "482b870f", "1b7eeb63")
check("each shadow is followed by its canary draft (bb793dbb / 482b870f / 1b7eeb63)", one_sec)
for cls in ("zero_turn_rgate_surface_fresh_draft", "zero_turn_rp26_redproof_cw026_forward_move"):
    rows = json.load(open(os.path.join(SNAP, "db", cls + "__intake_consult_drafts.json"), encoding="utf-8"))
    pref = "rgate" if "rgate" in cls else "rp26"
    check(f"{cls}: {len(rows)} rows, every client_id starts with {pref}, msgs 0, no run", all(str(r["client_id"]).startswith(pref) and not r.get("planning_run_id") and (not r.get("messages_json") or json.loads(r["messages_json"]) == []) for r in rows))
for f in ("zero_turn_rgate_surface_fresh_draft__run_vitals_runs.json", "zero_turn_rgate_surface_fresh_draft__run_vitals_events.json"):
    rows = json.load(open(os.path.join(SNAP, "db", f), encoding="utf-8"))
    for r in rows: print("      watcher-noise", f.split("__")[1][:-5], {k: str(r.get(k))[:70] for k in ("id", "draft_id", "event_type", "transcript_path") if k in r})

# ---- (c) residual zero-turn census today ----
print("\n(c) RESIDUAL zero-turn drafts created today (msgs 0, no run)")
z = q("SELECT draft_id, client_id, business_name, created_at FROM intake_consult_drafts WHERE DATE(created_at)=%s AND (messages_json IS NULL OR JSON_LENGTH(messages_json)=0) AND planning_run_id IS NULL ORDER BY created_at", ("2026-09-09",))
for x in z: print("      ", x["draft_id"][:8], x["client_id"], x["business_name"], x["created_at"])
print("   count:", len(z))
print("   intake_consult_drafts total rows now:", q("SELECT COUNT(*) n FROM intake_consult_drafts")[0]["n"])
print("\nRESULT: %d OK, %d FAIL" % tuple(OK))
c.close()
