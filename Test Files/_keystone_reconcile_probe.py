"""Reproduce the F&F correction turn's driver-reconcile offline: did
the CW-011 consequence contract revert the price/capacity landing?"""
import copy
import json
import os
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()

from api_handlers.intake_consult import (  # noqa: E402
    _lever_value_derivable, _message_figures, _reconcile_driver_correction,
)

MSG = ("I was looking at my numbers again - my price is actually 60 dollars "
       "per groom, not 112, and I can do 40 appointments a week, not 30.")
print("figures:", _message_figures(MSG))

ops_before = {"lob_models": [{"lob_name": "Primary line of business", "products": [{
    "product_name": "Mobile grooming appointment", "unit_price": 112,
    "units_per_period_capacity": 30, "units_per_week_capacity": 30,
    "utilization_rate": 0.7, "operating_periods_per_year": 52}]}]}
ops_after = copy.deepcopy(ops_before)
p = ops_after["lob_models"][0]["products"][0]
p["unit_price"] = 60.0
p["units_per_period_capacity"] = 40.0
p["units_per_week_capacity"] = 40.0

figs = _message_figures(MSG)
for leaf, v in (("unit_price", 60.0), ("units_per_period_capacity", 40.0),
                ("units_per_week_capacity", 40.0)):
    print(f"derivable({leaf}={v}):", _lever_value_derivable(leaf, v, figs, 52.0))

fixed, note = _reconcile_driver_correction(
    ops_before=ops_before, ops_after=ops_after, user_message=MSG,
    consumed_figures=[])
print("ops after reconcile:", json.dumps(
    fixed["lob_models"][0]["products"][0], indent=1))
print("note:", json.dumps(note, indent=1) if note else None)
