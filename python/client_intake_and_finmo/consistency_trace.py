from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TextIO


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_TRACE_LOG_DIR = Path(r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Terminal Logs")
_THREAD_STATE = threading.local()


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _read_root_env_value(name: str) -> str:
  try:
    raw_text = ROOT_ENV_PATH.read_text(encoding="utf-8")
  except Exception:
    return ""
  target = str(name or "").strip()
  if not target:
    return ""
  for raw_line in raw_text.splitlines():
    line = str(raw_line or "").strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, value = line.split("=", 1)
    if str(key or "").strip() != target:
      continue
    clean_value = str(value or "").strip()
    if len(clean_value) >= 2 and clean_value[0] == clean_value[-1] and clean_value[0] in {"'", '"'}:
      clean_value = clean_value[1:-1]
    return clean_value
  return ""


def consistency_trace_enabled() -> bool:
  cached = getattr(_THREAD_STATE, "consistency_trace_enabled", None)
  if cached is not None:
    return bool(cached)
  _load_root_env()
  raw = str(_read_root_env_value("CONSISTENCY_TRACE") or os.getenv("CONSISTENCY_TRACE") or "").strip().lower()
  enabled = raw in {"1", "true", "yes", "on"}
  _THREAD_STATE.consistency_trace_enabled = enabled
  return enabled


def _consistency_trace_log_dir() -> Path:
  raw = str(_read_root_env_value("CONSISTENCY_TRACE_DIR") or os.getenv("CONSISTENCY_TRACE_DIR") or "").strip()
  if raw:
    return Path(raw)
  return DEFAULT_TRACE_LOG_DIR


def _normalize_trace_file_name(name: str) -> str:
  raw = str(name or "").strip()
  if not raw:
    return ""
  base_name = Path(raw).name.strip()
  if not base_name:
    return ""
  if not base_name.lower().endswith(".txt"):
    base_name = f"{base_name}.txt"
  return base_name


def _build_trace_log_path() -> Path:
  configured_name = str(getattr(_THREAD_STATE, "consistency_trace_run_name", "") or "").strip()
  if configured_name:
    return _consistency_trace_log_dir() / configured_name
  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  pid = os.getpid()
  thread_id = threading.get_ident()
  return _consistency_trace_log_dir() / f"consistency_trace_{timestamp}_{pid}_{thread_id}.txt"


def configure_consistency_trace_run(name: str, *, reset_file: bool = False) -> None:
  normalized_name = _normalize_trace_file_name(name)
  if not normalized_name:
    return
  current_name = str(getattr(_THREAD_STATE, "consistency_trace_run_name", "") or "").strip()
  if current_name != normalized_name:
    handle = getattr(_THREAD_STATE, "consistency_trace_file_handle", None)
    if handle is not None:
      try:
        handle.close()
      except Exception:
        pass
      delattr(_THREAD_STATE, "consistency_trace_file_handle")
    if hasattr(_THREAD_STATE, "consistency_trace_file_path"):
      delattr(_THREAD_STATE, "consistency_trace_file_path")
  _THREAD_STATE.consistency_trace_run_name = normalized_name
  if reset_file:
    log_path = _consistency_trace_log_dir() / normalized_name
    try:
      log_path.parent.mkdir(parents=True, exist_ok=True)
      log_path.write_text("", encoding="utf-8")
    except Exception:
      pass


def _emit_line(line: str = "") -> None:
  print(line, flush=True)
  handle = _ensure_trace_log_handle()
  if handle is None:
    return
  try:
    handle.write(f"{line}\n")
    handle.flush()
  except Exception:
    pass


def _ensure_trace_log_handle() -> Optional[TextIO]:
  handle = getattr(_THREAD_STATE, "consistency_trace_file_handle", None)
  if handle is not None:
    return handle
  try:
    log_path = _build_trace_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
  except Exception as exc:
    if not getattr(_THREAD_STATE, "consistency_trace_file_error_logged", False):
      _THREAD_STATE.consistency_trace_file_error_logged = True
      print(f"[consistency_trace_file_error] {exc}", flush=True)
    _THREAD_STATE.consistency_trace_file_handle = None
    return None
  _THREAD_STATE.consistency_trace_file_handle = handle
  _THREAD_STATE.consistency_trace_file_path = str(log_path)
  return handle


def _json_safe(value: Any) -> Any:
  if value is None or isinstance(value, (str, int, float, bool)):
    return value
  if isinstance(value, dict):
    return {str(key): _json_safe(val) for key, val in value.items()}
  if isinstance(value, (list, tuple, set)):
    return [_json_safe(item) for item in value]
  return str(value)


def _emit_stage_header(stage: str) -> None:
  current_stage = getattr(_THREAD_STATE, "consistency_trace_stage", None)
  if current_stage == stage:
    return
  _THREAD_STATE.consistency_trace_stage = stage
  _emit_line(f"\n=== CONSISTENCY TRACE :: {stage} ===")


def trace(stage: str, title: str, payload: Optional[Any] = None) -> None:
  if not consistency_trace_enabled():
    return
  _emit_stage_header(str(stage or "TRACE").strip().upper())
  _emit_line(f"[{str(title or 'event').strip()}]")
  if payload is None:
    return
  _emit_line(
    json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=False)
  )


def trace_lazy(stage: str, title: str, producer: Callable[[], Any]) -> None:
  if not consistency_trace_enabled():
    return
  try:
    payload = producer()
  except Exception as exc:
    payload = {"trace_error": str(exc)}
  trace(stage, title, payload)


def trace_values(stage: str, title: str, **values: Any) -> None:
  if not consistency_trace_enabled():
    return
  trace(stage, title, values)


def trace_before_after(stage: str, title: str, *, before: Any, after: Any) -> None:
  if not consistency_trace_enabled():
    return
  trace(stage, title, {"before": before, "after": after})


def reset_consistency_trace_stage() -> None:
  handle = getattr(_THREAD_STATE, "consistency_trace_file_handle", None)
  if handle is not None:
    try:
      handle.close()
    except Exception:
      pass
    delattr(_THREAD_STATE, "consistency_trace_file_handle")
  if hasattr(_THREAD_STATE, "consistency_trace_file_path"):
    delattr(_THREAD_STATE, "consistency_trace_file_path")
  if hasattr(_THREAD_STATE, "consistency_trace_file_error_logged"):
    delattr(_THREAD_STATE, "consistency_trace_file_error_logged")
  if hasattr(_THREAD_STATE, "consistency_trace_stage"):
    delattr(_THREAD_STATE, "consistency_trace_stage")
  if hasattr(_THREAD_STATE, "consistency_trace_enabled"):
    delattr(_THREAD_STATE, "consistency_trace_enabled")
