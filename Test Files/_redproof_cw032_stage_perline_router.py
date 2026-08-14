"""CW-032 A-110 red-proof: the IN-STAGE router surface.

THE PRODUCTION CALL CHAIN (named first, per the E2E law):
  POST /intake/consult -> post_intake_consult_handler (focus=financials)
    -> _run_financials_turn_and_sync
    -> route_intent(consult_type="financials",
                    shared_context={financials_controller: {current_stage: cogs},
                                    operating_model: <4 lines>})
    -> _apply_stage_cogs_door_keys -> _apply_per_line_cogs_patch_keys -> ops rows

This probe drives the EXACT route_intent call the stage flow makes -- same
consult_type, same controller frame (built by the app's own
_build_financials_controller_context), same ops shape as the real Alderfen
draft 158f6816 -- with the client's real messages [75] and [77] from the run.

RED (pre-fix): the router narrows the per-line answer to the stage's blend
fields ("edit_patch for the narrow stage field(s) only"), so the patch
carries NO cogs_per_line_overrides and the 46/73/17/3 die at the blend
guard. GREEN (post-fix): message [75] emits FOUR entries with units, message
[77] emits ONE entry for Hardgoods sale; neither patches a blend field with
a per-line rate.
"""
import json
import os
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv("C:/dev/business_plann_app/.env")

from api_handlers.intake_consult import _build_financials_controller_context  # noqa: E402
from client_intake_and_finmo.intent_router import route_intent  # noqa: E402

# The real Alderfen ops shape (draft 158f6816): four lines, no rates yet.
OPS = {
  "lob_models": [
    {"lob_name": "Garden centre retail", "products": [
      {"product_name": "Plant sale", "unit_price": 65, "units_per_period_capacity": 360,
       "utilization_rate": 0.60, "operating_periods_per_year": 52, "unit_cadence": "weekly"},
      {"product_name": "Hardgoods sale", "unit_price": 85, "units_per_period_capacity": 150,
       "utilization_rate": 0.55, "operating_periods_per_year": 52, "unit_cadence": "weekly"},
    ]},
    {"lob_name": "Landscape services", "products": [
      {"product_name": "Install job", "unit_price": 4800, "units_per_period_capacity": 5,
       "utilization_rate": 0.68, "operating_periods_per_year": 52, "unit_cadence": "weekly"},
      {"product_name": "Design project", "unit_price": 950, "units_per_period_capacity": 3,
       "utilization_rate": 0.58, "operating_periods_per_year": 52, "unit_cadence": "weekly"},
    ]},
  ]
}

FINANCIALS = {"current_revenue": 1503000}

# The app's own per-line proposal, verbatim shape from the run (message [74]).
LAST_ASSISTANT = (
  "Your lines of business earn differently, so I'm setting up direct costs - "
  "materials, supplies, and other non-labor costs tied to delivering the work - "
  "separately for each:\n"
  "- Plant sale: about 58% of that line's revenue (typical range 53%-63%)\n"
  "- Hardgoods sale: about 68% of that line's revenue (typical range 63%-73%)\n"
  "- Install job: about 35% of that line's revenue (typical range 25%-45%)\n"
  "- Design project: about 5% of that line's revenue (typical range 0%-8%)\n"
  "Together that blends to about 50% of revenue. Should I use this "
  "direct-cost baseline?"
)

MSG_75 = (
  "Close, but let me give you my actual numbers. Plants are 46%. Hardgoods "
  "are 73% \u2014 that's the pallet-of-pavers problem. Install is 17% in "
  "materials because the labour is all on my payroll. And design is 3%, just "
  "printing and the odd soil test."
)
MSG_77 = "Hardgoods sale: 73 percent of that line's revenue."

# The COLLAPSE sentence the batch also routes in-stage (Nick's item):
MSG_COLLAPSE = (
  "Plants and hardgoods are both bought-in retail goods \u2014 treat those "
  "two as sharing one cost structure. Install and design each have their own."
)


