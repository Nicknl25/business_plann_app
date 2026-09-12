"""THE INTAKE GUARD - in the loop, not after it (Nick 2026-09-12).

"The agent sits between GPT and the store. It sees the patch before it
lands and the reply before it goes out. If a figure is going into the
wrong field, it corrects it before the write happens. If GPT is about to
tell the client something that contradicts the store, it stops it. Not
filing. Not surfacing. PREVENTING."

Two doors, one agent:
  door A (door_a.py)  - after the router returns a patch and BEFORE the
                        handler applies it. The guard returns the patch it
                        allows: unchanged, rewritten, or with a field held
                        back behind a question. A rewrite carries its receipt
                        in the client's language ("you told me the $2,400 is
                        the van lease, so I've recorded it there rather than
                        against rent") and the client's own words that carry
                        the figure. It never invents a number.
  door B (door_b.py)  - after the reply is assembled and BEFORE it persists.
                        Every figure the reply states is checked against the
                        store; a reply that contradicts the store is rewritten
                        from the store, or held behind the question.

Authority with an audit trail: the guard never writes to the store. It
hands the door a different patch, or the persistence a different reply,
and every action is recorded (audit.py) with the patch, the receipt and
the why. Fail OPEN on a timeout, logged loudly: a stalled intake is worse
than an unguarded turn.

The after-turn watcher (intake_watcher) is retired by this package.
"""
