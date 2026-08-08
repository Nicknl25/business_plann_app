"""CW-019 capacity coherence cross-check - the exact Catawba live shape.

The breaking turn, verbatim: the client corrected the seasonal price and
restated the arithmetic naming ONLY the utilized volume - "That's 1,120
jobs at $1,450, which is $1,624,000" - on a product stored capacity
1,400 @ 80%. The router wrote capacity=1120 (derivable: verbatim in the
client's words). RED: capacity 1,120 lands, implied revenue drops to
$7,761,200, post-gap 4% kills the (i2) reconcile, revenue propagates off
the stated $8,086,000 (observed $7,925,873 live). GREEN: coherence picks
1,400, implied total = stated exactly, disposition reconciles.
"""
import copy
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")

from dotenv import load_dotenv

load_dotenv()

from api_handlers.intake_consult import (  # noqa: E402
    _capacity_effective_volume_correction,
    _driver_correction_disposition,
    _guard_underivable_ops_lever_writes,
)

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


# The Catawba ops shape (real draft values, pre-correction price $1,300).
def _catawba_ops(seasonal_price, seasonal_cap):
    return {"lob_models": [{"lob_name": "Grounds", "products": [
        {"product_name": "maintenance_contracts", "unit_price": 1200,
         "units_per_period_capacity": 240, "operating_periods_per_year": 12,
         "utilization_rate": 0.75},
        {"product_name": "install_projects", "unit_price": 86000.0,
         "units_per_period_capacity": 60, "operating_periods_per_year": 1,
         "utilization_rate": 0.75},
        {"product_name": "seasonal_emergency_work", "unit_price": seasonal_price,
         "units_per_period_capacity": seasonal_cap, "operating_periods_per_year": 1,
         "utilization_rate": 0.8},
    ]}]}

T111 = ("Before I submit, one driver fix so the model ties to my statement. "
        "The seasonal and emergency average is $1,450 a job, not $1,300 - I "
        "gave you the number from two years ago, we repriced after the ice "
        "storm. That's 1,120 jobs at $1,450, which is $1,624,000. With "
        "maintenance at $2,592,000 and installs at $3,870,000 those three "
        "add to $8,086,000, which is exactly the revenue I told you.")

STATED_REVENUE = 8_086_000.0

before = _catawba_ops(1300, 1400)
# The router's live write: price corrected AND capacity clobbered with 1,120.
after = copy.deepcopy(before)
after["lob_models"][0]["products"][2]["unit_price"] = 1450
after["lob_models"][0]["products"][2]["units_per_period_capacity"] = 1120.0
after["lob_models"][0]["products"][2]["units_per_week_capacity"] = 1120.0

out = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(before), ops_after=after,
    user_message=T111, last_assistant="")
p_seasonal = out["lob_models"][0]["products"][2]
check("capacity coherence rejects the utilized volume, lands 1,400",
      p_seasonal["units_per_period_capacity"] == 1400.0)
check("price correction still lands ($1,450)", p_seasonal["unit_price"] == 1450)
check("week mirror follows the corrected capacity (1400 x 1/52)",
      abs(p_seasonal["units_per_week_capacity"] - round(1400 * 1 / 52.0, 6)) < 1e-9)


def _implied_total(ops):
    total = 0.0
    for lob in ops["lob_models"]:
        for p in lob["products"]:
            total += (p["units_per_period_capacity"] * p["operating_periods_per_year"]
                      * p["unit_price"] * p["utilization_rate"])
    return total

implied_corrected = _implied_total(out)
check("implied model lands ON the stated figure ($8,086,000 exactly)",
      abs(implied_corrected - STATED_REVENUE) < 1.0)

pre_implied = _implied_total(before)  # old price $1,300 model
disp = _driver_correction_disposition(
    pre_implied=pre_implied, post_implied=implied_corrected, stated=STATED_REVENUE)
check("disposition RECONCILES -> stated revenue holds at $8,086,000",
      disp == "reconcile")

# RED arithmetic (the live failure, for the record): with capacity 1,120
# the implied total is $7,761,200 - a 4% post-gap that legitimately
# defeats the (i2) reconcile and lets revenue propagate.
broken = copy.deepcopy(before)
broken["lob_models"][0]["products"][2]["unit_price"] = 1450
broken["lob_models"][0]["products"][2]["units_per_period_capacity"] = 1120.0
implied_broken = _implied_total(broken)
check("RED arithmetic confirmed: broken capacity implies $7,761,200 (4% gap)",
      abs(implied_broken - 7_761_200.0) < 1.0
      and _driver_correction_disposition(
          pre_implied=pre_implied, post_implied=implied_broken,
          stated=STATED_REVENUE) != "reconcile")

# NEG 1: a GENUINE capacity change whose raw reading matches the stated
# dollars must land untouched ("capacity is 1,600 now - 1,600 jobs at
# $1,450 at 80% is $1,856,000").
after_g = copy.deepcopy(before)
after_g["lob_models"][0]["products"][2]["units_per_period_capacity"] = 1600.0
out_g = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(before), ops_after=after_g,
    user_message="Capacity is 1,600 now - 1,600 jobs at $1,450 at 80% "
                 "utilization is $1,856,000 on that line.", last_assistant="")
check("NEG genuine capacity change (raw-coherent) lands untouched",
      out_g["lob_models"][0]["products"][2]["units_per_period_capacity"] == 1600.0)

# NEG 2: no dollar figures in the message -> no correction attempted.
after_n = copy.deepcopy(before)
after_n["lob_models"][0]["products"][2]["units_per_period_capacity"] = 1120.0
out_n = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(before), ops_after=after_n,
    user_message="We handle 1,120 jobs on the seasonal side.", last_assistant="")
check("NEG no stated dollars -> write kept as-is",
      out_n["lob_models"][0]["products"][2]["units_per_period_capacity"] == 1120.0)

# NEG 3: utilization 1.0 (raw == effective, ambiguous) -> keep the write.
check("NEG util=1.0 -> helper declines",
      _capacity_effective_volume_correction(
          1120.0, {"unit_price": 1450, "utilization_rate": 1.0,
                   "operating_periods_per_year": 1}, {}, T111) is None)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
