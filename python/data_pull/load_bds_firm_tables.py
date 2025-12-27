from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable, List, Optional

import mysql.connector
from mysql.connector.constants import ClientFlag


def _find_project_root(start: Path) -> Path:
  current = start.resolve()
  for _ in range(8):
    if (current / ".env").exists():
      return current
    if current.parent == current:
      break
    current = current.parent
  return start.resolve()


def _load_dotenv_from_root() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  root = _find_project_root(Path(__file__).resolve())
  env_path = root / ".env"
  if env_path.exists():
    load_dotenv(str(env_path))


def _getenv_required(name: str) -> str:
  value = (os.getenv(name) or "").strip()
  if not value:
    raise RuntimeError(f"Missing required env var: {name}")
  return value


def _mysql_port() -> int:
  raw = (os.getenv("MYSQL_PORT") or "3306").strip()
  try:
    return int(raw)
  except ValueError:
    return 3306


def _detect_line_terminator(csv_path: Path) -> str:
  try:
    with csv_path.open("rb") as f:
      chunk = f.read(65536)
    if b"\r\n" in chunk:
      return r"\r\n"
  except Exception:
    pass
  return r"\n"


def _sql_quote_literal(value: str) -> str:
  return "'" + value.replace("\\", "/").replace("'", "''") + "'"


def _pick_existing_path(candidates: List[Path]) -> Path:
  for candidate in candidates:
    if candidate.exists():
      return candidate
  return candidates[0]


# Numeric columns in the exact order of both CSV headers.
NUMERIC_COLS: List[str] = [
  "firms",
  "estabs",
  "emp",
  "denom",
  "estabs_entry",
  "estabs_entry_rate",
  "estabs_exit",
  "estabs_exit_rate",
  "job_creation",
  "job_creation_births",
  "job_creation_continuers",
  "job_creation_rate_births",
  "job_creation_rate",
  "job_destruction",
  "job_destruction_deaths",
  "job_destruction_continuers",
  "job_destruction_rate_deaths",
  "job_destruction_rate",
  "net_job_creation",
  "net_job_creation_rate",
  "reallocation_rate",
  "firmdeath_firms",
  "firmdeath_estabs",
  "firmdeath_emp",
]


def _bucket_column(conn, *, table: str, candidates: List[str]) -> str:
  cur = conn.cursor()
  try:
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    cols = {str(row[0]).strip().lower() for row in cur.fetchall()}
  finally:
    try:
      cur.close()
    except Exception:
      pass
  for c in candidates:
    if c.lower() in cols:
      return c
  raise RuntimeError(
    f"Unable to find bucket column in `{table}`. Expected one of: {candidates}"
  )


def _build_load_sql(
  *,
  table: str,
  csv_path: Path,
  fixed_cols: List[str],
  bucket_var: str,
  bucket_col: str,
) -> str:
  line_term = _detect_line_terminator(csv_path)
  file_lit = _sql_quote_literal(str(csv_path))
  columns_clause = (
    f"({', '.join(fixed_cols)}, @{bucket_var}, {', '.join(f'@{c}' for c in NUMERIC_COLS)})"
  )
  set_parts = [f"`{bucket_col}` = NULLIF(@{bucket_var}, '')"]
  set_parts += [f"`{c}` = NULLIF(@{c}, '')" for c in NUMERIC_COLS]
  return f"""LOAD DATA LOCAL INFILE {file_lit}
INTO TABLE `{table}`
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '{line_term}'
IGNORE 1 LINES
{columns_clause}
SET
  {', '.join(set_parts)};"""


DEFAULT_FIRM_AGE_CANDIDATES = [
  Path(r"C:\mysql_import\Business Dynanics Statistics - Firm Age.csv"),
  Path(
    r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Business Plan Generator Sources\References\Business Dynanics Statistics - Firm Age.csv"
  ),
]
DEFAULT_FIRM_SIZE_CANDIDATES = [
  Path(r"C:\mysql_import\Business Dynanics Statistics - Firm Size.csv"),
  Path(
    r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Business Plan Generator Sources\References\Business Dynanics Statistics - Firm Size.csv"
  ),
]


