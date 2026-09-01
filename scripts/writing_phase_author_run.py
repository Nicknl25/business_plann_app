"""Author The Business on the last N real drafts, verify, render, calibrate.

The MEASURE-DON'T-GREP run for the first written section (2026-09-01):
- authors the_business per draft through writing_phase.author (GPT + checks
  with one repair round),
- renders the token-substituted prose to --out for reading,
- then runs the similarity calibration Nick ordered: Willowbank vs Cedarhill
  (same persona, same NAICS) MUST trip the guard; Bluestem vs Halbrook (two
  real landscapers, same NAICS) must not.

usage: python scripts/writing_phase_author_run.py [--n 10] [--out DIR]
                                                  [--only PREFIX]
Outputs go to --out (default _writing_business/), never to the client folder -
no gate is resolved here and nothing is delivered.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from writing_phase import author as AU          # noqa: E402
from writing_phase import checks as CK          # noqa: E402
from writing_phase import payload as PL         # noqa: E402
from writing_phase import rules as R            # noqa: E402
from writing_phase.facts import build as B      # noqa: E402
from writing_phase.facts.assembler import assemble  # noqa: E402

DRAFT_COLS = ("draft_id, business_name, business_start_date, address_zip, address_state, "
              "operating_model_json, financials_json, target_market_json, people_json, "
              "fulfillment_json, finmo_json, model_input_json, payroll_headcount, "
              "marketing_schedule_json, messages_json, planning_context_summary_json, "
              "financials_year1_json, marketing_model_json, planning_run_id")


def _grams(payload, n):
  words = []
  for s in payload.get("sentences") or []:
    words.extend(re.findall(r"[a-z0-9']+", str(s.get("text") or "").lower()))
  return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--n", type=int, default=10)
  ap.add_argument("--out", default=os.path.join(ROOT, "_writing_business"))
  ap.add_argument("--only", default="", help="author only drafts whose id starts with this")
  a = ap.parse_args()
  os.makedirs(a.out, exist_ok=True)

  conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                                 password=os.getenv("MYSQL_PASSWORD"),
                                 database=os.getenv("MYSQL_DB"), autocommit=True)
  cur = conn.cursor(dictionary=True)
  cur.execute(f"""SELECT {DRAFT_COLS} FROM intake_consult_drafts
                  WHERE finmo_json IS NOT NULL AND payroll_headcount IS NOT NULL
                  ORDER BY updated_at DESC LIMIT %s""", (a.n,))
  drafts = cur.fetchall()
  plain = conn.cursor()

  payloads = {}
  for d in drafts:
    if a.only and not d["draft_id"].startswith(a.only):
      continue
    name = d["business_name"]
    cat = B.build_catalog(plain, d)
    asm = assemble(cat, sections=["the_business"], draft=d)
    brief = asm.sections["the_business"]
    res = AU.author_section(d, cat, brief)
    tag = "PASS" if res["ok"] else ("FAIL:" + str(res.get("error")))
    print("%-36s %-14s attempts=%s sentences=%s" % (
      name[:36], tag, res.get("attempts"),
      len((res.get("payload") or {}).get("sentences") or [])))
    for r in CK.failures(res.get("results") or []):
      print("    %s %s %s" % (r.rule_id, r.failure_code, "; ".join(r.offenders[:3])))
    if res.get("payload"):
      payloads[d["draft_id"]] = (d, res["payload"])
      text = AU.render_section_text(res["payload"], cat)
      base = os.path.join(a.out, "%s_%s" % (d["draft_id"][:8],
                                            re.sub(r"[^A-Za-z0-9]+", "_", name)[:30]))
      with io.open(base + ".txt", "w", encoding="utf-8") as f:
        f.write("THE BUSINESS - %s [%s]\n%s\n\n" % (name, tag, "=" * 60))
        f.write(text)
      with io.open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(res["payload"], f, ensure_ascii=False, indent=1)

  # ---- THE CALIBRATION (Nick 2026-09-01) ----------------------------------
  def naics(d):
    try:
      om = d["operating_model_json"]
      om = json.loads(om) if isinstance(om, (str, bytes)) else (om or {})
      return str(om.get("business_naics_6") or "")
    except Exception:
      return ""

  by_name = {d["business_name"]: (d, p) for d, p in payloads.values()}
  pairs = []
  names = list(by_name)
  for i, n1 in enumerate(names):
    for n2 in names[i + 1:]:
      if naics(by_name[n1][0]) and naics(by_name[n1][0]) == naics(by_name[n2][0]):
        pairs.append((n1, n2))
  n = R.SIMILARITY_GUARD["ngram_size"]
  print("\nSIMILARITY CALIBRATION (8-gram share vs the %.0f%% guard):"
        % (R.SIMILARITY_GUARD["max_overlap_share"] * 100))
  for n1, n2 in pairs:
    res = CK.check_cross_plan_similarity(by_name[n1][1],
                                         corpus_ngrams=_grams(by_name[n2][1], n))
    print("  %-30s vs %-30s -> %s (%s)" % (
      n1[:30], n2[:30], "GUARD FIRES" if not res.passed else "clean", res.detail))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
