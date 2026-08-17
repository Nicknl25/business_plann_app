# Does the discovery-answer reader use the app's shared comprehension? — RESEARCH (Nick, 2026-08-17)

Status: research for Nick's ruling. NOTHING BUILT. Draft e3af1f24 (Corvid
Press and Litho) is the evidence; every claim below is cited to code and
to the persisted transcript/latch.

## Verdict: NO — it is a special-cased reader, and the constraint is structural, not the prompt

The discovery answer is not comprehended by the intake's shared intent
machinery. It is REDUCED to N independent boolean existence questions
(one GPT call per proposed candidate) against a fixed proposition —
`RESTATEMENT TO CHECK: "<label>" is part of the client's business today`
— through the generic three-valued door `_classify_restatement_response`,
whose return is hard-filtered to `ACCEPT | REJECT | CLARIFY`. Corvid's
sentence "Digital printing is already part of our commercial print line
… not a separate thing" is TRUE under that proposition, so ACCEPT was
the correct verdict for the question actually asked — **the question is
the defect, not the model's reading**. The applier then did the only
thing it can do: mint a brand-new top-level LOB with null drivers. The
next turn's explicit "drop that line" had no door to enter, and the
carry-forward re-attached the row from `answer == "yes"` alone.

## Q1 — The path (client reply → recorded answer → append)
- Pending detection: `intake_consult.py:17070-17073`
  (`_sdisc.stream_discovery_pending(ops_json)`, `gpt_stream_discovery.py:853-860`).
- Applier `_apply_stream_discovery_answer` `intake_consult.py:11773` (called `:17075`);
  guards `:11790-11798` (latch asked; something pending; the ask/clarify
  was literally the last assistant message); door =
  `_classify_restatement_response` `:11805`.
- Reader `read_stream_discovery_answer` `gpt_stream_discovery.py:652-680`:
  `for lab in labs: classify(restatement=stream_discovery_intent_frame(ask_text, labs, lab), user_reply=text)`
  (`:671-678`); `_DOOR_TO_ANSWER = {ACCEPT: yes, REJECT: no, CLARIFY: unclear}` (`:649`).
- Record `intake_consult.py:11814-11829`; append `:11830-11840` →
  `append_confirmed_stream_rows` `gpt_stream_discovery.py:725-756`
  ("a confirmed discovered stream ALWAYS gets its OWN LOB", `:695-703`,
  `:754`; row `new_discovered_row` `:705-718`, all drivers None,
  `origin=discovery_confirmed`); receipt constant `:752/:755`
  ("Noted - <label> is its own line; a few quick numbers for it next.").
- Persist `:17082-17095`; `discovery_intent_override` → `continue_chat`
  `:17121/:17679-17683`; receipt prepended `:20331-20334`, `:20733-20743`.

## Q2 — HOW the reply is comprehended
- Door: `_classify_restatement_response(*, restatement, user_reply)`
  `intake_consult.py:11965`. System prompt `:11973-11983`: "Return
  exactly one of: ACCEPT, REJECT, CLARIFY … ACCEPT: the user generally
  agrees … even if they add extra nuance, caveats … Treat these as ACCEPT
  unless they clearly contradict." Plain text `/v1/responses`, no schema;
  return filtered `:12000-12001` to the three tokens, else `None` →
  `unclear`.
- Input: the WHOLE reply (`user_reply=text`), once PER CANDIDATE (4 GPT
  calls on Corvid against the same message). Context lives only in the
  deterministic frame (`stream_discovery_intent_frame` `:616-646`): the ask
  text, the pending labels, and the single label as an existence
  proposition; frame rule "Each stream stands on its own words" (`:643`)
  forbids exactly the cross-line reasoning ("this IS my existing line")
  that the merged answer needs. The frame's "nuance is NOT agreement …
  when unsure, CLARIFY" (`:639-642`) sits in the USER role and
  contradicts the door's SYSTEM-role "nuance → ACCEPT".
- Can it express "merged into an existing line"? **No.** "Remove/drop
  this line"? **No.** Three tokens; existence proposition.

## Q3 — Compared to the shared comprehension
(a) `consultant_chat_turn` `intake_consultant.py:208`: ONE GPT call with
the entire conversation + the whole intake_context (incl. the discovery
latch and, on the answer turn, `stream_discovery_note`), returning a
structured patch whose `lob_models` is a FULL snapshot. Its prompt
already carries merge/collapse authority — `:276` "THE CLIENT IS THE
FINAL AUTHORITY, at any point: 'treat them as one' collapses a proposed
split (re-model as a single line immediately, no pushback)" — but also
`:426` "carry forward already-known products … do not drop them", and
`:428/:665` "origin: carry forward … verbatim (e.g. discovery_confirmed)".
There is NO deterministic delete: `_apply_model_ops_patch`
`intake_consult.py:928-964` only assigns non-null keys; a row disappears
only if the model omits it. Grep for `del … products` /
`products.remove` / `lob_models.remove`: zero hits.
(b) `route_intent` `intent_router.py:1490`: actions `confirm_proceed |
confirm_clarify | edit_patch | answer_readonly | continue_chat` — no
remove-line, no merge intent; `lob_models` is BLOCKED as an ops-interview
patch target (`:1105-1111`); and for `focus == "ops"` without a locked
restatement the router is not invoked at all
(`intake_consult.py:17684-17687`, `action = "continue_chat"`).
(c) Greps for drop/remove/not a separate/combine/merge/same line/fold
into/collapse/retract across both files: nothing operative. **There is no
deterministic line-removal applier anywhere.**

