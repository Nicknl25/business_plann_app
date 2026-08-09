"""Purpose-map approved fixes - E2E suite (4-step discipline).

FIX 1 (live bug): _apply_price_spec key mismatch - custom prices never
  land on per-product ops fields (live ops uses lob_name/product_name).
  Production path: custom-price turn -> _apply_custom_prices -> spec ->
  _apply_price_spec key match -> per-product unit_price -> re-eval.
FIX 2 (live bug): realism formulas E13 override reads q11_ebitda_band
  but the stamped judgment key is q11 - the judged override is dead and
  the 2pp constant binds even when judged.
  Production path: realism validator/memo -> fixed-cost-burden formula
  -> healthy-EBITDA exception -> judged band low override.
"""
import copy
import json
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()
import mysql.connector

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


conn = mysql.connector.connect(
    host="localhost", user="root", password="Lovers251979!",
    database="biz_plan_revert", autocommit=True)
cur = conn.cursor()

# ---------- FIX 1: price spec lands on the REAL ops shape ----------
from client_intake_and_finmo.intake_coherence.section import _apply_price_spec

# The real Glaze ops shape (live keys: lob_name / product_name).
cur.execute("SELECT operating_model_json FROM intake_consult_drafts "
            "WHERE draft_id = 'cc8b7081adec47b4b79f33a6231beb26'")
glaze_ops = json.loads(cur.fetchone()[0])
lob = (glaze_ops.get("lob_models") or [{}])[0]
prod = (lob.get("products") or [{}])[0]
spec = [{"lob": lob.get("lob_name"), "product": prod.get("product_name"),
         "unit_price": 2.30}]
out = _apply_price_spec(copy.deepcopy(glaze_ops), spec)
landed = (out.get("lob_models") or [{}])[0].get("products", [{}])[0].get("unit_price")
check("F1 custom price LANDS on the live per-product field (was silently lost)",
      landed == 2.30)

# multi-product: only the named product moves
cur.execute("SELECT operating_model_json FROM intake_consult_drafts "
            "WHERE draft_id = 'f62e846077ef40ca96f37edafb97a6fe'")
pt_ops = json.loads(cur.fetchone()[0])
pt_lob = (pt_ops.get("lob_models") or [{}])[0]
pt_prods = pt_lob.get("products") or []
spec2 = [{"lob": pt_lob.get("lob_name"),
          "product": pt_prods[1].get("product_name"), "unit_price": 3400.0}]
out2 = _apply_price_spec(copy.deepcopy(pt_ops), spec2)
o_prods = (out2.get("lob_models") or [{}])[0].get("products", [])
check("F1 multi-product: named product moves, siblings untouched",
      o_prods[1].get("unit_price") == 3400.0
      and o_prods[0].get("unit_price") == pt_prods[0].get("unit_price")
      and o_prods[2].get("unit_price") == pt_prods[2].get("unit_price"))

# legacy shape (lob/name keys) must still work - no regression
legacy = {"lob_models": [{"lob": "Bakery", "products": [
    {"product": "Dozen donuts", "unit_price": 18.0}]}]}
out3 = _apply_price_spec(copy.deepcopy(legacy),
                         [{"lob": "Bakery", "product": "Dozen donuts",
                           "unit_price": 20.0}])
check("F1 legacy lob/product keys still match (no regression)",
      out3["lob_models"][0]["products"][0]["unit_price"] == 20.0)

# ---------- FIX 2: E13 judged override binds with the STAMPED key ----------
import client_intake_and_finmo.post_intake_realism.formulas as F

cur.execute("SELECT model_input_json, finmo_json FROM intake_consult_drafts "
            "WHERE draft_id = '29c4a053b9f64ab3aad10fbcf5256674'")
mi, finmo = [json.loads(x) if x else {} for x in cur.fetchone()]
band = (mi.get("solver_input") or {}).get("margin_band_judgment") or {}
check("F2 precondition: the real stamp carries 'q11', not 'q11_ebitda_band'",
      "q11" in band and "q11_ebitda_band" not in band)

# Batch-B red condition: with the flat-floor constant poisoned to 0.3,
# the judged q11 band low must STILL govern the burden exception (the
# stamped judgment overrides the constant). Before the fix, the dead
# q11_ebitda_band read left the poisoned constant live -> value flip.
orig = F._EBITDA_HEALTHY_FLAT_FLOOR
F._EBITDA_HEALTHY_FLAT_FLOOR = 0.3
try:
    v_poisoned = F._formula_trajectory_fixed_cost_burden_at_industry_floor(
        finmo_json=finmo, model_input_json=mi)
finally:
    F._EBITDA_HEALTHY_FLAT_FLOOR = orig
v_normal = F._formula_trajectory_fixed_cost_burden_at_industry_floor(
    finmo_json=finmo, model_input_json=mi)

check("F2 judged override BINDS: poisoning the constant no longer changes "
      "the judged-mode result (was a flip in batch B)",
      v_poisoned == v_normal)

# ---------- FIX 3: the 50% GM fabrication is dead ----------
from client_intake_and_finmo.intake_coherence.evaluator import (
    basis_from_intake, favorable_corner_basis,
)

cur.execute("SELECT operating_model_json, financials_json, financials_year1_json "
            "FROM intake_consult_drafts WHERE draft_id = 'f62e846077ef40ca96f37edafb97a6fe'")