def _frame(fin):
  shared = {
    "operating_model": OPS,
    "financials": fin,
    "financials_controller": _build_financials_controller_context(
      "cogs", last_assistant=LAST_ASSISTANT, financials_json=fin),
  }
  return shared


def drive(label, message):
  shared = _frame(dict(FINANCIALS))
  routed = route_intent(
    consult_type="financials",
    user_message=message,
    baseline_json=dict(FINANCIALS),
    shared_context=shared,
    recent_messages=[{"role": "assistant", "content": LAST_ASSISTANT}],
    confirm_question_override="Should I use this direct-cost baseline?",
    active_focus="financials",
  )
  action = routed.get("action")
  patch = routed.get("patch") if isinstance(routed.get("patch"), dict) else {}
  keys = sorted(patch.keys())
  per_line = None
  for k in ("financials.cogs_per_line_overrides", "cogs_per_line_overrides"):
    if k in patch:
      per_line = patch[k]
  groups = None
  for k in ("financials.cogs_shared_structure_groups", "cogs_shared_structure_groups"):
    if k in patch:
      groups = patch[k]
  blend_hit = [k for k in keys if k.split(".")[-1] in
               ("cogs_percent_of_revenue", "current_cogs", "cogs_total_year1")]
  print(f"== {label}")
  print(f"   action={action} patch_keys={keys}")
  print(f"   per_line={json.dumps(per_line)}")
  print(f"   groups={json.dumps(groups)}")
  print(f"   blend_fields_patched={blend_hit}")
  return {"action": action, "per_line": per_line, "groups": groups,
          "blend": blend_hit, "patch": patch}


def main():
  fails = []

  r75 = drive("[75] four per-line rates, one message", MSG_75)
  entries = r75["per_line"] if isinstance(r75["per_line"], list) else []
  named = {str((e or {}).get("line_name") or "").lower() for e in entries
           if isinstance(e, dict)}
  want = {"plant sale", "hardgoods sale", "install job", "design project"}
  ok_75 = (
    len(entries) == 4
    and all(isinstance(e, dict) and e.get("cogs_percent") is not None
            and str(e.get("cogs_percent_unit") or "") in ("percent", "ratio")
            for e in entries)
    and all(any(w in n or n in w for w in want) for n in named)
    and not r75["blend"]
  )
  if not ok_75:
    fails.append("[75] must emit 4 per-line entries w/ units, no blend field")

  r77 = drive("[77] canonical single-line retry", MSG_77)
  entries77 = r77["per_line"] if isinstance(r77["per_line"], list) else []
  ok_77 = (
    len(entries77) == 1
    and isinstance(entries77[0], dict)
    and "hardgoods" in str(entries77[0].get("line_name") or "").lower()
    and str(entries77[0].get("cogs_percent_unit") or "") == "percent"
    and not r77["blend"]
    and r77["action"] != "confirm_proceed"
  )
  if not ok_77:
    fails.append("[77] must emit ONE Hardgoods entry (percent), never "
                 "confirm_proceed on a contradicting number")

  rc = drive("[collapse] shared-structure sentence in-stage", MSG_COLLAPSE)
  gl = rc["groups"] if isinstance(rc["groups"], list) else []
  flat = []
  for g in gl:
    names = g if isinstance(g, list) else (g or {}).get("line_names") \
      if isinstance(g, dict) else []
    flat.append(sorted(str(n).lower() for n in (names or [])))
  ok_c = any("plant" in " ".join(ns) and "hardgood" in " ".join(ns)
             for ns in flat)
  if not ok_c:
    fails.append("[collapse] must emit cogs_shared_structure_groups with "
                 "plants+hardgoods in-stage")

  print()
  if fails:
    print("RED:")
    for f in fails:
      print("  -", f)
    sys.exit(1)
  print("GREEN: in-stage router emits the per-line door keys on all three "
        "wordings")
  sys.exit(0)


if __name__ == "__main__":
  main()
