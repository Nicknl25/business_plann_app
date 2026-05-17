"""Phase 9 P3.11 — Payroll validator-code translator.

Converts the token-formatted error codes returned by
:func:`validate_payroll_headcount_payload` (Layer A.2) into
structured failure objects GPT can read during iterative refinement.

Per the iter 19 doctrine (docs/architecture/doctrine.md §1 — GPT
as authoring source for payroll) and the P3.11 directive: payroll is
GPT-authored, and the iterative refinement loop runs GPT up to 10
rounds against structured validator feedback. The translator is the
shape layer between Python validators and GPT's next-round input.

Scope (Option A per P3.11 design):
- Layer A.2 codes ONLY — the `payroll_headcount_*` token format
  produced by ``validate_payroll_headcount_payload`` in
  ``post_intake_headcount/lookup.py``.
- Layer A.1 (contract-table prose errors) and Layer A.3 (economic
  feasibility violations) are routed to GPT through separate
  feedback paths; they do NOT pass through this translator.

Fail-fast invariant: any code that reaches the translator and does
not match a registered pattern raises
``PostIntakePreconditionFailed`` with
``operation=payroll_validator_translator_unmatched_code``. An
unmatched code indicates either a new validator code was added
without a corresponding translator pattern, or a non-Layer-A.2 code
was misrouted into the translator. Either way, the iteration
mechanics are broken and must be repaired before retrying — the
silent fallback to verbatim tokens would leave GPT unable to refine
that failure class, and the iterative refinement system would
silently degrade.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.fail_fast.common import (  # type: ignore
  PostIntakePreconditionFailed,
)


# ---------------------------------------------------------------------------
# Pattern definitions.
#
# Order matters where two patterns could match the same code; the
# evaluation loop runs more-specific patterns first.
# ---------------------------------------------------------------------------


# Pattern 6 — structural codes with no embedded values.
_STRUCTURAL_CODES = frozenset({
  "payroll_headcount_payload_not_object",
  "payroll_headcount_rows_not_array",
  "payroll_headcount_quarter_totals_not_array",
  "payroll_headcount_horizon_mismatch",
  "payroll_headcount_quarter_totals_missing_required_quarters",
  "payroll_headcount_contract_version_mismatch",
})


# Pattern 6 (with embedded values that are self-describing — kept as
# "structural" category because the value IS the diagnostic, not a
# field GPT can directly amend).
_PATTERN_DECISION_SOURCE_MISMATCH = re.compile(
  r"^payroll_headcount_decision_source_mismatch:expected=(?P<expected>.+)$"
)
_PATTERN_ECONOMIC_BASIS_MISMATCH = re.compile(
  r"^payroll_headcount_economic_basis_mismatch:expected=(?P<expected>.+?):actual=(?P<actual>.+)$"
)
_PATTERN_QUARTER_TOTALS_HORIZON = re.compile(
  r"^payroll_headcount_quarter_totals_must_cover_contract_horizon:(?P<n>\d+)$"
)
_PATTERN_FORBIDDEN_TEXT_FIELD = re.compile(
  r"^payroll_headcount_(?P<issue>forbidden_text_field|unapproved_text_field):(?P<path>.+)$"
)


# Pattern 5 — title lifecycle.
_PATTERN_DEAD_SUPPORT_TITLE = re.compile(
  r"^payroll_headcount_dead_support_title:(?P<label>.+)$"
)
_PATTERN_SUPPORT_TITLE_MISSING = re.compile(
  r"^payroll_headcount_support_title_missing_after_start:(?P<label>.+?):q(?P<quarter>\d+)$"
)
_PATTERN_SUPPORT_TITLE_STOPS = re.compile(
  r"^payroll_headcount_support_title_stops_after_start:(?P<label>.+?):q(?P<quarter>\d+)$"
)


# Pattern 4 — per-row field issues. Two sub-patterns:
#   ROW_GENERIC catches issues with literal multi-word names
#   (missing_oews_occ_title, fte_math_mismatch, etc.) — must run
#   before ROW_FORMAT to keep field naming accurate.
#   ROW_FORMAT catches the {issue}_{field}:{path} shape from
#   _validate_schedule_row's numeric-field loop.
_PATTERN_ROW_GENERIC = re.compile(
  r"^payroll_headcount_(?P<issue>row_not_object|invalid_quarter_index|missing_oews_occ_title|missing_resolved_annual_wage|missing_wage_source|fte_math_mismatch):(?P<path>.+)$"
)
_PATTERN_ROW_FORMAT = re.compile(
  r"^payroll_headcount_(?P<issue>non_numeric|negative|currency_not_integer)_(?P<field>.+?):(?P<path>.+)$"
)


# Quarter-total variants (Pattern 4 sub-class).
_PATTERN_QUARTER_TOTAL_FIELD = re.compile(
  r"^payroll_headcount_quarter_total_(?P<issue>missing|negative)_(?P<field>.+?):(?P<index>.+)$"
)
_PATTERN_QUARTER_TOTAL = re.compile(
  r"^payroll_headcount_quarter_total_(?P<issue>not_object|invalid_quarter|payroll_not_integer):(?P<index>.+)$"
)


# Pattern 1 — out-of-range numeric.
_PATTERN_OUT_OF_POLICY_RANGE = re.compile(
  r"^payroll_headcount_(?P<field>.+?)_out_of_policy_range:value=(?P<value>[^:]+):min=(?P<min>[^:]+):max=(?P<max>[^:]+)$"
)
_PATTERN_OUT_OF_TIER_BOUNDS = re.compile(
  r"^payroll_headcount_(?P<field>.+?)_out_of_tier_bounds:value=(?P<value>[^:]+):tier=(?P<tier>[^:]+):min=(?P<min>[^:]+):max=(?P<max>[^:]+)$"
)


# Pattern 3 — invalid enum value. Suffix `_invalid:` with the value
# after.
_PATTERN_INVALID_ENUM = re.compile(
  r"^payroll_headcount_(?P<field>.+?)_invalid:(?P<value>.*)$"
)


# Pattern 2 — missing required field. Anchored at end-of-string so it
# does NOT collide with row codes that embed `missing_` as part of the
# issue name (e.g., `missing_oews_occ_title:rows[3]`).
_PATTERN_MISSING = re.compile(
  r"^payroll_headcount_(?P<field>.+?)_missing$"
)


# Required keys every structured failure object must carry.
_REQUIRED_FAILURE_KEYS = frozenset({"code", "category"})


def translate_payroll_validator_codes(
  codes: List[str],
) -> Dict[str, Any]:
  """Translate ``validate_payroll_headcount_payload`` codes into
  structured failure objects.

  Returns ``{"structured_failures": [...], "unmatched_codes": []}``.
  Raises :class:`PostIntakePreconditionFailed` if any code does not
  match a registered pattern.
  """
  structured_failures: List[Dict[str, Any]] = []
  unmatched: List[str] = []

  for raw in codes or []:
    code = str(raw or "").strip()
    if not code:
      continue
    parsed = _translate_one(code)
    if parsed is None:
      unmatched.append(code)
      continue
    structured_failures.append(parsed)

  if unmatched:
    raise PostIntakePreconditionFailed(
      operation="payroll_validator_translator_unmatched_code",
      pipeline_stage="payroll_iterative_refinement",
      expected=(
        "every code returned by validate_payroll_headcount_payload "
        "matches a translator pattern"
      ),
      actual=f"{len(unmatched)} code(s) did not match any pattern",
      details={
        "unmatched_codes": unmatched[:20],
        "remediation": (
          "Either validate_payroll_headcount_payload added a new "
          "code class without updating "
          "payroll_validator_translator.py, or a non-Layer-A.2 "
          "code was routed into the translator (e.g., a "
          "contract-table prose error from Layer A.1). Update the "
          "translator's patterns to cover the new code shape or "
          "fix the dispatch in the iterative refinement loop. Do "
          "NOT silently fall back to verbatim tokens — the "
          "iterative refinement system relies on structured "
          "failure objects GPT can read."
        ),
      },
    )

  # Invariant #4: translator output well-formed.
  for failure in structured_failures:
    if not isinstance(failure, dict):
      raise PostIntakePreconditionFailed(
        operation="payroll_validator_translator_malformed_output",
        pipeline_stage="payroll_iterative_refinement",
        expected="every structured_failure entry is a dict",
        actual=f"got {type(failure).__name__}",
        details={"structured_failures_sample": structured_failures[:5]},
      )
    missing_keys = _REQUIRED_FAILURE_KEYS - set(failure.keys())
    if missing_keys:
      raise PostIntakePreconditionFailed(
        operation="payroll_validator_translator_malformed_output",
        pipeline_stage="payroll_iterative_refinement",
        expected=f"every structured_failure carries {sorted(_REQUIRED_FAILURE_KEYS)}",
        actual=f"missing keys {sorted(missing_keys)} in {failure!r}",
        details={"failure": failure},
      )

  return {
    "structured_failures": structured_failures,
    "unmatched_codes": [],
  }


def _coerce_number(raw: str) -> Any:
  s = str(raw or "").strip()
  try:
    if "." in s:
      return float(s)
    return int(s)
  except Exception:
    try:
      return float(s)
    except Exception:
      return s


def _translate_one(code: str) -> Optional[Dict[str, Any]]:
  """Dispatch one code to its translator pattern. Returns None when
  no pattern matches."""
  if code in _STRUCTURAL_CODES:
    return {
      "code": code,
      "category": "structural",
      "diagnostic": code,
    }

  m = _PATTERN_DECISION_SOURCE_MISMATCH.match(code)
  if m:
    return {
      "code": code,
      "category": "structural",
      "diagnostic": code,
      "context": {"expected_decision_source": m.group("expected")},
    }

  m = _PATTERN_ECONOMIC_BASIS_MISMATCH.match(code)
  if m:
    return {
      "code": code,
      "category": "structural",
      "diagnostic": code,
      "context": {
        "expected": m.group("expected"),
        "actual": m.group("actual"),
      },
    }

  m = _PATTERN_QUARTER_TOTALS_HORIZON.match(code)
  if m:
    return {
      "code": code,
      "category": "structural",
      "diagnostic": code,
      "context": {"expected_horizon": int(m.group("n"))},
    }

  m = _PATTERN_FORBIDDEN_TEXT_FIELD.match(code)
  if m:
    return {
      "code": code,
      "category": "structural",
      "diagnostic": code,
      "issue_type": m.group("issue"),
      "row_path": m.group("path"),
    }

  m = _PATTERN_SUPPORT_TITLE_MISSING.match(code)
  if m:
    return {
      "code": code,
      "field": "payroll_headcount_grid",
      "category": "title_lifecycle",
      "title_label": m.group("label"),
      "quarter": int(m.group("quarter")),
    }

  m = _PATTERN_SUPPORT_TITLE_STOPS.match(code)
  if m:
    return {
      "code": code,
      "field": "payroll_headcount_grid",
      "category": "title_lifecycle",
      "title_label": m.group("label"),
      "quarter": int(m.group("quarter")),
    }

  m = _PATTERN_DEAD_SUPPORT_TITLE.match(code)
  if m:
    return {
      "code": code,
      "field": "payroll_headcount_grid",
      "category": "title_lifecycle",
      "title_label": m.group("label"),
    }

  m = _PATTERN_QUARTER_TOTAL_FIELD.match(code)
  if m:
    return {
      "code": code,
      "field": f"quarter_totals[].{m.group('field')}",
      "category": "row_issue",
      "issue_type": m.group("issue"),
      "row_path": f"quarter_totals[{m.group('index')}]",
    }

  m = _PATTERN_QUARTER_TOTAL.match(code)
  if m:
    return {
      "code": code,
      "field": "quarter_totals",
      "category": "row_issue",
      "issue_type": m.group("issue"),
      "row_path": f"quarter_totals[{m.group('index')}]",
    }

  m = _PATTERN_ROW_GENERIC.match(code)
  if m:
    return {
      "code": code,
      "field": _row_generic_field(m.group("issue")),
      "category": "row_issue",
      "issue_type": m.group("issue"),
      "row_path": m.group("path"),
    }

  m = _PATTERN_OUT_OF_POLICY_RANGE.match(code)
  if m:
    return {
      "code": code,
      "field": m.group("field"),
      "category": "out_of_range",
      "actual_value": _coerce_number(m.group("value")),
      "required_range": [_coerce_number(m.group("min")), _coerce_number(m.group("max"))],
      "context": {},
    }

  m = _PATTERN_OUT_OF_TIER_BOUNDS.match(code)
  if m:
    return {
      "code": code,
      "field": m.group("field"),
      "category": "out_of_range",
      "actual_value": _coerce_number(m.group("value")),
      "required_range": [_coerce_number(m.group("min")), _coerce_number(m.group("max"))],
      "context": {"tier": m.group("tier")},
    }

  m = _PATTERN_ROW_FORMAT.match(code)
  if m:
    return {
      "code": code,
      "field": m.group("field"),
      "category": "row_issue",
      "issue_type": m.group("issue"),
      "row_path": m.group("path"),
    }

  m = _PATTERN_INVALID_ENUM.match(code)
  if m:
    return {
      "code": code,
      "field": m.group("field"),
      "category": "invalid_enum",
      "actual_value": m.group("value"),
    }

  m = _PATTERN_MISSING.match(code)
  if m:
    return {
      "code": code,
      "field": m.group("field"),
      "category": "missing",
    }

  return None


def _row_generic_field(issue: str) -> str:
  """Map ROW_GENERIC issue strings back to the underlying field they
  describe."""
  mapping = {
    "row_not_object": "row",
    "invalid_quarter_index": "quarter_index",
    "missing_oews_occ_title": "oews_occ_title",
    "missing_resolved_annual_wage": "annual_wage",
    "missing_wage_source": "wage_source",
    "fte_math_mismatch": "starting_fte+hires=ending_fte",
  }
  return mapping.get(issue, issue)
