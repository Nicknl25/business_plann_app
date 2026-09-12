"""Phase 9 P3.20 Part 1 — workbook Model Status fail-fast.

Runs AFTER workbook generation, BEFORE the run is marked complete.
Reads the workbook's `Checks!B2` Model Status cell (computed by
the Checks sheet's invariants: BS balance, CF tie, schedule
bridges, formula-logic diagnostics). If status != "OK", hard-stops
the run with a named diagnostic that explicitly directs the
operator to verify APP state first, not patch workbook formulas.

The doctrine reflected in the diagnostic message: the workbook is
a reflection of the app. When the workbook surfaces a failed
invariant, the FIRST hypothesis is that the app produced the wrong
data; the workbook is just exposing it. Patching workbook formulas
to mask the failure hides the real bug.

A CHECK THAT CANNOT RUN FAILS. IT NEVER PASSES BY DEFAULT.
(writing_phase/checks.py:11, the law written after the CoInitialize
bug of 2026-08-29 - and violated here, on purpose, until 2026-09-11.)

THE INCIDENT (Halvorsen Tide 836c2ca2, 2026-09-11 20:36:29). The
Excel COM recalc raised -2147418111 RPC_E_CALL_REJECTED - Excel
saying BUSY - and this module read it as "Excel isn't installed",
logged "workbook_model_status_check_skipped", and RETURNED. The raw
openpyxl workbook shipped with no cached values and Checks!B2 never
read; it was in the client's inbox four milliseconds later. Two
tests asserted that a workbook with Checks!B2 = "FAIL" should PASS
when the recalc reported an environment error. They are gone.

Nick's ruling, verbatim: "Excel wasn't unreachable. It said 'call
was rejected by callee' - that's BUSY, not ABSENT. The code reads a
transient rejection as 'Excel isn't installed' and skips the gate.
That misreading is the whole defect. And it matters far more than
one workbook, because in production there IS no Excel.
PythonAnywhere is Linux. So the branch written for 'Excel might not
be here' becomes the normal path, and the model-status gate turns
itself off permanently the day we deploy. The engine is the answer,
not the retry. Until then: a rejection is retried, a genuine absence
FAILS the run, and no workbook ships unverified."

THE ENGINES. Recalculation is a list of engines tried in order, not
one Windows-only call with an escape hatch:

  excel_com     Windows only. Opens the workbook in Excel, CalculateFull,
                Save - the delivered file gains cached values. A BUSY
                signal is retried with backoff; absence falls through.
  libreoffice   Everywhere production runs. `soffice --headless
                --convert-to xlsx` recalculates on load - the delivered
                workbooks use twenty standard functions, no volatile ones,
                and carry fullCalcOnLoad=1 (verified by inventory on the
                09-11 deliverables). Verifies on a COPY by default: a
                LibreOffice re-save can alter formatting on a
                client-operable workbook, and the gate's invariant is
                "verified", never "re-saved". write_back=True is available
                for an environment that wants cached values in the file.

An engine reporting a genuine FAILURE (neither busy nor missing) is a
verdict about the workbook and is never laundered by trying the next
engine. Only absence and an exhausted busy signal fall through. When
no engine can run, the gate RAISES.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple, Union

from client_intake_and_finmo.fail_fast.common import (  # type: ignore
  PostIntakePreconditionFailed,
  convergence_test_mode_enabled,
)


_logger = logging.getLogger(__name__)

# EXCEL COM IS ONE-AT-A-TIME (Nick 2026-09-10, going-live prerequisite):
# two request threads driving the one Excel application interleave COM
# calls and the losing thread's Save() silently never runs - the workbook
# ships with formulas and NO CACHED VALUES (the 08-29 defect by another
# route) while the model-status check soft-logs unable-to-evaluate.
# Process-wide mutex; every in-run COM use goes through it. Production
# Linux has no COM at all - the LibreOffice engine below is what runs there.
import threading as _threading
_EXCEL_COM_LOCK = _threading.RLock()


_MODEL_STATUS_OK = "OK"
_CHECKS_SHEET = "Checks"
_MODEL_STATUS_CELL_ROW = 2
_MODEL_STATUS_CELL_COL = 2  # column B

ENGINE_EXCEL_COM = "excel_com"
ENGINE_LIBREOFFICE = "libreoffice"
DEFAULT_ENGINES: Tuple[str, ...] = (ENGINE_EXCEL_COM, ENGINE_LIBREOFFICE)

#: Where a LibreOffice install puts soffice when it is not on PATH.
DEFAULT_SOFFICE_CANDIDATES: Tuple[str, ...] = (
  r"C:\Program Files\LibreOffice\program\soffice.exe",
  r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
  "/usr/bin/soffice",
  "/usr/bin/libreoffice",
  "/usr/lib/libreoffice/program/soffice",
  "/opt/libreoffice/program/soffice",
  "/snap/bin/libreoffice",
  "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)

_TRANSIENT_MARKERS: Tuple[str, ...] = (
  "-2147418111",            # RPC_E_CALL_REJECTED - "Call was rejected by callee"
  "rejected by callee",
  "-2147417846",            # RPC_E_SERVERCALL_RETRYLATER - "application is busy"
  "retrylater",
  "application is busy",
  "-2147417848",            # RPC_E_DISCONNECTED - the server went away mid-call
  "rpc server is unavailable",
  "-2147023174",            # RPC_S_SERVER_UNAVAILABLE
)

_ABSENT_MARKERS: Tuple[str, ...] = (
  "pywin32_unavailable",
  "libreoffice_unavailable",
  "no_recalc_engine_available",
  "invalid class string",   # -2147221005 CO_E_CLASSSTRING - Excel not registered
  "-2147221005",
  "class not registered",   # -2147221164 REGDB_E_CLASSNOTREG
  "-2147221164",
  "no module named 'win32com'",
  "no module named 'pythoncom'",
)


def classify_recalc_error(message: Any) -> str:
  """'transient' (the engine is BUSY - retry it), 'absent' (the engine is
  not here - try another, and if none is, FAIL), or 'failure' (the engine
  ran and the recalc itself broke - a verdict, never retried into a pass
  and never laundered by another engine). The whole 2026-09-11 defect was
  the first two being read as one."""
  text = str(message or "").strip().lower()
  if not text:
    return "failure"
  if any(m in text for m in _ABSENT_MARKERS):
    return "absent"
  if any(m in text for m in _TRANSIENT_MARKERS):
    return "transient"
  return "failure"


# --------------------------------------------------------------------------
# Engine 1: Excel COM (Windows)
# --------------------------------------------------------------------------

def _recalc_workbook_via_excel_com(
  workbook_path: str,
  *,
  attempts: int = 3,
  backoff_seconds: float = 1.5,
) -> Optional[str]:
  """Excel COM with the process-wide lock, retried on a BUSY signal only.
  Returns None on success or the last error string. Absence and genuine
  failures return on the first attempt - retrying a missing engine is just
  failing slower, and retrying a broken recalc hides a verdict."""
  last: Optional[str] = None
  n = max(1, int(attempts))
  for i in range(n):
    with _EXCEL_COM_LOCK:
      err = _recalc_workbook_via_excel_com_unlocked(workbook_path)
    if err is None:
      return None
    last = err
    if classify_recalc_error(err) != "transient":
      return err
    _logger.warning(
      "workbook_recalc_excel_busy attempt=%d/%d for %s: %s",
      i + 1, n, Path(str(workbook_path)).name, err,
    )
    if i + 1 < n and backoff_seconds > 0:
      time.sleep(float(backoff_seconds) * (i + 1))
  return last


def _recalc_workbook_via_excel_com_unlocked(workbook_path: str) -> Optional[str]:
  """Open the workbook in Excel via COM, force CalculateFull(), and save.
  Returns None on success or a short error description on failure; the
  caller classifies it (busy / absent / failure) - this function never
  decides what the error MEANS."""
  try:
    import win32com.client as _w32  # type: ignore
    import pythoncom as _com  # type: ignore
  except Exception as exc:
    return f"pywin32_unavailable: {type(exc).__name__}: {str(exc)[:200]}"
  excel = None
  wb = None
  # COM IS PER-THREAD (2026-08-29). This runs on a Flask request-handler
  # thread, and CoInitialize is per-thread state: without it EnsureDispatch
  # raises -2147221008 "CoInitialize has not been called", this function
  # returns an error, and the caller treats the workbook as unable-to-
  # evaluate. Two things then went wrong quietly for every delivered file:
  # the Save() below never ran, so the workbook shipped with formulas and NO
  # CACHED VALUES (Excel recalculates on open so a client still sees numbers,
  # but anything without a spreadsheet engine reads an empty file), and the
  # Checks!B2 model-status assertion was skipped on every run. A script's
  # MAIN thread is initialised by pythoncom on import, which is why the same
  # recalc always worked from the command line and never from the server.
  _com_ready = False
  try:
    _com.CoInitialize()
    _com_ready = True
  except Exception:
    # Already initialised on this thread, or an apartment-mode clash: either
    # way EnsureDispatch below is the real test, so carry on and let it speak.
    pass
  try:
    excel = _w32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Open(str(workbook_path))
    if wb is None:
      return "excel_workbook_open_returned_none"
    excel.CalculateFull()
    wb.Save()
    return None
  except Exception as exc:
    return f"excel_com_failure: {type(exc).__name__}: {str(exc)[:200]}"
  finally:
    try:
      if wb is not None:
        wb.Close(SaveChanges=False)
    except Exception:
      pass
    try:
      if excel is not None:
        excel.Quit()
    except Exception:
      pass
    if _com_ready:
      try:
        _com.CoUninitialize()
      except Exception:
        pass


# --------------------------------------------------------------------------
# Engine 2: LibreOffice headless (everywhere production runs)
# --------------------------------------------------------------------------

def _resolve_soffice(
  soffice: Union[None, str, Sequence[str]],
  which: Callable[[str], Optional[str]],
  candidates: Iterable[str],
) -> Optional[List[str]]:
  """The soffice command as an argv prefix: an explicit value (a path or a
  full argv, so a test can drive the engine with a stand-in), then
  LIBREOFFICE_SOFFICE, then PATH, then the usual install locations."""
  if soffice:
    if isinstance(soffice, str):
      return [soffice]
    return [str(s) for s in soffice]
  env = (os.environ.get("LIBREOFFICE_SOFFICE") or "").strip()
  if env:
    return [env]
  for name in ("soffice", "libreoffice"):
    found = which(name)
    if found:
      return [str(found)]
  for cand in candidates:
    if cand and os.path.isfile(cand):
      return [cand]
  return None


def _recalc_workbook_via_libreoffice(
  workbook_path: str,
  *,
  soffice: Union[None, str, Sequence[str]] = None,
  write_back: bool = False,
  which: Optional[Callable[[str], Optional[str]]] = None,
  candidates: Optional[Iterable[str]] = None,
  timeout_seconds: float = 180.0,
) -> Tuple[Optional[str], Optional[str]]:
  """`soffice --headless --convert-to xlsx` recalculates the workbook on the
  way through. Returns (error, verified_path): error None on success;
  verified_path is the recalculated file - a COPY in a fresh temp directory
  by default (the deliverable is never touched), or the deliverable itself
  when write_back=True. A fresh -env:UserInstallation profile per call
  keeps headless LibreOffice from refusing on a locked profile or another
  instance's lock, which is the standard failure on a shared Linux host."""
  src = Path(str(workbook_path or "").strip())
  if not str(src) or not src.is_file():
    return (f"libreoffice_input_missing: {src}", None)
  cmd = _resolve_soffice(
    soffice, which or shutil.which,
    DEFAULT_SOFFICE_CANDIDATES if candidates is None else candidates,
  )
  if not cmd:
    return (
      "libreoffice_unavailable: no soffice on PATH, LIBREOFFICE_SOFFICE unset, "
      "none of the default install locations exist",
      None,
    )
  outdir = tempfile.mkdtemp(prefix="wb_recalc_")
  profile = os.path.join(outdir, "profile")
  os.makedirs(profile, exist_ok=True)
  profile_uri = "file:///" + profile.replace("\\", "/").lstrip("/")
  argv = list(cmd) + [
    f"-env:UserInstallation={profile_uri}",
    "--headless", "--norestore", "--nologo",
    "--convert-to", "xlsx",
    "--outdir", outdir,
    str(src),
  ]
  out = Path(outdir) / src.name

  def _failed(err: str):
    # A failed convert leaves NOTHING behind: not the profile, not a
    # partial copy of a client's workbook. The dir is ours (wb_recalc_).
    _discard_verified_copy(str(out))
    return (err, None)

  try:
    proc = _run_killing_the_tree(argv, timeout_seconds=float(timeout_seconds))
  except subprocess.TimeoutExpired:
    return _failed(f"libreoffice_convert_timeout: {timeout_seconds:.0f}s for {src.name}")
  except OSError as exc:
    return _failed(f"libreoffice_unavailable: {type(exc).__name__}: {str(exc)[:200]}")
  if proc.returncode != 0:
    return _failed(
      "libreoffice_convert_failed: rc=%d stderr=%s"
      % (proc.returncode, (proc.stderr or proc.stdout or "").strip()[:300]))
  if not out.is_file():
    return _failed(
      "libreoffice_convert_produced_no_file: expected %s; stdout=%s"
      % (out, (proc.stdout or "").strip()[:200]))
  if write_back:
    shutil.copyfile(str(out), str(src))
    _discard_verified_copy(str(out))
    return (None, str(src))
  return (None, str(out))


