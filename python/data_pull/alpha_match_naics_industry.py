import os
import json
import mysql.connector
import pandas as pd
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Load ENV
# ---------------------------------------------------------------------------

PROJECT_ROOT_NAME = "Business Plan Generator"

def get_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if parent.name == PROJECT_ROOT_NAME:
            return parent
    raise FileNotFoundError(f"Project root '{PROJECT_ROOT_NAME}' not found")

def load_env():
    env_file = get_project_root() / ".env"
    load_dotenv(env_file, override=True)

load_env()

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)

# ---------------------------------------------------------------------------
# DB Helpers
# ---------------------------------------------------------------------------

def get_conn():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB
    )

# ---------------------------------------------------------------------------
# Load business types
# ---------------------------------------------------------------------------

def load_business_types():
    conn = get_conn()
    df = pd.read_sql("SELECT display_name, naics_code, industry_name FROM business_types", conn)
    conn.close()
    return df

def compress_business_types(df):
    return "\n".join(
        f"{row.display_name} | {row.naics_code} | {row.industry_name}"
        for row in df.itertuples()
    )

# ---------------------------------------------------------------------------
# Load tickers needing mapping
# ---------------------------------------------------------------------------

def load_unmapped_tickers():
    conn = get_conn()
    df = pd.read_sql("""
        SELECT symbol, industry, sector
        FROM ticker_metadata
        WHERE industry IS NOT NULL
          AND TRIM(industry) <> ''
          AND symbol NOT IN (SELECT symbol FROM alpha_match_naics_industry)
    """, conn)
    conn.close()
    return df

# ---------------------------------------------------------------------------
# GPT Classification (Responses API)
# ---------------------------------------------------------------------------

def classify_batch(batch, biztext):
    tickers_json = json.dumps(batch, indent=2)

    prompt = f"""
You are a NAICS classification engine.

You MUST return VALID JSON ONLY.
Output MUST be a JSON array matching the order of input tickers.

REQUIRED JSON FORMAT:
[
  {{
    "symbol": "...",
    "business_type": "...",
    "naics_code": "...",
    "confidence": 0.95
  }},
  ...
]

RULES:
- NEVER leave blank, null, or unknown fields.
- ALWAYS choose the closest business_type using:
    - ticker.industry + ticker.sector
    - business_type.industry_name

INPUT TICKERS:
{tickers_json}

BUSINESS TYPES (display_name | naics | industry_name):
{biztext}
"""

    try:
        resp = client.responses.create(
            model="gpt-4.1",
            input=prompt,
            max_output_tokens=5000
        )
    except Exception as e:
        print(f"[GPT REQUEST ERROR] {e}")
        return []

    raw = resp.output_text.strip()

    # Try parsing JSON strictly
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == len(batch):
            return parsed
        print("[JSON SHAPE ERROR]", raw[:300])
        return []
    except Exception:
        # Try to salvage JSON if surrounded by text
        try:
            json_start = raw.find("[")
            json_end = raw.rfind("]")
            if json_start != -1 and json_end != -1:
                cleaned = raw[json_start:json_end+1]
                parsed = json.loads(cleaned)
                if isinstance(parsed, list):
                    return parsed
        except Exception:
            pass

        print("[JSON PARSE ERROR]:", raw[:300])
        return []

# ---------------------------------------------------------------------------
# Insert mapping
# ---------------------------------------------------------------------------

def insert_mapping(row):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO alpha_match_naics_industry
        (symbol, industry, sector, business_type, naics_code, naics_industry_name, confidence, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        row["symbol"],
        row["industry"],
        row["sector"],
        row["business_type"],
        row["naics_code"],
        row["naics_industry_name"],
        row["confidence"],
        date.today()
    ))
    conn.commit()
    cur.close()
    conn.close()

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("Loading business types…")
    biz_df = load_business_types()
    biztext = compress_business_types(biz_df)

    # NEW — lookup dictionary to find industry_name fast
    bt_lookup = {
        row.display_name: row.industry_name
        for row in biz_df.itertuples()
    }

    print("Loading pending tickers…")
    tickers = load_unmapped_tickers().to_dict(orient="records")

    total = len(tickers)
    print(f"Total tickers needing mapping: {total}")

    batch_size = 20
    batches = (total + batch_size - 1) // batch_size

    for b in range(batches):
        batch = tickers[b*batch_size:(b+1)*batch_size]
        print(f"\n[Batch {b+1}/{batches}] -> {[t['symbol'] for t in batch]}")

        results = classify_batch(batch, biztext)
        if not results:
            print("⚠ GPT batch failed. Skipping.")
            continue

        for i, result in enumerate(results):
            info = batch[i]

            # Lookup real NAICS industry name based on business_type
            bt_name = result["business_type"]
            naics_industry_name = bt_lookup.get(bt_name)

            row = {
                "symbol": result["symbol"],
                "industry": info["industry"],
                "sector": info["sector"],
                "business_type": bt_name,
                "naics_code": result["naics_code"],
                "naics_industry_name": naics_industry_name,  # ← NEW
                "confidence": result["confidence"],
            }

            print(f" → {row['symbol']}: {row['business_type']} ({row['naics_code']}), "
                  f"NAICS Industry={row['naics_industry_name']}, conf={row['confidence']}")

            insert_mapping(row)

    print("\n✓ NAICS classification completed.\n")


if __name__ == "__main__":
    main()
