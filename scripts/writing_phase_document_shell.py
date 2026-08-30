"""Build the document shell against a real draft and PROVE the craft rules.

usage: python scripts/writing_phase_document_shell.py [--draft c9095a31]

Renders three of the eight registry figures from the draft's real numbers,
builds the placeholder shell into C:\\dev\\Client Written Plans (workbook
naming convention), probes the saved file, and runs checks R21/R22/R23
against the probe. A check that cannot run FAILS - and so does this script.
Nothing generated: no prose, no GPT call.
"""
from __future__ import annotations

import argparse
import datetime as dt
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

from writing_phase import checks as C  # noqa: E402
from writing_phase import rules as R  # noqa: E402
from writing_phase.document import probe as P  # noqa: E402
from writing_phase.document import renderer as REN  # noqa: E402
from writing_phase.document import theme as T  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--draft", default="c9095a31")
  a = ap.parse_args()
  conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                                 password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"))
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT draft_id, business_name, planning_run_id, finmo_json, model_input_json "
              "FROM intake_consult_drafts WHERE draft_id LIKE %s", (a.draft + "%",))
  d = cur.fetchone()
  if not d:
    print("no such draft"); return 2
  fj = json.loads(d["finmo_json"])
  mi = json.loads(d["model_input_json"])
  qr = {int(r["quarter_index"]): r for r in fj["quarter_rows"] if r.get("quarter_index") is not None}

  def ysum(key):
    return [sum(float(qr[i].get(key) or 0) for i in range(4 * y - 3, 4 * y + 1)) for y in range(1, 6)]

  # Figure 1 - revenue by line of business (product-keyed, as build.py does)
  by_prod, prod_lob = {}, {}
  for r in mi["sections"]["revenue"]:
    lever = str(r.get("lever_id") or "")
    prod = lever.rsplit("::", 1)[0] if "::" in lever else str(r.get("lob"))
    by_prod.setdefault(prod, {})[str(r.get("driver"))] = [float(v or 0) for v in (r.get("values") or [])]
    prod_lob[prod] = str(r.get("lob"))
  lob_annual = {}
  for prod, drv in by_prod.items():
    cap, pr, ut = drv.get("Capacity"), drv.get("Unit Price"), drv.get("Utilization")
    if not (cap and pr and ut):
      continue
    n = min(len(cap), len(pr), len(ut))
    qrev = [cap[i] * pr[i] * ut[i] for i in range(n)]
    lob = prod_lob[prod]
    acc = lob_annual.setdefault(lob, [0.0] * 5)
    for y in range(1, 6):
      acc[y - 1] += sum(qrev[i] for i in range(4 * y - 3, min(4 * y + 1, n)))

  cash = [float(qr[i].get("ending_cash") or 0) for i in range(1, 21)]
  trough = min(range(20), key=lambda i: cash[i])
  rev = ysum("revenue"); cg = ysum("cogs"); ni = ysum("net_income")
  eb = ysum("ebitda"); dep = ysum("depreciation")
  gross = [(rev[i] - cg[i]) / rev[i] if rev[i] else 0 for i in range(5)]
  oper = [(eb[i] - dep[i]) / rev[i] if rev[i] else 0 for i in range(5)]
  netm = [ni[i] / rev[i] if rev[i] else 0 for i in range(5)]

  def placement(key):
    return next(c["placement"] for c in R.CHART_REGISTRY if c["key"] == key)

  charts = [
    ("Revenue by Line of Business", T.fig_revenue_by_lob(lob_annual),
     "market_and_industry", placement("revenue_by_lob")),
    ("Revenue and Net Income", T.fig_revenue_net_income(rev, ni),
     "financial_plan", placement("revenue_and_net_income")),
    ("Margin Structure", T.fig_margin_structure(gross, oper, netm),
     "financial_plan", placement("margin_structure")),   # WRAP - the proof
    ("Cash Position", T.fig_cash_position(["Q%d" % i for i in range(1, 21)], cash, trough),
     "financial_plan", placement("cash_position")),
  ]

  stamp = dt.datetime.now().strftime(R.PLAN_FILENAME_STAMP_FORMAT)
  out = os.path.join(R.PLAN_OUTPUT_DIR,
                     R.PLAN_FILENAME_FORMAT.format(business_name=d["business_name"], stamp=stamp))
  run_id = str(d["planning_run_id"] or d["draft_id"])
  REN.build_shell(out, business_name=d["business_name"], run_id=run_id, charts=charts)
  print("shell written: %s" % out)

  pr = P.probe_docx(out, run_id=run_id)
  print("\nPROBE:")
  for k in sorted(pr):
    print("  %-32s %s" % (k, pr[k]))

  results = [
    C.check_footer_and_run_id(document_probe=pr),
    C.check_document_craft(document_probe=pr),
    C.check_editable(document_probe=pr),
  ]
  print("\nCRAFT CHECKS:")
  ok = True
  for r in results:
    status = "PASS" if (r.executed and r.passed) else "FAIL"
    ok = ok and (r.executed and r.passed)
    print("  %-4s %-4s executed=%s %s %s" % (r.rule_id, status, r.executed, r.detail, r.offenders[:4]))
  return 0 if ok else 1


if __name__ == "__main__":
  raise SystemExit(main())
