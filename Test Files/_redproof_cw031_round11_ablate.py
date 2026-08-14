"""CW-031 round 11 -- the RED half: neuter one D1/D2/D3 mechanism at a time.

Each ablation reverts one round-11 mechanism to (or toward) the broken shape
mini measured in _mini_cw031_r10_audit_20260813.txt, re-runs the green proof
(_redproof_cw031_round11_fixes.py), and requires it to go red on THAT
mechanism's own checks. Any ablation the proof survives is decorative and
this says so. Files restore from exact pre-ablation bytes; the proof re-runs
green at the end to prove the restore.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round11_ablate.py"
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IC = REPO_ROOT / "python" / "api_handlers" / "intake_consult.py"
PROOF = REPO_ROOT / "Test Files" / "_redproof_cw031_round11_fixes.py"

# (name, file, needle, replacement, checks that MUST go red)
ABLATIONS = [
  (
    # D2 reverted: the old 0.5% band swallows a correction as a confirmation.
    "R11A1 tolerance back to 0.5%", IC,
    "      if abs(f - value) <= max(0.5, 1e-9 * abs(value)):",
    "      if abs(f - value) <= max(0.5, 0.005 * abs(value)):",
    ("2b a 0.32% correction never claims a match",
     "2c a 0.45% correction never claims a match"),
  ),
  (
    # D1 reverted: first-leaf-wins naming on an ambiguous value.
    "R11A2 name the first leaf regardless of ambiguity", IC,
    """    distinct_names = {leaf for leaf, _ in found}
    item: Tuple[Optional[str], float] = (
      found[0] if len(distinct_names) == 1 else (None, found[0][1]))""",
    """    distinct_names = {leaf for leaf, _ in found}
    item: Tuple[Optional[str], float] = found[0]""",
    ("1a ambiguous value: match fires with NO field claim",),
  ),
  (
    # D3 reverted toward by-label identity: every listed row lumps into one
    # partition, so a label collision reads as one incoherent claim again.
    "R11A3 identity back to the label (one partition per label)", IC,
    """        if isinstance(_m, list) and _m:
          _key = frozenset(str(t).strip().lower() for t in _m)
          _parts.setdefault(_key, []).append(e)""",
    """        if isinstance(_m, list) and _m:
          _key = frozenset(str(t).strip().lower() for t in _m)
          _parts.setdefault(next(iter(_parts), _key), []).append(e)""",
    ("3a label collision: both healthy groups survive",),
  ),
  (
    # D3's stale-alone rule broken: an unhomed legacy row attaches to the
    # fresh partition and drags it down (the O2 defect restored).
    "R11A4 stale legacy row attaches instead of retiring alone", IC,
    """        else:
          _stale.append(e)""",
    """        else:
          _parts[next(iter(_parts))].append(e)""",
    ("3b stale legacy twin retires ALONE, fresh declaration survives",),
  ),
  (
    # D3's legacy fallback killed: a coherent label-only group retires.
    "R11A5 legacy label-parse fallback removed", IC,
    """        elif not _parts:
          _key = frozenset(t for t in _lbl[len("shared:"):].split("+") if t)
          _parts.setdefault(_key, []).append(e)""",
    """        elif not _parts:
          _stale.append(e)""",
    ("3d legacy-only coherent label survives (parse fallback)",),
  ),
]


def run_proof() -> str:
  out = subprocess.run(
    [str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), str(PROOF)],
    capture_output=True, text=True, timeout=300,
  )
  return (out.stdout or "") + (out.stderr or "")


def red_checks(output: str) -> list:
  return [line for line in output.splitlines()
          if line.strip().startswith("[FAIL]")]


def main() -> int:
  failures = []
  for name, path, needle, repl, musts in ABLATIONS:
    original = path.read_bytes()
    text = original.decode("utf-8")
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
