"""THE INTAKE WATCHER (Nick 2026-09-12): an agent that runs alongside the
intake with the transcript and the store, and NOTICES - the client corrected
the same figure four times and nothing moved; the store holds 7.6M where the
client said 633,312; rent changed after the client said the lease was signed.

It surfaces, it never writes. It has two inputs (the transcript, the
persisted draft before and after each turn) and one output (observation
records). No write path to the draft, no patch vocabulary, no router key.

Where code gives a certain answer, code answers (checks.py) - not because
it is cheaper but because a computed answer beats a judged one. Where the
transcript must be read, the model reads it (judgment.py). Both run on every
turn, always (observe.py), per-turn, read-only.
"""
