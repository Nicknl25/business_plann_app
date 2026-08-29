import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.32 K1 F1+F2 FIX COMMIT - LEAK A CLOSED

Commit: 21a48aa phase_9_p3_32_k1_f1_f2_close_leak_a_payroll_exhaustion_handler
HEAD:   pushed to origin/intake-stable

WHICH DRAFT SURFACED THIS:
  - P3.25 CareFirst Home Health Services: $36K/quarter Payroll
    divergence -> $677K Cash Q20 (documented since P3.25).
  - P3.32 V-4 verifier (just committed in d6d0caa) surfaced a
    LATENT FALSE_PASS: Caring Hands Home Health Services
    (workbook 4207488106054d72afbe16480e1de100.xlsx):
    Payroll Q20 = $2,809 off, Net Income Q20 = $2,141 off,
    Cash Q20 = $44,929 off. P3.28 had scored this 16/16
    GENUINE_PASS via runner-returncode + score inference;
    V-4 recalc surfaced the divergence instantly.

K PATTERN: K1 (Leak A — payroll catalog leak in exhaustion handler).
  Fix shape per P3.31 §5: F1+F2 first (~40 LOC, single commit).
  This commit is F1+F2.

DOCTRINE 3-SURFACE CHECK:
  Q1. What surfaces hold the conceptual data?
      payroll_headcount.{rows,quarter_totals,assumptions}
        — canonical authored by Handler C
      model_input.expenses["Payroll"].values
        — DERIVED via Handler C apply chain (controller_write=
          False, derived_driver=payroll_headcount tags)
      finmo.pl["Payroll"] / finmo.quarter_rows.payroll
        — DERIVED via build_python_finmo_json from model_input
  Q2. How are they kept aligned?
      Handler C as single writer + the apply chain enforcing
      Mirror Flavor 1 alignment via
      assert_payroll_headcount_model_input_applied +
      assert_finmo_payroll_matches_headcount_schedule
      (zero tolerance).
  Q3. Does this fix preserve alignment?
      YES. Removing the exhaustion handler's Payroll authority
      means all writes go through Handler C. No surface can
      drift because no path bypasses the canonical writer.

SCOPE:
  LOC:            ~95 total
                  (~30 production / ~65 tests)
  Files touched:  6 production + 1 new test + 1 test update
    handler.py            -- catalog + driver key map + writer
    tool_calling_session  -- PNL schema removes payroll field
    restoration_loop      -- mirror set
    prompts.py            -- system + extension language
    mini_finmo.py         -- docstring
    test_phase_9_p3_26_commit2.py  -- R-6 doctrine evolution
    test_phase_9_p3_32_k1_payroll_authority_closure.py  -- new

LATITUDES INVOKED:
  L-3 (doctrine evolution): P3.26 R-6 invariant explicitly
       evolved. Old text: "exhaustion handler lever set NOT
       modified by this commit." New text: "Payroll IS now
       removed; Handler C is canonical writer." Test updated
       to assert NEW set with diagnostic.

TESTS PASSING:
  Pre-K1 baseline:  384/387 pass
                    (3 pre-existing failures in
                    test_financial_model_engine_* —
                    test_lease_balance_is_floored_at_zero,
                    test_ppe_is_derived_from_opening_balance_
                    capex_and_depreciation,
                    test_model_input_json_round_trips_all_
                    controller_write_sections; unrelated to
                    P3.32)
  Post-K1:          394/397 pass
                    (same 3 pre-existing failures, +10 new
                    K1 regression guard tests passing)
  Net delta:        ZERO new failures from K1.

NEXT STEPS PER DIRECTIVE:
  - K1 F3+F4 (separate commit): add expenses::Payroll to
    target-solver _CASH_PASS_OWNED_LEVER_IDS analog
    (~50 LOC). Closes Leak B (restoration target-solver
    bypassing Handler C via realism row primary_levers).
  - Re-run V-4 against the affected workbooks (CareFirst,
    Caring Hands) once F1-F4 land + re-runs happen.
  - Begin draft 1 sweep (Anderson & Blake — cash_buffer K3
    pattern; will require designing the K3 cash buffer
    repair handler under L-1).
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = "[P3.32 K1 F1+F2] Leak A closed - exhaustion handler payroll authority removed"
msg["From"] = sender
msg["To"] = to

ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent.")
