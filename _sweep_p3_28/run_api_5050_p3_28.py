"""Phase 9 P3.28 28-draft empirical sweep API launcher.

Brings up the Flask backend with CONVERGENCE_TEST_MODE=true on port
5050 for the P3.28 sweep harness. Same pattern as P3.23 sweep launcher.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"

if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

os.environ["CONVERGENCE_TEST_MODE"] = "true"
os.environ.setdefault("FLASK_RUN_PORT", "5050")
os.environ.setdefault("PORT", "5050")

from api import app  # noqa: E402


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)
