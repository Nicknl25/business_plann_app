"""CW-018 PASS-1 mechanical cleanup - targeted E2E per item, production shapes.

#1b marked-price conversion: the CW-014 shape - "$1,200 a year" on a
    12-period product where the router fabricated the /10 arithmetic.
#2  positioning splice: the live Vanguard idiom + ops shape (two
    products, distinct prices/cadences).
#3  promise wording above the judged ceiling: the live Vanguard band
    numbers (11.5% vs 6-11%).
#4  reference code: generator + legacy display strip on a real stored id.
"""
import copy
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")
sys.path.insert(0, "C:/dev/business_plann_app/python/client_intake_and_finmo")

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


# ============ #1b marked-price conversion ============
from api_handlers.intake_consult import (  # noqa: E402
    _guard_underivable_ops_lever_writes,
    _marked_price_conversion,
)

def _ops(price, periods):
    return {"lob_models": [{"lob_name": "Services", "products": [{
        "product_name": "Maintenance plan", "unit_price": price,
        "units_per_period_capacity": 40, "operating_periods_per_year": periods,
        "utilization_rate": 0.8,
    }]}]}

# CW-014 shape: client marks ANNUAL, product is monthly; router wrote /10.
MSG_ANNUAL = "The maintenance plan runs $1,200 a year per client, not what you have."
before = _ops(90.0, 12)
after = copy.deepcopy(before)
after["lob_models"][0]["products"][0]["unit_price"] = 120.0  # router's /10 fabrication
out = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(before), ops_after=after,
    user_message=MSG_ANNUAL, last_assistant="")
check("#1b '/10' fabrication converts to stated x 1/12 = 100 (not drop)",
      out["lob_models"][0]["products"][0]["unit_price"] == 100.0)

# Weekly-marked on monthly product: "$300 a week" -> 300*52/12 = 1300.
after2 = copy.deepcopy(before)
after2["lob_models"][0]["products"][0]["unit_price"] = 3571.0  # fabricated
out2 = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(before), ops_after=after2,
    user_message="We charge about $300 a week for that plan.", last_assistant="")
check("#1b weekly-marked converts 300 x 52/12 = 1300",
      out2["lob_models"][0]["products"][0]["unit_price"] == 1300.0)

# NEG: no cadence marker -> old drop/revert behavior stands.
after3 = copy.deepcopy(before)
after3["lob_models"][0]["products"][0]["unit_price"] = 777.0
out3 = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(before), ops_after=after3,
    user_message="Take another look at those assumptions please.", last_assistant="")
check("#1b NEG no marker -> fabricated write still reverts",
      out3["lob_models"][0]["products"][0]["unit_price"] == 90.0)

# NEG: derivable raw write unaffected by conversion machinery.
after4 = copy.deepcopy(before)
after4["lob_models"][0]["products"][0]["unit_price"] = 1200.0
out4 = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(before), ops_after=after4,
    user_message="Call it $1,200 flat per period.", last_assistant="")
check("#1b NEG derivable raw write survives untouched",
      out4["lob_models"][0]["products"][0]["unit_price"] == 1200.0)

# NEG: unknown product cadence -> no conversion (revert), never a guess.
check("#1b NEG unknown periods -> helper returns None",
      _marked_price_conversion("it is $1,200 a year", None) is None)

# Gate branch (declared class now real).
from client_intake_and_finmo.basis_gate import gate_numeric  # noqa: E402
gv = gate_numeric(field="ops.unit_price", value=1200.0, stated_basis="annual",
                  user_message="it is $1,200 a year",
                  context={"product_periods_per_year": 12})
check("#1b gate driver_price convert verdict: 1200 annual -> 100/period",
      gv.get("verdict") == "convert" and gv.get("value") == 100.0)
gv2 = gate_numeric(field="ops.unit_price", value=100.0, stated_basis="monthly",
                   user_message="it is $100 a month",
                   context={"product_periods_per_year": 12})
check("#1b gate NEG matching cadence -> pass (no conversion)",
      gv2.get("verdict") == "pass")

# ============ #2 positioning splice (live Vanguard shape) ============
from client_intake_and_finmo.fact_templates import render_fact_template  # noqa: E402

cn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST") or "localhost", user=os.getenv("MYSQL_USER") or "root",
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB") or "biz_plan_revert",
    autocommit=True)
cur = cn.cursor()
cur.execute("SELECT operating_model_json FROM intake_consult_drafts WHERE draft_id LIKE '98552970%'")
VANGUARD_OPS = json.loads(cur.fetchone()[0])
cn.close()

TEMPLATE = ("with average account and project values anchored in "
            "{{fact:ops.unit_price}} per {{fact:ops.unit_name}} for planning")
rendered = render_fact_template(
    TEMPLATE, shared_context={"operating_model": VANGUARD_OPS}, business_facts={})
check("#2 no welded range in the idiom", "-$" not in rendered and "-" not in rendered.split("anchored in ")[1].split(" for planning")[0].replace("‑", ""))
check("#2 paired per-product rendering present",
      "$3,400 per" in rendered and "$22,500 per" in rendered and " and " in rendered)

# NEG: single product renders the plain scalar (no pairing, no range).
SINGLE_OPS = _ops(90.0, 12)
rendered_s = render_fact_template(
    "priced at {{fact:ops.unit_price}} per {{fact:ops.unit_name}}",
    shared_context={"operating_model": SINGLE_OPS}, business_facts={})
check("#2 NEG single product unchanged", "$90 per" in rendered_s and " and " not in rendered_s)

# NEG: price placeholder alone (no 'per name' idiom) keeps the range form.
rendered_r = render_fact_template(
    "prices span {{fact:ops.unit_price}} across lines",
    shared_context={"operating_model": VANGUARD_OPS}, business_facts={})
check("#2 NEG bare price placeholder keeps range", "$3,400-$22,500" in rendered_r)

# ============ #3 promise wording above ceiling ============
from client_intake_and_finmo.intake_coherence.section import _converged_suffix  # noqa: E402

EVAL = {"q11": {"ebitda": 635776.0, "ebitda_margin": 0.115, "revenue": 5528487.0}}
TH_ABOVE = {"band_low": 0.06, "band_high": 0.11}
txt = _converged_suffix(EVAL, TH_ABOVE)
check("#3 above-ceiling names the range and the tempering",
      "above the 6.0%-11.0% range" in txt and "temper" in txt
      and "honest ceiling" in txt)
check("#3 above-ceiling no longer reads as a clean pass",
      "comfortably above" not in txt)
TH_IN = {"band_low": 0.06, "band_high": 0.13}
txt2 = _converged_suffix(EVAL, TH_IN)
check("#3 NEG inside-band wording unchanged",
      "inside the 6.0%-13.0% range judged believable" in txt2)

# ============ #4 reference code ============
from client_intake_and_finmo.intake_submission import (  # noqa: E402
    display_reference_code, generate_client_id,
)

ids = [generate_client_id() for _ in range(50)]
check("#4 new ids are alphanumeric only (7 letters + 11 digits)",
      all(cid.isalnum() and len(cid) == 18 for cid in ids))
check("#4 legacy id display-strips the specials ('$%PEGJUYN...' -> 'PEGJUYN...')",
      display_reference_code("$%PEGJUYN94787121227") == "PEGJUYN94787121227")
check("#4 clean id passes through display unchanged",
      display_reference_code("JTFHGIN14891827972") == "JTFHGIN14891827972")

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
