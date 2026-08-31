import math
import os
from datetime import datetime, timedelta
from pathlib import Path
import smtplib
import traceback
from email.message import EmailMessage

import mysql.connector
import requests
from dotenv import load_dotenv

# --------------------------------------------------------
# LOAD ROOT .env FILE (WORKS FROM ANY SUBFOLDER)
# --------------------------------------------------------

def get_project_root() -> Path:
    """Find the repo root by its .env. The old check demanded a parent named
    'Business Plan Generator'; the repo is business_plann_app, so the loader
    has FileNotFoundError'd on this machine since the rename - which is why
    fred_macro_quarterly sat a year stale (found 2026-08-31)."""
    for parent in Path(__file__).resolve().parents:
        if parent.name == "Business Plan Generator" or (parent / ".env").exists():
            return parent
    raise FileNotFoundError("Could not locate a project root containing .env")


project_root = get_project_root()
env_file = project_root / ".env"

if not env_file.exists():
    raise FileNotFoundError(f"Expected root .env at {env_file}")

if not load_dotenv(dotenv_path=env_file, override=True):
    raise RuntimeError(f"Could not load environment variables from {env_file}")


def env_value(*keys: str) -> str | None:
    """Return the first non-empty env value from the provided keys."""
    for key in keys:
        val = os.getenv(key)
        if val:
            return val
    return None


MYSQL_HOST = env_value("MYSQL_HOST", "DB_HOST")
MYSQL_USER = env_value("MYSQL_USER", "DB_USER")
MYSQL_PASSWORD = env_value("MYSQL_PASSWORD", "DB_PASSWORD")
# Support MYSQL_DATABASE, MYSQL_DB, DB_NAME (root .env uses MYSQL_DB)
MYSQL_DATABASE = env_value("MYSQL_DATABASE", "MYSQL_DB", "DB_NAME")
FRED_API_KEY = env_value("FRED_API_KEY", "FRED_KEY")
EMAIL_ALERTS_ADDRESS = env_value("EMAIL_ALERTS_ADDRESS")
EMAIL_HOST = env_value("EMAIL_HOST")
EMAIL_PORT = env_value("EMAIL_PORT")
EMAIL_USER = env_value("EMAIL_USER")
EMAIL_PASSWORD = env_value("EMAIL_PASSWORD")

missing = [
    key
    for key, value in {
        "MYSQL_HOST": MYSQL_HOST,
        "MYSQL_USER": MYSQL_USER,
        "MYSQL_PASSWORD": MYSQL_PASSWORD,
        "MYSQL_DATABASE": MYSQL_DATABASE,
        "FRED_API_KEY": FRED_API_KEY,
        "EMAIL_ALERTS_ADDRESS": EMAIL_ALERTS_ADDRESS,
        "EMAIL_HOST": EMAIL_HOST,
        "EMAIL_PORT": EMAIL_PORT,
        "EMAIL_USER": EMAIL_USER,
        "EMAIL_PASSWORD": EMAIL_PASSWORD,
    }.items()
    if not value
]

if missing:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(missing)} (expected in {env_file})"
    )


# --------------------------------------------------------
# CONNECT TO MYSQL
# --------------------------------------------------------

conn = mysql.connector.connect(
    host=MYSQL_HOST,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DATABASE,
)
cursor = conn.cursor()

print("Connected to MySQL (FRED Loader)")


# --------------------------------------------------------
# HELPERS
# --------------------------------------------------------

def get_quarter(date_obj: datetime) -> int:
    """Return quarter number (1-4) based on month."""
    return math.ceil(date_obj.month / 3)


def fetch_fred_series(series_id: str, start_date: str, end_date: str):
    """Fetch a FRED series using FRED API."""
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}"
        f"&api_key={FRED_API_KEY}"
        "&file_type=json"
        f"&observation_start={start_date}"
        f"&observation_end={end_date}"
    )

    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"FRED request failed for {series_id}: HTTP {resp.status_code} {resp.text}")

    data = resp.json()
    if "observations" not in data:
        raise RuntimeError(f"FRED error for series {series_id}: {data}")

    return data["observations"]


