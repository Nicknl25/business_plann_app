"""Phase 9 P3.23 — 28-draft observation sweep harness.

OBSERVATION ONLY. No fixes during execution. Iterates through 28
source draft IDs, invoking the canonical runner
(Test Files/run_persisted_system_run.py) sequentially. Captures
per-draft stdout/stderr, wall-clock, pass/fail, and parses the
New Runner report for quarterly metrics + Model Status when the
run completes.

Writes a running CSV/JSON tally to _sweep_p3_23/results.json so the
sweep is restartable and the memo can be assembled from the
captured data. The runner already handles diagnostic preservation;
this harness does NOT alter runner semantics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "Test Files" / "run_persisted_system_run.py"
SWEEP_DIR = Path(__file__).resolve().parent
LOG_DIR = SWEEP_DIR / "per_draft_logs"
RESULTS_PATH = SWEEP_DIR / "results.json"

ONEDRIVE_APPS = Path(
  os.environ.get(
    "INTAKE_APPS_ROOT",
    str(
      Path(
        os.environ.get(
          "OneDriveCommercial",
          os.environ.get("OneDrive", str(Path.home() / "OneDrive")),
        )
      )
      / "Apps"
    ),
  )
)
NEW_RUNNER_DIR = ONEDRIVE_APPS / "New Runner"


DRAFT_IDS: List[str] = [
  "25f746500d1d456da638ee216669b78e",
  "201d0ad18ae243dba933703d19cda4df",
  "41f014a5567041d99b2572a67fe6b03d",
  "6d37c6b98ace41ee9c91dd5fbf68b83e",
  "4aaa94e10efc4968866844197f96f24c",
  "290547bbe8cf48899d897cc5ce865111",
  "52ba2e2c1f4f439c9868541606f3affd",
  "4207488106054d72afbe16480e1de100",
  "25b8e17eda804fa7a46adf72a3503900",
  "5dcd919aae314bd5af67849172aa52bb",
  "5af71d361b324f62a3598e8da40c98c7",
  "2aeae92f95f44fbd9a38b6e319c1bcc7",
  "d345194155584588a77cfb0c8dbedc8c",
  "28af3a88a2294237a1aa6294bf02e078",
  "0459723bad0e461f95dbfe5fbf14631f",
  "1bef9076e6504af9a9fe223af128110b",
  "0bda87acc8a945cb81c63a8940ef5044",
  "077e83b679eb4be7be5febabf05f6379",
  "194c29fed27c4fa39498ed95f8d45343",
  "0d0fb60aca754e00954f402a4fdec0ab",
  "0fe6f320519f412eb113f413d803d338",
  "56b8623063a34e6d9c1803568a730825",
  "11d6cd0c19c3430e8aaf8916b550ea7f",
  "26fc7c5b8d1349048a538f65b4f85beb",
  "0e1d881125b543aea68c603782e00da9",
  "03516b40b43d4592b8d7681a4f57dc67",
  "4c6ff03a7e474f57a3a1ff412860cc2f",
  "1aa5d27085e44aee98d401a5cd56bad0",
]

PER_DRAFT_TIMEOUT_SEC = 600  # 10 minutes hard ceiling


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_results() -> Dict[str, Any]:
  if RESULTS_PATH.exists():
    try:
      return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except Exception:
      pass
  return {"sweep_started_at": _now_iso(), "drafts": {}}


def _save_results(results: Dict[str, Any]) -> None:
  RESULTS_PATH.write_text(
    json.dumps(results, ensure_ascii=False, indent=2),
    encoding="utf-8",
  )


def _parse_runner_stdout(text: str) -> Dict[str, Any]:
  out: Dict[str, Any] = {}
  m = re.search(r"Cloned source intake state into new draft:\s+(\S+)", text)
  if m:
    out["new_draft_id"] = m.group(1).strip()
  m = re.search(r"New Client ID:\s+(\S+)", text)
  if m:
    out["new_client_id"] = m.group(1).strip()
  m = re.search(r"Loaded source persisted draft:\s+(\S+)", text)
  if m:
    out["source_draft_id"] = m.group(1).strip()
  m = re.search(r"Source Client ID:\s+(\S+)", text)
  if m:
    out["source_client_id"] = m.group(1).strip()
  m = re.search(r"Business Name:\s+(.+)", text)
  if m:
    out["business_name"] = m.group(1).strip()
  m = re.search(r"Saved client financial model workbook:\s+(.+)", text)
  if m:
    out["workbook_path"] = m.group(1).strip()
  m = re.search(r"System run duration:\s+(\d+)\s+ms", text)
  if m:
    try:
      out["system_run_ms"] = int(m.group(1))
    except ValueError:
      pass
  if "ERROR:" in text:
    err_lines = [line.strip() for line in text.splitlines() if line.startswith("ERROR:")]
    out["runner_error_lines"] = err_lines
  return out


def _read_new_runner_report(new_draft_id: str) -> Optional[Dict[str, Any]]:
  if not new_draft_id:
    return None
  # Match the file ending in `-- <new_draft_id>.txt` (not the quarter-grid).
  candidates: List[Path] = []
  if NEW_RUNNER_DIR.exists():
    for p in NEW_RUNNER_DIR.iterdir():
      name = p.name
      if not name.endswith(f"{new_draft_id}.txt"):
        continue
      if "quarter-grid" in name:
        continue
      candidates.append(p)
  if not candidates:
    return None
  candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
  body = candidates[0].read_text(encoding="utf-8", errors="replace")
  parsed: Dict[str, Any] = {"new_runner_report_path": str(candidates[0])}
  m = re.search(r"^Business Name:\s+(.+)$", body, re.MULTILINE)
  if m:
    parsed["business_name"] = m.group(1).strip()
  m = re.search(r"^Planning Mode:\s+(.+)$", body, re.MULTILINE)
  if m:
    parsed["planning_mode"] = m.group(1).strip()
  m = re.search(r"^Planning Mode Reason:\s+(.+)$", body, re.MULTILINE)
  if m:
    parsed["planning_mode_reason"] = m.group(1).strip()
  m = re.search(r"^Accounting All OK:\s+(.+)$", body, re.MULTILINE)
  if m:
    parsed["accounting_all_ok"] = m.group(1).strip()
  m = re.search(r"^Applied Lever Updates:\s+(\d+)$", body, re.MULTILINE)
  if m:
    parsed["applied_lever_updates"] = int(m.group(1))
  m = re.search(r"^Applied Levers:\s+(\d+)$", body, re.MULTILINE)
  if m:
    parsed["applied_levers"] = int(m.group(1))
  quarter_lines = re.findall(
    r"^(Q\d+)\s+\|\s+Revenue\s+([\d,\.\-]+)\s+\|\s+EBITDA\s+([\d,\.\-]+)\s+\|\s+Cash\s+([\d,\.\-]+)\s+\|\s+Acct Check\s+([\d\.\-]+)\s*$",
    body,
    re.MULTILINE,
  )
  quarters: List[Dict[str, Any]] = []
  for q_label, rev, ebitda, cash, acct in quarter_lines:
    quarters.append(
      {
        "q": q_label,
        "revenue": rev.replace(",", ""),
        "ebitda": ebitda.replace(",", ""),
        "cash": cash.replace(",", ""),
        "accounting_check": acct,
      }
    )
  parsed["quarters"] = quarters
  return parsed


def _classify_outcome(returncode: int, stdout: str, parsed_stdout: Dict[str, Any]) -> str:
  if returncode == 0:
    return "PASS"
  err_lines = parsed_stdout.get("runner_error_lines") or []
  for line in err_lines:
    if "PostIntakePreconditionFailed" in line or "FailFast" in line:
      return "FAIL"
    if "Model Status" in line or "model_status" in line:
      return "FAIL"
    if "accounting" in line.lower() and "equation" in line.lower():
      return "FAIL"
    if "cash" in line.lower() and "buffer" in line.lower():
      return "FAIL"
    if "convergence" in line.lower():
      return "FAIL"
    if "realism" in line.lower():
      return "FAIL"
  # Default for non-zero exit with ERROR lines is FAIL (business failure).
  if err_lines:
    return "FAIL"
  return "RUNNER_ERROR"


def _run_single_draft(source_draft_id: str) -> Dict[str, Any]:
  log_path = LOG_DIR / f"{source_draft_id}.log"
  start_iso = _now_iso()
  start_perf = time.perf_counter()
  try:
    proc = subprocess.run(
      [
        sys.executable,
        str(RUNNER),
        "--draft-id",
        source_draft_id,
        "--base-url",
        "http://127.0.0.1:5050",
      ],
      cwd=str(REPO_ROOT),
      capture_output=True,
      text=True,
      timeout=PER_DRAFT_TIMEOUT_SEC,
      check=False,
    )
    elapsed = time.perf_counter() - start_perf
    end_iso = _now_iso()
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    returncode = proc.returncode
    timed_out = False
  except subprocess.TimeoutExpired as exc:
    elapsed = time.perf_counter() - start_perf
    end_iso = _now_iso()
    stdout = (exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")) if exc.stdout else ""
    stderr = (exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")) if exc.stderr else ""
    returncode = -1
    timed_out = True

  log_path.write_text(
    "===== STDOUT =====\n"
    + stdout
    + "\n===== STDERR =====\n"
    + stderr,
    encoding="utf-8",
  )

  parsed = _parse_runner_stdout(stdout + "\n" + stderr)
  outcome = "RUNNER_TIMEOUT" if timed_out else _classify_outcome(returncode, stdout, parsed)
  new_runner_report = _read_new_runner_report(parsed.get("new_draft_id", "")) if parsed.get("new_draft_id") else None

  return {
    "source_draft_id": source_draft_id,
    "start_iso": start_iso,
    "end_iso": end_iso,
    "wall_clock_sec": round(elapsed, 2),
    "returncode": returncode,
    "timed_out": timed_out,
    "outcome": outcome,
    "parsed_stdout": parsed,
    "new_runner_report": new_runner_report,
    "log_path": str(log_path),
  }


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--limit", type=int, default=None, help="Only run the first N drafts.")
  parser.add_argument("--start-from", type=int, default=0, help="Start sweep from index N.")
  parser.add_argument(
    "--ids",
    type=str,
    default="",
    help="Comma-separated draft IDs to run instead of full list.",
  )
  args = parser.parse_args()

  ids = DRAFT_IDS
  if args.ids:
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
  if args.start_from:
    ids = ids[args.start_from :]
  if args.limit is not None:
    ids = ids[: args.limit]

  results = _load_results()
  drafts = results.setdefault("drafts", {})

  for idx, source_draft_id in enumerate(ids, start=1):
    if source_draft_id in drafts and drafts[source_draft_id].get("outcome") in {"PASS", "FAIL", "RUNNER_ERROR", "RUNNER_TIMEOUT"}:
      print(f"[{idx}/{len(ids)}] {source_draft_id} already complete ({drafts[source_draft_id]['outcome']}) — skipping.", flush=True)
      continue
    print(f"[{idx}/{len(ids)}] Running {source_draft_id} ...", flush=True)
    record = _run_single_draft(source_draft_id)
    drafts[source_draft_id] = record
    _save_results(results)
    print(
      f"[{idx}/{len(ids)}] {source_draft_id} {record['outcome']} ({record['wall_clock_sec']}s)",
      flush=True,
    )

  results["sweep_finished_at"] = _now_iso()
  _save_results(results)

  pass_n = sum(1 for r in drafts.values() if r.get("outcome") == "PASS")
  fail_n = sum(1 for r in drafts.values() if r.get("outcome") == "FAIL")
  err_n = sum(1 for r in drafts.values() if r.get("outcome") in {"RUNNER_ERROR", "RUNNER_TIMEOUT"})
  print(f"DONE. PASS={pass_n} FAIL={fail_n} RUNNER_ERROR/TIMEOUT={err_n}", flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
