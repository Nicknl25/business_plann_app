"""CW-016 ask-turn "$0 (0%)" wart - targeted RED/GREEN.

Live turn 62: the ask-first machinery correctly reverted the marketing
family and raised the percent-vs-dollar clarifier, but the stage ack
rendered the reverted hole as a claim: "Got it. I'll use a marketing
budget of $0 a year (0% of revenue). Quick check on that figure: ..."

The ack must not claim a value when the pending clarifier is about the
stage's own family; unrelated stages and normal (no-pending) acks keep
their applied-value rendering.
"""
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")

from api_handlers.intake_consult import _build_financials_stage_acknowledgement  # noqa: E402

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


# 1. THE LIVE STATE: marketing family reverted (absent), pending stamped.
fin = {
    "current_revenue": 11_097_600.0,
    "_basis_clarify_pending": {
        "kind": "percent_vs_dollar",
        "field": "marketing_percent_of_revenue",
        "recorded": "dollars",
        "percent_reading_dollars": 1_331_712.0,
        "dollar_reading": 12_000.0,
    },
}
ack = _build_financials_stage_acknowledgement(stage_name="marketing", financials_json=fin)
check("ask-turn marketing ack claims no value", "$0" not in ack and "0%" not in ack)
check("ask-turn marketing ack is the neutral check line", "quick check" in ack.lower())

# 2. Pending on marketing must NOT mute an unrelated stage's ack.
fin2 = dict(fin, cogs_total_year1=8_434_176.0, cogs_percent_of_revenue=0.76)
ack2 = _build_financials_stage_acknowledgement(stage_name="cogs", financials_json=fin2)
check("unrelated stage still renders values", "$8,434,176" in ack2)

# 3. No pending: normal marketing ack unchanged.
fin3 = {
    "current_revenue": 11_097_600.0,
    "marketing_total_year1": 12_000.0,
    "marketing_percent_of_revenue": 12_000.0 / 11_097_600.0,
}
ack3 = _build_financials_stage_acknowledgement(stage_name="marketing", financials_json=fin3)
check("no-pending marketing ack renders the recorded value", "$12,000" in ack3)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
