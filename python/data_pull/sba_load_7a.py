import os
import csv
import mysql.connector
from dotenv import load_dotenv

# ----------------------------------------------------------
# FORCE LOAD ROOT .env ONLY
# ----------------------------------------------------------
ROOT_ENV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '.env')
)
load_dotenv(ROOT_ENV_PATH)

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE")

if not MYSQL_DATABASE:
    raise ValueError("ERROR: MYSQL_DB or MYSQL_DATABASE missing from .env")

# ----------------------------------------------------------
# CSV PATH (change only if file moves)
# ----------------------------------------------------------
CSV_PATH = r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Business Plan Generator Sources\References\foia-7a-fy2020-present-asof-250930.csv"

print("\n=== SBA 7a Loader Starting ===\n")
print("Loading file:", CSV_PATH)

# ----------------------------------------------------------
# CONNECT TO MYSQL
# ----------------------------------------------------------
conn = mysql.connector.connect(
    host=MYSQL_HOST,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DATABASE
)
cursor = conn.cursor()

# ----------------------------------------------------------
# SQL INSERT TEMPLATE
# ----------------------------------------------------------
insert_sql = """
INSERT INTO sba_loan_7a_raw (
    AsOfDate, Program, BorrName, BorrStreet, BorrCity, BorrState, BorrZip,
    LocationID, BankName, BankFDICNumber, BankNCUANumber, BankStreet, BankCity,
    BankState, BankZip, GrossApproval, SBAGuaranteedApproval, ApprovalDate,
    ApprovalFY, FirstDisbursementDate, ProcessingMethod, Subprogram,
    InitialInterestRate, FixedOrVariableInterestRate, TermInMonths, NAICSCode,
    NAICSDescription, FranchiseCode, FranchiseName, ProjectCounty, ProjectState,
    SBADistrictOffice, CongressionalDistrict, BusinessType, BusinessAge,
    LoanStatus, PaidInFullDate, ChargeoffDate, GrossChargeoffAmount,
    RevolverStatus, JobsSupported, CollateralInd, SoldSecondMarketInd
) VALUES (
    %s,%s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,
    %s,%s,%s,%s,
    %s,%s,%s,%s,
    %s,%s,%s,%s,%s,
    %s,%s,%s,%s,
    %s,%s,%s,
    %s,%s,%s,%s,%s
)
"""

# ----------------------------------------------------------
# UTILITY: CLEAN NUMERIC FIELDS
# ----------------------------------------------------------
def to_int(val):
    try:
        return int(val.replace(",", "")) if val not in ("", None) else None
    except:
        return None

def to_float(val):
    try:
        return float(val) if val not in ("", None) else None
    except:
        return None

# ----------------------------------------------------------
# PROCESS CSV
# ----------------------------------------------------------
batch = []
batch_size = 500
row_count = 0

with open(CSV_PATH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)

    for row in reader:

        batch.append((
            row.get("AsOfDate"),
            row.get("Program"),
            row.get("BorrName"),
            row.get("BorrStreet"),
            row.get("BorrCity"),
            row.get("BorrState"),
            row.get("BorrZip"),

            row.get("LocationID"),
            row.get("BankName"),
            row.get("BankFDICNumber"),
            row.get("BankNCUANumber"),
            row.get("BankStreet"),
            row.get("BankCity"),
            row.get("BankState"),
            row.get("BankZip"),

            to_int(row.get("GrossApproval")),
            to_int(row.get("SBAGuaranteedApproval")),

            row.get("ApprovalDate"),
            to_int(row.get("ApprovalFY")),
            row.get("FirstDisbursementDate"),

            row.get("ProcessingMethod"),
            row.get("Subprogram"),

            to_float(row.get("InitialInterestRate")),
            row.get("FixedorVariableInterestRate"),
            to_int(row.get("TerminMonths")),  # CSV header is misspelled ("TerminMonths")
            row.get("NAICSCode"),

            row.get("NAICSDescription"),
            row.get("FranchiseCode"),
            row.get("FranchiseName"),
            row.get("ProjectCounty"),
            row.get("ProjectState"),

            row.get("SBADistrictOffice"),
            row.get("CongressionalDistrict"),
            row.get("BusinessType"),
            row.get("BusinessAge"),

            row.get("LoanStatus"),
            row.get("PaidinFullDate"),
            row.get("ChargeoffDate"),
            to_int(row.get("GrossChargeoffAmount")),

            row.get("RevolverStatus"),
            to_int(row.get("JobsSupported")),
            row.get("CollateralInd"),
            row.get("SoldSecondMarketInd")
        ))

        row_count += 1

        # Insert every 500 rows
        if len(batch) >= batch_size:
            cursor.executemany(insert_sql, batch)
            conn.commit()
            batch = []
            print(f"Inserted {row_count} rows so far...")

# Insert any remaining rows
if batch:
    cursor.executemany(insert_sql, batch)
    conn.commit()

cursor.close()
conn.close()

print(f"\n=== DONE ===")
print(f"Total rows inserted: {row_count}\n")
