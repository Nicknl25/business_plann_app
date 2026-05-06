"""Pull XBRL financial concepts from SEC EDGAR into a raw staging table.

This is an OFFLINE data-pull script. It populates `sec_edgar_facts`, which is
later aggregated by the baseline loader into `post_intake_industry_baseline_lookup`.
Production runtime never reads `sec_edgar_facts` directly.

Source: SEC EDGAR XBRL Frames API (https://data.sec.gov/api/xbrl/frames/...).
Public, no auth, but SEC fair-access policy requires a User-Agent header and
caps at ~10 requests/second. We pace at ~7 r/s to stay polite.

Three things this script does:

1. Downloads the SEC ticker -> CIK map (one HTTP call) and joins with our
   existing `alpha_match_naics_industry` table to produce CIK -> NAICS.
2. Iterates over a configurable list of US-GAAP concepts. For each concept,
   pulls the last N calendar quarters via the Frames API (one call per
   period). Frames returns one row per company that reported that concept in
   that period.
3. Inserts each row into `sec_edgar_facts` keyed by
   (cik, concept, fiscal_period, accession_number) for idempotency.
"""
from __future__ import annotations

import os
import sys
import time
import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv
import mysql.connector


load_dotenv()


# --- SEC client config -----------------------------------------------------

SEC_USER_AGENT = (
  "TitheFinancial Business Plan App ignatius.henry@tithefinancial.com"
)
SEC_BASE = "https://data.sec.gov"
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
RATE_LIMIT_SLEEP = 0.15  # seconds between requests; ~7 req/sec
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


_session = requests.Session()
_session.headers.update({
  "User-Agent": SEC_USER_AGENT,
  "Accept-Encoding": "gzip, deflate",
  "Host": "data.sec.gov",
})


def _http_get(url: str, *, host_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
  """GET a URL with retry and rate-limit backoff. Returns JSON or None on 404/non-200."""
  headers = dict(_session.headers)
  if host_override:
    headers["Host"] = host_override
  for attempt in range(MAX_RETRIES):
    try:
      resp = _session.get(url, headers=headers, timeout=HTTP_TIMEOUT)
      if resp.status_code == 200:
        return resp.json()
      if resp.status_code == 404:
        return None  # concept not reported in that period; expected
      if resp.status_code == 429:
        wait = float(resp.headers.get("Retry-After") or RETRY_BACKOFF * (attempt + 1))
        time.sleep(wait)
        continue
      if 500 <= resp.status_code < 600:
        time.sleep(RETRY_BACKOFF * (attempt + 1))
        continue
      print(f"  WARN: HTTP {resp.status_code} on {url}", file=sys.stderr)
      return None
    except requests.RequestException as exc:
      if attempt == MAX_RETRIES - 1:
        print(f"  WARN: giving up on {url}: {exc}", file=sys.stderr)
        return None
      time.sleep(RETRY_BACKOFF * (attempt + 1))
  return None


# --- DB helpers ------------------------------------------------------------


def _conn():
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
    autocommit=False,
  )


