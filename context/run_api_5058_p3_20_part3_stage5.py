"""Phase 9 P3.20 Part 3 Stage 5 launcher — Stages 1-4 combined.

Runs the Flask backend with CONVERGENCE_TEST_MODE=true on port 5058
against the current HEAD (commits ee291e4 + d8c6076 + 599765c +
b20fa18 + d45627e). Used for the Stage 5 E2E verification against
ExpressLogix Shipping Services lease-bearing scenario.
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
os.environ.setdefault("FLASK_RUN_PORT", "5058")
os.environ.setdefault("PORT", "5058")

from api import app  # noqa: E402


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5058, debug=False, use_reloader=False)
