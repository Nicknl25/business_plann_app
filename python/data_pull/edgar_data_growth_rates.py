"""Aggregate sec_edgar_facts (per-concept-per-period normalized) into
per-firm-per-quarter rows in `industry_metrics_edgar`, mirroring the
schema written by alpha_data_growth_rates.py to industry_metrics_alpha.

Design parallels alpha_data_growth_rates.py exactly: same target columns,
same ratio definitions, same insert path. Differences:

  * Pivots sec_edgar_facts.concept_name into wide form by
    (cik, fp_end_at), picking the latest accession_number per concept
    when a period has multiple amendments.
  * Concept-to-field map handles EDGAR's redundancy (Revenues vs
    RevenueFromContractWithCustomerExcludingAssessedTax; CostOfRevenue
    vs CostOfGoodsAndServicesSold; Depreciation vs DepreciationAndAmortization)
    by picking the first non-null in a documented priority order.
  * Symbol column: ticker if EDGAR has one for the CIK, else `EDGAR_<cik>`.
  * No cross-source dedupe: Alpha and EDGAR live in separate tables, so
    a firm can appear in both. The runtime alternating-fallback resolver
    is what prefers EDGAR over Alpha at each NAICS level. INSERT IGNORE
    on (symbol, fiscalDateEnding) handles intra-EDGAR re-runs.
  * Sanity guard: every computed ratio is bounds-checked. Out-of-range
    values are nulled (the row still inserts with valid columns), and
    rows whose total_revenue is non-positive or null are dropped entirely.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector
from dotenv import load_dotenv


load_dotenv()


MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")
MYSQL_PORT = int(os.getenv("MYSQL_PORT") or 3306)


def get_conn():
  return mysql.connector.connect(
    host=MYSQL_HOST,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DB,
    port=MYSQL_PORT,
  )


# Concepts we read from sec_edgar_facts. The order in each list is the
# priority for fallback when a period has multiple options.
REVENUE_CONCEPTS = (
  "RevenueFromContractWithCustomerExcludingAssessedTax",
  "Revenues",
)
COGS_CONCEPTS = (
  "CostOfGoodsAndServicesSold",
  "CostOfRevenue",
)
SGA_CONCEPTS = (
  "SellingGeneralAndAdministrativeExpense",
  "GeneralAndAdministrativeExpense",
)
RND_CONCEPTS = ("ResearchAndDevelopmentExpense",)
GROSS_PROFIT_CONCEPTS = ("GrossProfit",)
OPERATING_INCOME_CONCEPTS = ("OperatingIncomeLoss",)
NET_INCOME_CONCEPTS = ("NetIncomeLoss",)
DEPRECIATION_CONCEPTS = (
  "DepreciationAndAmortization",
  "Depreciation",
)
INTEREST_CONCEPTS = ("InterestExpense",)
CAPEX_CONCEPTS = ("PaymentsToAcquirePropertyPlantAndEquipment",)

# Balance-sheet (instant) concepts.
ASSETS_CONCEPTS = ("Assets",)
ASSETS_CURRENT_CONCEPTS = ("AssetsCurrent",)
LIAB_CONCEPTS = ("Liabilities",)
LIAB_CURRENT_CONCEPTS = ("LiabilitiesCurrent",)
EQUITY_CONCEPTS = ("StockholdersEquity",)
AR_CONCEPTS = ("AccountsReceivableNetCurrent",)
AP_CONCEPTS = ("AccountsPayableCurrent",)
INVENTORY_CONCEPTS = ("InventoryNet",)
PPE_CONCEPTS = ("PropertyPlantAndEquipmentNet",)
LTD_NONCURRENT_CONCEPTS = ("LongTermDebtNoncurrent",)
LTD_CURRENT_CONCEPTS = ("LongTermDebtCurrent",)


# All concepts we'll read in one query.
ALL_CONCEPTS: Tuple[str, ...] = tuple(set(
  REVENUE_CONCEPTS + COGS_CONCEPTS + SGA_CONCEPTS + RND_CONCEPTS
  + GROSS_PROFIT_CONCEPTS + OPERATING_INCOME_CONCEPTS + NET_INCOME_CONCEPTS
  + DEPRECIATION_CONCEPTS + INTEREST_CONCEPTS + CAPEX_CONCEPTS
  + ASSETS_CONCEPTS + ASSETS_CURRENT_CONCEPTS
  + LIAB_CONCEPTS + LIAB_CURRENT_CONCEPTS + EQUITY_CONCEPTS
  + AR_CONCEPTS + AP_CONCEPTS + INVENTORY_CONCEPTS + PPE_CONCEPTS
  + LTD_NONCURRENT_CONCEPTS + LTD_CURRENT_CONCEPTS
))


# --- Schema setup ----------------------------------------------------------


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS industry_metrics_edgar (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  symbol VARCHAR(20),
  naics_code VARCHAR(10),
  market_cap BIGINT,
  cap_category VARCHAR(10),
  fiscalDateEnding DATE,
  total_revenue DECIMAL(22,4),
  revenue_growth_q DECIMAL(18,6),
  gross_margin_q DECIMAL(18,6),
  operating_margin_q DECIMAL(18,6),
  ebit_margin_q DECIMAL(18,6),
  ebitda_margin_q DECIMAL(18,6),
  net_margin_q DECIMAL(18,6),
  sga_percent DECIMAL(18,6),
  rnd_percent DECIMAL(18,6),
  cogs_percent DECIMAL(18,6),
  dso DECIMAL(18,6),
  dpo DECIMAL(18,6),
  inventory_days DECIMAL(18,6),
  ccc DECIMAL(18,6),
  current_ratio DECIMAL(18,6),
  quick_ratio DECIMAL(18,6),
  debt_to_equity DECIMAL(18,6),
  debt_to_assets DECIMAL(18,6),
  debt_to_ebitda DECIMAL(18,6),
  interest_coverage DECIMAL(18,6),
  capex_percent_revenue DECIMAL(18,6),
  depreciation_percent_revenue DECIMAL(18,6),
  roa DECIMAL(18,6),
  roe DECIMAL(18,6),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY u_symbol_period (symbol, fiscalDateEnding),
  INDEX idx_naics (naics_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def ensure_table(cursor) -> None:
  cursor.execute(CREATE_TABLE_SQL)


# --- Helpers ---------------------------------------------------------------


def to_float(x: Any) -> Optional[float]:
  if x is None:
    return None
  try:
    return float(x)
  except Exception:
    return None


def div(a: Any, b: Any) -> Optional[float]:
  af = to_float(a)
  bf = to_float(b)
  if af is None or bf is None or bf == 0:
    return None
  return af / bf


def first_non_null(d: Dict[str, Any], concepts: Tuple[str, ...]) -> Optional[float]:
  for c in concepts:
    v = d.get(c)
    if v is not None:
      return to_float(v)
  return None


def cap_category_from_revenue(annual_rev: Optional[float]) -> Optional[str]:
  """Approximate cap_category from trailing annual revenue. We don't have
  market cap for EDGAR-only firms; revenue is the next best public signal.

  Thresholds chosen to roughly mirror Alpha's market_cap-based bands when
  applied to public-comp medians in the existing cap_category distribution.
  """
  if annual_rev is None:
    return None
  if annual_rev < 250_000_000:
    return "small"
  if annual_rev < 2_000_000_000:
    return "mid"
  return "large"


# --- Sanity bounds ---------------------------------------------------------
#
# (lower, upper). A computed ratio outside its bound is set to None.
# Rows with non-positive total_revenue are dropped (unrecoverable).

_BOUNDS: Dict[str, Tuple[float, float]] = {
  "gross_margin_q":          (-1.0, 1.0),
  "operating_margin_q":      (-2.0, 1.0),
  "ebit_margin_q":           (-2.0, 1.0),
  "ebitda_margin_q":         (-2.0, 1.5),
  "net_margin_q":            (-2.0, 1.5),
  "sga_percent":             (0.0, 1.5),
  "rnd_percent":             (0.0, 2.0),
  "cogs_percent":            (0.0, 1.5),
  "dso":                     (0.0, 365.0),
  "dpo":                     (0.0, 365.0),
  "inventory_days":          (0.0, 730.0),
  "ccc":                     (-365.0, 730.0),
  "current_ratio":           (0.0, 50.0),
  "quick_ratio":             (0.0, 50.0),
  "debt_to_equity":          (-50.0, 50.0),
  "debt_to_assets":          (0.0, 5.0),
  "debt_to_ebitda":          (-50.0, 50.0),
  "interest_coverage":       (-100.0, 1000.0),
  "capex_percent_revenue":   (0.0, 1.0),
  "depreciation_percent_revenue": (0.0, 1.0),
  "roa":                     (-2.0, 1.0),
  "roe":                     (-50.0, 50.0),
  "revenue_growth_q":        (-1.0, 50.0),
}


def clip_or_null(name: str, val: Optional[float]) -> Optional[float]:
  if val is None:
    return None
  bounds = _BOUNDS.get(name)
  if bounds is None:
    return val
  lo, hi = bounds
  if val < lo or val > hi:
    return None
  return val


# --- Main aggregation ------------------------------------------------------


def fetch_edgar_facts_grouped(cursor) -> Dict[Tuple[str, date], Dict[str, Any]]:
  """Pivot sec_edgar_facts into {(cik, fp_end_at): {concept: value, ...,
  '_naics': N, '_ticker': T}} for CIKs that have NAICS-6.

  When a (cik, fp_end_at, concept) has multiple rows (amendments), the
  highest accession_number wins (lex-sortable; later filings have higher
  accession numbers).
  """
  placeholders = ",".join(["%s"] * len(ALL_CONCEPTS))
  sql = f"""
    SELECT
      f.cik, f.ticker, f.naics_code,
      f.fp_end_at, f.concept_name, f.value, f.accession_number
    FROM sec_edgar_facts f
    WHERE f.naics_code IS NOT NULL AND CHAR_LENGTH(f.naics_code) = 6
      AND f.fp_end_at IS NOT NULL
      AND f.value IS NOT NULL
      AND f.concept_name IN ({placeholders})
    ORDER BY f.cik, f.fp_end_at, f.concept_name, f.accession_number DESC
  """
  cursor.execute(sql, ALL_CONCEPTS)

  pivoted: Dict[Tuple[str, date], Dict[str, Any]] = {}
  seen_concept_per_period: Dict[Tuple[str, date, str], bool] = {}
  for cik, ticker, naics, fp_end, concept, value, accn in cursor.fetchall():
    key = (cik, fp_end)
    if (cik, fp_end, concept) in seen_concept_per_period:
      continue  # earlier (higher accession) row already taken
    seen_concept_per_period[(cik, fp_end, concept)] = True
    bucket = pivoted.setdefault(key, {})
    bucket[concept] = value
    bucket.setdefault("_cik", cik)
    bucket.setdefault("_naics", naics)
    if ticker and not bucket.get("_ticker"):
      bucket["_ticker"] = ticker
  return pivoted


def compute_row_for_period(
  *,
  cik: str,
  ticker: Optional[str],
  naics: str,
  fp_end: date,
  facts: Dict[str, Any],
  prev_facts: Optional[Dict[str, Any]],
  prev_fp_end: Optional[date],
  trailing_4q_revenue: Optional[float],
) -> Optional[List[Any]]:
  """Compute a single industry_metrics_raw row from one period's pivoted
  EDGAR facts. Returns None if total_revenue is invalid.

  Period_days = (fp_end - prev_fp_end) if a prior period is available, else
  defaults to 90 (a calendar quarter).
  """
  rev = first_non_null(facts, REVENUE_CONCEPTS)
  if rev is None or rev <= 0:
    return None

  cogs = first_non_null(facts, COGS_CONCEPTS)
  sga = first_non_null(facts, SGA_CONCEPTS)
  rnd = first_non_null(facts, RND_CONCEPTS)
  gross_profit = first_non_null(facts, GROSS_PROFIT_CONCEPTS)
  op_inc = first_non_null(facts, OPERATING_INCOME_CONCEPTS)
  net = first_non_null(facts, NET_INCOME_CONCEPTS)
  dep = first_non_null(facts, DEPRECIATION_CONCEPTS)
  interest = first_non_null(facts, INTEREST_CONCEPTS)
  capex = first_non_null(facts, CAPEX_CONCEPTS)

  ta = first_non_null(facts, ASSETS_CONCEPTS)
  ca = first_non_null(facts, ASSETS_CURRENT_CONCEPTS)
  tl = first_non_null(facts, LIAB_CONCEPTS)
  cl = first_non_null(facts, LIAB_CURRENT_CONCEPTS)
  tse = first_non_null(facts, EQUITY_CONCEPTS)
  ar = first_non_null(facts, AR_CONCEPTS)
  ap = first_non_null(facts, AP_CONCEPTS)
  inv = first_non_null(facts, INVENTORY_CONCEPTS)
  ltd_nc = first_non_null(facts, LTD_NONCURRENT_CONCEPTS) or 0.0
  ltd_c = first_non_null(facts, LTD_CURRENT_CONCEPTS) or 0.0
  ltd = ltd_nc + ltd_c

  # Period length for days metrics. Default to 90 if no prior period.
  if prev_fp_end is not None:
    period_days = (fp_end - prev_fp_end).days
    if period_days <= 0 or period_days > 400:
      period_days = 90
  else:
    period_days = 90

  # Derived
  if gross_profit is None and cogs is not None:
    gross_profit = rev - cogs
  ebit = op_inc
  ebitda = (op_inc + dep) if (op_inc is not None and dep is not None) else None

  # Revenue growth qoq
  prev_rev = first_non_null(prev_facts, REVENUE_CONCEPTS) if prev_facts else None
  rev_growth = ((rev - prev_rev) / prev_rev) if (prev_rev and prev_rev > 0) else None

  # Margins (per quarter)
  gross_margin = div(gross_profit, rev)
  operating_margin = div(op_inc, rev)
  ebit_margin = div(ebit, rev)
  ebitda_margin = div(ebitda, rev)
  net_margin = div(net, rev)
  sga_pct = div(sga, rev)
  rnd_pct = div(rnd, rev)
  cogs_pct = div(cogs, rev)

  # DSO/DPO/InvDays — same convention as alpha_data_growth_rates.py
  dso_raw = div(ar, rev)
  dso = dso_raw * period_days if dso_raw is not None else None
  dpo_raw = div(ap, cogs) if cogs else None
  inv_raw = div(inv, cogs) if cogs else None
  dpo = dpo_raw * period_days if dpo_raw is not None else None
  inv_days = inv_raw * period_days if inv_raw is not None else None
  ccc = (
    dso + inv_days - dpo
    if (dso is not None and dpo is not None and inv_days is not None) else None
  )

  current_ratio = div(ca, cl)
  quick_ratio = div((ca or 0) - (inv or 0), cl)
  debt_to_equity = div(tl, tse)
  debt_to_assets = div(tl, ta)
  debt_to_ebitda = div(ltd, ebitda) if ebitda else None
  interest_coverage = div(ebit, interest) if interest else None
  capex_pct = div(capex, rev)
  dep_pct = div(dep, rev)
  roa = div(net, ta)
  roe = div(net, tse)

  # Sanity-bound everything.
  metrics = {
    "revenue_growth_q": rev_growth,
    "gross_margin_q": gross_margin,
    "operating_margin_q": operating_margin,
    "ebit_margin_q": ebit_margin,
    "ebitda_margin_q": ebitda_margin,
    "net_margin_q": net_margin,
    "sga_percent": sga_pct,
    "rnd_percent": rnd_pct,
    "cogs_percent": cogs_pct,
    "dso": dso,
    "dpo": dpo,
    "inventory_days": inv_days,
    "ccc": ccc,
    "current_ratio": current_ratio,
    "quick_ratio": quick_ratio,
    "debt_to_equity": debt_to_equity,
    "debt_to_assets": debt_to_assets,
    "debt_to_ebitda": debt_to_ebitda,
    "interest_coverage": interest_coverage,
    "capex_percent_revenue": capex_pct,
    "depreciation_percent_revenue": dep_pct,
    "roa": roa,
    "roe": roe,
  }
  for k in list(metrics.keys()):
    metrics[k] = clip_or_null(k, metrics[k])

  symbol = (ticker or "").strip().upper() or f"EDGAR_{cik}"
  cap_cat = cap_category_from_revenue(trailing_4q_revenue)

  return [
    symbol, naics, None, cap_cat, fp_end,
    rev, metrics["revenue_growth_q"],
    metrics["gross_margin_q"], metrics["operating_margin_q"], metrics["ebit_margin_q"],
    metrics["ebitda_margin_q"], metrics["net_margin_q"],
    metrics["sga_percent"], metrics["rnd_percent"], metrics["cogs_percent"],
    metrics["dso"], metrics["dpo"], metrics["inventory_days"], metrics["ccc"],
    metrics["current_ratio"], metrics["quick_ratio"],
    metrics["debt_to_equity"], metrics["debt_to_assets"],
    metrics["debt_to_ebitda"], metrics["interest_coverage"],
    metrics["capex_percent_revenue"], metrics["depreciation_percent_revenue"],
    metrics["roa"], metrics["roe"],
  ]


INSERT_SQL = """
  INSERT IGNORE INTO industry_metrics_edgar (
    symbol, naics_code, market_cap, cap_category, fiscalDateEnding,
    total_revenue, revenue_growth_q,
    gross_margin_q, operating_margin_q, ebit_margin_q,
    ebitda_margin_q, net_margin_q,
    sga_percent, rnd_percent, cogs_percent,
    dso, dpo, inventory_days, ccc,
    current_ratio, quick_ratio,
    debt_to_equity, debt_to_assets,
    debt_to_ebitda, interest_coverage,
    capex_percent_revenue, depreciation_percent_revenue,
    roa, roe
  )
  VALUES (
    %s, %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s,
    %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s,
    %s, %s,
    %s, %s,
    %s, %s
  )
