import os
import sys
import time
from datetime import date, datetime
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector
import pandas as pd
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment loading (root .env located via project folder name)
# ---------------------------------------------------------------------------

PROJECT_ROOT_NAME = "Business Plan Generator"


def get_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if parent.name == PROJECT_ROOT_NAME:
            return parent
    raise FileNotFoundError(f"Could not locate project root '{PROJECT_ROOT_NAME}'")


def load_env() -> Path:
    env_file = get_project_root() / ".env"
    if not env_file.exists():
        raise FileNotFoundError(f"Expected root .env at {env_file}")
    # Hard-coded to the root .env to avoid picking up other .env files
    if not load_dotenv(dotenv_path=env_file, override=True):
        raise RuntimeError(f"Could not load environment variables from {env_file}")
    return env_file.parent


def env_value(*keys: str, default: Optional[str] = None) -> Optional[str]:
    for key in keys:
        val = os.getenv(key)
        if val is not None and str(val).strip() != "":
            return val
    return default


def load_symbols_from_csv(csv_path: Path) -> List[str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Ticker CSV not found at {csv_path}")
    df = pd.read_csv(csv_path)
    # Preferred column names; fallback to first column
    candidates = [c for c in df.columns if c.lower() in {"symbol", "ticker"}]
    col = candidates[0] if candidates else df.columns[0]
    symbols = (
        df[col]
        .astype(str)
        .str.strip()
        .replace({"": pd.NA})
        .dropna()
        .unique()
        .tolist()
    )
    return [s for s in symbols if s]


# ---------------------------------------------------------------------------
# Helpers: parsing and simple type checks
# ---------------------------------------------------------------------------

def parse_date_env(key: str) -> date:
    val = env_value(key)
    if val is None:
        raise ValueError(f"{key} missing in environment")
    try:
        parsed = pd.to_datetime(val).date()
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"Could not parse {key}='{val}' as date") from exc
    return parsed


def bool_env(key: str, default: bool = False) -> bool:
    raw = env_value(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "t", "yes", "y"}


def numeric_env(key: str, default: Optional[int] = None) -> Optional[int]:
    raw = env_value(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def is_numeric_like(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return False
    if pd.api.types.is_numeric_dtype(series):
        return True
    sample = series.dropna()
    if sample.empty:
        return False
    sample = sample.astype(str).str.replace(",", "", regex=False).str.strip()
    sample = sample[~sample.isin(["", "NA", "NaN", "null", "NULL"])]
    if sample.empty:
        return False
    coerced = pd.to_numeric(sample, errors="coerce")
    valid_ratio = coerced.notna().mean()
    return valid_ratio >= 0.8 and coerced.notna().sum() > 0


def coerce_numeric_like_cols(df: pd.DataFrame) -> pd.DataFrame:
    def keep_text(col_name: str) -> bool:
        return bool(
            pd.Series(col_name)
            .str.contains("currency|industry|symbol|horizon|source|statement_type", case=False, regex=True)
            .iloc[0]
        )

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        if keep_text(col):
            continue
        if is_numeric_like(df[col]):
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
    return df


def normalize_value(val: Any) -> Any:
    """
    Robustly convert values so MySQL gets clean NULLs for invalid/blank inputs.
    - For strings: treat NaN/nan/None/'-'/' ' as NULL; if numeric-like, return float.
    - For numbers: pass through unless NaN, which becomes NULL.
    - For datetime/Timestamp: return date portion.
    """
    if val is None:
        return None
    # Handle pandas NA / NaN
    if isinstance(val, float) and pd.isna(val):
        return None
    if pd.isna(val):
        return None
    # Strings: trim and check for invalids
    if isinstance(val, str):
        s = val.strip()
        if s == "" or s.lower() in {"nan", "none", "-", "null"}:
            return None
        try:
            # Prefer numeric parse when possible
            num = float(s.replace(",", ""))
            return num
        except ValueError:
            return s  # keep as text
    # Datetime-like -> date
    if isinstance(val, (pd.Timestamp, datetime)):
        return val.date()
    return val


def normalize_datetime_series(series: pd.Series) -> pd.Series:
    """Convert to pandas Timestamps normalized to midnight for consistent comparisons."""
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def to_timestamp_set(values: List[Any]) -> set[pd.Timestamp]:
    """Convert iterable of date-like values to a set of normalized pandas Timestamps."""
    return set(normalize_datetime_series(pd.Series(values)).dropna().tolist())


# ---------------------------------------------------------------------------
# Alpha Vantage client helpers
# ---------------------------------------------------------------------------

ALPHA_BASE = "https://www.alphavantage.co/query"
session = requests.Session()
alpha_key: Optional[str] = None
end_date_global: Optional[date] = None
start_ts: Optional[pd.Timestamp] = None
end_ts: Optional[pd.Timestamp] = None


def polite_get(params: Dict[str, Any], *, timeout: int = 60) -> requests.Response:
    resp = session.get(ALPHA_BASE, params=params, timeout=timeout, headers={"User-Agent": "BusinessPlanApp/1.0"})
    if resp.status_code in {429, 500, 502, 503, 504}:
        time.sleep(1)
        resp = session.get(ALPHA_BASE, params=params, timeout=timeout, headers={"User-Agent": "BusinessPlanApp/1.0"})
    resp.raise_for_status()
    return resp


def get_alpha(function_name: str, symbol: str) -> pd.DataFrame:
    params = {"function": function_name, "symbol": symbol, "apikey": alpha_key}
    resp = polite_get(params)
    js = resp.json()

    note_text = js.get("Note") or js.get("Information") or js.get("Error Message")
    if note_text:
        print(f"Alpha Vantage response for {function_name}/{symbol}: {note_text}")

    qr = js.get("quarterlyReports")
    if qr is not None:
        df = pd.DataFrame(qr)
        if "fiscalDateEnding" in df.columns:
            df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"], errors="coerce")
        df["symbol"] = symbol
        df["statement_type"] = function_name
        return df

    if function_name == "OVERVIEW":
        return pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "industry": js.get("Industry"),
                    "sharesOutstanding": pd.to_numeric(js.get("SharesOutstanding"), errors="coerce"),
                }
            ]
        )

    if function_name == "GLOBAL_QUOTE":
        gq = js.get("Global Quote") or {}
        price = pd.to_numeric(gq.get("05. price"), errors="coerce")
        return pd.DataFrame([{"symbol": symbol, "sharePrice": price}])

    return pd.DataFrame()


