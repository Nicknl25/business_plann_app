"""mini CW-033 audit: peek the real Thornfield transcript turns + drafts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
from intake_submission import get_mysql_connection  # type: ignore

SOURCE_DRAFT = "d9b17850350545e9911fa09b3e333429"
SUMAC = "2ecc759c"

conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT messages_json, active_focus, financials_json, operating_model_json "
    "FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
src = cur.fetchone()
msgs = json.loads(src["messages_json"] or "[]")
print(f"total messages: {len(msgs)}")
for i in list(range(7, 13)) + list(range(73, 80)) + list(range(87, 92)):
    m = msgs[i]
    print(f"\n[{i}] {m.get('role')}: {str(m.get('content'))[:420]}")

fin = json.loads(src["financials_json"] or "{}")
print("\n--- financials keys:", sorted(fin.keys())[:40])
print("current_capex:", fin.get("current_capex"),
      "initial_assets:", fin.get("initial_assets"))

ops = json.loads(src["operating_model_json"] or "{}")
for lob in ops.get("lob_models") or []:
    for p in lob.get("products") or []:
        print("row:", p.get("product_name"),
              "| price", p.get("unit_price"),
              "| wk_cap", p.get("units_per_week_capacity"),
              "| cogs%", p.get("cogs_percent_of_line_revenue"),
              "| group", p.get("cogs_cost_structure_group"),
              "| basis", p.get("cogs_cost_structure_group_basis"))

cur.execute(
    "SELECT draft_id, business_name, active_focus, status FROM intake_consult_drafts "
    "WHERE draft_id LIKE %s", (SUMAC + "%",))
for r in cur.fetchall():
    print("\nSUMAC candidate:", r)
    cur2 = conn.cursor(dictionary=True)
    cur2.execute("SELECT operating_model_json, financials_json FROM intake_consult_drafts "
                 "WHERE draft_id=%s", (r["draft_id"],))
    row = cur2.fetchone()
    o2 = json.loads(row["operating_model_json"] or "{}")
    for lob in o2.get("lob_models") or []:
        for p in lob.get("products") or []:
            print("  row:", p.get("product_name"), "| price", p.get("unit_price"),
                  "| wk_cap", p.get("units_per_week_capacity"),
                  "| period_cap", p.get("units_per_period_capacity"))
cur.close()
conn.close()
