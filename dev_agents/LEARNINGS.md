# Persistent Learnings

This file is automatically updated by the dev-agent helper after sessions complete.

It captures lessons the agents should carry forward so they do not restart from zero every run.

Every learning uses this structure:

## Learning YYYY-MM-DD HH:MM

- issue:
- fix_attempted:
- result:
- verdict: good | bad | mixed
- learning_confidence: low | medium | high
- scope: general | case-specific | unknown
- notes:

Rules:

- prefer general principle over case-specific workaround
- do not promote a single-run result into a general truth without strong evidence
- architecture conclusions require high confidence and clear justification
- if a fix worked only for one scenario, mark scope as `case-specific` or `unknown`
- the helper should default to conservative confidence when evidence is thin
- the helper should avoid turning one med-spa result into a universal rule

Recent learnings will be appended below automatically.

## Learning 20260409-102751

- issue: no_cash_band_violation_detected / none
- fix_attempted: Strengthen prompt payload anti-baseline-authority language to reduce baseline Q2-Q20 flatness and leakage in grid AI planning.
- result: Run succeeded; cash shape=staircase; shape_change=staircase; decision=continue
- verdict: mixed
- learning_confidence: low
- scope: unknown
- notes: Solver success still produced a staircase cash shape. Applied fixes: Strengthen prompt payload anti-baseline-authority language to reduce baseline Q2-Q20 flatness and leakage in grid AI planning. Final reasons: Solver succeeded, but cash shape is still a generic staircase; continue iterating on visible strategy expression.
