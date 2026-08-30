"""Fact-catalogue coverage on REAL drafts (2026-08-30).

Nick's correction: the last TEN drafts through current code, not the 2,493.
Older drafts predate fields (the Falls City stale payload, the fifteen
below-term-minimum drafts) and would report "a fact doesn't compute" when the
real reason is the draft predates the field. Ten recent ones: if a fact fails
there, it is a real gap.

usage: python scripts/writing_phase_fact_coverage.py [--n 10] [--log-misses]
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

from writing_phase.facts import build as B  # noqa: E402
from writing_phase.facts import sentences as S  # noqa: E402
from writing_phase import rule_lookup as RL  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--n", type=int, default=10)
  ap.add_argument("--log-misses", action="store_true", help="write misses to writing_phase_fact_misses")
  ap.add_argument("--show", default="", help="draft prefix: print its full catalogue")
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

  hits = defaultdict(int); reasons = defaultdict(lambda: defaultdict(int))
  sent_hits = defaultdict(int); per_draft = []
  for d in drafts:
    cat = B.build_catalog(plain, d, miss_sink=sink)
    have = set(cat.keys())
    for k in S.all_required_keys():
      if k in have:
        hits[k] += 1
      else:
        reasons[k][cat.absent().get(k, "never computed")] += 1
    ok = 0
    for s in S.SENTENCES:
      # cat.get(), not cat.has(): this IS the demand the writing side will
      # make, so every unresolved key lands in the miss log with its reason.
      got = [cat.get(k, section_key=str(s["section"])) for k in s["needs"]]
      if all(g is not None for g in got):
        sent_hits[s["id"]] += 1; ok += 1
    per_draft.append((d["draft_id"][:8], d["business_name"][:30], len(have), ok, cat.builder_failures()))
    if a.show and d["draft_id"].startswith(a.show):
      print("\n=== CATALOGUE %s %s ===" % (d["draft_id"][:8], d["business_name"]))
      for f in [cat._facts[k] for k in cat.keys()]:
        print("  %-52s %-26s %-9s %s" % (f.key, f.render()[:26], f.provenance.grounding, f.provenance.basis[:60]))
      print("  ABSENT:")
      for k, why in sorted(cat.absent().items()):
        print("    %-50s %s" % (k, why[:80]))

  n = len(drafts)
  print("\nDRAFTS (last %d through current code)" % n)
  for did, name, nf, ns, fails in per_draft:
    print("  %s %-30s facts=%-3d sentences=%d/%d %s" % (did, name, nf, ns, len(S.SENTENCES), ("BUILDER FAIL " + str(fails)) if fails else ""))

  print("\nFACT COVERAGE (%d drafts)" % n)
  print("  %-52s %5s   %s" % ("key", "hits", "top reason when absent"))
  for k in S.all_required_keys():
    top = max(reasons[k].items(), key=lambda kv: kv[1])[0] if reasons[k] else ""
    flag = "" if hits[k] == n else ("  <-- PARTIAL" if hits[k] >= n // 2 else "  <-- WEAK")
    print("  %-52s %2d/%-2d  %s%s" % (k, hits[k], n, top[:70], flag))

  print("\nSENTENCE COVERAGE (all keys resolve)")
  for s in S.SENTENCES:
    print("  %s %2d/%-2d %-30s %s" % (s["id"], sent_hits[s["id"]], n, s["section"][:30], str(s["text"])[:70]))
  full = sum(1 for s in S.SENTENCES if sent_hits[s["id"]] == n)
  print("\n  sentences resolving on ALL %d drafts: %d of %d" % (n, full, len(S.SENTENCES)))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
