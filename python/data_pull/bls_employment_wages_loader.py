import csv
import mysql.connector
import os
from pathlib import Path
from dotenv import load_dotenv

# --------------------------------------------------------
# LOAD ROOT .env FILE (WORKS FROM ANY SUBFOLDER)
# --------------------------------------------------------

def get_project_root() -> Path:
    """Find the project root folder named 'Business Plan Generator'."""
    for parent in Path(__file__).resolve().parents:
        if parent.name == "Business Plan Generator":
            return parent
    raise FileNotFoundError("Could not locate project root 'Business Plan Generator'")


project_root = get_project_root()
env_file = project_root / ".env"

if not env_file.exists():
    raise FileNotFoundError(f"Expected root .env at {env_file}")

# Load environment variables explicitly from the project root .env
if not load_dotenv(dotenv_path=env_file, override=True):
    raise RuntimeError(f"Could not load environment variables from {env_file}")

# --------------------------------------------------------
# EXTRACT MYSQL VARIABLES FROM ROOT ENV
# --------------------------------------------------------

def env_value(*keys: str) -> str | None:
    """Return the first non-empty env value from the provided keys."""
    for key in keys:
        val = os.getenv(key)
        if val:
            return val
    return None


env_vars = {
    "MYSQL_HOST": env_value("MYSQL_HOST", "DB_HOST"),
    "MYSQL_USER": env_value("MYSQL_USER", "DB_USER"),
    "MYSQL_PASSWORD": env_value("MYSQL_PASSWORD", "DB_PASSWORD"),
    # Support both MYSQL_DATABASE and MYSQL_DB (as shown in the screenshot)
    "MYSQL_DATABASE": env_value("MYSQL_DATABASE", "MYSQL_DB", "DB_NAME"),
}

missing_vars = [key for key, value in env_vars.items() if not value]
if missing_vars:
    raise EnvironmentError(
        f"Missing MySQL environment variables {', '.join(missing_vars)} in {env_file}"
    )

MYSQL_HOST = env_vars["MYSQL_HOST"]
MYSQL_USER = env_vars["MYSQL_USER"]
MYSQL_PASSWORD = env_vars["MYSQL_PASSWORD"]
MYSQL_DATABASE = env_vars["MYSQL_DATABASE"]

# --------------------------------------------------------
# HELPERS FOR DATA CLEANUP
# --------------------------------------------------------

def to_number(val):
    """
    Convert a string to int/float; return None for blanks or suppressed values
    like **, *, #, or ~.
    """
    if val is None:
        return None
    v = str(val).strip()
    if v in ("", "*", "**", "#", "~"):
        return None
    v = v.replace(",", "")
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        return None

def to_bool_int(val):
    """Convert 'TRUE'/'FALSE'/1/0 to integers; return None for blanks/unknown."""
    if val is None:
        return None
    v = str(val).strip().upper()
    if v in ("TRUE", "T", "1"):
        return 1
    if v in ("FALSE", "F", "0", ""):
        return 0
    return None

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

print("Connected to MySQL")

# --------------------------------------------------------
# PATH TO THE OEWS STATE WAGE & EMPLOYMENT FILE
# --------------------------------------------------------

csv_path = project_root / "References" / "BLS Employment and Wages_loaded.csv"

# --------------------------------------------------------
# READ & PARSE CSV FILE
# --------------------------------------------------------

rows = []

with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
    reader = csv.DictReader(f)

    for row in reader:
        rows.append(
            (
                row.get("AREA"),
                row.get("AREA_TITLE"),
                row.get("AREA_TYPE"),
                row.get("PRIM_STATE"),
                row.get("NAICS"),
                row.get("NAICS_TITLE"),
                row.get("I_GROUP"),
                row.get("OWN_CODE"),
                row.get("OCC_CODE"),
                row.get("OCC_TITLE"),
                row.get("O_GROUP"),
                to_number(row.get("TOT_EMP")),
                to_number(row.get("EMP_PRSE")),
                to_number(row.get("JOBS_1000")),
                to_number(row.get("LOC_QUOTIENT")),
                to_number(row.get("PCT_TOTAL")),
                to_number(row.get("PCT_RPT")),
                to_number(row.get("H_MEAN")),
                to_number(row.get("A_MEAN")),
                to_number(row.get("MEAN_PRSE")),
                to_number(row.get("H_PCT10")),
                to_number(row.get("H_PCT25")),
                to_number(row.get("H_MEDIAN")),
                to_number(row.get("H_PCT75")),
                to_number(row.get("H_PCT90")),
                to_number(row.get("A_PCT10")),
                to_number(row.get("A_PCT25")),
                to_number(row.get("A_MEDIAN")),
                to_number(row.get("A_PCT75")),
                to_number(row.get("A_PCT90")),
                to_bool_int(row.get("ANNUAL")),
                to_bool_int(row.get("HOURLY")),
            )
        )

print(f"Loaded {len(rows)} rows from file")

# --------------------------------------------------------
# SQL INSERT STATEMENT
# --------------------------------------------------------

insert_sql = """
INSERT INTO oews_state_wages (
    area, area_title, area_type, prim_state,
    naics, naics_title, i_group, own_code,
    occ_code, occ_title, o_group,
    tot_emp, emp_prse, jobs_1000, loc_quotient, pct_total, pct_rpt,
    h_mean, a_mean, mean_prse,
    h_pct10, h_pct25, h_median, h_pct75, h_pct90,
    a_pct10, a_pct25, a_median, a_pct75, a_pct90,
    annual, hourly
) VALUES (
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s
)
"""

# --------------------------------------------------------
# BULK INSERT INTO MYSQL
# --------------------------------------------------------

CHUNK_SIZE = 20_000

def chunked(seq, size):
    """Yield successive chunks from seq."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


for i, chunk in enumerate(chunked(rows, CHUNK_SIZE), start=1):
    cursor.executemany(insert_sql, chunk)
    conn.commit()
    print(f"Committed batch {i} ({len(chunk)} rows)")

print("OEWS State Wage & Employment table loaded successfully!")

cursor.close()
conn.close()