CREATE_FACTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sec_edgar_facts (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  cik              VARCHAR(10) NOT NULL,
  ticker           VARCHAR(20) NULL,
  naics_code       VARCHAR(6)  NULL,
  concept_name     VARCHAR(120) NOT NULL,
  taxonomy         VARCHAR(20) NOT NULL DEFAULT 'us-gaap',
  units            VARCHAR(20) NOT NULL DEFAULT 'USD',
  fiscal_period    VARCHAR(20) NOT NULL,
  fiscal_year      SMALLINT NULL,
  fiscal_quarter   TINYINT NULL,
  is_instant       TINYINT(1) NOT NULL DEFAULT 0,
  value            DECIMAL(28,4) NULL,
  accession_number VARCHAR(40) NULL,
  filed_at         DATE NULL,
  form_type        VARCHAR(10) NULL,
  fy_end_at        DATE NULL,
  fp_end_at        DATE NULL,
  pulled_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_fact (cik, concept_name, fiscal_period, accession_number),
  INDEX idx_concept_period (concept_name, fiscal_period),
  INDEX idx_naics_concept  (naics_code, concept_name),
  INDEX idx_cik            (cik)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


# --- Ticker -> CIK -> NAICS map -------------------------------------------


def fetch_sec_ticker_to_cik() -> Dict[str, str]:
  """Download SEC's official ticker-to-CIK list. Returns {TICKER_UPPER: cik_padded10}."""
  payload = _http_get(SEC_TICKER_URL, host_override="www.sec.gov")
  out: Dict[str, str] = {}
  if not isinstance(payload, dict):
    return out
  for _idx, entry in payload.items():
    if not isinstance(entry, dict):
      continue
    ticker = str(entry.get("ticker") or "").strip().upper()
    cik = str(entry.get("cik_str") or entry.get("cik") or "").strip()
    if not ticker or not cik:
      continue
    cik_padded = cik.zfill(10)
    out[ticker] = cik_padded
  return out


def load_ticker_to_naics(conn) -> Dict[str, str]:
  """From alpha_match_naics_industry, return {ticker_upper: naics_6}."""
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT symbol, naics_code "
      "FROM alpha_match_naics_industry "
      "WHERE naics_code IS NOT NULL AND naics_code <> '' "
      "  AND symbol IS NOT NULL AND symbol <> '' "
      "  AND confidence >= 0.7"
    )
    out: Dict[str, str] = {}
    for r in cur.fetchall():
      sym = str(r["symbol"] or "").strip().upper()
      naics = "".join(ch for ch in str(r["naics_code"] or "") if ch.isdigit())
      if sym and len(naics) >= 6:
        out[sym] = naics[:6]
    return out
  finally:
    cur.close()


def build_cik_to_naics_map(conn) -> Dict[str, Dict[str, str]]:
  """Return {cik_padded10: {'ticker': T, 'naics': N}}."""
  print("Downloading SEC ticker -> CIK map ...")
  ticker_to_cik = fetch_sec_ticker_to_cik()
  print(f"  SEC ticker map: {len(ticker_to_cik)} tickers")
  print("Loading ticker -> NAICS from alpha_match_naics_industry ...")
  ticker_to_naics = load_ticker_to_naics(conn)
  print(f"  ticker->NAICS map: {len(ticker_to_naics)} tickers")
  out: Dict[str, Dict[str, str]] = {}
  matched = 0
  for ticker, cik in ticker_to_cik.items():
    naics = ticker_to_naics.get(ticker)
    if not naics:
      continue
    out[cik] = {"ticker": ticker, "naics": naics}
    matched += 1
  print(f"  CIK->NAICS coverage: {matched} CIKs mapped")
  return out


# --- Concept registry ------------------------------------------------------

