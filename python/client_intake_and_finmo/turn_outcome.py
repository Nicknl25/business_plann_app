from __future__ import annotations

from typing import Literal

TurnOutcome = Literal["ASK_NEXT", "SECTION_COMPLETE", "RUN_CONSISTENCY", "INTAKE_COMPLETE"]

ASK_NEXT: TurnOutcome = "ASK_NEXT"
SECTION_COMPLETE: TurnOutcome = "SECTION_COMPLETE"
RUN_CONSISTENCY: TurnOutcome = "RUN_CONSISTENCY"
INTAKE_COMPLETE: TurnOutcome = "INTAKE_COMPLETE"