def main(argv: Optional[Iterable[str]] = None) -> int:
  parser = argparse.ArgumentParser(
    description="Load BDS Firm Age and Firm Size CSVs into local MySQL tables."
  )
  parser.add_argument(
    "--firm-age-csv",
    default=(os.getenv("BDS_FIRM_AGE_CSV") or "").strip() or None,
    help="Path to Firm Age CSV (env: BDS_FIRM_AGE_CSV).",
  )
  parser.add_argument(
    "--firm-size-csv",
    default=(os.getenv("BDS_FIRM_SIZE_CSV") or "").strip() or None,
    help="Path to Firm Size CSV (env: BDS_FIRM_SIZE_CSV).",
  )
  parser.add_argument(
    "--truncate",
    action="store_true",
    help="TRUNCATE target tables before loading.",
  )
  args = parser.parse_args(list(argv) if argv is not None else None)

  _load_dotenv_from_root()

  firm_age_csv = (
    Path(args.firm_age_csv).expanduser()
    if args.firm_age_csv
    else _pick_existing_path(DEFAULT_FIRM_AGE_CANDIDATES)
  )
  firm_size_csv = (
    Path(args.firm_size_csv).expanduser()
    if args.firm_size_csv
    else _pick_existing_path(DEFAULT_FIRM_SIZE_CANDIDATES)
  )

  if not firm_age_csv.exists():
    raise FileNotFoundError(f"Firm age CSV not found: {firm_age_csv}")
  if not firm_size_csv.exists():
    raise FileNotFoundError(f"Firm size CSV not found: {firm_size_csv}")

  conn = mysql.connector.connect(
    host=_getenv_required("MYSQL_HOST"),
    port=_mysql_port(),
    user=_getenv_required("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD") or "",
    database=_getenv_required("MYSQL_DB"),
    allow_local_infile=True,
    client_flags=[ClientFlag.LOCAL_FILES],
  )
  try:
    cur = conn.cursor()
    try:
      cur.execute("SHOW VARIABLES LIKE 'local_infile'")
      row = cur.fetchone()
      if not row or str(row[1]).strip().lower() not in ("on", "1"):
        raise RuntimeError("local_infile is OFF in MySQL (enable and reconnect).")

      age_bucket_col = _bucket_column(
        conn, table="bds_firm_age", candidates=["eage", "firm_age_bucket"]
      )
      size_bucket_col = _bucket_column(
        conn, table="bds_firm_size", candidates=["ifsize", "firm_size_bucket"]
      )

      if args.truncate:
        print("Truncating tables...")
        cur.execute("TRUNCATE TABLE `bds_firm_age`")
        cur.execute("TRUNCATE TABLE `bds_firm_size`")
        conn.commit()

      print("Loading bds_firm_age from:", firm_age_csv)
      sql_age = _build_load_sql(
        table="bds_firm_age",
        csv_path=firm_age_csv,
        fixed_cols=["year", "vcnaics4"],
        bucket_var="eage",
        bucket_col=age_bucket_col,
      )
      cur.execute(sql_age)
      conn.commit()
      cur.execute("SELECT COUNT(*) FROM `bds_firm_age`")
      print("bds_firm_age rows:", cur.fetchone()[0])

      print("Loading bds_firm_size from:", firm_size_csv)
      sql_size = _build_load_sql(
        table="bds_firm_size",
        csv_path=firm_size_csv,
        fixed_cols=["year", "vcnaics4"],
        bucket_var="ifsize",
        bucket_col=size_bucket_col,
      )
      cur.execute(sql_size)
      conn.commit()
      cur.execute("SELECT COUNT(*) FROM `bds_firm_size`")
      print("bds_firm_size rows:", cur.fetchone()[0])

    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass

  print("DONE")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())

