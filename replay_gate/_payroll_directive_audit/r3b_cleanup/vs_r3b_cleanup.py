"""R3b CLEANUP (VS, 2026-09-09, item 3 of Nick's payroll rulings - Delete the artifacts).
Snapshots EVERY row and file it will remove into an UNTRACKED folder
(C:\\dev\\business_plann_app\\_r3b_cleanup_snapshots\\), guards the live Marchetti
artifacts by digest before and after, and deletes ONLY with --delete.
Doctrine (the sweep): every table in the DB that carries a draft_id or
planning_run_id column is swept for rows keyed to the scratch ids; the
response store (keyed by input_hash only) and supervisor_actions (no row)
carry nothing keyed to them. No code, no legs, no system run, no
writing-phase trigger, email path untouched (no email record row exists).
"""
import sys, os, json, hashlib, shutil, datetime, io
ROOT = r"C:\dev\business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path: sys.path.insert(0, p)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))
from intake_submission import get_mysql_connection

DELETE = "--delete" in sys.argv
E = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit", "r3b_cleanup")
SNAP = os.path.join(ROOT, "_r3b_cleanup_snapshots")
os.makedirs(os.path.join(SNAP, "db"), exist_ok=True); os.makedirs(os.path.join(SNAP, "files"), exist_ok=True)
LOG = io.StringIO()
def say(*a, sep=" "):
  s = sep.join(str(x) for x in a); print(s); LOG.write(s + "\n")

def conn():
  c = get_mysql_connection()
  try: c.autocommit = True
  except Exception: pass
  return c
def q(c, sql, args=()):
  cur = c.cursor(dictionary=True); cur.execute(sql, args); rows = cur.fetchall(); cur.close(); return rows
def x(c, sql, args=()):
  cur = c.cursor(); cur.execute(sql, args); n = cur.rowcount; cur.close(); c.commit(); return n
def sha(o):
  return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:16]
def fsha(p):
  with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()[:16]

# ---------------- targets ----------------
SCRATCH_DRAFT = "b9b1be210ae641c3aaa50302a26ac7c7"
SCRATCH_RUN = "7457d04b7f844b0fae61a7d8dc1f87d1"
SCRATCH_CLIENT = "vs0f49e2fe673343c99f"
LIVE_DRAFT = "3201a64c637f47beb9f9583262874351"
LIVE_RUN = "210a4b7209024b05b4397269a452dae7"

ZERO_TURN = {
  # creator: replay_gate/surface.py fresh_draft (client_id rgate+hex8) - Turn A gate legs 17:56 / 18:12
  "rgate_surface_fresh_draft": ["962ec5eb5407452eb8e999ba208a78f4", "5252fbad66264b4da743e1a78a7132f4",
                                "26ec0bd274434efb824e0aeed444d1aa", "0b8e7f54df1043f083ea4692338f1654"],
  # creator: Test Files/_redproof_cw026_forward_move.py create_draft (client_id rp26+hex8) - Turn B pins 18:53
  "rp26_redproof_cw026_forward_move": ["50b5fcf4fd8647c2a9a03311555e2a37", "67ab71107dda4b9d89e2a5ddc38cb1a3",
                                       "7cf4e87b12764e90b5cbbfc1fed58256", "859ecddaaa9942688743aa48b69ca770",
                                       "b83f0fa9cbdf43f0b021e5536c64d280", "c14c65eaf22343e9b55e455f96494958",
                                       "c3ce1423b5584a9eb2eea3c6c9d39bba", "080aafe4a1e844ee92c010379f2793ad",
                                       "395b5498663046bf92130cc5c5320a98", "983fc784d7464bd2a4217785d88c50e2",
                                       "cc61cebe19e844e39bbd0ef4ceb81dcf", "f3988bbf2b324e3c854129a96918611d",
                                       "9ba4f50497f74a12b08c5de8ccb8b429", "60594c10453a47629a33701501bb350e"],
  # creator: Test Files/run_intake_bypass.py _check_api - POST /api/intake-consult/session readiness probe,
  # mints a throwaway draft one second before each bypass canary draft (bb793dbb 13:03:21, 482b870f 16:48:01, 1b7eeb63 17:05:30)
  "bypass_check_api_probe": ["0972f98d134341128a1bbfb39471085c", "d06a9f3e18054188afe023d6ebbebc12", "efac5b2559894b719d62db59c0f24808"],
}
STAY = {
  "cowork_persona_start_attempts_issue_571": ["fc61585db30f4d7c8ea1fdb9ed4f7929", "8da24f3818e948c1b203ceecccab28d8", "583c6fa511734edd9c3515846702c886"],
  "bypass_canary_drafts_not_named": ["bb793dbbd2cb448683efeb98fad7f582", "176d4279", "482b870fcf9f4d549aadc27b2096844f", "1b7eeb634dac41cc97bae22db0ae5fbf"],
  "turn_b_live_smoke_not_named": ["aa3ee8535f3b4403b7e7748b8d6efd5e", "f2ed3d019d6a44ca9c6c7254c8fc472c"],
}

