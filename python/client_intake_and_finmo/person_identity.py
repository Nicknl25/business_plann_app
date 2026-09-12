"""PERSON IDENTITY AND WAGE PROVENANCE, ONE DEFINITION (Nick 2026-09-11).

"A person's identity is a free-text string a model picks per turn, and payroll
sums rows keyed by that string. Every fix so far has been a guard on top of
that, and we've been back here four times. Assign a stable person id at
capture. Every later mention resolves to that id. Provenance becomes an enum
validated at the boundary, not a free-text token GPT can invent."

WHAT WENT WRONG, three faces of ONE mechanism (Pelletier Orthotics 8bb68a68
and Halvorsen Tide 836c2ca2, both live, both shipped to a client):

  - a phantom nameless {role_title: "Owner"} row carrying the owner's whole
    salary a SECOND time (15,500 x 12 = 186,000 exactly), because the
    owner-pay door found no owner by title regex - "Certified
    Prosthetist-Orthotist" contains none of owner/principal/founder/
    managing/partner - and minted a new row beside the man himself;
  - "Bartholomew" and "Bartholomew Ndiaye" stored as two humans at 94,000
    each, because supplying a surname produced a different identity string;
  - a client's stated 186,000 silently replaced by 102,870, the OEWS 75th
    percentile for his own occupation, because the row carried
    wage_source "client_reported" - a token NO python in this repo writes,
    invented by the model that turn, and absent from the three-token
    whitelist that protects a stated wage.

All three land on payroll because _compute_payroll_baseline SUMS every row.
An identity split is therefore always a payroll error, and always silent.

This module is the one home for the two strings that were being trusted as
keys. It lives here, not in the API handler, for the same reason owner_pay
does: the workbook builder, the contracts and the writing phase cannot
import a handler.

PROVENANCE. The canonical token for "the client said this" stays
``client_override`` - readers substring-test it (run_intake_e2e_wage_
overrides.py:179,193; writing_phase_v2/warehouse.py:450-451;
people_roles.py:659) and renaming it would break them for no gain. What
changes is that every synonym folds INTO it and an unrecognised token can no
longer silently forfeit the client's number.

THE DEFAULT IS PROTECTIVE, deliberately. An unrecognised provenance could
mean "client stated" or "model estimate"; the two failure directions are not
symmetric. Guessing "estimate" lets a benchmark overwrite a fact the client
gave us and ship it in a plan - the defect above. Guessing "stated" only
means a benchmark does not upgrade an estimate, which is invisible and
harmless. So unknown-shaped tokens resolve to client_override and say so in
the report, rather than resolving to whatever loses the fact.

``unknown`` is NOT a synonym for client_override: the people consultant is
instructed to emit it (people_capability_consultant.py:223) and it means
"nobody stated a wage", which must stay distinguishable from "the client
did".
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Set, Tuple

# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

WAGE_SOURCE_CLIENT = "client_override"
WAGE_SOURCE_GPT = "gpt_estimate"
WAGE_SOURCE_UNKNOWN = "unknown"

#: Every value this codebase may store on a row's ``wage_source``.
CANONICAL_WAGE_SOURCES: Set[str] = {
  WAGE_SOURCE_CLIENT,
  WAGE_SOURCE_GPT,
  WAGE_SOURCE_UNKNOWN,
  "oews_pct10",
  "oews_pct25",
  "oews_median",
  "oews_pct75",
}

#: Tokens seen in the wild (and in stored drafts) that MEAN client_override.
#: ``client_reported`` is the one that shipped a corrupted plan; it was never
#: a real value and nothing rejected it.
_WAGE_SOURCE_SYNONYMS: Dict[str, str] = {
  "client_provided": WAGE_SOURCE_CLIENT,
  "client_reported": WAGE_SOURCE_CLIENT,
  "client_stated": WAGE_SOURCE_CLIENT,
  "client_confirmed": WAGE_SOURCE_CLIENT,
  "client": WAGE_SOURCE_CLIENT,
  "user_override": WAGE_SOURCE_CLIENT,
  "manual_override": WAGE_SOURCE_CLIENT,
  "stated": WAGE_SOURCE_CLIENT,
  "": WAGE_SOURCE_UNKNOWN,
  "none": WAGE_SOURCE_UNKNOWN,
  "null": WAGE_SOURCE_UNKNOWN,
  "not_stated": WAGE_SOURCE_UNKNOWN,
}

#: Substrings that mark a token as a BENCHMARK even when the exact spelling
#: is new. Checked before the protective default so an invented
#: "oews_p75_2023" or "bls_median" is not mistaken for the client's word.
_BENCHMARK_HINTS: Tuple[str, ...] = (
  "oews", "bls", "benchmark", "median", "percentile", "pct",
  "market", "estimate", "gpt", "model", "inferred", "default",
)

#: Substrings that mark a token as the CLIENT's own statement.
_CLIENT_HINTS: Tuple[str, ...] = (
  "client", "user", "manual", "override", "stated", "reported",
  "provided", "confirmed", "said", "given",
)


def normalize_wage_source(value: Any) -> Tuple[str, bool]:
  """(canonical token, recognised). ``recognised`` is False when the input
  matched nothing this module knows - the caller should log it, because an
  unrecognised provenance is a contract break even though the value that
  comes back is safe to store."""
  raw = str(value or "").strip().lower()
  if raw in CANONICAL_WAGE_SOURCES:
    return raw, True
  if raw in _WAGE_SOURCE_SYNONYMS:
    return _WAGE_SOURCE_SYNONYMS[raw], True
  if any(hint in raw for hint in _BENCHMARK_HINTS):
    return WAGE_SOURCE_GPT, False
  if any(hint in raw for hint in _CLIENT_HINTS):
    return WAGE_SOURCE_CLIENT, False
  # Nothing matched. Protect the client's number - see the module docstring
  # on why the two failure directions are not symmetric.
  return WAGE_SOURCE_CLIENT, False


def is_client_stated(value: Any) -> bool:
  """True when this provenance means THE CLIENT SAID IT, and therefore that
  no benchmark may overwrite the wage beside it. Accepts a row or a bare
  token so every caller asks the same question the same way."""
  if isinstance(value, dict):
    value = value.get("wage_source")
  token, _ = normalize_wage_source(value)
  return token == WAGE_SOURCE_CLIENT


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

PERSON_ID_KEY = "person_id"
OWNER_FLAG_KEY = "is_owner"
_PERSON_ID_PREFIX = "p_"


def new_person_id() -> str:
  """A stable id for one human, minted once at capture and persisted with
  the row. Opaque on purpose: nothing may parse meaning out of it."""
  return _PERSON_ID_PREFIX + uuid.uuid4().hex[:12]


def person_id_of(row: Any) -> Optional[str]:
  if not isinstance(row, dict):
    return None
  pid = str(row.get(PERSON_ID_KEY) or "").strip()
  return pid or None


def normalize_name(value: Any) -> str:
  return " ".join(str(value or "").strip().lower().split())


def name_tokens(value: Any) -> Set[str]:
  return {t for t in normalize_name(value).replace(".", " ").split() if t}


def names_are_same_human(a: Any, b: Any) -> bool:
  """One name is the other with more of it supplied. "Bartholomew" and
  "Bartholomew Ndiaye" are one man; "Tobias Pelletier" and "Dr. Tobias
  Pelletier" are one man. "John Smith" and "John Jones" are two - neither
  token set contains the other.

  STRICTLY a subset test, never a fuzzy one. The caller must ALSO establish
  that the match is unambiguous across the roster before folding: with both
  "Bartholomew Ndiaye" and "Bartholomew Smith" standing, a bare
  "Bartholomew" names neither, and guessing is how a merge becomes a silent
  rename (the Rasheed Fennimore class)."""
  ta, tb = name_tokens(a), name_tokens(b)
  if not ta or not tb:
    return False
  if ta == tb:
    return True
  return ta.issubset(tb) or tb.issubset(ta)


def is_owner_row(row: Any, *, owner_title_re=None) -> bool:
  """Owner by the RECORDED FACT first, the title pattern second. The flag is
  set by the owner-pay door, which knows the row it landed on IS the client
  ("what you pay YOURSELF"); the regex still answers for every roster
  captured before the flag existed."""
  if not isinstance(row, dict):
    return False
  if bool(row.get(OWNER_FLAG_KEY)):
    return True
  if owner_title_re is None:
    return False
  return bool(owner_title_re.search(str(row.get("role_title") or "")))
