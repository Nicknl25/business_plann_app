"""Safe runtime binding for extracted post-intake modules.

The API handler may still provide shared helper functions during the transition
out of ``intake_consult.py``. It must not provide deterministic post-intake
authority such as contracts, mapping constants, horizons, prompt paths, or cash
policy values. Those come from SQL lookup tables and post-intake modules.
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping


def _is_upper_authority_name(name: str) -> bool:
  text = str(name or "").strip()
  if not text:
    return False
  letters = [char for char in text if char.isalpha()]
  return bool(letters) and all(char.isupper() for char in letters)


def table_safe_runtime_bindings(dependencies: Dict[str, Any]) -> Dict[str, Any]:
  """Return handler-provided bindings that cannot override table authority."""
  if not isinstance(dependencies, dict):
    return {}
  safe: Dict[str, Any] = {}
  for key, value in dependencies.items():
    name = str(key or "").strip()
    if not name or name == "bind_runtime_dependencies":
      continue
    if _is_upper_authority_name(name):
      continue
    safe[name] = value
  return safe


def bind_table_safe_runtime_dependencies(
  module_globals: MutableMapping[str, Any],
  dependencies: Dict[str, Any],
) -> None:
  """Bind only non-authority runtime helpers into a post-intake module."""
  module_globals.update(table_safe_runtime_bindings(dependencies))


__all__ = [
  "bind_table_safe_runtime_dependencies",
  "table_safe_runtime_bindings",
]
