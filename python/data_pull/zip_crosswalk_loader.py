import csv
import mysql.connector
import os
from pathlib import Path
from dotenv import load_dotenv

# --------------------------------------------------------
# LOAD ROOT .env FILE (WORKS FROM ANY SUBFOLDER)
# --------------------------------------------------------

# Hard-code to the repo root folder name so we never pick up frontend/.env
def get_project_root() -> Path:
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
    # Support both MYSQL_DATABASE and MYSQL_DB
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
# PATH TO ZIP CROSSWALK FILE
# --------------------------------------------------------

csv_path = r"C:\Users\ignat\Documents\Business Plan Generator\References\zip_crosswalk.txt"

# --------------------------------------------------------
# READ & PARSE FILE
# --------------------------------------------------------

rows = []

with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
    reader = csv.DictReader(f)

    for row in reader:
        rows.append(
            (
                row["ZCTA5"],
                row["STATE"],
                row["COUNTY"],
                row["GEOID"],
                row["POPPT"],
                row["HUPT"],
                row["AREAPT"],
                row["AREALANDPT"],
                row["ZPOP"],
                row["ZHU"],
                row["ZAREA"],
                row["ZAREALAND"],
                row["COPOP"],
                row["COHU"],
                row["COAREA"],
                row["COAREALAND"],
                row["ZPOPPCT"],
                row["ZHUPCT"],
                row["ZAREAPCT"],
                row["ZAREALANDPCT"],
                row["COPOPPCT"],
                row["COHUPCT"],
                row["COAREAPCT"],
                row["COAREALANDPCT"],
            )
        )

print(f"Loaded {len(rows)} rows from file")

# --------------------------------------------------------
# INSERT INTO MYSQL
# --------------------------------------------------------

insert_sql = """
INSERT INTO zip_county_crosswalk (
    zcta, state_fips, county_fips, geoid,
    poppt, hupt, areapt, arealandpt,
    zpop, zhu, zarea, zarealand,
    copop, cohu, coarea, coarealand,
    zpop_pct, zhu_pct, zarea_pct, zarealand_pct,
    copop_pct, cohu_pct, coarea_pct, coarealand_pct
) VALUES (
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s
)
"""

cursor.executemany(insert_sql, rows)
conn.commit()

print("Crosswalk table loaded successfully!")

cursor.close()
conn.close()
