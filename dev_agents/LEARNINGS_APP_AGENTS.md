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
- the helper should avoid turning one business result into a universal rule

Cutover note:

- pre-app-agents learnings are obsolete
- do not carry forward conclusions that were specific to deleted legacy planner code
- only append learnings from the new app-agent planner architecture onward
