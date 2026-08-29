import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.32 K1 F7 - F5 NOW PASSES RICH PAYROLL VIOLATIONS TO HANDLER C

Commit: 794bf5d phase_9_p3_32_k1_f7_pre_cash_gate_rich_payroll_violations_to_handler_c
HEAD:   pushed to origin/intake-stable

ROOT CAUSE FOUND (during Skyward H4 investigation)
F5 implementation was putting violations under WRONG key with
WRONG values. Handler C compactor at schedule.py:514 reads from
the canonical "violations" key — but F5 was putting under
"payroll_touching_violations_sample" with TRANSLATED metrics
(actual_value=0.0, bounds=null due to the orchestrator translator
reading wrong keys for payroll violations).

Handler C iterated BLIND through 2-3 rounds before 180s budget
exhausted. That is why Skyward timed out.

CareFirst passed despite this bug because simpler problem space
let GPT converge by random exploration. Skyward complexity
exposed it.

F7 FIX
F5 now calls payroll_revenue_feasibility_violations() directly
to compute fresh rich violations, puts them under canonical
"violations" key. Handler C compactor finds them, extracts the
rich fields (payroll_percent_of_revenue, effective bounds,
deterministic_driver_math with precise repair direction), feeds
to GPT.

DOCTRINE THREE-SURFACE CHECK
Q1. Surfaces: payroll feasibility violations from canonical
    helper; Handler C compactor consumes them.
Q2. Alignment: compactor interface contract.
Q3. Preserved: F7 uses the canonical helper + canonical key.
    Mirror Flavor 1 input data (post K1 F6 re-sync) ensures
    violations are computed from coherent state.

EMPIRICAL VALIDATION (PARTIAL) - SKYWARD POST-F7
- Handler C used all 10 rounds (was timing out at 180s/2-3 rounds)
- Failed at round 10 with payroll_iterative_refinement_exhausted
- GPT chose labor_intensity_class=high (requires 16-70% payroll/
  revenue), produced target_payroll_percent_of_revenue=0.105 (10.5%)
- GPT rationale claimed "moved from 11% to 20%" but structured
  field carries 0.105 - classic H2 (P3.23a) rationale-vs-
  structured drift

This surfaces a NEW issue K8: Handler C lacks class-switching
feedback. When validator rejects value-X-for-class-C, GPT should
be told which alternative classes would accept X (e.g., "value
0.105 falls in 'medium' class bounds 0.05-0.4 - switch
labor_intensity_class").

K8 is a separate follow-up. F7 is independently valuable: it
unblocks Handler C from iterating blind, surfaces the real
remaining issues, and works correctly on businesses that converge
within the bounds GPT chooses.

SCOPE
  LOC: ~85 total (~40 production / ~45 tests)
  Files: orchestrator.py + new test_phase_9_p3_32_k1_f7_*.py

TESTS PASSING
  Pre-F7:  424/427 (3 pre-existing failures)
  Post-F7: 434/437 (same 3 pre-existing; +10 new F7 tests)
  Net delta: ZERO new failures.

NEXT
  - Investigate K8: extend Handler C failure feedback to suggest
    alternative labor_intensity_class options that would accept
    GPT's implied value.
  - Re-run Skyward with K8 in place.
  - Continue sweep with K8 in place (benefits all drafts that
    hit Handler C class-mismatch).
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = "[P3.32 K1 F7] Pre-cash gate rich payroll violations - Skyward now uses 10 rounds (was timing out)"
msg["From"] = sender
msg["To"] = to

ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent.")
