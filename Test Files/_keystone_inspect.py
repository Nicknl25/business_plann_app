"""Keystone confirmation - step 0: inspect the REAL F&F (50658fff) and
Sparrow (4aa25e24) drafts as they stand. Read-only."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
for like in ("50658fff%", "4aa25e24%"):
    cur.execute(
        "SELECT draft_id, client_id, business_name, status, active_focus, "
        "planning_run_status, financials_json, operating_model_json, "
        "people_json, JSON_LENGTH(messages_json) AS msg_count "
        "FROM intake_consult_drafts WHERE draft_id LIKE %s", (like,))
    r = cur.fetchone()
    if not r:
        print(f"NO DRAFT {like}")
        continue
    fin = json.loads(r["financials_json"] or "{}")
    ops = json.loads(r["operating_model_json"] or "{}")
    ppl = json.loads(r["people_json"] or "{}")
    st = fin.get("_coherence") or {}
    print("=" * 70)
    print(f"{r['business_name']}  draft={r['draft_id']}")
    print(f"  client_id={r['client_id']} status={r['status']} focus={r['active_focus']} "
          f"run={r['planning_run_status']} msgs={r['msg_count']}")
    print(f"  current_revenue={fin.get('current_revenue')}")
    print(f"  payroll trio: baseline={fin.get('baseline_payroll_year1')} "
          f"current={fin.get('current_payroll')} total={fin.get('payroll_total_year1')} "
          f"adj={fin.get('payroll_adjustment')}")
    print(f"  cogs: pct={fin.get('cogs_percent_of_revenue')} cur={fin.get('current_cogs')} "
          f"basis={fin.get('cogs_basis')!r}")
    print(f"  opex_abs={fin.get('other_opex_absolute')} mkt_total={fin.get('marketing_total_year1')} "
          f"rent_mo={fin.get('monthly_rent_expense')}")
    print(f"  coherence: status={st.get('status')!r} digest={bool(st.get('digest_hash'))} "
          f"band={bool(st.get('margin_band_judgment'))} "
          f"class={((st.get('margin_band_judgment') or {}).get('labor_intensity_class'))!r} "
          f"walls={st.get('walls')}")
    lines = []
    for lob in ops.get("lob_models") or []:
        for p in lob.get("products") or []:
            lines.append((lob.get("lob_name"), p.get("product_name"), p.get("unit_price"),
                          p.get("units_per_period_capacity"), p.get("utilization_rate"),
                          p.get("operating_periods_per_year")))
    print(f"  ops lines: {lines}")
    roles = [(p.get("role_title"), p.get("annual_wage")) for p in (ppl.get("people") or [])]
    print(f"  people: {roles} rest={ppl.get('rest_of_team_payroll_year1')}")
cur.close()
conn.close()
