"""DEAD-NET LIVE PROOF SERVER (FIX 2b, 2026-08-16).

Starts the real Flask app on :5050 exactly like _run_server_noreload.py,
with ONE test-only monkeypatch: joint_solver.synthesize_new_line_rows is
wrapped to STRIP the synthesized 'COGS %' row - the pre-FIX-1 searcher
shape - so the restructure net is structurally dead (every rung raises
the identical all-or-nothing ContractViolation, evals=0) on any per-line
COGS draft. Nothing in app code carries a test hook; the patch lives here
and dies with this process. Use ONLY for the fail-loud surface proof;
restart the normal backend (scripts/start_persona_backend.ps1) after.

  $env:BPLAN_SERVER_LOG='C:\dev\business_plann_app\_logs_deadnet_<stamp>.txt'
  .venv\Scripts\python.exe -u "Test Files\_rs_deadnet_live_server.py"
"""
import os
import sys

_log_path = (os.getenv("BPLAN_SERVER_LOG") or "").strip()
if _log_path:
    _log_handle = open(_log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = _log_handle
    sys.stderr = _log_handle
    for _fd in (1, 2):
        try:
            os.dup2(_log_handle.fileno(), _fd)
        except OSError:
            pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "python"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import api  # noqa: E402  -- constructs module-level `app`
from client_intake_and_finmo.post_intake_restructure import joint_solver as _js  # noqa: E402

_real_synth = _js.synthesize_new_line_rows


def _deadnet_synth(*a, **k):
    rows = _real_synth(*a, **k)
    stripped = [r for r in rows if r.get("driver") != "COGS %"]
    print(f"[deadnet-server] synthesize_new_line_rows: {len(rows)} rows -> {len(stripped)} (COGS % stripped)", flush=True)
    return stripped


_js.synthesize_new_line_rows = _deadnet_synth
print("[deadnet-server] PATCHED joint_solver.synthesize_new_line_rows (COGS % row stripped) - TEST SERVER ONLY", flush=True)

if __name__ == "__main__":
    port = int(os.getenv("PORT") or 5050)
    api.app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
