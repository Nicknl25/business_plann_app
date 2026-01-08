import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator


_LOGGER = logging.getLogger("llm_timing")
_CONFIGURED = False


def timing_enabled() -> bool:
  if (os.getenv("INTAKE_DEBUG_LOGS") or "").strip().lower() in ("1", "true", "yes", "y", "on"):
    return False
  raw = (os.getenv("LLM_TIMING") or os.getenv("INTAKE_TIMING") or "").strip().lower()
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
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.propagate = False
  except Exception:
    pass


def _sanitize_value(value: Any) -> str:
  s = " ".join(str(value).split())
  if len(s) > 300:
    return s[:297] + "..."
  return s


def _sanitize_fields(fields: Dict[str, Any]) -> str:
  if not fields:
    return ""
  parts = []
  for key in sorted(fields.keys(), key=lambda x: str(x).lower()):
    parts.append(f"{str(key)}={_sanitize_value(fields[key])}")
  return " ".join(parts)


def log_timing(name: str, *, ms: int, **fields: Any) -> None:
  if not timing_enabled():
    return
  _ensure_configured()
  extra = _sanitize_fields(fields)
  if extra:
    _LOGGER.info("timing name=%s ms=%d %s", str(name or ""), int(ms), extra)
  else:
    _LOGGER.info("timing name=%s ms=%d", str(name or ""), int(ms))


@contextmanager
def timed_span(name: str, **fields: Any) -> Iterator[None]:
  if not timing_enabled():
    yield
    return
  start = time.perf_counter()
  try:
    yield
  finally:
    ms = int((time.perf_counter() - start) * 1000)
    log_timing(name, ms=ms, **fields)
