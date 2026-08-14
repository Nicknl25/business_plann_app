"""CW-031 round 12 mini audit -- adversarial attack on VS's two judgment
calls and the two honest edges VS flagged.

Item 2b (the any-row guard): VS broadened my rule from "a name already
present on a MEMBERS-CARRYING row" to "already present on ANY row". The
question: is there a LEGITIMATE attach the broader guard now refuses?
G1/G2/G7 hunt for it: the only attaches the broader rule additionally
refuses are same-named twin #2 behind twin #1 (legacy or mixed), and a
frozenset key cannot claim one name twice, so a second same-named row can
never be homed by any claim -- refusing it is the law, not a loss.

Item 3 (the residual order edge): two same-named legacy rows competing for
one on-claim slot. G3 measures BOTH orderings and also shows why refusing
both would be WORSE: the partition's surviving name set would lose the
name and the whole coherent group -- including innocent bystanders --
would retire, violating retire-only-failing-claims.

Item 4 (the empty parse partition): G4/G5 drive every-row-off-claim and
the degenerate "shared:" label through the pass; the empty container must
retire nothing extra, crash nothing, and the receipt must name exactly
the stale rows.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r12_guard_attack.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers.intake_consult import (  # type: ignore
  _apply_per_line_cogs_patch_keys,
)

RESULTS = []


def check(tag: str, ok: bool, detail: str = "") -> None:
  RESULTS.append(ok)
  print(f"[{'PASS' if ok else 'FAIL'}] {tag}" + (f" -- {detail}" if detail else ""))


def _p(n, r):
  return {"product_name": n, "cogs_percent_of_line_revenue": r,
          "unit_price": 100.0, "units_per_period_capacity": 10.0,
          "operating_periods_per_year": 12.0}


def ops(names_rates, lob="Main"):
  return {"lob_models": [{"lob_name": lob,
                          "products": [_p(n, r) for n, r in names_rates]}]}


def prows(o, i=0):
  return o["lob_models"][i]["products"]


def legacy(row, label):
  row["cogs_cost_structure_group"] = label
  row["cogs_cost_structure_group_basis"] = "declared"


TRIGGER = {"financials.cogs_shared_structure_groups": [["C", "D"]]}

# G1 -- THE LEGITIMATE ATTACH THE GUARD MUST NOT REFUSE: R40's
# agreeing-mixed shape. A members-carrying alpha row plus a label-only
# legacy beta row under one label; beta's name is in the key and NOT on
# any row already in the partition, so it attaches and the group survives.
o = ops([("Alpha", 0.40), ("Beta", 0.40), ("C", 0.10), ("D", 0.10)])
ra, rb = prows(o)[:2]
legacy(ra, "shared:alpha+beta")
ra["cogs_cost_structure_group_members"] = ["alpha", "beta"]
legacy(rb, "shared:alpha+beta")  # label-only legacy, name on-claim, no twin
res = _apply_per_line_cogs_patch_keys(TRIGGER, ops_json=o)
check("G1 agreeing mixed attach still lands (guard refuses no legitimate attach)",
      bool(ra.get("cogs_cost_structure_group"))
      and bool(rb.get("cogs_cost_structure_group"))
      and not res.get("ungrouped"),
      f"ungrouped={res.get('ungrouped')!r}")

# G2 -- pure-legacy coherent pair, different names: both attach, survives.
o2 = ops([("Alpha", 0.40), ("Beta", 0.40), ("C", 0.10), ("D", 0.10)])
ra2, rb2 = prows(o2)[:2]
legacy(ra2, "shared:alpha+beta")
legacy(rb2, "shared:alpha+beta")
res2 = _apply_per_line_cogs_patch_keys(TRIGGER, ops_json=o2)
check("G2 pure-legacy coherent group survives an unrelated write",
      bool(ra2.get("cogs_cost_structure_group"))
      and bool(rb2.get("cogs_cost_structure_group"))
      and not res2.get("ungrouped"),
      f"ungrouped={res2.get('ungrouped')!r}")

# G3 -- the residual order edge, BOTH orderings: two same-named legacy
# rows, one on-claim slot. Partition-level outcome must be order-free
# (one twin retires, the coherent remainder survives). This is also the
# proof that refusing BOTH twins would over-retire: the surviving name
# set would drop 'alpha' and beta's healthy claim would die with it.
for tag, order in (("first", [("Alpha", 0.40), ("Alpha", 0.55), ("Beta", 0.40)]),
                   ("last", [("Alpha", 0.55), ("Beta", 0.40), ("Alpha", 0.40)])):
  o3 = ops(order + [("C", 0.10), ("D", 0.10)])
  twins = [r for r in prows(o3) if r["product_name"] == "Alpha"]
  rbeta = next(r for r in prows(o3) if r["product_name"] == "Beta")
  for r in twins + [rbeta]:
    legacy(r, "shared:alpha+beta")
  res3 = _apply_per_line_cogs_patch_keys(TRIGGER, ops_json=o3)
  kept = [bool(r.get("cogs_cost_structure_group")) for r in twins]
  check(f"G3 same-name twins (dup {tag}): exactly one twin keeps, beta survives",
        kept.count(True) == 1
        and bool(rbeta.get("cogs_cost_structure_group"))
        and len(res3.get("ungrouped") or []) == 1,
        f"kept={kept!r} beta={rbeta.get('cogs_cost_structure_group')!r} "
        f"ungrouped={res3.get('ungrouped')!r}")

# G4 -- every legacy row off-claim: the pre-created parse partition ends
# empty. All rows must go stale (named in the receipt), nothing extra,
# no crash.
o4 = ops([("Xray", 0.40), ("Yankee", 0.40), ("C", 0.10), ("D", 0.10)])
rx, ry = prows(o4)[:2]
legacy(rx, "shared:alpha+beta")  # both renamed after grouping
legacy(ry, "shared:alpha+beta")
res4 = _apply_per_line_cogs_patch_keys(TRIGGER, ops_json=o4)
check("G4 all-off-claim label: both retire, empty partition rides nothing",
      not rx.get("cogs_cost_structure_group")
      and not ry.get("cogs_cost_structure_group")
      and sorted(res4.get("ungrouped") or []) == ["Main / Xray", "Main / Yankee"],
      f"ungrouped={res4.get('ungrouped')!r}")

# G5 -- degenerate label "shared:" (empty membership): the parse key is
# the empty frozenset; no row can sit in it, the row goes stale, no crash.
o5 = ops([("Alpha", 0.40), ("C", 0.10), ("D", 0.10)])
ra5 = prows(o5)[0]
legacy(ra5, "shared:")
res5 = _apply_per_line_cogs_patch_keys(TRIGGER, ops_json=o5)
check("G5 degenerate 'shared:' label retires cleanly, no crash",
      not ra5.get("cogs_cost_structure_group")
      and "Main / Alpha" in (res5.get("ungrouped") or []),
      f"ungrouped={res5.get('ungrouped')!r}")

# G7 -- twin #2 behind a LEGITIMATE legacy attach (the exact case VS's
# broadening exists for, in the mixed tier): members alpha row, legacy
# beta attaches, then a SECOND legacy beta is refused and retires alone;
# the group survives intact.
o7 = {"lob_models": [
  {"lob_name": "Main", "products": [_p("Alpha", 0.40), _p("Beta", 0.40)]},
  {"lob_name": "Side", "products": [_p("Beta", 0.55), _p("C", 0.10),
                                    _p("D", 0.10)]},
]}
ma, mb = prows(o7, 0)
sb = prows(o7, 1)[0]
legacy(ma, "shared:alpha+beta")
ma["cogs_cost_structure_group_members"] = ["alpha", "beta"]
legacy(mb, "shared:alpha+beta")   # legitimate legacy attach
legacy(sb, "shared:alpha+beta")   # twin #2, other LOB, same name
res7 = _apply_per_line_cogs_patch_keys(TRIGGER, ops_json=o7)
check("G7 twin #2 behind a legacy attach: refused alone, group intact",
      bool(ma.get("cogs_cost_structure_group"))
      and bool(mb.get("cogs_cost_structure_group"))
      and not sb.get("cogs_cost_structure_group")
      and (res7.get("ungrouped") or []) == ["Side / Beta"],
      f"ungrouped={res7.get('ungrouped')!r} "
      f"mb={mb.get('cogs_cost_structure_group')!r} "
      f"sb={sb.get('cogs_cost_structure_group')!r}")

n_fail = sum(1 for ok in RESULTS if not ok)
print("=" * 78)
print(f"{len(RESULTS)} checks, {n_fail} FAIL")
raise SystemExit(1 if n_fail else 0)
