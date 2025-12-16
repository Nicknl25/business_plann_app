import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import mysql.connector
import pandas as pd
import requests
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# ENV / CONFIG
# ---------------------------------------------------------------------------

PROJECT_ROOT_NAME = "Business Plan Generator"
ALPHA_BASE = "https://www.alphavantage.co/query"


def get_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if parent.name == PROJECT_ROOT_NAME:
            return parent
    raise FileNotFoundError("Project root not found")


ROOT = get_project_root()
load_dotenv(ROOT / ".env", override=True)

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
ALPHA_KEY = os.getenv("ALPHAVANTAGE_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)
session = requests.Session()
desc_cache: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# DB Helpers
# ---------------------------------------------------------------------------


def get_conn():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
    )


# ---------------------------------------------------------------------------
# NAICS options from naics_master (business_types + 6_digit + naics_title)
# ---------------------------------------------------------------------------


def load_naics_options():
    conn = get_conn()
    df = pd.read_sql("SELECT business_types, naics_6 AS naics_code, naics_title FROM naics_master", conn)
    conn.close()
    options = []
    for row in df.itertuples():
        code = str(row.naics_code).strip() if row.naics_code is not None else ""
        title = (row.naics_title or "").strip()
        if not code or not title:
            continue
        code = code.zfill(6)[:6]
        bt_field = row.business_types or ""
        parts = [p.strip() for p in str(bt_field).split(",") if p and p.strip()]
        for p in parts:
            options.append({"business_type": p, "naics_code": code, "naics_title": title})
    # Deduplicate by business_type (case-insensitive)
    seen = set()
    uniq = []
    for opt in options:
        key = opt["business_type"].lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(opt)
    return uniq


def compress_business_types(options: List[Dict[str, str]]) -> str:
    return "\n".join(
        f"{opt['business_type']} | {opt['naics_code']} | {opt['naics_title']}"
        for opt in options
    )


# ---------------------------------------------------------------------------
# Load tickers needing mapping
# ---------------------------------------------------------------------------


def load_unmapped_tickers():
    conn = get_conn()
    df = pd.read_sql(
        """
        SELECT symbol, industry, sector
        FROM ticker_metadata
        WHERE industry IS NOT NULL
          AND TRIM(industry) <> ''
          AND symbol NOT IN (SELECT symbol FROM alpha_match_naics_industry)
        """,
        conn,
    )
    conn.close()
    return df


# ---------------------------------------------------------------------------
# Alpha Vantage description
# ---------------------------------------------------------------------------


def get_description(symbol: str) -> str:
    if symbol in desc_cache:
        return desc_cache[symbol]
    if not ALPHA_KEY:
        return ""
    try:
        resp = session.get(
            ALPHA_BASE,
            params={"function": "OVERVIEW", "symbol": symbol, "apikey": ALPHA_KEY},
            timeout=30,
        )
        resp.raise_for_status()
        js = resp.json()
        desc = js.get("Description") or ""
    except Exception:
        desc = ""
    desc = desc.strip()
    if len(desc) > 1200:
        desc = desc[:1200]
    desc_cache[symbol] = desc
    return desc


# ---------------------------------------------------------------------------
# GPT Classification (Responses API)
# ---------------------------------------------------------------------------


def classify_batch(batch, biztext):
    tickers_json = json.dumps(batch, indent=2)

    prompt = f"""
You are a NAICS classification engine. Use ticker industry, sector, and description to pick the closest business_type from the list.

Return VALID JSON ONLY; MUST be an array matching input order:
[
  {{
    "symbol": "...",
    "business_type": "...",
    "naics_code": "...",
    "confidence": 0.95
  }},
  ...
]

Rules:
- NEVER return blank/null/unknown fields.
- ALWAYS choose the closest business_type from the provided list.
- Use description if present; otherwise rely on industry/sector.
- If unsure, pick the closest reasonable match; do NOT leave anything empty.

INPUT TICKERS (symbol, industry, sector, description):
{tickers_json}

BUSINESS TYPES (business_type | naics_code | naics_title):
{biztext}
"""

    try:
        resp = client.responses.create(
            model="gpt-5.1",
            input=prompt,
            max_output_tokens=5000,
        )
    except Exception as e:
        print(f"[GPT REQUEST ERROR] {e}")
        return []

    raw = resp.output_text.strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == len(batch):
            return parsed
        print("[JSON SHAPE ERROR]", raw[:300])
        return []
    except Exception:
        try:
            json_start = raw.find("[")
            json_end = raw.rfind("]")
            if json_start != -1 and json_end != -1:
                cleaned = raw[json_start : json_end + 1]
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


def insert_mapping(row, cur):
    cur.execute(
        """
        INSERT INTO alpha_match_naics_industry
        (symbol, industry, sector, business_type, naics_code, naics_industry_name, confidence, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            row["symbol"],
            row["industry"],
            row["sector"],
            row["business_type"],
            row["naics_code"],
            row["naics_industry_name"],
            row["confidence"],
            date.today(),
        ),
    )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main():
    print("Loading business types from naics_master")
    naics_options = load_naics_options()
    if not naics_options:
        raise RuntimeError("No NAICS options loaded from naics_master (business_types + 6_digit + naics_title).")
    biztext = compress_business_types(naics_options)
    bt_lookup = {opt["business_type"]: (opt["naics_code"], opt["naics_title"]) for opt in naics_options}
    allowed_bt = set(bt_lookup.keys())

    print("Loading pending tickers")
    tickers_raw = load_unmapped_tickers().to_dict(orient="records")
    tickers = []
    for t in tickers_raw:
        desc = get_description(t["symbol"])
        tickers.append(
            {
                "symbol": t["symbol"],
                "industry": t.get("industry") or "",
                "sector": t.get("sector") or "",
                "description": desc,
            }
        )

    total = len(tickers)
    print(f"Total tickers needing mapping: {total}")

    conn = get_conn()
    cur = conn.cursor()

    batch_size = 20
    batches = (total + batch_size - 1) // batch_size
    mapped = 0

    for b in range(batches):
        batch = tickers[b * batch_size : (b + 1) * batch_size]
        print(f"\n[Batch {b+1}/{batches}] -> {[t['symbol'] for t in batch]}")

        results = classify_batch(batch, biztext)
        if not results:
            print("GPT batch failed. Skipping.")
            continue

        for i, result in enumerate(results):
            info = batch[i]

            bt_name = (result.get("business_type") or "Unknown").strip() or "Unknown"
            if bt_name not in allowed_bt:
                # Force to known option only
                first_opt = naics_options[0]
                bt_name = first_opt["business_type"]
            naics_code, naics_title = bt_lookup[bt_name]
            naics_code = naics_code.zfill(6)[:6]
            try:
                conf = float(result.get("confidence"))
            except Exception:
                conf = 0.5

            row = {
                "symbol": result.get("symbol") or info.get("symbol"),
                "industry": info.get("industry"),
                "sector": info.get("sector"),
                "business_type": bt_name,
                "naics_code": naics_code,
                "naics_industry_name": naics_title,
                "confidence": conf,
            }

            print(
                f" + {row['symbol']}: {row['business_type']} ({row['naics_code']}), NAICS Industry={row['naics_industry_name']}, conf={row['confidence']}"
            )

            insert_mapping(row, cur)
            mapped += 1

        conn.commit()
        print(f"Batch {b+1}/{batches} committed; mapped {mapped}/{total} tickers.")

    cur.close()
    conn.close()
    print("\nNAICS classification completed.\n")


if __name__ == "__main__":
    main()
