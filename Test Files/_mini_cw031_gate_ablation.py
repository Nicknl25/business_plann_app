"""CW-031 tier-1 mini audit, check 1: is any part of the artifact gate decorative?

Neuter ONE mechanism at a time in issue_registry.py, re-run VS's red-proof, and
record WHICH checks go red. A mechanism that can be removed with the proof still
green is decoration, and Nick wants that named.

Discipline, because this touches app code that is not mine:
  * the source is restored from the bytes read before the patch, in a finally;
  * the registry tables are snapshotted and restored after every ablation, so
    an ablated run cannot mint a false verdict into the shared issue DB;
  * a clean baseline is re-run at the end to prove the restore worked.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_gate_ablation.py"
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "python" / "client_intake_and_finmo" / "issue_registry.py"
REDPROOF = REPO_ROOT / "Test Files" / "_redproof_cw031_artifact_detector.py"
PY = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

MUTABLE = ["status", "occurrence_count", "reopened_count", "clean_exercise_count",
           "runs_since_last_seen", "resolved_detected_at", "resolution_basis",
           "resolution_confidence", "probe_json", "last_seen_at"]

ABLATIONS = [
  (
    "i-artifact-backed",
    'artifact_backed = rclass == "hard" and artifact["present"]',
    'artifact_backed = rclass == "hard"  # ABLATED: artifact presence ignored',
  ),
  (
    "ii-a-resolved-not-selected",
    "WHERE status IN ('open', 'recurring', 'resolved')",
    "WHERE status IN ('open', 'recurring')",
  ),
  (
    "ii-b-reaudit-branch-inert",
    '      if str(issue["status"]) == "resolved":',
    '      if str(issue["status"]) == "resolved":\n        continue  # ABLATED: re-audit branch inert',
  ),
  (
    "iii-no-retest-condition-guard",
    '  if not conditions:\n    return {"exercised": False,\n'
    '            "reason": "probe states no retest condition (metadata/notes only)"}',
    '  if False:  # ABLATED: no-retest-condition guard removed\n    pass',
  ),
]


def snapshot(conn):
  cur = conn.cursor()
  cur.execute(f"SELECT issue_id, {', '.join(MUTABLE)} FROM issues")
  issues = cur.fetchall()
  cur.execute("SELECT COALESCE(MAX(id), 0) FROM issue_occurrences")
  max_occ = int(cur.fetchone()[0] or 0)
  cur.execute("SELECT COALESCE(MAX(id), 0) FROM issue_resolution_events")
  max_evt = int(cur.fetchone()[0] or 0)
  cur.close()
  return {"issues": issues, "max_occ": max_occ, "max_evt": max_evt}


def restore(conn, snap) -> str:
  cur = conn.cursor()
  cur.execute("DELETE FROM issue_occurrences WHERE id > %s", (snap["max_occ"],))
  occ = cur.rowcount
  cur.execute("DELETE FROM issue_resolution_events WHERE id > %s", (snap["max_evt"],))
  evt = cur.rowcount
  sets = ", ".join(f"{c}=%s" for c in MUTABLE)
  for row in snap["issues"]:
    cur.execute(f"UPDATE issues SET {sets} WHERE issue_id=%s",
                (*row[1:], row[0]))
  conn.commit()
  cur.close()
  return f"deleted {occ} occurrence(s) + {evt} event(s), reset {len(snap['issues'])} issue row(s)"


def run_proof(tag: str):
  out = REPO_ROOT / f"_mini_ablation_{tag}.txt"
  proc = subprocess.run([str(PY), str(REDPROOF)], capture_output=True, text=True)
  out.write_text(proc.stdout + proc.stderr, encoding="utf-8")
  fails = [ln.split("[FAIL] ", 1)[1].split(":")[0]
           for ln in proc.stdout.splitlines() if "[FAIL]" in ln]
  crashed = "Traceback" in (proc.stdout + proc.stderr)
  return proc.returncode, fails, crashed, out.name


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  # BYTES, not text. read_text/write_text round-trips LF -> CRLF on Windows, so
  # a "restored" file came back content-identical and byte-different (git hid it
  # behind autocrlf). Ablating app code that is not mine has to leave the file
  # bit-for-bit as found.
  original_b = TARGET.read_bytes()
  original = original_b.decode("utf-8")
  conn = get_mysql_connection()
  conn.autocommit = False
  verdicts = []
  try:
    snap = snapshot(conn)
    print(f"snapshot: {len(snap['issues'])} issues, occ<={snap['max_occ']}, evt<={snap['max_evt']}\n")

    for tag, old, new in ABLATIONS:
      count = original.count(old)
      print(f"== ABLATION {tag} ==")
      if count != 1:
        print(f"  SETUP FAILURE: anchor text occurs {count}x, expected exactly 1")
        print(f"  anchor: {old[:80]!r}")
        verdicts.append((tag, "SETUP-FAILURE", []))
        continue
      TARGET.write_bytes(original.replace(old, new).encode("utf-8"))
      try:
        rc, fails, crashed, name = run_proof(tag)
      finally:
        TARGET.write_bytes(original_b)
      note = restore(conn, snap)
      status = "RED" if rc != 0 else "STILL-GREEN"
      if crashed:
        status += " (crashed)"
      print(f"  {status}: rc={rc}, failed checks={fails or 'none'}")
      print(f"  output: {name}; db {note}")
      verdicts.append((tag, status, fails))

    print("\n== RESTORE CHECK: clean source, clean baseline ==")
    assert TARGET.read_bytes() == original_b, "source not restored byte-for-byte"
    rc, fails, crashed, name = run_proof("restorecheck")
    restore(conn, snap)
    print(f"  baseline after restore: rc={rc}, failed={fails or 'none'} ({name})")
    verdicts.append(("restore-check", "GREEN" if rc == 0 else "RED", fails))
  finally:
    TARGET.write_bytes(original_b)
    try:
      conn.close()
    except Exception:
      pass

  print("\n" + "=" * 72)
  for tag, status, fails in verdicts:
    print(f"  {tag:34s} {status:18s} {fails}")
  decorative = [t for t, s, _ in verdicts
                if s == "STILL-GREEN" and t != "restore-check"]
  if decorative:
    print(f"\nDECORATIVE (removable with the proof still green): {decorative}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
