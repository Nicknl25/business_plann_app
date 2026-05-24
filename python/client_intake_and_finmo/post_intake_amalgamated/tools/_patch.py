"""Shared deep-merge helper for the ``revise_*`` partial-patch tools.

The cascade's revision step (spec §13.1) takes a currently-committed section
artifact (contract / payload / anchors / overrides) plus a sparse ``patch``
and produces a candidate the corresponding ``set_*`` tool can validate.

The merge rules are deliberately mechanical:

  - Mappings merge recursively (overlay keys win at each leaf).
  - Lists / scalars in the overlay replace the base verbatim (no per-element
    rules — a caller that wants to patch a specific list entry passes the
    full list).
  - Keys present only in the base are preserved unchanged.

The keys actually written by the patch are recorded as a flat list of
dotted-paths so audit log rows and authoring-tool envelopes can echo
``patch_applied: ["drivers.COGS", "drivers.Marketing", ...]``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Tuple


def deep_merge_patch(
  base: Any,
  patch: Any,
) -> Tuple[Any, List[str]]:
  """Return ``(merged, applied_paths)``.

  ``base`` is the currently committed payload (typically a Dict). ``patch``
  is the sparse overlay. ``applied_paths`` lists every leaf the patch touched
  in dotted form (``"section.lever.q11"``) so the caller can write one
  audit row per applied key.

  Both inputs are treated as immutable — the returned object is a fresh
  deepcopy.
  """
  applied: List[str] = []
  merged = _merge(copy.deepcopy(base), patch, prefix=(), applied=applied)
  return merged, applied


def _merge(base: Any, patch: Any, *, prefix: Tuple[str, ...], applied: List[str]) -> Any:
  if isinstance(patch, dict):
    if not isinstance(base, dict):
      # The overlay is a Dict but the base wasn't — overlay replaces base.
      for k, v in patch.items():
        applied.append(".".join(prefix + (str(k),)))
      return copy.deepcopy(patch)
    result: Dict[Any, Any] = dict(base)
    for k, v in patch.items():
      sub_prefix = prefix + (str(k),)
      if isinstance(v, dict) and isinstance(result.get(k), dict):
        result[k] = _merge(result[k], v, prefix=sub_prefix, applied=applied)
      else:
        result[k] = copy.deepcopy(v)
        applied.append(".".join(sub_prefix))
    return result
  # Non-dict patch overrides base at this prefix wholesale.
  applied.append(".".join(prefix) if prefix else "<root>")
  return copy.deepcopy(patch)


__all__ = ["deep_merge_patch"]
