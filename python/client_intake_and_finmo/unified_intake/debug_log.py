import logging
import os
from typing import Any, Dict


_LOGGER = logging.getLogger("intake_debug")
_CONFIGURED = False


def debug_enabled() -> bool:
  raw = (os.getenv("INTAKE_DEBUG_LOGS") or "").strip().lower()
  return raw in ("1", "true", "yes", "y", "on")


def _ensure_configured() -> None:
  global _CONFIGURED
  if _CONFIGURED:
    return
  _CONFIGURED = True
  try:
    _LOGGER.setLevel(logging.INFO)
    if _LOGGER.handlers:
      return
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("intake_debug: %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.propagate = False
  except Exception:
    pass


def _sanitize_value(value: Any) -> str:
  s = " ".join(str(value).split())
  if len(s) > 400:
    return s[:397] + "..."
  return s


def _sanitize_fields(fields: Dict[str, Any]) -> str:
  if not fields:
    return ""
  parts = []
  for key in sorted(fields.keys(), key=lambda x: str(x).lower()):
    parts.append(f"{str(key)}={_sanitize_value(fields[key])}")
  return " ".join(parts)


def debug_log(event: str, **fields: Any) -> None:
  if not debug_enabled():
    return
  _ensure_configured()
  extra = _sanitize_fields(fields)
  if extra:
    _LOGGER.info("event=%s %s", str(event or ""), extra)
  else:
    _LOGGER.info("event=%s", str(event or ""))
