"""THE DEMAND JUDGE E2E (Nick-ruled, all five rulings).

Production paths: revived _compute_marketing_model_json (bind + vocab
+ fail-loud) -> demand_evidence_level -> gpt_author_demand_response_
once -> validate_demand_response (THIN WITHHELD, rails) -> F-core
stamp -> plan_rounds consumption (conservative edge) -> option landing
(retained demand into the truth) -> Recalc.
Nick's five proofs: honest shape on real F&F; thin degrades honestly;
conservative edge; client override; byte-identical where demand
doesn't change.
"""
import copy
import json
import os
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


from client_intake_and_finmo.intake_coherence.gpt_demand_judgment import (  # noqa: E402
    demand_evidence_level, validate_demand_response,
)
from client_intake_and_finmo.intake_coherence.controller import (  # noqa: E402
    Thresholds, _costs_round, _price_move_basis, _pricing_round,
    _volume_round, ops_line_split, plan_rounds,
)
from client_intake_and_finmo.intake_coherence.evaluator import (  # noqa: E402
    basis_from_intake,
)
from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
    apply_router_patch,
)

# ---- D1: THIN-EVIDENCE DOCTRINE is airtight (validator-enforced).
thin_ev = demand_evidence_level({}, {})
check("D1 empty demand model classifies THIN with named reasons",
      thin_ev["level"] == "thin" and thin_ev["reasons"])
fabricated = {"price_response": {"verdict": "holds_most",
                                "retained_fraction_band": [0.97, 0.99],
                                "basis": "vibes"},
              "marketing_response": {"verdict": "insensitive",
                                     "demand_at_reduced_spend_band": [0.99, 1.0],
                                     "basis": "vibes"},
              "volume_headroom": {"supported_units_max": 99999, "basis": "vibes"},
              "rationale": "confident nonsense"}
v_thin = validate_demand_response(judgment=fabricated, evidence=thin_ev)
check("D1b THIN WITHHOLDS every verdict even when GPT fabricates "
      "confidence (the airtight rule)",
      v_thin["withheld"] is True and v_thin["price_response"] is None
      and v_thin["marketing_response"] is None
      and v_thin["volume_headroom"] is None
      and v_thin["evidence_level"] == "thin")

# ---- D2: rich validation rails - bands clamped, ordered, min width
# enforced by widening DOWNWARD (the conservative direction).
rich_ev = {"level": "rich", "reasons": []}
v_rich = validate_demand_response(judgment=fabricated, evidence=rich_ev)
band = v_rich["price_response"]["retained_fraction_band"]
check(f"D2 too-narrow band widened DOWNWARD to the 10-point floor "
      f"({band})", band[1] == 0.99 and abs(band[0] - 0.89) < 1e-6)

# ---- D3: conservative edge in the price projection - fewer retained
# customers means less revenue AND less COGS, overheads held.
OPS = {"lob_models": [{"lob_name": "G", "products": [{
    "product_name": "groom", "unit_price": 60.0,
    "units_per_period_capacity": 40.0, "operating_periods_per_year": 52.0,
    "utilization_rate": 0.7}]}]}
FIN = {"current_revenue": 87360.0, "baseline_payroll_year1": 39600.0,
       "current_payroll": 39600.0, "payroll_total_year1": 39600.0,
       "other_opex_absolute": 17400.0, "marketing_total_year1": 600.0,
       "cogs_percent_of_revenue": 0.08}
basis = basis_from_intake(financials_json=FIN, ops_json=OPS,
                          financials_year1_json={})
split = ops_line_split(OPS, FIN)
mults = {"G␟groom": 1.5}
moved_full = _price_move_basis(basis, split, mults, retained=1.0)
moved_cons = _price_move_basis(basis, split, mults, retained=0.85)
check("D3 retained=0.85: revenue = 1.5 x 0.85 x base; COGS dollars "
      "x0.85; payroll held",
      abs(moved_cons.q1_revenue_quarterly - basis.q1_revenue_quarterly * 1.275) < 0.01
      and abs(moved_cons.cogs_pct * moved_cons.q1_revenue_quarterly
              - basis.cogs_pct * basis.q1_revenue_quarterly * 0.85) < 0.01
      and moved_cons.q1_revenue_quarterly < moved_full.q1_revenue_quarterly
      and abs(moved_cons.payroll_quarterly - basis.payroll_quarterly) < 1e-9)

# ---- D4: the pricing round consumes the stamp's conservative edge and
# stamps the assumption + landing fraction on the option.
TH = Thresholds(gm_floor=0.3, burden_max=0.85, band_low=0.55,
                ni_floor=0.02, band_high=0.60, judged=True)
BOUNDS = {"existing_lines": [{"lob": "G", "product": "groom",
                              "price_multiplier_max": 1.5,
                              "unit_price_at_authoring": 60.0}],
          "cost_floors": {}, "team": {}}
DEMAND = {"evidence_level": "rich", "withheld": False,
          "price_response": {"verdict": "meaningful_loss",
                             "retained_fraction_band": [0.8, 0.95],
                             "basis": "test"},
          "marketing_response": {"verdict": "coupled",
                                 "demand_at_reduced_spend_band": [0.85, 0.97],
                                 "basis": "test"},
          "volume_headroom": {"supported_units_max": 1600.0, "basis": "test"}}
