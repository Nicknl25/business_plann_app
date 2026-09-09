"""mini: population census for (1) the owner-row uniqueness class (two named
owner-titled people collapsed to one) and (2) transient-field persistence
(_derived_patch_receipt / payroll_stated_total_target). Read-only."""
import json, os, re, sys
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/924bd877-ade8-4dd8-941d-a9a35bdf23fe/scratchpad")
from pd_db import q
OWNER = re.compile(r"owner|principal|founder|managing|partner", re.I)
rows = q("SELECT draft_id, business_name, status, created_at, people_json, financials_json, messages_json FROM intake_consult_drafts")
print("drafts:", len(rows))
hold, two_owner_now, transient_dpr, transient_target, two_named_owner_in_msgs = [], [], [], [], []
for r in rows:
    try: ppl = json.loads(r["people_json"] or "{}") or {}
    except Exception: ppl = {}
    try: fin = json.loads(r["financials_json"] or "{}") or {}
    except Exception: fin = {}
    people = [p for p in (ppl.get("people") or []) if isinstance(p, dict)]
    owners = [p for p in people if OWNER.search(str(p.get("role_title") or ""))]
    if len(owners) >= 2: two_owner_now.append((r["draft_id"][:8], r["business_name"], [(p.get("full_name"), p.get("role_title")) for p in owners]))
    if isinstance(fin.get("_owner_wage_conflict_hold"), dict): hold.append((r["draft_id"][:8], r["business_name"], str(r["created_at"])[:10], fin["_owner_wage_conflict_hold"], [(p.get("full_name"), p.get("role_title"), p.get("annual_wage")) for p in people]))
    if "_derived_patch_receipt" in fin: transient_dpr.append(r["draft_id"][:8])
    if "payroll_stated_total_target" in fin: transient_target.append((r["draft_id"][:8], fin.get("payroll_stated_total_target"), str(r["created_at"])[:10]))
print("\n[1] drafts holding >=2 owner-regex rows NOW:", len(two_owner_now))
for x in two_owner_now[:15]: print("   ", x)
print("\n[2] drafts carrying _owner_wage_conflict_hold (a second owner-titled person with a different stated wage was collapsed):", len(hold))
for x in hold: print("   ", x)
print("\n[3] transient _derived_patch_receipt persisted:", transient_dpr)
print("[4] payroll_stated_total_target persisted:", len(transient_target), transient_target[:12])
