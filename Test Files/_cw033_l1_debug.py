# CW-033 debug: one L1 turn, full reply + did the bundled 3,100 land +
# which stage is active afterwards.
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "live33", str(REPO_ROOT / "Test Files" / "_live_cw033_capacity_turns.py"))
live = importlib.util.module_from_spec(spec)
sys.modules["live33"] = live
spec.loader.exec_module.__self__ if False else None
# Load module without running main()
import types
src = (REPO_ROOT / "Test Files" / "_live_cw033_capacity_turns.py").read_text(encoding="utf-8")
src = src.replace('if __name__ == "__main__":\n    sys.exit(main())', "")
exec(compile(src, "_live_cw033_capacity_turns.py", "exec"), live.__dict__)

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env", override=False)
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
from intake_submission import get_mysql_connection  # type: ignore

conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s",
            (live.SOURCE_DRAFT,))
msgs = json.loads((cur.fetchone() or {}).get("messages_json") or "[]")
cur.close()
M99 = str(msgs[99].get("content"))

cid, kid, _ = live.make_clone(conn, "cw33dbg", 99, live._STRIP_FROM_OTHER_DEBT)
try:
    status, reply = live.post_turn(cid, kid, M99)
    print("FULL REPLY:\n", reply)
    fin = live._fresh_read(conn, cid, "financials_json")
    print("\nother_monthly_debt_payments =", fin.get("other_monthly_debt_payments"))
    print("annual_interest_payment =", fin.get("annual_interest_payment"))
    caps = live.ops_caps(conn, cid)
    print("install =", caps.get("Landscaping/installation job"))
finally:
    live.cleanup(conn, cid)
conn.close()
