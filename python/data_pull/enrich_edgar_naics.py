"""Enrich existing sec_edgar_facts rows with NAICS-6 classification for CIKs
that weren't in alpha_match_naics_industry.

This is the in-place complement to sec_edgar_xbrl_pull.py's expanded NAICS
resolution. Instead of re-pulling Frames data, this script:

  1. Finds distinct CIKs in sec_edgar_facts with NULL naics_code.
  2. Filters to CIKs that have rev + cost concepts (so they're actually
     usable cohort firms).
  3. Hits SEC submissions API for each to get SIC + ticker.
  4. Maps SIC -> NAICS-6 via sic_to_naics_crosswalk.
  5. UPDATEs sec_edgar_facts.naics_code (and ticker, when SEC has one) for
     all rows matching the resolved CIKs.

Re-runnable. Safe to run multiple times; the only DB writes are UPDATEs that
fill NULL values.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
import mysql.connector


load_dotenv()


SEC_USER_AGENT = (
  "TitheFinancial Business Plan App ignatius.henry@tithefinancial.com"
)
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
RATE_LIMIT_SLEEP = 0.15
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


_session = requests.Session()
_session.headers.update({
  "User-Agent": SEC_USER_AGENT,
  "Accept-Encoding": "gzip, deflate",
  "Host": "data.sec.gov",
})


def _conn():
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
    autocommit=False,
  )


def fetch_submission(cik_padded: str) -> Optional[Dict[str, Any]]:
  url = f"{SUBMISSIONS_BASE}/CIK{cik_padded}.json"
  for attempt in range(MAX_RETRIES):
    try:
      resp = _session.get(url, timeout=HTTP_TIMEOUT)
      if resp.status_code == 200:
        return resp.json()
      if resp.status_code == 404:
        return None
      if resp.status_code == 429:
        wait = float(resp.headers.get("Retry-After") or RETRY_BACKOFF * (attempt + 1))
        time.sleep(wait)
        continue
      if 500 <= resp.status_code < 600:
        time.sleep(RETRY_BACKOFF * (attempt + 1))
        continue
      return None
    except requests.RequestException:
      if attempt == MAX_RETRIES - 1:
        return None
      time.sleep(RETRY_BACKOFF * (attempt + 1))
  return None


# Make the crosswalk importable when running from python/data_pull or python/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_pull.sic_to_naics_crosswalk import sic_to_naics6  # noqa: E402


REV_CONCEPTS = (
  "Revenues",
  "RevenueFromContractWithCustomerExcludingAssessedTax",
)
COST_CONCEPTS = (
  "CostOfRevenue",
  "CostOfGoodsAndServicesSold",
  "GrossProfit",
  "OperatingIncomeLoss",
  "NetIncomeLoss",
)


def find_unmapped_usable_ciks(conn) -> List[str]:
  """Return distinct CIKs in sec_edgar_facts that have NULL/empty naics AND
  have at least one revenue concept AND at least one cost-side concept."""
  placeholders_rev = ",".join(["%s"] * len(REV_CONCEPTS))
  placeholders_cost = ",".join(["%s"] * len(COST_CONCEPTS))
  sql = f"""
    SELECT DISTINCT cik
    FROM sec_edgar_facts
    WHERE (naics_code IS NULL OR naics_code = '')
      AND cik IN (SELECT cik FROM sec_edgar_facts WHERE concept_name IN ({placeholders_rev}))
      AND cik IN (SELECT cik FROM sec_edgar_facts WHERE concept_name IN ({placeholders_cost}))
  """
  cur = conn.cursor()
  try:
    cur.execute(sql, REV_CONCEPTS + COST_CONCEPTS)
    rows = cur.fetchall() or []
    return [r[0] for r in rows]
  finally:
    cur.close()


def update_cik_naics(conn, cik: str, naics: str, ticker: Optional[str]) -> int:
  """UPDATE all rows for this CIK to set naics_code (and ticker if not present)."""
  cur = conn.cursor()
  try:
    if ticker:
      cur.execute(
        "UPDATE sec_edgar_facts "
        "SET naics_code = %s, "
        "    ticker = COALESCE(NULLIF(ticker, ''), %s) "
        "WHERE cik = %s AND (naics_code IS NULL OR naics_code = '')",
        (naics, ticker, cik),
      )
    else:
      cur.execute(
        "UPDATE sec_edgar_facts SET naics_code = %s "
        "WHERE cik = %s AND (naics_code IS NULL OR naics_code = '')",
        (naics, cik),
      )
    return cur.rowcount
  finally:
    cur.close()


def main() -> int:
  print("=" * 70)
  print("EDGAR NAICS enrichment via SEC submissions API + SIC->NAICS crosswalk")
  print("=" * 70)
  conn = _conn()
  try:
    unmapped = find_unmapped_usable_ciks(conn)
    print(f"\nUnmapped CIKs with rev+cost concepts: {len(unmapped)}")

    resolved = 0
    no_sic = 0
    sic_no_naics = 0
    rows_updated = 0
    for i, cik in enumerate(unmapped):
      payload = fetch_submission(cik)
      time.sleep(RATE_LIMIT_SLEEP)
      if not isinstance(payload, dict):
        no_sic += 1
        continue
      sic_raw = payload.get("sic")
      sic = str(sic_raw or "").strip()
      if not sic:
        no_sic += 1
        continue
      naics = sic_to_naics6(sic)
      if not naics or len(naics) < 6:
        sic_no_naics += 1
        continue
      tickers = payload.get("tickers")
      ticker_str = ""
      if isinstance(tickers, list) and tickers:
        ticker_str = str(tickers[0] or "").strip().upper()
      n = update_cik_naics(conn, cik, naics, ticker_str or None)
      rows_updated += n
      resolved += 1
      if (i + 1) % 200 == 0:
        conn.commit()
        print(f"  {i + 1}/{len(unmapped)}  resolved={resolved}  rows_updated={rows_updated}",
              file=sys.stderr)
    conn.commit()

    print(f"\nDone.")
    print(f"  Unmapped CIKs scanned:  {len(unmapped)}")
    print(f"  Resolved to NAICS-6:    {resolved}")
    print(f"  No SIC in submissions:  {no_sic}")
    print(f"  SIC missing in xwalk:   {sic_no_naics}")
    print(f"  sec_edgar_facts rows updated: {rows_updated}")
  finally:
    conn.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
