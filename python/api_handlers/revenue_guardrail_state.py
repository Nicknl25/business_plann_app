from __future__ import annotations

from typing import Dict, Optional


_ACKED_SIGNATURES: Dict[str, str] = {}


def acknowledge_signature(draft_id: str, signature: str) -> None:
  draft_id = str(draft_id or "").strip()
  signature = str(signature or "").strip()
  if not draft_id or not signature:
    return
  _ACKED_SIGNATURES[draft_id] = signature


def get_acknowledged_signature(draft_id: str) -> Optional[str]:
  draft_id = str(draft_id or "").strip()
  if not draft_id:
    return None
  return _ACKED_SIGNATURES.get(draft_id)
