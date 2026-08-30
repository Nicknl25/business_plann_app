"""CBP 2022 at COUNTY level -> cbp_2022_raw_county (Nick's directive, 2026-08-30).

Same shape as cbp_2022_raw.py, two deliberate differences:

  1. The table carries county_fips as well - a county pull returns state and
     county as separate columns - so it joins to zip_county_crosswalk on
     state_fips + county_fips, which is how the writing phase already
     resolves geography.
  2. Rows are parsed BY HEADER NAME, not by position. The state loader's
     positional unpack silently depends on the API's column order; at county
     level the response carries one more column and a positional unpack would
     load garbage without erroring.

County-level CBP suppresses small cells for confidentiality, so coverage is
expected to be thinner than the state table - measuring how much thinner is
the point of this load.

Standalone one-shot loader: creates the table if absent, refuses to double-load
into a non-empty table (drop it first to reload). Not imported by the app.
"""
import os
import sys

import mysql.connector
import requests
from dotenv import load_dotenv

# -------------------------------------------------------------------
# FORCE LOAD ROOT .env ONLY
# -------------------------------------------------------------------
ROOT_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
load_dotenv(ROOT_ENV_PATH)

CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")

# -------------------------------------------------------------------
# CENSUS API URL - the county endpoint, confirmed working
# -------------------------------------------------------------------
URL = (
    "https://api.census.gov/data/2022/cbp"
    "?get=GEO_ID,NAME,NAICS2017,NAICS2017_LABEL,ESTAB,PAYANN,PAYQTR1,EMP"
    "&for=county:*"
    "&LFO=001"
    + (f"&key={CENSUS_API_KEY}" if CENSUS_API_KEY else "")
)

TABLE = "cbp_2022_raw_county"

CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  geo_id VARCHAR(32) NOT NULL,
  state_name VARCHAR(128) NULL,
  naics VARCHAR(8) NOT NULL,
  naics_label VARCHAR(255) NULL,
  estab INT NULL,
  pay_ann BIGINT NULL,
  pay_q1 BIGINT NULL,
  emp INT NULL,
  lfo VARCHAR(4) NOT NULL DEFAULT '001',
  state_fips VARCHAR(2) NOT NULL,
  county_fips VARCHAR(3) NOT NULL,
  KEY ix_state_county_naics (state_fips, county_fips, naics),
  KEY ix_naics (naics)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

INSERT_SQL = f"""
INSERT INTO {TABLE}
(geo_id, state_fips, county_fips, state_name, naics, naics_label, estab, pay_ann, pay_q1, emp, lfo)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

BATCH = 5000


def to_int(val):
    return int(val) if val not in ("", None) else None


def main() -> int:
    print("Pulling CBP 2022 COUNTY data from Census API...")
    response = requests.get(URL, timeout=900)
    response.raise_for_status()
    data = response.json()

    headers = data[0]
    rows = data[1:]
    print(f"Total rows returned: {len(rows)}")

    col = {name: i for i, name in enumerate(headers)}
    for required in ("GEO_ID", "NAME", "NAICS2017", "NAICS2017_LABEL", "ESTAB",
                     "PAYANN", "PAYQTR1", "EMP", "state", "county"):
        if required not in col:
            raise SystemExit(f"API response lacks column {required!r}; headers={headers}")

    conn = mysql.connector.connect(
        host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD, database=MYSQL_DB,
    )
    cursor = conn.cursor()
    cursor.execute(CREATE_SQL)
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE}")
    existing = cursor.fetchone()[0]
    if existing:
        raise SystemExit(f"{TABLE} already holds {existing} rows - drop it first to reload.")

    batch = []
    inserted = 0
    for row in rows:
        name = str(row[col["NAME"]] or "")
        # "Kent County, Michigan" -> the state part; the county itself is keyed
        # by county_fips (display names come back through the crosswalk).
        state_name = name.rsplit(",", 1)[-1].strip() if "," in name else name
        batch.append((
            row[col["GEO_ID"]],
            str(row[col["state"]]).zfill(2),
            str(row[col["county"]]).zfill(3),
            state_name,
            row[col["NAICS2017"]],
            row[col["NAICS2017_LABEL"]],
            to_int(row[col["ESTAB"]]),
            to_int(row[col["PAYANN"]]),
            to_int(row[col["PAYQTR1"]]),
            to_int(row[col["EMP"]]),
            "001",
        ))
        if len(batch) >= BATCH:
            cursor.executemany(INSERT_SQL, batch)
            inserted += len(batch)
            batch = []
            if inserted % 100000 == 0:
                print(f"  ... {inserted} inserted")
    if batch:
        cursor.executemany(INSERT_SQL, batch)
        inserted += len(batch)

    conn.commit()
    cursor.close()
    conn.close()
    print(f"Inserted {inserted} records into {TABLE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
