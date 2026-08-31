"""THE TREASURY DIVERGENCE GUARD (Nick's ruling, 2026-08-31 evening).

Two ten-years live in this system and both are legitimate:

  valuation_reference_constants.risk_free_rate   the DCF's as-of-build
                                                 assumption - what the WACC
                                                 and the Valuation sheet use
  fred_series_quarterly DGS10 (latest quarter)   the live market rate - what
                                                 the prose cites (S49/S50/S51)

The prose cites LIVE because those sentences describe today's market and the
loader keeps them current; the constant stays the model's own input. This
guard is what makes that split safe: it FAILS when the pair drifts beyond
tolerance, so a stale constant surfaces as a red run instead of two numbers
quietly disagreeing in one document. The fix on failure is to re-point the
constant (and re-bless the valuation), never to widen the tolerance.

Per the CoInitialize law's spirit: a guard that cannot read either side FAILS.

usage: python scripts/writing_phase_treasury_guard.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

# 50bp: rates move, and inside half a point "the environment" and "the
# model's assumption" are the same story told at two vintages. Beyond it the
# DCF is priced off a different market than the one the prose describes.
TOLERANCE_PP = 0.50


def main() -> int:
  conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                                 password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"))
  cur = conn.cursor()

  cur.execute("SELECT value_default, source_as_of FROM valuation_reference_constants "
              "WHERE constant_key='risk_free_rate' AND active=1 LIMIT 1")
  r = cur.fetchone()
  if not r or r[0] is None:
    print("GUARD FAILURE: no active risk_free_rate constant - the DCF side is unreadable")
    return 1
  const_pct = float(r[0]) * 100.0
  const_asof = str(r[1] or "undated")

  cur.execute("SELECT date, value FROM fred_series_quarterly WHERE series_id='DGS10' "
              "ORDER BY date DESC LIMIT 1")
  s = cur.fetchone()
  if not s or s[1] is None:
    print("GUARD FAILURE: no DGS10 rows in fred_series_quarterly - the live side is "
          "unreadable, and a guard that cannot run does not pass")
    return 1
  live_pct = float(s[1])
  live_date = s[0]

  gap = abs(const_pct - live_pct)
  print("DCF constant risk_free_rate: %.2f%%  (as of %s)" % (const_pct, const_asof))
  print("live DGS10 quarterly:        %.2f%%  (quarter of %s)" % (live_pct, live_date))
  print("gap: %.0fbp  (tolerance %.0fbp)" % (gap * 100, TOLERANCE_PP * 100))
  if gap > TOLERANCE_PP:
    print("GUARD FAILURE: the prose's market rate and the DCF's assumption have "
          "diverged - re-point valuation_reference_constants.risk_free_rate and "
          "re-run the valuation guard")
    return 1
  print("GUARD PASS: one rate story, two labelled vintages")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
