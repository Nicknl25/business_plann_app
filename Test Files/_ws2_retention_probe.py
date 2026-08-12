"""THE RETENTION PROBE (#131 exercised-clean): clone the clean
Thistledown draft, raise a price through the LIVE handler, answer the
retention question, and verify the answer APPLIES (utilization and
revenue scale, frame cleared) - the class that was
acknowledged-then-ignored at Wren Hollow, now consumed at any surface."""
import io
import json
import os
import sys
import time
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "C:/dev/business_plann_app/python")
import requests
from dotenv import load_dotenv

load_dotenv("C:/dev/business_plann_app/.env")
import mysql.connector

BASE = "http://127.0.0.1:5050"
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    autocommit=True,
)
cur = conn.cursor(dictionary=True)

SRC = "be84629a"
new_draft = "probe" + uuid.uuid4().hex[:27]
new_client = "rprobe" + uuid.uuid4().hex[:10]

cur.execute("SHOW COLUMNS FROM intake_consult_drafts")
cols = [r["Field"] for r in cur.fetchall()]
col_list = ", ".join(f"`{c}`" for c in cols)
sel_list = ", ".join(
    f"%s" if c == "draft_id" else (f"%s" if c == "client_id" else f"`{c}`")
    for c in cols
)
cur.execute(
    f"INSERT INTO intake_consult_drafts ({col_list}) "
    f"SELECT {sel_list} FROM intake_consult_drafts WHERE draft_id LIKE %s",
    (new_draft, new_client, SRC + "%"),
)
print("cloned ->", new_draft)


def turn(msg):
    r = requests.post(f"{BASE}/api/intake-consult", json={
        "draft_id": new_draft, "client_id": new_client, "message": msg,
    }, timeout=600)
    body = r.json() if r.status_code == 200 else {}
    return str(body.get("assistant_message") or body.get("message") or "")[:400]


def state():
    cur.execute("SELECT financials_json, operating_model_json FROM "
                "intake_consult_drafts WHERE draft_id=%s", (new_draft,))
    row = cur.fetchone()
    f = json.loads(row["financials_json"] or "{}")
    o = json.loads(row["operating_model_json"] or "{}")
    st = f.get("_coherence") or {}
    utils = {}
    for lm in o.get("lob_models") or []:
        for p in lm.get("products") or []:
            utils[str(p.get("product_name"))[:18]] = (
                p.get("unit_price"), p.get("utilization_rate"))
    return f, st, utils


f0, st0, u0 = state()
print("BEFORE: rev:", f0.get("current_revenue"), "rows:", u0,
      "retention_pending:", bool(st0.get("retention_pending")))

print()
print("TURN 1 (price raise):")
reply1 = turn("Raise the average bike sale price to $1,400 - the market "
              "supports it.")
print(" ", reply1[:350])
f1, st1, u1 = state()
print("  rows:", u1, "| retention_pending:", bool(st1.get("retention_pending")),
      "| rev:", f1.get("current_revenue"))

print()
print("TURN 2 (retention answer):")
reply2 = turn("I'd keep about 85% of my bike buyers at that price.")
print(" ", reply2[:350])
f2, st2, u2 = state()
print("  rows:", u2, "| retention_pending:", bool(st2.get("retention_pending")),
      "| rev:", f2.get("current_revenue"))

ok_price = abs(float(u1.get("Average bike sale", (0, 0))[0] or 0) - 1400.0) < 0.5
frame_after_t1 = bool(st1.get("retention_pending"))
frame_cleared = not bool(st2.get("retention_pending"))
util_before = float(u1.get("Average bike sale", (0, 1))[1] or 0)
util_after = float(u2.get("Average bike sale", (0, 1))[1] or 0)
util_scaled = util_before > 0 and abs(util_after - round(util_before * 0.85, 4)) < 0.01

print()
print("VERDICT:")
print("  price landed 1400:", ok_price)
print("  retention frame stamped after the price turn:", frame_after_t1)
print("  frame cleared after the answer:", frame_cleared)
print(f"  utilization scaled by 0.85 ({util_before} -> {util_after}):", util_scaled)
