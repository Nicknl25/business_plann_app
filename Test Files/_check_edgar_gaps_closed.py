"""Verify the EDGAR-closed gaps for ValueMart and a SaaS NAICS code."""
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

print("\n=== Closed gap: prepaid_expenses_percent_of_revenue ===")
print("    ValueMart NAICS 455211 cascade:")
cur.execute(
    """
    SELECT naics_code, naics_level, benchmark_min, benchmark_target, benchmark_max,
           data_source, sample_size, confidence_tier
    FROM post_intake_industry_baseline_lookup
    WHERE metric_key = 'prepaid_expenses_percent_of_revenue'
      AND naics_code IN ('455211','45521','4552','455','45','*')
    ORDER BY naics_level DESC, data_source
    """
)
for r in cur.fetchall():
    print(
        f"  naics={r['naics_code']:6} L{r['naics_level']} "
        f"min={float(r['benchmark_min'] or 0):.4f} "
        f"target={float(r['benchmark_target'] or 0):.4f} "
        f"max={float(r['benchmark_max'] or 0):.4f} "
        f"src={r['data_source']:18} n={r['sample_size'] or 0:>5} {r['confidence_tier']}"
    )

print("\n=== Closed gap: deferred_revenue_percent_of_revenue ===")
print("    Software/SaaS NAICS 511210 (Software Publishers):")
cur.execute(
    """
    SELECT naics_code, naics_level, benchmark_min, benchmark_target, benchmark_max,
           data_source, sample_size, confidence_tier
    FROM post_intake_industry_baseline_lookup
    WHERE metric_key = 'deferred_revenue_percent_of_revenue'
      AND naics_code IN ('511210','51121','5112','511','51','*')
    ORDER BY naics_level DESC, data_source
    """
)
for r in cur.fetchall():
    print(
        f"  naics={r['naics_code']:6} L{r['naics_level']} "
        f"min={float(r['benchmark_min'] or 0):.4f} "
        f"target={float(r['benchmark_target'] or 0):.4f} "
        f"max={float(r['benchmark_max'] or 0):.4f} "
        f"src={r['data_source']:18} n={r['sample_size'] or 0:>5} {r['confidence_tier']}"
    )

print("\n=== New metric: marketing_percent_of_revenue (SEC EDGAR data-backed) ===")
print("    ValueMart NAICS 455211 cascade:")
cur.execute(
    """
    SELECT naics_code, naics_level, benchmark_min, benchmark_target, benchmark_max,
           data_source, sample_size, confidence_tier
    FROM post_intake_industry_baseline_lookup
    WHERE metric_key = 'marketing_percent_of_revenue'
      AND naics_code IN ('455211','45521','4552','455','45','*')
    ORDER BY naics_level DESC, data_source
    """
)
for r in cur.fetchall():
    print(
        f"  naics={r['naics_code']:6} L{r['naics_level']} "
        f"min={float(r['benchmark_min'] or 0):.4f} "
        f"target={float(r['benchmark_target'] or 0):.4f} "
        f"max={float(r['benchmark_max'] or 0):.4f} "
        f"src={r['data_source']:18} n={r['sample_size'] or 0:>5} {r['confidence_tier']}"
    )

print("\n    Software NAICS 511210 marketing cascade:")
cur.execute(
    """
    SELECT naics_code, naics_level, benchmark_min, benchmark_target, benchmark_max,
           data_source, sample_size, confidence_tier
    FROM post_intake_industry_baseline_lookup
    WHERE metric_key = 'marketing_percent_of_revenue'
      AND naics_code IN ('511210','51121','5112','511','51','*')
    ORDER BY naics_level DESC, data_source
    """
)
for r in cur.fetchall():
    print(
        f"  naics={r['naics_code']:6} L{r['naics_level']} "
        f"min={float(r['benchmark_min'] or 0):.4f} "
        f"target={float(r['benchmark_target'] or 0):.4f} "
        f"max={float(r['benchmark_max'] or 0):.4f} "
        f"src={r['data_source']:18} n={r['sample_size'] or 0:>5} {r['confidence_tier']}"
    )

print("\n=== rent_percent_of_revenue (NOW data-backed at NAICS-6 from SEC EDGAR) ===")
print("    Restaurants NAICS 722511 (Full-Service Restaurants):")
cur.execute(
    """
    SELECT naics_code, naics_level, benchmark_min, benchmark_target, benchmark_max,
           data_source, sample_size, confidence_tier
    FROM post_intake_industry_baseline_lookup
    WHERE metric_key = 'rent_percent_of_revenue'
      AND naics_code IN ('722511','72251','7225','722','72','*')
    ORDER BY naics_level DESC, data_source
    """
)
for r in cur.fetchall():
    print(
        f"  naics={r['naics_code']:6} L{r['naics_level']} "
        f"min={float(r['benchmark_min'] or 0):.4f} "
        f"target={float(r['benchmark_target'] or 0):.4f} "
        f"max={float(r['benchmark_max'] or 0):.4f} "
        f"src={r['data_source']:18} n={r['sample_size'] or 0:>5} {r['confidence_tier']}"
    )

print("\n=== Total table summary ===")
cur.execute(
    "SELECT data_source, COUNT(*) AS n, MIN(confidence_tier) AS min_conf, MAX(confidence_tier) AS max_conf "
    "FROM post_intake_industry_baseline_lookup GROUP BY data_source ORDER BY n DESC"
)
for r in cur.fetchall():
    print(
        f"  {r['data_source']:24} n={r['n']:>6}  conf range: {r['min_conf']} -> {r['max_conf']}"
    )

conn.close()
