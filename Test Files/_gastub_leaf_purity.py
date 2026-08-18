# -*- coding: utf-8 -*-
"""G&A stub fix - LEAF PURITY on Millgate (2e198cbf): rebuild model_input +
finmo through the production builder on a tree, dump; then diff two dumps
leaf by leaf and classify every moved leaf as G&A-stub-or-descendant.

    python "Test Files/_gastub_leaf_purity.py" --dump <dir>          # per tree
    python "Test Files/_gastub_leaf_purity.py" --diff <old> <new>
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "python"))

# Q0 (stub column) leaves that legitimately move when the Q0 G&A ratio moves:
# the ratio row itself, Q0 G&A dollars, and its arithmetic descendants at Q0
# (EBITDA -> pre-tax -> taxes -> NI -> RE / equity / cash / plug).
DESCENDANT_KEYS = {
  "g_and_a", "general_and_administrative", "ebitda", "taxes", "net_income",
  "retained_earnings", "equity", "total_equity", "cash", "ending_cash",
  "beginning_cash", "current_assets", "total_assets",
  "total_liabilities_and_equity", "operating_cash_flow", "net_cash_flow",
  "accounting_equation_check", "other_equity", "owners_capital",
}


def dump(out_dir):
  import _redproof_ga_stub_denominator as rp  # noqa: E402
  from client_intake_and_finmo import finmo_bridge as fb
  from client_intake_and_finmo.intake_submission import get_mysql_connection
  fb._load_root_env()
  conn = get_mysql_connection()
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s LIMIT 1", (rp.DRAFT_PREFIX + "%",))
  row = cur.fetchone()
  mij, finmo, _fin, _ops, _y1 = rp.build(row)
  os.makedirs(out_dir, exist_ok=True)
  for name, payload in (("model_input", mij), ("finmo", finmo)):
    with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as fh:
      json.dump(payload, fh, sort_keys=True, indent=1, default=str)
  print("dumped ->", out_dir)


def _leaves(node, prefix, acc):
  if isinstance(node, dict):
    for k in sorted(node):
      _leaves(node[k], f"{prefix}.{k}" if prefix else str(k), acc)
  elif isinstance(node, list):
    for i, v in enumerate(node):
      _leaves(v, f"{prefix}[{i}]", acc)
  else:
    acc[prefix] = node


DESCENDANT_LABELS = {
  "General & Administrative", "EBITDA", "Taxes", "Net Income", "Pre-Tax Income",
  "Retained Earnings", "Cash", "Total Equity", "Total Assets", "Equity",
  "Total Liabilities & Equity", "Operating Cash Flow", "Net Cash Flow",
  "Ending Cash", "Beginning Cash",
}


def classify(path, old, new, model_input_ga_row_prefix, mirror_labels):
  # model_input: the G&A row's values[0]
  if model_input_ga_row_prefix and path == f"{model_input_ga_row_prefix}.values[0]":
    return "GA_STUB_CELL"
  # finmo: quarter_rows[0].<descendant>
  if path.startswith("quarter_rows[0]."):
    key = path.split(".", 1)[1]
    if key in DESCENDANT_KEYS:
      return "Q0_DESCENDANT"
  # finmo statement mirrors (pl[i]/cash_flow[i]/balance_sheet[i]) at Q0 =
  # values[0]; classify by the row label
  import re as _re
  m = _re.match(r"^(pl|cash_flow|balance_sheet|income_statement)\[(\d+)\]\.values\[0\]$", path)
  if m:
    label = mirror_labels.get((m.group(1), int(m.group(2))))
    if label in DESCENDANT_LABELS:
      return f"Q0_MIRROR({m.group(1)}:{label})"
  return "OTHER"


def diff(old_dir, new_dir):
  rc = 0
  for name in ("model_input", "finmo"):
    with open(os.path.join(old_dir, f"{name}.json"), encoding="utf-8") as fh:
      old = json.load(fh)
    with open(os.path.join(new_dir, f"{name}.json"), encoding="utf-8") as fh:
      new = json.load(fh)
    a, b = {}, {}
    _leaves(old, "", a)
    _leaves(new, "", b)
    ga_prefix = None
    if name == "model_input":
      for i, r in enumerate((new.get("sections") or {}).get("expenses") or []):
        if isinstance(r, dict) and r.get("label") == "General & Administrative":
          ga_prefix = f"sections.expenses[{i}]"
    mirror_labels = {}
    for sec in ("pl", "cash_flow", "balance_sheet", "income_statement"):
      for i, r in enumerate(new.get(sec) or []):
        if isinstance(r, dict):
          mirror_labels[(sec, i)] = str(r.get("label") or r.get("name") or "")
    changed = [k for k in a if k in b and a[k] != b[k]]
    added = [k for k in b if k not in a]
    removed = [k for k in a if k not in b]
    print(f"== {name}: {len(a)} leaves; changed {len(changed)} added {len(added)} removed {len(removed)}")
    tally = {}
    for k in changed:
      cls = classify(k, a[k], b[k], ga_prefix, mirror_labels)
      tally[cls] = tally.get(cls, 0) + 1
      print(f"   [{cls}] {k}: {a[k]} -> {b[k]}")
    for k in added:
      print(f"   [ADDED] {k}: {b[k]}")
    for k in removed:
      print(f"   [REMOVED] {k}: {a[k]}")
    print("   tally:", tally)
    if tally.get("OTHER") or added or removed:
      rc = 1
  print("PURITY:", "PURE - every moved leaf is the G&A stub cell or a Q0 descendant" if rc == 0 else "IMPURE - see OTHER/ADDED/REMOVED")
  return rc


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("--dump")
  ap.add_argument("--diff", nargs=2)
  args = ap.parse_args()
  if args.dump:
    dump(args.dump)
  elif args.diff:
    sys.exit(diff(*args.diff))
