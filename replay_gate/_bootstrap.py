# -*- coding: utf-8 -*-
"""Root resolution, env, and DB connections for the replay gate.

The gate code is CONSTANT; the app code under test VARIES by root. That
split is the whole point: point --root at a worktree and the same gate
exercises that build's real handlers.

Never import app modules before calling bind_root().
"""
import io
import os
import sys

# The repo that owns .env and the gate itself. The app code under test may
# live somewhere else entirely (a worktree at an older commit).
HOME_REPO = os.environ.get("REPLAY_GATE_HOME") or r"C:\dev\business_plann_app"
DEFAULT_ROOT = os.environ.get("REPLAY_GATE_ROOT") or HOME_REPO

_BOUND = {"root": None}


def bind_root(root=None):
    """Put <root>/python at the head of sys.path and load .env from HOME_REPO.

    .env is gitignored, so a worktree checkout has none - credentials and
    API keys always come from the home repo regardless of which build is
    under test.
    """
    root = os.path.abspath(root or DEFAULT_ROOT)
    pkg = os.path.join(root, "python")
    if not os.path.isdir(pkg):
        raise SystemExit(f"SETUP FAILED: no python/ package under {root}")
    # Drop any previously bound root so a re-bind cannot resolve stale.
    sys.path[:] = [p for p in sys.path if os.path.normcase(p) != os.path.normcase(pkg)]
    sys.path.insert(0, pkg)

    from dotenv import load_dotenv

    load_dotenv(os.path.join(HOME_REPO, ".env"))
    _BOUND["root"] = root
    return root


def bound_root():
    return _BOUND["root"]


def build_id():
    """Short identity of the build under test, for the report header."""
    root = _BOUND["root"] or DEFAULT_ROOT
    head = "unknown"
    try:
        import subprocess

        head = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        pass
    return f"{root} @ {head}"


def utf8_stdout():
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass


def gate_connection():
    """Write/turn connection, in AUTOCOMMIT.

    TRAP THIS AVOIDS: MySQL REPEATABLE READ pins a snapshot at the first
    read of a transaction, so a non-autocommit connection re-reading a
    draft after the turn wrote it serves the STALE pre-turn row forever
    and the gate reports a false RED ("didn't land") on a build that
    landed it fine. Every connection the gate opens is autocommit.
    """
    from client_intake_and_finmo.intake_submission import get_mysql_connection

    conn = get_mysql_connection()
    try:
        conn.autocommit = True
    except Exception:
        try:
            conn.autocommit(True)
        except Exception:
            pass
    return conn


def read_connection():
    """Separate autocommit connection for stored-field readback.

    A distinct connection means the readback cannot inherit the turn
    connection's transaction snapshot even if the app opened one.
    """
    return gate_connection()
