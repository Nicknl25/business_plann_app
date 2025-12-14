import os
import json
import mysql.connector
from dotenv import load_dotenv
from openai import OpenAI

# ============================================================
# ENV
# ============================================================

load_dotenv()

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD"),
    "database": os.getenv("MYSQL_DB"),
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ============================================================
# DB HELPERS
# ============================================================

def get_conn():
    return mysql.connector.connect(**MYSQL_CONFIG)

def fetch_naics_master(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT naics_code, naics_title
        FROM naics_master
        WHERE LENGTH(naics_code) = 6
    """)
    rows = cur.fetchall()
    cur.close()
    return rows

def fetch_unmapped_titles(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT naics_title
        FROM SOI_corporate_tax_returns
        WHERE naics_title IS NOT NULL
          AND naics_title <> ''
          AND naics_6_digit IS NULL
    """)
    titles = [r[0] for r in cur.fetchall()]
    cur.close()
    return titles

# ============================================================
# GPT NAICS RESOLUTION
# ============================================================

def resolve_naics(industry, naics_master):
    candidates = "\n".join(
        f"{r['naics_code']}: {r['naics_title']}"
        for r in naics_master
    )

    prompt = f"""
You are an expert in NAICS classification.

Choose the SINGLE best 6-digit NAICS code that matches
the industry description below.

Industry:
{industry}

Candidate NAICS codes:
{candidates}

Return ONLY JSON:
{{"naics_code":"######"}}
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    return result["naics_code"].zfill(6)

# ============================================================
# MAIN
# ============================================================

def main():
    conn = get_conn()

    naics_master = fetch_naics_master(conn)
    titles = fetch_unmapped_titles(conn)

    print(f"Found {len(titles)} NAICS titles to map.")

    cur = conn.cursor()

    for i, title in enumerate(titles, 1):
        print(f"[{i}/{len(titles)}] Mapping: {title}")

        try:
            code6 = resolve_naics(title, naics_master)

            cur.execute("""
                UPDATE SOI_corporate_tax_returns
                SET
                    naics_2_digit = %s,
                    naics_3_digit = %s,
                    naics_4_digit = %s,
                    naics_5_digit = %s,
                    naics_6_digit = %s
                WHERE naics_title = %s
            """, (
                code6[:2],
                code6[:3],
                code6[:4],
                code6[:5],
                code6[:6],
                title
            ))

            conn.commit()

        except Exception as e:
            print(f"❌ Failed mapping '{title}': {e}")

    cur.close()
    conn.close()

    print("✅ NAICS enrichment complete.")

if __name__ == "__main__":
    main()