class _Completed:
  def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
    self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _run_killing_the_tree(argv: List[str], *, timeout_seconds: float) -> _Completed:
  """subprocess.run with a timeout that actually ends LibreOffice.
  soffice.exe is a launcher; the work happens in a child, soffice.bin.
  subprocess.run's timeout kills only the launcher and the child lives on -
  which is how the first convert after install (a cold launch that never
  finished) sat at 0 CPU for eight minutes past a 300s timeout on
  2026-09-12. On Windows the tree goes down with taskkill /T; elsewhere the
  child is started in its own process group and the group is signalled."""
  kwargs: Dict[str, Any] = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
  if os.name != "nt":
    kwargs["start_new_session"] = True
  proc = subprocess.Popen(argv, **kwargs)
  try:
    out, err = proc.communicate(timeout=timeout_seconds)
  except subprocess.TimeoutExpired:
    try:
      if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, timeout=30)
      else:
        import signal
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
      pass
    try:
      proc.kill()
    except Exception:
      pass
    try:
      proc.communicate(timeout=10)
    except Exception:
      pass
    raise
  return _Completed(proc.returncode, out or "", err or "")


def _discard_verified_copy(verified_path: Optional[str], *, attempts: int = 6,
                           backoff_seconds: float = 0.25) -> bool:
  """Remove a verify-on-copy file and ONLY its own temp directory (the
  wb_recalc_ prefix is this module's) - never a directory it did not make.

  The copy is a client's financial workbook sitting in a temp dir; it must
  not be left behind. On Windows the file can still be held for a moment
  after soffice.bin exits, so a failed unlink is RETRIED with a short
  backoff, and a copy that still could not be removed is logged as a
  warning naming the path - never swallowed. Returns True when nothing of
  ours remains."""
  if not verified_path:
    return True
  p = Path(verified_path)
  parent = p.parent
  ours = parent.name.startswith("wb_recalc_")
  last: Optional[BaseException] = None
  for i in range(max(1, int(attempts))):
    try:
      if p.is_file():
        p.unlink()
      if ours and parent.is_dir():
        shutil.rmtree(str(parent))
      if not p.exists() and not (ours and parent.exists()):
        return True
    except Exception as exc:  # PermissionError while the handle is released
      last = exc
    time.sleep(backoff_seconds * (i + 1))
  logger.warning(
    "workbook verify-on-copy NOT discarded after %d attempts: %s (%s)",
    attempts, parent if ours else p, repr(last) if last else "still present")
  return False


