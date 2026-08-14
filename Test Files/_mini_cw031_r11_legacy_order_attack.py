"""CW-031 round 11 mini audit -- adversarial attack on the D3 legacy tier
and the D1 sentence composition.

VS's judgment call (round-11 item 2): at the PURE-LEGACY tier an off-claim
row retires ALONE and the coherent remainder survives. The redproof proves
that shape with the stale row LAST in the carrying list (3d/3e). This probe
asks whether the behaviour is a LAW or an ACCIDENT OF ROW ORDER: the parse
fallback partition is created by whichever legacy row iterates FIRST
(`elif not _parts`), and that row JOINS the partition it creates even when
its own name is off-claim.

T1a stale row LAST  (VS's 3d ordering)  -> expected: stale alone, rest live
T1b stale row FIRST (same rows, reordered) -> same expectation if it is a law
T2  duplicate product name across LOBs: a stale legacy twin whose NAME is
    claimed by a fresh members-carrying group attaches and SURVIVES because
    the name set dedups -- does a stale row keep a group it never earned?
T3  D1 composition: one ambiguous + one unique figure in a single turn.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r11_legacy_order_attack.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers.intake_consult import (  # type: ignore
  _apply_per_line_cogs_patch_keys,
  _figures_all_on_file,
  _spoken_on_file_match,
)

RESULTS = []


def check(tag: str, ok: bool, detail: str = "") -> None:
  RESULTS.append(ok)
  print(f"[{'PASS' if ok else 'FAIL'}] {tag}" + (f" -- {detail}" if detail else ""))


def ops(names_rates, lob="Main"):
  return {"lob_models": [{
    "lob_name": lob,
    "products": [
      {"product_name": n, "cogs_percent_of_line_revenue": r,
       "unit_price": 100.0, "units_per_period_capacity": 10.0,
       "operating_periods_per_year": 12.0}
      for n, r in names_rates
    ],
  }]}


def prows(o, i=0):
  return o["lob_models"][i]["products"]


def legacy(row, label):
  row["cogs_cost_structure_group"] = label
  row["cogs_cost_structure_group_basis"] = "declared"


# The coherence pass runs only after a group write or separation (line
# ~3161: `if receipt["separated"] or receipt["grouped"]`), so the trigger
# is a group declaration on UNRELATED lines -- the redproof's own 3d shape.

# T1a -- pure legacy, stale row LAST (the redproof's 3d ordering).
o = ops([("A", 0.30), ("B", 0.30), ("Zed", 0.20), ("C", 0.10), ("D", 0.10)])
ra, rb, rz = prows(o)[:3]
for r in (ra, rb, rz):
  legacy(r, "shared:a+b")  # Zed was renamed after grouping: off-claim
res = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["C", "D"]]}, ops_json=o)
check("T1a stale LAST: off-claim retires alone, coherent remainder survives",
      bool(ra.get("cogs_cost_structure_group"))
      and bool(rb.get("cogs_cost_structure_group"))
      and not rz.get("cogs_cost_structure_group"),
      f"ungrouped={res.get('ungrouped')!r}")

# T1b -- SAME rows, stale row FIRST in the carrying order.
o2 = ops([("Zed", 0.20), ("A", 0.30), ("B", 0.30), ("C", 0.10), ("D", 0.10)])
rz2, ra2, rb2 = prows(o2)[:3]
for r in (rz2, ra2, rb2):
  legacy(r, "shared:a+b")
res2 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["C", "D"]]}, ops_json=o2)
check("T1b stale FIRST: same rows, same law, same outcome",
      bool(ra2.get("cogs_cost_structure_group"))
      and bool(rb2.get("cogs_cost_structure_group"))
      and not rz2.get("cogs_cost_structure_group"),
      f"ungrouped={res2.get('ungrouped')!r} "
      f"a={ra2.get('cogs_cost_structure_group')!r} "
      f"b={rb2.get('cogs_cost_structure_group')!r} "
      f"z={rz2.get('cogs_cost_structure_group')!r}")

# T2 -- duplicate product name across LOBs shadows a stale row: the fresh
# group is staged WITH members (as the door writes it), the stale twin is a
# label-only row of the SAME NAME in another LOB, and the pass is triggered
# by an unrelated declaration.
def _p(n, r):
  return {"product_name": n, "cogs_percent_of_line_revenue": r,
          "unit_price": 100.0, "units_per_period_capacity": 10.0,
          "operating_periods_per_year": 12.0}

o3 = {"lob_models": [
  {"lob_name": "Main", "products": [_p("Alpha", 0.40), _p("Beta", 0.40)]},
  {"lob_name": "Side", "products": [_p("Alpha", 0.55), _p("Gamma", 0.20),
                                    _p("Delta", 0.20)]},
]}
ma, mb = prows(o3, 0)
sa, sg, sd = prows(o3, 1)
for r in (ma, mb):
  legacy(r, "shared:alpha+beta")
  r["cogs_cost_structure_group_members"] = ["alpha", "beta"]
legacy(sa, "shared:alpha+beta")  # stale label-only twin, duplicate name
res3 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["Gamma", "Delta"]]},
  ops_json=o3)
check("T2 stale duplicate-name twin does NOT keep an unearned group",
      not sa.get("cogs_cost_structure_group"),
      f"side_a group={sa.get('cogs_cost_structure_group')!r} "
      f"main_a={ma.get('cogs_cost_structure_group')!r} "
      f"main_b={mb.get('cogs_cost_structure_group')!r} "
      f"ungrouped={res3.get('ungrouped')!r}")

# T3 -- D1 composition: ambiguous + unique in one turn.
state = {"financials": {"monthly_rent_expense": 9800.0,
                        "annual_interest_payment": 9800.0,
                        "current_revenue": 1553000.0}}
m = _figures_all_on_file(state, [9800.0, 1553000.0])
sent = ("That matches what I have - "
        + " and ".join(_spoken_on_file_match(l, v) for l, v in m[:3]) + "."
        ) if m else "(no match)"
check("T3 mixed ambiguous+unique composes honestly",
      bool(m) and m[0][0] is None and m[1][0] == "current_revenue"
      and "$9,800 on file" in sent and "current revenue is $1,553,000" in sent,
      f"sent={sent!r}")

n_fail = sum(1 for ok in RESULTS if not ok)
print("=" * 78)
print(f"{len(RESULTS)} checks, {n_fail} FAIL")
raise SystemExit(1 if n_fail else 0)
