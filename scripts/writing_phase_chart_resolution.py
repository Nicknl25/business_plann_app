"""Chart resolution on the SAME ten drafts the fact coverage uses.

For every chart in the registry: does each required series/fact resolve, per
draft? A chart missing any requirement is OMITTED for that draft (silently in
the document, loudly here). With --log-misses each unresolved requirement
lands in writing_phase_fact_misses, per Nick's ruling that every requested
series key that doesn't resolve is logged.

usage: python scripts/writing_phase_chart_resolution.py [--n 10] [--log-misses]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from writing_phase import rules as R  # noqa: E402
from writing_phase.facts import build as B  # noqa: E402
from writing_phase import rule_lookup as RL  # noqa: E402
from writing_phase.document import tables as TB  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--n", type=int, default=10)
  ap.add_argument("--log-misses", action="store_true")
  a = ap.parse_args()
  conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                                 password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
                                 autocommit=True)
  cur = conn.cursor(dictionary=True)
  cur.execute("""SELECT draft_id, business_name, business_start_date, address_zip, address_state,
                        operating_model_json, financials_json, target_market_json, people_json,
                        finmo_json, model_input_json, payroll_headcount, marketing_schedule_json, planning_run_id
                 FROM intake_consult_drafts
                 WHERE finmo_json IS NOT NULL AND payroll_headcount IS NOT NULL
                 ORDER BY updated_at DESC LIMIT %s""", (a.n,))
  drafts = cur.fetchall()
  plain = conn.cursor()

  sink = None
  if a.log_misses:
    RL.ensure_fact_miss_table(conn)
    def sink(**kw):
      RL.log_fact_miss(conn, planning_run_id=None, **kw)

  charts = sorted(R.CHART_REGISTRY, key=lambda c: c["order"])
  per_chart = defaultdict(int)
  blockers = defaultdict(lambda: defaultdict(int))
  print("%-34s %s" % ("", "  ".join(d["draft_id"][:6] for d in drafts)))
  matrix = {c["key"]: [] for c in charts}
  totals = []
  tmatrix = {fn.__name__.replace("build_", ""): [] for fn in TB.BODY_TABLE_BUILDERS}
  for d in drafts:
    for fn in TB.BODY_TABLE_BUILDERS:
      try:
        ok = fn(d) is not None
      except Exception:
        ok = False
      tmatrix[fn.__name__.replace("build_", "")].append("Y" if ok else ".")
    cat = B.build_catalog(plain, d, miss_sink=sink)
    n_ok = 0
    for c in charts:
      missing = [k for k in c["requires_facts"] if cat.get(k) is None]
      ok = not missing
      matrix[c["key"]].append("Y" if ok else ".")
      if ok:
        per_chart[c["key"]] += 1
        n_ok += 1
      else:
        for k in missing:
          blockers[c["key"]][k] += 1
    totals.append(n_ok)
  for c in charts:
    print("%-34s %s   %d/%d" % (c["key"], "  ".join("%-6s" % v for v in matrix[c["key"]]),
                                per_chart[c["key"]], len(drafts)))
  print("%-34s %s" % ("CHARTS RENDERING", "  ".join("%-6d" % t for t in totals)))
  print("\nBODY TABLES")
  for k, v in tmatrix.items():
    print("%-34s %s   %d/%d" % (k, "  ".join("%-6s" % x for x in v), v.count("Y"), len(drafts)))
  print("\nblocking requirements (chart <- fact, drafts blocked):")
  for ck, m in blockers.items():
    for k, n in sorted(m.items(), key=lambda kv: -kv[1]):
      print("  %-30s <- %-38s %d" % (ck, k, n))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
