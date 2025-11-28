import os
import requests
import mysql.connector
from dotenv import load_dotenv

# -------------------------------------------------------------------
# FORCE LOAD ROOT .env ONLY
# -------------------------------------------------------------------
ROOT_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
load_dotenv(ROOT_ENV_PATH)

# -------------------------------------------------------------------
# ENV VARS
# -------------------------------------------------------------------
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")

# -------------------------------------------------------------------
# CENSUS API URL (all NAICS → we filter in Python)
# -------------------------------------------------------------------
URL = (
    "https://api.census.gov/data/2022/cbp"
    "?get=GEO_ID,NAME,NAICS2017,NAICS2017_LABEL,ESTAB,PAYANN,PAYQTR1,EMP"
    "&for=state:*"
    "&LFO=001"
    f"&key={CENSUS_API_KEY}"
)

print("Pulling CBP 2022 data from Census API...")

response = requests.get(URL)
response.raise_for_status()
data = response.json()

headers = data[0]
rows = data[1:]  # actual data

print(f"Total rows returned: {len(rows)}")

# -------------------------------------------------------------------
# CONNECT TO MYSQL
# -------------------------------------------------------------------
conn = mysql.connector.connect(
    host=MYSQL_HOST,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DB
)

cursor = conn.cursor()

# -------------------------------------------------------------------
# INSERT TEMPLATE
# -------------------------------------------------------------------
insert_sql = """
INSERT INTO cbp_2022_raw
(geo_id, state_fips, state_name, naics, naics_label, estab, pay_ann, pay_q1, emp, lfo)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

# -------------------------------------------------------------------
# UTILITY: convert integers
# -------------------------------------------------------------------
def to_int(val):
    return int(val) if val not in ("", None) else None


# -------------------------------------------------------------------
# PROCESS ROWS — FILTER BEFORE INSERT
# -------------------------------------------------------------------
clean_count = 0

for row in rows:
    (
    geo_id,
    state_name,
    naics,
    naics_label,
    estab,
    pay_ann,
    pay_q1,
    emp,
    lfo,
    state_fips
) = row


    # ---------------------------------------------------------------
    # FILTER: Keep only pure 3-digit numeric NAICS
    # ---------------------------------------------------------------
    if not (naics.isdigit() and len(naics) == 3):
        continue  # skip all other NAICS levels

    # convert to numbers
    estab = to_int(estab)
    pay_ann = to_int(pay_ann)
    pay_q1 = to_int(pay_q1)
    emp = to_int(emp)

    lfo = "001"  # from API filter

    cursor.execute(insert_sql, (
        geo_id,
        state_fips,
        state_name,
        naics,
        naics_label,
        estab,
        pay_ann,
        pay_q1,
        emp,
        lfo
    ))

    clean_count += 1

conn.commit()
cursor.close()
conn.close()

print(f"Inserted {clean_count} clean 3-digit NAICS records into cbp_2022_raw.")
