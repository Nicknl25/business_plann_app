"""Post-intake `Python proposes, GPT critiques` shared infrastructure (Module 5).

Architectural principle: deterministic Python builds a full payload (the
"proposal") using SQL-driven data — NAICS resolver, intake anchors,
mapping table formulas, policy rows. GPT receives the proposal as input
(not a blank slate) and either accepts it, amends specific fields, or
rejects it. When GPT amends, Python applies the corrections to produce
the final payload. When GPT fails (timeout, garbage response, rejected
without alternatives), Python's proposal stands as the safety floor —
because every value already has data provenance, the floor is always
reasonable.

Public surface:
  - `CritiqueResponse` — typed result the critic can produce
  - `CritiqueCorrection` — one corrective edit
  - `CRITIQUE_CONTRACT_SCHEMA` — JSON schema GPT writes against
  - `apply_corrections_to_proposal` — applies a CritiqueResponse to a
    proposal payload via dotted field_path notation
  - `proposal_only_response` — synthesize an "accepted" response when
    Python wants to bypass GPT for diagnostics
"""

from .contract import (
  CRITIQUE_CONTRACT_SCHEMA,
  CritiqueCorrection,
  CritiqueResponse,
  apply_corrections_to_proposal,
  proposal_only_response,
)

__all__ = [
  "CRITIQUE_CONTRACT_SCHEMA",
  "CritiqueCorrection",
  "CritiqueResponse",
  "apply_corrections_to_proposal",
  "proposal_only_response",
]
