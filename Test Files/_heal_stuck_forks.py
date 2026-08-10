"""Nick-ruled: heal the two stuck forked drafts (4de1d55c, 6d36e540)
by running the PRODUCTION run-entry recalc against them (persists only
what changed; the new flat-mirror heal rides the canonical pass).
Ground truth (transcripts): the product row carries the resolved
values; flat is a stale mirror."""
import json
import os
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

from api_handlers.intake_consult import _run_entry_recalc  # noqa: E402

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)
for prefix in ("4de1d55c", "6d36e540"):
    cur.execute("SELECT draft_id FROM intake_consult_drafts WHERE draft_id LIKE %s",
                (prefix + "%",))
    did = cur.fetchone()["draft_id"]
    _run_entry_recalc(conn=conn, draft_id=did)
    cur.execute("SELECT operating_model_json FROM intake_consult_drafts "
                "WHERE draft_id=%s", (did,))
    ops = json.loads(cur.fetchone()["operating_model_json"] or "{}")
    p = (ops.get("lob_models") or [{}])[0].get("products", [{}])[0]
    flat = {k: ops.get(k) for k in ("unit_price", "units_per_week_capacity",
                                    "units_per_period_capacity", "utilization_rate")}
    prod = {k: p.get(k) for k in ("unit_price", "units_per_week_capacity",
                                  "units_per_period_capacity", "utilization_rate")}
    agree = all(
        flat.get(k) is None or p.get(k) is None
        or abs(float(flat[k]) - float(prod[k])) < 1e-6
        for k in flat)
    print(f"{prefix}: flat={flat}")
    print(f"{'':10}prod={prod}  -> {'HEALED (mirror == product)' if agree else 'STILL FORKED'}")
cur.close()
conn.close()
