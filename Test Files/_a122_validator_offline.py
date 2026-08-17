"""A-122 offline seam checks on process_intake_submission (pre-DB errors dict):
(c) rowless legacy w/ flat drivers -> no unit_* errors; empty rowless -> SAME 3 messages
(d) single row lacking unit_price -> unit_price rejected (validation not skipped)
(e) multi-line -> unit_* checks skipped as before
Payloads deliberately omit contact fields so the run stops at IntakeValidationError."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from client_intake_and_finmo.intake_submit_service import process_intake_submission, IntakeValidationError

def errs(payload):
  base = {"consumer_type": "b2b", "client_id": "X", "business_type": "printing", "current_revenue": 1,
          "business_name": "b", "target_market_summary": "t", "key_people_summary": "k", "first_name": "a",
          "last_name": "b", "email_address": "e@e.com", "business_start_date": "2024-01-15",
          "target_market_b2b_industry": "x", "target_market_b2b_size": "x", "target_market_b2b_age": "x",
          "shipping_method": "none", "sales_modality": "physical", "geographic_scope": "local",
          "geographic_coverage": "town", "countries": "US", "milestones": [{"description": "d", "timing": "t"}],
          "capacity_driver": "labor", "primary_growth_lever": "x", "legal_entity": "LLC",
          "business_description_summary": "s"}
  base.update(payload)
  try:
    process_intake_submission(base)
  except IntakeValidationError as e:
    return {k: v for k, v in e.errors.items() if k.startswith("unit")}
  except Exception as e:
    return {"__other__": type(e).__name__}
  return {"__inserted__": True}  # must never happen: business_type is unmapped so naics lookup rejects

UNIT_KEYS = ("unit_name", "unit_description", "units_per_week_capacity", "unit_price")
fails = 0
def check(label, ok, detail=""):
  global fails
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
  fails += 0 if ok else 1

single = {"lob_models": [{"products": [{"unit_name": "print job", "unit_description": "d", "unit_price": 720, "units_per_week_capacity": 28}]}]}
e = errs(single); check("(a-seam) single row w/ drivers -> no unit_* errors", e == {}, str(e))
e = errs({"lob_models": [{"products": [{"unit_name": "print job", "unit_description": "d", "units_per_week_capacity": 28}]}]})
check("(d) single row lacking unit_price -> rejected", e == {"unit_price": "unit_price must be a number"}, str(e))
e = errs({"lob_models": [{"products": [{"unit_name": "print job", "unit_description": "d", "unit_price": 0, "units_per_week_capacity": 28}]}]})
check("(d2) single row unit_price 0 -> rejected", e == {"unit_price": "unit_price must be greater than 0"}, str(e))
e = errs({"unit_name": "appt", "unit_description": "d", "unit_price": 60, "units_per_week_capacity": 40})
check("(c) rowless legacy flat -> no unit_* errors", e == {}, str(e))
e = errs({})
check("(c) empty rowless -> SAME error text (4 unit_* keys)", e == {"unit_name": "unit_name is required", "unit_description": "unit_description is required", "units_per_week_capacity": "units_per_week_capacity must be a number", "unit_price": "unit_price must be a number"}, str(e))
e = errs({"lob_models": [{"products": [{"unit_name": "a", "unit_price": 1, "units_per_week_capacity": 1}, {"unit_name": "b"}]}]})
check("(e) multi-line -> unit_* checks skipped (unchanged)", e == {}, str(e))
e = errs({"lob_models": [{"products": [{"unit_name": "print job", "unit_price": 720, "units_per_week_capacity": 28}]}], "unit_description": "flat-desc"})
check("(f) row lacks unit_description, flat carries it (Tanager shape pre-Aug12 desc) -> accepted", e == {}, str(e))
print("RESULT:", "GREEN" if fails == 0 else f"RED ({fails})")
sys.exit(1 if fails else 0)
