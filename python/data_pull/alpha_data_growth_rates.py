import os
import mysql.connector
from dotenv import load_dotenv
import statistics

# --------------------------------------------------------------
# LOAD ROOT ENV
# --------------------------------------------------------------

ROOT_ENV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".env"
)
load_dotenv(ROOT_ENV)

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))

START_DATE = os.getenv("START_DATE")
END_DATE = os.getenv("END_DATE")


# --------------------------------------------------------------
# DB CONNECTION
# --------------------------------------------------------------

def get_conn():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        port=MYSQL_PORT
    )


# --------------------------------------------------------------
# TABLE CREATION
# --------------------------------------------------------------

def create_tables(cursor):

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS industry_metrics_raw (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20),
        naics_code VARCHAR(10),
        market_cap BIGINT,
        cap_category VARCHAR(10),
        fiscalDateEnding DATE,
        total_revenue DECIMAL(22,4),
        revenue_growth_q DECIMAL(18,6),

        gross_margin_q DECIMAL(18,6),
        operating_margin_q DECIMAL(18,6),
        ebit_margin_q DECIMAL(18,6),
        ebitda_margin_q DECIMAL(18,6),
        net_margin_q DECIMAL(18,6),

        sga_percent DECIMAL(18,6),
        rnd_percent DECIMAL(18,6),
        cogs_percent DECIMAL(18,6),

        dso DECIMAL(18,6),
        dpo DECIMAL(18,6),
        inventory_days DECIMAL(18,6),
        ccc DECIMAL(18,6),

        current_ratio DECIMAL(18,6),
        quick_ratio DECIMAL(18,6),
        debt_to_equity DECIMAL(18,6),
        debt_to_assets DECIMAL(18,6),
        debt_to_ebitda DECIMAL(18,6),
        interest_coverage DECIMAL(18,6),

        capex_percent_revenue DECIMAL(18,6),
        depreciation_percent_revenue DECIMAL(18,6),

        roa DECIMAL(18,6),
        roe DECIMAL(18,6),

        UNIQUE KEY u_symbol_period (symbol, fiscalDateEnding)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS industry_growth_table (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        naics_code VARCHAR(10),
        fiscalDateEnding DATE,
        quarter TINYINT,

        industry_gross_margin_q DECIMAL(18,6),
        industry_operating_margin_q DECIMAL(18,6),
        industry_ebit_margin_q DECIMAL(18,6),
        industry_ebitda_margin_q DECIMAL(18,6),
        industry_net_margin_q DECIMAL(18,6),
        industry_revenue_growth_q DECIMAL(18,6),

        industry_sga_percent DECIMAL(18,6),
        industry_rnd_percent DECIMAL(18,6),
        industry_cogs_percent DECIMAL(18,6),

        industry_dso DECIMAL(18,6),
        industry_dpo DECIMAL(18,6),
        industry_inventory_days DECIMAL(18,6),
        industry_ccc DECIMAL(18,6),

        industry_capex_percent_revenue DECIMAL(18,6),
        industry_depreciation_percent_revenue DECIMAL(18,6),

        industry_roa DECIMAL(18,6),
        industry_roe DECIMAL(18,6),

        UNIQUE KEY u_industry_period (naics_code, fiscalDateEnding)
    );
    """)

    # Add missing columns if tables pre-existed without new fields
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'industry_metrics_raw';
    """)
    cols_raw = {row[0] for row in cursor.fetchall()}
    if "total_revenue" not in cols_raw:
        cursor.execute("ALTER TABLE industry_metrics_raw ADD COLUMN total_revenue DECIMAL(22,4)")
    if "revenue_growth_q" not in cols_raw:
        cursor.execute("ALTER TABLE industry_metrics_raw ADD COLUMN revenue_growth_q DECIMAL(18,6)")

    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'industry_growth_table';
    """)
    cols_growth = {row[0] for row in cursor.fetchall()}
    if "industry_revenue_growth_q" not in cols_growth:
        cursor.execute("ALTER TABLE industry_growth_table ADD COLUMN industry_revenue_growth_q DECIMAL(18,6)")
    if "quarter" not in cols_growth:
        cursor.execute("ALTER TABLE industry_growth_table ADD COLUMN quarter TINYINT AFTER fiscalDateEnding")
# --------------------------------------------------------------
# UTILITIES
# --------------------------------------------------------------

def to_float(x):
    try:
        return float(x)
    except:
        return None

def div(a, b):
    a = to_float(a)
    b = to_float(b)
    return (a / b) if (a is not None and b not in (None, 0)) else None


# --------------------------------------------------------------
# GET NEW QUARTERS TO PROCESS
# --------------------------------------------------------------

def get_new_quarters(cursor):
    cursor.execute(f"""
        SELECT DISTINCT fiscalDateEnding
        FROM alpha_data
        WHERE fiscalDateEnding BETWEEN '{START_DATE}' AND '{END_DATE}'
        AND fiscalDateEnding NOT IN (
            SELECT fiscalDateEnding FROM industry_metrics_raw
        )
        ORDER BY fiscalDateEnding;
    """)
    return [row[0] for row in cursor.fetchall()]


# --------------------------------------------------------------
# MAIN PYTHON RATIO ENGINE — CLEAN, FINAL VERSION
# --------------------------------------------------------------

def compute_ratios_for_quarter(cursor, period):

    cursor.execute(f"""
        SELECT
            ad.symbol,
            nm.naics_code,
            tm.market_cap,

            ad.totalRevenue AS total_revenue,
            ad.grossProfit,
            ad.operatingIncome,
            ad.ebit,
            ad.ebitda,
            ad.netIncome_x,

            ad.sellingGeneralAndAdministrative,
            ad.researchAndDevelopment,
            ad.costOfRevenue,

            ad.currentNetReceivables,
            ad.currentAccountsPayable,
            ad.inventory,

            ad.totalCurrentAssets,
            ad.totalCurrentLiabilities,

            ad.cashAndCashEquivalentsAtCarryingValue,
            ad.shortTermInvestments,

            ad.totalLiabilities,
            ad.totalAssets,
            ad.totalShareholderEquity,
            ad.longTermDebt,
            ad.interestExpense,

            ad.capitalExpenditures,
            ad.depreciation,
            ad.fiscalDateEnding

        FROM alpha_data ad
        LEFT JOIN alpha_match_naics_industry nm
            ON BINARY ad.symbol = BINARY nm.symbol
        LEFT JOIN ticker_metadata tm
            ON BINARY ad.symbol = BINARY tm.symbol

        WHERE ad.fiscalDateEnding = '{period}';
    """)

    rows = cursor.fetchall()
    if not rows:
        return []

    # fetch all prior rows for revenue + date lookup
    cursor.execute("""
        SELECT symbol, total_revenue, fiscalDateEnding
        FROM industry_metrics_raw
        ORDER BY fiscalDateEnding DESC
    """)
    prev_rows = cursor.fetchall()

    prev_rev_map = {}
    prev_date_map = {}

    for sym, total_rev_prev, fdate_prev in prev_rows:
        rev_prev_float = to_float(total_rev_prev)
        if sym not in prev_rev_map:
            prev_rev_map[sym] = rev_prev_float
            prev_date_map[sym] = fdate_prev

    results = []

    for r in rows:
        (symbol, naics, market_cap,
         rev, gp, op_inc, ebit, ebitda, net,
         sga, rnd, cogs,
         ar, ap, inv,
         ca, cl,
         cash, sti,
         tl, ta, tse, ltd, interest,
         capex, dep, fdate) = r

        # float conversion
        rev      = to_float(rev)
        gp       = to_float(gp)
        op_inc   = to_float(op_inc)
        ebit     = to_float(ebit)
        ebitda   = to_float(ebitda)
        net      = to_float(net)
        sga      = to_float(sga)
        rnd      = to_float(rnd)
        cogs     = to_float(cogs)
        ar       = to_float(ar)
        ap       = to_float(ap)
        inv      = to_float(inv)
        ca       = to_float(ca)
        cl       = to_float(cl)
        cash     = to_float(cash)
        sti      = to_float(sti)
        tl       = to_float(tl)
        ta       = to_float(ta)
        tse      = to_float(tse)
        ltd      = to_float(ltd)
        interest = to_float(interest)
        capex    = to_float(capex)
        dep      = to_float(dep)

        # real period length
        prev_date = prev_date_map.get(symbol)
        if prev_date:
            period_days = (fdate - prev_date).days
        else:
            period_days = None

        # revenue growth
        prev_rev = prev_rev_map.get(symbol)
        revenue_growth = div((rev - prev_rev) if (rev is not None and prev_rev is not None) else None, prev_rev)

        # margins
        gross_margin = div(gp, rev)
        operating_margin = div(op_inc, rev)
        ebit_margin = div(ebit, rev)
        ebitda_margin = div(ebitda, rev)
        net_margin = div(net, rev)

        # expenses
        sga_pct = div(sga, rev)
        rnd_pct = div(rnd, rev)
        cogs_pct = div(cogs, rev)

        # REAL DSO / DPO / InvDays
        dso_raw = div(ar, rev)
        dso = dso_raw * period_days if (period_days and dso_raw is not None) else None

        dpo_raw = div(ap, cogs)
        inv_raw = div(inv, cogs)
        dpo = dpo_raw * period_days if (period_days and dpo_raw is not None) else None
        inv_days = inv_raw * period_days if (period_days and inv_raw is not None) else None

        ccc = dso + inv_days - dpo if (dso is not None and dpo is not None and inv_days is not None) else None

        # liquidity + leverage
        current_ratio = div(ca, cl)
        quick_ratio = div((cash or 0) + (sti or 0) + (ar or 0), cl)
        debt_to_equity = div(tl, tse)
        debt_to_assets = div(tl, ta)
        debt_to_ebitda = div(ltd, ebitda)
        interest_coverage = div(ebit, interest)

        # capex / depr
        capex_pct = div(capex, rev)
        dep_pct = div(dep, rev)

        # returns
        roa = div(net, ta)
        roe = div(net, tse)

        # cap category
        if market_cap is None:
            cap_cat = None
        elif market_cap < 2_000_000_000:
            cap_cat = "small"
        elif market_cap < 10_000_000_000:
            cap_cat = "mid"
        else:
            cap_cat = "large"

        # append clean row
        results.append([
            symbol, naics, market_cap, cap_cat, fdate,
            rev, revenue_growth,

            gross_margin, operating_margin, ebit_margin,
            ebitda_margin, net_margin,
            sga_pct, rnd_pct, cogs_pct,

            dso, dpo, inv_days, ccc,

            current_ratio, quick_ratio, debt_to_equity, debt_to_assets,
            debt_to_ebitda, interest_coverage,

            capex_pct, dep_pct,

            roa, roe
        ])

    return results
# --------------------------------------------------------------
# INSERT RAW
# --------------------------------------------------------------

def insert_raw(cursor, rows):
    if not rows:
        return

    sql = """
        INSERT IGNORE INTO industry_metrics_raw (
            symbol, naics_code, market_cap, cap_category, fiscalDateEnding,
            total_revenue, revenue_growth_q,
            gross_margin_q, operating_margin_q, ebit_margin_q,
            ebitda_margin_q, net_margin_q, sga_percent, rnd_percent, cogs_percent,
            dso, dpo, inventory_days, ccc,
            current_ratio, quick_ratio, debt_to_equity, debt_to_assets,
            debt_to_ebitda, interest_coverage,
            capex_percent_revenue, depreciation_percent_revenue,
            roa, roe
        )
        VALUES (%s, %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s)
    """
    cursor.executemany(sql, rows)


# --------------------------------------------------------------
# MEDIANS BY INDUSTRY
# --------------------------------------------------------------

def compute_and_insert_industry_medians(cursor, period):

    cursor.execute(f"""
        SELECT
            naics_code,
            revenue_growth_q,
            gross_margin_q,
            operating_margin_q,
            ebit_margin_q,
            ebitda_margin_q,
            net_margin_q,
            sga_percent,
            rnd_percent,
            cogs_percent,
            dso,
            dpo,
            inventory_days,
            ccc,
            capex_percent_revenue,
            depreciation_percent_revenue,
            roa,
            roe
        FROM industry_metrics_raw
        WHERE fiscalDateEnding = '{period}';
    """)

    rows = cursor.fetchall()
    if not rows:
        return

    grouped = {}
    for r in rows:
        naics = r[0]
        grouped.setdefault(naics, []).append(r[1:])

    for naics, metrics_list in grouped.items():

        cols = list(zip(*metrics_list))

        medians = [
            statistics.median([v for v in col if v is not None])
            if any(v is not None for v in col)
            else None
            for col in cols
        ]

        qtr = ((period.month - 1) // 3) + 1

        cursor.execute("""
            INSERT IGNORE INTO industry_growth_table (
                naics_code, fiscalDateEnding, quarter,
                industry_revenue_growth_q,
                industry_gross_margin_q,
                industry_operating_margin_q,
                industry_ebit_margin_q,
                industry_ebitda_margin_q,
                industry_net_margin_q,
                industry_sga_percent,
                industry_rnd_percent,
                industry_cogs_percent,
                industry_dso,
                industry_dpo,
                industry_inventory_days,
                industry_ccc,
                industry_capex_percent_revenue,
                industry_depreciation_percent_revenue,
                industry_roa,
                industry_roe
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [naics, period, qtr] + medians)


# --------------------------------------------------------------
# MAIN PIPELINE
# --------------------------------------------------------------

def main():

    conn = get_conn()
    cursor = conn.cursor()

    print("Creating tables...")
    create_tables(cursor)
    conn.commit()

    print("Checking for new quarters...")
    periods = get_new_quarters(cursor)

    if not periods:
        print("No new quarters.")
        return

    for period in periods:
        print(f"Processing {period}...")

        rows = compute_ratios_for_quarter(cursor, period)
        insert_raw(cursor, rows)
        conn.commit()

        compute_and_insert_industry_medians(cursor, period)
        conn.commit()

        print(f"Finished {period}.")

    cursor.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
