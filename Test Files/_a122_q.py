import os, sys
from dotenv import load_dotenv; load_dotenv()
import mysql.connector
c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True)
cur = c.cursor(dictionary=True); cur.execute(sys.argv[1])
for r in cur.fetchall(): print(r)
