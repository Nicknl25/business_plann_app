from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List


def create_checkpoint(*, repo_root: Path, targets: Iterable[str], checkpoint_dir: Path) -> str:
  checkpoint_dir.mkdir(parents=True, exist_ok=True)
  files: List[Dict[str, str]] = []
  for target in sorted(set(str(item).replace("\\", "/").strip() for item in targets if str(item).strip())):
    file_path = repo_root / target
    if not file_path.exists():
      continue
    backup_name = target.replace("/", "__")
    backup_path = checkpoint_dir / backup_name
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")
    files.append({"target": target, "backup_path": str(backup_path)})
  manifest = {"files": files}
  manifest_path = checkpoint_dir / "manifest.json"
  manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
  return str(manifest_path)


def restore_checkpoint(*, repo_root: Path, manifest_path: str) -> List[str]:
  path = Path(str(manifest_path or "")).resolve()
  if not path.exists():
    return []
  try:
    manifest = json.loads(path.read_text(encoding="utf-8"))
  except Exception:
    return []
  restored: List[str] = []
  for item in manifest.get("files") or []:
    if not isinstance(item, dict):
      continue
    target = str(item.get("target") or "").replace("\\", "/").strip()
    backup_path = Path(str(item.get("backup_path") or "")).resolve()
    if not target or not backup_path.exists():
      continue
    file_path = repo_root / target
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
    restored.append(target)
  return restored
