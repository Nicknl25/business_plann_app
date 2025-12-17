import os
import mysql.connector
from dotenv import load_dotenv
from datetime import date

# --------------------------------------------------
# ENV
# --------------------------------------------------

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

# --------------------------------------------------
# POLICY (LOCKED)
# --------------------------------------------------

MIN_FIRMS_USABLE = 3
MIN_QUARTERS_USABLE = 12
MIN_FIRMS_TRUSTED = 5

NAICS_LEVELS = [6, 5, 4, 3, 2]

# --------------------------------------------------
# DB
# --------------------------------------------------

def get_conn():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        port=MYSQL_PORT,
    )

# --------------------------------------------------
# BUILD INDEX
# --------------------------------------------------

def build_growth_index():
    conn = get_conn()
    cur = conn.cursor()

    print("Rebuilding industry_growth_index...")
    cur.execute("TRUNCATE TABLE industry_growth_index")

    today = date.today()

    insert_sql = """
        INSERT INTO industry_growth_index (
            naics_code,
            naics_level,
            firm_count,
            quarter_count,
            usable,
            trust,
            last_updated
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """

    for level in NAICS_LEVELS:
        print(f"Processing NAICS level {level}...")

        if level == 6:
            naics_expr = "naics_code"
        else:
            naics_expr = f"LEFT(naics_code, {level})"

        cur.execute(f"""
            SELECT
                {naics_expr} AS naics_code,
                COUNT(DISTINCT symbol) AS firm_count,
                COUNT(DISTINCT fiscalDateEnding) AS quarter_count
            FROM industry_metrics_raw
            WHERE naics_code IS NOT NULL
              AND LENGTH(naics_code) >= {level}
            GROUP BY {naics_expr}
        """)

        rows = cur.fetchall()

        for naics_code, firm_count, quarter_count in rows:

            usable = (
                firm_count >= MIN_FIRMS_USABLE
                and quarter_count >= MIN_QUARTERS_USABLE
            )

            if not usable:
                trust = "unusable"
            elif firm_count >= MIN_FIRMS_TRUSTED:
                trust = "trusted"
            else:
                trust = "fallback"

            cur.execute(
                insert_sql,
                (
                    naics_code,
                    level,
                    firm_count,
                    quarter_count,
                    usable,
                    trust,
                    today,
                ),
            )

    conn.commit()
    cur.close()
    conn.close()

    print("industry_growth_index rebuilt successfully.")

# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    build_growth_index()