# --------------------------------------------------------------------------
# The engine list
# --------------------------------------------------------------------------

def recalc_workbook(
  workbook_path: str,
  *,
  engines: Optional[Iterable[str]] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
  """Try each engine in order. Returns (engine, error, verified_path).

  success                -> (engine, None, path to read Checks!B2 from)
  a genuine FAILURE      -> (engine, error, None) - stops here; the next
                            engine must not launder a verdict
  absent / busy-exhausted -> falls through to the next engine
  nothing could run      -> ("none", "no_recalc_engine_available: ...", None)
  """
  names = [str(e) for e in (engines or DEFAULT_ENGINES)]
  errors: List[str] = []
  for name in names:
    if name == ENGINE_EXCEL_COM:
      err = _recalc_workbook_via_excel_com(str(workbook_path))
      if err is None:
        return (ENGINE_EXCEL_COM, None, str(workbook_path))
      if classify_recalc_error(err) == "failure":
        return (ENGINE_EXCEL_COM, err, None)
      errors.append(f"{ENGINE_EXCEL_COM}: {err}")
      continue
    if name == ENGINE_LIBREOFFICE:
      err, verified = _recalc_workbook_via_libreoffice(str(workbook_path))
      if err is None and verified:
        return (ENGINE_LIBREOFFICE, None, verified)
      if err is not None and classify_recalc_error(err) == "failure":
        return (ENGINE_LIBREOFFICE, err, None)
      errors.append(f"{ENGINE_LIBREOFFICE}: {err}")
      continue
    errors.append(f"{name}: unknown_engine")
  return ("none", "no_recalc_engine_available: " + "; ".join(errors), None)


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def _read_model_status(workbook_path: str) -> Any:
  """Open the recalculated workbook with openpyxl data_only=True
  and return the Checks!B2 value."""
  import openpyxl  # type: ignore

  wb = openpyxl.load_workbook(str(workbook_path), data_only=True)
  try:
    if _CHECKS_SHEET not in wb.sheetnames:
      return None
    checks = wb[_CHECKS_SHEET]
    return checks.cell(row=_MODEL_STATUS_CELL_ROW, column=_MODEL_STATUS_CELL_COL).value
  finally:
    try:
      wb.close()
    except Exception:
      pass


def assert_workbook_model_status_ok(
  workbook_path: Any,
  *,
  pipeline_stage: str = "post_intake_finalize_validation_workbook_model_status",
) -> None:
  """Post-run machinery fail-fast: the generated workbook's
  Checks!B2 Model Status cell must read "OK".

  Behavior:
    - If the workbook file doesn't exist, raise immediately
      (this is a precondition failure, not a quality issue).
    - Recalculate through the engine list (Excel COM, then
      LibreOffice headless). If NO engine could run - Excel busy
      past its retries, or neither engine installed - RAISE. A check
      that cannot run fails; it never passes by default. This is the
      2026-09-11 change: the old branch logged a warning and
      returned, and a workbook whose invariants were never read
      shipped to a client.
    - If recalc succeeds and Checks!B2 == "OK": return silently.
    - If Checks!B2 is anything else (including None, "FAIL",
      "BLOCKED", "WARN", etc.): raise PostIntakePreconditionFailed
      with diagnostic naming the actual value and pointing the
      operator at app-side fail-fasts FIRST.

  Diagnostic doctrine: when the status check fires, the FIRST
  hypothesis is that the app produced wrong data, NOT that the
  workbook formula is wrong. The operator should verify app state
  via existing post-intake fail-fasts (accounting equation,
  stored-totals, capital lease components, schedule reconciliations)
  before adjusting any workbook formula.
  """
  path = Path(str(workbook_path or "").strip())
  if not str(path):
    raise PostIntakePreconditionFailed(
      operation="workbook_model_status_workbook_path_missing",
      pipeline_stage=pipeline_stage,
      expected="non-empty workbook_path",
      actual="empty",
    )
  if not path.exists():
    raise PostIntakePreconditionFailed(
      operation="workbook_model_status_workbook_missing",
      pipeline_stage=pipeline_stage,
      expected=f"workbook file exists at {path}",
      actual="file not found",
      details={"workbook_path": str(path)},
    )
  engine, recalc_error, verified_path = recalc_workbook(str(path))
  if recalc_error is not None or not verified_path:
    kind = classify_recalc_error(recalc_error or "")
    _logger.error(
      "workbook_model_status_recalc_unavailable engine=%s kind=%s for %s: %s",
      engine, kind, path.name, recalc_error,
    )
    raise PostIntakePreconditionFailed(
      operation="workbook_model_status_recalc_unavailable",
      pipeline_stage=pipeline_stage,
      expected=(
        "a recalculated workbook (Excel COM on Windows, LibreOffice headless "
        "everywhere) so Checks!B2 can be read"
      ),
      actual=f"{engine}: {recalc_error}",
      details={
        "workbook_path": str(path),
        "engine": engine,
        "error_kind": kind,
        "guidance": (
          "A CHECK THAT CANNOT RUN FAILS. transient = the engine was busy and "
          "stayed busy past its retries; absent = no engine is installed here "
          "(production has no Excel - install LibreOffice); failure = the "
          "recalc itself broke on this workbook. The workbook is NOT verified "
          "and must not ship."
        ),
      },
    )
  try:
    try:
      status_value = _read_model_status(str(verified_path))
    except Exception as exc:
      raise PostIntakePreconditionFailed(
        operation="workbook_model_status_read_failed",
        pipeline_stage=pipeline_stage,
        expected=f"readable Checks!B2 in {Path(str(verified_path)).name}",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={"workbook_path": str(path), "verified_path": str(verified_path)},
      ) from exc
  finally:
    if str(Path(str(verified_path)).resolve()) != str(path.resolve()):
      _discard_verified_copy(str(verified_path))
  if status_value == _MODEL_STATUS_OK:
    return
  message_parts = [
    f"workbook_model_status={status_value!r} (expected {_MODEL_STATUS_OK!r}).",
    "Inspect Checks sheet rows where Status=FAIL for the failing invariants.",
    "DEFAULT ASSUMPTION: the failure indicates a bug in the APP, not the workbook.",
    "Verify app state via existing post-intake fail-fasts (accounting_equation_violation,",
    "stored_totals_match_components_violation, capital_lease_* validators,",
    "debt/payroll schedule reconciliations) BEFORE adjusting any workbook formula.",
  ]
  raise PostIntakePreconditionFailed(
    operation="workbook_model_status_fail",
    pipeline_stage=pipeline_stage,
    expected=_MODEL_STATUS_OK,
    actual=str(status_value),
    details={
      "workbook_path": str(path),
      "verified_by": engine,
      "checks_sheet_model_status_cell": f"{_CHECKS_SHEET}!B{_MODEL_STATUS_CELL_ROW}",
      "guidance": " ".join(message_parts),
    },
  )
