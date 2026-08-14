"""mini, CW-031 round 10 audit — item 2: attack the match-on-file sentence.

RE-POINTED BY VS (round 11, D1/D2 fixes landed): A1 and A2 now assert the
NEW law as RED conditions — a match never names an ambiguous field (two or
more distinct leaf names matching -> leaf None, bare value spoken), and a
near-miss never claims a match (tolerance is float dust, max(0.5, 1e-9*|v|)).
The original findings this probe confirmed are in
_mini_cw031_r10_match_attack_20260813.txt; mini's R41 pins from these shapes.

A1  COINCIDENCE, mechanism: a stated figure that equals an UNRELATED stored
    leaf used to earn the match sentence NAMING the first-walked leaf. Now:
    multiple distinct names -> leaf must be None and the sentence carries
    no field claim; the match itself must still fire.
A2  TOLERANCE, mechanism: the match tolerance was max(0.5, 0.5% of value) —
    +/-7,765 at 1.5M, swallowing a correction as a confirmation. Now only
    an exact restatement (to float dust) may match.
A3  FLOOR: below-1000 figures never match (VS's stated limit — verify).
A4  CENSUS, artifact-level: on real drafts, how often do two DIFFERENT
    numeric leaves >= 1000 in financials+ops share a value? That is the
    coincidence exposure rate the 1000 floor is supposed to make rare.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r10_match_attack.py"
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers.intake_consult import (  # type: ignore
  _figures_all_on_file,
  _spoken_on_file_match,
)

bad = []
notes = []

# ---- A1: coincidence names the first-walked leaf, not the client's field ---
state = {
  "financials": {
    "monthly_rent": 3500.0,
    "current_revenue": 1553000.0,
  },
  "people": {},
  "ops": {"lob_models": [{"products": [
    {"product_name": "Plant sale", "unit_price": 3500.0},
  ]}]},
}
# Client restates their PRICE ("our plant install price is 3,500") — the walk
# hits financials.monthly_rent first.
m = _figures_all_on_file(state, [3500.0])
spoken = _spoken_on_file_match(*m[0]) if m else "(no match)"
print(f"A1 coincidence: stated 3500 (a price) -> matched leaf {m!r}")
print(f"   spoken: {spoken!r}")
if not m:
  bad.append("A1: an on-file value under two names no longer matches at all "
             "— ambiguity must drop the FIELD CLAIM, not the match")
elif m[0][0] is not None:
  bad.append(
    f"A1: two distinct leaf names match 3500 but the sentence names "
    f"{m[0][0]!r} — a match may name a field only when exactly one "
    "distinct name matches")
elif "3,500" not in spoken or " is " in spoken:
  bad.append(f"A1: ambiguous match spoken wrongly: {spoken!r} — must speak "
             "the bare value with no field claim")

# ---- A2: a 0.5%-off CORRECTION is spoken as a match ------------------------
state2 = {"financials": {"current_revenue": 1553000.0}, "ops": {}}
for stated, should_match in [
  (1553000.0, True),    # exact restatement — the designed case
  (1552999.999999999, True),  # float dust — the tolerance's only legit job
  (1548000.0, False),   # 5,000 off (0.32%) — a CORRECTION, must NOT match
  (1546000.0, False),   # 7,000 off (0.45%) — a CORRECTION, must NOT match
  (1545000.0, False),   # 8,000 off (0.52%) — outside even the old band
]:
  m2 = _figures_all_on_file(state2, [stated])
  verdictish = "MATCH" if m2 else "no match"
  print(f"A2 stated {stated:,.2f} vs stored 1,553,000 -> {verdictish}")
  if should_match and not m2:
    bad.append(f"A2: exact/dust restatement {stated!r} failed to match — "
               "the designed confirmation case is dead")
  if not should_match and m2:
    bad.append(
      f"A2: stated {stated:,.0f} (a correction, "
      f"{abs(stated-1553000):,.0f} off) is spoken as 'that matches what I "
      "have' — a correction swallowed as a confirmation")

# ---- A3: the floor holds -----------------------------------------------------
state3 = {"financials": {"cogs_pct": 45.0, "monthly_rent": 45.0}, "ops": {}}
m3 = _figures_all_on_file(state3, [45.0])
print(f"A3 sub-floor figure 45 -> {m3!r} (must be [])")
if m3:
  bad.append("A3: a sub-1000 figure earned the match sentence — floor dead")

# mixed: one big matching + one small figure kills the whole match (documented)
m3b = _figures_all_on_file(
  {"financials": {"current_revenue": 1553000.0, "seats": 45.0}, "ops": {}},
  [1553000.0, 45.0])
print(f"A3b big-match + small figure -> {m3b!r} (documented: [] — small "
      "figure kills the match, failed-change register)")

# ---- A4: census — coincidence exposure on real drafts -----------------------
from dotenv import load_dotenv  # type: ignore
load_dotenv(REPO_ROOT / ".env", override=False)
from intake_submission import get_mysql_connection  # type: ignore

FLOOR = 1000.0

def leaves_of(obj, out):
  if isinstance(obj, dict):
    for k, v in obj.items():
      if isinstance(v, bool):
        continue
      if isinstance(v, (int, float)):
        out.append((str(k), float(v)))
      else:
        leaves_of(v, out)
  elif isinstance(obj, list):
    for it in obj:
      leaves_of(it, out)

conn = get_mysql_connection()
cur = conn.cursor()
cur.execute(
  "SELECT draft_id, financials_json, operating_model_json "
  "FROM intake_consult_drafts "
  "WHERE financials_json IS NOT NULL AND financials_json != ''")
rows = cur.fetchall()
cur.close()
conn.close()

n_drafts = 0
n_exposed = 0          # drafts with >=1 cross-leaf value collision >= FLOOR
n_cross_name = 0       # collisions where the leaf NAMES differ
examples = []
for draft_id, fin, ops_j in rows:
  try:
    state_d = {"financials": json.loads(fin or "{}"),
               "ops": json.loads(ops_j or "{}") if ops_j else {}}
  except Exception:
    continue
  lv = []
  leaves_of(state_d, lv)
  big = [(k, v) for k, v in lv if v >= FLOOR]
  if not big:
    continue
  n_drafts += 1
  by_val = {}
  for k, v in big:
    by_val.setdefault(round(v, 2), set()).add(k)
  collided = {v: ks for v, ks in by_val.items() if len(ks) > 1}
  if collided:
    n_exposed += 1
    n_cross_name += 1
    if len(examples) < 8:
      v, ks = next(iter(collided.items()))
      examples.append((draft_id[:12], v, sorted(ks)[:4]))

print(f"A4 census: {n_drafts} drafts with >=1 leaf >= {FLOOR:,.0f}; "
      f"{n_exposed} ({100.0*n_exposed/max(1,n_drafts):.1f}%) carry at least "
      "one value >= 1000 stored under TWO OR MORE different leaf names")
for d, v, ks in examples:
  print(f"   e.g. {d}: {v:,.2f} under {ks}")

print("=" * 78)
for n in notes:
  print("FINDING:", n)
if bad:
  print("MATCH-ATTACK: RED (mechanism broken)")
  for b in bad:
    print("  -", b)
  raise SystemExit(1)
print("MATCH-ATTACK: mechanisms verified; findings above are judgment input")