V2 = r"C:\dev\Client Written Plans\_v2_runs\marchetti_fen"
ONEDRIVE_FM = r"C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\Business Plan Generator Sources\Client Plans\Financial Models"
FILES = [
  r"C:\dev\Cilient Plans\Marchetti Fen -- 09-09-2026 17-55-55.xlsx",
  os.path.join(ONEDRIVE_FM, "Marchetti Fen -- 09-09-2026 17-55-55.xlsx"),
  os.path.join(V2, "Marchetti & Fen -- FAILED DRAFT (CLAUDE v2).docx"),
  os.path.join(V2, "Marchetti & Fen -- FAILED DRAFT (CLAUDE v2).docx.render_report.json"),
] + [os.path.join(V2, n) for n in (
  "marchetti_fen_bundle_v1.json", "marchetti_fen_bundle_v2.json", "marchetti_fen_qa_report.json", "marchetti_fen_render_data.json",
  "marchetti_fen_claude_plan.json", "marchetti_fen_claude_raw.json", "marchetti_fen_claude_plan_edited.json",
  "marchetti_fen_claude_raw_edited.json", "marchetti_fen_claude_plan_final.json")]
CHARTS = os.path.join(V2, "charts_claude")
FILES += sorted(os.path.join(CHARTS, n) for n in os.listdir(CHARTS)) if os.path.isdir(CHARTS) else []
AUTO_LOG = os.path.join(V2, "auto_run.log")
LIVE_FILES = [
  r"C:\dev\Cilient Plans\Marchetti Fen -- 09-09-2026 15-44-39.xlsx",
  os.path.join(ONEDRIVE_FM, "Marchetti Fen -- 09-09-2026 15-44-39.xlsx"),
  r"C:\dev\Client Written Plans\Marchetti & Fen -- Business Plan (CLAUDE v2, edited).docx",
  r"C:\dev\Client Written Plans\Marchetti & Fen -- Business Plan (CLAUDE v2, edited).docx.render_report.json",
]

c = conn()
db = q(c, "SELECT DATABASE() d")[0]["d"]
say("R3b CLEANUP", "DELETE" if DELETE else "DRY RUN", datetime.datetime.now().isoformat(timespec="seconds"), "db=" + db)

