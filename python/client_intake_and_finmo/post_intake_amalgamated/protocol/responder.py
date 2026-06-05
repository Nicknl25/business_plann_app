"""Production responder for the amalgamated restructure session
(spec §6.3 + §6.4).

The responder is the callable the SessionDriver invokes to get a
structured GPT decision for each cascade step. It round-trips through
the Chat Completions API with the four response tools
(confirm_proposal / veto_proposal / choose_option / other_proposal)
exposed as the ONLY callable functions — GPT cannot reply with free-
form prose per spec §6.4.

Public surface:

  make_amalgamated_responder(*, conn, draft_id, planning_run_id,
                             mirror, model="gpt-5.1", seed=1729,
                             temperature=0.0, _http=None) -> responder

  The returned callable matches the SessionDriver._responder seam
  signature:
    (mode, tier, proposal_or_options, state, **_) -> ProposalResponse

Failure modes (spec §6.4 + §8.5 disposition):

  - OPENAI_API_KEY unset: synthetic veto (kind="veto",
    reason="openai_api_key_unset_synthetic_veto"). The cascade
    advances tier-by-tier and ultimately hits the §9.2 floor
    primitive, which produces a deterministic in-bounds plan.
  - HTTP error or non-2xx: synthetic veto with the error detail in
    the reason field.
  - GPT returns no tool call / malformed payload: synthetic veto with
    code "responder_malformed".

This module does NOT mutate state. It builds a request, sends it,
parses the response into a ProposalResponse, and hands back. All
side effects (audit rows, plan_state writes) are the session
driver's responsibility.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Union

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
  FailureMode,
)
from client_intake_and_finmo.post_intake_amalgamated.mirror import Mirror
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
  CascadeTier,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
  StepType,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (
  ProposalResponse,
  choose_option,
  confirm_proposal,
  other_proposal,
  veto_proposal,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructure_proposer import (
  Proposal,
)


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Tool specs — the four response tools as OpenAI function definitions.
# ---------------------------------------------------------------------------

_RESPONSE_TOOL_SPECS: List[Dict[str, Any]] = [
  {
    "type": "function",
    "function": {
      "name": "confirm_proposal",
      "description": (
        "Apply the Python-proposed change as-is. Use this when the "
        "cohort target is the right call for this specific business."
      ),
      "parameters": {"type": "object", "properties": {}, "required": []},
    },
  },
  {
    "type": "function",
    "function": {
      "name": "veto_proposal",
      "description": (
        "Reject the Python-proposed change. Use only when this specific "
        "business has a reason the cohort default does not apply. "
        "Provide a one-sentence business reason; 'I would prefer not "
        "to' is not a veto reason."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "reason": {
            "type": "string",
            "description": "One-sentence business reason for the veto.",
          },
        },
        "required": ["reason"],
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "choose_option",
      "description": (
        "Pick one of the labeled options (A, B, or C) presented in the "
        "Type B proposal. Use this when the proposer offers explicit "
        "alternatives."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "option_id": {
            "type": "string",
            "enum": ["A", "B", "C"],
            "description": "The option letter to apply.",
          },
        },
        "required": ["option_id"],
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "other_proposal",
      "description": (
        "Propose an in-band free-form alternative when none of the "
        "Type B options fit. Out-of-band proposals are treated as a "
        "veto. Provide a one-sentence reason."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "section": {"type": "string"},
          "field": {"type": "string"},
          "value": {"type": "number"},
          "reason": {"type": "string"},
        },
        "required": ["section", "field", "value", "reason"],
      },
    },
  },
]


# ---------------------------------------------------------------------------
# Prompt rendering — spec §6.3 templates.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
  "You are the executive role in a Python-managed restructure protocol "
  "for a post-intake business-plan amalgamated session. Python is the "
  "manager: it diagnoses failures, selects which lever is on the table, "
  "and computes the proposed value. You provide JUDGMENT — confirm "
  "Python's call, veto with a one-sentence business reason when this "
  "specific business has a reason the cohort default does not apply, "
  "or pick from explicit options when the proposer presents alternatives. "
  "You CANNOT reply with free-form prose. The four response tools are "
  "the only acceptable responses. The cohort target is the realism "
  "anchor; 'I would prefer not to' is not a valid veto reason."
)


# Render order for the operating_model digest (business portrait) in the
# executive's prompt. Identity/pricing/capacity first, free-text last.
_OM_DIGEST_RENDER_ORDER = (
  "business_type", "consumer_type", "business_stage",
  "unit_name", "unit_description", "unit_cadence",
  "unit_price", "units_per_week_capacity", "units_per_period_capacity",
  "utilization_rate", "operating_periods_per_year",
  "capacity_driver", "primary_growth_lever",
  "sales_modality", "shipping_method",
  "geographic_scope", "geographic_coverage",
  "business_description_summary", "competitive_advantage",
)


def _fmt(value: Any) -> str:
  if value is None:
    return "(unset)"
  if isinstance(value, float):
    return f"{value:.4f}"
  return str(value)


def render_mirror_for_proposal(
  *,
  mirror: Optional[Mirror],
  proposal_or_options: Union[Proposal, List[Proposal]],
  mode: FailureMode,
  tier: CascadeTier,
) -> str:
  """Build the §6.3 user-message text from the proposal + mirror context.

  Returns a single string with the template filled in. The session
  driver passes the live mirror so this function can echo the
  business_facts + plan_state + validation_state slices the executive
  needs to make a judgment call.
  """
  lines: List[str] = []
  if isinstance(proposal_or_options, list):
    head = proposal_or_options[0] if proposal_or_options else None
  else:
    head = proposal_or_options
  failing_check = getattr(head, "rationale_text", "") or "(see proposal rationale)"

  if tier.step_type == StepType.TYPE_A:
    lines.append("RESTRUCTURE PROPOSAL — please confirm or veto.")
    lines.append("")
    lines.append(f"Cascade: {mode.value} / Tier {tier.tier_id} — {tier.name}")
    if head is not None:
      lines.append(f"Failing context: {failing_check}")
      lines.append("")
      lines.append("Proposed change:")
      lines.append(f"  Section: {head.section}")
      lines.append(f"  Lever:   {head.field}")
      lines.append(f"  Current: {_fmt(head.current_value)}")
      lines.append(f"  Target:  {_fmt(head.proposed_value)}")
      lines.append(f"  Rationale: {head.rationale_text or '(none)'}")
      lines.append("")
      lines.append("Constraint context (band):")
      lines.append(
        f"  min: {_fmt(head.band_min)}  target: {_fmt(head.band_target)}  "
        f"max: {_fmt(head.band_max)}"
      )
      lines.append(f"  Current is {head.pinning_summary or '(unknown)'}.")
    lines.append("")
    lines.append("Respond with confirm_proposal or veto_proposal(reason=...).")
  elif tier.step_type == StepType.TYPE_B:
    lines.append("RESTRUCTURE CHOICE — please pick one option.")
    lines.append("")
    lines.append(f"Cascade: {mode.value} / Tier {tier.tier_id} — {tier.name}")
    if head is not None:
      lines.append(f"Failing context: {failing_check}")
    lines.append("")
    lines.append("Options:")
    options = proposal_or_options if isinstance(proposal_or_options, list) else [proposal_or_options]
    for opt in options:
      if opt is None:
        continue
      lines.append(
        f"  ({opt.option_id or '?'}) {opt.summary or '(no summary)'}"
      )
      lines.append(
        f"      Section/field/target: {opt.section}/{opt.field}/{_fmt(opt.proposed_value)}"
      )
      lines.append(f"      Trade-off: {opt.tradeoff_text or '(none)'}")
    lines.append("")
    lines.append(
      "Respond with choose_option(option_id=A|B|C) or "
      "other_proposal(section, field, value, reason)."
    )
  else:
    lines.append(
      f"Unexpected step_type {tier.step_type!r} reached the responder; "
      "this is a protocol bug. Vetoing."
    )

  if mirror is not None:
    biz = getattr(mirror, "business_facts", {}) or {}
    if biz:
      lines.append("")
      lines.append("Business facts:")
      for k in ("naics_6", "naics_2", "business_stage", "consumer_type",
                "business_name", "primary_lob"):
        if k in biz:
          lines.append(f"  {k}: {biz[k]}")

    # Business portrait (operating_model digest) — what this business IS and
    # how it makes money, so revenue-lever judgments (price / utilization /
    # capacity) are grounded in the actual business, not made blind.
    om = biz.get("operating_model_digest") if isinstance(biz, dict) else None
    if isinstance(om, dict) and om:
      lines.append("")
      lines.append("Business portrait (operating model):")
      for k in _OM_DIGEST_RENDER_ORDER:
        if k in om and om[k] not in (None, ""):
          label = k.replace("_", " ")
          lines.append(f"  {label}: {_fmt(om[k])}")

    # P3.40 bug 3 fix: render the current standards-check state so the
    # executive sees the failure context the cascade is responding to.
    # The mirror's validation_state is populated by
    # Mirror.set_validation_state after each SessionDriver._evaluate
    # call (small projection; not the full EvaluatePlanResult).
    vs = getattr(mirror, "validation_state", None) or {}
    if isinstance(vs, dict) and vs:
      # P3.40 Contract 7 Commit 3 -- Shape D consumer-side gate per
      # spec §5.2.2. Validates the Bug 3 bounded projection (11
      # fields per mirror.py:146-157) including F6 invariants
      # (cap=12, truncation flag consistency, outside_band filter)
      # before consumers render it into GPT prompt context.
      try:
        from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore  # noqa: E501
          SIDE_CONSUMER as _AS_SIDE_CONSUMER,
          validate_amalgamated_validation_state_at_boundary,
        )
        validate_amalgamated_validation_state_at_boundary(
          vs, side=_AS_SIDE_CONSUMER,
        )
      except ImportError:
        pass  # contract module absent -- skip (best-effort)
      lines.append("")
      lines.append("Current standards-check state:")
      lines.append(
        f"  round {vs.get('round_number', '?')} | strictness "
        f"{vs.get('strictness', '?')} | "
        f"all_pass: {vs.get('all_pass')}"
      )
      fail_count = vs.get("failing_check_count")
      if fail_count is not None:
        lines.append(f"  failing checks: {fail_count}")
      worst = vs.get("worst_failing_check")
      if worst:
        lines.append(
          f"  worst: {worst} (distance "
          f"{_fmt(vs.get('worst_failing_distance'))})"
        )
      names = vs.get("failing_check_names") or []
      if names:
        truncated = vs.get("failing_check_names_truncated")
        suffix = " (truncated)" if truncated else ""
        lines.append(f"  failing-check names{suffix}: " + ", ".join(names))
      margins = vs.get("failing_lever_margins") or []
      if margins:
        truncated = vs.get("failing_lever_margins_truncated")
        suffix = " (truncated)" if truncated else ""
        lines.append(f"  out-of-band levers{suffix}:")
        for m in margins:
          if not isinstance(m, dict):
            continue
          lever_id = m.get("lever_id") or "?"
          cur = _fmt(m.get("current"))
          bmin = _fmt(m.get("band_min"))
          bmax = _fmt(m.get("band_max"))
          pin = ""
          if m.get("pinned_min"):
            pin = " [pinned-min]"
          elif m.get("pinned_max"):
            pin = " [pinned-max]"
          lines.append(f"    {lever_id}: {cur} (band {bmin}..{bmax}){pin}")

  return "\n".join(lines)


# ---------------------------------------------------------------------------
# OpenAI request + response parsing.
# ---------------------------------------------------------------------------

def _build_openai_request(
  *,
  user_prompt: str,
  model: str,
  seed: int,
  temperature: float,
) -> Dict[str, Any]:
  return {
    "model": model,
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": user_prompt},
    ],
    "tools": _RESPONSE_TOOL_SPECS,
    "tool_choice": "required",
    "temperature": float(temperature),
    "seed": int(seed),
  }


def _parse_tool_call_response(payload: Dict[str, Any]) -> ProposalResponse:
  """Turn the OpenAI Chat Completions response payload into a
  ProposalResponse. Malformed shapes -> synthetic veto."""
  if not isinstance(payload, dict):
    return veto_proposal(reason="responder_malformed:non_dict_response")
  choices = payload.get("choices") if isinstance(payload.get("choices"), list) else None
  if not choices:
    return veto_proposal(reason="responder_malformed:no_choices")
  message = choices[0].get("message") if isinstance(choices[0], dict) else None
  tool_calls = (
    message.get("tool_calls")
    if isinstance(message, dict) and isinstance(message.get("tool_calls"), list)
    else None
  )
  if not tool_calls:
    return veto_proposal(reason="responder_malformed:no_tool_calls")

  call = tool_calls[0] if isinstance(tool_calls[0], dict) else {}
  fn = call.get("function") if isinstance(call.get("function"), dict) else {}
  fn_name = str(fn.get("name") or "").strip()
  args_raw = fn.get("arguments")
  args: Dict[str, Any] = {}
  if isinstance(args_raw, str) and args_raw:
    try:
      parsed = json.loads(args_raw)
      if isinstance(parsed, dict):
        args = parsed
    except Exception:
      return veto_proposal(reason="responder_malformed:arguments_not_json")
  elif isinstance(args_raw, dict):
    args = args_raw

  if fn_name == "confirm_proposal":
    return confirm_proposal()
  if fn_name == "veto_proposal":
    return veto_proposal(reason=args.get("reason"))
  if fn_name == "choose_option":
    return choose_option(option_id=args.get("option_id"))
  if fn_name == "other_proposal":
    return other_proposal(
      section=args.get("section"),
      field=args.get("field"),
      value=args.get("value"),
      reason=args.get("reason"),
    )
  return veto_proposal(reason=f"responder_malformed:unknown_tool:{fn_name}")


# ---------------------------------------------------------------------------
# Responder factory
# ---------------------------------------------------------------------------

def make_amalgamated_responder(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  mirror: Optional[Mirror] = None,
  model: str = "gpt-5.1",
  seed: int = 1729,
  temperature: float = 0.0,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
  _http: Optional[Callable[..., Any]] = None,
) -> Callable[..., ProposalResponse]:
  """Return a responder callable bound to a session's parameters.

  The returned callable matches the SessionDriver._responder seam:
    responder(mode, tier, proposal_or_options, state, **_) -> ProposalResponse

  ``_http`` is a test seam — when supplied, it replaces the live
  ``post_openai_with_retries`` call. Production callers pass None.
  """

  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  http_fn = _http
  if http_fn is None and api_key:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries

  def _emit_responder_diag(event_code_name: str, *, attempt: int,
                           reason: str) -> None:
    """Best-effort diagnostic emit for responder retry/exhaust events.
    Mirrors the SessionDriver._emit pattern — swallows exceptions so
    observability never breaks the responder."""
    try:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
        EventCode as _RDxEventCode, PhaseCode as _RDxPhaseCode,
        Status as _RDxStatus, safe_emit as _rdx_safe_emit,
      )
      ec = getattr(_RDxEventCode, event_code_name, None)
      if ec is None:
        return
      _rdx_safe_emit(
        conn,
        draft_id=str(draft_id or ""),
        planning_run_id=str(planning_run_id or ""),
        phase=_RDxPhaseCode.CASCADE_WALK,
        event_code=ec,
        status=_RDxStatus.STARTED if "ATTEMPTED" in event_code_name else _RDxStatus.FAILED,
        diagnostic_data={"attempt": attempt, "reason": reason[:300]},
      )
    except Exception:
      pass

  def responder(
    *,
    mode: FailureMode,
    tier: CascadeTier,
    proposal_or_options: Union[Proposal, List[Proposal]],
    state: Any = None,
    **_kwargs: Any,
  ) -> ProposalResponse:
    if api_key is None:
      return veto_proposal(reason="openai_api_key_unset_synthetic_veto")
    user_prompt = render_mirror_for_proposal(
      mirror=mirror,
      proposal_or_options=proposal_or_options,
      mode=mode, tier=tier,
    )
    headers = {
      "Authorization": f"Bearer {api_key}",
      "Content-Type": "application/json",
    }

    # C12 (spec §6.4) — one retry on malformed / transient failure
    # before treating as synthetic veto. The retry uses a fresh
    # OpenAI request (no caching). HTTP-layer retries (the http_fn
    # internal retries on 5xx/429) are independent of this protocol-
    # level retry; they handle TCP failure, this handles GPT
    # responding with shape it shouldn't have.
    last_failure_reason = "no_attempt_made"
    for attempt in range(2):  # 0 = initial, 1 = retry
      payload = _build_openai_request(
        user_prompt=user_prompt, model=model, seed=seed + attempt,
        temperature=temperature,
      )
      try:
        resp = http_fn(
          url=_OPENAI_URL,
          headers=headers,
          payload=payload,
          timeout_seconds=timeout_seconds,
          retryable_status=(429, 500, 502, 503, 504),
          max_attempts=max_attempts,
        )
      except Exception as exc:
        last_failure_reason = f"responder_http_error:{type(exc).__name__}"
        if attempt == 0:
          _emit_responder_diag("RESPONDER_RETRY_ATTEMPTED",
                               attempt=attempt + 1,
                               reason=last_failure_reason)
          continue
        _emit_responder_diag("RESPONDER_RETRY_EXHAUSTED",
                             attempt=attempt + 1,
                             reason=last_failure_reason)
        return veto_proposal(reason=last_failure_reason)

      status = int(getattr(resp, "status_code", 0) or 0)
      if status != 200:
        detail = str(getattr(resp, "text", ""))[:200] or f"http_status_{status}"
        last_failure_reason = f"responder_http_non_200:{status}:{detail}"
        if attempt == 0:
          _emit_responder_diag("RESPONDER_RETRY_ATTEMPTED",
                               attempt=attempt + 1,
                               reason=last_failure_reason)
          continue
        _emit_responder_diag("RESPONDER_RETRY_EXHAUSTED",
                             attempt=attempt + 1,
                             reason=last_failure_reason)
        return veto_proposal(reason=last_failure_reason)

      try:
        body = resp.json()
      except Exception:
        last_failure_reason = "responder_malformed:non_json_body"
        if attempt == 0:
          _emit_responder_diag("RESPONDER_RETRY_ATTEMPTED",
                               attempt=attempt + 1,
                               reason=last_failure_reason)
          continue
        _emit_responder_diag("RESPONDER_RETRY_EXHAUSTED",
                             attempt=attempt + 1,
                             reason=last_failure_reason)
        return veto_proposal(reason=last_failure_reason)

      parsed = _parse_tool_call_response(body)

      # If the parser returned a synthetic veto with a "responder_malformed"
      # reason, retry once. Real vetoes (with GPT-supplied reason text)
      # and other valid responses pass through immediately.
      is_synthetic_malformed = (
        parsed.kind == "veto"
        and isinstance(parsed.reason, str)
        and parsed.reason.startswith("responder_malformed")
      )
      if is_synthetic_malformed and attempt == 0:
        last_failure_reason = parsed.reason or "responder_malformed"
        _emit_responder_diag("RESPONDER_RETRY_ATTEMPTED",
                             attempt=attempt + 1,
                             reason=last_failure_reason)
        continue

      return parsed

    # Loop exhausted (defensive — the inner branches above handle
    # every termination case explicitly).
    _emit_responder_diag("RESPONDER_RETRY_EXHAUSTED",
                         attempt=2, reason=last_failure_reason)
    return veto_proposal(reason=f"responder_retry_exhausted:{last_failure_reason}")

  return responder


__all__ = [
  "make_amalgamated_responder",
  "render_mirror_for_proposal",
]
