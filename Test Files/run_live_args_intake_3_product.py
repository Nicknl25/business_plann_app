import importlib.util
import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
TARGET = THIS_DIR / "run_live_args_intake.py"


def _load_target():
  spec = importlib.util.spec_from_file_location("run_live_args_intake_3p", str(TARGET))
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load {TARGET}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


if __name__ == "__main__":
  mod = _load_target()
  raise SystemExit(mod.main(sys.argv[1:], forced_product_count=3))