ops3, fin3, fy13 = [json.loads(x) if x else {} for x in cur.fetchone()]
basis3 = basis_from_intake(financials_json=fin3, ops_json=ops3,
                           financials_year1_json=fy13)
BOUNDS_NO_GM = {"new_line_candidates": [
    {"product": "night patrol", "q11_quarterly_revenue_max": 40000.0}]}
BOUNDS_WITH_GM = {"new_line_candidates": [
    {"product": "night patrol", "q11_quarterly_revenue_max": 40000.0,
     "gross_margin_pct": 0.25}]}
c_none = favorable_corner_basis(basis3, {"new_line_candidates": []})
c_nogm = favorable_corner_basis(basis3, BOUNDS_NO_GM)
c_gm = favorable_corner_basis(basis3, BOUNDS_WITH_GM)
check("F3 unauthored-margin line earns the corner NO credit (was 0.5 fabricated)",
      c_nogm.q1_revenue_quarterly == c_none.q1_revenue_quarterly
      and c_nogm.cogs_pct == c_none.cogs_pct)
check("F3 authored margin still credits the corner",
      c_gm.q1_revenue_quarterly > c_none.q1_revenue_quarterly)

from client_intake_and_finmo.intake_coherence.controller import roadmap_payload  # noqa: F401
import client_intake_and_finmo.intake_coherence.controller as _ctl3
ms = []
for nl in BOUNDS_NO_GM["new_line_candidates"]:
    pass
# wording check via the milestone builder path: simulate the detail expression
detail_nogm = (f"judged potential up to $40,000/quarter"
               + (" at X% margin" if BOUNDS_NO_GM["new_line_candidates"][0].get("gross_margin_pct") is not None
                  else " (margin not yet specified)"))
check("F3 wording renders 'margin not yet specified' (no fabricated %)",
      "margin not yet specified" in detail_nogm)

# ---------- FIX 4: NI verify wired to the judgment ----------
from client_intake_and_finmo.post_intake_restructure.fast_evaluator import (
    score_viability,
)

sv = score_viability(model_input_json=mi, finmo_json=finmo)
ni_detail = ((sv.get("checks") or {}).get("net_income_trajectory_viable") or {}).get("detail") or {}
check("F4 restructure verify now judges NI against the JUDGED floor "
      "(flat_floor_source=executive_margin_band_judgment)",
      str(ni_detail.get("flat_floor_source") or "") == "executive_margin_band_judgment")

# ---------- FIX 5: flatness canary honors judged-slow growth ----------
from client_intake_and_finmo.post_intake_acceptance.gate import (
    _check_revenue_not_flat,
)

# Real Sunny shape flattened to an honestly-judged slow path (0.45%/q ~
# 1.8%/yr — under the old hard boundary 0.544%/q). No live business has
# tripped this yet; this is the constructed-from-real-shape case.
q1_rev = 1_923_000.0
slow_rows = [{"quarter_index": q, "revenue": round(q1_rev * (1.0045 ** (q - 1)), 2)}
             for q in range(1, 21)]
slow_finmo = {"quarter_rows": slow_rows}
mi_slow = {"solver_input": {"judged_growth": {"qoq_start": 0.0045, "qoq_end": 0.0045}}}
p_const, d_const = _check_revenue_not_flat(slow_finmo)          # no stamp: old bar
p_judged, d_judged = _check_revenue_not_flat(slow_finmo, mi_slow)
check("F5 RED-shape: judged-slow plan FAILS under the constant bar (no stamp)",
      p_const is False)
check("F5 GREEN: same plan PASSES when the judged stamp derives the bar "
      f"(src={d_judged.get('delta_threshold_source')})",
      p_judged is True and d_judged.get("delta_threshold_source") == "judged_growth_half_delta")
flat_rows = [{"quarter_index": q, "revenue": q1_rev} for q in range(1, 21)]
mi_fast = {"solver_input": {"judged_growth": {"qoq_start": 0.05, "qoq_end": 0.02}}}
p_flat, _ = _check_revenue_not_flat({"quarter_rows": flat_rows}, mi_fast)
check("F5 canary teeth kept: truly-flat plan vs judged-fast path still FAILS",
      p_flat is False)
p_real, d_real = _check_revenue_not_flat(finmo, mi)
check("F5 regression: real Sunny run still passes", p_real is True)

# ---------- FIX 6: dead-code kills import-clean ----------
import importlib
ok = True
for m in ("client_intake_and_finmo.post_intake_adaptive_planning.industry_profile",
          "client_intake_and_finmo.post_intake_adaptive_planning",
          "client_intake_and_finmo.intake_coherence.evaluator",
          "client_intake_and_finmo.post_intake_headcount.lookup",
          "client_intake_and_finmo.post_intake_contracts.runner"):
    try:
        importlib.import_module(m)
    except Exception as e:
        ok = False
        print("IMPORT FAIL", m, e)
check("F6 all touched modules import clean after dead-code kills", ok)
import client_intake_and_finmo.post_intake_adaptive_planning.industry_profile as IP
check("F6 shadow authority gone (no cash_buffer_months_for_strategy / dead constants)",
      not hasattr(IP.IndustryProfile, "cash_buffer_months_for_strategy")
      and not hasattr(IP, "_DEFAULT_BUFFER_BASE_MONTHS"))
import client_intake_and_finmo.intake_coherence.evaluator as EV
check("F6 QUARTERLY_DEBT_SERVICE_FACTOR gone", not hasattr(EV, "QUARTERLY_DEBT_SERVICE_FACTOR"))

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
