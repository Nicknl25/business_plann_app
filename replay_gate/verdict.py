# -*- coding: utf-8 -*-
"""Forward-move judgment and RED/GREEN reporting.

One rule, applied identically to every leg: a correction turn at the
completed-financials surface must produce a FORWARD MOVE - the value
LANDS in a stored field, or an inferred landing is APPLIED-AND-PROPOSED.
Anything else (dead stop, verbatim repeat, empty, silent no-op) is a
FREEZE and the gate goes RED.
"""

# The dead-stop signature. Present at 5b5ffbb as:
#   "You gave me {fig} and I couldn't tell where to record it - tell me
#    which line that belongs to and I'll put it there."
# Match ONLY on "couldn't tell where to record". Do NOT match on "tell me
# which line" alone: the FIXED build ships that phrase inside a forward
# move ("...I've set it to X. If that's not right, tell me which line it
# belongs to and I'll move it."), so the looser marker would false-RED
# the fix.
DEAD_END_MARKERS = (
    "couldn't tell where to record",
    "couldn t tell where to record",
    "could not tell where to record",
)

# An inferred landing that ships as a proposal is a forward move.
PROPOSAL_MARKERS = (
    "it looks like you mean",
    "i've set it to",
    "i have set it to",
    "did you mean",
    "i'll take that as",
    "assuming you mean",
)


def _norm(text):
    return " ".join(str(text or "").split()).strip().lower()


def message_of(turn):
    return str((turn or {}).get("assistant_message") or "")


def _structured_proposal(turn):
    """A proposal carried in the turn payload rather than the prose."""
    if not isinstance(turn, dict):
        return False
    for key, val in turn.items():
        k = str(key).lower()
        if any(t in k for t in ("propos", "pending", "confirm", "await")):
            if val:
                return True
    return False


def judge(leg, turn, landed, last_assistant):
    """Return (ok, verdict, detail). verdict: LAND | PROPOSE | FREEZE."""
    msg = message_of(turn)
    n = _norm(msg)

    for marker in DEAD_END_MARKERS:
        if marker in n:
            return False, "FREEZE", (
                "dead stop: handed disambiguation back to the client "
                "(\"couldn't tell where to record it\")")

    if not n:
        return False, "FREEZE", "empty assistant message - turn produced nothing"

    if n == _norm(last_assistant):
        return False, "FREEZE", "verbatim repeat of the previous assistant turn"

    held = (turn or {}).get("guard_hold") if isinstance(turn, dict) else None
    if held:
        # A HOLD IS A FORWARD MOVE (Nick 2026-09-13). Option B: when the
        # client's figure disagrees with what is on file, the guard holds it
        # behind a question rather than landing it. R02, R03, R15 and I03 were
        # written before that ruling and read the hold as a freeze - they
        # asserted the behaviour the ruling replaced. The turn now says it is
        # holding, so the judge can tell a question from a dead end.
        return True, "HOLD", ("held behind a question rather than landed: "
                              + ", ".join(str(h) for h in (held if isinstance(held, list) else [held])))

    if landed:
        return True, "LAND", "value landed in the stored field"

    proposed = any(m in n for m in PROPOSAL_MARKERS) or _structured_proposal(turn)
    if proposed:
        return True, "PROPOSE", "inferred landing applied and proposed for confirmation"

    return False, "FREEZE", (
        "no forward move: value did not land and nothing was proposed")


class _AbortLeg:
    """Stands in for a leg so an aborted run renders through the same path.

    IT DID NOT RENDER. `emit` prints `leg.bug` and `leg.title`, and this class
    carried neither - so the instant an abort fired, the emitter raised
    AttributeError and the gate died mid-report. The run then exited non-zero
    with a traceback and NO verdict: no ABORTED line, no reason, nothing naming
    what had written to the database. A pre-push hook refused a push and could
    not say why (2026-09-26).

    That is worse than the failure it was built to report. `abort` says it
    records a failure row "so the gate can never come back green after
    aborting - a half-run suite that prints GREEN is the worst possible
    outcome"; a suite that prints a traceback instead of its verdict is the
    same class of instrument failure, one step further along. The attributes
    the emitter actually reads are here now, and the abort reason travels in
    the row's `detail` as it always did.
    """
    id = "ABORT"
    kind = "GATE"
    name = "run-aborted"
    # EVERY attribute `emit` reads, found by reading the emitter rather than by
    # fixing one AttributeError at a time: id, kind, bug, title, issue,
    # fix_commit, baseline. Adding them one crash at a time is how a half-fixed
    # reporter still dies on the row after next.
    bug = "run-aborted"
    title = "the database stayed quiet for the whole run"
    claim = "the database stayed quiet for the whole run"
    issue = ""
    fix_commit = ""
    baseline = ""
    fixed_at = ""
    broken_at = ""


