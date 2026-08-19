"""Load the VALUATION REFERENCE CONSTANTS — the slow-moving inputs a DCF cites.

A DCF is mostly assumptions. The point of this table is that none of them are
*guesses*: every row carries the figure, its published source, the date that
figure was published, and the window it is effective for, so the valuation sheet
can print "ERP 4.28% — Damodaran implied, 1 Aug 2026" instead of a bare number.

Two kinds of row:

  FETCHED   recomputed from a live source on every run (FRED-derived long-run
            growth; the Damodaran implied ERP page). Re-running the loader
            genuinely refreshes these.
  PINNED    published in a report we cannot scrape (Kroll's cost-of-capital
            recommendations, BizBuySell's transaction multiples). The figure and
            its as-of date are pinned in PINNED_CONSTANTS below; refreshing them
            is a one-line edit in this file, once or twice a year.

Every run UPSERTs, so it is safe to re-run: `python -m data_pull.valuation_reference_constants_loader`
(or `python python/data_pull/valuation_reference_constants_loader.py`).

Nothing consumes this table yet — the DCF sheet (X5) will.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Project root — deliberately NOT the "find a folder literally named 'Business
# Plan Generator'" pattern used by the other loaders in this directory, which
# raises FileNotFoundError in this checkout and is why several of them are dead.
# ---------------------------------------------------------------------------

def project_root() -> Path:
  override = os.getenv("BPLAN_ROOT")
  if override:
    return Path(override).resolve()
  here = Path(__file__).resolve()
  for parent in here.parents:
    if (parent / ".env").exists() or (parent / ".git").exists():
      return parent
  return here.parents[2]


ROOT = project_root()
load_dotenv(ROOT / ".env")

TABLE = "valuation_reference_constants"

CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS `{TABLE}` (
  id BIGINT NOT NULL AUTO_INCREMENT,
  constant_key VARCHAR(80) NOT NULL,
  constant_label VARCHAR(160) NOT NULL,
  applies_to VARCHAR(16) NOT NULL DEFAULT 'ALL',
  unit VARCHAR(24) NOT NULL,
  value_min DECIMAL(20,6) NULL,
  value_default DECIMAL(20,6) NOT NULL,
  value_max DECIMAL(20,6) NULL,
  data_source VARCHAR(64) NOT NULL,
  source_citation TEXT NOT NULL,
  source_as_of DATE NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  confidence_tier ENUM('high','medium','low','judgment') NOT NULL DEFAULT 'medium',
  refresh_mode ENUM('fetched','pinned') NOT NULL DEFAULT 'pinned',
  derivation_formula TEXT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  notes TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_constant (constant_key, applies_to, effective_from),
  KEY ix_lookup (constant_key, applies_to, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

UPSERT_SQL = f"""
INSERT INTO `{TABLE}`
  (constant_key, constant_label, applies_to, unit, value_min, value_default, value_max,
   data_source, source_citation, source_as_of, effective_from, effective_to,
   confidence_tier, refresh_mode, derivation_formula, active, notes)
VALUES (%(constant_key)s, %(constant_label)s, %(applies_to)s, %(unit)s, %(value_min)s,
        %(value_default)s, %(value_max)s, %(data_source)s, %(source_citation)s,
        %(source_as_of)s, %(effective_from)s, %(effective_to)s, %(confidence_tier)s,
        %(refresh_mode)s, %(derivation_formula)s, %(active)s, %(notes)s)
ON DUPLICATE KEY UPDATE
  constant_label=VALUES(constant_label), unit=VALUES(unit),
  value_min=VALUES(value_min), value_default=VALUES(value_default), value_max=VALUES(value_max),
  data_source=VALUES(data_source), source_citation=VALUES(source_citation),
  source_as_of=VALUES(source_as_of), effective_to=VALUES(effective_to),
  confidence_tier=VALUES(confidence_tier), refresh_mode=VALUES(refresh_mode),
  derivation_formula=VALUES(derivation_formula), active=VALUES(active), notes=VALUES(notes)
