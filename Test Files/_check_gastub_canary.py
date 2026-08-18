# -*- coding: utf-8 -*-
"""Read-only: verify the G&A stub on a stored draft (canary / e2e) equals
stated other_opex / stated current_revenue and FINMO Q0 G&A = stated
quarterly dollars. Usage: python _check_gastub_canary.py <draft_id_prefix>"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "python"))
from client_intake_and_finmo import finmo_bridge as fb  # noqa: E402
from client_intake_and_finmo.intake_submission import get_mysql_connection  # noqa: E402

fb._load_root_env()
prefix = sys.argv[1]
conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT draft_id, business_name, financials_json, model_input_json, finmo_json, planning_run_json "
            "FROM intake_consult_drafts WHERE draft_id LIKE %s ORDER BY updated_at DESC LIMIT 1", (prefix + "%",))
r = cur.fetchone()
assert r, prefix
fin = json.loads(r["financials_json"] or "{}")
mi = json.loads(r["model_input_json"] or "{}")
fm = json.loads(r["finmo_json"] or "{}")
pr = json.loads(r["planning_run_json"] or "{}")
print("draft", r["draft_id"], r["business_name"])
print("run status:", pr.get("status"))
stated = fb._safe_float(fin.get("current_revenue")) or 0.0
opex = fb._safe_float(fin.get("other_opex_absolute")) or fb._safe_float(fin.get("other_operating_expense")) or 0.0
print("stated current_revenue", stated, "other_opex_absolute", fin.get("other_opex_absolute"),
      "other_operating_expense", fin.get("other_operating_expense"))
ga = [row for row in (mi.get("sections", {}).get("expenses") or []) if row.get("label") == "General & Administrative"][0]
vals = ga["values"]
print("G&A values[0:3]", vals[:3], "len", len(vals))
exp = round(opex / stated, 6) if stated else None
print("expected stub", exp, "-> stub", vals[0], "MATCH" if exp is not None and abs(vals[0] - exp) < 1e-9 else "MISMATCH")
q0 = (fm.get("quarter_rows") or [{}])[0]
print("finmo Q0 revenue", q0.get("revenue"), "g_and_a", q0.get("g_and_a"), "stated quarterly", opex / 4.0 if opex else None)
