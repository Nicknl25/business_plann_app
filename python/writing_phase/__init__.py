"""THE WRITING PHASE.

Nothing in this package generates a document yet. What lives here is the RULE
SET that will govern everything the writing phase ever produces, and the checks
that hold it — established by Nick's directive of 2026-08-30 and his rulings on
A-H, the quarterly-chart question, the dependency question and the chart set.

The one law that governs the rest, drawn from the CoInitialize bug of
2026-08-29: A CHECK THAT CANNOT RUN FAILS THE SECTION. It never passes by
default. That bug shipped for weeks because a recalc returned "unable to
evaluate" and the caller read it as fine.
"""
