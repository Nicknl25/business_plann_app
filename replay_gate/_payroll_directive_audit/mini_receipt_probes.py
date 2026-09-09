"""mini: adversarial receipt probes at the scoped door (unit level) - the
derived-field door must never drop in silence; a mixed patch must carry both
halves; the stated-total door must leave its receipt; transport keys must not
render. Handler-level reply composition is audited from the live canary."""
import json, os, sys
ROOT = r"C:/dev/business_plann_app"
for p in (ROOT, os.path.join(ROOT, "python")):
    if p not in sys.path: sys.path.insert(0, p)
from api_handlers.intake_consult import _apply_scoped_patch, _RECALC_DERIVED_FINANCIALS_FIELDS
from client_intake_and_finmo.capture_receipt import numeric_receipt, receipt_summary
fin0 = {"current_revenue": 1000000.0, "current_payroll": 282042.5, "payroll_total_year1": 282042.5, "owner_compensation": 8349.17}
def door(patch, fin=None):
    _bf, _op, _mk, _pp, fin1, _ff = _apply_scoped_patch(patch, business_facts={}, ops_json={}, market_json={}, people_json={"people": []}, financials_json=dict(fin or fin0), fulfillment_json={})
    return fin1
print("derived fields:", sorted(_RECALC_DERIVED_FINANCIALS_FIELDS)[:40])
print("\n[1] derived-only patch (owner_compensation=9000):")
f = door({"financials.owner_compensation": 9000})
print("   receipt:", f.get("_derived_patch_receipt"), "| owner_compensation stored:", f.get("owner_compensation"), "| landed directly?", f.get("owner_compensation") == 9000)
print("\n[2] mixed patch (current_revenue=1,200,000 + owner_compensation=9000):")
f = door({"financials.current_revenue": 1200000, "financials.owner_compensation": 9000})
r = numeric_receipt(before={"financials": fin0}, after={"financials": {k: v for k, v in f.items() if not k.startswith('_')}}, requested_fields=["financials.current_revenue", "financials.owner_compensation"])
print("   receipt transport:", f.get("_derived_patch_receipt"))
print("   numeric_receipt written:", r.get("written"), "dropped:", r.get("dropped"), "| summary:", receipt_summary(r))
print("\n[3] echo restatement (current_payroll=282042.5, equals stored):")
f = door({"financials.current_payroll": 282042.5})
print("   receipt transport:", f.get("_derived_patch_receipt"), "| stated target:", f.get("payroll_stated_total_target"))
print("\n[4] payroll-total statement (current_payroll=300000):")
f = door({"financials.current_payroll": 300000})
print("   receipt transport:", f.get("_derived_patch_receipt"), "| stated target:", f.get("payroll_stated_total_target"), "| current_payroll untouched:", f.get("current_payroll"))
print("\n[5] receipt_summary never renders the transport keys:")
r = numeric_receipt(before={"financials": fin0}, after={"financials": {**fin0, "payroll_stated_total_target": 300000.0}}, requested_fields=["financials.current_payroll"])
print("   ", r, "|", repr(receipt_summary(r)))
