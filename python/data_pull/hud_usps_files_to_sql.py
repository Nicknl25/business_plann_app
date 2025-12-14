"""
Bulk load HUD USPS reference files into MySQL, one table per file.

Source folder (absolute):
    C:/Users/ignat/OneDrive - Tithe Financial Wealth Management/Apps/Business Plan Generator Sources/References/HUD USPS

Behavior:
    - Table name = HUD_<filename_without_extension>
    - If table exists, DROP it and recreate.
    - If table does not exist, create it.
    - Then insert all rows from the file.
    - Supports CSV and Excel (.xlsx/.xls).

Type rules (per column):
    - If column is mostly numeric: DECIMAL(38,10) NULL
    - Otherwise: LONGTEXT NULL
    - Column names are normalized to snake_case, stripped of spaces/special chars.

Usage:
    python python/data_pull/hud_usps_files_to_sql.py
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import mysql.connector
import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT_NAME = "Business Plan Generator"
SOURCE_DIR = Path(
    r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Business Plan Generator Sources\References\HUD USPS"
)


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def get_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if parent.name == PROJECT_ROOT_NAME:
            return parent
    raise FileNotFoundError(f"Could not locate project root '{PROJECT_ROOT_NAME}'")


ROOT = get_project_root()
env_path = ROOT / ".env"
if not env_path.exists():
    raise FileNotFoundError(f"Root .env not found at {env_path}")
if not load_dotenv(env_path, override=True):
    raise RuntimeError(f"Failed to load environment from {env_path}")

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST"),
    "user": os.getenv("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD"),
    "database": os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_conn() -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(**MYSQL_CONFIG)


def normalize_col(name: str) -> str:
    # lower, replace non-alnum with underscore, collapse repeats, strip edges
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "col"


def infer_types(df: pd.DataFrame) -> Dict[str, str]:
    col_types: Dict[str, str] = {}
    for col in df.columns:
        series = df[col]
        # drop na and trim strings for inference
        if pd.api.types.is_numeric_dtype(series):
            col_types[col] = "DECIMAL(38,10) NULL"
            continue
        sample = series.dropna()
        if sample.empty:
            col_types[col] = "LONGTEXT NULL"
            continue
        sample_as_num = pd.to_numeric(sample, errors="coerce")
        valid_ratio = sample_as_num.notna().mean()
        if valid_ratio >= 0.8:
            col_types[col] = "DECIMAL(38,10) NULL"
        else:
            col_types[col] = "LONGTEXT NULL"
    return col_types


def ensure_table(conn: mysql.connector.MySQLConnection, table: str, df: pd.DataFrame) -> None:
    cur = conn.cursor()
    # Drop if exists, then create fresh
    cur.execute(f"DROP TABLE IF EXISTS `{table}`")
    col_types = infer_types(df)
    cols_sql = ", ".join(f"`{normalize_col(c)}` {col_types[c]}" for c in df.columns)
    cur.execute(
        f"""
        CREATE TABLE `{table}` (
            id INT AUTO_INCREMENT PRIMARY KEY,
            {cols_sql}
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """
    )
    conn.commit()
    cur.close()


def upsert_rows(conn: mysql.connector.MySQLConnection, table: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    df = df.copy()
    df.columns = [normalize_col(c) for c in df.columns]
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(f"`{c}`" for c in cols)
    sql = f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})"
    cur = conn.cursor()
    cur.executemany(sql, [tuple(row) for row in df.itertuples(index=False, name=None)])
    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported file type: {path}")


def main() -> None:
    if not SOURCE_DIR.exists() or not SOURCE_DIR.is_dir():
        raise FileNotFoundError(f"Source directory not found: {SOURCE_DIR}")

    files = [p for p in SOURCE_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".xlsx", ".xls"}]
    if not files:
        print("No CSV/XLSX files found in source directory.")
        return

    conn = get_conn()
    try:
        for path in files:
            table = f"HUD_{path.stem}"
            print(f"Loading {path.name} -> table {table} ...")
            df = load_file(path)
            if df.empty:
                print(f"  Skipped {path.name}: empty file.")
                continue
            ensure_table(conn, table, df)
            upsert_rows(conn, table, df)
            print(f"  Inserted/updated {len(df)} rows into {table}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
