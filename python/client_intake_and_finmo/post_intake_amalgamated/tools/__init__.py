"""Authoring tools the amalgamated GPT session calls (memo §3.2).

Each tool validates inputs against cohort bands + the contract schema,
returns a structured {accepted, violations, bands_echoed} payload, and
on acceptance writes the section to plan_state. Rejection does NOT
mutate state — the violations array carries enough information for GPT
to fix and retry.

Step 3 commits each tool one at a time and deletes the corresponding
legacy GPT session loop in the same commit.
"""

from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # noqa: F401
  set_stage_ramp_contract,
)
