"""Nick's RULING 2026-08-15 on #343 (post-intake re-bases stated capacity):
CLOSED WONT-FIX - post-intake did exactly its job. Same registry door as
the triage closer (issue_registry.resolve_manually); reasoning in the note."""
from __future__ import annotations
import sys
from pathlib import Path
from dotenv import load_dotenv
REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
from client_intake_and_finmo import issue_registry  # noqa: E402
from intake_submission import get_mysql_connection  # noqa: E402
SIG = "verdict:plan_build:stated_capacity_silently_rebased_above_what_the_client_stated"
NOTE = ("NICK'S RULING 2026-08-15: CLOSED WONT-FIX - not a deal breaker; post-intake did exactly its job. "
        "PRINCIPLE: the workbook proves it - Kestrelbrook's stub (as-stated snapshot) runs EBITDA -83,876, a LOSS; "
        "carried forward literally (40 jobs/wk at 95% util, no funded growth) it would have FAILED post-intake. The "
        "executive/cascade infrastructure exists to turn an unsustainable-as-stated snapshot into a realistic, funded, "
        "fundable forecast. The re-expression is honest not fabricated (stub 519.84 cap x 0.95 = Q1 705.49 x 0.70 = "
        "identical volume, re-expressed at sustainable utilization with headroom); the growth is toward what the client "
        "explicitly asked for (crew side up ~30%, primary_growth_lever = add crew capacity) and it is FUNDED (payroll "
        "+35.5%); it is a uniform realistic-utilization policy across all four lines (~0.70), a deliberate forecast rule; "
        "Q1-Q20 is a future-dated forecast. Failing this on 'forecast exceeds literal as-stated capacity' would be a FALSE "
        "NEGATIVE - failing a fundable business on a technicality, as much a defect as a false pass. The divergence between "
        "the stated snapshot and the delivered forecast IS the product's value. PARKED as a FEATURE DECISION (Nick's, later): "
        "an optional plain-language narrative note disclosing the growth assumption. Recurrence re-opens (resolved is not terminal).")
conn = get_mysql_connection()
out = issue_registry.resolve_manually(conn, signature=SIG, note=NOTE)
print("closed", SIG, "->", out.get("status"), "/", out.get("resolution_basis"))
conn.close()
