# -*- coding: utf-8 -*-
"""Per-leg proof: RED on its own broken baseline, GREEN on the fix.

A leg that passes on the commit where its bug was still live is on a
fixture path - it is not reaching the code that broke. Those legs get
QUARANTINED: excluded from the gate verdict and named, rather than
silently believed.

Each leg is proved ALONE (`--only <leg id>`), in a clean subprocess with
its own bound root. Running one leg at a time is what makes a red
attributable: several of these bugs were fixed in one "slate" commit, so
a whole-suite run at a shared baseline goes red for many reasons at once.
"""
import os
import re
import subprocess
import sys

from . import _bootstrap

BASELINE_DIR = os.environ.get("REPLAY_GATE_BASELINE_DIR", r"C:\dev\bpa_gate_baselines")

# Modules a completeness probe must be able to import for a baseline to be
# considered usable. `api_handlers.intake_consult` transitively pulls most of
# the tree, which is why a partial checkout surfaced there first (a dropped
# realism_memo.py took it down mid-import).
#
# Kept deliberately narrow. A broader list would quarantine more aggressively,
# but every module added here can quarantine legs that would otherwise have
# proved fine, so coverage is traded for caution one entry at a time.
BASELINE_PROBE_MODULES = ("api_handlers.intake_consult",)

# Paths checked out into every baseline worktree. `python/` alone was enough
# until the workbook became a pinned surface: client_statements_output_excel/
# lives OUTSIDE python/, so a leg importing it would have resolved it from the
# HOME repo - i.e. computed a "baseline" workbook hash with CURRENT workbook
# code, and matched itself every time. A vacuous golden master is worse than
# none. Cached trees built before this are repaired by the presence check in
# ensure_baseline().
BASELINE_PATHS = ("python", "client_statements_output_excel")

# Baselines that failed the probe and were repaired in this pass. Surfaced in
# the proof table: a tree that needed repairing was, until this run, silently
# producing crash-reds.
REPAIRED = set()


# A leg that dies on ImportError/AttributeError/TypeError exits 1 - the SAME
# code as a clean behavioural red. Before this, prove() classified on the exit
# code alone, so a crash-red printed as "RED ... PROVEN" and was invisible
# without --verbose. Eight legs rode that on 2026-08-12; one of them (I10) was
# very likely GREEN-on-its-own-baseline underneath the crash.
#
# The child log is ALWAYS scanned now, verbose or not. --verbose only controls
# whether the full log is echoed.
def structural_reason(log):
    """-> the exception text if the run died, else '' for a behavioural red."""
    for line in (log or "").splitlines():
        s = line.strip()
        if s.startswith("ERROR: leg raised "):
            return s[len("ERROR: leg raised "):].strip()[:220]
    if "Traceback (most recent call last)" in (log or ""):
        for line in reversed((log or "").splitlines()):
            s = line.strip().lstrip("| ").strip()
            if s and ("Error" in s or "Exception" in s):
                return s[:220]
        return "child process traceback (no exception line found)"
    return ""


# A golden-master leg may pin SEVERAL surfaces at once - the floor for a
# single-line business covers the model input, the finmo payload and the
# workbook formulas, and ALL of them have to be identical for the floor to
# hold. Each line is "GOLDEN-SHA <surface> <hex>"; a bare "GOLDEN-SHA <hex>"
# is still accepted and files under "artifact".
GOLDEN_RE = re.compile(r"GOLDEN-SHA\s+(?:([A-Za-z0-9_.:-]+)\s+)?([0-9a-f]{16,64})")


def golden_shas(log):
    """-> {surface: hex} for every GOLDEN-SHA line the leg printed."""
    out = {}
    for name, digest in GOLDEN_RE.findall(log or ""):
        out[name or "artifact"] = digest
    return out


class BaselineIncomplete(RuntimeError):
    """The baseline tree exists but cannot be imported.

    This is NOT a red. A leg whose baseline cannot import tells you nothing
    about whether its bug behaves - the run would have crashed identically on
    a build where the bug was fixed. Raising this routes the leg to
    quarantine instead of letting a crash masquerade as red-on-broken.
    """


def _git(args, cwd=None):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                          text=True, timeout=600)


