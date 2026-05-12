"""Phase 9 P3.10 E2E test launcher.

Brings up a second API server on port 5051 so the running 5050
instance (started before Commits 1-4 landed) is left undisturbed.
This launcher imports api.app AFTER setting the env, so the new
code from Commits 1-4 is loaded along with CONVERGENCE_TEST_MODE=true.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"

if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

# Force test mode for this server instance regardless of .env order.
os.environ["CONVERGENCE_TEST_MODE"] = "true"
os.environ.setdefault("FLASK_RUN_PORT", "5051")
os.environ.setdefault("PORT", "5051")

from api import app  # noqa: E402


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5051, debug=False, use_reloader=False)
