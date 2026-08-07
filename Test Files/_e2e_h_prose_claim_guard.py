"""CW-016 (h) no-request prose false-claim - targeted RED/GREEN.

Live event (2nd occurrence): the client corrected the maintenance
agreement price $4,000 -> $4,300 (turn 121). The router emitted NO write
- receipt empty, nothing requested - but its prose claimed the update.
The old rule ("prose only speaks when nothing was asked", CW-012 (f))
let it through; the stored price stayed $4,000 and the client had to
ask three times.

This suite drives _prose_claims_unrequested_change with the LIVE prose
verbatim (claims must be caught) and the benign no-request proses that
must keep speaking (no false "couldn't apply" on ordinary turns).
"""
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")

from api_handlers.intake_consult import _prose_claims_unrequested_change  # noqa: E402

results = []


def check(label, prose, want):
    got = _prose_claims_unrequested_change(prose)
    ok = got == want
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + f"{label}: got {got}, want {want}")


# LIVE claims, verbatim - must be caught (True).
check("live t122 'updating the ... unit price to $4,300'",
      "Got it\u2014updating the maintenance agreement unit price to $4,300 "
      "just like you outlined.", True)
check("live t124 'I've now updated that ... unit price'",
      "Got it\u2014I've now updated that maintenance/tenant-improvement unit "
      "price to $4,300, which puts that side of the model at about "
      "$1,857,600 a year.", True)
check("live t128 'I'll update your monthly lease commitment to $0'",
      "Got it, I\u2019ll update your monthly lease commitment beyond main "
      "rent to $0 instead of the placeholder $1 you used to move past the "
      "repeating question.", True)
check("synthetic 'I'll use $12,000 for marketing'",
      "Got it. I\u2019ll use a marketing budget of $12,000 a year.", True)
check("synthetic 'switching that to monthly'",
      "Sure - switching that to a monthly basis now.", True)

# BENIGN no-request proses - must keep speaking (False).
check("benign 'all set' completion line",
      "You're all set - the intake is complete again and you can submit "
      "whenever you're ready.", False)
check("benign confirmation 'that's correct'",
      "Yes, that's correct - revenue stays at $11,097,600.", False)
check("benign 'that matches what I have on file'",
      "Got it - that matches what I already have on file.", False)
check("benign next-question prose",
      "No problem - let's keep going. About how much cash does the "
      "business have on hand right now?", False)
check("benign empty prose", "", False)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
