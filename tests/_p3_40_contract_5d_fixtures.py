"""Shared fixture builders for Contract 5d (PeopleJsonContract
sub-contract retrofit) acceptance tests.

Module is leading-underscore-prefixed so the test runner does
NOT auto-discover it as a test module.

Per spec §6 Commit 5d-1: fixtures provide minimal-valid +
toggle-friendly defaults. Default profile matches the
PRODUCTION POST-POP shape per F1 / T3 -- key_people_summary
OMITTED (popped at intake_consult.py:6241 before persistence).
The toggle ``include_key_people_summary`` exercises the
contract's PSL2 acceptance of both presence + absence.

Fixtures align with the §0 value-constraint policy: payloads
exercise STRUCTURAL shape only; values use simple defaults
(empty strings, 0.0, [] are FINE -- no value checks to
satisfy).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


# ---------------------------------------------------------------------------
# PersonContract -- 9 fields per people_capability_consultant.py:94-114
# ---------------------------------------------------------------------------

def valid_person_dict(
  *,
  full_name: str = "Jane Doe",
  role_title: str = "Founder",
  experience_years: str = "8 years",
  annual_wage: Optional[float] = 75000.0,
  wage_source: str = "client_override",
) -> Dict[str, Any]:
  """PersonContract-shaped dict. 9 fields. Defaults: a single
  founder with 8 years experience + client-confirmed wage."""
  return {
    "full_name": full_name,
    "role_title": role_title,
    "primary_responsibilities": (
      "Strategy, operations, customer relationships."
    ),
    "relevant_background": (
      "MBA + 8 years in adjacent industry."
    ),
    "experience_years": experience_years,
    "why_strengthens_business": (
      "Domain expertise and existing network."
    ),
    "paragraph": (
      "Jane founded the business after a successful career in the "
      "adjacent industry and brings the relevant operational expertise."
    ),
    "annual_wage": annual_wage,
    "wage_source": wage_source,
  }


# ---------------------------------------------------------------------------
# InferredRoleContract -- 5 fields per people_capability_consultant.py:124-131
# ---------------------------------------------------------------------------

def valid_inferred_role_dict(
  *,
  role_title: str = "Store Manager",
  annual_wage: Optional[float] = 55000.0,
  wage_source: str = "gpt_estimate",
  months_until_hire: Optional[float] = 6.0,
  notes: str = "Inferred from staffing model.",
) -> Dict[str, Any]:
  """InferredRoleContract-shaped dict. 5 fields. Defaults: a
  store manager role to be hired 6 months out."""
  return {
    "role_title": role_title,
    "annual_wage": annual_wage,
    "wage_source": wage_source,
    "months_until_hire": months_until_hire,
    "notes": notes,
  }


# ---------------------------------------------------------------------------
# Top-level PeopleJsonContract -- 6 typed fields
# ---------------------------------------------------------------------------

def valid_people_json_dict(
  *,
  people: Optional[List[Dict[str, Any]]] = None,
  inferred_roles: Optional[List[Dict[str, Any]]] = None,
  include_business_naics_6: bool = True,
  include_key_people_summary: bool = False,
  **overrides: Any,
) -> Dict[str, Any]:
  """PeopleJsonContract-shaped dict. Default profile matches
  the PRODUCTION POST-POP shape per F1 / T3:
    - 1 person + 1 inferred_role populated
    - inferred_roles_summary populated
    - confidence 0.85
    - business_naics_6 populated (cross-flow default per T3)
    - key_people_summary OMITTED (popped at intake_consult.py:
      6241 before persistence)

  Toggle ``include_key_people_summary`` exercises the
  contract's PSL2 acceptance of BOTH presence + absence of
  this field.

  **overrides applied last -- caller can override any field.
  """
  if people is None:
    people = [valid_person_dict()]
  if inferred_roles is None:
    inferred_roles = [valid_inferred_role_dict()]
  payload: Dict[str, Any] = {
    "people": people,
    "inferred_roles": inferred_roles,
    "inferred_roles_summary": (
      "Year-1 hires: 1x Store Manager at ~6 months ($55,000)."
    ),
    "confidence": 0.85,
  }
  if include_business_naics_6:
    payload["business_naics_6"] = "722515"
  if include_key_people_summary:
    payload["key_people_summary"] = (
      "Jane Doe (Founder, 8 years experience) leads the business."
    )
  payload.update(overrides)
  return payload


__all__ = [
  "valid_person_dict",
  "valid_inferred_role_dict",
  "valid_people_json_dict",
]
