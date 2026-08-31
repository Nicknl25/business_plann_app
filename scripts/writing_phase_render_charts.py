"""Render every resolvable chart for one draft to PNG, plus the four body
tables to a check file - the proof the renderers draw real data with the
ruled annotations.

usage: python scripts/writing_phase_render_charts.py [--draft c9095a31] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from writing_phase import rules as R  # noqa: E402
from writing_phase.facts import build as B  # noqa: E402
from writing_phase.document import theme as T  # noqa: E402
from writing_phase.document import tables as TB  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))


def _qnum(v) -> int:
  """A quarter fact may arrive as an int or a 'Q6' style label."""
  try:
    return int(float(v))
  except (TypeError, ValueError):
    s = str(v)
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if digits else 0


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--draft", default="c9095a31")
  ap.add_argument("--out", default=os.path.join(ROOT, "_chart_render"))
  a = ap.parse_args()
  os.makedirs(a.out, exist_ok=True)
  conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                                 password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"))
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (a.draft + "%",))
  d = cur.fetchone()
  if not d:
    print("no such draft"); return 2
  cat = B.build_catalog(conn.cursor(), d)
  V = lambda k: (cat.get(k).value if cat.get(k) is not None else None)

  jobs = {}
  if V("industry.establishments_history") is not None:
    hist = V("industry.establishments_history")
    entry = None
    try:
      entry = int(str(d.get("business_start_date"))[:4])
    except (TypeError, ValueError):
      pass
    jobs["industry_establishments_history"] = lambda: T.fig_industry_history(
      [r[0] for r in hist], [r[1] for r in hist], entry_year=entry)
  if V("market.composition") is not None:
    jobs["local_market_composition"] = lambda: T.fig_local_market_composition(V("market.composition"))
  if V("annual.revenue_by_lob") is not None:
    jobs["revenue_by_lob"] = lambda: T.fig_revenue_by_lob(V("annual.revenue_by_lob"))
  if V("annual.headcount_by_role_group") is not None:
    jobs["headcount_by_role"] = lambda: T.fig_headcount_by_role(V("annual.headcount_by_role_group"))
  if V("entity.wage_positioning") is not None:
    jobs["oews_wage_positioning"] = lambda: T.fig_wage_positioning(V("entity.wage_positioning"))
  rev5, ni5 = V("annual.revenue_series"), V("annual.net_income_series")
  if rev5 is not None and ni5 is not None:
    jobs["revenue_and_net_income"] = lambda: T.fig_revenue_net_income(
      rev5, ni5, cagr=V("annual.revenue_cagr_y1_y5"))
  if V("annual.margin_structure_series") is not None:
    jobs["margin_structure"] = lambda: T.fig_margin_structure(V("annual.margin_structure_series"))
  cashq = V("quarterly.cash_balance_series")
  costq = V("quarterly.total_cost_series")
  if cashq is not None and V("quarterly.cash_trough") is not None:
    months = None
    if costq:
      monthly = sum(costq[:4]) / 12.0
      trough_amt = V("quarterly.cash_trough_amount")
      if monthly > 0 and trough_amt is not None:
        months = float(trough_amt) / monthly
    jobs["cash_position"] = lambda: T.fig_cash_position(
      cashq, _qnum(V("quarterly.cash_trough")), months_cover=months)
  revq = V("quarterly.revenue_series")
  if revq is not None and costq is not None and V("quarterly.break_even") is not None:
    jobs["break_even"] = lambda: T.fig_break_even_cvp(
      revq, costq, _qnum(V("quarterly.break_even")),
      margin_of_safety=V("annual.margin_of_safety"))
  lo, hi = V("annual.marketing_demand_low"), V("annual.marketing_demand_high")
  if rev5 is not None and lo is not None and hi is not None:
    jobs["sensitivity_band"] = lambda: T.fig_sensitivity_band(rev5, float(lo), float(hi))
  dist, ask = V("industry.sba_amount_distribution"), V("entity.funding_request")
  if dist is not None and ask is not None:
    jobs["sba_ask_distribution"] = lambda: T.fig_sba_ask_distribution(
      dist, float(ask), percentile_label=str(V("industry.sba_ask_percentile") or ""),
      loan_count=V("industry.sba_loan_count"))

  order = {c["key"]: c["order"] for c in R.CHART_REGISTRY}
  n = 0
  for key in sorted(jobs, key=lambda k: order.get(k, 999)):
    try:
      png = jobs[key]()
      path = os.path.join(a.out, "%03d_%s.png" % (order.get(key, 999), key))
      with open(path, "wb") as f:
        f.write(png)
      n += 1
      print("rendered %-34s %6.1f KB" % (key, len(png) / 1024.0))
    except Exception as exc:  # noqa: BLE001
      print("FAILED   %-34s %s: %s" % (key, type(exc).__name__, exc))
  missing = [c["key"] for c in R.CHART_REGISTRY if c["key"] not in jobs]
  if missing:
    print("omitted (series absent): %s" % ", ".join(missing))
  print("charts rendered: %d of %d designs" % (n, len(R.CHART_REGISTRY)))

  specs = TB.build_body_tables(d)
  with open(os.path.join(a.out, "tables.json"), "w", encoding="utf-8") as f:
    json.dump(specs, f, indent=1, ensure_ascii=False)
  print("body tables built: %s" % ", ".join(s["key"] for s in specs))
  return 0 if n else 1


if __name__ == "__main__":
  raise SystemExit(main())
