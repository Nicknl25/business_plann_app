import importlib.util
from pathlib import Path
from typing import Optional, List


THIS_DIR = Path(__file__).resolve().parent
SEEDER_PATH = THIS_DIR / "seed_completed_intake_from_scenario.py"


def _load_module():
  spec = importlib.util.spec_from_file_location("seed_completed_intake_args", str(SEEDER_PATH))
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load module from {SEEDER_PATH}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def main(argv: Optional[List[str]] = None) -> int:
  return int(_load_module().main(argv) or 0)


if __name__ == "__main__":
  raise SystemExit(main())