price_cache: Dict[str, pd.DataFrame] = {}


def get_share_price_on_date(symbol: str, target_date: Any) -> Optional[float]:
    if pd.isna(target_date):
        return None
    if symbol not in price_cache:
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "apikey": alpha_key,
            "outputsize": "full",
        }
        resp = polite_get(params)
        js = resp.json()
        ts = js.get("Time Series (Daily)")
        if ts is None:
            return None
        records = []
        for d_str, vals in ts.items():
            dt = pd.to_datetime(d_str, errors="coerce")
            adj = pd.to_numeric(vals.get("5. adjusted close"), errors="coerce")
            records.append((dt, adj))
        df = pd.DataFrame(records, columns=["d", "adj"]).sort_values("d")
        if end_ts is not None:
            df = df[df["d"] <= end_ts]
        price_cache[symbol] = df
    df = price_cache[symbol]
    if df.empty:
        return None
    target_dt = pd.to_datetime(target_date, errors="coerce")
    if pd.isna(target_dt):
        return None
    filtered = df[df["d"] <= target_dt]
    if filtered.empty:
        return None
    return float(filtered.tail(1)["adj"].iloc[0]) if pd.notna(filtered.tail(1)["adj"].iloc[0]) else None


def get_earnings_calendar(symbol: str) -> pd.DataFrame:
    horizons = ["3month", "6month", "12month"]
    out: Dict[str, Optional[date]] = {}
    for horizon in horizons:
        params = {
            "function": "EARNINGS_CALENDAR",
            "symbol": symbol,
            "horizon": horizon,
            "apikey": alpha_key,
        }
        resp = polite_get(params)
        text = resp.text
        cal_df = None
        try:
            js = resp.json()
            if isinstance(js, dict) and js.get("earningsCalendar") is not None:
                cal_df = pd.DataFrame(js["earningsCalendar"])
        except Exception:
            cal_df = None
        if cal_df is None:
            try:
                cal_df = pd.read_csv(io.StringIO(text))
            except Exception:
                cal_df = None
        if cal_df is not None and not cal_df.empty:
            date_cols = [c for c in cal_df.columns if c.lower() in {"reportdate", "report_date", "reportdate"}]
            report_col = date_cols[0] if date_cols else None
            if report_col:
                dates = pd.to_datetime(cal_df[report_col], errors="coerce")
                earliest = dates.min()
                out[horizon] = earliest.date() if pd.notna(earliest) else None
            else:
                out[horizon] = None
        else:
            out[horizon] = None
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "earningsDate_3M": out.get("3month"),
                "earningsDate_6M": out.get("6month"),
                "earningsDate_12M": out.get("12month"),
            }
        ]
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_connection(host: str, user: str, password: str, database: str) -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(host=host, user=user, password=password, database=database)


