# CW-033 offline probe: what do the REAL parsing functions see in the three
# Thornfield capacity-correction messages? No fixes yet - mechanism check.
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers import intake_consult as ic

M99 = ("About 3,100 a month on those. And one thing I need to fix from "
       "earlier - I said we can do 5 install jobs a week, but that was me "
       "thinking of two crews. We're running three crews now, so the "
       "install line's weekly capacity should be 7 jobs, not 5. Everything "
       "else stays as it is.")
M107 = ("Before I answer that - please go back and fix the install line. "
        "Its weekly capacity is wrong. It is currently set to five jobs "
        "per week and it needs to be seven jobs per week, because we run "
        "three crews now. Do not change any other line.")
M111 = ("Accounts payable about 121,000. Also, set the landscaping and "
        "installation line weekly capacity to seven jobs per week.")

OPS = {
    "lob_models": [
        {"lob_name": "Plant and nursery sales", "products": [
            {"product_name": "Plant and nursery sale", "unit_price": 52.0,
             "units_per_week_capacity": 340.0, "units_per_period_capacity": 340.0,
             "utilization_rate": 0.62, "operating_periods_per_year": 52,
             "unit_cadence": "weekly"}]},
        {"lob_name": "Hard goods retail", "products": [
            {"product_name": "Hard goods sale", "unit_price": 95.0,
             "units_per_week_capacity": 165.0, "units_per_period_capacity": 165.0,
             "utilization_rate": 0.57, "operating_periods_per_year": 52,
             "unit_cadence": "weekly"}]},
        {"lob_name": "Landscaping and installation services", "products": [
            {"product_name": "Landscaping/installation job", "unit_price": 2400.0,
             "units_per_week_capacity": 5.0, "units_per_period_capacity": 5.0,
             "utilization_rate": 0.66, "operating_periods_per_year": 52,
             "unit_cadence": "weekly"}]},
        {"lob_name": "Garden design and consultation", "products": [
            {"product_name": "Design/consultation project", "unit_price": 1250.0,
             "units_per_week_capacity": 3.0, "units_per_period_capacity": 3.0,
             "utilization_rate": 0.6, "operating_periods_per_year": 52,
             "unit_cadence": "weekly"}]},
    ]
}

for name, msg in (("M99", M99), ("M107", M107), ("M111", M111)):
    print("=" * 60)
    print(name, "figures:", ic._message_figures(msg))
    res = ic._apply_cross_section_driver_correction(
        ops_json=OPS, user_message=msg, report={})
    rep = {}
    res = ic._apply_cross_section_driver_correction(
        ops_json=OPS, user_message=msg, report=rep)
    if res is None:
        print(name, "applier -> None, report:", rep)
    else:
        _ops, ack = res
        rows = {p["product_name"]: p.get("units_per_week_capacity")
                for l in _ops["lob_models"] for p in l["products"]}
        print(name, "applier -> LANDED:", ack, rows)

print("=" * 60)
print("infer '58 rate':", ic._infer_figure_landing(
    figure=58.0,
    user_message=("The plants and hard goods lines share one cost "
                  "structure - call it one shared rate at 58 percent of "
                  "revenue for both."),
    financials_json={}, people_json={}, ops_json=OPS))
print("=" * 60)
import copy
move = {"key": "ops.units_per_period_capacity", "value": 7.0,
        "label": "capacity", "attributed": True}
shared = {"operating_model": copy.deepcopy(OPS), "people_capability": {}}
fin, sh, copy_txt = ic._apply_forward_move(
    move=move, stage_shared_context=shared, next_financials={},
    financials_year1_json={}, conn=None, intake_context={},
    user_message=M99, last_assistant="")
rows = {p["product_name"]: p.get("units_per_week_capacity")
        for l in sh["operating_model"]["lob_models"] for p in l["products"]}
print("forward-move copy:", repr(copy_txt))
print("forward-move rows after:", rows)
print("flat leak:", {k: v for k, v in sh["operating_model"].items()
                     if k != "lob_models"})
