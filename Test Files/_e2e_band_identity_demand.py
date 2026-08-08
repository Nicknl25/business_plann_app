"""CW-020: band identity excludes KNOB-DERIVED market-demand numerics.

The Oak City escape: a $1,300->$1,450 price repair recomputed the
marketing model (required_units_year1 = revenue/price etc.), the demand
numerics re-keyed the identity digest, and the band re-authored
{7%,14%} -> {8%,16%} mid-session - two submit_margin_band_judgment
calls in the GPT store. RED: demand-numeric change re-judges. GREEN:
knob-derived demand changes reuse the stamp; a GENUINE market-identity
change (basis summary) still re-judges.
"""
import copy
import sys
import types

sys.path.insert(0, "C:/dev/business_plann_app/python")

from dotenv import load_dotenv

load_dotenv()

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


_calls = {"n": 0}
_stub = types.ModuleType("client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment")
def _stub_author(**kwargs):
    _calls["n"] += 1
    return {"ok": True, "judgment": {
        "q11_ebitda_band": {"low": 0.07, "high": 0.14},
        "q20_ebitda_band": {"low": 0.08, "high": 0.15},
    }}
def _stub_validate(*args, **kwargs):
    return dict(kwargs.get("judgment") or (args[0] if args else {}))
def _stub_from_mi(mi):
    return None
_stub.gpt_author_margin_band_once = _stub_author
_stub.validate_margin_band_judgment = _stub_validate
_stub.margin_band_from_model_input = _stub_from_mi
_real = sys.modules.get("client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment")
sys.modules["client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment"] = _stub
try:
    from client_intake_and_finmo.intake_coherence.section import _ensure_margin_band

    OPS = {"business_type": "facility services", "lob_models": [{"lob_name": "Facilities", "products": [{
        "product_name": "On-call repair & service jobs", "unit_price": 1300,
        "units_per_period_capacity": 1400, "operating_periods_per_year": 1,
        "utilization_rate": 0.8,
    }]}]}
    # The Oak City marketing model shape: derived demand numerics present.
    MKT_A = {"reachable_market": 2400, "required_units_year1": 5240,
             "expected_units_year1": 5100, "capture_rate_year1": 0.31,
             "required_revenue_year1": 6_812_000,
             "marketing_basis_summary": "Commercial property managers in the Raleigh metro",
             "geography_basis": "Raleigh-Durham"}

    def _gate(ops, mkt, state):
        return _ensure_margin_band(
            dict(state), ops_json=ops, people_json={}, market_json={},
            marketing_model_json=mkt, financials_json={"current_revenue": 6_812_000},
            financials_year1_json={})

    st = _gate(OPS, MKT_A, {})
    first = _calls["n"]
    check("band authored once at gate", first == 1)

    # The escape shape: price repair + marketing model recompute changes
    # ONLY knob-derived demand numerics.
    OPS_B = copy.deepcopy(OPS)
    OPS_B["lob_models"][0]["products"][0]["unit_price"] = 1450
    MKT_B = dict(MKT_A)
    MKT_B.update({"required_units_year1": 4698, "expected_units_year1": 4560,
                  "capture_rate_year1": 0.28, "required_revenue_year1": 6_812_000})
    st2 = _gate(OPS_B, MKT_B, st)
    check("price repair + demand recompute does NOT re-judge (stamp reused)",
          _calls["n"] == first)
    check("stamp survives", st2.get("margin_band_judgment") is not None)

    # NEG: a genuine market-identity change re-judges.
    MKT_C = dict(MKT_B)
    MKT_C["marketing_basis_summary"] = "Statewide industrial plants and hospital systems"
    _gate(OPS_B, MKT_C, st2)
    check("NEG genuine market-identity change re-judges", _calls["n"] == first + 1)
finally:
    if _real is not None:
        sys.modules["client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment"] = _real
    else:
        sys.modules.pop("client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment", None)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