# ---------------- live guards (before) ----------------
def live_digests(cc):
  d = {}
  d["draft_3201a64c"] = sha(q(cc, "SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (LIVE_DRAFT,)))
  d["run_210a4b72"] = sha(q(cc, "SELECT * FROM planning_runs WHERE planning_run_id=%s", (LIVE_RUN,)))
  d["checkpoints_210a4b72"] = sha(q(cc, "SELECT checkpoint_id FROM planning_run_checkpoints WHERE planning_run_id=%s ORDER BY checkpoint_id", (LIVE_RUN,)))
  d["workbook_deliveries_61"] = sha(q(cc, "SELECT * FROM workbook_deliveries WHERE draft_id=%s", (LIVE_DRAFT,)))
  d["writing_phase_bundle_live"] = sha(q(cc, "SELECT * FROM writing_phase_bundle WHERE planning_run_id=%s", (LIVE_RUN,)))
  d["northwind_3c2224e1"] = sha(q(cc, "SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", ("3c2224e1%",)))
  for k, grp in STAY.items():
    for did in grp: d["stay_" + did[:8]] = sha(q(cc, "SELECT draft_id, updated_at, JSON_LENGTH(messages_json) m FROM intake_consult_drafts WHERE draft_id LIKE %s", (did[:8] + "%",)))
  for p in LIVE_FILES: d[p] = fsha(p) if os.path.exists(p) else "MISSING"
  d["issue_occurrences_571"] = sha(q(cc, "SELECT id FROM issue_occurrences WHERE issue_id=571 ORDER BY id"))
  return d
before = live_digests(c)
say("LIVE GUARD BEFORE:")
for k, v in before.items(): say("  ", k, v)

# ---------------- the sweep ----------------
cols = q(c, "SELECT TABLE_NAME t, COLUMN_NAME c FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s", (db,))
by = {}
for r in cols: by.setdefault(r["t"], set()).add(r["c"])
swept = sorted(t for t, cs in by.items() if "draft_id" in cs or "planning_run_id" in cs)
say("SWEEP TABLES (carry draft_id or planning_run_id):", len(swept)); say("  ", ", ".join(swept))

def keyed_where(t, draft_ids, run_ids):
  cs = by[t]; parts = []; args = []
  if "draft_id" in cs and draft_ids: parts.append("draft_id IN (%s)" % ",".join(["%s"] * len(draft_ids))); args += draft_ids
  if "planning_run_id" in cs and run_ids: parts.append("planning_run_id IN (%s)" % ",".join(["%s"] * len(run_ids))); args += run_ids
  return (" OR ".join(parts), args) if parts else (None, None)

plan = []  # (table, where, args, rows)
def collect(label, draft_ids, run_ids):
  total = 0
  for t in swept:
    w, a = keyed_where(t, draft_ids, run_ids)
    if not w: continue
    rows = q(c, f"SELECT * FROM `{t}` WHERE {w}", a)
    if rows:
      plan.append((t, w, a, rows)); total += len(rows)
      fn = os.path.join(SNAP, "db", f"{label}__{t}.json")
      with open(fn, "w", encoding="utf-8") as f: json.dump(rows, f, default=str, ensure_ascii=False, indent=1)
      say(f"  {label}: {t} = {len(rows)} rows -> snapshot {os.path.relpath(fn, ROOT)}")
  return total

say("SCRATCH DRAFT/RUN rows keyed to", SCRATCH_DRAFT, SCRATCH_RUN)
n_scratch = collect("scratch_b9b1be21", [SCRATCH_DRAFT], [SCRATCH_RUN])
for t, cs in sorted(by.items()):
  if "client_id" in cs and t not in swept:
    n = q(c, f"SELECT COUNT(*) n FROM `{t}` WHERE client_id=%s", (SCRATCH_CLIENT,))[0]["n"]
    if n: say(f"  NOTE client_id-only table {t} carries {n} rows for {SCRATCH_CLIENT} (NOT in sweep)")
say("  response store rows mentioning the scratch ids:", q(c, "SELECT COUNT(*) n FROM post_intake_gpt_response_store WHERE response_text LIKE %s OR response_text LIKE %s", ("%" + SCRATCH_DRAFT + "%", "%" + SCRATCH_RUN + "%"))[0]["n"], "(store is keyed by input_hash; no draft/run column)")
say("  supervisor_actions rows keyed to scratch:", q(c, "SELECT COUNT(*) n FROM supervisor_actions WHERE draft_id=%s OR planning_run_id=%s", (SCRATCH_DRAFT, SCRATCH_RUN))[0]["n"])
say("  TOTAL scratch rows:", n_scratch)

say("ZERO-TURN SCRATCH DRAFTS")
n_zero = 0; zero_ids = []
for cls, ids in ZERO_TURN.items():
  for did in ids:
    row = q(c, "SELECT draft_id, client_id, business_name, created_at, planning_run_id, JSON_LENGTH(messages_json) msgs FROM intake_consult_drafts WHERE draft_id=%s", (did,))
    assert len(row) == 1, ("missing", did)
    r = row[0]
    assert r["msgs"] in (0, None) and r["planning_run_id"] is None, ("NOT zero-turn", r)
    if cls.startswith("rgate"): assert r["client_id"].startswith("rgate"), r
    elif cls.startswith("rp26"): assert r["client_id"].startswith("rp26"), r
    else: assert r["business_name"] is None and len(r["client_id"]) == 18, r
    say(f"  [{cls}] {r['draft_id']} client_id={r['client_id']} biz={r['business_name']} created={r['created_at']} msgs={r['msgs']} run={r['planning_run_id']}")
    zero_ids.append(did)
  n_zero += collect("zero_turn_" + cls, ids, [])
say("  TOTAL zero-turn rows (drafts + keyed rows):", n_zero)
for k, grp in STAY.items(): say("  STAY [" + k + "]:", ", ".join(grp))

# ---------------- files ----------------
say("FILES")
file_plan = []
for p in FILES:
  if os.path.exists(p):
    rel = p.replace(":", "").replace("\\", "/").replace("//", "/").lstrip("/")
    dst = os.path.join(SNAP, "files", rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(p, dst); file_plan.append((p, os.path.getsize(p), fsha(p), dst))
    say(f"  DEL {p} ({os.path.getsize(p)} bytes sha {fsha(p)}) -> snapshot")
  else:
    say(f"  ABSENT {p}")
with open(AUTO_LOG, encoding="utf-8") as f: log_lines = f.read().split("\n")
hdr = [i for i, ln in enumerate(log_lines) if ln.startswith("=== auto-trigger " + SCRATCH_DRAFT)]
assert len(hdr) == 1, hdr
keep = log_lines[:hdr[0]]
assert any(ln.startswith("=== auto-trigger " + LIVE_DRAFT) for ln in keep)
dst = os.path.join(SNAP, "files", "auto_run.log.FULL"); shutil.copy2(AUTO_LOG, dst)
say(f"  TRIM {AUTO_LOG}: {len(log_lines)} lines -> keep {len(keep)} (live block), drop {len(log_lines) - len(keep)} (scratch block from line {hdr[0] + 1}); full copy -> snapshot")
say("  KEEP live:", *LIVE_FILES, sep="\n    ")

if not DELETE:
  say("DRY RUN complete - nothing deleted. Re-run with --delete.")
  open(os.path.join(E, "r3b_cleanup_DRYRUN.txt"), "w", encoding="utf-8").write(LOG.getvalue()); sys.exit(0)

# ---------------- delete ----------------
say("DELETING DB ROWS (children first, drafts last)")
order = {"intake_consult_drafts": 9, "planning_runs": 8}
deleted = []
for t, w, a, rows in sorted(plan, key=lambda p: order.get(p[0], 0)):
  n = x(c, f"DELETE FROM `{t}` WHERE {w}", a)
  assert n == len(rows), (t, n, len(rows))
  deleted.append((t, n)); say(f"  {t}: deleted {n} (= snapshot {len(rows)})")
say("DELETING FILES")
deleted_paths = []
for p, size, h, dst in file_plan:
  os.remove(p); assert not os.path.exists(p); deleted_paths.append(p); say(f"  deleted {p}")
with open(AUTO_LOG, "w", encoding="utf-8", newline="") as f: f.write("\n".join(keep))
say(f"  rewrote {AUTO_LOG} with the live block only ({len(keep)} lines)")
if os.path.isdir(CHARTS) and not os.listdir(CHARTS):
  os.rmdir(CHARTS); deleted_paths.append(CHARTS + os.sep); say(f"  removed emptied dir {CHARTS}")

# ---------------- readback on a fresh connection ----------------
c.close(); c2 = conn()
say("READBACK (fresh connection)")
bad = 0
for t in swept:
  w, a = keyed_where(t, [SCRATCH_DRAFT] + zero_ids, [SCRATCH_RUN])
  if not w: continue
  n = q(c2, f"SELECT COUNT(*) n FROM `{t}` WHERE {w}", a)[0]["n"]
  if n: bad += n; say(f"  RESIDUAL {t}: {n}")
say("  residual rows for every deleted key across the sweep:", bad)
for p in FILES: assert not os.path.exists(p), p
say("  all listed files absent:", True)
after = live_digests(c2)
say("LIVE GUARD AFTER:")
for k, v in after.items(): say("  ", k, v, "OK" if before[k] == v else "MOVED!")
assert before == after, "LIVE ARTIFACT MOVED"
say("LIVE GUARD: all", len(after), "digests equal before/after")
say("DELETED PATHS:")
for p in deleted_paths: say("  ", p)
say("DELETED ROWS:")
for t, n in deleted: say(f"   {t}: {n}")
say("SNAPSHOT:", SNAP, "(untracked)")
open(os.path.join(E, "r3b_cleanup_DELETE.txt"), "w", encoding="utf-8").write(LOG.getvalue())
with open(os.path.join(E, "deleted_paths_and_rows.txt"), "w", encoding="utf-8") as f:
  f.write("FILES DELETED\n" + "\n".join(deleted_paths) + "\n\nDB ROWS DELETED (table: count)\n" + "\n".join(f"{t}: {n}" for t, n in deleted) + "\n")
  f.write("\nDRAFT IDS DELETED\n" + SCRATCH_DRAFT + " (scratch, run " + SCRATCH_RUN + ")\n" + "\n".join(zero_ids) + "\n")
