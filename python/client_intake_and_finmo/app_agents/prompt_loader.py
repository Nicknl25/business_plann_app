from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(file_name: str) -> str:
  path = PROMPTS_DIR / str(file_name or "").strip()
  return path.read_text(encoding="utf-8").strip()

