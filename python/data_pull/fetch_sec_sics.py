"""One-shot script to fetch SIC + ticker data from SEC submissions API for a
list of CIKs and print their SIC code distribution.

Used to size the SIC->NAICS crosswalk before committing to hand-mapping vs
vendoring the full Census concordance.

Endpoint: https://data.sec.gov/submissions/CIK{cik_padded10}.json
Returns SIC (4-digit), sicDescription, tickers list, and other metadata.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, Optional

import requests


SEC_USER_AGENT = (
  "TitheFinancial Business Plan App ignatius.henry@tithefinancial.com"
)
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
RATE_LIMIT_SLEEP = 0.15
HTTP_TIMEOUT = 30
MAX_RETRIES = 3


_session = requests.Session()
_session.headers.update({
  "User-Agent": SEC_USER_AGENT,
  "Accept-Encoding": "gzip, deflate",
  "Host": "data.sec.gov",
})


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
        wait = float(resp.headers.get("Retry-After") or 2.0 * (attempt + 1))
        time.sleep(wait)
        continue
      if 500 <= resp.status_code < 600:
        time.sleep(2.0 * (attempt + 1))
        continue
      return None
    except requests.RequestException:
      if attempt == MAX_RETRIES - 1:
        return None
      time.sleep(2.0 * (attempt + 1))
  return None


def main(cik_file: str, output_csv: str) -> None:
  with open(cik_file, "r", encoding="utf-8") as f:
    ciks = [line.strip() for line in f if line.strip()]
  print(f"Fetching {len(ciks)} CIKs from SEC submissions API ...", file=sys.stderr)
  results = []
  sic_counter: Counter = Counter()
  fail_count = 0
  for i, cik in enumerate(ciks):
    payload = fetch_submission(cik)
    time.sleep(RATE_LIMIT_SLEEP)
    if payload is None:
      fail_count += 1
      results.append((cik, "", "", ""))
      continue
    sic = str(payload.get("sic") or "").strip()
    sic_desc = str(payload.get("sicDescription") or "").strip()
    tickers_raw = payload.get("tickers")
    ticker_str = ",".join(tickers_raw) if isinstance(tickers_raw, list) else ""
    sic_counter[sic] += 1
    results.append((cik, sic, sic_desc, ticker_str))
    if (i + 1) % 100 == 0:
      print(f"  {i + 1}/{len(ciks)}  unique_sics={len(sic_counter)}", file=sys.stderr)
  print(f"Done. fails={fail_count}, unique_sics={len(sic_counter)}", file=sys.stderr)

  with open(output_csv, "w", encoding="utf-8") as out:
    out.write("cik,sic,sic_description,tickers\n")
    for cik, sic, desc, tickers in results:
      desc_safe = desc.replace('"', '""')
      tickers_safe = tickers.replace('"', '""')
      out.write(f'{cik},{sic},"{desc_safe}","{tickers_safe}"\n')

  # Print SIC distribution to stdout
  print("\n=== SIC distribution (top 50) ===")
  for sic, count in sic_counter.most_common(50):
    print(f"{sic}\t{count}")
  print(f"\n=== Total unique SICs: {len(sic_counter)} ===")
  print(f"=== CIKs with SIC: {sum(sic_counter.values())} ===")
  print(f"=== CIKs failed: {fail_count} ===")


if __name__ == "__main__":
  cik_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/unmapped_ciks.txt"
  output_csv = sys.argv[2] if len(sys.argv) > 2 else "/tmp/sec_sic_lookup.csv"
  main(cik_file, output_csv)
