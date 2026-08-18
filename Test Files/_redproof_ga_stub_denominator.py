# -*- coding: utf-8 -*-
"""G&A STUB DENOMINATOR red-proof (Nick's ruling 2026-08-17; research
docs/STUB_CELLS_WHY_RESEARCH.md SS1).

Replays Millgate Press (draft 2e198cbf...) through the PRODUCTION model-input
builder (build_python_model_input_json + apply_derived_driver_policies_to_
model_input) and build_python_finmo_json - the exact chain the initial-grid
runner and the gate's byte floor use - and asserts:

  * Model Inputs G&A stub (values[0]) == other_opex_absolute / STATED
    current_revenue (Millgate 31,200 / 854,000 = 0.036534), NOT the
    capacity-ceiling ratio 0.027701.
  * The stub equals the coherence gate's own G&A percent on the same draft.
  * FINMO Q0 G&A dollars == stated quarterly dollars (31,200 / 4 = 7,800).
  * FORECAST Q1-Q20 G&A values are BYTE-IDENTICAL to the pre-fix capture
    (--capture writes them; --compare checks).
  * The other three derived stub cells (taxes, depreciation, capacity) are
    untouched vs the capture.

RED on the pre-fix tree (stub 0.027701); GREEN on the fix.

Usage:
    python "Test Files/_redproof_ga_stub_denominator.py" --capture <json>   # pre-fix tree
    python "Test Files/_redproof_ga_stub_denominator.py" --compare <json>   # post-fix tree
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, ROOT)

from client_intake_and_finmo import finmo_bridge as fb  # noqa: E402
from client_intake_and_finmo.intake_submission import get_mysql_connection  # noqa: E402

DRAFT_PREFIX = os.environ.get("GA_DRAFT_PREFIX", "2e198cbf")


def _obj(raw):
  if isinstance(raw, dict):
    return raw
  try:
    return json.loads(raw) if raw else {}
  except Exception:
    return {}


def _facts(row):
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


def build(row):
  ops = _obj(row.get("operating_model_json"))
  fin = _obj(row.get("financials_json"))
  people = _obj(row.get("people_json"))
  year1 = _obj(row.get("financials_year1_json"))
  marketing = _obj(row.get("marketing_model_json"))
  ppe = float(fin.get("initial_assets") or 0.0)
  mij = fb.apply_derived_driver_policies_to_model_input(
    fb.build_python_model_input_json(
      business_facts=_facts(row),
      ops_json=ops,
      people_json=people,
      financials_json=fin,
      financials_year1_json=year1,
      marketing_model_json=marketing,
      forecast_starting_ppe=ppe,
      maintenance_rate=0.05,
    ))
  finmo = fb.build_python_finmo_json(model_input_json=mij)
  return mij, finmo, fin, ops, year1


def _row(mij, label):
  for sec, rows in ((mij.get("sections") or {}).items()):
    for row in rows or []:
      if isinstance(row, dict) and str(row.get("label") or "").strip() == label:
        return row
  return {}


def _q0(finmo, key):
  rows = finmo.get("quarter_rows") or []
  for r in rows:
    if isinstance(r, dict) and int(float(r.get("quarter_index", r.get("slot_index", -1)) or 0)) == 0:
      return r.get(key)
  return (rows[0] or {}).get(key) if rows else None


def snapshot(row):
  mij, finmo, fin, ops, year1 = build(row)
  ga = _row(mij, "General & Administrative")
  vals = [float(v) for v in (ga.get("values") or [])]
  snap = {
    "ga_values": vals,
    "taxes_stub": float((_row(mij, "Taxes").get("values") or [None])[0] or 0.0),
    "depreciation_stub": float((_row(mij, "Depreciation").get("values") or [None])[0] or 0.0),
    "capacity_stubs": [float((r.get("values") or [0.0])[0] or 0.0)
                       for r in ((mij.get("sections") or {}).get("revenue") or [])
                       if isinstance(r, dict) and str(r.get("driver") or "") == "Capacity"],
    "finmo_q0": {k: _q0(finmo, k) for k in ("revenue", "g_and_a", "gna", "general_and_administrative", "ebitda", "taxes", "net_income")},
    "finmo_q0_keys": sorted(((finmo.get("quarter_rows") or [{}])[0] or {}).keys()),
    "stated_revenue": fb._safe_float(fin.get("current_revenue")) or 0.0,
    "other_opex_absolute": fb._safe_float(fin.get("other_opex_absolute")) or 0.0,
  }
  # coherence gate basis on the same draft
  try:
    from client_intake_and_finmo.intake_coherence.evaluator import basis_from_intake
    b = basis_from_intake(financials_json=fin, ops_json=ops, financials_year1_json=year1)
    snap["gate_fields"] = sorted(getattr(b, "__dataclass_fields__", {}).keys())
    gp = None
    for name in ("gna_pct", "g_and_a_pct", "ga_pct"):
      if hasattr(b, name):
        gp = getattr(b, name)
        break
    snap["gate_gna_pct"] = float(gp) if gp is not None else None
  except Exception as exc:  # pragma: no cover
    snap["gate_gna_pct"] = None
    snap["gate_error"] = repr(exc)
  return snap, finmo


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--capture", help="write the pre-fix snapshot here")
  ap.add_argument("--compare", help="compare against this pre-fix snapshot")
  args = ap.parse_args()

  fb._load_root_env()
  conn = get_mysql_connection()
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s LIMIT 1", (DRAFT_PREFIX + "%",))
  row = cur.fetchone()
  assert row, f"no draft {DRAFT_PREFIX}"
  print(f"draft {row['draft_id']} {row.get('business_name')}")

  snap, finmo = snapshot(row)
  if args.capture:
    with open(args.capture, "w", encoding="utf-8") as fh:
      json.dump(snap, fh, indent=1, sort_keys=True)
    print(f"captured -> {args.capture}")

  fails = []

  def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
      fails.append(msg)

  vals = snap["ga_values"]
  stated = snap["stated_revenue"]
  opex = snap["other_opex_absolute"]
  expected = round(opex / stated, 6) if stated else None
  print(f"  stated current_revenue={stated:,.0f} other_opex_absolute={opex:,.0f} -> expected stub {expected}")
  print(f"  G&A row values[0:4] = {vals[:4]}  ... len={len(vals)}")
  print(f"  finmo Q0: {json.dumps(snap['finmo_q0'])}")
  print(f"  finmo Q0 keys: {snap['finmo_q0_keys']}")
  print(f"  coherence gate gna pct = {snap.get('gate_gna_pct')}  (fields {snap.get('gate_fields')}) {snap.get('gate_error','')}")
  check(len(vals) >= 21, "G&A row has stub + 20 live values")
  check(expected is not None and abs(vals[0] - expected) < 1e-9,
        f"stub == other_opex_absolute / stated current_revenue = {expected} (got {vals[0]})")
  check(abs(vals[0] - 0.027701) > 1e-6, "stub is NOT the capacity-ceiling ratio 0.027701")
  gp = snap.get("gate_gna_pct")
  if gp:
    check(abs(round(gp, 6) - vals[0]) < 1e-9, f"stub == coherence gate's own G&A pct {round(gp,6)}")
  q0rev = fb._safe_float(snap["finmo_q0"].get("revenue")) or 0.0
  q0ga = None
  for k in ("g_and_a", "gna", "general_and_administrative"):
    if snap["finmo_q0"].get(k) is not None:
      q0ga = fb._safe_float(snap["finmo_q0"].get(k))
      break
  if q0ga is not None and stated:
    print(f"  finmo Q0 revenue={q0rev:,.2f} G&A={q0ga:,.2f} (stated quarterly = {opex/4:,.2f})")
    check(abs(q0ga - opex / 4.0) < 0.5, f"FINMO Q0 G&A == stated quarterly dollars {opex/4:,.2f} (got {q0ga:,.2f})")

  if args.compare:
    with open(args.compare, encoding="utf-8") as fh:
      pre = json.load(fh)
    pv = pre["ga_values"]
    check(pv[1:21] == vals[1:21], "FORECAST Q1-Q20 G&A byte-identical to pre-fix capture")
    if pv[1:21] != vals[1:21]:
      for i, (a, b) in enumerate(zip(pv[1:21], vals[1:21]), start=1):
        if a != b:
          print(f"     Q{i}: pre {a} post {b}")
    check(pre["taxes_stub"] == snap["taxes_stub"], f"taxes stub untouched ({snap['taxes_stub']})")
    check(pre["depreciation_stub"] == snap["depreciation_stub"], f"depreciation stub untouched ({snap['depreciation_stub']})")
    check(pre["capacity_stubs"] == snap["capacity_stubs"], f"capacity stubs untouched ({snap['capacity_stubs']})")
    print(f"  PRE stub {pv[0]} -> POST stub {vals[0]}  ({pv[0]*q0rev:,.2f}/q -> {vals[0]*q0rev:,.2f}/q at Q0 revenue {q0rev:,.2f})")

  print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failures)")
  return 0 if not fails else 1


if __name__ == "__main__":
  sys.exit(main())
