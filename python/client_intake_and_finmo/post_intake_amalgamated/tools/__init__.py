"""Authoring tools the amalgamated GPT session calls (memo §3.2).

Each tool validates inputs against cohort bands + the contract schema,
returns a structured {accepted, violations, bands_echoed} payload, and
on acceptance writes the section to plan_state. Rejection does NOT
mutate state — the violations array carries enough information for GPT
to fix and retry.

Step 3 commits each ``set_*`` tool one at a time and deletes the
corresponding legacy GPT session loop in the same commit. Step 4 adds
the ``revise_*`` partial-patch variants the cascade's revision step
(spec §13.1) uses to make a small edit to an already-committed section
without re-authoring the whole payload.
"""

from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # noqa: F401
  set_stage_ramp_contract,
)
from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (  # noqa: F401
  set_payroll_schedule,
)
from client_intake_and_finmo.post_intake_amalgamated.tools.set_drivers import (  # noqa: F401
  set_drivers,
)
from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: F401
  set_capex_rd_balance_seed,
)

# Step 4 — partial-patch (revise_*) variants. Stage_ramp and payroll
# revise tools land in the next commit alongside their tests.
from client_intake_and_finmo.post_intake_amalgamated.tools.revise_drivers import (  # noqa: F401
  revise_drivers,
)
from client_intake_and_finmo.post_intake_amalgamated.tools.revise_capex_rd_balance_seed import (  # noqa: F401  # noqa: E501
  revise_capex_rd_balance_seed,
)
