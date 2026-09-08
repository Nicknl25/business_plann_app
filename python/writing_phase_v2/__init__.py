"""WRITING PHASE v2 (2026-09-08) - one-call plan writing for every business.

The five stages of the Build Instruction, in build order:
    [1] ASSEMBLER  bundle.py    record+judgments+model+derived+warehouse -> bundle
    [2] WRITER     runners      standing brief + bundle -> plan.json (model-agnostic)
    [3] CHECKER    checker      every number resolves; the gates
    [4] EDITOR     editor       whole draft + findings -> corrected draft, once
    [5] RENDERER   renderer     prose from the plan, figures from the bundle

Standing rules (directive 2026-09-08, non-negotiable): no fact keys, floors
or per-section prompts; the writer never sees QA material or our machinery;
notes are external sources only; the brief is never edited to pass a finding.

The acceptance gate for the assembler: it reproduces the hand-built
Thornfield reference (bundle_thornfield_v2.json) in shape and content.
"""
