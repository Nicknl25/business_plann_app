"""mini's OWN CW-043 before/after harness (independent of VS's).

usage: python mini_cw043_harness.py <repo_root> <out_dir> [--tamper-paste] [--no-recalc]

BEFORE' : stored Halbrook payloads (frozen lease) through <repo_root>'s sheet code.
AFTER   : principal row taken from the REAL bridge (build_python_model_input_json +
          apply_derived_driver_policies_to_model_input on the committed fixture),
          spliced into the stored model_input, finmo rebuilt through the REAL engine,
          exported through the production exporter. Both recalculated in Excel.
"""
import copy, json, os, sys, time
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv

ROOT = sys.argv[1]; OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
TAMPER = "--tamper-paste" in sys.argv
RECALC = "--no-recalc" not in sys.argv
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "python"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(r"C:\dev\business_plann_app\.env")

from client_intake_and_finmo import finmo_bridge as fb
from client_intake_and_finmo.post_intake_sequence import post_intake_sequence_step_scope
from client_statements_output_excel.export_client_workbook import export_workbook_for_row
import client_statements_output_excel.schedule_sheets as ss
print("code under test:", fb.__file__, "|", ss.__file__)

def _engine(mi):
  with post_intake_sequence_step_scope(step_key='amalgamated_in_cascade_evaluate',
      phase='post_intake_target_seeking', executor_function='amalgamated_in_cascade_evaluate'):
    return fb.build_python_finmo_json(model_input_json=mi)

c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'),
                            password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE 'ecd0e148%'"); row = dict(cur.fetchone())
cur.execute("SELECT diagnostics_json FROM post_intake_run_diagnostics WHERE draft_id LIKE 'ecd0e148%'")
diag = json.loads(cur.fetchone()["diagnostics_json"]); cur.close(); c.close()
mi_stored = json.loads(row["model_input_json"]); finmo_stored = json.loads(row["finmo_json"])

# sanity: engine determinism
fr = _engine(copy.deepcopy(mi_stored))
same = json.dumps(fr["quarter_rows"], sort_keys=True, default=str) == json.dumps(finmo_stored["quarter_rows"], sort_keys=True, default=str)
print("engine determinism (unpatched rebuild == stored finmo):", same)

# AFTER: principal row from the REAL bridge on the committed fixture
fx = json.load(open(r"C:\dev\business_plann_app\tests\fixtures\cw043_halbrook_inputs.json", encoding="utf-8"))
fin = fx["financials_json"]
mij = fb.apply_derived_driver_policies_to_model_input(fb.build_python_model_input_json(
    business_facts=fx["business_facts"], ops_json=fx["operating_model_json"], people_json=fx["people_json"],
    financials_json=fin, financials_year1_json=fx["financials_year1_json"], marketing_model_json=fx["marketing_model_json"],
    forecast_starting_ppe=float(fin.get("initial_assets") or 0.0), maintenance_rate=0.05))
bridge_row = next(r for r in mij["sections"]["schedules"]["rows"] if r["label"] == "Less: Principal Repayments")
print("bridge-authored principal row:", bridge_row["values"])
print("bridge seed:", mij["sections"]["schedules"].get("lease_opening_balance_seed"))
mi_after = copy.deepcopy(mi_stored)
for r_ in mi_after["sections"]["schedules"]["rows"]:
  if r_["label"] == "Less: Principal Repayments":
    print("stored principal row was:", r_["values"])
    r_["values"] = list(bridge_row["values"])
finmo_after = _engine(mi_after)
json.dump(finmo_after, open(OUT / "finmo_after.json", "w"), default=str)
json.dump(finmo_stored, open(OUT / "finmo_stored.json", "w"), default=str)
json.dump(mi_after, open(OUT / "mi_after.json", "w"), default=str)

def _export(tag, mi, fm):
  r2 = dict(row); r2["model_input_json"] = json.dumps(mi, ensure_ascii=False, default=str)
  r2["finmo_json"] = json.dumps(fm, ensure_ascii=False, default=str); r2["business_name"] = f"MINI {tag}"
  p = export_workbook_for_row(r2, output_dir=OUT, run_diagnostics=diag); print("built", tag, p.name); return p

if TAMPER:
  try:
    _export("TAMPER", mi_after, finmo_after); print("TAMPER: build SUCCEEDED (guard did NOT fire)")
  except AssertionError as e:
    print("TAMPER: build KILLED by guard ->", e)
  sys.exit(0)

pb = _export("BEFOREPRIME", mi_stored, finmo_stored)
pa = _export("AFTER", mi_after, finmo_after)
if RECALC:
  import win32com.client as win32
  x = win32.gencache.EnsureDispatch("Excel.Application"); x.Visible = False; x.DisplayAlerts = False
  for p in (pb, pa):
    w = x.Workbooks.Open(str(p))
    for _ in range(20):
      try: w.Sheets(1).Name; break
      except Exception: time.sleep(1.5)
    x.CalculateFullRebuild(); w.Save(); w.Close(False)
  x.Quit(); print("recalculated both in Excel")
print("BEFOREPRIME=", pb); print("AFTER=", pa)
