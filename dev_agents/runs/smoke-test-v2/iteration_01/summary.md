Run failed in Q2

Root cause:
- primary: capital allocation insufficient
- secondary: engine overpowered
- affected rows: capex, marketing, principal_repayments
- band violation: Q2: cash 408,929.38 vs band 236,450.26 to 279,441.22

Feasibility:
- cash too tight: True
- levers insufficient: True
- engine overpowered: True
- recommendation: Relax the later-quarter cash path or add materially wider deployment capacity where the first failing quarter breaks. Strengthen capital-allocation rows in the first failing window rather than relying on small schedule ranges. Reduce the operating engine or widen non-cash absorption so cash generation does not outrun the bands.

Fix applied:
- none

Fix proposed:
- Strengthen later-quarter non-authority language in the main planner prompt.
- Remove raw fixed-facts model views from the AI-facing planning-mode payload.
- Widen capex / schedule deployment behavior in the first failing window.
- Relax later-quarter cash posture where the business cannot credibly absorb the surplus.
- Strengthen non-cash planning pressure against an overpowered operating engine.
- Increase midpoint pressure so feasible solves gravitate more strongly toward band centers.

Replay result:
- moved failure: n/a
- shape change: dip

Decision:
- escalate
- High-risk change requires user review: Increase midpoint pressure so feasible solves gravitate more strongly toward band centers.