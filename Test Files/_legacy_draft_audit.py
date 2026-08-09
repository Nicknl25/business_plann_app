"""LEGACY-DRAFT AUDIT (Nick's confidence question): do the live-truth
guarantees hold on drafts created BEFORE the architecture shipped?

Sweeps every non-phantom draft for each latent-gap class:
  A. ops FORK - single-product models whose flat driver fields disagree
     with the product row (the defect-#5 class, at rest)
  B. payroll trio incoherence - baseline/current/total disagree, or the
     people-derived rollup disagrees with the stored trio (CW-023 class
     at rest; a supervisor rerun builds on stored fields with NO Recalc)
  C. unfolded payroll_adjustment != 0 (folds on next turn; zero engine
     readers, listed for completeness)
  D. band stamps missing labor_intensity_class (wall dead until the
     next gate entry backfills)
  E. cogs_basis population (statement-durability applies only to
     figures stated after 1e2d7a5 - Nick-ruled legacy=ratio)
Read-only.
"""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, business_name, status, planning_run_status, "
    "operating_model_json, people_json, financials_json, "
    "JSON_LENGTH(messages_json) AS msgs, updated_at "
    "FROM intake_consult_drafts")
rows = cur.fetchall()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


DRIVERS = ("unit_price", "units_per_week_capacity",
           "units_per_period_capacity", "utilization_rate")
fork, trio_bad, rollup_bad, adj, no_class, basis_stats = [], [], [], [], [], {}
total = 0
for r in rows:
    if not r["msgs"]:
        continue  # phantom page-load shells
    total += 1
    did = r["draft_id"][:8]
    tag = f"{did} {r['business_name'] or '?'} [{r['status']}/{r['planning_run_status']}]"
    ops = json.loads(r["operating_model_json"] or "{}")
    ppl = json.loads(r["people_json"] or "{}")
    fin = json.loads(r["financials_json"] or "{}")

    # A. ops fork
    lms = ops.get("lob_models") or []
    if len(lms) == 1 and isinstance(lms[0], dict):
        prods = lms[0].get("products") or []
        if len(prods) == 1 and isinstance(prods[0], dict):
            p = prods[0]
            for k in DRIVERS:
                fv, pv = _f(ops.get(k)), _f(p.get(k))
                if fv is not None and pv is not None and abs(fv - pv) > max(0.01, 0.001 * abs(pv)):
                    fork.append(f"{tag}: {k} flat={fv} product={pv}")

    # B. trio coherence
    trio = [_f(fin.get(k)) for k in
            ("baseline_payroll_year1", "current_payroll", "payroll_total_year1")]
    present = [v for v in trio if v is not None]
    if len({round(v, 2) for v in present}) > 1:
        trio_bad.append(f"{tag}: trio={trio}")
    # people rollup vs trio (people with substance only)
    people_rows = ppl.get("people") or []
    rest = _f(ppl.get("rest_of_team_payroll_year1")) or 0.0
    wages = [(_f(p.get("annual_wage")) or 0.0) for p in people_rows if isinstance(p, dict)]
    if (people_rows or rest > 0) and present:
        expected = sum(wages) + rest
        stored = present[-1]
        if expected > 0 and abs(expected - stored) > max(1.0, 0.01 * expected):
            rollup_bad.append(f"{tag}: people-derived={expected:,.0f} stored={stored:,.0f}")

    # C. unfolded adjustment
    a = _f(fin.get("payroll_adjustment"))
    if a is not None and abs(a) > 0.005:
        adj.append(f"{tag}: adj={a}")

    # D. class-less band stamps
    st = fin.get("_coherence") or {}
    mbj = st.get("margin_band_judgment")
    if isinstance(mbj, dict) and not mbj.get("labor_intensity_class"):
        no_class.append(tag)

    # E. cogs basis
    b = str(fin.get("cogs_basis") or "untagged")
    basis_stats[b] = basis_stats.get(b, 0) + 1

print(f"drafts audited (non-phantom): {total}\n")
for label, items in (
    ("A. OPS FORK (flat vs product row)", fork),
    ("B1. PAYROLL TRIO internally incoherent", trio_bad),
    ("B2. PEOPLE ROLLUP vs stored trio", rollup_bad),
    ("C. UNFOLDED payroll_adjustment", adj),
    ("D. BAND STAMP w/o labor class (wall off until next gate entry)", no_class),
):
    print(f"{label}: {len(items)}")
    for it in items[:15]:
        print(f"   {it}")
    if len(items) > 15:
        print(f"   ... +{len(items) - 15} more")
print(f"E. cogs_basis population: {basis_stats}")
cur.close()
conn.close()