# Each entry: (concept_name, kind)
#   kind = 'instant'  for balance-sheet point-in-time concepts (period suffix 'I')
#   kind = 'duration' for income/cash-flow flow concepts (no 'I' suffix)
CONCEPTS: List[Tuple[str, str]] = [
  # === Deferred revenue (P&L gap) ===
  ("DeferredRevenue",                                   "instant"),
  ("DeferredRevenueCurrent",                            "instant"),
  ("DeferredRevenueNoncurrent",                         "instant"),
  ("ContractWithCustomerLiabilityCurrent",              "instant"),
  ("ContractWithCustomerLiabilityNoncurrent",           "instant"),
  ("ContractWithCustomerLiability",                     "instant"),

  # === Prepaid (BS gap) ===
  ("PrepaidExpenseCurrent",                             "instant"),
  ("PrepaidExpenseAndOtherAssetsCurrent",               "instant"),
  ("PrepaidExpenseAndOtherAssets",                      "instant"),

  # === Marketing / advertising (high-priority) ===
  ("AdvertisingExpense",                                "duration"),
  ("MarketingExpense",                                  "duration"),
  ("MarketingAndAdvertisingExpense",                    "duration"),
  ("SellingAndMarketingExpense",                        "duration"),

  # === Operating lease / rent ===
  ("OperatingLeaseExpense",                             "duration"),
  ("OperatingLeasesRentExpenseNet",                     "duration"),
  ("LeaseAndRentalExpense",                             "duration"),
  ("OperatingLeaseRightOfUseAsset",                     "instant"),
  ("OperatingLeaseLiability",                           "instant"),

  # === R&D ===
  ("ResearchAndDevelopmentExpense",                     "duration"),

  # === Core P&L ===
  ("Revenues",                                          "duration"),
  ("RevenueFromContractWithCustomerExcludingAssessedTax", "duration"),
  ("CostOfRevenue",                                     "duration"),
  ("CostOfGoodsAndServicesSold",                        "duration"),
  ("GrossProfit",                                       "duration"),
  ("SellingGeneralAndAdministrativeExpense",            "duration"),
  ("GeneralAndAdministrativeExpense",                   "duration"),
  ("DepreciationAndAmortization",                       "duration"),
  ("Depreciation",                                      "duration"),
  ("InterestExpense",                                   "duration"),
  ("IncomeTaxExpenseBenefit",                           "duration"),
  ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "duration"),
  ("OperatingIncomeLoss",                               "duration"),
  ("NetIncomeLoss",                                     "duration"),

  # === Balance sheet core ===
  ("Assets",                                            "instant"),
  ("AssetsCurrent",                                     "instant"),
  ("Liabilities",                                       "instant"),
  ("LiabilitiesCurrent",                                "instant"),
  ("StockholdersEquity",                                "instant"),
  ("AccountsReceivableNetCurrent",                      "instant"),
  ("AccountsPayableCurrent",                            "instant"),
  ("InventoryNet",                                      "instant"),
  ("PropertyPlantAndEquipmentNet",                      "instant"),
  ("LongTermDebtNoncurrent",                            "instant"),
  ("LongTermDebtCurrent",                               "instant"),

  # === Cash flow ===
  ("PaymentsToAcquirePropertyPlantAndEquipment",        "duration"),
  ("PaymentsOfDividendsCommonStock",                    "duration"),
  ("PaymentsOfDividends",                               "duration"),
  ("ShareBasedCompensation",                            "duration"),
  ("NetCashProvidedByUsedInOperatingActivities",        "duration"),
]


# --- Pull periods ----------------------------------------------------------

def calendar_quarters_back(n: int) -> List[Tuple[int, int]]:
  """Return last n (year, quarter) in reverse chronological order, ending at the
  most recently completed calendar quarter."""
  now = datetime.utcnow()
  current_q = (now.month - 1) // 3 + 1
  current_y = now.year
  # Skip the current in-progress quarter; we want completed quarters only.
  current_q -= 1
  if current_q < 1:
    current_q = 4
    current_y -= 1
  out: List[Tuple[int, int]] = []
  y, q = current_y, current_q
  for _ in range(n):
    out.append((y, q))
    q -= 1
    if q < 1:
      q = 4
      y -= 1
  return out


def frames_url(concept: str, kind: str, year: int, quarter: int) -> str:
  suffix = "I" if kind == "instant" else ""
  return f"{SEC_BASE}/api/xbrl/frames/us-gaap/{concept}/USD/CY{year}Q{quarter}{suffix}.json"


# --- Pull + insert ---------------------------------------------------------


def insert_facts_batch(cur, rows: List[Tuple]) -> int:
  if not rows:
    return 0
  cur.executemany(
    """
    INSERT IGNORE INTO sec_edgar_facts
      (cik, ticker, naics_code, concept_name, taxonomy, units,
       fiscal_period, fiscal_year, fiscal_quarter, is_instant,
       value, accession_number, filed_at, form_type, fy_end_at, fp_end_at)
    VALUES (%s,%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,%s,%s)
    """,
    rows,
  )
  return cur.rowcount


