"""CW-031 round-7 mini audit -- ARTIFACT CENSUS, no live turns.

Three questions the round-7 fixes turn on, all answered off stored artifacts:

  Q1 (item 2)  Do the door's TRANSPORT keys get PERSISTED into financials_json?
               _apply_scoped_patch applies every "<group>.<field>" key, and
               "financials.cogs_per_line_overrides" is such a key -- so the
               client's raw figure (48, unit "percent") may be landing in the
               stored financials JSON, where the receipt only stopped RENDERING
               it. Also enumerate every OTHER persisted numeric leaf that lives
               under a container key rather than a real stored field.

  Q2 (item 3)  Can _cogs_line_revenue_weight see the weight real product rows
               actually carry? It reads unit_price + (units_per_period_capacity
               | units_per_week_capacity). Census the driver field names on real
               product rows and count rows that carry SOME revenue driver the
               function cannot see -- those would announce a plain average where
               a weighted one was owed.

  Q3 (item 4)  How common is the N=2 coincidence? Count real drafts whose
               product rows all carry the SAME cogs rate, split by N, and how
               many carry a recorded cogs_cost_structure_group.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r7_census.py"
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]

# What _cogs_line_revenue_weight reads today.
WEIGHT_FIELDS_SEEN = ("unit_price", "units_per_period_capacity", "units_per_week_capacity",
                      "utilization_rate", "operating_periods_per_year")
# Anything else on a product row that plainly denotes price or volume.
REVENUE_HINTS = ("price", "capacity", "units", "volume", "revenue", "quantity", "qty",
                 "rate_per", "per_unit", "ticket", "monthly", "weekly", "annual")


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  cur = conn.cursor()
  cur.execute(
    "SELECT draft_id, operating_model_json, financials_json "
    "FROM intake_consult_drafts "
    "WHERE operating_model_json IS NOT NULL AND operating_model_json <> ''")
  rows = cur.fetchall()
  cur.close()
  conn.close()
  print(f"drafts with an ops model: {len(rows)}")

  # ---------------- Q1: transport keys persisted into financials_json --------
  fin_container_leaves: Counter = Counter()
  overrides_examples = []
  groups_examples = []
  for draft_id, _ops_raw, fin_raw in rows:
    try:
      fin = json.loads(fin_raw or "{}")
    except Exception:
      continue
    if not isinstance(fin, dict):
      continue
    for key, value in fin.items():
      if isinstance(value, (list, dict)) and not str(key).startswith("_"):
        fin_container_leaves[key] += 1
    if fin.get("cogs_per_line_overrides") is not None and len(overrides_examples) < 6:
      overrides_examples.append((draft_id, fin.get("cogs_per_line_overrides")))
    if fin.get("cogs_shared_structure_groups") is not None and len(groups_examples) < 6:
      groups_examples.append((draft_id, fin.get("cogs_shared_structure_groups")))

  print("\n--- Q1  container keys stored in financials_json (count of drafts) ---")
  for key, count in fin_container_leaves.most_common(40):
    print(f"  {count:5d}  {key}")
  print(f"\n  drafts carrying financials.cogs_per_line_overrides : {len(overrides_examples)}"
        f"{' (capped at 6)' if len(overrides_examples) == 6 else ''}")
  for draft_id, value in overrides_examples:
    print(f"    {draft_id[:12]}  {json.dumps(value)[:220]}")
  print(f"  drafts carrying financials.cogs_shared_structure_groups: {len(groups_examples)}")
  for draft_id, value in groups_examples:
    print(f"    {draft_id[:12]}  {json.dumps(value)[:220]}")

  # ---------------- Q2 + Q3: product-row driver census -----------------------
  field_counter: Counter = Counter()
  rows_total = 0
  rows_weightable = 0
  rows_blind_but_priced = []   # a revenue driver exists that the weight fn cannot see
  uniform_by_n: Counter = Counter()
  distinct_by_n: Counter = Counter()
  grouped_drafts = 0
  for draft_id, ops_raw, _fin_raw in rows:
    try:
      ops = json.loads(ops_raw or "{}")
    except Exception:
      continue
    rates, groups, n_rows = [], [], 0
    for lob in (ops.get("lob_models") or []):
      if not isinstance(lob, dict):
        continue
      for product in (lob.get("products") or []):
        if not isinstance(product, dict):
          continue
        rows_total += 1
        n_rows += 1
        for key in product:
          field_counter[str(key)] += 1
        price = product.get("unit_price")
        cap = product.get("units_per_period_capacity")
        if cap is None:
          cap = product.get("units_per_week_capacity")
        seen_ok = isinstance(price, (int, float)) and isinstance(cap, (int, float))
        if seen_ok:
          rows_weightable += 1
        else:
          unseen = [k for k, v in product.items()
                    if k not in WEIGHT_FIELDS_SEEN
                    and isinstance(v, (int, float)) and not isinstance(v, bool)
                    and any(h in str(k).lower() for h in REVENUE_HINTS)
                    and float(v) > 0]
          if unseen and len(rows_blind_but_priced) < 12:
            rows_blind_but_priced.append((draft_id, product.get("product_name"), unseen,
                                          {k: product.get(k) for k in WEIGHT_FIELDS_SEEN}))
        pct = product.get("cogs_percent_of_line_revenue")
        if isinstance(pct, (int, float)):
          rates.append(round(float(pct), 6))
        if product.get("cogs_cost_structure_group"):
          groups.append(product.get("cogs_cost_structure_group"))
    if n_rows >= 2 and len(rates) == n_rows:
      if len(set(rates)) == 1:
        uniform_by_n[n_rows] += 1
      else:
        distinct_by_n[n_rows] += 1
    if groups:
      grouped_drafts += 1

  print("\n--- Q2  product-row field census (field -> rows carrying it) ---")
  print(f"  product rows total: {rows_total}   weight-visible (price+capacity): {rows_weightable}")
  for key, count in field_counter.most_common(45):
    mark = " <= weight fn reads" if key in WEIGHT_FIELDS_SEEN else ""
    print(f"  {count:6d}  {key}{mark}")
  print(f"\n  rows with NO visible weight but SOME revenue-ish driver: "
        f"{len(rows_blind_but_priced)}{' (capped at 12)' if len(rows_blind_but_priced) == 12 else ''}")
  for draft_id, name, unseen, seen in rows_blind_but_priced:
    print(f"    {draft_id[:12]}  {str(name)[:28]:<28} unseen={unseen}  seen={seen}")

  print("\n--- Q3  uniform-vs-distinct per-line rates on real drafts ---")
  print(f"  drafts with any cogs_cost_structure_group stored: {grouped_drafts}")
  for n in sorted(set(list(uniform_by_n) + list(distinct_by_n))):
    print(f"    N={n}: all-rates-identical={uniform_by_n.get(n, 0):4d}   "
          f"mixed={distinct_by_n.get(n, 0):4d}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
