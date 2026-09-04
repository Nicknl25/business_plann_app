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
from writing_phase.document import assemble as ASM  # noqa: E402
from writing_phase.document import probe as PRB     # noqa: E402
from writing_phase.facts import build as B      # noqa: E402
from writing_phase.facts.assembler import assemble  # noqa: E402

DRAFT_COLS = ("draft_id, business_name, business_start_date, address_zip, address_state, "
              "operating_model_json, financials_json, target_market_json, people_json, "
              "fulfillment_json, finmo_json, model_input_json, payroll_headcount, "
              "marketing_schedule_json, messages_json, planning_context_summary_json, "
              "financials_year1_json, marketing_model_json, planning_run_id")


def print_receipt(name, res, payload):
  """THE QUALITY RECEIPT (Nick 2026-09-03): verdict, the six metrics, and
  which checks bit versus slept - so Nick reads receipts, and prose only on
  an anomalous receipt or as the one random sample per batch."""
  sents = payload.get("sentences") or []
  n = len(sents) or 1
  paras = {}
  for s in sents:
    paras.setdefault(int(s.get("paragraph") or 1), []).append(str(s.get("text") or ""))
  ptexts = [" ".join(paras[k]) for k in sorted(paras)]
  words = sum(len(CK.FACT_TOKEN.sub("X", str(s.get("text") or "")).split()) for s in sents)
  full = " ".join(str(s.get("text") or "") for s in sents)
  classes = {}
  for s in sents:
    classes[str(s.get("class") or "?")] = classes.get(str(s.get("class") or "?"), 0) + 1
  first = name.split()[0].lower() if name.split() else ""
  anaphora = sum(1 for s in sents
                 if not CK.FACT_TOKEN.search(str(s.get("text") or ""))
                 and first not in str(s.get("text") or "").lower()
                 and CK._ANAPHOR.search(str(s.get("text") or "")))
  machinery = (full.count("trade group that includes")
               + full.count("{{fact:industry.bds_scope_label}}")
               + full.count("NAICS"))
  last_toks = CK.FACT_TOKEN.findall(ptexts[-1]) if ptexts else []
  closer = "EXERCISED" if last_toks else "SLEPT(qualitative)"
  verdict = "PASS" if res.get("ok") else "FAIL"
  print("    RECEIPT %s | words=%d paras=%d sentences=%d | %s | name=%d notes=%d "
        "machinery=%d anaphora-only=%d | closer-check=%s" % (
          verdict, words, len(ptexts), len(sents),
          " ".join("%s=%d%%" % (k[:4], round(100 * v / n)) for k, v in sorted(classes.items())),
          len(re.findall(re.escape(name), full)), len(payload.get("notes") or []),
          machinery, anaphora, closer))
  bit = [r for r in (res.get("results") or []) if r.offenders or not (r.executed and r.passed)]
  print("    CHECKS %d ran | bit: %s | failed: %s" % (
    len(res.get("results") or []),
    ",".join(sorted({r.rule_id for r in bit})) or "none",
    ",".join(r.rule_id for r in (res.get("results") or []) if not (r.executed and r.passed)) or "none"))


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
  ap.add_argument("--identity-only", action="store_true", dest="identity_only",
                  help="run just the identity-guard matrix, no authoring")
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

  # ---- THE IDENTITY GUARD, proven on every pair (Nick 2026-09-01) ---------
  print("IDENTITY GUARD (deterministic; NAICS alone never fires):")
  for i, d1 in enumerate(drafts):
    for d2 in drafts[i + 1:]:
      v = CK.identity_match(d1, d2)
      if v["fired"] or set(v["matched"]) - {"naics"}:
        print("  %-30s vs %-30s -> %s matched=%s%s" % (
          d1["business_name"][:30], d2["business_name"][:30],
          "FIRED" if v["fired"] else "silent", ",".join(v["matched"]),
          " owners=%s" % ",".join(v["shared_owners"]) if v["shared_owners"] else ""))
  if a.identity_only:
    return 0

  # ---- R02 GATES (Nick 2026-09-03): the corpus is the stored prior sections
  # in the same NAICS; empty corpus = the first plan in its industry, a
  # vacuous pass. Every PASS deposits its section here, so the gate grows
  # teeth exactly as fast as plans are written.
  ccur = conn.cursor()
  ccur.execute("""CREATE TABLE IF NOT EXISTS writing_phase_section_corpus (
      id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
      draft_id VARCHAR(64) NOT NULL, naics6 VARCHAR(16) NOT NULL,
      section_key VARCHAR(64) NOT NULL, payload_json JSON NOT NULL,
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      KEY ix_naics_section (naics6, section_key)) ENGINE=InnoDB
      DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
  conn.commit()

  payloads = {}
  for d in drafts:
    if a.only and not d["draft_id"].startswith(a.only):
      continue
    name = d["business_name"]
    cat = B.build_catalog(plain, d)
    asm = assemble(cat, sections=["the_business"], draft=d)
    brief = asm.sections["the_business"]
    try:
      n6 = str((json.loads(d["operating_model_json"]) if isinstance(d["operating_model_json"], (str, bytes))
                else (d["operating_model_json"] or {})).get("business_naics_6") or "")
    except Exception:
      n6 = ""
    ccur.execute("SELECT payload_json FROM writing_phase_section_corpus "
                 "WHERE naics6=%s AND section_key='the_business' AND draft_id<>%s",
                 (n6, d["draft_id"]))
    corpus = set()
    for (pj,) in ccur.fetchall():
      corpus |= _grams(json.loads(pj), R.SIMILARITY_GUARD["ngram_size"])
    res = AU.author_section(d, cat, brief, corpus_ngrams=corpus)
    tag = "PASS" if res["ok"] else ("FAIL:" + str(res.get("error")))
    print("%-36s %-14s attempts=%s sentences=%s" % (
      name[:36], tag, res.get("attempts"),
      len((res.get("payload") or {}).get("sentences") or [])))
    for r in CK.failures(res.get("results") or []):
      print("    %s %s %s" % (r.rule_id, r.failure_code, "; ".join(r.offenders[:3])))
    if res.get("payload"):
      print_receipt(name, res, res["payload"])
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
      if res["ok"]:
        ccur.execute("DELETE FROM writing_phase_section_corpus "
                     "WHERE draft_id=%s AND section_key='the_business'", (d["draft_id"],))
        ccur.execute("INSERT INTO writing_phase_section_corpus "
                     "(draft_id, naics6, section_key, payload_json) VALUES (%s,%s,%s,%s)",
                     (d["draft_id"], n6, "the_business", json.dumps(res["payload"])))
        conn.commit()
      if res["ok"]:
        # ---- land it where Nick reads (his order, 2026-09-01): the docx
        # shell into C:\dev\Client Written Plans, then PROBE the saved file
        # and hold it to R21/R22/R23 - open the artifact, never trust the
        # writer.
        rid = str(d.get("planning_run_id") or d["draft_id"])
        path = ASM.build_section_draft_docx(
          business_name=name, run_id=rid, section_key="the_business",
          payload=res["payload"], cat=cat)
        pr = PRB.probe_docx(path, run_id=rid)
        craft = [CK.check_footer_and_run_id(document_probe=pr),
                 CK.check_document_craft(document_probe=pr),
                 CK.check_editable(document_probe=pr)]
        ok = all(c.executed and c.passed for c in craft)
        print("    docx %s -> %s" % ("R21/R22/R23 OK" if ok else "CRAFT FAIL", path))
        for c in craft:
          if not (c.executed and c.passed):
            print("      %s %s %s" % (c.rule_id, c.failure_code, "; ".join(c.offenders[:4])))

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