class Report(object):
    def __init__(self, build):
        self.build = build
        self.rows = []
        self.quarantined = []
        self.skipped = []

    def add(self, leg, ok, verdict, detail, evidence=""):
        self.rows.append({
            "leg": leg, "ok": bool(ok), "verdict": verdict,
            "detail": detail, "evidence": evidence,
        })

    def abort(self, why):
        """The run stopped before finishing and its verdict means nothing.

        Recorded as a failure row so the gate can never come back green after
        aborting - a half-run suite that prints GREEN is the worst possible
        outcome."""
        self.aborted = why
        self.rows.append({
            "leg": _AbortLeg(), "ok": False, "verdict": "ABORTED",
            "detail": why, "evidence": "",
        })

    def quarantine(self, leg, why):
        self.quarantined.append({"leg": leg, "why": why})

    def skip(self, leg, why):
        self.skipped.append({"leg": leg, "why": why})

    @property
    def failures(self):
        return [r for r in self.rows if not r["ok"]]

    @property
    def green(self):
        return bool(self.rows) and not self.failures

    def emit(self):
        print("")
        print("=" * 78)
        print("REPLAY GATE - every known issue")
        print("  build under test: " + self.build)
        print("=" * 78)
        for r in self.rows:
            leg = r["leg"]
            flag = "  ok  " if r["ok"] else " FAIL "
            ref = f" [{leg.issue}]" if leg.issue else ""
            print(f"[{flag}] {leg.id} {leg.kind:<10} {leg.bug}{ref}")
            print(f"          {leg.title}")
            print(f"          {r['verdict']}: {r['detail']}")
            if r["evidence"]:
                print(f"          {r['evidence']}")
        passed = len(self.rows) - len(self.failures)
        print("-" * 78)
        print(f"{passed}/{len(self.rows)} legs clear")

        if self.skipped:
            print("")
            print(f"  NOT RUN ({len(self.skipped)}) - coverage this run did NOT check:")
            for s in self.skipped:
                print(f"    - {s['leg'].id} {s['leg'].bug}: {s['why']}")
        if self.quarantined:
            print("")
            print(f"  QUARANTINED ({len(self.quarantined)}) - legs excluded from this verdict:")
            for q in self.quarantined:
                print(f"    - {q['leg'].id} {q['leg'].bug}: {q['why']}")
            print("    These are NOT covered. Fix the leg, re-prove, then trust it.")

        if self.green:
            print("")
            print("  GREEN - every known issue that ran is clear.")
            if self.skipped or self.quarantined:
                print("  (Coverage is partial - see NOT RUN / QUARANTINED above.)")
            print("  Safe to spend a Cowork run.")
        else:
            print("")
            print("  RED - bounce to VS. Regressed or violated:")
            for r in self.failures:
                leg = r["leg"]
                kind = "FIXED BUG REGRESSED" if leg.kind == "REGRESSION" \
                    else "INVARIANT VIOLATED"
                ref = f" [{leg.issue}]" if leg.issue else ""
                print(f"    * {kind}: {leg.bug}{ref}  ({leg.id})")
                print(f"        {leg.title}")
                print(f"        {r['detail']}")
                if r["evidence"]:
                    print(f"        {r['evidence']}")
                print(f"        fixed at {leg.fix_commit}, was live at {leg.baseline}")
            print("")
            print("  Do NOT spend a Cowork run on this build.")
        print("=" * 78)
        return 0 if self.green else 1