WHERE IT DIVERGES: the reply IS also fed to `consultant_chat_turn`
(continue_chat) — the shared reader does see the message — but the
BINDING decision (yes → append → receipt) was already made and persisted
by the narrow per-candidate door BEFORE the shared reader ran, and the
shared reader's contrary output is then undone: immediately after the
model patch, `ops_json = _sdisc.carry_stream_discovery(_ops_before,
ops_json)` (`intake_consult.py:20356-20359`; function
`gpt_stream_discovery.py:764-850`) rebuilds `confirmed` SOLELY from
`latch.candidates[answer == "yes"]` (`:779-783`) and, under the comment
"Dropped by the replacement: restore the before-row … or a fresh null
row" (`:830-844`), re-appends any confirmed label the replacement no
longer contains. It consults NO dropped/retracted state (none exists).
The same call runs at both finalize sites (`:19725`, `:21077`).
Second-order effect that produced the exact symptom: the wrap gate
(`:20501-20509`) evaluates a FRESH `consultant_finalize` snapshot that is
never passed through `carry_stream_discovery` — so on the "drop that
line" turn the gate saw a snapshot WITHOUT the row (GPT honored the
client), judged every product complete, and fired the competitive-
advantage proposal (msg 26 verbatim), while the persisted `ops_json`
had the row re-attached at `:20357`. The wrap gate and the persisted
state disagreed; the persisted state is what reaches the boundary.

## Q4 — Can it ever produce "merged" or "remove"? NO — three layers
1. Enum/return filter `intake_consult.py:12001` (three tokens; hardest).
2. Per-candidate existence framing `gpt_stream_discovery.py:631` +
   "each stream stands on its own words" `:643`.
3. Bespoke downstream logic: `append_confirmed_stream_rows` has no
   placement decision (`:695-703`, `:754` unconditional own-LOB);
   `_apply_stream_discovery_answer` early-returns once nothing is
   pending (`intake_consult.py:11793-11796`) — an answer can never be
   revised on a later turn.
The prompt is the WEAKEST constraint; a perfect prompt could not emit
a fourth verdict.

## Q5 — Any path honoring "drop / remove that line"? NO
- Discovery module: none; no retracted state; `stream_discovery_pending`
  false once all answered → applier never re-entered.
- General ops patch: only if `consultant_chat_turn` omits the row from
  its snapshot — discouraged by its own `:426` "do not drop them" — and
  then `carry_stream_discovery` re-attaches it anyway (`:830-844`),
  every ops turn (`:20357`) and at both finalize sites.
- Router: blocked field + not invoked for ops turns.
It is, by design, a one-way latch.

## Transcript / latch confirmation (persisted)
msg 22 the ask (4 labels, why-clause, serial comma). msg 23 the client's
"already part of our commercial print line … not a separate thing. No
copying… No graphic design… And no bindery… as a line." msg 24 "Noted -
Digital printing services is its own line; a few quick numbers for it
next. … in a fully busy month, about how many Digital printing services
can you handle?" msg 25 "No, don't make digital printing a separate
line … you'd be counting the same work twice. Please drop that line."
msg 26 the competitive-advantage proposal — no acknowledgment. Latch:
Digital printing services `answer: yes` (answered_from = msg 23), three
`no`; no clarify, no retraction field. Final `lob_models`: the phantom
row with unit_name/price/capacity/periods None, util 0.8,
origin=discovery_confirmed → boundary ContractViolation.

## What converging onto the shared path would take (for the ruling; nothing built)
Option A (converge — the likely fix): make `consultant_chat_turn` the
PRIMARY reader of the discovery-window reply. It already receives the
full conversation, the latch, and returns a full `lob_models` snapshot;
let the SHARED path return the whole ops model — including "digital
printing stays inside commercial print" (no new row) or a removed row —
instead of four boolean side-questions. Demote the per-candidate door to
at most a tie-breaker / latch bookkeeper (record what the shared model
did per label: added / merged_into:<line> / declined). Then:
`append_confirmed_stream_rows` stops unconditionally minting an own-LOB
(append only what the shared reading actually added, or let the shared
patch add it and just stamp origin); `carry_stream_discovery` gates its
re-attach on the latch's real state (added AND not retracted/merged) —
otherwise any correction, however read, is reversed next turn; and the
wrap gate must evaluate the SAME row set that gets persisted (either
carry the latch through the gate snapshot or gate on persisted
ops_json). Discovery-path + the finalize/carry-forward seam →
neighbor-check tier when built.
Option B (keep the per-candidate shape, widen it): a discovery-specific
classifier with verdicts `yes | no | unclear | already_covered_by:<line>
| retracted`, plus latch fields `resolved_to_existing_line` /
`retracted_turn`, plus the same append/carry-forward/gate changes. More
code, still a second reader — Nick's "comprehend like the rest of the
app" points to A.
Either way, D3 (the judge proposing a sub-category of a stated line)
remains a separate, smaller judge-prompt item.
