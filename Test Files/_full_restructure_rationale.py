"""Full executive rationale for a restructure run — every judgment,
verbatim, domain by domain."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
draft_id = sys.argv[1]
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT repair_guidance_json, model_input_json, planning_run_json, finmo_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
)
row = cur.fetchone() or {}


def _j(v):
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


g = _j(row.get("repair_guidance_json"))
mi = _j(row.get("model_input_json"))
pr = _j(row.get("planning_run_json"))
hist = ((g or {}).get("restructure") or {}).get("history") or []

SEP = "=" * 72
for it in hist:
    stage = str(it.get("stage") or "")
    print(SEP)
    print("STAGE:", stage)
    if stage == "bounds":
        b = it.get("bounds") or {}
        print("feasible_region_exists:", b.get("feasible_region_exists"))
        for ln in b.get("existing_lines") or []:
            print(f"\nLINE {ln.get('lob')} / {ln.get('product')}")
            print(f"  price ceiling x{ln.get('price_multiplier_max')}, volume cap x{ln.get('volume_multiplier_max')}, "
                  f"can_drop={ln.get('can_drop')}, gross margin {ln.get('gross_margin_pct')}")
            print("  WHY:", ln.get("rationale"))
        for nl in b.get("new_line_candidates") or []:
            print(f"\nNEW LINE {nl.get('lob')} / {nl.get('product')}")
            print(f"  price ${nl.get('unit_price')}, market cap ${nl.get('q11_quarterly_revenue_max')}/q, "
                  f"margin {nl.get('gross_margin_pct')}")
            print("  WHY:", nl.get("rationale"))
        for key in ("team", "facility", "cost_floors", "growth"):
            sec = b.get(key) or {}
            print(f"\n{key.upper()}:", {k: v for k, v in sec.items() if k != "rationale"})
            print("  WHY:", sec.get("rationale"))
        print("\nOVERALL:", b.get("overall_rationale"))
        print("\nREALITY CONSTRAINT ATTESTATIONS:")
        for k, v in (b.get("reality_constraints") or {}).items():
            print(f"  {k}: {v}")
    elif stage.startswith("search"):
        print("found:", it.get("found"), "evals:", it.get("evals"))
        for t in it.get("trace") or []:
            print("  ", t)
        print("candidate:", json.dumps(it.get("candidate"), sort_keys=True))
        print("landed:", json.dumps(it.get("landed"), sort_keys=True))
    elif stage.startswith("review"):
        r = it.get("review") or {}
        print("approved:", r.get("approved"),
              "| revenue_story_required:", r.get("revenue_story_required"),
              "| no_realistic_design_exists:", r.get("no_realistic_design_exists"))
        print("tightened:", json.dumps(r.get("tightened_lines"), sort_keys=True))
        print("FULL RATIONALE:", r.get("rationale"))
    else:
        print(json.dumps(it, default=str)[:800])

print(SEP)
print("PIPELINE JUDGMENTS ON THE RESTRUCTURED BUSINESS:")
si = (mi.get("solver_input") or {}) if isinstance(mi, dict) else {}
for key in ("wc_judgment", "margin_band", "judged_growth", "headcount_coherence", "restructure_directive"):
    v = si.get(key)
    if isinstance(v, dict):
        print(f"\n{key}:")
        print(json.dumps({k: vv for k, vv in v.items() if k not in ("history",)}, sort_keys=True, default=str)[:1200])
print("\nCASH STRATEGY (planning_run_json):")
for key in ("cash_strategy_review_decision", "cash_strategy_effect_summary"):
    v = pr.get(key)
    if v:
        print(f"\n{key}:", json.dumps(v, default=str)[:1200])
cur.close()
conn.close()