def parse_filed(value: Any) -> Optional[str]:
  if not value:
    return None
  s = str(value).strip()[:10]
  return s or None


def pull_concept_period(
  *,
  concept: str,
  kind: str,
  year: int,
  quarter: int,
  cik_to_naics: Dict[str, Dict[str, str]],
) -> List[Tuple]:
  url = frames_url(concept, kind, year, quarter)
  payload = _http_get(url)
  time.sleep(RATE_LIMIT_SLEEP)
  if not isinstance(payload, dict):
    return []
  data = payload.get("data") if isinstance(payload.get("data"), list) else []
  fiscal_period = f"CY{year}Q{quarter}{'I' if kind == 'instant' else ''}"
  out: List[Tuple] = []
  for entry in data:
    if not isinstance(entry, dict):
      continue
    cik_raw = entry.get("cik")
    if cik_raw is None:
      continue
    try:
      cik_padded = str(int(cik_raw)).zfill(10)
    except Exception:
      continue
    mapping = cik_to_naics.get(cik_padded)
    ticker = (mapping or {}).get("ticker")
    naics = (mapping or {}).get("naics")
    val = entry.get("val")
    accn = str(entry.get("accn") or "").strip() or None
    filed = parse_filed(entry.get("filed"))
    form = str(entry.get("form") or "").strip()[:10] or None
    fy = entry.get("fy")
    fp_end = parse_filed(entry.get("end"))
    fp_start = parse_filed(entry.get("start"))
    out.append((
      cik_padded, ticker, naics, concept, "us-gaap", "USD",
      fiscal_period,
      int(fy) if fy is not None else year,
      int(quarter),
      1 if kind == "instant" else 0,
      val,
      accn, filed, form,
      None,  # fy_end_at not directly given; leave null
      fp_end,
    ))
  return out


def main(quarters_back: int = 8) -> int:
  print("=" * 70)
  print("SEC EDGAR XBRL Frames pull")
  print("=" * 70)
  conn = _conn()
  try:
    cur = conn.cursor()
    print("\nEnsuring sec_edgar_facts table exists ...")
    cur.execute(CREATE_FACTS_TABLE_SQL)
    conn.commit()

    cik_to_naics = build_cik_to_naics_map(conn)

    quarters = calendar_quarters_back(quarters_back)
    print(f"\nPulling {len(CONCEPTS)} concepts x {len(quarters)} quarters = "
          f"{len(CONCEPTS) * len(quarters)} API calls ...")
    print(f"  quarters: {quarters}")

    total_inserted = 0
    total_seen = 0
    for concept, kind in CONCEPTS:
      concept_inserted = 0
      concept_seen = 0
      for (year, quarter) in quarters:
        rows = pull_concept_period(
          concept=concept, kind=kind, year=year, quarter=quarter,
          cik_to_naics=cik_to_naics,
        )
        concept_seen += len(rows)
        if rows:
          # Batch insert in chunks of 1000
          for i in range(0, len(rows), 1000):
            chunk = rows[i:i + 1000]
            inserted = insert_facts_batch(cur, chunk)
            concept_inserted += inserted
          conn.commit()
      print(f"  {concept:65} seen={concept_seen:>6} inserted={concept_inserted:>6}")
      total_inserted += concept_inserted
      total_seen += concept_seen

    print(f"\nDone. Seen={total_seen}, inserted={total_inserted}.")
    cur.close()
  finally:
    conn.close()
  return 0


if __name__ == "__main__":
  q_back = int(os.getenv("SEC_EDGAR_QUARTERS_BACK") or "8")
  sys.exit(main(quarters_back=q_back))
