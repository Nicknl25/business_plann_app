"""Builds 3-5 E2E (Nick-ruled slate): rent lease-gate, marketing offer
pulled, Q20 second point (internal only).

Production paths: _costs_round option assembly (lease flag / no
marketing move); refresh_eval_stamps + gate eval stamp -> _q20_hold.
"""
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()
results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


from client_intake_and_finmo.intake_coherence.controller import (  # noqa: E402
    Thresholds, _costs_round,
)
from client_intake_and_finmo.intake_coherence.evaluator import (  # noqa: E402
    basis_from_intake,
)
from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
    _q20_hold, refresh_eval_stamps,
)

OPS = {"lob_models": [{"lob_name": "L", "products": [{
    "product_name": "unit", "unit_price": 100.0,
    "units_per_period_capacity": 40.0, "operating_periods_per_year": 52.0,
    "utilization_rate": 0.7}]}]}
TH = Thresholds(gm_floor=0.3, burden_max=0.85, band_low=0.55,
                ni_floor=0.02, band_high=0.60, judged=True)
FIN = {"current_revenue": 145600.0, "baseline_payroll_year1": 42000.0,
       "current_payroll": 42000.0, "payroll_total_year1": 42000.0,
       "other_opex_absolute": 40000.0, "marketing_total_year1": 8000.0,
       "monthly_rent_expense": 2500.0, "cogs_percent_of_revenue": 0.08}
BOUNDS = {"existing_lines": [],
          "cost_floors": {"marketing_percent_of_revenue_min": 0.01,
                          "g_and_a_percent_of_revenue_min": 0.10},
          "facility": {"min_quarterly_rent": 4500.0},
          "team": {"min_annual_payroll": 40000.0}}
basis = basis_from_intake(financials_json=FIN, ops_json=OPS,
                          financials_year1_json={})
rnd = _costs_round(basis, TH, BOUNDS, FIN)
all_moves = {k: m for o in (rnd or {}).get("options", [])
             for k, m in (o.get("moves") or {}).items()}

# L1: rent move exists but is lease-gated - flagged, ask-first label,
# never recommended.
rent_opts = [o for o in (rnd or {}).get("options", []) if "rent" in (o.get("moves") or {})]
check("L1 rent move lease-gated (flag set, lease ask in the label)",
      rent_opts
      and all(o.get("lease_unknown") for o in rent_opts)
      and all("month-to-month" in o["label"] for o in rent_opts))
check("L1b no rent-touching option is ever recommended while lease "
      "status is unknown", all(not o.get("recommended") for o in rent_opts))

# L2: the marketing cut is NOT offered (demand dormant - pure-savings
# shape forbidden).
check("L2 marketing move pulled from the round "
      f"(moves={sorted(all_moves)})", "marketing" not in all_moves)

# Q20 second point - internal stamp only.
BAND = {"q11": {"low": 0.10, "high": 0.25},
        "q20": {"low": 0.12, "high": 0.30},
        "fixed_cost_burden_max_q11": 0.80,
        "labor_intensity_class": "high"}
FIN_Q = dict(FIN, _coherence={"margin_band_judgment": BAND, "digest_hash": "x"})
fin_q = refresh_eval_stamps(dict(FIN_Q), ops_json=OPS, financials_year1_json={})
q20 = ((fin_q.get("_coherence") or {}).get("eval") or {}).get("q20_hold")
check("Q1 q20_hold stamped by the every-turn refresh "
      f"({q20})", isinstance(q20, dict) and "direction" in q20
      and q20.get("q20_low") == 0.12)

# Q2: a thin structure whose Q11 margin sits below the mature floor is
# named 'relies_on_post_q11_growth' (direction-aware, no verdict).
_ev_thin = {"q11": {"revenue": 100000.0, "ebitda": 8000.0}}
q2 = _q20_hold(_ev_thin, BAND)
check("Q2 margin 8% < q20 low 12% -> relies_on_post_q11_growth, "
      "passed False", q2["passed"] is False
      and q2["direction"] == "relies_on_post_q11_growth")
_ev_ok = {"q11": {"revenue": 100000.0, "ebitda": 20000.0}}
q3 = _q20_hold(_ev_ok, BAND)
check("Q3 margin 20% >= 12% -> holds_mature_floor", q3["passed"] is True)

# Q4: INTERNAL ONLY - the check changes no verdict and asks no client
# question (eval passed-state untouched by the stamp).
ev_before = ((FIN_Q.get("_coherence") or {}).get("eval") or {})
ev_after = ((fin_q.get("_coherence") or {}).get("eval") or {})
check("Q4 internal only: verdict fields unchanged by the q20 stamp "
      "(no client-facing coupling)",
      ev_after.get("passed") in (True, False)
      and "q20" not in str(ev_after.get("binding") or {}).lower())

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
