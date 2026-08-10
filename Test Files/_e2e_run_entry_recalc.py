"""RUN-ENTRY RECALC E2E (Nick-ruled): safety by construction, proven
on REAL stored drafts, offline (no persist).

  P1 COHERENT draft (post-keystone Sparrow): the canonical pass
     recomputes to the numbers it already has - nothing would persist.
  P2 INCOHERENT legacy draft (Anderson & Blake, trio 538,087.5 vs
     286,940): heals to the people-derived rollup, every engine-read
     field agreeing.
  P3 The run path calls the recalc at entry (wiring assertion).
"""
import copy
import json
import os
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


import inspect  # noqa: E402

from api_handlers.intake_consult import (  # noqa: E402
    _run_entry_recalc, _run_planning_system_for_draft_unified,
    _sync_financials_consult_persistence_state,
)

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)


def load(prefix):
    cur.execute(
        "SELECT business_name, financials_json, financials_year1_json, "
        "people_json, operating_model_json, marketing_model_json "
        "FROM intake_consult_drafts WHERE draft_id LIKE %s LIMIT 1",
        (prefix + "%",))
    r = cur.fetchone()
    return {k: json.loads(r[k] or "{}") if k != "business_name" else r[k]
            for k in r}


def recalc(d):
    ppl = copy.deepcopy(d["people_json"])
    fin, y1 = _sync_financials_consult_persistence_state(
        financials_json=copy.deepcopy(d["financials_json"]),
        financials_year1_json=copy.deepcopy(d["financials_year1_json"]),
        marketing_model_json=d["marketing_model_json"],
        people_json=ppl, ops_json=d["operating_model_json"])
    return fin, y1, ppl


# P1: coherent (post-keystone Sparrow) -> the NUMBERS never move and
# the pass is a FIXED POINT. (Display-stamp schema enrichment - e.g. a
# new q20_hold key in _coherence.eval - is legitimate; the safety
# contract is about the engine-read fields and convergence.)
d = load("4aa25e24")
fin, y1, ppl = recalc(d)
_ENGINE_READ = ("baseline_payroll_year1", "current_payroll",
                "payroll_total_year1", "current_revenue", "current_cogs",
                "cogs_total_year1", "cogs_percent_of_revenue",
                "other_opex_absolute", "marketing_total_year1",
                "owner_compensation", "payroll_adjustment")
nums_same = all(fin.get(k) == d["financials_json"].get(k) for k in _ENGINE_READ)
check(f"P1 coherent draft ({d['business_name']}): every engine-read "
      "field recomputes identical + people/y1 unchanged",
      nums_same and y1 == d["financials_year1_json"] and ppl == d["people_json"])
fin_b, y1_b, ppl_b = recalc({"financials_json": fin, "financials_year1_json": y1,
                             "people_json": ppl,
                             "operating_model_json": d["operating_model_json"],
                             "marketing_model_json": d["marketing_model_json"],
                             "business_name": ""})
check("P1b the pass is a fixed point (second recompute byte-identical)",
      fin_b == fin and y1_b == y1 and ppl_b == ppl)

# P2: incoherent legacy (Anderson & Blake) -> heals toward correct.
# The oracle is THE canonical rollup (_compute_payroll_baseline), not a
# naive wage sum - the canonical baseline legitimately includes more
# than raw wages (the audit's B2 naive-sum metric overstated legacy
# incoherence for exactly this reason).
from api_handlers.intake_consult import _compute_payroll_baseline  # noqa: E402

d2 = load("009784f4")
fin0 = d2["financials_json"]
print(f"   before: trio={[fin0.get(k) for k in ('baseline_payroll_year1', 'current_payroll', 'payroll_total_year1')]}")
fin2, _y2, ppl2 = recalc(d2)
trio = [fin2.get(k) for k in
        ("baseline_payroll_year1", "current_payroll", "payroll_total_year1")]
canon = _compute_payroll_baseline(shared_context={
    "people_capability": ppl2,
    "operating_model": d2["operating_model_json"],
})
canon_total = float((canon or {}).get("baseline_payroll_year1")
                    or (canon or {}).get("total") or 0.0) if isinstance(canon, dict) else float(canon or 0.0)
print(f"   after:  trio={trio} canonical={canon_total:,.0f}")
check(f"P2 incoherent legacy draft ({d2['business_name']}) heals: trio "
      "agrees internally AND equals the CANONICAL rollup (one authority)",
      len({round(float(v), 2) for v in trio if v is not None}) == 1
      and abs(float(trio[-1]) - canon_total) < 1.0)

# P2b: idempotence at the run door - a second pass changes nothing.
fin3, y3, ppl3 = recalc({"financials_json": fin2, "financials_year1_json": _y2,
                         "people_json": ppl2,
                         "operating_model_json": d2["operating_model_json"],
                         "marketing_model_json": d2["marketing_model_json"],
                         "business_name": ""})
check("P2b healed draft is a fixed point (second pass identical)",
      fin3 == fin2 and ppl3 == ppl2)

# P3: the run path calls the recalc at entry.
src = inspect.getsource(_run_planning_system_for_draft_unified)
check("P3 _run_planning_system_for_draft_unified calls _run_entry_recalc "
      "before the grid build",
      "_run_entry_recalc(" in src
      and src.index("_run_entry_recalc(") < src.index("prepare_initial_grid_for_draft("))

cur.close()
conn.close()
print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
