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

    if landed:
        return True, "LAND", "value landed in the stored field"

    proposed = any(m in n for m in PROPOSAL_MARKERS) or _structured_proposal(turn)
    if proposed:
        return True, "PROPOSE", "inferred landing applied and proposed for confirmation"

    return False, "FREEZE", (
        "no forward move: value did not land and nothing was proposed")


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
