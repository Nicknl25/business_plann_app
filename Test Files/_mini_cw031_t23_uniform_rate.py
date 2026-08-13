"""CW-031 mini audit, tiers 2/3 -- the consequence my LIVE W3 turn exposes.

W3 ("Everything except design runs at about 55 percent for materials") wrote
0.55 to three lines through the live router. The four-line version of that
sentence is just as ordinary, and it produces four rows carrying ONE rate.

I ruled last round that distinct rates should be the DEFAULT, and VS shipped it
that way. The docstring says the all-share case "must opt out EXPLICITLY, from
the recorded grouping" -- but the code only reads spec['allow_shared_rates'],
a probe-spec key. Nobody sets probe specs mid-run, and Nick never edits
machinery. So this checks what actually happens to a client who declares one
rate for every line, and whether a STORED group covering every line rescues it.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_t23_uniform_rate.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


def ops(rates, group=None):
  products = []
  for name, rate in rates.items():
    row = {"product_name": name, "unit_price": 40.0,
           "units_per_period_capacity": 20, "utilization_rate": 1.0,
           "operating_periods_per_year": 52}
    if rate is not None:
      row["cogs_percent_of_line_revenue"] = rate
    if group:
      row["cogs_cost_structure_group"] = group
    products.append(row)
  return {"lob_models": [{"lob_name": "Garden", "products": products}]}


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from client_intake_and_finmo import issue_registry as reg  # type: ignore

  spec = {"kind": "ops_per_line_cogs", "min_lines": 2}   # #138's own probe spec
  group_spec = {"kind": "ops_cogs_shared_group"}
  cases = [
    ("four lines, four different rates (the fixed Ravenwood)",
     ops({"Plant sale": 0.48, "Hard goods sale": 0.71,
          "Install project": 0.19, "Design consult": 0.04})),
    ("the client's declared collapse: two share, two differ",
     ops({"Plant sale": 0.5793, "Hard goods sale": 0.5793,
          "Install project": 0.19, "Design consult": 0.04})),
    ("THE CLIENT SAYS ONE RATE FOR EVERY LINE (no group stored)",
     ops({"Plant sale": 0.55, "Hard goods sale": 0.55,
          "Install project": 0.55, "Design consult": 0.55})),
    ("THE SAME, with the collapse STORED on all four rows",
     ops({"Plant sale": 0.55, "Hard goods sale": 0.55,
          "Install project": 0.55, "Design consult": 0.55},
         group="shared:design consult+hard goods sale+install project+plant sale")),
  ]
  real = reg._load_ops_model
  print("=" * 78)
  print("#138's probe (ops_per_line_cogs) against four artifact shapes")
  print("=" * 78)
  try:
    for label, model in cases:
      reg._load_ops_model = lambda _c, _d, _m=model: _m  # type: ignore
      out = reg._assert_ops_per_line_cogs(None, "synthetic", dict(spec))
      grp = reg._assert_ops_cogs_shared_group(None, "synthetic", dict(group_spec))
      print(f"  {label}")
      print(f"    ops_per_line_cogs   : {out['verdict']:<15} {out['detail'][:96]}")
      print(f"    ops_cogs_shared_group: {grp['verdict']:<14} {grp['detail'][:96]}")
  finally:
    reg._load_ops_model = real  # type: ignore

  print()
  print("  READING: a client who declares one rate for every line is recorded as a")
  print("  RECURRENCE of #138 -- the false-confirmation's mirror image. The stored")
  print("  group, which is the client's own authority and IS on the rows, does not")
  print("  rescue it: the check never looks at cogs_cost_structure_group.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
