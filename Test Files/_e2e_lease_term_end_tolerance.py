"""CW-016 capital-lease term-end tolerance - targeted E2E.

Reproduces the EXACT Ironbridge build failure (run 58f9eef5): the $1/mo
placeholder lease annualizes to a $12 seed; the bridge authors quarterly
principal = 12/20 = 0.6 (float); snapshot rows int-round it to $1; the
validator's mirror retires the obligation at Q12 (12 - 12x$1) while
FINMO's float closing is 12 - 12x0.6 = 4.8 -> rounds to 5 > flat
tolerance 1 -> lease_obligation_zero_at_term_end -> plan dead over $5.

Rows here are built with the SAME arithmetic the production snapshot
uses: FINMO float chain, every field int(round()) - the production data
shape at the validator boundary. Seed arrives via model_input_json
sections.schedules.lease_opening_balance_seed, same as production.

RED (pre-fix): case 1 emits the violation. GREEN (post-fix): case 1
passes; genuinely un-closed schedules (residue just above the derived
bound, and a $5,000 residue) STILL fail.
"""
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")

from client_intake_and_finmo.post_intake_capital_lease.schedule import (  # noqa: E402
    validate_capital_lease_schedule_payload,
)


def snapshot_rows(seed_f, quarterly_f, horizon=20, leak_per_quarter=0.0):
    """FINMO float chain -> int-rounded rows, exactly as the production
    snapshot reads them. leak_per_quarter injects a GENUINE un-closed
    chain (closing retains balance the principal stream never pays) -
    the defect class check #9 exists to catch."""
    rows = []
    obligation = seed_f
    dep = seed_f / 20.0
    rou = seed_f
    for q in range(1, horizon + 1):
        opening = obligation
        principal = min(quarterly_f, max(0.0, opening))
        closing = max(0.0, opening - principal + leak_per_quarter)
        rows.append({
            "quarter_index": q,
            "opening_balance": int(round(opening)),
            "principal_payment": int(round(principal)),
            "interest_payment": 0,
            "closing_balance": int(round(closing)),
            "rou_asset_opening": int(round(rou)),
            "lease_asset_depreciation": int(round(min(dep, max(0.0, rou)))),
            "rou_asset_closing": int(round(max(0.0, rou - dep))),
            "interest_rate": 0.0,
        })
        obligation = closing
        rou = max(0.0, rou - dep)
    return rows


def run_case(label, seed_f, quarterly_f, leak_per_quarter=0.0, expect_term_end_violation=False):
    payload = {
        "opening_balance_seed": int(round(seed_f)),
        "interest_rate": 0.0,
        "rows": snapshot_rows(seed_f, quarterly_f, leak_per_quarter=leak_per_quarter),
    }
    model_input = {"sections": {"schedules": {
        "lease_opening_balance_seed": seed_f}}}
    violations = validate_capital_lease_schedule_payload(
        capital_lease_schedule=payload, model_input_json=model_input)
    term_end = [v for v in violations if v.get("reason") == "lease_obligation_zero_at_term_end"]
    ok = bool(term_end) == expect_term_end_violation
    detail = f" term_end={term_end}" if term_end else ""
    print(("PASS " if ok else "FAIL ") + label + detail)
    return ok


results = []
# 1. THE IRONBRIDGE FAILURE, exact: seed $12, quarterly $0.60.
#    Mirror retires at Q12, float closing 4.8 -> row 5. Rounding, not a
#    real residue - must NOT fail the plan.
results.append(run_case("Ironbridge $12 seed / $0.60 quarterly (residue 5 @ Q12)",
                        12.0, 0.6, expect_term_end_violation=False))
# 2. Same shape at another scale: seed $250, quarterly 12.5 -> rows $12
#    (half-even) -> mirror retires early vs float chain. Rounding class.
results.append(run_case("$250 seed / 12.5 quarterly rounding drift",
                        250.0, 12.5, expect_term_end_violation=False))
# 3. NEGATIVE: a chain leaking $1/quarter - principals retire the seed
#    but $20 of balance remains at Q20, above the derived bound of 11.
results.append(run_case("NEG chain leaking $1/q ($20 residue) still fails",
                        12000.0, 600.0, leak_per_quarter=1.0,
                        expect_term_end_violation=True))
# 4. NEGATIVE: the classic real defect - $250/q leak leaves $5,000
#    genuinely unpaid at term end.
results.append(run_case("NEG un-closed by $5,000 still fails",
                        100000.0, 5000.0, leak_per_quarter=250.0,
                        expect_term_end_violation=True))

print()
fails = len([r for r in results if not r])
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
