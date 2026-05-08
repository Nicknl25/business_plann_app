"""High-level analysis of sec_edgar_facts: how powerful is what we pulled."""
import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)

print("=" * 70)
print("SEC EDGAR FACTS - POWER ANALYSIS")
print("=" * 70)

print("\n--- 1) Total scale ---")
cur.execute(
    "SELECT COUNT(*) AS rows_, COUNT(DISTINCT cik) AS ciks, "
    "       COUNT(DISTINCT ticker) AS tickers, "
    "       COUNT(DISTINCT naics_code) AS naics_codes_6digit, "
    "       COUNT(DISTINCT concept_name) AS concepts, "
    "       COUNT(DISTINCT fiscal_period) AS quarters_covered, "
    "       COUNT(DISTINCT accession_number) AS distinct_filings "
    "FROM sec_edgar_facts"
)
r = cur.fetchone()
for k, v in r.items():
    print(f"  {k:30} {v:>10,}")

print("\n--- 2) NAICS coverage breakdown ---")
cur.execute(
    "SELECT COUNT(DISTINCT LEFT(naics_code,2)) AS naics_2, "
    "       COUNT(DISTINCT LEFT(naics_code,3)) AS naics_3, "
    "       COUNT(DISTINCT LEFT(naics_code,4)) AS naics_4, "
    "       COUNT(DISTINCT LEFT(naics_code,5)) AS naics_5, "
    "       COUNT(DISTINCT naics_code) AS naics_6 "
    "FROM sec_edgar_facts WHERE naics_code IS NOT NULL"
)
r = cur.fetchone()
for k, v in r.items():
    print(f"  {k:15} {v:>5}")

print("\n--- 3) NAICS-2 sector coverage (CIKs per 2-digit sector) ---")
cur.execute(
    """
    SELECT LEFT(naics_code,2) AS naics_2,
           COUNT(DISTINCT cik) AS ciks,
           COUNT(*) AS facts
    FROM sec_edgar_facts
    WHERE naics_code IS NOT NULL
    GROUP BY LEFT(naics_code,2)
    ORDER BY ciks DESC
    """
)
sector_titles = {
    "11": "Agriculture, Forestry, Fishing, Hunting",
    "21": "Mining, Quarrying, Oil & Gas",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing",
    "32": "Manufacturing",
    "33": "Manufacturing",
    "42": "Wholesale Trade",
    "44": "Retail Trade",
    "45": "Retail Trade",
    "48": "Transportation & Warehousing",
    "49": "Transportation & Warehousing",
    "51": "Information",
    "52": "Finance & Insurance",
    "53": "Real Estate, Rental, Leasing",
    "54": "Professional/Scientific/Technical Services",
    "55": "Management of Companies",
    "56": "Administrative/Support/Waste Mgmt",
    "61": "Educational Services",
    "62": "Health Care & Social Assistance",
    "71": "Arts, Entertainment, Recreation",
    "72": "Accommodation & Food Services",
    "81": "Other Services (except Public Admin)",
    "92": "Public Administration",
}
for r in cur.fetchall():
    title = sector_titles.get(r['naics_2'], '?')
    print(f"  NAICS-{r['naics_2']:>2} {title:42} CIKs={r['ciks']:>4}  facts={r['facts']:>7,}")

print("\n--- 4) Financial-statement coverage (CIKs reporting key concepts) ---")
fs_groups = {
    "P&L_revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "P&L_cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "P&L_grossProfit": ["GrossProfit"],
    "P&L_sga": ["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"],
    "P&L_marketing": ["MarketingExpense", "MarketingAndAdvertisingExpense", "SellingAndMarketingExpense", "AdvertisingExpense"],
    "P&L_rnd": ["ResearchAndDevelopmentExpense"],
    "P&L_depreciation": ["DepreciationAndAmortization", "Depreciation"],
    "P&L_interest": ["InterestExpense"],
    "P&L_tax": ["IncomeTaxExpenseBenefit"],
    "P&L_pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    "P&L_operatingIncome": ["OperatingIncomeLoss"],
    "P&L_netIncome": ["NetIncomeLoss"],
    "P&L_lease/rent": ["OperatingLeaseExpense", "OperatingLeasesRentExpenseNet", "LeaseAndRentalExpense"],
    "BS_assets": ["Assets"],
    "BS_currentAssets": ["AssetsCurrent"],
    "BS_liabilities": ["Liabilities"],
    "BS_equity": ["StockholdersEquity"],
    "BS_AR": ["AccountsReceivableNetCurrent"],
    "BS_AP": ["AccountsPayableCurrent"],
    "BS_inventory": ["InventoryNet"],
    "BS_PPE": ["PropertyPlantAndEquipmentNet"],
    "BS_LTdebt": ["LongTermDebtNoncurrent"],
    "BS_deferredRev": ["DeferredRevenue", "DeferredRevenueCurrent", "DeferredRevenueNoncurrent",
                       "ContractWithCustomerLiabilityCurrent", "ContractWithCustomerLiabilityNoncurrent",
                       "ContractWithCustomerLiability"],
    "BS_prepaid": ["PrepaidExpenseCurrent", "PrepaidExpenseAndOtherAssetsCurrent", "PrepaidExpenseAndOtherAssets"],
    "BS_RoUasset": ["OperatingLeaseRightOfUseAsset"],
    "BS_leaseLiability": ["OperatingLeaseLiability"],
    "CF_capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "CF_dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "CF_SBC": ["ShareBasedCompensation"],
    "CF_operatingCash": ["NetCashProvidedByUsedInOperatingActivities"],
}
for label, concepts in fs_groups.items():
    placeholders = ",".join(["%s"] * len(concepts))
    cur.execute(
        f"SELECT COUNT(DISTINCT cik) AS ciks, COUNT(DISTINCT naics_code) AS naics, "
        f"       COUNT(*) AS facts "
        f"FROM sec_edgar_facts WHERE concept_name IN ({placeholders})",
        tuple(concepts),
    )
    r = cur.fetchone()
    print(f"  {label:24} CIKs={r['ciks']:>5}  distinct NAICS-6={r['naics']:>4}  facts={r['facts']:>7,}")

print("\n--- 5) Period coverage ---")
cur.execute(
    "SELECT fiscal_period, COUNT(DISTINCT cik) AS ciks, COUNT(*) AS facts "
    "FROM sec_edgar_facts GROUP BY fiscal_period ORDER BY fiscal_period DESC"
)
for r in cur.fetchall():
    print(f"  {r['fiscal_period']:15} CIKs={r['ciks']:>4}  facts={r['facts']:>7,}")

print("\n--- 6) Top 15 NAICS-6 with most CIKs (deepest coverage) ---")
cur.execute(
    """
    SELECT naics_code, COUNT(DISTINCT cik) AS ciks, COUNT(*) AS facts
    FROM sec_edgar_facts WHERE naics_code IS NOT NULL
    GROUP BY naics_code
    ORDER BY ciks DESC LIMIT 15
    """
)
for r in cur.fetchall():
    print(f"  NAICS {r['naics_code']}  CIKs={r['ciks']:>3}  facts={r['facts']:>5,}")

print("\n--- 7) Top 10 most-covered concepts ---")
cur.execute(
    "SELECT concept_name, COUNT(DISTINCT cik) AS ciks, COUNT(*) AS facts "
    "FROM sec_edgar_facts GROUP BY concept_name ORDER BY ciks DESC LIMIT 10"
)
for r in cur.fetchall():
    print(f"  {r['concept_name']:55} CIKs={r['ciks']:>4}  facts={r['facts']:>6,}")

conn.close()
