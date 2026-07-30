"""Local dev launcher: run the Flask app WITHOUT the debug reloader.

The reloader's re-exec'd child was hanging on this machine; importing the app
and calling app.run(use_reloader=False) binds in-process. Committed because
scripts/start_persona_backend.ps1 (the persona-stack launch chain) requires it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "python"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import api  # noqa: E402  -- constructs module-level `app`

if __name__ == "__main__":
    port = int(os.getenv("PORT") or 5050)
    api.app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
