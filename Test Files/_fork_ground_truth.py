"""Stuck-fork ground truth (Nick-ruled fix, step 0): for 4de1d55c and
6d36e540, determine WHICH side of the flat-vs-product fork carries the
client's truth before healing. Evidence: rescale provenance, the
transcript's capacity/utilization statements, timestamps. Read-only."""
import json
import os
import re
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)
for prefix in ("4de1d55c", "6d36e540"):
    cur.execute(
        "SELECT draft_id, business_name, status, updated_at, "
        "operating_model_json, financials_year1_json, messages_json "
        "FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
    r = cur.fetchone()
    ops = json.loads(r["operating_model_json"] or "{}")
    y1 = json.loads(r["financials_year1_json"] or "{}")
    msgs = json.loads(r["messages_json"] or "[]")
    print("=" * 72)
    print(f"{r['business_name']}  {r['draft_id'][:8]}  status={r['status']} "
          f"updated={r['updated_at']}  msgs={len(msgs)}")
    p = (ops.get("lob_models") or [{}])[0].get("products", [{}])[0]
    flat = {k: ops.get(k) for k in
            ("unit_price", "units_per_week_capacity",
             "units_per_period_capacity", "utilization_rate")}
    prod = {k: p.get(k) for k in
            ("unit_price", "units_per_week_capacity",
             "units_per_period_capacity", "utilization_rate")}
    print(f"  flat:    {flat}")
    print(f"  product: {prod}")
    prov = y1.get("_rescale_provenance")
    print(f"  rescale_provenance: {prov}")
    if prov and prov.get("factor"):
        f = float(prov["factor"])
        for k in ("units_per_week_capacity", "units_per_period_capacity",
                  "utilization_rate"):
            fv, pv = flat.get(k), prod.get(k)
            if fv and pv:
                print(f"    {k}: product/flat = {float(pv)/float(fv):.4f} "
                      f"(rescale factor {f:.4f})")
    # transcript statements of the forked numbers
    pat = re.compile(r"\b(70|55|88|0\.88|76)\b")
    hits = []
    for i, m in enumerate(msgs):
        t = str(m.get("content") or "")
        if pat.search(t) and any(w in t.lower() for w in
                                 ("capacity", "utilization", "per week",
                                  "appointments", "sessions", "clients",
                                  "treatments", "week")):
            hits.append((i, m.get("role"), t[:220].replace("\n", " ")))
    for i, role, t in hits[-6:]:
        print(f"  msg[{i}] {role}: {t}")
cur.close()
conn.close()
