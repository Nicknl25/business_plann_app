import os
import requests
import pymysql
from dotenv import load_dotenv

# ----------------------------------------------------
# HARD-CODED ABSOLUTE PATH TO ROOT .env
# ----------------------------------------------------
ROOT_ENV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".env")
)
load_dotenv(ROOT_ENV_PATH)

# Now .env variables are ONLY loaded from the ROOT
# ----------------------------------------------------

CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")

DB_HOST = os.getenv("MYSQL_HOST")
DB_USER = os.getenv("MYSQL_USER")
DB_PASS = os.getenv("MYSQL_PASSWORD")
DB_NAME = os.getenv("MYSQL_DB")

SSL = {"ssl": {}}

# -------------------------------
# ACS URLs
# -------------------------------

ACS_PART1_URL = (
    "https://api.census.gov/data/2022/acs/acs5"
    "?get=NAME,B01001_001E,B01002_001E,B19013_001E,"
    "B19001_001E,B19001_002E,B19001_003E,B19001_004E,"
    "B19001_005E,B19001_006E,B19001_007E,B19001_008E,"
    "B19001_009E,B19001_010E,B19001_011E,B19001_012E,"
    "B19001_013E,B19001_014E,B19001_015E,B19001_016E,"
    "B19001_017E,B15003_017E,B15003_022E,B15003_023E,"
    "B15003_025E,B11001_001E,B11001_002E,B11001_007E,"
    "B25001_001E,B25064_001E,B25077_001E,B03002_012E,"
    "B02001_002E,B02001_003E,B02001_005E,"
    "B23025_003E,B23025_004E,B23025_005E"
    "&for=zip%20code%20tabulation%20area:*"
)

ACS_PART2_URL = (
    "https://api.census.gov/data/2022/acs/acs5"
    "?get=B01001_003E,B01001_027E,B01001_004E,B01001_028E,"
    "B01001_005E,B01001_029E,B01001_006E,B01001_030E,"
    "B01001_007E,B01001_031E,B01001_008E,B01001_032E,"
    "B01001_009E,B01001_033E,B01001_010E,B01001_034E,"
    "B01001_011E,B01001_035E,B01001_012E,B01001_036E,"
    "B01001_013E,B01001_037E,B01001_014E,B01001_038E,"
    "B01001_015E,B01001_039E,B01001_016E,B01001_040E,"
    "B01001_017E,B01001_041E,B01001_018E,B01001_042E,"
    "B01001_019E,B01001_043E,B01001_020E,B01001_044E,"
    "B01001_021E,B01001_045E,B01001_022E,B01001_046E,"
    "B01001_023E,B01001_047E,B01001_024E,B01001_048E,"
    "B01001_025E,B01001_049E"
    "&for=zip%20code%20tabulation%20area:*"
)

# Append KEY
ACS_PART1_URL += f"&key={CENSUS_API_KEY}"
ACS_PART2_URL += f"&key={CENSUS_API_KEY}"


# -------------------------------
# Fetch ACS data
# -------------------------------
def fetch_acs(url):
    print(f"Fetching: {url[:120]}...")
    r = requests.get(url)
    r.raise_for_status()
    data = r.json()
    return data[0], data[1:]


# -------------------------------
# UPSERT Helper
# -------------------------------
def upsert_rows(cursor, table, header, rows):
    # Convert ACS geography label → SQL column
    columns = ["zcta" if c == "zip code tabulation area" else c for c in header]

    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(columns)
    update_list = ", ".join([f"{c}=VALUES({c})" for c in columns if c != "zcta"])

    sql = f"""
        INSERT INTO {table} ({col_list})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {update_list}
    """

    for row in rows:
        clean_row = [None if v in ("", None) else v for v in row]
        cursor.execute(sql, clean_row)


# -------------------------------
# MAIN RUNNER
# -------------------------------
def run():
    conn = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        ssl=SSL
    )
    cursor = conn.cursor()

    # PART 1
    header1, rows1 = fetch_acs(ACS_PART1_URL)
    upsert_rows(cursor, "acs_zip_2022_part1", header1, rows1)
    conn.commit()
    print(f"Part 1 loaded: {len(rows1)} rows.")

    # PART 2
    header2, rows2 = fetch_acs(ACS_PART2_URL)
    upsert_rows(cursor, "acs_zip_2022_part2", header2, rows2)
    conn.commit()
    print(f"Part 2 loaded: {len(rows2)} rows.")

    cursor.close()
    conn.close()

    print("ACS ZIP 2022 FULL LOAD COMPLETE.")


if __name__ == "__main__":
    run()