"""


def main() -> int:
  conn = get_conn()
  cur = conn.cursor()
  try:
    print("Ensuring industry_metrics_edgar table exists ...")
    ensure_table(cur)
    conn.commit()

    print("Pivoting sec_edgar_facts into per-(cik, fp_end_at) buckets ...")
    pivoted = fetch_edgar_facts_grouped(cur)
    print(f"  total pivoted (cik, period) buckets: {len(pivoted)}")

    # Group by CIK to compute period-over-period revenue growth.
    by_cik: Dict[str, List[Tuple[date, Dict[str, Any]]]] = {}
    for (cik, fp_end), bucket in pivoted.items():
      by_cik.setdefault(cik, []).append((fp_end, bucket))
    for cik in by_cik:
      by_cik[cik].sort(key=lambda kv: kv[0])

    rows_to_insert: List[List[Any]] = []
    rows_dropped_no_revenue = 0
    firms_inserted: set = set()
    for cik, periods in by_cik.items():
      # Compute trailing 4-period revenue per period for cap_category proxy.
      revenues = []
      for fp_end, bucket in periods:
        rev = first_non_null(bucket, REVENUE_CONCEPTS)
        revenues.append(rev)
      for i, (fp_end, bucket) in enumerate(periods):
        prev_fp_end, prev_bucket = (None, None)
        if i > 0:
          prev_fp_end, prev_bucket = periods[i - 1]
        # trailing 4Q revenue = sum of last 4 quarter revenues if available
        window = revenues[max(0, i - 3): i + 1]
        valid = [r for r in window if r is not None and r > 0]
        ttm_rev = sum(valid) if valid else (
          revenues[i] * 4 if revenues[i] else None
        )
        ticker = bucket.get("_ticker")
        naics = bucket.get("_naics")
        if not naics:
          continue
        row = compute_row_for_period(
          cik=cik, ticker=ticker, naics=naics, fp_end=fp_end,
          facts=bucket, prev_facts=prev_bucket, prev_fp_end=prev_fp_end,
          trailing_4q_revenue=ttm_rev,
        )
        if row is None:
          rows_dropped_no_revenue += 1
          continue
        symbol = row[0]
        rows_to_insert.append(row)
        firms_inserted.add(symbol)

    print(f"\nAggregation summary:")
    print(f"  rows to insert:               {len(rows_to_insert)}")
    print(f"  rows dropped (no revenue):    {rows_dropped_no_revenue}")
    print(f"  distinct firms:               {len(firms_inserted)}")

    if rows_to_insert:
      print("\nInserting in chunks of 500 ...")
      total_inserted = 0
      for i in range(0, len(rows_to_insert), 500):
        chunk = rows_to_insert[i:i + 500]
        cur.executemany(INSERT_SQL, chunk)
        total_inserted += cur.rowcount
        conn.commit()
        if (i // 500) % 10 == 0 and i > 0:
          print(f"  {i}/{len(rows_to_insert)} ...")
      print(f"  Inserted (rowcount): {total_inserted}")
  finally:
    cur.close()
    conn.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
