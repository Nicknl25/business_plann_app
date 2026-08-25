STATUS: awaiting-mini

TURN: 2/16

TASK:
  Audit the CW-043 frozen-capital-lease fix with your own instruments - I built it, I found the defect late (Nick found it first, in the delivered file), so nothing I report about it counts until you re-measure it. Commits: 0b26ce8 (the fix) and 022542b (R32/R49 re-bless), on top of ef2d6e7 + e4fb9a4 (yesterday's CW-041 capture + instrumentation, which you have also never audited - the fix commit exists because ef2d6e7 split the lease seed from the lease amortizer). CLAIMS TO VERIFY, each independently: (1) finmo_bridge "Less: Principal Repayments" now authors capital_lease_balance/20 per live quarter and the legacy initial_lease x12/20 path still works - tests/test_cw043_lease_amortizer.py red-proofs it on the captured Halbrook fixture; check the test would catch a subtler break than the one it pins (a partial author, a wrong divisor). (2) The Debt Schedule pastes NO literal outside the amber inputs (new borrowing, rates, terms, extra principal, lease additions) and its build-time guard actually kills a literal - tamper-test it. (3) My byte-identical claim: stored Halbrook payloads through the new sheet code == the delivered 17-57-48 file on every sheet, debt block identical under the fix; my harness is scratchpad cw043_before_after.py + cw043_compare.py - re-derive, do not trust my diff. (4) The scheduled/extra split: extra = engine repay - (opening+new)/remaining-term mirrored in python; check the float claim (Excel-vs-python same IEEE ops) holds on the recalculated file rather than by argument. (5) R32/R49 re-bless at 0b26ce8 is the one-place flow and the digests match what the gate computes. (6) I07 ack-matches-stored is RED and quarantined; I measured its stage-setup rot as PRE-EXISTING (same 'marketing' stage resolution at ef2d6e7~1 and now) and therefore out of the debt/lease scope - verify that measurement, and if it is wrong, that is a finding against me. Deal-breaker rule stands: a wrong number in a delivered plan on the guided path outranks everything else.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: none yet
  SUMMARY: Task seeded by VS after the CW-043 fix; watcher re-armed this turn.
