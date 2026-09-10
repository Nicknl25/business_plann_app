"""Turn 18 neighbor check (VS, 2026-09-10): what the canonicalizer would do
to EVERY stored roster - read-only, deep copies, nothing written.

Per draft: rows that carry a raw-shape key (aliased), rows with no identity
after aliasing (would DROP), healed echoes that would fold (healed), and the
bare owner-titled rows without a name (the Sumac F5 class - must survive).
The merge is the real helper on (stored_rows, []) - the shape of the next
people write on that draft.
"""
import copy, json, os, re, sys, datetime
ROOT = r"C:\dev\business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path: sys.path.insert(0, p)
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/8a0ab62f-278e-4bdb-9881-0fea4d8ebc67/scratchpad")
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))
from pd_db import q
from api_handlers.intake_consult import (
  _merge_people_rows, _canonicalize_person_row, _person_row_identity, _OWNER_TITLE_RE,
)

rows = q("SELECT draft_id, business_name, created_at, people_json FROM intake_consult_drafts")
print(f"=== turn 18 census at {datetime.datetime.now().isoformat(timespec='seconds')}: drafts={len(rows)}")
tot = dict(drafts_with_people=0, rows=0, aliased=0, would_drop=0, healed=0, bare_owner_rows=0,
           drafts_bare_owner=0, drafts_touched=0, drafts_row_count_changed=0)
touched, bare_list = [], []
for r in rows:
  try:
    ppl = json.loads(r["people_json"] or "{}") or {}
  except Exception:
    continue
  people = [p for p in (ppl.get("people") or []) if isinstance(p, dict)]
  if not people:
    continue
  tot["drafts_with_people"] += 1
  tot["rows"] += len(people)
  bare = [p for p in people
          if _OWNER_TITLE_RE.search(str(p.get("role_title") or "")) and not str(p.get("full_name") or "").strip()]
  if bare:
    tot["bare_owner_rows"] += len(bare)
    tot["drafts_bare_owner"] += 1
    bare_list.append((r["draft_id"][:8], r["business_name"]))
  merged, rep = _merge_people_rows(copy.deepcopy(people), [])
  n_alias, n_drop, n_heal = len(rep["aliased"]), len(rep["dropped"]), len(rep["healed"])
  tot["aliased"] += n_alias; tot["would_drop"] += n_drop; tot["healed"] += n_heal
  if n_alias or n_drop or n_heal:
    tot["drafts_touched"] += 1
    touched.append((r["draft_id"][:8], r["business_name"], str(r["created_at"])[:16],
                    dict(rows=len(people), after=len(merged), aliased=rep["aliased"],
                         dropped=rep["dropped"], healed=rep["healed"])))
  if len(merged) != len(people):
    tot["drafts_row_count_changed"] += 1
  # the bare owner rows must all survive the merge
  bare_after = [p for p in merged
                if _OWNER_TITLE_RE.search(str(p.get("role_title") or "")) and not str(p.get("full_name") or "").strip()]
  assert len(bare_after) == len(bare), (r["draft_id"], len(bare), len(bare_after))
  # rows that were canonical must be byte-equal after the merge
  if not (n_alias or n_drop or n_heal):
    assert merged == people, r["draft_id"]
print("totals:", json.dumps(tot))
print(f"drafts with a nameless owner-titled row (F5 class): {tot['drafts_bare_owner']} - every one survives the merge (asserted)")
for d in bare_list[:8]:
  print("   ", d)
if len(bare_list) > 8:
  print("    ...", len(bare_list) - 8, "more")
print(f"drafts the canonicalizer would touch on their next people write: {tot['drafts_touched']}")
for t in touched:
  print("   ", t)
print("every untouched draft merged byte-equal to its stored rows (asserted)")
