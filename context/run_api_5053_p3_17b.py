"""Phase 9 P3.17 Phase 3b + rerun launcher.

Brings up a dedicated API server on port 5053 with the Phase 3b
stored_totals_match_components fail-fast active (in addition to
Phase 2's accounting_equation_violation fail-fast). Separate
port so a long-running 5052 process can stay up if needed.
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
os.environ.setdefault("FLASK_RUN_PORT", "5053")
os.environ.setdefault("PORT", "5053")

from api import app  # noqa: E402


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5053, debug=False, use_reloader=False)
