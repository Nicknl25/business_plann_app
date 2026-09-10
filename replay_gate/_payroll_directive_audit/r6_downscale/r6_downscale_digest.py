"""Item 6 byte-equal proof (VS, 2026-09-09): run the anchor on the
Marchetti-shaped test roster with a DOWN-SCALE stated pool (100,000 against
an authored Q1 pool of 189,801.60), an UP-SCALE pool (523,000) and the two
band edges, and digest the returned rows + stamp. Run at HEAD before the
edit (--label before) and after (--label after); the digests must match.
Pure function, no DB, writes only the evidence json."""
import copy, hashlib, json, os, sys, io, logging, datetime, subprocess
ROOT = r"C:\dev\business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path: sys.path.insert(0, p)
from client_intake_and_finmo.post_intake_headcount import schedule as S

LABEL = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else "before"
OUT = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit", "r6_downscale")
os.makedirs(OUT, exist_ok=True)

def _row(q, title, start, hires, end, wage):
  return {"quarter_index": q, "oews_occ_title": title, "staffing_class": "supporting_staff",
          "starting_fte": start, "hires": hires, "ending_fte": end, "annual_wage": wage}

ROWS = [
  _row(1, "Architectural and Civil Drafters", 0.0, 2.0, 2.0, 60000),
  _row(1, "Office and Administrative Support Workers", 0.0, 1.32, 1.32, 52880),
  _row(2, "Architectural and Civil Drafters", 2.0, 0.5, 2.5, 60000),
  _row(2, "Office and Administrative Support Workers", 1.32, 0.0, 1.32, 52880),
]
Q1_POOL = 2.0 * 60000 + 1.32 * 52880  # 189,801.60
CASES = {
  "downscale_100000": 100000.0,
  "upscale_523000": 523000.0,
  "band_edge_below_0.996": round(Q1_POOL * 0.996, 2),
  "band_edge_above_1.004": round(Q1_POOL * 1.004, 2),
  "downscale_just_outside_band_0.99": round(Q1_POOL * 0.99, 2),
}
head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
res = {"label": LABEL, "git_head": head, "at": datetime.datetime.now().isoformat(timespec="seconds"),
       "q1_pool_authored": round(Q1_POOL, 2), "cases": {}}
for name, pool in CASES.items():
  buf = io.StringIO(); h = logging.StreamHandler(buf); h.setLevel(logging.INFO)
  lg = logging.getLogger(S.__name__); lg.addHandler(h); old = lg.level; lg.setLevel(logging.INFO)
  try:
    rows, anchor = S._anchor_supporting_rows_to_stated_pool(
      copy.deepcopy(ROWS), people_json={"rest_of_team_payroll_year1": pool})
  finally:
    lg.removeHandler(h); lg.setLevel(old)
  blob = json.dumps({"rows": rows, "anchor": anchor}, sort_keys=True, separators=(",", ":"))
  res["cases"][name] = {
    "stated_pool": pool,
    "digest_rows_and_stamp": hashlib.sha256(blob.encode()).hexdigest()[:16],
    "rows": rows, "anchor": anchor,
    "log_lines": [l for l in buf.getvalue().splitlines() if "REST_OF_TEAM_ANCHOR" in l],
  }
  print(f"{name:34s} pool={pool:>12.2f} digest={res['cases'][name]['digest_rows_and_stamp']} "
        f"applied={anchor.get('applied') if anchor else None} factor={anchor.get('factor') if anchor else None}")
  for l in res["cases"][name]["log_lines"]:
    print("   LOG:", l)
path = os.path.join(OUT, f"downscale_digest_{LABEL}.json")
with open(path, "w", encoding="utf-8") as fh:
  json.dump(res, fh, indent=1, sort_keys=True)
print("wrote", path, "at", head)