"""

# ---------------------------------------------------------------------------
# PINNED constants — published figures we cannot scrape. To refresh: change the
# number AND its source_as_of date together. Nothing else needs editing.
# ---------------------------------------------------------------------------

PINNED_CONSTANTS: List[Dict[str, Any]] = [
  {
    "constant_key": "equity_risk_premium_kroll",
    "constant_label": "Equity risk premium — Kroll recommended (normalized-rate convention)",
    "unit": "decimal_rate", "value_min": None, "value_default": 0.05, "value_max": None,
    "data_source": "kroll",
    "source_citation": "Kroll, Recommended U.S. Equity Risk Premium and Corresponding Risk-Free Rates — "
                       "https://www.kroll.com/en/reports/cost-of-capital/recommended-us-equity-risk-premium-and-corresponding-risk-free-rates",
    "source_as_of": date(2025, 9, 2),
    "confidence_tier": "high",
    "notes": "ALTERNATIVE CONVENTION, not the default. Kroll pairs this 5.0% with the HIGHER of a "
             "normalized risk-free rate of 3.5% or the spot 20-year Treasury yield - NOT with the "
             "spot 10-year. Pairing it with our live DGS10 would mix conventions and overstate the "
             "cost of equity. Use only together with equity_risk_premium_kroll_rf.",
  },
  {
    "constant_key": "equity_risk_premium_kroll_rf",
    "constant_label": "Normalized risk-free rate that Kroll's ERP is paired with",
    "unit": "decimal_rate", "value_min": None, "value_default": 0.035, "value_max": None,
    "data_source": "kroll",
    "source_citation": "Kroll, U.S. normalized risk-free rate (use the higher of this or the spot "
                       "20-year Treasury yield) — https://www.kroll.com/en/reports/cost-of-capital/"
                       "kroll-increases-us-risk-free-rate-but-spot-treasury-yield-preferred",
    "source_as_of": date(2025, 9, 2),
    "confidence_tier": "high",
    "notes": "Only meaningful alongside equity_risk_premium_kroll.",
  },
  {
    "constant_key": "size_premium_micro_cap",
    "constant_label": "Size premium for a micro-cap / main-street business",
    "unit": "decimal_rate", "value_min": 0.047, "value_default": 0.112, "value_max": 0.118,
    "data_source": "kroll_crsp",
    "source_citation": "Kroll CRSP Deciles Size Study (formerly Duff & Phelps / Ibbotson SBBI). "
                       "Decile 10 long-run size premium 4.7% (1926-2023); smallest sub-decile 10z "
                       "ranged 11.17%-11.77% over 2012-2022.",
    "source_as_of": date(2023, 12, 31),
    "confidence_tier": "medium",
    "derivation_formula": "min = CRSP decile 10 (4.7%); default = 10z sub-decile (~11.2%); max = 10z high (11.8%)",
    "notes": "DISCLOSE AS AN EXTRAPOLATION. A 3-FTE, sub-$1m-revenue business sits far BELOW even the "
             "smallest published CRSP bucket (10z), so the published premium is a floor for a business "
             "this small, not a measurement of it. Default uses 10z because decile 10 materially "
             "understates main-street risk.",
  },
  {
    "constant_key": "company_specific_risk_premium",
    "constant_label": "Company-specific risk premium (key person, customer concentration, marketability)",
    "unit": "decimal_rate", "value_min": 0.0, "value_default": 0.03, "value_max": 0.05,
    "data_source": "judgment",
    "source_citation": "Standard build-up-method judgment component. No published series exists; the "
                       "range is the conventional 0-5% band used in small-business appraisal.",
    "source_as_of": None,
    "confidence_tier": "judgment",
    "notes": "PURE JUDGMENT - must render as an editable, clearly-labelled assumption cell. Basis to "
             "state on the sheet: owner dependence, customer concentration, and the absence of a "
             "ready market for the shares.",
  },
  {
    "constant_key": "exit_multiple_sde",
    "constant_label": "Exit multiple — price as a multiple of seller's discretionary earnings",
    "applies_to": "ALL",
    "unit": "multiple", "value_min": 2.0, "value_default": 2.7, "value_max": 3.5,
    "data_source": "bizbuysell",
    "source_citation": "BizBuySell Insight Report, Q2 2026 (2,117 closed small-business transactions): "
                       "average cash-flow multiple 2.7x, median sale price $349,250, median cash flow "
                       "$155,921, median revenue $692,087 — https://www.bizbuysell.com/insight-report/",
    "source_as_of": date(2026, 6, 30),
    "confidence_tier": "high",
    "notes": "REAL CLOSED-TRANSACTION DATA for businesses of exactly our clients' size (the median "
             "business in this sample had $692k revenue). This is an SDE multiple - SDE is EBITDA plus "
             "owner compensation - so it must NOT be applied to EBITDA without the add-back.",
  },
  {
    "constant_key": "exit_multiple_revenue",
    "constant_label": "Exit multiple — price as a multiple of revenue (cross-check only)",
    "applies_to": "ALL",
    "unit": "multiple", "value_min": 0.5, "value_default": 0.7, "value_max": 1.0,
    "data_source": "bizbuysell",
    "source_citation": "BizBuySell Insight Report, Q2 2026: average revenue multiple 0.7x — "
                       "https://www.bizbuysell.com/insight-report/",
    "source_as_of": date(2026, 6, 30),
    "confidence_tier": "medium",
    "notes": "A sanity cross-check on the SDE multiple, never a primary valuation method.",
  },
  {
    "constant_key": "exit_multiple_sde",
    "constant_label": "Exit multiple (SDE) — automotive repair and maintenance",
    "applies_to": "8111",
    "unit": "multiple", "value_min": 2.0, "value_default": 2.5, "value_max": 3.0,
    "data_source": "industry_transaction_reports",
    "source_citation": "Owner-operated single-bay auto repair shops in the sub-$250k SDE band "
                       "transacted at 2.0x-3.0x SDE, 2024 through Q2 2026; multi-bay shops with "
                       "$500k-$1m SDE cleared 3.0x-4.5x. (CT Acquisitions, Auto Repair & Mechanic Shop "
                       "M&A Multiples Report 2026.)",
    "source_as_of": date(2026, 6, 30),
    "confidence_tier": "medium",
    "notes": "Applies to NAICS 8111*. Larger multi-bay operators sit above this range - the default is "
             "set for the owner-operated case our clients typically are.",
  },
  {
    "constant_key": "exit_multiple_sde",
    "constant_label": "Exit multiple (SDE) — nursery and garden centres",
    "applies_to": "4442",
    "unit": "multiple", "value_min": 2.5, "value_default": 3.0, "value_max": 4.2,
    "data_source": "industry_transaction_reports",
    "source_citation": "Plant nursery and garden centre businesses averaged roughly 2.5x-3.0x earnings "
                       "historically, rising to about 4.2x in 2025; median sale price near $400k. "
                       "(BizBuySell nursery & garden centre valuation benchmarks.)",
    "source_as_of": date(2026, 6, 30),
    "confidence_tier": "medium",
    "notes": "Applies to NAICS 4442*.",
  },
  {
    "constant_key": "wacc_minus_growth_floor",
    "constant_label": "Minimum spread between WACC and terminal growth",
    "unit": "decimal_rate", "value_min": None, "value_default": 0.03, "value_max": None,
    "data_source": "judgment",
    "source_citation": "Structural guard on the Gordon growth model: as (WACC - g) approaches zero the "
                       "terminal value diverges, so a small rounding change swings the valuation wildly.",
    "source_as_of": None,
    "confidence_tier": "judgment",
    "notes": "Not a market input - a guard rail. The valuation sheet should refuse to compute a "
             "perpetuity terminal value when the spread is below this.",
  },
]

# ---------------------------------------------------------------------------
# FETCHED constants
# ---------------------------------------------------------------------------

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def _fred_series(series_id: str, start: str = "2000-01-01") -> List[Dict[str, str]]:
  key = os.getenv("FRED_API_KEY") or os.getenv("FRED_KEY")
  if not key:
    raise RuntimeError("FRED_API_KEY missing from .env")
  resp = requests.get(
    FRED_BASE,
    params={"series_id": series_id, "api_key": key, "file_type": "json",
            "observation_start": start},
    timeout=30,
  )
  resp.raise_for_status()
  return [o for o in resp.json().get("observations", []) if o.get("value") not in (None, ".", "")]


def fetch_terminal_growth() -> Optional[Dict[str, Any]]:
  """Long-run NOMINAL growth ceiling = real GDP trend + market-implied inflation.

  A perpetuity growing faster than the economy eventually IS the economy, so
  this is the hard ceiling on the terminal growth rate; the DEFAULT is inflation
  only, because a single-location owner-operated business does not compound real
  market share forever.
  """
  try:
    real = _fred_series("GDPC1", "1995-01-01")
    breakeven = _fred_series("T10YIE", "2024-01-01")
  except Exception as exc:  # pragma: no cover - network
    print(f"  ! FRED fetch failed ({exc}); falling back to the pinned ceiling")
    return None
  if len(real) < 81 or not breakeven:
    return None
  latest, prior = real[-1], real[-81]              # 80 quarters = 20 years
  cagr = (float(latest["value"]) / float(prior["value"])) ** (1 / 20.0) - 1.0
  infl = float(breakeven[-1]["value"]) / 100.0
  ceiling = cagr + infl
  return {
    "constant_key": "terminal_growth_rate",
    "constant_label": "Terminal perpetuity growth — default and ceiling",
    "unit": "decimal_rate",
    "value_min": 0.0, "value_default": round(infl, 6), "value_max": round(ceiling, 6),
    "data_source": "fred_derived",
    "source_citation": (
      f"FRED GDPC1 real GDP 20-year CAGR {cagr * 100:.2f}% (through {latest['date']}) "
      f"+ FRED T10YIE 10-year breakeven inflation {infl * 100:.2f}% (as of "
      f"{breakeven[-1]['date']}) = nominal ceiling {ceiling * 100:.2f}%."
    ),
    "source_as_of": date.fromisoformat(breakeven[-1]["date"]),
    "confidence_tier": "high",
    "refresh_mode": "fetched",
    "derivation_formula": "ceiling = GDPC1 20y real CAGR + T10YIE; default = T10YIE (inflation only)",
    "notes": "DEFAULT is inflation only - no permanent real growth for a single-location business. "
             "MAX is the long-run nominal GDP ceiling; a terminal growth rate above it is indefensible.",
  }


DAMODARAN_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm"
DAMODARAN_FALLBACK = {"erp": 0.0428, "rf": 0.0474, "as_of": date(2026, 8, 1)}


def fetch_damodaran_erp() -> Dict[str, Any]:
  """The implied ERP, computed monthly against the SPOT 10-year Treasury — which
  is the convention that matches our live FRED DGS10 risk-free rate."""
  erp, rf, as_of = DAMODARAN_FALLBACK["erp"], DAMODARAN_FALLBACK["rf"], DAMODARAN_FALLBACK["as_of"]
  fetched = False
  try:
    import html as _html

    raw = requests.get(DAMODARAN_URL, timeout=30).text
    # The page splits digits across tags ("4.<span>28%</span>"), so strip the
    # markup first and allow whitespace INSIDE the number.
    text = _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)))
    m = re.search(
      r"Implied\s+ERP\s+on\s+([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})\s*=\s*([\d.\s]+?)\s*%",
      text, re.I)
    if m:
      months = ("january february march april may june july august september "
                "october november december").split()
      as_of = date(int(m.group(3)), months.index(m.group(1).lower()) + 1, int(m.group(2)))
      erp = round(float(re.sub(r"\s+", "", m.group(4))) / 100.0, 6)
      fetched = True
    r = re.search(r"treasury\s+rate\s+of\s+([\d.\s]+?)\s*%", text, re.I)
    if r:
      rf = round(float(re.sub(r"\s+", "", r.group(1))) / 100.0, 6)
  except Exception as exc:  # pragma: no cover - network
    print(f"  ! Damodaran fetch failed ({exc}); using the pinned figure")
  return {
    "constant_key": "equity_risk_premium",
    "constant_label": "Equity risk premium — implied, spot-10-year convention (DEFAULT)",
    "unit": "decimal_rate",
    "value_min": 0.0368, "value_default": erp, "value_max": 0.0625,
    "data_source": "damodaran",
    "source_citation": (
      f"Aswath Damodaran, implied equity risk premium for the S&P 500, {as_of.isoformat()}: "
      f"{erp * 100:.2f}% (trailing-12-month adjusted-payout basis), computed against a risk-free "
      f"rate of {rf * 100:.2f}% — {DAMODARAN_URL}"
    ),
    "source_as_of": as_of,
    "confidence_tier": "high",
    "refresh_mode": "fetched" if fetched else "pinned",
    "derivation_formula": "implied ERP from S&P 500 index level, expected cash flows and the spot 10y Treasury",
    "notes": "THE DEFAULT, because it is computed against the SPOT 10-year Treasury - the same rate we "
             "pull live from FRED (DGS10). min/max are the range across the methodologies Damodaran "
             "publishes for the same date. Do NOT pair the Kroll 5.0% ERP with a spot risk-free rate.",
  }


# ---------------------------------------------------------------------------

def _connection():
  import mysql.connector  # type: ignore

  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), port=int(os.getenv("MYSQL_PORT") or 3306),
    user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
  )


def _row_defaults(row: Dict[str, Any], effective_from: date) -> Dict[str, Any]:
  out = {
    "applies_to": "ALL", "value_min": None, "value_max": None, "source_as_of": None,
    "effective_from": effective_from, "effective_to": None, "confidence_tier": "medium",
    "refresh_mode": "pinned", "derivation_formula": None, "active": 1, "notes": None,
  }
  out.update(row)
  return out


def main() -> int:
  effective_from = date.today()
  print(f"=== valuation reference constants — effective {effective_from.isoformat()} ===")

  rows: List[Dict[str, Any]] = []
  print("fetching live sources...")
  erp = fetch_damodaran_erp()
  print(f"  ERP           {erp['value_default'] * 100:.2f}%  ({erp['refresh_mode']}, as of {erp['source_as_of']})")
  rows.append(erp)

  growth = fetch_terminal_growth()
  if growth:
    print(f"  growth        default {growth['value_default'] * 100:.2f}% / ceiling {growth['value_max'] * 100:.2f}%  (fetched)")
    rows.append(growth)
  else:
    rows.append({
      "constant_key": "terminal_growth_rate",
      "constant_label": "Terminal perpetuity growth — default and ceiling",
      "unit": "decimal_rate", "value_min": 0.0, "value_default": 0.023, "value_max": 0.043,
      "data_source": "fred_derived",
      "source_citation": "FRED GDPC1 20-year real CAGR 1.98% + T10YIE 2.30% = 4.28% nominal ceiling "
                         "(pinned fallback; FRED unreachable at load time).",
      "source_as_of": date(2026, 8, 19), "confidence_tier": "medium",
      "notes": "Pinned fallback - re-run the loader when FRED is reachable to refresh.",
    })

  rows.extend(PINNED_CONSTANTS)

  conn = _connection()
  cur = conn.cursor()
  cur.execute(CREATE_SQL)
  conn.commit()
  for row in rows:
    cur.execute(UPSERT_SQL, _row_defaults(dict(row), effective_from))
  conn.commit()

  cur.execute(
    f"SELECT constant_key, applies_to, value_min, value_default, value_max, unit, "
    f"data_source, source_as_of, refresh_mode, confidence_tier FROM `{TABLE}` "
    f"WHERE active=1 ORDER BY constant_key, applies_to"
  )
  print(f"\n{'constant':32s} {'scope':6s} {'min':>8s} {'default':>9s} {'max':>8s}  {'source':<26s} {'as of':<11s} {'mode':<8s} tier")
  print("-" * 128)
  for r in cur.fetchall():
    fmt = lambda v: f"{float(v):>8.4f}" if v is not None else " " * 8
    print(f"{r[0]:32s} {r[1]:6s} {fmt(r[2])} {fmt(r[3])[:9]:>9s} {fmt(r[4])}  {r[6]:<26s} "
          f"{str(r[7] or '-'):<11s} {r[8]:<8s} {r[9]}")
  cur.close()
  conn.close()
  print(f"\n{len(rows)} constants upserted into {TABLE}. Re-run any time; it is idempotent.")
  return 0


if __name__ == "__main__":
  sys.exit(main())
