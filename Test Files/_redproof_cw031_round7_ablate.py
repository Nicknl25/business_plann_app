"""CW-031 round 7 -- the RED half: neuter one fix at a time on the real files.

A proof that is only ever green proves nothing. This reverts each hunk to the
exact code mini measured as broken, re-runs
Test Files/_redproof_cw031_round7_fixes.py, and requires that it goes red on
THAT hunk's own checks and nowhere else. If a hunk can be removed with the
proof still green, that fix is decorative and this says so.

The files are restored from the bytes read before each ablation, and verified
byte-identical against HEAD at the end.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round7_ablate.py"
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IC = REPO_ROOT / "python" / "api_handlers" / "intake_consult.py"
IR = REPO_ROOT / "python" / "client_intake_and_finmo" / "issue_registry.py"
CR = REPO_ROOT / "python" / "client_intake_and_finmo" / "capture_receipt.py"
PROOF = REPO_ROOT / "Test Files" / "_redproof_cw031_round7_fixes.py"

# (name, file, needle, replacement, checks that MUST go red)
ABLATIONS = [
  (
    # THE DEFECT EXACTLY AS MINI MEASURED IT: an absent unit falling back to the
    # >1.0 heuristic, so a bare 1 from an ordinary sentence stores 100%.
    "A1a refusal when the unit is absent (back to the >1.0 heuristic)", IC,
    """    return None, "no_unit\"""",
    """    return round(max(0.0, min(1.0, value / 100.0 if value > 1.0 else value)), 4), "ok\"""",
    ("no unit -> nothing written", "no unit -> receipt asks"),
  ),
  (
    "A1b the percent-range contradiction guard", IC,
    """      if value < 0.0 or value > 100.0:""",
    """      if False:""",
    ("contradiction 150 as percent", "contradiction -2 as percent"),
  ),
  (
    "A1c the ratio-range contradiction guard", IC,
    """      if value < 0.0 or value > 1.0:""",
    """      if False:""",
    ("contradiction 71 as ratio",),
  ),
  (
    "A2 the collapse fallback (back to weight-or-zero)", IC,
    """      if len(rated) == 1:""",
    """      weights = [(w or 0.0) for w in weights]
      unweighted = []
      if sum(weights) > 0:
        shared_pct = round(
          sum(r * float(w) for r, w in zip(rates, weights)) / sum(weights), 4)
        basis = "revenue weighted"
      elif False:""",
    ("stated rate not discarded", "basis is named on the receipt", "the client is TOLD"),
  ),
  (
    "A3 the door's all-lines group", IC,
    """  if len(directory) >= 2 and len(receipt["written"]) == len(directory):""",
    """  if False:""",
    ("door records the client's own collapse", "the receipt says the collapse happened",
     "uniform + recorded collapse PASSES"),
  ),
  (
    "A4 the assertion's recorded-collapse opt-out", IR,
    """      if len(grouped) == len(products) and len(labels) == 1:""",
    """      if False:""",
    ("uniform + recorded collapse PASSES",),
  ),
  (
    "A4b the transport key hidden from the receipt", CR,
    """  "cogs_percent",""",
    """  "cogs_percent_NOT_FILTERED",""",
    ("the raw router figure is not spoken",),
  ),
  (
    "A5 the unnamed-row guard (back to the wildcard)", IC,
    """    if (line_name and target in line_name) or (product_name and product_name in target):""",
    """    if target in line_name or product_name in target:""",
    ("unnamed row refuses 'the pavers side'", "unnamed row refuses 'the two retail ones'",
     "unnamed row refuses 'everything except design'"),
  ),
]


def run_proof() -> str:
  out = subprocess.run(
    [str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), str(PROOF)],
    cwd=str(REPO_ROOT), capture_output=True,
  )
  return (out.stdout + out.stderr).decode("utf-8", "replace")


def failing(text: str) -> set:
  return {m.group(1).strip() for m in re.finditer(r"\[FAIL\] ([^:]+):", text)}


def main() -> int:
  problems = []

  baseline = run_proof()
  if "GREEN" not in baseline:
    print("BASELINE IS NOT GREEN -- nothing below means anything:")
    print(baseline[-3000:])
    return 1
  print("baseline: GREEN\n")

  for name, path, needle, replacement, must_fail in ABLATIONS:
    original = path.read_bytes()
    text = original.decode("utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8")
    if text.count(needle) != 1:
      problems.append(f"{name}: needle appears {text.count(needle)}x, expected 1")
      print(f"[SKIP] {name}: needle not unique")
      continue
    patched = text.replace(needle, replacement)
    prefix = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    try:
      path.write_bytes(prefix + patched.encode("utf-8"))
      out = run_proof()
    finally:
      path.write_bytes(original)

    reds = failing(out)
    missing = [c for c in must_fail if c not in reds]
    extra = sorted(reds - set(must_fail))
    if "GREEN" in out and not reds:
      problems.append(f"{name}: DECORATIVE -- removed with the proof still green")
      print(f"[DECORATIVE] {name}: proof stayed green without it")
      continue
    if missing:
      problems.append(f"{name}: red, but not on {missing}")
      print(f"[WRONG-REASON] {name}: red on {sorted(reds)}; expected {list(must_fail)}")
      continue
    print(f"[RED, RIGHT REASON] {name}")
    print(f"    turns red: {sorted(reds)}")
    if extra:
      print(f"    also red (same fix, related check): {extra}")

  after = subprocess.run(["git", "status", "--porcelain",
                          "python/api_handlers/intake_consult.py",
                          "python/client_intake_and_finmo/issue_registry.py",
                          "python/client_intake_and_finmo/capture_receipt.py"],
                         cwd=str(REPO_ROOT), capture_output=True)
  print("\nrestored; git status of the ablated files:")
  print("  " + (after.stdout.decode().strip() or "(clean)"))
  final = run_proof()
  print(f"post-ablation re-run: {'GREEN' if 'GREEN' in final else 'RED'}")
  if "GREEN" not in final:
    problems.append("files did not restore: proof no longer green")

  print()
  if problems:
    for p in problems:
      print(f"PROBLEM: {p}")
    return 1
  print("EVERY FIX IS LOAD-BEARING -- each one, removed alone, turns its own checks red")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