def probe_baseline(root, home=None):
    """Clean-subprocess import check. -> (ok, detail)

    Runs in its own interpreter so a partial tree cannot poison the proving
    process's sys.modules, and so a hard crash on import is caught as a
    non-zero exit rather than taking the pass down with it.
    """
    home = home or _bootstrap.HOME_REPO
    pkg = os.path.join(root, "python")
    src = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib\n"
        "for m in %r:\n"
        "    importlib.import_module(m)\n"
        "print('BASELINE_IMPORT_OK')\n"
    ) % (pkg, list(BASELINE_PROBE_MODULES))
    try:
        p = subprocess.run([sys.executable, "-c", src], cwd=home,
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "import probe timed out after 180s"
    if p.returncode == 0 and "BASELINE_IMPORT_OK" in (p.stdout or ""):
        return True, ""
    err = (p.stderr or p.stdout or "").strip().splitlines()
    tail = err[-1] if err else f"rc={p.returncode}"
    return False, tail[:300]


def ensure_baseline(sha, home=None):
    """Materialize (and cache) a worktree with <sha>'s python/ package.

    Only python/ is checked out - it is the whole import surface and a
    full checkout of ~9,600 files per baseline would make proving slow
    enough that nobody runs it. .env is copied in because it is
    gitignored, so a worktree has none and the app's own
    parents[2]/'.env' lookups would otherwise miss.
    """
    home = home or _bootstrap.HOME_REPO
    root = os.path.join(BASELINE_DIR, sha)
    marker = os.path.join(root, "python", "api_handlers", "intake_consult.py")

    if not os.path.isfile(marker):
        os.makedirs(BASELINE_DIR, exist_ok=True)
        r = _git(["worktree", "add", "--no-checkout", "--detach", root, sha], cwd=home)
        if r.returncode != 0 and "already exists" not in (r.stderr or ""):
            raise RuntimeError(f"worktree add {sha} failed: {r.stderr.strip()}")
        r = _git(["checkout", "-f", sha, "--"] + list(BASELINE_PATHS), cwd=root)
        if r.returncode != 0:
            raise RuntimeError(f"checkout @ {sha} failed: {r.stderr.strip()}")
        src_env = os.path.join(home, ".env")
        dst_env = os.path.join(root, ".env")
        if os.path.isfile(src_env) and not os.path.isfile(dst_env):
            with open(src_env, "rb") as fh:
                data = fh.read()
            with open(dst_env, "wb") as fh:
                fh.write(data)
        if not os.path.isfile(marker):
            raise RuntimeError(
                f"baseline {sha} has no python/api_handlers/intake_consult.py")

    # COMPLETENESS PROBE - runs on the cached path too, deliberately.
    #
    # The marker file alone is not completeness. A worktree checkout that died
    # partway (an index.lock crash) leaves intake_consult.py in place while a
    # module it imports is missing; the legs then crash on import, exit 1, and
    # the exit-code check reads that as a clean red-on-broken.
    #
    # Probing only on the freshly-built path would miss exactly the case that
    # bit us: the partial tree was ALREADY on disk from the crashed checkout,
    # so every later pass took the cache branch and never re-checked it.
    excel_pkg = os.path.join(root, "client_statements_output_excel", "__init__.py")
    ok, detail = probe_baseline(root, home=home)
    if ok and os.path.isfile(excel_pkg):
        return root
    if ok and not os.path.isfile(excel_pkg):
        detail = ("client_statements_output_excel/ is missing - this tree "
                  "predates the workbook surface being pinned")

    # ONE repair attempt. The usual cause is a truncated checkout - a slow or
    # interrupted `checkout -f -- python` leaves a subset of the tree on disk
    # and every later pass takes the cache branch over it. Re-running the
    # scoped checkout is idempotent and fixes exactly that.
    #
    # Deliberately one attempt, and the outcome is reported either way: a
    # baseline that needs repairing on every pass is telling you something,
    # and silently healing it forever would hide that.
    repair = _git(["checkout", "-f", sha, "--"] + list(BASELINE_PATHS), cwd=root)
    if repair.returncode != 0:
        raise BaselineIncomplete(
            f"{sha} tree is incomplete - {detail}; repair checkout failed: "
            f"{(repair.stderr or '').strip()[:200]}")
    ok, detail2 = probe_baseline(root, home=home)
    if not ok:
        raise BaselineIncomplete(
            f"{sha} tree is incomplete even after a repair checkout - {detail2}")
    REPAIRED.add(sha)
    return root


def _run_one(root, leg_id, tier, home):
    env = dict(os.environ)
    env["PYTHONPATH"] = home + os.pathsep + env.get("PYTHONPATH", "")
    # --prove compares each golden surface across BOTH commits itself, which
    # is a stronger check than the blessed record and is the authority here.
    # Without this the bare comparison would also fire, and a leg that
    # legitimately moved would go RED at HEAD instead of reporting DRIFT.
    env["REPLAY_GATE_PROVING"] = "1"
    cmd = [sys.executable, "-m", "replay_gate.run_gate",
           "--root", root, "--only", leg_id, "--tier", tier, "--quiet"]
    p = subprocess.run(cmd, cwd=home, env=env, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def prove(legs, tier="fast", home=None, verbose=False):
    """-> (all_ok, results, quarantine_ids)"""
    home = home or _bootstrap.HOME_REPO
    current = home
    results = []
    quarantine = []
    for leg in legs:
        try:
            base_root = ensure_baseline(leg.baseline, home=home)
        except BaselineIncomplete as exc:
            # Explicitly NOT a red. The leg is unproven, not proven-red.
            results.append({"leg": leg, "base_rc": None, "cur_rc": None,
                            "ok": False, "incomplete": True,
                            "why": (f"BASELINE INCOMPLETE - {exc}. Not a red: a "
                                    f"leg whose baseline cannot import proves "
                                    f"nothing either way."),
                            "log": ""})
            quarantine.append(leg.id)
            continue
        except Exception as exc:
            results.append({"leg": leg, "base_rc": None, "cur_rc": None,
                            "ok": False, "why": f"baseline unavailable: {exc}",
                            "log": ""})
            quarantine.append(leg.id)
            continue
        base_rc, base_log = _run_one(base_root, leg.id, tier, home)
        cur_rc, cur_log = _run_one(current, leg.id, tier, home)
        crash = structural_reason(base_log) if base_rc == 1 else ""
        proof_class = getattr(leg, "proof", "behavioural")
        labelled = proof_class == "structural-absence"

        if proof_class == "golden-master":
            # NEGATIVE CONTROL. The claim is "this output did not change", so
            # green-on-both is the PASS, not a fixture path - and the proof is
            # that the artifact hash matches ACROSS the two commits.
            b_map, c_map = golden_shas(base_log), golden_shas(cur_log)
            shared = sorted(set(b_map) & set(c_map))
            moved = [k for k in shared if b_map[k] != c_map[k]]
            missing = sorted(set(b_map) ^ set(c_map))
            gok = (base_rc == 0 and cur_rc == 0 and bool(shared)
                   and not moved and not missing)
            if not b_map or not c_map:
                outcome, why = "UNEARNED", (
                    "golden-master leg printed no GOLDEN-SHA on "
                    + ("the baseline" if not b_map else "the current build")
                    + " - without hashes from BOTH sides there is nothing to "
                    "compare and the control proves nothing")
            elif missing:
                outcome, why = "UNEARNED", (
                    f"surfaces hashed on only ONE side: {', '.join(missing)} - "
                    f"a surface that vanished is not a match, it is an "
                    f"unmeasured surface")
            elif moved:
                outcome, why = "DRIFT", ("THE OUTPUT MOVED on " + ", ".join(
                    f"{k} (baseline {b_map[k][:12]} vs current {c_map[k][:12]})"
                    for k in moved) + ". This leg exists to prove it does not.")
            elif base_rc != 0 or cur_rc != 0:
                outcome, why = "UNEARNED", (
                    f"hashes match but the leg's own assertions failed "
                    f"(base rc={base_rc}, current rc={cur_rc})")
            else:
                outcome, why = "GOLDEN", (
                    f"{len(shared)} surface(s) identical on both commits: "
                    + ", ".join(f"{k}={b_map[k][:12]}" for k in shared)
                    + " (negative control - green on both sides is the pass)")
            results.append({"leg": leg, "base_rc": base_rc, "cur_rc": cur_rc,
                            "ok": gok, "why": why, "outcome": outcome,
                            "crash": "", "labelled": False, "golden": b_map,
                            "log": (base_log + cur_log) if verbose else ""})
            if not gok:
                quarantine.append(leg.id)
            continue

        # RED on the baseline (1) and GREEN on the fix (0). A setup failure (2)
        # or a crash on either side proves nothing.
        ok = (base_rc == 1 and cur_rc == 0)
        outcome = "PROVEN" if ok else "QUARANTINE"
        why = ""
        if base_rc == 0:
            why = ("PASSED on its own broken baseline - fixture path, the leg "
                   "is not reaching the code that broke")
        elif base_rc == 2 or cur_rc == 2:
            why = "setup failed - the leg never reached its surface"
        elif cur_rc != 0:
            why = ("RED on the current build too - either the fix regressed or "
                   "the leg's assertion is wrong")
        elif base_rc not in (0, 1):
            why = f"baseline run crashed (rc={base_rc})"
        elif crash and labelled:
            # Expected, declared, and justified in the leg's proof_note.
            outcome = "STRUCT-ABSENCE"
            why = (f"declared STRUCTURAL-ABSENCE: {crash}. Honest but NOT "
                   f"behavioural - the capability did not exist at this "
                   f"commit. {getattr(leg, 'proof_note', '') or ''}").strip()
        elif crash:
            # THE UNEARNED CLASS. Exit code 1, but the leg died before it could
            # observe anything. Says a signature changed; says nothing about
            # whether the bug behaved.
            ok, outcome = False, "UNEARNED"
            why = (f"CRASH-RED on the baseline, not a behavioural red: {crash}. "
                   f"The leg never reached its assertion, so the property it "
                   f"pins was NEVER evaluated on the broken side - it may even "
                   f"have held there. Re-fixture to the baseline's own call "
                   f"shape, or declare STRUCTURAL_ABSENCE with the grep that "
                   f"proves the capability was missing.")
        elif labelled:
            # Good news worth surfacing: the label is now stricter than reality.
            outcome = "PROVEN"
            why = ("labelled STRUCTURAL-ABSENCE but the baseline red is "
                   "BEHAVIOURAL - the label can be dropped")
        results.append({"leg": leg, "base_rc": base_rc, "cur_rc": cur_rc,
                        "ok": ok, "why": why, "outcome": outcome,
                        "crash": crash, "labelled": labelled,
                        "log": (base_log + cur_log) if verbose else ""})
        if not ok:
            quarantine.append(leg.id)
    return (not quarantine), results, quarantine


def emit(results, quarantine):
    word = {0: "GREEN", 1: "RED", 2: "SETUP-FAIL", None: "n/a"}
    print("")
    print("=" * 78)
    print("PER-LEG PROOF   (each leg alone: RED on its broken baseline, GREEN on the fix)")
    print("=" * 78)
    print(f"{'leg':<5} {'bug':<32} {'baseline':<9} {'on base':<11} {'on now':<8} proof")
    print("-" * 78)
    for r in results:
        leg = r["leg"]
        b = word.get(r["base_rc"], f"rc={r['base_rc']}")
        c = word.get(r["cur_rc"], f"rc={r['cur_rc']}")
        if r.get("crash"):
            b = "CRASH-RED"          # never printed as a plain RED again
        if r.get("outcome") in ("GOLDEN", "DRIFT"):
            b = "SAME" if r.get("outcome") == "GOLDEN" else "MOVED"
        if r.get("incomplete"):
            b = "INCOMPLETE"
        mark = r.get("outcome") or ("PROVEN" if r["ok"] else "QUARANTINE")
        print(f"{leg.id:<5} {leg.bug[:32]:<32} {leg.baseline[:7]:<9} {b:<11} {c:<8} {mark}")
        if r["why"]:
            print(f"      -> {r['why']}")
        if r["log"]:
            for line in r["log"].splitlines():
                print(f"         | {line}")
    print("-" * 78)
    proven = [r for r in results if r["ok"] and r.get("outcome") not in
              ("STRUCT-ABSENCE", "GOLDEN")]
    golden = [r for r in results if r.get("outcome") == "GOLDEN"]
    drift = [r for r in results if r.get("outcome") == "DRIFT"]
    absent = [r for r in results if r.get("outcome") == "STRUCT-ABSENCE"]
    unearned = [r for r in results if r.get("outcome") == "UNEARNED"]
    incomplete = [r for r in results if r.get("incomplete")]
    other = [r for r in results if not r["ok"] and not r.get("incomplete")
             and r.get("outcome") not in ("UNEARNED", "DRIFT")]

    # THE COUNT, split. One number cannot carry this: "43/43 proven" was true
    # by exit code and false by meaning on 2026-08-12.
    print(f"COUNT   {len(proven)} proven BEHAVIOURALLY (red shows the bug behaving)")
    print(f"        {len(absent)} STRUCTURAL-ABSENCE (declared + justified; not behavioural)")
    print(f"        {len(golden)} GOLDEN-MASTER (negative control: output identical on both commits)")
    print(f"        {len(drift)} DRIFT (a negative control MOVED - the output changed)")
    print(f"        {len(unearned)} UNEARNED (crash-red / no hash: the property was never evaluated)")
    print(f"        {len(other)} other failures   |   {len(incomplete)} baseline incomplete")
    print(f"        {len(results)} legs total")

    if drift:
        print("")
        print(f"  DRIFT ({len(drift)}) - A NEGATIVE CONTROL MOVED. Read this first:")
        for r in drift:
            print(f"    - {r['leg'].id} {r['leg'].bug}: {r['why']}")
        print("    A golden-master leg exists to prove an output did NOT change.")
        print("    A DRIFT means it did. Nothing else in this table matters until")
        print("    you know whether that change was intended.")
    if unearned:
        print("")
        print(f"  UNEARNED ({len(unearned)}) - the property was never evaluated:")
        for r in unearned:
            print(f"    - {r['leg'].id} {r['leg'].bug} @ {r['leg'].baseline[:7]}")
            print(f"        {r['crash'] or r['why']}")
        print("    A crash-red is not evidence. Each of these may be hiding a leg")
        print("    that would go GREEN on its own broken baseline. Re-fixture to")
        print("    the baseline's own call shape (see surface.call_compat), or")
        print("    declare proof=STRUCTURAL_ABSENCE with the grep that justifies it.")
    if absent:
        print("")
        print(f"  STRUCTURAL-ABSENCE ({len(absent)}) - honest, declared, NOT behavioural:")
        for r in absent:
            print(f"    - {r['leg'].id} {r['leg'].bug} @ {r['leg'].baseline[:7]}: {r['crash']}")
        print("    The capability did not exist at these commits, so no behavioural")
        print("    red was available. They guard the CURRENT build (their green side")
        print("    is behavioural); they do not prove the broken side.")
    if REPAIRED:
        print("")
        print(f"  REPAIRED BASELINES ({len(REPAIRED)}): "
              + ", ".join(sorted(REPAIRED)))
        print("    These trees failed the import probe and were rebuilt before")
        print("    proving. Any EARLIER proof run against them was reading")
        print("    crash-reds, not behavioural reds - re-prove anything that")
        print("    was 'PROVEN' against these before this run.")
    if incomplete:
        print("")
        print(f"  BASELINE INCOMPLETE ({len(incomplete)}) - these were NOT proved red:")
        for r in incomplete:
            print(f"    - {r['leg'].id} {r['leg'].bug} @ {r['leg'].baseline[:7]}")
        print("    Their baseline trees could not import. A crash-red is not a")
        print("    behavioural red. Rebuild the worktree and re-prove:")
        shas = sorted({r["leg"].baseline[:7] for r in incomplete})
        for sha in shas:
            print(f"      git -C <repo> worktree remove --force <baselines>/{sha}")
            print(f"      ... then re-run --prove to rebuild {sha} cleanly")
    if quarantine:
        print("")
        print("  QUARANTINED: " + ", ".join(quarantine))
        print("  These legs are NOT trusted and are excluded from the gate")
        print("  verdict until they can go red on their own broken baseline.")
        print("  Pass them to the gate with --quarantine to keep it honest:")
        print("    ... --quarantine " + ",".join(quarantine))
        return 1
    print("")
    if absent:
        print(f"  CLEAN - {len(proven)} legs go red BEHAVIOURALLY on the commit where")
        print(f"  their bug was live and green on the fix; {len(absent)} are declared")
        print("  STRUCTURAL-ABSENCE. No unearned proofs. The gate is on the real chain.")
    else:
        print("  ALL LEGS PROVEN BEHAVIOURALLY - every red shows the bug behaving on")
        print("  the commit where it was live, and green on the fix. No crash-reds.")
    return 0
