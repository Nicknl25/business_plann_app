import os
import time
import pandas as pd
import requests
import mysql.connector
from dotenv import load_dotenv
from math import floor

# ------------------------------------------------
# Load environment variables
# ------------------------------------------------
load_dotenv()

ALPHA_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")
API_SLEEP = float(os.getenv("API_SLEEP_SECONDS", "2"))

API_SLEEP = min(API_SLEEP, 15)  # cap at 15 seconds

if not ALPHA_KEY:
    raise Exception("Missing ALPHAVANTAGE_API_KEY in .env")

# ------------------------------------------------
# Load ticker CSV
# ------------------------------------------------
csv_path = r"C:\Users\ignat\Documents\Business Plan Generator\ticker symbols.csv"
df = pd.read_csv(csv_path)
symbols = df["Symbol"].dropna().unique().tolist()
total = len(symbols)

print(f"Loaded {total} tickers")

# ------------------------------------------------
# MySQL connection
# ------------------------------------------------
conn = mysql.connector.connect(
    host=MYSQL_HOST,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DB
)
cursor = conn.cursor()

UPSERT_SQL = """
INSERT INTO ticker_metadata (symbol, market_cap, industry, sector)
VALUES (%s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    market_cap = VALUES(market_cap),
    industry = VALUES(industry),
    sector = VALUES(sector);
"""

# ------------------------------------------------
# Helper to call Alpha Overview
# ------------------------------------------------
def get_overview(symbol):
    url = (
        "https://www.alphavantage.co/query"
        f"?function=OVERVIEW&symbol={symbol}&apikey={ALPHA_KEY}"
    )
    for attempt in range(2):  # retry once
        r = requests.get(url, timeout=30)
        if r.status_code in [429, 500, 502, 503, 504]:
            time.sleep(1)
            continue
        data = r.json()
        return {
            "symbol": symbol,
            "market_cap": data.get("MarketCapitalization"),
            "industry": data.get("Industry"),
            "sector": data.get("Sector")
        }
    return None

# ------------------------------------------------
# Main loop
# ------------------------------------------------
for i, sym in enumerate(symbols, start=1):

    # one-line progress indicator
    print(f"Processing {i} of {total}", end="\r")

    meta = get_overview(sym)
    if meta is None:
        continue

    cursor.execute(
        UPSERT_SQL,
        (
            meta["symbol"],
            meta["market_cap"],
            meta["industry"],
            meta["sector"]
        )
    )
    conn.commit()

    time.sleep(API_SLEEP)

print("\nDone.")
cursor.close()
conn.close()
