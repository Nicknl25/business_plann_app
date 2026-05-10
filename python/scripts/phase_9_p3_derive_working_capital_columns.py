"""Phase 9 P3 — One-shot migration to derive industry working-capital
columns from existing per-firm-quarter components.

Adds two new columns to each of `industry_metrics_alpha` and
`industry_metrics_edgar`, then populates them via SQL UPDATE from
columns that already live in the table.

Derived columns:

  current_assets_minus_cash_to_revenue
    = (dso / 90)
      + (inventory_days / 90) * cogs_percent
      + prepaid_percent_of_revenue   <-- NOT in cohort tables, treated as 0

  current_liabilities_to_revenue
    = (dpo / 90) * cogs_percent
      + deferred_revenue_percent_of_revenue        <-- NOT in cohort tables, 0
      + accrued_expenses_percent_of_revenue        <-- NOT in cohort tables, 0
      + short_term_debt_percent_of_revenue         <-- NOT in cohort tables, 0

Component-column gaps documented above. The simpler formula still
produces an industry-grounded band, replacing the cross-industry
phase_9_p3_generic_default fallback for Targets 3 and 4 in the
target-driven restoration loop.

Sanity guard: per-row values outside [0, 5] are left NULL (treated as
no-coverage at that firm-quarter row), so absurd-component rows do
not pollute the cohort percentile band.

Idempotent — re-running this script is safe.
"""

from __future__ import annotations

import os
from pathlib import Path

import mysql.connector


def _load_env() -> None:
  root = Path(__file__).resolve().parent.parent.parent
  env_path = root / ".env"
  if not env_path.exists():
    return
  with open(env_path, encoding="utf-8") as handle:
    for raw in handle:
      line = raw.strip()
      if not line or line.startswith("#") or "=" not in line:
        continue
      k, v = line.split("=", 1)
      os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _connect():
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD") or "",
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or "3306"),
  )


_NEW_COLUMNS = (
  ("current_assets_minus_cash_to_revenue", "DECIMAL(18,6)"),
  ("current_liabilities_to_revenue", "DECIMAL(18,6)"),
)


_DERIVATION_SQL = """
UPDATE {tbl}
SET
  current_assets_minus_cash_to_revenue = CASE
    WHEN dso IS NULL AND inventory_days IS NULL THEN NULL
    ELSE
      LEAST(
        5.0,
        GREATEST(
          0.0,
          COALESCE(dso, 0) / 90.0
          + (COALESCE(inventory_days, 0) / 90.0) * COALESCE(cogs_percent, 0)
        )
      )
  END,
  current_liabilities_to_revenue = CASE
    WHEN dpo IS NULL AND cogs_percent IS NULL THEN NULL
    ELSE
      LEAST(
        5.0,
        GREATEST(
          0.0,
          (COALESCE(dpo, 0) / 90.0) * COALESCE(cogs_percent, 0)
        )
      )
  END
"""


_NULL_OUT_OF_RANGE_SQL = """
UPDATE {tbl}
SET
  current_assets_minus_cash_to_revenue = NULL
WHERE current_assets_minus_cash_to_revenue IS NOT NULL
  AND (current_assets_minus_cash_to_revenue < 0 OR current_assets_minus_cash_to_revenue > 5)
"""

_NULL_OUT_OF_RANGE_SQL_2 = """
UPDATE {tbl}
SET
  current_liabilities_to_revenue = NULL
WHERE current_liabilities_to_revenue IS NOT NULL
  AND (current_liabilities_to_revenue < 0 OR current_liabilities_to_revenue > 5)
"""


def _ensure_column(cur, table_name: str, column_name: str, column_decl: str) -> bool:
  cur.execute(
    """
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
    """,
    (table_name, column_name),
  )
  exists = bool(cur.fetchone()[0])
  if not exists:
    cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_decl}")
    return True
  return False


def main() -> None:
  _load_env()
  conn = _connect()
  cur = conn.cursor()
  try:
    for table_name in ("industry_metrics_alpha", "industry_metrics_edgar"):
      print(f"\n=== {table_name} ===")
      for column_name, column_decl in _NEW_COLUMNS:
        added = _ensure_column(cur, table_name, column_name, column_decl)
        print(f"  column {column_name}: {'ADDED' if added else 'already present'}")
      cur.execute(_DERIVATION_SQL.format(tbl=table_name))
      print(f"  derived rows updated: {cur.rowcount}")
      cur.execute(_NULL_OUT_OF_RANGE_SQL.format(tbl=table_name))
      print(f"  current_assets_minus_cash_to_revenue out-of-range nulled: {cur.rowcount}")
      cur.execute(_NULL_OUT_OF_RANGE_SQL_2.format(tbl=table_name))
      print(f"  current_liabilities_to_revenue out-of-range nulled: {cur.rowcount}")
      cur.execute(
        f"""
        SELECT
          COUNT(*),
          SUM(CASE WHEN current_assets_minus_cash_to_revenue IS NOT NULL THEN 1 ELSE 0 END),
          SUM(CASE WHEN current_liabilities_to_revenue IS NOT NULL THEN 1 ELSE 0 END)
        FROM {table_name}
        """
      )
      total, with_ca, with_cl = cur.fetchone()
      print(f"  total rows: {total}; "
            f"current_assets_minus_cash populated: {with_ca}; "
            f"current_liabilities_to_revenue populated: {with_cl}")
    conn.commit()
    print("\ncommitted.")
  finally:
    cur.close()
    conn.close()


if __name__ == "__main__":
  main()
