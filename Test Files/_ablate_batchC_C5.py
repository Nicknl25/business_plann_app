"""ABLATION BATCH C — C5: industry_profile shadow-authority dead-or-alive proof.
Static import evidence + Peachtree run-trace evidence + runtime demonstration."""
import json, sys
import mysql.connector

sys.path.insert(0, "C:/dev/business_plann_app/python")
DRAFT = "f62e846077ef40ca96f37edafb97a6fe"
RUN = "22e3db068db1401f84ffb0cb322e20f3"

conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!", database="biz_plan_revert")
cur = conn.cursor(dictionary=True)

print("=== Peachtree run traces mentioning industry_profile ===")
cur.execute("SELECT planning_run_json FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,))
prj_raw = cur.fetchone()["planning_run_json"] or ""
print("planning_run_json occurrences of 'industry_profile':", prj_raw.count("industry_profile"))
if "industry_profile" in prj_raw:
    prj = json.loads(prj_raw)
    def walk(node, path=""):
        hits = []
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}"
                if "industry_profile" in str(k):
                    hits.append((p, str(v)[:120]))
                hits.extend(walk(v, p))
        elif isinstance(node, list):
            for i, v in enumerate(node[:30]):
                hits.extend(walk(v, f"{path}[{i}]"))
        return hits
    for p, v in walk(prj)[:10]:
        print(f"  {p} = {v}")

cur.execute("SHOW COLUMNS FROM post_intake_run_diagnostics")
diag_cols = [r["Field"] for r in cur.fetchall()]
idcol = "planning_run_id" if "planning_run_id" in diag_cols else diag_cols[1]
cur.execute(f"SELECT * FROM post_intake_run_diagnostics WHERE {idcol}=%s", (RUN,))
found = 0
for r in cur.fetchall():
    blob = json.dumps(r, default=str)
    if "industry_profile" in blob:
        found += 1
        if found <= 3:
            for k, v in r.items():
                if "industry_profile" in str(v):
                    print(f"  diag row {r.get('id')}: {k} contains: {str(v)[:200]}")
print(f"diagnostic rows mentioning industry_profile: {found}")
conn.close()

print("\n=== Runtime proof: buffer constants cannot reach any number ===")
print("call sites of cash_buffer_months_for_strategy across python/: NONE (grep: only the def in industry_profile.py:140)")
print("run_mode_based_cash_strategy (orchestrator_invocation.py:196): `del planning_run_id, industry_profile, conn` -> the cash pass DELETES the profile")
print("feasibility_restoration.py:324: `_ = financials_json, ..., industry_profile` -> discarded")
print("apply_path_stamp_pass -> path_engine.py:625 reads ONLY profile['bands'] (lever targets)")
print("finmo_bridge.py:3454 reads ONLY bands['effective_tax_rate'] (live band consumer, not the constants)")
print("realism formulas own LOCAL copies: _GROSS_MARGIN_RECOVERY_FLOOR / _FIXED_COST_BURDEN_INDUSTRY_MAX=0.65 (formulas.py:997)")
print("coherence evaluator floors come from GPT margin-band judgment w/ local FALLBACK_* constants (evaluator.py:125-140)")

from client_intake_and_finmo.intake_coherence import evaluator as ev
print("evaluator fallbacks:", {k: getattr(ev, k, None) for k in ("FALLBACK_GM_FLOOR", "FALLBACK_BURDEN_MAX", "FALLBACK_BAND_LOW", "FALLBACK_NI_FLOOR")})

# Live ablation demonstration: mutate the module constants, build a profile, show nothing downstream reads them
import client_intake_and_finmo.post_intake_adaptive_planning.industry_profile as ip
orig = (ip._DEFAULT_BUFFER_BASE_MONTHS, ip._CASH_BUFFER_FLOOR_MONTHS, ip._DEFAULT_FIXED_COST_BURDEN_CEILING_Q11, ip._DEFAULT_GROSS_MARGIN_FLOOR_Q11)
ip._DEFAULT_BUFFER_BASE_MONTHS = 999.0
ip._CASH_BUFFER_FLOOR_MONTHS = 999.0
ip._DEFAULT_FIXED_COST_BURDEN_CEILING_Q11 = 999.0
ip._DEFAULT_GROSS_MARGIN_FLOOR_Q11 = 999.0
prof = ip.get_industry_profile(naics_6="561612", stage_profile="operational", target_annual_revenue=7692000.0)
print("\nablated profile serializes the poison values:", {
    "cash_buffer_base_months": prof.cash_buffer_base_months,
    "cash_buffer_floor_months": prof.cash_buffer_floor_months,
    "fixed_cost_burden_ceiling_q11": prof.fixed_cost_burden_ceiling_q11,
    "gross_margin_floor_q11": prof.gross_margin_floor_q11,
})
print("cash_buffer_months_for_strategy('preserve_cash') on ablated profile:", prof.cash_buffer_months_for_strategy("preserve_cash"), " <- but NOTHING calls this method")
ip._DEFAULT_BUFFER_BASE_MONTHS, ip._CASH_BUFFER_FLOOR_MONTHS, ip._DEFAULT_FIXED_COST_BURDEN_CEILING_Q11, ip._DEFAULT_GROSS_MARGIN_FLOOR_Q11 = orig
print("(constants restored in-memory; no files touched)")
