"""Confirming Cowork run (Kestrelbrook fd3d1b02, 2026-08-15): close #344
WONT-FIX under Nick's triage law. Cowork itself filed it as cosmetic; the
prices reach the workbook correctly (48/105/850/650). #343 is NOT closed
here - it is a product decision for Nick (deal-breaker candidate).
Same door as the triage closer: issue_registry.resolve_manually."""
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
SIG = "experience:positioning:unit_prices_rendered_with_a_cadence_suffix_and_no_line_names"
NOTE = ("TRIAGE 2026-08-15 (deal-breaker law, confirming run Kestrelbrook): WONT-FIX - "
        "cosmetic positioning copy; unit prices are truthful and reach the workbook "
        "exactly (48/105/850/650); the cadence suffix on a unit price is awkward, not a "
        "wrong number or false claim. Recurrence re-opens (resolved is not terminal).")
conn = get_mysql_connection()
out = issue_registry.resolve_manually(conn, signature=SIG, note=NOTE)
print("closed", SIG, "->", out.get("status"), "/", out.get("resolution_basis"))
conn.close()
