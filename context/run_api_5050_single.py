"""Permanent local API launcher for the autonomous 5050 backend helper."""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"

if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

os.environ.setdefault("FLASK_RUN_PORT", "5050")
os.environ.setdefault("PORT", "5050")

from api import app  # noqa: E402


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False, use_reloader=False)
