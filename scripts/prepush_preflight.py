"""PRE-PUSH - the preflight runs on every push that touches post-intake code
(Nick 2026-09-11: "install the PREFLIGHT, not the full replay ... 0.6 seconds
on every push touching post-intake, mandatory, no bypass worth using").

Called by .git/hooks/pre-push with git's ref lines on stdin. When the pushed
commits touch a post-intake path it runs scripts/preflight.py and
refuses the push on failure. Pushes that touch no post-intake path pass
straight through.

The ten-draft replay (scripts/replay_post_intake.py) is deliberately NOT here:
it is a command, run before any push that changes payload shape, schema or
authoring, and always before a Cowork run.

The preflight checks the WORKING TREE, so a push of something other than HEAD,
or uncommitted post-intake edits, would check code that is not being shipped -
both refuse rather than report a verdict about the wrong build.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZERO = "0" * 40
POST_INTAKE_PATHS = (
    "python/client_intake_and_finmo/",
    "python/financial_model_engine/",
    "python/api_handlers/intake_consult.py",
    "python/writing_phase_v2/",
    "client_statements_output_excel/",
    "scripts/preflight.py",
    "scripts/prepush_preflight.py",
    "replay_gate/",
)


# THE KNOWN-ISSUE GATE on pushes touching intake or payroll (Nick 2026-09-11:
# "100 seconds is nothing, and it's the gate that caught the seven - the hook
# as it stands would have let last night through"). Measured: on e4a13f26
# every unit pin the preflight runs passed while seven gate legs were red.
# The writing phase is not gated here - the gate does not test it.
GATE_PATHS = (
    "python/client_intake_and_finmo/",
    "python/financial_model_engine/",
    "python/api_handlers/intake_consult.py",
    "client_statements_output_excel/",
    "replay_gate/",
)
GATE_REPORT = os.path.join(ROOT, "_runtime", "prepush_gate_last.txt")


def _gate_relevant(path: str) -> bool:
    if not path.startswith(GATE_PATHS):
        return False
    # The gate's own notes and hand-off files are not code under test.
    return not path.startswith("replay_gate/") or path.endswith(".py")


def run_known_issue_gate() -> int:
    """The whole known-issue gate, strict GPT lock (a leg can never spend).
    The FULL output is saved; every failing leg and the clear count are
    printed - never a tail."""
    env = dict(os.environ)
    env["GPT_RESPONSE_LOCK_STRICT"] = "1"
    os.makedirs(os.path.dirname(GATE_REPORT), exist_ok=True)
    with open(GATE_REPORT, "w", encoding="utf-8") as fh:
        r = subprocess.run([sys.executable, "-X", "utf8", "-m", "replay_gate.run_gate"],
                           cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    with open(GATE_REPORT, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    fails = [l for l in lines if l.startswith("[ FAIL ]")]
    clear = next((l.strip() for l in lines if l.strip().endswith("legs clear")), "no clear count")
    print("KNOWN-ISSUE GATE: %s (exit %d) - full output in %s" % (clear, r.returncode, GATE_REPORT))
    for l in fails:
        print("  " + l)
    return r.returncode


def _git(*args) -> str:
    return subprocess.check_output(["git", "-C", ROOT] + list(args), text=True).strip()


def pushed_files(ref_lines):
    files, shas = set(), set()
    for line in ref_lines:
        parts = line.split()
        if len(parts) < 4 or parts[1] == ZERO:
            continue  # malformed, or a branch delete
        local_sha, remote_sha = parts[1], parts[3]
        shas.add(local_sha)
        if remote_sha == ZERO:
            out = _git("log", "--name-only", "--format=", local_sha, "--not", "--remotes")
        else:
            out = _git("diff", "--name-only", remote_sha, local_sha)
        files.update(f for f in out.splitlines() if f.strip())
    return files, shas


def main() -> int:
    files, shas = pushed_files(sys.stdin.read().splitlines())
    hits = sorted(f for f in files if f.startswith(POST_INTAKE_PATHS))
    if not hits:
        return 0
    print("PREFLIGHT (pre-push): %d post-intake file(s) in this push" % len(hits))
    if shas - {_git("rev-parse", "HEAD")}:
        print("PUSH REFUSED: pushing a commit that is not HEAD - the preflight checks the "
              "working tree, so it would not be checking what you ship.", file=sys.stderr)
        return 1
    dirty = [l for l in _git("status", "--porcelain", "--", *POST_INTAKE_PATHS, "replay_gate").splitlines()
             if l.strip() and (not l[3:].startswith("replay_gate/") or l.rstrip().endswith(".py"))]
    if dirty:
        print("PUSH REFUSED: uncommitted post-intake changes in the tree - the preflight would "
              "check them, not the push. Commit or stash first:", file=sys.stderr)
        for l in dirty[:12]:
            print("  " + l, file=sys.stderr)
        return 1
    r = subprocess.run([sys.executable, "-X", "utf8",
                        os.path.join(ROOT, "scripts", "preflight.py")], cwd=ROOT)
    if r.returncode != 0:
        print("PUSH REFUSED: preflight failed (exit %d)." % r.returncode, file=sys.stderr)
        return 1
    if any(_gate_relevant(f) for f in files):
        code = run_known_issue_gate()
        if code != 0:
            print("PUSH REFUSED: the known-issue gate is not green (exit %d). A red leg "
                  "is either a real regression or a leg that encodes old behaviour - "
                  "both are fixed before the push, never skipped." % code, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
