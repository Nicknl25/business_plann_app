"""mini, CW-031 round 9 audit, item 2 (offline half): the group-coherence
pass must never retire a group the client still holds.

The pass keys on product-name sets ENCODED IN THE LABEL (shared:a+b+c,
parsed by split('+')). Attacks:

  O1  Two disjoint declared groups; separate one member of ONE. The other
      group must survive byte-identical (deep compare, not just label).
  O2  THE '+' TRAP: a product named 'Design + Build' encodes into a label
      whose split('+') no longer reproduces the membership, so the pass
      should retire the group the client JUST declared, in the same call.
      This probe measures whether that is real.
  O3  Loose-name subset rows ('Install' and 'Install project' both real
      rows): group both, separate 'Install' -- the right row must clear and
      the survivor must be retired BY NAME, with the third row untouched.
  O4  Case drift: a product name whose stored case differs from the label
      casing must not cause a false retire.

Pure-Python: calls _apply_per_line_cogs_patch_keys directly on synthetic
directories -- this is the pass's own logic, no router in the loop.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r9_coherence_attack.py"
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers.intake_consult import _apply_per_line_cogs_patch_keys  # type: ignore


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


def rows(o):
  return [(p.get("product_name"), p.get("cogs_percent_of_line_revenue"),
           p.get("cogs_cost_structure_group"),
           p.get("cogs_cost_structure_group_basis"))
          for p in o["lob_models"][0]["products"]]


bad = []

# ---- O1: disjoint groups, separate one member of one -----------------------
o = ops([("Plant sale", 0.55), ("Hard goods sale", 0.55),
         ("Install project", 0.20), ("Design consult", 0.20)])
r = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [
    ["Plant sale", "Hard goods sale"], ["Install project", "Design consult"]]},
  ops_json=o)
print("O1 after two groups :", rows(o))
g2_before = copy.deepcopy(
  [p for p in o["lob_models"][0]["products"]
   if p["product_name"] in ("Install project", "Design consult")])
r = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_separate_lines": ["Plant sale"]}, ops_json=o)
print("O1 after separation :", rows(o), "| ungrouped:", r["ungrouped"])
g2_after = [p for p in o["lob_models"][0]["products"]
            if p["product_name"] in ("Install project", "Design consult")]
if g2_after != g2_before:
  bad.append(f"O1: the OTHER group changed ({g2_before} -> {g2_after})")
plant = o["lob_models"][0]["products"][0]
hard = o["lob_models"][0]["products"][1]
if plant.get("cogs_cost_structure_group") or hard.get("cogs_cost_structure_group"):
  bad.append("O1: separated group not fully cleared")
if "Main / Hard goods sale" not in r["ungrouped"] and "Hard goods sale" not in str(r["ungrouped"]):
  bad.append(f"O1: survivor not named in ungrouped ({r['ungrouped']})")

# ---- O2: the '+' trap ------------------------------------------------------
o = ops([("Design + Build", 0.30), ("Plant sale", 0.30), ("Hard goods", 0.60)])
r = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["Design + Build", "Plant sale"]]},
  ops_json=o)
print("O2 after declaring  :", rows(o), "| ungrouped:", r["ungrouped"],
      "| grouped:", [g["group"] for g in r["grouped"]])
db = o["lob_models"][0]["products"][0]
ps = o["lob_models"][0]["products"][1]
if not (db.get("cogs_cost_structure_group") and ps.get("cogs_cost_structure_group")):
  bad.append("O2 REAL: the '+'-named group was retired in the same call that "
             f"declared it (ungrouped={r['ungrouped']})")

# ---- O3: loose-name subset rows -------------------------------------------
o = ops([("Install", 0.40), ("Install project", 0.40), ("Design consult", 0.10)])
r = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["Install", "Install project"]]},
  ops_json=o)
print("O3 after group      :", rows(o))
gi = [p.get("cogs_cost_structure_group") for p in o["lob_models"][0]["products"]]
if not (gi[0] and gi[1] and gi[0] == gi[1] and not gi[2]):
  bad.append(f"O3: subset-named group stored wrong ({gi})")
r = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_separate_lines": ["Install"]}, ops_json=o)
print("O3 after separation :", rows(o), "| separated:", r["separated"],
      "| ungrouped:", r["ungrouped"])
p0, p1, p2 = o["lob_models"][0]["products"]
if p0.get("cogs_cost_structure_group"):
  bad.append("O3: 'Install' separation cleared the wrong row or none")
if p1.get("cogs_cost_structure_group"):
  bad.append("O3: survivor 'Install project' kept a label whose membership is gone")
if p2.get("cogs_cost_structure_group"):
  bad.append("O3: untouched third row gained a label")

# ---- O4: case drift --------------------------------------------------------
o = ops([("PLANT Sale", 0.55), ("hard GOODS sale", 0.55), ("Design consult", 0.10)])
r = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["PLANT Sale", "hard GOODS sale"]]},
  ops_json=o)
print("O4 after group      :", rows(o), "| ungrouped:", r["ungrouped"])
g4 = [p.get("cogs_cost_structure_group") for p in o["lob_models"][0]["products"]]
if not (g4[0] and g4[1]):
  bad.append(f"O4: mixed-case group retired on declaration ({g4}, "
             f"ungrouped={r['ungrouped']})")

print("=" * 78)
if bad:
  print("COHERENCE-ATTACK RESULT: RED")
  for b in bad:
    print(f"  - {b}")
  raise SystemExit(1)
print("COHERENCE-ATTACK RESULT: CLEAN (no healthy group retired)")
