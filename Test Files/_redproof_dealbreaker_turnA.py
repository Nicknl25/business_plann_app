"""DEAL-BREAKER BATCH, TURN A (2026-08-15) - offline red->green proof for
the three SPOT-CHECK fixes A1 / A2 / A4. Each block names its production
call chain (the E2E law: name the chain first) and the wrong number or
false claim it prevents.

  A1  price/utilization branches of _apply_cross_section_driver_correction
      CHAIN: POST /api/intake-consult (focus=market|people|financials)
        -> _apply_cross_section_driver_correction -> ops row write.
      WRONG NUMBER: 'price should be 650, I was thinking of 520 before'
      wrote 520 (cands[-1], the discarded figure) as unit_price.
  A2  #134 payment-term guard in the forward mover's figure selection
      CHAIN: /api/intake-consult financials turn -> _unlanded_figures_disclosure
        (small-figure attribution) -> _apply_forward_move -> ops row write.
      WRONG NUMBER: 'Clients owe us ... invoices go out net 45' landed
      capacity 45 over the client's confirmed 80 (Fernhill 073a90af t52).
  A4  #122 invented price tier in the market positioning copy
      CHAIN: market finalize -> target_market_finalize (GPT, prompt invites
        a value/mid-market/premium tier) -> render -> marketing_plan_summary
        persisted -> plan positioning paragraph.
      FALSE CLAIM: 'a mid-market price point ($85 per office cleaning
      visit)' on a below-market price (Brightline 3de095cb).

RED PROTOCOL: run at the pre-fix tree (git stash) - A1/A2/A4 red; run at the
fixed tree - all green. Both outputs are the turn's artifact.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_dealbreaker_turnA.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers import intake_consult as ic  # noqa: E402
from client_intake_and_finmo import target_market_consultant as tmc  # noqa: E402

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def one_row_ops(price=500.0, util=0.62, cap=80.0) -> dict:
    return {"lob_models": [{"lob_name": "Consulting", "products": [
        {"product_name": "Consulting engagement", "unit_price": price,
         "units_per_period_capacity": cap, "utilization_rate": util,
         "operating_periods_per_year": 12, "unit_cadence": "monthly"}]}]}


def row(ops: dict) -> dict:
    return ops["lob_models"][0]["products"][0]


# --------------------------------------------------------------- A1
print("A1 - price/utilization corrections: the MARKED figure lands, never "
      "the discarded one; ambiguity refuses")
cases = [
    ("price: should-be + old", "Fix the price - it should be 650, I was thinking of 520 before.",
     "unit_price", 650.0),
    ("price: 'not' old value", "Set the price to 700, not 650.", "unit_price", 700.0),
    ("price: old first, new marked", "I said 520 earlier but the price is now 650.",
     "unit_price", 650.0),
    ("utilization: should-be + old", "Correct that: utilization should be 75%, I said 60% earlier.",
     "utilization_rate", 0.75),
    ("utilization: 'not' old value", "Fix utilization to 80%, not 55%.",
     "utilization_rate", 0.80),
]
for name, msg, leaf, want in cases:
    rep: dict = {}
    res = ic._apply_cross_section_driver_correction(
        ops_json=one_row_ops(), user_message=msg, report=rep)
    if res is None:
        check(f"{name} lands", False, f"None, report={rep}")
        continue
    got = row(res[0]).get(leaf)
    check(f"{name} -> {leaf}={want}", abs(float(got) - want) < 1e-9,
          f"stored {got}; ack={res[1][:80]!r}")

rep_amb: dict = {}
res_amb = ic._apply_cross_section_driver_correction(
    ops_json=one_row_ops(),
    user_message="Fix the price - it was 520 and 610 and 700 in different quotes.",
    report=rep_amb)
check("price: several unmarked candidates REFUSE (no write)", res_amb is None,
      f"{res_amb and row(res_amb[0]).get('unit_price')}")
rep_mix: dict = {}
res_mix = ic._apply_cross_section_driver_correction(
    ops_json=one_row_ops(),
    user_message="Rent is 2,200 and marketing was 4,000 last year. Also, fix "
                 "the price - it should be 650.",
    report=rep_mix)
check("price: sentence-scoped - other sentences' figures never compete",
      res_mix is not None and abs(float(row(res_mix[0])["unit_price"]) - 650.0) < 1e-9,
      f"{res_mix and row(res_mix[0]).get('unit_price')}")

# --------------------------------------------------------------- A2
print("\nA2 - #134: a net-N payment term is never a capacity/price/count "
      "candidate (real Fernhill sentence, at the wall)")
FERNHILL = ("Cash is about $186,000. Clients owe us around $215,000 - consulting "
            "invoices go out net 45 and manufacturers are slow. We owe about "
            "$22,000 to subcontractors and vendors. No inventory at all, we "
            "don't hold anything.")
fin = {"cash_on_hand": 186000.0, "ar_balance": 215000.0, "ap_balance": 22000.0}
shared = {"operating_model": one_row_ops(price=2400.0, cap=80.0), "people_capability": {}}
_f, _txt, move = ic._unlanded_figures_disclosure(
    next_financials=dict(fin), stage_shared_context=shared, user_message=FERNHILL,
    landed_patch=dict(fin), prior_sections=None, last_assistant="")
check("Fernhill 'net 45' proposes NO ops move", move is None, f"move={move}")
for variant in ("Our terms are net 45.", "Customers pay net-30 mostly.",
                "Clients are on net 60 days; a few pay net 30."):
    _f2, _t2, mv2 = ic._unlanded_figures_disclosure(
        next_financials={}, stage_shared_context=shared, user_message=variant,
        landed_patch=None, prior_sections=None, last_assistant="")
    check(f"{variant!r} -> no move", mv2 is None, f"move={mv2}")
_f3, _t3, mv3 = ic._unlanded_figures_disclosure(
    next_financials={}, stage_shared_context=shared,
    user_message="We can take on 40 clients a month now.",
    landed_patch=None, prior_sections=None, last_assistant="")
check("control: a real client-count capacity statement still moves (40)",
      bool(mv3) and mv3.get("key") == "ops.units_per_period_capacity"
      and float(mv3.get("value")) == 40.0, f"move={mv3}")

# --------------------------------------------------------------- A4
print("\nA4 - #122: an undeclared price-tier claim never reaches the "
      "positioning copy")
BRIGHT = ("The business model is a straightforward recurring service where clients "
          "pay per office cleaning visit on a weekly cadence and are invoiced monthly "
          "at a mid-market price point ({{fact:ops.unit_price}} per "
          "{{fact:ops.unit_name}}), with labor in the evening window as the primary "
          "capacity driver.")
scrub = getattr(tmc, "_strip_undeclared_price_tier", None)
check("scrub exists on target_market_consultant", callable(scrub))
if callable(scrub):
    out = scrub(BRIGHT, client_messages=["We charge $85 a visit.", "Weekly, invoiced monthly."])
    check("'mid-market price point' -> tier dropped, price kept",
          "mid-market" not in out.lower() and "{{fact:ops.unit_price}}" in out, out[:160])
    out2 = scrub("Positioned as a premium-priced boutique at {{fact:ops.unit_price}}.",
                 client_messages=["We are the cheap option honestly."])
    check("'premium-priced' undeclared -> dropped", "premium" not in out2.lower(), out2)
    out3 = scrub(BRIGHT, client_messages=["We sit mid-market on price, about $85."])
    check("client DECLARED mid-market -> claim kept", "mid-market" in out3.lower(), out3[:120])
    out4 = scrub("Premium Office Care serves offices at {{fact:ops.unit_price}}.",
                 client_messages=[])
    check("a business NAME containing Premium is untouched",
          out4.startswith("Premium Office Care"), out4)
src = Path(tmc.__file__).read_text(encoding="utf-8")
check("finalize prompt no longer invites a value/mid-market/premium tier",
      "describe the tier (value/mid-market/premium)" not in src)

print("\n" + ("ALL GREEN" if not FAILURES else f"RED: {len(FAILURES)} failing -> {FAILURES}"))
sys.exit(1 if FAILURES else 0)
