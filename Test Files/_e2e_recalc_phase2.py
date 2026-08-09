"""PHASE 2 - invalidation honesty E2E.

Production path: gate_and_turn -> _compute_band_identity_digest (now
includes the client-stated financials basis, excludes the walk's own
lever writes) -> stale-artifact pops -> roadmap re-evaluation.
RED evidence = the residency findings: the digest excluded financials
entirely (corrections could never invalidate artifacts judged from
them) and the roadmap was a permanent latch.
"""
import copy
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
    _compute_band_identity_digest, _financials_identity_basis, gate_and_turn,
)

OPS = {"lob_models": [{"lob_name": "Cleaning", "products": [{
    "product_name": "House cleans", "unit_price": 110.0,
    "units_per_period_capacity": 50.0, "operating_periods_per_year": 52.0,
    "utilization_rate": 0.7}]}]}
FIN = {"current_revenue": 199294.0, "baseline_payroll_year1": 143400.0,
       "other_opex_absolute": 17400.0, "marketing_total_year1": 600.0,
       "cogs_percent_of_revenue": 0.08}

# P1: a stated-fact CORRECTION changes the identity (re-judges).
st = {}
d1, _ = _compute_band_identity_digest(
    st, ops_json=OPS, people_json={}, market_json={},
    marketing_model_json={}, financials_json=FIN)
FIN_CORRECTED = dict(FIN, baseline_payroll_year1=163400.0)
d2, _ = _compute_band_identity_digest(
    st, ops_json=OPS, people_json={}, market_json={},
    marketing_model_json={}, financials_json=FIN_CORRECTED)
check("P1 a financials correction changes the band identity (was: digest "
      "excluded financials entirely)", d1 != d2)

# P2: the walk's OWN lever write does NOT change the identity (CW-020):
# the {from,to} substitution keeps the post-lever digest BYTE-IDENTICAL
# to the digest the band was authored under (d1).
st_lever = {"_lever_writes": {
    "current_revenue": {"from": 199294.0, "to": 250000.0}}}
FIN_LEVER = dict(FIN, current_revenue=250000.0)
d3, _ = _compute_band_identity_digest(
    st_lever, ops_json=OPS, people_json={}, market_json={},
    marketing_model_json={}, financials_json=FIN_LEVER)
check("P2 post-lever digest == authoring digest (CW-020: lever accept "
      "never re-keys)", d3 == d1)
# ...but a CLIENT correction to a different value re-enters the digest.
FIN_CLIENT = dict(FIN, current_revenue=300000.0)
d4, _ = _compute_band_identity_digest(
    st_lever, ops_json=OPS, people_json={}, market_json={},
    marketing_model_json={}, financials_json=FIN_CLIENT)
check("P3 a client correction PAST the lever value re-keys (re-judges)",
      d4 != d3 and d4 != d1)

# P3b: chained levers keep the EPOCH ORIGIN (a second accept moving the
# same field still digests to the authoring identity).
from client_intake_and_finmo.intake_coherence.section import _record_lever_write  # noqa: E402
_lw_chain = {"current_revenue": {"from": 199294.0, "to": 250000.0}}
_record_lever_write(_lw_chain, "current_revenue", 250000.0, 280000.0)
d5, _ = _compute_band_identity_digest(
    {"_lever_writes": _lw_chain}, ops_json=OPS, people_json={},
    market_json={}, marketing_model_json={},
    financials_json=dict(FIN, current_revenue=280000.0))
check("P3b chained lever preserves the epoch origin (still == authoring)",
      _lw_chain["current_revenue"]["from"] == 199294.0 and d5 == d1)

# P4: basis-tag awareness - dollars-basis drafts key on the dollar.
b_ratio = _financials_identity_basis({}, dict(FIN))
b_dollar = _financials_identity_basis(
    {}, dict(FIN, cogs_basis="dollars", current_cogs=5900.0))
check("P4 identity basis honors the cogs basis tag",
      "cogs_ratio" in b_ratio and "cogs_dollars" in b_dollar)

# P5: THE ROADMAP LATCH IS DEAD - an identity change clears the roadmap
# and the gate re-evaluates (falls through past the canned reply).
fin_rm = dict(FIN)
fin_rm["_coherence"] = {
    "status": "roadmap",
    "digest_hash": d1,  # authored at the OLD identity
    "roadmap": {"corner_gap_display": "$5,000", "milestones": []},
}
turn5, fin5, sfx5 = gate_and_turn(
    ops_json=copy.deepcopy(OPS), people_json={}, market_json={},
    marketing_model_json={}, financials_json=dict(FIN_CORRECTED, _coherence=dict(fin_rm["_coherence"])),
    financials_year1_json={})
_msg5 = str((turn5 or {}).get("assistant_message") or "") + str(sfx5 or "")
_st5 = (fin5.get("_coherence") or {})
# The latch is broken when (a) the canned hold is NOT replayed and
# (b) every artifact now standing was authored at the NEW identity
# (a fresh re-conclusion of roadmap is honest re-judgment, not a latch).
check("P5 roadmap latch cleared on identity change - gate re-evaluated "
      f"(status now {_st5.get('status')!r}, digest re-keyed)",
      "roadmap territory" not in _msg5 and _st5.get("digest_hash") != d1)

# P6: unchanged identity keeps the roadmap (no thrash) with the engage reply.
turn6, fin6, _s6 = gate_and_turn(
    ops_json=copy.deepcopy(OPS), people_json={}, market_json={},
    marketing_model_json={},
    financials_json=dict(FIN, _coherence={
        "status": "roadmap", "digest_hash": d1,
        "roadmap": {"corner_gap_display": "$5,000", "milestones": []}}),
    financials_year1_json={})
check("P6 unchanged identity keeps the roadmap hold (stable, no thrash)",
      "roadmap territory" in str((turn6 or {}).get("assistant_message") or "")
      and (fin6.get("_coherence") or {}).get("status") == "roadmap")

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