def get_indexed_columns(conn: mysql.connector.MySQLConnection, table: str) -> List[str]:
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"SHOW INDEX FROM `{table}`")
        rows = cur.fetchall()
        return list({row["Column_name"] for row in rows})
    except mysql.connector.Error:
        return []
    finally:
        cur.close()


def compute_field_types(
    df: pd.DataFrame, conn: Optional[mysql.connector.MySQLConnection] = None, table: Optional[str] = None
) -> Dict[str, str]:
    indexed = set(get_indexed_columns(conn, table)) if conn and table else set()
    types: Dict[str, str] = {}
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            types[col] = "DATE NULL"
        elif is_numeric_like(series):
            types[col] = "DOUBLE NULL"
        else:
            types[col] = "VARCHAR(255) NULL" if col in indexed or col == "symbol" else "TEXT NULL"
    return types


def sync_table_schema(conn: mysql.connector.MySQLConnection, table: str, df: pd.DataFrame) -> None:
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        info = cur.fetchall()
    except mysql.connector.Error:
        cur.close()
        return

    existing_fields = [row["Field"] for row in info]
    to_add = [col for col in df.columns if col not in existing_fields]
    if to_add:
        ft = compute_field_types(df[to_add], conn=conn, table=table)
        for col in to_add:
            col_type = ft[col]
            cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col}` {col_type}")
        conn.commit()
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        info = cur.fetchall()
        existing_fields = [row["Field"] for row in info]

    indexed = set(get_indexed_columns(conn, table))
    for row in info:
        col = row["Field"]
        if col not in df.columns:
            continue
        series = df[col]
        desired = (
            "DATE"
            if pd.api.types.is_datetime64_any_dtype(series)
            else ("NUMERIC" if is_numeric_like(series) else ("VARCHAR" if col in indexed or col == "symbol" else "TEXT"))
        )
        current = row["Type"].lower()
        is_date = "date" in current
        is_numeric_family = any(
            kw in current for kw in ["double", "float", "decimal", "numeric", "int", "bigint", "real"]
        )
        is_double = "double" in current
        is_text_family = ("text" in current) or ("char" in current)
        is_varchar = current.startswith("varchar")

        # Always widen numeric-family columns to DOUBLE NULL to avoid truncation.
        if is_numeric_family and not is_double:
            cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` DOUBLE NULL")
            continue

        if desired == "DATE":
            if not is_date:
                cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` DATE NULL")
        elif desired == "NUMERIC":
            # Stay within numeric family; widen to DOUBLE to avoid truncation
            if is_numeric_family and not is_double:
                cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` DOUBLE NULL")
            elif not is_numeric_family:
                # Respect request: do not flip text->numeric
                continue
        elif desired == "TEXT":
            # Stay within text family; widen varchar to at least 255 or TEXT
            if is_text_family:
                if is_varchar:
                    widen = True
                    try:
                        size = int(current.split("(")[1].split(")")[0])
                        widen = size < 255
                    except Exception:
                        widen = True
                    if widen:
                        cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` VARCHAR(255) NULL")
                elif "text" not in current:
                    try:
                        cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` TEXT NULL")
                    except mysql.connector.Error:
                        pass
            else:
                # Respect request: do not flip numeric->text
                continue
        elif desired == "VARCHAR":
            if not is_varchar:
                cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` VARCHAR(255) NULL")
            else:
                try:
                    size = int(current.split("(")[1].split(")")[0])
                    if size < 255:
                        cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` VARCHAR(255) NULL")
                except Exception:
                    cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` VARCHAR(255) NULL")
    conn.commit()
    cur.close()


def create_table_from_df(conn: mysql.connector.MySQLConnection, table: str, df: pd.DataFrame) -> None:
    ft = compute_field_types(df, conn=conn, table=table)
    cols_sql = ", ".join(f"`{col}` {ft[col]}" for col in df.columns)
    cur = conn.cursor()
    cur.execute(f"CREATE TABLE IF NOT EXISTS `{table}` ({cols_sql})")
    conn.commit()
    cur.close()


def fetch_existing_symbol_dates(
    conn: mysql.connector.MySQLConnection,
    table: str,
    symbol: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> set[date]:
    cur = conn.cursor(dictionary=True)
    sql = f"SELECT fiscalDateEnding FROM `{table}` WHERE symbol = %s"
    params: List[Any] = [symbol]
    if start is not None and end is not None:
        sql += " AND fiscalDateEnding BETWEEN %s AND %s"
        params.extend([start, end])
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    cur.close()
    date_series = pd.Series([r["fiscalDateEnding"] for r in rows])
    return set(normalize_datetime_series(date_series).dropna().tolist())


def insert_rows(
    conn: mysql.connector.MySQLConnection, table: str, df: pd.DataFrame, chunk_size: int = 500
) -> int:
    if df.empty:
        return 0
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    col_sql = ", ".join(f"`{c}`" for c in cols)
    sql = f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})"
    cur = conn.cursor()
    inserted = 0
    rows_iter = df.itertuples(index=False, name=None)
    batch: List[Tuple[Any, ...]] = []
    for row in rows_iter:
        batch.append(tuple(normalize_value(v) for v in row))
        if len(batch) >= chunk_size:
            cur.executemany(sql, batch)
            conn.commit()
            inserted += len(batch)
            batch = []
    if batch:
        cur.executemany(sql, batch)
        conn.commit()
        inserted += len(batch)
    cur.close()
    return inserted


# ---------------------------------------------------------------------------
# Data assembly per symbol
# ---------------------------------------------------------------------------

start_date: Optional[date] = None


def make_symbol_frame(symbol: str) -> pd.DataFrame:
    inc = get_alpha("INCOME_STATEMENT", symbol)
    bal = get_alpha("BALANCE_SHEET", symbol)
    cfl = get_alpha("CASH_FLOW", symbol)

    frames = []
    for df in (inc, bal, cfl):
        if df is not None and not df.empty:
            df = df.drop(columns=[c for c in df.columns if c == "statement_type"], errors="ignore")
            if "fiscalDateEnding" in df.columns:
                df["fiscalDateEnding"] = normalize_datetime_series(df["fiscalDateEnding"])
            frames.append(df)

    if not frames:
        joined = pd.DataFrame([{"symbol": symbol, "fiscalDateEnding": pd.NaT}])
    elif len(frames) == 1:
        joined = frames[0]
    else:
        joined = frames[0]
        for df in frames[1:]:
            joined = joined.merge(df, on=["fiscalDateEnding", "symbol"], how="outer")

    if joined.empty:
        joined = pd.DataFrame([{"symbol": symbol, "fiscalDateEnding": pd.NaT}])

    # overview = get_alpha("OVERVIEW", symbol)
    # if overview is not None and not overview.empty:
    #     joined["industry"] = overview.get("industry", pd.Series([None])).iloc[0]
    #     joined["sharesOutstanding"] = overview.get("sharesOutstanding", pd.Series([None])).iloc[0]

    # if "fiscalDateEnding" in joined.columns:
    #     joined["sharePrice"] = joined["fiscalDateEnding"].apply(lambda d: get_share_price_on_date(symbol, d))

    # cal = get_earnings_calendar(symbol)
    # if cal is not None and not cal.empty:
    #     joined["earningsDate_3M"] = cal["earningsDate_3M"].iloc[0]
    #     joined["earningsDate_6M"] = cal["earningsDate_6M"].iloc[0]
    #     joined["earningsDate_12M"] = cal["earningsDate_12M"].iloc[0]

    joined["symbol"] = symbol
    joined["pull_date"] = date.today()

    if "fiscalDateEnding" in joined.columns and start_ts is not None and end_ts is not None:
        joined = joined[
            (joined["fiscalDateEnding"].isna())
            | (
                (joined["fiscalDateEnding"] >= start_ts)
                & (joined["fiscalDateEnding"] <= end_ts)
            )
        ]

    return joined


# ---------------------------------------------------------------------------
# Earnings calendar persistence
# ---------------------------------------------------------------------------

def write_earnings_calendar(conn: mysql.connector.MySQLConnection, symbol: str, cal_df: pd.DataFrame) -> None:
    if cal_df is None or cal_df.empty:
        return
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS `Earnings_Calendar` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `symbol` VARCHAR(10),
            `horizon` VARCHAR(10),
            `reportDate` DATE,
            `pull_date` DATE,
            `source` VARCHAR(20)
        )
        """
    )
    cur.execute("DELETE FROM `Earnings_Calendar` WHERE symbol = %s", (symbol,))
    conn.commit()
    cur.close()

    cal_rows = pd.DataFrame(
        {
            "symbol": symbol,
            "horizon": ["3month", "6month", "12month"],
            "reportDate": [
                cal_df["earningsDate_3M"].iloc[0],
                cal_df["earningsDate_6M"].iloc[0],
                cal_df["earningsDate_12M"].iloc[0],
            ],
            "pull_date": date.today(),
            "source": "AlphaVantage",
        }
    )
    cal_rows = cal_rows.dropna(subset=["reportDate"])
    insert_rows(conn, "Earnings_Calendar", cal_rows)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    global alpha_key, start_date, end_date_global, start_ts, end_ts

    project_root = load_env()
    start_date = parse_date_env("START_DATE")
    end_date_global = parse_date_env("END_DATE")
    if start_date is None or end_date_global is None:
        raise RuntimeError("START_DATE or END_DATE missing/invalid in environment (.env)")
    start_ts = pd.to_datetime(start_date).normalize()
    end_ts = pd.to_datetime(end_date_global).normalize()

    alpha_key = env_value("ALPHAVANTAGE_API_KEY")
    if alpha_key is None:
        raise EnvironmentError("ALPHAVANTAGE_API_KEY is missing. Add it to .env")

    mysql_host = env_value("MYSQL_HOST", "DB_HOST")
    mysql_user = env_value("MYSQL_USER", "DB_USER")
    mysql_password = env_value("MYSQL_PASSWORD", "DB_PASSWORD")
    mysql_db = env_value("MYSQL_DATABASE", "MYSQL_DB", "DB_NAME", default="business_plan_app")

    missing = [k for k, v in {"MYSQL_HOST": mysql_host, "MYSQL_USER": mysql_user, "MYSQL_PASSWORD": mysql_password}.items() if v is None]
    if missing:
        raise EnvironmentError(f"Missing DB env vars: {', '.join(missing)}")

    api_sleep_env = env_value("API_SLEEP_SECONDS")
    try:
        api_sleep = float(api_sleep_env) if api_sleep_env is not None else 2.0
    except ValueError:
        api_sleep = 2.0
    api_sleep = min(api_sleep, 15.0)
    print(f"API pacing: {api_sleep} seconds between symbols")

    test_mode = bool_env("TEST_MODE", default=False)
    ticker_limit = numeric_env("TICKER_LIMIT", default=10)
    tbl_name = "alpha_data"

    ticker_csv = Path(
        r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Business Plan Generator Sources\References\ticker symbols.csv"
    )
    symbols = load_symbols_from_csv(ticker_csv)
    if test_mode and ticker_limit is not None and ticker_limit > 0:
        symbols = symbols[: ticker_limit]

    if test_mode:
        print(f"Running TEST MODE: start={start_date}, end={end_date_global}, tickers={len(symbols)}")
    print(f"Processing {len(symbols)} symbols: {', '.join(symbols)}")

    new_rows_total = 0

    for idx, sym in enumerate(symbols, start=1):
        conn = None
        try:
            print(f"Processing {idx} of {len(symbols)}: {sym} ...")
            sym_df = make_symbol_frame(sym)
            sym_df = coerce_numeric_like_cols(sym_df)

            conn = get_connection(mysql_host, mysql_user, mysql_password, mysql_db)
            cur = conn.cursor()

            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                (mysql_db, tbl_name),
            )
            exists = cur.fetchone()[0] > 0
            cur.close()

            existing_dates: set[pd.Timestamp] = set()
            if exists:
                existing_dates = fetch_existing_symbol_dates(conn, tbl_name, sym, start_date, end_date_global)
            sym_dates = (
                to_timestamp_set(sym_df["fiscalDateEnding"].tolist()) if "fiscalDateEnding" in sym_df.columns else set()
            )
            if sym_dates and sym_dates.issubset(existing_dates):
                print(f"All dates for {sym} already present; skipping.")
                continue
            if "fiscalDateEnding" in sym_df.columns and existing_dates:
                fd_norm = normalize_datetime_series(sym_df["fiscalDateEnding"])
                sym_df = sym_df[fd_norm.isna() | (~fd_norm.isin(existing_dates))]
            if sym_df.empty:
                print(f"No new rows for {sym}; skipping.")
                continue

            if not exists:
                print(f"Creating table {tbl_name} ...")
                create_table_from_df(conn, tbl_name, sym_df)
                appended = insert_rows(conn, tbl_name, sym_df)
            else:
                sync_table_schema(conn, tbl_name, sym_df)
                cur = conn.cursor()
                for legacy_col in ["earningsReportDate", "earningsDate_3M", "earningsDate_6M", "earningsDate_12M"]:
                    cur.execute(
                        f"SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name=%s",
                        (mysql_db, tbl_name, legacy_col),
                    )
                    if cur.fetchone()[0]:
                        cur.execute(f"ALTER TABLE `{tbl_name}` DROP COLUMN `{legacy_col}`")
                # cur.execute(
                #     f"SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name='sharePrice'",
                #     (mysql_db, tbl_name),
                # )
                # if not cur.fetchone()[0]:
                #     cur.execute(f"ALTER TABLE `{tbl_name}` ADD COLUMN `sharePrice` DOUBLE NULL")
                # cur.execute(f"ALTER TABLE `{tbl_name}` MODIFY COLUMN `sharePrice` DOUBLE NULL")
                conn.commit()
                cur.close()

                table_fields_cur = conn.cursor()
                table_fields_cur.execute(f"SHOW COLUMNS FROM `{tbl_name}`")
                table_fields = [row[0] for row in table_fields_cur.fetchall()]
                table_fields_cur.close()

                # Build insert frame in one shot to avoid fragmentation warnings
                to_insert = sym_df.reindex(columns=table_fields)

                appended = insert_rows(conn, tbl_name, to_insert)

                # updates = sym_df[["symbol", "fiscalDateEnding", "sharePrice"]].drop_duplicates()
                # updates = updates[pd.notna(updates["fiscalDateEnding"])]
                # updates["fiscalDateEnding"] = pd.to_datetime(updates["fiscalDateEnding"], errors="coerce").dt.date
                # updates = updates[pd.notna(updates["sharePrice"])]
                # if not updates.empty:
                #     upd_sql = f"UPDATE `{tbl_name}` SET sharePrice = %s WHERE symbol = %s AND fiscalDateEnding = %s"
                #     upd_rows = [
                #         (float(r.sharePrice), r.symbol, r.fiscalDateEnding) for r in updates.itertuples(index=False)
                #     ]
                #     cur = conn.cursor()
                #     cur.executemany(upd_sql, upd_rows)
                #     conn.commit()
                #     cur.close()

            # cal_row = get_earnings_calendar(sym)
            # write_earnings_calendar(conn, sym, cal_row)

            new_rows_total += int(appended)
            print(f"Appended {int(appended)} new rows for {sym}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            if sym in price_cache:
                price_cache.pop(sym, None)
            time.sleep(api_sleep)

    print("\nSummary:")
    print(f"- Symbols processed: {len(symbols)}")
    print(f"- New rows appended: {new_rows_total:,}")

    conn_chk = get_connection(mysql_host, mysql_user, mysql_password, mysql_db)
    cur_chk = conn_chk.cursor()
    cur_chk.execute(
        f"SELECT COUNT(*) AS n FROM `{tbl_name}` WHERE fiscalDateEnding BETWEEN %s AND %s",
        (start_date, end_date_global),
    )
    recent_rows = cur_chk.fetchone()[0]
    print(f"- Rows within date range now in table: {recent_rows:,}")
    cur_chk.close()

    conn_chk.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - script entrypoint
        print(f"Error: {exc}")
        sys.exit(1)
