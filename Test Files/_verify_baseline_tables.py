"""Verify the three new baseline tables and show concrete examples."""
import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)

print("=== Table existence + row counts ===")
for t in (
    "post_intake_industry_baseline_lookup",
    "post_intake_industry_metric_registry",
    "post_intake_industry_baseline_coverage_audit",
):
    cur.execute(f"SELECT COUNT(*) AS n FROM `{t}`")
    print(f"  {t}: {cur.fetchone()['n']} rows")

print("\n=== Concrete example: ValueMart Superstores (NAICS 455211) ===")
print("    What does the cascade resolve for each critical metric?")
cur.execute(
    """
    SELECT metric_key, naics_code, naics_level, benchmark_min, benchmark_target,
           benchmark_max, data_source, sample_size, confidence_tier
    FROM post_intake_industry_baseline_lookup
    WHERE metric_key IN (
        'effective_tax_rate', 'payroll_percent_of_revenue', 'revenue_per_fte',
        'fte_per_million_revenue', 'cogs_percent_of_revenue', 'ar_days_dso',
        'capex_percent_of_revenue', 'avg_wage_per_fte', 'ebitda_margin',
        'rent_percent_of_revenue', 'lease_percent_of_revenue',
        'occupancy_total_percent_of_revenue'
    )
    AND naics_code IN ('455211', '45521', '4552', '455', '45', '*')
    OR (metric_key IN ('rent_percent_of_revenue','lease_percent_of_revenue','occupancy_total_percent_of_revenue')
        AND naics_code IN ('45','*'))
    ORDER BY metric_key, naics_level DESC
    """
)
prev = None
for r in cur.fetchall():
    line = (
        f"  {r['metric_key']:35} naics={r['naics_code']:6} L{r['naics_level']} "
        f"target={float(r['benchmark_target'] or 0):>14,.4f} "
        f"src={r['data_source']:18} n={r['sample_size'] or 0:>6} {r['confidence_tier']}"
    )
    if r["metric_key"] != prev:
        print()
        prev = r["metric_key"]
    print(line)

print("\n=== Coverage audit summary ===")
cur.execute(
    """
    SELECT metric_key, metric_domain, total_rows,
           level_6_rows, level_5_rows, level_4_rows,
           level_3_rows, level_2_rows, generic_default_rows,
           highest_level_with_coverage, primary_data_source
    FROM post_intake_industry_baseline_coverage_audit
    ORDER BY metric_domain, metric_key
    """
)
print(f"  {'metric':40} {'domain':15} {'tot':>5} {'L6':>4} {'L5':>4} {'L4':>4} {'L3':>4} {'L2':>4} {'gen':>3} {'src':22}")
for r in cur.fetchall():
    print(
        f"  {r['metric_key']:40} {r['metric_domain']:15} "
        f"{r['total_rows']:>5} {r['level_6_rows']:>4} {r['level_5_rows']:>4} "
        f"{r['level_4_rows']:>4} {r['level_3_rows']:>4} {r['level_2_rows']:>4} "
        f"{r['generic_default_rows']:>3} {(r['primary_data_source'] or '-'):22}"
    )

print("\n=== Metric registry summary ===")
cur.execute(
    """
    SELECT metric_domain, COUNT(*) AS n,
           SUM(CASE WHEN governs_model_input_lever IS NOT NULL THEN 1 ELSE 0 END) AS levered
    FROM post_intake_industry_metric_registry
    GROUP BY metric_domain
    ORDER BY metric_domain
    """
)
for r in cur.fetchall():
    print(f"  {r['metric_domain']:20} metrics={r['n']:>3}  levered={r['levered']:>3}")

conn.close()
