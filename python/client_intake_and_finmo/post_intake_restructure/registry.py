"""In-process registry for the ACTIVE restructure directive.

WHY PROCESS MEMORY AND NOT THE DRAFT ROW: the pipeline's own stage
persists (persist_post_intake_execution_state) rebuild
repair_guidance_json with a fresh default payload at every stage
boundary — a directive persisted to the draft row is wiped within
seconds of the re-run starting, before the initial grid can read it.
The restructure loop and the solver re-run it triggers always live in
the SAME process and the SAME request, so process memory is the
correct home for the ACTIVE directive; repair_guidance_json keeps the
permanent audit record only (the post-loop persist, which no pipeline
persist follows).

The registry is keyed by draft_id. It is populated ONLY by the
restructure stage immediately before a solver re-run and cleared in
its finally block — a viable business never has an entry, so the
initial-grid loader is a no-op for every normal run.
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Dict, Optional

_LOCK = threading.Lock()
_ACTIVE: Dict[str, Dict[str, Any]] = {}


def set_active_directive(draft_id: str, directive: Dict[str, Any]) -> None:
  key = str(draft_id or "").strip()
  if not key or not isinstance(directive, dict):
    return
  with _LOCK:
    _ACTIVE[key] = copy.deepcopy(directive)


def get_active_directive(draft_id: str) -> Optional[Dict[str, Any]]:
  key = str(draft_id or "").strip()
  with _LOCK:
    found = _ACTIVE.get(key)
    return copy.deepcopy(found) if isinstance(found, dict) else None


def clear_active_directive(draft_id: str) -> None:
  key = str(draft_id or "").strip()
  with _LOCK:
    _ACTIVE.pop(key, None)
