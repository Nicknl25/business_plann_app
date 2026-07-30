"""Local dev launcher: run the Flask app WITHOUT the debug reloader.

The reloader's re-exec'd child was hanging on this machine; importing the app
and calling app.run(use_reloader=False) binds in-process. Committed because
scripts/start_persona_backend.ps1 (the persona-stack launch chain) requires it.
"""
import os
import sys

# Self-redirect stdout+stderr when BPLAN_SERVER_LOG is set (persona-stack
# launch). fd-level dup2 so every write lands in one file — replaces the
# former `cmd /c ... >> log 2>&1` layer, which powershell.exe 5.1's
# Start-Process argument re-quoting broke (cmd exited 1 before opening the
# redirect, so the backend died with no log at all).
_log_path = (os.getenv("BPLAN_SERVER_LOG") or "").strip()
if _log_path:
    _log_handle = open(_log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    # Stream-level reassignment is the guaranteed path: a -WindowStyle Hidden
    # process has no console, so fds 1/2 can be invalid and dup2 raises
    # OSError(9). Reassigning BEFORE `import api` means logging handlers
    # (created in api._configure_logging) bind this handle. dup2 stays as
    # best-effort for any C-level writes.
    sys.stdout = _log_handle
    sys.stderr = _log_handle
    for _fd in (1, 2):
        try:
            os.dup2(_log_handle.fileno(), _fd)
        except OSError:
            pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "python"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import api  # noqa: E402  -- constructs module-level `app`

if __name__ == "__main__":
    port = int(os.getenv("PORT") or 5050)
    api.app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
