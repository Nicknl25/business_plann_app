"""ABLATION BATCH C — C3 (wage positioning multiplier) + C4 (min_annual_wage /
wage inflation / benchmark ratio) on Peachtree's real shipped payroll schedule."""
import json, sys
from collections import defaultdict
import mysql.connector

DRAFT = "f62e846077ef40ca96f37edafb97a6fe"
conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!", database="biz_plan_revert")
cur = conn.cursor(dictionary=True)
cur.execute("SELECT payroll_headcount FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,))
ph = json.loads(cur.fetchone()["payroll_headcount"])
rows = ph.get("rows") or []

print("=== C3: wage positioning multiplier on THIS run ===")
mults = defaultdict(int)
sources = defaultdict(int)
for row in rows:
    mults[(row.get("staffing_class"), row.get("wage_positioning_multiplier"))] += 1
    sources[row.get("wage_source")] += 1
print("  (staffing_class, wage_positioning_multiplier) counts:", dict(mults))
print("  wage_source counts:", dict(sources))
print(f"  schedule root: tier={ph.get('wage_positioning_tier')} multiplier={ph.get('wage_positioning_multiplier')}")
guard_q1 = next(r for r in rows if r.get("staffing_class") == "supporting_staff" and r.get("quarter_index") == 1)
w = guard_q1["annual_wage"]
print(f"  guards Q1 wage (mult=1.0 actual): {w:,}; identical to mult-ablated-1.0. Counterfactual tiers: "
      f"market-min(1.10)={round(w*1.10):,}, premium-min(1.35)={round(w*1.35):,}, specialized-min(1.70)={round(w*1.70):,}")

print("\n=== C4: wage constants on THIS run ===")
by_title_year = defaultdict(dict)
for row in rows:
    q = int(row.get("quarter_index") or 0)
    year = (q - 1) // 4 + 1
    key = (row.get("position_title"), row.get("staffing_class"))
    by_title_year[key][year] = row.get("annual_wage")
print("  annual_wage by title by year (3%/yr inflation check):")
for key, years in by_title_year.items():
    seq = [years.get(y) for y in sorted(years)]
    ratios = [round(seq[i+1]/seq[i], 4) for i in range(len(seq)-1) if seq[i]]
    print(f"    {key}: {seq}  yr-over-yr ratios {ratios}")
min_wage_hits = [r for r in rows if int(r.get("annual_wage") or 0) == 25000]
below = [r for r in rows if 0 < int(r.get("annual_wage") or 0) < 25000]
floor_adapted = [r for r in rows if "floor_adapted" in str(r.get("wage_source") or "")]
print(f"  rows with annual_wage == 25000: {len(min_wage_hits)}  |  below 25000: {len(below)}  |  wage_source contains 'floor_adapted': {len(floor_adapted)}")

q20_guard = next(r for r in rows if r.get("staffing_class") == "supporting_staff" and r.get("quarter_index") == 20)
base = guard_q1["annual_wage"]
print(f"  guards wage Q1={base:,} Q20={q20_guard['annual_wage']:,} (= Q1 x 1.03^4 = {round(base*1.03**4):,})")
for rate, label in [(0.0, "ablate rate=0"), (0.06, "ablate rate=2x (0.06)")]:
    q20 = round(base * (1+rate)**4)
    print(f"  {label}: Q20 guard wage {q20:,} (delta {q20 - q20_guard['annual_wage']:+,} per FTE-year)")

# Aggregate payroll effect of inflation ablation: recompute wage cost with wages rebased
tot_now, tot_flat, tot_2x = 0.0, 0.0, 0.0
for row in rows:
    q = int(row.get("quarter_index") or 0)
    yoff = (q - 1) // 4
    wc = float(row.get("quarterly_wage_cost") or 0)
    infl = 1.03 ** yoff
    tot_now += wc
    tot_flat += wc / infl
    tot_2x += wc / infl * (1.06 ** yoff)
b = 1.22
print(f"  20q loaded payroll: rate 0.03 (real) = {round(tot_now*b):,} | rate 0 = {round(tot_flat*b):,} ({round((tot_flat/tot_now-1)*100,1)}%) | rate 0.06 = {round(tot_2x*b):,} (+{round((tot_2x/tot_now-1)*100,1)}%)")

print("\n=== C3 live frequency across recent drafts with a payroll schedule ===")
cur.execute("""SELECT draft_id, business_name, payroll_headcount FROM intake_consult_drafts
               WHERE payroll_headcount IS NOT NULL AND payroll_headcount != '' ORDER BY updated_at DESC LIMIT 40""")
seen = 0
tier_counts = defaultdict(int)
for r in cur.fetchall():
    try:
        p = json.loads(r["payroll_headcount"])
    except Exception:
        continue
    tier = p.get("wage_positioning_tier"); mult = p.get("wage_positioning_multiplier")
    if not tier and not mult:
        continue
    seen += 1
    tier_counts[(tier, mult)] += 1
print(f"  {seen} recent drafts with schedules; (tier, multiplier) counts: {dict(tier_counts)}")
conn.close()
