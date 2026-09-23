"""POST AN ISSUE ROW SO THAT A FAILURE IS IMPOSSIBLE TO MISTAKE FOR SUCCESS.

WHAT THIS EXISTS FOR (Nick, 2026-09-22): "a write that fails fails LOUDLY on
both sides. Neither of you may ever again believe you've spoken when nothing
landed."

Between 2026-09-18 21:02 and 2026-09-22 21:02 the store was not listening.
Cowork filed an entire CW-077 sequence into it. VS came back to a table whose
newest row was its own from Friday. Nobody was lied to on purpose: each side
made a call, got no usable answer, and carried on as if it had.

THREE RULES, AND THE THIRD IS THE ONE THAT WAS MISSING:

  1. A POST IS NOT LANDED UNTIL THE STORE SAYS WHICH ROW IT IS. A 200 is not
     enough and neither is an absent exception - this reads the issue_id back
     out of the response and treats a reply without one as a failure.

  2. A FAILED POST IS SPOOLED, NEVER DROPPED. It goes to _runtime/issue_spool/
     as the exact payload that failed. Nothing a client said, and nothing an
     agent concluded, is lost because a socket was shut.

  3. THE SPOOL IS REPLAYED AND THE FAILURE IS ANNOUNCED. Every call first
     drains anything spooled earlier, so the moment the store returns the
     backlog lands in order. And a failure prints a line that cannot be read as
     success, with the spool path in it.

Use it as a library:
    from scripts.issue_post import post_issue
    ok, detail = post_issue({...})
    if not ok: ...          # detail says where it was spooled

or from the command line, which is what a non-Python caller (Cowork) can use:
    python scripts/issue_post.py payload.json
    python scripts/issue_post.py --drain          # replay the spool, report
    python scripts/issue_post.py --check          # is the store answering?
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

REPO = Path(__file__).resolve().parents[1]
SPOOL = REPO / "_runtime" / "issue_spool"
LOG = REPO / "_runtime" / "issue_post.log"
URL = "http://127.0.0.1:5050/api/issues"


def _now() -> str:
  return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(line: str) -> None:
  LOG.parent.mkdir(parents=True, exist_ok=True)
  with open(LOG, "a", encoding="utf-8") as fh:
    fh.write("%s %s\n" % (_now(), line))


def _spool(payload: Dict[str, Any], why: str) -> Path:
  SPOOL.mkdir(parents=True, exist_ok=True)
  path = SPOOL / ("%s_%s.json" % (datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
                                  str(payload.get("source") or "unknown")))
  path.write_text(json.dumps({"payload": payload, "failed_at": _now(),
                              "why": why}, indent=2), encoding="utf-8")
  return path


def _send(payload: Dict[str, Any], timeout: float = 30.0) -> Tuple[bool, str]:
  """One attempt. True only when the store names the row it wrote."""
  body = json.dumps(payload).encode("utf-8")
  req = urllib.request.Request(URL, data=body, method="POST",
                               headers={"Content-Type": "application/json"})
  try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      raw = resp.read().decode("utf-8")
      if resp.status != 200:
        return False, "HTTP %s: %s" % (resp.status, raw[:300])
      obj = json.loads(raw or "{}")
  except urllib.error.HTTPError as exc:
    detail = ""
    try:
      detail = exc.read().decode("utf-8")[:300]
    except Exception:
      pass
    return False, "HTTP %s: %s" % (exc.code, detail)
  except Exception as exc:                                    # noqa: BLE001
    return False, "%s: %s" % (type(exc).__name__, exc)
  # A REPLY WITHOUT A ROW ID IS NOT A LANDING. This is the check whose absence
  # let four days of filings read as successes.
  issue = obj.get("issue") if isinstance(obj, dict) else None
  row_id = None
  if isinstance(issue, dict):
    row_id = issue.get("issue_id") or issue.get("id")
  if not row_id:
    return False, "no row id in the reply: %s" % json.dumps(obj)[:300]
  return True, str(row_id)


def drain() -> Tuple[int, int]:
  """Replay everything spooled, oldest first. Returns (sent, still_spooled)."""
  if not SPOOL.exists():
    return 0, 0
  sent = 0
  pending = sorted(SPOOL.glob("*.json"))
  for path in pending:
    try:
      rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
      continue
    ok, detail = _send(rec.get("payload") or {})
    if not ok:
      return sent, len(pending) - sent
    path.unlink(missing_ok=True)
    sent += 1
    _log("SPOOL REPLAYED -> row %s (%s)" % (detail, path.name))
  return sent, 0


def post_issue(payload: Dict[str, Any], *, retries: int = 2) -> Tuple[bool, str]:
  """The only way VS should file a row. Drains the spool first so a backlog
  lands in order the moment the store is back."""
  drained, still = drain()
  if drained:
    print("STORE BACK: replayed %d spooled row(s) before this one" % drained)
  for attempt in range(retries + 1):
    ok, detail = _send(payload)
    if ok:
      _log("POSTED row %s  %s" % (detail, str(payload.get("signature") or "")[:60]))
      return True, detail
    if attempt < retries:
      time.sleep(2.0 * (attempt + 1))
  path = _spool(payload, detail)
  _log("POST FAILED (%s) -> spooled %s" % (detail, path.name))
  # LOUD. Not a return code someone can ignore, not a debug line - the words
  # say the row is NOT filed and name the file holding it.
  print("=" * 72)
  print("ISSUE POST FAILED - NOTHING WAS FILED. The other side has NOT heard this.")
  print("  why    : %s" % detail)
  print("  spooled: %s" % path)
  print("  it will be sent automatically by the next successful post, or by")
  print("  python scripts/issue_post.py --drain")
  print("=" * 72)
  return False, str(path)


def main(argv: list) -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("payload", nargs="?", help="path to a JSON file holding the row")
  ap.add_argument("--drain", action="store_true", help="replay the spool and report")
  ap.add_argument("--check", action="store_true", help="is the store answering?")
  args = ap.parse_args(argv)

  if args.check:
    ok, detail = _send({"source": "vs", "category": "progress", "severity": "note",
                        "signature": "vs_store_reachability_probe",
                        "title": "store reachability probe",
                        "expected": "the store answers and names the row",
                        "observed": "probe from scripts/issue_post.py --check"})
    print("STORE ANSWERS, row %s" % detail if ok else "STORE DID NOT ANSWER: %s" % detail)
    return 0 if ok else 1

  if args.drain:
    sent, still = drain()
    print("replayed %d, still spooled %d" % (sent, still))
    return 0 if still == 0 else 1

  if not args.payload:
    ap.error("give a payload file, --drain or --check")
  payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
  ok, detail = post_issue(payload)
  print("row %s" % detail if ok else "NOT FILED - spooled at %s" % detail)
  return 0 if ok else 1


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
