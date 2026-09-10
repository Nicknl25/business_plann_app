"""The writing-phase trigger switch - the freeze made REAL (Nick, 2026-09-09).

Why this exists. The writing phase starts on its own from the system-run
success tail (api_handlers/intake_consult.py, _auto_trigger_writing_phase).
Until 2026-09-09 a "freeze" on a client's plan was a request in a handoff
file: Turn A's proof run shipped a FAILED DRAFT docx and an outcome email
into the live client folders DURING a declared freeze. This module is the
code-level switch that tail consults BEFORE it decides anything.

Contract:
  * State lives in ONE gitignored JSON file, FLAG_PATH
    (<repo>/_runtime/writing_phase_trigger.json). No DB, no import-time
    cache: read_state() opens the file every call, so a flip takes effect
    on the very next system run without a :5050 restart.
  * ABSENT file = trigger ON (the default; the writing phase fires as it
    always did). {"trigger": "off"} = FROZEN.
  * A file that exists but cannot be parsed, or names an unknown value, is
    treated as FROZEN (fail-closed: the deal breaker is a plan shipping
    during a freeze, never a plan delayed) and the state says why.
  * Only scripts/writing_phase_freeze.py {on|off|status} writes it. Nick
    reads the one-line ping; he never edits the file.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLAG_PATH = os.path.join(REPO_ROOT, "_runtime", "writing_phase_trigger.json")

TRIGGER_ON = "on"
TRIGGER_OFF = "off"


def _flag_path(path: Optional[str]) -> str:
  return path or FLAG_PATH


def read_state(path: Optional[str] = None) -> Dict[str, Any]:
  """Read the switch NOW. Never raises; never caches.

  Returns {trigger: on|off, frozen: bool, source: default|file|corrupt,
           set_at, by, note, path, error}.
  """
  fp = _flag_path(path)
  state: Dict[str, Any] = {
    "trigger": TRIGGER_ON, "frozen": False, "source": "default",
    "set_at": None, "by": None, "note": None, "path": fp, "error": None,
  }
  if not os.path.exists(fp):
    return state
  try:
    with open(fp, "r", encoding="utf-8") as fh:
      raw = json.load(fh)
    if not isinstance(raw, dict):
      raise ValueError("flag file is not a JSON object")
    value = str(raw.get("trigger") or "").strip().lower()
    if value not in (TRIGGER_ON, TRIGGER_OFF):
      raise ValueError(f"unknown trigger value {value!r}")
    state.update({
      "trigger": value, "frozen": value == TRIGGER_OFF, "source": "file",
      "set_at": raw.get("set_at"), "by": raw.get("by"), "note": raw.get("note"),
    })
  except Exception as exc:  # fail-closed
    state.update({
      "trigger": TRIGGER_OFF, "frozen": True, "source": "corrupt",
      "error": f"{type(exc).__name__}: {str(exc)[:160]}",
    })
  return state


def is_frozen(path: Optional[str] = None) -> bool:
  return bool(read_state(path)["frozen"])


def set_state(on: bool, *, by: str = "", note: str = "",
              path: Optional[str] = None) -> Dict[str, Any]:
  """Write the switch. on=True -> trigger fires; on=False -> FROZEN."""
  fp = _flag_path(path)
  os.makedirs(os.path.dirname(fp), exist_ok=True)
  payload = {
    "trigger": TRIGGER_ON if on else TRIGGER_OFF,
    "set_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "by": by or os.environ.get("USERNAME") or os.environ.get("USER") or "",
    "note": note or "",
  }
  tmp = fp + ".tmp"
  with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
  os.replace(tmp, fp)
  return read_state(fp)


def one_line(state: Dict[str, Any]) -> str:
  """The single line Nick reads."""
  if state["source"] == "default":
    return ("writing-phase trigger: ON (default - no flag file; the writing "
            "phase fires after every passing system run)")
  if state["source"] == "corrupt":
    return (f"writing-phase trigger: FROZEN (flag file unreadable, treated as "
            f"off - {state['error']}; {state['path']})")
  who = f" by {state['by']}" if state.get("by") else ""
  note = f" - {state['note']}" if state.get("note") else ""
  if state["frozen"]:
    return (f"writing-phase trigger: FROZEN (off since {state['set_at']}{who}"
            f"{note}; system runs still deliver workbooks, no plan is written)")
  return (f"writing-phase trigger: ON (set {state['set_at']}{who}{note}; the "
          f"writing phase fires after every passing system run)")
