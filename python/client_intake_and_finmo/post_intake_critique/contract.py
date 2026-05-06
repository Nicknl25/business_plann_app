"""Shared critique contract for `Python proposes, GPT critiques`.

Each post-intake module that uses the proposer/critique pattern reuses
this contract. The contract is intentionally tiny — it only describes
WHAT GPT may say about a proposal, not what it may invent. A focused
critique surface keeps GPT's decision space small (less variance, less
latency) and keeps Python's proposal as the safety floor.

Field-path semantics for `corrections`:
  - Top-level fields: `"applicable"`, `"contract_version"`, etc.
  - Array indexing: `"balance_sheet_seed_grid[0].applicable"`,
    `"quarter_decisions[2].equity_issuance"`
  - Nested objects: `"funding_plan.q3.debt_issuance"`

The critic only modifies fields that already exist in the proposal. New
fields are NOT created; new array entries are NOT appended. Both keep
the contract closed and the proposal as the structural authority.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


CRITIQUE_REVIEW_STATUSES = ("accepted", "amended", "rejected")


CRITIQUE_CONTRACT_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "review_status": {
      "type": "string",
      "enum": list(CRITIQUE_REVIEW_STATUSES),
      "description": (
        "accepted: the Python proposal stands unchanged. "
        "amended: apply the corrections; the proposal is otherwise correct. "
        "rejected: the proposal is not usable; provide reason in critique_summary; "
        "Python will fall back to the proposal anyway as the safety floor."
      ),
    },
    "corrections": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "field_path": {
            "type": "string",
            "description": (
              "Dotted path to the proposal field. Use bracket notation for arrays: "
              "balance_sheet_seed_grid[0].applicable. Field MUST already exist in the proposal."
            ),
          },
          "current_value": {
            "type": ["string", "number", "boolean", "null"],
            "description": "The value currently in the proposal (for verification).",
          },
          "amended_value": {
            "type": ["string", "number", "boolean", "null"],
            "description": "The value the critic believes is correct.",
          },
          "reason": {
            "type": "string",
            "description": "One sentence explaining why this field needs to change for THIS business.",
          },
        },
        "required": ["field_path", "current_value", "amended_value", "reason"],
      },
    },
    "critique_summary": {
      "type": "string",
      "description": "One- or two-sentence summary of the review. Empty when review_status=accepted.",
    },
  },
  "required": ["review_status", "corrections", "critique_summary"],
}


@dataclass
class CritiqueCorrection:
  field_path: str
  current_value: Any
  amended_value: Any
  reason: str

  def to_dict(self) -> Dict[str, Any]:
    return {
      "field_path": self.field_path,
      "current_value": self.current_value,
      "amended_value": self.amended_value,
      "reason": self.reason,
    }


@dataclass
class CritiqueResponse:
  review_status: str
  corrections: List[CritiqueCorrection] = field(default_factory=list)
  critique_summary: str = ""
  raw_openai_response: Optional[Dict[str, Any]] = None

  @classmethod
  def from_payload(cls, payload: Optional[Dict[str, Any]]) -> "CritiqueResponse":
    raw = payload if isinstance(payload, dict) else {}
    status = str(raw.get("review_status") or "").strip().lower()
    if status not in CRITIQUE_REVIEW_STATUSES:
      raise RuntimeError(
        f"post_intake_critique_invalid_review_status: status={status!r} expected one of {CRITIQUE_REVIEW_STATUSES}"
      )
    raw_corrections = raw.get("corrections") if isinstance(raw.get("corrections"), list) else []
    corrections: List[CritiqueCorrection] = []
    for item in raw_corrections:
      if not isinstance(item, dict):
        continue
      field_path = str(item.get("field_path") or "").strip()
      reason = str(item.get("reason") or "").strip()
      if not field_path:
        continue
      corrections.append(
        CritiqueCorrection(
          field_path=field_path,
          current_value=item.get("current_value"),
          amended_value=item.get("amended_value"),
          reason=reason,
        )
      )
    summary = str(raw.get("critique_summary") or "").strip()
    return cls(
      review_status=status,
      corrections=corrections,
      critique_summary=summary,
    )

  def to_dict(self) -> Dict[str, Any]:
    return {
      "review_status": self.review_status,
      "corrections": [c.to_dict() for c in self.corrections],
      "critique_summary": self.critique_summary,
    }


def proposal_only_response(*, reason: str = "no_critic_invoked") -> CritiqueResponse:
  """Synthesize an `accepted` response. Used when Python wants to skip the
  critic entirely (test mode, no API key, deterministic-only run).
  """
  return CritiqueResponse(
    review_status="accepted",
    corrections=[],
    critique_summary=reason,
  )


# ---------------------------------------------------------------------------
# Field-path resolution.
# ---------------------------------------------------------------------------


_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _parse_path(field_path: str) -> List[Any]:
  tokens: List[Any] = []
  for match in _PATH_TOKEN_RE.finditer(str(field_path or "")):
    name, index = match.group(1), match.group(2)
    if name is not None:
      tokens.append(name)
    elif index is not None:
      tokens.append(int(index))
  return tokens


def _walk(payload: Any, tokens: List[Any]) -> Any:
  cursor = payload
  for token in tokens:
    if isinstance(token, int):
      if not isinstance(cursor, list) or token < 0 or token >= len(cursor):
        raise KeyError(f"path_index_out_of_range: {tokens}")
      cursor = cursor[token]
    else:
      if not isinstance(cursor, dict) or token not in cursor:
        raise KeyError(f"path_key_missing: {tokens}")
      cursor = cursor[token]
  return cursor


def _set_at_path(payload: Any, tokens: List[Any], value: Any) -> None:
  if not tokens:
    raise KeyError("empty_field_path")
  parent_tokens = tokens[:-1]
  last = tokens[-1]
  parent = _walk(payload, parent_tokens) if parent_tokens else payload
  if isinstance(last, int):
    if not isinstance(parent, list) or last < 0 or last >= len(parent):
      raise KeyError(f"path_index_out_of_range_at_set: {tokens}")
    parent[last] = value
  else:
    if not isinstance(parent, dict) or last not in parent:
      raise KeyError(f"path_key_missing_at_set: {tokens}")
    parent[last] = value


def apply_corrections_to_proposal(
  *,
  proposal: Dict[str, Any],
  response: CritiqueResponse,
) -> Dict[str, Any]:
  """Return a deep copy of `proposal` with the critic's corrections applied.

  When `review_status == "accepted"` or `"rejected"` (the latter is the
  safety-floor case), no corrections are applied. When `"amended"`, each
  correction's `field_path` is resolved against the proposal and the
  field's value replaced with `amended_value`. Corrections that refer to
  paths that do not exist in the proposal are silently dropped (Python
  treats them as "GPT misread the structure" rather than failing the run);
  they're surfaced in the diagnostic payload returned alongside.
  """
  result = copy.deepcopy(proposal)
  if response.review_status != "amended":
    return result
  applied: List[Dict[str, Any]] = []
  dropped: List[Dict[str, Any]] = []
  for correction in response.corrections:
    tokens = _parse_path(correction.field_path)
    if not tokens:
      dropped.append({"correction": correction.to_dict(), "reason": "empty_path"})
      continue
    try:
      _set_at_path(result, tokens, correction.amended_value)
      applied.append(correction.to_dict())
    except (KeyError, IndexError, TypeError) as exc:
      dropped.append({"correction": correction.to_dict(), "reason": str(exc)})
  result["_critique_diagnostics"] = {
    "review_status": response.review_status,
    "applied_corrections": applied,
    "dropped_corrections": dropped,
    "critique_summary": response.critique_summary,
  }
  return result
