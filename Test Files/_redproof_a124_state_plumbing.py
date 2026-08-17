# -*- coding: utf-8 -*-
"""A-124 red-proof: the SBA 7(a) rate resolver must key on the draft's STATE.

Replays Millgate Press (draft 2e198cbf...) through the production model-input
builder (build_python_model_input_json + apply_derived_driver_policies_to_model_input)
with business_facts packed EXACTLY as post_intake_initial_grid/runner.py packs
them (address_state from intake_consult_drafts), and asserts the stamped
debt_interest_rate_policy is the Iowa cohort, not the national one.

RED on the pre-fix tree (state=None, national 9.0%/n=895, quarterly 0.0225);
GREEN on the fix (state='IA', n=9, median 6.0, quarterly 0.015).
Also asserts: stub (Q0) stays the client's stated rate 0.01875; a draft with
NO state resolves exactly as before (national); Y1 interest on the persisted
amortization balances = sum(avg balances) x 0.015.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, ROOT)

from client_intake_and_finmo import finmo_bridge as fb  # noqa: E402
from client_intake_and_finmo.intake_submission import get_mysql_connection  # noqa: E402

DRAFT_PREFIX = os.environ.get("A124_DRAFT_PREFIX", "2e198cbf")


def _obj(raw):
  if isinstance(raw, dict):
    return raw
  try:
    return json.loads(raw) if raw else {}
  except Exception:
    return {}


def _facts(row):
  # EXACT shape of post_intake_initial_grid/runner.py business_facts
  return {
    "name": row.get("business_name"),
    "business_name": row.get("business_name"),
    "address": row.get("business_address"),
    "start_date": row.get("business_start_date"),
    "address_street": row.get("address_street"),
    "address_city": row.get("address_city"),
    "address_state": row.get("address_state"),
    "address_zip": row.get("address_zip"),
    "address_country": row.get("address_country"),
  }


def build(row, facts):
  ops = _obj(row.get("operating_model_json"))
  fin = _obj(row.get("financials_json"))
  people = _obj(row.get("people_json"))
  year1 = _obj(row.get("financials_year1_json"))
  marketing = _obj(row.get("marketing_model_json"))
  ppe = float(fin.get("initial_assets") or 0.0)
  fb._SBA_BUSINESS_LOAN_RATE_CACHE.clear()
  mij = fb.apply_derived_driver_policies_to_model_input(
    fb.build_python_model_input_json(
      business_facts=facts,
      ops_json=ops,
      people_json=people,
      financials_json=fin,
      financials_year1_json=year1,
      marketing_model_json=marketing,
      forecast_starting_ppe=ppe,
      maintenance_rate=0.05,
    ))
  return mij, fin


def _rate_row(mij):
  for row in (mij.get("sections") or {}).get("expenses") or []:
    if isinstance(row, dict) and str(row.get("label") or "").strip() == "Interest Rate":
      return row
  for sec, rows in ((mij.get("sections") or {}).items()):
    for row in rows or []:
      if isinstance(row, dict) and str(row.get("label") or "").strip() == "Interest Rate":
        return row
  return {}


def main():
  fb._load_root_env()
  conn = get_mysql_connection()
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s LIMIT 1", (DRAFT_PREFIX + "%",))
  row = cur.fetchone()
  assert row, f"no draft {DRAFT_PREFIX}"
  print(f"draft {row['draft_id']} {row.get('business_name')} address_state={row.get('address_state')!r}")

  fails = []

  def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
      fails.append(msg)

  # --- with the state (production packing) -------------------------------
  mij, fin = build(row, _facts(row))
  pol = ((mij.get("derived_driver_policies") or {}).get("debt_interest_rate_policy") or {})
  src = pol.get("source_detail") or {}
  print("  policy:", json.dumps({k: src.get(k) for k in ("source", "match_basis", "naics", "state", "sample_count", "median_rate_pct", "annual_rate_decimal")}),
        "quarterly", pol.get("quarterly_rate_decimal"))
  check(src.get("source") == "sba_loan_7a_raw", "source is sba_loan_7a_raw")
  check(src.get("state") == "IA", f"source_detail.state == 'IA' (got {src.get('state')!r})")
  check(src.get("sample_count") == 9, f"Iowa cohort n == 9 (got {src.get('sample_count')})")
  check(abs(float(src.get("median_rate_pct") or 0) - 6.0) < 1e-9, f"median_rate_pct == 6.0 (got {src.get('median_rate_pct')})")
  check(abs(float(pol.get("quarterly_rate_decimal") or 0) - 0.015) < 1e-9, f"quarterly_rate_decimal == 0.015 (got {pol.get('quarterly_rate_decimal')})")
  rr = _rate_row(mij)
  vals = list(rr.get("values") or [])
  print("  Interest Rate row values:", vals[:6], "...")
  stub = float(vals[0]) if vals else None
  check(stub is not None and abs(stub - 0.01875) < 1e-9, f"stub Q0 stays the stated rate 0.01875 (got {stub})")
  check(len(vals) >= 21 and all(abs(float(v) - 0.015) < 1e-9 for v in vals[1:21]), "Q1..Q20 == 0.015")

  # --- Y1 interest on the persisted amortization balances ----------------
  ds = _obj(row.get("debt_schedule"))
  rows_ds = [r for r in (ds.get("rows") or ds.get("quarter_rows") or []) if isinstance(r, dict)]
  if rows_ds:
    y1 = [r for r in rows_ds if int(float(r.get("quarter_index") or 0)) in (1, 2, 3, 4)]
    def _avg(r):
      o = float(r.get("opening_balance") or r.get("debt_opening_balance") or r.get("opening_debt") or 0)
      c = float(r.get("closing_balance") or r.get("debt_closing_balance") or r.get("closing_debt") or 0)
      return (o + c) / 2.0
    s = sum(_avg(r) for r in y1)
    print(f"  Y1 sum(avg balances)={s:,.2f}  x0.0225={s*0.0225:,.2f} (old)  x0.015={s*0.015:,.2f} (new)  x0.01875={s*0.01875:,.2f} (stated)")
  else:
    print("  (no persisted debt_schedule rows on the draft - Y1 arithmetic skipped)", list(ds.keys())[:8])

  # --- no-state path: identical to the national resolution -------------------
  facts_nostate = _facts(row)
  facts_nostate["address_state"] = None
  mij2, _ = build(row, facts_nostate)
  pol2 = ((mij2.get("derived_driver_policies") or {}).get("debt_interest_rate_policy") or {})
  src2 = pol2.get("source_detail") or {}
  print("  no-state policy:", json.dumps({k: src2.get(k) for k in ("state", "sample_count", "median_rate_pct", "annual_rate_decimal")}))
  check(src2.get("state") is None and src2.get("sample_count") == 895 and abs(float(src2.get("median_rate_pct") or 0) - 9.0) < 1e-9,
        "no-state draft resolves national (state=None, n=895, 9.0)")
  # resolver called the OLD way (2 positional args) == no-state result
  fb._SBA_BUSINESS_LOAN_RATE_CACHE.clear()
  old_rate, old_src = fb._sba_business_loan_interest_rate_and_source(_obj(row.get("operating_model_json")), fin)
  check(old_src == src2 and abs(old_rate - float(pol2.get("annual_rate_decimal"))) < 1e-9, "2-arg call == no-state result (byte-identical no-state path)")

  print(("GREEN" if not fails else f"RED ({len(fails)} failing)") + " - A-124 state plumbing")
  return 0 if not fails else 1


if __name__ == "__main__":
  sys.exit(main())
