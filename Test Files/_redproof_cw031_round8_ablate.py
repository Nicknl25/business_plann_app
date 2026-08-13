"""CW-031 round 8 -- the RED half: neuter one fix at a time on the real files.

A proof that is only ever green proves nothing. This reverts each hunk to the
exact code mini measured as broken in _mini_cw031_r7_audit_20260813.txt,
re-runs Test Files/_redproof_cw031_round8_fixes.py, and requires that it goes
red on THAT hunk's own checks. If a hunk can be removed with the proof still
green, that fix is decorative and this says so.

The files are restored from the bytes read before each ablation, and the proof
is re-run at the end to prove they restored.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round8_ablate.py"
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IC = REPO_ROOT / "python" / "api_handlers" / "intake_consult.py"
IR = REPO_ROOT / "python" / "client_intake_and_finmo" / "issue_registry.py"
PROOF = REPO_ROOT / "Test Files" / "_redproof_cw031_round8_fixes.py"

_TRANSPORT_NEEDLE = "      if field in _PER_LINE_COGS_TRANSPORT_FIELDS:"

# (name, file, needle, replacement, checks that MUST go red)
ABLATIONS = [
  (
    # THE DEFECT AS MINI MEASURED IT: the door consumes the key and the
    # correction path persists it anyway, on all twelve live turns.
    "B1 the per-line transport keys consumed at the correction door", IC,
    _TRANSPORT_NEEDLE,
    "      if False:",
    ("1a transport key not stored", "1d the group transport key not stored"),
  ),
  (
    # mini 4d: at N=2 one coincidence is enough.
    "B3 the N>=3 floor under the value-equality net", IC,
    """  if (len(directory) >= 3 and receipt["written"]""",
    """  if (len(directory) >= 2 and receipt["written"]""",
    ("2a N=2 coincidence mints NO group",
     "2b the receipt does not claim a collapse"),
  ),
  (
    # mini 4e: the one-patch condition misses a declaration split over two
    # messages, which is how clients actually talk.
    "B4 POST-WRITE state (back to the one-patch condition)", IC,
    """    _rates = [_safe_float(e["row"].get("cogs_percent_of_line_revenue")) for e in directory]""",
    """    _written_names = {w["line_name"] for w in receipt["written"]}
    _rates = [_safe_float(e["row"].get("cogs_percent_of_line_revenue")) for e in directory
              if e["line_name"] in _written_names]""",
    ("2h the second message completes the collapse (POST-WRITE state)",),
  ),
  (
    "B5 the DECLARED provenance stamp", IC,
    """      member["row"]["cogs_cost_structure_group_basis"] = "declared\"""",
    """      member["row"].pop("cogs_cost_structure_group_basis", None)""",
    ("2i a DECLARED all-lines collapse is recorded as declared",),
  ),
  (
    "B6 the INFERRED provenance stamp", IC,
    """        entry["row"]["cogs_cost_structure_group_basis"] = "inferred from identical stated rates\"""",
    """        entry["row"].pop("cogs_cost_structure_group_basis", None)""",
    ("2d the stored group names its own authority",
     "2f the assertion passes it WITHOUT calling it the client's own"),
  ),
  (
    "B7 the receipt sentence that makes the inference correctable", IC,
    """    if group.get("basis") == "uniform rates stated":""",
    """    if False:""",
    ("2e the receipt names the inference as an inference",),
  ),
  (
    "B8 the verdict naming WHOSE collapse it read", IR,
    """        _whose = ("the client's own recorded collapse" if _bases == {"declared"}
                  else "a recorded collapse (" + "; ".join(sorted(_bases)) + ")")""",
    """        _whose = "the client's own recorded collapse\"""",
    ("2f the assertion passes it WITHOUT calling it the client's own",),
  ),
  (
    # THE DELETED RULE, restored verbatim: divide by 100 only above 1.0.
    "B9 the stage blend's refusal (back to _normalize_ratio_like's rescaling)", IC,
    """      if float(numeric) < 0.0 or float(numeric) > 1.0:
        logger.info(
          "BLEND_RATE_NOT_A_FRACTION path=stage field=%s value=%r - refused, never rescaled",
          field_name, raw_value,
        )
        continue""",
    """      if float(numeric) > 1.0:
        numeric = float(numeric) / 100.0""",
    # NOT 3d: with the rescaling restored, 1.5 becomes 0.015, which the
    # mid-intake derivability guard then drops anyway (0.015 is not derivable
    # from the message's 150) -- so 3d would be measuring that guard, not this
    # rule. 3c is the discriminating case: 71 rescaled to 0.71 and stored.
    ("3c stage - a non-fraction is REFUSED, never rescaled",),
  ),
  (
    # The correction path was WORSE than the stage path: no conversion, no
    # check -- 71 stored 7,100% and re-derived the dollar twin to match.
    "B10 the correction blend's refusal (back to storing it raw)", IC,
    """        if _blend is None or float(_blend) < 0.0 or float(_blend) > 1.0:""",
    """        if _blend is None:""",
    ("3g correction path REFUSES a non-fraction and asks",
     "3h the blend question does not borrow the per-line wording"),
  ),
  (
    "B11 the per-line transport keys kept out of the say-do dropped list", IC,
    """      - _PER_LINE_COGS_TRANSPORT_FIELDS)""",
    """      )""",
    ("3k a transport key is never reported as an unapplied field",),
  ),
  (
    "B12 the blend refusal's own wording", IC,
    """    _of_what = ("revenue" if str(first.get("scope") or "") == "blend"
                else "that line's revenue")""",
    """    _of_what = "that line's revenue\"""",
    ("3h the blend question does not borrow the per-line wording",),
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
  if "ALL CLEAN" not in baseline:
    print("BASELINE IS NOT CLEAN -- nothing below means anything:")
    print(baseline[-3000:])
    return 1
  print("baseline: ALL CLEAN\n")

  for name, path, needle, replacement, must_fail in ABLATIONS:
    original = path.read_bytes()
    text = original.decode("utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8")
    # intake_consult.py is CRLF and issue_registry.py is LF; a multi-line needle
    # written here in LF silently matches nothing in the first. Translate rather
    # than rewrite line endings on a production file.
    if "\r\n" in text:
      needle = needle.replace("\n", "\r\n")
      replacement = replacement.replace("\n", "\r\n")
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
    if "ALL CLEAN" in out and not reds:
      problems.append(f"{name}: DECORATIVE -- removed with the proof still clean")
      print(f"[DECORATIVE] {name}: proof stayed clean without it")
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
                          "python/client_intake_and_finmo/issue_registry.py"],
                         cwd=str(REPO_ROOT), capture_output=True)
  print("\nrestored; git status of the ablated files:")
  print("  " + (after.stdout.decode().strip() or "(clean vs HEAD)"))
  final = run_proof()
  print(f"post-ablation re-run: {'ALL CLEAN' if 'ALL CLEAN' in final else 'RED'}")
  if "ALL CLEAN" not in final:
    problems.append("files did not restore: proof no longer clean")

  print()
  if problems:
    for p in problems:
      print(f"PROBLEM: {p}")
    return 1
  print("EVERY FIX IS LOAD-BEARING -- each one, removed alone, turns its own checks red")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
