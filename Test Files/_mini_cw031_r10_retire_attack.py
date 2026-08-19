"""mini, CW-031 round 10 audit — item 3: the disagreeing-claims retire,
adversarially, plus the W5 scope question.

O1  LABEL COLLISION: two DIFFERENT member sets can produce the SAME label
    when product names contain '+' with no surrounding spaces
    ('A+B','C' vs 'A','B+C' both label "shared:a+b+c"). If both groups are
    declared, the pass sees one label with disagreeing member lists and
    retires ALL rows — two healthy client-declared groups killed.
O2  MIXED LEGACY: a fresh members-carrying declaration sharing its label
    with a stale legacy label-only row — does the retire kill the fresh
    declaration along with the stale row?
O3  POSITIVE: legacy fallback cannot false-retire a members-carrying group
    (VS's claim: fallback only engages when NO carrying row has a list).
    Mixed case where membership AGREES: one row with list, one without,
    names match the list — must survive.
O4  ORDINARY SEQUENCES: partial regroup and overlapping re-declarations
    (the ways a real client talks) — can any produce one label with
    disagreeing member lists? (The door writes label+members atomically to
    all members per call, so this should be unreachable without collision.)
W5b Where does annual_wage live? (the live W5 match came from somewhere —
    find the leaf the scan walked.)

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r10_retire_attack.py"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers.intake_consult import (  # type: ignore
  _apply_per_line_cogs_patch_keys,
  _build_per_line_cogs_receipt_text,
)


def ops(names_rates):
  return {"lob_models": [{
    "lob_name": "Main",
    "products": [
      {"product_name": n, "cogs_percent_of_line_revenue": r,
       "unit_price": 100.0, "units_per_period_capacity": 10.0,
       "operating_periods_per_year": 12.0}
      for n, r in names_rates
    ],
  }]}


def prows(o):
  return o["lob_models"][0]["products"]


def show(tag, o, receipt=None):
  print(tag, [(p.get("product_name"), p.get("cogs_cost_structure_group"),
               p.get("cogs_cost_structure_group_members"))
              for p in prows(o)],
        ("| ungrouped: " + repr(receipt.get("ungrouped"))) if receipt else "")


findings = []

# ---- O1: label collision ----------------------------------------------------
# Four distinct products whose two 2-member groups join to the same label.
o1 = ops([("A+B", 0.30), ("C", 0.30), ("A", 0.50), ("B+C", 0.50)])
r1a = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["A+B", "C"]]}, ops_json=o1)
show("O1 after group1 {A+B, C}:", o1, r1a)
r1b = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["A", "B+C"]]}, ops_json=o1)
show("O1 after group2 {A, B+C}:", o1, r1b)
g = [p.get("cogs_cost_structure_group") for p in prows(o1)]
if not all(g):
  findings.append(
    f"O1 CONFIRMED: label collision — declaring {{A, B+C}} retired rows from "
    f"the disjoint healthy group {{A+B, C}} (groups now {g!r}, "
    f"ungrouped {r1b.get('ungrouped')!r})")
else:
  print("O1: both collided-label groups survive (labels equal, member lists "
        "disagree — check how)")
  labels = {p.get("cogs_cost_structure_group") for p in prows(o1)}
  print("O1 labels:", labels)

# ---- O2: mixed legacy — fresh declaration + stale label-only twin ----------
o2 = ops([("Alpha", 0.40), ("Beta", 0.40), ("Gamma", 0.20)])
a2, b2, g2 = prows(o2)
# Gamma was RENAMED after an old label-only grouping stamped it (the only
# path to a same-label legacy row): it wears "shared:alpha+beta" label-only.
g2["cogs_cost_structure_group"] = "shared:alpha+beta"
g2["cogs_cost_structure_group_basis"] = "declared"
r2 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["Alpha", "Beta"]]}, ops_json=o2)
show("O2 fresh {Alpha,Beta} + stale label-only Gamma:", o2, r2)
if not (a2.get("cogs_cost_structure_group")
        and b2.get("cogs_cost_structure_group")):
  findings.append(
    "O2 CONFIRMED: a stale legacy label-only row sharing the label killed "
    f"the FRESH declaration in its own call (ungrouped {r2.get('ungrouped')!r})")
elif g2.get("cogs_cost_structure_group"):
  findings.append("O2: the stale legacy row survived (retire lost its tooth)")
else:
  print("O2: fresh declaration survived, stale twin retired — correct")

# ---- O3: agreeing mixed membership must survive ----------------------------
o3 = ops([("Plum", 0.30), ("Pear", 0.30)])
p3, q3 = prows(o3)
for row in (p3, q3):
  row["cogs_cost_structure_group"] = "shared:pear+plum"
  row["cogs_cost_structure_group_basis"] = "declared"
p3["cogs_cost_structure_group_members"] = ["pear", "plum"]  # q3 legacy-shaped
r3 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_per_line": [
    {"line_name": "Plum", "cogs_percent": 0.31, "unit": "ratio"}]},
  ops_json=o3)
show("O3 agreeing mixed (one list, one legacy):", o3, r3)
if not (p3.get("cogs_cost_structure_group") and q3.get("cogs_cost_structure_group")):
  findings.append(
    "O3: an AGREEING mixed group (one row with list, one legacy) was "
    f"retired — false retire (ungrouped {r3.get('ungrouped')!r})")

# ---- O4: ordinary sequences -------------------------------------------------
o4 = ops([("P1", 0.30), ("P2", 0.30), ("P3", 0.30), ("P4", 0.10)])
_apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["P1", "P2", "P3"]]}, ops_json=o4)
r4 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["P1", "P2"]]}, ops_json=o4)
show("O4 regroup {P1,P2} out of {P1,P2,P3}:", o4, r4)
rows4 = prows(o4)
if rows4[2].get("cogs_cost_structure_group"):
  findings.append("O4: P3 kept a stale label after the regroup")
sets4 = {}
for row in rows4:
  lbl = row.get("cogs_cost_structure_group")
  if lbl:
    sets4.setdefault(lbl, []).append(
      tuple(row.get("cogs_cost_structure_group_members") or ()))
for lbl, ms in sets4.items():
  if len(set(ms)) > 1:
    findings.append(f"O4: ordinary regroup produced disagreeing lists on "
                    f"{lbl!r}: {ms!r}")

# overlapping redeclaration: {P2,P3,P4} over existing {P1,P2}
r4b = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["P2", "P3", "P4"]]}, ops_json=o4)
show("O4b overlap {P2,P3,P4} over {P1,P2}:", o4, r4b)
rows4b = prows(o4)
if rows4b[0].get("cogs_cost_structure_group"):
  print("O4b note: P1 still wears", rows4b[0].get("cogs_cost_structure_group"),
        "members", rows4b[0].get("cogs_cost_structure_group_members"))
  if (rows4b[0].get("cogs_cost_structure_group") or "").startswith("shared:") \
     and rows4b[0].get("cogs_cost_structure_group_members"):
    ms0 = rows4b[0]["cogs_cost_structure_group_members"]
    if "p2" in [m.lower() for m in ms0]:
      findings.append(
        "O4b: P1 left claiming membership with P2, which has moved on — a "
        "one-row group wearing a two-member claim (retire should have fired)")

# ---- W5b: where does annual_wage live? -------------------------------------
from dotenv import load_dotenv  # type: ignore
load_dotenv(REPO_ROOT / ".env", override=False)
from intake_submission import get_mysql_connection  # type: ignore
conn = get_mysql_connection()
cur = conn.cursor()
cur.execute("SELECT financials_json, operating_model_json FROM "
            "intake_consult_drafts WHERE draft_id=%s",
            ("1070c6a560a04f3d971019a3787180bf",))
fin_j, ops_j = cur.fetchone()
cur.close()
conn.close()

def paths_with(obj, needle, path=""):
  hits = []
  if isinstance(obj, dict):
    for k, v in obj.items():
      if isinstance(v, (int, float)) and not isinstance(v, bool) \
         and abs(float(v) - needle) < 0.5:
        hits.append(f"{path}{k}={v}")
      else:
        hits.extend(paths_with(v, needle, f"{path}{k}."))
  elif isinstance(obj, list):
    for i, it in enumerate(obj):
      hits.extend(paths_with(it, needle, f"{path}{i}."))
  return hits

print("W5b 96000 in financials_json:", paths_with(json.loads(fin_j or "{}"), 96000.0))
print("W5b 96000 in operating_model_json:",
      paths_with(json.loads(ops_j or "{}"), 96000.0))

print("=" * 78)
if findings:
  print("RETIRE-ATTACK FINDINGS:")
  for f in findings:
    print("  -", f)
  raise SystemExit(1)
print("RETIRE-ATTACK: clean — no reachable false retire found")
