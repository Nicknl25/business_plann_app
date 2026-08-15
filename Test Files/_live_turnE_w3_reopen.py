"""TURN E (CW-033, 2026-08-15): the W3 t2 reopen-surface receipt on a Sumac
clone, asserting ABSENCE of the two false clauses mini found in the turn-5
artifact (_live_cw033_turn5_20260814.txt W3 t2):
  E1  'monthly capacity -> 40'   (the week twin spoken under the period label)
  E2  "didn't end up using 40"   (the stated, converted figure claimed unused)
Reuses the turn-5 harness helpers verbatim (clone / post / cleanup).

  .venv\Scripts\python.exe "Test Files\_live_turnE_w3_reopen.py"
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("t5", HERE / "_live_cw033_turn5_turns.py")
t5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t5)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(t5.REPO_ROOT / ".env", override=False)
    sys.path.insert(0, str(t5.REPO_ROOT / "python"))
    sys.path.insert(0, str(t5.REPO_ROOT / "python" / "client_intake_and_finmo"))
    from intake_submission import get_mysql_connection  # type: ignore
    conn = get_mysql_connection()
    check, note = t5.check, t5.note

    print("TURN E - W3 (mini's C3 sequence) on a Sumac clone, absence checks")
    c3, k3 = t5.make_clone(conn, t5.SUMAC, "vs33te", None, ())
    status, reply = t5.post_turn(c3, k3, "Our mowing capacity should be 40 a month, not 34.")
    print(f"\nW3 t1 FULL REPLY < [{status}]\n{reply}\n")
    row = t5.ops_rows(conn, c3).get("Property contract", {})
    check("t1 live turn 200", status == 200, str(status))
    check("t1 identity on the 12-period row (period 40)", row.get("period") == 40.0, str(row))
    status, reply = t5.post_turn(c3, k3, "Sorry - mowing capacity is 40 a week.")
    print(f"\nW3 t2 FULL REPLY < [{status}]\n{reply}\n")
    row = t5.ops_rows(conn, c3).get("Property contract", {})
    lo = reply.lower().replace("→", "->")
    check("t2 live turn 200", status == 200, str(status))
    check("t2 CONVERTS (period 173.3333, wk 40)",
          row.get("period") is not None and abs(float(row["period"]) - 173.3333) < 0.01
          and row.get("wk") == 40.0, str(row))
    check("t2 speaks the client's cadence", "40 a week" in lo, reply[:200])
    check("E1 NO 'monthly capacity -> 40' (the week twin is weekly)",
          "monthly capacity -> 40;" not in lo and "monthly capacity -> 40." not in lo
          and "monthly capacity -> 40 " not in lo and not lo.endswith("monthly capacity -> 40"),
          reply[:400])
    check("E1 the week twin is spoken as weekly capacity -> 40",
          "weekly capacity -> 40" in lo, reply[:400])
    check("E2 NO false non-use claim of the stated 40",
          "didn't end up using 40" not in lo and "didn’t end up using 40" not in lo,
          reply[:600])
    t5.cleanup(conn, c3)
    conn.close()
    print()
    if t5.FAILURES:
        print(f"RESULT: RED - {len(t5.FAILURES)} failing check(s):")
        for f in t5.FAILURES:
            print("  -", f)
        return 1
    print("RESULT: GREEN - all live checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
