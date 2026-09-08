"""THE EDITOR (stage 4, spec 3.3) - one call, same system prompt, same
bundle, the full draft, plus the checker's findings; returns the whole
corrected plan, changing nothing the findings do not name. Then the checker
runs again. Two writer-side calls per plan maximum: if the second check
still fails, the run stops and reports - nothing retries silently.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from . import writer as W

_INSTRUCTION = (
    "\n\n== CURRENT DRAFT (plan.json, your previous submission) ==\n%s"
    "\n\n== CHECKER FINDINGS ==\n%s"
    "\n\n== EDITOR INSTRUCTION ==\n"
    "You are correcting the draft above. Fix every checker finding: an "
    "unresolved number is replaced with the bundle's figure or covered by a "
    "derivation you declare; a note finding is fixed in the notes array; a "
    "vocabulary finding is rewritten so the banned word and the construction "
    "behind it are gone. Change NOTHING the findings do not name - every "
    "other sentence, block, note and derivation returns exactly as it is. "
    "Return the WHOLE corrected plan through submit_plan."
)


def edit_plan(bundle: Dict[str, Any], plan: Dict[str, Any],
              findings: List[str], *, model_family: str
              ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], str]:
    """One corrective call on the same model family as the writer."""
    user = W.build_user(bundle) + _INSTRUCTION % (
        json.dumps(plan, ensure_ascii=False, indent=1),
        "\n".join(findings))
    write = W.WRITERS[model_family]
    return write(bundle, user=user)
