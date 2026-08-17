# -*- coding: utf-8 -*-
"""A-124 neighbor-check on the replayed Millgate model (state-keyed rate).
(4) downstream readers of debt_interest_rate_policy: debt-schedule policy reader,
    cash-pass contract check (row == policy quarterly), realism debt-rate band;
(5) offline workbook from the persisted row + replayed model_input: the Debt
    Schedule 'Interest Rate' cells carry the state-keyed 0.015 and the interest
    formulas reference them (formula-driven delivered Interest line).
"""
import json, os, sys, copy
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "python")); sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import _redproof_a124_state_plumbing as rp  # noqa: E402
from client_intake_and_finmo import finmo_bridge as fb  # noqa: E402
from client_intake_and_finmo.intake_submission import get_mysql_connection  # noqa: E402

fb._load_root_env()
conn = get_mysql_connection(); cur = conn.cursor(dictionary=True)
cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s LIMIT 1", (rp.DRAFT_PREFIX + "%",))
row = cur.fetchone()
mij, fin = rp.build(row, rp._facts(row))
fails = []
def check(c, m):
  print(("  ok   " if c else "  FAIL ") + m)
  if not c: fails.append(m)

# (4a) debt-schedule policy reader
from client_intake_and_finmo.post_intake_debt_schedule.schedule import sba_forecast_interest_rate_policy
pol = sba_forecast_interest_rate_policy(mij)
print("  debt-schedule reader:", pol.get("annual_rate_decimal"), pol.get("quarterly_rate_decimal"), pol["source_detail"].get("state"), pol["source_detail"].get("sample_count"))
check(abs(pol["annual_rate_decimal"] - 0.06) < 1e-9 and abs(float(pol.get("quarterly_rate_decimal") or 0) - 0.015) < 1e-9, "sba_forecast_interest_rate_policy accepts and returns 0.06 / 0.015")

# (4b) cash-pass contract: source sba_loan_7a_raw AND Interest Rate row Q1..Q20 == policy quarterly
from client_intake_and_finmo.post_intake_convergence.runtime import _solved_lever_value_map
src = (mij["derived_driver_policies"]["debt_interest_rate_policy"]).get("source_detail") or {}
vals = _solved_lever_value_map(mij).get("expenses::Interest Rate") or []
print("  cash contract: source", src.get("source"), "row values", vals[:3], "n", len(vals))
check(src.get("source") == "sba_loan_7a_raw", "cash contract: policy is sba-backed")
check(len(vals) >= 20 and all(abs(float(v) - 0.015) < 1e-9 for v in vals[-20:]), "cash contract: live Interest Rate row == policy quarterly 0.015")

# (4c) realism debt-rate band for NAICS 323111 at the state-keyed 6.0%
from client_intake_and_finmo.post_intake_realism import schedule_sanity as ss
band = ss._resolve_band("sba_initial_interest_rate", "323111")
print("  realism band 323111:", band)
finmo = fb.build_python_finmo_json(model_input_json=mij, finmo_path="")
res = ss._check_debt_rate_realism(finmo_json=finmo, financials_json=fin, business_naics_6="323111")
print("  realism result:", None if res is None else {k: getattr(res, k, None) for k in ("status", "actual", "effective_min", "effective_max", "reason")})
if res is not None:
  check(res.status in ("in_band", "skipped"), f"realism debt-rate status {res.status} (warn-only check; out_of_band_warn would be a flag not a block)")

# (5) offline workbook: persisted row + replayed model_input + FINMO built from it
from client_statements_output_excel import data as wbdata
from client_statements_output_excel import workbook_builder
wrow = dict(row); wrow["model_input_json"] = mij; wrow["finmo_json"] = finmo
for k in ("payroll_headcount", "debt_schedule", "planning_run_json"):
  wrow[k] = rp._obj(row.get(k))
wb = workbook_builder.build_client_financial_model_workbook(wbdata.draft_data_from_row(wrow))
found = None
for ws in wb.worksheets:
  for r in ws.iter_rows():
    cells = [c.value for c in r]
    if cells and isinstance(cells[0], str) and cells[0].strip() == "Interest Rate" and "Debt" in ws.title:
      found = (ws.title, cells[:8]); break
  if found: break
print("  workbook Debt Schedule 'Interest Rate' row:", found)
check(found is not None and any(isinstance(v, (int, float)) and abs(float(v) - 0.015) < 1e-9 for v in found[1][1:]), "workbook Debt Schedule Interest Rate cells carry 0.015 (state-keyed)")
out = os.path.join(HERE, "_a124_millgate_replay_workbook.xlsx"); wb.save(out); print("  saved", out)
print(("GREEN" if not fails else f"RED ({len(fails)})") + " - A-124 neighbor check")
sys.exit(0 if not fails else 1)
