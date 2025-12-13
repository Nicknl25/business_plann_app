import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import mysql.connector
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Load root .env (hard-coded project root)
# ---------------------------------------------------------------------------

PROJECT_ROOT_NAME = "Business Plan Generator"


def get_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if parent.name == PROJECT_ROOT_NAME:
            return parent
    raise FileNotFoundError("Could not find project root folder.")


ROOT = get_project_root()
load_dotenv(ROOT / ".env", override=True)

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST"),
    "user": os.getenv("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD"),
    "database": os.getenv("MYSQL_DB"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
}

OPENAI_KEY = os.getenv("OPENAI_API_KEY")

EXCEL_PATH = Path(
    r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Business Plan Generator Sources\References\naics_cenesus_list.xlsx"
)

BATCH_SIZE = 50

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def get_conn():
    return mysql.connector.connect(**MYSQL_CONFIG)


def ensure_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS naics_master (
            id INT AUTO_INCREMENT PRIMARY KEY,
            raw_id TEXT,
            raw_naics_code TEXT,
            raw_naics_title TEXT,
            naics_code VARCHAR(10),
            naics_title TEXT,
            naics_2 VARCHAR(6),
            naics_3 VARCHAR(6),
            naics_4 VARCHAR(6),
            naics_5 VARCHAR(6),
            naics_6 VARCHAR(6),
            business_types TEXT,
            UNIQUE KEY uniq_code (naics_code)
        )
        """
    )
    # Add missing columns if table pre-existed
    cursor.execute(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'naics_master';
        """
    )
    cols = {row[0] for row in cursor.fetchall()}
    alters = []
    if "raw_id" not in cols:
        alters.append("ADD COLUMN raw_id TEXT")
    if "raw_naics_code" not in cols:
        alters.append("ADD COLUMN raw_naics_code TEXT")
    if "raw_naics_title" not in cols:
        alters.append("ADD COLUMN raw_naics_title TEXT")
    if "naics_code" not in cols:
        alters.append("ADD COLUMN naics_code VARCHAR(10)")
    if "naics_title" not in cols:
        alters.append("ADD COLUMN naics_title TEXT")
    if "naics_2" not in cols:
        alters.append("ADD COLUMN naics_2 VARCHAR(6)")
    if "naics_3" not in cols:
        alters.append("ADD COLUMN naics_3 VARCHAR(6)")
    if "naics_4" not in cols:
        alters.append("ADD COLUMN naics_4 VARCHAR(6)")
    if "naics_5" not in cols:
        alters.append("ADD COLUMN naics_5 VARCHAR(6)")
    if "naics_6" not in cols:
        alters.append("ADD COLUMN naics_6 VARCHAR(6)")
    if "business_types" not in cols:
        alters.append("ADD COLUMN business_types TEXT")
    for alter in alters:
        try:
            cursor.execute(f"ALTER TABLE naics_master {alter}")
        except Exception:
            pass


def insert_rows(cursor, rows: List[tuple]):
    sql = """
        INSERT INTO naics_master
        (raw_id, raw_naics_code, raw_naics_title,
         naics_code, naics_title, naics_2, naics_3, naics_4, naics_5, naics_6, business_types)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            raw_id=VALUES(raw_id),
            raw_naics_code=VALUES(raw_naics_code),
            raw_naics_title=VALUES(raw_naics_title),
            naics_title=VALUES(naics_title),
            naics_2=VALUES(naics_2),
            naics_3=VALUES(naics_3),
            naics_4=VALUES(naics_4),
            naics_5=VALUES(naics_5),
            naics_6=VALUES(naics_6),
            business_types=VALUES(business_types)
    """
    cursor.executemany(sql, rows)


# ---------------------------------------------------------------------------
# GPT helpers
# ---------------------------------------------------------------------------


