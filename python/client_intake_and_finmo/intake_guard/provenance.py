"""PROVENANCE, NOT INFERENCE (Nick 2026-09-12).

A write is authorised when it came from one of four origins, and the
guard is told which. Anything else is a leak.

  router_patch        the client's stated figure, in the patch door A allowed
  option_pick         an option the client picked by id and the engine priced;
                      its writes are in the walk's lever-writes record
  guard_rewrite       the guard's own correction, with its receipt
  estimator_baseline  the marketing estimator's bookkeeping (baseline and
                      adjustment); the engine reads the total, which is the
                      client's stated figure - "bookkeeping rather than a
                      wrong number" (Nick), never a leak, never a rewrite

The old watcher diffed the store and had to guess; the guard does not.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

ROUTER_PATCH = "router_patch"
OPTION_PICK = "option_pick"
GUARD_REWRITE = "guard_rewrite"
ESTIMATOR_BASELINE = "estimator_baseline"
AUTHORISED_ORIGINS = (ROUTER_PATCH, OPTION_PICK, GUARD_REWRITE, ESTIMATOR_BASELINE)

# the estimator's own fields: stamped from the marketing model, never a client figure
ESTIMATOR_OWNED_FIELDS = frozenset({
  "baseline_marketing", "baseline_marketing_percent", "marketing_adjustment",
  "marketing_intensity", "marketing_basis_summary",
})


def _leaf(field: str) -> str:
  return str(field or "").split(".")[-1]


def origin_of(field: str, *, allowed_patch: Optional[Dict[str, Any]] = None, lever_writes: Optional[Dict[str, Any]] = None,
              guard_rewrites: Optional[Iterable[str]] = None) -> Optional[str]:
  """Which authorised origin a written field came from, or None (a leak)."""
  f = str(field or "")
  leaf = _leaf(f)
  if leaf in ESTIMATOR_OWNED_FIELDS:
    return ESTIMATOR_BASELINE
  if allowed_patch and (f in allowed_patch or any(_leaf(k) == leaf for k in allowed_patch)):
    return ROUTER_PATCH
  if lever_writes and (f in lever_writes or leaf in lever_writes or any(str(k).endswith(":" + leaf) for k in lever_writes)):
    return OPTION_PICK
  if guard_rewrites and (f in guard_rewrites or leaf in {_leaf(g) for g in guard_rewrites}):
    return GUARD_REWRITE
  return None


def is_authorised(field: str, **ctx: Any) -> bool:
  return origin_of(field, **ctx) is not None


def never_rewrite(field: str) -> bool:
  """Door A must not touch the estimator's bookkeeping: it is not a client
  figure, so there are no client words to carry it."""
  return _leaf(field) in ESTIMATOR_OWNED_FIELDS
