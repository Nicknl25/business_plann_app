from __future__ import annotations

"""
Thin HTTP wrappers for the unified intake consult.

The implementation lives in `python/client_intake_and_finmo/unified_intake/controller.py`
so model math, persistence, and orchestration can evolve independently of Flask routing.
"""

try:
  from unified_intake.controller import (  # type: ignore
    get_intake_consult_draft_handler,
    post_intake_consult_handler,
    post_intake_consult_session_handler,
  )
except Exception as exc:  # pragma: no cover
  # In most runtime paths, `python/client_intake_and_finmo` is added to sys.path by `api.create_app()`.
  # If this module is imported in isolation, surface a clear import error.
  raise RuntimeError(f"Failed to import unified intake controller: {exc}") from exc