def build_prompt(batch: List[Dict[str, str]]) -> str:
    lines = [f"{item['naics_code']} | {item['naics_title']}" for item in batch]
    lines_text = "\n".join(lines)

    return f"""
You are a business classification expert.

For EACH NAICS entry below, output ONE line ONLY:
- Containing 3 to 10 human-friendly business types
- Comma-separated
- No NAICS code repeated
- No numbering
- No JSON
- No quotes
- No explanations
- Keep output in EXACT SAME ORDER as input

Example output lines:
Coffee Shop, Boba Tea Shop, Smoothie Bar
Hair Salon, Blow Dry Bar, Women's Styling Studio

Now produce one line for each NAICS row below:

{lines_text}
"""



def call_gpt_batch(client: OpenAI, batch: List[Dict[str, str]]) -> Dict[str, Optional[str]]:
    prompt = build_prompt(batch)

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=3000
        )

        raw = (resp.choices[0].message.content or "").strip()

        # Split output into lines
        lines = [line.strip() for line in raw.split("\n") if line.strip()]

        # Validate response count
        if len(lines) != len(batch):
            raise Exception(f"GPT returned {len(lines)} lines but expected {len(batch)}")

        # Map output lines back to NAICS codes
        out = {}
        for record, line in zip(batch, lines):
            out[str(record["naics_code"]).strip()] = line

        return out

    except Exception as e:
        print(f"GPT batch error: {e}")
        return {}



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def clean_code(val: str) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "", "none"):
        return None
    return s


def main():
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"Excel file not found: {EXCEL_PATH}")

    print("Loading Excel...")
    raw_df = pd.read_excel(EXCEL_PATH)
    # take first three columns to avoid trailing blanks
    raw_df = raw_df.iloc[:, :3]
    raw_df.columns = ["raw_id", "raw_naics_code", "raw_naics_title"]

    # Drop fully empty rows
    raw_df = raw_df.dropna(how="all")

    # Clean codes/titles
    raw_df["naics_code"] = raw_df["raw_naics_code"].apply(clean_code)
    raw_df["naics_title"] = raw_df["raw_naics_title"].apply(lambda x: str(x).strip() if pd.notna(x) else None)

    # Filter out rows without a code
    raw_df = raw_df[raw_df["naics_code"].notna()].copy()

    # Digit splits
    raw_df["naics_2"] = raw_df["naics_code"].apply(lambda x: x if len(x) == 2 else None)
    raw_df["naics_3"] = raw_df["naics_code"].apply(lambda x: x if len(x) == 3 else None)
    raw_df["naics_4"] = raw_df["naics_code"].apply(lambda x: x if len(x) == 4 else None)
    raw_df["naics_5"] = raw_df["naics_code"].apply(lambda x: x if len(x) == 5 else None)
    raw_df["naics_6"] = raw_df["naics_code"].apply(lambda x: x if len(x) == 6 else None)

    raw_df["business_types"] = None

    # GPT for 6-digit codes
    if OPENAI_KEY and not raw_df.empty:
        client = OpenAI(api_key=OPENAI_KEY)
        six_df = raw_df[raw_df["naics_6"].notna()].copy()
        batches = [
            six_df.iloc[i : i + BATCH_SIZE]
            for i in range(0, len(six_df), BATCH_SIZE)
        ]
        for idx, batch_df in enumerate(batches, start=1):
            batch_records = batch_df[["naics_code", "naics_title"]].to_dict(orient="records")
            print(f"GPT batch {idx}/{len(batches)}: {len(batch_records)} rows")
            result_map = call_gpt_batch(client, batch_records)
            for code, bt in result_map.items():
                raw_df.loc[raw_df["naics_code"] == code, "business_types"] = bt
            time.sleep(0.5)

    print("Writing to MySQL...")
    conn = get_conn()
    cur = conn.cursor()
    ensure_table(cur)

    rows = [
        (
            row.raw_id,
            row.raw_naics_code,
            row.raw_naics_title,
            row.naics_code,
            row.naics_title,
            row.naics_2,
            row.naics_3,
            row.naics_4,
            row.naics_5,
            row.naics_6,
            row.business_types,
        )
        for row in raw_df.itertuples()
    ]
    insert_rows(cur, rows)
    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
