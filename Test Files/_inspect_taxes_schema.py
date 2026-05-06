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
cur.execute("DESCRIBE SOI_corporate_tax_returns")
print("--- columns ---")
for r in cur.fetchall():
    print(r["Field"], r["Type"])
cur.execute("SELECT * FROM SOI_corporate_tax_returns LIMIT 3")
print("\n--- sample rows ---")
for r in cur.fetchall():
    print(r)
print("\n--- ValueMart NAICS check ---")
cur.execute(
    "SELECT business_name, financials_json, operating_model_json, people_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    ("b6134325d26842228cad0430aa9649b3",),
)
r = cur.fetchone()
import json
fj = json.loads(r["financials_json"]) if r and r["financials_json"] else {}
oj = json.loads(r["operating_model_json"]) if r and r["operating_model_json"] else {}
pj = json.loads(r["people_json"]) if r and r["people_json"] else {}
print(f"Business: {r['business_name']}")
print(f"financials taxes_percent: {fj.get('taxes_percent')!r}")
print(f"financials naics_code: {fj.get('naics_code')!r}")
print(f"ops naics_code: {oj.get('naics_code')!r}")
print(f"ops business_naics_6: {oj.get('business_naics_6')!r}")
print(f"people business_naics_6: {pj.get('business_naics_6')!r}")
# search for SOI lookup
naics = (
    str(oj.get("business_naics_6") or "").strip()
    or str(pj.get("business_naics_6") or "").strip()
    or str(oj.get("naics_code") or "").strip()
    or ""
)
naics = "".join(c for c in naics if c.isdigit())[:6]
print(f"\nResolved naics_6: {naics!r}")
if naics:
    cur.execute(
        "SELECT naics_title, income_subject_to_tax, total_income_tax_after_credits "
        "FROM SOI_corporate_tax_returns WHERE naics_6_digit=%s",
        (naics,),
    )
    r2 = cur.fetchone()
    if r2 and r2["income_subject_to_tax"] and float(r2["income_subject_to_tax"]) > 0:
        rate = float(r2["total_income_tax_after_credits"]) / float(r2["income_subject_to_tax"])
        print(f"SOI title: {r2['naics_title']}; effective tax rate: {rate:.4f}")
    else:
        # try less specific
        for col in ("naics_5_digit", "naics_4_digit", "naics_3_digit", "naics_2_digit"):
            prefix_len = int(col.split("_")[1]) if False else int(col[6])  # parse
            try:
                pl = int(col.replace("naics_", "").replace("_digit", ""))
            except Exception:
                pl = 0
            if not pl:
                continue
            cur.execute(
                f"SELECT naics_title, income_subject_to_tax, total_income_tax_after_credits "
                f"FROM SOI_corporate_tax_returns WHERE {col}=%s LIMIT 1",
                (naics[:pl],),
            )
            r2 = cur.fetchone()
            if r2 and r2.get("income_subject_to_tax") and float(r2["income_subject_to_tax"]) > 0:
                rate = float(r2["total_income_tax_after_credits"]) / float(r2["income_subject_to_tax"])
                print(f"SOI {col} match: {r2['naics_title']}; effective tax rate: {rate:.4f}")
                break
conn.close()
