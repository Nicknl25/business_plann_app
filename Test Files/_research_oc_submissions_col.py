# RESEARCH ONLY: does intake_submissions carry owner_compensation? who reads it?
import mysql.connector

conn = mysql.connector.connect(
    host="localhost", user="root", password="Lovers251979!",
    database="biz_plan_revert", autocommit=True,
)
cur = conn.cursor()
cur.execute("SHOW COLUMNS FROM intake_submissions LIKE '%owner%'")
print("owner columns:", cur.fetchall())
cur.execute("SHOW COLUMNS FROM intake_submissions")
allcols = [r[0] for r in cur.fetchall()]
print("has owner_compensation:", "owner_compensation" in allcols)
if "owner_compensation" in allcols:
    cur.execute(
        "SELECT id, business_name, owner_compensation FROM intake_submissions "
        "ORDER BY id DESC LIMIT 6"
    )
    for r in cur.fetchall():
        print(r)
