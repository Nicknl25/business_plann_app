"""Response-tool stubs for the restructure protocol (spec §6.4).

The four functions exposed here are the **only** acceptable GPT responses to
a restructure proposal. Free-form prose is rejected (the session driver in
step 5 ignores any other shape and re-presents the proposal once, then
treats no-structured-response as a veto and advances).

Each function:

  - validates its inputs structurally (required args, length caps, type
    checks);
  - returns a normalised ``ProposalResponse`` the session driver in step 5
    dispatches on. The driver routes a CONFIRM/CHOOSE/OTHER to the
    appropriate revise_* tool and routes a VETO straight to the
    restructuring_log writer with applied_value=None.

Step 4 ships the functions and the response shape. Step 5 wires the
amalgamated session's tool catalog to expose them as the only GPT-callable
responses during a restructure step (and adds the no-progress / retry /
budget-aware behavior the spec §7-§8 require around them).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional


# spec §6.3 — the choice template lists at most three options (A, B, C).
_VALID_OPTION_IDS = ("A", "B", "C")

# spec §6.3 — veto/other reasons are one short business sentence. The
# restructuring_log column caps at 512 chars; we cap inputs to a slightly
# larger window so the writer truncation is observable rather than silent.
_REASON_MAX_LEN = 600

# §10.5 — the protocol never modifies Stub 0. The session driver also
# enforces this at apply time; the response-tool stub catches an
# obviously-illegal section earlier.
_ALLOWED_SECTIONS = (
  "stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet",
  # capex/R&D/balance-sheet-seed is sometimes referenced as one section in
  # the spec; the tool wrapper exposes it under this combined name too.
  "capex_rd_balance_seed",
  # operating_model levers (price, utilization, capacity, headcount) are
  # in stage_ramp / drivers / payroll depending on the lever. The proposer
  # picks the right section; we accept all five canonical names.
)


@dataclass
class ProposalResponse:
  """Normalised result of one response-tool call.

  ``kind`` discriminates which response was given. The remaining fields
  carry the response's payload (option_id for choose, section/field/value
  for other, reason for veto/other). ``validation_errors`` lists structural
  problems with the inputs — non-empty means the session driver should
  treat the response as "no structured response" and advance the cascade.
  """
  kind: str                                          # "confirm"|"veto"|"choose"|"other"
  option_id: Optional[str] = None
  reason: Optional[str] = None
  section: Optional[str] = None
  field: Optional[str] = None
  value: Optional[float] = None
  validation_errors: List[Dict[str, str]] = dc_field(default_factory=list)

  @property
  def validated(self) -> bool:
    return not self.validation_errors


def _string(value: Any, *, max_len: Optional[int] = None) -> str:
  s = str(value if value is not None else "").strip()
  if max_len is not None and len(s) > max_len:
    s = s[:max_len]
  return s


def confirm_proposal() -> ProposalResponse:
  """Type-A CONFIRM — apply the Python proposal as-is.

  No arguments. The session driver in step 5 reads the proposal from
  ``SessionState.pending_proposal`` and calls the corresponding revise_*
  tool with the proposer-computed patch.
  """
  return ProposalResponse(kind="confirm")


def veto_proposal(reason: Optional[str] = None) -> ProposalResponse:
  """Type-A VETO — reject the Python proposal with a one-sentence reason.

  The session driver writes a restructuring_log row with applied_value=None,
  veto_reason=<truncated>, applied_by=amalgamated_gpt_vetoed, then advances
  the cascade to the next tier (spec §8.1).
  """
  text = _string(reason, max_len=_REASON_MAX_LEN)
  errors: List[Dict[str, str]] = []
  if not text:
    errors.append({
      "code": "veto_reason_required",
      "message": (
        "veto_proposal requires a one-sentence business reason. "
        "'I'd prefer not to' is not a veto reason — the cohort target is "
        "the realism anchor (spec §6.3 Type A template)."
      ),
    })
  return ProposalResponse(kind="veto", reason=text or None, validation_errors=errors)


def choose_option(option_id: Optional[str] = None) -> ProposalResponse:
  """Type-B CHOOSE — pick option A/B/C from the proposer's option list.

  The session driver applies that option via the corresponding revise_*
  tool and logs the row with applied_by=amalgamated_gpt_chose.
  """
  raw = _string(option_id).upper()
  errors: List[Dict[str, str]] = []
  if raw not in _VALID_OPTION_IDS:
    errors.append({
      "code": "invalid_option_id",
      "message": (
        f"choose_option requires option_id in {list(_VALID_OPTION_IDS)}; "
        f"got {option_id!r}. Use other_proposal for an in-band free-form "
        "alternative (spec §6.3 Type B template)."
      ),
    })
  return ProposalResponse(
    kind="choose",
    option_id=raw if not errors else None,
    validation_errors=errors,
  )


def other_proposal(
  section: Optional[str] = None,
  field: Optional[str] = None,
  value: Any = None,
  reason: Optional[str] = None,
) -> ProposalResponse:
  """Type-B OTHER — propose an in-band free-form alternative.

  The session driver in step 5 validates the (section, field, value) tuple
  against the live cohort bands. If in-band, applies via the corresponding
  revise_* tool and logs with applied_by=amalgamated_gpt_other. If out-of-
  band, the session driver downgrades to amalgamated_gpt_other_out_band,
  treats as a veto, and advances the cascade (spec §6.2 / §8.1).

  This stub validates only the **structural** shape; band-validity is the
  session driver's job (it has the cohort_bands payload).
  """
  sec  = _string(section, max_len=32)
  fld  = _string(field, max_len=128)
  rsn  = _string(reason, max_len=_REASON_MAX_LEN)

  errors: List[Dict[str, str]] = []
  if not sec:
    errors.append({"code": "other_section_required",
                   "message": "other_proposal requires a target section name."})
  elif sec not in _ALLOWED_SECTIONS:
    errors.append({
      "code": "other_section_unknown",
      "message": (
        f"section {sec!r} is not one of the authoring sections "
        f"{list(_ALLOWED_SECTIONS)}; stub 0 facts cannot be modified."
      ),
    })
  if not fld:
    errors.append({"code": "other_field_required",
                   "message": "other_proposal requires a target lever/field name."})
  value_f: Optional[float] = None
  if value is None:
    errors.append({"code": "other_value_required",
                   "message": "other_proposal requires a proposed value."})
  else:
    try:
      value_f = float(value)
    except (TypeError, ValueError):
      errors.append({
        "code": "other_value_not_numeric",
        "message": f"other_proposal value must be numeric; got {value!r}.",
      })

  if not rsn:
    errors.append({
      "code": "other_reason_required",
      "message": "other_proposal requires a one-sentence reason (spec §6.3 Type B template).",
    })

  return ProposalResponse(
    kind="other",
    section=sec or None,
    field=fld or None,
    value=value_f,
    reason=rsn or None,
    validation_errors=errors,
  )


__all__ = [
  "ProposalResponse",
  "confirm_proposal",
  "veto_proposal",
  "choose_option",
  "other_proposal",
]
