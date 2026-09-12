"""The observation vocabulary - CLASSES of defect, not the instances seen on
12 September. Every observation the watcher files carries one of these
kinds; a kind names who detects it (code, the model, or both) so a filing
is never a guess dressed as a fact.

Nick: "Design for what hasn't happened yet - a value that moved with no
message causing it, a receipt that disagrees with the store, an intake
completing with a hold open, a figure the client stated that appears
nowhere."
"""
from __future__ import annotations

from typing import Dict, Tuple

CODE = "code"
MODEL = "model"
BOTH = "both"

BLOCKER = "blocker"
MAJOR = "major"
MINOR = "minor"

# kind -> (severity, detector, one-line meaning)
KINDS: Dict[str, Tuple[str, str, str]] = {
  # ---- the store disagrees with the client's words
  "unit_copied": (BLOCKER, CODE,
    "a figure the client stated in one time basis landed in a field declared in another, unconverted"),
  "figure_unplaced": (MAJOR, CODE,
    "a figure the client stated appears in no stored leaf after the turn and the app did not ask about it"),
  "correction_ignored": (BLOCKER, BOTH,
    "the client restated the same figure or correction and nothing in the store moved"),
  "refusal_violated": (BLOCKER, BOTH,
    "a cost or lever the client refused was moved anyway"),
  "figure_misread": (MAJOR, MODEL,
    "the app read a number out of the client's words that the client did not say (nine hundred thousand -> 900)"),
  "unstated_figure_in_basis": (MAJOR, BOTH,
    "a figure with no client statement behind it sits where a client-stated figure should (invented roles' wages in payroll)"),
  # ---- the store disagrees with itself or with the receipt
  "value_moved_without_cause": (BLOCKER, CODE,
    "a stored leaf changed on a turn whose message carried no figure and whose reply does not account for the move"),
  "receipt_disagrees_with_store": (BLOCKER, CODE,
    "the reply's receipt states a value the store does not hold"),
  "roster_not_in_basis": (MAJOR, CODE,
    "a person with a wage on the roster is missing from the payroll basis"),
  "basis_sum_mismatch": (MAJOR, CODE,
    "the payroll basis rows do not sum to the stored payroll total"),
  "lever_moved_stated_figure": (BLOCKER, BOTH,
    "a coherence lever moved a client-stated figure without the client's stated agreement"),
  # ---- the conversation did not do what the client asked
  "intent_unmet": (MAJOR, MODEL,
    "the client asked to stop, skip, move on, or wrap up and the app did something else"),
  "question_unanswered": (MINOR, MODEL,
    "the client asked a question and the reply did not answer it"),
  "reply_repeated": (MAJOR, CODE,
    "the app sent a reply identical to an earlier one in this intake"),
  "loop": (MAJOR, CODE,
    "the app asked the same question three or more times"),
  "raw_field_name_shown": (MAJOR, CODE,
    "the client was shown a machine field name"),
  # ---- a section closed or the intake completed with a hole
  "required_field_empty_at_wrap": (BLOCKER, CODE,
    "a section closed with a field the submit gate requires still empty"),
  "completed_with_hold_open": (BLOCKER, CODE,
    "the intake completed while a hold or a pending question was still open"),
  # ---- coherence offered or recommended something it should not
  "recommendation_not_largest": (MAJOR, CODE,
    "the recommended option closes less of the gap than another qualifying option"),
  "option_touches_refusal": (BLOCKER, CODE,
    "an offered option moves a cost or lever the client refused"),
}


def severity_of(kind: str) -> str:
  return KINDS.get(kind, (MINOR, CODE, ""))[0]


def detector_of(kind: str) -> str:
  return KINDS.get(kind, (MINOR, CODE, ""))[1]


MODEL_KINDS = tuple(k for k, v in KINDS.items() if v[1] in (MODEL, BOTH))
CODE_KINDS = tuple(k for k, v in KINDS.items() if v[1] in (CODE, BOTH))


def observation(kind: str, *, draft_id: str, turn: int, client_words: str = "",
                stored_value=None, expected=None, why: str = "", field: str = "",
                detector: str = "") -> Dict[str, object]:
  """One record. Every field is a fact the reader can check: the client's
  words, the stored value, the expected value, the field, the turn."""
  if kind not in KINDS:
    raise ValueError(f"unknown observation kind: {kind}")
  return {
    "kind": kind,
    "severity": severity_of(kind),
    "detector": detector or detector_of(kind),
    "draft_id": str(draft_id),
    "turn": int(turn),
    "field": str(field or ""),
    "client_words": str(client_words or "")[:600],
    "stored_value": stored_value,
    "expected": expected,
    "why": str(why or "")[:800],
  }
