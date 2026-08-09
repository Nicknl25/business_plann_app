"""PHASE 4 - lever lifts E2E: the volume round + the COGS move.

Production path: plan_rounds -> _volume_round (corner's own projection
math) -> apply_router_patch "ops_volume" -> ops truth + anchor +
basis-tagged COGS + {from,to} lever writes; and _costs_round's new cogs
move (basis-tag-aware field patch). RED evidence: the corner SPENDS
volume_multiplier_max and cogs_percent_of_revenue_min, so clients were
routed into walks whose arithmetic assumed levers no round could offer
(F&F's 'another dog or two' had no lever).
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
    ROUND_VOLUME, Thresholds, _costs_round, _effective_vmax,
    _volume_move_basis, _volume_round, ops_line_split, plan_rounds,
)
from client_intake_and_finmo.intake_coherence.evaluator import (  # noqa: E402
    basis_from_intake,
)
from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
    _compute_band_identity_digest, apply_router_patch,
)

OPS = {"lob_models": [{"lob_name": "Grooming", "products": [{
    "product_name": "Full groom", "unit_price": 60.0,
    "units_per_period_capacity": 40.0, "operating_periods_per_year": 52.0,
    "utilization_rate": 0.7}]}]}
FIN = {"current_revenue": 87360.0, "baseline_payroll_year1": 75000.0,
       "other_opex_absolute": 17400.0, "marketing_total_year1": 600.0,
       "cogs_percent_of_revenue": 0.08}
# band_low high enough that this shape has a real Q11 gap - rounds only
# build while a gap is open.
TH = Thresholds(gm_floor=0.3, burden_max=0.75, band_low=0.40,
                ni_floor=0.02, band_high=0.55, judged=True)
BOUNDS = {"existing_lines": [{
    "lob": "Grooming", "product": "Full groom",
    "price_multiplier_max": 1.2, "volume_multiplier_max": 1.5,
    "unit_price_at_authoring": 60.0,
    "annual_units_at_authoring": 40.0 * 52.0 * 0.7,  # 1,456
}], "cost_floors": {"cogs_percent_of_revenue_min": 0.05}}

split = ops_line_split(OPS, FIN)
basis = basis_from_intake(financials_json=FIN, ops_json=OPS,
                          financials_year1_json={})

# V1: the units ratchet - after volume grows, the effective multiple
# shrinks so units never exceed authoring x vmax.
line = dict(split[0])
check("V1 effective vmax = raw vmax at authoring volume",
      abs(_effective_vmax(line, BOUNDS["existing_lines"][0]) - 1.5) < 1e-9)
line_grown = dict(line, annual_units=line["annual_units"] * 1.25)
ev = _effective_vmax(line_grown, BOUNDS["existing_lines"][0])
check(f"V1b after a 1.25x volume move the ceiling caps at 1.2x ({ev:.4f}) "
      "- units never exceed authoring x 1.5", abs(ev - 1.5 / 1.25) < 1e-6)

# V2: volume-move semantics (the corner's law): cogs pct HOLDS, dollar
# overheads rescale, revenue scales.
moved = _volume_move_basis(basis, split, {"Grooming␟Full groom": 1.5})
check("V2 volume carries COGS (pct held), revenue x1.5, G&A pct rescaled",
      abs(moved.q1_revenue_quarterly - basis.q1_revenue_quarterly * 1.5) < 0.01
      and abs(moved.cogs_pct - basis.cogs_pct) < 1e-9
      and abs(moved.gna_pct - basis.gna_pct / 1.5) < 1e-9
      and abs(moved.payroll_quarterly - basis.payroll_quarterly) < 1e-9)

# V3: the round - options, closure, utilization-first landing.
rnd = _volume_round(basis, TH, BOUNDS, split)
check("V3 volume round exists with mid+max options",
      rnd is not None and rnd["key"] == ROUND_VOLUME
      and {o["id"] for o in rnd["options"]} == {"volume_mid", "volume_max"})
o_max = next(o for o in rnd["options"] if o["id"] == "volume_max")
landing = o_max["patch"]["volumes"][0]
# m=1.5 on util 0.7 -> util fills to 1.0, capacity x (1.5*0.7/1.0)=1.05
check("V3b utilization-first landing (util 0.7 -> 1.0, cap 40 -> 42)",
      abs(landing["utilization_rate"] - 1.0) < 1e-6
      and abs(landing["units_per_period_capacity"] - 42.0) < 1e-3)
check("V3c anchor moves with the units (87,360 -> 131,040)",
      abs(o_max["patch"]["current_revenue"] - 87360.0 * 1.5) < 1.0)
o_mid = next(o for o in rnd["options"] if o["id"] == "volume_mid")
land_mid = o_mid["patch"]["volumes"][0]
check("V3d mid option stays inside capacity (util 0.7 -> 0.875, cap held)",
      abs(land_mid["utilization_rate"] - 0.875) < 1e-6
      and abs(land_mid["units_per_period_capacity"] - 40.0) < 1e-3)

# V4: plan_rounds offers volume (pricing leads, volume next by order).
allr = plan_rounds(basis=basis, thresholds=TH, bounds=BOUNDS,
                   ops_json=OPS, financials_json=FIN,
                   rounds_done=["pricing"])
check("V4 plan_rounds reaches the volume round once pricing is walked",
      allr is not None and allr["key"] == ROUND_VOLUME)

# V5: APPLY (ratio-basis): ops truth updated, anchor moved, cogs pct
# held, lever writes {from,to}; the identity digest matches authoring.
fin_r = dict(FIN)
fin_r["_coherence"] = {"round": rnd}
d0, _ = _compute_band_identity_digest(
    {}, ops_json=OPS, people_json={}, market_json={},
    marketing_model_json={}, financials_json=FIN)
_rem, ops2, fin2, notes = apply_router_patch(
    patch={"coherence.option": "volume_max"},
    ops_json=OPS, financials_json=fin_r)
p2 = ops2["lob_models"][0]["products"][0]
check("V5 ops truth landed (util 1.0, cap 42) and anchor moved",
      abs(p2["utilization_rate"] - 1.0) < 1e-6
      and abs(p2["units_per_period_capacity"] - 42.0) < 1e-3
      and abs(fin2["current_revenue"] - 131040.0) < 1.0)
st2 = fin2.get("_coherence") or {}
lw2 = st2.get("_lever_writes") or {}
check("V5b lever write recorded {from 87,360, to 131,040}",
      isinstance(lw2.get("current_revenue"), dict)
      and abs(lw2["current_revenue"]["from"] - 87360.0) < 0.01
      and abs(lw2["current_revenue"]["to"] - 131040.0) < 1.0)
check("V5c ratio-basis cogs pct untouched (Recalc re-derives dollars)",
      abs(fin2.get("cogs_percent_of_revenue") - 0.08) < 1e-9)
d1, _ = _compute_band_identity_digest(
    st2, ops_json=ops2, people_json={}, market_json={},
    marketing_model_json={}, financials_json=fin2)
check("V5d post-lever digest == authoring digest (CW-020 held for volume)",
      d1 == d0)

# V6: APPLY (dollars-basis): stated COGS dollars scale with volume
# (volume carries cost) and the write is excluded from identity.
fin_d = dict(FIN, cogs_basis="dollars", current_cogs=5900.0,
             cogs_total_year1=5900.0)
fin_d["_coherence"] = {"round": rnd}
_rem, ops3, fin3, _n3 = apply_router_patch(
    patch={"coherence.option": "volume_max"},
    ops_json=OPS, financials_json=fin_d)
check("V6 dollars-basis COGS scales with volume ($5,900 -> $8,850)",
      abs(fin3["current_cogs"] - 8850.0) < 0.01
      and abs(fin3["cogs_total_year1"] - 8850.0) < 0.01)
lw3 = (fin3.get("_coherence") or {}).get("_lever_writes") or {}
check("V6b cogs lever write recorded {from 5,900, to 8,850}",
      isinstance(lw3.get("current_cogs"), dict)
      and abs(lw3["current_cogs"]["from"] - 5900.0) < 0.01)

# V7: the COGS move in the costs round, basis-tag-aware.
rnd_c = _costs_round(basis, TH, BOUNDS, FIN)
cogs_move = None
if rnd_c:
    for o in rnd_c["options"]:
        if o["id"] == "costs_cogs":
            cogs_move = o
check("V7 ratio-basis cogs move patches the PCT to the judged floor",
      cogs_move is not None
      and cogs_move["patch"]["fields"][0]["field"] == "cogs_percent_of_revenue"
      and abs(cogs_move["patch"]["fields"][0]["value"] - 0.05) < 1e-9)
rnd_cd = _costs_round(basis, TH, BOUNDS,
                      dict(FIN, cogs_basis="dollars", current_cogs=6988.8))
cogs_move_d = None
if rnd_cd:
    for o in rnd_cd["options"]:
        if o["id"] == "costs_cogs":
            cogs_move_d = o
_fields_d = {f["field"]: f["value"] for f in (cogs_move_d or {}).get("patch", {}).get("fields", [])}
check("V7b dollars-basis cogs move patches the DOLLARS "
      f"(cogs_total_year1+current_cogs = {_fields_d.get('cogs_total_year1')})",
      cogs_move_d is not None
      and abs(_fields_d.get("cogs_total_year1", 0) - 0.05 * 87360.0) < 0.01
      and abs(_fields_d.get("current_cogs", 0) - 0.05 * 87360.0) < 0.01)
# deep-cut guard: a floor below half the stated line flags ask-first.
rnd_deep = _costs_round(
    basis, TH,
    {"existing_lines": BOUNDS["existing_lines"],
     "cost_floors": {"cogs_percent_of_revenue_min": 0.03}}, FIN)
deep_opt = next((o for o in (rnd_deep or {}).get("options", [])
                 if o["id"] == "costs_cogs"), None)
check("V7c deep cut (>50% of the stated line) flagged, never recommended",
      deep_opt is not None and deep_opt["deep_cut"] and not deep_opt["recommended"])

# V8: client floor honored - 'the supplies are what they are'.
fin_floor = dict(FIN)
fin_floor["_coherence"] = {"client_floors": {"cogs": True}}
rnd_f = _costs_round(basis, TH, BOUNDS, fin_floor)
check("V8 asserted cogs floor kills the move",
      not any(o["id"] == "costs_cogs" for o in (rnd_f or {}).get("options", [])))

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
