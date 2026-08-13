"""CW-031 round 9 -- the RED half: neuter one fix at a time on the real files.

A proof that is only ever green proves nothing. Each ablation reverts one
round-9 mechanism to (or toward) the broken shape mini measured in
_mini_cw031_r8_audit_20260813.txt, re-runs the green proof, and requires it to
go red on THAT mechanism's own checks. If any ablation leaves the proof green,
that part of the fix is decorative and this says so. Files are restored from
the exact bytes read before each ablation, and the proof re-runs green at the
end to prove the restore.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round9_ablate.py"
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IC = REPO_ROOT / "python" / "api_handlers" / "intake_consult.py"
IR = REPO_ROOT / "python" / "client_intake_and_finmo" / "issue_registry.py"
SP = REPO_ROOT / "scripts" / "_active_intake_probe.py"
PROOF = REPO_ROOT / "Test Files" / "_redproof_cw031_round9_fixes.py"

# (name, file, needle, replacement, checks that MUST go red)
ABLATIONS = [
  (
    # THE OLD NET, RESTORED: uniform post-write rates STORE an inferred
    # all-lines group instead of asking. This is the exact round-8 behaviour
    # mini killed (A2 clobber + A5 echo + false PASS), so removing the ask
    # and restoring the store must go red on the store-nothing checks AND on
    # the declared-stamp survival -- proving the ask is what protects the
    # declaration.
    "R9A1 the net stores nothing (restore the mint)", IC,
    """        receipt["uniform_rate_ask"] = {
          "count": len(directory),
          "rate": next(iter(_distinct)),
        }""",
    """        _all_label = "shared:" + "+".join(
          sorted(str(e["product_name"] or e["line_name"]).strip().lower()
                 for e in directory))
        for entry in directory:
          entry["row"]["cogs_cost_structure_group"] = _all_label
          entry["row"]["cogs_cost_structure_group_basis"] = (
            "inferred from identical stated rates")""",
    ("1a uniform write stores NO group", "1b receipt carries the ask",
     "1e declared partial group SURVIVES a coinciding write"),
  ),
  (
    "R9A2 the ask fires once (drop the entry snapshot)", IC,
    """  if (len(directory) >= 3 and receipt["written"] and not _uniform_before
      and not any(g.get("all_lines") for g in receipt["grouped"])):""",
    """  if (len(directory) >= 3 and receipt["written"]
      and not any(g.get("all_lines") for g in receipt["grouped"])):""",
    ("1d echo of uniform state: no store, no re-ask",),
  ),
  (
    "R9A3 the N>=3 floor", IC,
    """  _uniform_before = (
    len(directory) >= 3 and None not in _rates_before""",
    """  _uniform_before = (
    len(directory) >= 300 and None not in _rates_before""",
    # Lowering the ask condition itself is covered by R9A2; here we break the
    # snapshot's own floor so N=2's pre-uniform state stops being seen, then
    # the ask block still requires >=3 -- so instead break the ask block:
    ("1f N=2 uniform: no ask, no store",),
  ),
  (
    "R9A4 the separation door's clear", IC,
    """    if str(entry["row"].get("cogs_cost_structure_group") or "").strip():
      entry["row"].pop("cogs_cost_structure_group", None)
      entry["row"].pop("cogs_cost_structure_group_basis", None)
      receipt["wrote"] = True""",
    """    if False:
      receipt["wrote"] = True""",
    ("3a separation clears the named row's group AND basis",),
  ),
  (
    "R9A5 the group-coherence pass", IC,
    """  if receipt["separated"] or receipt["grouped"]:
    _by_label: Dict[str, List[Dict[str, Any]]] = {}""",
    """  if False:
    _by_label: Dict[str, List[Dict[str, Any]]] = {}""",
    ("3b the stale label is retired from the rows left behind",
     "3e a regroup clears the stale label from the row it leaves out"),
  ),
  (
    "R9A6 the gate's declared-only rule", IR,
    """        if _bases == {"declared"}:""",
    """        if True:""",
    ("2b inferred-basis group FAILS the gate",),
  ),
  (
    "R9A7 the F1 predicate's figure scan", IC,
    """  stated = [f for f in _message_figures(message) if f > 0]""",
    """  stated = []""",
    ("4a mini's A-B2 reply is caught", "4b mini's A-B3 reply is caught",
     "4e a unit-scaled echo is caught (38 <-> 0.38)"),
  ),
  (
    "R9A8 the F1 predicate's unit doubling", IC,
    """  targets: List[float] = []
  for f in stated:
    targets.extend((f, f * 100.0, f / 100.0))""",
    """  targets: List[float] = list(stated)""",
    ("4e a unit-scaled echo is caught (38 <-> 0.38)",),
  ),
  (
    "R9A9 the probe's zero-message exclusion", SP,
    """      AND d.messages_json IS NOT NULL
      AND d.messages_json <> ''
      AND d.messages_json <> '[]'""",
    "",
    ("6a a zero-message draft does NOT block the restart",),
  ),
]


def run_proof() -> str:
  out = subprocess.run(
    [str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), str(PROOF)],
    capture_output=True, text=True, timeout=300,
  )
  return (out.stdout or "") + (out.stderr or "")


def red_checks(output: str) -> list:
  """The full [FAIL] lines; check tags may themselves contain colons, so
  membership is tested by substring against the whole line."""
  return [line for line in output.splitlines()
          if line.strip().startswith("[FAIL]")]


def main() -> int:
  failures = []
  # N=2 check in R9A3 needs the ask block itself lowered, not the snapshot;
  # patch the ablation to break the block's own floor.
  for i, (name, path, needle, repl, musts) in enumerate(ABLATIONS):
    if name.startswith("R9A3"):
      ABLATIONS[i] = (
        name, path,
        """  if (len(directory) >= 3 and receipt["written"] and not _uniform_before""",
        """  if (len(directory) >= 2 and receipt["written"] and not _uniform_before""",
        musts,
      )
  for name, path, needle, repl, musts in ABLATIONS:
    original = path.read_bytes()
    text = original.decode("utf-8")
    # The repo files carry CRLF endings; the needles here are written with
    # bare \n. Match and write in the file's own newline style.
    if "\r\n" in text:
      needle = needle.replace("\r\n", "\n").replace("\n", "\r\n")
      repl = repl.replace("\r\n", "\n").replace("\n", "\r\n")
    if needle not in text:
      print(f"[BROKEN] {name}: needle not found in {path.name}")
      failures.append(name)
      continue
    try:
      path.write_bytes(text.replace(needle, repl, 1).encode("utf-8"))
      output = run_proof()
      reds = red_checks(output)
      missing = [m for m in musts if not any(m in line for line in reds)]
      if missing:
        print(f"[DECORATIVE] {name}: proof stayed green on {missing} "
              f"(reds seen: {sorted(reds)})")
        if not reds and "PASS" not in output:
          print("  (proof produced no check lines; tail of output:)")
          print("  " + "\n  ".join(output.splitlines()[-12:]))
        failures.append(name)
      else:
        print(f"[RED-FOR-THE-RIGHT-REASON] {name}: {sorted(m for m in musts)}")
    finally:
      path.write_bytes(original)
  print("\nrestore check: re-running the proof on restored files...")
  output = run_proof()
  if "0 FAIL" not in output:
    print("[BROKEN] proof not green after restore!")
    print(output[-2000:])
    return 2
  print("restored: proof green again.")
  if failures:
    print(f"\n{len(failures)} ablation(s) DECORATIVE or broken: {failures}")
    return 1
  print(f"\nall {len(ABLATIONS)} ablations red on their own checks; "
        "none decorative.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
