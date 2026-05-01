# Golden Rule to Live By

This file is a hard invariant for post-intake work.

When working on post-intake, treat this as the architecture rule that everything else must obey.

## The Architecture Goal

Python owns deterministic structure through lookup tables.

GPT owns judgment and decisions inside those table-backed contracts.

FINMO calculates only from model inputs.

So anything predictable should not live as scattered code or prompt prose. It should live in lookup tables and be accessed through lookup functions.

This includes:

- mapping
- process sequence
- contracts
- context payloads
- numeric format rules
- cash policy
- headcount policy
- issue ownership
- driver bundles
- horizons
- any repeatable validation or normalization rules

The deeper goal is consistency: there should be one source of truth for each deterministic concept.

If code conflicts with the tables, the code is legacy and should be converted or deleted.

If a table is missing metadata needed to make behavior deterministic, add columns or rows to the table instead of hardcoding around it.

`intake_consult.py` should be intake/API orchestration only.

Post-intake behavior belongs in post-intake folders with functions that route through the lookup tables wherever appropriate.

## Working Rule

If something is consistent, structural, repeatable, or contract-like, it belongs in a lookup table or a table-backed function.

If something requires business judgment, GPT decides it, but only inside a table-defined schema, context, and contract.

## Distinct Jobs

The controller runs the play.

The controller's job is orchestration:

- run the correct post-intake sequence
- call the correct phase modules
- enforce process order, cycle limits, time limits, and progress checks
- persist state and diagnostics
- route failures to the correct fail-fast path

The controller must not invent values, choose mappings, repair financial logic, or act as a hidden decision-maker.

Python draws the field and enforces the rules.

Python's job is deterministic structure:

- read lookup tables
- build prompts, schemas, context packets, contracts, and sequence rules from lookup tables
- validate GPT payloads against table-backed contracts
- normalize only where the contract explicitly allows lossless formatting normalization
- compute deterministic derived drivers
- apply accepted GPT decisions to `model_input_json`
- run FINMO
- detect issues using table-backed issue/driver/target definitions
- fail fast when required metadata is missing or a contract is incomplete

Python must not complete, infer, broaden, proxy, top up, rewrite, or silently repair GPT-owned decision content.

GPT makes the business decisions inside the marked lanes.

GPT's job is judgment:

- choose realistic values inside Python/table-defined bounds
- decide ramp shape, headcount shape, R&D applicability, maintenance capex percentage, and repair values when asked by a contract
- reason about business type, stage, planning mode, and strategy
- fill the exact table-backed contract it is given

GPT must not define structure, invent fields, choose unsupported targets, bypass lookup tables, or freeform outside the contract.

FINMO calculates the scoreboard from model inputs.

FINMO's job is calculation only:

- consume model-input drivers
- calculate financial outputs
- preserve the 3-statement model relationship

FINMO should not receive patched output rows from post-intake. Post-intake changes drivers; FINMO calculates outputs.

## Current Reality Check

We are past concept and the structural architecture is now close to fully manifested.

Infrastructure is mostly there:

- tables exist
- lookup functions exist
- post-intake has been split out of `intake_consult.py`
- cash, headcount, contracts, context, mapping, prompts, issue detection, and sequence are moving through table-backed structure

Enforcement now exists, but operational proof is still incomplete:

- Golden Rule checks validate table availability and alignment
- retired issue-code literals are guarded against
- issue detector sets are checked against SQL issue mappings
- cash issue emission is gated through SQL-owned cash-pass issue codes
- prompt/schema/context generation is table-backed for post-intake GPT contracts

Stability proof is not fully there yet:

- we have not run enough clean E2Es after the latest separation to say the app consistently obeys the table-first architecture

Current estimate:

- structurally: near 100 percent for the intended table-backed skeleton
- operationally proven: still not fully proven until repeated E2Es pass after the latest cleanup

## Remaining Work

The remaining work is not to invent the architecture. The architecture is clear.

The remaining work is enforcement:

- audit every post-intake phase and confirm it gets sequence, context, contract, mapping, cash, and headcount rules through lookup functions
- delete or convert anything that still defines those rules locally
- make fail-fast errors prove when a table is missing required metadata
- run E2Es and fix only root causes where legacy code conflicts with the table system

The big win is that we now know what correct means.

The next step is to make it impossible for post-intake to operate outside the lookup-table structure.

## Enforcement Added

The app now has structural Golden Rule enforcement in `python/client_intake_and_finmo/post_intake_foundation/`.

The enforcement layer validates these lookup authorities before post-intake starts and before convergence runs:

- `post_intak_mapping_lookup`
- `post_intake_cash_policy_lookup`
- `post_intake_gpt_contract_lookup`
- `post_intake_gpt_context_lookup`
- `post_intake_headcount_policy_lookup`
- `post_intake_process_sequence_lookup`

Runtime dependency binding from `intake_consult.py` is intentionally table-safe. Post-intake modules may receive shared helper functions from the API handler, but uppercase deterministic authority values such as horizons, mapping constants, prompt paths, cash levers, and contract constants are not allowed to overwrite post-intake module/table authority.

The structural guard fails fast if:

- required lookup rows are missing
- required contracts or prompt-context rows are missing
- forecast horizons do not resolve to the contract-backed Q1-Q20 horizon
- process sequence steps do not declare required lookup tables and horizon rules
- issue codes are not backed by mapping-table levers/targets where required
- post-intake prompt files do not reference SQL table authority
- `intake_consult.py` reintroduces forbidden post-intake authority constants

This does not prove operational E2E stability by itself. It proves the structure now has a fail-fast wall around the table-first architecture so later E2E failures should expose real remaining code paths or data gaps instead of silently bypassing the lookup tables.

## Table-Rendered Prompt Concept

Prompts should become a rendering of table data, not another source of truth.

The practical rule is:

- contracts define fields, types, required status, normalization, allowed aliases, horizon rules, lookup sources, and validation rules
- context lookup defines which runtime facts are allowed into the prompt
- prompt text should render those contract/context rows into a readable instruction block
- static prompt prose should stay minimal and only describe the thinking task

That means prompt structure should be:

- static role/task instruction
- generated contract spec from `post_intake_gpt_contract_lookup`
- generated context spec from `post_intake_gpt_context_lookup`
- small task instruction that says to produce a valid payload and not add or omit fields

GPT still decides values, tradeoffs, and realistic shape inside the contract.

Tables control structure, allowed fields, formats, horizons, and validation.

This prevents drift:

- prompt says X
- schema expects X
- validator checks X
- normalizer applies X

All of those should come from the same table-backed contract path wherever possible.

Do not over-automate natural-language reasoning. The goal is not to generate every sentence from SQL. The goal is to generate deterministic contract/context structure from SQL, while keeping business judgment instructions concise and static.