def send_email(subject: str, body: str):
    """Send a plain-text email using Outlook SMTP credentials from .env."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_ALERTS_ADDRESS
    msg.set_content(body)

    with smtplib.SMTP(EMAIL_HOST, int(EMAIL_PORT), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(EMAIL_USER, EMAIL_PASSWORD)
        smtp.send_message(msg)


# --------------------------------------------------------
# LOAD DATA (10 YEARS INITIAL + 6-MONTH ROLLING UPDATES)
# --------------------------------------------------------

today = datetime.today()
ten_years_ago = today - timedelta(days=365 * 10)

start_initial = ten_years_ago.strftime("%Y-%m-%d")
end_initial = today.strftime("%Y-%m-%d")

six_months_ago = today - timedelta(days=30 * 6)
start_recent = six_months_ago.strftime("%Y-%m-%d")

SERIES = {
    "gdp": "GDP",
    "cpi": "CPIAUCSL",
    "consumer_spending": "PCE",
}

# --------------------------------------------------------
# FETCH FRED DATA
# --------------------------------------------------------
success = False
failure_reason = None

try:
    # --------------------------------------------------------
    # FETCH FRED DATA
    # --------------------------------------------------------
    print("Fetching GDP...")
    gdp_data = fetch_fred_series(SERIES["gdp"], start_initial, end_initial)

    print("Fetching CPI...")
    cpi_data = fetch_fred_series(SERIES["cpi"], start_initial, end_initial)

    print("Fetching PCE...")
    pce_data = fetch_fred_series(SERIES["consumer_spending"], start_initial, end_initial)

    if not gdp_data:
        failure_reason = "GDP API returned empty"
        raise RuntimeError(failure_reason)
    if not cpi_data:
        failure_reason = "CPI API returned empty"
        raise RuntimeError(failure_reason)
    if not pce_data:
        failure_reason = "PCE API returned empty"
        raise RuntimeError(failure_reason)

    print("All FRED series downloaded.")

    # --------------------------------------------------------
    # MERGE OBSERVATIONS BY DATE
    # --------------------------------------------------------
    merged = {}
    gdp_dates = set()

    # Seed merged rows with GDP dates only
    for item in gdp_data:
        date_str = item["date"]
        value = item["value"]
        if value in ("", ".", None):
            continue
        merged[date_str] = {"gdp": float(value)}
        gdp_dates.add(date_str)

    # Build a lookup of monthly CPI values
    cpi_monthly = {}
    for item in cpi_data:
        date_str = item["date"]
        value = item["value"]
        if value in ("", ".", None):
            continue
        cpi_monthly[date_str] = float(value)

    # Compute YoY inflation for each month where prior year data exists
    inflation_monthly = {}
    for date_str, cpi_val in cpi_monthly.items():
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        prev_year = date_obj.replace(year=date_obj.year - 1)
        prev_key = prev_year.strftime("%Y-%m-%d")
        prev_val = cpi_monthly.get(prev_key)
        if prev_val is None or prev_val == 0:
            continue
        inflation_monthly[date_str] = ((cpi_val - prev_val) / prev_val) * 100

    # Add CPI and inflation values only when the date is present in GDP (quarter start months)
    for date_str in list(gdp_dates):
        if date_str in cpi_monthly:
            merged[date_str]["cpi"] = cpi_monthly[date_str]
        if date_str in inflation_monthly:
            merged[date_str]["inflation_rate"] = inflation_monthly[date_str]

    for item in pce_data:
        date_str = item["date"]
        value = item["value"]
        if value in ("", ".", None) or date_str not in gdp_dates:
            continue
        merged[date_str]["consumer_spending"] = float(value)

    # --------------------------------------------------------
    # INSERT OR UPDATE ROWS
    # --------------------------------------------------------
    insert_sql = """
    INSERT INTO fred_macro_quarterly 
    (date, year, quarter, gdp, cpi, consumer_spending, inflation_rate)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        gdp = VALUES(gdp),
        cpi = VALUES(cpi),
        consumer_spending = VALUES(consumer_spending),
        inflation_rate = VALUES(inflation_rate);
    """

    count = 0

    for date_str, values in merged.items():
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        year = date_obj.year
        quarter = get_quarter(date_obj)

        gdp = values.get("gdp")
        cpi = values.get("cpi")
        pce = values.get("consumer_spending")
        inflation_rate = values.get("inflation_rate")

        cursor.execute(insert_sql, (date_str, year, quarter, gdp, cpi, pce, inflation_rate))
        count += 1

    conn.commit()
    print(f"Loaded or updated {count} rows into fred_macro_quarterly.")

    # --------------------------------------------------------
    # SUCCESS VALIDATION (LATEST GDP DATE MATCH)
    # --------------------------------------------------------
    cursor.execute("SELECT date, inflation_rate FROM fred_macro_quarterly ORDER BY date DESC LIMIT 1")
    latest_row = cursor.fetchone()
    latest_sql_date = latest_row[0] if latest_row else None
    latest_sql_inflation = latest_row[1] if latest_row else None

    # Determine latest GDP date from FRED
    gdp_dates_sorted = sorted(gdp_dates)
    latest_fred_gdp_date = gdp_dates_sorted[-1] if gdp_dates_sorted else None

    if not latest_sql_date or not latest_fred_gdp_date or str(latest_sql_date) != latest_fred_gdp_date:
        failure_reason = (
            f"Latest GDP date mismatch: SQL={latest_sql_date}, FRED={latest_fred_gdp_date}"
        )
        raise RuntimeError(failure_reason)

    success = True

except Exception as exc:
    if not failure_reason:
        failure_reason = f"Exception: {exc}"
    failure_reason += "\n" + traceback.format_exc()
    success = False
finally:
    try:
        cursor.close()
        conn.close()
    except Exception:
        pass

# --------------------------------------------------------
# PHASE 2 - THE WIDER SERIES (2026-08-31)
# --------------------------------------------------------
# New series land in fred_series_quarterly, LONG (keyed by series), never in
# fred_macro_quarterly: a column per series would force an ALTER on the wired
# table for every future series, and long-keyed scales to industry PPIs
# without touching any reader. Daily/monthly series are averaged per quarter.
#
#   DGS10    10-year Treasury  - the rate environment a plan borrows into
#   DGS2     2-year Treasury   - with DGS10, the curve
#   FEDFUNDS policy rate
#   UNRATE   unemployment      - labour-market context beside OEWS wages
#   PPIACO   producer prices   - input-cost pressure for COGS context
WIDE_SERIES = {
    "DGS10": "10-Year Treasury Constant Maturity",
    "DGS2": "2-Year Treasury Constant Maturity",
    "FEDFUNDS": "Effective Federal Funds Rate",
    "UNRATE": "Unemployment Rate",
    "PPIACO": "Producer Price Index, All Commodities",
}

wide_summary = []
if success:
    try:
        conn2 = mysql.connector.connect(
            host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
        )
        cur2 = conn2.cursor()
        cur2.execute(
            """
            CREATE TABLE IF NOT EXISTS fred_series_quarterly (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
              series_id VARCHAR(32) NOT NULL,
              series_label VARCHAR(128) NOT NULL,
              date DATE NOT NULL,
              year INT NOT NULL,
              quarter INT NOT NULL,
              value DOUBLE NOT NULL,
              obs_count INT NOT NULL,
              UNIQUE KEY uq_series_q (series_id, date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        for sid, label in WIDE_SERIES.items():
            print(f"Fetching {sid}...")
            obs = fetch_fred_series(sid, start_initial, end_initial)
            buckets = {}
            for item in obs:
                val = item.get("value")
                if val in ("", ".", None):
                    continue
                d = datetime.strptime(item["date"], "%Y-%m-%d")
                qstart = datetime(d.year, 3 * (get_quarter(d) - 1) + 1, 1)
                b = buckets.setdefault(qstart, [0.0, 0])
                b[0] += float(val)
                b[1] += 1
            for qstart, (total, n) in sorted(buckets.items()):
                cur2.execute(
                    """
                    INSERT INTO fred_series_quarterly
                      (series_id, series_label, date, year, quarter, value, obs_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE value=VALUES(value), obs_count=VALUES(obs_count),
                                            series_label=VALUES(series_label)
                    """,
                    (sid, label, qstart.strftime("%Y-%m-%d"), qstart.year,
                     get_quarter(qstart), total / n, n),
                )
            conn2.commit()
            cur2.execute("SELECT MAX(date), COUNT(*) FROM fred_series_quarterly WHERE series_id=%s", (sid,))
            mx, n_rows = cur2.fetchone()
            wide_summary.append(f"{sid}: {n_rows} quarters, latest {mx}")
            print(f"  {sid}: {n_rows} quarters, latest {mx}")
        cur2.close(); conn2.close()
    except Exception as exc:
        wide_summary.append(f"PHASE 2 FAILED: {exc}")
        print(f"Phase 2 (wide series) failed: {exc}")


# --------------------------------------------------------
# EMAIL ALERTS
# --------------------------------------------------------
timestamp = datetime.utcnow().isoformat()
if success:
    subject = "FRED Macro Loader: SUCCESS"
    body = (
        "FRED macro loader ran successfully.\n"
        f"Latest GDP date in SQL: {latest_sql_date}\n"
        f"inflation_rate for that date: {latest_sql_inflation}\n"
        f"Timestamp (UTC): {timestamp}\n\n"
        + ("Wide series (fred_series_quarterly):\n  " + "\n  ".join(wide_summary) + "\n\n" if wide_summary else "")
        + "Reminder: update any manual macro sources if needed."
    )
else:
    subject = "FRED Macro Loader: FAILURE"
    body = (
        "FRED macro loader failed.\n"
        f"Reason: {failure_reason}\n"
        f"Timestamp (UTC): {timestamp}\n"
    )

try:
    send_email(subject, body)
except Exception as exc:
    print(f"Failed to send alert email: {exc}")

print("FRED macro loader completed.")