rnd = _pricing_round(basis, TH, BOUNDS, split, demand=DEMAND)
opt = next(o for o in rnd["options"] if o["id"] == "pricing_max")
check("D4 pricing option consumes the CONSERVATIVE edge (0.8) and "
      "carries the assumption + landing fraction",
      opt["retained_assumption"]["fraction_lo"] == 0.8
      and opt["patch"]["retained_fraction"] == 0.8
      and abs(opt["patch"]["current_revenue"] - 87360.0 * 1.5 * 0.8) < 1.0)

# ---- D5: LANDING - accept ripples the retained demand into the TRUTH
# (utilization scales so ops-implied == landed anchor; identity digest
# unchanged: lever accept never re-keys).
from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
    _compute_band_identity_digest,
)
fin5 = dict(FIN)
fin5["_coherence"] = {"round": rnd, "demand_response": DEMAND}
d0, _ = _compute_band_identity_digest(
    {}, ops_json=OPS, people_json={}, market_json={},
    marketing_model_json={}, financials_json=FIN)
_rem, ops5, fin5b, _n = apply_router_patch(
    patch={"coherence.option": "pricing_max"}, ops_json=copy.deepcopy(OPS),
    financials_json=fin5)
p5 = ops5["lob_models"][0]["products"][0]
_implied = p5["unit_price"] * p5["units_per_period_capacity"] * 52.0 * p5["utilization_rate"]
check("D5 landing: price 90, utilization 0.7 -> 0.56 (x0.8), "
      f"ops-implied {_implied:,.0f} == landed anchor "
      f"{fin5b['current_revenue']:,.0f}",
      abs(p5["unit_price"] - 90.0) < 0.01
      and abs(p5["utilization_rate"] - 0.56) < 1e-6
      and abs(_implied - fin5b["current_revenue"]) < 1.0)
d1, _ = _compute_band_identity_digest(
    fin5b.get("_coherence") or {}, ops_json=ops5, people_json={},
    market_json={}, marketing_model_json={}, financials_json=fin5b)
check("D5b post-landing digest == authoring digest (CW-020 held with "
      "the demand consequence)", d1 == d0)

# ---- D6: volume round capped by demand headroom (1600 units vs ops
# ceiling) - "do more" only where demand supports.
BOUNDS_V = {"existing_lines": [{"lob": "G", "product": "groom",
                                "volume_multiplier_max": 1.5,
                                "annual_units_at_authoring": 1456.0}],
            "cost_floors": {}, "team": {}}
rnd_v = _volume_round(basis, TH, BOUNDS_V, split, demand=DEMAND)
opt_v = next(o for o in rnd_v["options"] if o["id"] == "volume_max")
_to_units = opt_v["volumes"][0]["to_annual_units"]
check(f"D6 volume ceiling = demand headroom (1,600), not ops 1.5x "
      f"(2,184): to_annual_units={_to_units}",
      abs(_to_units - 1600.0) < 2.0)

# ---- D7: marketing REVIVED with coupled consequence; thin -> pulled.
FIN_M = dict(FIN, marketing_total_year1=8000.0)
basis_m = basis_from_intake(financials_json=FIN_M, ops_json=OPS,
                            financials_year1_json={})
BOUNDS_M = {"existing_lines": [], "cost_floors":
            {"marketing_percent_of_revenue_min": 0.01}, "team": {}}
rnd_m = _costs_round(basis_m, TH, BOUNDS_M, FIN_M, demand=DEMAND)
mv = {k: m for o in (rnd_m or {}).get("options", [])
      for k, m in (o.get("moves") or {}).items()}
check("D7 marketing move revived WITH its demand consequence "
      "(keep ~85% of the customers, in the display - CW-024 copy)",
      "marketing" in mv
      and mv["marketing"]["demand_consequence"]["demand_mult_lo"] == 0.85
      and "keep ~85%" in mv["marketing"]["to_display"])
rnd_m_thin = _costs_round(basis_m, TH, BOUNDS_M, FIN_M, demand=None)
mv_thin = {k: m for o in (rnd_m_thin or {}).get("options", [])
           for k, m in (o.get("moves") or {}).items()}
check("D7b no judgment -> marketing stays pulled (build-4 state)",
      "marketing" not in mv_thin)

# ---- D8: plan_rounds threads the stamp and ignores withheld.
fin8 = dict(FIN_M)
fin8["_coherence"] = {"demand_response": dict(DEMAND, withheld=True)}
rnds8 = plan_rounds(basis=basis_m, thresholds=TH, bounds=BOUNDS_M,
                    ops_json=OPS, financials_json=fin8, rounds_done=[])
_opts8 = (rnds8 or {}).get("options") or []
_all8 = {k for o in _opts8 for k in (o.get("moves") or {})}
check("D8 a WITHHELD stamp is ignored (marketing not offered; "
      "pre-demand behavior)", "marketing" not in _all8)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
