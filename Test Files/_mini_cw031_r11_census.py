"""CW-031 round 11 mini audit -- reach census for the two D3 attack shapes.

C1 duplicate product names across LOBs (T2's precondition), and among those,
   how many also carry a shared: group label anywhere.
C2 pure-legacy group labels (rows carrying cogs_cost_structure_group with NO
   cogs_cost_structure_group_members list) -- T1b's precondition -- and
   whether any has an off-claim carrying row (name not in the parsed label).

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r11_census.py"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from dotenv import load_dotenv  # type: ignore
load_dotenv(REPO_ROOT / ".env", override=False)

from intake_submission import get_mysql_connection  # type: ignore

conn = get_mysql_connection()
cur = conn.cursor()
cur.execute(
  "SELECT draft_id, operating_model_json FROM intake_consult_drafts "
  "WHERE operating_model_json IS NOT NULL AND operating_model_json != ''")
rows = cur.fetchall()

n_ops = 0
dup_names = []           # drafts with a duplicate product name across LOBs
dup_and_grouped = []     # ... that also carry any shared: label
legacy_rows = []         # (draft, label) rows with label but no members list
legacy_offclaim = []     # legacy labels with an off-claim carrying row
for draft_id, om in rows:
  try:
    o = json.loads(om)
  except Exception:
    continue
  lobs = (o or {}).get("lob_models") or []
  if not isinstance(lobs, list) or not lobs:
    continue
  n_ops += 1
  names = []
  by_label = {}
  any_group = False
  for lob in lobs:
    for p in (lob or {}).get("products") or []:
      if not isinstance(p, dict):
        continue
      nm = str(p.get("product_name") or "").strip().lower()
      if nm:
        names.append(nm)
      lbl = str(p.get("cogs_cost_structure_group") or "").strip()
      if lbl.startswith("shared:"):
        any_group = True
        m = p.get("cogs_cost_structure_group_members")
        has_members = isinstance(m, list) and bool(m)
        by_label.setdefault(lbl, []).append((nm, has_members))
  if len(names) != len(set(names)):
    dup_names.append(draft_id)
    if any_group:
      dup_and_grouped.append(draft_id)
  for lbl, carrying in by_label.items():
    legacy_only = [c for c in carrying if not c[1]]
    if legacy_only:
      legacy_rows.append((draft_id, lbl))
      parsed = {t for t in lbl[len("shared:"):].split("+") if t}
      off = [nm for nm, hm in legacy_only if nm not in parsed]
      if off:
        legacy_offclaim.append((draft_id, lbl, off))

print(f"drafts with an ops model: {n_ops}")
print(f"C1 duplicate product names across LOBs: {len(dup_names)}")
for d in dup_names[:10]:
  print(f"   {d}")
print(f"C1b ...that also carry a shared: group label: {len(dup_and_grouped)}")
for d in dup_and_grouped[:10]:
  print(f"   {d}")
print(f"C2 rows with a group label and NO member list (legacy): "
      f"{len(legacy_rows)} label-instances")
for d, l in legacy_rows[:10]:
  print(f"   {d} {l!r}")
print(f"C2b legacy labels with an OFF-CLAIM carrying row: {len(legacy_offclaim)}")
for d, l, off in legacy_offclaim[:10]:
  print(f"   {d} {l!r} off={off!r}")
