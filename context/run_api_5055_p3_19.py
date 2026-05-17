"""Phase 9 P3.19 launcher — fresh API on 5055 with the rate fix
(commit 758fa9f) and all earlier P3.16/P3.17 fail-fasts active."""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"

if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

os.environ["CONVERGENCE_TEST_MODE"] = "true"
os.environ.setdefault("FLASK_RUN_PORT", "5055")
os.environ.setdefault("PORT", "5055")

from api import app  # noqa: E402


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)
