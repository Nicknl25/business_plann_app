"""Phase 9 P3.17 E2E test launcher.

Brings up a dedicated API server on port 5052 with the new
accounting_equation_violation fail-fast active. CONVERGENCE_TEST_MODE
is forced on so the new Type 2 machinery fail-fast actually raises
rather than returning a status dict.
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
os.environ.setdefault("FLASK_RUN_PORT", "5052")
os.environ.setdefault("PORT", "5052")

from api import app  # noqa: E402


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5052, debug=False, use_reloader=False)
